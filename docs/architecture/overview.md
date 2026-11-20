# Architecture overview

_Status: binding. Decided in ADR-0002 to ADR-0013, accepted by the owner on 2026-11-17 (ADR-0011 and ADR-0012 on 2026-11-18 and 2026-11-19, ADR-0013 on 2026-11-19)._

## Shape

MuniSense is a **modular monolith**: one Python 3.13 application, one PostgreSQL 17 database. Every interface (REST API, staff console with its staff-only calculator, MCP server) calls the same **application services**. The calculation core is pure: it receives tariff data as arguments and never touches the database, the network or the clock.

```text
  REST API (/v1)   Staff console + staff calculator   MCP server (P7)
        \                     |                          /
         +------------ application services (services/) -+
                 |                                  |
     pure domain core (domain/)          catalogue, provenance,
     money, tariffs, billing             ingestion, persistence
                                                    |
                                          PostgreSQL 17 (Docker)
```

## Package layout

```text
src/munisense/
  domain/
    base.py       DomainModel (strict, frozen, no extra fields, no schema path that accepts a float) and DomainError; every layer may import it, and it imports no layer
    periods/      DateRange (half-open [start, end))
    citations/    Citation, Cited[T] (the "cited value"), VerificationStatus (Verified, Estimated, UserProvided), weakest()
    money/        ExactDecimal, exact(), Money, Rate, RateUnit, CanonicalUnit, VatRate, VatTable, Quantisation, RoundingPolicy (Decimal only)
    tariffs/      TariffVersion (header + ordered components; PriceBasis), FixedCharge, FlatEnergy, BlockEnergy, SeasonalEnergy (Season, SeasonDates), Levy, FreeBasicAllocation, VatTreatment, BillingPolicy; later TOU calendars
    billing/      calculate_bill() -> Bill (LineItem with Sources by role, BillWarning); calculate_period() -> PeriodBill (split at months, versions, seasons and VAT changes; ADR-0011); ConsumptionProfile (PeriodTotal; TimeOfUseBuckets refused until P4), BillingPeriod; calculate_purchase() / calculate_month() -> Purchase (prepaid, P1-14)
  catalogue/      suppliers (SupplierCatalogue, suppliers.py, P2-6), customer classes, supply areas
  provenance/     canonical JSON (canonical.py) and the publication envelope: PublicationRecord, TariffPublication, VatRatePublication, withdrawals (publication.py, ADR-0012, ADR-0013, P2-4); source manifests (SourceManifest, sources.py) and reading and writing data files in canonical form (drafts.py, P2-6). The per-value Citation and status types live in domain/citations, because the domain may not import this package
  ingestion/      the citation check (citation_check.py; P2-7), whose PDF text extraction runs in a
                  separate, resource-limited `python -I` process (pdf_text.py, stdlib and pypdf only);
                  the publish step (publish.py, `poe publish`; P2-8) and the publication guards
                  CI runs (guards.py, `poe publications-check`; P2-9); later the review workflow
  persistence/    Alembic migrations, the loader (`poe db-rebuild`; it reuses ingestion's
                  publication guards, and ingestion never imports persistence), the
                  read-only repository ("as recorded on" queries, P2-12)
  services/       use cases: calculate_bill, compare_tariffs, publish_version, ... (from P2). Today only
                  demo.py: the `poe demo` entry point, which reads the published Tariff B and VAT
                  rate through the repository as currently recorded (P2-13; `persistence.connection.connect`
                  gives it a connection without importing SQLAlchemy)
  api/            FastAPI routers, schemas, auth, errors (P5)
  console/        Jinja2 + HTMX pages (P6)
  mcp/            MCP server (P7)
  platform/       settings (pydantic-settings), logging (structlog), health
tests/
  unit/  property/  integration/  contract/  golden/
  fixtures/drafts/  the three drafts as before their first publication (P2-13), test inputs only
migrations/       Alembic (P2)
data/
  catalogue/      suppliers.json: supplier codes, names, kind, cited tariff-year start month
  drafts/         bare versions in canonical form, waiting to be published (none since P2-13;
                  publishing removes the draft): <supplier>/<tariff-year>/<tariff-code>.json, and
                  vat/south-africa/<start>.json (one VAT rate per file)
  tariffs/        publications, immutable: <supplier>/<tariff-code>/<effective-from>.r<N>.json
  vat/            VAT publications, immutable: south-africa/<effective-from>.r<N>.json
  golden/         anonymised golden bills (committed)
  observations/   user-provided figures that are not tariff data (committed; figures only)
  sources/        <publisher>/sources.json (the manifest) and the source PDFs (committed;
                  identified by SHA-256), with a README of human notes per publisher
  private/        un-anonymised bills (git-ignored; never committed)
```

