"""PreToolUse hook (Bash): blocks destructive or policy-breaking shell commands.

Exit code 2 stops the command before it runs and shows the reason to Claude.
Permission rules in .claude/settings.json are the first line of defence; this
hook catches variants that simple patterns miss.
"""

from __future__ import annotations

import re
import shlex
import sys

from _common import OK, block, read_input

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


def main() -> int:
    data = read_input()
    command = str((data.get("tool_input", {}) or {}).get("command", ""))
    if not command:
        return OK

    reasons = [reason for pattern, reason in RULES if pattern.search(command)]
    if recursive_force_rm(command):
        reasons.append("`rm -rf` deletes irreversibly. Delete specific files, or ask the owner.")

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
