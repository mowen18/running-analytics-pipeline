-- Conservation check: the band mart's counts (the D14 seed bands plus
-- the explicit indoor and no_weather rows — band-count agnostic) must
-- sum to the total number of valid runs
-- in fct_runs — the core relation the marts read. A shortfall means
-- runs are being silently dropped from the comparison; an excess means
-- a run landed in two bands.
select
    (select coalesce(sum(valid_run_count), 0)
     from {{ ref('mart_efficiency_by_temp_band') }}) as banded_total,
    (select count(*)
     from {{ ref('fct_runs') }}
     where is_valid) as valid_total
where
    (select coalesce(sum(valid_run_count), 0)
     from {{ ref('mart_efficiency_by_temp_band') }})
    != (select count(*) from {{ ref('fct_runs') }} where is_valid)
