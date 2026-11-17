# Coding standards

These apply to all code in `src/` and `tests/`. Tools enforce most of them; reviewers check the rest.

## Correctness first

- **Money is `Decimal`**, constructed from strings. No `float` in money, tariff or billing code. Every quantisation names its `RoundingPolicy`.
- **No invented data.** No tariff value, threshold, VAT rate or effective date in code. Data lives in tariff records with a citation and a status. Test fixtures live under `tests/` and are clearly marked as fixtures.
- **Refuse rather than guess.** Missing or ambiguous data raises a typed error or produces an explicit warning. Never default silently.
- **The domain is pure:** no I/O, no clock (`datetime.now()`), no randomness, no environment access in `munisense.domain`. Pass time and data in.

## Types and structure

- `mypy --strict` passes. No `Any` in the domain. `# type: ignore` needs a specific error code and a comment.
- Pydantic models at system boundaries (API, ingestion drafts, settings). Inside the domain, Pydantic v2 models in **strict mode only**, with a Decimal type that rejects floats; plain frozen dataclasses are fine where no validation is needed (ADR-0004).
- Functions are short (aim for under about 40 lines) and do one thing; modules have one job.
- Names describe the domain (`block_threshold_kwh`, not `t1`). Use the glossary's terms.
- No copy-paste between suppliers. Differences are data or policy.
- No speculative generality: build what the current phase needs.

## Errors and logging

- Domain errors are typed exceptions in each module's `errors.py`. The API maps them to RFC 9457 problem responses with stable codes.
- Never catch-all-and-ignore. Catching `Exception` is allowed only at the top-level boundary, where it is logged and re-raised or converted.
- Logs are structured (structlog), with no request bodies, secrets or personal information.

## Style

- ruff formats and lints; its configuration lives in `pyproject.toml`. The `format_lint.py` hook runs it after every edit.
- Docstrings on public functions and classes: what it does, and anything surprising. No restating the code.
- Comments explain *why*, not *what*.

## Dependencies

- Every new dependency needs the owner's approval: purpose, licence (MIT, BSD or Apache preferred; no GPL/AGPL in the service without an ADR), maintenance status and size.
- Runtime dependencies are added only in the phase that needs them.
- `uv.lock` is committed. No `pip install`.

## Git

- One task, one branch, one pull request. Conventional Commits.
- Never `--no-verify`, never force-push, never rewrite main.
- Pull request description: what changed, why, how it was verified, what was not verified, and decisions made.
