-- Phase 1: raw Strava activity storage and sync-state watermark.
-- Idempotent: runs on first container init via docker-entrypoint-initdb.d
-- (alphabetically after bootstrap.sql, which creates the schemas) and can
-- be re-applied any time with `make bootstrap`.

CREATE TABLE IF NOT EXISTS raw_strava.activities (
    activity_id       bigint       PRIMARY KEY,
    start_date_utc    timestamptz  NOT NULL,
    activity_type     text,
    payload           jsonb        NOT NULL,
    source_updated_at timestamptz  NULL,
    fetched_at        timestamptz  NOT NULL
);

COMMENT ON TABLE raw_strava.activities IS
    'One row per Strava activity: full API payload in JSONB, sync-critical fields promoted to typed columns';
COMMENT ON COLUMN raw_strava.activities.activity_type IS
    'sport_type from the payload (the deprecated type field remains available in JSONB)';
COMMENT ON COLUMN raw_strava.activities.source_updated_at IS
    'Strava-reported update time when the payload provides one; NULL means not provided (missing, not zero)';

-- activity_id is covered by the primary-key index; the plan also requires:
CREATE INDEX IF NOT EXISTS activities_start_date_utc_idx
    ON raw_strava.activities (start_date_utc);
CREATE INDEX IF NOT EXISTS activities_activity_type_idx
    ON raw_strava.activities (activity_type);

CREATE TABLE IF NOT EXISTS raw_strava.sync_state (
    sync_key       text         PRIMARY KEY,
    last_synced_at timestamptz  NOT NULL,
    updated_at     timestamptz  NOT NULL
);

COMMENT ON TABLE raw_strava.sync_state IS
    'Last-successful-sync watermark per ingestion job (sync_key: activities now, streams in Phase 5); advanced only after a fully successful run';
