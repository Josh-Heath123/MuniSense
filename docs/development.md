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
uv sync                     # install locked dependencies
uv run poe db-bootstrap     # once per volume, after uv sync: the two roles and the munisense schema
uv run pre-commit install   # git hooks: file checks, ruff, gitleaks; refuses a push to main (needs Docker)
uv run poe fmt              # format and auto-fix
uv run poe check            # lint, types, fast tests (the Stop hook runs this)
uv run poe demo             # the README's example bill, from the real data and engine
uv run poe publish <draft> --reason "..." [--supersedes <id>] [--check]
                            # publish a draft (ADR-0012); --check runs every check, writes nothing
uv run poe publish --withdraw <id> --reason "..."   # withdraw a publication
uv run poe publications-check [--base <ref> [--pull-request]]   # what CI checks about publications (P2-9)
uv run poe verify           # everything CI runs (offline)
uv run poe audit            # dependency vulnerability audit (needs network)
uv run mutmut run           # mutation testing of domain.billing (slow; see docs/quality/mutation-p1-15.md)
```

## Database settings

Settings are read from the process environment (`src/munisense/platform/settings.py`). Only docker compose reads the local settings file; Python does not, so if you change the port or a password there, export the matching `MUNISENSE_*` URLs too. While `MUNISENSE_ENVIRONMENT` is `local` (the default, which includes CI), every host must be loopback and unset URLs use the published local defaults. Any libpq `PG*` environment variable is refused. Run `uv run poe db-bootstrap` once per volume before the database tests (`tests/integration`, marked `db`). They refuse any database whose name does not end in `_test` and connect as:

- `munisense_app`: reads only (`SELECT`); this is what the application uses;
- `munisense_migration`: owns the `munisense` schema; migrations and the loader use it.

Neither is a superuser. Only the bootstrap's own tests (`tests/integration/bootstrap`, also marked `db_admin`) connect as the local superuser. Every connection uses `gssencmode=disable` and `require_auth=scram-sha-256`.

`CLAUDE.md` has the rules for working on the code, and `docs/README.md` maps every document.

## Publishing

`uv run poe publish` turns a draft into an immutable publication under `data/tariffs/` or `data/vat/` (ADR-0012). It refuses, listing every reason, unless the draft sits in its folder, every citation passes the citation check (or is honestly `no_text_layer`), every `Verified` value agrees with the computed text check, and the version overlaps no current publication of the same tariff that it does not supersede. Record time is the moment you run it. Run it with `--check` first; then run it for real, commit the new file together with the removed draft, and open a pull request. A correction is `--supersedes <id>`; if it moves the effective date into another tariff year, its draft sits in that year's folder. A mid-year amendment is two publications in one pull request, the shortening revision first. `--by <handle>` records who published (default `owner`; a pseudonymous handle, never a name). The command reads `data/` under the working directory. Exit codes: 0 published (or would publish), 1 refused, 2 wrong arguments, 3 published but the draft could not be removed (remove it by hand). Never edit a published file.
