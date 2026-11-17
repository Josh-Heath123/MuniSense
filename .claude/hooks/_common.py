"""Shared helpers for MuniSense Claude Code hooks. Standard library only."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

# Exit codes understood by Claude Code hooks.
OK = 0
BLOCK = 2  # blocks the action; stderr is shown to Claude


def read_input() -> dict[str, Any]:
    """Read the hook's JSON payload from stdin. Returns {} if it cannot be parsed."""
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def project_dir(data: dict[str, Any]) -> Path:
    """The repository root: CLAUDE_PROJECT_DIR if set, else the session's cwd."""
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    if env:
        return Path(env)
    return Path(data.get("cwd") or os.getcwd())


def run(cmd: list[str], cwd: Path, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    """Run a command and capture its output as text. Never raises for a non-zero exit."""
    return subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def tool_missing(result: subprocess.CompletedProcess[str]) -> bool:
    """True when `uv run <tool>` failed because the tool is not installed yet."""
    output = (result.stderr or "") + (result.stdout or "")
    return "Failed to spawn" in output or "No such file or directory" in output


def block(message: str) -> int:
    """Print a message for Claude and return the blocking exit code."""
    print(message, file=sys.stderr)
    return BLOCK


def tail(text: str, lines: int = 80) -> str:
    """The last `lines` lines of `text`."""
    return "\n".join(text.strip().splitlines()[-lines:])
