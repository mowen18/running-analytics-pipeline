"""Thin presentation layer: exactly three views (D19), reading ONLY the
approved mart tables. No business logic here — every
metric, threshold, flag, and exclusion is computed in dbt; this file
selects, charts, and explains. Sample counts and data sufficiency are
always visible, missing data is explained rather than hidden, and all
trend language stays observational (never causal).
"""

from decimal import Decimal

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
INK_SECONDARY = "#52514e"
# The three D14 bands use the ordinal blue ramp; the two pseudo-bands
# (indoor = weather not applicable, no_weather = weather missing) sit
# outside the temperature scale and get neutral grays instead.
ORDINAL_RAMP = {
    "cold": "#86b6ef",
    "mild": "#2a78d6",
    "warm": "#104281",
    "indoor": "#898781",
    "no_weather": "#c3c2b7",
}
GRIDLINE = "#e1e0d9"

# Daily time axis: date-level tick labels, never hour-level.
DAY_AXIS = alt.Axis(format="%b %d", labelAngle=0, tickCount="day")
# Pixel padding so edge points/bars aren't clipped against the plot frame.
TIME_X_SCALE = alt.Scale(padding=20)


def week_axis(week_dates) -> alt.Axis:
    """Ticks exactly under the Monday-based training weeks present.

    Vega's "week" tick interval is Sunday-based, which strands labels
    between our Monday data points; explicit values fix that, and
    labelOverlap thins them once the history grows.
    """
    values = [{"year": d.year, "month": d.month, "date": d.day} for d in sorted(set(week_dates))]
    return alt.Axis(format="%b %d", labelAngle=0, values=values, labelOverlap="greedy")


# The app may read exactly the approved marts — nothing else, even in
# the analytics schema (core facts live there too). The allow-list is
# the D19 "marts only" rule made mechanical; tests/test_app.py pins its
# contents and asserts everything off the list is refused.
# mart_band_weekly is deliberately absent: the weekly band statistics
# travel inside mart_band_trend (v1.4); mart_run_band_segments is the
# band chart's run-level scatter (v1.6). Each revision grows the list
# by exactly one name, proven red first.
ANALYTICS_TABLES = (
    "mart_weekly_training",
    "mart_efficiency_trend",
    "mart_efficiency_by_temp_band",
    "mart_run_quality",
    "mart_run_drift",
    "mart_drift_trend",
    "mart_band_trend",
    "mart_run_band_segments",
)

OBSERVATIONAL_NOTE = (
    "Observational signal, not proof: efficiency and drift move with weather, "
    "terrain, sleep, and measurement noise — trends here are never causal claims."
)


def to_dataframe(rows, columns) -> pd.DataFrame:
    """Rows → DataFrame with Postgres numerics coerced to float64.

    psycopg returns `numeric` as Decimal; Streamlit ships DataFrames to
    the browser as Arrow decimal128, which Vega-Lite reads UNSCALED
    (0.7838 charts as 7838). Floats round-trip correctly, and None
    becomes NaN, which tables render as blank instead of "None".
    """
    df = pd.DataFrame(rows, columns=columns)
    for col in df.columns:
        non_null = df[col].dropna()
        if non_null.empty:
            # All-NULL columns (e.g. weather fields with no outdoor runs)
            # stay object dtype and would print the literal "None".
            df[col] = df[col].astype("float64")
        elif isinstance(non_null.iloc[0], Decimal):
            df[col] = df[col].astype("float64")
        elif isinstance(non_null.iloc[0], str):
            # Nullable string dtype renders missing text as blank too.
            df[col] = df[col].astype("string")
    return df


@st.cache_data(ttl=300)
def load(table: str) -> pd.DataFrame:
    if table not in ANALYTICS_TABLES:
        raise ValueError(f"{table} is not an approved analytics relation")
    with get_connection(load_settings()) as conn:
        cursor = conn.execute(f"SELECT * FROM analytics.{table}")  # noqa: S608 — allow-listed
        columns = [description.name for description in cursor.description]
        return to_dataframe(cursor.fetchall(), columns)


def themed(chart: alt.Chart) -> alt.Chart:
    return chart.configure_axis(
        gridColor=GRIDLINE, labelColor=GRAY, titleColor=GRAY, domainColor="#c3c2b7"
    ).configure_view(strokeWidth=0)


