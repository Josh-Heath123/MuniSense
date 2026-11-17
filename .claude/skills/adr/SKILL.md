---
name: adr
description: Draft a new architecture decision record with status Proposed, for the owner to approve.
argument-hint: "<short title>"
disable-model-invocation: true
---

# /adr

1. Find the next free number in `docs/adr/` and create `docs/adr/NNNN-<slug-of-title>.md` from `docs/adr/0000-template.md`. Use title `$ARGUMENTS`, status **Proposed** and today's date.
2. Fill in every section honestly:
   - Context: the problem and its constraints, with links to evidence.
   - Decision: what you propose.
   - Consequences: good and bad, including cost now and later, and how hard it is to reverse.
   - Alternatives: at least two real options, and why they lose.
3. If this supersedes an earlier ADR, say which one. Mark the earlier one "Superseded by ADR-NNNN" only after the owner accepts the new one.
4. Add the decision to "Waiting for the owner" in `docs/status.md`.
5. Never mark an ADR Accepted yourself. Only do so after the owner approves it in the conversation, and record the date of approval.
