# Running Analytics Pipeline

Incremental analytics pipeline evaluating whether aerobic running efficiency
is improving over time, using Strava activities and historical hourly weather.
Pipeline-first: the deliverables are ingestion, warehouse models, metrics,
tests, and docs — the dashboard is a thin cap.

**Full spec:** [docs/PROJECT_PLAN.md](docs/PROJECT_PLAN.md) (decisions D1–D21 are locked).
**Status:** Phase 3 complete — ingestion plus dbt staging/intermediate/core models. Phase 4 (efficiency metrics) is next.

## Prerequisites

- Docker Desktop
- Python 3.13 (`brew install python@3.13`)
- A [Strava API application](https://www.strava.com/settings/api) (free)

## Setup

```bash
# 1. Virtual environment + dependencies
python3.13 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 2. Configuration — fill in your Strava app credentials and a DB password
cp .env.example .env

# 3. Database (Postgres 17 on host port 5433; schemas created on first boot)
docker compose up -d

# 4. One-time Strava authorization (browser flow, ~30 seconds)
running-pipeline authorize

# 5. Verify authenticated access
running-pipeline athlete
```

## Environment variables

All configuration lives in `.env` (gitignored); the full annotated contract is
[`.env.example`](.env.example). Highlights:

| Variable | Purpose |
|---|---|
| `STRAVA_CLIENT_ID` / `STRAVA_CLIENT_SECRET` | From your Strava API app settings |
| `STRAVA_REFRESH_TOKEN` | Optional bootstrap only — after the first refresh, the rotated token in `.secrets/strava_tokens.json` is authoritative |
| `POSTGRES_*` | Database connection (decision D2: `running_analytics_db` / `running_user` / port 5433) |
| `SYNC_START_DATE`, `SYNC_OVERLAP_DAYS` | Ingestion window (decisions D5, D6 — used from Phase 1) |
| `WEATHER_REQUEST_BUDGET`, `WEATHER_BATCH_GAP_DAYS` | Optional weather-sync bounds (Phase 2). Open-Meteo needs **no API key** — there are no weather credentials |

## Token handling

Strava rotates the refresh token on every refresh. The pipeline persists the
newest access/refresh/expiry trio to `.secrets/strava_tokens.json`
(gitignored, `0600` permissions, atomic writes) immediately after every
refresh. Tokens are never logged. If the file is lost, re-run
`running-pipeline authorize`.

## Commands

```bash
make up               # start Postgres
make down             # stop Postgres
make bootstrap        # (re-)apply every sql/*.sql — idempotent
make athlete          # print the authenticated athlete profile
make sync-activities  # incremental Strava activity sync (14-day overlap)
make reconcile        # full reconciliation from SYNC_START_DATE
make sync-weather     # fetch hourly weather for outdoor runs not yet covered
make reconcile-weather # re-fetch weather even for already-cached hours
make dbt-build        # build all dbt models and run their tests
make dbt-test         # dbt tests only
make dbt-freshness    # source freshness (raw fetched_at ages)
make dbt-docs         # generate + serve dbt documentation locally
make test             # pytest (all external HTTP mocked; DB-integration
                      # tests skip visibly when Postgres is down)
make lint             # ruff check
make format           # ruff format
```

## Warehouse layout

Five schemas (decision D3): `raw_strava`, `raw_weather`, `staging`,
`intermediate`, `analytics`. Schemas and tables are created idempotently by
the [`sql/`](sql/) scripts on first container init (or `make bootstrap`).
Phase 1 owns `raw_strava.activities` — one row per activity, full API
payload in JSONB with sync-critical fields promoted to typed columns
(`activity_id` PK, `start_date_utc`, `activity_type`) — and
`raw_strava.sync_state`, which holds per-job sync watermarks. Phase 2 owns
`raw_weather.hourly` — one row per normalized location and UTC hour, typed
measurement columns plus the original per-hour payload in JSONB, unique on
`(location_key, weather_timestamp)`.

## Incremental sync strategy

`make sync-activities` loads every activity started on or after
`SYNC_START_DATE` (D5: 2024-01-01). Re-runs are idempotent: rows upsert by
`activity_id`, and rows whose payload is unchanged are skipped without
being rewritten, so inserted / updated / skipped counts are measured, not
inferred.

Each successful run records its own UTC start time as a watermark in
`raw_strava.sync_state`. The next incremental run re-fetches from
`watermark − SYNC_OVERLAP_DAYS` (D6: 14 days), so late uploads and recent
edits inside that window are captured automatically. One documented
limitation: the Strava list API filters on activity *start date*, so an
activity uploaded or edited more than 14 days after it occurred is only
caught by `make reconcile`, which re-fetches the whole historical window
on demand.

Transient API failures retry with bounded backoff (1s/2s/4s). When usage
approaches Strava's reported rate limits (≥90% of the 15-minute or daily
read limit), the sync stops cleanly: completed pages stay committed, the
watermark is not advanced, and the command exits with code 3 so the
interruption is visible — the next run simply re-covers the window. Failed
or interrupted runs never advance the watermark. Counts are logged on
every run; token values never are.

