# Running Analytics Pipeline — Finalized Project Plan

| | |
|---|---|
| **Status** | Finalized — approved for implementation |
| **Version** | 1.0 |
| **Date** | July 4, 2026 |
| **Repository** | `running-analytics-pipeline` |
| **MVP Definition** | Phases 0–4 (Release 1.0) |

---

## 1. Project Summary

### Objective

Build an incremental analytics pipeline that evaluates whether aerobic running efficiency is improving over time, focusing on questions that standard Strava and Apple Fitness views cannot answer:

* Is pace at a comparable heart rate improving?
* How does running efficiency vary under different weather conditions?
* Is cardiac drift decreasing during longer easy runs?
* How is weekly training volume changing alongside these efficiency measures?

### Primary Analytical Question

> Is aerobic efficiency improving over time under reasonably comparable effort and environmental conditions?

### Project Identity

The repository is **pipeline-first, not dashboard-first**. The primary deliverables are the ingestion system, warehouse models, metric definitions, tests, and documentation. The Streamlit app is a thin presentation layer capped at three views.

---

## 2. Decision Log

All previously open recommendations are now locked. Any change to these decisions requires a documented revision to this plan.

| # | Decision | Final Value |
|---|----------|-------------|
| D1 | Database infrastructure | Project-owned PostgreSQL Docker service; no dependency on Habit Focus Observatory container |
| D2 | Database configuration | `running_analytics_db` / `running_user` / host port **5433** / volume `running_postgres_data` |
| D3 | Schemas | `raw_strava`, `raw_weather`, `staging`, `intermediate`, `analytics` |
| D4 | dbt project location | `dbt/` subdirectory (not repository root); documented in README and Makefile |
| D5 | Historical ingestion window | Activities with `start_date_utc >= 2024-01-01`, configurable via `SYNC_START_DATE` |
| D6 | Incremental overlap window | **14 days**, configurable via `SYNC_OVERLAP_DAYS` |
| D7 | Coordinate normalization | Round latitude/longitude to **2 decimal places** (~1.1 km cell); `location_key = '{lat_2dp}_{lon_2dp}'` |
| D8 | Weather source & grain | Open-Meteo historical API, **hourly** grain; temperature, apparent temperature, relative humidity, wind speed |
| D9 | Easy-run eligibility (v1) | Avg HR ≤ `EASY_HR_MAX` (default **152 bpm**); moving time ≥ 30 min; not a race/workout; heart rate present; pace within 4:00–20:00 min/mi; avg HR within 90–200 bpm |
| D10 | Efficiency metric | `aerobic_efficiency_m_per_heartbeat = speed_m_per_minute / average_hr_bpm` |
| D11 | Weekly summary statistic | **Median** efficiency is primary; mean shown as secondary |
| D12 | Weekly data-sufficiency threshold | Minimum **2 qualifying easy runs** per week for trend display |
| D13 | Rolling trend window | **28-day rolling median** |
| D14 | Temperature bands | `< 50°F`, `50–70°F`, `> 70°F`; defined once in a dbt seed/macro, never repeated in model SQL |
| D15 | Stream eligibility | Run activity, moving time ≥ **45 min**, heart rate present, within historical window, not already loaded |
| D16 | Drift analysis window | Drop non-moving samples; exclude first **10 min** (warm-up) and final **5 min** (cooldown); require ≥ **30 min** remaining; split into two equal-duration halves |
| D17 | Decoupling sign convention | Positive = efficiency declined in second half (documented in README and dbt YAML) |
| D18 | Orchestration | Makefile + Python CLI |
| D19 | Dashboard constraint | Maximum **3 Streamlit views**; marts only, no raw-table queries, no SQL in app code |
| D20 | Cross-domain integration | Deferred stretch goal. If pursued, use **Option A: shared integration warehouse** with domain schemas |
| D21 | MVP boundary | Phases 0–4. Cardiac drift (Phase 5) is Release 1.1, not an MVP requirement |

---

## 3. Scope and Guardrails

### In Scope (Initial Project)

* Strava OAuth2 authentication with refresh-token rotation
* Incremental Strava activity ingestion with overlap-window sync
* Historical hourly weather ingestion (Open-Meteo)
* Project-owned PostgreSQL database
* dbt staging, intermediate, fact, and mart models with tests and documentation
* Pace-at-heart-rate efficiency metrics with explicit eligibility rules
* Weather-context analysis by temperature band
* Weekly training summaries
* Stream-level ingestion for qualifying runs (Release 1.1)
* Cardiac-drift calculations (Release 1.1)
* Thin Streamlit presentation layer (≤ 3 views)
* Automated pytest and dbt tests; reproducible local setup

### Explicitly Out of Scope

* Machine-learning models, performance predictions, race-time predictions
* Real-time processing
* Mobile application development
* Replication of standard Strava screens
* Complex cloud deployment

---

## 4. Target Architecture

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

### Infrastructure (Final)

The project owns its PostgreSQL Docker service. The Habit Focus Observatory compose file may be **copied as a template**, but its running container, database, credentials, and volume are **never dependencies** of this project.

```text
Container service: postgres
Database:          running_analytics_db
User:              running_user
Host port:         5433   (avoids conflict with Habit Focus Observatory on 5432)
Container port:    5432
Volume:            running_postgres_data
```

Running data is never written into `habit_focus_db`.

---

## 5. Repository Structure (Final)

