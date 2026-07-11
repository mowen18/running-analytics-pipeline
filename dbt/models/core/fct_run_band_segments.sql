{#
  D22 run x HR-band segments: analyzed candidates only — the verdict
  comes from int_run_band_assessment, where the exclusion ladder is
  encoded once. A run contributes a band only with dwell of at least
  band_min_dwell_minutes: transitions passing through a band must not
  deposit junk medians.

  Medians are computed in VELOCITY space; pace is derived from the
  median velocity for display. The weekly and rolling statistics
  downstream aggregate these run-level velocity medians the same way,
  so every pace column in the band chain is the same monotone
  transformation of a velocity median.
#}

with analyzed as (

    select activity_id, week_start_date, start_date_local
    from {{ ref('int_run_band_assessment') }}
    where exclusion_reason is null

),

samples as (

    select * from {{ ref('int_band_window_samples') }}

)

select
    analyzed.activity_id,
    analyzed.week_start_date,
    analyzed.start_date_local,
    samples.band_key,
    round(sum(samples.dwell_s)::numeric, 1)  as dwell_s,
    count(*)                                 as sample_count,
    round(
        (percentile_cont(0.5) within group (order by samples.velocity_m_per_s))::numeric,
        3
    )                                        as median_velocity_m_per_s,
    round(
        (1609.344 / nullif(
            percentile_cont(0.5) within group (order by samples.velocity_m_per_s) * 60.0,
            0
        ))::numeric,
        2
    )                                        as median_pace_min_per_mi
from analyzed
inner join samples using (activity_id)
group by
    analyzed.activity_id,
    analyzed.week_start_date,
    analyzed.start_date_local,
    samples.band_key
having sum(samples.dwell_s) >= {{ var('band_min_dwell_minutes') }} * 60
