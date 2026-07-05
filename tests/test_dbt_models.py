"""dbt model behavior against the scratch database (@integration).

The real warehouse currently has no outdoor or HR-carrying runs, so the
weather-matching and eligibility logic in the dbt models can only be
exercised with synthetic fixtures. These tests seed the scratch DB
(conftest's running_analytics_test), run the real dbt project against it
in a subprocess, and assert model outputs; the last test proves the dbt
test suite FAILS when known-invalid fixtures are introduced — Phase 3
acceptance criterion 6.

All coordinates are deliberately fake.
"""

import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest

from running_pipeline.config import Settings

REPO_ROOT = Path(__file__).resolve().parent.parent
DBT_DIR = REPO_ROOT / "dbt"
DBT_BIN = Path(sys.executable).parent / "dbt"
TEST_DB = "running_analytics_test"  # the conftest scratch database


@pytest.fixture
def db(integration_db):
    integration_db.execute("TRUNCATE raw_strava.activities, raw_weather.hourly")
    integration_db.commit()
    return integration_db


def run_dbt(*args: str) -> subprocess.CompletedProcess:
    """Run dbt against the scratch DB by overriding the profile env vars."""
    if not (DBT_DIR / "profiles.yml").exists():
        shutil.copy(DBT_DIR / "profiles.yml.example", DBT_DIR / "profiles.yml")
    settings = Settings()  # integration tests intentionally read .env
    env = {
        **os.environ,
        "POSTGRES_HOST": settings.postgres_host,
        "POSTGRES_PORT": str(settings.postgres_port),
        "POSTGRES_USER": settings.postgres_user,
        "POSTGRES_PASSWORD": settings.postgres_password.get_secret_value(),
        "POSTGRES_DB": TEST_DB,
    }
    return subprocess.run(
        [str(DBT_BIN), *args, "--profiles-dir", "."],
        cwd=DBT_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )


def insert_activity(
    conn,
    activity_id,
    *,
    sport_type="Run",
    start="2026-06-15T09:47:23Z",
    start_local="2026-06-15T04:47:23Z",
    start_latlng=(12.34, -56.78),
    trainer=False,
    distance=10000.0,
    moving_time=3000,
    elapsed_time=3100,
    average_heartrate=None,
    workout_type=None,
):
    payload = {
        "id": activity_id,
        "name": f"Fixture {activity_id}",
        "sport_type": sport_type,
        "start_date": start,
        "start_date_local": start_local,
        "timezone": "(GMT-06:00) America/Chicago",
        "start_latlng": list(start_latlng) if start_latlng else [],
        "trainer": trainer,
        "distance": distance,
        "moving_time": moving_time,
        "elapsed_time": elapsed_time,
        "total_elevation_gain": 42.0,
        "average_speed": distance / moving_time if moving_time else 0,
        "has_heartrate": average_heartrate is not None,
        "average_heartrate": average_heartrate,
        "workout_type": workout_type,
    }
    conn.execute(
        """
        INSERT INTO raw_strava.activities
            (activity_id, start_date_utc, activity_type, payload, fetched_at)
        VALUES (%s, %s, %s, %s, now())
        """,
        (activity_id, datetime.fromisoformat(start), sport_type, json.dumps(payload)),
    )


def insert_weather(conn, *, hour, temperature, location="12.34_-56.78"):
    lat, lon = (Decimal(part) for part in location.split("_"))
    conn.execute(
        """
        INSERT INTO raw_weather.hourly
            (location_key, latitude, longitude, weather_timestamp, temperature_c,
             relative_humidity_pct, payload, fetched_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, now())
        """,
        (
            location,
            lat,
            lon,
            datetime.fromisoformat(hour),
            temperature,
            None if temperature is None else 55,
            json.dumps({"time": hour}),
        ),
    )


@pytest.mark.integration
def test_dbt_build_matches_weather_and_flags_eligibility(db):
    # Outdoor run at 09:47 UTC with HR — the case real data cannot cover.
    insert_activity(db, 1, average_heartrate=145.0)
    # Treadmill run: stays in the grain, permanently unmatched, no HR.
    insert_activity(db, 2, trainer=True, start_latlng=None)
    # Walk: must not reach fct_runs at all.
    insert_activity(db, 3, sport_type="Walk", trainer=True, start_latlng=None)
    # 09:00 carries data; 10:00 is an explicit "archive had no data" row.
    # 10:00 is nearer to 09:47, but a missing-marker must never win the
    # match, so the model has to pick 09:00 (47 minutes away).
    insert_weather(db, hour="2026-06-15T09:00:00+00:00", temperature=20.0)
    insert_weather(db, hour="2026-06-15T10:00:00+00:00", temperature=None)
    db.commit()

    result = run_dbt("build")

    assert result.returncode == 0, f"dbt build failed:\n{result.stdout}"

    rows = db.execute(
        """
        SELECT activity_id, weather_available, temperature_c, weather_match_minutes,
               easy_run_eligible, long_run_eligible, pace_min_per_mi
        FROM analytics.fct_runs ORDER BY activity_id
        """
    ).fetchall()
    assert len(rows) == 2  # the Walk is filtered out

    outdoor, treadmill = rows
    assert outdoor[1] is True  # matched despite the nearer all-NULL row
    assert outdoor[2] == Decimal("20.0")  # the 09:00 observation, not NULL
    assert outdoor[3] == 47
    # 50 min moving, HR 145 <= 152, pace ~8 min/mi, untagged: easy + long.
    assert (outdoor[4], outdoor[5]) == (True, True)
    assert outdoor[6] == Decimal("8.05")

    assert treadmill[1] is False  # no coordinates: explicit, not an error
    assert treadmill[2] is None  # missing weather stays NULL, never zero
    assert (treadmill[4], treadmill[5]) == (False, True)  # no HR; 50 min


@pytest.mark.integration
def test_dbt_tests_fail_on_known_invalid_fixtures(db):
    # Physically impossible: moving time exceeds elapsed time.
    insert_activity(db, 1, moving_time=4000, elapsed_time=3000)
    # Out-of-range humidity on an otherwise valid observation.
    insert_weather(db, hour="2026-06-15T09:00:00+00:00", temperature=20.0)
    db.execute("UPDATE raw_weather.hourly SET relative_humidity_pct = 150")
    db.commit()

    result = run_dbt("build")

    assert result.returncode != 0, "dbt build should fail on invalid fixtures"
    assert "assert_moving_time_not_longer_than_elapsed" in result.stdout
    assert "accepted_range_stg_weather__hourly_relative_humidity_pct" in result.stdout