```text
running-analytics-pipeline/
├── compose.yml
├── .env.example
├── .gitignore
├── Makefile
├── README.md
├── CLAUDE.md
├── pyproject.toml
├── requirements.txt
│
├── src/
│   └── running_pipeline/
│       ├── __init__.py
│       ├── config.py
│       ├── cli.py
│       ├── database.py
│       ├── strava_client.py
│       ├── weather_client.py
│       ├── activity_ingestion.py
│       ├── stream_ingestion.py
│       └── sync_state.py
│
├── sql/
│   └── bootstrap.sql
│
├── dbt/
│   ├── dbt_project.yml
│   ├── profiles.yml.example
│   ├── models/
│   │   ├── sources/
│   │   ├── staging/
│   │   ├── intermediate/
│   │   ├── core/
│   │   └── marts/
│   └── tests/
│
├── app/
│   └── streamlit_app.py
│
├── tests/
│   ├── test_activity_ingestion.py
│   ├── test_stream_ingestion.py
│   ├── test_weather_ingestion.py
│   ├── test_token_refresh.py
│   └── fixtures/
│
└── images/
```

Per D4, the dbt project lives in `dbt/` and all dbt commands are wrapped in Makefile targets so path handling never leaks into daily workflow.

---

# 6. Implementation Phases

## Phase 0 — Project and Infrastructure Setup

**Objective:** Create a self-contained local development environment and verify authenticated Strava access.

### Tasks

* [ ] Create the `running-analytics-pipeline` repository with `.gitignore`, `.env.example`, README stub, and dependency configuration
* [ ] Add project-owned `compose.yml` with PostgreSQL per D2, including a database healthcheck
* [ ] Create the five schemas per D3 via `sql/bootstrap.sql`
* [ ] Register a Strava API application; complete the initial OAuth authorization flow with read scope for the athlete's activities
* [ ] Implement token refresh logic; **persist the newest refresh token** returned by each auth response
* [ ] Store all secrets via environment variables / ignored local config only
* [ ] Add a minimal Strava API client and a CLI command that retrieves and prints athlete-profile information
* [ ] Add `CLAUDE.md` covering: virtual-environment setup, test command, formatting/linting commands, database and schema conventions, and rules against committing secrets

### Acceptance Criteria

1. `docker compose up -d` starts the project database, reachable on port 5433
2. The five expected schemas exist
3. A script can refresh credentials and retains the newest refresh token securely
4. A script retrieves the authenticated athlete's profile
5. A new developer can reproduce setup from repository documentation plus their own credentials

**Estimated effort:** 1–2 days

---

## Phase 1 — Strava Activity Ingestion

**Objective:** Load all relevant historical running activities and support safe, idempotent incremental synchronization.

### Raw Activity Table (Final)

```text
raw_strava.activities
- activity_id        bigint primary key
- start_date_utc     timestamptz
- activity_type      text
- payload            jsonb not null
- source_updated_at  timestamptz null
- fetched_at         timestamptz not null
```

The Strava activity ID is a relational column, not JSON-only. Indexes on `activity_id`, `start_date_utc`, `activity_type`.

### Tasks

* [ ] Implement paginated activity retrieval, limited to `SYNC_START_DATE` (D5: 2024-01-01) onward
* [ ] Preserve the complete API payload in JSONB; promote sync-critical metadata to typed columns
* [ ] Upsert by `activity_id` with ingestion timestamps
* [ ] Structured logging: pages requested, activities received, inserted / updated / skipped counts, API failures
* [ ] Implement overlap-window incremental sync per D6 (14 days): read last successful sync timestamp → subtract overlap → fetch → upsert → record sync result
* [ ] Support an explicit full-reconciliation command
* [ ] Bounded retries for transient API failures; read rate-limit headers and stop cleanly when limits approach
* [ ] Never log access or refresh tokens

### Acceptance Criteria

1. Every intended historical run exists in `raw_strava.activities`
2. Re-running ingestion creates no duplicates
3. Late uploads and recent edits are captured by the overlap window
4. A normal incremental run processes only the overlap window and newer data
5. Full reconciliation is available on demand
6. Auth and API failures produce actionable error messages

**Estimated effort:** 1 weekend

---

## Phase 2 — Weather Ingestion

**Objective:** Attach weather conditions representing the approximate time and location of each run.

**Design decision (final):** Weather is captured at **hourly** granularity matched to the run's start hour — never daily aggregates.

### Raw Weather Table (Final)

```text
raw_weather.hourly
- location_key            text        -- '{lat_2dp}_{lon_2dp}' per D7
- latitude                numeric
- longitude               numeric
- weather_timestamp       timestamptz
- temperature_c           numeric
- apparent_temperature_c  numeric
- relative_humidity_pct   numeric
- wind_speed_kph          numeric
- payload                 jsonb
- fetched_at              timestamptz
UNIQUE (location_key, weather_timestamp)
```

### Tasks

* [ ] Extract run start coordinates and timestamp; normalize coordinates per D7 (2-decimal rounding, ~1.1 km cell)
* [ ] Request historical hourly weather from Open-Meteo for each location-hour; batch multi-day requests where supported
* [ ] Cache previously requested location-hour combinations
* [ ] Provide `sync-weather` backfill and incremental commands
* [ ] Record missing weather **explicitly** (never as zero); document timezone handling
* [ ] Preserve original weather payload in JSONB

### Acceptance Criteria

1. Every eligible run has a matching or explicitly-missing weather record
2. Weather represents the run's start hour, not its date
3. Backfill re-runs create no duplicates
4. Repeated runs in similar locations hit the cache
5. Missing coordinates or unavailable weather never fail the whole pipeline

**Estimated effort:** 1 weekend

---

## Phase 3 — dbt Staging and Core Models

**Objective:** Convert raw API payloads into typed, tested, documented analytical models.

### Model Inventory

