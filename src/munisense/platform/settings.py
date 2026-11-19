"""Database settings, read from the environment and checked before anything connects (P2-3).

Two kinds of environment:

- `local`: a developer's machine and CI, whose PostgreSQL is a throwaway container bound to
  localhost (E50). Unset URLs fall back to the published local defaults, which also appear
  in `docker-compose.yml`, `.env.example` and `ci.yml`.
- `deployed`: anything else. Every URL must be set explicitly, must not use a published
  default password, and must require `sslmode=verify-full`.

Every connection disables GSSAPI encryption (`gssencmode=disable`) and refuses libpq
service lookups (`service=`, `PGSERVICE`, `PGSERVICEFILE`), which is how `ldap://` service
entries are reached. Both keep the old Kerberos and LDAP code bundled in psycopg-binary off
the connection path (P2-2 security review, TD-15).
"""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit, urlunsplit


class SettingsError(ValueError):
    """A setting is missing, malformed or unsafe for this environment."""


class Environment(StrEnum):
    LOCAL = "local"
    DEPLOYED = "deployed"


class Role(StrEnum):
    """The database roles. Neither is a superuser (P2 security notes)."""

    APP = "app"
    """Reads published data: `SELECT` only (ADR-0012: nothing is ever updated)."""
    MIGRATION = "migration"
    """Owns the schema: runs migrations and loads the database from the files."""


# The published local and CI passwords (docker-compose.yml, .env.example, ci.yml). They
# protect nothing, so they are refused outside a local environment.
PUBLISHED_PASSWORDS = frozenset(
    {
        "munisense-local-only",
        "munisense-app-local-only",
        "munisense-migration-local-only",
        "ci-only-not-a-secret",
    }
)

LOCAL_DEFAULTS = {
    "MUNISENSE_ADMIN_DATABASE_URL": "postgresql://munisense:munisense-local-only@localhost:5432/munisense_dev",
    "MUNISENSE_DATABASE_URL": "postgresql://munisense_app:munisense-app-local-only@localhost:5432/munisense_dev",
    "MUNISENSE_MIGRATION_DATABASE_URL": "postgresql://munisense_migration:munisense-migration-local-only@localhost:5432/munisense_dev",
    "MUNISENSE_TEST_DATABASE_URL": "postgresql://munisense_app:munisense-app-local-only@localhost:5432/munisense_test",
    "MUNISENSE_TEST_MIGRATION_DATABASE_URL": "postgresql://munisense_migration:munisense-migration-local-only@localhost:5432/munisense_test",
}

FORCED_OPTIONS = {"gssencmode": "disable"}
REFUSED_OPTIONS = frozenset({"service", "servicefile"})
REFUSED_ENVIRONMENT = ("PGSERVICE", "PGSERVICEFILE")


@dataclass(frozen=True)
class DatabaseUrl:
    """A checked libpq URL. `url` carries the forced options; `database` is its name."""

    url: str
    user: str
    database: str

    def with_database(self, database: str) -> "DatabaseUrl":
        parts = urlsplit(self.url)
        return DatabaseUrl(urlunsplit(parts._replace(path=f"/{database}")), self.user, database)


def environment(env: Mapping[str, str]) -> Environment:
    value = env.get("MUNISENSE_ENVIRONMENT", Environment.LOCAL.value)
    try:
        return Environment(value)
    except ValueError:
        msg = f"MUNISENSE_ENVIRONMENT must be 'local' or 'deployed', not {value!r}"
        raise SettingsError(msg) from None


def database_url(env: Mapping[str, str], name: str) -> DatabaseUrl:
    """Read and check the URL in environment variable `name`."""
    where = environment(env)
    for variable in REFUSED_ENVIRONMENT:
        if env.get(variable):
            msg = f"{variable} is set: libpq service lookups are refused"
            raise SettingsError(msg)
    raw = env.get(name) or (LOCAL_DEFAULTS.get(name) if where is Environment.LOCAL else None)
    if not raw:
        msg = f"{name} is not set"
        raise SettingsError(msg)
    return check_url(raw, where, name)


def check_url(raw: str, where: Environment, name: str) -> DatabaseUrl:
    parts = urlsplit(raw)
    if parts.scheme not in {"postgresql", "postgres"}:
        msg = f"{name} must be a postgresql:// URL"
        raise SettingsError(msg)
    user = unquote(parts.username or "")
    database = unquote(parts.path.removeprefix("/"))
    if not user or not database or not parts.hostname:
        msg = f"{name} must name a user, a host and a database"
        raise SettingsError(msg)
    options = dict(parse_qsl(parts.query, keep_blank_values=True))
    if refused := REFUSED_OPTIONS & options.keys():
        msg = f"{name} uses {sorted(refused)[0]}=: libpq service lookups are refused"
        raise SettingsError(msg)
    if options.get("gssencmode", "disable") != "disable":
        msg = f"{name} must not enable GSSAPI encryption (gssencmode=disable)"
        raise SettingsError(msg)
    if where is Environment.DEPLOYED:
        if unquote(parts.password or "") in PUBLISHED_PASSWORDS:
            msg = f"{name} uses a published local password outside a local environment"
            raise SettingsError(msg)
        if options.get("sslmode") != "verify-full":
            msg = f"{name} must use sslmode=verify-full outside a local environment"
            raise SettingsError(msg)
    options.update(FORCED_OPTIONS)
    url = urlunsplit(parts._replace(scheme="postgresql", query=urlencode(sorted(options.items()))))
    return DatabaseUrl(url, user, database)


def require_test_database(url: DatabaseUrl) -> DatabaseUrl:
    """Tests may only touch a database whose name ends in `_test` (P2 security notes)."""
    if not url.database.endswith("_test"):
        msg = f"refusing to run tests against {url.database!r}: the name must end in '_test'"
        raise SettingsError(msg)
    return url
