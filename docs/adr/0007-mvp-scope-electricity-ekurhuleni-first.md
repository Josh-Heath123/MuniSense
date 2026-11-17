# ADR-0007: MVP scope is electricity, with Ekurhuleni as the pilot

- **Status:** Accepted
- **Date:** 2026-11-17 (proposed); 2026-11-17 (accepted by the owner)
- **Deciders:** Josh Heath (owner)

## Context

The brief covers electricity, water, sanitation and property rates for residential and commercial customers. Doing all of it at once would delay any proof of accuracy. Electricity has the most complex tariffs and the clearest early buyers (solar installers, energy consultants, property managers). The owner lives in Ekurhuleni and can supply real bills there.

## Decision

- **Scope:** electricity for residential and small-business customers, for both credit and prepaid meters. For prepaid meters this includes the **prepaid purchase calculation**: the kWh received for a rand amount, given earlier purchases in the same month (built in P1). The data model allows water, sanitation, refuse and property rates, but they are built after the MVP.
- **Pilot supplier:** City of Ekurhuleni (P3). Then, in P8: Eskom-direct, City Power, City of Cape Town, City of Tshwane, eThekwini and Nelson Mandela Bay, in an order the owner chooses.
- **Interfaces:** REST API (P5), staff curation console with a **staff-only** calculator behind the console login (P6), MCP server as the last MVP build step (P7). Whether to offer a public calculator is decided at P9, together with the legal opinion.
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
| A public calculator in the MVP | Brings abuse handling and possible liability for figures shown to consumers, without serving the business buyers |
| Start with Eskom-direct | Fewer pilot bills available to the owner; municipal complexity is the real moat |
