---
name: next
description: Pick the next task from docs/status.md, plan it and start it. Use at the start of a work session or after finishing a task.
argument-hint: "[task id, e.g. P1-3]"
disable-model-invocation: true
---

# /next

1. Read `docs/status.md`, `docs/roadmap.md` and the ADRs relevant to the current phase.
2. If something in "Waiting for the owner" blocks the next task, stop and say so. Do not start around it.
3. Choose the task:
   - If `$ARGUMENTS` names a task, use that one.
   - Otherwise take the first `todo` task in the current phase whose dependencies are done.
   - If the current phase has no task list yet, break its roadmap row into tasks of at most about half a day each. Give every task acceptance criteria that can be checked. Add them to `docs/status.md`, show the list to the owner and **stop for approval**.
4. Write a short plan:
   - goal and acceptance criteria
   - files likely to change
   - the tests you will write first
   - risks and unknowns
   - anything that needs the owner's approval under the CLAUDE.md escalation rules
5. If the plan needs approval, ask in the CLAUDE.md format (options, recommendation, cost, reversibility) and stop.
6. Otherwise create the branch, mark the task `in progress` in `docs/status.md` and start work.
