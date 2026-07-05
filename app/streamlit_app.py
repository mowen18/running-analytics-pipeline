"""Thin presentation layer: exactly three views (D19), reading ONLY the
analytics schema (marts + fct_runs). No business logic here — every
metric, threshold, flag, and exclusion is computed in dbt; this file
selects, charts, and explains. Sample counts and data sufficiency are
always visible, missing data is explained rather than hidden, and all
trend language stays observational (never causal).
"""

import altair as alt
import pandas as pd
import streamlit as st

from running_pipeline.config import load_settings
from running_pipeline.database import get_connection

# Reference dataviz palette (validated): emphasis blue, de-emphasis
# gray for context series, an ordinal blue ramp for the ordered
# temperature bands, and recessive chart chrome.
BLUE = "#2a78d6"
GRAY = "#898781"
ORDINAL_RAMP = {"cold": "#86b6ef", "mild": "#2a78d6", "warm": "#104281", "no_weather": "#c3c2b7"}
GRIDLINE = "#e1e0d9"

# The app may read exactly these relations, all in the analytics schema.
# The allow-list is the D19 "marts only" rule made mechanical (and is
# asserted by tests/test_app.py).
ANALYTICS_TABLES = (
    "fct_runs",
    "mart_weekly_training",
    "mart_efficiency_trend",
    "mart_efficiency_by_temp_band",
    "mart_run_drift",
    "mart_drift_trend",
)

OBSERVATIONAL_NOTE = (
    "Observational signal, not proof: efficiency and drift move with weather, "
    "terrain, sleep, and measurement noise — trends here are never causal claims."
)


@st.cache_data(ttl=300)
def load(table: str) -> pd.DataFrame:
    if table not in ANALYTICS_TABLES:
        raise ValueError(f"{table} is not an approved analytics relation")
    with get_connection(load_settings()) as conn:
        cursor = conn.execute(f"SELECT * FROM analytics.{table}")  # noqa: S608 — allow-listed
        columns = [description.name for description in cursor.description]
        return pd.DataFrame(cursor.fetchall(), columns=columns)


def themed(chart: alt.Chart) -> alt.Chart:
    return chart.configure_axis(
        gridColor=GRIDLINE, labelColor=GRAY, titleColor=GRAY, domainColor="#c3c2b7"
    ).configure_view(strokeWidth=0)


def hr_availability_note(runs: pd.DataFrame) -> str:
    with_hr = int(runs["has_heartrate"].sum()) if not runs.empty else 0
    return (
        f"{with_hr} of {len(runs)} recorded runs carry heart-rate data. "
        "Every efficiency and drift metric requires it (D9/D15): runs synced "
        "from Apple Health arrive without HR, so these views populate once "
        "runs are recorded in a way that sends HR to Strava."
    )


# ── View 1: Aerobic Efficiency ────────────────────────────────────────


