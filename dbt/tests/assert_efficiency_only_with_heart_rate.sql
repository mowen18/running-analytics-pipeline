-- Efficiency divides by HR: it must exist exactly when HR and speed do.
-- NULL efficiency on an HR-carrying run silently drops it from every
-- mart; a value without HR means a divide-by-garbage slipped through.
select activity_id, average_hr_bpm, speed_m_per_min, aerobic_efficiency_m_per_heartbeat
from {{ ref('int_run_efficiency') }}
where
    (aerobic_efficiency_m_per_heartbeat is not null
        and (average_hr_bpm is null or speed_m_per_min is null))
    or (aerobic_efficiency_m_per_heartbeat is null
        and average_hr_bpm > 0 and speed_m_per_min is not null)
