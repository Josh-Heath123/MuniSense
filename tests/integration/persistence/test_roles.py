"""The two database roles do only what they must (P2-3, ADR-0012)."""

from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError

PROBES = (
    ("TABLE", "munisense.p2_3_probe"),
    ("SEQUENCE", "munisense.p2_3_probe_seq"),
    ("FUNCTION", "munisense.p2_3_probe_fn()"),
)


def _scalar(e: Engine, sql: str) -> object:
    with e.connect() as connection:
        return connection.execute(text(sql)).scalar_one()


@pytest.mark.parametrize("which", ["app_engine", "migration_engine"])
def test_neither_role_is_a_superuser_or_can_create_roles_or_databases(
    which: str, request: pytest.FixtureRequest
) -> None:
    e: Engine = request.getfixturevalue(which)
    flags = _scalar(
        e,
        "SELECT rolsuper OR rolcreaterole OR rolcreatedb OR rolbypassrls"
        " FROM pg_roles WHERE rolname = current_user",
    )
    assert flags is False


@pytest.mark.parametrize("which", ["app_engine", "migration_engine"])
def test_the_driver_connects_with_the_forced_options(
    which: str, request: pytest.FixtureRequest
) -> None:
    e: Engine = request.getfixturevalue(which)
    with e.connect() as connection:
        pgconn = connection.connection.driver_connection.pgconn  # type: ignore[union-attr]
        # libpq's own values. The require_auth check is meaningful; the gssencmode one
        # cannot fail with this psycopg-binary build, whose compiled default is already
        # `disable` (the settings unit tests and the engine agreement test cover it).
        values = {option.keyword: option.val for option in pgconn.info}
    assert values[b"gssencmode"] == b"disable"
    assert values[b"require_auth"] == b"scram-sha-256"


def test_connections_use_the_munisense_schema(app_engine: Engine) -> None:
    assert _scalar(app_engine, "SHOW search_path") == "munisense"


def test_app_sessions_are_read_only_by_default(app_engine: Engine) -> None:
    assert _scalar(app_engine, "SHOW default_transaction_read_only") == "on"


@pytest.fixture
def probe_objects(migration_engine: Engine) -> Iterator[None]:
    """A table, a sequence and a function made by the migration role."""
    with migration_engine.begin() as connection:
        for kind, name in PROBES:
            connection.execute(text(f"DROP {kind} IF EXISTS {name}"))
        connection.execute(text("CREATE TABLE munisense.p2_3_probe (x int)"))
        connection.execute(text("INSERT INTO munisense.p2_3_probe VALUES (1)"))
        connection.execute(text("CREATE SEQUENCE munisense.p2_3_probe_seq"))
        connection.execute(
            text("CREATE FUNCTION munisense.p2_3_probe_fn() RETURNS int LANGUAGE sql AS 'SELECT 1'")
        )
    yield
    with migration_engine.begin() as connection:
        for kind, name in PROBES:
            connection.execute(text(f"DROP {kind} {name}"))


@pytest.mark.usefixtures("probe_objects")
def test_the_app_role_reads_tables_the_migration_role_creates(app_engine: Engine) -> None:
    assert _scalar(app_engine, "SELECT x FROM munisense.p2_3_probe") == 1


@pytest.mark.usefixtures("probe_objects")
@pytest.mark.parametrize(
    "statement",
    [
        "INSERT INTO munisense.p2_3_probe VALUES (2)",
        "UPDATE munisense.p2_3_probe SET x = 3",
        "DELETE FROM munisense.p2_3_probe",
        "TRUNCATE munisense.p2_3_probe",
        "DROP TABLE munisense.p2_3_probe",
        "CREATE TABLE munisense.p2_3_other (x int)",
        "CREATE TABLE public.p2_3_other (x int)",
        "CREATE TEMP TABLE p2_3_temp (x int)",
        "SELECT nextval('munisense.p2_3_probe_seq')",
        "SELECT munisense.p2_3_probe_fn()",
    ],
)
def test_the_app_role_is_refused_everything_but_reading(app_engine: Engine, statement: str) -> None:
    # Read-only sessions are switched off first, so the refusal shown is the privilege
    # check itself, not only the read-only default.
    with app_engine.connect() as connection:
        connection.execute(text("SET SESSION CHARACTERISTICS AS TRANSACTION READ WRITE"))
        connection.commit()
        with pytest.raises(DBAPIError, match=r"permission denied|must be owner"):
            connection.execute(text(statement))
