"""SQLAlchemy engines from checked settings (P2-3)."""

from sqlalchemy import Engine, create_engine

from munisense.platform.settings import DatabaseUrl

SCHEMA = "munisense"


def engine(url: DatabaseUrl) -> Engine:
    """An engine for a checked URL (`gssencmode=disable` is already part of it).

    `search_path` is set per connection, so a role never writes to `public` by accident.
    """
    return create_engine(
        url.url.replace("postgresql://", "postgresql+psycopg://", 1),
        connect_args={"options": f"-c search_path={SCHEMA}"},
        pool_pre_ping=True,
    )
