with source as (

    select * from {{ source('raw_strava', 'activities') }}

)

select
    activity_id,
    payload ->> 'name'                                     as activity_name,
    activity_type                                          as sport_type,
    payload ->> 'type'                                     as legacy_type,
    (payload ->> 'workout_type')::integer                  as workout_type,
    start_date_utc,
    -- Strava sends start_date_local with a literal 'Z' even though it is
    -- local wall-clock time; ::timestamp deliberately drops that bogus
    -- zone marker instead of treating the value as UTC.
    (payload ->> 'start_date_local')::timestamp            as start_date_local,
    payload ->> 'timezone'                                 as timezone_label,
    (payload ->> 'distance')::numeric                      as distance_m,
    (payload ->> 'moving_time')::integer                   as moving_time_s,
    (payload ->> 'elapsed_time')::integer                  as elapsed_time_s,
    (payload ->> 'total_elevation_gain')::numeric          as elevation_gain_m,
    (payload ->> 'average_speed')::numeric                 as average_speed_m_per_s,
    (payload ->> 'max_speed')::numeric                     as max_speed_m_per_s,
    coalesce((payload ->> 'has_heartrate')::boolean, false) as has_heartrate,
    -- HR only when the source says it exists: missing stays NULL, never 0.
    case
        when coalesce((payload ->> 'has_heartrate')::boolean, false)
            then (payload ->> 'average_heartrate')::numeric
    end                                                    as average_hr_bpm,
    case
        when coalesce((payload ->> 'has_heartrate')::boolean, false)
            then (payload ->> 'max_heartrate')::numeric
    end                                                    as max_hr_bpm,
    coalesce((payload ->> 'trainer')::boolean, false)      as is_trainer,
    case
        when jsonb_array_length(coalesce(payload -> 'start_latlng', '[]'::jsonb)) = 2
            then (payload -> 'start_latlng' ->> 0)::numeric
    end                                                    as start_latitude,
    case
        when jsonb_array_length(coalesce(payload -> 'start_latlng', '[]'::jsonb)) = 2
            then (payload -> 'start_latlng' ->> 1)::numeric
    end                                                    as start_longitude,
    fetched_at
from source
