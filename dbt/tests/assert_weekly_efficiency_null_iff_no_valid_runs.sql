-- Weekly efficiency must be NULL exactly when the week has no valid
-- runs: a zero would fake a collapse, a NULL alongside valid runs
-- would silently drop the week from trends.
select week_start_date, valid_run_count, median_efficiency_m_per_beat
from {{ ref('mart_weekly_training') }}
where (median_efficiency_m_per_beat is null) != (valid_run_count = 0)
