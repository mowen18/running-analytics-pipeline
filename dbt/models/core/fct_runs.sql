-- Core projection of int_run_efficiency (Revision v1.2): the mart- and
-- app-facing run-level contract. Columns 1–34 are the pre-v1.2 fct_runs
-- surface, unchanged in order and value; 35–37 expose the analytic
-- columns so marts read core only.
with runs as (

    select * from {{ ref('int_run_efficiency') }}

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
    weather_available,
    long_run_eligible,
    fetched_at,
    aerobic_efficiency_m_per_heartbeat,
    is_valid,
    exclusion_reason
from runs
