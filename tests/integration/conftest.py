"""Database tests: every test here is marked `db` and runs against `*_test` only (P2-3).

The session fixture prepares the test database's roles and schema with the bootstrap,
connecting as the local superuser (`MUNISENSE_ADMIN_DATABASE_URL`), and refuses any
database whose name does not end in `_test`.
"""

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine

from munisense.persistence.bootstrap import bootstrap
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


@pytest.fixture(scope="session")
def test_database() -> TestDatabase:
    app = require_test_database(database_url(os.environ, "MUNISENSE_TEST_DATABASE_URL"))
    migration = require_test_database(
        database_url(os.environ, "MUNISENSE_TEST_MIGRATION_DATABASE_URL")
    )
    admin = require_test_database(
        database_url(os.environ, "MUNISENSE_ADMIN_DATABASE_URL").with_database(app.database)
    )
    bootstrap(admin, app, migration)
    return TestDatabase(admin, app, migration)


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
