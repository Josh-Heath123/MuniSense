# ADR-0008: The MVP stores no personal information

- **Status:** Proposed
- **Date:** 2026-11-17
- **Deciders:** Malcolm Heath (owner)

## Context

POPIA defines personal information broadly. It includes addresses, location information, identifying numbers and information about juristic persons (companies). A bill calculation linked to an address and a customer would be personal information. Storing it brings duties: lawful basis, security safeguards, an information officer, breach notification and more. Legal compliance cannot be claimed from technical controls alone.

## Decision

- Calculations are **stateless**: inputs are processed and discarded, not stored.
- Logs record request metadata only: never bodies, addresses or account numbers.
- Real bills used as test data are **anonymised to figures only** before entering the repository. Originals stay in git-ignored `data/private/` on the owner's machine.
- P5 API keys for pilot organisations are stored as hashes. Contact details for those organisations are the first personal information MuniSense will hold. Before P5, the owner decides what is stored and the POPIA register is updated.
- Formal POPIA steps (information officer registration, PAIA manual, privacy notice, operator agreements) are listed in `security/security-and-privacy.md` and done before production (P9 and P10).

## Consequences

- Good: minimal legal exposure during development; simpler security.
- Bad: no saved calculations, user history or address-based personalisation in the MVP.
- Cost: R0.
- Reversibility: easy to start storing data later, but it would trigger the full set of POPIA duties at that point.

## Alternatives considered

| Option | Why not |
| --- | --- |
| Store requests for analytics | Creates personal information with no MVP benefit |
| Public user accounts in the MVP | Personal information, authentication and support burden before value is proven |
