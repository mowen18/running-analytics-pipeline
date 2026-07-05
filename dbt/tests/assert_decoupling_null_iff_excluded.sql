-- Decoupling and the exclusion reason are mutually exclusive and
-- jointly exhaustive: every candidate either has a computed value or a
-- reason it doesn't (acceptance criterion 4 — never both, never
-- neither).
select activity_id, decoupling_pct, exclusion_reason
from {{ ref('int_run_drift_halves') }}
where (decoupling_pct is null) != (exclusion_reason is not null)
