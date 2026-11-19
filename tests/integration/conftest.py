"""Database tests: every test here is marked `db` and runs against `*_test` only (P2-3).

They connect as the two roles only, never as a superuser. The roles and schema are made
beforehand by `uv run poe db-bootstrap` (CI runs it as a step before the tests). The
bootstrap's own tests, which must connect as the superuser, live in `bootstrap/` and are
also marked `db_admin`.
"""

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import OperationalError

from munisense.persistence.connection import engine
from munisense.platform.settings import database_url, require_test_database
from support.database import TestDatabase

# Not resolved: `resolve()` per item is slow on the /mnt/c disk, and this hook sees every
# collected test, not only this folder's.
HERE = Path(__file__).parent


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        if item.path.is_relative_to(HERE):
            item.add_marker(pytest.mark.db)
            if item.path.is_relative_to(HERE / "bootstrap"):
                item.add_marker(pytest.mark.db_admin)


@pytest.fixture(scope="session")
def test_database() -> TestDatabase:
    app = require_test_database(database_url(os.environ, "MUNISENSE_TEST_DATABASE_URL"))
    migration = require_test_database(
        database_url(os.environ, "MUNISENSE_TEST_MIGRATION_DATABASE_URL")
    )
    probe = engine(app)
    try:
        with probe.connect() as connection:
            connection.execute(text("SELECT 1"))
    except OperationalError:
        pytest.fail("cannot connect as the app role: run `uv run poe db-bootstrap` first")
    finally:
        probe.dispose()
    return TestDatabase(app, migration)


@pytest.fixture
def app_engine(test_database: TestDatabase) -> Iterator[Engine]:
    e = engine(test_database.app)
    yield e
    e.dispose()


@pytest.fixture
def migration_engine(test_database: TestDatabase) -> Iterator[Engine]:
    e = engine(test_database.migration)
    yield e
    e.dispose()
