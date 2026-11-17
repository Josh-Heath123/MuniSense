"""PreToolUse hook (Edit|Write|MultiEdit): blocks writes that leak secrets or rewrite history.

Blocks:
- writing .env files or key files
- content that looks like a private key or a live token
- editing an ADR whose status is Accepted on main (supersede it with a new ADR instead).
  An ADR that is Accepted only on an unmerged branch may still be corrected. If git
  cannot say what main holds, the working-tree file decides, as before.
- editing an Alembic migration that already exists on the main branch
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from _common import OK, block, project_dir, read_input, run

SECRET_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----"), "a private key"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b"), "a GitHub token"),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{50,}\b"), "a GitHub token"),
    (re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}"), "an Anthropic API key"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "an AWS access key"),
    (re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"), "a Slack token"),
    (re.compile(r"\bsk_live_[A-Za-z0-9]{16,}"), "a live payment secret key"),
]

KEY_SUFFIXES = {".pem", ".key", ".p12", ".pfx"}
ADR_PATH = re.compile(r"^docs/adr/\d{4}-[^/]+\.md$")
ACCEPTED = re.compile(r"(?im)^\W*status\W*:?\W*accepted\b")
MIGRATION_PATH = re.compile(r"(^|/)migrations/versions/[^/]+\.py$")


def new_content(tool_input: dict[str, Any]) -> str:
    """All text the tool call would write."""
    parts = [str(tool_input.get("content", "")), str(tool_input.get("new_string", ""))]
    for edit in tool_input.get("edits", []) or []:
        if isinstance(edit, dict):
            parts.append(str(edit.get("new_string", "")))
    return "\n".join(parts)


def relative(path: Path, root: Path) -> str | None:
    """Path relative to the project root with forward slashes, on Windows too."""
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return None


def on_main(rel: str, root: Path) -> bool:
    """True if the file exists on the main branch (locally or on origin)."""
    for ref in ("main", "origin/main"):
        if run(["git", "cat-file", "-e", f"{ref}:{rel}"], cwd=root, timeout=10).returncode == 0:
            return True
    return False


def ref_exists(ref: str, root: Path) -> bool:
    """True if `ref` resolves to a commit in the repository at `root` (never raises)."""
    try:
        result = run(["git", "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"], cwd=root, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def accepted_on_main(rel: str, root: Path) -> bool | None:
    """Whether the ADR at `rel` is Accepted on main or origin/main.

    None when git cannot answer (not a repository, git missing, no main branch).
    False when main exists but the file is not on it, or is not Accepted there.
    """
    answered = False
    for ref in ("main", "origin/main"):
        if not ref_exists(ref, root):
            continue
        answered = True
        try:
            result = run(["git", "show", f"{ref}:{rel}"], cwd=root, timeout=10)
        except (OSError, subprocess.SubprocessError):
            return None
        if result.returncode == 0 and ACCEPTED.search(result.stdout):
            return True
    return False if answered else None


def main() -> int:
    data = read_input()
    tool_input = data.get("tool_input", {}) or {}
    file_path = str(tool_input.get("file_path", ""))
    if not file_path:
        return OK

    root = project_dir(data)
    path = Path(file_path)
    if not path.is_absolute():
        path = root / path
    name = path.name
    text = new_content(tool_input)
    problems: list[str] = []

    if name == ".env" or (name.startswith(".env.") and name != ".env.example"):
        problems.append(
            "Secret files (.env) are managed by the owner, not Claude. Update .env.example instead."
        )
    if path.suffix.lower() in KEY_SUFFIXES or name.startswith(("id_rsa", "id_ed25519", "id_ecdsa")):
        problems.append("Key and certificate files must never be written into the project.")
    for pattern, what in SECRET_PATTERNS:
        if pattern.search(text):
            problems.append(
                f"The new content appears to contain {what}. Secrets belong in .env only."
            )

    rel = relative(path, root)
    if rel and ADR_PATH.match(rel) and path.exists():
        adr_on_main = accepted_on_main(rel, root)
        if adr_on_main is None:  # git cannot answer: fall back to the working-tree file
            current = path.read_text(encoding="utf-8", errors="replace")
            accepted = bool(ACCEPTED.search(current))
        else:
            accepted = adr_on_main
        if accepted and "superseded by" not in text.lower():
            problems.append(
                f"{rel} is Accepted{' on main' if adr_on_main else ''}. Accepted ADRs are never edited. "
                "Create a new ADR "
                "with /adr that supersedes it; the only permitted edit here is marking "
                "it 'Superseded by ADR-NNNN'."
            )
    if rel and MIGRATION_PATH.search(rel) and path.exists() and on_main(rel, root):
        problems.append(
            f"{rel} is already on main. Never edit a released migration; "
            "add a new migration instead."
        )

    if not problems:
        return OK
    return block(
        "Blocked by .claude/hooks/guard_files.py.\n"
        + "\n".join(f"- {p}" for p in problems)
        + f"\nFile: {file_path}\n"
        "Do not try to work around this. Ask the owner if you believe it is wrong."
    )


if __name__ == "__main__":
    sys.exit(main())
