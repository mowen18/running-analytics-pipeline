-- When Strava reports has_heartrate = false, HR columns must be NULL:
-- missing heart rate stays distinguishable from a measured zero.
select activity_id, average_hr_bpm, max_hr_bpm
from {{ ref('stg_strava__activities') }}
where not has_heartrate and (average_hr_bpm is not null or max_hr_bpm is not null)
