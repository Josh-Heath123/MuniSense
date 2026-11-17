---
name: report
description: Write a progress or phase-gate report for the owner and the architect chat, using the fixed template.
argument-hint: "[progress|gate]"
disable-model-invocation: true
---

# /report

The report type is `$ARGUMENTS`: `progress` (default) or `gate` (end of a phase).

1. Gather evidence:
   - a fresh `uv run poe verify` and `uv run poe audit` (or what exists so far)
   - how long `uv run poe check` takes (`time uv run poe check`), for the quality-numbers table
   - `git log` since the last report in `docs/reports/`
   - `docs/status.md` and `docs/tech-debt.md`
   - CI status of recent pull requests (`gh pr checks`, `gh run list`)
2. Write the report using the template in `docs/reports/README.md`. Every claim needs its evidence (test names, numbers, commit or pull request links). Mandatory sections:
   - what was proven
   - what was **not** verified, and why
   - assumptions made, and values marked `estimated`
   - deviations from the roadmap or ADRs
   - technical debt added
   - decisions waiting for the owner
3. Save it as `docs/reports/YYYY-MM-DD-<phase>-<type>.md` and update `docs/status.md`.
4. Print the full report in your reply so the owner can paste it into the architect chat.
5. For a `gate` report, end with "Requesting approval to start Phase N+1." and **stop**. Do not begin the next phase.
