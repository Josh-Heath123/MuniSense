# Architecture overview

_Status: binding. Decided in ADR-0002 to ADR-0010, accepted by the owner on 2026-11-17._

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
    citations/    Citation, Cited[T] (the "cited value"), VerificationStatus (Verified, Estimated, UserProvided), weakest()
    money/        ExactDecimal, exact(), Money, Rate, RateUnit, CanonicalUnit, VatRate, RoundingPolicy (Decimal only)
    tariffs/      TariffVersion, component types, TOU calendars, validation
    billing/      calculate(), prepaid purchase, period splitting, consumption profiles,
                  LineItem, BillResult, warnings
  catalogue/      suppliers, customer classes, supply areas
  provenance/     SourceDocument records, verification workflow, review log (the per-value Citation and status types live in domain/citations, because the domain may not import this package)
  ingestion/      draft format, parsers/helpers, validator, review-and-publish
  persistence/    SQLAlchemy models, repositories, Alembic migrations, as-of queries
  services/       use cases: calculate_bill, compare_tariffs, publish_version, ...
  api/            FastAPI routers, schemas, auth, errors (P5)
  console/        Jinja2 + HTMX pages (P6)
  mcp/            MCP server (P7)
  platform/       settings (pydantic-settings), logging (structlog), health
tests/
  unit/  property/  integration/  contract/  golden/
migrations/       Alembic (P2)
data/
  drafts/         structured tariff drafts (committed)
  tariffs/        published tariff files, reviewed and committed: the source of truth
                  (name and layout confirmed by the P2 storage ADR)
  golden/         anonymised golden bills (committed)
  sources/        source PDFs (committed; identified by SHA-256)
  private/        un-anonymised bills (git-ignored; never committed)
```

## Dependency rules (enforced in CI by import-linter and `tests/unit/test_domain_purity.py`)

1. `munisense.domain` imports nothing outside `munisense.domain`, an allow-list of pure standard-library modules and Pydantic v2 (strict mode only, never `pydantic.v1`; ADR-0004). It does no I/O, reads no clock and uses no randomness: `open`, `print`, `input`, `eval`, `exec`, `compile` and `__import__` are refused, and so are `now`, `today` and `utcnow`, called or passed (for example as a Pydantic `default_factory`). `zoneinfo` and `uuid` are deliberately not on the allow-list: the caller passes dates and offset-aware datetimes in, and identifiers are made outside the domain. import-linter enforces the munisense part and forbids named third-party packages (rule 1b); the test enforces the allow-list.
2. Within the domain: `citations` ← `money` ← `tariffs` ← `billing` (arrows point at what may be imported). `domain/base.py` is outside the layers and may be imported by all of them.
3. `api`, `console` and `mcp` import `services` and `platform` only, never `persistence` or `ingestion` directly.
4. Only `persistence` imports SQLAlchemy.
5. Nothing imports `api`, `console` or `mcp`.

## Data model (target for P2; details decided in the P2 storage ADR if they differ)

The database is a deterministic projection of the committed tariff files (ADR-0003). It can be dropped and rebuilt from them at any time.

| Table | Purpose | Key points |
| --- | --- | --- |
| `supplier` | Municipality, municipal utility or Eskom | Code, name, type, tariff year start month |
| `customer_class` | Domestic, small business, etc. | Per supplier |
| `tariff` | Stable identity of a named tariff | Supplier, code, class, meter type, phase |
| `tariff_version` | Published prices for one validity period | `valid_period` (daterange), `recorded_during` (tstzrange: from publication until superseded), `supersedes_id`, `schema_version`. Only published versions are stored here; drafts and checked versions stay in the ingestion area. Exclusion constraint (needs `btree_gist`): no two versions of the same tariff whose `valid_period` and `recorded_during` both overlap |
| `tariff_component` | Typed component of a version | `type`, `position`, `payload` (JSONB, validated by the domain model). **Every value inside the payload carries its own citation reference and status.** The component's `status` column is a summary: the weakest status of its values |
| `source_document` | An official document | URL, title, retrieved_at, SHA-256, approval reference, local path |
| `citation` | Where a value came from | Document, page, table/row, original text as printed |
| `vat_rate` | VAT by date | Rate, valid_period, citation |
| `tou_calendar` | Seasons, day types, public holidays | Versioned like tariffs |
| `review_event` | Who checked or published what, when | Append-only |
| `organisation`, `api_key`, `usage_event` | P5 only | Key hashes only; see the POPIA register |

**Two timelines.** Valid time (`valid_period`) says when a price applies. Record time (`recorded_during`) says when MuniSense believed it. **Record time starts at publication**, and the publish step writes it explicitly into the tariff file; it is never derived from git history. Published rows are never updated in place, except to close `recorded_during` when a version is superseded. "As recorded on D" means: rows where `recorded_during` contains D. Because the exclusion constraint covers record time too, every past snapshot is free of overlaps.

## Money rules

- `Decimal` everywhere, created from strings, never floats.
- Every rate keeps its original printed value and unit (for example `234.67 c/kWh`) **and** a canonical value (ZAR per kWh, per day or per month).
- Quantise only at the points the supplier's `RoundingPolicy` names (line amount, VAT, total, prepaid kWh allocation); ADR-0005 is the authority. Until a supplier's policy is learned from real bills, it is `estimated` and results carry a warning.
- VAT comes from the `vat_rate` table by date, applied per the charge's VAT treatment.

## Calculation flow

1. The service resolves the supplier, tariff and versions covering the period (as of now, or as recorded on a given date).
2. It splits the period at version boundaries and season boundaries. The allocation of consumption across splits is explicit and reported (pro-rata by days unless the supplier's policy says otherwise).
3. The pure engine evaluates each component for each split and returns line items with component, quantity, rate, amount, citation and status. Consumption arrives as a **profile** (a monthly total now; time-of-use buckets from P4).
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
