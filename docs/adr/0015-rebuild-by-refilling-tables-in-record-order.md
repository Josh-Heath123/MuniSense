# ADR-0015: The rebuild refills the tables in one transaction, loading publications in record order

- **Status:** Accepted. Supersedes two points of ADR-0012 section 6: "drops and recreates the schema" (in "The command") and "Within each, files load in sorted path order" together with the VAT-then-tariff order of publications (in "Load order"). Everything else in ADR-0012 stands.
- **Date:** 2026-11-20 (decided by the owner, W22 option 1, E54)
- **Deciders:** Josh Heath (owner)

## Context

Building the loader (P2-11, PR #42) showed that two points of ADR-0012 section 6 do not fit the rest of P2:

- **Dropping and recreating the schema.** The rebuild connects as the migration role, which may not create a schema (P2-3: the bootstrap creates the schema as the superuser, and only the bootstrap connects as the superuser, E51).
- **Sorted path order.** `publication.supersedes` is a foreign key to another publication, and it is not deferrable. A correction filed under an earlier date (a sorted path before its target) would name a row not yet inserted. Loading VAT publications before tariff ones changes nothing about this.

## Decision

- **The rebuild empties and refills every table in one transaction.** `uv run poe db-rebuild` applies the Alembic migrations to head (as the migration role), then, in one transaction: refuses a schema whose tables differ from the loader's list, deletes every row, loads everything, checks the loaded rows, and commits. Any error rolls the whole transaction back, so a failed rebuild leaves the previous contents.
- **Publications load in record order:** by `published_at`, then by id. A publication is always recorded after what it supersedes (the guards refuse otherwise), so a supersede always names a row already inserted. The catalogue, the source documents, and the tariffs and customer classes still load first.
- Everything else in section 6 is unchanged: where it may run, deterministic keys, `recorded_during` from successors and withdrawals, checks at load, and nothing else writes the database.

## Consequences

- Good: the migration role needs no extra privilege, and a failed rebuild keeps the previous contents.
- Good: the load order follows the data's own dependency, so no constraint needs to be deferred.
- **A rebuild does not reset schema drift.** It assumes the database is at the migration head with exactly the loader's tables. A missing or extra table is refused; other drift (columns, constraints, indexes) is not detected. In particular, **a migration edited after it was applied locally is not reset by `db-rebuild`:** run `uv run alembic downgrade base` first (`docs/development.md`). Migrations already on `main` may not be edited (the file guard), so this concerns local work in progress.

## Alternatives considered

| Option | Why not |
| --- | --- |
| Before every load, `alembic downgrade base` then `upgrade head` as the migration role (W22 option 2) | It would reset drift. PostgreSQL rolls back `DROP TABLE` and `CREATE TABLE` inside a transaction, so it could be made all-or-nothing with the load. Rejected for the added complexity (running the migrations inside the load's transaction) on a projection that is disposable and rebuilt from the files at any time, not because a failed load would have to leave an empty database |
| Give the migration role `CREATE` on the database, to follow ADR-0012's wording (W22 option 3) | More privilege for the role that runs on every rebuild, for no gain on content |
| Deferrable foreign keys, to keep sorted path order | Weakens the schema for every writer to suit one load order; record order is natural and already guaranteed by the guards |
