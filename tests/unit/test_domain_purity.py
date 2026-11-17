"""The domain is pure (CLAUDE.md rule 3, ADR-0004, architecture overview rule 1).

`munisense.domain` imports only an allow-list of standard-library modules, Pydantic v2 and
itself, and does no I/O, reads no clock and uses no randomness. import-linter (rule 1b in
pyproject.toml) forbids named third-party packages; it cannot express an allow-list, so this
test does. A new standard-library module is refused until it is added to the list on purpose.

It is a best-effort check: it sees only what the source text names directly (not `getattr`
tricks or imports hidden in strings). Relative imports are not checked here; import-linter
rule 1 resolves them and refuses any that leave the domain.
"""

import ast
import sys
from pathlib import Path

import pytest

DOMAIN_ROOT = Path(__file__).resolve().parents[2] / "src" / "munisense" / "domain"

# Pure standard-library modules the domain may use. Extend deliberately, with a reason in
# the pull request. Not on the list on purpose: zoneinfo (reads tz data from disk; the
# domain takes dates and offset-aware datetimes from its caller) and uuid (ids are made
# outside the domain).
ALLOWED_STDLIB = frozenset(
    {
        "__future__",
        "abc",
        "calendar",
        "collections",
        "contextlib",
        "copy",
        "dataclasses",
        "datetime",
        "decimal",
        "enum",
        "fractions",
        "functools",
        "itertools",
        "math",
        "numbers",
        "operator",
        "re",
        "string",
        "types",
        "typing",
    }
)
ALLOWED_THIRD_PARTY = frozenset({"pydantic", "pydantic_core"})
FORBIDDEN_PYDANTIC = ("pydantic.v1",)  # ADR-0004: Pydantic v2 only

FORBIDDEN_BUILTINS = frozenset({"open", "input", "print", "breakpoint", "eval", "exec"})
FORBIDDEN_BUILTINS |= {"compile", "__import__"}
# date.today, datetime.now, datetime.utcnow, datetime.today: the clock, called or passed
# (for example as a Pydantic default_factory).
CLOCK_ATTRIBUTES = frozenset({"now", "today", "utcnow"})


def _import_violation(module: str) -> str | None:
    top = module.split(".")[0]
    if module == "munisense.domain" or module.startswith("munisense.domain."):
        return None
    if top == "munisense":
        return f"imports {module} from outside the domain"
    if any(module == bad or module.startswith(bad + ".") for bad in FORBIDDEN_PYDANTIC):
        return f"imports {module} (Pydantic v1 API)"
    if top in ALLOWED_THIRD_PARTY or top in ALLOWED_STDLIB:
        return None
    if top in sys.stdlib_module_names:
        return f"imports standard-library module {module}, which is not on the allow-list"
    return f"imports third-party package {module}"


def _name_violation(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name) and node.id in FORBIDDEN_BUILTINS:
        return f"uses builtin {node.id}"
    if isinstance(node, ast.Attribute) and node.attr in CLOCK_ATTRIBUTES:
        return f"uses .{node.attr} (reads the clock)"
    return None


def _node_violations(node: ast.AST) -> list[str]:
    if isinstance(node, ast.Import):
        return [p for alias in node.names if (p := _import_violation(alias.name))]
    if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
        problem = _import_violation(node.module)
        return [problem] if problem else []
    problem = _name_violation(node)
    return [problem] if problem else []


def violations(source: str, filename: str = "<source>") -> list[str]:
    """Return a description of every purity violation in one module's source."""
    found: list[str] = []
    for node in ast.walk(ast.parse(source, filename)):
        line = node.lineno if isinstance(node, ast.stmt | ast.expr) else 0
        found += [f"{filename}:{line}: {problem}" for problem in _node_violations(node)]
    return found


def test_domain_modules_are_pure() -> None:
    modules = sorted(DOMAIN_ROOT.rglob("*.py"))
    assert modules, f"no domain modules found under {DOMAIN_ROOT}"
    found = [v for path in modules for v in violations(path.read_text(encoding="utf-8"), str(path))]
    assert found == []


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("import os", "not on the allow-list"),
        ("from pathlib import Path", "not on the allow-list"),
        ("import codecs", "not on the allow-list"),
        ("import builtins", "not on the allow-list"),
        ("import zoneinfo", "not on the allow-list"),
        ("import random", "not on the allow-list"),
        ("import requests", "third-party package"),
        ("from sqlalchemy.orm import Session", "third-party package"),
        ("from pydantic.v1 import BaseModel", "Pydantic v1"),
        ("from munisense.persistence import models", "outside the domain"),
        ("import munisense.services", "outside the domain"),
        ("x = open('tariff.json')", "builtin open"),
        ("f = open", "builtin open"),
        ("print('total')", "builtin print"),
        ("from datetime import datetime\nx = datetime.now()", "reads the clock"),
        ("from datetime import date\nx = date.today()", "reads the clock"),
        ("x = Field(default_factory=datetime.now)", "reads the clock"),
    ],
)
def test_a_violation_is_reported(source: str, expected: str) -> None:
    found = violations(source)
    assert len(found) == 1
    assert expected in found[0]


@pytest.mark.parametrize(
    "source",
    [
        "from decimal import Decimal, ROUND_HALF_UP",
        "from datetime import date",
        "import pydantic",
        "from pydantic import BaseModel, ConfigDict",
        "from pydantic_core import core_schema",
        "from munisense.domain.money import Money",
        "from . import errors",
        "from typing import Annotated",
        "x = record.today_kwh",
    ],
)
def test_allowed_code_passes(source: str) -> None:
    assert violations(source) == []
