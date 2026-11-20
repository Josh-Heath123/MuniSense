"""SQLAlchemy engines from checked settings (P2-3)."""

import os
from collections.abc import Iterator, Mapping
from contextlib import contextmanager

from sqlalchemy import URL, Connection, Engine, create_engine
from sqlalchemy.exc import DBAPIError, OperationalError, ProgrammingError

from munisense.platform.settings import DatabaseUrl, refuse_libpq_environment

SCHEMA = "munisense"


class DatabaseUnavailableError(ConnectionError):
    """The database could not be reached or refused the connection.

    The message names the database, never the URL. psycopg gives no SQLSTATE for a failed
    connection (checked on psycopg 3 against PostgreSQL 17: `None` for a wrong password and
    for a missing database), so a server that is down and one that refused the role, the
    password or the database name are not told apart without parsing its message text.
    """


class DatabaseNotReadyError(LookupError):
    """The server answered, but the tables are missing or the role cannot read them."""


_NOT_READY = {"42P01", "42501"}  # undefined table; insufficient privilege


def _sqlstate(error: DBAPIError) -> str | None:
    state = getattr(error.orig, "sqlstate", None)
    return state if isinstance(state, str) else None


def engine(url: DatabaseUrl, env: Mapping[str, str] = os.environ) -> Engine:
    """An engine built from a checked URL's parts (its forced options are among them).

    The libpq environment is checked again here, because libpq reads the process
    environment at connect time, not the mapping the settings were read from.
    `search_path` is set per connection, so a role never writes to `public` by accident.
    `hide_parameters` keeps bound values (passwords now, consumer inputs from P5) out of
    exception messages and logs.
    """
    refuse_libpq_environment(env)
    target = URL.create(
        "postgresql+psycopg",
        username=url.user,
        password=url.password,
        host=url.host,
        port=url.port,
        database=url.database,
        query=dict(url.options),
    )
    return create_engine(
        target,
        connect_args={"options": f"-c search_path={SCHEMA}"},
        pool_pre_ping=True,
        hide_parameters=True,
    )


@contextmanager
def connect(url: DatabaseUrl, env: Mapping[str, str] = os.environ) -> Iterator[Connection]:
    """One connection for a service that only reads; the engine is disposed afterwards.

    Lets a service read through the repository without importing SQLAlchemy (rule 4).
    A refused connection becomes `DatabaseUnavailableError`; a missing table or a missing
    privilege during the reads becomes `DatabaseNotReadyError`. Both messages name the
    database only. The driver's error stays on `__context__` (hidden by `from None` in
    tracebacks): anything that logs these must log the message, never the chain.
    """
    target = engine(url, env)
    try:
        try:
            connection = target.connect()
        except OperationalError:
            msg = f"cannot connect to the database {url.database!r}"
            raise DatabaseUnavailableError(msg) from None
        with connection:
            try:
                yield connection
            except ProgrammingError as error:
                if _sqlstate(error) not in _NOT_READY:
                    raise
                msg = f"the database {url.database!r} has no tables, or the role cannot read them"
                raise DatabaseNotReadyError(msg) from None
    finally:
        target.dispose()
