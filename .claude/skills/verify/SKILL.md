---
name: verify
description: Run the full quality gate and summarise the results honestly, including what was not checked.
disable-model-invocation: true
---

# /verify

1. Run `uv run poe verify`, then `uv run poe audit` (pip-audit; needs network). If either does not exist yet (early Phase 0), run whatever checks do exist, and list what is missing. If the audit cannot reach the network, report it as **not run**, not as passed.
2. Summarise each check with its result and numbers:
   - lint and format
   - mypy (error count)
   - import-linter contracts
   - tests (passed, failed, skipped) and coverage (line and branch, with domain coverage separately)
   - pip-audit findings
   - mutation score, if the task touched `domain.billing` and mutation testing was run
3. List explicitly what this run does **not** prove. Examples: no real bills yet; CI has not run on this branch; not tested on native Windows; external source not re-checked.
4. If any check failed or was skipped, say so first, in plain words. Never report success over a red or skipped check.
