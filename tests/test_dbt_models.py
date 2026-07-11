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
    integration_db.execute(
        "TRUNCATE raw_strava.activities, raw_strava.streams, "
        "raw_strava.activity_coordinates, raw_weather.hourly"
    )
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
    # Map-privacy case: payload carries no coordinates, but the resolved
    # activity_coordinates row (decoded polyline) must drive the match.
    insert_activity(db, 4, start="2026-06-15T11:47:23Z", start_latlng=None, average_heartrate=None)
    db.execute(
        "INSERT INTO raw_strava.activity_coordinates VALUES "
        "(4, 22.446, 33.786, 'map_polyline', now())"
    )
    insert_weather(db, hour="2026-06-15T11:00:00+00:00", temperature=25.0, location="22.45_33.79")
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
               long_run_eligible, pace_min_per_mi
        FROM analytics.fct_runs ORDER BY activity_id
        """
    ).fetchall()
    assert len(rows) == 3  # the Walk is filtered out

    outdoor, treadmill, resolved = rows
    assert outdoor[1] is True  # matched despite the nearer all-NULL row
    assert outdoor[2] == Decimal("20.0")  # the 09:00 observation, not NULL
    assert outdoor[3] == 47
    assert outdoor[4] is True  # 50 min moving >= the 45-minute long-run bar
    assert outdoor[5] == Decimal("8.05")

    assert treadmill[1] is False  # no coordinates: explicit, not an error
    assert treadmill[2] is None  # missing weather stays NULL, never zero
    assert treadmill[4] is True  # 50 min moving

    # The map-privacy fallback: coordinates came from the resolved
    # activity_coordinates row, so weather still matches (11:00 obs at
    # the run's D7 cell, 47 minutes from the 11:47 start).
    assert resolved[1] is True
    assert resolved[2] == Decimal("25.0")
    assert resolved[3] == 47


def outdoor_run(db, activity_id, *, day, hr, cell="12.34_-56.78", temp_c=15.0, **kwargs):
    """A valid-shaped run plus a matching observation at its cell.

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
    # ── Week of Mon 2026-06-01: two valid runs (sufficient per D12).
    # temp_c values are chosen so temperature_f lands exactly on the D14
    # band edges after staging's 1-dp rounding: 9.94°C -> 49.9°F (cold),
    # 10.0°C -> 50.0°F (mild).
    outdoor_run(db, 1, day="2026-06-02", hr=140.0, cell="10.00_10.00", temp_c=9.94)
    outdoor_run(db, 2, day="2026-06-04", hr=150.0, cell="11.00_11.00", temp_c=10.0)
    # ── Week of Mon 2026-06-08: a valid run without weather, two runs
    # the old D9 ladder excluded (race tag, hard effort) that are VALID
    # under v1.1, and one run per remaining data-validity rule.
    outdoor_run(db, 3, day="2026-06-09", hr=145.0, temp_c=None)
    outdoor_run(db, 4, day="2026-06-10", hr=150.0, workout_type=1)  # race: valid now
    outdoor_run(db, 5, day="2026-06-11", hr=None)  # no HR
    outdoor_run(db, 6, day="2026-06-12", hr=160.0)  # hard effort: valid now
    # 10 min moving at an in-bounds pace (2 km), so the duration rung —
    # not the pace rung that precedes it — is the one that fires.
    outdoor_run(
        db, 7, day="2026-06-13", hr=140.0, distance=2000.0, moving_time=600, elapsed_time=700
    )
    outdoor_run(db, 11, day="2026-06-08", hr=210.0)  # outside sanity band
    outdoor_run(db, 12, day="2026-06-14", hr=140.0, distance=1000.0)  # ~80 min/mi
    # ── Week of Mon 2026-06-15: the 70°F edge — 21.11°C -> 70.0°F stays
    # mild per D14's "50-70"; 21.17°C -> 70.1°F is warm.
    outdoor_run(db, 8, day="2026-06-16", hr=145.0, cell="12.00_12.00", temp_c=21.11)
    outdoor_run(db, 9, day="2026-06-17", hr=145.0, cell="13.00_13.00", temp_c=21.17)
    # ── Valid treadmill run (isolated week of Mon 2026-05-18):
    # must land in the explicit 'indoor' pseudo-band, not 'no_weather'.
    insert_activity(
        db,
        10,
        start="2026-05-20T09:47:23Z",
        start_local="2026-05-20T04:47:23Z",
        start_latlng=None,
        trainer=True,
        average_heartrate=145.0,
    )
    db.commit()

    result = run_dbt("build")
    assert result.returncode == 0, f"dbt build failed:\n{result.stdout}"

    # Exclusion reasons: first failing validity rule (v1.1 order),
    # never a silent filter — and no intensity/intent rungs anymore.
    reasons = dict(
        db.execute(
            "SELECT activity_id, exclusion_reason FROM intermediate.int_run_efficiency ORDER BY 1"
        ).fetchall()
    )
    assert reasons == {
        1: None,
        2: None,
        3: None,
        4: None,  # race tag no longer excludes (v1.1)
        5: "no heart rate data",
        6: None,  # no intensity ceiling anymore (v1.1)
        7: "moving time under 15 minutes",
        8: None,
        9: None,
        10: None,  # treadmill runs are valid — weather isn't a rule
        11: "average HR outside 90–200 bpm sanity band",
        12: "pace outside 4.0–20.0 min/mi bounds",
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
        SELECT week_start_date::text, valid_run_count, is_sufficient,
               median_efficiency_m_per_beat
        FROM analytics.mart_weekly_training ORDER BY week_start_date
        """
    ).fetchall()
    assert [(w[0], w[1], w[2]) for w in weeks] == [
        ("2026-05-18", 1, False),  # the treadmill run's isolated week
        ("2026-06-01", 2, True),
        ("2026-06-08", 3, True),  # race + hard effort now count (v1.1)
        ("2026-06-15", 2, True),
    ]
    # Week 1 median interpolates between 200/150 and 200/140.
    assert float(weeks[1][3]) == pytest.approx((200.0 / 150.0 + 200.0 / 140.0) / 2, abs=0.0001)

    # Trend mart: the 28-day window ending Sun 2026-06-21 spans all
    # seven valid runs after Sun 2026-05-24 (the treadmill run on 05-20
    # falls outside); the week's band comes from its avg temperature.
    (rolling_count, rolling_median, band) = db.execute(
        """
        SELECT rolling_valid_run_count, rolling_median_efficiency,
               temperature_band_key
        FROM analytics.mart_efficiency_trend WHERE week_start_date = '2026-06-15'
        """
    ).fetchone()
    assert rolling_count == 7
    assert float(rolling_median) == pytest.approx(200.0 / 145.0, abs=0.0001)
    assert band == "warm"  # avg(70.0, 70.1) = 70.05 -> rounds into warm

    # Band mart: every band present, boundaries exact, nothing dropped.
    bands = {
        row[0]: (row[1], row[2])
        for row in db.execute(
            """
            SELECT band_key, valid_run_count, median_efficiency_m_per_beat
            FROM analytics.mart_efficiency_by_temp_band
            """
        ).fetchall()
    }
    assert bands["cold"][0] == 1  # 49.9°F
    # 50.0°F and 70.0°F (both edges inclusive) plus the race and the
    # hard effort at the 59.0°F default.
    assert bands["mild"][0] == 4
    assert bands["warm"][0] == 1  # 70.1°F
    # "Not applicable" and "missing" stay distinct: the treadmill run is
    # indoor, the coordinate-less outdoor run is weather-unavailable.
    assert bands["indoor"][0] == 1
    assert bands["no_weather"][0] == 1
    assert sum(count for count, _ in bands.values()) == 8  # conservation

    # Run-level quality mart: every run visible with its verdict, band,
    # and an efficiency value even when invalid.
    quality = {
        row[0]: (row[1], row[2], row[3])
        for row in db.execute(
            "SELECT activity_id, exclusion_reason, temperature_band_label, "
            "       aerobic_efficiency_m_per_heartbeat "
            "FROM analytics.mart_run_quality"
        ).fetchall()
    }
    assert len(quality) == 12  # every run, valid or not
    assert quality[4][0] is None  # the race counts now (v1.1)
    assert quality[11][0] == "average HR outside 90–200 bpm sanity band"
    assert quality[11][2] is not None  # invalid runs keep their value
    assert quality[1][1] == "< 50°F"  # banded per-run by its own temp
    assert quality[3][1] == "weather unavailable"  # outdoor, unmatched
    assert quality[10][1] == "indoor"  # trainer: not applicable, not missing
    assert quality[5][2] is None  # no HR -> no value (missing, not zero)


def insert_stream(db, activity_id, *, status="success", samples=None, drop=()):
    """Store a synthetic key_by_type streams payload (or a status-only row).

    `drop` removes stream types from an otherwise complete payload — the
    'missing required stream types' fixtures need a success row whose
    arrays are incomplete.
    """
    payload = {}
    sample_count = None
    if samples is not None:
        elapsed, hr, velocity, moving = samples
        sample_count = len(elapsed)
        payload = {
            "time": {"data": elapsed, "original_size": sample_count},
            "heartrate": {"data": hr, "original_size": sample_count},
            "velocity_smooth": {"data": velocity, "original_size": sample_count},
            "moving": {"data": moving, "original_size": sample_count},
            "grade_smooth": {"data": [0.0] * sample_count, "original_size": sample_count},
        }
        for stream_type in drop:
            payload.pop(stream_type, None)
    db.execute(
        """
        INSERT INTO raw_strava.streams
            (activity_id, payload, sample_count, fetched_at, ingestion_status)
        VALUES (%s, %s, %s, now(), %s)
        """,
        (activity_id, json.dumps(payload), sample_count, status),
    )


def steady_stream(*, seconds=3600, step=1, first_half_hr=140.0, second_half_hr=150.0, pause=None):
    """A hand-checkable synthetic run at constant 3.0 m/s (180 m/min).

    The D16 window for a 3600 s run is 600..3300 s, midpoint 1950. HR
    switches exactly at the midpoint, and the warm-up/cool-down carry
    absurd values (10 m/s sprint, 0.5 m/s crawl) so any trimming bug
    changes the expected numbers. `pause` marks [start, end) elapsed
    seconds as non-moving. Efficiency per half = 180 / HR, so
    decoupling_pct = (1 - first_half_hr / second_half_hr) * 100.
    """
    elapsed = list(range(0, seconds, step))
    hr, velocity, moving = [], [], []
    for t in elapsed:
        if t < 600:
            hr.append(120.0)
            velocity.append(10.0)  # would inflate half 1 if trimming broke
        elif t > seconds - 300:
            hr.append(190.0)
            velocity.append(0.5)  # would poison half 2 if trimming broke
        else:
            hr.append(first_half_hr if t <= (600 + seconds - 300) / 2 else second_half_hr)
            velocity.append(3.0)
        moving.append(not (pause and pause[0] <= t < pause[1]))
    return elapsed, hr, velocity, moving


def band_stream(
    *, seconds=3600, step=1, first_hr=135.0, second_hr=145.0, velocity=3.0, hr_schedule=None
):
    """A hand-checkable synthetic run for the D22 BAND window.

    The steady_stream pattern re-sized to the band trims: the D22
    window for the run is 300 .. (last sample - 120) s, and the
    warm-up/cool-down carry absurd values (10 m/s sprint at HR 120,
    0.5 m/s crawl at HR 190) so any trimming bug visibly shifts the
    band inventory and its medians. By default HR switches exactly at
    the band-window midpoint, so the run splits its dwell almost evenly
    between two decade bands at constant `velocity`; `hr_schedule(t)`
    overrides the two-band default for ladder fixtures (band cycling,
    short band visits).
    """
    window_start = 300  # band_warmup_trim_minutes * 60
    window_end = (seconds - step) - 120  # last sample - band_cooldown_trim_minutes * 60
    midpoint = (window_start + window_end) / 2
    elapsed = list(range(0, seconds, step))
    hr, vel, moving = [], [], []
    for t in elapsed:
        if t < window_start:
            hr.append(120.0)
            vel.append(10.0)  # would pollute the low bands if trimming broke
        elif t > seconds - 120:
            hr.append(190.0)
            vel.append(0.5)  # would poison the high bands if trimming broke
        else:
            if hr_schedule is not None:
                hr.append(hr_schedule(t))
            else:
                hr.append(first_hr if t <= midpoint else second_hr)
            vel.append(velocity)
        moving.append(True)
    return elapsed, hr, vel, moving


def drift_run(db, activity_id, *, day, moving_time=3600, hr=145.0, **kwargs):
    """An HR-carrying, drift-length activity (no weather needed)."""
    insert_activity(
        db,
        activity_id,
        start=f"{day}T09:00:00Z",
        start_local=f"{day}T04:00:00Z",
        start_latlng=None,
        trainer=False,
        distance=10800.0,
        moving_time=moving_time,
        elapsed_time=moving_time + 100,
        average_heartrate=hr,
        **kwargs,
    )


@pytest.mark.integration
def test_drift_decoupling_formula_and_analysis_window(db):
    # Two clean runs in one week: decoupling = (1 - HR1/HR2) * 100
    # exactly, because speed is constant across the window. The second
    # is tagged as a race: intensity/intent no longer gates drift
    # candidacy (D15 revised v1.1) — only duration and HR do.
    drift_run(db, 1, day="2026-06-15")
    insert_stream(db, 1, samples=steady_stream())  # 140 -> 150: 6.667 %
    drift_run(db, 2, day="2026-06-17", workout_type=1)
    insert_stream(db, 2, samples=steady_stream(second_half_hr=145.0))  # 3.448 %
    # Excluded candidates, one per D16 ladder rung that data can reach:
    drift_run(db, 3, day="2026-06-18")  # no streams row at all
    drift_run(db, 4, day="2026-06-19")
    insert_stream(db, 4, status="unavailable")
    drift_run(db, 5, day="2026-06-20", moving_time=2700)  # 45 min run,
    insert_stream(db, 5, samples=steady_stream(seconds=2400))  # 25-min window
    drift_run(db, 6, day="2026-06-21")
    insert_stream(db, 6, samples=steady_stream(pause=(600, 1420)))  # ~30 % paused
    drift_run(db, 7, day="2026-06-22")
    insert_stream(db, 7, samples=steady_stream(step=5))  # 5 s gaps > 3 s max
    # Not a candidate: short run (< 45 min) must not appear at all.
    insert_activity(
        db, 8, start_latlng=None, average_heartrate=140.0, moving_time=2400, elapsed_time=2500
    )
    # Not a candidate either: long enough, but no HR (the other half of
    # the revised D15 gate).
    drift_run(db, 9, day="2026-06-23", hr=None)
    db.commit()

    result = run_dbt("build")
    assert result.returncode == 0, f"dbt build failed:\n{result.stdout}"

    halves = {
        row[0]: (row[1], row[2])
        for row in db.execute(
            "SELECT activity_id, decoupling_pct, exclusion_reason "
            "FROM analytics.fct_drift_candidates"
        ).fetchall()
    }
    assert set(halves) == {1, 2, 3, 4, 5, 6, 7}  # 8 (short) and 9 (no HR) are not candidates

    # The formula, exactly (acceptance criterion 5).
    assert float(halves[1][0]) == pytest.approx((1 - 140 / 150) * 100, abs=0.01)
    assert float(halves[2][0]) == pytest.approx((1 - 140 / 145) * 100, abs=0.01)

    # Deterministic reasons, first failing check per run (criterion 4).
    assert halves[3] == (None, "streams not yet loaded")
    assert halves[4] == (None, "streams unavailable from Strava")
    assert halves[5][1] == "analysis window under 30 minutes after trimming"
    assert halves[6][1] == "excessive pauses (non-moving share above 0.25)"
    assert halves[7][1] == "insufficient sample coverage"

    # The documented window: 3600 s run -> 600..3300 -> 45 minutes.
    (window_min, first_hr, second_hr) = db.execute(
        "SELECT analysis_window_min, first_half_hr_bpm, second_half_hr_bpm "
        "FROM analytics.mart_run_drift WHERE activity_id = 1"
    ).fetchone()
    assert float(window_min) == 45.0
    assert (float(first_hr), float(second_hr)) == (140.0, 150.0)  # trim held

    # Only analyzed runs reach the mart; the trend week is sufficient.
    assert db.execute("SELECT count(*) FROM analytics.mart_run_drift").fetchone()[0] == 2
    (count, median, sufficient) = db.execute(
        "SELECT drift_run_count, median_decoupling_pct, is_sufficient "
        "FROM analytics.mart_drift_trend WHERE week_start_date = '2026-06-15'"
    ).fetchone()
    assert count == 2
    expected_median = ((1 - 140 / 150) * 100 + (1 - 140 / 145) * 100) / 2
    assert float(median) == pytest.approx(expected_median, abs=0.01)
    assert sufficient is True


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


@pytest.mark.integration
def test_relationships_test_fails_on_orphan_drift_candidate(db):
    # The fct_drift_candidates -> fct_runs relationships test was proven
    # red-first once (commit 6e478af); this re-proves it on every run.
    # Both models descend from int_run_efficiency, so no raw fixture can
    # produce an orphan — it must be injected into the built table.
    result = run_dbt("build")
    assert result.returncode == 0, f"dbt build failed:\n{result.stdout}"

    # Insert AFTER the build and test WITHOUT rebuilding: a rebuild
    # would erase the orphan and a green run would prove nothing.
    db.execute("INSERT INTO analytics.fct_drift_candidates (activity_id) VALUES (999999999)")
    db.commit()

    selector = "relationships_fct_drift_candidates_activity_id__activity_id__ref_fct_runs_"
    result = run_dbt("test", "--select", selector)
    assert result.returncode != 0, "relationships test should fail on an orphan candidate"
    assert selector in result.stdout

    db.execute("DELETE FROM analytics.fct_drift_candidates WHERE activity_id = 999999999")
    db.commit()

    result = run_dbt("test", "--select", selector)
    assert result.returncode == 0, f"relationships test still failing:\n{result.stdout}"


@pytest.mark.integration
def test_relationships_test_fails_on_orphan_band_candidate(db):
    # The fct_band_candidates -> fct_runs relationships test, proven red
    # the same way as the drift one (commit f8c7185): both models descend
    # from int_run_efficiency, so no raw fixture can produce an orphan —
    # it must be injected into the built table.
    drift_run(db, 1, day="2026-06-15")
    insert_stream(db, 1, samples=steady_stream())
    db.commit()

    result = run_dbt("build")
    assert result.returncode == 0, f"dbt build failed:\n{result.stdout}"

    # Insert AFTER the build and test WITHOUT rebuilding: a rebuild
    # would erase the orphan and a green run would prove nothing.
    db.execute("INSERT INTO analytics.fct_band_candidates (activity_id) VALUES (999999999)")
    db.commit()

    selector = "relationships_fct_band_candidates_activity_id__activity_id__ref_fct_runs_"
    result = run_dbt("test", "--select", selector)
    assert result.returncode != 0, "relationships test should fail on an orphan candidate"
    assert selector in result.stdout

    db.execute("DELETE FROM analytics.fct_band_candidates WHERE activity_id = 999999999")
    db.commit()

    result = run_dbt("test", "--select", selector)
    assert result.returncode == 0, f"relationships test still failing:\n{result.stdout}"


@pytest.mark.integration
def test_band_candidates_exclusive_exhaustive(db):
    # D22 contract: every band candidate carries EXACTLY ONE of
    # (>= 1 band segment, exclusion_reason) — mutually exclusive,
    # jointly exhaustive. Fixtures put data on both sides so neither
    # direction passes vacuously: an analyzed hour-long run, and a
    # 25-minute HR run past the fetch gate but with no streams row yet.
    drift_run(db, 1, day="2026-06-15")
    insert_stream(db, 1, samples=steady_stream())
    drift_run(db, 2, day="2026-06-16", moving_time=1500)  # candidate, no streams
    # Not a candidate: HR run under the 20-minute fetch gate.
    insert_activity(
        db, 3, start_latlng=None, average_heartrate=140.0, moving_time=900, elapsed_time=1000
    )
    db.commit()

    result = run_dbt("build")
    assert result.returncode == 0, f"dbt build failed:\n{result.stdout}"

    candidates = {
        row[0]
        for row in db.execute("SELECT activity_id FROM analytics.fct_band_candidates").fetchall()
    }
    assert candidates == {1, 2}  # 3 is under the fetch gate

    violations = db.execute(
        """
        SELECT c.activity_id, c.exclusion_reason, coalesce(s.segment_count, 0)
        FROM analytics.fct_band_candidates c
        LEFT JOIN (
            SELECT activity_id, count(*) AS segment_count
            FROM analytics.fct_run_band_segments
            GROUP BY activity_id
        ) s USING (activity_id)
        WHERE (c.exclusion_reason IS NULL) != (coalesce(s.segment_count, 0) >= 1)
        """
    ).fetchall()
    assert violations == [], f"candidates violating the segments-XOR-reason contract: {violations}"


@pytest.mark.integration
def test_band_medians_dwell_and_exclusion_ladder(db):
    # Acceptance criterion 3: constant 3.0 m/s, HR stepping 135 -> 145
    # at the band-window midpoint -> two decade bands, near-equal dwell,
    # median velocity 3.0 in each. The poisoned warm-up/cool-down means
    # a trimming break shifts every number asserted below.
    drift_run(db, 1, day="2026-06-15")
    insert_stream(db, 1, samples=band_stream())
    # Same week, slower run: the weekly statistic must be the median
    # ACROSS RUNS of the run-level medians (D11), not a sample pool.
    drift_run(db, 2, day="2026-06-17")
    insert_stream(db, 2, samples=band_stream(first_hr=137.0, second_hr=147.0, velocity=2.5))
    # Criterion 4's dwell-minimum fixture: a 2-minute visit to the 150s
    # band must leave that band ABSENT while the run itself analyzes.
    drift_run(db, 3, day="2026-06-22")
    insert_stream(
        db,
        3,
        samples=band_stream(
            hr_schedule=lambda t: 155.0 if t < 420 else (135.0 if t <= 1889.5 else 145.0)
        ),
    )
    # One fixture per remaining reachable ladder rung (criterion 4):
    drift_run(db, 4, day="2026-06-18")  # no streams row at all
    drift_run(db, 5, day="2026-06-19")
    insert_stream(db, 5, status="unavailable")
    drift_run(db, 6, day="2026-06-19")
    insert_stream(db, 6, status="failed")
    drift_run(db, 7, day="2026-06-20")
    insert_stream(db, 7, samples=band_stream(), drop=("heartrate",))
    drift_run(db, 8, day="2026-06-20", moving_time=1500)  # 25-min run,
    insert_stream(db, 8, samples=band_stream(seconds=900))  # ~8-min window
    drift_run(db, 9, day="2026-06-21")
    insert_stream(db, 9, samples=band_stream(step=5))  # 5 s gaps > 3 s max
    drift_run(db, 10, day="2026-06-21", moving_time=1500)
    insert_stream(  # cycles FIVE bands every 60 s across an 18-block
        # window: no band collects more than 4 blocks (240 s < 5 min)
        db,
        10,
        samples=band_stream(seconds=1500, hr_schedule=lambda t: 135.0 + 10.0 * ((t // 60) % 5)),
    )
    # Not candidates: an HR run under the 20-minute FETCH gate, and a
    # long run without HR (the other half of the revised D15 gate).
    insert_activity(
        db, 11, start_latlng=None, average_heartrate=140.0, moving_time=900, elapsed_time=1000
    )
    drift_run(db, 12, day="2026-06-23", hr=None)
    db.commit()

    result = run_dbt("build")
    assert result.returncode == 0, f"dbt build failed:\n{result.stdout}"

    candidates = {
        row[0]: row[1]
        for row in db.execute(
            "SELECT activity_id, exclusion_reason FROM analytics.fct_band_candidates"
        ).fetchall()
    }
    assert set(candidates) == {1, 2, 3, 4, 5, 6, 7, 8, 9, 10}  # 11 (short) and 12 (no HR) are out

    # Deterministic reasons, first failing check per run (the ladder).
    assert candidates[4] == "streams not yet loaded"
    assert candidates[5] == "streams unavailable from Strava"
    assert candidates[6] == "stream fetch failed (retried by next backfill)"
    assert candidates[7] == "missing required stream types"
    assert candidates[8] == "analysis window under 10 minutes after trimming"
    assert candidates[9] == "insufficient sample coverage"
    assert candidates[10] == "no band meets the dwell minimum"
    assert candidates[1] is None and candidates[2] is None and candidates[3] is None

    segments = {
        (row[0], row[1]): (float(row[2]), float(row[3]), float(row[4]))
        for row in db.execute(
            "SELECT activity_id, band_key, dwell_s, median_velocity_m_per_s,"
            "       median_pace_min_per_mi"
            "  FROM analytics.fct_run_band_segments"
        ).fetchall()
    }
    # Run 1, hand-checked: window 300..3479 s; 135 bpm through t=1889
    # (1590 samples: the first carries the 3 s dwell cap, the rest 1 s
    # gaps), 145 bpm for t=1890..3479 (1590 samples, all 1 s gaps).
    # Median velocity 3.0 m/s -> 1609.344 / 180 = 8.94 min/mi.
    assert segments[(1, "130_139")] == (1592.0, 3.0, 8.94)
    assert segments[(1, "140_149")] == (1590.0, 3.0, 8.94)
    # Run 2: same shape at 2.5 m/s -> 1609.344 / 150 = 10.73 min/mi.
    assert segments[(2, "130_139")][1:] == (2.5, 10.73)
    assert segments[(2, "140_149")][1:] == (2.5, 10.73)
    # Run 3: the 2-minute 150s visit deposits NO segment (dwell 122 s
    # < 5 min); the run still contributes its two real bands.
    run3_bands = {band for (activity, band) in segments if activity == 3}
    assert run3_bands == {"130_139", "140_149"}

    # Weekly (D11 median-of-runs, D12 at week x band grain): the week
    # of 2026-06-15 has runs 1 (3.0 m/s) and 2 (2.5 m/s) in both bands
    # -> median velocity 2.75 -> 1609.344 / 165 = 9.75 min/mi.
    weekly = {
        row[0]: (row[1], float(row[2]), row[3])
        for row in db.execute(
            "SELECT band_key, contributing_run_count, median_pace_min_per_mi, is_sufficient"
            "  FROM analytics.mart_band_weekly WHERE week_start_date = '2026-06-15'"
        ).fetchall()
    }
    assert weekly["130_139"] == (2, 9.75, True)
    assert weekly["140_149"] == (2, 9.75, True)
    # Run 3's week has one contributing run: present but insufficient.
    (run3_sufficient,) = db.execute(
        "SELECT is_sufficient FROM analytics.mart_band_weekly"
        " WHERE week_start_date = '2026-06-22' AND band_key = '130_139'"
    ).fetchone()
    assert run3_sufficient is False

    # Trend: static rolling columns; the 28-day window ending the later
    # week's Sunday spans all three analyzed runs.
    trend = {
        row[0]: (float(row[1]), row[2], row[3])
        for row in db.execute(
            "SELECT week_start_date::text, rolling_median_pace_min_per_mi,"
            "       rolling_band_run_count, is_sufficient"
            "  FROM analytics.mart_band_trend WHERE band_key = '130_139'"
        ).fetchall()
    }
    assert trend["2026-06-15"] == (9.75, 2, True)  # runs 1 + 2
    assert trend["2026-06-22"] == (8.94, 3, False)  # runs 1 + 2 + 3: median 3.0 m/s

    # The reasons ride to the dashboard mart on the drift route.
    quality = {
        row[0]: row[1]
        for row in db.execute(
            "SELECT activity_id, band_exclusion_reason FROM analytics.mart_run_quality"
        ).fetchall()
    }
    assert quality[4] == "streams not yet loaded"
    assert quality[1] is None  # analyzed
    assert quality[11] is None  # not a band candidate at all
