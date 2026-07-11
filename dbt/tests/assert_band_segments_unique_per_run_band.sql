-- fct_run_band_segments' grain is run x HR band (composite — the
-- single-column unique test cannot express it, same as the weather
-- cache's location + hour).
select activity_id, band_key, count(*) as row_count
from {{ ref('fct_run_band_segments') }}
group by activity_id, band_key
having count(*) > 1
