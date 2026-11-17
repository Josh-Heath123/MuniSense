# ADR-0005: Use Decimal money and explicit, per-supplier rounding policies

- **Status:** Proposed
- **Date:** 2026-11-17
- **Deciders:** Malcolm Heath (owner)

## Context

The product promise is "matches your bill to the cent". Binary floating point cannot represent most cent values exactly. Suppliers quote rates in different units (c/kWh, R/kWh, R/day, R/month) and round differently, and their rounding rules are not published reliably. They must be learned from real bills.

## Decision

- All money and rate arithmetic uses Python `Decimal`, constructed from strings. `float` is banned in money, tariff and billing code (enforced by review and a lint rule where possible).
- Each rate stores its **original printed value and unit** and a **canonical value**.
- Quantisation happens only at defined points (line items, totals) under a named `RoundingPolicy` per supplier: granularity, rounding mode, and whether rounding is per line or per bill.
- A rounding policy not yet confirmed from real bills has status `estimated`, and every result using it carries a warning.
- The VAT rate comes from a dated table, never a constant.

## Consequences

- Good: exact, explainable results; differences from real bills can be traced to a specific rule.
- Bad: slightly more verbose code than floats.
- Cost: R0.
- Reversibility: easy to change policies; very hard to retrofit exactness later, so it is decided now.

## Alternatives considered

| Option | Why not |
| --- | --- |
| float | Inexact; errors accumulate across lines |
| Integer cents everywhere | Rates need more precision than cents (for example 234.67 c/kWh); conversions become error-prone |
| One global rounding rule | Suppliers differ; it would guarantee mismatches |
