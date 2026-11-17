# Product requirements: MuniSense MVP

_Status: decisions D1 to D3, E2 and E5 approved by the owner on 2026-11-17 (`status.md`); this text is approved when the owner merges the `docs/accept-decisions` pull request._

## Problem

South Africa has more than 250 municipalities, plus Eskom as a direct supplier. Each publishes its own tariffs every year for the services it provides (electricity, water, sanitation, refuse, property rates), in PDF schedules with different structures: inclining blocks, flat rates, seasonal and time-of-use prices, fixed and capacity charges, levies, free basic allocations and VAT rules. Tariffs change every 1 July (Eskom's change on 1 April) and are sometimes changed retroactively.

Businesses that need to know "what will this cost at this address", such as solar installers, energy consultants, property managers recovering utilities from tenants and finance teams assessing solar loans, re-key these schedules by hand or guess. AI agents have no reliable, citable source at all.

## Product

A trusted service that calculates municipal utility bills exactly. Every number traces back to the official document, page and effective date it came from. It is delivered as an API for software and an MCP server for AI agents, with a curation console behind it.

## Users and buyers

| Who | Need | MVP interface |
| --- | --- | --- |
| Solar installers and solar software | Before-and-after bills, and export-credit value, for proposals | API |
| Energy consultants | Tariff comparisons and audit-ready figures | API |
| Property managers | Correct utility recovery from tenants | API |
| Solar-finance teams | Savings estimates they can defend | API |
| AI agents acting for any of these | A citable answer with provenance | MCP server (P7) |
| MuniSense staff (the owner, initially) | Load, check, correct and publish tariffs safely; run calculations for demos | Console, staff-only calculator |

Buyer interviews (the owner's parallel track) will confirm or change this table before P5.

## MVP scope

**In:** electricity for residential and small-business customers of the pilot suppliers (Ekurhuleni first, then Eskom-direct and five metros in P8). Prepaid and credit meters, including the prepaid purchase calculation (rand amount to kWh, given earlier purchases in the same month); single- and three-phase supply; block, flat, seasonal and time-of-use tariffs; fixed and capacity charges; free basic electricity; VAT; small-scale embedded generation export credits where published. Historical tariffs from 2025/26 onward. REST API, staff console with a staff-only calculator, MCP server.

**Out of the MVP (modelled so they can be added later):** water, sanitation, refuse and property rates; large-power-user and industrial tariffs; address-to-supplier lookup beyond a basic list; user accounts for the public; payments; hosting; a public calculator (decided at P9, with the legal opinion).

## Functional requirements

1. Store versioned electricity tariffs. Each value is linked to its source document, page and verification status.
2. Calculate a bill for a period, supplier, tariff, meter type, phase and consumption (and time-of-use profile where needed). Return line items, VAT, total, assumptions and warnings.
3. Split periods that straddle a tariff change or season boundary, and report how the split was made.
4. For a prepaid meter, calculate the kWh received for a rand amount, given earlier purchases in the same month, and show how the kWh fall across the blocks.
5. Compare two or more tariffs for the same consumption, including solar export where the tariff allows it.
6. Answer "as recorded on date X", reproducing any past answer exactly.
7. Never return a number without its provenance and status. Refuse or warn rather than guess when data is missing or estimated.
8. Provide a staff review-and-publish workflow with states draft, checked and published.
9. Expose these through a versioned REST API and, at the end of the MVP, an MCP server.

## Quality requirements

- **Accuracy:** golden bills match to the cent, or each difference is explained. Accuracy is measured and published internally per supplier.
- **Traceability:** every published value has a citation and a status; every change is recorded.
- **Privacy:** no personal information is stored in the MVP.
- **Cost:** R0 until the Phase 9 spending decision.
- **Maintainability:** adding a supplier with known tariff shapes needs data, not code.

## Success measures for the validated MVP (end of P9)

- At least 10 real Ekurhuleni golden cases reproduced (P3). A prepaid golden case is a whole month of purchases, which matches when, given each purchase's rand amount and the month's earlier purchases, the computed kWh equals the receipt's kWh at the printed precision.
- Golden bills passing for every pilot supplier (P8).
- Pilot users confirm accuracy on their own bills.
- An intent-to-pay pass mark, agreed with the owner before P9, is met.

## Open questions

See `domain/sa-tariffs.md`, under open questions, and the decisions waiting for the owner in `status.md`.
