# Mac Setup Status

Completed: 2026-07-12

## Transfer Verification

- USB source: `/Volumes/Untitled/TRADINGAGENTS_MAC_TRANSFER`
- Local workspace: `/Users/corbinfloyd/Documents/TradingAgents`
- Transfer copied with `rsync`.
- The supplied SHA-256 manifest contains Windows backslashes and CRLF line endings. After normalizing those two transport details for verification, all `13,122` manifest entries passed (`hash_exit=0`).
- The transfer contained no credential-bearing `.env` files. During the later setup pass, local `.env` files appeared in both app roots; their values were not printed. The only `.pem` files found are generated CA bundles inside the new virtual environments (`certifi`).

## Repository Layout

- TradingAgents: `/Users/corbinfloyd/Documents/TradingAgents/01_REPO/tradingagents-main`
- MiroFish: `/Users/corbinfloyd/Documents/TradingAgents/01_REPO/mirofish-main`
- MiroFish backend: `/Users/corbinfloyd/Documents/TradingAgents/01_REPO/mirofish-main/backend`
- MiroFish frontend: `/Users/corbinfloyd/Documents/TradingAgents/01_REPO/mirofish-main/frontend`
- Compact handoff context: `/Users/corbinfloyd/Documents/TradingAgents/02_CONTEXT_TODAY_2026-07-11`
- Paused automation snapshots: `/Users/corbinfloyd/Documents/TradingAgents/03_AUTOMATIONS`

## Runtime and Dependency State

- Python 3.13.14 installed for TradingAgents; environment at `01_REPO/tradingagents-main/.venv`.
- Python 3.12.13 installed for MiroFish backend; environment at `01_REPO/mirofish-main/backend/.venv`.
- `uv sync --frozen --python 3.13` completed for TradingAgents.
- `uv sync --frozen --python 3.12` completed for MiroFish backend.
- `npm ci --ignore-scripts` completed in MiroFish root and `frontend/`.
- Node.js 22.22.3 and npm 10.9.8 are available.
- Docker is not installed; Docker deployment remains optional and was not attempted.
- npm reported 2 critical audit findings in the MiroFish root workspace and 5 findings (2 moderate, 3 high) in the frontend. Lockfiles were not changed with `npm audit fix`.

## Safe Validation Results

- TradingAgents package import/version: passed (`0.2.5`).
- TradingAgents focused tests: passed, `4 passed in 0.21s`.
- MiroFish backend import: passed on Python 3.12.
- MiroFish backend tests: passed, `40 passed in 5.07s`.
- MiroFish frontend production build: passed with Vite. Warnings: one dynamic/static import split warning and one large chunk warning.
- TradingAgents Ruff: failed with 25 existing lint findings across tests and source prompt/import formatting. No automatic fixes were applied.

## Explicitly Disabled Operations

- No `.env` or API credentials were created or restored.
- Presence-only checks now find local TradingAgents and MiroFish `.env` files. TradingAgents contains local Alpaca variable names; MiroFish currently contains only a management-key variable. Values were not printed, copied, or used by the Docker/n8n setup. No broker command was run.
- No Alpaca check, preview, submit, or live/paper order command was run.
- No n8n runner, scheduler, background service, Docker Compose stack, email delivery, or autonomous research/simulation was started.
- The handoff pause receipt records `14/14` Codex automations paused and zero orders/email invoked.

## Docker and n8n

- Docker Desktop installed at `/Applications/Docker.app` (4.81.0).
- Docker daemon verified healthy: Engine 29.6.1, Compose v5.2.0, context `desktop-linux`.
- User-local CLI links are available through `~/.local/bin/docker` and the Docker credential helpers; the privileged `/usr/local/bin` symlink step was not needed.
- n8n is running from the pinned `n8nio/n8n:2.29.10` image at `http://localhost:5678`.
- Persistent n8n volume: `tradingagents-main_n8n_data`.
- Twelve source-controlled observer/evaluation workflows are imported and remain inactive/manual.
- Duplicate dashboard tags in the source JSON caused n8n 2.29.10's bulk importer to reject the batch, so temporary tagless copies were used for import; source workflow files were not modified.
- The allowlisted runner is persistent through `~/Library/LaunchAgents/com.tradingagents.n8n-runner.plist`, bound to `127.0.0.1:8765`, with a clean child environment. It reports 24 jobs and zero submit-capable jobs.
- n8n reaches the runner through `host.docker.internal:8765` and both host and container health probes pass.
- First-run n8n owner account setup remains a one-time browser action at `http://localhost:5678`; no account password or API key was created by setup.
- Browser verification on 2026-07-12: the signed-in n8n Usage and plan page reports `Community Edition — Registered`. The activation token was not copied, printed, or saved in the workspace.
- Docker Desktop's n8n image logs a Python task-runner warning because the image lacks Python; the JavaScript observer workflows work and no deprecated runner variable remains in the compose file.

## Required Human Decisions Before Any Trading

1. Review and manually populate provider/broker credentials from the sanitized templates only if needed.
2. Review account mode, risk envelope, and live-gate state on this Mac.
3. Resolve or consciously accept the existing Ruff findings and npm audit findings.
4. Keep the preserved automation snapshots paused until each Mac-side job is independently reviewed and recreated.
5. Choose whether to initialize separate Git histories for the two imported repositories; the transfer root remains uncommitted on local `master`.

6. Open `http://localhost:5678` once and create the local n8n owner account. This is local-only; it is not an n8n Cloud account.

## Next Inspection Point

Use the saved plan at `/Users/corbinfloyd/Documents/TradingAgents/04_SETUP/2026-07-12-mac-workspace-completion-plan.md` for any follow-up hardening. The workspace is ready for development and safe local tests, but not authorized or configured for trading operations.
