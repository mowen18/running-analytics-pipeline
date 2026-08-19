-- The D12-spirit weekly cycling sufficiency flag must equal the
-- threshold comparison it claims to encode, under whatever value the
-- var currently has.
select week_start_date, valid_ride_count, is_sufficient
from {{ ref('mart_weekly_cycling') }}
where is_sufficient != (valid_ride_count >= {{ var('min_weekly_valid_rides') }})
