# ADR-0002: Build a Python modular monolith with FastAPI

- **Status:** Proposed
- **Date:** 2026-11-17
- **Deciders:** Malcolm Heath (owner)

## Context

One developer (Claude Code, directed by the owner) builds a service with a calculation core, a REST API, a staff console, a public calculator and later an MCP server. The work involves heavy document and data handling (PDF tariff schedules). Everything must be free to develop and run locally, and must not need rewriting when it becomes commercial.

## Decision

- One Python 3.13 application in one repository, structured as modules with enforced boundaries (see `architecture/overview.md`).
- FastAPI with Pydantic v2 for the API; Jinja2 + HTMX for HTML pages (ADR-0009).
- uv for Python versions, dependencies and the lockfile; poethepoet for task commands.
- A pure domain core with no I/O; interfaces call application services only. import-linter enforces this in CI.

## Consequences

- Good: one deployable unit, one test suite, simple local development. Strong libraries for PDFs and data. OpenAPI generated from code.
- Bad: Python is slower than compiled languages, which is irrelevant at MVP scale. Module discipline depends on import-linter staying in CI.
- Cost: R0.
- Reversibility: modules can be extracted into services later if load or team size demands it.

## Alternatives considered

| Option | Why not |
| --- | --- |
| Microservices | Operational overhead with no benefit for one developer |
| TypeScript/Node (NestJS) | Weaker for PDF and data work; two ecosystems if Python is needed for extraction anyway |
| Django + DRF | Heavier; its ORM and admin pull towards CRUD rather than a pure domain core |
| Flask | Less built-in typing and validation; more assembly required |
