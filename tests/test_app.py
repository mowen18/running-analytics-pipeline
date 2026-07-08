"""Streamlit app tests.

The marts-only rule (D19) is enforced mechanically at two levels: the
app source must never name a non-analytics schema, and the allow-list
must contain exactly the six marts — core facts share the analytics
schema, so only a table-level pin can keep them out. The @integration
tests drive the real app headlessly (streamlit AppTest) against the
scratch database — once with empty marts (every view must explain
itself, not crash) and once with the drift fixtures (every view must
render its charts).
"""

import importlib.util
import os
from pathlib import Path

import pandas as pd
import pytest
import streamlit as st

from test_dbt_models import (
    db,  # noqa: F401 — shared truncating fixture
    drift_run,
    insert_stream,
    run_dbt,
    steady_stream,
)

APP_PATH = Path(__file__).resolve().parent.parent / "app" / "streamlit_app.py"
TEST_DB = "running_analytics_test"
VIEW_NAMES = ["Aerobic efficiency", "Weekly training", "Cardiac drift"]

# The complete mart layer (dbt/models/marts/) — D19 allows nothing else.
MART_TABLES = frozenset(
    {
        "mart_weekly_training",
        "mart_efficiency_trend",
        "mart_efficiency_by_temp_band",
        "mart_run_quality",
        "mart_run_drift",
        "mart_drift_trend",
    }
)


def load_app_module():
    spec = importlib.util.spec_from_file_location("streamlit_app", APP_PATH)
    app = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(app)  # safe: the shell runs only under __main__
    return app


def test_app_reads_only_the_analytics_schema():
    source = APP_PATH.read_text()
    for forbidden in ("raw_strava", "raw_weather", "staging.", "intermediate."):
        assert forbidden not in source, f"app source references {forbidden}: marts only (D19)"
    assert 'SELECT * FROM analytics.{table}"' in source  # the single query site


def test_allow_list_is_pinned_to_the_six_marts():
    app = load_app_module()
    assert set(app.ANALYTICS_TABLES) == MART_TABLES, "the allow-list is marts only (D19)"


def test_core_relations_are_refused_even_in_the_analytics_schema():
    """fct_runs lives in the same Postgres schema as the marts, so a
    schema-level check would let it through — the table-level guard in
    load() must refuse it before any connection is opened."""
    app = load_app_module()
    with pytest.raises(ValueError, match="not an approved analytics relation"):
        app.load("fct_runs")


def test_decimals_are_coerced_to_float_for_the_browser():
    """Postgres numerics arrive as Decimal; Arrow ships Decimal as
    decimal128, which Vega-Lite reads UNSCALED (0.7838 charted as 7838).
    to_dataframe must coerce to float64 — the regression test for the
    first-real-data chart bug."""
    from decimal import Decimal

    app = load_app_module()

    df = app.to_dataframe(
        [
            (1, Decimal("0.7838"), None, None, "mild"),
            (2, Decimal("14.5"), Decimal("70.0"), None, None),
        ],
        ["week", "efficiency", "temperature_f", "humidity", "band"],
    )

    assert df["efficiency"].dtype == "float64"
    assert df["temperature_f"].dtype == "float64"
    assert df["efficiency"].tolist() == [0.7838, 14.5]
    assert pd.isna(df["temperature_f"].iloc[0])  # None -> NaN, shown blank
    # All-NULL columns (no weather anywhere) must not stay object dtype,
    # or tables render the literal string "None".
    assert df["humidity"].dtype == "float64"
    assert df["humidity"].isna().all()
    # Text columns go nullable-string so missing text renders blank too.
    assert df["band"].dtype == "string"
    assert pd.isna(df["band"].iloc[1])
    assert df["week"].tolist() == [1, 2]  # non-Decimal columns untouched


def render(view: str):
    """Run the app headlessly on the scratch DB, switched to `view`."""
    from streamlit.testing.v1 import AppTest

    st.cache_data.clear()  # never let one test's frames leak into the next
    os.environ["POSTGRES_DB"] = TEST_DB  # Settings: env beats .env
    try:
        at = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
        at.sidebar.radio[0].set_value(view)
        return at.run()
    finally:
        del os.environ["POSTGRES_DB"]


@pytest.mark.integration
def test_every_view_explains_empty_marts_without_crashing(db):  # noqa: F811
    result = run_dbt("build")
    assert result.returncode == 0, f"dbt build failed:\n{result.stdout}"

    for view in VIEW_NAMES:
        at = render(view)
        assert not at.exception, f"{view} raised with empty marts: {at.exception}"
        # Missing data is explained, never a blank page (dashboard rule).
        assert at.info, f"{view} shows no empty-state explanation"


@pytest.mark.integration
def test_every_view_renders_with_populated_marts(db):  # noqa: F811
    drift_run(db, 1, day="2026-06-15")
    insert_stream(db, 1, samples=steady_stream())
    drift_run(db, 2, day="2026-06-17")
    insert_stream(db, 2, samples=steady_stream(second_half_hr=145.0))
    db.commit()
    result = run_dbt("build")
    assert result.returncode == 0, f"dbt build failed:\n{result.stdout}"

    for view in VIEW_NAMES:
        at = render(view)
        assert not at.exception, f"{view} raised with populated marts: {at.exception}"

    weekly = render("Weekly training")
    assert weekly.metric[0].value == "13.4"  # 2 × 10.8 km in miles
    drift = render("Cardiac drift")
    # Sign convention must be stated on the view itself (D17).
    assert any("positive = " in c.value for c in drift.caption)
    # The eligibility table renders alongside the weekly trend table.
    efficiency = render("Aerobic efficiency")
    assert len(efficiency.dataframe) >= 2
