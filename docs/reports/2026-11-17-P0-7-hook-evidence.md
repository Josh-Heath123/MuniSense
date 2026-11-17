# P0-7 hook evidence: 2026-11-17

Evidence that each hook works inside WSL (`Ubuntu` 24.04, non-root user, repository at `/mnt/c/MuniSense/MuniSense`). The summary is in `docs/status.md` (P0-7 row in "Done"). This file holds the exact commands and outputs, so that they can be checked.

## Claude Code hooks, seen in Claude's WSL session

| Hook | What was run | Result |
| --- | --- | --- |
| session_context | Session start; and run directly with `{}` on stdin | Context printed at session start; run directly, it prints `MuniSense session context …`, `Git: branch 'chore/p0-7-prove-hooks', 0 uncommitted file(s).`, then the "Now" and "Waiting for the owner" sections; exit 0 |
| guard_bash | The Bash tool was asked to run `git push --dry-run origin HEAD:main`, `docker volume rm munisense-p07-nonexistent-volume`, `rm -rf <scratchpad>/p07-does-not-exist`, and `git commit --no-verify --allow-empty --dry-run -m …`. Each was chosen to be harmless had it run | Each was refused with `Blocked by .claude/hooks/guard_bash.py.` and the matching reason (push to `main`, Docker volumes, `rm -rf`, `--no-verify`). The message names guard_bash, so the block came from the hook, not from a `deny` rule in `settings.json`. Earlier in this same session it blocked `cat .env` (P0-1 re-run). It allowed the feature-branch pushes made in this session, for example `git push -u origin chore/p0-7-prove-hooks` |
| guard_files | Edit of `docs/adr/0002-python-modular-monolith.md` (title change); Write of a scratchpad file containing a private-key header line | Both refused with `Blocked by .claude/hooks/guard_files.py.`: "is Accepted on main", and "appears to contain a private key". ADR-0002 is unchanged |
| format_lint | Write of `p07_format_check.py` containing an unused import, bad spacing and an undefined name | The hook reformatted the file, removed the import ("1 fixed") and blocked on `F821 Undefined name` ("1 remaining"). The file was then deleted |
| quality_gate | See the next section | |

## quality_gate

- **Run directly with the Stop payload:**
  - with the broken `p07_format_check.py` present, exit 2 (`Quality gate failed: uv run --quiet poe check exited with code 1`);
  - with `{"stop_hook_active": true}`, exit 0, so it cannot loop;
  - after the file was removed (no changed Python file), exit 0.
- **Live, at the end of a real turn:**
  - Setup: the temporary file `src/munisense/p07_gate_check.py` (a function annotated `-> int` that returns a string) passes ruff, so format_lint stayed quiet. Claude then ended its turn.
  - Claude Code ran the `Stop` hook. It blocked once, with this feedback:

    ```text
    Quality gate failed: `uv run --quiet poe check` exited with code 1.
    ...
    src/munisense/p07_gate_check.py:5: error: Incompatible return value type (got "str", expected "int")  [return-value]
    Found 1 error in 1 file (checked 17 source files)
    ...
    Error: Sequence aborted after failed subtask '_types'
    ```

  - The temporary file was then deleted.

## pre-commit pre-push hook: a real push to `main` (run by the owner)

The owner ran this script from Claude Code's `!` shell, which runs in the same WSL session, after reading it. It uses a throwaway clone (with `origin` removed) and a throwaway local bare repository, so it cannot reach GitHub or the real repository.

```bash
#!/usr/bin/env bash
set -u
d=$(mktemp -d)
echo "Working in $d"
git clone -q /mnt/c/MuniSense/MuniSense "$d/work"
git init -q --bare "$d/remote.git"
cd "$d/work" || exit 1
git remote remove origin            # the clone can no longer reach the real repository
git remote add throwaway "$d/remote.git"
uv run pre-commit install

echo; echo "=== 1. push to main on the throwaway remote (expected: refused)"
git push throwaway HEAD:refs/heads/main
echo "exit code: $?"

echo; echo "=== 2. push to a feature branch on the throwaway remote (expected: accepted)"
git push throwaway HEAD:refs/heads/feat/p07-proof
echo "exit code: $?"

echo; echo "=== branches that reached the throwaway remote:"
git --git-dir="$d/remote.git" branch --list
```

Output, as the owner ran it:

```text
Working in /tmp/tmp.Mi1Tifq3CV
pre-commit installed at .git/hooks/pre-commit
pre-commit installed at .git/hooks/pre-push

=== 1. push to main on the throwaway remote (expected: refused)
refuse pushes to main....................................................Failed
- hook id: no-push-to-main
- exit code: 1

Pushing to main is not allowed. Push a branch and open a pull request.

error: failed to push some refs to '/tmp/tmp.Mi1Tifq3CV/remote.git'
exit code: 1

=== 2. push to a feature branch on the throwaway remote (expected: accepted)
refuse pushes to main....................................................Passed
To /tmp/tmp.Mi1Tifq3CV/remote.git
 * [new branch]      HEAD -> feat/p07-proof
exit code: 0

=== branches that reached the throwaway remote:
  feat/p07-proof
```

This shows a single-ref push to `main` being refused. The hook's known gaps (deleting `main`, multi-ref pushes, a stale view of `main`) are untouched and accepted as TD-9 (E21).

## Hook unit tests

`uv run poe hook-tests`: 33 tests pass. They also run in CI through `uv run poe verify`.
