-- Weekly efficiency must be NULL exactly when the week has no
-- qualifying runs: a zero would fake a collapse, a NULL alongside
-- qualifying runs would silently drop the week from trends.
select week_start_date, qualifying_run_count, median_efficiency_m_per_beat
from {{ ref('mart_weekly_training') }}
where (median_efficiency_m_per_beat is null) != (qualifying_run_count = 0)