## Dependency rules (enforced in CI by import-linter and `tests/unit/test_domain_purity.py`)

1. `munisense.domain` imports nothing outside `munisense.domain`, an allow-list of pure standard-library modules and Pydantic v2 (strict mode only, never `pydantic.v1`; ADR-0004). It does no I/O, reads no clock and uses no randomness: `open`, `print`, `input`, `eval`, `exec`, `compile` and `__import__` are refused, and so are `now`, `today` and `utcnow`, called or passed (for example as a Pydantic `default_factory`). `zoneinfo` and `uuid` are deliberately not on the allow-list: the caller passes dates and offset-aware datetimes in, and identifiers are made outside the domain. import-linter enforces the munisense part and forbids named third-party packages (rule 1b); the test enforces the allow-list.
2. Within the domain: (`citations` | `periods`) ← `money` ← `tariffs` ← `billing` (arrows point at what may be imported). `domain/base.py` is outside the layers and may be imported by all of them.
3. `api`, `console` and `mcp` import `services` and `platform` only, never `persistence` or `ingestion` directly.
4. Only `persistence` imports SQLAlchemy, Alembic and psycopg (and Mako, which only Alembic uses).
4b. Only `ingestion` imports pypdf.
5. Nothing imports `api`, `console` or `mcp`.
6. No production code imports the test-support package `support` (`tests/support`), which is importable only under pytest and mypy.

## Data model (built in P2-10; ADR-0003, ADR-0012, ADR-0013)

The database is a deterministic projection of the committed files (ADR-0003): the loader (P2-11) rebuilds it from them and inserts final rows; nothing is ever updated, and the application role has `SELECT` only. The generated source of truth for the schema is the migration, `src/munisense/persistence/migrations/versions/0001_initial_schema.py`; this table summarises it. Everything lives in the `munisense` schema.

| Table | Purpose | Key points |
| --- | --- | --- |
| `supplier` | Municipality, municipal utility or Eskom | `code`, `name`, `kind`, `tariff_year_start_month`; `status` and `payload` (JSONB, the supplier as the model writes it, so the start month keeps its citation) |
| `customer_class` | Residential, small business, etc. | Per supplier |
| `tariff` | Stable identity of a named tariff | `supplier_code`, `tariff_code` (unique together), `customer_class_code`; the phase is part of the tariff code |
| `source_document` | A committed source document, from the source manifests | `sha256` (key), `publisher`, `file`, `title`, `url`, `retrieved_on`, `approval`, `pages`, `text_layer` |
| `publication` | Every publication, withdrawals included | `id` (equal to its place `scope/code/effective_from/r<revision>`, unique), `kind` (`tariff` or `vat`), `published_at`, `published_by`, `supersedes` (same tariff, never a withdrawal, at most one successor), `is_withdrawal` (a withdrawal supersedes something), `reason`, `checks` (JSONB) |
| `tariff_version` | Published prices for one validity period | One per publication that holds a version (never a withdrawal; a composite key ties it to a tariff publication). `valid_period` (daterange) and `recorded_during` (tstzrange: from publication until superseded or withdrawn), both non-empty, bounded below and `[lower, upper)`; `schema_version`; `status` (recomputed, the weakest of its values); `payload` (JSONB, the version as published). Exclusion constraint (`btree_gist`): no two versions of the same tariff whose `valid_period` and `recorded_during` both overlap |
| `tariff_component` | One component of a version | `position`, `name`, `kind`, `status` (recomputed), `payload` (JSONB). Every value inside a payload carries its own citation and status |
| `vat_rate` | One VAT rate per publication (ADR-0012 section 2) | Like `tariff_version`, per `country`, with the same exclusion constraint |
| `alembic_version` | The migration state | Readable by the app role (harmless) |

