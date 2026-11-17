# ADR-0007: MVP scope is electricity, with Ekurhuleni as the pilot

- **Status:** Proposed
- **Date:** 2026-11-17
- **Deciders:** Malcolm Heath (owner)

## Context

The brief covers electricity, water, sanitation and property rates for residential and commercial customers. Doing all of it at once would delay any proof of accuracy. Electricity has the most complex tariffs and the clearest early buyers (solar installers, energy consultants, property managers). The owner lives in Ekurhuleni and can supply real bills there.

## Decision

- **Scope:** electricity for residential and small-business customers. The data model allows water, sanitation, refuse and property rates, but they are built after the MVP.
- **Pilot supplier:** City of Ekurhuleni (P4). Then, in P8: Eskom-direct, City Power, City of Cape Town, City of Tshwane, eThekwini and Nelson Mandela Bay, in an order the owner chooses.
- **Interfaces:** REST API (P5), staff curation console and a simple public calculator (P6), MCP server as the last MVP build step (P7).
- **History:** from the 2025/26 tariff year onward.

## Consequences

- Good: the hardest case is proven first, on bills the owner can supply; early value for the clearest buyers.
- Bad: buyers who need water or rates must wait; the scope must be revisited after buyer interviews.
- Cost: R0.
- Reversibility: easy. Scope can widen after any gate.

## Alternatives considered

| Option | Why not |
| --- | --- |
| All services at once | Delays the first proof of accuracy by months |
| Metros only, quick prototype (the earlier research plan) | Faster to show, but the brief asks for a foundation that will not need rewriting |
| Start with Eskom-direct | Fewer pilot bills available to the owner; municipal complexity is the real moat |
