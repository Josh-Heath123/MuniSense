"""Rules 4 and 4b: one package owns each infrastructure dependency (P2-2, closes TD-6).

import-linter enforces the rules; this test stops them being loosened silently: every
top-level package except the owner must be a source module of the contract that forbids
the dependency. A planted violation broke both contracts when they were added (see the
P2-2 pull request).
"""

import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PACKAGES = sorted(
    p.name for p in (ROOT / "src" / "munisense").iterdir() if (p / "__init__.py").is_file()
)
OWNERS = {
    "sqlalchemy": "persistence",
    "alembic": "persistence",
    "psycopg": "persistence",
    "pypdf": "ingestion",
}


def _sources_forbidding(dependency: str) -> set[str]:
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    sources: set[str] = set()
    for contract in config["tool"]["importlinter"]["contracts"]:
        if contract["type"] == "forbidden" and dependency in contract["forbidden_modules"]:
            sources |= {str(m).removeprefix("munisense.") for m in contract["source_modules"]}
    return sources


@pytest.mark.parametrize(("dependency", "owner"), sorted(OWNERS.items()))
def test_every_package_but_the_owner_is_forbidden_the_dependency(
    dependency: str, owner: str
) -> None:
    sources = _sources_forbidding(dependency)
    assert sources >= set(PACKAGES) - {owner}
    assert owner not in sources


def test_the_package_list_is_the_architecture() -> None:
    assert len(PACKAGES) == 10
    assert {"persistence", "ingestion"} <= set(PACKAGES)
