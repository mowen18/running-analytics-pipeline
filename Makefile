# Phase 0–2 targets. dbt/app targets arrive with their phases.

VENV := .venv/bin

.PHONY: help up down bootstrap athlete authorize sync-activities reconcile \
	sync-weather reconcile-weather test lint format

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

sync-weather:  ## fetch hourly weather for outdoor runs not yet covered
	$(VENV)/running-pipeline sync-weather

reconcile-weather:  ## re-fetch weather even for already-cached hours
	$(VENV)/running-pipeline sync-weather --full

test:
	$(VENV)/pytest

lint:
	$(VENV)/ruff check src tests

format:
	$(VENV)/ruff format src tests
