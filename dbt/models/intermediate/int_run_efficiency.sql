with runs as (

    select * from {{ ref('fct_runs') }}

),

classified as (

    select
        *,
        -- Aerobic efficiency per D10: meters per heartbeat. Computed for
        -- ANY run with HR and speed (a race has a real efficiency value);
        -- is_valid decides what the marts aggregate. Guarded: NULL
        -- when HR or speed is missing/zero, never an error or a zero.
        case
            when average_hr_bpm > 0 and speed_m_per_min is not null
                then round(speed_m_per_min / average_hr_bpm, 4)
        end as aerobic_efficiency_m_per_heartbeat,
        -- Run validity per D9 (revised v1.1): data-validity rules only,
        -- no intensity ceiling and no race/workout exclusion. Kept as an
        -- independent boolean so the CASE ladder below is a second
        -- encoding of the same rules — their equivalence is asserted by
        -- assert_exclusion_reason_matches_validity.
        (
            has_heartrate
            and average_hr_bpm is not null
            and average_hr_bpm between {{ var('hr_sanity_floor') }}
                and {{ var('hr_sanity_ceiling') }}
            and pace_min_per_mi is not null
            and pace_min_per_mi between {{ var('pace_min_per_mi_floor') }}
                and {{ var('pace_min_per_mi_ceiling') }}
            and moving_time_min >= {{ var('valid_run_min_moving_minutes') }}
        ) as is_valid,
        -- First failing validity rule in the v1.1 priority order; NULL
        -- means valid. Priority runs data-availability -> sanity ->
        -- pace -> duration, so the most fundamental problem is the one
        -- reported.
        case
            when not has_heartrate or average_hr_bpm is null
                then 'no heart rate data'
            when average_hr_bpm not between {{ var('hr_sanity_floor') }}
                and {{ var('hr_sanity_ceiling') }}
                then 'average HR outside {{ var("hr_sanity_floor") }}–{{ var("hr_sanity_ceiling") }} bpm sanity band'
            when pace_min_per_mi is null
                or pace_min_per_mi not between {{ var('pace_min_per_mi_floor') }}
                    and {{ var('pace_min_per_mi_ceiling') }}
                then 'pace outside {{ var("pace_min_per_mi_floor") }}–{{ var("pace_min_per_mi_ceiling") }} min/mi bounds'
            when moving_time_min < {{ var('valid_run_min_moving_minutes') }}
                then 'moving time under {{ var("valid_run_min_moving_minutes") }} minutes'
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
    is_trainer,
    is_valid,
    long_run_eligible,
    exclusion_reason
from classified
