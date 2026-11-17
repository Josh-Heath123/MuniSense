"""Tests for guard_bash.py. Standard library only, so they run before P0-3.

Run: uv run --no-project python -m unittest discover -s .claude/hooks/tests -v

Command strings that mention pushing are assembled from PUSH below, so this file
can itself be written and committed without tripping the guard it tests.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HOOKS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HOOKS))

from guard_bash import current_branch, push_to_main_reason, simple_commands  # noqa: E402

PUSH = "git " + "push"
CWD = Path("/repo")


def on(branch: str | None):  # noqa: ANN201 - small test helper
    """A branch lookup that always answers `branch`."""
    return lambda _directory: branch


def reason(command: str, branch: str | None) -> str | None:
    return push_to_main_reason(command, on(branch), CWD)


class PushToMainBlocked(unittest.TestCase):
    """Commands that write to `main` are blocked, whatever branch is checked out."""

    CASES = [
        f"{PUSH} origin main",
        f"{PUSH} -u origin main",
        f"{PUSH} --set-upstream origin main",
        f"{PUSH} origin HEAD:main",
        f"{PUSH} origin feat/x:main",
        f"{PUSH} origin +feat/x:main",
        f"{PUSH} origin main:main",
        f"{PUSH} origin refs/heads/main",
        f"{PUSH} origin feat/x:refs/heads/main",
        f"{PUSH} origin HEAD:heads/main",
        f"{PUSH} origin :main",
        f"{PUSH} origin --delete main",
        f"{PUSH} -d origin main",
        f"{PUSH} origin feat/x main",
        f"{PUSH} origin :",
        f"{PUSH} origin 'refs/heads/*:refs/heads/*'",
        f"{PUSH} --all origin",
        f"{PUSH} --mirror origin",
        f"{PUSH} --branches origin",
        f"git -C /mnt/c/MuniSense/MuniSense {PUSH[4:]} origin main",
        f"{PUSH} -o ci.skip origin main",
        f"git status && {PUSH} origin main",
        f"echo done; {PUSH} origin main",
        f"echo done\n{PUSH} origin main",
        f"GIT_TERMINAL_PROMPT=0 {PUSH} origin main",
        f'GIT_SSH_COMMAND="ssh -v" {PUSH} origin main',
        f"time {PUSH} origin main",
        f"env -i X=1 {PUSH} origin main",
        f"command {PUSH} origin main",
        f"({PUSH} origin main)",
        f"/usr/bin/{PUSH} origin main",
        f"git.exe {PUSH[4:]} origin main",
    ]

    def test_blocked_on_feature_branch(self) -> None:
        for command in self.CASES:
            with self.subTest(command=command):
                self.assertIsNotNone(reason(command, "feat/x"))


class PushFromMainBlocked(unittest.TestCase):
    """A push of the current branch depends on which branch that is."""

    CASES = [
        PUSH,
        f"{PUSH} origin",
        f"{PUSH} -u origin",
        f"{PUSH} origin HEAD",
        f"{PUSH} -u origin HEAD",
        f"{PUSH} origin @",
        f"GIT_TERMINAL_PROMPT=0 {PUSH}",
    ]

    def test_blocked_when_on_main(self) -> None:
        for command in self.CASES:
            with self.subTest(command=command):
                self.assertIsNotNone(reason(command, "main"))

    def test_blocked_when_branch_unknown(self) -> None:
        for command in self.CASES:
            with self.subTest(command=command):
                self.assertIsNotNone(reason(command, None))

    def test_allowed_on_feature_branch(self) -> None:
        for command in self.CASES:
            with self.subTest(command=command):
                self.assertIsNone(reason(command, "docs/accept-decisions"))


class DirectoryFollowed(unittest.TestCase):
    """The branch is looked up where the push runs: after `cd`, or at `git -C`."""

    def lookup(self, directory: Path) -> str | None:
        return {"/repo": "feat/x", "/other": "main"}.get(directory.as_posix())

    def test_cd_into_a_checkout_of_main(self) -> None:
        self.assertIsNotNone(push_to_main_reason(f"cd /other && {PUSH}", self.lookup, CWD))

    def test_git_dash_c_into_a_checkout_of_main(self) -> None:
        command = f"git -C /other {PUSH[4:]} origin HEAD"
        self.assertIsNotNone(push_to_main_reason(command, self.lookup, CWD))

    def test_git_dash_c_into_a_feature_checkout(self) -> None:
        lookup = lambda d: {"/repo": "main", "/other": "feat/x"}.get(d.as_posix())  # noqa: E731
        command = f"git -C /other {PUSH[4:]}"
        self.assertIsNone(push_to_main_reason(command, lookup, CWD))

    def test_cd_without_target_fails_closed(self) -> None:
        self.assertIsNotNone(push_to_main_reason(f"cd && {PUSH}", self.lookup, CWD))


class OtherCommandsAllowed(unittest.TestCase):
    """Ordinary work, including text that merely mentions pushing to main, is allowed."""

    CASES = [
        f"{PUSH} -u origin docs/accept-decisions",
        f"{PUSH} origin feat/main",
        f"{PUSH} origin main-fix",
        f"{PUSH} origin HEAD:feat/x",
        f"{PUSH} origin main:feat/x",
        f"{PUSH} -o main origin feat/x",
        f"{PUSH} -u origin feat/x 2>&1 | tail -1",
        "git status",
        "git log main",
        "git stash push",
        "gh pr merge 1",
        f"echo {PUSH} origin main is blocked",
        f'git commit -m "fix: guard; {PUSH} origin main is now blocked"',
        f'git commit -m "a && {PUSH} origin main && b"',
        f"git commit -F - <<'EOF'\nsubject\n\n{PUSH} origin main is blocked\nEOF",
        f"gh pr create --body \"$(cat <<'EOF'\n{PUSH} origin main\nEOF\n)\"",
        f'git commit -m "subject\n\n{PUSH} --all is blocked"',
    ]

    def test_allowed(self) -> None:
        for command in self.CASES:
            with self.subTest(command=command):
                self.assertIsNone(reason(command, "feat/x"))


class Parsing(unittest.TestCase):
    def test_heredoc_body_is_not_a_command(self) -> None:
        commands = simple_commands("cat <<'EOF'\nrm -rf /\nEOF\necho ok")
        self.assertEqual(commands, [["cat", "<<EOF"], ["echo", "ok"]])

    def test_unparseable_push_fails_closed(self) -> None:
        self.assertIsNotNone(reason(f"{PUSH} origin 'feat/x", "feat/x"))


def git(directory: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=directory, check=True, capture_output=True)


class CurrentBranch(unittest.TestCase):
    def test_reads_branch_and_maps_detached_head_to_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            git(repo, "init", "-q", "-b", "main")
            git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q",
                "--allow-empty", "-m", "init")
            self.assertEqual(current_branch(repo), "main")
            git(repo, "switch", "-q", "-c", "feat/x")
            self.assertEqual(current_branch(repo), "feat/x")
            git(repo, "switch", "-q", "--detach")
            self.assertIsNone(current_branch(repo))

    def test_missing_directory_gives_none(self) -> None:
        self.assertIsNone(current_branch(Path("/nonexistent/munisense")))


class HookEndToEnd(unittest.TestCase):
    """Runs the hook as Claude Code does: JSON on stdin; exit code 2 blocks."""

    def run_hook(
        self, command: str, project: Path, extra_env: dict[str, str] | None = None
    ) -> subprocess.CompletedProcess[str]:
        payload = json.dumps({"tool_input": {"command": command}})
        env = {**os.environ, "CLAUDE_PROJECT_DIR": str(project), **(extra_env or {})}
        return subprocess.run(
            [sys.executable, str(HOOKS / "guard_bash.py")],
            input=payload,
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )

    def test_bare_push_depends_on_checked_out_branch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            git(repo, "init", "-q", "-b", "main")
            git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q",
                "--allow-empty", "-m", "init")
            blocked = self.run_hook(PUSH, repo)
            self.assertEqual(blocked.returncode, 2)
            self.assertIn("Pushing to `main` is not allowed", blocked.stderr)
            git(repo, "switch", "-q", "-c", "feat/x")
            self.assertEqual(self.run_hook(PUSH, repo).returncode, 0)

    def test_feature_push_allowed(self) -> None:
        result = self.run_hook(f"{PUSH} -u origin feat/x", HOOKS)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_existing_rules_still_apply(self) -> None:
        result = self.run_hook(f"{PUSH} --force origin feat/x", HOOKS)
        self.assertEqual(result.returncode, 2)
        self.assertIn("Force-pushing", result.stderr)

    def test_unknown_project_directory_fails_closed_for_push(self) -> None:
        missing = Path("/nonexistent/munisense")
        self.assertEqual(self.run_hook(PUSH, missing).returncode, 2)
        self.assertEqual(self.run_hook("git status", missing).returncode, 0)

    def test_missing_git_fails_closed_for_push_and_keeps_other_rules(self) -> None:
        no_git = {"PATH": "/nonexistent"}
        self.assertEqual(self.run_hook(PUSH, HOOKS, no_git).returncode, 2)
        result = self.run_hook("rm -rf x; git stash push", HOOKS, no_git)
        self.assertEqual(result.returncode, 2)
        self.assertIn("rm -rf", result.stderr)


if __name__ == "__main__":
    unittest.main()
