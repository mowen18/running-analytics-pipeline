with drift_runs as (

    select * from {{ ref('mart_run_drift') }}

),

weekly as (

    select
        week_start_date,
        count(*)                                     as drift_run_count,
        percentile_cont(0.5) within group (order by decoupling_pct)
                                                     as median_decoupling_pct,
        avg(moving_time_min)                         as avg_moving_time_min,
        avg(temperature_f)                           as avg_temperature_f,
        count(*) filter (where weather_available)    as runs_with_weather
    from drift_runs
    group by week_start_date

),

rolling as (

    -- Same explicit join-window pattern as mart_efficiency_trend:
    -- median decoupling across the trend_window_days ending with each
    -- week's Sunday.
    select
        weekly.week_start_date,
        percentile_cont(0.5) within group (order by drift_runs.decoupling_pct)
                 as rolling_median_decoupling_pct,
        count(*) as rolling_drift_run_count
    from weekly
    inner join drift_runs
        on drift_runs.start_date_local::date
            > weekly.week_start_date + 6 - {{ var('trend_window_days') }}
        and drift_runs.start_date_local::date <= weekly.week_start_date + 6
    group by weekly.week_start_date

)

select
    weekly.week_start_date,
    weekly.drift_run_count,
    round(weekly.median_decoupling_pct::numeric, 2)          as median_decoupling_pct,
    round(rolling.rolling_median_decoupling_pct::numeric, 2)
        as rolling_median_decoupling_pct,
    coalesce(rolling.rolling_drift_run_count, 0)
        as rolling_drift_run_count,
    round(weekly.avg_moving_time_min::numeric, 1)            as avg_moving_time_min,
    round(weekly.avg_temperature_f::numeric, 1)              as avg_temperature_f,
    weekly.runs_with_weather,
    -- Acceptance criterion 7: the dashboard HIDES trend points where
    -- this is false — the rows stay present here so nothing is
    -- silently dropped from the warehouse.
    weekly.drift_run_count >= {{ var('min_weekly_valid_runs') }} as is_sufficient
from weekly
left join rolling using (week_start_date)
