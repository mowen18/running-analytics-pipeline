-- v1.6 consistency contract: mart_band_weekly's weekly statistic must
-- equal the median recomputed from mart_run_band_segments' per-run
-- rows, week x band by week x band, and both marts must cover exactly
-- the same keys with the same run counts.
--
-- The comparison lives in VELOCITY space only. Percentile
-- interpolation does not commute with the 1/x pace transform (runs at
-- 2 and 4 m/s: weekly median velocity 3 m/s ~ 8.94 min/mi, but the
-- median of the two run paces is 10.06), and the weekly pace column is
-- derived from the UNROUNDED weekly percentile, so pace-space
-- comparisons would false-fail. In velocity space both sides take
-- percentile_cont(0.5) over the identical multiset of already-rounded
-- core values and round to 3 dp, so exact equality is required.
--
-- The run-count check is not redundant with the median check: a
-- uniform fan-out duplicates every value, which leaves the median
-- unchanged — only the count can catch it here.
with recomputed as (

    select
        week_start_date,
        band_key,
        round(
            (percentile_cont(0.5) within group (order by median_velocity_m_per_s))::numeric, 3
        )        as recomputed_median_velocity_m_per_s,
        count(*) as run_count
    from {{ ref('mart_run_band_segments') }}
    group by week_start_date, band_key

)

select
    coalesce(weekly.week_start_date, recomputed.week_start_date) as week_start_date,
    coalesce(weekly.band_key, recomputed.band_key)               as band_key,
    weekly.median_velocity_m_per_s,
    recomputed.recomputed_median_velocity_m_per_s,
    weekly.contributing_run_count,
    recomputed.run_count
from {{ ref('mart_band_weekly') }} weekly
full outer join recomputed
    on recomputed.week_start_date = weekly.week_start_date
    and recomputed.band_key = weekly.band_key
where weekly.band_key is null
   or recomputed.band_key is null
   or weekly.median_velocity_m_per_s
      is distinct from recomputed.recomputed_median_velocity_m_per_s
   or weekly.contributing_run_count is distinct from recomputed.run_count
