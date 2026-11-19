"""SQLAlchemy engines from checked settings (P2-3)."""

import os
from collections.abc import Mapping

from sqlalchemy import URL, Engine, create_engine

from munisense.platform.settings import DatabaseUrl, refuse_libpq_environment

SCHEMA = "munisense"


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
