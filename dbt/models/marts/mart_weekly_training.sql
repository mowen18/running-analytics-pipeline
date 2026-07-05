with runs as (

    select * from {{ ref('int_run_efficiency') }}

),

weekly as (

    select
        week_start_date,
        count(*)                                          as run_count,
        count(*) filter (where is_valid)                  as valid_run_count,
        count(*) filter (where long_run_eligible)         as long_run_count,
        round(sum(distance_mi), 1)                        as total_distance_mi,
        round(sum(moving_time_min), 0)                    as total_moving_time_min,
        round(sum(elevation_gain_m), 0)                   as total_elevation_gain_m,
        -- Median is the primary weekly statistic (D11); mean is shown
        -- as secondary only. Both aggregate VALID runs only, and both
        -- are NULL — never zero — when no run is valid.
        percentile_cont(0.5) within group (
            order by aerobic_efficiency_m_per_heartbeat
        ) filter (where is_valid)                         as median_efficiency_m_per_beat,
        avg(aerobic_efficiency_m_per_heartbeat)
            filter (where is_valid)                       as mean_efficiency_m_per_beat,
        -- Intensity context: the aggregates no longer filter on effort
        -- (v1.1), so the mix behind each week stays visible.
        avg(average_hr_bpm) filter (where is_valid)       as avg_hr_bpm,
        avg(temperature_f) filter (where is_valid and weather_available)
                                                          as avg_temperature_f,
        avg(relative_humidity_pct) filter (where is_valid and weather_available)
                                                          as avg_relative_humidity_pct,
        count(*) filter (where is_valid and weather_available)
                                                          as valid_runs_with_weather
    from runs
    group by week_start_date

)

select
    week_start_date,
    run_count,
    valid_run_count,
    long_run_count,
    total_distance_mi,
    total_moving_time_min,
    total_elevation_gain_m,
    round(median_efficiency_m_per_beat::numeric, 4) as median_efficiency_m_per_beat,
    round(mean_efficiency_m_per_beat::numeric, 4)   as mean_efficiency_m_per_beat,
    round(avg_hr_bpm::numeric, 0)                   as avg_hr_bpm,
    round(avg_temperature_f::numeric, 1)            as avg_temperature_f,
    round(avg_relative_humidity_pct::numeric, 0)    as avg_relative_humidity_pct,
    valid_runs_with_weather,
    -- D12: a weekly efficiency point is only trend-worthy with at least
    -- min_weekly_valid_runs runs with valid HR data behind it.
    valid_run_count >= {{ var('min_weekly_valid_runs') }} as is_sufficient
from weekly
