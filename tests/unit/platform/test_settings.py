"""Database settings refuse unsafe values before anything connects (P2-3)."""

from urllib.parse import quote

import pytest

from munisense.platform.settings import (
    ALLOWED_OPTIONS,
    LIBPQ_ENVIRONMENT,
    LOCAL_DEFAULTS,
    PUBLISHED_PASSWORDS,
    DatabaseUrl,
    Environment,
    SettingsError,
    database_url,
    environment,
    require_test_database,
)

APP = "MUNISENSE_DATABASE_URL"
DEPLOYED = {"MUNISENSE_ENVIRONMENT": "deployed"}
SAFE = "postgresql://munisense_app:a-real-secret@db.example.org:5432/munisense?sslmode=verify-full"
LOCAL = "postgresql://u:p@localhost/x_test"


def _url(database: str) -> DatabaseUrl:
    return DatabaseUrl("u", "p", "localhost", None, database, ())


def test_the_environment_is_local_by_default() -> None:
    assert environment({}) is Environment.LOCAL
    assert environment(DEPLOYED) is Environment.DEPLOYED


def test_an_unknown_environment_is_refused() -> None:
    with pytest.raises(SettingsError, match="'local' or 'deployed'"):
        environment({"MUNISENSE_ENVIRONMENT": "production"})


def test_a_local_environment_falls_back_to_the_published_defaults() -> None:
    url = database_url({}, APP)
    assert (url.user, url.database) == ("munisense_app", "munisense_dev")


@pytest.mark.parametrize("name", sorted(LOCAL_DEFAULTS))
def test_every_connection_forces_the_safe_authentication_options(name: str) -> None:
    url = database_url({}, name).url
    assert "gssencmode=disable" in url
    assert "require_auth=scram-sha-256" in url


def test_the_forced_options_are_added_to_a_url_without_them() -> None:
    url = database_url({APP: LOCAL + "?sslmode=prefer"}, APP)
    assert url.url == (
        "postgresql://u:p@localhost/x_test?gssencmode=disable"
        "&require_auth=scram-sha-256&sslmode=prefer"
    )


@pytest.mark.parametrize(
    "query", ["gssencmode=prefer", "require_auth=gss", "require_auth=password"]
)
def test_weaker_authentication_options_are_refused(query: str) -> None:
    with pytest.raises(SettingsError, match="must use"):
        database_url({APP: f"{LOCAL}?{query}"}, APP)


@pytest.mark.parametrize(
    "key",
    [
        "dbname",
        "user",
        "password",
        "host",
        "hostaddr",
        "port",
        "options",
        "service",
        "servicefile",
        "passfile",
        "krbsrvname",
        "gsslib",
    ],
)
def test_query_keys_that_could_replace_what_was_checked_are_refused(key: str) -> None:
    with pytest.raises(SettingsError, match=f"sets {key}="):
        database_url({APP: f"{LOCAL}?{key}=x"}, APP)


def test_a_percent_encoded_refused_key_is_refused() -> None:
    with pytest.raises(SettingsError, match="sets dbname="):
        database_url({APP: f"{LOCAL}?db%6Eame=munisense_dev"}, APP)


def test_every_allowed_option_is_accepted() -> None:
    query = "&".join(f"{key}=x" for key in sorted(ALLOWED_OPTIONS - {"gssencmode", "require_auth"}))
    assert database_url({APP: f"{LOCAL}?{query}"}, APP).database == "x_test"


def test_a_repeated_key_keeps_its_last_value_once() -> None:
    url = database_url({APP: f"{LOCAL}?sslmode=disable&sslmode=require"}, APP).url
    assert url.count("sslmode=") == 1
    assert "sslmode=require" in url


@pytest.mark.parametrize("variable", LIBPQ_ENVIRONMENT)
def test_every_libpq_environment_variable_is_refused_even_empty(variable: str) -> None:
    with pytest.raises(SettingsError, match=f"{variable} is set"):
        database_url({variable: ""}, APP)


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ("mysql://u:p@localhost/x", "postgresql:// URL"),
        ("postgresql://localhost/x", "a user, a host and a database"),
        ("postgresql://u:p@localhost/", "a user, a host and a database"),
        ("postgresql://u:p@/x", "a user, a host and a database"),
        ("postgresql://u:p@[::1/x", "not a valid URL"),
        ("postgresql://u:p@localhost:port/x", "not a valid URL"),
        ("postgresql://u:p@localhost,127.0.0.1/x", "one host"),
    ],
)
def test_a_malformed_url_is_refused_without_echoing_it(raw: str, message: str) -> None:
    with pytest.raises(SettingsError, match=message) as refused:
        database_url({APP: raw}, APP)
    assert "u:p" not in str(refused.value)


