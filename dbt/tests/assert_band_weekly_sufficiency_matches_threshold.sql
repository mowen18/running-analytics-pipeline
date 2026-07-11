-- The D12 sufficiency flag at week x HR-band grain must equal the
-- threshold comparison it claims to encode, under whatever value the
-- var currently has (same guard mart_weekly_training carries).
select week_start_date, band_key, contributing_run_count, is_sufficient
from {{ ref('mart_band_weekly') }}
where is_sufficient != (contributing_run_count >= {{ var('min_weekly_valid_runs') }})
