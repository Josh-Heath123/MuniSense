"""The bootstrap itself: these tests connect as the local superuser (`db_admin`, P2-3)."""

import os
from collections.abc import Callable, Iterator
from dataclasses import replace
from unittest.mock import patch

import pytest
from sqlalchemy import Engine, event, text

from munisense.persistence import bootstrap as bootstrap_module
from munisense.persistence.bootstrap import bootstrap
from munisense.persistence.connection import engine
from munisense.platform.settings import DatabaseUrl, database_url, require_test_database
from support.database import TestDatabase


def _recording_engine(listener: Callable[..., None]) -> Callable[[DatabaseUrl], Engine]:
    def make(url: DatabaseUrl) -> Engine:
        e = engine(url)
        event.listen(e, "before_cursor_execute", listener)
        return e

    return make


@pytest.fixture
def admin(test_database: TestDatabase) -> DatabaseUrl:
    url = database_url(os.environ, "MUNISENSE_ADMIN_DATABASE_URL")
    return require_test_database(url.with_database(test_database.app.database))


@pytest.fixture
def admin_engine(admin: DatabaseUrl) -> Iterator[Engine]:
    e = engine(admin)
    yield e
    e.dispose()


def test_the_bootstrap_never_sends_a_password_in_plain_text(
    test_database: TestDatabase, admin: DatabaseUrl
) -> None:
    """Every statement and bound value the bootstrap sends is recorded; none holds a password.

    (Checking the stored value alone would prove nothing: the server stores SCRAM by default.)
    """
    sent: list[str] = []

    def record(
        _conn: object, _cursor: object, statement: str, parameters: object, *_: object
    ) -> None:
        sent.append(f"{statement} {parameters!r}")

    db = test_database
    with patch.object(bootstrap_module, "engine", _recording_engine(record)):
        bootstrap(admin, db.app, db.migration)
    assert sent
    assert not [s for s in sent if db.app.password in s or db.migration.password in s]


def test_passwords_are_stored_as_scram_verifiers(admin_engine: Engine) -> None:
    with admin_engine.connect() as connection:
        stored = list(
            connection.execute(
                text("SELECT rolpassword FROM pg_authid WHERE rolname LIKE 'munisense_%'")
            ).scalars()
        )
    assert stored
    assert all(p.startswith("SCRAM-SHA-256$") for p in stored)


def test_the_bootstrap_creates_a_role_that_does_not_exist(
    test_database: TestDatabase, admin: DatabaseUrl, admin_engine: Engine
) -> None:
    db = test_database
    probe = replace(db.app, user="munisense_p2_3_probe")
    try:
        bootstrap(admin, probe, db.migration)
        with admin_engine.connect() as connection:
            row = connection.execute(
                text("SELECT rolsuper FROM pg_roles WHERE rolname = 'munisense_p2_3_probe'")
            ).one()
        assert row.rolsuper is False
    finally:
        with admin_engine.begin() as connection:
            connection.execute(text("DROP OWNED BY munisense_p2_3_probe"))
            connection.execute(text("DROP ROLE munisense_p2_3_probe"))


def test_the_command_is_idempotent(test_database: TestDatabase, admin: DatabaseUrl) -> None:
    db = test_database
    env = {
        "MUNISENSE_ADMIN_DATABASE_URL": admin.url,
        "MUNISENSE_DATABASE_URL": db.app.url,
        "MUNISENSE_MIGRATION_DATABASE_URL": db.migration.url,
        "MUNISENSE_TEST_DATABASE_URL": db.app.url,
        "MUNISENSE_TEST_MIGRATION_DATABASE_URL": db.migration.url,
    }
    assert bootstrap_module.main(env) == 0
    assert bootstrap_module.main(env) == 0
