"""The pre-push hook in .pre-commit-config.yaml refuses pushes to main (P0-5).

Runs the hook's real `entry` from the config, with the environment pre-commit sets.
"""

import os
import shlex
import subprocess
from pathlib import Path

import pytest
import yaml  # type: ignore[import-untyped]  # pyyaml ships no type stubs; test-only use

CONFIG = Path(__file__).resolve().parents[2] / ".pre-commit-config.yaml"


def hook_entry(hook_id: str) -> list[str]:
    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    for repo in config["repos"]:
        for hook in repo["hooks"]:
            if hook["id"] == hook_id:
                return shlex.split(hook["entry"])
    raise LookupError(hook_id)


def run_hook(remote_branch: str | None) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if k != "PRE_COMMIT_REMOTE_BRANCH"}
    if remote_branch is not None:
        env["PRE_COMMIT_REMOTE_BRANCH"] = remote_branch
    return subprocess.run(  # noqa: S603 - runs the repository's own hook entry
        hook_entry("no-push-to-main"), env=env, capture_output=True, text=True, check=False
    )


def test_push_to_main_is_refused() -> None:
    result = run_hook("refs/heads/main")
    assert result.returncode == 1
    assert "Pushing to main is not allowed" in result.stderr


@pytest.mark.parametrize(
    "branch", ["refs/heads/feat/x", "refs/heads/main-fix", "refs/heads/chore/main"]
)
def test_push_to_other_branches_is_allowed(branch: str) -> None:
    assert run_hook(branch).returncode == 0


@pytest.mark.parametrize("branch", [None, ""])
def test_unknown_remote_branch_fails_closed(branch: str | None) -> None:
    result = run_hook(branch)
    assert result.returncode == 1
    assert "Remote branch unknown" in result.stderr


def test_hook_runs_only_at_push_time() -> None:
    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    hooks = {h["id"]: h for repo in config["repos"] for h in repo["hooks"]}
    assert hooks["no-push-to-main"]["stages"] == ["pre-push"]
    # Without always_run the hook is skipped for pushes that change no files.
    assert hooks["no-push-to-main"]["always_run"] is True
    assert "pre-push" in config["default_install_hook_types"]
