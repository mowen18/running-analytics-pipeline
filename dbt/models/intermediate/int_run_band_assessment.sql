{#
  D22 run-grain assessment: window stats and the band exclusion ladder,
  encoded ONCE here. Both core band models consume this verdict —
  fct_band_candidates as an explicit-column projection,
  fct_run_band_segments as its analyzed-only filter — mirroring how
  int_run_efficiency carries the validity ladder for fct_runs and
  fct_drift_candidates (no core -> core edge needed).

  Candidates are HR-carrying runs past the stream FETCH gate (D15
  revised v1.4: stream_fetch_min_moving_minutes), so drift candidacy
  (long_run_min_moving_minutes) stays a strict subset by construction.

  The ladder reports the FIRST failing check in dependency order
  (mirrors fct_drift_candidates, same strings where the mechanism is
  shared): stream availability -> required arrays -> window length ->
  coverage -> dwell minimum. "Window length" is the addendum's "moving
  time remaining": the pooled moving dwell (sum of capped per-sample
  dwell) must reach band_min_window_minutes — which also covers runs
  whose samples never reach the window at all. Coverage mirrors drift
  exactly: average spacing of VALID samples inside the window (moving
  or not) must not exceed drift_max_avg_sample_gap_s.
#}

with candidates as (

    select activity_id, moving_time_min, week_start_date, start_date_local
    from {{ ref('int_run_efficiency') }}
    where average_hr_bpm is not null
      and moving_time_min >= {{ var('stream_fetch_min_moving_minutes') }}

),

stream_state as (

    select * from {{ ref('int_run_stream_state') }}

),

windows as (

    -- The same trim arithmetic int_band_window_samples applies to the
    -- pooled samples, needed here at full sample grain so coverage
    -- counts valid samples whether or not they are moving.
    select
        activity_id,
        {{ var('band_warmup_trim_minutes') }} * 60                    as window_start_s,
        max(elapsed_s) - {{ var('band_cooldown_trim_minutes') }} * 60 as window_end_s
    from {{ ref('int_run_stream_samples') }}
    group by activity_id

),

window_stats as (

    select
        samples.activity_id,
        min(windows.window_end_s - windows.window_start_s) as window_duration_s,
        count(*)                                           as window_sample_count,
        count(*) filter (where samples.is_valid_sample)    as valid_sample_count
    from {{ ref('int_run_stream_samples') }} samples
    inner join windows using (activity_id)
    where samples.elapsed_s between windows.window_start_s and windows.window_end_s
    group by samples.activity_id

),

band_dwell as (

    select
        activity_id,
        band_key,
        sum(dwell_s)  as band_dwell_s,
        count(*)      as band_sample_count
    from {{ ref('int_band_window_samples') }}
    group by activity_id, band_key

),

band_stats as (

    select
        activity_id,
        sum(band_dwell_s)       as pooled_moving_dwell_s,
        sum(band_sample_count)  as pooled_sample_count,
        max(band_dwell_s)       as max_band_dwell_s,
        count(*) filter (where band_dwell_s >= {{ var('band_min_dwell_minutes') }} * 60)
                                as qualifying_band_count
    from band_dwell
    group by activity_id

)

select
    candidates.activity_id,
    candidates.week_start_date,
    candidates.start_date_local,
    candidates.moving_time_min,
    window_stats.window_duration_s,
    window_stats.window_sample_count,
    window_stats.valid_sample_count,
    round(
        window_stats.window_duration_s::numeric
        / nullif(window_stats.valid_sample_count, 0), 2
    )                                                   as avg_sample_gap_s,
    round(coalesce(band_stats.pooled_moving_dwell_s, 0) / 60.0, 1)
                                                        as pooled_moving_dwell_min,
    coalesce(band_stats.qualifying_band_count, 0)       as qualifying_band_count,
    case
        when stream_state.activity_id is null
            then 'streams not yet loaded'
        when stream_state.ingestion_status = 'unavailable'
            then 'streams unavailable from Strava'
        when stream_state.ingestion_status = 'failed'
            then 'stream fetch failed (retried by next backfill)'
        when not stream_state.has_required_arrays
            then 'missing required stream types'
        when band_stats.activity_id is null
            or band_stats.pooled_moving_dwell_s
                < {{ var('band_min_window_minutes') }} * 60
            then 'analysis window under {{ var("band_min_window_minutes") }} minutes after trimming'
        when window_stats.valid_sample_count = 0
            or window_stats.window_duration_s::numeric / window_stats.valid_sample_count
                > {{ var('drift_max_avg_sample_gap_s') }}
            then 'insufficient sample coverage'
        when band_stats.max_band_dwell_s < {{ var('band_min_dwell_minutes') }} * 60
            then 'no band meets the dwell minimum'
    end as exclusion_reason
from candidates
left join stream_state using (activity_id)
left join window_stats using (activity_id)
left join band_stats using (activity_id)