| Layer | Model | Grain |
|---|---|---|
| Source | `raw_strava.activities`, `raw_weather.hourly` | as ingested |
| Staging | `stg_strava__activities` | one row per activity |
| Staging | `stg_weather__hourly` | one row per location-hour |
| Intermediate | `int_runs_with_weather` | one row per run + nearest qualifying weather |
| Core | `fct_runs` | **one row per Strava running activity** |

`stg_strava__activities` exposes: activity id/name/type/sport type, UTC and local start times, timezone, distance (m), moving and elapsed time (s), elevation gain (m), average/max speed (m/s), average/max HR (bpm), `has_heartrate`, start coordinates, `fetched_at`. The running-activity filter rule is documented in the model YAML.

`stg_weather__hourly` exposes both metric and imperial units (°C/°F, kph/mph) with explicit unit suffixes.

`int_runs_with_weather` matches each run to the nearest hourly observation at the normalized location, records the match time-difference, and carries a weather-matched flag.

`fct_runs` derives: distance (mi), moving time (min), pace (min/mi), speed (m/min), elevation gain per mile, average HR, weather fields, week-start date, month, year, easy-run eligibility flag (per D9), long-run eligibility flag, weather-availability flag.

### dbt Tests (minimum set)

* Unique + not-null on `activity_id`
* Positive distance and moving time; `moving_time_seconds <= elapsed_time_seconds`
* Accepted HR range when present; null HR when source indicates unavailable
* Valid latitude/longitude ranges
* Unique location-hour weather key; relationship tests on weather joins
* Source freshness on ingestion timestamps
* No division-by-zero in derived pace/efficiency fields

### Acceptance Criteria

1. `dbt build` succeeds
2. `fct_runs` contains one row per qualifying run
3. All measurements have documented units
4. Missing HR and weather remain distinguishable from zero
5. Core models carry model- and column-level documentation
6. Tests fail when known-invalid fixtures are introduced

**Estimated effort:** 1 weekend

---

## Phase 4 — Aerobic-Efficiency Metrics

**Objective:** Measure changes in pace-at-heart-rate efficiency under comparable effort conditions.

### Metric (Final)

```text
aerobic_efficiency_m_per_heartbeat = speed_m_per_minute / average_hr_bpm
```

> Interpretation: approximate meters traveled per heartbeat. Higher = faster at the same HR, or lower HR at the same speed. This is an observational signal, not proof of physiological improvement — and all project language reflects that.

### Easy-Run Eligibility (Final, per D9)

All rules configurable via env/dbt vars; defaults:

* Average HR ≤ 152 bpm (`EASY_HR_MAX`)
* Moving time ≥ 30 minutes
* Not flagged as race or workout
* Heart-rate data present
* Sanity bounds: pace 4:00–20:00 min/mi, average HR 90–200 bpm

Ineligible runs receive an **exclusion reason**, never a silent filter.

### Models

| Model | Grain | Key contents |
|---|---|---|
| `int_run_efficiency` | one row per qualifying run | identifiers, pace/speed, avg HR, efficiency, weather fields, elevation, eligibility flags, exclusion reason |
| `mart_weekly_training` | one row per training week | mileage, moving time, run counts (total/easy/long), **median** efficiency (primary) + mean, avg weather, elevation, data-sufficiency flag (≥ 2 qualifying runs per D12) |
| `mart_efficiency_trend` | one row per week | weekly median efficiency, 28-day rolling median (D13), qualifying-run count, temperature band, avg temperature, sufficiency flag |
| `mart_efficiency_by_temp_band` | one row per temp band (+ period) | bands per D14: <50°F, 50–70°F, >70°F — defined once in a seed/macro |

### Analysis Language Standard

Approved framing: *"Pace-at-heart-rate efficiency has increased during qualifying easy runs under similar temperature conditions."*
Prohibited framing: *"The metric proves aerobic fitness improved."*

### Acceptance Criteria

1. Every efficiency value traces to documented source fields
2. Excluded runs carry a clear exclusion reason
3. Weekly metrics enforce the minimum qualifying-run count
4. Efficiency is comparable across weather bands
5. The trend is interpretable without manual run exclusion
6. Metric definitions appear in dbt YAML and the README

**Estimated effort:** 1–2 weekends

**→ Completion of Phase 4 = MVP complete (Release 1.0). The project is documented and portfolio-ready at this point.**

---

## Phase 5 — Stream Ingestion and Cardiac Drift (Release 1.1)

**Objective:** Use time-series activity streams to estimate pace-to-heart-rate decoupling during longer easy runs.

**Scope gate:** Begins only after the activity, weather, and efficiency pipeline is complete and tested.

### Stream Eligibility (Final, per D15)

Run activity · moving time ≥ 45 min · heart rate present · within historical window · not already loaded.

### Raw Stream Table (Final)

```text
raw_strava.streams
- activity_id             bigint primary key
- payload                 jsonb not null
- stream_types_requested  text[]
- sample_count            integer
- fetched_at              timestamptz
- ingestion_status        text        -- success / failed / unavailable
- error_message           text null
```

Stream types requested: time, heart rate, smoothed velocity, moving status, grade.

### Backfill Requirements

* [ ] Resumable: skips activities already loaded successfully; restartable without duplication
* [ ] Tracks failed and unavailable responses distinctly from not-yet-attempted
* [ ] Reads rate-limit headers and stops cleanly before exceeding limits
* [ ] Configurable max activities per invocation; logs last successfully processed activity
* [ ] Bounded backoff retries for transient failures

### Drift Calculation (Final, per D16–D17)

Eligibility: ≥ 45 min moving time; HR/time/velocity present; sufficient sample coverage; easy-run classification; no excessive pauses; no invalid HR or velocity values.

Analysis window: exclude non-moving samples → drop first 10 min (warm-up) → drop final 5 min (cooldown) → require ≥ 30 min remaining → split into two equal-duration halves → compute HR, speed, and efficiency per half.

