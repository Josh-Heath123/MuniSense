# ADR-0012: Keep published tariffs as immutable JSON files and rebuild the database from them

- **Status:** Accepted. Its revision rule (section 2 "File name", and the revision sentences of sections 3 and 7) and the shape of `checks` (section 3): Superseded by ADR-0013. In section 6, "drops and recreates the schema" and the load order of publications (sorted path order, VAT before tariffs): Superseded by ADR-0015. Everything else in this ADR stands.
- **Date:** 2026-11-18 (proposed; revised after the architect's review); 2026-11-19 (accepted by the owner, W16)
- **Deciders:** Josh Heath (owner)

## Context

ADR-0003 makes committed, reviewed tariff files the source of truth through P9, with PostgreSQL as a deterministic projection of them. It also says that record time is written into the file by the publish step and never taken from git, that published rows are append-only, and that "the storage ADR, written at the start of P2, decides the file format, layout and loader". This is that ADR. It also settles where drafts live, which ADR-0003 left open.

What already exists (P1):

- **Typed, strict Pydantic models** for a tariff version (`TariffVersion`, ADR-0004). Every value is a `Cited[T]` with its own citation (document SHA-256, page, locator, printed text) and status (ADR-0006). A `Verified` status records the human verifier, the method, the date and the text check (`passed` or `no_text_layer`). The models round-trip through JSON exactly: decimals are strings, and floats are refused.
- **Draft files** in `data/drafts/ekurhuleni/2026-27/` (Tariff B) and `data/drafts/vat/`. They are bare `TariffVersion` and VAT-table JSON, all `estimated`.
- **Source PDFs** in `data/sources/<publisher>/`, identified by SHA-256. A Markdown README per folder records each document's URL, retrieval date and hash. The Ekurhuleni schedule is a scan with no text layer; the SARS documents that the VAT table cites have one.

What P2 must prove (roadmap):
- rebuilding the database twice from the same files gives identical results;
- constraints reject overlaps, including in past snapshots;
- migrations upgrade and downgrade;
- P1 examples survive a round trip from file to database and back.

**Constraints:**
- **Cost and tooling:** zero cost. SQLAlchemy, Alembic and psycopg are already planned (ADR-0003). The owner has approved pypdf for the citation check, for text extraction only (E47).
- **One publisher:** the owner, through pull requests.
- **Domain purity:** the domain stays pure, so the file I/O, PDF reading, the clock reading for record time, and the database live outside it.
- **Published files are immutable, but the code is not.** The models, Pydantic and Python will change. No check on a published file may depend on today's model reproducing it byte for byte.

## Decision

### 1. Format: JSON in a canonical form defined on the text alone

- **The models define the content.** A published file holds a version as the domain models write it (`model_dump_json`), so for the current `schema_version` there is one definition of the content, already strict and tested.
- **Canonical form is a property of the JSON text, not of the model.** A file is canonical when its text equals `json.dumps(json.loads(text), indent=2, ensure_ascii=False)` followed by one final newline, read as UTF-8. Parsing refuses floats (`parse_float` raises), `NaN`, `Infinity` and `-Infinity` (`parse_constant` raises; `parse_float` does not see them, and `json.loads` would otherwise turn them into floats) and duplicate keys (`object_pairs_hook` raises). Key order is whatever the publish step wrote, which is the model's order at that time; the check keeps that order and never reorders. So the check stays true for a file published years ago, whatever the models have become since.
- **Validation is a separate check.** A file is also valid when its content loads through the model for its `schema_version`. For the current version that is the model itself. For an older version it is a converter, tested against every committed file of that version, whose output loads through the current model. The loader accepts only listed versions. A failing validation is a code problem to fix in the converter, never a reason to edit the file.
- **Envelope versioning.** Every file carries `schema_version` in its envelope. A format change is a new schema version with its converter.
- **Drafts** are written in the same canonical form by the tools that produce them. The P1 drafts are equivalent but were hand-written; they are re-written in canonical form when this is built.

### 2. Layout

```text
data/
  catalogue/suppliers.json                   supplier codes, names, kind, tariff-year start month
  sources/<publisher>/sources.json           machine-readable manifest of the source documents (new)
  sources/<publisher>/*.pdf, README.md        the documents and their human notes (as now)
  drafts/<supplier>/<tariff-year>/<tariff-code>.json            drafts: bare versions
  tariffs/<supplier>/<tariff-code>/<effective-from>.r<N>.json   publications, immutable
  vat/south-africa/<effective-from>.r<N>.json                   VAT publications (one rate each), immutable
  observations/                               user-provided figures, not tariff data (as now)
```

- **Folder per tariff.** `<supplier>` and `<tariff-code>` are the catalogue keys already in `TariffVersion` (for example `city-of-ekurhuleni` and `b-residential-1-phase`). Today's drafts sit in `data/drafts/ekurhuleni/` and `data/drafts/vat/`; they move to the supplier-code folders when they are re-written in canonical form.
- **File name.** `<effective-from>` is the first day of the version the file holds (`2026-07-01`). `r<N>` is the revision: a first publication is `r1`; a publication that supersedes another takes the superseded one's revision plus one, even when it is filed under a different date (section 3). The publish step refuses a path that already exists.
- **Lookup.** A publication can be found by path, without reading every file.
- **VAT: one rate per publication.** A VAT publication holds one `VatRate` (its cited percentage, start and end) in the same envelope as a tariff version. VAT therefore uses the same rules as tariffs: overlap refusal, corrections, withdrawals and mid-year amendments. The repository assembles a `VatTable` from the rates current at the requested record time; a gap or an overlap refuses the calculation. Today's draft (one table) is split into one draft per rate when it is re-written.
- **The source manifest** (`sources.json`) lists each document's SHA-256, path, URL, title, publisher, retrieval date, approval reference and whether it has a text layer. It is what the database's `source_document` table is loaded from. The READMEs stay as the human notes, and a test checks that the two agree.

### 3. A publication: a version (or a withdrawal) plus a publication record

```json
{
  "schema_version": 1,
  "publication": {
    "id": "city-of-ekurhuleni/b-residential-1-phase/2026-07-01/r1",
    "published_at": "2026-12-01T09:30:00+02:00",
    "published_by": "owner",
    "supersedes": null,
    "reason": "first publication of the 2026/27 schedule",
    "checks": {
      "tool_version": "munisense 0.1.0",
      "schema": "valid",
      "documents": "all cited documents in a manifest; hashes match",
      "overlap": "none",
      "citation_check": {"passed": 0, "no_text_layer": 31, "failed": 0}
    }
  },
  "version": { "...": "the TariffVersion, exactly as the model writes it" }
}
```

- **`published_at`** is the record time: when MuniSense starts to believe this publication. It is offset-aware, and written by the publish step (section 5).
- **`published_by`** is a pseudonymous handle, never a name (ADR-0008; the same rule as `Verified.verifier`).
- **`supersedes`** names the publication this one replaces, or is `null`. A publication may be superseded at most once; the loader refuses a second successor.
- **`checks` holds only the publish step's own automatic results.** Human verification has one record: the `Verified` status on each value (verifier, method, date, text check), as now. Agent results and review evidence live in the pull request and, for humans, in those statuses. They are not copied into the publication.
- **A correction may change any field,** including `effective_from` and `effective_to`. It is filed under its own (possibly new) effective-from date, with `supersedes` pointing at the old publication's `id`.
- **A withdrawal** is a publication with `supersedes` set, a `reason`, and no `version` (`"version": null`). It ends the withdrawn version's `recorded_during` at its own `published_at` and puts nothing in its place. It is filed under the withdrawn version's date with the next revision number. **A withdrawal cannot be superseded:** to bring a withdrawn version back, publish it again as a new publication with `supersedes: null`.
- **Files are never changed once on `main`**: never edited, deleted or renamed. A CI check and the file guard (both built in P2; neither exists yet) refuse any of these, as the guard already does for migrations on `main`. A correction or withdrawal is a new file; the old file is untouched.

### 4. How citations and statuses are stored

- **In the files: inline,** exactly as now. Each value carries its citation and its status. This keeps a value and its provenance together in review, and is what the domain validates.
- **In the database:**
  - **`tariff_version.payload`** holds the whole version as JSONB, so a version read back from the database is the version that was published. The P1 round-trip test reads it back through the domain model and compares it. Questions such as "which values cite page 4 of this document" or "every `estimated` value in a tariff" are answered with JSONB path queries over the payload, in repository functions with tests.
  - **`source_document`** is loaded from the manifests. The loader refuses any citation whose document is not in it, and recomputes every document's hash.
  - **Summary statuses** (`tariff_version.status`, `tariff_component.status`) are recomputed at load with the domain's own walker, never stored as truth, so the database cannot disagree with the files.
  - **`publication`** holds every publication, withdrawals included (id, `published_at`, `published_by`, `supersedes`, reason, checks). `tariff_version` rows exist only for publications with a version.
- **A per-value `cited_value` table is deferred.** JSONB path queries answer the same questions now. It is a candidate for P6 if the console needs faster or simpler queries.

### 5. The publish step writes record time

- **The command.** `uv run poe publish <draft-path>` runs in the ingestion area, which may read the clock and the PDFs (the domain may not). `uv run poe publish --check <draft-path>` is a dry run: it runs every check and refusal and writes nothing.
- **What it does, in order:**
  1. **Validate.** It loads the draft with the current domain model.
  2. **Refuse what cannot be published:**
     - a value without a citation, or a citation of a document not in a manifest;
     - a document whose committed bytes do not match its SHA-256;
     - a version that would overlap, in valid time, a current publication of the same tariff that it does not supersede;
     - a `supersedes` that names a publication already superseded, or one that does not exist;
     - a citation-check failure, or a `Verified` value whose declared `text_check` differs from the computed one.
  3. **Citation check** (pypdf, text extraction only). For each cited value, it extracts the text of the cited page and normalises whitespace on both sides (every run of Unicode whitespace becomes one space, and the ends are trimmed). The result is:
     - `passed` when the normalised printed text appears in the normalised page text;
     - `no_text_layer` only when the manifest says the document has no text layer and the page yields no extractable text;
     - `failed` otherwise, including extraction errors, empty text from a document said to have a text layer, and text found on a page of a document said to have none. A failure refuses publication: the check fails closed.
  4. **Write record time.** It sets `published_at` to the current time and writes the publication under `data/tariffs/` (or `data/vat/`) in canonical form.
  5. **Remove the draft** in the same change. Git keeps its history.
- **The owner publishes by merging.** The owner runs the step, and the resulting change is reviewed and merged as a pull request. The pull request may not edit the publication. CI checks:
  - that every publication on the branch is canonical and valid (section 1);
  - on pull requests only, for publications **added** by the pull request: `published_at` is no later than CI's own time and **no more than 24 hours earlier**. The check does not run on a push to `main`, where a failure after the merge could not be fixed. The bound is therefore against the pull request's last CI run, not the merge: the owner merges soon after CI passes, or re-runs CI first, and re-runs the publish step if the bound has passed;
  - that a superseding publication is later than the one it supersedes;
  - that no publication already on `main` was edited, deleted or renamed.
- **The remaining gap.** `published_at` is when the owner ran the step: up to 24 hours before the pull request's last CI run, plus however long the merge waits after that run. If the pull request is never merged, the publication never existed. This is preferred to taking record time from git, which ADR-0003 rules out. The gap is recorded as TD-14, to revisit when a deployed service exists.
- **Estimated values may be published.** Every result that uses them warns (ADR-0006). What decides publication is that every value is cited, every citation passes the check or is honestly `no_text_layer`, and every `Verified` status is consistent with it; not that every value is `verified`. P3's pilot depends on this, because the Ekurhuleni schedule is a scan.

### 6. The database is rebuilt deterministically from the files

- **The command.** `uv run poe db-rebuild` drops and recreates the schema, applies the Alembic migrations to head, and loads every file.
- **Where it may run.** It refuses to run unless the database name ends in `_dev` or `_test`. It connects as the migration role; the application role only reads (P2 security notes). Whether and how it may run against a deployed database is a P9 decision.
- **Load order:** the catalogue, then the source manifests, then VAT publications, then tariff publications. Within each, files load in sorted path order. The load is one transaction: any error aborts it completely.
- **No clock, no randomness, no sequences.** Every row's identity comes from the files:
  - a publication's key is its `id`;
  - other keys are UUIDv5 derived from it;
  - a version's `recorded_during` is `[published_at, published_at of the publication that supersedes it)` (a correction or a withdrawal), or open-ended while nothing supersedes it.

  So two rebuilds from the same files give identical rows, and a test proves it by comparing a canonical dump of every table.
- **Checks at load.** Every file is checked for canonical form and validated (section 1), and every document hash is recomputed. The exclusion constraint of ADR-0003 rejects overlaps in valid and record time together. A file set that breaks any rule cannot be loaded.
- **Nothing else writes the database.** A rebuild replaces it entirely, so there is nothing to migrate in the data, only in the schema. The P6 console's publish action also produces a file and a pull request (ADR-0003), never a row.

### 7. From draft to published

| Stage | Where | What it means | Used in calculations? |
| --- | --- | --- | --- |
| Draft | `data/drafts/…` (committed): a bare version | Being transcribed and reviewed; values `estimated`, `user_provided` or `verified`; may be incomplete or invalid. `poe publish --check` shows what would refuse it | No (P1's `poe demo` is the one exception, TD-13; it moves to published data when P2 lands) |
| Published | `data/tariffs/…r<N>.json` | Record time set; immutable; loaded into the database | **Yes**: only published versions are used (ADR-0006) |
| Superseded | the same file, untouched | A correction or withdrawal supersedes it; its `recorded_during` ends at that publication's `published_at` | Only for "as recorded on" a date before the successor |

- **Drafts stay out of the database.** They are not part of the two-timeline data (ADR-0003). They are files in the repository, so they are backed up and reviewed like everything else, and never live only in a Docker volume (the P3 note).
- **A correction** copies the published version into a new draft, changes and re-checks it, and publishes it with `supersedes` set. If its effective-from date changes, it is filed under the new date.
- **A mid-year amendment** (prices change from, say, 1 February) is two publications in one pull request, published in this order:
  1. a revision of the current version that shortens it (a new `effective_to` of 31 January), superseding it;
  2. the new version from 1 February, with `supersedes: null`.

  The publish step checks overlaps against the publications on disk, including the revision just written, so publishing them in the other order is refused. The revision's `published_at` is therefore no later than the new version's, and no snapshot in record time has two versions covering the same day.

## Consequences

**Good:**
- One definition of the content (the domain models) for files, validation and the database payload, without tying old files to today's model.
- Every published value keeps its citation and status through every step; human verification has one record.
- Past answers are reproducible because files are immutable and record time is explicit; withdrawals and moved corrections keep that true.
- Citations that can be checked against a text layer are checked, and a check that cannot run fails closed rather than passing.
- The database can be thrown away at any moment, and reviews are ordinary diffs.
- Nothing here costs money. pypdf is the one new dependency, approved for this use.

**Bad:**
- Two representations to keep in step. The loader and round-trip tests carry that weight.
- Published files cannot be fixed in place, even for a typo. Every fix is a new revision.
- Old schema versions need converters kept and tested for as long as their files exist.
- `published_at` can be up to 24 hours before the pull request's last CI run, and the merge can come later still (TD-14).
- Queries over citations are JSONB path queries, which are less obvious than a table; they live in tested repository functions.
- pypdf's text extraction may not reproduce every printed text exactly (ligatures, columns, hyphenation). The check then fails closed, and the value cannot be published until the citation's printed text or locator is corrected.

**Cost:** R0.

**Reversibility:**
- The file format is versioned, so it can change with a converter.
- A `cited_value` table can be added later without changing the files.
- Moving the source of truth from files to the database after P9 remains a separate decision (ADR-0003).
- What is hard to undo is the immutability of published files, because past answers depend on it. That is why it is decided now.

## Alternatives considered

| Option | Why not |
| --- | --- |
| YAML or TOML files | Need a new dependency and a second schema; YAML parses numbers and dates implicitly, which is unsafe for money |
| Canonical form defined by re-serialising through the current model | Published files may never be edited, but the model will change; the check would eventually fail on files nobody may fix |
| One file per tariff holding every version and revision | Correcting a version would edit a file that holds published history, which defeats immutability |
| Close `recorded_during` by editing the superseded file | Edits published files. Deriving the end from the successor's `published_at` keeps every file immutable and gives the same result |
| Human and agent checks recorded in `publication.checks` | Two records of human verification that can disagree with the values' `Verified` statuses; agent evidence belongs in the pull request |
| One VAT table per publication | A new rate would correct the whole table, and VAT would need its own overlap and withdrawal rules |
| Superseding a withdrawal to restore a version | A chain through a withdrawal is harder to read and check; republishing with `supersedes: null` says plainly what happened |
| A "checked" draft stage with its own file format | A dry run (`--check`) gives the same feedback without a second format |
| A `cited_value` table now | Duplicates the payload; JSONB path queries answer the same questions; deferred to P6 if needed |
| No citation check until a later phase | The VAT table cites SARS documents with a text layer, so the check can run now; publishing without it would let wrong printed text through |
| Record time from the merge commit's date | Ruled out by ADR-0003: git history can be rewritten, and the merge time is not under the publish step's control |
| No limit on the publish-to-merge gap | A pull request left for weeks would publish with a record time weeks before anyone could have seen it |
| Drafts in database tables | Drafts would live only in a Docker volume, which the P3 note forbids; files give backup and review for free |
| Database sequences and `now()` defaults | Two rebuilds would differ; deterministic keys and file-supplied times make rebuilds identical |
