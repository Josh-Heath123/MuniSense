"""SessionStart hook: gives Claude the project's current state at the start of every session.

Prints the git branch, the number of uncommitted files, and the "Now" and
"Waiting for the owner" sections of docs/status.md. Claude Code adds this
output to Claude's context.
"""

from __future__ import annotations

import sys
from pathlib import Path

from _common import OK, project_dir, read_input, run

SECTIONS = ("## Now", "## Waiting for the owner")
MAX_LINES_PER_SECTION = 30


def section(text: str, heading: str) -> list[str]:
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.strip().lower() == heading.lower():
            body: list[str] = []
            for nxt in lines[i + 1 :]:
                if nxt.startswith("## "):
                    break
                body.append(nxt)
            body = [b for b in body if b.strip()][:MAX_LINES_PER_SECTION]
            return [heading, *body] if body else []
    return []


def git_summary(root: Path) -> str:
    try:
        branch = run(["git", "branch", "--show-current"], cwd=root, timeout=10)
        status = run(["git", "status", "--porcelain"], cwd=root, timeout=10)
    except FileNotFoundError:
        return "Git: not installed."
    if branch.returncode != 0:
        return "Git: this folder is not a git repository yet."
    dirty = len([line for line in status.stdout.splitlines() if line.strip()])
    return f"Git: branch '{branch.stdout.strip() or '(detached)'}', {dirty} uncommitted file(s)."


def main() -> int:
    data = read_input()
    root = project_dir(data)
    out = ["MuniSense session context (from .claude/hooks/session_context.py)", git_summary(root)]

    status_file = root / "docs" / "status.md"
    if status_file.exists():
        text = status_file.read_text(encoding="utf-8", errors="replace")
        for heading in SECTIONS:
            out.extend(section(text, heading))
    else:
        out.append("docs/status.md is missing. Restore it before doing any work.")

    out.append("Rules: CLAUDE.md. Pick work with /next. Nothing is done without evidence.")
    print("\n".join(out))
    return OK


if __name__ == "__main__":
    sys.exit(main())