def zero_rule() -> alt.Chart:
    return (
        alt.Chart(pd.DataFrame({"y": [0.0]}))
        .mark_rule(color=GRAY, strokeDash=[4, 3])
        .encode(y="y:Q")
    )


def hr_availability_note(runs: pd.DataFrame) -> str:
    # average_hr_bpm presence is what the metrics actually divide by —
    # mart_run_quality has one row per running activity, same as core.
    with_hr = int(runs["average_hr_bpm"].notna().sum()) if not runs.empty else 0
    return (
        f"{with_hr} of {len(runs)} recorded runs carry heart-rate data. "
        "Every efficiency and drift metric requires it (D9/D15): runs synced "
        "from Apple Health arrive without HR, so these views populate once "
        "runs are recorded in a way that sends HR to Strava."
    )


# ── View 1: Aerobic Efficiency ────────────────────────────────────────

EFFICIENCY_TREND_COLUMNS = {
    "week_start_date": st.column_config.DateColumn("Week", format="MMM D"),
    "valid_run_count": st.column_config.NumberColumn("Valid (n)"),
    "median_efficiency_m_per_beat": st.column_config.NumberColumn(
        "Weekly median (m/beat)", format="%.4f"
    ),
    "rolling_median_efficiency": st.column_config.NumberColumn(
        "28-day median (m/beat)", format="%.4f"
    ),
    "rolling_valid_run_count": st.column_config.NumberColumn("28-day (n)"),
    # Intensity context: aggregates no longer filter on effort (v1.1),
    # so the mix behind each weekly point stays visible.
    "avg_hr_bpm": st.column_config.NumberColumn("Avg HR", format="%.0f"),
    "avg_temperature_f": st.column_config.NumberColumn("Avg °F", format="%.1f"),
    "is_sufficient": st.column_config.CheckboxColumn("Sufficient"),
}

RUN_QUALITY_COLUMNS = {
    "activity_id": None,
    "start_date_local": st.column_config.DatetimeColumn("Date", format="MMM D"),
    "week_start_date": None,
    "activity_name": st.column_config.TextColumn("Run"),
    "sport_type": None,
    "is_trainer": None,  # the band column says 'indoor'
    "distance_mi": st.column_config.NumberColumn("Miles", format="%.1f"),
    "moving_time_min": st.column_config.NumberColumn("Min", format="%.1f"),
    "pace_min_per_mi": st.column_config.NumberColumn("Pace (min/mi)", format="%.2f"),
    "average_hr_bpm": st.column_config.NumberColumn("Avg HR", format="%.0f"),
    "aerobic_efficiency_m_per_heartbeat": st.column_config.NumberColumn(
        "Eff (m/beat)", format="%.4f"
    ),
    "is_valid": st.column_config.CheckboxColumn("Valid"),
    "exclusion_reason": st.column_config.TextColumn("Why excluded"),
    "long_run_eligible": None,
    "weather_available": None,  # the band column carries the outcome
    "temperature_f": st.column_config.NumberColumn("°F", format="%.1f"),
    "temperature_band_label": st.column_config.TextColumn("Band"),
    "decoupling_pct": st.column_config.NumberColumn("Decoupling %", format="%.2f"),
    "drift_exclusion_reason": st.column_config.TextColumn("Drift note"),
    "band_exclusion_reason": st.column_config.TextColumn("HR-band note"),
}

# Bands whose total contributing-run count across all weeks falls below
# this start deselected in the band filter — still selectable, just not
# shown by default. Presence-and-count driven, never a band-name list.
DEFAULT_BAND_MIN_TOTAL_RUNS = 3

# v1.6.1: the rolling line is a window-grain statistic, so a vertex
# needs only its own 28-day window to hold this many contributing runs
# (rolling_band_run_count); weekly D12 sufficiency governs the table
# flag, never the line. Weeks under this break the line — no bridging.
ROLLING_LINE_MIN_WINDOW_RUNS = 2

BAND_TREND_COLUMNS = {
    "week_start_date": st.column_config.DateColumn("Week", format="MMM D"),
    "band_key": None,  # the label column already carries it
    "band_label": st.column_config.TextColumn("HR band"),
    "band_sort_order": None,
    "contributing_run_count": st.column_config.NumberColumn("Runs (n)"),
    "median_velocity_m_per_s": None,  # pace is the display unit
    "median_pace_min_per_mi": st.column_config.NumberColumn(
        "Weekly median (min/mi)", format="%.2f"
    ),
    "rolling_median_velocity_m_per_s": None,
    "rolling_median_pace_min_per_mi": st.column_config.NumberColumn(
        "28-day median (min/mi)", format="%.2f"
    ),
    "rolling_band_run_count": st.column_config.NumberColumn("28-day (n)"),
    "avg_temperature_f": st.column_config.NumberColumn("Avg °F", format="%.1f"),
    "is_sufficient": st.column_config.CheckboxColumn("Sufficient"),
}


