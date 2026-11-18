# Testing strategy

The goal is evidence that MuniSense calculates bills correctly and refuses when it cannot, not a coverage number.

## Layers

| Layer | Folder | Tools | What it proves | Target |
| --- | --- | --- | --- | --- |
| Unit | `tests/unit/` | pytest | Each function and component behaves as specified, including edge cases | Fast (whole layer under about 30 seconds) |
| Property | `tests/property/` (the slowest are marked `slow`, so `poe check` skips them; `poe verify` and CI run all, E43) | Hypothesis | Invariants hold for any input: bills never negative; block bills never decrease as consumption rises; splitting a period changes totals by no more than rounding; VAT equals rate times VAT-able subtotal | Engine: 95% branch coverage across unit and property tests |
| Golden bills | `tests/golden/` + `data/golden/` | pytest | Real (anonymised) or official example bills reproduce to the cent. A prepaid golden case is a whole month of purchases | Every published tariff has at least one, or is flagged unverified |
| Integration | `tests/integration/` | pytest + real PostgreSQL | Migrations up and down; constraints; repositories; "as recorded on" queries; rebuilding the database from tariff files is deterministic | Every migration and query path |
| Contract | `tests/contract/` | Schemathesis + OpenAPI snapshot | The API matches its spec; no accidental breaking changes | All endpoints (from P5) |
| End-to-end | `tests/e2e/` | pytest + HTTP client | Review-and-publish and staff calculator flows work through the real app | Key flows (from P6) |
| Agent evaluation | `tests/eval/` | Scripted questions | The MCP tool improves answer accuracy against golden answers | P7 |
| Mutation | n/a | mutmut on `domain.billing` (`[tool.mutmut]` in `pyproject.toml`; last result in [mutation-p1-15.md](mutation-p1-15.md)) | Tests catch injected bugs | At least 80% killed; survivors reviewed |
| Architecture | n/a | import-linter | Dependency rules hold | All contracts pass |

## Markers and commands

- `uv run poe check` runs ruff, mypy and tests not marked `slow` or `db`. This is the fast loop and what the Stop hook runs.
- `uv run poe test` runs all tests with coverage (needs `docker compose up -d db`).
- `uv run poe verify` runs everything CI runs except the audit, including import-linter. It works offline.
- `uv run poe audit` runs pip-audit, which needs network access. CI always runs it, and a finding fails CI. A finding is ignored only with the owner's approval, an ignore entry naming the vulnerability, and a `tech-debt.md` row with a pay-back trigger.
- Every gate report states how long `uv run poe check` takes (the repository is on `/mnt/c`, which is slower from WSL; ADR-0010).
- Mutation testing runs at the end of P1 and P4, and before each gate when `domain.billing` changed (slow; not in CI by default).

## Rules

- A bug fix starts with a failing test that reproduces it.
- Tests use fixtures, never live websites. Tariff fixtures are marked as fixtures and are not real data unless they cite a source.
- No test depends on the current date. Pass dates explicitly.
- Tests for refusal paths are as important as tests for answers: missing version, estimated data, ambiguous period.
- Coverage must not fall. Overall line coverage at least 85%. (In P0 there is only a placeholder test; the P0-3 pull request states the threshold it sets and why.)
- Pydantic in the domain: a test proves that a `float` is rejected wherever money or a rate is expected.

## What tests cannot prove

Real-world accuracy depends on the bills used. Until P3 the engine is proven only against published figures and hand calculations. Every report says so.
