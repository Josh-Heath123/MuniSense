"""What the database tests connect with (P2-3)."""

import json
from dataclasses import dataclass

from sqlalchemy import text

from munisense.persistence.connection import engine
from munisense.persistence.loader import TABLES
from munisense.platform.settings import DatabaseUrl


@dataclass(frozen=True)
class TestDatabase:
    """The test database as the application role and as the migration role."""

    __test__ = False  # not a test class, despite the name

    app: DatabaseUrl
    migration: DatabaseUrl


def dump(url: DatabaseUrl, time_zone: str = "UTC") -> dict[str, list[str]]:
    """Every loaded table's rows as sorted JSON text, timestamps rendered in `time_zone`.

    Equal dumps under the same time zone mean equal rows (timestamps are stored as instants).
    """
    target = engine(url)
    try:
        with target.connect() as connection:
            connection.execute(text("SELECT set_config('TimeZone', :z, false)"), {"z": time_zone})
            return {
                table: sorted(
                    json.dumps(row, sort_keys=True)
                    for row in connection.execute(
                        text(f"SELECT to_jsonb(t) AS r FROM {table} t")  # noqa: S608  # fixed names
                    ).scalars()
                )
                for table in TABLES
            }
    finally:
        target.dispose()
