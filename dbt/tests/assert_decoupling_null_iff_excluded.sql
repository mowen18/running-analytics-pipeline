-- Decoupling and the exclusion reason are mutually exclusive and
-- jointly exhaustive: every candidate either has a computed value or a
-- reason it doesn't (acceptance criterion 4 — never both, never
-- neither).
select activity_id, decoupling_pct, exclusion_reason
from {{ ref('fct_drift_candidates') }}
where (decoupling_pct is null) != (exclusion_reason is not null)