def band_chart(band_trend, run_segments, selected_bands) -> alt.LayerChart:
    """The pace-at-HR-band chart layers for one band selection.

    Extracted from the view so the exact shipped spec can be rendered
    headlessly (chart.save → PNG): rendering bugs — like nulled rows
    pinning to the reversed axis's top edge — are invisible to schema
    validation and AppTest alike.
    """
    run_selected = run_segments[run_segments["band_label"].isin(selected_bands)]
    # v1.6.1 vertex rule, segment edition: the line data holds PASSING
    # weeks only (window >= threshold) — never null-y rows, which the
    # reversed axis would render pinned to the top edge. Per band, a
    # hole longer than one week — a thin-window week or an absent row
    # alike — starts a new line_segment_id, and the detail channel
    # keeps each segment its own path, so gaps never bridge.
    line_frame = (
        band_trend[
            band_trend["band_label"].isin(selected_bands)
            & (band_trend["rolling_band_run_count"] >= ROLLING_LINE_MIN_WINDOW_RUNS)
        ]
        .sort_values(["band_label", "week_start_date"])
        .copy()
    )
    weeks = pd.to_datetime(line_frame["week_start_date"])
    new_segment = weeks.groupby(line_frame["band_label"]).diff().dt.days.gt(7)
    line_frame["line_segment_id"] = (
        new_segment.groupby(line_frame["band_label"]).cumsum().astype(int)
    )

    # Monday ticks from the scatter's weeks (a superset of the line's
    # weeks); the SAME axis and title go to every layer, or Vega-Lite
    # concatenates the merged axis titles.
    axis = week_axis(run_selected["week_start_date"])
    # reverse=True: pace improves DOWNWARD in min/mi, so the
    # reversed axis makes an improving aerobic base read as
    # an upward trend — the caption states the convention. No fixed
    # domain: the axis fits whatever bands are selected.
    pace_y_scale = alt.Scale(zero=False, nice=True, reverse=True)
    # Ordered low->high HR bands on the ordinal blue ramp, same
    # philosophy as the temperature bands — clamped away from the
    # near-white end so FAINT scatter points in the lowest bands
    # stay visible (the washed-out-ramp lesson, applied to hue).
    band_color = alt.Color(
        "band_label:N",
        sort=alt.EncodingSortField(field="band_sort_order", op="min"),
        scale=alt.Scale(scheme=alt.SchemeParams(name="blues", extent=[0.35, 1])),
        title="HR band",
    )
    # One faint point per run per band (v1.6): the run's median
    # pace in that band, on the run's own date. Weekly medians stay
    # in the table below — on the chart they duplicated these
    # points at current data volume.
    run_points = (
        alt.Chart(run_selected)
        .mark_circle(size=40, opacity=0.5)
        .encode(
            x=alt.X("start_date_local:T", title="training week", axis=axis, scale=TIME_X_SCALE),
            y=alt.Y(
                "median_pace_min_per_mi:Q",
                title="min per mile (up = faster)",
                scale=pace_y_scale,
            ),
            color=band_color,
            tooltip=[
                alt.Tooltip("start_date_local:T", title="run", format="%b %d"),
                alt.Tooltip("band_label:N", title="band"),
                alt.Tooltip("median_pace_min_per_mi:Q", title="run band median", format=".2f"),
                alt.Tooltip("dwell_min:Q", title="minutes in band", format=".1f"),
            ],
        )
    )
    line_tooltip = [
        alt.Tooltip("week_start_date:T", title="week", format="%b %d"),
        alt.Tooltip("band_label:N", title="band"),
        alt.Tooltip("rolling_median_pace_min_per_mi:Q", title="28-day median", format=".2f"),
        alt.Tooltip("rolling_band_run_count:Q", title="runs in window (n)"),
        alt.Tooltip("median_pace_min_per_mi:Q", title="weekly median", format=".2f"),
        alt.Tooltip("contributing_run_count:Q", title="runs this week (n)"),
    ]
    band_lines = (
        alt.Chart(line_frame)
        .mark_line(strokeWidth=2)
        .encode(
            x=alt.X("week_start_date:T", title="training week", axis=axis, scale=TIME_X_SCALE),
            y=alt.Y(
                "rolling_median_pace_min_per_mi:Q",
                title="min per mile (up = faster)",
                scale=pace_y_scale,
            ),
            color=band_color,
            detail=alt.Detail("line_segment_id:N"),
            tooltip=line_tooltip,
        )
    )
    band_vertices = (
        alt.Chart(line_frame.dropna(subset=["rolling_median_pace_min_per_mi"]))
        .mark_circle(size=36)
        .encode(
            x=alt.X("week_start_date:T", title="training week", axis=axis, scale=TIME_X_SCALE),
            y=alt.Y(
                "rolling_median_pace_min_per_mi:Q",
                title="min per mile (up = faster)",
                scale=pace_y_scale,
            ),
            color=band_color,
            tooltip=line_tooltip,
        )
    )
    return alt.layer(run_points, band_lines, band_vertices).properties(height=320)


