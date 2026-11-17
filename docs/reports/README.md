# Reports

`/report` writes reports here as `YYYY-MM-DD-<phase>-<progress|gate>.md`. The owner pastes them into the architect chat for review.

## Template

```markdown
# <Phase> <progress|gate> report: YYYY-MM-DD

## Summary
Two or three sentences: where we are, and whether anything is red.

## Completed tasks
| Task | Pull request | Evidence (tests, output) |

## What was proven
- Claim, then evidence (test names, numbers, CI run link).

## What was NOT verified, and why
- Item, then reason (no real bills yet, no network, untested platform, ...).

## Quality numbers
| Check | Result |
| ruff / mypy / import-linter | pass/fail, counts |
| Tests | passed / failed / skipped |
| Coverage | line %, branch %, domain.billing branch % |
| Mutation score (if run) | killed / total |
| pip-audit | findings |
| CI | link and status |
| `uv run poe check` duration | seconds, measured on the owner's machine (WSL, repository on `/mnt/c`) |

## Assumptions and estimated values
- Each one, with where it is recorded.

## Deviations from the roadmap or ADRs
- What, why, and whether an ADR is needed.

## Technical debt added
- Rows added to docs/tech-debt.md.

## Risks and concerns
- Anything the owner or architect should worry about, including disagreements with the plan.

## Decisions waiting for the owner
| ID | Question | Options | Recommendation | Cost | Reversible? |

## Next
- Proposed next tasks. For a gate report: "Requesting approval to start Phase N+1."
```
