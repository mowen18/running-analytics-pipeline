-- Coordinate resolution for runs whose API payload lacks start_latlng.
-- Strava's "hide entire map" privacy setting strips start/end coordinates
-- from API responses (even the owner's), while the activity detail
-- endpoint still carries the encoded route polyline; this table stores
-- the resolved start coordinate with explicit provenance.
-- Idempotent, applied via docker-entrypoint-initdb.d / `make bootstrap`.

CREATE TABLE IF NOT EXISTS raw_strava.activity_coordinates (
    activity_id bigint       PRIMARY KEY,
    latitude    numeric      NULL,
    longitude   numeric      NULL,
    source      text         NOT NULL
        CHECK (source IN ('start_latlng', 'map_polyline', 'unavailable')),
    fetched_at  timestamptz  NOT NULL,
    CHECK ((latitude IS NULL) = (longitude IS NULL)),
    CHECK ((source = 'unavailable') = (latitude IS NULL))
);

COMMENT ON TABLE raw_strava.activity_coordinates IS
    'Resolved run-start coordinate per activity: start_latlng when the payload carries one, else the first decoded point of the detail map.polyline, else an explicit unavailable row (terminal — the activity has no route data). Absent row = not yet attempted.';
COMMENT ON COLUMN raw_strava.activity_coordinates.source IS
    'Provenance: start_latlng (from the summary payload, no extra API call) / map_polyline (decoded from the detail endpoint) / unavailable (no route data exists)';
COMMENT ON COLUMN raw_strava.activity_coordinates.latitude IS
    'Full-precision start latitude; NULL only for unavailable rows. Never logged or committed — downstream use rounds to the D7 2-dp cell.';
