"""The two database roles do only what they must (P2-3, ADR-0012)."""

from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import ProgrammingError

from munisense.persistence import bootstrap as bootstrap_module
from munisense.persistence.bootstrap import bootstrap
from munisense.persistence.connection import engine
from munisense.platform.settings import DatabaseUrl
from support.database import TestDatabase


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
def test_connections_do_not_use_gssapi_encryption(
    which: str, request: pytest.FixtureRequest
) -> None:
    e: Engine = request.getfixturevalue(which)
    assert _scalar(e, "SELECT encrypted FROM pg_stat_gssapi WHERE pid = pg_backend_pid()") is False


def test_connections_use_the_munisense_schema(app_engine: Engine) -> None:
    assert _scalar(app_engine, "SHOW search_path") == "munisense"


@pytest.mark.parametrize("schema", ["munisense", "public"])
def test_the_app_role_cannot_create_tables(app_engine: Engine, schema: str) -> None:
    with (
        app_engine.connect() as connection,
        pytest.raises(ProgrammingError, match="permission denied"),
    ):
        connection.execute(text(f"CREATE TABLE {schema}.p2_3_probe (x int)"))


@pytest.fixture
def probe_table(migration_engine: Engine) -> Iterator[str]:
    with migration_engine.begin() as connection:
        connection.execute(text("DROP TABLE IF EXISTS munisense.p2_3_probe"))
        connection.execute(text("CREATE TABLE munisense.p2_3_probe (x int)"))
        connection.execute(text("INSERT INTO munisense.p2_3_probe VALUES (1)"))
    yield "munisense.p2_3_probe"
    with migration_engine.begin() as connection:
        connection.execute(text("DROP TABLE munisense.p2_3_probe"))


def test_the_app_role_reads_tables_the_migration_role_creates(
    app_engine: Engine, probe_table: str
) -> None:
    assert _scalar(app_engine, "SELECT x FROM munisense.p2_3_probe") == 1


@pytest.mark.parametrize(
    "statement",
    [
        "INSERT INTO {t} VALUES (2)",
        "UPDATE {t} SET x = 3",
        "DELETE FROM {t}",
        "TRUNCATE {t}",
        "DROP TABLE {t}",
    ],
)
def test_the_app_role_cannot_change_data(
    app_engine: Engine, probe_table: str, statement: str
) -> None:
    with app_engine.connect() as connection, pytest.raises(ProgrammingError):
        connection.execute(text(statement.format(t=probe_table)))


def test_the_bootstrap_is_idempotent_and_runs_from_its_command(
    test_database: TestDatabase, app_engine: Engine
) -> None:
    db = test_database
    env = {
        "MUNISENSE_ADMIN_DATABASE_URL": db.admin.url,
        "MUNISENSE_DATABASE_URL": db.app.url,
        "MUNISENSE_MIGRATION_DATABASE_URL": db.migration.url,
        "MUNISENSE_TEST_DATABASE_URL": db.app.url,
        "MUNISENSE_TEST_MIGRATION_DATABASE_URL": db.migration.url,
    }
    assert bootstrap_module.main(env) == 0
    assert _scalar(app_engine, "SELECT current_user") == db.app.user


def test_the_bootstrap_creates_a_role_that_does_not_exist(test_database: TestDatabase) -> None:
    db = test_database
    probe = DatabaseUrl(
        db.app.url.replace(f"//{db.app.user}:", "//munisense_p2_3_probe:", 1),
        "munisense_p2_3_probe",
        db.app.database,
    )
    admin = engine(db.admin)
    try:
        bootstrap(db.admin, probe, db.migration)
        with admin.connect() as connection:
            row = connection.execute(
                text("SELECT rolsuper FROM pg_roles WHERE rolname = 'munisense_p2_3_probe'")
            ).one()
        assert row.rolsuper is False
    finally:
        with admin.begin() as connection:
            connection.execute(text("DROP OWNED BY munisense_p2_3_probe"))
            connection.execute(text("DROP ROLE munisense_p2_3_probe"))
        admin.dispose()
