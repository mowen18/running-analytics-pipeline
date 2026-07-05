-- Phase 5: raw activity-stream storage (time-series samples per run).
-- Idempotent: applied on first container init via docker-entrypoint-initdb.d
-- (alphabetically after raw_strava.sql) and re-appliable with `make bootstrap`.

CREATE TABLE IF NOT EXISTS raw_strava.streams (
    activity_id            bigint       PRIMARY KEY,
    payload                jsonb        NOT NULL,
    stream_types_requested text[],
    sample_count           integer,
    fetched_at             timestamptz  NOT NULL,
    ingestion_status       text         NOT NULL
        CHECK (ingestion_status IN ('success', 'failed', 'unavailable')),
    error_message          text         NULL
);

COMMENT ON TABLE raw_strava.streams IS
    'One row per attempted stream fetch. success = streams stored; unavailable = Strava has no streams for the activity (terminal); failed = transient error, retried by the next backfill. Absent row = not yet attempted.';
COMMENT ON COLUMN raw_strava.streams.payload IS
    'Full key_by_type streams response for success; {} for failed/unavailable (NOT NULL so "no payload" is always explicit, never ambiguous)';
COMMENT ON COLUMN raw_strava.streams.sample_count IS
    'Length of the aligned time stream for success rows; NULL otherwise (missing, not zero)';
COMMENT ON COLUMN raw_strava.streams.error_message IS
    'Actionable failure detail for failed/unavailable rows; never contains tokens';

CREATE INDEX IF NOT EXISTS streams_ingestion_status_idx
    ON raw_strava.streams (ingestion_status);
