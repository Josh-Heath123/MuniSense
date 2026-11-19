"""What the database tests connect with (P2-3)."""

from dataclasses import dataclass

from munisense.platform.settings import DatabaseUrl


@dataclass(frozen=True)
class TestDatabase:
    """The test database as the superuser, the application role and the migration role."""

    __test__ = False  # not a test class, despite the name

    admin: DatabaseUrl
    app: DatabaseUrl
    migration: DatabaseUrl
