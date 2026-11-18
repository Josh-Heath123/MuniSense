# ADR-0012: Keep published tariffs as immutable JSON files and rebuild the database from them

- **Status:** Proposed
- **Date:** 2026-11-18 (proposed)
- **Deciders:** Josh Heath (owner)

## Context

ADR-0003 makes committed, reviewed tariff files the source of truth through P9, with PostgreSQL as a deterministic projection of them. It also says that record time is written into the file by the publish step and never taken from git, that published rows are append-only, and that "the storage ADR, written at the start of P2, decides the file format, layout and loader". This is that ADR. It also settles where drafts live, which ADR-0003 left open.

What already exists (P1):

- **Typed, strict Pydantic models** for a tariff version (`TariffVersion`, ADR-0004). Every value is a `Cited[T]` with its own citation (document SHA-256, page, locator, printed text) and status (ADR-0006). The models round-trip through JSON exactly: decimals are strings, and floats are refused.
- **Draft files** in `data/drafts/ekurhuleni/2026-27/` (Tariff B) and `data/drafts/vat/`. These are the same JSON, all `estimated`.
- **Source PDFs** in `data/sources/<publisher>/`, identified by SHA-256. A Markdown README per folder records each document's URL, retrieval date and hash.

What P2 must prove (roadmap):
- rebuilding the database twice from the same files gives identical results;
- constraints reject overlaps, including in past snapshots;
- migrations upgrade and downgrade;
- P1 examples survive a round trip from file to database and back.

**Constraints:**
- **Cost and tooling:** zero cost, and no new dependency without the owner's approval. SQLAlchemy, Alembic and psycopg are already planned (ADR-0003). The citation check's PDF library is a separate approval.
- **One publisher:** the owner, through pull requests.
- **Domain purity:** the domain stays pure, so the file I/O, the clock reading for record time, and the database live outside it.

## Decision

### 1. Format: the domain's own JSON, in one canonical form

- **The models are the schema.** Tariff files are JSON written by the domain models themselves (`model_dump_json`), so the file schema *is* the model schema: one definition, already strict and tested.
- **Canonical form.** Every committed file is in canonical form: the model's own field order, two-space indentation, UTF-8 and a final newline. A test re-serialises each file and fails unless it is byte-identical. Canonical files make diffs reviewable and rebuilds reproducible. (The P1 drafts are equivalent but not yet canonical: their key order differs. They are re-serialised when this is built.)
- **Envelope versioning.** Every file carries `schema_version` in its envelope. The models already version each component and version (`schema_version: 1`). A format change is a new schema version, with a converter tested against every committed file. The loader accepts only listed versions.

### 2. Layout

```text
data/
  catalogue/suppliers.json                   supplier codes, names, kind, tariff-year start month
  sources/<publisher>/sources.json           machine-readable manifest of the source documents (new)
  sources/<publisher>/*.pdf, README.md        the documents and their human notes (as now)
  drafts/<supplier>/<tariff-year>/<tariff-code>.json        drafts and checked drafts
  tariffs/<supplier>/<tariff-code>/<effective-from>.r<N>.json   published versions, immutable
  vat/south-africa.r<N>.json                  published VAT tables, immutable
  observations/                               user-provided figures, not tariff data (as now)
```

- **Folder per tariff.** `<supplier>` and `<tariff-code>` are the catalogue keys already in `TariffVersion` (for example `city-of-ekurhuleni` and `b-residential-1-phase`). Today's drafts sit in `data/drafts/ekurhuleni/` and `data/drafts/vat/`; they move to the supplier-code folders when they are re-serialised in canonical form.
- **File name.** `<effective-from>` is the version's first day (`2026-07-01`). `r<N>` is the revision: the first publication is `r1`, and each correction of the same version is the next number.
- **Lookup.** A published version can be found by path, without reading every file.
- **The source manifest** (`sources.json`) lists each document's SHA-256, path, URL, title, publisher, retrieval date, approval reference and whether it has a text layer. It is what the database's `source_document` table is loaded from. The READMEs stay as the human notes, and a test checks that the two agree.

### 3. A published file: the version plus a publication record

