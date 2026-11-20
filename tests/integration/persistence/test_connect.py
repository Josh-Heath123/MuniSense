"""`persistence.connection.connect`: what a service sees when the database is not usable (P2-13).

Every message names the database only: never the URL, the host, the role or the password.
"""

from dataclasses import replace

import pytest
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

from munisense.persistence.connection import (
    DatabaseNotReadyError,
    DatabaseUnavailableError,
    connect,
)
from support.database import TestDatabase


@pytest.mark.parametrize("wrong", ["password", "database"])
def test_a_refused_connection_names_the_database_only(
    test_database: TestDatabase, wrong: str
) -> None:
    url = test_database.app
    url = (
        replace(url, password="not-the-" + "password")
        if wrong == "password"
        else url.with_database("munisense_missing_test")
    )
    with pytest.raises(DatabaseUnavailableError) as refused, connect(url):
        pass  # pragma: no cover  # never reached
    assert str(refused.value) == f"cannot connect to the database {url.database!r}"
    assert refused.value.__suppress_context__  # the driver's message is not shown


def test_a_missing_table_means_the_database_is_not_ready(test_database: TestDatabase) -> None:
    with pytest.raises(DatabaseNotReadyError) as not_ready, connect(test_database.app) as c:
        c.execute(text("SELECT * FROM no_such_table"))
    assert str(not_ready.value) == (
        f"the database {test_database.app.database!r} has no tables, or the role cannot read them"
    )


def test_other_query_errors_pass_through(test_database: TestDatabase) -> None:
    with pytest.raises(ProgrammingError), connect(test_database.app) as c:
        c.execute(text("SELEC 1"))  # a syntax error is a bug, not an unready database
