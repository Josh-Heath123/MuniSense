# P2 checkpoint after P2-9: the publication pipeline (2026-11-19)

For the architect and the owner. P2-2 to P2-9 are built and reviewed. This is the stop point the P2 task list sets before the database work (P2-10 to P2-12) and the first real publications (P2-13). Nothing real has been published: `data/tariffs/` and `data/vat/` do not exist yet.

## What is built

| Task | Pull request | What it does | Reviews |
| --- | --- | --- | --- |
| P2-2 Dependencies | #31 (merged) | SQLAlchemy 2.1, Alembic 1.20, psycopg 3.3 (binary), pypdf 6.21; each owned by one package (import rules 4, 4b) | code and security APPROVE |
| P2-3 Settings and roles | #33 (open, **waits for W17**) | Checked database URLs (an allow-list of query keys; libpq `PG*` variables refused; `gssencmode=disable` and `require_auth=scram-sha-256` forced; `verify-full` when deployed; loopback-only when local); a read-only app role and a schema-owning migration role; SCRAM verifiers sent from the client | code CHANGES REQUIRED three times, then APPROVE; security APPROVE |
| P2-4 Canonical JSON and the envelope | #34 | Canonical form on the JSON text alone; strict publication models with the id, revision and withdrawal rules | code APPROVE after one round |
| P2-6 Catalogue, manifests, drafts | #35 | Supplier catalogue; source manifests for Ekurhuleni and SARS; drafts in ADR-0012's layout, canonical, values unchanged | code APPROVE after one round; tariff-verifier MATCH |
| P2-7 Citation check | #36 | pypdf in a limited `python -I` child process (bytes checked against the manifest hash first; empty environment; hard limits set by the child before pypdf loads); fails closed | code and security CHANGES REQUIRED (the file was not checked against its hash), then APPROVE |
| P2-8 Publish step | #37 | `poe publish` with every ADR-0012 refusal, atomic writes that never overwrite, record time that only moves forward within a tariff | code CHANGES REQUIRED, then APPROVE |
| P2-9 Publication guards | #38 | `poe publications-check` in CI (whole set; no change to a published file; added publications re-checked on pull requests); the file hook refuses Claude's file tools under the publication folders | code and security CHANGES REQUIRED, then APPROVE |