```json
{
  "schema_version": 1,
  "publication": {
    "id": "city-of-ekurhuleni/b-residential-1-phase/2026-07-01/r1",
    "published_at": "2026-12-01T09:30:00+02:00",
    "published_by": "owner",
    "supersedes": null,
    "reason": "first publication of the 2026/27 schedule",
    "checks": [
      {"kind": "citation_check", "result": "no_text_layer", "on": "2026-11-30", "by": "publish-step"},
      {"kind": "tariff_verifier", "result": "all_values_match", "on": "2026-11-30", "by": "agent"},
      {"kind": "human_check", "result": "verified", "on": "2026-11-30", "by": "owner"}
    ]
  },
  "version": { "...": "the TariffVersion, exactly as the model writes it" }
}
```

- **`published_at`** is the record time: when MuniSense starts to believe this version. It is offset-aware, and written by the publish step (section 5).
- **`published_by`** and every check's `by` are pseudonymous handles or fixed categories, never names (ADR-0008; the same rule as `Verified.verifier` in the security register).
- **`supersedes`** names the publication this one corrects, or is `null`.
- **`checks`** is the review log carried with the file: the citation check, agent checks and human checks. A human check is what makes values `verified` in the version's own statuses (ADR-0006). Agent results are evidence only.
- **Files are never edited once on `main`.** A CI check and the file guard (both built in P2; neither exists yet) refuse changes to a published file, as the guard already does for migrations on `main`. A correction is a new file with the next revision and `supersedes`. The old file is untouched.

### 4. How citations and statuses are stored

- **In the files: inline,** exactly as now. Each value carries its citation and its status. This keeps a value and its provenance together in review, and is what the domain validates.
- **In the database: twice.**
  - **Faithfully:** `tariff_version.payload` holds the whole version as JSONB, so a version read back from the database is the version that was published. The P1 round-trip test reads it back through the domain model and compares it.
  - **For queries:** the loader extracts a `cited_value` row for every cited value. A row holds the version, the value's JSON path (for example `components[1].seasons[0].blocks[0].rate`), the document SHA-256 (a foreign key to `source_document`), page, locator, printed text, status kind and the status details. This answers questions such as "which values cite page 4 of this document", "every `estimated` value in a tariff" and "what does this publication's citation check cover". The foreign key makes a citation of an unknown document impossible.
- **Summaries are recomputed at load, never stored as truth.** `tariff_version.status` and `tariff_component.status` are recomputed with the domain's own walker, so the database cannot disagree with the files.

### 5. The publish step writes record time

- **The command.** `uv run poe publish <draft-path>` runs in the ingestion area, which may read the clock (the domain may not).
- **What it does, in order:**
  1. **Validate.** It loads the draft with the domain model.
  2. **Refuse what cannot be published:** a value without a citation, a citation of a document not in a manifest, a document whose committed bytes do not match its SHA-256, a version that would overlap a published version of the same tariff in valid time without superseding it, and a `verified` status without a recorded human check.
  3. **Citation check.** For documents with a text layer, it checks that each printed text appears on the cited page. A mismatch refuses publication. For scanned documents it records `no_text_layer`.
  4. **Write record time.** It sets `published_at` to the current time and writes the file under `data/tariffs/` in canonical form.
  5. **Remove the draft** in the same change. Git keeps its history.
- **The owner publishes by merging.** The owner runs the step and the resulting change is reviewed and merged as a pull request. The pull request may not edit the published file, and CI checks:
  - that every published file is canonical, validates, and has `published_at` no later than CI's own time;
  - that a superseding file is later than the file it supersedes;
  - that no published file on `main` was changed.
- **The gap between publishing and merging.** `published_at` is when the owner ran the step, not when the pull request merged. If the pull request is not merged, the file never existed. The owner publishes and merges in one sitting, so the gap is minutes. This is preferred to taking record time from git, which ADR-0003 rules out.
- **Estimated values may be published.** Every result that uses them warns (ADR-0006). What decides publication is that every value is cited and every claim is backed by a check, not that every value is `verified`. P3's pilot depends on this, because the Ekurhuleni schedule is a scan.

### 6. The database is rebuilt deterministically from the files

