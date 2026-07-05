# CLAUDE.md

## Source of truth
- The full spec is docs/PROJECT_PLAN.md. Read it before starting work.
- Decisions D1–D21 in the plan are locked. If a task conflicts with
  one, stop and ask — do not silently deviate.

## Current status
- Phases 0–2 are complete. Phase 3 (dbt staging and core models) is next
- All activities ingested so far are indoor (trainer=true, no coordinates),
  so `sync-weather` correctly reports eligible_runs=0 until the first
  outdoor GPS run — that is expected, not a bug

## Conventions
- Postgres: running_analytics_db / running_user / host port 5433
- Schemas: raw_strava, raw_weather, staging, intermediate, analytics
- Never commit secrets, tokens, .env, or exact coordinates.
- Never log access or refresh tokens.
- If reality doesn't match the plan mid-task, stop and surface it.

## Commands
- Activate the venv first: `source .venv/bin/activate` (Python 3.13)
- Test:    `make test`    (pytest; all external HTTP mocked; DB-integration
  tests run against a scratch database and skip visibly when Postgres is down)
- Lint:    `make lint`    (ruff check src tests)
- Format:  `make format`  (ruff format src tests)
- DB:      `make up` / `make down` / `make bootstrap`
- Sync:    `make sync-activities` (incremental) / `make reconcile` (full)
- Weather: `make sync-weather` (incremental by nature) /
  `make reconcile-weather` (re-fetch cached hours)
- CLI:     `running-pipeline athlete` / `running-pipeline authorize` /
  `running-pipeline sync-activities [--full]` /
  `running-pipeline sync-weather [--full]`
- Sync watermark lives in raw_strava.sync_state (last successful run's UTC
  start time); it advances only after a fully successful sync
- Weather has NO watermark and NO credentials: raw_weather.hourly is the
  cache (UNIQUE location_key + weather_timestamp); missing weather is a
  row with NULL measurements, never zero and never silently absent;
  everything is requested and matched in UTC
- Rotated Strava tokens live in `.secrets/strava_tokens.json` (gitignored,
  0600). The STRAVA_REFRESH_TOKEN in .env is bootstrap-only and goes stale
  after the first refresh — that is by design, not a bug.