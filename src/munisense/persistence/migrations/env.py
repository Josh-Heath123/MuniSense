"""Alembic environment (P2-10). Migrations run as the migration role, online only.

The URL comes from `MUNISENSE_MIGRATION_DATABASE_URL`, checked by the settings (P2-3), or,
in tests, from `config.attributes["url"]` (a checked `DatabaseUrl`). The version table
lives in the `munisense` schema.
"""

import os

from alembic import context

from munisense.persistence.connection import SCHEMA, engine
from munisense.platform.settings import DatabaseUrl, database_url


def _url() -> DatabaseUrl:
    given = context.config.attributes.get("url")
    if isinstance(given, DatabaseUrl):
        return given
    return database_url(os.environ, "MUNISENSE_MIGRATION_DATABASE_URL")


def run_migrations_online() -> None:
    connectable = engine(_url())
    try:
        with connectable.connect() as connection:
            context.configure(
                connection=connection,
                version_table_schema=SCHEMA,
                transaction_per_migration=True,
            )
            with context.begin_transaction():
                context.run_migrations()
    finally:
        connectable.dispose()


if context.is_offline_mode():  # pragma: no cover  # offline SQL generation is not used
    msg = "offline migrations are not supported; run against the database"
    raise RuntimeError(msg)
run_migrations_online()
