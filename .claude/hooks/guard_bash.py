"""PreToolUse hook (Bash): blocks destructive or policy-breaking shell commands.

Exit code 2 stops the command before it runs and shows the reason to Claude.
Permission rules in .claude/settings.json are the first line of defence; this
hook catches variants that simple patterns miss.
"""

from __future__ import annotations

import re
import shlex
import sys
from typing import Any

from _common import OK, block, project_dir, read_input, run

# (pattern, reason). Patterns are searched in the whole command string.
RULES: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(r"\bgit\s+push\b[^\n;&|]*(\s--force\S*|\s-[a-zA-Z]*f[a-zA-Z]*\b|\s\+\S)"),
        "Force-pushing rewrites shared history.",
    ),
    (
        re.compile(r"\bgit\b[^\n;&|]*\s--no-verify\b"),
        "Skipping git hooks (--no-verify) bypasses the quality and secret checks.",
    ),
    (
        re.compile(r"""\bgit\s+commit\b[^\n;&|"']*\s-[a-zA-Z]*n[a-zA-Z]*\b"""),
        "`git commit -n` skips git hooks, which bypasses the quality and secret checks.",
    ),
    (
        re.compile(r"\bgit\s+reset\b[^\n;&|]*\s--hard\b"),
        "`git reset --hard` discards work irreversibly.",
    ),
    (
        re.compile(r"\bgit\s+clean\b[^\n;&|]*\s-[a-zA-Z]*f"),
        "`git clean -f` deletes untracked files irreversibly.",
    ),
    (
        re.compile(r"\bgit\s+(checkout|restore)\b[^\n;&|]*\s\.(\s|$)"),
        "Discarding all working-tree changes is irreversible.",
    ),
    (
        re.compile(r"(?i)\bdrop\s+(database|schema|table)\b"),
        "Dropping databases, schemas or tables destroys data. Use migrations.",
    ),
    (
        re.compile(r"(?i)\btruncate\s+(table\s+)?[\w\".]+"),
        "TRUNCATE destroys data.",
    ),
    (
        re.compile(r"\bdocker\s+volume\s+(rm|prune)\b"),
        "Deleting Docker volumes destroys the local database.",
    ),
    (
        re.compile(r"\bdocker\s+(system|container|image|volume)\s+prune\b"),
        "Docker prune commands delete data and images irreversibly.",
    ),
    (
        re.compile(r"\bdocker[\s-]+compose\b[^\n;&|]*\bdown\b[^\n;&|]*(\s-v\b|\s--volumes\b)"),
        "`docker compose down -v` deletes the local database volume.",
    ),
    (
        re.compile(r"\b(curl|wget|iwr|Invoke-WebRequest)\b[^\n;&]*\|\s*(sudo\s+)?(ba|z|da)?sh\b"),
        "Piping a download straight into a shell runs unreviewed code.",
    ),
    (
        re.compile(r"\|\s*(iex|Invoke-Expression)\b"),
        "Piping into Invoke-Expression runs unreviewed code.",
    ),
    (
        re.compile(r"(^|[\s;&|(])(python3?\s+-m\s+)?pip3?\s+install\b"),
        "Install packages with `uv add` (which asks the owner), "
        "so uv.lock stays the single source of truth.",
    ),
    (
        re.compile(r"\buv\s+pip\s+install\b"),
        "`uv pip install` bypasses the lockfile. Use `uv add`, which asks the owner.",
    ),
    (
        re.compile(r"(^|[\s;&|(])sudo\s"),
        "sudo is not needed for project work. Ask the owner to run system changes.",
    ),
    (
        # .env, .env.local, path/.env ... but not .env.example
        re.compile(r"(?<![\w.-])(?:[\w./~-]*/)?\.env(?:\.(?!example\b)[\w-]+)?(?![\w.-])"),
        "Secret files (.env) are off limits to Claude. The owner manages them.",
    ),
    (
        re.compile(r"(\.ssh/|\bid_(rsa|ed25519|ecdsa)\b|\.aws/credentials)"),
        "Credential files are off limits.",
    ),
]

SEGMENT_SPLIT = re.compile(r"&&|\|\||;|\||\n")