- **The command.** `uv run poe db-rebuild` drops and recreates the schema, applies the Alembic migrations to head, and loads every file.
- **Where it may run.** It refuses to run unless the database name ends in `_dev` or `_test`. It connects as the migration role; the application role only reads (P2 security notes).
- **Load order:** the catalogue, then the source manifests, then VAT tables, then tariff files. Within each, files load in sorted path order. The load is one transaction: any error aborts it completely.
- **No clock, no randomness, no sequences.** Every row's identity comes from the files:
  - a version's key is its publication `id`;
  - other keys are UUIDv5 derived from it;
  - `recorded_during` is `[published_at, published_at of the file that supersedes it)`, or open-ended for the current revision.

  So two rebuilds from the same files give identical rows, and a test proves it by comparing a canonical dump of every table.
- **Checks at load.** Every file is validated by the domain models again, and every document hash is recomputed. The exclusion constraint of ADR-0003 rejects overlaps in valid and record time together. A file set that breaks any rule cannot be loaded.
- **Nothing else writes the database.** A rebuild replaces it entirely, so there is nothing to migrate in the data, only in the schema. The P6 console's publish action also produces a file and a pull request (ADR-0003), never a row.

### 7. From draft to published

| Stage | Where | What it means | Used in calculations? |
| --- | --- | --- | --- |
| Draft | `data/drafts/…` (committed) | Being transcribed; values `estimated` or `user_provided`; may be incomplete or invalid | No (P1's `poe demo` is the one exception, TD-13; it moves to published data when P2 lands) |
| Checked | the same file, with a `checks` list | Validated, citation check run, tariff-verifier run; human checks recorded when done | No |
| Published | `data/tariffs/…r<N>.json` | Record time set; immutable; loaded into the database | **Yes**: only published versions are used (ADR-0006) |
| Superseded | the same file, untouched | A later revision supersedes it; its `recorded_during` ends at the successor's `published_at` | Only for "as recorded on" a date before the successor |

- **Drafts stay out of the database.** They are not part of the two-timeline data (ADR-0003). They are files in the repository, so they are backed up and reviewed like everything else, and never live only in a Docker volume (the P3 note).
- **A correction** copies the published version into a new draft, changes and re-checks it, and publishes it as the next revision with `supersedes` set.

## Consequences

**Good:**
- One schema (the domain models) for files, validation and the database payload.
- Every published value keeps its citation and status through every step.
- Past answers are reproducible because files are immutable and record time is explicit.
- The database can be thrown away at any moment.
- Reviews are ordinary diffs.
- Nothing here costs money or adds a dependency beyond those ADR-0003 already planned.

**Bad:**
- Two representations to keep in step. The loader and round-trip tests carry that weight.
- Published files cannot be fixed in place, even for a typo. Every fix is a new revision.
- `published_at` is when the owner ran the publish step, minutes before the merge.
- The `cited_value` table duplicates what is in the payload. It is recomputed at every rebuild, so the duplication cannot drift.
- The canonical-form rule means drafts must be re-serialised before commit.

**Cost:** R0.

**Reversibility:**
- The file format is versioned, so it can change with a converter.
- Moving the source of truth from files to the database after P9 remains a separate decision (ADR-0003).
- What is hard to undo is the immutability of published files, because past answers depend on it. That is why it is decided now.

## Alternatives considered

| Option | Why not |
| --- | --- |
| YAML or TOML files | Need a new dependency and a second schema; YAML parses numbers and dates implicitly, which is unsafe for money |
| One file per tariff holding every version and revision | Correcting a version would edit a file that holds published history, which defeats immutability |
| Close `recorded_during` by editing the superseded file | Edits published files. Deriving the end from the successor's `published_at` keeps every file immutable and gives the same result |
| Citations in separate files referenced by ID | Splits a value from its provenance in review, and needs an ID scheme for every value. The JSON path in `cited_value` gives the same queries without changing the files |
| Store only the normalised tables, no JSONB payload | The round trip back to the domain model would depend on reassembling every component type from tables, and new component types would need new tables |
| Record time from the merge commit's date | Ruled out by ADR-0003: git history can be rewritten, and the merge time is not under the publish step's control |
| Drafts in database tables | Drafts would live only in a Docker volume, which the P3 note forbids; files give backup and review for free |
| Database sequences and `now()` defaults | Two rebuilds would differ; deterministic keys and file-supplied times make rebuilds identical |
