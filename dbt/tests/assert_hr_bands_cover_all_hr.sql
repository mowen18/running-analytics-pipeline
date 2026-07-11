-- The D22 HR bands must stay gap-free and non-overlapping at the
-- 1-bpm integer resolution the band join uses (samples are joined on
-- round(hr_bpm)). Probes every integer across a generous superset of
-- the sample-validity domain (25-250); each must land in exactly one
-- band. This is the guard that makes editing seeds/hr_bands.csv safe.
with probes as (

    select t as hr_bpm
    from generate_series(0, 300) as t

),

matches as (

    select probes.hr_bpm, count(bands.band_key) as band_count
    from probes
    left join {{ ref('hr_bands') }} bands
        on {{ hr_band_range('probes.hr_bpm') }}
    group by probes.hr_bpm

)

select hr_bpm, band_count
from matches
where band_count != 1
