"""SQLAlchemy engines from checked settings (P2-3)."""

import os
from collections.abc import Mapping

from sqlalchemy import Engine, create_engine

from munisense.platform.settings import DatabaseUrl, refuse_libpq_environment

SCHEMA = "munisense"


def engine(url: DatabaseUrl, env: Mapping[str, str] = os.environ) -> Engine:
    """An engine for a checked URL (its forced options are already part of it).

    The libpq environment is checked again here, because libpq reads the process
    environment at connect time, not the mapping the settings were read from.
    `search_path` is set per connection, so a role never writes to `public` by accident.
    `hide_parameters` keeps bound values (passwords now, consumer inputs from P5) out of
    exception messages and logs.
    """
    refuse_libpq_environment(env)
    return create_engine(
        url.url.replace("postgresql://", "postgresql+psycopg://", 1),
        connect_args={"options": f"-c search_path={SCHEMA}"},
        pool_pre_ping=True,
        hide_parameters=True,
    )
