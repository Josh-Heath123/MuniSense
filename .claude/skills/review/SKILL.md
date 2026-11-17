---
name: review
description: Run the independent reviewer subagents on the current change, fix blocking findings and record deferred ones.
disable-model-invocation: true
---

# /review

1. **Commit first, then record the "before" state.** `git status --porcelain --untracked-files=all` must print nothing; if it prints anything, commit the work (or ask the owner) before reviewing. Then record:
   - `git rev-parse HEAD`
   - `git branch --show-current`
   - `git stash list`
   - `git for-each-ref --format='%(refname) %(objectname)'`
   Do not edit files while the reviewers run, and ask the owner not to either: any change in that window is treated as a reviewer's.
2. Work out the change: `git diff main...HEAD`. Get the task's acceptance criteria from `docs/status.md`.
3. Launch these subagents in parallel, giving each the diff scope and the acceptance criteria. Reviewers never modify files or evade hooks (see each agent file):
   - `code-reviewer`, always
   - `security-reviewer`, always
   - `tariff-verifier`, if tariff data, citations, statuses or golden bills changed
4. **Check the reviewers did not change anything.** When all reviewers have finished, repeat every command from step 1. Any difference is a **BLOCKING** finding against the reviewers, reported to the owner with the files or refs involved, together with any hook a reviewer says it was blocked by and anything suggesting it worked around a hook.
   - **Working-tree changes** (`git status --porcelain --untracked-files=all` prints lines): revert them file by file. Use `git restore --staged --worktree -- <file>` for a modified or deleted tracked file, `rm -- <file>` for a new file, and for a rename (`R  old -> new`) restore `old` and remove `new`. Never use `git checkout .`, `git clean` or `rm -r`.
   - **A new commit, a branch switch, a stash or a changed ref:** do not try to undo it yourself, because that needs `git reset` or similar. Stop and ask the owner.
   - **Limits:** this check cannot see writes outside the repository, writes to git-ignored paths, or writes inside `.git/` that change no ref (for example `.git/hooks/` or `.git/config`). The agent files forbid all of these.
5. Collect the findings as BLOCKING, SHOULD-FIX or NOTE.
6. Fix every BLOCKING finding, then run `/verify` again. Fix SHOULD-FIX findings unless there is a good reason not to. In that case, add a row to `docs/tech-debt.md` giving the reason.
7. Summarise what each reviewer found and what you did about each finding. Never dismiss a finding without a stated reason. If you disagree with a reviewer, say so and explain why, and leave the call to the owner if it matters.
