# Running Analytics Pipeline

Incremental analytics pipeline evaluating whether aerobic running efficiency
is improving over time, using Strava activities and historical hourly weather.
Pipeline-first: the deliverables are ingestion, warehouse models, metrics,
tests, and docs — the dashboard is a thin cap.

**Questions this answers** (that standard Strava/Apple Fitness views can't):

* Is pace at a comparable heart rate improving over time?
* How does running efficiency vary under different weather conditions?
* Is cardiac drift decreasing during longer runs?
* How is weekly volume changing alongside these efficiency measures?

**Full spec:** [docs/PROJECT_PLAN.md](docs/PROJECT_PLAN.md) (decisions D1–D21 are
locked; Revision v1.1 supersedes D9 and amends D15; Revision v1.2 corrects
the dbt layering — output-invariant).
**Status:** all six phases complete (Release 1.1 + presentation layer).

## Architecture

```text
Strava API ──────────────┐
                         │
Open-Meteo API ──────────┼──> Python ingestion (src/running_pipeline)
                         │          │
                         │          v
                         │   PostgreSQL container
                         │   running_analytics_db (port 5433)
                         │          │
                         │          v
                         │    dbt transformations (dbt/)
                         │          │
                         │          v
                         └────> Analytics marts
                                    │
                                    v
                              Streamlit app (app/)
```

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
make backfill-coordinates # resolve run-start coordinates (payload, else polyline)
make sync-weather     # fetch hourly weather for outdoor runs not yet covered
make reconcile-weather # re-fetch weather even for already-cached hours
make sync-streams     # backfill activity streams for drift-eligible runs
make app              # launch the Streamlit dashboard (three views)
make all              # full refresh: every sync, then dbt build
make dbt-build        # build all dbt models and run their tests
make dbt-test         # dbt tests only
make dbt-freshness    # source freshness (raw fetched_at ages)
make dbt-docs         # generate + serve dbt documentation locally
make dbt-dag          # regenerate the dbt DAG diagram embedded in this README
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

**Map-privacy fallback.** Strava's "hide entire map" setting strips
`start_latlng` from API payloads — even the owner's — so
`make backfill-coordinates` resolves each run's start coordinate with
explicit provenance in `raw_strava.activity_coordinates`: the payload's
`start_latlng` when present (free), else the first decoded point of the
detail endpoint's route polyline (one API call per run, resumable with
the same rate-limit contract as the other backfills), else an explicit
`unavailable` row. Weather eligibility and dbt staging prefer the
resolved coordinate over the payload.

## Warehouse models (dbt)

<!-- dbt-dag:start -->
```mermaid
flowchart LR

    subgraph sources["Sources"]
        source_running_analytics_raw_strava_activities[("raw_strava.activities")]
        source_running_analytics_raw_strava_activity_coordinates[("raw_strava.activity_coordinates")]
        source_running_analytics_raw_strava_streams[("raw_strava.streams")]
        source_running_analytics_raw_strava_sync_state[("raw_strava.sync_state")]
        source_running_analytics_raw_weather_hourly[("raw_weather.hourly")]
    end

    subgraph seeds["Seeds"]
        seed_running_analytics_temperature_bands(["temperature_bands"])
    end

    subgraph staging["Staging"]
        model_running_analytics_stg_strava__activities["stg_strava__activities"]
        model_running_analytics_stg_weather__hourly["stg_weather__hourly"]
    end

    subgraph intermediate["Intermediate"]
        model_running_analytics_int_run_efficiency["int_run_efficiency"]
        model_running_analytics_int_run_stream_samples["int_run_stream_samples"]
        model_running_analytics_int_runs_with_weather["int_runs_with_weather"]
    end

    subgraph core["Core"]
        model_running_analytics_fct_drift_candidates["fct_drift_candidates"]
        model_running_analytics_fct_runs["fct_runs"]
    end

    subgraph marts["Marts"]
        model_running_analytics_mart_drift_trend["mart_drift_trend"]
        model_running_analytics_mart_efficiency_by_temp_band["mart_efficiency_by_temp_band"]
        model_running_analytics_mart_efficiency_trend["mart_efficiency_trend"]
        model_running_analytics_mart_run_drift["mart_run_drift"]
        model_running_analytics_mart_run_quality["mart_run_quality"]
        model_running_analytics_mart_weekly_training["mart_weekly_training"]
    end

    model_running_analytics_fct_drift_candidates --> model_running_analytics_mart_run_drift
    model_running_analytics_fct_drift_candidates --> model_running_analytics_mart_run_quality
    model_running_analytics_fct_runs --> model_running_analytics_mart_efficiency_by_temp_band
    model_running_analytics_fct_runs --> model_running_analytics_mart_efficiency_trend
    model_running_analytics_fct_runs --> model_running_analytics_mart_run_drift
    model_running_analytics_fct_runs --> model_running_analytics_mart_run_quality
    model_running_analytics_fct_runs --> model_running_analytics_mart_weekly_training
    model_running_analytics_int_run_efficiency --> model_running_analytics_fct_drift_candidates
    model_running_analytics_int_run_efficiency --> model_running_analytics_fct_runs
    model_running_analytics_int_run_stream_samples --> model_running_analytics_fct_drift_candidates
    model_running_analytics_int_runs_with_weather --> model_running_analytics_int_run_efficiency
    model_running_analytics_mart_run_drift --> model_running_analytics_mart_drift_trend
    model_running_analytics_mart_weekly_training --> model_running_analytics_mart_efficiency_trend
    model_running_analytics_stg_strava__activities --> model_running_analytics_int_runs_with_weather
    model_running_analytics_stg_weather__hourly --> model_running_analytics_int_runs_with_weather
    seed_running_analytics_temperature_bands --> model_running_analytics_mart_efficiency_by_temp_band
    seed_running_analytics_temperature_bands --> model_running_analytics_mart_efficiency_trend
    seed_running_analytics_temperature_bands --> model_running_analytics_mart_run_quality
    source_running_analytics_raw_strava_activities --> model_running_analytics_stg_strava__activities
    source_running_analytics_raw_strava_activity_coordinates --> model_running_analytics_stg_strava__activities
    source_running_analytics_raw_strava_streams --> model_running_analytics_fct_drift_candidates
    source_running_analytics_raw_strava_streams --> model_running_analytics_int_run_stream_samples
    source_running_analytics_raw_weather_hourly --> model_running_analytics_stg_weather__hourly
```
<!-- dbt-dag:end -->

