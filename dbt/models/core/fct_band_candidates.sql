-- Core projection of int_run_band_assessment (Revision v1.4, the
-- fct_runs <- int_run_efficiency pattern): one row per D22 band
-- candidate — an HR-carrying run past the stream fetch gate — with its
-- window stats and the deterministic exclusion verdict. Every
-- candidate carries exactly one of (>= 1 row in fct_run_band_segments,
-- exclusion_reason); the contract is enforced by
-- assert_band_candidates_exclusive_exhaustive.
with assessment as (

    select * from {{ ref('int_run_band_assessment') }}

)

select
    activity_id,
    week_start_date,
    start_date_local,
    moving_time_min,
    window_duration_s,
    window_sample_count,
    valid_sample_count,
    avg_sample_gap_s,
    pooled_moving_dwell_min,
    qualifying_band_count,
    exclusion_reason
from assessment
