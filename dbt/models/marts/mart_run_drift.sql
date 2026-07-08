with analyzed as (

    -- Successfully analyzed candidates only; the full candidate set
    -- with exclusion reasons stays queryable in fct_drift_candidates
    -- and reaches the dashboard as mart_run_quality's
    -- drift_exclusion_reason (D19 allow-list: the app reads marts
    -- only, never core relations).
    select * from {{ ref('fct_drift_candidates') }}
    where exclusion_reason is null

),

context as (

    select
        activity_id,
        activity_name,
        distance_mi,
        temperature_f,
        weather_available
    from {{ ref('fct_runs') }}

)

select
    analyzed.activity_id,
    context.activity_name,
    analyzed.start_date_local,
    analyzed.week_start_date,
    analyzed.moving_time_min,
    context.distance_mi,
    context.temperature_f,
    context.weather_available,
    round(analyzed.window_duration_s / 60.0, 1) as analysis_window_min,
    analyzed.first_half_hr_bpm,
    analyzed.second_half_hr_bpm,
    analyzed.first_half_speed_m_per_min,
    analyzed.second_half_speed_m_per_min,
    analyzed.first_half_efficiency,
    analyzed.second_half_efficiency,
    analyzed.decoupling_pct,
    -- Data-quality context for the dashboard: how much signal is
    -- behind this run's number.
    analyzed.window_sample_count,
    analyzed.valid_sample_count,
    analyzed.paused_fraction,
    analyzed.avg_sample_gap_s
from analyzed
inner join context using (activity_id)
