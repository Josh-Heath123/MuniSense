"""Tests for guard_bash.py. Standard library only, so they run before P0-3.

Run: uv run --no-project python -m unittest discover -s .claude/hooks/tests -v
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

HOOKS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HOOKS))

from guard_bash import push_to_main_reason  # noqa: E402


class PushToMainBlocked(unittest.TestCase):
    """Commands that write to `main` are blocked, whatever branch is checked out."""

    CASES = [
        "git push origin main",
        "git push -u origin main",
        "git push --set-upstream origin main",
        "git push origin HEAD:main",
        "git push origin feat/x:main",
        "git push origin +feat/x:main",
        "git push origin refs/heads/main",
        "git push origin feat/x:refs/heads/main",
        "git push origin :main",
        "git push origin --delete main",
        "git push origin feat/x main",
        "git push --all origin",
        "git push --mirror origin",
        "git -C /mnt/c/MuniSense/MuniSense push origin main",
        "git push -o ci.skip origin main",
        "git status && git push origin main",
        "echo done; git push origin main",
    ]

    def test_blocked_on_feature_branch(self) -> None:
        for command in self.CASES:
            with self.subTest(command=command):
                self.assertIsNotNone(push_to_main_reason(command, "feat/x"))


class PushFromMainBlocked(unittest.TestCase):
    """A push with no refspec pushes the current branch, so it depends on the branch."""

    CASES = ["git push", "git push origin", "git push -u origin", "git push origin HEAD"]

    def test_blocked_when_on_main(self) -> None:
        for command in self.CASES:
            with self.subTest(command=command):
                self.assertIsNotNone(push_to_main_reason(command, "main"))

    def test_blocked_when_branch_unknown(self) -> None:
        for command in ["git push", "git push origin"]:
            with self.subTest(command=command):
                self.assertIsNotNone(push_to_main_reason(command, None))

    def test_allowed_on_feature_branch(self) -> None:
        for command in self.CASES:
            with self.subTest(command=command):
                self.assertIsNone(push_to_main_reason(command, "docs/accept-decisions"))


class OtherPushesAllowed(unittest.TestCase):
    CASES = [
        "git push -u origin docs/accept-decisions",
        "git push origin feat/main",
        "git push origin main-fix",
        "git push origin HEAD:feat/x",
        "git push origin main:feat/x",
        "git push -o main origin feat/x",
        "git status",
        "git log main",
        "gh pr merge 1",
        "echo git push origin main is blocked",
    ]

    def test_allowed(self) -> None:
        for command in self.CASES:
            with self.subTest(command=command):
                self.assertIsNone(push_to_main_reason(command, "main"))


class HookEndToEnd(unittest.TestCase):
    """Runs the hook script as Claude Code does: JSON on stdin, exit code 2 blocks."""

    def run_hook(self, command: str) -> subprocess.CompletedProcess[str]:
        payload = json.dumps({"tool_input": {"command": command}})
        env = {**os.environ, "CLAUDE_PROJECT_DIR": str(HOOKS.parent.parent)}
        return subprocess.run(
            [sys.executable, str(HOOKS / "guard_bash.py")],
            input=payload,
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )

    def test_push_to_main_exits_2_with_reason(self) -> None:
        result = self.run_hook("git push origin HEAD:main")
        self.assertEqual(result.returncode, 2)
        self.assertIn("Pushing to `main` is not allowed", result.stderr)

    def test_push_of_feature_branch_exits_0(self) -> None:
        result = self.run_hook("git push -u origin feat/x")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_existing_rules_still_apply(self) -> None:
        result = self.run_hook("git push --force origin feat/x")
        self.assertEqual(result.returncode, 2)
        self.assertIn("Force-pushing", result.stderr)


if __name__ == "__main__":
    unittest.main()
