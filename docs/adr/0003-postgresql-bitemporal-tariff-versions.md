# ADR-0003: Store tariffs in PostgreSQL with two timelines

- **Status:** Accepted
- **Date:** 2026-11-17 (proposed); 2026-11-17 (accepted by the owner)
- **Deciders:** Josh Heath (owner)

## Context

Tariffs change every year (1 July for municipalities, 1 April for Eskom), are amended mid-year, and are sometimes changed retroactively. Nelson Mandela Bay was ordered in August 2026 to restore its 2026/27 block tariff from 1 July 2026. Customers will ask both "what is the price for this period?" and "what did MuniSense tell me on 3 August?". Both must have exact, reproducible answers.

Published tariff data must also survive the loss of one laptop. Until P10 there is no managed database and no backup service, and a local Docker volume can be deleted by one mistaken command.

## Decision

- **Source of truth through P9: committed, reviewed tariff files.** Published tariff versions are files in the repository, reviewed through pull requests. The database is a **deterministic projection** of those files: it can be dropped and rebuilt from them at any time, with identical results. The storage ADR, written at the start of P2, decides the file format, layout and loader.
- **Record time is written explicitly into the file by the publish step.** It is never derived from git history (commit dates, merge times), which can be rewritten or differ from the moment of publication.
- PostgreSQL 17, run locally in Docker Compose and in CI as a service container.
- SQLAlchemy 2 for data access and Alembic for migrations (only the `persistence` module uses them).
- Tariff versions carry **valid time** (`valid_period`, a `daterange`) and **record time** (`recorded_during`, a `tstzrange` from the moment of publication until the moment of being superseded; open-ended while current).
- **Record time starts at publication.** Drafts and checked versions are not part of the two-timeline data. They live in the ingestion area (draft files) and enter the published table only when published. Published rows are append-only: a correction is a new version with `supersedes_id`, and the only change to an existing published row is closing its `recorded_during` range when it is superseded.
- **Every past snapshot is free of overlaps.** A PostgreSQL exclusion constraint on (tariff, `valid_period`, `recorded_during`) rejects any two published versions of the same tariff whose valid periods and record periods both overlap. This needs the `btree_gist` extension.
- Component payloads are JSONB, validated by the domain model before saving (ADR-0004).

## Consequences

- Good: any past answer can be reproduced; corrections never destroy history; the database itself enforces integrity, including for "as recorded on" queries in the past. Git and pull requests provide backup, history and review of tariff data at no cost. The database is disposable.
- Bad: queries are more complex ("as of" filters everywhere), so they live in repositories with tests. There are two representations (files and database) to keep in step, so the loader needs round-trip tests. The P6 console "publish" step must produce a tariff file rather than only a database row.
- Cost: R0 locally. Managed PostgreSQL in production costs money (Phase 9 decision).
- Reversibility: hard to reverse once data exists. That is why this is decided now. Moving the source of truth from files to the database after P9 is planned to be a separate decision.

## Alternatives considered

| Option | Why not |
| --- | --- |
| SQLite | No range types or exclusion constraints; weak concurrency for a server |
| MongoDB | Weak relational integrity for suppliers, versions and citations |
| Latest-value-only tables | Cannot reproduce past answers or survive retroactive changes |
| Event sourcing | More machinery than needed; append-only versions give the same audit benefit |
| Database as the only source of truth | Published data and its history would live only in one Docker volume on one laptop until P10 |
| Record time as two columns (`recorded_at`, `superseded_at`) with a constraint on current rows only | A past "as recorded on" query is not protected against overlapping versions |
| Record time taken from git commit dates | Not under the publish step's control; history can be rewritten or merged later than publication |
| PostgreSQL 18 | Stable, but nothing here needs it. Its `WITHOUT OVERLAPS` keys do not cover the "published only" constraint we need, so the exclusion constraint stays either way |