The dbt project lives in `dbt/` (decision D4) and is driven entirely
through the Make targets above; `dbt/profiles.yml` is auto-copied from
the committed example on first run and reads connection values from the
same `.env` contract as the Python pipeline — no separate credentials.

| Layer | Model | Schema | Grain |
|---|---|---|---|
| Staging | `stg_strava__activities` | `staging` | one row per activity, any sport type |
| Staging | `stg_weather__hourly` | `staging` | one row per D7 cell + UTC hour, metric & imperial units |
| Intermediate | `int_runs_with_weather` | `intermediate` | one row per running activity + nearest qualifying observation |
| Intermediate | `int_run_efficiency` | `intermediate` | one row per running activity — derived measures + efficiency and validity verdict (feeds `fct_runs`) |
| Core | `fct_runs` | `analytics` | one row per running activity — the mart-facing contract: measures, weather, validity + efficiency |
| Mart | `mart_weekly_training` | `analytics` | one row per training week |
| Mart | `mart_efficiency_trend` | `analytics` | one row per week + 28-day rolling median |
| Mart | `mart_efficiency_by_temp_band` | `analytics` | one row per D14 temp band (+ explicit weather-unavailable row) |
| Mart | `mart_run_quality` | `analytics` | one row per running activity + quality verdicts (validity, band, drift) |
| Seed | `temperature_bands` | `analytics` | the D14 bands, defined once, joined by range everywhere |
| Intermediate | `int_run_stream_samples` | `intermediate` | one row per activity + aligned stream sample |
| Core | `fct_drift_candidates` | `analytics` | one row per drift candidate + halves and exclusion verdict |
| Mart | `mart_run_drift` | `analytics` | one row per analyzed drift run |
| Mart | `mart_drift_trend` | `analytics` | one row per week of drift runs + rolling median |

Conventions worth knowing: the running-activity filter
(Run/TrailRun/VirtualRun) is applied after staging, never in it; weather
matches the *nearest* observation that actually carries measurements
(explicit "archive had no data" rows never match) and only counts as
matched within 60 minutes of the run's start; training weeks are local
wall-clock (`week_start_date` = Monday of the local week); metric
thresholds (the D9 run-validity rules as revised by v1.1, the 45-minute
long-run definition) are dbt vars, never inline SQL. Every measurement column carries an explicit
unit suffix, and missing HR/weather stays NULL through every layer.

**Missing weather is explicit, never zero.** Hours the archive has no data
for (recent runs fall inside its ~5-day publication delay) are stored as
rows with NULL measurements and the original payload preserved; later
incremental syncs re-request those hours until data appears. A failed
request for one location never fails the sync — it is logged, counted in
`failed_batches`, and retried next run. Exact coordinates are never logged;
only 2-decimal cell keys appear in logs and stored keys.

## Metric definitions

**Aerobic efficiency (D10)** — the project's primary metric:

```text
aerobic_efficiency_m_per_heartbeat = speed_m_per_minute / average_hr_bpm
```

Approximate meters traveled per heartbeat. Higher = faster at the same
heart rate, or a lower heart rate at the same speed. **This is an
observational signal, not proof of physiological improvement.** The
approved framing is *"pace-at-heart-rate efficiency has increased across
runs with valid heart-rate data"* — never *"the metric proves aerobic
fitness improved."* Weather, terrain, sleep, and measurement noise all
move it, and **intensity mix is not controlled for**: the metric already
normalizes by HR, so hard efforts and races feed the same aggregates,
with average HR displayed alongside for context.

