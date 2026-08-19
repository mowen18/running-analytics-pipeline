with rides as (

    select * from {{ ref('int_rides_with_weather') }}

),

derived as (

    select
        *,
        round(distance_m / 1609.344, 2) as distance_mi,
        round(moving_time_s / 60.0, 1)  as moving_time_min,
        -- Re-derived from distance and moving time (the running
        -- re-derivation pattern), never the payload's average_speed.
        -- Every division is guarded: a zero denominator yields NULL,
        -- never an error and never a fake zero.
        case
            when distance_m > 0 and moving_time_s > 0
                then round((distance_m / 1609.344) / (moving_time_s / 3600.0), 1)
        end                             as avg_speed_mph,
        -- Training calendar is local wall-clock: a 9 PM Tuesday ride
        -- belongs to Tuesday even when it is Wednesday in UTC.
        date_trunc('week', start_date_local)::date as week_start_date,
        extract(month from start_date_local)::integer as start_month,
        extract(year from start_date_local)::integer  as start_year
    from rides

),

classified as (

    select
        *,
        -- Ride validity per D25 is encoded ONCE, as this ladder;
        -- is_valid is definitionally (exclusion_reason is null). First
        -- failing rule, priority sanity -> derived-metric bounds ->
        -- duration. HR ABSENCE is deliberately not a rung (D25: HR is
        -- required only for HR-based aggregates, never for the grain);
        -- the sanity band applies only when HR is present, and reuses
        -- the running hr_sanity vars — one mechanism, two consumers.
        case
            when average_hr_bpm is not null
                and average_hr_bpm not between {{ var('hr_sanity_floor') }}
                    and {{ var('hr_sanity_ceiling') }}
                then 'average HR outside {{ var("hr_sanity_floor") }}–{{ var("hr_sanity_ceiling") }} bpm sanity band'
            when avg_speed_mph is null
                or avg_speed_mph not between {{ var('ride_speed_mph_floor') }}
                    and {{ var('ride_speed_mph_ceiling') }}
                then 'average speed outside {{ var("ride_speed_mph_floor") }}–{{ var("ride_speed_mph_ceiling") }} mph bounds'
            when moving_time_min < {{ var('valid_ride_min_moving_minutes') }}
                then 'moving time under {{ var("valid_ride_min_moving_minutes") }} minutes'
        end as exclusion_reason
    from derived

)

select
    activity_id,
    activity_name,
    sport_type,
    workout_type,
    start_date_utc,
    start_date_local,
    week_start_date,
    start_month,
    start_year,
    distance_m,
    distance_mi,
    moving_time_s,
    moving_time_min,
    elapsed_time_s,
    avg_speed_mph,
    elevation_gain_m,
    has_heartrate,
    average_hr_bpm,
    max_hr_bpm,
    average_cadence_rpm,
    is_trainer,
    is_indoor,
    location_key,
    temperature_c,
    temperature_f,
    apparent_temperature_c,
    apparent_temperature_f,
    relative_humidity_pct,
    wind_speed_kph,
    wind_speed_mph,
    weather_match_minutes,
    weather_matched as weather_available,
    fetched_at,
    (exclusion_reason is null) as is_valid,
    exclusion_reason
from classified
