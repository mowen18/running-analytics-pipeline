"""Strava activity ingestion: historical backfill and incremental sync.

Incremental runs fetch from (watermark − SYNC_OVERLAP_DAYS) so late
uploads and recent edits inside the overlap window are re-captured; the
upsert makes the re-fetch harmless. Because the Strava list endpoint
filters on activity *start date*, anything uploaded or edited more than
the overlap window after it occurred is only caught by a full
reconciliation (full=True).

Counts are logged; token values never are.
"""

import logging
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta

import psycopg
from psycopg.types.json import Jsonb

from running_pipeline import sync_state
from running_pipeline.config import Settings
from running_pipeline.strava_client import RateLimitStop, StravaClient

SYNC_KEY = "activities"

logger = logging.getLogger(__name__)

# xmax = 0 marks a freshly inserted row; anything else means an update.
# The WHERE clause turns identical re-fetches into no-ops (RETURNING
# yields no row), so unchanged rows are never rewritten and "skipped"
# is observable rather than inferred.
_UPSERT_SQL = """
    INSERT INTO raw_strava.activities
        (activity_id, start_date_utc, activity_type, payload, source_updated_at, fetched_at)
    VALUES (%(activity_id)s, %(start_date_utc)s, %(activity_type)s, %(payload)s,
            %(source_updated_at)s, %(fetched_at)s)
    ON CONFLICT (activity_id) DO UPDATE SET
        start_date_utc    = EXCLUDED.start_date_utc,
        activity_type     = EXCLUDED.activity_type,
        payload           = EXCLUDED.payload,
        source_updated_at = EXCLUDED.source_updated_at,
        fetched_at        = EXCLUDED.fetched_at
    WHERE activities.payload IS DISTINCT FROM EXCLUDED.payload
    RETURNING (xmax = 0) AS inserted
"""


@dataclass
class SyncReport:
    pages: int = 0
    received: int = 0
    inserted: int = 0
    updated: int = 0
    skipped: int = 0
    stopped_early: bool = False


def compute_window_start(
    sync_start_date: date,
    overlap_days: int,
    watermark: datetime | None,
    full: bool,
) -> datetime:
    """Open the fetch window per D5 (historical floor) and D6 (overlap)."""
    floor = datetime.combine(sync_start_date, time.min, tzinfo=UTC)
    if full or watermark is None:
        return floor
    return max(floor, watermark - timedelta(days=overlap_days))


def sync_activities(
    settings: Settings,
    client: StravaClient,
    conn: psycopg.Connection,
    *,
    full: bool = False,
) -> SyncReport:
    """Fetch and upsert activities; advance the watermark only on full success.

    A rate-limit stop keeps every committed page and leaves the watermark
    untouched, so the next run re-covers the same window idempotently.
    """
    run_started_at = datetime.now(UTC)
    watermark = None if full else sync_state.get_last_synced_at(conn, SYNC_KEY)
    window_start = compute_window_start(
        settings.sync_start_date, settings.sync_overlap_days, watermark, full
    )
    mode = "full" if full else "incremental"
    logger.info(
        "activity sync starting mode=%s window_start=%s watermark=%s",
        mode,
        window_start.isoformat(),
        watermark.isoformat() if watermark is not None else "none",
    )

    report = SyncReport()
    try:
        for page in client.iter_activity_pages(after=window_start):
            fetched_at = datetime.now(UTC)
            outcomes = Counter(_upsert_activity(conn, activity, fetched_at) for activity in page)
            conn.commit()  # page-level durability: a later failure keeps this work
            report.pages += 1
            report.received += len(page)
            report.inserted += outcomes["inserted"]
            report.updated += outcomes["updated"]
            report.skipped += outcomes["skipped"]
            logger.info(
                "activity sync page=%d received=%d inserted=%d updated=%d skipped=%d",
                report.pages,
                len(page),
                outcomes["inserted"],
                outcomes["updated"],
                outcomes["skipped"],
            )
    except RateLimitStop as stop:
        report.stopped_early = True
        logger.warning(
            "activity sync stopped early: %s | pages=%d received=%d inserted=%d "
            "updated=%d skipped=%d — committed pages kept, watermark not advanced",
            stop,
            report.pages,
            report.received,
            report.inserted,
            report.updated,
            report.skipped,
        )
        return report

    sync_state.set_last_synced_at(conn, SYNC_KEY, run_started_at)
    conn.commit()
    logger.info(
        "activity sync complete mode=%s pages=%d received=%d inserted=%d updated=%d "
        "skipped=%d watermark=%s",
        mode,
        report.pages,
        report.received,
        report.inserted,
        report.updated,
        report.skipped,
        run_started_at.isoformat(),
    )
    return report


def _upsert_activity(conn: psycopg.Connection, activity: dict, fetched_at: datetime) -> str:
    row = conn.execute(
        _UPSERT_SQL,
        {
            "activity_id": activity["id"],
            "start_date_utc": datetime.fromisoformat(activity["start_date"]),
            "activity_type": activity.get("sport_type"),
            "payload": Jsonb(activity),
            "source_updated_at": _optional_timestamp(activity.get("updated_at")),
            "fetched_at": fetched_at,
        },
    ).fetchone()
    if row is None:
        return "skipped"
    return "inserted" if row[0] else "updated"


def _optional_timestamp(value: str | None) -> datetime | None:
    return None if value is None else datetime.fromisoformat(value)