## Weather ingestion

`make sync-weather` attaches hourly weather (Open-Meteo historical archive,
decision D8) to each **outdoor run**: sport type `Run`/`TrailRun`, start
coordinates present, and Strava's `trainer` flag not set. Indoor and
virtual runs are excluded by design — they have no location, and outdoor
weather would be wrong for them — and are reported explicitly as
`runs_without_location`. Open-Meteo requires **no API key**; a per-sync
request budget (`WEATHER_REQUEST_BUDGET`) and 429 handling keep usage far
below its ~10k requests/day free tier, with the same stop-cleanly / exit
code 3 contract as the activity sync.

**Timezone handling:** everything is UTC end to end. Archive requests pass
`timezone=UTC`, returned hourly timestamps are stored as `timestamptz`,
and a run is matched to the observation at its start hour —
`date_trunc('hour', start_date_utc)` — never to a daily aggregate.

**The table is the cache.** There is no separate cache layer and no
watermark: each sync derives the location-hours eligible runs need,
subtracts what `raw_weather.hourly` already holds (unique on
`(location_key, weather_timestamp)`; coordinates are rounded to 2 decimal
places, a ~1.1 km cell, per decision D7), and batches the remainder into
one archive request per location and contiguous date range. Re-runs are
idempotent and repeated runs in the same cell hit the cache with zero
requests.

## Warehouse models (dbt)

The dbt project lives in `dbt/` (decision D4) and is driven entirely
through the Make targets above; `dbt/profiles.yml` is auto-copied from
the committed example on first run and reads connection values from the
same `.env` contract as the Python pipeline — no separate credentials.

| Layer | Model | Schema | Grain |
|---|---|---|---|
| Staging | `stg_strava__activities` | `staging` | one row per activity, any sport type |
| Staging | `stg_weather__hourly` | `staging` | one row per D7 cell + UTC hour, metric & imperial units |
| Intermediate | `int_runs_with_weather` | `intermediate` | one row per running activity + nearest qualifying observation |
| Core | `fct_runs` | `analytics` | one row per running activity, derived measures + eligibility flags |

Conventions worth knowing: the running-activity filter
(Run/TrailRun/VirtualRun) is applied after staging, never in it; weather
matches the *nearest* observation that actually carries measurements
(explicit "archive had no data" rows never match) and only counts as
matched within 60 minutes of the run's start; training weeks are local
wall-clock (`week_start_date` = Monday of the local week); metric
thresholds (D9 easy-run rules, the 45-minute long-run definition) are
dbt vars, never inline SQL. Every measurement column carries an explicit
unit suffix, and missing HR/weather stays NULL through every layer.

**Missing weather is explicit, never zero.** Hours the archive has no data
for (recent runs fall inside its ~5-day publication delay) are stored as
rows with NULL measurements and the original payload preserved; later
incremental syncs re-request those hours until data appears. A failed
request for one location never fails the sync — it is logged, counted in
`failed_batches`, and retried next run. Exact coordinates are never logged;
only 2-decimal cell keys appear in logs and stored keys.
