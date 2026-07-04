"""Last-successful-sync watermarks (raw_strava.sync_state).

The watermark is the wall-clock UTC time a sync *started*, written only
after the run finished completely. Using the start (not the end) means
activities uploaded while a sync was running still fall inside the next
incremental window; failed or rate-limit-stopped runs never advance it.
"""

from datetime import datetime

import psycopg


def get_last_synced_at(conn: psycopg.Connection, sync_key: str) -> datetime | None:
    row = conn.execute(
        "SELECT last_synced_at FROM raw_strava.sync_state WHERE sync_key = %s",
        (sync_key,),
    ).fetchone()
    return row[0] if row is not None else None


def set_last_synced_at(conn: psycopg.Connection, sync_key: str, last_synced_at: datetime) -> None:
    conn.execute(
        """
        INSERT INTO raw_strava.sync_state (sync_key, last_synced_at, updated_at)
        VALUES (%s, %s, now())
        ON CONFLICT (sync_key) DO UPDATE
            SET last_synced_at = EXCLUDED.last_synced_at,
                updated_at = now()
        """,
        (sync_key, last_synced_at),
    )
