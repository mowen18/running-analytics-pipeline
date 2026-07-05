# Phase 0–3 targets. App targets arrive with their phase.

VENV := .venv/bin

# dbt runs from dbt/ (decision D4) with a local profile auto-copied from
# the committed example; .env supplies connection values via env_var().
DBT = cd dbt && set -a && . ../.env && set +a && ../$(VENV)/dbt

.PHONY: help up down bootstrap athlete authorize sync-activities reconcile \
	backfill-coordinates sync-weather reconcile-weather sync-streams \
	dbt-profile dbt-build dbt-test dbt-freshness dbt-docs app all test \
	lint format

help:
	@grep -E '^[a-z-]+:' Makefile | sed 's/:.*//' | sort

up:            ## start Postgres (healthcheck-gated)
	docker compose up -d --wait

down:          ## stop Postgres (data volume preserved)
	docker compose down

bootstrap:     ## (re-)apply every sql/*.sql in order — idempotent
	for f in sql/*.sql; do \
		docker compose exec postgres psql -U running_user -d running_analytics_db \
			-v ON_ERROR_STOP=1 -f "/docker-entrypoint-initdb.d/$$(basename $$f)" \
			|| exit 1; \
	done

athlete:       ## print the authenticated athlete profile
	$(VENV)/running-pipeline athlete

authorize:     ## one-time Strava browser authorization
	$(VENV)/running-pipeline authorize

sync-activities:   ## incremental Strava activity sync (14-day overlap window)
	$(VENV)/running-pipeline sync-activities

reconcile:     ## full reconciliation: re-fetch everything from SYNC_START_DATE
	$(VENV)/running-pipeline sync-activities --full

backfill-coordinates:  ## resolve run-start coordinates (payload, else detail polyline)
	$(VENV)/running-pipeline backfill-coordinates

sync-weather:  ## fetch hourly weather for outdoor runs not yet covered
	$(VENV)/running-pipeline sync-weather

reconcile-weather:  ## re-fetch weather even for already-cached hours
	$(VENV)/running-pipeline sync-weather --full

sync-streams:  ## backfill activity streams for drift-eligible runs (resumable)
	$(VENV)/running-pipeline sync-streams

dbt-profile:   ## create dbt/profiles.yml from the example if absent
	@test -f dbt/profiles.yml || cp dbt/profiles.yml.example dbt/profiles.yml

dbt-build: dbt-profile     ## build all dbt models and run their tests
	$(DBT) build --profiles-dir .

dbt-test: dbt-profile      ## run dbt tests only
	$(DBT) test --profiles-dir .

dbt-freshness: dbt-profile ## check source freshness (raw fetched_at ages)
	$(DBT) source freshness --profiles-dir .

dbt-docs: dbt-profile      ## generate + serve dbt docs locally
	$(DBT) docs generate --profiles-dir . && $(DBT) docs serve --profiles-dir .

app:           ## launch the Streamlit dashboard (three views, marts only)
	$(VENV)/streamlit run app/streamlit_app.py

all: sync-activities backfill-coordinates sync-weather sync-streams dbt-build  ## full refresh: all syncs + dbt

test:
	$(VENV)/pytest

lint:
	$(VENV)/ruff check src tests

format:
	$(VENV)/ruff format src tests
