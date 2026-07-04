# Running Analytics Pipeline

Incremental analytics pipeline evaluating whether aerobic running efficiency
is improving over time, using Strava activities and historical hourly weather.
Pipeline-first: the deliverables are ingestion, warehouse models, metrics,
tests, and docs — the dashboard is a thin cap.

**Full spec:** [docs/PROJECT_PLAN.md](docs/PROJECT_PLAN.md) (decisions D1–D21 are locked).
**Status:** Phase 1 complete — activity ingestion with incremental sync. Phase 2 (weather) is next.

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
`raw_strava.sync_state`, which holds per-job sync watermarks.

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