def test_percent_encoded_credentials_are_decoded() -> None:
    raw = f"postgresql://{quote('app user')}:{quote('p@ss:w/rd', safe='')}@localhost/x_test"
    url = database_url({APP: raw}, APP)
    assert (url.user, url.password) == ("app user", "p@ss:w/rd")


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "[::1]"])
def test_a_local_environment_accepts_loopback_hosts(host: str) -> None:
    assert database_url({APP: f"postgresql://u:p@{host}:5432/x_test"}, APP).user == "u"


def test_a_local_environment_refuses_a_remote_host() -> None:
    with pytest.raises(SettingsError, match="not loopback"):
        database_url({APP: SAFE}, APP)


def test_the_postgres_scheme_becomes_postgresql() -> None:
    url = database_url({APP: "postgres://u:p@localhost/x_test"}, APP).url
    assert url.startswith("postgresql://u:p@localhost/x_test?")


def test_a_deployed_environment_needs_every_url_set() -> None:
    with pytest.raises(SettingsError, match="is not set"):
        database_url(DEPLOYED, APP)


def test_every_published_password_is_in_the_refused_set() -> None:
    defaults = {database_url({}, name).password for name in LOCAL_DEFAULTS}
    assert defaults | {"ci-only-not-a-secret"} == PUBLISHED_PASSWORDS


@pytest.mark.parametrize("password", sorted(PUBLISHED_PASSWORDS))
@pytest.mark.parametrize("encode", [False, True])
def test_a_deployed_environment_refuses_the_published_passwords(
    password: str, *, encode: bool
) -> None:
    written = "".join(f"%{ord(c):02X}" for c in password) if encode else password
    with pytest.raises(SettingsError, match="published local password"):
        database_url({**DEPLOYED, APP: SAFE.replace("a-real-secret", written)}, APP)


@pytest.mark.parametrize("query", ["", "?sslmode=require", "?sslmode=verify-ca"])
def test_a_deployed_environment_requires_verify_full(query: str) -> None:
    raw = SAFE.removesuffix("?sslmode=verify-full") + query
    with pytest.raises(SettingsError, match="sslmode=verify-full"):
        database_url({**DEPLOYED, APP: raw}, APP)


def test_a_safe_deployed_url_is_accepted() -> None:
    url = database_url({**DEPLOYED, APP: SAFE}, APP)
    assert url.url.endswith("?gssencmode=disable&require_auth=scram-sha-256&sslmode=verify-full")


def test_the_repr_never_shows_the_password() -> None:
    assert "munisense-app-local-only" not in repr(database_url({}, APP))


def test_with_database_changes_only_the_database() -> None:
    url = database_url({}, APP).with_database("munisense_test")
    assert url.database == "munisense_test"
    assert url.password == database_url({}, APP).password
    assert "/munisense_test?gssencmode=disable" in url.url


@pytest.mark.parametrize("name", ["munisense_dev", "munisense", "munisense_test_copy"])
def test_tests_refuse_a_database_not_named_test(name: str) -> None:
    url = _url(name)
    with pytest.raises(SettingsError, match="must end in '_test'"):
        require_test_database(url)


def test_tests_accept_a_test_database() -> None:
    url = _url("munisense_test")
    assert require_test_database(url) is url


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        (f"{LOCAL}?sslrootcert=/x#&dbname=munisense_dev", "must not contain '#'"),
        (f"{LOCAL}#fragment", "must not contain '#'"),
        ("postgresql://u:p@evil.example.org@localhost/x_test", "exactly one '@'"),
        ("postgresql://u:p@%2Fvar%2Frun%2Fpostgresql/x_test", "percent-encode the host"),
        ("postgresql://u:p@db%2Eexample.org/x_test", "percent-encode the host"),
    ],
)
def test_urls_that_parsers_read_differently_are_refused(raw: str, message: str) -> None:
    with pytest.raises(SettingsError, match=message):
        database_url({APP: raw}, APP)


def test_a_deployed_unix_socket_is_refused() -> None:
    raw = "postgresql://u:a-real-secret@%2Fvar%2Frun%2Fpostgresql/prod?sslmode=verify-full"
    with pytest.raises(SettingsError, match="cannot name a Unix socket"):
        database_url({**DEPLOYED, APP: raw}, APP)


def test_the_url_property_reads_back_to_the_same_parts() -> None:
    raw = "postgresql://app%20user:p%40ss%3Aw%2Frd@[::1]:5433/x_test?sslmode=prefer"
    url = database_url({APP: raw}, APP)
    assert database_url({APP: url.url}, APP) == url
    assert (url.host, url.port) == ("::1", 5433)


def test_every_libpq_environment_variable_is_listed() -> None:
    """Checked against the bundled libpq's own option table (PQconndefaults)."""
    from psycopg import pq  # tests may import the driver

    libpq = {o.envvar.decode() for o in pq.Conninfo.get_defaults() if o.envvar}
    assert libpq <= set(LIBPQ_ENVIRONMENT)
