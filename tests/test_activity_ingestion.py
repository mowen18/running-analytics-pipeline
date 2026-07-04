"""Ingestion engine tests.

Unit tests exercise window math, counts, logging, and watermark rules
with in-memory fakes. The @integration tests run the same engine against
the real local Postgres (fake client, real SQL) and skip visibly when
the database is down — see the integration_db fixture in conftest.
"""

import logging
from datetime import UTC, date, datetime, timedelta

import pytest

from running_pipeline import activity_ingestion, sync_state
from running_pipeline.activity_ingestion import (
    SYNC_KEY,
    SyncReport,
    compute_window_start,
    sync_activities,
)
from running_pipeline.config import Settings
from running_pipeline.strava_client import RateLimitApproaching

START_DATE = date(2024, 1, 1)
START_FLOOR = datetime(2024, 1, 1, tzinfo=UTC)


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


class FakeClient:
    """Yields canned pages regardless of `after`; optionally raises after them."""

    def __init__(self, pages, raise_after=None):
        self.pages = pages
        self.raise_after = raise_after
        self.requested_after = None

    def iter_activity_pages(self, after, per_page=200):
        self.requested_after = after
        yield from self.pages
        if self.raise_after is not None:
            raise self.raise_after


class FakeConn:
    def __init__(self):
        self.commits = 0

    def commit(self):
        self.commits += 1


def strava_activity(activity_id, start="2024-03-01T09:00:00Z", **extra):
    """Synthetic SummaryActivity; deliberately carries no coordinates."""
    return {
        "id": activity_id,
        "name": f"Test Run {activity_id}",
        "sport_type": "Run",
        "type": "Run",
        "start_date": start,
        "distance": 8046.7,
        "moving_time": 3000,
        "average_heartrate": 147.5,
        **extra,
    }


# ── Window math (D5 floor, D6 overlap) ────────────────────────────────


def test_first_run_window_starts_at_sync_start_date():
    assert compute_window_start(START_DATE, 14, watermark=None, full=False) == START_FLOOR


def test_incremental_window_subtracts_overlap():
    watermark = datetime(2026, 7, 1, 6, 30, tzinfo=UTC)
    window = compute_window_start(START_DATE, 14, watermark, full=False)
    assert window == watermark - timedelta(days=14)


def test_window_never_precedes_sync_start_date():
    watermark = datetime(2024, 1, 5, tzinfo=UTC)  # overlap would reach into 2023
    assert compute_window_start(START_DATE, 14, watermark, full=False) == START_FLOOR


def test_full_reconciliation_ignores_watermark():
    watermark = datetime(2026, 7, 1, tzinfo=UTC)
    assert compute_window_start(START_DATE, 14, watermark, full=True) == START_FLOOR


# ── Engine behavior (fakes for every DB seam) ─────────────────────────


@pytest.fixture
def engine_fakes(monkeypatch):
    """Replace the DB-touching seams; returns the recorder dict."""
    state = {"watermark": None, "set_calls": []}
    monkeypatch.setattr(
        activity_ingestion.sync_state,
        "get_last_synced_at",
        lambda conn, key: state["watermark"],
    )
    monkeypatch.setattr(
        activity_ingestion.sync_state,
        "set_last_synced_at",
        lambda conn, key, value: state["set_calls"].append((key, value)),
    )
    monkeypatch.setattr(
        activity_ingestion,
        "_upsert_activity",
        lambda conn, activity, fetched_at: activity["_outcome"],
    )
    return state


def test_report_counts_across_pages(engine_fakes, tmp_path):
    pages = [
        [{"_outcome": "inserted"}, {"_outcome": "inserted"}, {"_outcome": "updated"}],
        [{"_outcome": "skipped"}, {"_outcome": "inserted"}],
    ]
    conn = FakeConn()

    report = sync_activities(make_settings(tmp_path), FakeClient(pages), conn)

    assert report == SyncReport(pages=2, received=5, inserted=3, updated=1, skipped=1)
    assert conn.commits == 3  # one per page + the watermark write


def test_incremental_requests_only_overlap_and_newer(engine_fakes, tmp_path):
    engine_fakes["watermark"] = datetime(2026, 7, 1, tzinfo=UTC)
    client = FakeClient([])

    sync_activities(make_settings(tmp_path), client, FakeConn())

    assert client.requested_after == datetime(2026, 6, 17, tzinfo=UTC)


def test_full_requests_from_sync_start_date(engine_fakes, tmp_path):
    engine_fakes["watermark"] = datetime(2026, 7, 1, tzinfo=UTC)
    client = FakeClient([])

    sync_activities(make_settings(tmp_path), client, FakeConn(), full=True)

    assert client.requested_after == START_FLOOR


