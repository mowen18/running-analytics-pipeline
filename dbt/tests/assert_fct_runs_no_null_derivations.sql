-- Guarded divisions must only be NULL when their denominator is zero;
-- a NULL pace on a real run would silently drop it from every metric.
select activity_id
from {{ ref('fct_runs') }}
where
    (distance_m > 0 and moving_time_s > 0 and pace_min_per_mi is null)
    or (moving_time_s > 0 and speed_m_per_min is null)
    or (distance_m > 0 and elevation_gain_m is not null and elevation_gain_m_per_mi is null)
