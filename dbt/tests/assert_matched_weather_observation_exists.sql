-- Composite relationship test on the weather join (the built-in
-- relationships test can't cover a two-column key): every matched run
-- must point at a real observation row in staging.
select i.activity_id, i.location_key, i.weather_timestamp
from {{ ref('int_runs_with_weather') }} i
left join {{ ref('stg_weather__hourly') }} w
    on w.location_key = i.location_key
    and w.weather_timestamp = i.weather_timestamp
where i.weather_matched and w.location_key is null
