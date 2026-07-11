{#
  The run-level quality view: one row per running activity with its
  efficiency value, validity verdict, weather context, and drift
  context. This is the mart that lets the dashboard answer "why didn't
  run X count?" while reading only the core layer (Revision v1.2:
  marts reference core, seeds, and other marts only). Efficiency is
  computed for EVERY heart-rate-carrying run
  while the trend/band marts aggregate runs with valid HR data (D9
  revised v1.1); both facts are visible here side by side.
#}

with runs as (

    select * from {{ ref('fct_runs') }}

),

drift as (

    select
        activity_id,
        decoupling_pct,
        exclusion_reason as drift_exclusion_reason
    from {{ ref('fct_drift_candidates') }}

),

band_candidates as (

    -- Same route the drift reason takes (v1.4): NULL means the run is
    -- not a band candidate OR was analyzed successfully — the candidate
    -- table itself distinguishes the two.
    select
        activity_id,
        exclusion_reason as band_exclusion_reason
    from {{ ref('fct_band_candidates') }}

)

select
    runs.activity_id,
    runs.start_date_local,
    runs.week_start_date,
    runs.activity_name,
    runs.sport_type,
    runs.is_trainer,
    runs.distance_mi,
    runs.moving_time_min,
    runs.pace_min_per_mi,
    runs.average_hr_bpm,
    runs.aerobic_efficiency_m_per_heartbeat,
    runs.is_valid,
    runs.exclusion_reason,
    runs.long_run_eligible,
    runs.weather_available,
    runs.temperature_f,
    -- Per-run band, same vocabulary as mart_efficiency_by_temp_band:
    -- indoor (weather not applicable) / a D14 seed band / weather
    -- unavailable (outdoor, unmatched or temperature missing).
    case
        when runs.is_trainer then 'indoor'
        else coalesce(bands.band_label, 'weather unavailable')
    end as temperature_band_label,
    drift.decoupling_pct,
    drift.drift_exclusion_reason,
    band_candidates.band_exclusion_reason
from runs
left join {{ ref('temperature_bands') }} bands
    on not runs.is_trainer
    and runs.weather_available
    and {{ temperature_band_range('runs.temperature_f') }}
left join drift using (activity_id)
left join band_candidates using (activity_id)
