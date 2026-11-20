# ADR-0013: Number every publication by the next free revision under its date

- **Status:** Accepted. Supersedes ADR-0012's revision rule (section 2, "File name", and the revision sentences of sections 3 and 7) and the shape of `checks` (section 3); everything else in ADR-0012 stands.
- **Date:** 2026-11-19 (proposed and accepted by the owner at the P2 checkpoint, W18, E51)
- **Deciders:** Josh Heath (owner)

## Context

ADR-0012 numbers a publication that supersedes another as "the superseded one's revision plus one, even when it is filed under a different date", and a first publication as `r1`. Building P2-4, P2-8 and P2-9 showed three problems (W18):

- **A withdrawn version could not be restored.** ADR-0012 restores it with `supersedes: null`, which made it `r1`, but `r1` already exists under its date. P2-4 adopted a provisional reading: any revision.
- **The rule can deadlock.** A correction moved to a date where "the superseded revision plus one" already exists can never be published (`poe publish` refuses it as "already exists"; tested in P2-8).
- **A withdrawal's `checks` said nothing true.** They recorded `schema: valid`, the documents sentence and `overlap: none`, which describe a version, not a withdrawal.

## Decision

- **Every publication, of any kind, takes the next free revision number under the date it is filed under:** one more than the highest revision under that date, or `r1` if there is none. `supersedes` alone records what a publication corrects or withdraws; the revision number carries no link to it. A correction is filed under its own (possibly new) effective-from date; a withdrawal under the withdrawn version's date; a restore of a withdrawn version under its date, with `supersedes: null`.
- **No revision gaps.** Under each date of each tariff, the revisions are `r1` to `rN` with none missing. The publication guards refuse a gap (P2-9's check, extended).
- **A withdrawal records what was checked for a withdrawal.** Every `checks` object now starts with `kind`, which says which shape it is. A withdrawal's `checks` are `kind: "withdrawal"`, the tool label and `withdrawn: "exists and is current"` (the withdrawn publication exists, is not itself a withdrawal and has no successor). A version's `checks` are `kind: "version"` followed by ADR-0012 section 3's fields (tool label, `schema`, `documents`, `overlap`, `citation_check`). Each envelope refuses the other kind. Changed under `schema_version` 1: nothing is published yet, so no converter is needed. The `kind` key and the literal `exists and is current` are implementation details chosen when this was built (W18 follow-up), not part of the owner's specification.

## Consequences

- Good: a restore and a moved correction can always be published; the deadlock is gone; every revision number is predictable from the folder alone; a withdrawal's record is true.
- Bad: the revision number no longer shows what a publication supersedes; readers follow `supersedes`. A correction that forgot `supersedes` is caught only by the overlap refusal (as under P2-4's provisional reading).
- Cost: R0.
- Reversibility: easy until the first publication; after that, numbering rules can only be extended, because published files never change.

## Alternatives considered

| Option | Why not |
| --- | --- |
| Keep "superseded revision plus one" and refuse the collision | Leaves a correction that can never be published |
| Restore by superseding the withdrawal | ADR-0012 refuses superseding a withdrawal; a chain through a withdrawal is harder to read |
| Global revision numbers per tariff (not per date) | Breaks lookup by date and path; needs a counter across dates |
