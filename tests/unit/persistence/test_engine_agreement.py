"""The engine connects with exactly what the settings checked (P2-3 review).

For any URL the settings accept, the connection arguments SQLAlchemy's psycopg dialect
builds hold exactly the checked user, password, host, port and database, and only the
allowed options. Hypothesis generates URLs, including awkward ones (`#`, a second `@`,
query keys hidden in values, percent-encoding), so the next parser disagreement fails here.
"""

from urllib.parse import quote

import pytest
from hypothesis import example, given, settings
from hypothesis import strategies as st

from munisense.persistence.connection import engine
from munisense.platform.settings import (
    ALLOWED_OPTIONS,
    DatabaseUrl,
    Environment,
    SettingsError,
    check_url,
)

AWKWARD = "@#?&=/:%[], ;'\"\\"
text = st.text(
    alphabet=st.characters(codec="utf-8", exclude_categories=["Cs", "Cc"])
    | st.sampled_from(AWKWARD),
    min_size=1,
    max_size=12,
)
keys = st.sampled_from(sorted(ALLOWED_OPTIONS | {"dbname", "user", "host", "password", "port"}))


def _connect_args(url: DatabaseUrl) -> dict[str, object]:
    e = engine(url, env={})
    try:
        _, kwargs = e.dialect.create_connect_args(e.url)
    finally:
        e.dispose()
    # `context` is psycopg's type-adapter map, not a connection setting.
    return {k: v for k, v in kwargs.items() if k != "context"}


def _assert_agrees(url: DatabaseUrl) -> None:
    kwargs = _connect_args(url)
    expected: dict[str, object] = {
        "user": url.user,
        "password": url.password,
        "host": url.host,
        "dbname": url.database,
        **dict(url.options),
    }
    if url.port is not None:
        expected["port"] = url.port
    assert kwargs == expected
    assert set(dict(url.options)) <= ALLOWED_OPTIONS


@settings(max_examples=300)
@given(
    user=text,
    password=text,
    database=text,
    port=st.none() | st.integers(1, 65535),
    options=st.lists(st.tuples(keys, text), max_size=4),
    raw_tail=st.sampled_from(["", "#", "#&dbname=other", "@evil.example.org", "&dbname=other"]),
    host=st.sampled_from(["localhost", "127.0.0.1", "[::1]"]),
)
@example(
    user="munisense_app",
    password="pw",  # noqa: S106  # a test value
    database="munisense_test",
    port=5432,
    options=[("sslrootcert", "/x")],
    raw_tail="#&dbname=munisense_dev",
    host="localhost",
)
def test_accepted_urls_connect_with_exactly_the_checked_parts(
    user: str,
    password: str,
    database: str,
    port: int | None,
    options: list[tuple[str, str]],
    raw_tail: str,
    host: str,
) -> None:
    query = "&".join(f"{quote(k, safe='')}={quote(v, safe='')}" for k, v in options)
    port_part = f":{port}" if port is not None else ""
    raw = (
        f"postgresql://{quote(user, safe='')}:{quote(password, safe='')}@{host}{port_part}"
        f"/{quote(database, safe='')}?{query}{raw_tail}"
    )
    try:
        url = check_url(raw, Environment.LOCAL, "MUNISENSE_DATABASE_URL")
    except SettingsError:
        return
    _assert_agrees(url)
    assert (url.user, url.password, url.database, url.port) == (user, password, database, port)


@given(raw=st.text(max_size=80).map(lambda tail: "postgresql://u:p@localhost/x_test" + tail))
def test_any_accepted_string_agrees_with_the_driver(raw: str) -> None:
    try:
        url = check_url(raw, Environment.LOCAL, "MUNISENSE_DATABASE_URL")
    except SettingsError:
        return
    _assert_agrees(url)


@pytest.mark.parametrize(
    "raw",
    [
        "postgresql://munisense_app:pw@localhost:5432/munisense_test",
        "postgresql://a%40b:p%23w%3Fx@127.0.0.1/db%2Fname?sslmode=prefer&application_name=x%26y",
        "postgresql://u:p@[::1]:5433/x_test?connect_timeout=5&sslrootcert=%2Fetc%2Fca.pem",
    ],
)
def test_known_accepted_urls_reach_the_agreement_check(raw: str) -> None:
    """The generated tests skip refused URLs; these are accepted, so the check really runs."""
    _assert_agrees(check_url(raw, Environment.LOCAL, "MUNISENSE_DATABASE_URL"))
