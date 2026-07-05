"""Coordinate resolution tests: polyline decoding, detail fetch, and the
backfill engine (fake client, real SQL against the scratch database).

All coordinates are the public Google polyline documentation example or
obviously fake values — never real cells.
"""

import json
import time
from datetime import datetime

import psycopg
import pytest
import responses

from running_pipeline.config import Settings
from running_pipeline.polyline import decode_polyline, first_point
from running_pipeline.strava_client import API_BASE, StravaClient, TokenSet, TokenStore

# The worked example from Google's encoded-polyline documentation.
GOOGLE_EXAMPLE = "_p~iF~ps|U_ulLnnqC_mqNvxq`@"
GOOGLE_POINTS = [(38.5, -120.2), (40.7, -120.95), (43.252, -126.453)]


def make_settings(tmp_path, **overrides) -> Settings:
    defaults = {
        "strava_client_id": "12345",
        "strava_client_secret": "test-client-secret",
        "strava_refresh_token": "env-bootstrap-token",
        "postgres_password": "test-db-password",
        "token_file": tmp_path / "strava_tokens.json",
    }
    defaults.update(overrides)
    # _env_file=None keeps tests hermetic: never read the developer's .env.
    return Settings(_env_file=None, **defaults)


def make_client(tmp_path) -> StravaClient:
    settings = make_settings(tmp_path)
    TokenStore(settings.token_file).save(
        TokenSet(
            access_token="stored-access-token",
            refresh_token="stored-refresh-token",
            expires_at=int(time.time()) + 3600,
        )
    )
    return StravaClient(settings, sleep=lambda s: None)


# ── Polyline decoding ─────────────────────────────────────────────────


def encode_polyline(points) -> str:
    """Reference encoder (Google's published algorithm) for round-trips."""
    out = []
    prev_lat = prev_lon = 0
    for lat, lon in points:
        for value, prev in ((round(lat * 1e5), prev_lat), (round(lon * 1e5), prev_lon)):
            delta = value - prev
            zigzag = ~(delta << 1) if delta < 0 else delta << 1
            while zigzag >= 0x20:
                out.append(chr((0x20 | (zigzag & 0x1F)) + 63))
                zigzag >>= 5
            out.append(chr(zigzag + 63))
        prev_lat, prev_lon = round(lat * 1e5), round(lon * 1e5)
    return "".join(out)


def assert_points_equal(actual, expected):
    assert len(actual) == len(expected)
    for (a_lat, a_lon), (e_lat, e_lon) in zip(actual, expected, strict=True):
        assert a_lat == pytest.approx(e_lat, abs=1e-5)
        assert a_lon == pytest.approx(e_lon, abs=1e-5)


def test_decodes_the_documented_google_example():
    assert_points_equal(decode_polyline(GOOGLE_EXAMPLE), GOOGLE_POINTS)


def test_first_point_returns_route_start():
    lat, lon = first_point(GOOGLE_EXAMPLE)
    assert (lat, lon) == pytest.approx((38.5, -120.2))


def test_first_point_handles_missing_polylines():
    assert first_point(None) is None
    assert first_point("") is None


def test_round_trips_negative_and_fractional_coordinates():
    # Negative deltas, sign flips, and near-zero values exercise the
    # zigzag handling; the encoder is the published reference algorithm.
    points = [(-1.0, -0.00001), (-1.5, 0.00004), (42.12345, -87.65432)]
    assert_points_equal(decode_polyline(encode_polyline(points)), points)
    assert encode_polyline(GOOGLE_POINTS) == GOOGLE_EXAMPLE  # encoder sanity


# ── Detail fetch ──────────────────────────────────────────────────────


@responses.activate
def test_detail_fetch_returns_payload(tmp_path):
    responses.get(
        f"{API_BASE}/activities/42",
        json={"id": 42, "map": {"polyline": GOOGLE_EXAMPLE}},
    )

    detail = make_client(tmp_path).get_activity_detail(42)

    assert detail["map"]["polyline"] == GOOGLE_EXAMPLE


@responses.activate
def test_detail_404_returns_none(tmp_path):
    responses.get(f"{API_BASE}/activities/42", status=404, json={"message": "Not Found"})

    assert make_client(tmp_path).get_activity_detail(42) is None


# ── Backfill engine (fake client, real SQL) ───────────────────────────


class FakeDetailClient:
    """Canned detail outcomes: dict payload, None (404), or an exception."""

    def __init__(self, outcomes):
        self.outcomes = outcomes
        self.calls = []
        self._approaching = []

    def get_activity_detail(self, activity_id):
        self.calls.append(activity_id)
        outcome = self.outcomes[activity_id]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def rate_limit_approaching(self):
        return self._approaching