def recursive_force_rm(command: str) -> bool:
    """True if any `rm` in the command is both recursive and forced."""
    for segment in SEGMENT_SPLIT.split(command):
        try:
            tokens = shlex.split(segment)
        except ValueError:
            tokens = segment.split()
        if not tokens or tokens[0] not in {"rm", "/bin/rm", "/usr/bin/rm"}:
            continue
        flags = "".join(t[1:] for t in tokens[1:] if t.startswith("-") and not t.startswith("--"))
        long_flags = {t for t in tokens[1:] if t.startswith("--")}
        recursive = "r" in flags or "R" in flags or "--recursive" in long_flags
        forced = "f" in flags or "--force" in long_flags
        if recursive and forced:
            return True
    return False


PROTECTED_BRANCH = "main"
# `git` options that take a separate value, e.g. `git -C path push`.
GIT_OPTIONS_WITH_VALUE = {"-C", "-c", "--git-dir", "--work-tree", "--namespace"}
# `git push` options that take a separate value, e.g. `git push -o ci.skip origin x`.
PUSH_OPTIONS_WITH_VALUE = {"-o", "--push-option", "--repo", "--receive-pack", "--exec"}
PUSH_ALL_FLAGS = {"--all", "--mirror", "--branches"}
PUSH_TO_MAIN_REASON = (
    "Pushing to `main` is not allowed. Push a branch and open a pull request; "
    "the owner merges it (decision E6)."
)


def _push_arguments(tokens: list[str]) -> list[str] | None:
    """The arguments after `git [options] push`, or None if this is not a git push."""
    if not tokens or tokens[0] not in {"git", "/usr/bin/git"}:
        return None
    i = 1
    while i < len(tokens) and tokens[i].startswith("-"):
        i += 2 if tokens[i] in GIT_OPTIONS_WITH_VALUE else 1
    if i >= len(tokens) or tokens[i] != "push":
        return None
    return tokens[i + 1 :]


def _destination(refspec: str, current_branch: str | None) -> str | None:
    """The branch a refspec writes to (None if unknown), e.g. `HEAD:main` -> `main`."""
    dst = refspec.lstrip("+").split(":")[-1]
    if dst == "HEAD":
        dst = current_branch or ""
    dst = dst.removeprefix("refs/heads/")
    return dst or None


def push_to_main_reason(command: str, current_branch: str | None) -> str | None:
    """Why the command would push to the protected branch, or None if it would not.

    `current_branch` is the checked-out branch (None if unknown). A push without a
    refspec pushes the current branch, so it is blocked on `main` or when the
    branch is unknown (fail closed).
    """
    for segment in SEGMENT_SPLIT.split(command):
        try:
            tokens = shlex.split(segment)
        except ValueError:
            tokens = segment.split()
        args = _push_arguments(tokens)
        if args is None:
            continue
        positional: list[str] = []
        i = 0
        while i < len(args):
            arg = args[i]
            if arg in PUSH_ALL_FLAGS:
                return PUSH_TO_MAIN_REASON
            if arg.startswith("-"):
                i += 2 if arg in PUSH_OPTIONS_WITH_VALUE else 1
                continue
            positional.append(arg)
            i += 1
        refspecs = positional[1:]  # positional[0] is the remote
        if not refspecs:
            if current_branch is None:
                return PUSH_TO_MAIN_REASON + " (The current branch could not be determined.)"
            if current_branch == PROTECTED_BRANCH:
                return PUSH_TO_MAIN_REASON
            continue
        if any(_destination(r, current_branch) == PROTECTED_BRANCH for r in refspecs):
            return PUSH_TO_MAIN_REASON
    return None


def current_branch(data: dict[str, Any]) -> str | None:
    """The checked-out branch in the project, or None if git cannot say."""
    result = run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=project_dir(data), timeout=10
    )
    branch = result.stdout.strip()
    return branch if result.returncode == 0 and branch and branch != "HEAD" else None


def main() -> int:
    data = read_input()
    command = str((data.get("tool_input", {}) or {}).get("command", ""))
    if not command:
        return OK

    reasons = [reason for pattern, reason in RULES if pattern.search(command)]
    if recursive_force_rm(command):
        reasons.append("`rm -rf` deletes irreversibly. Delete specific files, or ask the owner.")
    if re.search(r"\bpush\b", command):
        push_reason = push_to_main_reason(command, current_branch(data))
        if push_reason:
            reasons.append(push_reason)

    if not reasons:
        return OK

    return block(
        "Blocked by .claude/hooks/guard_bash.py.\n"
        + "\n".join(f"- {r}" for r in reasons)
        + f"\nCommand: {command}\n"
        "Do not try to work around this. If the action is genuinely needed, explain why "
        "and ask the owner to run it."
    )


if __name__ == "__main__":
    sys.exit(main())
