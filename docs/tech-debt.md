# Technical debt

Deliberate shortcuts and deferred review findings. Each row needs a reason and a trigger for paying it back.

| ID | Added | Item | Why deferred | Pay back when | Status |
| --- | --- | --- | --- | --- | --- |
| TD-1 | 2026-11-17 | guard_files reads `main` and `origin/main` as last fetched. An ADR accepted by a merge on GitHub is not protected until the next `git fetch` | No network call in a hook; fetching belongs in a workflow step | Add a `git fetch` step to `/next` or the session start (needs an owner-approved `.claude/` change) | open |
| TD-2 | 2026-11-17 | guard_files' "Superseded by" exemption allows any edit of an Accepted ADR whose new text contains those words, not only a status-line change | Predates this change; fixing it needs old/new comparison per tool | Next change to guard_files, or if it is ever abused | open |
| TD-3 | 2026-11-17 | guard_files covers Edit and Write only; Bash (`sed -i`, scripts) can still change ADRs and migrations | Hooks cannot see every write a shell makes | Owner's pull-request review is the backstop; revisit if it ever happens | open |
| TD-4 | 2026-11-17 | Hook tests run by hand only | No CI yet | P0-6 runs `.claude/hooks/tests` in CI | open |
| TD-5 | 2026-11-17 | `.claude/` is excluded from the project-wide ruff run (`extend-exclude`); the hooks' own test files are not ruff-formatted | Formatting `.claude/` needs the owner's approval | The next owner-approved `.claude/` change: format and lint the hooks, then remove the exclusion | open |
