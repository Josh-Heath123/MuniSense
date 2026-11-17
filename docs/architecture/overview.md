# Architecture overview

_Status: proposed in ADR-0002 to ADR-0010; becomes binding when the owner accepts them._

## Shape

MuniSense is a **modular monolith**: one Python 3.13 application, one PostgreSQL 17 database. Every interface (REST API, staff console, public calculator, MCP server) calls the same **application services**. The calculation core is pure: it receives tariff data as arguments and never touches the database, the network or the clock.

```text
  REST API (/v1)   Staff console   Public calculator   MCP server (P7)
        \               |                 |                 /
         +---------- application services (services/) ----+
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
    money/        Money, Rate, Unit, VatRate, RoundingPolicy (Decimal only)
    tariffs/      TariffVersion, component types, TOU calendars, validation
    billing/      calculate(), period splitting, LineItem, BillResult, warnings
  catalogue/      suppliers, customer classes, supply areas
  provenance/     SourceDocument, Citation, VerificationStatus, review log
  ingestion/      draft format, parsers/helpers, validator, review-and-publish
  persistence/    SQLAlchemy models, repositories, Alembic migrations, as-of queries
  services/       use cases: calculate_bill, compare_tariffs, publish_version, ...
  api/            FastAPI routers, schemas, auth, errors (P5)
  console/        Jinja2 + HTMX pages (P6)
  mcp/            MCP server (P7)
  platform/       settings (pydantic-settings), logging (structlog), health
tests/
  unit/  property/  integration/  contract/  golden/
migrations/       Alembic (P3)
data/
  drafts/         structured tariff drafts (committed)
  golden/         anonymised golden bills (committed)
  sources/        source PDFs (git-ignored; identified by SHA-256)
  private/        un-anonymised bills (git-ignored; never committed)
```

## Dependency rules (enforced by import-linter in CI)

1. `munisense.domain` imports nothing outside `munisense.domain` and the standard library (plus Pydantic for value validation, if ADR-0004 says so).
2. Within the domain: `money` ← `tariffs` ← `billing` (arrows point at what may be imported).
3. `api`, `console` and `mcp` import `services` and `platform` only, never `persistence` or `ingestion` directly.
4. Only `persistence` imports SQLAlchemy.
5. Nothing imports `api`, `console` or `mcp`.

## Data model (target for P3; details decided in P3 via ADR if they differ)

| Table | Purpose | Key points |
| --- | --- | --- |
| `supplier` | Municipality, municipal utility or Eskom | Code, name, type, tariff year start month |
| `customer_class` | Domestic, small business, etc. | Per supplier |
| `tariff` | Stable identity of a named tariff | Supplier, code, class, meter type, phase |
| `tariff_version` | Prices for one validity period | `valid_period` (daterange), `recorded_at`, `superseded_at`, `supersedes_id`, `state` (draft, checked, published), `schema_version`. Exclusion constraint: no overlapping published `valid_period` for the same tariff among current records |
| `tariff_component` | Typed component of a version | `type`, `position`, `payload` (JSONB, validated by the domain model), `citation_id`, `status` |
| `source_document` | An official document | URL, title, retrieved_at, SHA-256, approval reference, local path |
| `citation` | Where a value came from | Document, page, table/row, original text as printed |
| `vat_rate` | VAT by date | Rate, valid_period, citation |
| `tou_calendar` | Seasons, day types, public holidays | Versioned like tariffs |
| `review_event` | Who checked or published what, when | Append-only |
| `organisation`, `api_key`, `usage_event` | P5 only | Key hashes only; see the POPIA register |

**Two timelines.** Valid time (`valid_period`) says when a price applies. Record time (`recorded_at`, `superseded_at`) says when MuniSense believed it. Rows are never updated in place, except to close `superseded_at`. "As recorded on D" means: rows where `recorded_at <= D` and (`superseded_at` is null or `> D`).

## Money rules

- `Decimal` everywhere, created from strings, never floats.
- Every rate keeps its original printed value and unit (for example `234.67 c/kWh`) **and** a canonical value (ZAR per kWh, per day or per month).
- Quantise only at line items, using the supplier's `RoundingPolicy`. Until a supplier's policy is learned from real bills, it is `estimated` and results carry a warning.
- VAT comes from the `vat_rate` table by date, applied per the charge's VAT treatment.

## Calculation flow

1. The service resolves the supplier, tariff and versions covering the period (as of now, or as recorded on a given date).
2. It splits the period at version boundaries and season boundaries. The allocation of consumption across splits is explicit and reported (pro-rata by days unless the supplier's policy says otherwise).
3. The pure engine evaluates each component for each split and returns line items with component, quantity, rate, amount, citation and status.
4. VAT and rounding are applied; totals are computed.
5. The result includes assumptions (for example "consumption pro-rated by days") and warnings (for example "rounding policy estimated").

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

PDFs are stored locally under `data/sources/` (git-ignored) and identified by SHA-256 in `source_document`. This keeps the repository small. **Open question for P3:** where source documents live in production (object storage costs money) and how a second machine gets them. Decide by ADR before P9.

## Deliberately not built yet

User accounts for the public, multi-tenant roles, webhooks, caching layers, background job queues, a separate front-end application, microservices. Extension points (`organisation` table, service interfaces) exist only when the first feature needs them.
