"""Postgres connection handling for the single-shot CLI.

One connection per command, no pooling. psycopg's context-manager
semantics apply: `with get_connection(settings) as conn:` commits on
clean exit, rolls back on exception, and closes either way. The password
leaves Settings only here, at connect time, never in reprs or logs.
"""

import psycopg

from running_pipeline.config import Settings


def get_connection(settings: Settings) -> psycopg.Connection:
    return psycopg.connect(
        host=settings.postgres_host,
        port=settings.postgres_port,
        dbname=settings.postgres_db,
        user=settings.postgres_user,
        password=settings.postgres_password.get_secret_value(),
    )