Not built, and why: a per-value `citation` table (deferred to P6 if needed; citations are queried inside the JSONB payloads, ADR-0012 section 4); `tou_calendar` (P4); `review_event` (not planned: human verification lives in each value's `Verified` status and review evidence in pull requests, ADR-0012 sections 3 and 4); `organisation`, `api_key`, `usage_event` (P5).

**Two timelines.** Valid time (`valid_period`) says when a price applies. Record time (`recorded_during`) says when MuniSense believed it. **Record time starts at publication**, and the publish step writes it explicitly into the file; it is never derived from git history. Rows are never updated: a rebuild computes each `recorded_during` from the publication that supersedes or withdraws it. "As recorded on D" means: rows where `recorded_during` contains D. Because the exclusion constraint covers record time too, every past snapshot is free of overlaps.

## Money rules

- `Decimal` everywhere, created from strings, never floats.
- Every rate keeps its original printed value and unit (for example `234.67 c/kWh`) **and** a canonical value (ZAR per kWh, per day or per month).
- Quantise only at the points the supplier's `RoundingPolicy` names (line amount, VAT, total, prepaid kWh allocation); ADR-0005 is the authority. Until a supplier's policy is learned from real bills, it is `estimated` and results carry a warning.
- VAT comes from the `vat_rate` table by date, applied per the charge's VAT treatment.

## Calculation flow

1. The service resolves the supplier, tariff and versions covering the period (as of now, or as recorded on a given date).
2. It splits the period at version boundaries and season boundaries. The allocation of consumption across splits is explicit and reported (pro-rata by days unless the supplier's policy says otherwise).
3. The pure engine evaluates each component for each split and returns line items with component, quantity, rate, amount, citation and status. Consumption arrives as a **profile** (a period total now; time-of-use buckets from P4).
4. VAT and rounding are applied; totals are computed.
5. The result includes assumptions (for example "consumption pro-rated by days") and warnings (for example "rounding policy estimated").

**Prepaid purchase.** For a prepaid meter the engine also runs in the other direction: given a rand amount and the purchases already made in the same month, it returns the kWh received and how they fall across the blocks. When the month's block allocation resets is a supplier policy in data, not code.

## API conventions (from P5)

- URL-versioned: `/v1/...`. Breaking changes only in a new version.
- JSON. Money and rates as **decimal strings** (`"123.45"`), never JSON numbers. Currency `ZAR`.
- Dates in ISO 8601. The business time zone is Africa/Johannesburg; datetimes carry an offset.
- Errors follow RFC 9457 (`application/problem+json`) with a stable `code`.
- Every calculated response includes provenance and verification status for each line.
- Pagination by cursor; rate limits signalled with standard headers.

## Configuration, logging and errors

- Settings from environment variables via pydantic-settings; `.env` for local secrets (never committed; `.env.example` documents the variables).
- structlog JSON logs with request ID, route, status and duration. **Never request bodies or personal information.**
- Domain errors are typed. Unknown or missing data raises; it never defaults silently.

## Source documents

PDFs are **committed** under `data/sources/` and identified by SHA-256 in `source_document`. They amount to a few MB a year; committing them backs them up, gives a second machine a copy, and lets CI check citations against the source text. **Open question:** where source documents live in production (object storage costs money). Decide by ADR before P9.

## Deliberately not built yet

A public calculator (decided at P9), user accounts for the public, multi-tenant roles, webhooks, caching layers, background job queues, a separate front-end application, microservices. Extension points (`organisation` table, service interfaces) exist only when the first feature needs them.
