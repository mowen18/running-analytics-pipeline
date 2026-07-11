{#
  D22 sample pool: the valid, moving, in-window stream samples with
  their HR band and per-sample dwell contribution. The band analysis
  window trims the first band_warmup_trim_minutes of elapsed time
  (warm-up HR is still climbing, so untrimmed samples pair a too-low HR
  with full pace and pollute the LOW bands optimistically) and the
  final band_cooldown_trim_minutes. Unlike drift's time-based halves,
  pooling simply DROPS non-moving samples, so pauses cannot bias band
  medians — there is deliberately no pause-share check downstream.

  Dwell: each kept sample contributes least(gap to the previous kept
  sample, the drift coverage cap) seconds. The cap — the same
  drift_max_avg_sample_gap_s var, one mechanism with two consumers —
  keeps recording gaps from inflating dwell; sparse recordings fail the
  coverage rung in int_run_band_assessment before dwell is trusted. The
  first kept sample has no predecessor and carries the cap.

  Bands come from the hr_bands seed, joined by range via the
  hr_band_range macro (the D14 pattern). The join is on round(hr_bpm)
  so the seed's integer bounds cannot leave a fractional gap. This is
  the sanctioned seed read from an intermediate model (Revision v1.4's
  single layer-matrix widening).
#}

with samples as (

    select * from {{ ref('int_run_stream_samples') }}

),

windows as (

    -- Band trim bounds per run, from the full elapsed span of its
    -- samples (the drift windows construction, narrower trims).
    select
        activity_id,
        {{ var('band_warmup_trim_minutes') }} * 60                    as window_start_s,
        max(elapsed_s) - {{ var('band_cooldown_trim_minutes') }} * 60 as window_end_s
    from samples
    group by activity_id

),

pooled as (

    select
        samples.activity_id,
        samples.sample_index,
        samples.elapsed_s,
        samples.hr_bpm,
        samples.velocity_m_per_s,
        samples.elapsed_s - lag(samples.elapsed_s) over (
            partition by samples.activity_id order by samples.elapsed_s
        ) as gap_to_previous_s
    from samples
    inner join windows using (activity_id)
    where samples.elapsed_s between windows.window_start_s and windows.window_end_s
      and samples.is_moving
      and samples.is_valid_sample

)

select
    pooled.activity_id,
    pooled.sample_index,
    pooled.elapsed_s,
    pooled.hr_bpm,
    pooled.velocity_m_per_s,
    bands.band_key,
    least(
        coalesce(pooled.gap_to_previous_s, {{ var('drift_max_avg_sample_gap_s') }}),
        {{ var('drift_max_avg_sample_gap_s') }}
    ) as dwell_s
from pooled
inner join {{ ref('hr_bands') }} bands
    on {{ hr_band_range('round(pooled.hr_bpm)') }}
