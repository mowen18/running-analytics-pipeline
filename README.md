# Running Analytics Pipeline

Incremental analytics pipeline evaluating whether aerobic running efficiency
is improving over time, using Strava activities and historical hourly weather.
Pipeline-first: the deliverables are ingestion, warehouse models, metrics,
tests, and docs — the dashboard is a thin cap.

**Full spec:** [docs/PROJECT_PLAN.md](docs/PROJECT_PLAN.md) (decisions D1–D21 are locked).
**Status:** Phase 0 — infrastructure and Strava auth.

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
make up          # start Postgres
make down        # stop Postgres
make bootstrap   # (re-)apply sql/bootstrap.sql — idempotent
make athlete     # print the authenticated athlete profile
make test        # pytest (all external HTTP mocked)
make lint        # ruff check
make format      # ruff format
```

## Warehouse layout

Five schemas (decision D3): `raw_strava`, `raw_weather`, `staging`,
`intermediate`, `analytics`. Created idempotently by
[`sql/bootstrap.sql`](sql/bootstrap.sql) on first container init.
