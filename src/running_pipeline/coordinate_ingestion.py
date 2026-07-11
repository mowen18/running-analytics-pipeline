"""Run-start coordinate resolution (raw_strava.activity_coordinates).

The map-privacy workaround: when Strava's "hide entire map" setting
strips start_latlng from API payloads, the activity DETAIL endpoint
still carries the encoded route polyline, whose first point is the run
start. Resolution order per running activity:

1. payload start_latlng, when present  -> source 'start_latlng' (free)
2. detail map.polyline first point     -> source 'map_polyline' (1 call)
3. no route data at all                -> source 'unavailable' (terminal)

Absent row = not yet attempted; a failed detail fetch writes nothing so
the next run retries it. Same resumability/rate-limit contracts as the
stream backfill: per-row commits, a per-invocation cap, and clean stops
between fetches. Exact coordinates are stored, never logged.
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, time

import psycopg

from running_pipeline import polyline
from running_pipeline.config import Settings
from running_pipeline.strava_client import RateLimitStop, StravaApiError, StravaClient

logger = logging.getLogger(__name__)

RUNNING_SPORT_TYPES = ("Run", "TrailRun", "VirtualRun")

# Resolution 1: coordinates already in the stored payload — pure SQL,
# no API calls, idempotent via the anti-join.
_HARVEST_SQL = """
    INSERT INTO raw_strava.activity_coordinates
        (activity_id, latitude, longitude, source, fetched_at)
    SELECT a.activity_id,
           (a.payload->'start_latlng'->>0)::numeric,
           (a.payload->'start_latlng'->>1)::numeric,
           'start_latlng',
           now()
    FROM raw_strava.activities a
    LEFT JOIN raw_strava.activity_coordinates c USING (activity_id)
    WHERE c.activity_id IS NULL
      AND a.activity_type = ANY(%(running_types)s)
      AND a.start_date_utc >= %(floor)s
      AND jsonb_array_length(coalesce(a.payload->'start_latlng', '[]'::jsonb)) = 2
"""

# Resolution 2 candidates: outdoor-flagged runs with no payload
# coordinates and no resolution row yet. Trainer runs are skipped
# entirely (a treadmill has no route to decode).
_CANDIDATES_SQL = """
    SELECT a.activity_id
    FROM raw_strava.activities a
    LEFT JOIN raw_strava.activity_coordinates c USING (activity_id)
    WHERE c.activity_id IS NULL
      AND a.activity_type = ANY(%(running_types)s)
      AND a.start_date_utc >= %(floor)s
      AND NOT coalesce((a.payload->>'trainer')::boolean, false)
      AND jsonb_array_length(coalesce(a.payload->'start_latlng', '[]'::jsonb)) != 2
    ORDER BY a.start_date_utc, a.activity_id
    LIMIT %(cap)s
"""

_INSERT_SQL = """
    INSERT INTO raw_strava.activity_coordinates
        (activity_id, latitude, longitude, source, fetched_at)
    VALUES (%(activity_id)s, %(latitude)s, %(longitude)s, %(source)s, now())
    ON CONFLICT (activity_id) DO UPDATE SET
        latitude   = EXCLUDED.latitude,
        longitude  = EXCLUDED.longitude,
        source     = EXCLUDED.source,
        fetched_at = EXCLUDED.fetched_at
"""


@dataclass
class CoordinateBackfillReport:
    harvested: int = 0  # resolved from payload start_latlng, no API calls
    candidates: int = 0  # needed a detail fetch this run
    decoded: int = 0
    unavailable: int = 0
    failed: int = 0
    stopped_early: bool = False


def backfill_coordinates(
    settings: Settings, client: StravaClient, conn: psycopg.Connection
) -> CoordinateBackfillReport:
    floor = datetime.combine(settings.sync_start_date, time.min, tzinfo=UTC)
    report = CoordinateBackfillReport()

    report.harvested = conn.execute(
        _HARVEST_SQL, {"running_types": list(RUNNING_SPORT_TYPES), "floor": floor}
    ).rowcount
    conn.commit()

    candidate_ids = [
        row[0]
        for row in conn.execute(
            _CANDIDATES_SQL,
            {
                "running_types": list(RUNNING_SPORT_TYPES),
                "floor": floor,
                "cap": settings.coordinate_max_activities_per_run,
            },
        ).fetchall()
    ]
    report.candidates = len(candidate_ids)
    logger.info(
        "coordinate backfill starting harvested=%d polyline_candidates=%d (cap %d)",
        report.harvested,
        report.candidates,
        settings.coordinate_max_activities_per_run,
    )

    for activity_id in candidate_ids:
        try:
            detail = client.get_activity_detail(activity_id)
        except RateLimitStop as stop:
            report.stopped_early = True
            logger.warning(
                "coordinate backfill stopped early at the rate limit before activity %d: %s "
                "— committed rows kept; re-run to resume",
                activity_id,
                stop,
            )
            break
        except StravaApiError as exc:
            report.failed += 1
            logger.warning(
                "coordinate detail fetch failed activity=%d (no row written, retried next run): %s",
                activity_id,
                exc,
            )
            continue

        point = None
        if detail is not None:
            map_data = detail.get("map") or {}
            point = polyline.first_point(
                map_data.get("polyline") or map_data.get("summary_polyline")
            )
        if point is None:
            _record(conn, activity_id, None, None, "unavailable")
            report.unavailable += 1
            outcome = "unavailable"
        else:
            _record(conn, activity_id, point[0], point[1], "map_polyline")
            report.decoded += 1
            outcome = "map_polyline"
        conn.commit()  # per-activity durability
        # Coordinates never appear in logs — outcome and id only.
        logger.info("coordinate resolved activity=%d source=%s", activity_id, outcome)

        triggered = client.rate_limit_approaching()
        if triggered:
            report.stopped_early = True
            logger.warning(
                "coordinate backfill stopping before the Strava rate limit: %s "
                "— committed rows kept; re-run to resume",
                "; ".join(status.describe() for status in triggered),
            )
            break

    logger.info(
        "coordinate backfill %s harvested=%d decoded=%d unavailable=%d failed=%d",
        "stopped early" if report.stopped_early else "complete",
        report.harvested,
        report.decoded,
        report.unavailable,
        report.failed,
    )
    return report


def _record(
    conn: psycopg.Connection,
    activity_id: int,
    latitude: float | None,
    longitude: float | None,
    source: str,
) -> None:
    conn.execute(
        _INSERT_SQL,
        {
            "activity_id": activity_id,
            "latitude": latitude,
            "longitude": longitude,
            "source": source,
        },
    )
