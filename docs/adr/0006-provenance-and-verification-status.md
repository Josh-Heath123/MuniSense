# ADR-0006: Every value carries provenance and a verification status

- **Status:** Accepted. The first condition for `verified` (the deterministic text check), for citations of drawn items listed in a source manifest only: Superseded by ADR-0016 (point 5, the `drawn` outcome with the owner's visual check); everything else in this ADR stands.
- **Date:** 2026-11-17 (proposed); 2026-11-17 (accepted by the owner)
- **Deciders:** Josh Heath (owner)

## Context

MuniSense's value is trust: a customer, or an AI agent, must be able to see where a number came from and how sure we are. The owner's brief forbids silently inventing values and requires distinguishing verified, estimated and user-provided data, traceable to sources with effective dates and history. Municipal documents are messy, and some values will be uncertain.

## Decision

- Use **official sources only**: municipal tariff schedules and budget annexures (published under MFMA s75), Eskom tariff books, NERSA decisions. Secondary sources may guide research but never become data.
- Each source document is recorded with URL, retrieval date, SHA-256 and approval reference. **The source documents themselves are committed to the repository** (under `data/sources/`), so they are backed up and CI can check citations against them.
- **Each value** has its own **citation** (document, page, table or row, original printed text). This holds inside a component too: a block tariff's thresholds and rates each carry their own citation and status (ADR-0004).
- Each value has a **verification status**: `verified`, `estimated` (with a written reason) or `user_provided` (with who provided it).
- **`verified` requires both:**
  1. a deterministic check that the value's original printed text appears verbatim in the extracted text of the cited page, where the PDF has a text layer; and
  2. a recorded verifier identity, method and date.
  The first tariff per supplier also needs the owner's check. A page without a text layer (a scan) cannot reach `verified` without a human check. A check by a Claude subagent alone is not enough, because its errors are not independent of the transcriber's.
- Only **published** tariff versions are used in calculations. Every result shows the status of every line, and results that rely on `estimated` values carry a warning.
- Commercial use requires a South African legal opinion on reusing tariff documents before charging money (Phase 9).

## Consequences

- Good: answers are auditable; uncertainty is visible instead of hidden; this is the moat.
- Bad: loading data is slower because every value needs a citation and a check.
- Cost: R0 now; legal opinion fees before charging (amount unknown).
- Reversibility: dropping provenance later would be easy but would destroy the product's value.

## Alternatives considered

| Option | Why not |
| --- | --- |
| Use aggregator data (for example comparison sites) | Not authoritative; possible copyright and terms issues; errors inherited |
| Provenance per tariff rather than per value | Too coarse to explain a single disputed line |
| No status labels | Hides uncertainty, which the brief explicitly forbids |
