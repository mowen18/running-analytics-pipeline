-- D23: motor assist breaks HR-effort comparability, so e-bike types
-- must never appear in the ride grain — and every row's sport_type must
-- come from the same var the grain filter renders, so the filter and
-- this pin can never drift apart under --vars overrides. Offending rows
-- are returned with their diagnostics.
select activity_id, sport_type
from {{ ref('fct_rides') }}
where sport_type in ('EBikeRide', 'EMountainBikeRide')
   or sport_type not in (
        {%- for ride_type in var('ride_sport_types') %}
        '{{ ride_type }}'{% if not loop.last %},{% endif %}
        {%- endfor %}
   )
