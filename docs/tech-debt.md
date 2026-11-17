# Technical debt

Deliberate shortcuts and deferred review findings. Each row needs a reason and a trigger for paying it back.

| ID | Added | Item | Why deferred | Pay back when | Status |
| --- | --- | --- | --- | --- | --- |
| TD-1 | 2026-11-17 | guard_files reads `main` and `origin/main` as last fetched. An ADR accepted by a merge on GitHub is not protected until the next `git fetch` | No network call in a hook; fetching belongs in a workflow step | Add a `git fetch` step to `/next` or the session start (needs an owner-approved `.claude/` change) | open |
| TD-2 | 2026-11-17 | guard_files' "Superseded by" exemption allows any edit of an Accepted ADR whose new text contains those words, not only a status-line change | Predates this change; fixing it needs old/new comparison per tool | Next change to guard_files, or if it is ever abused | open |
| TD-3 | 2026-11-17 | guard_files covers Edit and Write only; Bash (`sed -i`, scripts) can still change ADRs and migrations | Hooks cannot see every write a shell makes | Owner's pull-request review is the backstop; revisit if it ever happens | open |
| TD-4 | 2026-11-17 | Hook tests run locally in `poe verify` only, not in CI | No CI yet | P0-6 | open |
| TD-5 | 2026-11-17 | `.claude/` is excluded from ruff (`extend-exclude` with `force-exclude`, so the format_lint hook skips it too). Running ruff on the hooks would report 64 findings and reformat two test files | Changing `.claude/` needs the owner's approval | The next owner-approved `.claude/` change: format and lint the hooks, then remove the exclusion | open |
| TD-6 | 2026-11-17 | Import contracts on third-party packages are not enforced yet: rule 4 (only `persistence` imports SQLAlchemy) and the third-party half of rule 1 (the domain imports only the standard library and Pydantic) | No third-party runtime dependency exists yet; the contracts need `include_external_packages` | When Pydantic arrives (P1) and SQLAlchemy (P2) | open |
