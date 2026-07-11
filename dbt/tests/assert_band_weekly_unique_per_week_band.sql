-- mart_band_weekly's grain is week x HR band (composite). The trend
-- mart left-joins this grain one-to-one, so a duplicate here would fan
-- out silently downstream.
select week_start_date, band_key, count(*) as row_count
from {{ ref('mart_band_weekly') }}
group by week_start_date, band_key
having count(*) > 1
