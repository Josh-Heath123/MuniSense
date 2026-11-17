# ADR-0003: Store tariffs in PostgreSQL with two timelines

- **Status:** Proposed
- **Date:** 2026-11-17
- **Deciders:** Malcolm Heath (owner)

## Context

Tariffs change every year (1 July for municipalities, 1 April for Eskom), are amended mid-year, and are sometimes changed retroactively. Nelson Mandela Bay was ordered in August 2026 to restore its 2026/27 block tariff from 1 July 2026. Customers will ask both "what is the price for this period?" and "what did MuniSense tell me on 3 August?". Both must have exact, reproducible answers.

## Decision

- PostgreSQL 17, run locally in Docker Compose and in CI as a service container.
- SQLAlchemy 2 for data access and Alembic for migrations (only the `persistence` module uses them).
- Tariff versions carry **valid time** (`valid_period`, a `daterange`) and **record time** (`recorded_at`, `superseded_at`). Rows are append-only; a correction is a new version with `supersedes_id`.
- A PostgreSQL exclusion constraint prevents overlapping published validity periods for the same tariff among current records.
- Component payloads are JSONB, validated by the domain model before saving (ADR-0004).

## Consequences

- Good: any past answer can be reproduced; corrections never destroy history; the database itself enforces integrity.
- Bad: queries are more complex ("as of" filters everywhere), so they live in repositories with tests.
- Cost: R0 locally. Managed PostgreSQL in production costs money (Phase 9 decision).
- Reversibility: hard to reverse once data exists. That is why this is decided now.

## Alternatives considered

| Option | Why not |
| --- | --- |
| SQLite | No range types or exclusion constraints; weak concurrency for a server |
| MongoDB | Weak relational integrity for suppliers, versions and citations |
| Latest-value-only tables | Cannot reproduce past answers or survive retroactive changes |
| Event sourcing | More machinery than needed; append-only versions give the same audit benefit |
