# CLAUDE.md

## Source of truth
- The full spec is docs/PROJECT_PLAN.md. Read it before starting work.
- Decisions D1–D21 in the plan are locked. If a task conflicts with
  one, stop and ask — do not silently deviate.

## Current status
- Phase 0 is complete. Phase 1 is next

## Conventions
- Postgres: running_analytics_db / running_user / host port 5433
- Schemas: raw_strava, raw_weather, staging, intermediate, analytics
- Never commit secrets, tokens, .env, or exact coordinates.
- Never log access or refresh tokens.
- If reality doesn't match the plan mid-task, stop and surface it.

## Commands
- Activate the venv first: `source .venv/bin/activate` (Python 3.13)
- Test:    `make test`    (pytest; all external HTTP mocked)
- Lint:    `make lint`    (ruff check src tests)
- Format:  `make format`  (ruff format src tests)
- DB:      `make up` / `make down` / `make bootstrap`
- CLI:     `running-pipeline athlete` / `running-pipeline authorize`
- Rotated Strava tokens live in `.secrets/strava_tokens.json` (gitignored,
  0600). The STRAVA_REFRESH_TOKEN in .env is bootstrap-only and goes stale
  after the first refresh — that is by design, not a bug.