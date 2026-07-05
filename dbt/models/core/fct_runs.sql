with runs as (

    select * from {{ ref('int_runs_with_weather') }}

),

derived as (

    select
        *,
        round(distance_m / 1609.344, 2) as distance_mi,
        round(moving_time_s / 60.0, 1)  as moving_time_min,
        -- Every division is guarded: a zero denominator yields NULL,
        -- never an error and never a fake zero.
        case
            when distance_m > 0 and moving_time_s > 0
                then round((moving_time_s / 60.0) / (distance_m / 1609.344), 2)
        end                             as pace_min_per_mi,
        case
            when moving_time_s > 0
                then round(distance_m / (moving_time_s / 60.0), 1)
        end                             as speed_m_per_min,
        case
            when distance_m > 0
                then round(elevation_gain_m / (distance_m / 1609.344), 1)
        end                             as elevation_gain_m_per_mi,
        -- Training calendar is local wall-clock: a 9 PM Tuesday run
        -- belongs to Tuesday even when it is Wednesday in UTC.
        date_trunc('week', start_date_local)::date as week_start_date,
        extract(month from start_date_local)::integer as start_month,
        extract(year from start_date_local)::integer  as start_year
    from runs

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
    pace_min_per_mi,
    speed_m_per_min,
    elevation_gain_m,
    elevation_gain_m_per_mi,
    has_heartrate,
    average_hr_bpm,
    max_hr_bpm,
    is_trainer,
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
    -- Easy-run eligibility per D9, thresholds via vars (never inline).
    (
        has_heartrate
        and average_hr_bpm is not null
        and average_hr_bpm <= {{ var('easy_hr_max') }}
        and average_hr_bpm between {{ var('hr_sanity_floor') }} and {{ var('hr_sanity_ceiling') }}
        and moving_time_min >= {{ var('easy_min_moving_minutes') }}
        and coalesce(workout_type, 0) not in (1, 3)  -- 1 = race, 3 = workout
        and pace_min_per_mi between {{ var('easy_pace_min_per_mi_floor') }}
            and {{ var('easy_pace_min_per_mi_ceiling') }}
    )                       as easy_run_eligible,
    moving_time_min >= {{ var('long_run_min_moving_minutes') }} as long_run_eligible,
    fetched_at
from derived
