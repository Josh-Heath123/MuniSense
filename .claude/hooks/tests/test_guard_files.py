"""Tests for the Accepted-ADR rule in guard_files.py. Standard library only.

Run: uv run --no-project python -m unittest discover -s .claude/hooks/tests -v

An ADR counts as Accepted only when it is Accepted on main (or origin/main). If git
cannot answer, the working-tree file decides.
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
ADR = "docs/adr/0002-example.md"
PROPOSED = "# ADR-0002: Example\n\n- **Status:** Proposed\n\nText.\n"
ACCEPTED = "# ADR-0002: Example\n\n- **Status:** Accepted\n\nText.\n"


def git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
        cwd=repo,
        check=True,
        capture_output=True,
    )


def write_adr(repo: Path, content: str) -> None:
    path = repo / ADR
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def commit_adr(repo: Path, content: str, message: str) -> None:
    write_adr(repo, content)
    git(repo, "add", ADR)
    git(repo, "commit", "-q", "-m", message)


class AdrRule(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def init_repo(self) -> None:
        git(self.repo, "init", "-q", "-b", "main")
        git(self.repo, "commit", "-q", "--allow-empty", "-m", "init")

    def edit(
        self, new_string: str = "Corrected text.", rel: str = ADR
    ) -> subprocess.CompletedProcess[str]:
        """Run the hook as Claude Code does for an Edit of `rel`."""
        payload = json.dumps(
            {"tool_input": {"file_path": str(self.repo / rel), "new_string": new_string}}
        )
        env = {**os.environ, "CLAUDE_PROJECT_DIR": str(self.repo)}
        return subprocess.run(
            [sys.executable, str(HOOKS / "guard_files.py")],
            input=payload,
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )

    def test_accepted_on_main_is_blocked_on_a_branch(self) -> None:
        self.init_repo()
        commit_adr(self.repo, ACCEPTED, "accept")
        git(self.repo, "switch", "-q", "-c", "docs/x")
        result = self.edit()
        self.assertEqual(result.returncode, 2)
        self.assertIn("is Accepted on main", result.stderr)

    def test_accepted_only_on_branch_may_be_corrected(self) -> None:
        self.init_repo()
        commit_adr(self.repo, PROPOSED, "propose")
        git(self.repo, "switch", "-q", "-c", "docs/x")
        commit_adr(self.repo, ACCEPTED, "accept on branch")
        result = self.edit()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_new_adr_accepted_on_branch_may_be_corrected(self) -> None:
        self.init_repo()
        git(self.repo, "switch", "-q", "-c", "docs/x")
        write_adr(self.repo, ACCEPTED)  # not on main at all, not even committed
        self.assertEqual(self.edit().returncode, 0)

    def test_marking_superseded_is_allowed(self) -> None:
        self.init_repo()
        commit_adr(self.repo, ACCEPTED, "accept")
        result = self.edit("- **Status:** Superseded by ADR-0011")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_origin_main_counts_when_local_main_is_missing(self) -> None:
        self.init_repo()
        commit_adr(self.repo, ACCEPTED, "accept")
        git(self.repo, "update-ref", "refs/remotes/origin/main", "HEAD")
        git(self.repo, "branch", "-q", "-m", "main", "trunk")
        self.assertEqual(self.edit().returncode, 2)

    def accepted_then_branch(self) -> None:
        """main holds the ADR as Accepted; work continues on branch docs/x."""
        self.init_repo()
        commit_adr(self.repo, ACCEPTED, "accept")
        git(self.repo, "switch", "-q", "-c", "docs/x")

    def test_case_variant_path_is_blocked(self) -> None:
        # On /mnt/c the file system ignores case; git does not. Match by ADR number.
        self.accepted_then_branch()
        self.assertEqual(self.edit(rel="docs/adr/0002-EXAMPLE.md").returncode, 2)
        self.assertEqual(self.edit(rel="DOCS/ADR/0002-example.md").returncode, 2)

    def test_renamed_adr_is_blocked(self) -> None:
        self.accepted_then_branch()
        git(self.repo, "mv", ADR, "docs/adr/0002-renamed.md")
        self.assertEqual(self.edit(rel="docs/adr/0002-renamed.md").returncode, 2)

    def test_recreating_a_deleted_accepted_adr_is_blocked(self) -> None:
        self.accepted_then_branch()
        (self.repo / ADR).unlink()
        self.assertEqual(self.edit().returncode, 2)

    def test_reverting_working_tree_to_proposed_does_not_unlock(self) -> None:
        self.accepted_then_branch()
        commit_adr(self.repo, PROPOSED, "pretend it was never accepted")
        self.assertEqual(self.edit().returncode, 2)

    def test_origin_accepted_local_main_stale_is_blocked(self) -> None:
        self.init_repo()
        commit_adr(self.repo, PROPOSED, "propose")
        git(self.repo, "switch", "-q", "-c", "accepted")
        commit_adr(self.repo, ACCEPTED, "accept")
        git(self.repo, "update-ref", "refs/remotes/origin/main", "HEAD")
        git(self.repo, "switch", "-q", "main")  # local main still says Proposed
        self.assertEqual(self.edit().returncode, 2)

    def test_local_main_accepted_origin_stale_is_blocked(self) -> None:
        self.init_repo()
        commit_adr(self.repo, PROPOSED, "propose")
        git(self.repo, "update-ref", "refs/remotes/origin/main", "HEAD")  # origin: Proposed
        commit_adr(self.repo, ACCEPTED, "accept")  # local main: Accepted
        self.assertEqual(self.edit().returncode, 2)

    def test_shadowing_refs_cannot_hide_main(self) -> None:
        self.init_repo()
        commit_adr(self.repo, PROPOSED, "propose")
        git(self.repo, "tag", "main")  # a tag named main pointing at the Proposed commit
        git(self.repo, "branch", "origin/main", "HEAD")  # a local branch named origin/main
        commit_adr(self.repo, ACCEPTED, "accept")  # refs/heads/main: Accepted
        self.assertEqual(self.edit().returncode, 2)

    def test_without_git_the_working_tree_decides(self) -> None:
        # Not a repository: git cannot answer, so the previous rule applies.
        write_adr(self.repo, ACCEPTED)
        self.assertEqual(self.edit().returncode, 2)
        write_adr(self.repo, PROPOSED)
        self.assertEqual(self.edit().returncode, 0)

    def test_without_git_binary_the_working_tree_decides(self) -> None:
        self.init_repo()
        write_adr(self.repo, ACCEPTED)
        payload = json.dumps(
            {"tool_input": {"file_path": str(self.repo / ADR), "new_string": "x"}}
        )
        env = {**os.environ, "CLAUDE_PROJECT_DIR": str(self.repo), "PATH": "/nonexistent"}
        result = subprocess.run(
            [sys.executable, str(HOOKS / "guard_files.py")],
            input=payload,
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        self.assertEqual(result.returncode, 2, result.stderr)


class MigrationRuleUnchanged(unittest.TestCase):
    """The migration rule shares main() with the ADR rule; it must still work."""

    def run_edit(self, repo: Path, rel: str) -> subprocess.CompletedProcess[str]:
        payload = json.dumps({"tool_input": {"file_path": str(repo / rel), "new_string": "x"}})
        env = {**os.environ, "CLAUDE_PROJECT_DIR": str(repo)}
        return subprocess.run(
            [sys.executable, str(HOOKS / "guard_files.py")],
            input=payload,
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )

    def test_migration_on_main_blocked_and_new_migration_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            git(repo, "init", "-q", "-b", "main")
            released = "migrations/versions/0001_init.py"
            (repo / "migrations/versions").mkdir(parents=True)
            (repo / released).write_text("# released\n", encoding="utf-8")
            git(repo, "add", released)
            git(repo, "commit", "-q", "-m", "migration")
            git(repo, "switch", "-q", "-c", "feat/x")
            blocked = self.run_edit(repo, released)
            self.assertEqual(blocked.returncode, 2, blocked.stderr)
            self.assertIn("already on main", blocked.stderr)
            (repo / released).unlink()
            recreated = self.run_edit(repo, released)
            self.assertEqual(recreated.returncode, 2, "deleting then rewriting must not unlock")
            fresh = "migrations/versions/0002_next.py"
            (repo / fresh).write_text("# new\n", encoding="utf-8")
            allowed = self.run_edit(repo, fresh)
            self.assertEqual(allowed.returncode, 0, allowed.stderr)


if __name__ == "__main__":
    unittest.main()
