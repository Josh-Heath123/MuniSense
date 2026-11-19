# Development setup

This page describes how the owner's machine is set up. The portable quick start is in the [README](../README.md#quick-start). This page adds the Windows and WSL2 details, and the commands that need Docker.

## Windows with WSL2

Everything runs inside WSL2 (Ubuntu), so local development matches CI and future hosting.

1. **WSL2.** In PowerShell as administrator, run `wsl --install -d Ubuntu-24.04`. The project uses Ubuntu 24.04 with a normal, non-root user. Restart, then open "Ubuntu" from the Start menu and create your Linux user. Skip this if you already have WSL2 with Ubuntu (`wsl -l -v` shows `VERSION 2`).
2. **Docker Desktop.** Install it from docker.com. In Settings, open Resources, then WSL integration, and enable your Ubuntu distribution. Docker Desktop is free for personal use and small businesses.
3. **Tools inside Ubuntu:**
   ```bash
   sudo apt update && sudo apt install -y git unzip build-essential gh
   curl -LsSf https://astral.sh/uv/install.sh | sh
   exec $SHELL
   uv python install 3.13
   git config --global user.name "Your Name"
   git config --global user.email "you@example.com"
   gh auth login
   gh auth setup-git
   ```
   In this repository, commits use the owner's GitHub noreply address, set with `git config user.email` inside the repository. GitHub refuses pushes that would publish a private address.
4. **Claude Code inside Ubuntu:** `curl -fsSL https://claude.ai/install.sh | bash`, then `claude --version`.
5. **This repository** lives at `C:\MuniSense\MuniSense`, so the architect chat in the Claude desktop app can read it. Work on it from Ubuntu at `/mnt/c/MuniSense/MuniSense`, and use git from Ubuntu (not Windows git) for this repository. Linux reaches files on `C:` slowly, so the Python environment is kept on the Linux side. Add this shortcut once:
   ```bash
   echo "alias munisense='cd /mnt/c/MuniSense/MuniSense && export UV_PROJECT_ENVIRONMENT=\$HOME/.venvs/munisense'" >> ~/.bashrc
   exec $SHELL
   ```
   Then start every session with `munisense` followed by `claude`.
6. **Optional system tools** for documents and assets:
   - `poppler-utils` renders scanned PDF pages (E30).
   - `librsvg2-bin` renders the README assets (E44).

   Install both with `sudo apt install poppler-utils librsvg2-bin`.

## Commands

```bash
cp .env.example .env        # optional: local settings (the defaults work)
docker compose up -d db     # PostgreSQL 17: databases munisense_dev and munisense_test (needed from P2)
uv run poe db-bootstrap     # once per volume: the app (read-only) and migration roles, and the munisense schema
uv sync                     # install locked dependencies
uv run pre-commit install   # git hooks: file checks, ruff, gitleaks; refuses a push to main (needs Docker)
uv run poe fmt              # format and auto-fix
uv run poe check            # lint, types, fast tests (the Stop hook runs this)
uv run poe demo             # the README's example bill, from the real data and engine
uv run poe verify           # everything CI runs (offline)
uv run poe audit            # dependency vulnerability audit (needs network)
uv run mutmut run           # mutation testing of domain.billing (slow; see docs/quality/mutation-p1-15.md)
```

## Database settings

Settings are read from the environment (`src/munisense/platform/settings.py`); `.env.example` lists them. While `MUNISENSE_ENVIRONMENT` is `local` (the default, which includes CI), unset URLs use the published local defaults. The database tests (`tests/integration`, marked `db`) prepare the roles themselves and refuse any database whose name does not end in `_test`. They connect as:

- `munisense_app`: reads only (`SELECT`); this is what the application uses;
- `munisense_migration`: owns the `munisense` schema; migrations and the loader use it.

Neither is a superuser. Every connection disables GSSAPI encryption and refuses libpq service lookups.

`CLAUDE.md` has the rules for working on the code, and `docs/README.md` maps every document.
