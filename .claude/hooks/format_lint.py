"""PostToolUse hook (Edit|Write|MultiEdit): formats and lints a Python file right after it changes.

Runs `ruff format` and `ruff check --fix` on the edited file. If problems remain,
exits with code 2 so Claude sees them immediately. Does nothing until the project
has a pyproject.toml with ruff installed (Phase 0, task P0-3).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from _common import OK, block, project_dir, read_input, run, tail, tool_missing


def main() -> int:
    data = read_input()
    file_path = str((data.get("tool_input", {}) or {}).get("file_path", ""))
    if not file_path.endswith(".py"):
        return OK

    root = project_dir(data)
    path = Path(file_path)
    if not (root / "pyproject.toml").exists() or not path.exists():
        return OK

    try:
        formatted = run(["uv", "run", "--quiet", "ruff", "format", str(path)], cwd=root)
        if tool_missing(formatted):
            return OK  # ruff not installed yet
        checked = run(["uv", "run", "--quiet", "ruff", "check", "--fix", str(path)], cwd=root)
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        print(f"format_lint.py could not run ruff: {exc}", file=sys.stderr)
        return 1  # non-blocking error

    if checked.returncode == 0:
        return OK
    return block(
        f"ruff reported problems in {path.name} that it could not fix automatically. "
        f"Fix them now:\n{tail(checked.stdout + checked.stderr, 60)}"
    )


if __name__ == "__main__":
    sys.exit(main())