```text
first_half_efficiency  = first_half_speed_m_per_min  / first_half_hr_bpm
second_half_efficiency = second_half_speed_m_per_min / second_half_hr_bpm

decoupling_pct = (first_half_efficiency - second_half_efficiency)
                 / first_half_efficiency * 100
```

Sign convention (stated in README and dbt YAML): **positive = declining efficiency in the second half**; near zero = stable; negative = second half improved.

### Models

| Model | Grain | Key contents |
|---|---|---|
| `int_run_stream_samples` | one row per activity + aligned sample index | elapsed seconds, HR, velocity, moving flag, grade, sample-valid flag |
| `int_run_drift_halves` | one row per qualifying run | per-half duration/speed/HR/efficiency, sample counts, coverage checks, eligibility + exclusion fields |
| `mart_run_drift` | one row per qualifying run | activity id, date, duration, distance, temperature, decoupling %, data-quality flags |
| `mart_drift_trend` | one row per week | median + rolling median decoupling, qualifying-run count, avg duration, avg temperature, sufficiency flag |

### Acceptance Criteria

1. Stream ingestion can be interrupted and resumed safely
2. Stream arrays are normalized into aligned sample rows
3. Drift calculations use the documented analysis window
4. Every excluded run has a deterministic exclusion reason
5. Unit tests validate the formula with synthetic stream fixtures
6. Manual inspection confirms several calculated runs are plausible
7. Drift trends are hidden for periods with insufficient qualifying runs

**Estimated effort:** 2–3 weekends

---

## Phase 6 — Presentation, Automation, and Documentation

**Objective:** Provide a small presentation layer and a reproducible operational workflow.

### Streamlit Views (exactly three, per D19)

| View | Contents |
|---|---|
| **1. Aerobic Efficiency** | Weekly/rolling efficiency trend, qualifying-run counts, temperature-band comparison, weather context, clear metric definition |
| **2. Weekly Training** | Weekly mileage, moving time, run/easy/long counts, optional elevation, optional HR-zone summary when source data is reliable |
| **3. Cardiac Drift** | Run-level decoupling, rolling drift trend, duration and weather context, data-quality and eligibility info |

Dashboard rules: marts only (no raw tables); no SQL/business logic in Streamlit where feasible; no duplication of standard Strava screens; sample counts and data sufficiency always shown; missing data explained, never silently dropped; observational trends never presented as causal.

### Orchestration (Final, per D18)

Makefile + CLI. No Airflow in v1 — added later only if it improves the actual workflow, not as a résumé keyword.

```bash
make up            make down          make bootstrap
make sync-activities   make sync-weather   make sync-streams
make dbt-build     make test          make app          make all
```

### Python Test Coverage

OAuth token refresh · rotated refresh-token persistence · activity pagination · upsert idempotency · overlap-window sync · weather caching · weather timestamp matching · stream-backfill resumability · stream-array alignment · drift eligibility · drift formula · API failure handling · rate-limit handling. All external HTTP is mocked in unit tests.

### README Contents

Problem statement · questions answered · architecture diagram · local setup · OAuth setup · environment-variable reference · schema overview · incremental-sync strategy · metric definitions · eligibility rules · data-quality assumptions · known limitations · example commands · dbt lineage image · dashboard screenshots · sample results using non-sensitive values.

### Acceptance Criteria

1. A new user can run the project from documented instructions
2. All tests and `dbt build` pass
3. The dashboard reads only prepared analytical models
4. The README clearly distinguishes observation from causation
5. Screenshots communicate the project without requiring the reviewer to run it
6. No credentials, exact home coordinates, or private activity payloads are committed

**Estimated effort:** 1 weekend

---

## Phase 7 — Cross-Domain Integration (Optional Stretch, Release 1.2)

**Objective:** Explore associations between running outcomes and Habit Focus Observatory data.

**Architectural constraint (final):** Both projects remain independently runnable. Per D20, if this phase is pursued, integration uses **Option A — a deliberately managed shared integration warehouse** with domain-specific schemas. (Exported-dataset and foreign-data-wrapper approaches were considered and rejected as the long-term path.)

### Potential Mart: `mart_run_recovery_context`

Grain: one row per run with prior-night / same-day habit and recovery context — run metrics, prior-night sleep, prior-day caffeine and exercise, self-reported energy/focus, data-completeness flags.

### Analytical Restrictions

Results are exploratory and correlational · missingness preserved explicitly · no causal inference · small samples documented · integration never delays completion of the main project.

### Acceptance Criteria

1. Both source projects remain independently reproducible
2. Cross-domain logic exists only in a documented integration layer
3. Missing observations remain distinct from logged zeros
4. The README describes the analysis as exploratory and correlational

---

# 7. Data-Quality Principles

1. **Missing does not mean zero.** Missing HR, weather, streams, or habit data stays null or explicitly unavailable.
2. **Raw data remains recoverable.** Source JSON is preserved while idempotency keys are exposed relationally.
3. **Every analytical model has a declared grain.** Documentation begins with the meaning of one row.
4. **Units are explicit.** Names distinguish m/mi, s/min, °C/°F, kph/mph.
5. **Derived metrics require eligibility rules.** Non-null columns alone never justify a calculation.
6. **Exclusions are explainable.** Exclusion reasons are stored, never silently filtered.
7. **Incremental ingestion is repeatable.** Re-runs never duplicate or corrupt data.
8. **Claims match evidence.** The project measures trends and associations, not medical or physiological certainty.

---

# 8. Privacy and Security Requirements

