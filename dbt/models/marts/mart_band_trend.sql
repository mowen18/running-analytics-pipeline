{#
  D22 trend at week x HR-band grain — the mart the dashboard reads.
  Weekly columns ride in from mart_band_weekly (the sanctioned one-hop
  mart-to-mart edge); the rolling median is computed per band over the
  RUN-LEVEL band medians from fct_run_band_segments across the
  trend_window_days ending with each week's Sunday — the same explicit
  join-window pattern as mart_efficiency_trend (percentile_cont is not
  a window function, and the window arithmetic stays visible).

  Static column names per v1.3: trend_window_days changes the window,
  never the interface. Sign of interest (stated on the view and in
  marts.yml): RISING pace — falling min/mi — at the same band is the
  observational signal of an improving aerobic base; never causal.
#}

with weekly as (

    select * from {{ ref('mart_band_weekly') }}

),

run_medians as (

    select
        start_date_local::date as run_date,
        band_key,
        median_velocity_m_per_s
    from {{ ref('fct_run_band_segments') }}

),

rolling as (

    select
        weekly.week_start_date,
        weekly.band_key,
        percentile_cont(0.5) within group (order by run_medians.median_velocity_m_per_s)
                 as rolling_median_velocity_m_per_s,
        count(*) as rolling_band_run_count
    from weekly
    inner join run_medians
        on run_medians.band_key = weekly.band_key
        and run_medians.run_date
            > weekly.week_start_date + 6 - {{ var('trend_window_days') }}
        and run_medians.run_date <= weekly.week_start_date + 6
    group by weekly.week_start_date, weekly.band_key

)

select
    weekly.week_start_date,
    weekly.band_key,
    weekly.band_label,
    weekly.band_sort_order,
    weekly.contributing_run_count,
    weekly.median_velocity_m_per_s,
    weekly.median_pace_min_per_mi,
    round(rolling.rolling_median_velocity_m_per_s::numeric, 3)
        as rolling_median_velocity_m_per_s,
    round(
        (1609.344 / nullif(rolling.rolling_median_velocity_m_per_s * 60.0, 0))::numeric,
        2
    )   as rolling_median_pace_min_per_mi,
    coalesce(rolling.rolling_band_run_count, 0)
        as rolling_band_run_count,
    weekly.avg_temperature_f,
    weekly.is_sufficient
from weekly
left join rolling using (week_start_date, band_key)
