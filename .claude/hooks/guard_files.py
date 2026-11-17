"""PreToolUse hook (Edit|Write|MultiEdit): blocks writes that leak secrets or rewrite history.

Blocks:
- writing .env files or key files
- content that looks like a private key or a live token
- editing an ADR whose number is Accepted on main or origin/main (supersede it with a new
  ADR instead). An ADR Accepted only on an unmerged branch may still be corrected. If git
  cannot say what main holds, the working-tree file decides, as before.

Any crash blocks (fails closed). Git calls share a time budget below the hook timeout.
- editing an Alembic migration that already exists on the main branch
"""

from __future__ import annotations

import re
import subprocess
import sys
import time
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
ADR_PATH = re.compile(r"^docs/adr/(\d{4})-[^/]+\.md$", re.IGNORECASE)
ACCEPTED = re.compile(r"(?im)^\W*status\W*:?\W*accepted\b")
MIGRATION_PATH = re.compile(r"(^|/)migrations/versions/[^/]+\.py$", re.IGNORECASE)


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


MAIN_REFS = ("refs/heads/main", "refs/remotes/origin/main")  # fully qualified: no shadowing
GIT_BUDGET_SECONDS = 20.0  # the hook's own timeout in settings.json is 30 s
GIT_CALL_SECONDS = 5.0


class GitBudget:
    """Runs git with a total time budget, so the hook finishes before Claude Code kills it."""

    def __init__(self, root: Path, seconds: float = GIT_BUDGET_SECONDS) -> None:
        self.root = root
        self.deadline = time.monotonic() + seconds

    def __call__(self, *args: str) -> subprocess.CompletedProcess[str] | None:
        """The finished git command, or None if git could not run or time ran out."""
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            return None
        try:
            return run(["git", *args], cwd=self.root, timeout=min(GIT_CALL_SECONDS, remaining))
        except (OSError, subprocess.SubprocessError, ValueError):
            return None


def main_refs(git: GitBudget) -> list[str] | None:
    """The main refs that exist, or None if git cannot answer."""
    found: list[str] = []
    for ref in MAIN_REFS:
        result = git("rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
        if result is None:
            return None
        if result.returncode == 0:
            found.append(ref)
    return found


def on_main(rel: str, git: GitBudget) -> bool | None:
    """True if the file exists on main (locally or on origin); None if git cannot answer."""
    refs = main_refs(git)
    if refs is None:
        return None
    for ref in refs:
        result = git("cat-file", "-e", f"{ref}:{rel}")
        if result is None:
            return None
        if result.returncode == 0:
            return True
    return False


def adr_accepted_on_main(number: str, git: GitBudget) -> bool | None:
    """Whether any ADR with this number is Accepted on main or origin/main.

    Matching by number, not by path, covers renamed ADRs and case-variant paths on
    case-insensitive file systems such as /mnt/c. Returns None when git cannot answer
    (not a repository, git missing, no main branch, time budget used up).

    Known limit: the refs are only as fresh as the last `git fetch`. An ADR accepted
    by a merge on GitHub that has not been fetched yet is not seen as Accepted.
    Assumes the project directory is the repository root.
    """
    refs = main_refs(git)
    if not refs:
        return None
    prefix = f"docs/adr/{number}-"
    for ref in refs:
        listing = git("ls-tree", "--name-only", "--full-tree", ref, "docs/adr/")
        if listing is None or listing.returncode != 0:
            return None
        for name in listing.stdout.splitlines():
            if not name.lower().startswith(prefix):
                continue
            shown = git("show", f"{ref}:{name}")
            if shown is None or shown.returncode != 0:
                return None
            if ACCEPTED.search(shown.stdout):
                return True
    return False


def check(data: dict[str, Any]) -> int:
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
    git = GitBudget(root)
    adr = ADR_PATH.match(rel) if rel else None
    if adr:
        adr_on_main = adr_accepted_on_main(adr.group(1), git)
        if adr_on_main is None:  # git cannot answer: the working-tree file decides
            current = (
                path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
            )
            accepted = bool(ACCEPTED.search(current))
        else:
            accepted = adr_on_main
        if accepted and "superseded by" not in text.lower():
            where = " on main" if adr_on_main else ""
            problems.append(
                f"{rel} is Accepted{where}. Accepted ADRs are never edited. Create a new "
                "ADR with /adr that supersedes it; the only permitted edit here is "
                "marking it 'Superseded by ADR-NNNN'."
            )
    if rel and MIGRATION_PATH.search(rel):
        released = on_main(rel, git)
        if released is None and path.exists():
            problems.append(
                f"Could not check with git whether {rel} is already on main, "
                "so the edit is blocked. Ask the owner."
            )
        elif released:
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


def main() -> int:
    data = read_input()
    try:
        return check(data)
    except Exception as exc:  # top-level boundary: a crashed guard must block, not allow
        return block(
            f"Blocked: .claude/hooks/guard_files.py crashed ({type(exc).__name__}: {exc}), "
            "so it fails closed. Tell the owner; do not work around it."
        )


if __name__ == "__main__":
    sys.exit(main())
