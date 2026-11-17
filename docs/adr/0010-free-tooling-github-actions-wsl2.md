# ADR-0010: Free tooling, GitHub Actions CI and WSL2 for development

- **Status:** Proposed
- **Date:** 2026-11-17
- **Deciders:** Malcolm Heath (owner)

## Context

The brief requires free resources until the product shows commercial promise. Work must be independently checked on a clean machine, not just on the developer's laptop. The owner's computer runs Windows.

## Decision

- **Code hosting:** a private GitHub repository on the free plan. GitHub Free includes 2,000 Actions minutes a month for private repositories, which is ample at this stage.
- **CI:** GitHub Actions runs `uv run poe verify` with a PostgreSQL service container on every pull request and every push to main. Nothing merges red.
- **Development machine:** Windows with WSL2 (Ubuntu) and Docker Desktop with WSL integration. Claude Code, git, uv and Docker commands run inside WSL2. Docker Desktop is free for personal use and for businesses under its size thresholds.
- **Repository location:** `C:\MuniSense\MuniSense`, worked on from WSL2 at `/mnt/c/MuniSense/MuniSense`. This lets the architect chat in the Claude desktop app read the repository directly. Linux file access to `C:` is slower, so the Python virtual environment lives on the Linux side (`UV_PROJECT_ENVIRONMENT=$HOME/.venvs/munisense`). If speed becomes a real problem, move the working copy into the Linux file system and accept that the architect chat then sees only what is pasted.
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