* No raw API responses, exact start/end coordinates, or `.env` files committed
* No home-location patterns exposed in screenshots
* No tokens logged; refresh-token persistence lives outside version control
* Sample or redacted data used in tests
* Coordinates masked/rounded in analytical models
* Fields excluded from public examples for privacy are documented

---

# 9. MVP Definition

The formal MVP is **Phases 0–4**. It is complete when the project can:

1. Authenticate with Strava
2. Incrementally ingest running activities
3. Attach hourly weather context
4. Transform data through dbt
5. Calculate documented pace-at-heart-rate efficiency
6. Produce weekly training and efficiency marts
7. Compare efficiency across temperature bands
8. Pass automated ingestion and dbt tests
9. Present architecture and findings clearly in the README

Cardiac drift is an advanced second release, **not** an MVP requirement. The project is documented and treated as complete after the MVP.

---

# 10. Release Milestones

| Release | Contents |
|---|---|
| **0.1 — Infrastructure & Auth** | Project-owned PostgreSQL, repo scaffolding, OAuth flow, token refresh, athlete-profile request |
| **0.2 — Activity Warehouse** | Historical backfill, incremental sync, raw activity storage, ingestion tests |
| **0.3 — Weather & Core dbt** | Hourly weather ingestion + caching, staging models, `fct_runs`, source and data-quality tests |
| **1.0 — Aerobic-Efficiency MVP** | Easy-run eligibility, run-level efficiency, weekly + weather-band marts, README docs, initial Streamlit views |
| **1.1 — Cardiac Drift** | Stream backfill, normalized samples, drift eligibility, decoupling, drift trend mart, drift dashboard view |
| **1.2 — Optional Integration** | Independent integration environment, habit/recovery context, exploratory combined marts |

---

# 11. Effort Estimate

| Phase | Estimated effort |
|---|---:|
| Phase 0 — Setup | 1–2 days |
| Phase 1 — Activity ingestion | 1 weekend |
| Phase 2 — Weather ingestion | 1 weekend |
| Phase 3 — dbt core models | 1 weekend |
| Phase 4 — Efficiency metrics | 1–2 weekends |
| Phase 5 — Streams and drift | 2–3 weekends |
| Phase 6 — Presentation and docs | 1 weekend |
| Phase 7 — Cross-domain integration | Optional |

**MVP (through Phase 4): ~4–6 part-time weekends. Full project through cardiac drift: ~6–8 part-time weekends.**

---

# 12. Portfolio Outcomes

The completed project supports resume claims such as:

* Built an incremental ELT pipeline ingesting authenticated Strava and historical weather data into a project-owned PostgreSQL warehouse
* Implemented idempotent API ingestion using paginated requests, overlap-window synchronization, relational keys, JSONB raw storage, and resumable backfills
* Modeled raw API payloads through tested dbt staging, intermediate, fact, and mart layers
* Developed documented aerobic-efficiency and cardiac-drift metrics from heart-rate, pace, weather, and stream-level time-series data
* Created a reproducible Docker-based development environment with automated pytest and dbt validation
* Designed a thin analytical application exposing domain-specific insights without duplicating source-platform functionality

---

# 13. Final Architectural Statement

The Running Analytics Pipeline owns its PostgreSQL Docker service. The Habit Focus Observatory configuration may be copied as a template, but its container, database, credentials, and volume are never dependencies of this project. Cross-domain analysis, if implemented, uses a deliberately designed integration environment only after both projects are independently complete.

## Revision v1.1 — 2026-07-05 — Remove intensity gating from efficiency aggregation

**Rationale:** D9's easy-HR ceiling excluded nearly all real runs, leaving the
trend charts structurally empty. Run-difficulty categorization was defining
far more behavior than it earned. The efficiency metric (D10) already
normalizes by HR; intensity mix is accepted as a displayed-not-filtered
noise source. Difficulty categorization is no longer a project priority.

**Revised decisions:**
- **D9 (revised):** "Easy-run eligibility" is replaced by **run-validity
  rules**. A run feeds all efficiency aggregates when: HR data present;
  avg HR within 90–200 bpm; pace within 4:00–20:00 min/mi; moving time
  ≥ 15 min. There is NO intensity ceiling and NO race/workout exclusion.
  `EASY_HR_MAX` / `easy_hr_max` is retired.
- **D12/D13 (unchanged mechanics):** sufficiency (≥2/week) and the 28-day
  rolling median now count valid runs, not "easy" runs.
- **D15 (revised):** drift candidacy = moving time ≥ 45 min + HR present.
  Easy classification is no longer a drift prerequisite.
- **Language standard (revised):** approved framing is "pace-at-heart-rate
  efficiency across runs with valid heart-rate data"; docs note that
  intensity mix is not controlled for.
- Exclusion reasons remain first-class (never silent), but the ladder now
  contains only data-validity rungs: no HR → HR out of sanity range →
  pace out of bounds → under minimum duration.

## Revision v1.2 — 2026-07-08 — Correct the dbt layering inversion

**Rationale:** The implemented dbt graph inverted the intended layering:
`fct_runs` (core) fed `int_run_efficiency` (intermediate), every mart read
the intermediate model, and core fed nothing downstream. The Phase 3/4
model inventories describe that inverted shape. This revision corrects
only the DIRECTION of the reference graph:

    before: stg_* -> int_runs_with_weather -> fct_runs -> int_run_efficiency
            -> {all six marts, int_run_drift_halves}
    after:  stg_* -> int_runs_with_weather -> int_run_efficiency -> fct_runs
            -> {mart_weekly_training, mart_efficiency_trend,
                mart_efficiency_by_temp_band, mart_run_quality, mart_run_drift};
            int_run_efficiency -> fct_drift_candidates
            -> {mart_run_drift, mart_run_quality}