def efficiency_view():
    st.header("Aerobic efficiency")
    st.caption(
        "aerobic_efficiency_m_per_heartbeat = speed (m/min) ÷ average HR (bpm) — "
        "approximate meters per heartbeat across runs with valid heart-rate data "
        "(D9 validity rules, median weekly, 28-day rolling median). Intensity mix "
        "is not controlled for — avg HR is shown for context. " + OBSERVATIONAL_NOTE
    )

    trend = load("mart_efficiency_trend")
    # astype(bool): psycopg hands back object dtype on empty frames, and
    # a non-bool mask would select columns instead of rows.
    sufficient = trend[trend["is_sufficient"].astype(bool)].copy()

    if sufficient["median_efficiency_m_per_beat"].dropna().empty:
        st.info(
            "No trend to display yet: no week has the required "
            "2 runs with valid HR data. " + hr_availability_note(load("mart_run_quality"))
        )
    else:
        axis = week_axis(sufficient["week_start_date"])
        # zero=False: values live around 0.7–0.8, and a zero-anchored
        # axis would flatten the trend into the top sliver of the plot.
        y_scale = alt.Scale(zero=False, nice=True)
        weekly = (
            alt.Chart(sufficient)
            .mark_circle(size=64, color=GRAY)
            .encode(
                x=alt.X("week_start_date:T", title="training week", axis=axis, scale=TIME_X_SCALE),
                y=alt.Y("median_efficiency_m_per_beat:Q", title="m per heartbeat", scale=y_scale),
                tooltip=[
                    alt.Tooltip("week_start_date:T", title="week", format="%b %d"),
                    alt.Tooltip(
                        "median_efficiency_m_per_beat:Q", title="weekly median", format=".4f"
                    ),
                    alt.Tooltip("valid_run_count:Q", title="valid runs (n)"),
                    alt.Tooltip("avg_hr_bpm:Q", title="avg HR (bpm)", format=".0f"),
                    alt.Tooltip("avg_temperature_f:Q", title="avg temp (°F)", format=".1f"),
                ],
            )
            .properties(height=320)
        )
        rolling = (
            alt.Chart(sufficient.dropna(subset=["rolling_median_efficiency"]))
            .mark_line(color=BLUE, strokeWidth=2, point=alt.OverlayMarkDef(color=BLUE, size=36))
            .encode(
                x=alt.X("week_start_date:T", axis=axis, scale=TIME_X_SCALE),
                y=alt.Y("rolling_median_efficiency:Q", scale=y_scale),
                tooltip=[
                    alt.Tooltip("week_start_date:T", title="week", format="%b %d"),
                    alt.Tooltip("rolling_median_efficiency:Q", title="28-day median", format=".4f"),
                    alt.Tooltip("rolling_valid_run_count:Q", title="runs in window (n)"),
                ],
            )
        )
        st.altair_chart(themed(alt.layer(weekly, rolling)), use_container_width=True)
        st.caption(
            "Blue line: 28-day rolling median (the primary trend). Gray points: "
            "single-week medians. Weeks below the 2-valid-run sufficiency "
            "threshold are excluded from this chart and flagged in the table."
        )

    st.subheader("Efficiency by temperature band")
    bands = load("mart_efficiency_by_temp_band")
    if bands["valid_run_count"].sum() == 0:
        st.info("All temperature bands are empty until runs with valid HR data exist.")
    else:
        bands = bands.copy()
        bands["n_label"] = "n=" + bands["valid_run_count"].astype(int).astype(str)
        bands["label_x"] = bands["median_efficiency_m_per_beat"].fillna(0)
        # EncodingSortField (with op), not SortField: a bare SortField is
        # invalid for ordering an axis by another column in a layered
        # chart, and Vega-Lite silently falls back to alphabetical.
        band_y = alt.Y(
            "band_label:N",
            sort=alt.EncodingSortField(field="sort_order", op="min", order="ascending"),
            title=None,
            axis=alt.Axis(labelLimit=200),
        )
        bars = (
            alt.Chart(bands)
            .mark_bar(cornerRadiusTopRight=4, cornerRadiusBottomRight=4, height=26)
            .encode(
                y=band_y,
                x=alt.X("median_efficiency_m_per_beat:Q", title="median m/beat"),
                color=alt.Color(
                    "band_key:N",
                    scale=alt.Scale(domain=list(ORDINAL_RAMP), range=list(ORDINAL_RAMP.values())),
                    legend=None,  # ordered bands are named on the axis
                ),
                tooltip=[
                    alt.Tooltip("band_label:N", title="band"),
                    alt.Tooltip("median_efficiency_m_per_beat:Q", title="median", format=".4f"),
                    alt.Tooltip("mean_efficiency_m_per_beat:Q", title="mean", format=".4f"),
                    alt.Tooltip("valid_run_count:Q", title="runs (n)"),
                    alt.Tooltip("avg_hr_bpm:Q", title="avg HR (bpm)", format=".0f"),
                ],
            )
        )
        labels = (
            alt.Chart(bands)
            .mark_text(align="left", dx=6, color=INK_SECONDARY)
            .encode(y=band_y, x=alt.X("label_x:Q"), text="n_label:N")
        )
        st.altair_chart(
            themed(alt.layer(bars, labels).properties(height=190)), use_container_width=True
        )
        st.caption(
            "Median of per-run efficiency across runs with valid HR data in "
            "each band — runs are banded individually by their own matched "
            "temperature, never averaged by week."
        )

    st.subheader("Pace at heart-rate band")
    st.caption(
        "Pace at the same 10-bpm heart-rate band, one point per run per "
        "band: stream samples pooled after a 5-minute warm-up and 2-minute "
        "cool-down trim, a run counts in a band only with ≥ 5 minutes "
        "there, each point = that run's median pace in the band (D11 "
        "medians end to end), 28-day rolling median on top. "
        "RISING pace — falling min/mi — at the same band is the observational "
        "signal of an improving aerobic base (D22)."
    )
    band_trend = load("mart_band_trend")
    run_segments = load("mart_run_band_segments")
    # Empty-state on the PRE-filter frame: the weekly marts aggregate
    # these rows, so run rows exist iff weekly rows exist — and keying
    # on the post-filter frame would show this backfill message when
    # the user merely deselects every band.
    if run_segments.empty:
        st.info(
            "No band data yet: no run has an HR band with the required "
            "5 minutes of dwell. Runs of 20–45 minutes gain streams as the "
            "post-v1.4 backfill drains, so this section fills in after "
            "`make sync-streams` catches up."
        )
    else:
        # Band filter: every band present in the data, low->high HR.
        # Sparse bands start deselected so the y-axis fits the bands
        # that carry the trend; nothing is hidden for good — any band
        # can be re-selected. Options and defaults come from the weekly
        # frame, whose contributing_run_count totals the runs per band.
        band_order = band_trend.sort_values("band_sort_order")["band_label"].unique().tolist()
        band_totals = band_trend.groupby("band_label")["contributing_run_count"].sum()
        default_bands = [
            label for label in band_order if band_totals[label] >= DEFAULT_BAND_MIN_TOTAL_RUNS
        ] or band_order  # every band sparse: show all rather than a blank chart
        selected_bands = st.multiselect("HR bands", options=band_order, default=default_bands)
        st.altair_chart(
            themed(band_chart(band_trend, run_segments, selected_bands)),
            use_container_width=True,
        )
        st.caption(
            "One faint point per run per HR band — that run's median pace "
            "in the band. One line per band: the 28-day rolling median "
            "across those run medians, with a vertex wherever the 28-day "
            f"window holds at least {ROLLING_LINE_MIN_WINDOW_RUNS} runs; "
            "a gap means the window was too thin. Weekly sufficiency is a "
            "table flag, not a line rule (v1.6.1)."
        )
    st.dataframe(
        band_trend.sort_values(["week_start_date", "band_sort_order"]),
        use_container_width=True,
        hide_index=True,
        column_config=BAND_TREND_COLUMNS,
    )
    st.caption("All week × band rows, including insufficient ones — nothing dropped, only flagged.")

    st.subheader("Every run, with its verdict")
    quality = load("mart_run_quality").sort_values("start_date_local", ascending=False)
    st.dataframe(
        quality, use_container_width=True, hide_index=True, column_config=RUN_QUALITY_COLUMNS
    )
    st.caption(
        "Efficiency is computed for every heart-rate-carrying run; the trend "
        "and band charts aggregate every run with VALID heart-rate data (D9 "
        "validity rules: HR present, 90–200 bpm, pace 4:00–20:00 min/mi, "
        "≥ 15 min moving). Intensity is displayed, never filtered — the Avg HR "
        "column shows the effort mix behind each aggregate."
    )

    st.dataframe(
        trend, use_container_width=True, hide_index=True, column_config=EFFICIENCY_TREND_COLUMNS
    )
    st.caption("All weeks, including insufficient ones — nothing is dropped, only flagged.")


