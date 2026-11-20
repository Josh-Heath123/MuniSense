"""SQLAlchemy engines from checked settings (P2-3)."""

import os
from collections.abc import Iterator, Mapping
from contextlib import contextmanager

from sqlalchemy import URL, Connection, Engine, create_engine
from sqlalchemy.exc import OperationalError

from munisense.platform.settings import DatabaseUrl, refuse_libpq_environment

SCHEMA = "munisense"


class DatabaseUnavailableError(ConnectionError):
    """The database could not be reached. The message names the database, never the URL."""


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
    A refused connection becomes `DatabaseUnavailableError`.
    """
    target = engine(url, env)
    try:
        try:
            connection = target.connect()
        except OperationalError:
            msg = f"cannot connect to the database {url.database!r}"
            raise DatabaseUnavailableError(msg) from None
        with connection:
            yield connection
    finally:
        target.dispose()
