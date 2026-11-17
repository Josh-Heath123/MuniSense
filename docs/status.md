# Status

_Last updated: 2026-11-17, on branch `chore/p0-6-ci`._

## Now

- **Phase:** P0 Foundation (in progress). P0-1, P0-2, P0-3 and P0-9 are done; P0-6 is in review.
- **Next task:** P0-4 Local PostgreSQL, then P0-5 pre-commit, P0-7 hook proof and P0-8 gate report (E16 moved P0-6 first).
- **Blocked on:** nothing. Pull requests with green CI and clean reviews are merged with `gh pr merge --squash` (the owner approves the prompt).

## Waiting for the owner

| ID | Question | Recommendation |
| --- | --- | --- |
| W1 | Confirm in GitHub Settings → Billing that the Actions spending limit is $0, so CI can never be charged. The repository uses about 1 minute per run of the 2,000 free minutes a month | Check once; R0 |
| W2 | Optional, free GitHub settings: require actions pinned to a full commit SHA, and allow only GitHub-owned actions plus `astral-sh/setup-uv`; and/or enable Dependabot version updates for GitHub Actions (TD-7) | Turn on the SHA-pinning requirement; decide Dependabot when TD-7 is paid back. These change account settings, so they are the owner's call |

## Decided (owner: Josh Heath, 2026-11-17)

| ID | Decision | Record |
| --- | --- | --- |
| D1 | Electricity only in the MVP, for credit and prepaid meters, including the prepaid purchase calculation (E2) | ADR-0007 |
| D2 | City of Ekurhuleni first; then Eskom-direct, City Power, Cape Town, Tshwane, eThekwini, Nelson Mandela Bay, in an order the owner chooses in P8 | ADR-0007 |
| D3 | REST API, staff console with a **staff-only** calculator (E5), MCP server as the last MVP step | ADR-0007, ADR-0009 |
| D4 | Python 3.13 modular monolith: FastAPI, PostgreSQL 17, SQLAlchemy 2, Alembic. Record time as a range, with a two-dimensional exclusion constraint (`btree_gist`); record time starts at publication | ADR-0002, ADR-0003 |
| D5 | Private GitHub repository on the free plan; GitHub Actions. No branch protection; Claude Code is blocked from pushing to `main` (E6) | ADR-0010 |
| D6 | Windows with WSL2 (Ubuntu 24.04, non-root user) and Docker Desktop; repository at `C:\MuniSense\MuniSense`, worked on from WSL2 | ADR-0010 |
| D7 | Official sources only; per-value citations; stricter `verified` (deterministic text check plus recorded verifier); source PDFs committed; legal opinion before charging | ADR-0006 |
| D8 | The MVP stores no personal information | ADR-0008 |
| D9 | Keep "MuniSense" as the working name | (this table) |
| D10 | Declarative components with per-value provenance; Pydantic v2 in the domain in strict mode; Decimal money with explicit quantisation points, including VAT; server-rendered console | ADR-0004, ADR-0005, ADR-0009 |
| E1 | Working environment: WSL `Ubuntu` 24.04, non-root user | ADR-0010 |
| E2 | The owner's bills are prepaid. The prepaid purchase calculation is in MVP scope and built in P1. Prepaid golden cases are whole months of purchases | ADR-0004, ADR-0007, `roadmap.md` |
| E3 | Phases reordered: P1 calculation core (with seasons, period splitting, prepaid), P2 versioned storage, P3 Ekurhuleni pilot, P4 time-of-use, demand, capacity and export credits. P5 to P10 unchanged. Consumption input designed as a profile type now | `roadmap.md`, ADR-0004 |
| E4 | Committed, reviewed tariff files are the source of truth through P9; the database is rebuilt from them deterministically. The publish step writes record time into the file. Source PDFs are committed. Storage ADR at the start of P2 | ADR-0003, ADR-0006 |
| E5 | Calculator is staff-only in the MVP; a public one is decided at P9 | ADR-0007 |
| E6 | Block `git push` to `main` in `guard_bash.py`, with tests | P0-9 |
| E7 | The owner is Josh Heath | All documents |
| E8 | P3 loads the 2025/26 Ekurhuleni schedule as well as 2026/27, so 10 whole months of prepaid receipts can be golden cases | `roadmap.md` |
| E10 | `.claude/` changes approved: P0-9 push guard with tests, and skills and agents aligned with the decisions | P0-9 |
| E9 | ADR-0003, ADR-0004 and ADR-0010 corrected on the unmerged `docs/accept-decisions` branch after review, with the owner's permission | PR #1 |
| E11 | Reviewers never modify files or evade hooks (all three agent files); `/review` requires a clean tree and compares `git status --porcelain` before and after, reverting any change and reporting it as BLOCKING | `chore/p0-followups` |
| E12 | `guard_files.py` treats an ADR as Accepted only when it is Accepted on main (falling back to the working-tree file when git cannot answer), so a branch can correct an ADR before the owner merges it | `chore/p0-followups` |
| E13 | Prepaid golden case match rule: given each purchase's rand amount and the month's earlier purchases, the computed kWh equals the receipt's kWh at the printed precision | `roadmap.md` |
| E14 | Dev dependencies approved: ruff, mypy, pytest, pytest-cov, import-linter, poethepoet, pip-audit (P0-3); pre-commit, gitleaks (P0-5); hypothesis (P1). The lock ignores releases younger than 14 days (`exclude-newer`) | `pyproject.toml` |
| E15 | Licence policy in `quality/standards.md`: permissive licences (MIT, BSD, Apache-2.0, ISC, PSF) are fine; MPL-2.0 and LGPL are fine for unmodified libraries; GPL and AGPL need an ADR. New dependencies still need the owner's approval. certifi and pathspec (MPL-2.0, transitive, dev-only) accepted | `quality/standards.md` |
| E16 | P0-6 (CI) before P0-4 and P0-5, so every later pull request is checked on a clean machine | this file |
| E17 | When a pull request has green CI and clean reviews, Claude Code runs `gh pr merge --squash` (the owner approves the prompt) and carries on with the next task, unless something is on the escalation list in `CLAUDE.md` | this file |
| E18 | Stop hardening the hooks. TD-1 to TD-3 are accepted: pull requests, the pre-push hook (P0-5) and CI are the real controls. A hook changes only if it breaks or blocks legitimate work | `tech-debt.md` |
| Review items | Accepted: A1 to A3, A5 to A7, A9 to A13. A8: City Power dropped from P1; P1 examples use the Ekurhuleni 2026/27 electricity schedule, downloaded in P1 from the official municipal website only. C2: Pydantic in the domain, strict mode, float rejection tested. C5: keep PostgreSQL 17 and Python 3.13. C6: not now. B4: stay on `/mnt/c`; every gate report states how long `uv run poe check` takes | `reports/2026-11-17-P0-progress.md` |

