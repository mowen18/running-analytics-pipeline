with valid_runs as (

    select * from {{ ref('fct_runs') }}
    where is_valid

),

banded as (

    select
        bands.band_key,
        bands.band_label,
        bands.sort_order,
        count(runs.activity_id) as valid_run_count,
        percentile_cont(0.5) within group (
            order by runs.aerobic_efficiency_m_per_heartbeat
        )                       as median_efficiency,
        avg(runs.aerobic_efficiency_m_per_heartbeat) as mean_efficiency,
        avg(runs.temperature_f) as avg_temperature_f,
        avg(runs.pace_min_per_mi) as avg_pace_min_per_mi,
        avg(runs.average_hr_bpm) as avg_hr_bpm
    from {{ ref('temperature_bands') }} bands
    -- LEFT JOIN from the seed: every D14 band appears even with zero
    -- runs (count 0, NULL statistics — an empty band is data, not a
    -- missing row).
    left join valid_runs runs
        on runs.weather_available
        and (bands.min_temperature_f is null
            or runs.temperature_f >= bands.min_temperature_f)
        and (bands.max_temperature_f is null
            or runs.temperature_f <= bands.max_temperature_f)
    group by bands.band_key, bands.band_label, bands.sort_order

),

-- Valid runs outside the temperature bands get explicit
-- pseudo-band rows rather than vanishing (data-quality principle 1) —
-- and "not applicable" is kept distinct from "missing":
--   indoor      = treadmill runs; no outdoor weather APPLIES
--   no_weather  = outdoor runs with no matched observation (unresolved
--                 coordinates or an archive gap); weather is MISSING
-- Both rows are always present, count 0 when empty.
indoor as (

    select
        'indoor' as band_key,
        'indoor' as band_label,
        98 as sort_order,
        count(*) as valid_run_count,
        percentile_cont(0.5) within group (
            order by aerobic_efficiency_m_per_heartbeat
        ) as median_efficiency,
        avg(aerobic_efficiency_m_per_heartbeat) as mean_efficiency,
        null::numeric as avg_temperature_f,
        avg(pace_min_per_mi) as avg_pace_min_per_mi,
        avg(average_hr_bpm) as avg_hr_bpm
    from valid_runs
    where is_trainer

),

unbanded as (

    select
        'no_weather' as band_key,
        'weather unavailable' as band_label,
        99 as sort_order,
        count(*) as valid_run_count,
        percentile_cont(0.5) within group (
            order by aerobic_efficiency_m_per_heartbeat
        ) as median_efficiency,
        avg(aerobic_efficiency_m_per_heartbeat) as mean_efficiency,
        null::numeric as avg_temperature_f,
        avg(pace_min_per_mi) as avg_pace_min_per_mi,
        avg(average_hr_bpm) as avg_hr_bpm
    from valid_runs
    where not is_trainer and not weather_available

)

select
    'all_time' as period,
    band_key,
    band_label,
    sort_order,
    valid_run_count,
    round(median_efficiency::numeric, 4)  as median_efficiency_m_per_beat,
    round(mean_efficiency::numeric, 4)    as mean_efficiency_m_per_beat,
    round(avg_temperature_f::numeric, 1)  as avg_temperature_f,
    round(avg_pace_min_per_mi::numeric, 2) as avg_pace_min_per_mi,
    round(avg_hr_bpm::numeric, 0)         as avg_hr_bpm
from banded

union all

select
    'all_time',
    band_key,
    band_label,
    sort_order,
    valid_run_count,
    round(median_efficiency::numeric, 4),
    round(mean_efficiency::numeric, 4),
    avg_temperature_f,
    round(avg_pace_min_per_mi::numeric, 2),
    round(avg_hr_bpm::numeric, 0)
from indoor

union all

select
    'all_time',
    band_key,
    band_label,
    sort_order,
    valid_run_count,
    round(median_efficiency::numeric, 4),
    round(mean_efficiency::numeric, 4),
    avg_temperature_f,
    round(avg_pace_min_per_mi::numeric, 2),
    round(avg_hr_bpm::numeric, 0)
from unbanded
