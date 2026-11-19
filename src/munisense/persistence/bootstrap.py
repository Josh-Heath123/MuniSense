"""Create the two database roles and the schema in a local database (P2-3).

`uv run poe db-bootstrap` runs this against the development and test databases, as the
local superuser (`MUNISENSE_ADMIN_DATABASE_URL`). It is idempotent. It refuses to run
outside a local environment: setting up a deployed database is a P9 decision.

- `munisense_migration` owns the `munisense` schema: it runs migrations and loads data.
- `munisense_app` may connect and read: `USAGE` on the schema and `SELECT` on every table
  the migration role creates, now or later. It cannot create, insert, update or delete.
- Neither role is a superuser, and neither may create databases or roles.
"""

import os
import sys
from collections.abc import Mapping
from urllib.parse import unquote, urlsplit

from sqlalchemy import Connection, text

from munisense.persistence.connection import SCHEMA, engine
from munisense.platform.settings import (
    DatabaseUrl,
    Environment,
    SettingsError,
    database_url,
    environment,
)

ROLE_LIMITS = "LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS"


def _ensure_role(connection: Connection, role: str, password: str) -> None:
    quoted = connection.dialect.identifier_preparer.quote_identifier(role)
    exists = connection.execute(
        text("SELECT 1 FROM pg_roles WHERE rolname = :role"), {"role": role}
    ).first()
    if exists is None:
        connection.execute(text(f"CREATE ROLE {quoted} LOGIN"))
    connection.execute(text(f"ALTER ROLE {quoted} {ROLE_LIMITS}"))
    # ALTER ROLE takes no bind parameters, so the server quotes the password literal.
    literal = connection.execute(text("SELECT quote_literal(:p)"), {"p": password}).scalar_one()
    connection.execute(text(f"ALTER ROLE {quoted} PASSWORD {literal}"))


def _password(url: DatabaseUrl) -> str:
    return unquote(urlsplit(url.url).password or "")


def bootstrap(admin: DatabaseUrl, app: DatabaseUrl, migration: DatabaseUrl) -> None:
    """Create or reset the roles and the schema in `admin`'s database."""
    with engine(admin).begin() as connection:
        for url in (app, migration):
            _ensure_role(connection, url.user, _password(url))
        q = connection.dialect.identifier_preparer.quote_identifier
        database, reader, owner = q(admin.database), q(app.user), q(migration.user)
        statements = [
            f"REVOKE ALL ON DATABASE {database} FROM PUBLIC",
            f"GRANT CONNECT ON DATABASE {database} TO {reader}, {owner}",
            "REVOKE CREATE ON SCHEMA public FROM PUBLIC",
            f"CREATE SCHEMA IF NOT EXISTS {SCHEMA} AUTHORIZATION {owner}",
            f"ALTER SCHEMA {SCHEMA} OWNER TO {owner}",
            f"REVOKE ALL ON SCHEMA {SCHEMA} FROM PUBLIC",
            f"GRANT USAGE ON SCHEMA {SCHEMA} TO {reader}",
            f"GRANT SELECT ON ALL TABLES IN SCHEMA {SCHEMA} TO {reader}",
            f"ALTER DEFAULT PRIVILEGES FOR ROLE {owner} IN SCHEMA {SCHEMA}"
            f" GRANT SELECT ON TABLES TO {reader}",
        ]
        for statement in statements:
            connection.execute(text(statement))


def main(env: Mapping[str, str] = os.environ) -> int:
    if environment(env) is not Environment.LOCAL:
        sys.stderr.write("db-bootstrap runs only in a local environment (P9 decides deployment)\n")
        return 2
    try:
        admin = database_url(env, "MUNISENSE_ADMIN_DATABASE_URL")
        pairs = [
            (
                database_url(env, "MUNISENSE_DATABASE_URL"),
                database_url(env, "MUNISENSE_MIGRATION_DATABASE_URL"),
            ),
            (
                database_url(env, "MUNISENSE_TEST_DATABASE_URL"),
                database_url(env, "MUNISENSE_TEST_MIGRATION_DATABASE_URL"),
            ),
        ]
    except SettingsError as error:
        sys.stderr.write(f"db-bootstrap: {error}\n")
        return 2
    for app, migration in pairs:
        bootstrap(admin.with_database(app.database), app, migration)
        sys.stdout.write(f"db-bootstrap: roles and schema ready in {app.database}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
