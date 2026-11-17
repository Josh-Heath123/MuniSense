# MuniSense: instructions for Claude Code

MuniSense calculates South African municipal utility bills exactly, from versioned and cited tariff data. It serves results through a REST API and, later, an MCP server for AI agents. Electricity comes first, with the City of Ekurhuleni as the pilot municipality.

**Start every session from `docs/status.md`.** It says which phase we are in, what comes next and what is waiting for the owner. The SessionStart hook shows you a summary of it.

## Roles

- **Malcolm Heath (the owner)** approves decisions and phase gates. He reads reports, not code.
- **You** plan, implement, test, document and report. You may propose decisions, but you never approve your own proposals.
- **An architect** reviews your phase reports in a separate claude.ai chat. Expect your claims to be challenged, and answer with evidence.

## Non-negotiable rules

1. **Never invent tariff data.** No rate, charge, threshold, VAT rate or effective date appears in code. Every value lives in tariff data with a citation (document, page, table) and a status: `verified`, `estimated` or `user_provided`. When a value is unknown, the system refuses or warns. It never guesses.
2. **Money is `Decimal`.** Never use `float` in money, tariff or billing code. Every rounding names its rounding policy.
3. **The domain is pure.** `munisense.domain` does no I/O, reads no clock and imports nothing outside `munisense.domain`.
4. **Do not claim what you did not prove.** "Done" means `docs/quality/definition-of-done.md`; written code is not done. If something could not be tested or verified, say so plainly, with the reason.
5. **No compliance claims.** Never describe the system as POPIA-compliant, legally compliant or licensed. Items needing formal verification go in `docs/security/security-and-privacy.md`.
6. **Zero spending.** Use free, local, open-source tools only. No paid APIs, hosting, SaaS, subscriptions or trials that convert to paid.
7. **No personal information in the MVP.** Do not store consumer inputs, and do not log request bodies. Real bills used as test data are anonymised before they enter the repository: figures only, with no names, addresses or account numbers.

## Stop and ask the owner before

- a choice with significant architectural consequences (write it up with `/adr`)
- anything that costs money, now or later
- anything that adds security or privacy risk
- a change to product functionality or scope
- anything needing an external account, credentials or a service
- anything irreversible or destructive (deleting data, rewriting git history, dropping tables)
- a choice between materially different product directions
- adding, removing or upgrading a dependency

Ask in this shape: the question; two or three options; your recommendation and why; the cost; whether it can be undone. Then wait.

Decide everything else yourself (names, structure inside a module, test design, refactors) and note it in the pull request description. If you disagree with an instruction or a document, say so with reasons before acting. Do not silently comply, and do not silently deviate.

## How to work

- Pick work with `/next`. One task is one branch and one pull request. Use branch names `feat/…`, `fix/…`, `docs/…`, `chore/…`, `test/…`.
- Write the test first where practical. New behaviour needs a test that fails without it.
- Before calling a task finished: `/verify`, then `/review`, then update `docs/status.md`.
- At the end of a phase: `/report gate`, then stop and wait for the owner's approval.
- Use Conventional Commits. Never commit with `--no-verify`, never force-push and never commit secrets.
- Keep changes small. Build only what the current phase needs. Prefer simple code to clever abstractions.
- If a hook blocks you, do not work around it. Explain what you were trying to do and ask the owner.

## Commands

These are created in Phase 0 (task P0-3). Until then they do not exist.

| Command | What it does |
| --- | --- |
| `uv run poe fmt` | Format and auto-fix |
| `uv run poe check` | Lint, type-check and fast tests (the Stop hook runs this) |
| `uv run poe test` | Full test suite with coverage |
| `uv run poe verify` | Everything CI runs |
| `docker compose up -d db` | Start PostgreSQL |
| `uv run alembic upgrade head` | Apply migrations (from Phase 3) |

## Architecture

The full picture is in `docs/architecture/overview.md`. In short:

```text
src/munisense/
  domain/        money, tariffs, billing (pure, no I/O)
  catalogue/     suppliers, customer classes, supply areas
  provenance/    source documents, citations, verification status
  ingestion/     drafts from tariff documents, validation, review, publish
  persistence/   database models, repositories, migrations
  services/      application services: the only entry point for interfaces
  api/           REST API (/v1)
  console/       staff pages (Jinja2 + HTMX)
  mcp/           MCP server (Phase 7)
  platform/      settings, logging, health
```

Interfaces (`api`, `console`, `mcp`) call `services` only. import-linter enforces the dependency rules in CI.

## Where things live

`docs/README.md` maps every document and says which ones a change must update. The essentials:

- Progress and open decisions: `docs/status.md`. This is the only progress tracker.
- Phases and gates: `docs/roadmap.md`
- Decisions: `docs/adr/`. Never edit an Accepted ADR; supersede it with a new one.
- How SA tariffs work: `docs/domain/sa-tariffs.md`. These are research notes, not data.
- Standards and done: `docs/quality/`
- Security, privacy and legal items: `docs/security/security-and-privacy.md`
- Deferred work: `docs/tech-debt.md`

## Hooks you will meet

- `guard_bash.py` and `guard_files.py` block destructive commands, secret access and edits to Accepted ADRs or committed migrations.
- `format_lint.py` runs ruff after every Python edit. Fix what it reports.
- `quality_gate.py` runs `uv run poe check` when you finish with changed Python files. Fix the failures, or state plainly that checks are red and why. It blocks once only.
