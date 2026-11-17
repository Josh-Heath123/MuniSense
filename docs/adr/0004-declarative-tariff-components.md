# ADR-0004: Model tariffs as declarative, typed components

- **Status:** Proposed
- **Date:** 2026-11-17
- **Deciders:** Malcolm Heath (owner)

## Context

Suppliers combine a limited set of building blocks in different ways: fixed charges, flat energy, inclining blocks, seasonal and time-of-use energy, demand and capacity charges, levies, free basic allocations and export credits. Writing calculation code per municipality would not scale to more than 250 municipalities and would make every tariff change a code change. NERSA's current review may also change structures.

## Decision

- A tariff version is a header plus an **ordered list of typed components**. Each component type is a domain class with a validated payload and a `schema_version`.
- Initial component types: `FixedCharge`, `FlatEnergy`, `BlockEnergy`, `SeasonalEnergy`, `TimeOfUseEnergy`, `DemandCharge`, `CapacityCharge`, `Levy`, `FreeBasicAllocation`, `ExportCredit`. Each is built only when the phase that needs it arrives.
- The engine evaluates components generically. Supplier-specific behaviour (rounding, pro-rating, prepaid block reset) is expressed as **policies in data**, not code branches.
- A new component type requires an ADR and a schema version.

## Consequences

- Good: adding a supplier with known shapes is data entry plus verification. The P8 roadmap phase measures this claim.
- Bad: the component model must be designed carefully; a wrong abstraction is costly. Edge cases may push towards a "custom" escape hatch, which is **not** allowed without an ADR.
- Cost: R0.
- Reversibility: moderate. Component payloads are versioned, so migrations between schemas are possible.

## Alternatives considered

| Option | Why not |
| --- | --- |
| Code per supplier | Does not scale; every tariff change becomes a deployment |
| A general expression language or rules engine | Powerful but hard to validate, test and explain to customers |
| Spreadsheet-driven formulas | Untyped, hard to verify, no provenance per value |
