# orchestration/ — Airflow scaffolding (v1.5)

This directory is the repo-side surface of the v1.5 Airflow adoption
(docs/decisions/v1.5-airflow-addendum.md, which revises D18). Airflow
is a THIN scheduling and observability layer: it decides *when* to run
and shows *what happened*; the Makefile + CLI remain the sole
execution layer.

## Layout

```text
orchestration/
└── dags/        # AIRFLOW__CORE__DAGS_FOLDER points here.
                 # Empty until the DAG implementation session;
                 # .gitkeep holds the directory in git.
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
                       # hardcoded); example DAGs disabled
```

Overrides:

- `make airflow-install AIRFLOW_PYTHON=python3.14` — interpreter that
  seeds the venv (default `python3.13`; the target fails fast with an
  actionable message if the interpreter is not on PATH).
- `make airflow-install AIRFLOW_VERSION=3.3.0` — pin the Airflow
  version and its matching constraints branch (default floats to
  `constraints-latest`).

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
