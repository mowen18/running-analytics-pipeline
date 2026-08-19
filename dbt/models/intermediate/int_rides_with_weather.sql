with rides as (

    -- D23 ride grain, rendered from the ride_sport_types var (e-bike
    -- types are not in the var: motor assist breaks HR-effort
    -- comparability). is_indoor := trainer or VirtualRide, and indoor
    -- rides get a NULL location_key BY CONSTRUCTION so they are
    -- permanently unmatched — deliberately stronger than the running
    -- side, where the flag never gates the cell (v2.0 Phase C1).
    select
        *,
        (is_trainer or sport_type = 'VirtualRide') as is_indoor,
        case
            when not (is_trainer or sport_type = 'VirtualRide')
                and start_latitude is not null then
                -- Normalized D7 cell, mirroring the Python
                -- weather_client.location_key formatting (see
                -- int_runs_with_weather for the rounding-mode parity
                -- note; a disagreement surfaces as weather_matched =
                -- false, never as wrong weather).
                trim(to_char(round(start_latitude, 2), 'FM990.00'))
                || '_'
                || trim(to_char(round(start_longitude, 2), 'FM990.00'))
        end as location_key
    from {{ ref('stg_strava__activities') }}
    where sport_type in (
        {%- for ride_type in var('ride_sport_types') %}
        '{{ ride_type }}'{% if not loop.last %},{% endif %}
        {%- endfor %}
    )

),

observations as (

    -- Qualifying = carries at least one measurement. The explicit
    -- all-NULL "archive had no data" rows must never win a match.
    select * from {{ ref('stg_weather__hourly') }}
    where has_measurements

),

nearest as (

    select
        rides.activity_id,
        observations.weather_timestamp,
        observations.temperature_c,
        observations.temperature_f,
        observations.apparent_temperature_c,
        observations.apparent_temperature_f,
        observations.relative_humidity_pct,
        observations.wind_speed_kph,
        observations.wind_speed_mph,
        round(
            abs(extract(epoch from (observations.weather_timestamp - rides.start_date_utc))) / 60.0
        )::integer as weather_match_minutes,
        row_number() over (
            partition by rides.activity_id
            order by abs(extract(epoch from (observations.weather_timestamp - rides.start_date_utc)))
        ) as closeness_rank
    from rides
    inner join observations using (location_key)

)

select
    rides.activity_id,
    rides.activity_name,
    rides.sport_type,
    rides.workout_type,
    rides.start_date_utc,
    rides.start_date_local,
    rides.timezone_label,
    rides.distance_m,
    rides.moving_time_s,
    rides.elapsed_time_s,
    rides.elevation_gain_m,
    rides.average_speed_m_per_s,
    rides.max_speed_m_per_s,
    rides.has_heartrate,
    rides.average_hr_bpm,
    rides.max_hr_bpm,
    rides.average_cadence_rpm,
    rides.is_trainer,
    rides.is_indoor,
    rides.location_key,
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
    -- that the weather no longer describes the ride's start conditions.
    coalesce(nearest.weather_match_minutes <= 60, false) as weather_matched,
    rides.fetched_at
from rides
left join nearest
    on nearest.activity_id = rides.activity_id
    and nearest.closeness_rank = 1