The pull requests are stacked (#34 on #33, #35 on #34, and so on), so they merge in order. `uv run poe verify` on the top of the stack: 1026 tests, 100% line and branch coverage, 36 hook tests.

On the committed data: both VAT 404 page 15 printed texts pass the citation check; all 16 citations in each Tariff B draft are `no_text_layer` (the schedule is a scan); dry runs of `poe publish --check` on all three drafts would publish each as `r1`.

## Decisions for the owner and the architect

1. **W17: the bootstrap's own tests connect as the superuser.** The P2-3 criterion says tests never do. Every other database test connects as the two roles; only `tests/integration/bootstrap` (marker `db_admin`) needs a superuser, because creating roles is what it tests. Recommendation: accept for those tests only. #33, and so the whole stack, waits for this.
2. **W18: three questions about ADR-0012's revision rule.**
   - (a) A withdrawn version is restored with `supersedes: null`, but `r1` already exists under its date. Provisional reading (in `publication.py` and `publish.py`): a publication that supersedes nothing takes the next free revision under its date. Trade-off: a correction that forgot its `supersedes` is caught only by the overlap refusal, and revision gaps are not refused.
   - (b) **"The superseded revision plus one, even under another date" can deadlock:** a correction moved to a date where that revision already exists can never be published. The publish step refuses it safely ("already exists"); it is tested. Recommendation: a moved correction takes the next free revision under its new date. That changes ADR-0012, so it needs a decision.
   - (c) A withdrawal's `checks` record `schema: valid`, the documents sentence and `overlap: none`, which say nothing for a file without a version. The guards treat withdrawals explicitly (zero counts). Recommendation: a separate `checks` shape for withdrawals in a later schema version.
3. **W19: E43 is not met.** `poe check` measured 26 to 31 s after P2-3 and 30 to 51 s after P2-7, rising from run to run on unchanged code, while no single fast test takes more than 0.8 s. The heavy new test modules (publish, guards, the citation check's process tests) are marked `slow` and run only in `verify` and CI. The rest looks like mypy on SQLAlchemy (about 6 s) and per-run overhead on the `/mnt/c` disk. Options: accept a higher limit, or decide between parallel tests (a new dependency) and taking mypy out of `check`.
4. **Merge protection is not enforced (new).** Nothing technical requires review or green CI before a merge; it is a working rule (E17). The publication guards run the pull request's own code, so a pull request that also edits the guards can switch them off; the owner's review of any pull request that touches `guards.py`, `publish.py`, `provenance/`, `ci.yml` or `pyproject.toml` together with publications is the real control. Whether CODEOWNERS and branch protection are available on the current GitHub plan has not been checked.

## Tightenings adopted under the E50 process (reported here, as E50 asks)

Each tightened a task's own criteria, with no new dependency, design change, cost or change visible to users:

- **P2-3:**
  - local means a loopback host;
  - URL query keys are an allow-list; `#`, a second `@` and percent-encoded hosts are refused;
  - every libpq `PG*` variable is refused;
  - `require_auth=scram-sha-256` is forced (a P9 constraint: certificate-only authentication would need a decision);
  - engines are built from the checked parts;
  - app sessions are read-only by default;
  - an app and migration pair names one database.
- **P2-4:** integers longer than 30 digits are refused (not in ADR-0012; can only ever be raised).
- **P2-7:**
  - The CPU and wall-clock limits were raised (120 s and 300 s) after measuring the child's CPU time on the largest document at 5.7 to 11.4 s.
  - The file is checked against its manifest hash before parsing.
  - The child process is hardened (empty environment, no file writes, no core dumps).
- **P2-8:**
  - record time must be later than the tariff's latest publication, not only the superseded one;
  - a free basic allocation is refused while TD-10 is open (E49 made mechanical);
  - a document listed in two manifests is refused.
- **P2-9:**
  - symlinks, submodules, FIFOs and case variants are refused;
  - the supplier catalogue, free basic allocations and the tool label are checked on every file or added file;
  - the file hook now compares the project root without regard to case, which also closes that gap for the existing ADR and migration rules.

## Changes to owner-approved items (for the owner to see)

- `.claude/hooks/guard_files.py` gained the publication rule (in P2-9's criteria) and a case-insensitive root comparison (a tightening).
- TD-3, accepted by the owner under E18, is widened. It now records that Bash can also write publications, and names the CI guards as a backstop within their limits.

## Known limits, recorded in the security register

- The guards run the pull request's own code, and a direct push to `main` skips the pull-request re-check.
- Bash can write under the publication folders (TD-3).
- A fabricated source document added together with its own manifest entry passes. The owner's review of new sources is the control.
- `published_at` is declared by the file. The 24-hour window is a freshness check, not proof.
- The citation check's child process is resource-limited, not sandboxed. A pypdf bug that ran code could still read files and use the network.
- The native libraries bundled in psycopg-binary are outside pip-audit (TD-15). The first manual check is due at the P2 gate.

## For the owner, outside the code

- Two comments in `.env.example` are out of date. The bash guard blocks Claude from editing `.env` files.
  - The connection comment should mention the loopback rule, the refused `PG*` variables and the forced `require_auth=scram-sha-256`.
  - The admin URL comment should say "the bootstrap's own tests" instead of "the database tests' setup".
- pypdf warns that fontTools is needed to fully decode some fonts in the Act 3 of 2026 PDF. The Act is not cited for any value, and a misread page would fail the check rather than pass. Adding fontTools would be a dependency decision.

## Next, after this checkpoint

1. P2-10: schema and first migration. The bootstrap creates `btree_gist` as the superuser.
2. P2-11: the loader and `poe db-rebuild`.
3. P2-12: "as recorded on" queries.
4. P2-13: first publications. **Stop before publishing, for the owner's hand check of Tariff B.**
5. P2-14: the gate report.
