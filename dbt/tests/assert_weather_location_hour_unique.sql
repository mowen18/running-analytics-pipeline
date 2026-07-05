-- One row per place-hour: the composite key the raw UNIQUE constraint
-- enforces, re-asserted at staging (no dbt_utils, so a singular test
-- instead of unique_combination_of_columns).
select location_key, weather_timestamp, count(*) as row_count
from {{ ref('stg_weather__hourly') }}
group by location_key, weather_timestamp
having count(*) > 1
