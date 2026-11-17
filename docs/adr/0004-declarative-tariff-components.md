# ADR-0004: Model tariffs as declarative, typed components

- **Status:** Accepted
- **Date:** 2026-11-17 (proposed); 2026-11-17 (accepted by the owner)
- **Deciders:** Josh Heath (owner)

## Context

Suppliers combine a limited set of building blocks in different ways: fixed charges, flat energy, inclining blocks, seasonal and time-of-use energy, demand and capacity charges, levies, free basic allocations and export credits. Writing calculation code per municipality would not scale to more than 250 municipalities and would make every tariff change a code change. NERSA's current review may also change structures.

## Decision

- A tariff version is a header plus an **ordered list of typed components**. Each component type is a domain class with a validated payload and a `schema_version`.
- Initial component types: `FixedCharge`, `FlatEnergy`, `BlockEnergy`, `SeasonalEnergy`, `TimeOfUseEnergy`, `DemandCharge`, `CapacityCharge`, `Levy`, `FreeBasicAllocation`, `ExportCredit`. Each is built only when the phase that needs it arrives (time-of-use, demand, capacity and export credits in P4).
- **Every value inside a payload carries its own citation reference and verification status** (ADR-0006). A component's status is a summary: the weakest status of its values.
- The engine evaluates components generically. Supplier-specific behaviour (rounding, pro-rating, prepaid block reset) is expressed as **policies in data**, not code branches.
- **Consumption input is a profile type**, designed now so that time-of-use does not force a redesign later: a monthly kWh total, kWh per time-of-use bucket, or (later) interval data. P1 builds the total only; the time-of-use evaluation is built in P4.
- The engine supports two directions: **forward** (consumption to cost) and **prepaid purchase** (a rand amount to kWh, given earlier purchases in the same month). Both use the same components and policies.
- **Pydantic v2 is allowed inside the domain**, for component payloads and value objects, in **strict mode only**. Money and rate fields use a Decimal type that rejects `float` input. A test proves that a float is rejected. Pydantic does no I/O, so the domain stays pure.
- A new component type requires an ADR and a schema version.

## Consequences

- Good: adding a supplier with known shapes is data entry plus verification. The P8 roadmap phase measures this claim. One schema can serve JSONB validation and tariff files, with JSON Schema available for free. Whether the API reuses domain models or has its own schemas is decided in P5.
- Bad: the component model must be designed carefully; a wrong abstraction is costly. Edge cases may push towards a "custom" escape hatch, which is **not** allowed without an ADR. The domain depends on a third-party library; Pydantic's lax mode silently converts floats, so strict mode is essential and is tested.
- Cost: R0.
- Reversibility: moderate. Component payloads are versioned, so migrations between schemas are possible.

## Alternatives considered

| Option | Why not |
| --- | --- |
| Code per supplier | Does not scale; every tariff change becomes a deployment |
| A general expression language or rules engine | Powerful but hard to validate, test and explain to customers |
| Spreadsheet-driven formulas | Untyped, hard to verify, no provenance per value |
| Plain frozen dataclasses in the domain, Pydantic only at the edges | Two parallel schemas (domain and boundary) to keep in step, with hand-written validation |
| Pydantic in lax (default) mode | Silently converts floats to Decimal, which breaks the money rule |
