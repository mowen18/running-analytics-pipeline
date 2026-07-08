with weekly as (

    select * from {{ ref('mart_weekly_training') }}

),

valid_runs as (

    select
        start_date_local::date as run_date,
        aerobic_efficiency_m_per_heartbeat
    from {{ ref('fct_runs') }}
    where is_valid

),

rolling as (

    -- 28-day rolling median (D13) over run-level efficiency, windowed
    -- on the trend_window_days ending with each week's Sunday.
    -- percentile_cont is not a window function, so the window is an
    -- explicit join + group: trivially cheap at personal-training data
    -- volumes, and the window arithmetic stays visible.
    select
        weekly.week_start_date,
        percentile_cont(0.5) within group (
            order by valid_runs.aerobic_efficiency_m_per_heartbeat
        )        as rolling_median_efficiency,
        count(*) as rolling_valid_run_count
    from weekly
    inner join valid_runs
        on valid_runs.run_date
            > weekly.week_start_date + 6 - {{ var('trend_window_days') }}
        and valid_runs.run_date <= weekly.week_start_date + 6
    group by weekly.week_start_date

)

select
    weekly.week_start_date,
    weekly.valid_run_count,
    weekly.median_efficiency_m_per_beat,
    round(rolling.rolling_median_efficiency::numeric, 4)
        as rolling_{{ var('trend_window_days') }}d_median_efficiency,
    coalesce(rolling.rolling_valid_run_count, 0)
        as rolling_{{ var('trend_window_days') }}d_valid_run_count,
    weekly.avg_hr_bpm,
    weekly.avg_temperature_f,
    bands.band_key   as temperature_band_key,
    bands.band_label as temperature_band_label,
    weekly.is_sufficient
from weekly
left join rolling using (week_start_date)
-- The week's band comes from its average valid-run temperature; NULL
-- when the week has no weather-matched valid runs (missing, never a
-- default band).
left join {{ ref('temperature_bands') }} bands
    on (bands.min_temperature_f is null
        or weekly.avg_temperature_f >= bands.min_temperature_f)
    and (bands.max_temperature_f is null
        or weekly.avg_temperature_f <= bands.max_temperature_f)
