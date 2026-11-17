"""PreToolUse hook (Bash): blocks destructive or policy-breaking shell commands.

Exit code 2 stops the command before it runs and shows the reason to Claude.
Permission rules in .claude/settings.json are the first line of defence; this
hook catches variants that simple patterns miss.
"""

from __future__ import annotations

import re
import shlex
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
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




# --- Pushing to main (owner decision E6) ---------------------------------------
#
# Known limits, documented in docs/security/security-and-privacy.md: pushes driven
# only by git configuration (remote.<name>.push, push.default=upstream on a branch
# that tracks main) and commands hidden inside `bash -c`, `eval` or scripts are not
# inspected. The owner merging pull requests remains the main control.

PROTECTED_BRANCH = "main"
GIT_OPTIONS_WITH_VALUE = {"-C", "-c", "--git-dir", "--work-tree", "--namespace"}
PUSH_OPTIONS_WITH_VALUE = {"-o", "--push-option", "--repo", "--receive-pack", "--exec"}
PUSH_ALL_FLAGS = {"--all", "--mirror", "--branches"}
WRAPPERS = {"time", "command", "env", "nohup", "exec", "builtin"}
ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
HEREDOC = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")
PUSH_TO_MAIN_REASON = (
    "Pushing to `main` is not allowed. Push a branch and open a pull request; "
    "the owner merges it (decision E6)."
)
UNKNOWN_BRANCH = " (The current branch could not be determined, so the guard fails closed.)"

BranchLookup = Callable[[Path], "str | None"]


def strip_heredoc_bodies(command: str) -> str:
    """Remove here-document bodies, which are data (commit messages, PR bodies), not commands."""
    kept: list[str] = []
    pending: list[str] = []
    for line in command.split("\n"):
        if pending:
            if line.strip() == pending[0]:
                pending.pop(0)
            continue
        kept.append(line)
        pending.extend(m.group(2) for m in HEREDOC.finditer(line))
    return "\n".join(kept)


def _unquoted_newlines_to_semicolons(command: str) -> str:
    """Newlines outside quotes separate commands; inside quotes they are text."""
    out: list[str] = []
    quote = ""
    escaped = False
    for ch in command:
        if escaped:
            escaped = False
        elif ch == "\\" and quote != "'":
            escaped = True
        elif quote:
            if ch == quote:
                quote = ""
        elif ch in "'\"":
            quote = ch
        elif ch == "\n":
            ch = ";"
        out.append(ch)
    return "".join(out)


def simple_commands(command: str) -> list[list[str]]:
    """Split a shell command into simple commands, respecting quotes and here-documents.

    Raises ValueError for input shlex cannot parse (for example unbalanced quotes).
    """
    text = _unquoted_newlines_to_semicolons(strip_heredoc_bodies(command))
    lexer = shlex.shlex(text, posix=True, punctuation_chars=";&|()")
    lexer.whitespace_split = True
    commands: list[list[str]] = [[]]
    for token in lexer:
        if token and set(token) <= set(";&|()"):
            commands.append([])
        else:
            commands[-1].append(token)
    return [c for c in commands if c]


def _strip_prefixes(tokens: list[str]) -> list[str]:
    """Drop `NAME=value` assignments and wrappers such as `time`, `env -i`, `command`."""
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if ASSIGNMENT.match(token):
            i += 1
        elif token in WRAPPERS:
            i += 1
            while i < len(tokens) and tokens[i].startswith("-"):
                i += 1
        else:
            break
    return tokens[i:]


def _is_git(token: str) -> bool:
    return token.replace("\\", "/").rsplit("/", 1)[-1].lower() in {"git", "git.exe"}


def _push_arguments(tokens: list[str]) -> tuple[list[str], str | None] | None:
    """(arguments after `push`, the `-C` directory if any), or None if not a git push."""
    tokens = _strip_prefixes(tokens)
    if not tokens or not _is_git(tokens[0]):
        return None
    directory: str | None = None
    i = 1
    while i < len(tokens) and tokens[i].startswith("-"):
        if tokens[i] in GIT_OPTIONS_WITH_VALUE:
            if tokens[i] == "-C" and i + 1 < len(tokens):
                directory = tokens[i + 1]
            i += 2
        else:
            i += 1
    if i >= len(tokens) or tokens[i] != "push":
        return None
    return tokens[i + 1 :], directory