def efficiency_view():
    st.header("Aerobic efficiency")
    st.caption(
        "aerobic_efficiency_m_per_heartbeat = speed (m/min) ÷ average HR (bpm) — "
        "approximate meters per heartbeat across qualifying easy runs (D9 rules, "
        "median weekly, 28-day rolling median). " + OBSERVATIONAL_NOTE
    )

    trend = load("mart_efficiency_trend")
    # astype(bool): psycopg hands back object dtype on empty frames, and
    # a non-bool mask would select columns instead of rows.
    sufficient = trend[trend["is_sufficient"].astype(bool)].copy()

    if sufficient["median_efficiency_m_per_beat"].dropna().empty:
        st.info(
            "No trend to display yet: no week has the required "
            f"{2} qualifying easy runs. " + hr_availability_note(load("fct_runs"))
        )
    else:
        weekly = (
            alt.Chart(sufficient)
            .mark_circle(size=64, color=GRAY)
            .encode(
                x=alt.X("week_start_date:T", title="training week"),
                y=alt.Y("median_efficiency_m_per_beat:Q", title="m per heartbeat"),
                tooltip=[
                    alt.Tooltip("week_start_date:T", title="week"),
                    alt.Tooltip("median_efficiency_m_per_beat:Q", title="weekly median"),
                    alt.Tooltip("qualifying_run_count:Q", title="qualifying runs (n)"),
                ],
            )
            .properties(height=320)
        )
        rolling = (
            alt.Chart(sufficient.dropna(subset=["rolling_28d_median_efficiency"]))
            .mark_line(color=BLUE, strokeWidth=2, point=alt.OverlayMarkDef(color=BLUE, size=36))
            .encode(
                x="week_start_date:T",
                y="rolling_28d_median_efficiency:Q",
                tooltip=[
                    alt.Tooltip("week_start_date:T", title="week"),
                    alt.Tooltip("rolling_28d_median_efficiency:Q", title="28-day median"),
                    alt.Tooltip("rolling_28d_qualifying_run_count:Q", title="runs in window (n)"),
                ],
            )
        )
        st.altair_chart(themed(alt.layer(weekly, rolling)), use_container_width=True)
        st.caption(
            "Blue line: 28-day rolling median (the primary trend). Gray points: "
            "single-week medians. Weeks below the 2-qualifying-run sufficiency "
            "threshold are excluded from this chart and flagged in the table."
        )

    st.subheader("Efficiency by temperature band")
    bands = load("mart_efficiency_by_temp_band")
    if bands["qualifying_run_count"].sum() == 0:
        st.info("All temperature bands are empty until qualifying runs exist.")
    else:
        band_chart = (
            alt.Chart(bands)
            .mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4)
            .encode(
                x=alt.X("band_label:N", sort=alt.SortField("sort_order"), title=None),
                y=alt.Y("median_efficiency_m_per_beat:Q", title="median m per heartbeat"),
                color=alt.Color(
                    "band_key:N",
                    scale=alt.Scale(domain=list(ORDINAL_RAMP), range=list(ORDINAL_RAMP.values())),
                    legend=None,  # ordered bands are labeled on the axis
                ),
                tooltip=[
                    alt.Tooltip("band_label:N", title="band"),
                    alt.Tooltip("median_efficiency_m_per_beat:Q", title="median"),
                    alt.Tooltip("mean_efficiency_m_per_beat:Q", title="mean"),
                    alt.Tooltip("qualifying_run_count:Q", title="runs (n)"),
                ],
            )
            .properties(height=260)
        )
        st.altair_chart(themed(band_chart), use_container_width=True)

    st.dataframe(trend, use_container_width=True, hide_index=True)
    st.caption("All weeks, including insufficient ones — nothing is dropped, only flagged.")


# ── View 2: Weekly Training ───────────────────────────────────────────


def weekly_view():
    st.header("Weekly training")
    weekly = load("mart_weekly_training")

    if weekly.empty:
        st.info("No running weeks yet — run `make sync-activities` then `make dbt-build`.")
        return

    total_mi = weekly["total_distance_mi"].sum()
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total miles", f"{total_mi:,.1f}")
    col2.metric("Runs", int(weekly["run_count"].sum()))
    col3.metric("Long runs (≥45 min)", int(weekly["long_run_count"].sum()))
    col4.metric("Qualifying easy runs", int(weekly["qualifying_run_count"].sum()))

    mileage = (
        alt.Chart(weekly)
        .mark_bar(color=BLUE, cornerRadiusTopLeft=4, cornerRadiusTopRight=4)
        .encode(
            x=alt.X("week_start_date:T", title="training week"),
            y=alt.Y("total_distance_mi:Q", title="miles"),
            tooltip=[
                alt.Tooltip("week_start_date:T", title="week"),
                alt.Tooltip("total_distance_mi:Q", title="miles"),
                alt.Tooltip("total_moving_time_min:Q", title="moving min"),
                alt.Tooltip("run_count:Q", title="runs (n)"),
            ],
        )
        .properties(height=300)
    )
    st.altair_chart(themed(mileage), use_container_width=True)

    st.dataframe(weekly, use_container_width=True, hide_index=True)
    st.caption(
        "Volume counts every run; efficiency columns aggregate qualifying easy "
        "runs only and stay empty (never zero) for weeks without them."
    )


