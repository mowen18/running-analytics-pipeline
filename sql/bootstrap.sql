-- Bootstrap the five warehouse schemas (decision D3).
-- Idempotent: runs on first container init via docker-entrypoint-initdb.d
-- and can be re-applied any time with `make bootstrap`.
-- Tables are created by their owning phases (Phase 1+), never here.

CREATE SCHEMA IF NOT EXISTS raw_strava AUTHORIZATION running_user;
COMMENT ON SCHEMA raw_strava IS 'Raw Strava API payloads (activities, streams) as ingested';

CREATE SCHEMA IF NOT EXISTS raw_weather AUTHORIZATION running_user;
COMMENT ON SCHEMA raw_weather IS 'Raw Open-Meteo hourly weather observations as ingested';

CREATE SCHEMA IF NOT EXISTS staging AUTHORIZATION running_user;
COMMENT ON SCHEMA staging IS 'dbt staging models: typed, renamed, one row per source record';

CREATE SCHEMA IF NOT EXISTS intermediate AUTHORIZATION running_user;
COMMENT ON SCHEMA intermediate IS 'dbt intermediate models: joins and enrichment between staging and marts';

CREATE SCHEMA IF NOT EXISTS analytics AUTHORIZATION running_user;
COMMENT ON SCHEMA analytics IS 'dbt facts and marts consumed by the Streamlit app';
