# Security and privacy

> Technical controls do not make MuniSense legally compliant. This document lists controls that exist, risks, and **items that need formal verification by a qualified person**. Never describe the system as "POPIA-compliant".

## Principles

- Collect nothing that is not needed. The MVP stores no personal information (ADR-0008).
- Secrets only in environment variables (`.env` locally; never committed).
- Least privilege for database roles, API keys and staff accounts.
- Validate every external input with types and size limits.
- Log metadata, never bodies or personal information.

## Controls by phase

| Control | Phase | Status |
| --- | --- | --- |
| Secret scanning (gitleaks v8.30.1, official image pinned by digest, run with no network and a read-only mount): staged changes on every commit (pre-commit) and the full history in CI. CI **detects** after the push; it does not prevent a secret reaching GitHub (rotation, and possibly a history rewrite, would then be owner decisions). CI fails if an in-repository gitleaks config or ignore file exists, or an inline allow comment appears in the tree or anywhere in the history (except in `ci.yml`'s own history). Gaps: the local hook can be skipped (`--no-verify`, `SKIP=`); default rules miss low-entropy passwords inside connection URLs (the throwaway CI password was not flagged); gitleaks does not detect personal information; and in CI the large-file check checks nothing (it only looks at staged files). Full-history scan on 2026-11-17: no leaks, no allowlist | P0 | built (P0-5) |
| Dependency vulnerability audit (`uv run poe audit`): pip-audit on the exported lock, every locked package for every platform, hashes required | P0 | built; runs in CI on every pull request and push to main (P0-6) |
| CI on GitHub Actions: a fresh GitHub-hosted runner per run, with the uv package cache restored from the GitHub Actions cache (scoped per branch; installs checked against the lock's hashes). Actions pinned to commit SHAs in `ci.yml`, required by the repository settings (E22) and the `postgres:17` image pinned by digest. Read-only `GITHUB_TOKEN`, checkout without persisted credentials, `UV_LOCKED=1`; no repository secrets, only the read-only `GITHUB_TOKEN`. Fork pull requests do not run workflows (repository Actions settings, read with `gh api` during review; not enforced by this file) | P0 | built (P0-6) |
| Locked, hash-verified dependencies from PyPI only; wheels only (`no-build`, so no package build code runs at install); the lock ignores releases younger than 14 days (`exclude-newer`). Gaps: the cutoff is relative and not recorded as a date in the lock. Since E23 the 14-day rule also applies to tools (uv, GitHub Actions, Docker images, pre-commit tools) by process, not by any automatic check; a younger release is adopted only for a security fix, stated in the pull request. uv 0.13.9 predates the rule and was kept by the owner (W5, E23). pre-commit hooks run locked tools only. CI actions and the Postgres image are pinned (P0-6) but not updated automatically (TD-7); the repository settings require actions pinned to a full commit SHA (owner, E22) | P0 | built (P0-3) |
| guard_bash.py blocks the common forms of `git push` to `main`, and fails closed if it crashes (18 tests in `test_guard_bash.py`). Known gaps: pushes driven only by git configuration, and commands hidden in `bash -c`, `eval` or scripts. A pre-commit pre-push hook (P0-5) refuses a push whose remote ref is `refs/heads/main` and fails closed when the ref is unknown. pre-commit gives the hook only the first ref of a push, so it does **not** catch: deleting `main`; multi-ref pushes (`--all`, `--mirror`, several refspecs, configured `remote.<name>.push` refspecs) where `main` is not first; or pushes whose commits are already on an origin ref while the local view of `main` is stale (no hook runs at all). It is per clone and can be bypassed (`--no-verify`, `SKIP=`, `core.hooksPath`). "Changes reach `main` only through a pull request the owner merges" is a process rule, not an enforced control: there is no branch protection | P0 | built (PR #2; pre-push hook P0-5). A real push to `main` was refused on a throwaway local remote (P0-7, run by the owner); the gaps are accepted as TD-9 (E21) |
| Local PostgreSQL bound to `127.0.0.1` only (checked with `docker port`). The committed passwords in `docker-compose.yml`, `.env.example` and `ci.yml` are throwaway local or CI values: they protect nothing and must never be used anywhere else. Real credentials belong only in the git-ignored secret settings file: `.gitignore` keeps that file out of commits, and gitleaks flags secret-like values in staged changes and in CI history. The database user is a PostgreSQL superuser (see the P2 note in `status.md`). The image digest is pinned in both `ci.yml` and `docker-compose.yml` | P0 | built (P0-4) |
| Claude Code guard hooks (destructive commands, secrets): best-effort only. Each hook was seen firing on chosen examples inside WSL (P0-7; `docs/reports/2026-11-17-P0-7-hook-evidence.md`). Known gaps: commands hidden in `bash -c`, `eval` or scripts get past guard_bash; guard_bash matches text, not intent, so it also blocks harmless mentions (TD-8) and does not stop secret reads made another way; guard_files covers Edit and Write only (TD-3), judges ADRs by the last-fetched `main` (TD-1) and allows any edit containing "Superseded by" (TD-2); its secret patterns are a fixed short list. Pull requests, CI and the owner's review are the backstop (E18) | P0 | built (P0-7) |
| guard_files.py: an ADR is immutable when its number is Accepted on `refs/heads/main` or `refs/remotes/origin/main`; an ADR Accepted only on an unmerged branch may be corrected (deliberately looser than before). Falls back to the working-tree file when git cannot answer; fails closed on a crash (15 tests in `test_guard_files.py`). Known gaps: refs are only as fresh as the last `git fetch`; the guard covers Edit and Write only, so Bash (`sed -i`, scripts) can still change files; the "Superseded by" exemption allows any edit whose new text contains those words; the owner's pull-request review is the backstop | P0 | built (`chore/p0-followups`) |
| Reviewer subagents never modify files or evade hooks: an instruction in each agent file, plus a before-and-after check in `/review` (working tree, HEAD, branch, stash, refs). It cannot see writes outside the repository, to git-ignored paths, or inside `.git/` that change no ref | P0 | built (`chore/p0-followups`) |
| Exact-decimal input limits in the domain (`ExactDecimal`): floats, ints and bools refused in Python and JSON; JSON strings must match a strict ASCII grammar (`-?digits[.digits]`, at most 15 integer digits and 12 decimals; no exponents, whitespace, underscores or non-ASCII digits); Python values must be finite and fit 60 significant digits. Validation messages are fixed text and never echo the input. Arithmetic runs in a context that raises domain errors on rounding, division by zero, overflow, invalid operations and floats. `model_construct` and `model_copy` (which skip validation) are banned in the domain by `test_domain_purity.py` | P1 | built (P1-2); tested in `tests/unit/domain/money/` |
| Parameterised queries only (SQLAlchemy); separate migration and app database roles | P2 | planned |
| Hashed API keys, timing-safe comparison, rate limits, request size limits | P5 | planned |
| RFC 9457 errors without stack traces; debug off by default | P5 | planned |
| Console and staff-only calculator: argon2 passwords, secure session cookies, CSRF tokens, security headers | P6 | planned |
| MCP server: same authentication and limits as the API; read-only tools | P7 | planned |
| Backups, encryption at rest and in transit, monitoring, incident response | P10 | planned |

## Threats to watch (short list)

| Threat | Mitigation |
| --- | --- |
| Wrong tariff data published (the biggest business risk) | Citations, verifier, golden bills, review-and-publish, statuses shown to users |
| Malicious or malformed source documents (PDF parsing) | Parse in isolation; size limits; never execute content; human review of extracted values |
| Secret leakage via commits or logs | gitleaks; guard hooks; log policy |
| Injection (SQL, template) | ORM parameters; auto-escaping templates; no string-built queries |
| API abuse | Keys, rate limits, size limits (P5) |
| Supply-chain compromise | Hash-verified lock; wheels only; 14-day release delay; pip-audit on the whole lock; owner approval for new packages; pre-commit hooks run locked tools only, and the gitleaks image is pinned by digest and runs without network |
| Claude Code acting destructively | Permission rules, guard hooks (including a block on pushing to `main`), pull requests, CI, the owner approving merges. (GitHub branch protection on private repositories needs a paid plan, so it is not relied on.) |
| Tampered or swapped source documents | Source PDFs are committed and identified by SHA-256. A deterministic check of citations against the committed file is planned for P2 |

## POPIA register

| Processing | Personal information? | Phase | Notes and decisions needed |
| --- | --- | --- | --- |
| Bill calculation requests | Potentially (consumption plus any identifying context) | P5 | Stateless; not stored; bodies not logged (ADR-0008) |
| Real bills and prepaid receipts used for testing | Yes, before anonymisation (receipts may show a meter number or token) | P3 | Originals stay in git-ignored `data/private/` on the owner's machine; only figures (amount, kWh, date) enter the repository. **Owner decision before P3:** redact bills before Claude Code reads them, or let Claude Code read the originals (their content is then sent to the model provider) |
| Pilot organisations' API keys and contact details | Yes (names, emails; juristic persons are covered too) | P5 | **Owner decision before P5:** what is stored, where, for how long |
| Staff console accounts | Yes (staff names, emails) | P6 | Minimal fields; hashed passwords |
| Pilot user feedback | Possibly | P9 | Consent and retention to be decided |
| Production logs and analytics | Possibly (IP addresses) | P10 | Retention and minimisation policy needed |

## Needs formal verification before charging money or going to production

- [ ] Legal opinion: may tariff schedules and related municipal and Eskom documents be reused commercially? (Copyright Act s12(8)(a) suggests yes for official administrative texts; confirm.)
- [ ] Legal opinion: terms of use of any website the data comes from.
- [ ] POPIA: register an information officer with the Information Regulator; prepare a PAIA manual.
- [ ] POPIA: privacy notice; lawful basis for each processing activity; retention periods; operator agreements with any hosting provider.
- [ ] POPIA s72: requirements if data is hosted outside South Africa.
- [ ] Terms of service and limitation of liability for calculation errors (Consumer Protection Act and ECTA considerations). Needed before any public calculator (decided at P9).
- [ ] Tax: VAT registration and invoicing requirements once revenue starts (accountant).
- [ ] Trademark and domain checks for the product name.
- [ ] Before the repository is ever made public: review whether the committed municipal and Eskom source PDFs may be republished.
