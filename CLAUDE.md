# CLAUDE.md

## Source of truth
- The full spec is docs/PROJECT_PLAN.md plus revision addendums in
  docs/decisions/ (v1.5 onward). Read them before starting work.
- Decisions D1–D22 in the plan are locked (D18 as revised by the v1.5
  addendum). If a task conflicts with one, stop and ask — do not
  silently deviate.

## Current status
- Revision v1.1 is implemented: efficiency aggregates cover every run
  with valid HR data (`is_valid` — HR present, 90–200 bpm, pace
  4:00–20:00, ≥15 min). easy_run_eligible / easy_hr_max and the
  "qualifying easy runs" vocabulary are gone; marts expose
  valid_run_count etc. Drift candidacy is ≥45 min moving + HR present
- Revision v1.2 is implemented: layering is staging → intermediate →
  core → marts. int_run_efficiency computes measures + validity /
  efficiency and feeds fct_runs (37 cols; original 34 unchanged); marts
  read core/seeds/marts only; int_run_drift_halves is now core
  fct_drift_candidates (analytics schema). is_valid := exclusion_reason
  is null; layering enforced by tests/test_dbt_layering.py. source()
  lives in staging only, except raw_strava.streams readable from
  intermediate (int_run_stream_state feeds fct_drift_candidates).
- Revision v1.3 is implemented: trend-mart rolling columns have static
  names (rolling_median_efficiency / rolling_valid_run_count in
  mart_efficiency_trend; rolling_median_decoupling_pct /
  rolling_drift_run_count in mart_drift_trend) — trend_window_days
  changes the window, never the interface. The D14 band range predicate
  renders from the temperature_band_range macro (the seed stays the
  sole bounds definition). fct_drift_candidates.activity_id carries a
  relationships test to fct_runs (proven red on an orphan row first).
- Revision v1.4 is implemented (addendum in docs/PROJECT_PLAN.md): the
  45-min var split — the stream FETCH gate is
  stream_fetch_min_moving_minutes (20, settings field + dbt var, env
  STREAM_FETCH_MIN_MOVING_MINUTES); drift candidacy and
  long_run_eligible keep 45 unchanged. D22 pace-at-HR-band metric:
  hr_bands seed (10 bpm, joined by range via hr_band_range on
  round(hr_bpm)), int_band_window_samples + int_run_band_assessment
  (exclusion ladder, encoded once) → fct_band_candidates (its core
  projection) + fct_run_band_segments → mart_band_weekly →
  mart_band_trend; weekly statistic is the median across runs of
  run-level band medians (velocity space, pace derived); trims 5/2
  min, window ≥ 10 min of pooled moving dwell, dwell ≥ 5 min/band,
  coverage var reused from drift (also as the dwell cap). One
  deliberate layer-matrix widening, proven red first: seeds are
  allowed parents of intermediate models. Renders inside the Aerobic
  Efficiency view — D19's three-view cap is NOT amended; allow-list
  grew by exactly mart_band_trend (mart_band_weekly deliberately off
  it). Existing marts proven byte-identical pre-gate-change; band data
  for 20–45 min runs arrives only as post-merge `make sync-streams`
  backfill drains ('streams not yet loaded' until then).
- Airflow adoption (v1.5) is complete and merged to main
  (2026-07-16). Addendum (docs/decisions/v1.5-airflow-addendum.md,
  revising D18) adopted; Airflow 3.3.0 at ~/.venvs/airflow on Python 3.13.14;
  the running_pipeline DAG (orchestration/dags/running_pipeline_dag.py)
  mirrors `make all` daily 06:00 America/Chicago, proven on the real
  scheduler path (10/10 task successes, idempotent no-op counts).
  Airflow is a THIN scheduling and observability layer only; see the
  scope constraints below.
- Current phase: v1.6 + v1.6.1 merged to main (2026-07-20).
  mart_run_band_segments (run × band grain, explicit-column projection
  of core fct_run_band_segments + the hr_bands seed — no layer-matrix
  change; the app allow-list grew by exactly this name, red-first)
  feeds the band chart: one faint point per run per band under the
  28-day rolling median line, whose vertices key on window support
  (rolling_band_run_count >= ROLLING_LINE_MIN_WINDOW_RUNS, app-side
  constant, default 2) with segment-id path breaks — never bridging
  (v1.6.1 supersedes v1.6's "sufficient weeks only" line rule). D22's
  weekly definition and mart_band_weekly's output are unchanged,
  pinned by assert_band_weekly_matches_segment_mart (velocity space).
  Addendums: docs/decisions/v1.6-band-run-scatter.md + the v1.6.1
  entry appended to docs/PROJECT_PLAN.md.

## Scope constraints — Airflow adoption (v1.5)
- (a) Airflow owns no state — watermarks, per-item status rows, and
  destination-as-cache remain the pipeline's.
- (b) catchup=False and no templated date windows, because Strava
  filters by activity start date and interval-based windows would
  reintroduce the late-upload gap the 14-day overlap already solves.
- (c) tasks invoke existing Make targets unchanged — no pipeline code
  changes.
- (d) LocalExecutor-or-simpler, SQLite metadata DB, no
  Celery/Redis/Docker for Airflow in this release.
- (e) Airflow lives in its own venv, never in the project's
  dependencies.
- All DAG code must use the Airflow 3 API — schedule=, no
  schedule_interval, no execution_date.
- Exit-3 policy (addendum): CLI exit 3 = clean rate-limit stop →
  task SKIPPED (skip_on_exit_code=3), downstream none_failed; sync
  tasks call the CLI directly because make masks recipe exit codes —
  a narrow, documented amendment to constraint (c)'s letter.

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
- Coordinates: `make backfill-coordinates` resolves run starts into
  raw_strava.activity_coordinates (payload start_latlng, else detail
  polyline first point, else explicit 'unavailable'). Needed because
  Strava's "hide entire map" privacy setting strips start_latlng from
  ALL API payloads; weather eligibility and dbt staging prefer the
  resolved row. Run it before sync-weather (make all does)
- dbt:     `make dbt-build` / `make dbt-test` / `make dbt-freshness` /
  `make dbt-docs` (project in dbt/ per D4; profiles.yml auto-copied from
  the example, reads .env; metric thresholds are dbt vars in
  dbt_project.yml; layers map to the D3 schemas via the
  generate_schema_name override — do not remove it)
- App:     `make app` (Streamlit, three views per D19) / `make all`
  (every sync + dbt build)
- Airflow: `make airflow-install` (separate venv at ~/.venvs/airflow —
  never the project venv) / `make airflow-start` (airflow standalone,
  AIRFLOW_HOME=~/airflow, DAGs read from orchestration/dags)
- Airflow standalone first-start verified (2026-07-16, PATH fix in
  airflow-start: standalone respawns its components as bare `airflow`
  resolved via PATH, so the recipe must prepend $(AIRFLOW_VENV)/bin —
  absolute-path invocation alone is not enough)
- Rotated Strava tokens live in `.secrets/strava_tokens.json` (gitignored,
  0600). The STRAVA_REFRESH_TOKEN in .env is bootstrap-only and goes stale
  after the first refresh — that is by design, not a bug.

## Verifying chart changes

Any change that affects a rendered chart is verified by looking at the
rendered result, never by spec or schema validation alone.

Procedure:
1. Ensure Postgres is up and start the app (make app, port 8501).
2. Use the Playwright MCP tools to open the view, wait for the chart
   canvas to render, and take a screenshot.
3. Open the screenshot and check it against the change's intent before
   committing. State in the report what the image shows.

If the app cannot run (no database), fall back to chart.save PNG via
vl-convert and say so in the report.