**Run validity (D9, revised by v1.1)** — a run feeds every efficiency
aggregate when all of the following hold (each threshold is a dbt var,
editable in `dbt/dbt_project.yml` without touching model SQL). There is
no intensity ceiling and no race/workout exclusion:

| Rule | Default |
|---|---|
| Heart-rate data present | required |
| Average HR within instrument-sanity band | 90–200 bpm |
| Pace within sanity bounds | 4:00–20:00 min/mi |
| Moving time | ≥ 15 min |

Invalid runs are never silently dropped: `int_run_efficiency` gives
every excluded run a human-readable `exclusion_reason` (the first failing
rule in a documented priority order), carried through `fct_runs` and
`mart_run_quality`.

**Weekly statistics (D11, D12)** — the weekly summary statistic is the
**median** efficiency across valid runs (mean shown as secondary);
a week is trend-worthy only with ≥ 2 valid runs (`is_sufficient`).
**Trend (D13)** — a 28-day rolling median over run-level efficiency
smooths single-week noise. **Temperature bands (D14)** — < 50 °F,
50–70 °F, > 70 °F, defined once in the `temperature_bands` seed and
joined by range; valid runs without matched weather appear in an
explicit *weather unavailable* row rather than vanishing from the
comparison.

## Stream ingestion and cardiac drift

`make sync-streams` backfills time-series streams (time, heart rate,
smoothed velocity, moving flag, grade) for drift-eligible runs per D15:
running activity, heart rate present, moving time ≥ 45 min, within the
historical window. The backfill is **resumable by construction**: each
activity's outcome commits as its own row in `raw_strava.streams` with
an explicit status — `success` and `unavailable` (Strava has no streams
for that activity; that never changes) are terminal, `failed` is retried
automatically next run, and an absent row means not yet attempted. At
most `STREAM_MAX_ACTIVITIES_PER_RUN` (default 50) activities per
invocation; rate limits stop the run cleanly between fetches with the
same exit-code-3 contract as the other syncs.

**Cardiac drift (decoupling)** — per D16, each analyzed run drops
non-moving samples, trims the first 10 minutes (warm-up) and final
5 minutes (cool-down), requires ≥ 30 minutes remaining, splits the
window into two equal-duration halves, and computes efficiency per half:

```text
decoupling_pct = (first_half_efficiency − second_half_efficiency)
                 / first_half_efficiency × 100
```

**Sign convention (D17): positive = efficiency declined in the second
half; near zero = stable; negative = the second half improved.** A
rising decoupling trend over comparable long runs is the observational
signal of interest — never proof of a fitness change on its own.

Coverage and pause thresholds (the two checks D16 leaves unquantified)
are dbt vars: average sample spacing in the window ≤ 3 s, non-moving
share ≤ 25 %. Every drift candidate that can't be analyzed carries a
deterministic exclusion reason in `fct_drift_candidates`; drift trend
weeks below the D12 run count are flagged `is_sufficient = false` and
hidden by the dashboard, never deleted.

## Dashboard

`make app` serves exactly three Streamlit views (decision D19):
**Aerobic Efficiency** (weekly + 28-day rolling trend, temperature-band
comparison), **Weekly Training** (mileage, moving time, run counts), and
**Cardiac Drift** (run-level decoupling with the rolling trend). The app
is deliberately thin: it reads **only the `analytics` schema** — a rule
enforced by an allow-list in the code and a test that fails if any other
schema is ever named — and contains no business logic; every metric,
threshold, and flag is computed and tested in dbt. Sample counts appear
beside every statistic, insufficient weeks are flagged and excluded from
trend lines but never hidden from tables, and each empty view explains
exactly what data would populate it.

## Data-quality principles

1. **Missing never means zero.** Absent HR, weather, or streams stays
   NULL (or an explicit status row) through every layer, down to the
   dashboard's empty states.
2. **Raw data stays recoverable.** Full API payloads live in JSONB next
   to the typed columns that ingestion itself needs; remodeling is a
   re-transform, never a re-download.
3. **Exclusion is explained, never silent.** Every ineligible run
   carries a human-readable reason; every aggregate carries its sample
   count.
4. **Idempotency everywhere.** Re-running any sync or build converges;
   nothing duplicates and nothing is lost to interruption.

## Known limitations

* **Long runs are currently treadmill runs**, so drift rows and
  most valid runs carry no weather — correct behavior (indoor
  runs have no meaningful outdoor weather), but it keeps the
  temperature-band comparison sparse until valid outdoor runs
  accumulate.
* Activities uploaded or edited **more than 14 days after they
  occurred** are only caught by `make reconcile`, not incremental sync.
  (The July 2026 heart-rate re-import was ingested exactly this way:
  old-dated re-uploads are invisible to the incremental window.)
* Open-Meteo's archive runs **~5 days behind**; recent runs carry
  explicit NULL weather rows that self-heal on later syncs.
* The history is **short** (April 2026 onward): weekly sufficiency and
  rolling medians work, but long-horizon trend claims need more months
  of data.
* The **dashboard screenshots** in `images/` are still pending capture
  now that the marts are populated. (dbt lineage is rendered directly
  in this README via `make dbt-dag`.)
