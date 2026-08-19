{#
  The ride-level quality view (v2.0 Phase C1): one row per D23 ride with
  its measures, validity verdict, and weather context — the
  mart_run_quality mirror, letting the dashboard answer "why didn't ride
  X count?" while reading only core (and the D14 seed). No drift or band
  joins: those analyses are running-only (ride drift is deferred —
  coasting breaks the D16 halves comparison).
#}

with rides as (

    select * from {{ ref('fct_rides') }}

)

select
    rides.activity_id,
    rides.start_date_local,
    rides.week_start_date,
    rides.activity_name,
    rides.sport_type,
    rides.is_indoor,
    rides.distance_mi,
    rides.moving_time_min,
    rides.avg_speed_mph,
    rides.average_hr_bpm,
    rides.average_cadence_rpm,
    rides.is_valid,
    rides.exclusion_reason,
    rides.weather_available,
    rides.temperature_f,
    rides.apparent_temperature_f,
    -- Per-ride band, same vocabulary as the running marts: indoor
    -- (weather not applicable — trainer or VirtualRide) / a D14 seed
    -- band (v1.7: assigned by apparent temperature) / weather
    -- unavailable (outdoor, unmatched or feels-like missing).
    case
        when rides.is_indoor then 'indoor'
        else coalesce(bands.band_label, 'weather unavailable')
    end as temperature_band_label
from rides
left join {{ ref('temperature_bands') }} bands
    on not rides.is_indoor
    and rides.weather_available
    and {{ temperature_band_range('rides.apparent_temperature_f') }}
