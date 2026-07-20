-- mart_run_band_segments must stay one row per run x band. Core
-- already guards this grain (assert_band_segments_unique_per_run_band);
-- this re-check exists to catch fan-out introduced at the mart hop —
-- the hr_bands seed join would duplicate rows if the seed ever grew
-- two rows per band_key.
select activity_id, band_key, count(*) as row_count
from {{ ref('mart_run_band_segments') }}
group by activity_id, band_key
having count(*) > 1