## Phase 0 tasks

| ID | Task | Acceptance criteria | Status |
| --- | --- | --- | --- |
| P0-1 | Verify the development environment | Versions reported for WSL2, git, uv, Python 3.13, Docker and Compose, gh (authenticated) and the GitHub remote. Confirms the working directory is `/mnt/c/MuniSense/MuniSense` and `UV_PROJECT_ENVIRONMENT` points to a Linux path. Missing items listed with exact install commands. Nothing installed by Claude | **done** |
| P0-2 | Review the documents and ADRs | Written list of contradictions, gaps, risks and disagreements, with reasons. A view on each decision D1 to D10 | **done** |
| P0-3 | Python project skeleton | Starts with **one approval request listing every dev dependency and its licence**. `pyproject.toml` (Python 3.13, src layout); package folders as in `architecture/overview.md` (empty modules only); dev tools only, no runtime dependencies yet; poe tasks `fmt`, `check`, `test`, `verify`, and a separate `audit` (pip-audit); ruff, mypy strict, pytest, import-linter contracts; one placeholder test; `uv run poe verify` passes; the coverage threshold for P0 is stated in the pull request | **done** (PR #4, merged before CI existed) |
| P0-4 | Local PostgreSQL | `docker-compose.yml` with PostgreSQL 17, a healthcheck, a named volume and separate dev and test databases. `.env.example` documents the variables. `docker compose up -d db` gives a healthy database | todo |
| P0-5 | pre-commit | ruff, gitleaks and basic file checks run on commit, and are proven by a failing example. A **pre-push** hook rejects any push whose remote branch (`PRE_COMMIT_REMOTE_BRANCH`) is `main`, catching pushes that the `guard_bash.py` parser cannot see; proven by a blocked push | todo |
| P0-6 | Continuous integration | GitHub Actions on `ubuntu-latest` with a `postgres:17` service and `astral-sh/setup-uv` runs `uv run poe verify` (which includes the hook tests in `.claude/hooks/tests/`) and `uv run poe audit`, with `UV_LOCKED=1` so a stale lock fails instead of being re-resolved on pull requests and on pushes to main. A pull request shows green. The current free Actions allowance is re-checked | in review (`chore/p0-6-ci`) |
| P0-9 | Block pushes to `main` (E6) | `guard_bash.py` blocks `git push` to `main` (explicit refspecs, `HEAD:main`, and a bare `git push` while on `main`); tests show blocked and allowed cases. Needs the owner's approval because it changes `.claude/` | **done** (PR #2) |
| P0-7 | Prove the hooks inside WSL | Evidence, from a WSL session, that each hook blocks or acts as documented: guard_bash (including the push-to-main rule), guard_files, format_lint, quality_gate, session_context | todo |
| P0-8 | Gate report | `/report gate` saved in `docs/reports/`, including how long `uv run poe check` takes | todo |

## Done

| Task | Evidence |
| --- | --- |
| P0-1 Verify the environment | `reports/2026-11-17-P0-progress.md`, section "P0-1 re-run inside WSL": every item green, run from WSL `Ubuntu` 24.04 |
| P0-6 Continuous integration | `.github/workflows/ci.yml`: ubuntu-latest, `postgres:17` service pinned by digest (healthy; `pg_isready` step), uv 0.13.9 via `astral-sh/setup-uv`, actions pinned by commit SHA, `UV_LOCKED=1`, read-only token, 15-minute timeout. Green on the final commit: see the PR. **Shown to fail** on: a lint error ([run](https://github.com/Josh-Heath123/MuniSense/actions/runs/44085470862), ruff), a type error ([run](https://github.com/Josh-Heath123/MuniSense/actions/runs/44085568527), mypy), a stale lock ([run](https://github.com/Josh-Heath123/MuniSense/actions/runs/44086990624): `The lockfile at uv.lock needs to be updated, but UV_LOCKED=1 was provided`) and a failing test ([run](https://github.com/Josh-Heath123/MuniSense/actions/runs/44087740947): `1 failed`, `Sequence aborted after failed subtask 'test'`). About 1 billed minute per run. Free allowance re-checked on 2026-11-17 against public sources only: [GitHub's pricing page](https://github.com/pricing) still lists 2,000 minutes a month for private repositories on Free; the [2026 pricing change](https://github.com/resources/insights/2026-pricing-changes-for-github-actions) builds a platform charge into hosted-runner rates; the account's own billing page was **not** checked (needs a broader token scope), hence W1 |
| P0-3 Python project skeleton | `uv run poe verify` passes: ruff format and lint clean, mypy strict clean (15 source files), 5 import-linter contracts kept, and **each contract shown to break** on a deliberate violation (Rule 3 also shown to allow `api -> services -> domain`), 1 test passed, 33 hook tests passed. `uv run poe audit` audits all 46 locked packages for every platform (exported lock, hashes required): no known vulnerabilities. Wheels only (`no-build`). `uv run poe check`: 4.0 to 4.8 s on `/mnt/c`. Licences: no GPL or AGPL; MPL-2.0 for hypothesis (approved) and, transitively and dev-only, certifi and pathspec (accepted, E15); PSF for defusedxml and typing-extensions; the rest MIT, BSD or Apache |
| P0 follow-ups (E11, E12, E13) | Branch `chore/p0-followups`: 33 hook tests in `.claude/hooks/tests/` pass (18 guard_bash, 15 guard_files); 5 of the new guard_files tests fail against the previous version; a case-variant ADR path on `/mnt/c` is blocked (reproduced by hand); code and security reviews done, findings fixed or recorded in `tech-debt.md` |
| P0-9 Block pushes to `main` | PR #2: 18 tests in `.claude/hooks/tests/` pass; a live `git push --dry-run origin HEAD:main` was blocked; review findings fixed |
| P0-2 Review the documents | `reports/2026-11-17-P0-progress.md`, sections A to D; the owner's decisions are in the table above and applied to the documents on `docs/accept-decisions` |

## Notes for later phases

| Phase | Note |
| --- | --- |
| P2 | The PDF text-extraction dependency for the citation check must **not** be PyMuPDF (AGPL). pypdf (BSD) or pdfplumber (MIT) are acceptable candidates; the choice still needs the owner's dependency approval |
| Before P5 | Add a build backend (owner approval as a dependency) so the application can run outside the test setup (`package = false` today) |
| Before P5 | Document how to install an urgent security fix that is younger than the 14-day `exclude-newer` window (for example a per-package override, `exclude-newer-package`, with the owner's approval and a `tech-debt.md` row) |

## Known limitations

- No application code exists yet: the package holds empty modules, so the 100% coverage reported in P0 is vacuous.
- Hypothesis (approved, MPL-2.0) is added in P1; pre-commit and gitleaks in P0-5.
- guard_files, format_lint and quality_gate have not yet been seen running inside WSL (P0-7).
- CI is not a merge gate: there is no branch protection on the free plan, so a red pull request can still be merged by hand. Claude Code merges only on green (E17).
- CI starts PostgreSQL 17, but no test connects to it yet; P0-4 aligns its settings with `.env.example`, and database tests arrive in P2.
- `ubuntu-latest` is now Ubuntu 26.04, while development runs on Ubuntu 24.04. uv supplies CPython 3.13 on both (the patch level may differ).
- The tariff facts in `domain/sa-tariffs.md` come from desk research and are not yet verified against primary documents.
