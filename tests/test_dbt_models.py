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


def outdoor_run(db, activity_id, *, day, hr, cell="12.34_-56.78", temp_c=15.0, **kwargs):
    """A qualifying-shaped run plus a matching observation at its cell.

    Defaults give speed 200 m/min (10 km in 50 min), so efficiency is
    200 / hr — hand-checkable. temp_c=None skips the weather row so the
    run lands in the explicit no_weather pseudo-band.
    """
    lat, lon = (float(part) for part in cell.split("_"))
    insert_activity(
        db,
        activity_id,
        start=f"{day}T09:47:23Z",
        start_local=f"{day}T04:47:23Z",
        start_latlng=(lat, lon),
        average_heartrate=hr,
        **kwargs,
    )
    if temp_c is not None:
        insert_weather(db, hour=f"{day}T09:00:00+00:00", temperature=temp_c, location=cell)


@pytest.mark.integration
def test_efficiency_marts_compute_metrics_exclusions_and_bands(db):
    # ── Week of Mon 2026-06-01: two qualifying runs (sufficient per D12).
    # temp_c values are chosen so temperature_f lands exactly on the D14
    # band edges after staging's 1-dp rounding: 9.94°C -> 49.9°F (cold),
    # 10.0°C -> 50.0°F (mild).
    outdoor_run(db, 1, day="2026-06-02", hr=140.0, cell="10.00_10.00", temp_c=9.94)
    outdoor_run(db, 2, day="2026-06-04", hr=150.0, cell="11.00_11.00", temp_c=10.0)
    # ── Week of Mon 2026-06-08: one qualifying run without weather
    # (insufficient), plus one run per exclusion rule.
    outdoor_run(db, 3, day="2026-06-09", hr=145.0, temp_c=None)
    outdoor_run(db, 4, day="2026-06-10", hr=150.0, workout_type=1)  # race
    outdoor_run(db, 5, day="2026-06-11", hr=None)  # no HR
    outdoor_run(db, 6, day="2026-06-12", hr=160.0)  # above easy max
    outdoor_run(db, 7, day="2026-06-13", hr=140.0, moving_time=1200, elapsed_time=1300)
    # ── Week of Mon 2026-06-15: the 70°F edge — 21.11°C -> 70.0°F stays
    # mild per D14's "50-70"; 21.17°C -> 70.1°F is warm.
    outdoor_run(db, 8, day="2026-06-16", hr=145.0, cell="12.00_12.00", temp_c=21.11)
    outdoor_run(db, 9, day="2026-06-17", hr=145.0, cell="13.00_13.00", temp_c=21.17)
    db.commit()

    result = run_dbt("build")
    assert result.returncode == 0, f"dbt build failed:\n{result.stdout}"

    # Exclusion reasons: first failing D9 rule, never a silent filter.
    reasons = dict(
        db.execute(
            "SELECT activity_id, exclusion_reason FROM intermediate.int_run_efficiency ORDER BY 1"
        ).fetchall()
    )
    assert reasons == {
        1: None,
        2: None,
        3: None,
        4: "tagged as race",
        5: "no heart rate data",
        6: "average HR above easy maximum (152 bpm)",
        7: "moving time under 30 minutes",
        8: None,
        9: None,
    }

    # Efficiency traces to documented fields: 200 m/min at 140 bpm.
    (efficiency,) = db.execute(
        "SELECT aerobic_efficiency_m_per_heartbeat FROM intermediate.int_run_efficiency "
        "WHERE activity_id = 1"
    ).fetchone()
    assert float(efficiency) == pytest.approx(200.0 / 140.0, abs=0.0001)

    # Weekly mart: D12 sufficiency and NULL-not-zero efficiency.
    weeks = db.execute(
        """
        SELECT week_start_date::text, qualifying_run_count, is_sufficient,
               median_efficiency_m_per_beat
        FROM analytics.mart_weekly_training ORDER BY week_start_date
        """
    ).fetchall()
    assert [(w[0], w[1], w[2]) for w in weeks] == [
        ("2026-06-01", 2, True),
        ("2026-06-08", 1, False),  # excluded runs don't count toward D12
        ("2026-06-15", 2, True),
    ]
    # Week 1 median interpolates between 200/150 and 200/140.
    assert float(weeks[0][3]) == pytest.approx((200.0 / 150.0 + 200.0 / 140.0) / 2, abs=0.0001)

    # Trend mart: the 28-day window ending Sun 2026-06-21 spans all five
    # qualifying runs; the week's own band comes from its avg temperature.
    (rolling_count, rolling_median, band) = db.execute(
        """
        SELECT rolling_28d_qualifying_run_count, rolling_28d_median_efficiency,
               temperature_band_key
        FROM analytics.mart_efficiency_trend WHERE week_start_date = '2026-06-15'
        """
    ).fetchone()
    assert rolling_count == 5
    assert float(rolling_median) == pytest.approx(200.0 / 145.0, abs=0.0001)
    assert band == "warm"  # avg(70.0, 70.1) = 70.05 -> rounds into warm

    # Band mart: every band present, boundaries exact, nothing dropped.
    bands = {
        row[0]: (row[1], row[2])
        for row in db.execute(
            """
            SELECT band_key, qualifying_run_count, median_efficiency_m_per_beat
            FROM analytics.mart_efficiency_by_temp_band
            """
        ).fetchall()
    }
    assert bands["cold"][0] == 1  # 49.9°F
    assert bands["mild"][0] == 2  # 50.0°F and 70.0°F — both edges inclusive
    assert bands["warm"][0] == 1  # 70.1°F
    assert bands["no_weather"][0] == 1  # explicit, not silently dropped
    assert sum(count for count, _ in bands.values()) == 5  # conservation


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