# ── View 3: Cardiac Drift ─────────────────────────────────────────────


def drift_view():
    st.header("Cardiac drift")
    st.caption(
        "Decoupling % compares efficiency between equal halves of long easy runs "
        "(first 10 min and last 5 min trimmed). Sign convention (D17): positive = "
        "efficiency declined in the second half; near zero = stable; negative = "
        "second half improved. " + OBSERVATIONAL_NOTE
    )

    runs = load("mart_run_drift")
    if runs.empty:
        st.info(
            "No analyzed drift runs yet. Drift needs runs ≥45 minutes with "
            "heart-rate streams (D15). " + hr_availability_note(load("fct_runs"))
        )
        return

    zero_line = alt.Chart(pd.DataFrame({"y": [0.0]})).mark_rule(color=GRAY).encode(y="y:Q")
    points = (
        alt.Chart(runs)
        .mark_circle(size=80, color=BLUE)
        .encode(
            x=alt.X("start_date_local:T", title="run date"),
            y=alt.Y("decoupling_pct:Q", title="decoupling % (positive = second-half decline)"),
            tooltip=[
                alt.Tooltip("start_date_local:T", title="run"),
                alt.Tooltip("decoupling_pct:Q", title="decoupling %"),
                alt.Tooltip("analysis_window_min:Q", title="window (min)"),
                alt.Tooltip("valid_sample_count:Q", title="valid samples (n)"),
                alt.Tooltip("temperature_f:Q", title="°F"),
            ],
        )
        .properties(height=320)
    )
    st.altair_chart(themed(alt.layer(zero_line, points)), use_container_width=True)

    trend = load("mart_drift_trend")
    sufficient = trend[trend["is_sufficient"].astype(bool)]
    if sufficient.empty:
        st.info(
            "Weekly drift trend hidden: no week reaches the 2-run sufficiency "
            "threshold yet (weeks and counts below)."
        )
    else:
        rolling = (
            alt.Chart(sufficient.dropna(subset=["rolling_28d_median_decoupling_pct"]))
            .mark_line(color=BLUE, strokeWidth=2, point=alt.OverlayMarkDef(color=BLUE, size=36))
            .encode(
                x=alt.X("week_start_date:T", title="training week"),
                y=alt.Y("rolling_28d_median_decoupling_pct:Q", title="28-day median decoupling %"),
                tooltip=[
                    alt.Tooltip("week_start_date:T", title="week"),
                    alt.Tooltip("rolling_28d_median_decoupling_pct:Q", title="28-day median"),
                    alt.Tooltip("rolling_28d_drift_run_count:Q", title="runs in window (n)"),
                ],
            )
            .properties(height=280)
        )
        st.altair_chart(themed(alt.layer(zero_line, rolling)), use_container_width=True)

    st.dataframe(trend, use_container_width=True, hide_index=True)
    st.caption("All drift weeks with sample counts; insufficient weeks are flagged, not deleted.")


# ── Shell ─────────────────────────────────────────────────────────────

st.set_page_config(page_title="Running Analytics", layout="wide")
st.sidebar.title("Running analytics")
VIEWS = {
    "Aerobic efficiency": efficiency_view,
    "Weekly training": weekly_view,
    "Cardiac drift": drift_view,
}
choice = st.sidebar.radio("View", list(VIEWS))
st.sidebar.caption(
    "Reads analytics marts only — every metric is defined, tested, and "
    "documented in dbt (see README for definitions)."
)
VIEWS[choice]()
