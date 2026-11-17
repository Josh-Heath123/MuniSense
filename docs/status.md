# Status

_Last updated: 2026-11-17, when the starter pack was created in the architect chat._

## Now

- **Phase:** P0 Foundation (not started)
- **Next task:** P0-1 Verify the environment, then P0-2 Review the documents. No code until the owner approves the decisions below.
- **Blocked on:** the owner's decisions D1 to D10

## Waiting for the owner

| ID | Decision | Recommendation | Record |
| --- | --- | --- | --- |
| D1 | MVP scope | Electricity only. Model water, sanitation and property rates later | ADR-0007 |
| D2 | First supplier | City of Ekurhuleni; then Eskom-direct, City Power, Cape Town, Tshwane, eThekwini, Nelson Mandela Bay | ADR-0007 |
| D3 | What the MVP exposes | REST API, staff curation console, simple public calculator; MCP server as the last MVP step | ADR-0007 |
| D4 | Technology | Python modular monolith: FastAPI, PostgreSQL 17, SQLAlchemy 2, Alembic | ADR-0002, ADR-0003 |
| D5 | Code hosting and CI | Private GitHub repository on the free plan; GitHub Actions | ADR-0010 |
| D6 | Development machine | Windows with WSL2 (Ubuntu) and Docker Desktop; repository at `C:\MuniSense\MuniSense`, worked on from WSL2 | ADR-0010 |
| D7 | Data and legal stance | Official sources only; every value labelled verified, estimated or user-provided; legal opinion before charging | ADR-0006 |
| D8 | Personal information | The MVP stores none | ADR-0008 |
| D9 | Name | Keep "MuniSense" as the working name | (this table) |
| D10 | Technical design | Declarative tariff components, Decimal money with per-supplier rounding, server-rendered console | ADR-0004, ADR-0005, ADR-0009 |

## Phase 0 tasks

| ID | Task | Acceptance criteria | Status |
| --- | --- | --- | --- |
| P0-1 | Verify the development environment | Versions reported for WSL2, git, uv, Python 3.13, Docker and Compose, gh (authenticated) and the GitHub remote. Confirms the working directory is `/mnt/c/MuniSense/MuniSense` and `UV_PROJECT_ENVIRONMENT` points to a Linux path. Missing items listed with exact install commands. Nothing installed by Claude | todo |
| P0-2 | Review the documents and ADRs | Written list of contradictions, gaps, risks and disagreements, with reasons. A view on each decision D1 to D10 | todo |
| P0-3 | Python project skeleton | `pyproject.toml` (Python 3.13, src layout); package folders as in `architecture/overview.md` (empty modules only); dev tools only, no runtime dependencies yet; poe tasks `fmt`, `check`, `test`, `verify`; ruff, mypy strict, pytest, import-linter contracts; one placeholder test; `uv run poe verify` passes | todo |
| P0-4 | Local PostgreSQL | `docker-compose.yml` with PostgreSQL 17, a healthcheck, a named volume and separate dev and test databases. `.env.example` documents the variables. `docker compose up -d db` gives a healthy database | todo |
| P0-5 | pre-commit | ruff, gitleaks and basic file checks run on commit, and are proven by a failing example | todo |
| P0-6 | Continuous integration | GitHub Actions runs `uv run poe verify` with a PostgreSQL service on pull requests and on pushes to main. A pull request shows green | todo |
| P0-7 | Prove the hooks | Evidence that each hook blocks or acts as documented: guard_bash, guard_files, format_lint, quality_gate, session_context | todo |
| P0-8 | Gate report | `/report gate` saved in `docs/reports/` | todo |

## Done

Nothing yet.

## Known limitations

- Nothing is built yet.
- The tariff facts in `domain/sa-tariffs.md` come from desk research and are not yet verified against primary documents.
