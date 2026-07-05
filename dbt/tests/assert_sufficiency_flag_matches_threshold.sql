-- The D12 sufficiency flag must equal the threshold comparison it
-- claims to encode, under whatever value the var currently has.
select week_start_date, valid_run_count, is_sufficient
from {{ ref('mart_weekly_training') }}
where is_sufficient != (valid_run_count >= {{ var('min_weekly_valid_runs') }})
