"""The first schema (P2-10): migrations, overlap constraints and the read-only app role."""

import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, Engine, inspect, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from support.database import TestDatabase

ROOT = Path(__file__).resolve().parents[3]
TABLES = {
    "supplier",
    "customer_class",
    "tariff",
    "source_document",
    "publication",
    "tariff_version",
    "tariff_component",
    "vat_rate",
}


def _config(test_database: TestDatabase) -> Config:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "src/munisense/persistence/migrations"))
    config.attributes["url"] = test_database.migration
    return config


@pytest.fixture
def migrated(test_database: TestDatabase) -> None:
    command.upgrade(_config(test_database), "head")


def _tables(engine: Engine) -> set[str]:
    return set(inspect(engine).get_table_names(schema="munisense"))


def test_upgrade_and_downgrade(test_database: TestDatabase, migration_engine: Engine) -> None:
    config = _config(test_database)
    command.upgrade(config, "head")
    assert _tables(migration_engine) >= TABLES
    command.downgrade(config, "base")
    assert not (_tables(migration_engine) & TABLES)
    command.upgrade(config, "head")
    assert _tables(migration_engine) >= TABLES


# --- overlap constraints ----------------------------------------------------------------

TARIFF = uuid.UUID(int=1)


def _run(connection: Connection, *statements: str, **values: object) -> None:
    """One statement per call: psycopg prepares each, so it cannot hold several."""
    for statement in statements:
        connection.execute(text(statement), values)


def _catalogue(connection: Connection) -> None:
    _run(
        connection,
        "INSERT INTO supplier VALUES ('s', 'S', 'municipality', 7)",
        "INSERT INTO customer_class VALUES ('s', 'residential')",
        "INSERT INTO tariff VALUES (:id, 's', 't', 'residential')",
        id=TARIFF,
    )


def _version(connection: Connection, n: int, valid: str, recorded: str) -> None:
    pid = f"s/t/2026-07-01/r{n}"
    _run(
        connection,
        "INSERT INTO publication VALUES (:pid, 's', 't', '2026-07-01', :n,"
        " '2026-12-01T00:00:00Z', 'owner', NULL, 'test', false, '{}')",
        pid=pid,
        n=n,
    )
    _run(
        connection,
        "INSERT INTO tariff_version VALUES (:vid, :pid, :tariff, CAST(:valid AS daterange),"
        " CAST(:recorded AS tstzrange), 1, 'estimated', '{}')",
        vid=uuid.UUID(int=100 + n),
        pid=pid,
        tariff=TARIFF,
        valid=valid,
        recorded=recorded,
    )


def _vat(connection: Connection, n: int, valid: str, recorded: str) -> None:
    pid = f"vat/south-africa/2018-04-01/r{n}"
    _run(
        connection,
        "INSERT INTO publication VALUES (:pid, 'vat', 'south-africa', '2018-04-01', :n,"
        " '2026-12-01T00:00:00Z', 'owner', NULL, 'test', false, '{}')",
        pid=pid,
        n=n,
    )
    _run(
        connection,
        "INSERT INTO vat_rate VALUES (:vid, :pid, 'south-africa', CAST(:valid AS daterange),"
        " CAST(:recorded AS tstzrange), 'estimated', '{}')",
        vid=uuid.UUID(int=200 + n),
        pid=pid,
        valid=valid,
        recorded=recorded,
    )


@pytest.fixture
def connection(migrated: None, migration_engine: Engine) -> Iterator[Connection]:
    """A transaction that is always rolled back: nothing stays in the test database."""
    with migration_engine.connect() as connection:
        transaction = connection.begin()
        try:
            yield connection
        finally:
            transaction.rollback()


CURRENT = "[2026-12-01 00:00+00,)"
SUPERSEDED = "[2026-12-01 00:00+00,2026-12-05 00:00+00)"
LATER = "[2026-12-05 00:00+00,)"


