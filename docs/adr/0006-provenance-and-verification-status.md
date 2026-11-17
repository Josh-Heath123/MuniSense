# ADR-0006: Every value carries provenance and a verification status

- **Status:** Proposed
- **Date:** 2026-11-17
- **Deciders:** Malcolm Heath (owner)

## Context

MuniSense's value is trust: a customer, or an AI agent, must be able to see where a number came from and how sure we are. The owner's brief forbids silently inventing values and requires distinguishing verified, estimated and user-provided data, traceable to sources with effective dates and history. Municipal documents are messy, and some values will be uncertain.

## Decision

- Use **official sources only**: municipal tariff schedules and budget annexures (published under MFMA s75), Eskom tariff books, NERSA decisions. Secondary sources may guide research but never become data.
- Each source document is recorded with URL, retrieval date, SHA-256 and approval reference. Each value has a **citation** (document, page, table or row, original printed text).
- Each value has a **verification status**: `verified` (matched to the source by the verifier), `estimated` (with a written reason) or `user_provided` (with who provided it).
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
