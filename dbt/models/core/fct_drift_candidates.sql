{#
  D16 analysis window, applied in the plan's order: exclude non-moving
  samples -> drop the first drift_warmup_minutes -> drop the final
  drift_cooldown_minutes -> require >= drift_min_window_minutes
  remaining -> split into two equal-duration halves by elapsed time.

  Candidates are HR-carrying runs long enough for drift (D15 revised
  v1.1: the same 45-minute var as long_run_eligible). Every candidate
  appears in the output; runs that can't be analyzed carry the FIRST
  failing check as a deterministic exclusion reason (acceptance
  criterion 4), in dependency order: stream availability -> required
  arrays -> window length -> pauses -> coverage.
#}

with candidates as (

    select activity_id, moving_time_min, week_start_date, start_date_local
    from {{ ref('int_run_efficiency') }}
    where long_run_eligible and average_hr_bpm is not null

),

stream_state as (

    select * from {{ ref('int_run_stream_state') }}

),

windows as (

    -- Trim bounds per run, from the full elapsed span of its samples.
    select
        activity_id,
        {{ var('drift_warmup_minutes') }} * 60                    as window_start_s,
        max(elapsed_s) - {{ var('drift_cooldown_minutes') }} * 60 as window_end_s
    from {{ ref('int_run_stream_samples') }}
    group by activity_id

),

windowed as (

    select
        samples.activity_id,
        windows.window_start_s,
        windows.window_end_s,
        windows.window_end_s - windows.window_start_s as window_duration_s,
        samples.elapsed_s,
        samples.hr_bpm,
        samples.velocity_m_per_s,
        samples.is_moving,
        samples.is_valid_sample,
        samples.elapsed_s
            <= (windows.window_start_s + windows.window_end_s) / 2.0 as in_first_half
    from {{ ref('int_run_stream_samples') }} samples
    inner join windows using (activity_id)
    where samples.elapsed_s between windows.window_start_s and windows.window_end_s

),

window_stats as (

    select
        activity_id,
        min(window_duration_s)                                as window_duration_s,
        count(*)                                              as window_sample_count,
        count(*) filter (where is_valid_sample)               as valid_sample_count,
        count(*) filter (where not is_moving)::numeric
            / nullif(count(*), 0)                             as paused_fraction,
        count(*) filter (where is_moving and is_valid_sample and in_first_half)
                                                              as first_half_sample_count,
        count(*) filter (where is_moving and is_valid_sample and not in_first_half)
                                                              as second_half_sample_count,
        avg(hr_bpm) filter (where is_moving and is_valid_sample and in_first_half)
                                                              as first_half_hr_bpm,
        avg(hr_bpm) filter (where is_moving and is_valid_sample and not in_first_half)
                                                              as second_half_hr_bpm,
        avg(velocity_m_per_s) filter (where is_moving and is_valid_sample and in_first_half)
            * 60                                              as first_half_speed_m_per_min,
        avg(velocity_m_per_s) filter (where is_moving and is_valid_sample and not in_first_half)
            * 60                                              as second_half_speed_m_per_min
    from windowed
    group by activity_id

),

assessed as (

    select
        candidates.activity_id,
        candidates.week_start_date,
        candidates.start_date_local,
        candidates.moving_time_min,
        window_stats.window_duration_s,
        window_stats.window_sample_count,
        window_stats.valid_sample_count,
        round(window_stats.paused_fraction, 3)        as paused_fraction,
        round(
            window_stats.window_duration_s::numeric
            / nullif(window_stats.valid_sample_count, 0), 2
        )                                             as avg_sample_gap_s,
        window_stats.first_half_sample_count,
        window_stats.second_half_sample_count,
        round(window_stats.first_half_hr_bpm, 1)      as first_half_hr_bpm,
        round(window_stats.second_half_hr_bpm, 1)     as second_half_hr_bpm,
        round(window_stats.first_half_speed_m_per_min, 1)
                                                      as first_half_speed_m_per_min,
        round(window_stats.second_half_speed_m_per_min, 1)
                                                      as second_half_speed_m_per_min,
        case
            when stream_state.activity_id is null
                then 'streams not yet loaded'
            when stream_state.ingestion_status = 'unavailable'
                then 'streams unavailable from Strava'
            when stream_state.ingestion_status = 'failed'
                then 'stream fetch failed (retried by next backfill)'
            when not stream_state.has_required_arrays
                then 'missing required stream types'
            when window_stats.activity_id is null
                or window_stats.window_duration_s
                    < {{ var('drift_min_window_minutes') }} * 60
                then 'analysis window under {{ var("drift_min_window_minutes") }} minutes after trimming'
            when window_stats.paused_fraction > {{ var('drift_max_paused_fraction') }}
                then 'excessive pauses (non-moving share above {{ var("drift_max_paused_fraction") }})'
            when window_stats.valid_sample_count = 0
                or window_stats.window_duration_s::numeric / window_stats.valid_sample_count
                    > {{ var('drift_max_avg_sample_gap_s') }}
                or window_stats.first_half_sample_count = 0
                or window_stats.second_half_sample_count = 0
                then 'insufficient sample coverage'
        end as exclusion_reason
    from candidates
    left join stream_state using (activity_id)
    left join window_stats using (activity_id)

)

select
    *,
    round((first_half_speed_m_per_min / first_half_hr_bpm)::numeric, 4)
        as first_half_efficiency,
    round((second_half_speed_m_per_min / second_half_hr_bpm)::numeric, 4)
        as second_half_efficiency,
    -- D17 sign convention: POSITIVE = efficiency declined in the second
    -- half; near zero = stable; negative = second half improved.
    case
        when exclusion_reason is null
            then round(
                (
                    (first_half_speed_m_per_min / first_half_hr_bpm)
                    - (second_half_speed_m_per_min / second_half_hr_bpm)
                )
                / nullif(first_half_speed_m_per_min / first_half_hr_bpm, 0) * 100.0,
                2
            )
    end as decoupling_pct
from assessed
