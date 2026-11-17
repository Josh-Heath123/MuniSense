# Roadmap to a validated MVP

The MVP is **validated** at the end of Phase 9, when pilot users have checked MuniSense against their own bills and said whether they would pay. Phase 10 is production and starts only if the owner approves the cost. **Nothing in phases 0 to 8 costs money.**

Each phase ends at a **gate**. Claude Code runs `/report gate`, the owner takes the report to the architect chat for review, and the owner approves the next phase.

| Phase | Objective and deliverables | Proven by | Gate |
| --- | --- | --- | --- |
| **P0 Foundation** | Working, checked environment and agreed decisions. Project skeleton with locked dev dependencies, PostgreSQL in Docker, pre-commit, CI. ADRs 0002 to 0010 accepted or amended. No application code | `uv run poe verify` and CI pass on a placeholder test; `uv run poe audit` runs in CI; every hook shown working inside WSL; database reachable | Owner approves the decision log |
| **P1 Calculation core** | Money types (Decimal, units, VAT table, rounding policies with named quantisation points). Tariff components: fixed charge, flat energy, inclining block, seasonal energy, free basic allocation, levy. Consumption input designed as a profile type (monthly total built now; time-of-use buckets later). Engine for a billing period, with line items that reference their sources. **Seasons and period splitting** across a tariff change or season boundary. **Prepaid purchase calculation:** the kWh received for a rand amount, given earlier purchases in the same month. Pydantic v2 in the domain in strict mode | Property tests (a bill is never negative; a block bill never falls as use rises; VAT adds up; splitting a period changes the total by no more than rounding). Hand-checked prepaid examples, including a purchase that crosses a block threshold and a month made of several purchases. A test proving floats are rejected. 95% branch coverage on the engine; mutation score of at least 80%. Figures from the Ekurhuleni 2026/27 electricity schedule reproduced in hand-checked examples. The schedule is downloaded in P1 from the official municipal website only, committed under `data/sources/`, and cited (document, page, SHA-256) | Reviewers clean; examples match to the cent |
| **P2 Versioned storage** | **Storage ADR written at the start of the phase.** Committed, reviewed tariff files as the source of truth; the database rebuilt from them deterministically. Database schema and migrations. Tariff versions with two timelines (record time written into the file by the publish step) and a two-dimensional overlap constraint. Source documents, per-value citations, verification status. "As recorded on" queries. Draft, checked and published states | Migrations upgrade and downgrade; constraints reject overlaps, including in past snapshots; rebuilding the database twice from the same files gives identical results; P1 examples survive a file-to-database round trip | Reviewers clean |
| **P3 Ekurhuleni pilot** | The 2026/27 Ekurhuleni electricity schedule loaded with page citations. Rounding, pro-rating and prepaid rules derived from the owner's real bills and prepaid receipts. `/add-tariff` proven end to end | At least 10 real golden cases (anonymised) reproduced to the cent, or each difference explained and logged. **A prepaid golden case is a whole month of purchases**, not a single receipt. Every value verified against its source | **Owner confirms the bills match.** First real evidence of accuracy |
| **P4 Time-of-use and demand** | Time-of-use calendars (day types, public holidays). Time-of-use energy, demand, capacity and export-credit components. Time-of-use consumption profiles evaluated | Eskom Homeflex examples from the rate card. Property tests carried over from P1 hold for the new components | As P1 |
| **P5 REST API v1** | Calculate, compare, list suppliers and tariffs, show sources. Hashed API keys, rate limits, RFC 9457 errors, usage counting. OpenAPI published | Contract tests from the spec; authentication tests; security review | Owner calls it with own examples |
| **P6 Staff console** | Login, review queue, side-by-side version comparison, publish (writes the reviewed tariff file with its record time; ADR-0003). Staff-only calculator behind the login, using the same services | End-to-end tests of review and publish; security review; owner walkthrough | Owner can publish a correction unaided |
| **P7 MCP server** | MCP tools for calculate, compare and lookup, returning provenance with every answer. Local first | Tool contract tests. Agent evaluation: bill questions answered with and without the tool, scored against golden answers | The tool measurably improves accuracy |
| **P8 More suppliers** | Eskom-direct (tariff year starts 1 April), City Power, Cape Town, Tshwane, eThekwini, Nelson Mandela Bay. Data only; a new component type needs an ADR | Golden bills per supplier. Code changes per supplier reported, testing the "data, not code" claim | Owner chooses the order |
| **P9 Pilot validation** | Three to five pilot users (for example property managers or solar installers) via demos or local installs. Legal opinion. POPIA plan. Hosting options with prices. Production checklist | Accuracy on pilot users' bills; documented feedback; an intent-to-pay pass mark agreed with the owner beforehand | **First spending decision:** go, change course or stop |
| **P10 Production** | Hosting, managed database with backups, domain, monitoring, payments, terms of service, privacy notice, information officer registration | Tested deployment runbook; backup restored successfully; security review; legal sign-off | Outside the MVP; only after the owner's approval |

## Dependencies

- P1 and P2 run in sequence.
- P3 needs P2 and the owner's real bills.
- P4 follows P3. It must finish before Eskom-direct or any other time-of-use tariff is loaded in P8.
- P5 may start against test data while P3 waits for bills, but cannot finish until P3 passes.
- P6 and P7 build on P5's services. P8 reuses P3's workflow. P9 needs at least P5 and P6.
- A public calculator is not in the MVP. It is decided at P9 with the legal opinion.

## The owner's parallel track

| When | What |
| --- | --- |
| P0 | Approve decisions D1 to D10 |
| P1 to P3 | Run 10 buyer interviews. Choose MVP customer classes. Supply at least 10 real golden cases: prepaid purchase receipts grouped by whole month (and any municipal bills) |
| P5 to P8 | Set the pricing to test. Try the API and console. Choose the order of the next suppliers |
| P9 | Recruit pilot users. Commission a legal opinion. Approve spending, or stop |

## How every phase runs

1. `/next` breaks the phase into small tasks with acceptance criteria in `status.md`, and the owner approves the list.
2. Each task follows the same loop: branch, tests, code, `/verify`, `/review`, pull request, green CI, merge.
3. `/report gate` at the end, then stop. Every gate report states how long `uv run poe check` takes.
