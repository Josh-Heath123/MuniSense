"""The first schema (P2-10): migrations, integrity constraints and the read-only app role."""

import uuid
from collections.abc import Callable, Iterator
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, Engine, inspect, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from support.database import TestDatabase

ROOT = Path(__file__).resolve().parents[3]
TABLES = {
    "alembic_version",
    "supplier",
    "customer_class",
    "tariff",
    "source_document",
    "publication",
    "tariff_version",
    "tariff_component",
    "vat_rate",
}
Insert = Callable[..., None]


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


# --- migrations -----------------------------------------------------------------------


def test_upgrade_and_downgrade(test_database: TestDatabase, migration_engine: Engine) -> None:
    config = _config(test_database)
    command.upgrade(config, "head")
    assert _tables(migration_engine) == TABLES
    command.downgrade(config, "base")
    assert _tables(migration_engine) == {"alembic_version"}
    command.upgrade(config, "head")
    assert _tables(migration_engine) == TABLES


def test_alembic_reads_the_migration_url_from_the_environment(
    test_database: TestDatabase, migration_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """As `uv run alembic upgrade head` does: no URL handed in, and the test database
    (not the development one) is the one migrated."""
    config = _config(test_database)
    command.downgrade(config, "base")
    monkeypatch.setenv("MUNISENSE_MIGRATION_DATABASE_URL", test_database.migration.url)
    del config.attributes["url"]
    command.upgrade(config, "head")
    assert _tables(migration_engine) == TABLES


def test_a_url_that_is_not_checked_is_refused(test_database: TestDatabase) -> None:
    config = _config(test_database)
    config.attributes["url"] = test_database.migration.url  # a str, not a DatabaseUrl
    with pytest.raises(TypeError, match="must be a checked DatabaseUrl"):
        command.upgrade(config, "head")


def test_migrations_refuse_a_superuser_connection(test_database: TestDatabase) -> None:
    """A stand-in engine says the role is a superuser; no superuser connection is made."""
    stand_in = MagicMock()
    connection = stand_in.connect.return_value.__enter__.return_value
    connection.execute.return_value.scalar_one.return_value = True
    with (
        patch("munisense.persistence.connection.engine", return_value=stand_in),
        pytest.raises(RuntimeError, match="never as a superuser"),
    ):
        command.upgrade(_config(test_database), "head")


# --- rows -----------------------------------------------------------------------------

TARIFF = uuid.UUID(int=1)
OTHER_TARIFF = uuid.UUID(int=2)
CURRENT = "[2026-12-01 00:00+00,)"
SUPERSEDED = "[2026-12-01 00:00+00,2026-12-05 00:00+00)"
LATER = "[2026-12-05 00:00+00,)"


def _run(connection: Connection, statement: str, **values: object) -> None:
    connection.execute(text(statement), values)


def _catalogue(connection: Connection) -> None:
    _run(
        connection,
        "INSERT INTO supplier VALUES ('s', 'S', 'municipality', 7, 'estimated', '{}')",
    )
    _run(connection, "INSERT INTO customer_class VALUES ('s', 'residential')")
    for tariff, code in ((TARIFF, "t"), (OTHER_TARIFF, "u")):
        _run(
            connection,
            "INSERT INTO tariff VALUES (:id, 's', :code, 'residential')",
            id=tariff,
            code=code,
        )


def _publication(
    connection: Connection,
    scope: str,
    code: str,
    day: str,
    n: int,
    *,
    supersedes: str | None = None,
    withdrawal: bool = False,
    pid: str | None = None,
) -> str:
    pid = pid or f"{scope}/{code}/{day}/r{n}"
    _run(
        connection,
        "INSERT INTO publication (id, kind, scope, code, effective_from, revision, published_at,"
        " published_by, supersedes, reason, is_withdrawal, checks) VALUES (:pid,"
        " CASE WHEN :scope = 'vat' THEN 'vat' ELSE 'tariff' END, :scope, :code,"
        " CAST(:day AS date), :n, '2026-12-01T00:00:00Z', 'owner', :supersedes, 'test',"
        " :withdrawal, '{}')",
        pid=pid,
        scope=scope,
        code=code,
        day=day,
        n=n,
        supersedes=supersedes,
        withdrawal=withdrawal,
    )
    return pid


def _version(
    connection: Connection, n: int, valid: str, recorded: str, *, tariff: uuid.UUID = TARIFF
) -> None:
    code = "t" if tariff == TARIFF else "u"
    pid = _publication(connection, "s", code, "2026-07-01", n)
    _run(
        connection,
        "INSERT INTO tariff_version (id, publication_id, tariff_id, valid_period, recorded_during,"
        " schema_version, status, payload) VALUES (:vid, :pid, :tariff,"
        " CAST(:valid AS daterange), CAST(:recorded AS tstzrange), 1, 'estimated', '{}')",
        vid=uuid.uuid4(),
        pid=pid,
        tariff=tariff,
        valid=valid,
        recorded=recorded,
    )


def _vat(
    connection: Connection, n: int, valid: str, recorded: str, *, country: str = "south-africa"
) -> None:
    pid = _publication(connection, "vat", country, "2018-04-01", n)
    _run(
        connection,
        "INSERT INTO vat_rate (id, publication_id, country, valid_period, recorded_during,"
        " schema_version, status, payload) VALUES (:vid, :pid, :country,"
        " CAST(:valid AS daterange), CAST(:recorded AS tstzrange), 1, 'estimated', '{}')",
        vid=uuid.uuid4(),
        pid=pid,
        country=country,
        valid=valid,
        recorded=recorded,
    )


@pytest.fixture
def connection(migrated: None, migration_engine: Engine) -> Iterator[Connection]:
    """A transaction that is always rolled back: nothing stays in the test database."""
    with migration_engine.connect() as connection:
        transaction = connection.begin()
        _catalogue(connection)
        try:
            yield connection
        finally:
            transaction.rollback()


BOTH = pytest.mark.parametrize("insert", [_version, _vat], ids=["tariff", "vat"])


# --- the overlap constraints -----------------------------------------------------------


@BOTH
def test_two_current_versions_with_overlapping_valid_time_are_refused(
    connection: Connection, insert: Insert
) -> None:
    insert(connection, 1, "[2026-07-01,2027-07-01)", CURRENT)
    with pytest.raises(IntegrityError, match="no_overlap"):
        insert(connection, 2, "[2027-01-01,2027-07-01)", CURRENT)


@BOTH
def test_a_superseded_version_may_overlap_its_successor_in_valid_time(
    connection: Connection, insert: Insert
) -> None:
    insert(connection, 1, "[2026-07-01,2027-07-01)", SUPERSEDED)
    insert(connection, 2, "[2026-07-01,2027-07-01)", LATER)


@BOTH
def test_an_overlap_in_a_past_snapshot_is_refused(connection: Connection, insert: Insert) -> None:
    """Both were believed on 2026-12-03: the record periods overlap in the past."""
    insert(connection, 1, "[2026-07-01,2027-07-01)", SUPERSEDED)
    with pytest.raises(IntegrityError, match="no_overlap"):
        insert(connection, 2, "[2026-07-01,2027-07-01)", "[2026-12-03 00:00+00,)")


@BOTH
def test_touching_periods_and_open_ends_do_not_overlap(
    connection: Connection, insert: Insert
) -> None:
    insert(connection, 1, "[2026-07-01,2027-07-01)", CURRENT)
    insert(connection, 2, "[2027-07-01,)", CURRENT)


def test_the_overlap_rule_is_per_tariff(connection: Connection) -> None:
    """Tariff B 1-phase and 3-phase share their periods (E49)."""
    _version(connection, 1, "[2026-07-01,2027-07-01)", CURRENT)
    _version(connection, 2, "[2026-07-01,2027-07-01)", CURRENT, tariff=OTHER_TARIFF)


def test_the_overlap_rule_is_per_country(connection: Connection) -> None:
    _vat(connection, 1, "[2018-04-01,)", CURRENT)
    _vat(connection, 2, "[2018-04-01,)", CURRENT, country="elsewhere")


# --- ranges ----------------------------------------------------------------------------


@BOTH
@pytest.mark.parametrize(
    ("valid", "recorded", "constraint"),
    [
        ("[2026-07-01,2026-07-01)", CURRENT, "valid_period"),
        ("(,2027-07-01)", CURRENT, "valid_period"),
        ("[2026-07-01,2027-07-01)", "[2026-12-01 00:00+00,2026-12-01 00:00+00)", "recorded_during"),
        ("[2026-07-01,2027-07-01)", "(,)", "recorded_during"),
        ("[2026-07-01,2027-07-01)", "(2026-12-01 00:00+00,)", "recorded_during"),
        ("[2026-07-01,2027-07-01)", "[2026-12-01 00:00+00,2026-12-05 00:00+00]", "recorded_during"),
    ],
    ids=[
        "empty valid",
        "unbounded valid",
        "empty record",
        "unbounded record",
        "exclusive record start",
        "inclusive record end",
    ],
)
def test_ranges_are_non_empty_bounded_below_and_half_open(
    connection: Connection, insert: Insert, valid: str, recorded: str, constraint: str
) -> None:
    with pytest.raises(IntegrityError, match=constraint):
        insert(connection, 1, valid, recorded)


# --- publications ----------------------------------------------------------------------


def test_a_publication_is_superseded_at_most_once(connection: Connection) -> None:
    first = _publication(connection, "s", "t", "2026-07-01", 1)
    _publication(connection, "s", "t", "2026-07-01", 2, supersedes=first, withdrawal=True)
    with pytest.raises(IntegrityError, match="publication_one_successor"):
        _publication(connection, "s", "t", "2026-07-01", 3, supersedes=first)


def test_a_place_holds_one_publication(connection: Connection) -> None:
    """ADR-0013's unique place (the id check is dropped here, inside the rolled-back
    transaction, only to reach this rule)."""
    _run(connection, "ALTER TABLE publication DROP CONSTRAINT publication_id_is_its_place")
    _publication(connection, "s", "t", "2026-07-01", 1)
    with pytest.raises(IntegrityError, match="publication_place_unique"):
        _publication(connection, "s", "t", "2026-07-01", 1, pid="another-id")


def _withdraw_then_supersede(connection: Connection, first: str) -> None:
    withdrawal = _publication(
        connection, "s", "t", "2026-07-01", 2, supersedes=first, withdrawal=True
    )
    _publication(connection, "s", "t", "2026-07-01", 3, supersedes=withdrawal)


@pytest.mark.parametrize(
    ("change", "constraint"),
    [
        ("id", "publication_id_is_its_place"),
        ("withdrawal without supersedes", "publication_withdrawal"),
        ("supersedes itself", "publication_not_itself"),
        ("supersedes another tariff", "publication_supersedes"),
        ("supersedes a withdrawal", "publication_supersedes"),
        ("supersedes nothing that exists", "publication_supersedes"),
    ],
)
def test_publication_integrity(connection: Connection, change: str, constraint: str) -> None:
    first = _publication(connection, "s", "t", "2026-07-01", 1)
    actions: dict[str, Callable[[], object]] = {
        "id": lambda: _publication(connection, "s", "t", "2026-07-01", 2, pid="s/t/2026-07-01/r9"),
        "withdrawal without supersedes": lambda: _publication(
            connection, "s", "t", "2026-07-01", 2, withdrawal=True
        ),
        "supersedes itself": lambda: _publication(
            connection, "s", "t", "2026-07-01", 2, supersedes="s/t/2026-07-01/r2"
        ),
        "supersedes another tariff": lambda: _publication(
            connection, "s", "u", "2026-07-01", 1, supersedes=first
        ),
        "supersedes a withdrawal": lambda: _withdraw_then_supersede(connection, first),
        "supersedes nothing that exists": lambda: _publication(
            connection, "s", "t", "2026-07-01", 2, supersedes="s/t/2026-07-01/r7"
        ),
    }
    with pytest.raises(IntegrityError, match=constraint):
        actions[change]()


@pytest.mark.parametrize("target", ["withdrawal", "vat publication"])
def test_a_tariff_version_belongs_to_a_tariff_publication_that_is_not_a_withdrawal(
    connection: Connection, target: str
) -> None:
    first = _publication(connection, "s", "t", "2026-07-01", 1)
    pid = (
        _publication(connection, "s", "t", "2026-07-01", 2, supersedes=first, withdrawal=True)
        if target == "withdrawal"
        else _publication(connection, "vat", "south-africa", "2018-04-01", 1)
    )
    with pytest.raises(IntegrityError, match="tariff_version_publication"):
        _run(
            connection,
            "INSERT INTO tariff_version (id, publication_id, tariff_id, valid_period,"
            " recorded_during, schema_version, status, payload) VALUES (:vid, :pid, :tariff,"
            " '[2026-07-01,2027-07-01)', CAST(:recorded AS tstzrange), 1, 'estimated', '{}')",
            vid=uuid.uuid4(),
            pid=pid,
            tariff=TARIFF,
            recorded=CURRENT,
        )


def test_a_vat_rate_belongs_to_a_vat_publication(connection: Connection) -> None:
    pid = _publication(connection, "s", "t", "2026-07-01", 1)
    with pytest.raises(IntegrityError, match="vat_rate_publication"):
        _run(
            connection,
            "INSERT INTO vat_rate (id, publication_id, country, valid_period, recorded_during,"
            " schema_version, status, payload) VALUES (:vid, :pid, 'south-africa',"
            " '[2018-04-01,)', CAST(:recorded AS tstzrange), 1, 'estimated', '{}')",
            vid=uuid.uuid4(),
            pid=pid,
            recorded=CURRENT,
        )


# --- the application role -------------------------------------------------------------

UPDATE_COLUMN = {
    "alembic_version": "version_num",
    "supplier": "name",
    "customer_class": "code",
    "tariff": "tariff_code",
    "source_document": "title",
    "publication": "reason",
    "tariff_version": "status",
    "tariff_component": "name",
    "vat_rate": "status",
}


@pytest.mark.usefixtures("migrated")
def test_the_app_role_reads_every_table(app_engine: Engine) -> None:
    tables = _tables(app_engine)
    assert tables == TABLES
    with app_engine.connect() as connection:
        for table in sorted(tables):
            connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()  # noqa: S608


@pytest.mark.usefixtures("migrated")
@pytest.mark.parametrize("table", sorted(UPDATE_COLUMN))
@pytest.mark.parametrize("verb", ["INSERT", "UPDATE", "DELETE", "TRUNCATE"])
def test_the_app_role_cannot_write(app_engine: Engine, table: str, verb: str) -> None:
    column = UPDATE_COLUMN[table]
    statement = {
        "INSERT": f"INSERT INTO {table} DEFAULT VALUES",
        "UPDATE": f"UPDATE {table} SET {column} = {column}",  # noqa: S608
        "DELETE": f"DELETE FROM {table}",  # noqa: S608
        "TRUNCATE": f"TRUNCATE {table}",
    }[verb]
    with app_engine.connect() as connection:
        connection.execute(text("SET SESSION CHARACTERISTICS AS TRANSACTION READ WRITE"))
        connection.commit()
        with pytest.raises(DBAPIError, match="permission denied"):
            connection.execute(text(statement))