# ── View 2: Weekly Training ───────────────────────────────────────────

WEEKLY_COLUMNS = {
    "week_start_date": st.column_config.DateColumn("Week", format="MMM D"),
    "run_count": st.column_config.NumberColumn("Runs"),
    "valid_run_count": st.column_config.NumberColumn("Valid (n)"),
    "long_run_count": st.column_config.NumberColumn("Long runs"),
    "total_distance_mi": st.column_config.NumberColumn("Miles", format="%.1f"),
    "total_moving_time_min": st.column_config.NumberColumn("Moving (min)", format="%.0f"),
    "total_elevation_gain_m": st.column_config.NumberColumn("Elev gain (m)", format="%.0f"),
    "median_efficiency_m_per_beat": st.column_config.NumberColumn(
        "Median eff (m/beat)", format="%.4f"
    ),
    "mean_efficiency_m_per_beat": st.column_config.NumberColumn("Mean eff (m/beat)", format="%.4f"),
    "avg_hr_bpm": st.column_config.NumberColumn("Avg HR", format="%.0f"),
    "avg_temperature_f": st.column_config.NumberColumn("Avg °F", format="%.1f"),
    "avg_relative_humidity_pct": st.column_config.NumberColumn("Avg RH %", format="%.0f"),
    "valid_runs_with_weather": st.column_config.NumberColumn("Valid w/ weather (n)"),
    "is_sufficient": st.column_config.CheckboxColumn("Sufficient"),
}


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
    col4.metric("Runs with valid HR", int(weekly["valid_run_count"].sum()))

    mileage = (
        alt.Chart(weekly)
        .mark_bar(size=24, color=BLUE, cornerRadiusTopLeft=4, cornerRadiusTopRight=4)
        .encode(
            x=alt.X(
                "week_start_date:T",
                title="training week",
                axis=week_axis(weekly["week_start_date"]),
                scale=TIME_X_SCALE,
            ),
            y=alt.Y("total_distance_mi:Q", title="miles"),
            tooltip=[
                alt.Tooltip("week_start_date:T", title="week", format="%b %d"),
                alt.Tooltip("total_distance_mi:Q", title="miles", format=".1f"),
                alt.Tooltip("total_moving_time_min:Q", title="moving min", format=".0f"),
                alt.Tooltip("run_count:Q", title="runs (n)"),
            ],
        )
        .properties(height=300)
    )
    st.altair_chart(themed(mileage), use_container_width=True)

    st.dataframe(weekly, use_container_width=True, hide_index=True, column_config=WEEKLY_COLUMNS)
    st.caption(
        "Volume counts every run; efficiency columns aggregate runs with valid "
        "HR data only and stay empty (never zero) for weeks without them."
    )