def test_watermark_advances_to_run_start_on_success(engine_fakes, tmp_path):
    before = datetime.now(UTC)

    sync_activities(make_settings(tmp_path), FakeClient([[{"_outcome": "inserted"}]]), FakeConn())

    ((key, value),) = engine_fakes["set_calls"]
    assert key == SYNC_KEY
    assert before <= value <= datetime.now(UTC)


def test_empty_sync_still_advances_watermark(engine_fakes, tmp_path):
    report = sync_activities(make_settings(tmp_path), FakeClient([]), FakeConn())

    assert report == SyncReport()
    assert len(engine_fakes["set_calls"]) == 1


def test_rate_limit_stop_keeps_counts_and_watermark(engine_fakes, tmp_path, caplog):
    client = FakeClient(
        [[{"_outcome": "inserted"}, {"_outcome": "inserted"}]],
        raise_after=RateLimitApproaching("read 15-min 95/100, daily 300/1000"),
    )
    conn = FakeConn()

    with caplog.at_level(logging.INFO):
        report = sync_activities(make_settings(tmp_path), client, conn)

    assert report == SyncReport(pages=1, received=2, inserted=2, stopped_early=True)
    assert engine_fakes["set_calls"] == []  # watermark untouched
    assert conn.commits == 1  # the completed page stayed committed
    assert "stopped early" in caplog.text
    assert "watermark not advanced" in caplog.text


def test_logs_carry_counts_and_no_tokens(engine_fakes, tmp_path, caplog):
    pages = [[{"_outcome": "inserted"}, {"_outcome": "updated"}]]

    with caplog.at_level(logging.INFO):
        sync_activities(make_settings(tmp_path), FakeClient(pages), FakeConn())

    assert "received=2 inserted=1 updated=1 skipped=0" in caplog.text
    assert "env-bootstrap-token" not in caplog.text
    assert "test-client-secret" not in caplog.text


# ── Real upsert and sync_state against local Postgres ─────────────────


@pytest.fixture
def db(integration_db):
    integration_db.execute("TRUNCATE raw_strava.activities, raw_strava.sync_state")
    integration_db.commit()
    return integration_db


@pytest.mark.integration
def test_rerun_with_identical_payloads_creates_no_duplicates(db, tmp_path):
    settings = make_settings(tmp_path)
    pages = [[strava_activity(1), strava_activity(2)], [strava_activity(3)]]

    first = sync_activities(settings, FakeClient(pages), db)
    second = sync_activities(settings, FakeClient(pages), db)

    assert (first.inserted, first.updated, first.skipped) == (3, 0, 0)
    assert (second.inserted, second.updated, second.skipped) == (0, 0, 3)
    assert db.execute("SELECT count(*) FROM raw_strava.activities").fetchone()[0] == 3


@pytest.mark.integration
def test_edited_activity_is_updated_in_place(db, tmp_path):
    settings = make_settings(tmp_path)
    sync_activities(settings, FakeClient([[strava_activity(1)]]), db)

    edited = strava_activity(1, name="Renamed Run")
    report = sync_activities(settings, FakeClient([[edited]]), db)

    assert (report.inserted, report.updated, report.skipped) == (0, 1, 0)
    row = db.execute(
        "SELECT payload->>'name', count(*) OVER () FROM raw_strava.activities WHERE activity_id = 1"
    ).fetchone()
    assert row == ("Renamed Run", 1)


@pytest.mark.integration
def test_typed_columns_promoted_from_payload(db, tmp_path):
    activity = strava_activity(7, start="2024-05-04T06:15:00Z", sport_type="TrailRun")

    sync_activities(make_settings(tmp_path), FakeClient([[activity]]), db)

    row = db.execute(
        """
        SELECT start_date_utc, activity_type, source_updated_at, fetched_at
        FROM raw_strava.activities WHERE activity_id = 7
        """
    ).fetchone()
    assert row[0] == datetime(2024, 5, 4, 6, 15, tzinfo=UTC)
    assert row[1] == "TrailRun"
    assert row[2] is None  # list endpoint sends no updated_at: missing, not zero
    assert row[3] is not None


@pytest.mark.integration
def test_watermark_round_trip(db, tmp_path):
    assert sync_state.get_last_synced_at(db, SYNC_KEY) is None

    before = datetime.now(UTC)
    sync_activities(make_settings(tmp_path), FakeClient([[strava_activity(1)]]), db)

    stored = sync_state.get_last_synced_at(db, SYNC_KEY)
    assert stored is not None
    assert before <= stored <= datetime.now(UTC)

    # Overwrite path of the sync_state upsert.
    sync_state.set_last_synced_at(db, SYNC_KEY, datetime(2026, 1, 1, tzinfo=UTC))
    db.commit()
    assert sync_state.get_last_synced_at(db, SYNC_KEY) == datetime(2026, 1, 1, tzinfo=UTC)