def _writes_to_main(refspec: str, current_branch: str | None) -> bool | None:
    """True if the refspec writes to main, False if not, None if that cannot be known."""
    spec = refspec.lstrip("+")
    if spec == ":":  # the "matching" refspec pushes every matching branch, main included
        return True
    dst = spec.split(":")[-1]
    if "*" in dst:
        return True
    if dst in {"HEAD", "@"}:
        if current_branch is None:
            return None
        dst = current_branch
    for prefix in ("refs/", "heads/"):
        dst = dst.removeprefix(prefix)
    return dst == PROTECTED_BRANCH


def push_to_main_reason(command: str, branch_of: BranchLookup, cwd: Path) -> str | None:
    """Why the command would push to main, or None if it would not.

    `branch_of(directory)` returns the branch checked out there, or None if unknown.
    It is only called when the answer matters. `cwd` is where the command starts;
    `cd DIR` and `git -C DIR` are followed.
    """
    try:
        commands = simple_commands(command)
    except ValueError:
        # Unparseable: fall back to a plain search, failing closed.
        if re.search(r"\bgit\b.*\bpush\b", command):
            return PUSH_TO_MAIN_REASON + " (The command could not be parsed.)"
        return None

    directory: Path | None = cwd
    for tokens in commands:
        bare = _strip_prefixes(tokens)
        if bare and bare[0] == "cd":
            target = bare[1] if len(bare) > 1 else None
            if target is None or target == "-" or directory is None:
                directory = None
            else:
                directory = directory / Path(target).expanduser()
            continue
        parsed = _push_arguments(tokens)
        if parsed is None:
            continue
        args, git_dir = parsed
        push_dir = directory
        if git_dir is not None and push_dir is not None:
            push_dir = push_dir / git_dir

        def branch() -> str | None:
            return branch_of(push_dir) if push_dir is not None else None  # noqa: B023

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
            current = branch()
            if current is None:
                return PUSH_TO_MAIN_REASON + UNKNOWN_BRANCH
            if current == PROTECTED_BRANCH:
                return PUSH_TO_MAIN_REASON
            continue
        needs_branch = any(r.lstrip("+").split(":")[-1] in {"HEAD", "@"} for r in refspecs)
        current = branch() if needs_branch else None
        for refspec in refspecs:
            verdict = _writes_to_main(refspec, current)
            if verdict is None:
                return PUSH_TO_MAIN_REASON + UNKNOWN_BRANCH
            if verdict:
                return PUSH_TO_MAIN_REASON
    return None


def current_branch(directory: Path) -> str | None:
    """The branch checked out in `directory`, or None if git cannot say (never raises)."""
    try:
        result = run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=directory, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    branch = result.stdout.strip()
    return branch if result.returncode == 0 and branch and branch != "HEAD" else None


def check(data: dict[str, Any]) -> list[str]:
    """Every reason to block the command in this hook payload."""
    command = str((data.get("tool_input", {}) or {}).get("command", ""))
    if not command:
        return []
    reasons = [reason for pattern, reason in RULES if pattern.search(command)]
    if recursive_force_rm(command):
        reasons.append("`rm -rf` deletes irreversibly. Delete specific files, or ask the owner.")
    if re.search(r"\bpush\b", command):
        cwd = Path(str(data.get("cwd") or project_dir(data)))
        push_reason = push_to_main_reason(command, current_branch, cwd)
        if push_reason:
            reasons.append(push_reason)
    return reasons


def main() -> int:
    data = read_input()
    try:
        reasons = check(data)
    except Exception as exc:  # top-level boundary: a crashed guard must block, not allow
        return block(
            f"Blocked: .claude/hooks/guard_bash.py crashed ({type(exc).__name__}: {exc}), "
            "so it fails closed. Tell the owner; do not work around it."
        )
    if not reasons:
        return OK
    command = str((data.get("tool_input", {}) or {}).get("command", ""))
    return block(
        "Blocked by .claude/hooks/guard_bash.py.\n"
        + "\n".join(f"- {r}" for r in reasons)
        + f"\nCommand: {command}\n"
        "Do not try to work around this. If the action is genuinely needed, explain why "
        "and ask the owner to run it."
    )


if __name__ == "__main__":
    sys.exit(main())
