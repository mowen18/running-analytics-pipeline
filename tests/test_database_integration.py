"""DDL shape and idempotency against the real local Postgres.

The whole module skips with an actionable reason when the database is
down or .env is unconfigured — see the integration_db fixture.
"""

import pytest

pytestmark = pytest.mark.integration


def test_ddl_reapplies_idempotently(integration_db, sql_dir):
    # The fixture already applied every sql/*.sql once; `make bootstrap`
    # re-runs them freely, so a second application must be a no-op.
    for ddl_file in sorted(sql_dir.glob("*.sql")):
        integration_db.execute(ddl_file.read_text())
    integration_db.commit()


def test_activities_columns_match_plan(integration_db):
    rows = integration_db.execute(
        """
        SELECT column_name, data_type, is_nullable
        FROM information_schema.columns
        WHERE table_schema = 'raw_strava' AND table_name = 'activities'
        ORDER BY ordinal_position
        """
    ).fetchall()
    assert rows == [
        ("activity_id", "bigint", "NO"),
        ("start_date_utc", "timestamp with time zone", "NO"),
        ("activity_type", "text", "YES"),
        ("payload", "jsonb", "NO"),
        ("source_updated_at", "timestamp with time zone", "YES"),
        ("fetched_at", "timestamp with time zone", "NO"),
    ]


def test_activities_indexes_cover_plan_columns(integration_db):
    rows = integration_db.execute(
        """
        SELECT indexname FROM pg_indexes
        WHERE schemaname = 'raw_strava' AND tablename = 'activities'
        """
    ).fetchall()
    names = {name for (name,) in rows}
    # activity_id is covered by the primary-key index.
    assert {
        "activities_pkey",
        "activities_start_date_utc_idx",
        "activities_activity_type_idx",
    } <= names


def test_sync_state_shape(integration_db):
    rows = integration_db.execute(
        """
        SELECT column_name, data_type, is_nullable
        FROM information_schema.columns
        WHERE table_schema = 'raw_strava' AND table_name = 'sync_state'
        ORDER BY ordinal_position
        """
    ).fetchall()
    assert rows == [
        ("sync_key", "text", "NO"),
        ("last_synced_at", "timestamp with time zone", "NO"),
        ("updated_at", "timestamp with time zone", "NO"),
    ]
