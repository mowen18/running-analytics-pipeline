-- The exclusion reason and the D9 flag are two encodings of one rule
-- set: eligible runs must carry no reason, ineligible runs must carry
-- exactly one. A drift between them means the CASE ladder and
-- fct_runs.easy_run_eligible no longer implement the same D9.
select activity_id, is_qualifying, exclusion_reason
from {{ ref('int_run_efficiency') }}
where is_qualifying = (exclusion_reason is not null)