The refactor is OUTPUT-INVARIANT: no metric formula, threshold, grain, or
value changes anywhere; all six marts stay byte-identical, and `fct_runs`
keeps its 34 columns byte-identical while additionally exposing the three
analytic columns so marts can read core.
Procedure note (added after Revision v1.4's verification postscript):
the baseline schema is RETAINED until the PR merges — or dumped to a
gitignored file — and dropping it is a post-merge cleanup step, so the
proof stays re-executable during review; the v1.4 audit could only
re-read its proof, not re-run it, because the baseline had already
been dropped.

**Revised decisions (design clarifications — no D-number is superseded;
D3 schemas, D4 dbt location, and D19 marts-only app reads are untouched):**

- **Layering (new):** model references follow staging → intermediate →
  core → marts. `int_run_efficiency` reads `int_runs_with_weather` and
  computes BOTH the derived measures (previously in `fct_runs`) and the
  D9/D10 analytic columns; `fct_runs` becomes an explicit-column core
  projection of `int_run_efficiency` — its previous 34 columns in the
  same order, plus `aerobic_efficiency_m_per_heartbeat`, `is_valid`,
  `exclusion_reason`. Enforced by a manifest-based layering test.
- **Strict mart matrix (new):** marts may reference core models, seeds,
  and other marts ONLY. The two existing mart-to-mart trend edges
  (`mart_efficiency_trend` ← `mart_weekly_training`,
  `mart_drift_trend` ← `mart_run_drift`) remain allowed.
- **fct_drift_candidates (relocation):** `int_run_drift_halves` moves to
  core as `fct_drift_candidates` — same SQL body, same
  one-row-per-drift-candidate grain, same columns; materialization
  follows the core folder config (view → table, schema `intermediate`
  → `analytics`). `mart_run_drift` and `mart_run_quality` read it there.
- **Documented sources exception (new):** stream payloads are
  deliberately unstaged (JSONB key/array probing; a staging pass would
  add no typing value), so intermediate AND core models may read
  `source('raw_strava', 'streams')` directly. This is the only
  sanctioned model read of a raw source outside staging.
- **is_valid single encoding (amends the v1.1 note):** `is_valid` is
  DEFINED as `exclusion_reason is null`; the exclusion-reason CASE
  ladder is the single encoding of the D9 (revised v1.1) validity
  rules. The independent boolean AND-chain and its equivalence test
  (`assert_exclusion_reason_matches_validity`) are retired; coverage is
  the ladder's own column tests plus this refactor's output-invariance
  comparison.
- **Model inventory (corrected):** the Phase 3/Phase 4 model tables are
  superseded on layer placement. Current shape — intermediate:
  `int_runs_with_weather`, `int_run_efficiency`,
  `int_run_stream_samples`; core: `fct_runs`, `fct_drift_candidates`;
  marts: unchanged (six). `int_run_efficiency` is UPSTREAM of
  `fct_runs`, not downstream.
- **Numbering note:** "Revision v1.x" numbers revisions of THIS document
  (v1.1 above, this block); "Release 1.x" numbers delivery milestones
  (Release 1.0 = MVP, Release 1.1 = cardiac drift, Release 1.2 = the
  optional Phase 7 stretch). Revision v1.2 is unrelated to Release 1.2.

### Revision v1.2 follow-up — 2026-07-08 — Streams exception restricted to intermediate

The fct_drift_candidates relocation silently carried its direct
`source('raw_strava', 'streams')` read into core, and the "Documented
sources exception" bullet above codified that widening ("intermediate
AND core"). Both were accidental. Verified inventory of what core read
from the source: `activity_id` (row absence = "streams not yet
loaded"), `ingestion_status` ("unavailable"/"failed" rungs), and a
payload key-existence probe on time/heartrate/velocity_smooth
("missing required stream types" rung) — none derivable from
int_run_stream_samples, which keeps only success rows and unnests to
sample grain (never-fetched / unavailable / failed / zero-samples all
collapse to zero rows there).

**Corrected rule (supersedes the sources-exception bullet above):**
source() is permitted in staging; the single exception is
raw_strava.streams, readable from INTERMEDIATE models only. Core and
marts contain zero source() reads. fct_drift_candidates takes its
stream state from the new activity-grain intermediate
`int_run_stream_state` (the former stream_state CTE, verbatim),
keeping output byte-identical. The layering guard encodes the
exception per-layer and per-source-table, and was proven to fail on
the core read before the fix.

## Revision v1.3 — 2026-07-08 — Trend mart columns: vars change behavior, never interface

**Rationale:** `mart_efficiency_trend` and `mart_drift_trend` rendered
`trend_window_days` into their rolling-column NAMES
(`rolling_28d_median_efficiency` and siblings under the default 28).
That couples the marts' schema contract to configuration: overriding
the var via `--vars` silently renames the columns, breaking marts.yml
(column docs and not_null tests) and the dashboard's column
references. A dbt var may change the VALUES a contract carries, never
the shape of the contract itself.

**Revised decision (amends column naming only — the D13 28-day default
and the window mechanics are unchanged):** the rolling columns carry
static names — `rolling_median_efficiency` / `rolling_valid_run_count`
in `mart_efficiency_trend`, and `rolling_median_decoupling_pct` /
`rolling_drift_run_count` in `mart_drift_trend`. The window length
remains the `trend_window_days` var and is referenced in the columns'
YAML descriptions. Output-invariance requirement: under default vars,
mart values are identical before and after; only the four column names
differ.

**Also in this revision (pure refactor, output-invariant):** the D14
temperature-band range predicate, previously hand-written in three
marts (`mart_efficiency_by_temp_band`, `mart_run_quality`,
`mart_efficiency_trend`), is rendered by a single macro,
`temperature_band_range(temperature_expression, bands_alias='bands')`.
The seed stays the sole definition of the band BOUNDS (D14); the macro
centralizes only the null-tolerant range-predicate rendering.
Call-site-specific conditions (`weather_available`, `not is_trainer`)
stay at the call sites. Built mart data is byte-identical before and
after; compiled SQL differs only in whitespace.

# Revision v1.4 — Pace-at-HR-Band Trend (Addendum)

Status: DRAFT — review before committing. Docs-before-code: this
addendum lands before any implementation session.

## What this revision changes and why

The 45-minute threshold currently carries one deliberate meaning across
two uses: D15's stream-fetch eligibility gate and the `long_run_eligible`
flag (core.yml states the alignment explicitly). Runs under 45 minutes
therefore never receive streams, which starves every sample-grain metric
— including the new one this revision introduces — for an athlete whose
runs are mostly shorter.

This revision **splits the fetch gate from the analysis gates**:

- **Stream fetch eligibility (D15 revised v1.4):** running activity ·
  HR present · moving time ≥ `stream_fetch_min_moving_minutes` (20) ·
  within historical window · not already loaded. Fetching is now a
  *data-availability* decision, not a metric-eligibility decision.
- **Drift candidacy: unchanged.** HR-carrying run ≥ 45 minutes
  (`long_run_min_moving_minutes`), exactly as revised in v1.1.
- **`long_run_eligible`: unchanged.** "Long run" keeps its single
  45-minute meaning.

Three previously-coupled meanings, now three explicit vars/uses. The
v1.2 lesson applies: this widening is *chosen here*, not absorbed from
a diff.

## D22 (new) — Pace-at-HR-band trend

**Definition.** Pool valid, moving, post-trim stream samples per run;
assign each sample an HR band (10 bpm, `hr_bands` seed, joined by
range — the `temperature_bands` pattern); per run per band compute
dwell seconds and median velocity; weekly statistic per band = **median
across contributing runs of the run-level band medians** (D11's
median-of-runs philosophy: one long run must not dominate a week by
sample count). 28-day rolling median per band smooths week noise (D13
pattern; static column names per v1.3).

**Sign of interest:** rising pace (falling min/mi) at the same HR band
= the observational signal of an improving aerobic base. Observational,
never causal — same framing discipline as D17.

**Analysis window, in order (mirrors D16's ordering discipline):**

1. Exclude invalid samples (`is_valid_sample`) and non-moving samples.
2. Trim the first `band_warmup_trim_minutes` (5) of elapsed time —
   warm-up HR is still climbing, so untrimmed samples pair a too-low
   HR with full pace and pollute the *low* bands optimistically.
3. Trim the final `band_cooldown_trim_minutes` (2).
4. Require ≥ `band_min_window_minutes` (10) of moving time remaining.
5. Require sample coverage: average gap within the window ≤ the
   existing drift coverage var (3 s). Reused, not duplicated.
6. Assign bands; a run contributes to a band only with dwell ≥
   `band_min_dwell_minutes` (5) — transitions passing through a band
   must not deposit junk medians.

No pause-share rung: unlike drift's time-based halves, pooling simply
drops non-moving samples, so pauses cannot bias band medians. The
omission is deliberate (an unused check is a hole waiting for an
occupant, inverted).

**Dwell definition.** Each in-window sample contributes
`least(elapsed_gap_to_previous_sample, coverage_cap_seconds)` seconds
to its band. The cap (the same 3 s var) prevents recording gaps from
inflating dwell; sparse recordings fail rung 5 before dwell is trusted.

**Exclusion ladder (deterministic, first failing check, dependency
order):** streams not yet loaded → streams unavailable from Strava →
stream fetch failed → required arrays missing → analysis window under
10 minutes after trimming → insufficient sample coverage → no band
meets the dwell minimum. Contract test: every candidate carries exactly
one of (≥1 band segment, exclusion_reason) — mutually exclusive,
jointly exhaustive.

**Candidate population:** HR-carrying runs ≥ the *fetch* gate
(20 min). Drift candidacy remains a strict subset by construction.

## Vars (all thresholds are vars, never inline SQL)

| Var | Value | Notes |
|---|---|---|
| `stream_fetch_min_moving_minutes` | 20 | NEW — split from the 45-min var; flows into `_ELIGIBLE_SQL` |
| `band_warmup_trim_minutes` | 5 | Lighter than D16's 10: a 20-min run must survive the trim |
| `band_cooldown_trim_minutes` | 2 | |
| `band_min_window_minutes` | 10 | 20-min run − 5 − 2 = 13 min ≥ 10 |
| `band_min_dwell_minutes` | 5 | Per run per band, to contribute a median |
| (reused) drift coverage max avg gap | 3 s | One mechanism, two consumers |
| (reused) D12 weekly sufficiency | ≥ 2 | Contributing runs per week × band |

## Models

| Layer | Model | Grain | Key contents |
|---|---|---|---|
| Seed | `hr_bands` | one row per band | 10 bpm bands, defined once, joined by range (range predicate via macro, per the v1.3 `temperature_band_range` precedent) |
| Intermediate | `int_band_window_samples` | run × sample | valid + moving + in-window samples with band assigned and per-sample dwell contribution |
| Intermediate | `int_run_band_assessment` | run | window stats + the exclusion ladder (single encoding), per candidate — the shared verdict both core band models consume, mirroring how `int_run_efficiency` carries the validity ladder |
| Core | `fct_band_candidates` | run | explicit-column core projection of `int_run_band_assessment` (the `fct_runs` ← `int_run_efficiency` pattern); `relationships` test to `fct_runs` (proven red on an orphan first, per v1.3) |
| Core | `fct_run_band_segments` | run × band | dwell seconds, sample count, median velocity/pace — analyzed runs only |
| Mart | `mart_band_weekly` | week × band | weekly median pace, contributing-run count, avg temp (context), `is_sufficient` |
| Mart | `mart_band_trend` | week × band | 28-day rolling median + rolling run count (static names); the sanctioned one-hop mart-to-mart edge |
| Mart | `mart_run_quality` | (existing) | gains `band_exclusion_reason`, the same route drift reasons take to the dashboard |

Layering: `int_run_band_assessment` reads `int_run_efficiency`,
`int_run_stream_samples`, `int_run_stream_state`, and
`int_band_window_samples` — the same sanctioned parents as
`fct_drift_candidates`, plus the new sample-grain intermediate.
`fct_band_candidates` is its explicit-column core projection and
`fct_run_band_segments` reads `int_band_window_samples` +
`int_run_band_assessment`, so the analyzed-only filter needs no
core → core edge. One layer-matrix permission IS required and is
chosen here, not absorbed from a diff (the v1.2 lesson, applied
deliberately): band assignment joins the `hr_bands` seed at sample
grain, so seeds become allowed parents of INTERMEDIATE models. The
guard is proven red on that edge before the matrix line changes; no
other matrix change is permitted.

## Dashboard (D19: clarified, not amended)

The band trend renders as a section **inside the Aerobic Efficiency
view**. It is the same analytical question with intensity controlled by
construction, and the three-view maximum holds. The app's pinned
allow-list grows by exactly one name (`mart_band_trend` — the weekly
statistics travel inside it, per the existing trend-mart interface);
the allow-list test and its negative case (a core table is refused)
update accordingly, red-first.

Rendering conventions carry over: statistic next to its sample count,
insufficient week × band points excluded from trend lines but visible
in tables, definition and sign convention stated on the view itself.

## Ingestion and backfill

The only ingestion change is threading `stream_fetch_min_moving_minutes`
into `_ELIGIBLE_SQL`'s `min_moving_seconds`. Newly eligible activities
have no streams row; absent-row-means-not-attempted makes the backfill
automatic across successive `make sync-streams` invocations (batch of
50, rate-limit stop contract unchanged).

**Sequencing rule:** the gate default changes only *after* the model
changes are proven output-invariant on existing data. Code invariance
and data growth are separate events, verified separately.

## Acceptance criteria

1. Existing marts byte-identical after the model changes, before the
   gate change — bidirectional `EXCEPT ALL`, row counts, checksum;
   `mart_run_quality` compared on its pre-existing column set (the new
   column is additive).
2. Drift candidacy and `long_run_eligible` provably unchanged (same
   invariance run covers this).
3. Band medians validated by hand-checkable synthetic fixtures:
   constant 3.0 m/s, HR stepping 135 → 145 at the window midpoint →
   two bands, equal dwell, median velocity 3.0 in each; poisoned
   warm-up/cool-down so a trimming break visibly shifts the numbers.
4. One fixture per reachable exclusion rung, including a
   dwell-minimum fixture (2 minutes in a band → band absent).
5. Exclusivity/exhaustiveness contract test on `fct_band_candidates`.
6. Layering guard passes with exactly one deliberate widening — seeds
   become allowed parents of intermediate models (the `hr_bands`
   sample-grain join) — proven red before the matrix line changes; no
   other matrix change.
7. Allow-list test updated with its negative case intact, proven red
   before the app change.
8. Manual inspection of several real run-band segments for
   plausibility — deferred until the backfill lands data (the D16
   criterion-6 precedent). COMPLETED 2026-07-11, post-merge: backfill
   drained exactly as pre-registered (eligible 8 → 0), 15/15
   candidates analyzed, seg-dwell ≤ pooled ≤ window on every run,
   band paces coherent with HR (monotone across bands within runs),
   weekly sufficiency flips exactly at the D12 threshold, zero
   exclusion reasons on real data; owner signed off on the two
   flagged nuances (early-run dominant-band/avg-HR gaps, >20 min/mi
   medians in low bands — run/walk material, as designed).

# Revision v1.5 — 2026-07-16 — Airflow as a thin scheduling and observability layer (Addendum to D18)

Recorded in `docs/decisions/v1.5-airflow-addendum.md` — the first
revision kept under `docs/decisions/` rather than appended here.
Summary: D18's Makefile + CLI remains the sole execution layer;
Airflow is adopted post-MVP as a THIN scheduling and observability
layer under five constraints — (a) Airflow owns no state (watermarks,
per-item status rows, destination-as-cache stay the pipeline's);
(b) catchup=False and no templated date windows (Strava filters by
activity start date; interval windows would reintroduce the
late-upload gap the 14-day overlap already solves); (c) tasks invoke
existing Make targets unchanged — no pipeline code changes;
(d) LocalExecutor-or-simpler, SQLite metadata DB, no
Celery/Redis/Docker for Airflow in this release; (e) Airflow lives in
its own venv, never in the project's dependencies.

# Revision v1.6 — 2026-07-20 — Run×band scatter mart for the band view (Addendum)

Recorded in `docs/decisions/v1.6-band-run-scatter.md`.
Summary: new mart `mart_run_band_segments` (run × band grain — an
explicit-column projection of core `fct_run_band_segments` joined to
the `hr_bands` seed; no layer-matrix change, nothing upstream of
existing marts moves). The dashboard's band chart becomes one faint
point per run per band with the 28-day rolling median line as the only
line, and the allow-list grows by exactly that mart, proven red first.
D22's weekly median-of-run-medians definition and `mart_band_weekly`'s
output are unchanged, pinned by a velocity-space consistency test
(`assert_band_weekly_matches_segment_mart`); no threshold var changes.
