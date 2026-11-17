# ADR-0001: Record architecture decisions

- **Status:** Accepted
- **Date:** 2026-11-17
- **Deciders:** Josh Heath (owner)

## Context

MuniSense is built by Claude Code across many sessions and reviewed in a separate architect chat. Without a written record, decisions are re-argued, forgotten or silently reversed between sessions.

## Decision

Record every significant decision as a short ADR in `docs/adr/`, numbered in sequence, using `0000-template.md`. Claude Code drafts ADRs as **Proposed** (`/adr`). Only the owner accepts them. Accepted ADRs are never edited; a new ADR supersedes them. The `guard_files.py` hook enforces this.

## Consequences

- Good: decisions and their reasons survive across sessions and chats; the architect chat can review them.
- Bad: a small writing overhead per decision.
- Cost: none.
- Reversibility: trivial.

## Alternatives considered

| Option | Why not |
| --- | --- |
| Decisions in chat history only | Lost between sessions; not visible to Claude Code |
| A wiki or project tool | Separate from the code; may cost money |
