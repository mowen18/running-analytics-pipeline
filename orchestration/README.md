# orchestration/ — Airflow scaffolding (v1.5)

This directory is the repo-side surface of the v1.5 Airflow adoption
(docs/decisions/v1.5-airflow-addendum.md, which revises D18). Airflow
is a THIN scheduling and observability layer: it decides *when* to run
and shows *what happened*; the Makefile + CLI remain the sole
execution layer.

## Layout

```text
orchestration/
└── dags/
    └── running_pipeline_dag.py   # the one pipeline DAG (below);
                                  # AIRFLOW__CORE__DAGS_FOLDER points here
```

Everything else Airflow needs lives OUTSIDE the repo, by design
(addendum constraint (e)):

- `~/.venvs/airflow` — Airflow's own venv. apache-airflow is never
  added to this project's pyproject, requirements, or `.venv`.
- `~/airflow` — `AIRFLOW_HOME`: SQLite metadata DB, config, logs,
  the standalone credential file. None of it is committed.

## Usage

```bash
make airflow-install   # one-time: create ~/.venvs/airflow and install
                       # apache-airflow with the official constraints
                       # file matching that venv's Python version
make airflow-start     # run `airflow standalone` with AIRFLOW_HOME and
                       # the DAGs folder above (repo path derived, not
                       # hardcoded); example DAGs disabled. The recipe
                       # prepends ~/.venvs/airflow/bin to PATH because
                       # standalone respawns its components as bare
                       # `airflow` resolved via PATH
```

Overrides:

- `make airflow-install AIRFLOW_PYTHON=python3.14` — interpreter that
  seeds the venv (default `python3.13`; the target fails fast with an
  actionable message if the interpreter is not on PATH).
- `make airflow-install AIRFLOW_VERSION=3.3.0` — pin the Airflow
  version and its matching constraints branch (default floats to
  `constraints-latest`).

## Operational gotchas (learned the hard way)

- **Bare `airflow` CLI calls need the full env block** — the Make
  targets set it via `$(AIRFLOW_ENV)`, but a hand-typed command does
  not. Copy-paste, run from the repo root:

  ```bash
  PATH="$HOME/.venvs/airflow/bin:$PATH" AIRFLOW_HOME="$HOME/airflow" \
  AIRFLOW__CORE__DAGS_FOLDER="$(pwd)/orchestration/dags" \
  AIRFLOW__CORE__LOAD_EXAMPLES=False airflow <subcommand>
  ```

  Without `LOAD_EXAMPLES=False`, a parse (e.g. `dags reserialize`)
  pollutes the metadata DB with Airflow's example DAGs.
- **`airflow dags list` / `list-import-errors` read the metadata DB,
  not the DAGs folder.** When no dag-processor is running (standalone
  stopped), run `airflow dags reserialize` first — otherwise a new or
  edited DAG file is invisible to both commands.

## The DAG: `running_pipeline`

Mirrors `make all` as a linear chain — sync_activities →
backfill_coordinates → sync_weather → sync_streams → dbt_build. Daily
at 06:00 America/Chicago; the cron and timezone are the
`SCHEDULE_CRON` / `SCHEDULE_TZ` constants at the top of the DAG file
(one-line changes). `catchup=False`, no templated date windows
(constraint (b) — the 14-day overlap owns incremental correctness),
`max_active_runs=1`.

Exit-code-3 behavior (policy in the addendum): the CLI exits 3 on a
clean rate-limit/budget stop with committed work kept, so those tasks
are marked SKIPPED (`skip_on_exit_code=3`) and downstream tasks use
`trigger_rule="none_failed"` — dbt_build still runs on already-ingested
data, while a genuine failure (exit 1) halts the chain. Because GNU
make masks recipe exit codes (any failure → make exits 2), the four
sync tasks invoke `.venv/bin/running-pipeline <cmd>` directly — the
verbatim one-line body of each make recipe, cwd = repo root — while
dbt_build stays behind `make dbt-build` (real recipe logic, no exit-3
contract).

## Constraints (addendum, verbatim)

- (a) Airflow owns no state — watermarks, per-item status rows, and
  destination-as-cache remain the pipeline's;
- (b) catchup=False and no templated date windows, because Strava
  filters by activity start date and interval-based windows would
  reintroduce the late-upload gap the 14-day overlap already solves;
- (c) tasks invoke existing Make targets unchanged — no pipeline code
  changes;
- (d) LocalExecutor-or-simpler, SQLite metadata DB, no
  Celery/Redis/Docker for Airflow in this release;
- (e) Airflow lives in its own venv, never in the project's
  dependencies.
