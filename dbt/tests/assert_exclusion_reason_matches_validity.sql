-- The exclusion reason and the validity flag are two encodings of one
-- rule set (D9 revised v1.1): valid runs must carry no reason, invalid
-- runs must carry exactly one. A drift between them means the CASE
-- ladder and is_valid no longer implement the same rules.
select activity_id, is_valid, exclusion_reason
from {{ ref('int_run_efficiency') }}
where is_valid = (exclusion_reason is not null)
