# Status

_Last updated: 2026-11-17, on branch `docs/accept-decisions` (owner's decisions applied to the documents)._

## Now

- **Phase:** P0 Foundation (in progress). P0-1 and P0-2 are done.
- **Next task:** P0-3 Python project skeleton, starting with one dependency approval request. It starts after the owner merges the `docs/accept-decisions` pull request.
- **Blocked on:** the owner merging the `docs/accept-decisions` pull request. P0-9 (push guard) waits separately for the owner's approval of a `.claude/` change; P0-3 does not depend on it.

## Waiting for the owner

| ID | Question | Recommendation |
| --- | --- | --- |
| W1 | Merge the `docs/accept-decisions` pull request | Merge. CI does not exist yet (P0-6), so it has no checks |
| W2 | Approve `.claude/` changes: (a) P0-9, a `guard_bash.py` rule blocking `git push` to `main`, with tests; (b) bringing skills and agents in line with the decisions: `skills/add-tariff/SKILL.md` (phase numbers, committed sources, stricter `verified`, publish writes the tariff file), `agents/tariff-verifier.md` (stricter `verified`), `skills/verify/SKILL.md` (run `poe audit` separately), `skills/report/SKILL.md` (time `poe check`) | Approve. Small and can be undone |
| W3 | P3 gate: "at least 10 golden cases" with a prepaid case being a whole month means 10 whole months of receipts, but only about 4 complete months exist under the 2026/27 schedule (from 1 July 2026) | Load the 2025/26 schedule as well in P3 (ADR-0007 already covers history from 2025/26), so earlier months count |

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
| Review items | Accepted: A1 to A3, A5 to A7, A9 to A13. A8: City Power dropped from P1; P1 examples use the Ekurhuleni 2026/27 electricity schedule, downloaded in P1 from the official municipal website only. C2: Pydantic in the domain, strict mode, float rejection tested. C5: keep PostgreSQL 17 and Python 3.13. C6: not now. B4: stay on `/mnt/c`; every gate report states how long `uv run poe check` takes | `reports/2026-11-17-P0-progress.md` |

## Phase 0 tasks

| ID | Task | Acceptance criteria | Status |
| --- | --- | --- | --- |
| P0-1 | Verify the development environment | Versions reported for WSL2, git, uv, Python 3.13, Docker and Compose, gh (authenticated) and the GitHub remote. Confirms the working directory is `/mnt/c/MuniSense/MuniSense` and `UV_PROJECT_ENVIRONMENT` points to a Linux path. Missing items listed with exact install commands. Nothing installed by Claude | **done** |
| P0-2 | Review the documents and ADRs | Written list of contradictions, gaps, risks and disagreements, with reasons. A view on each decision D1 to D10 | **done** |
| P0-3 | Python project skeleton | Starts with **one approval request listing every dev dependency and its licence**. `pyproject.toml` (Python 3.13, src layout); package folders as in `architecture/overview.md` (empty modules only); dev tools only, no runtime dependencies yet; poe tasks `fmt`, `check`, `test`, `verify`, and a separate `audit` (pip-audit); ruff, mypy strict, pytest, import-linter contracts; one placeholder test; `uv run poe verify` passes; the coverage threshold for P0 is stated in the pull request | todo |
| P0-4 | Local PostgreSQL | `docker-compose.yml` with PostgreSQL 17, a healthcheck, a named volume and separate dev and test databases. `.env.example` documents the variables. `docker compose up -d db` gives a healthy database | todo |
| P0-5 | pre-commit | ruff, gitleaks and basic file checks run on commit, and are proven by a failing example | todo |
| P0-6 | Continuous integration | GitHub Actions on `ubuntu-latest` with a `postgres:17` service and `astral-sh/setup-uv` runs `uv run poe verify` and `uv run poe audit` on pull requests and on pushes to main. A pull request shows green. The current free Actions allowance is re-checked | todo |
| P0-9 | Block pushes to `main` (E6) | `guard_bash.py` blocks `git push` to `main` (explicit refspecs, `HEAD:main`, and a bare `git push` while on `main`); tests show blocked and allowed cases. Needs the owner's approval because it changes `.claude/` | waiting for owner (W2) |
| P0-7 | Prove the hooks inside WSL | Evidence, from a WSL session, that each hook blocks or acts as documented: guard_bash (including the push-to-main rule), guard_files, format_lint, quality_gate, session_context | todo |
| P0-8 | Gate report | `/report gate` saved in `docs/reports/`, including how long `uv run poe check` takes | todo |

## Done

| Task | Evidence |
| --- | --- |
| P0-1 Verify the environment | `reports/2026-11-17-P0-progress.md`, section "P0-1 re-run inside WSL": every item green, run from WSL `Ubuntu` 24.04 |
| P0-2 Review the documents | `reports/2026-11-17-P0-progress.md`, sections A to D; the owner's decisions are in the table above and applied to the documents on `docs/accept-decisions` |

## Known limitations

- No code exists yet.
- No CI exists yet (P0-6), so nothing has been checked on a clean machine.
- guard_files, format_lint and quality_gate have not yet been seen running inside WSL (P0-7).
- The tariff facts in `domain/sa-tariffs.md` come from desk research and are not yet verified against primary documents.
