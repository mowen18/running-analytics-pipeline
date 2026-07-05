with runs as (

    -- Running activities only (the filter documented in staging YAML).
    -- Indoor/coordinate-less runs stay in the grain with a NULL cell —
    -- they simply can never match weather.
    select
        *,
        case
            when start_latitude is not null then
                -- Normalized D7 cell, mirroring the Python
                -- weather_client.location_key formatting. Rounding-mode
                -- parity note: Postgres rounds numeric half-away-from-zero
                -- while Python formats the float; they can only disagree
                -- on exact half-cent coordinates, which GPS precision
                -- makes practically impossible — and a disagreement
                -- surfaces visibly as weather_matched = false, never as
                -- wrong weather.
                trim(to_char(round(start_latitude, 2), 'FM990.00'))
                || '_'
                || trim(to_char(round(start_longitude, 2), 'FM990.00'))
        end as location_key
    from {{ ref('stg_strava__activities') }}
    where sport_type in ('Run', 'TrailRun', 'VirtualRun')

),

observations as (

    -- Qualifying = carries at least one measurement. The explicit
    -- all-NULL "archive had no data" rows must never win a match.
    select * from {{ ref('stg_weather__hourly') }}
    where has_measurements

),

nearest as (

    select
        runs.activity_id,
        observations.weather_timestamp,
        observations.temperature_c,
        observations.temperature_f,
        observations.apparent_temperature_c,
        observations.apparent_temperature_f,
        observations.relative_humidity_pct,
        observations.wind_speed_kph,
        observations.wind_speed_mph,
        round(
            abs(extract(epoch from (observations.weather_timestamp - runs.start_date_utc))) / 60.0
        )::integer as weather_match_minutes,
        row_number() over (
            partition by runs.activity_id
            order by abs(extract(epoch from (observations.weather_timestamp - runs.start_date_utc)))
        ) as closeness_rank
    from runs
    inner join observations using (location_key)

)

select
    runs.activity_id,
    runs.activity_name,
    runs.sport_type,
    runs.workout_type,
    runs.start_date_utc,
    runs.start_date_local,
    runs.timezone_label,
    runs.distance_m,
    runs.moving_time_s,
    runs.elapsed_time_s,
    runs.elevation_gain_m,
    runs.average_speed_m_per_s,
    runs.max_speed_m_per_s,
    runs.has_heartrate,
    runs.average_hr_bpm,
    runs.max_hr_bpm,
    runs.is_trainer,
    runs.location_key,
    nearest.weather_timestamp,
    nearest.temperature_c,
    nearest.temperature_f,
    nearest.apparent_temperature_c,
    nearest.apparent_temperature_f,
    nearest.relative_humidity_pct,
    nearest.wind_speed_kph,
    nearest.wind_speed_mph,
    nearest.weather_match_minutes,
    -- Matched = a real observation within an hour of the start. Beyond
    -- that the weather no longer describes the run's start conditions.
    coalesce(nearest.weather_match_minutes <= 60, false) as weather_matched,
    runs.fetched_at
from runs
left join nearest
    on nearest.activity_id = runs.activity_id
    and nearest.closeness_rank = 1
