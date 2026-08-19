-- Core projection of int_ride_measures (v2.0 Phase C1): the mart- and
-- app-facing ride-level contract, one row per D23 ride. All computation
-- happens upstream; this is a pure explicit-column surface so marts read
-- core only. E-bike types never enter the grain — the filter renders
-- from the ride_sport_types var and is pinned by
-- assert_fct_rides_excludes_ebike_types.
with rides as (

    select * from {{ ref('int_ride_measures') }}

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
    weather_available,
    fetched_at,
    is_valid,
    exclusion_reason
from rides
