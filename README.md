<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/hero-dark.svg">
  <img alt="MuniSense: exact, source-cited municipal electricity bills for South Africa. The banner shows one line of a City of Ekurhuleni Tariff B bill calculated by MuniSense: energy charge, 350 kWh at R3.3700 per kWh, R1,179.50, cited to page 4 of the 2026/27 schedule, status estimated." src="docs/assets/hero-light.svg" width="100%">
</picture>

**Exact, source-cited municipal electricity bills for South Africa: every value traced to its page, every rounding named.**

[![CI](https://github.com/Josh-Heath123/MuniSense/actions/workflows/ci.yml/badge.svg)](https://github.com/Josh-Heath123/MuniSense/actions/workflows/ci.yml)
![Python 3.13](https://img.shields.io/badge/python-3.13-52524E)
![Licence: proprietary](https://img.shields.io/badge/licence-proprietary-060606)

## The problem

Municipal electricity tariffs are published as long PDF schedules. Ekurhuleni's signed 2026/27 schedule is a 37-page scan.
Checking a bill or a prepaid purchase against them by hand is slow and easy to get wrong.
Software and AI agents need exact answers that can be traced back to the page they came from.

## What it does now

Phase 1, the calculation core, is **Built** and passed its gate on 2026-11-18. It is a pure Python library; there is no API or user interface yet.

| Capability | Status |
| --- | --- |
| Exact money and rates: `Decimal` only, floats refused, every rounding at a named policy point | Built |
| A citation (document SHA-256, page, printed text) and a status (verified, estimated or user-provided) on every tariff value | Built |
| Forward bills: fixed charges, flat, block and seasonal energy, levies, free basic allocations, VAT | Built |
| Billing periods split across months, tariff versions, seasons and VAT changes, pro-rated by a named policy | Built |
| Prepaid purchases: the kWh a rand amount buys, given the month's earlier purchases | Built |
| City of Ekurhuleni 2026/27 Tariff B (Residential), transcribed with a citation per value | Built, all values `estimated` |
| Versioned storage, publishing workflow, automatic citation check | Planned (P2) |
| REST API, staff console, MCP server for AI agents | Planned (P5, P6, P7) |

### An example from the real tariff

<!-- demo:start -->
TARIFF B (RESIDENTIAL), single-phase, July 2026, 350 kWh (`uv run poe demo`):

| Line | Quantity | Rate | Amount | Source | Status |
| --- | --- | --- | ---: | --- | --- |
| Basic charge | 1 month | R109.78/month | R109.78 | Ekurhuleni schedule, p. 4 | estimated |
| Energy charge | 350 kWh | R3.3700/kWh | R1,179.50 | Ekurhuleni schedule, p. 4 | estimated |
| Subtotal | | | R1,289.28 | | |
| VAT | 15% | | R193.39 | SARS VAT 404, p. 15 | estimated |
| **Total** | | | **R1,482.67** | | **estimated** |

Warnings on the bill:

- Some values used are estimated, not verified against the source; see each line's status.
- Rounding policy 'ekurhuleni-estimated' is estimated; cent-level differences from a real bill are possible.
<!-- demo:end -->

This table is the engine's own output, and a test keeps it identical to the code. The values are **estimated**: they are transcribed from the City of Ekurhuleni's signed 2026/27 schedule, which is a scan, and nothing is marked verified until a person has checked it against the page. The rounding policy is an assumption until it can be confirmed from real Ekurhuleni bills or receipts.

## Engineering highlights

All figures are from the [P1 gate report](docs/reports/2026-11-18-P1-gate.md).

- **578 tests, 100% line and branch coverage** of the code built so far, run in CI on every pull request.
- **90.2% mutation score** on the billing engine: 1,380 of 1,530 injected bugs caught. Every surviving mutant is reviewed and listed in [mutation-p1-15.md](docs/quality/mutation-p1-15.md).
- **No floats, no silent rounding.** Arithmetic is exact or refused. Rounding happens only at points a supplier's policy names ([ADR-0005](docs/adr/0005-decimal-money-and-rounding-policies.md), [ADR-0011](docs/adr/0011-pro-rating-quantisation-point.md)). Tests: [`test_money.py`](tests/unit/domain/money/test_money.py), [`test_rounding.py`](tests/unit/domain/money/test_rounding.py).
- **A citation on every value.** Each value has its own citation and status, and every result reports the weakest status of what it used ([ADR-0006](docs/adr/0006-provenance-and-verification-status.md); [`test_cited_values.py`](tests/unit/domain/citations/test_cited_values.py)).
- **A pure domain.** The calculation core does no I/O and imports only the standard library and Pydantic. This is enforced by import-linter and a purity test ([ADR-0004](docs/adr/0004-declarative-tariff-components.md); [`test_domain_purity.py`](tests/unit/test_domain_purity.py)).
- **Property tests against independent references.** A bill is never negative and never falls as use rises. VAT adds up. Splitting a period changes the total by no more than the named roundings. A month of prepaid purchases costs what the month is billed ([`tests/property/`](tests/property/domain/billing/)).

## How it works

```mermaid
flowchart LR
  pdf["Official tariff schedule (PDF)<br/>committed, identified by SHA-256<br/><i>Built</i>"]:::built
  draft["Transcription<br/>a citation and status per value<br/><i>Built</i>"]:::built
  agent["Independent recalculation<br/>tariff-verifier agent<br/><i>Built</i>"]:::built
  check["Automatic citation check<br/>for PDFs with a text layer<br/><i>Planned: P2</i>"]:::planned
  human["Human check: verified<br/><i>Planned: P2 to P3</i>"]:::planned
  engine["Engine<br/>bills, period splits, prepaid<br/><i>Built</i>"]:::built
  bill["Result: each line cites document,<br/>page and printed text, with a status<br/><i>Built</i>"]:::built
  pdf --> draft --> agent --> engine --> bill
  draft -.-> check -.-> human -.-> engine
  classDef built fill:#060606,stroke:#A8A8A3,color:#FDFDFD
  classDef planned fill:#F4F4F2,stroke:#767671,stroke-dasharray:5 4,color:#52524E
```

```mermaid
flowchart TB
  api["api: REST API<br/><i>Planned: P5</i>"]:::planned
  console["console: staff console<br/><i>Planned: P6</i>"]:::planned
  mcp["mcp: MCP server<br/><i>Planned: P7</i>"]:::planned
  services["services: application use cases<br/><i>Planned: P2 · a demo entry point exists</i>"]:::planned
  persistence["persistence: versioned storage<br/><i>Planned: P2</i>"]:::planned
  provenance["provenance and catalogue<br/><i>Planned: P2</i>"]:::planned
  ingestion["ingestion: drafts, review, publish<br/><i>Planned: P2 to P3</i>"]:::planned
  billing["domain.billing<br/>bills, periods, prepaid<br/><i>Built</i>"]:::built
  tariffs["domain.tariffs<br/>components, versions, policies<br/><i>Built</i>"]:::built
  money["domain.money<br/>Decimal, rates, VAT, rounding<br/><i>Built</i>"]:::built
  base["domain.citations, domain.periods<br/><i>Built</i>"]:::built
  api --> services
  console --> services
  mcp --> services
  services --> persistence
  services --> ingestion
  services --> provenance
  services --> billing
  billing --> tariffs --> money --> base
  classDef built fill:#060606,stroke:#A8A8A3,color:#FDFDFD
  classDef planned fill:#F4F4F2,stroke:#767671,stroke-dasharray:5 4,color:#52524E
```

Arrows point at what a module may use. Solid dark modules are built; dashed light ones are planned, with the phase that builds them. Pine green is kept for what is verified or important, so it is not used for "built".

## Status

| Phase | What | Status |
| --- | --- | --- |
| P0 | Foundation: tooling, CI, hooks, decisions | Built (gate 2026-11-17) |
| P1 | Calculation core | Built (gate 2026-11-18) |
| P2 | Versioned storage, provenance, citation check, publishing | Planned (next) |
| P3 | Ekurhuleni pilot: schedules loaded, golden cases from real bills and receipts | Planned |
| P4 | Time-of-use and demand | Planned |
| P5 | REST API v1 | Planned |
| P6 | Staff console | Planned |
| P7 | MCP server for AI agents | Planned |
| P8 | More suppliers | Planned |
| P9 | Pilot validation | Planned |
| P10 | Production | Planned, only with the owner's approval of the cost |

The live tracker is [`docs/status.md`](docs/status.md); the phases and their proofs are in [`docs/roadmap.md`](docs/roadmap.md).

## How it's built

MuniSense is built by Claude Code, working under the direction of the owner, Josh Heath. The owner makes the product decisions, accepts the architecture decision records and approves each phase gate. Claude Code plans, implements, tests and documents.

Every pull request is reviewed by an independent code-review agent before it is merged. When tariff data changes, a tariff-verifier agent also recalculates each value and compares it with the source page. An agent's check never makes a value verified; that takes a person.

Pull requests are merged only when continuous integration is green. That is a working rule, not an enforced one: the free GitHub plan has no branch protection.

Mutation testing measures whether the billing engine's tests catch injected bugs. It was last run at the end of Phase 1 (90.2%), and is re-run before each phase gate that changes the engine.

The rules are in [`CLAUDE.md`](CLAUDE.md).

## Quick start

You need [uv](https://docs.astral.sh/uv/) and git. uv installs Python 3.13 and every locked dependency.

```bash
uv sync               # install the locked dependencies
uv run poe check      # lint, type-check and fast tests
uv run poe demo       # print the example bill above, from the real data and engine
```

Setting up the owner's Windows and WSL2 machine, and running the Docker-based commands, is covered in [`docs/development.md`](docs/development.md).

## Documentation

| Document | What |
| --- | --- |
| [`docs/status.md`](docs/status.md) | Current phase, tasks, decisions |
| [`docs/roadmap.md`](docs/roadmap.md) | Phases, deliverables, gates |
| [`docs/architecture/overview.md`](docs/architecture/overview.md) | Modules, dependency rules, data model |
| [`docs/adr/`](docs/adr/) | Architecture decision records |
| [`docs/brand.md`](docs/brand.md) | Design system (colour, type, glass, motion) |
| [`docs/README.md`](docs/README.md) | The full documentation map |

## Licence and data

Proprietary. All rights reserved ([`LICENSE`](LICENSE)).

- **Official documents.** The tariff schedules and other official documents in [`data/sources/`](data/sources/) belong to their publishers (the City of Ekurhuleni and the South African Revenue Service). They are kept so that every value can be cited to its page.
- **Transcriptions.** The values in [`data/drafts/`](data/drafts/) are unreviewed transcriptions, all marked `estimated`.
- **User-provided figures.** [`data/observations/`](data/observations/) holds user-provided figures only, with no personal details. These are not tariff data.

MuniSense is not affiliated with any municipality, Eskom, NERSA or SARS. Its results are calculations, not bills.
