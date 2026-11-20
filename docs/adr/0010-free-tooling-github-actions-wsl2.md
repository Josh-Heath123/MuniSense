# ADR-0010: Free tooling, GitHub Actions CI and WSL2 for development

- **Status:** Accepted. Its "Protecting `main`" point: Superseded by ADR-0014; everything else in this ADR stands.
- **Date:** 2026-11-17 (proposed); 2026-11-17 (accepted by the owner)
- **Deciders:** Josh Heath (owner)

## Context

The brief requires free resources until the product shows commercial promise. Work must be independently checked on a clean machine, not just on the developer's laptop. The owner's computer runs Windows.

## Decision

- **Code hosting:** a private GitHub repository on the free plan. GitHub Free includes 2,000 Actions minutes a month for private repositories, which is ample at this stage.
- **CI:** GitHub Actions (`ubuntu-latest`, a `postgres:17` service container, uv installed with `astral-sh/setup-uv`) runs `uv run poe verify` and `uv run poe audit` on every pull request and every push to main. Nothing merges red.
- **Protecting `main`:** GitHub branch protection on a private repository needs a paid plan, so it is not relied on. Instead, `guard_bash.py` will block Claude Code from pushing to `main` (task P0-9); changes reach `main` only through a pull request that the owner merges.
- **Development machine:** Windows with WSL2 (Ubuntu 24.04, as a non-root user) and Docker Desktop with WSL integration. Claude Code, git, uv and Docker commands run inside WSL2. Docker Desktop is free for personal use and for businesses under its size thresholds.
- **Repository location:** `C:\MuniSense\MuniSense`, worked on from WSL2 at `/mnt/c/MuniSense/MuniSense`. This lets the architect chat in the Claude desktop app read the repository directly. Linux file access to `C:` is slower, so the Python virtual environment lives on the Linux side (`UV_PROJECT_ENVIRONMENT=$HOME/.venvs/munisense`). If speed becomes a real problem, move the working copy into the Linux file system and accept that the architect chat then sees only what is pasted. To watch this, every gate report states how long `uv run poe check` takes.
- **Tools:** uv, ruff, mypy, pytest, Hypothesis, Schemathesis, mutmut, import-linter, pre-commit, gitleaks and pip-audit. All are open source.

## Consequences

- Good: identical Linux environment locally and in CI; R0 cost; independent verification.
- Bad: requires the owner's GitHub account (external account; owner action). Minutes are limited, so keep CI lean and watch usage.
- Cost: R0 within limits. Exceeding Actions minutes or Docker Desktop's free-use terms would cost money, so check before either could happen.
- Reversibility: easy. Git is portable and CI config is small.

## Alternatives considered

| Option | Why not |
| --- | --- |
| No CI, local checks only | No independent proof; "works on my machine" |
| GitLab CI | Fine too, but GitHub has better Claude Code and `gh` integration |
| Native Windows development | Hooks and tooling differ from CI and production; Docker works better from WSL2 |
| Paid CI or hosting | Not allowed before the Phase 9 decision |
| Docker Engine inside WSL instead of Docker Desktop | Apache-licensed with no size threshold, but Docker Desktop works now. Revisit if the business approaches Docker Desktop's free-use limits |
