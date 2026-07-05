# CLAUDE.md

## Source of truth
- The full spec is docs/PROJECT_PLAN.md. Read it before starting work.
- Decisions D1–D21 in the plan are locked. If a task conflicts with
  one, stop and ask — do not silently deviate.

## Current status
- Phases 0–5 are complete (Release 1.1). Next: Phase 6 — Streamlit
  views (max 3, marts only, per D19) and portfolio docs
- Efficiency and drift marts are structurally empty of trend data until
  HR-carrying runs exist — see the no-HR note below; sync-streams
  likewise reports eligible=0 (D15 requires HR)
- All activities ingested so far are indoor (trainer=true, no coordinates),
  so `sync-weather` correctly reports eligible_runs=0 until the first
  outdoor GPS run — that is expected, not a bug
- No activity has heart-rate data (has_heartrate=false everywhere; the
  Apple Health → Strava sync carries no HR), so easy_run_eligible is
  false for the whole current history — also expected, not a bug

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
- Streams: `make sync-streams` (resumable; success/unavailable are
  terminal statuses in raw_strava.streams, failed retries next run)
- CLI:     `running-pipeline athlete` / `running-pipeline authorize` /
  `running-pipeline sync-activities [--full]` /
  `running-pipeline sync-weather [--full]`
- Sync watermark lives in raw_strava.sync_state (last successful run's UTC
  start time); it advances only after a fully successful sync
- Weather has NO watermark and NO credentials: raw_weather.hourly is the
  cache (UNIQUE location_key + weather_timestamp); missing weather is a
  row with NULL measurements, never zero and never silently absent;
  everything is requested and matched in UTC
- dbt:     `make dbt-build` / `make dbt-test` / `make dbt-freshness` /
  `make dbt-docs` (project in dbt/ per D4; profiles.yml auto-copied from
  the example, reads .env; metric thresholds are dbt vars in
  dbt_project.yml; layers map to the D3 schemas via the
  generate_schema_name override — do not remove it)
- Rotated Strava tokens live in `.secrets/strava_tokens.json` (gitignored,
  0600). The STRAVA_REFRESH_TOKEN in .env is bootstrap-only and goes stale
  after the first refresh — that is by design, not a bug.