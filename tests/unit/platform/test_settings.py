"""Database settings refuse unsafe values before anything connects (P2-3)."""

import pytest

from munisense.platform.settings import (
    LOCAL_DEFAULTS,
    DatabaseUrl,
    Environment,
    SettingsError,
    database_url,
    environment,
    require_test_database,
)

APP = "MUNISENSE_DATABASE_URL"
SAFE = "postgresql://munisense_app:a-real-secret@db.example.org:5432/munisense?sslmode=verify-full"


def test_the_environment_is_local_by_default() -> None:
    assert environment({}) is Environment.LOCAL
    assert environment({"MUNISENSE_ENVIRONMENT": "deployed"}) is Environment.DEPLOYED


def test_an_unknown_environment_is_refused() -> None:
    with pytest.raises(SettingsError, match="'local' or 'deployed'"):
        environment({"MUNISENSE_ENVIRONMENT": "production"})


def test_a_local_environment_falls_back_to_the_published_defaults() -> None:
    url = database_url({}, APP)
    assert url.user == "munisense_app"
    assert url.database == "munisense_dev"


@pytest.mark.parametrize("name", sorted(LOCAL_DEFAULTS))
def test_every_connection_disables_gssapi_encryption(name: str) -> None:
    assert "gssencmode=disable" in database_url({}, name).url


def test_gssencmode_is_forced_even_when_the_url_omits_it() -> None:
    url = database_url({APP: "postgresql://u:p@localhost/x_dev?sslmode=prefer"}, APP)
    assert url.url == "postgresql://u:p@localhost/x_dev?gssencmode=disable&sslmode=prefer"


def test_a_url_that_enables_gssapi_encryption_is_refused() -> None:
    with pytest.raises(SettingsError, match="gssencmode=disable"):
        database_url({APP: "postgresql://u:p@localhost/x?gssencmode=prefer"}, APP)


@pytest.mark.parametrize("option", ["service=munisense", "servicefile=/tmp/s.conf"])
def test_service_lookups_in_the_url_are_refused(option: str) -> None:
    with pytest.raises(SettingsError, match="service lookups are refused"):
        database_url({APP: f"postgresql://u:p@localhost/x?{option}"}, APP)


@pytest.mark.parametrize("variable", ["PGSERVICE", "PGSERVICEFILE"])
def test_service_lookups_from_the_environment_are_refused(variable: str) -> None:
    with pytest.raises(SettingsError, match=f"{variable} is set"):
        database_url({variable: "munisense"}, APP)


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ("mysql://u:p@localhost/x", "postgresql:// URL"),
        ("postgresql://localhost/x", "a user, a host and a database"),
        ("postgresql://u:p@localhost/", "a user, a host and a database"),
        ("postgresql://u:p@/x", "a user, a host and a database"),
    ],
)
def test_a_malformed_url_is_refused(raw: str, message: str) -> None:
    with pytest.raises(SettingsError, match=message):
        database_url({APP: raw}, APP)


def test_a_deployed_environment_needs_every_url_set() -> None:
    with pytest.raises(SettingsError, match="is not set"):
        database_url({"MUNISENSE_ENVIRONMENT": "deployed"}, APP)


@pytest.mark.parametrize("password", ["munisense-local-only", "ci-only-not-a-secret"])
def test_a_deployed_environment_refuses_the_published_passwords(password: str) -> None:
    raw = SAFE.replace("a-real-secret", password)
    with pytest.raises(SettingsError, match="published local password"):
        database_url({"MUNISENSE_ENVIRONMENT": "deployed", APP: raw}, APP)


@pytest.mark.parametrize("query", ["", "?sslmode=require", "?sslmode=verify-ca"])
def test_a_deployed_environment_requires_verify_full(query: str) -> None:
    raw = SAFE.removesuffix("?sslmode=verify-full") + query
    with pytest.raises(SettingsError, match="sslmode=verify-full"):
        database_url({"MUNISENSE_ENVIRONMENT": "deployed", APP: raw}, APP)


def test_a_safe_deployed_url_is_accepted() -> None:
    url = database_url({"MUNISENSE_ENVIRONMENT": "deployed", APP: SAFE}, APP)
    assert url.url.endswith("?gssencmode=disable&sslmode=verify-full")


def test_the_local_ci_container_does_not_need_tls() -> None:
    raw = "postgresql://munisense_app:ci-only-not-a-secret@localhost:5432/munisense_test"
    assert database_url({APP: raw}, APP).database == "munisense_test"


def test_with_database_changes_only_the_database() -> None:
    url = database_url({}, APP).with_database("munisense_test")
    assert url.database == "munisense_test"
    assert url.url.startswith("postgresql://munisense_app:")
    assert "/munisense_test?gssencmode=disable" in url.url


@pytest.mark.parametrize("name", ["munisense_dev", "munisense", "munisense_test_copy"])
def test_tests_refuse_a_database_not_named_test(name: str) -> None:
    url = DatabaseUrl(f"postgresql://u:p@localhost/{name}", "u", name)
    with pytest.raises(SettingsError, match="must end in '_test'"):
        require_test_database(url)


def test_tests_accept_a_test_database() -> None:
    url = DatabaseUrl("postgresql://u:p@localhost/munisense_test", "u", "munisense_test")
    assert require_test_database(url) is url
