-- A run contributes a band only with dwell >= band_min_dwell_minutes
-- (D22): transitions passing through a band must not deposit junk
-- medians. Rendered from the same var the model filter uses, so the
-- test can never disagree with behavior.
select activity_id, band_key, dwell_s
from {{ ref('fct_run_band_segments') }}
where dwell_s < {{ var('band_min_dwell_minutes') }} * 60
