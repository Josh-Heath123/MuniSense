"""What the database tests connect with (P2-3)."""

from dataclasses import dataclass

from munisense.platform.settings import DatabaseUrl


@dataclass(frozen=True)
class TestDatabase:
    """The test database as the application role and as the migration role."""

    __test__ = False  # not a test class, despite the name

    app: DatabaseUrl
    migration: DatabaseUrl