def insert_run(db, activity_id, *, start_latlng=None, trainer=False, sport_type="Run"):
    payload = {
        "id": activity_id,
        "sport_type": sport_type,
        "start_date": f"2026-06-{10 + activity_id:02d}T09:00:00Z",
        "start_latlng": list(start_latlng) if start_latlng else [],
        "trainer": trainer,
    }
    db.execute(
        """
        INSERT INTO raw_strava.activities
            (activity_id, start_date_utc, activity_type, payload, fetched_at)
        VALUES (%s, %s, %s, %s, now())
        """,
        (
            activity_id,
            datetime.fromisoformat(payload["start_date"]),
            sport_type,
            json.dumps(payload),
        ),
    )


def coordinate_rows(db):
    return {
        row[0]: (row[1], row[2], row[3])
        for row in db.execute(
            "SELECT activity_id, latitude, longitude, source FROM raw_strava.activity_coordinates"
        ).fetchall()
    }


def detail_with_polyline(encoded=GOOGLE_EXAMPLE):
    return {"map": {"polyline": encoded, "summary_polyline": ""}}


@pytest.mark.integration
def test_backfill_resolves_by_provenance(db, tmp_path):
    from running_pipeline.coordinate_ingestion import backfill_coordinates
    from running_pipeline.strava_client import StravaApiError

    insert_run(db, 1, start_latlng=(12.34, -56.78))  # free harvest
    insert_run(db, 2)  # needs polyline decode
    insert_run(db, 3)  # detail has no route at all
    insert_run(db, 4, trainer=True)  # treadmill: skipped entirely
    insert_run(db, 5)  # transient failure: retried next run
    insert_run(db, 6, sport_type="Walk")  # not a run: ignored
    db.commit()
    client = FakeDetailClient(
        {
            2: detail_with_polyline(),
            3: {"map": {"polyline": None, "summary_polyline": ""}},
            5: StravaApiError("HTTP 503 after retries"),
        }
    )

    report = backfill_coordinates(make_settings(tmp_path), client, db)

    assert (report.harvested, report.decoded, report.unavailable, report.failed) == (1, 1, 1, 1)
    rows = coordinate_rows(db)
    assert rows[1][2] == "start_latlng"
    assert float(rows[2][0]) == pytest.approx(38.5)  # Google example start
    assert float(rows[2][1]) == pytest.approx(-120.2)
    assert rows[2][2] == "map_polyline"
    assert rows[3] == (None, None, "unavailable")
    assert 4 not in rows and 6 not in rows  # never candidates
    assert 5 not in rows  # failed: absent row means retry next run

    # Second run: only the failed activity is retried, and it heals.
    healing = FakeDetailClient({5: detail_with_polyline()})
    second = backfill_coordinates(make_settings(tmp_path), healing, db)

    assert healing.calls == [5]
    assert (second.harvested, second.decoded, second.failed) == (0, 1, 0)
    assert coordinate_rows(db)[5][2] == "map_polyline"


@pytest.mark.integration
def test_backfill_respects_cap_and_summary_polyline_fallback(db, tmp_path):
    from running_pipeline.coordinate_ingestion import backfill_coordinates

    insert_run(db, 1)
    insert_run(db, 2)
    insert_run(db, 3)
    db.commit()
    # Detail with only a summary polyline still resolves.
    client = FakeDetailClient(
        {
            1: {"map": {"polyline": None, "summary_polyline": GOOGLE_EXAMPLE}},
            2: detail_with_polyline(),
        }
    )
    settings = make_settings(tmp_path, coordinate_max_activities_per_run=2)

    report = backfill_coordinates(settings, client, db)

    assert client.calls == [1, 2]  # the cap stopped before activity 3
    assert report.candidates == 2
    assert coordinate_rows(db)[1][2] == "map_polyline"


# ── DDL ───────────────────────────────────────────────────────────────


@pytest.fixture
def db(integration_db):
    integration_db.execute("TRUNCATE raw_strava.activities, raw_strava.activity_coordinates")
    integration_db.commit()
    return integration_db


@pytest.mark.integration
def test_unavailable_rows_must_have_null_coordinates(db):
    db.execute(
        "INSERT INTO raw_strava.activity_coordinates VALUES (1, NULL, NULL, 'unavailable', now())"
    )
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute(
            "INSERT INTO raw_strava.activity_coordinates "
            "VALUES (2, 12.34, -56.78, 'unavailable', now())"
        )
    db.rollback()


@pytest.mark.integration
def test_resolved_rows_must_have_both_coordinates(db):
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute(
            "INSERT INTO raw_strava.activity_coordinates "
            "VALUES (1, 12.34, NULL, 'map_polyline', now())"
        )
    db.rollback()
