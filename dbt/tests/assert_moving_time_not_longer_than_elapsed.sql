-- Moving time can never exceed elapsed time (elapsed includes pauses).
select activity_id, moving_time_s, elapsed_time_s
from {{ ref('stg_strava__activities') }}
where moving_time_s > elapsed_time_s
