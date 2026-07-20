{#
  D22 run x band grain for the dashboard (v1.6) — one row per analyzed
  run per HR band: the run's band median, its date and training week,
  and its minutes of dwell. An explicit-column projection of core
  fct_run_band_segments joined to the hr_bands seed for display columns
  (the mart_run_drift pattern, at run x band grain). No filters here:
  core already applies the analyzed-only and dwell-minimum rules.

  median_velocity_m_per_s rides along for the v1.6 consistency
  contract — assert_band_weekly_matches_segment_mart pins
  mart_band_weekly's weekly median to these rows in velocity space —
  while pace stays the display unit, as everywhere else.
#}

with segments as (

    select * from {{ ref('fct_run_band_segments') }}

),

bands as (

    select
        band_key,
        band_label,
        sort_order
    from {{ ref('hr_bands') }}

)

select
    segments.activity_id,
    segments.start_date_local,
    segments.week_start_date,
    segments.band_key,
    bands.band_label,
    bands.sort_order as band_sort_order,
    segments.median_velocity_m_per_s,
    segments.median_pace_min_per_mi,
    round(segments.dwell_s / 60.0, 1) as dwell_min
from segments
inner join bands using (band_key)
