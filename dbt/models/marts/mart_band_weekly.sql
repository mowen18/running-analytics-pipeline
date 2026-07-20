{#
  D22 weekly rollup at week x HR-band grain. The weekly statistic is
  the MEDIAN ACROSS CONTRIBUTING RUNS of the run-level band medians
  (D11's median-of-runs philosophy: one long run must not dominate a
  week by sample count). Sufficiency reuses the D12 var against the
  contributing-run count, exactly as the other weekly marts do.
  Temperature is context only (dry-bulb, like everywhere else).

  This mart is deliberately NOT on the app's allow-list: the weekly
  columns travel inside mart_band_trend, per the existing trend-mart
  interface.
#}

with segments as (

    select * from {{ ref('fct_run_band_segments') }}

),

context as (

    select activity_id, temperature_f
    from {{ ref('fct_runs') }}

),

weekly as (

    select
        segments.week_start_date,
        segments.band_key,
        count(*) as contributing_run_count,
        percentile_cont(0.5) within group (order by segments.median_velocity_m_per_s)
            as median_velocity_m_per_s,
        avg(context.temperature_f) as avg_temperature_f
    from segments
    left join context using (activity_id)
    group by segments.week_start_date, segments.band_key

)

select
    weekly.week_start_date,
    bands.band_key,
    bands.band_label,
    bands.sort_order as band_sort_order,
    weekly.contributing_run_count,
    round(weekly.median_velocity_m_per_s::numeric, 3) as median_velocity_m_per_s,
    round(
        (1609.344 / nullif(weekly.median_velocity_m_per_s * 60.0, 0))::numeric, 2
    )                                                 as median_pace_min_per_mi,
    round(weekly.avg_temperature_f::numeric, 1)       as avg_temperature_f,
    -- D12 reused at week x band grain. The flag gates presentation
    -- downstream (how is the dashboard's business); the rows stay
    -- present so nothing is silently dropped from the warehouse.
    weekly.contributing_run_count >= {{ var('min_weekly_valid_runs') }} as is_sufficient
from weekly
inner join {{ ref('hr_bands') }} bands using (band_key)