@pytest.mark.parametrize("insert", [_version, _vat], ids=["tariff", "vat"])
def test_two_current_versions_with_overlapping_valid_time_are_refused(
    connection: Connection, insert: object
) -> None:
    _catalogue(connection)
    insert(connection, 1, "[2026-07-01,2027-07-01)", CURRENT)  # type: ignore[operator]
    with pytest.raises(IntegrityError, match="no_overlap"):
        insert(connection, 2, "[2027-01-01,2027-07-01)", CURRENT)  # type: ignore[operator]


@pytest.mark.parametrize("insert", [_version, _vat], ids=["tariff", "vat"])
def test_a_superseded_version_may_overlap_its_successor_in_valid_time(
    connection: Connection, insert: object
) -> None:
    _catalogue(connection)
    insert(connection, 1, "[2026-07-01,2027-07-01)", SUPERSEDED)  # type: ignore[operator]
    insert(connection, 2, "[2026-07-01,2027-07-01)", LATER)  # type: ignore[operator]


@pytest.mark.parametrize("insert", [_version, _vat], ids=["tariff", "vat"])
def test_an_overlap_in_a_past_snapshot_is_refused(connection: Connection, insert: object) -> None:
    """Both were believed on 2026-12-03: the record periods overlap in the past."""
    _catalogue(connection)
    insert(connection, 1, "[2026-07-01,2027-07-01)", SUPERSEDED)  # type: ignore[operator]
    with pytest.raises(IntegrityError, match="no_overlap"):
        insert(connection, 2, "[2026-07-01,2027-07-01)", "[2026-12-03 00:00+00,)")  # type: ignore[operator]


def test_touching_valid_periods_do_not_overlap(connection: Connection) -> None:
    _catalogue(connection)
    _version(connection, 1, "[2026-07-01,2027-07-01)", CURRENT)
    _version(connection, 2, "[2027-07-01,2028-07-01)", CURRENT)


def test_a_publication_is_superseded_at_most_once(connection: Connection) -> None:
    _catalogue(connection)
    _version(connection, 1, "[2026-07-01,2027-07-01)", SUPERSEDED)
    insert = text(
        "INSERT INTO publication VALUES (:pid, 's', 't', '2026-07-01', :n,"
        " '2026-12-05T00:00:00Z', 'owner', 's/t/2026-07-01/r1', 'test', true, '{}')"
    )
    connection.execute(insert, {"pid": "s/t/2026-07-01/r2", "n": 2})
    with pytest.raises(IntegrityError, match="publication_one_successor"):
        connection.execute(insert, {"pid": "s/t/2026-07-01/r3", "n": 3})


# --- the application role -------------------------------------------------------------


@pytest.mark.usefixtures("migrated")
@pytest.mark.parametrize("table", sorted(TABLES))
def test_the_app_role_reads_every_table(app_engine: Engine, table: str) -> None:
    with app_engine.connect() as connection:
        connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()  # noqa: S608


@pytest.mark.usefixtures("migrated")
@pytest.mark.parametrize(
    "statement",
    [
        "INSERT INTO supplier VALUES ('x', 'X', 'municipality', 7)",
        "UPDATE tariff_version SET status = 'verified'",
        "DELETE FROM publication",
        "UPDATE vat_rate SET payload = '{}'",
        "DELETE FROM source_document",
    ],
)
def test_the_app_role_cannot_write(app_engine: Engine, statement: str) -> None:
    with app_engine.connect() as connection:
        connection.execute(text("SET SESSION CHARACTERISTICS AS TRANSACTION READ WRITE"))
        connection.commit()
        with pytest.raises(DBAPIError, match="permission denied"):
            connection.execute(text(statement))


def test_alembic_reads_the_migration_url_from_the_environment(
    test_database: TestDatabase, monkeypatch: pytest.MonkeyPatch
) -> None:
    """As `uv run alembic upgrade head` does, with no URL handed in."""
    monkeypatch.setenv("MUNISENSE_MIGRATION_DATABASE_URL", test_database.migration.url)
    config = _config(test_database)
    del config.attributes["url"]
    command.upgrade(config, "head")
    command.current(config)
