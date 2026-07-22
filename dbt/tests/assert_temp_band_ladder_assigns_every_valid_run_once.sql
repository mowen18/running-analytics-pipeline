-- Run-grain partition proof for the D14 ladder (v1.7): every valid run
-- lands in EXACTLY ONE of {seed band, indoor, no_weather}. The legs
-- below mirror mart_efficiency_by_temp_band's ladder leg-for-leg and
-- MUST be edited in lockstep with that model. This exists alongside the
-- aggregate conservation test
-- (assert_band_mart_accounts_for_every_valid_run) because a sum can be
-- fooled by offsetting errors — one dropped run plus one double-counted
-- run nets to zero — which a run-grain count cannot.

with valid_runs as (

    select * from {{ ref('fct_runs') }}
    where is_valid

),

assignments as (

    select runs.activity_id
    from valid_runs runs
    inner join {{ ref('temperature_bands') }} bands
        on not runs.is_trainer
        and runs.weather_available
        and {{ temperature_band_range('runs.apparent_temperature_f') }}

    union all

    select activity_id from valid_runs where is_trainer

    union all

    select activity_id
    from valid_runs
    where not is_trainer
        and (not weather_available or apparent_temperature_f is null)

)

select
    valid_runs.activity_id,
    count(assignments.activity_id) as assignment_count
from valid_runs
left join assignments using (activity_id)
group by valid_runs.activity_id
having count(assignments.activity_id) != 1
