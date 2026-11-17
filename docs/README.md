# Documentation map

Each fact lives in exactly one place. Other documents link to it rather than repeating it.

| Document | Holds | Owner of changes |
| --- | --- | --- |
| [`status.md`](status.md) | Current phase, tasks, decisions waiting for the owner, known limitations. **The only progress tracker.** | Claude Code, every task |
| [`roadmap.md`](roadmap.md) | Phases, deliverables, acceptance criteria, gates | Changes only with the owner's approval |
| [`product/prd.md`](product/prd.md) | Problem, users, MVP scope, requirements, success measures | Changes only with the owner's approval |
| [`product/glossary.md`](product/glossary.md) | Domain terms | Claude Code, when a new term appears |
| [`domain/sa-tariffs.md`](domain/sa-tariffs.md) | How South African tariffs work, with sources. Research notes, **not data** | Claude Code, when research adds or corrects something |
| [`architecture/overview.md`](architecture/overview.md) | Modules, dependency rules, data model, API conventions | Claude Code, when structure changes |
| [`adr/`](adr/) | Decisions and their reasons. Never edited once Accepted | New ADR via `/adr`; the owner accepts |
| [`quality/standards.md`](quality/standards.md) | Coding standards | Changes only with the owner's approval |
| [`quality/testing-strategy.md`](quality/testing-strategy.md) | Test layers, tools, targets | Claude Code, with a note in the report |
| [`quality/definition-of-done.md`](quality/definition-of-done.md) | When a task is done | Changes only with the owner's approval |
| [`security/security-and-privacy.md`](security/security-and-privacy.md) | Controls, threats, POPIA register, legal items needing formal verification | Claude Code, when a change affects security or privacy |
| [`tech-debt.md`](tech-debt.md) | Deferred work, with reasons | Claude Code |
| [`deployment.md`](deployment.md) | How it runs locally; what production would need and cost | Claude Code |
| [`reports/`](reports/) | Progress and gate reports for the owner and the architect chat | Claude Code, via `/report` |

Generated documents (added in later phases): the API reference comes from the OpenAPI spec produced by the code, and the database schema comes from the migrations. Do not write either by hand.

## What a change must update

| If you change… | Also update |
| --- | --- |
| Anything | `status.md` |
| A module boundary, dependency or data model | `architecture/overview.md`, and an ADR if it is significant |
| An API endpoint or response | The OpenAPI snapshot test (regenerate it), and note it in the PR description |
| Tariff data or golden bills | Run `tariff-verifier`; update `domain/sa-tariffs.md` if you learned something about how tariffs work |
| Anything touching inputs, storage, logs, auth or dependencies | `security/security-and-privacy.md` if controls or the POPIA register change |
| Scope or behaviour visible to users | Stop. That needs the owner's approval first (`prd.md`) |
| A shortcut you took on purpose | `tech-debt.md` |
| A new term | `product/glossary.md` |
