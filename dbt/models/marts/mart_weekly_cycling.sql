{#
  Weekly cycling training summary (v2.0 Phase C1): one row per training
  week with volume over ALL D23 rides and statistics over VALID rides
  (D25). Median speed is primary, mean secondary (the D11 discipline);
  each conditional statistic publishes its own sample count, and every
  statistic is NULL — never zero — when no ride qualifies for it.
#}

with rides as (

    select * from {{ ref('fct_rides') }}

),

weekly as (

    select
        week_start_date,
        count(*)                                          as ride_count,
        count(*) filter (where is_valid)                  as valid_ride_count,
        round(sum(distance_mi), 1)                        as total_distance_mi,
        round(sum(moving_time_min), 0)                    as total_moving_time_min,
        round(sum(elevation_gain_m), 0)                   as total_elevation_gain_m,
        percentile_cont(0.5) within group (
            order by avg_speed_mph
        ) filter (where is_valid)                         as median_speed_mph,
        avg(avg_speed_mph) filter (where is_valid)        as mean_speed_mph,
        -- HR and cadence average only the valid rides that carry them
        -- (D25: HR gates HR aggregates, never the grain; D26: missing
        -- cadence stays NULL), with the sample size published beside.
        avg(average_hr_bpm) filter (where is_valid and average_hr_bpm is not null)
                                                          as avg_hr_bpm,
        count(*) filter (where is_valid and average_hr_bpm is not null)
                                                          as valid_rides_with_hr,
        avg(average_cadence_rpm) filter (where is_valid and average_cadence_rpm is not null)
                                                          as avg_cadence_rpm,
        count(*) filter (where is_valid and average_cadence_rpm is not null)
                                                          as rides_with_cadence,
        avg(temperature_f) filter (where is_valid and weather_available)
                                                          as avg_temperature_f,
        avg(relative_humidity_pct) filter (where is_valid and weather_available)
                                                          as avg_relative_humidity_pct,
        count(*) filter (where is_valid and weather_available)
                                                          as valid_rides_with_weather
    from rides
    group by week_start_date

)

select
    week_start_date,
    ride_count,
    valid_ride_count,
    total_distance_mi,
    total_moving_time_min,
    total_elevation_gain_m,
    round(median_speed_mph::numeric, 1)             as median_speed_mph,
    round(mean_speed_mph::numeric, 1)               as mean_speed_mph,
    round(avg_hr_bpm::numeric, 0)                   as avg_hr_bpm,
    valid_rides_with_hr,
    round(avg_cadence_rpm::numeric, 0)              as avg_cadence_rpm,
    rides_with_cadence,
    round(avg_temperature_f::numeric, 1)            as avg_temperature_f,
    round(avg_relative_humidity_pct::numeric, 0)    as avg_relative_humidity_pct,
    valid_rides_with_weather,
    -- D12 spirit: a weekly cycling point is only trend-worthy with at
    -- least min_weekly_valid_rides valid rides behind it.
    valid_ride_count >= {{ var('min_weekly_valid_rides') }} as is_sufficient
from weekly
