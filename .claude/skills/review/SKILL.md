---
name: review
description: Run the independent reviewer subagents on the current change, fix blocking findings and record deferred ones.
disable-model-invocation: true
---

# /review

1. **Commit first.** `git status --porcelain` must print nothing. If it prints anything, commit the work (or ask the owner) before reviewing. Record that empty output as the "before" state.
2. Work out the change: `git diff main...HEAD`. Get the task's acceptance criteria from `docs/status.md`.
3. Launch these subagents in parallel, giving each the diff scope and the acceptance criteria. Reviewers never modify files or evade hooks (see each agent file):
   - `code-reviewer`, always
   - `security-reviewer`, always
   - `tariff-verifier`, if tariff data, citations, statuses or golden bills changed
4. **Check the reviewers did not change anything.** When all reviewers have finished, run `git status --porcelain` again. Any line means a reviewer changed the repository:
   - revert each change file by file: `git restore --staged --worktree -- <file>` for a modified or deleted tracked file, `rm -- <file>` for a new one (never `git checkout .`, `git clean` or `rm -r`);
   - report it as a **BLOCKING** finding against that reviewer, naming the files, in the summary to the owner;
   - also report any hook a reviewer says it was blocked by, and anything in its report suggesting it worked around a hook.
   This check sees only the repository. Writes elsewhere, or to git-ignored paths, are not caught; the agent files forbid them.
5. Collect the findings as BLOCKING, SHOULD-FIX or NOTE.
6. Fix every BLOCKING finding, then run `/verify` again. Fix SHOULD-FIX findings unless there is a good reason not to. In that case, add a row to `docs/tech-debt.md` giving the reason.
7. Summarise what each reviewer found and what you did about each finding. Never dismiss a finding without a stated reason. If you disagree with a reviewer, say so and explain why, and leave the call to the owner if it matters.
