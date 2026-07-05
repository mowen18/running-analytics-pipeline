-- The D14 bands must stay gap-free and non-overlapping at the 1-dp
-- resolution of stg_weather__hourly.temperature_f. Probes every 0.1°F
-- across a generous range; each must land in exactly one band. This is
-- the guard that makes editing seeds/temperature_bands.csv safe.
with probes as (

    select round(t / 10.0, 1) as temperature_f
    from generate_series(-300, 1300) as t

),

matches as (

    select probes.temperature_f, count(bands.band_key) as band_count
    from probes
    left join {{ ref('temperature_bands') }} bands
        on (bands.min_temperature_f is null or probes.temperature_f >= bands.min_temperature_f)
        and (bands.max_temperature_f is null or probes.temperature_f <= bands.max_temperature_f)
    group by probes.temperature_f

)

select temperature_f, band_count
from matches
where band_count != 1
