"""Rules 4 and 4b: one package owns each infrastructure dependency (P2-2, closes TD-6).

import-linter enforces the rules; this test stops them being loosened silently: every
top-level package except the owner must be a source module of a contract that forbids
the dependency, with no `ignore_imports` exemption. Top-level modules (the root
`__init__.py`) are outside the contracts, so they are checked here directly. A planted
violation broke both contracts when they were added (see the P2-2 pull request).
"""

import ast
import tomllib
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "munisense"
# Every directory counts, with or without `__init__.py`: a namespace subpackage must not
# slip past the contracts.
PACKAGES = sorted(p.name for p in SRC.iterdir() if p.is_dir() and p.name != "__pycache__")
OWNERS = {
    "sqlalchemy": "persistence",
    "alembic": "persistence",
    "psycopg": "persistence",
    "psycopg_binary": "persistence",
    "mako": "persistence",
    "pypdf": "ingestion",
}


def _forbidding(dependency: str) -> list[dict[str, Any]]:
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return [
        c
        for c in config["tool"]["importlinter"]["contracts"]
        if c["type"] == "forbidden" and dependency in c["forbidden_modules"]
    ]


@pytest.mark.parametrize(("dependency", "owner"), sorted(OWNERS.items()))
def test_every_package_but_the_owner_is_forbidden_the_dependency(
    dependency: str, owner: str
) -> None:
    contracts = _forbidding(dependency)
    sources = {str(m).removeprefix("munisense.") for c in contracts for m in c["source_modules"]}
    assert sources >= set(PACKAGES) - {owner}
    assert owner not in sources
    assert all("ignore_imports" not in c for c in contracts)


@pytest.mark.parametrize("module", sorted(p.name for p in SRC.glob("*.py")))
def test_top_level_modules_import_no_owned_dependency(module: str) -> None:
    tree = ast.parse((SRC / module).read_text(encoding="utf-8"))
    imported = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        (node.module or "").split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }
    assert not imported & set(OWNERS)


def test_the_package_list_is_the_architecture() -> None:
    assert len(PACKAGES) == 10
    assert all((SRC / p / "__init__.py").is_file() for p in PACKAGES)
