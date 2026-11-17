# ADR-0009: Server-rendered console and calculator with Jinja2 and HTMX

- **Status:** Proposed
- **Date:** 2026-11-17
- **Deciders:** Malcolm Heath (owner)

## Context

The MVP needs a staff console (review queue, version comparison, publish) and a simple public calculator page. Both are small. The API is the product; the pages exist to load data safely and to demonstrate it.

## Decision

Render HTML on the server with Jinja2 templates inside the same FastAPI application, adding interactivity with HTMX. Console logins use argon2 password hashes, secure cookies and CSRF protection. No JavaScript build chain.

## Consequences

- Good: one codebase, one language, one deployment; pages call the same services as the API.
- Bad: less suited to a rich, app-like interface. If a full customer portal is needed later, revisit.
- Cost: R0.
- Reversibility: moderate. The pages can be replaced by a separate front end calling the API.

## Alternatives considered

| Option | Why not |
| --- | --- |
| React or Next.js single-page app | A second codebase and build chain for no MVP benefit |
| FastAPI admin libraries | Pull towards CRUD on tables rather than a review-and-publish workflow |
