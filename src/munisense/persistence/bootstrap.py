"""Create the two database roles and the schema in a local database (P2-3).

`uv run poe db-bootstrap` runs this once per volume against the development and test
databases, and CI runs it before the tests. It connects as the local superuser
(`MUNISENSE_ADMIN_DATABASE_URL`), is idempotent, and refuses to run outside a local
environment: setting up a deployed database is a P9 decision.

- `munisense_migration` owns the `munisense` schema: it runs migrations and loads data.
- `munisense_app` may connect and read: `USAGE` on the schema and `SELECT` on every table
  the migration role creates, now or later. Its sessions are read-only by default. It
  cannot create, write, create temporary tables or run functions the migration role makes.
- Neither role is a superuser, and neither may create databases or roles.

Passwords are turned into SCRAM verifiers on the client, so the plaintext never reaches the
server or its log. Statements go to the driver directly, so a `:word` in a verifier is
never read as a bind parameter.
"""

import os
import re
import sys
from collections.abc import Mapping

from sqlalchemy import Connection

from munisense.persistence.connection import SCHEMA, engine
from munisense.platform.settings import (
    DatabaseUrl,
    Environment,
    SettingsError,
    database_url,
    environment,
)

ROLE_LIMITS = "LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS"
SCRAM_VERIFIER = re.compile(r"SCRAM-SHA-256\$\d+:[A-Za-z0-9+/=]+\$[A-Za-z0-9+/=]+:[A-Za-z0-9+/=]+")


def _verifier(connection: Connection, role: str, password: str) -> str:
    pgconn = connection.connection.driver_connection.pgconn  # type: ignore[union-attr]
    verifier: bytes = pgconn.encrypt_password(password.encode(), role.encode(), b"scram-sha-256")
    text = verifier.decode("ascii")
    if not SCRAM_VERIFIER.fullmatch(text):  # pragma: no cover  # libpq's own output format
        msg = "libpq returned an unexpected password verifier"
        raise RuntimeError(msg)
    return text


def _ensure_role(connection: Connection, role: str, password: str) -> None:
    quoted = connection.dialect.identifier_preparer.quote_identifier(role)
    exists = connection.exec_driver_sql(
        "SELECT 1 FROM pg_roles WHERE rolname = %(role)s", {"role": role}
    ).first()
    if exists is None:
        connection.exec_driver_sql(f"CREATE ROLE {quoted} LOGIN")
    connection.exec_driver_sql(f"ALTER ROLE {quoted} {ROLE_LIMITS}")
    connection.exec_driver_sql(
        f"ALTER ROLE {quoted} PASSWORD '{_verifier(connection, role, password)}'"
    )


def bootstrap(admin: DatabaseUrl, app: DatabaseUrl, migration: DatabaseUrl) -> None:
    """Create or reset the roles and the schema in `admin`'s database."""
    with engine(admin).begin() as connection:
        for url in (app, migration):
            _ensure_role(connection, url.user, url.password)
        q = connection.dialect.identifier_preparer.quote_identifier
        database, reader, owner = q(admin.database), q(app.user), q(migration.user)
        statements = [
            f"REVOKE ALL ON DATABASE {database} FROM PUBLIC",
            f"GRANT CONNECT ON DATABASE {database} TO {reader}, {owner}",
            f"CREATE SCHEMA IF NOT EXISTS {SCHEMA} AUTHORIZATION {owner}",
            f"ALTER SCHEMA {SCHEMA} OWNER TO {owner}",
            f"REVOKE ALL ON SCHEMA {SCHEMA} FROM PUBLIC",
            f"GRANT USAGE ON SCHEMA {SCHEMA} TO {reader}",
            f"GRANT SELECT ON ALL TABLES IN SCHEMA {SCHEMA} TO {reader}",
            f"ALTER DEFAULT PRIVILEGES FOR ROLE {owner} IN SCHEMA {SCHEMA}"
            f" GRANT SELECT ON TABLES TO {reader}",
            # Global form: per-schema defaults can only add privileges, not remove them.
            f"ALTER DEFAULT PRIVILEGES FOR ROLE {owner} REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC",
            f"ALTER ROLE {reader} SET default_transaction_read_only = on",
        ]
        for statement in statements:
            connection.exec_driver_sql(statement)


def _pairs(env: Mapping[str, str]) -> list[tuple[DatabaseUrl, DatabaseUrl]]:
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
    passwords: dict[str, str] = {}
    for app, migration in pairs:
        if app.database != migration.database:
            msg = f"the app and migration URLs name different databases ({app.database})"
            raise SettingsError(msg)
        for url in (app, migration):
            # Roles are cluster-wide: a second password would silently replace the first.
            if passwords.setdefault(url.user, url.password) != url.password:
                msg = f"role {url.user} is given two different passwords"
                raise SettingsError(msg)
    return pairs


def main(env: Mapping[str, str] = os.environ) -> int:
    try:
        if environment(env) is not Environment.LOCAL:
            sys.stderr.write("db-bootstrap runs only in a local environment (P9 decides)\n")
            return 2
        admin = database_url(env, "MUNISENSE_ADMIN_DATABASE_URL")
        pairs = _pairs(env)
    except SettingsError as error:
        sys.stderr.write(f"db-bootstrap: {error}\n")
        return 2
    done: set[str] = set()
    for app, migration in pairs:
        if app.database not in done:
            bootstrap(admin.with_database(app.database), app, migration)
            sys.stdout.write(f"db-bootstrap: roles and schema ready in {app.database}\n")
            done.add(app.database)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
