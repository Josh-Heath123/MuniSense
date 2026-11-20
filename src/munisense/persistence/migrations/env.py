"""Alembic environment (P2-10). Migrations run as the migration role, online only.

The URL comes from `MUNISENSE_MIGRATION_DATABASE_URL`, checked by the settings (P2-3), or,
in tests, from `config.attributes["url"]` (a checked `DatabaseUrl`; anything else is
refused). A superuser connection is refused. The version table lives in the `munisense`
schema, so the app role can read it too (harmless).
"""

import os

from alembic import context
from sqlalchemy import text

from munisense.persistence.connection import SCHEMA, engine
from munisense.platform.settings import DatabaseUrl, database_url


def _url() -> DatabaseUrl:
    given = context.config.attributes.get("url")
    if given is None:
        return database_url(os.environ, "MUNISENSE_MIGRATION_DATABASE_URL")
    if not isinstance(given, DatabaseUrl):
        # Never fall back to the environment's (development) database by mistake.
        msg = "config.attributes['url'] must be a checked DatabaseUrl"
        raise TypeError(msg)
    return given


def run_migrations_online() -> None:
    connectable = engine(_url())
    try:
        with connectable.connect() as connection:
            superuser = connection.execute(
                text("SELECT rolsuper FROM pg_roles WHERE rolname = current_user")
            ).scalar_one()
            if superuser:
                # Tables owned by a superuser escape the default privileges (P2-3).
                msg = "migrations run as the migration role, never as a superuser"
                raise RuntimeError(msg)
            # End the check's own transaction: if one were still open, Alembic would treat
            # it as the caller's and never commit the migrations.
            connection.commit()
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
