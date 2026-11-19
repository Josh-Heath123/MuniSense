"""Database settings, read from the environment and checked before anything connects (P2-3).

Two kinds of environment:

- `local`: a developer's machine and CI, whose PostgreSQL is a throwaway container bound to
  localhost (E50). Every host must be a loopback address, so a remote database can never be
  treated as local by forgetting a setting. Unset URLs fall back to the published local
  defaults, which also appear in `docker-compose.yml`, `.env.example` and `ci.yml`.
- `deployed`: anything else. Every URL must be set explicitly, must not use a published
  password, and must require `sslmode=verify-full`.

Every connection:

- uses only the user, password, host, port and database written in the URL itself. Query
  keys are an allow-list, so `?dbname=`, `?user=`, `?host=` and `?password=` cannot replace
  what was checked;
- refuses the libpq environment variables (`PGHOST`, `PGPASSWORD`, `PGSERVICE` and the rest),
  which libpq would otherwise read at connect time;
- forces `gssencmode=disable` and `require_auth=scram-sha-256`, so neither GSSAPI encryption
  nor Kerberos authentication is ever negotiated, and no server can downgrade the login to a
  cleartext or MD5 password. Together with refusing service lookups (the way `ldap://`
  service entries are reached), this keeps the old Kerberos and LDAP code bundled in
  psycopg-binary off the connection path (P2-2 security review, TD-15).
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit, urlunsplit


class SettingsError(ValueError):
    """A setting is missing, malformed or unsafe. The message never contains the URL."""


class Environment(StrEnum):
    LOCAL = "local"
    DEPLOYED = "deployed"


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
    "MUNISENSE_ADMIN_DATABASE_URL": (
        "postgresql://munisense:munisense-local-only@localhost:5432/munisense_dev"
    ),
    "MUNISENSE_DATABASE_URL": (
        "postgresql://munisense_app:munisense-app-local-only@localhost:5432/munisense_dev"
    ),
    "MUNISENSE_MIGRATION_DATABASE_URL": (
        "postgresql://munisense_migration:munisense-migration-local-only"
        "@localhost:5432/munisense_dev"
    ),
    "MUNISENSE_TEST_DATABASE_URL": (
        "postgresql://munisense_app:munisense-app-local-only@localhost:5432/munisense_test"
    ),
    "MUNISENSE_TEST_MIGRATION_DATABASE_URL": (
        "postgresql://munisense_migration:munisense-migration-local-only"
        "@localhost:5432/munisense_test"
    ),
}

LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})

FORCED_OPTIONS = {"gssencmode": "disable", "require_auth": "scram-sha-256"}

# Query keys a URL may carry: TLS, timeouts and labels. Everything else is refused, in
# particular `dbname`, `user`, `password`, `host`, `hostaddr`, `port`, `options`, `service`.
ALLOWED_OPTIONS = frozenset(
    {
        "sslmode",
        "sslrootcert",
        "sslcert",
        "sslkey",
        "sslcrl",
        "sslnegotiation",
        "channel_binding",
        "connect_timeout",
        "application_name",
        "target_session_attrs",
    }
    | FORCED_OPTIONS.keys()
)

# Environment variables libpq reads at connect time (PostgreSQL 18 documentation, "Environment
# Variables"). Any of them, even empty, is refused: the URL is the only source of settings.
LIBPQ_ENVIRONMENT = (
    "PGHOST",
    "PGHOSTADDR",
    "PGPORT",
    "PGDATABASE",
    "PGUSER",
    "PGPASSWORD",
    "PGPASSFILE",
    "PGREQUIREAUTH",
    "PGCHANNELBINDING",
    "PGSERVICE",
    "PGSERVICEFILE",
    "PGOPTIONS",
    "PGAPPNAME",
    "PGSSLMODE",
    "PGREQUIRESSL",
    "PGSSLNEGOTIATION",
    "PGSSLCOMPRESSION",
    "PGSSLCERT",
    "PGSSLKEY",
    "PGSSLCERTMODE",
    "PGSSLROOTCERT",
    "PGSSLCRL",
    "PGSSLCRLDIR",
    "PGSSLSNI",
    "PGREQUIREPEER",
    "PGSSLMINPROTOCOLVERSION",
    "PGSSLMAXPROTOCOLVERSION",
    "PGGSSENCMODE",
    "PGKRBSRVNAME",
    "PGGSSLIB",
    "PGGSSDELEGATION",
    "PGCONNECT_TIMEOUT",
    "PGCLIENTENCODING",
    "PGTARGETSESSIONATTRS",
    "PGLOADBALANCEHOSTS",
    "PGMINPROTOCOLVERSION",
    "PGMAXPROTOCOLVERSION",
    "PGDATESTYLE",
    "PGTZ",
    "PGGEQO",
    "PGSYSCONFDIR",
    "PGLOCALEDIR",
)


@dataclass(frozen=True)
class DatabaseUrl:
    """A checked libpq URL. Its `repr` never shows the URL, which holds the password."""

    url: str = field(repr=False)
    user: str
    database: str

    @property
    def password(self) -> str:
        return unquote(urlsplit(self.url).password or "")

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


def refuse_libpq_environment(env: Mapping[str, str]) -> None:
    """Refuse every libpq environment variable, set even to an empty string."""
    if found := [name for name in LIBPQ_ENVIRONMENT if name in env]:
        msg = f"{found[0]} is set: database settings come only from the MUNISENSE_* URLs"
        raise SettingsError(msg)


def database_url(env: Mapping[str, str], name: str) -> DatabaseUrl:
    """Read and check the URL in environment variable `name`."""
    where = environment(env)
    refuse_libpq_environment(env)
    raw = env.get(name) or (LOCAL_DEFAULTS.get(name) if where is Environment.LOCAL else None)
    if not raw:
        msg = f"{name} is not set"
        raise SettingsError(msg)
    return check_url(raw, where, name)


def check_url(raw: str, where: Environment, name: str) -> DatabaseUrl:
    try:
        parts = urlsplit(raw)
        hostname, password = parts.hostname, unquote(parts.password or "")
        parts.port  # noqa: B018  # parsed for its check: a malformed port raises
    except ValueError:
        msg = f"{name} is not a valid URL"
        raise SettingsError(msg) from None
    if parts.scheme not in {"postgresql", "postgres"}:
        msg = f"{name} must be a postgresql:// URL"
        raise SettingsError(msg)
    user = unquote(parts.username or "")
    database = unquote(parts.path.removeprefix("/"))
    if not user or not database or not hostname:
        msg = f"{name} must name a user, a host and a database"
        raise SettingsError(msg)
    if "," in parts.netloc:
        msg = f"{name} must name one host"
        raise SettingsError(msg)
    options = dict(parse_qsl(parts.query, keep_blank_values=True))
    if refused := sorted(options.keys() - ALLOWED_OPTIONS):
        msg = f"{name} sets {refused[0]}=, which only the URL itself may give (or never)"
        raise SettingsError(msg)
    for key, value in FORCED_OPTIONS.items():
        if options.get(key, value) != value:
            msg = f"{name} must use {key}={value}"
            raise SettingsError(msg)
    if where is Environment.LOCAL and hostname not in LOOPBACK_HOSTS:
        msg = f"{name} names a host that is not loopback; set MUNISENSE_ENVIRONMENT=deployed"
        raise SettingsError(msg)
    if where is Environment.DEPLOYED:
        if password in PUBLISHED_PASSWORDS:
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
