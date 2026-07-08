-- Activity-grain stream-fetch state (one row per raw_strava.streams row):
-- feeds fct_drift_candidates' stream-availability exclusion rungs without
-- core reading the raw source. raw_strava.streams is the only source
-- readable outside staging, from intermediate models ONLY (Revision v1.2
-- follow-up); payloads are deliberately unstaged.
select
    activity_id,
    ingestion_status,
    (payload ? 'time' and payload ? 'heartrate' and payload ? 'velocity_smooth')
        as has_required_arrays
from {{ source('raw_strava', 'streams') }}
