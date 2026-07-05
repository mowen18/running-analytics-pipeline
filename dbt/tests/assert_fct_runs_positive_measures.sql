-- Runs must have positive distance and moving time (the staging layer
-- only enforces non-negative, because zero is legitimate for non-run
-- sport types like Workout).
select activity_id, distance_m, moving_time_s
from {{ ref('fct_runs') }}
where distance_m <= 0 or moving_time_s <= 0
