-- D22 contract (acceptance criterion 5): every band candidate carries
-- EXACTLY ONE of (>= 1 row in fct_run_band_segments, exclusion_reason)
-- — mutually exclusive, jointly exhaustive; never both, never neither.
-- The reverse direction (a segment row without a candidate) is covered
-- by the relationships test on fct_run_band_segments.activity_id.
with segment_counts as (

    select activity_id, count(*) as segment_count
    from {{ ref('fct_run_band_segments') }}
    group by activity_id

)

select
    candidates.activity_id,
    candidates.exclusion_reason,
    coalesce(segment_counts.segment_count, 0) as segment_count
from {{ ref('fct_band_candidates') }} candidates
left join segment_counts using (activity_id)
where (candidates.exclusion_reason is null)
    != (coalesce(segment_counts.segment_count, 0) >= 1)
