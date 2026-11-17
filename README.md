# MuniSense

Exact, source-cited South African municipal utility bill calculations, for software and AI agents.

> **Status:** Phase 0 (foundation). No application code yet. See [`docs/status.md`](docs/status.md).

## What it will do

- Store municipal and Eskom electricity tariffs as versioned data. Every value is linked to its official source document, page and verification status.
- Calculate a bill for a supplier, tariff, period and consumption, returning line items, VAT, assumptions and warnings. For prepaid meters, calculate the kWh a purchase buys, given earlier purchases that month.
- Answer "what did we calculate on date X" exactly, even after a tariff is corrected retroactively.
- Serve all of this through a REST API, a staff curation console with a staff-only calculator and, later, an MCP server.

## Set up (Windows with WSL2)

Everything runs inside WSL2 (Ubuntu), so local development matches CI and future hosting.

1. **WSL2.** In PowerShell as administrator, run `wsl --install -d Ubuntu-24.04` (the project uses Ubuntu 24.04 with a normal, non-root user), restart, then open "Ubuntu" from the Start menu and create your Linux user. Skip this if you already have WSL2 with Ubuntu (`wsl -l -v` shows `VERSION 2`).
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
4. **Claude Code inside Ubuntu:** `curl -fsSL https://claude.ai/install.sh | bash`, then `claude --version`.
5. **This repository** lives at `C:\MuniSense\MuniSense`, so the architect chat in the Claude desktop app can read it. Work on it from Ubuntu at `/mnt/c/MuniSense/MuniSense`, and use git from Ubuntu (not Windows git) for this repository. Linux reaches files on `C:` slowly, so the Python environment is kept on the Linux side. Add this shortcut once:
   ```bash
   echo "alias munisense='cd /mnt/c/MuniSense/MuniSense && export UV_PROJECT_ENVIRONMENT=\$HOME/.venvs/munisense'" >> ~/.bashrc
   exec $SHELL
   ```
   Then start every session with `munisense` followed by `claude`.

## Run

Phase 0 creates these commands:

```bash
docker compose up -d db     # PostgreSQL 17
uv sync                     # install locked dependencies
uv run poe check            # lint, types, fast tests
uv run poe verify           # everything CI runs (offline)
uv run poe audit            # dependency vulnerability audit (needs network)
```

## How this project is built

Claude Code develops it under the rules in [`CLAUDE.md`](CLAUDE.md). Decisions are recorded in [`docs/adr/`](docs/adr/), and phases and gates are in [`docs/roadmap.md`](docs/roadmap.md). Nothing in phases 0 to 8 costs money.

## Licence

Proprietary. All rights reserved. (No licence decision has been made; ask the owner.)
