"""Stop hook: runs the fast quality checks before Claude finishes, if Python files changed.

Runs `uv run poe check` (lint, types, fast tests). On failure it blocks once and
shows Claude the output. If Claude is already continuing because of this hook
(stop_hook_active), it lets Claude stop, so it can never loop. CLAUDE.md then
requires Claude to state plainly that checks are red.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from _common import OK, block, project_dir, read_input, run, tail, tool_missing


def python_changed(root: Path) -> bool:
    status = run(["git", "status", "--porcelain", "--untracked-files=all"], cwd=root, timeout=30)
    if status.returncode != 0:
        return False  # not a git repository yet
    return any(line.rstrip().endswith(".py") for line in status.stdout.splitlines())


def main() -> int:
    data = read_input()
    if data.get("stop_hook_active"):
        return OK

    root = project_dir(data)
    try:
        if not (root / "pyproject.toml").exists() or not python_changed(root):
            return OK
        command = ["uv", "run", "--quiet", "poe", "check"]
        result = run(command, cwd=root, timeout=540)
        if tool_missing(result):
            command = ["uv", "run", "--quiet", "ruff", "check", "."]
            result = run(command, cwd=root, timeout=120)
            if tool_missing(result):
                return OK  # no checks installed yet (early Phase 0)
    except FileNotFoundError:
        print("quality_gate.py: git or uv is not installed, so no checks ran.", file=sys.stderr)
        return 1
    except subprocess.TimeoutExpired:
        return block(
            "Quality gate: the checks took too long and were stopped. "
            "The fast checks must stay fast. Find out why, or tell the owner "
            "the checks did not complete."
        )

    if result.returncode == 0:
        return OK
    return block(
        f"Quality gate failed: `{' '.join(command)}` exited with code {result.returncode}.\n"
        "Fix these before finishing. If you cannot, finish anyway, but state plainly in your reply "
        "that the checks are failing and why. This hook will not block a second time.\n\n"
        + tail(result.stdout + "\n" + result.stderr, 80)
    )


if __name__ == "__main__":
    sys.exit(main())
