-- Conservation check: the band mart's counts (three D14 bands + the
-- explicit no_weather row) must sum to the total number of valid runs.
-- A shortfall means runs are being silently dropped from the
-- comparison; an excess means a run landed in two bands.
select
    (select coalesce(sum(valid_run_count), 0)
     from {{ ref('mart_efficiency_by_temp_band') }}) as banded_total,
    (select count(*)
     from {{ ref('int_run_efficiency') }}
     where is_valid) as valid_total
where
    (select coalesce(sum(valid_run_count), 0)
     from {{ ref('mart_efficiency_by_temp_band') }})
    != (select count(*) from {{ ref('int_run_efficiency') }} where is_valid)
