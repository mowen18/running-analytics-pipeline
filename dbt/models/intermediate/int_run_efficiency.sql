with runs as (

    select * from {{ ref('fct_runs') }}

),

classified as (

    select
        *,
        -- Aerobic efficiency per D10: meters per heartbeat. Computed for
        -- ANY run with HR and speed (a race has a real efficiency value);
        -- is_qualifying decides what the marts aggregate. Guarded: NULL
        -- when HR or speed is missing/zero, never an error or a zero.
        case
            when average_hr_bpm > 0 and speed_m_per_min is not null
                then round(speed_m_per_min / average_hr_bpm, 4)
        end as aerobic_efficiency_m_per_heartbeat,
        -- First failing D9 rule in documented priority order; NULL means
        -- eligible. Priority runs data-availability -> sanity -> effort
        -- -> duration -> intent -> pace, so the most fundamental problem
        -- is the one reported.
        case
            when not has_heartrate or average_hr_bpm is null
                then 'no heart rate data'
            when average_hr_bpm not between {{ var('hr_sanity_floor') }}
                and {{ var('hr_sanity_ceiling') }}
                then 'average HR outside {{ var("hr_sanity_floor") }}–{{ var("hr_sanity_ceiling") }} bpm sanity band'
            when average_hr_bpm > {{ var('easy_hr_max') }}
                then 'average HR above easy maximum ({{ var("easy_hr_max") }} bpm)'
            when moving_time_min < {{ var('easy_min_moving_minutes') }}
                then 'moving time under {{ var("easy_min_moving_minutes") }} minutes'
            when workout_type = 1
                then 'tagged as race'
            when workout_type = 3
                then 'tagged as workout'
            when pace_min_per_mi is null
                or pace_min_per_mi not between {{ var('easy_pace_min_per_mi_floor') }}
                    and {{ var('easy_pace_min_per_mi_ceiling') }}
                then 'pace outside {{ var("easy_pace_min_per_mi_floor") }}–{{ var("easy_pace_min_per_mi_ceiling") }} min/mi bounds'
        end as exclusion_reason
    from runs

)

select
    activity_id,
    activity_name,
    sport_type,
    start_date_utc,
    start_date_local,
    week_start_date,
    start_month,
    start_year,
    distance_mi,
    moving_time_min,
    pace_min_per_mi,
    speed_m_per_min,
    elevation_gain_m,
    elevation_gain_m_per_mi,
    average_hr_bpm,
    aerobic_efficiency_m_per_heartbeat,
    temperature_c,
    temperature_f,
    apparent_temperature_f,
    relative_humidity_pct,
    wind_speed_mph,
    weather_available,
    easy_run_eligible as is_qualifying,
    long_run_eligible,
    exclusion_reason
from classified
