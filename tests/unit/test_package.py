"""Placeholder test for P0: every package in the skeleton imports cleanly."""

import importlib
import pkgutil

import munisense

# Keep in step with the import-linter contracts in pyproject.toml.
EXPECTED = {
    "munisense.domain",
    "munisense.domain.money",
    "munisense.domain.tariffs",
    "munisense.domain.billing",
    "munisense.catalogue",
    "munisense.provenance",
    "munisense.ingestion",
    "munisense.persistence",
    "munisense.services",
    "munisense.api",
    "munisense.console",
    "munisense.mcp",
    "munisense.platform",
}


def test_every_package_in_the_architecture_exists_and_imports() -> None:
    found = {
        info.name
        for info in pkgutil.walk_packages(munisense.__path__, prefix="munisense.")
        if info.ispkg
    }
    assert found == EXPECTED
    for name in sorted(found):
        importlib.import_module(name)
