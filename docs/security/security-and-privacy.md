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
| Secret scanning (gitleaks) in pre-commit and CI | P0 | planned |
| Dependency vulnerability audit (pip-audit, `uv run poe audit`) in CI on every run | P0 | planned |
| guard_bash.py blocks the common forms of `git push` to `main`, and fails closed if it crashes (18 tests in `test_guard_bash.py`). Known gaps: pushes driven only by git configuration, and commands hidden in `bash -c`, `eval` or scripts. A pre-commit pre-push hook (P0-5) is planned to narrow the gap; client-side git hooks can be bypassed (`--no-verify`, `core.hooksPath`). "Changes reach `main` only through a pull request the owner merges" is a process rule, not an enforced control: there is no branch protection | P0 | built (PR #2); pre-push hook planned (P0-5) |
| Claude Code guard hooks (destructive commands, secrets) | P0 | in starter pack, to be proven in P0-7 |
| guard_files.py: an ADR is immutable when its number is Accepted on `refs/heads/main` or `refs/remotes/origin/main`; an ADR Accepted only on an unmerged branch may be corrected (deliberately looser than before). Falls back to the working-tree file when git cannot answer; fails closed on a crash (15 tests in `test_guard_files.py`). Known gaps: refs are only as fresh as the last `git fetch`; the guard covers Edit and Write only, so Bash (`sed -i`, scripts) can still change files; the "Superseded by" exemption allows any edit whose new text contains those words; the owner's pull-request review is the backstop | P0 | built (`chore/p0-followups`) |
| Reviewer subagents never modify files or evade hooks: an instruction in each agent file, plus a before-and-after check in `/review` (working tree, HEAD, branch, stash, refs). It cannot see writes outside the repository, to git-ignored paths, or inside `.git/` that change no ref | P0 | built (`chore/p0-followups`) |
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
| Supply-chain compromise | Locked dependencies; pip-audit; owner approval for new packages |
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