# ── View 3: Cardiac Drift ─────────────────────────────────────────────

DRIFT_TREND_COLUMNS = {
    "week_start_date": st.column_config.DateColumn("Week", format="MMM D"),
    "drift_run_count": st.column_config.NumberColumn("Drift runs (n)"),
    "median_decoupling_pct": st.column_config.NumberColumn("Median decoupling %", format="%.2f"),
    "rolling_median_decoupling_pct": st.column_config.NumberColumn(
        "28-day median %", format="%.2f"
    ),
    "rolling_drift_run_count": st.column_config.NumberColumn("28-day (n)"),
    "avg_moving_time_min": st.column_config.NumberColumn("Avg moving (min)", format="%.1f"),
    "avg_temperature_f": st.column_config.NumberColumn("Avg °F", format="%.1f"),
    "runs_with_weather": st.column_config.NumberColumn("With weather (n)"),
    "is_sufficient": st.column_config.CheckboxColumn("Sufficient"),
}


def drift_view():
    st.header("Cardiac drift")
    st.caption(
        "Decoupling % compares efficiency between equal halves of long runs — "
        "≥ 45 min moving with HR (D15), first 10 min and last 5 min trimmed. "
        "Sign convention (D17): positive = "
        "efficiency declined in the second half; near zero = stable; negative = "
        "second half improved. " + OBSERVATIONAL_NOTE
    )

    runs = load("mart_run_drift")
    if runs.empty:
        st.info(
            "No analyzed drift runs yet. Drift needs runs ≥45 minutes with "
            "heart-rate streams (D15). " + hr_availability_note(load("mart_run_quality"))
        )
        return

    points = (
        alt.Chart(runs)
        .mark_circle(size=80, color=BLUE)
        .encode(
            x=alt.X("start_date_local:T", title="run date", axis=DAY_AXIS, scale=TIME_X_SCALE),
            y=alt.Y("decoupling_pct:Q", title="decoupling %"),
            tooltip=[
                alt.Tooltip("start_date_local:T", title="run", format="%b %d"),
                alt.Tooltip("decoupling_pct:Q", title="decoupling %", format=".2f"),
                alt.Tooltip("analysis_window_min:Q", title="window (min)", format=".1f"),
                alt.Tooltip("valid_sample_count:Q", title="valid samples (n)"),
                alt.Tooltip("temperature_f:Q", title="°F", format=".1f"),
            ],
        )
        .properties(height=320)
    )
    st.altair_chart(themed(alt.layer(zero_rule(), points)), use_container_width=True)

    trend = load("mart_drift_trend")
    sufficient = trend[trend["is_sufficient"].astype(bool)]
    if sufficient.empty:
        st.info(
            "Weekly drift trend hidden: no week reaches the 2-run sufficiency "
            "threshold yet (weeks and counts below)."
        )
    else:
        rolling = (
            alt.Chart(sufficient.dropna(subset=["rolling_median_decoupling_pct"]))
            .mark_line(color=BLUE, strokeWidth=2, point=alt.OverlayMarkDef(color=BLUE, size=36))
            .encode(
                x=alt.X(
                    "week_start_date:T",
                    title="training week",
                    axis=week_axis(sufficient["week_start_date"]),
                    scale=TIME_X_SCALE,
                ),
                y=alt.Y("rolling_median_decoupling_pct:Q", title="28-day median decoupling %"),
                tooltip=[
                    alt.Tooltip("week_start_date:T", title="week", format="%b %d"),
                    alt.Tooltip(
                        "rolling_median_decoupling_pct:Q", title="28-day median", format=".2f"
                    ),
                    alt.Tooltip("rolling_drift_run_count:Q", title="runs in window (n)"),
                ],
            )
            .properties(height=280)
        )
        st.altair_chart(themed(alt.layer(zero_rule(), rolling)), use_container_width=True)
        if len(sufficient) < 2:
            st.caption(
                "One sufficient week so far — the rolling median draws a line "
                "segment once a second sufficient week exists."
            )

    st.dataframe(
        trend, use_container_width=True, hide_index=True, column_config=DRIFT_TREND_COLUMNS
    )
    st.caption("All drift weeks with sample counts; insufficient weeks are flagged, not deleted.")


# ── Shell ─────────────────────────────────────────────────────────────


def main():
    st.set_page_config(page_title="Running Analytics", layout="wide")
    st.sidebar.title("Running analytics")
    views = {
        "Aerobic efficiency": efficiency_view,
        "Weekly training": weekly_view,
        "Cardiac drift": drift_view,
    }
    choice = st.sidebar.radio("View", list(views))
    st.sidebar.caption(
        "Reads analytics marts only — every metric is defined, tested, and "
        "documented in dbt (see README for definitions)."
    )
    views[choice]()


if __name__ == "__main__":
    main()
