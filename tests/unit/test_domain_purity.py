"""The domain is pure (CLAUDE.md rule 3, ADR-0004, architecture overview rule 1).

`munisense.domain` imports only the standard library, Pydantic v2 and itself, and does no
I/O, reads no clock and uses no randomness. import-linter cannot express an allow-list of
third-party packages, so this test parses every domain module and checks its imports and
a short list of forbidden calls. It is a best-effort check: it sees only what the source
text names directly (not `getattr` tricks or imports hidden in strings).
"""

import ast
import sys
from pathlib import Path

import pytest

DOMAIN_ROOT = Path(__file__).resolve().parents[2] / "src" / "munisense" / "domain"

ALLOWED_THIRD_PARTY = frozenset({"pydantic", "pydantic_core"})

# Standard-library modules that do I/O, read the clock or the environment, or are random.
FORBIDDEN_STDLIB = frozenset(
    {
        "asyncio",
        "ctypes",
        "ftplib",
        "glob",
        "http",
        "importlib",
        "io",
        "logging",
        "multiprocessing",
        "os",
        "pathlib",
        "pickle",
        "random",
        "secrets",
        "shelve",
        "shutil",
        "smtplib",
        "socket",
        "sqlite3",
        "ssl",
        "subprocess",
        "sys",
        "tempfile",
        "threading",
        "time",
        "urllib",
        "uuid",
        "zoneinfo",
    }
)

FORBIDDEN_BUILTIN_CALLS = frozenset({"open", "input", "eval", "exec", "__import__"})
# date.today(), datetime.now(), datetime.utcnow(), datetime.today(): the clock.
FORBIDDEN_METHOD_CALLS = frozenset({"now", "today", "utcnow"})


def _import_violation(module: str) -> str | None:
    top = module.split(".")[0]
    if module == "munisense.domain" or module.startswith("munisense.domain."):
        return None
    if top == "munisense":
        return f"imports {module} from outside the domain"
    if top in ALLOWED_THIRD_PARTY:
        return None
    if top in sys.stdlib_module_names:
        return (
            f"imports {module} (I/O, clock, environment or randomness)"
            if (top in FORBIDDEN_STDLIB)
            else None
        )
    return f"imports third-party package {module}"


def _call_violation(node: ast.Call) -> str | None:
    func = node.func
    if isinstance(func, ast.Name) and func.id in FORBIDDEN_BUILTIN_CALLS:
        return f"calls {func.id}()"
    if isinstance(func, ast.Attribute) and func.attr in FORBIDDEN_METHOD_CALLS:
        return f"calls .{func.attr}() (reads the clock)"
    return None


def violations(source: str, filename: str = "<source>") -> list[str]:
    """Return a description of every purity violation in one module's source."""
    found: list[str] = []
    for node in ast.walk(ast.parse(source, filename)):
        problem: str | None = None
        if isinstance(node, ast.Import):
            for alias in node.names:
                if problem := _import_violation(alias.name):
                    found.append(f"{filename}:{node.lineno}: {problem}")
            continue
        if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            problem = _import_violation(node.module)
        elif isinstance(node, ast.Call):
            problem = _call_violation(node)
        if problem and isinstance(node, ast.stmt | ast.expr):
            found.append(f"{filename}:{node.lineno}: {problem}")
    return found


def test_domain_modules_are_pure() -> None:
    modules = sorted(DOMAIN_ROOT.rglob("*.py"))
    assert modules, f"no domain modules found under {DOMAIN_ROOT}"
    found = [v for path in modules for v in violations(path.read_text(), str(path))]
    assert found == []


@pytest.mark.parametrize(
    "source",
    [
        "import os",
        "from pathlib import Path",
        "import requests",
        "from sqlalchemy.orm import Session",
        "from munisense.persistence import models",
        "import munisense.services",
        "from datetime import datetime\nx = datetime.now()",
        "from datetime import date\nx = date.today()",
        "x = open('tariff.json')",
        "import random",
        "import time",
    ],
)
def test_a_violation_is_reported(source: str) -> None:
    assert violations(source) != []


@pytest.mark.parametrize(
    "source",
    [
        "from decimal import Decimal",
        "from datetime import date",
        "import pydantic",
        "from pydantic import BaseModel, ConfigDict",
        "from pydantic_core import core_schema",
        "from munisense.domain.money import Money",
        "from . import errors",
        "from typing import Annotated",
    ],
)
def test_allowed_imports_pass(source: str) -> None:
    assert violations(source) == []
