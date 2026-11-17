---
name: review
description: Run the independent reviewer subagents on the current change, fix blocking findings and record deferred ones.
disable-model-invocation: true
---

# /review

1. Work out the change: `git diff main...HEAD` plus any uncommitted changes. Get the task's acceptance criteria from `docs/status.md`.
2. Launch these subagents in parallel, giving each the diff scope and the acceptance criteria:
   - `code-reviewer`, always
   - `security-reviewer`, always
   - `tariff-verifier`, if tariff data, citations, statuses or golden bills changed
3. Collect the findings as BLOCKING, SHOULD-FIX or NOTE.
4. Fix every BLOCKING finding, then run `/verify` again. Fix SHOULD-FIX findings unless there is a good reason not to. In that case, add a row to `docs/tech-debt.md` giving the reason.
5. Summarise what each reviewer found and what you did about each finding. Never dismiss a finding without a stated reason. If you disagree with a reviewer, say so and explain why, and leave the call to the owner if it matters.
