# TradingAgents and MiroFish Mac Workspace Completion Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the imported 2026-07-11 Windows handoff a verified, usable Mac development workspace for both TradingAgents and MiroFish without enabling credentials, trading, email, schedulers, or autonomous research.

**Architecture:** Keep the USB transfer root as the evidence and operating-context layer. Treat `01_REPO/tradingagents-main` and `01_REPO/mirofish-main` as separate applications with separate dependency environments. Establish only reproducible, lockfile-based development environments and report operational actions that still require explicit human review.

**Tech Stack:** Python/uv, Node/npm, Docker Compose (optional), TradingAgents, MiroFish backend/frontend, Git, SHA-256.

## Global Constraints

- Workspace root: `/Users/corbinfloyd/Documents/TradingAgents`.
- Do not create `.env` files, restore credentials, use broker accounts, send email, resume automations, start n8n, or run autonomous research.
- Do not copy Windows `.venv`, `node_modules`, caches, or excluded Git metadata from the handoff.
- Prefer `uv sync` and the committed lockfiles for Python dependencies; prefer `npm ci` only when its lockfile and runtime version are compatible.
- Preserve the supplied source-state and validation records; do not rewrite evidence packets.
- Treat Python 3.14, Node runtime availability, native compilation, and lockfile resolution as compatibility checks that may produce a documented blocker.

---

### Task 1: Validate and orient the imported transfer

**Files:**
- Read: `00_START_HERE_MAC.md`
- Read: `02_CONTEXT_TODAY_2026-07-11/TODAY_HANDOFF.md`
- Read: `04_SETUP/DEPENDENCIES_AND_SETUP.md`
- Read: `05_VALIDATION/SHA256SUMS.txt`
- Read: `01_REPO/tradingagents-main/results/_context/latest-summary.json`
- Read: `01_REPO/tradingagents-main/results/_context/latest-flags.json`
- Read: `01_REPO/tradingagents-main/results/_context/recent-deltas.md`

- [ ] **Step 1: Confirm the local package count and byte size against the handoff validation.**

Run:

```bash
find /Users/corbinfloyd/Documents/TradingAgents -type f | wc -l
du -sk /Users/corbinfloyd/Documents/TradingAgents
```

Expected: approximately 13,123 transferred source files plus the pre-existing local Git directory, and about 483 MB of transferred content.

- [ ] **Step 2: Verify the supplied SHA-256 manifest from the local copy.**

Run from `/Users/corbinfloyd/Documents/TradingAgents/05_VALIDATION`:

```bash
shasum -a 256 -c SHA256SUMS.txt
```

Expected: every manifest entry reports `OK`; any missing or mismatch is recorded before proceeding.

- [ ] **Step 3: Read only the compact TradingAgents context route.**

Run:

```bash
cd /Users/corbinfloyd/Documents/TradingAgents/01_REPO/tradingagents-main
python3 scripts/automation_context_snapshot.py --help
sed -n '1,240p' results/_context/latest-summary.json
sed -n '1,240p' results/_context/latest-flags.json
sed -n '1,240p' results/_context/recent-deltas.md
```

Expected: no job executes; the copied context establishes the current safe next inspection point.

### Task 2: Map the two repository setup surfaces

**Files:**
- Read: `01_REPO/tradingagents-main/AGENTS.md`
- Read: `01_REPO/tradingagents-main/pyproject.toml`
- Read: `01_REPO/tradingagents-main/uv.lock`
- Read: `01_REPO/tradingagents-main/README.md`
- Read: `01_REPO/mirofish-main/package.json`
- Read: `01_REPO/mirofish-main/package-lock.json`
- Read: `01_REPO/mirofish-main/backend/pyproject.toml`
- Read: `01_REPO/mirofish-main/backend/uv.lock`
- Read: `01_REPO/mirofish-main/README.md`

- [ ] **Step 1: Record installed runtime versions without changing state.**

Run:

```bash
python3 --version
command -v uv && uv --version
command -v node && node --version
command -v npm && npm --version
command -v docker && docker --version
```

Expected: each available dependency reports its version; unavailable tools are explicit blockers, not silently replaced.

- [ ] **Step 2: Inspect manifest-declared runtime and setup commands.**

Run:

```bash
cd /Users/corbinfloyd/Documents/TradingAgents/01_REPO/tradingagents-main
rg -n 'requires-python|\[project\]|\[dependency-groups\]|\[tool\.pytest' pyproject.toml
cd /Users/corbinfloyd/Documents/TradingAgents/01_REPO/mirofish-main
node -e 'const p=require("./package.json"); console.log(JSON.stringify({engines:p.engines,scripts:p.scripts},null,2))'
cd backend
rg -n 'requires-python|\[project\]|\[dependency-groups\]' pyproject.toml
```

Expected: the exact safe install and validation commands can be selected from source manifests rather than from the Windows machine.

### Task 3: Create clean local dependency environments

**Files:**
- Create (generated, untracked): `01_REPO/tradingagents-main/.venv/`
- Create (generated, untracked): `01_REPO/mirofish-main/backend/.venv/`
- Create (generated, untracked): `01_REPO/mirofish-main/node_modules/`

- [ ] **Step 1: Install uv if it is missing, using its official installer and without adding application credentials.**

Run only if `command -v uv` fails:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Expected: `uv --version` reports an installed version. If the installer cannot be verified or network policy blocks it, stop and report the missing tool.

- [ ] **Step 2: Create the TradingAgents environment from its lockfile.**

Run:

```bash
cd /Users/corbinfloyd/Documents/TradingAgents/01_REPO/tradingagents-main
uv sync --frozen
```

Expected: `.venv` is created and dependency resolution uses `uv.lock`; no `.env` is created.

- [ ] **Step 3: Create the MiroFish backend environment from its lockfile.**

Run:

```bash
cd /Users/corbinfloyd/Documents/TradingAgents/01_REPO/mirofish-main/backend
uv sync --frozen
```

Expected: `backend/.venv` is created and dependency resolution uses `backend/uv.lock`.

- [ ] **Step 4: Restore the MiroFish frontend dependencies exactly from its package lock.**

Run:

```bash
cd /Users/corbinfloyd/Documents/TradingAgents/01_REPO/mirofish-main
npm ci --ignore-scripts
cd frontend
npm ci --ignore-scripts
```

Expected: root and `frontend/node_modules` are created from their respective lockfiles without executing third-party lifecycle scripts. Later project-defined build/test scripts remain explicit validation actions.

### Task 4: Run safe health and validation checks

**Files:**
- Read: `05_VALIDATION/FOCUSED_TESTS.txt`
- Read: `03_AUTOMATIONS/AUTOMATION_CATALOG.md`
- Read: `03_AUTOMATIONS/PAUSE_RECEIPT.md`
- Read: `01_REPO/tradingagents-main/pyproject.toml`
- Read: `01_REPO/mirofish-main/package.json`

- [ ] **Step 1: Prove both Python environments can import their own package metadata.**

Run:

```bash
cd /Users/corbinfloyd/Documents/TradingAgents/01_REPO/tradingagents-main
uv run python -c 'import importlib.metadata; print(importlib.metadata.version("tradingagents"))'
cd /Users/corbinfloyd/Documents/TradingAgents/01_REPO/mirofish-main/backend
uv run python -c 'import sys; print(sys.executable)'
```

Expected: package metadata and the backend interpreter print successfully; no server starts.

- [ ] **Step 2: Run manifest-defined static or test commands that do not call brokers, email, schedulers, or live external services.**

Run after inspecting the manifest scripts:

```bash
cd /Users/corbinfloyd/Documents/TradingAgents/01_REPO/tradingagents-main
uv run --group static-analysis ruff check
cd /Users/corbinfloyd/Documents/TradingAgents/01_REPO/mirofish-main
npm run build --if-present
```

Expected: checks either pass or produce a precise compatibility failure to diagnose. Do not run `tradingagents alpaca`, n8n, Docker Compose, background services, or simulation commands.

- [ ] **Step 3: Confirm automation remains paused.**

Run:

```bash
sed -n '1,260p' /Users/corbinfloyd/Documents/TradingAgents/03_AUTOMATIONS/PAUSE_RECEIPT.md
sed -n '1,320p' /Users/corbinfloyd/Documents/TradingAgents/03_AUTOMATIONS/AUTOMATION_CATALOG.md
```

Expected: snapshots show paused source-state only; no Mac scheduler is created or enabled.

### Task 5: Establish provenance and final handoff

**Files:**
- Read: `04_SETUP/SOURCE_STATE.md`
- Read: `04_SETUP/tradingagents-uncommitted.diff`
- Create: `04_SETUP/2026-07-12-mac-setup-status.md`
- Optional Git initialization only after user confirmation: `01_REPO/tradingagents-main/.git/`, `01_REPO/mirofish-main/.git/`

- [ ] **Step 1: Compare the source-state record with the copied repositories.**

Run:

```bash
cd /Users/corbinfloyd/Documents/TradingAgents
sed -n '1,260p' 04_SETUP/SOURCE_STATE.md
sed -n '1,260p' 04_SETUP/tradingagents-diff-stat.txt
```

Expected: report which provenance information was transferred and which Git history was deliberately excluded.

- [ ] **Step 2: Write the Mac setup status with exact results, environment paths, passed checks, and blockers.**

Required sections:

```markdown
# Mac Setup Status

## Transfer Verification
## Repository Layout
## Runtime and Dependency State
## Safe Validation Results
## Explicitly Disabled Operations
## Required Human Decisions Before Any Trading
```

Expected: a future operator can start from the status file without reading raw rollout logs.

- [ ] **Step 3: Keep local Git provenance uncommitted until the user approves the repository boundary.**

Run:

```bash
git -C /Users/corbinfloyd/Documents/TradingAgents status --short --branch
```

Expected: the transfer root remains a local import workspace. Initialize independent repository histories or make import commits only after the user explicitly chooses the history layout.

## Plan Self-Review

- Scope coverage: includes USB verification, TradingAgents, MiroFish backend/frontend, clean environments, safe validation, automation safety, source provenance, and local handoff.
- No placeholders: every command and expected result is stated; commands that could cause financial or external side effects are prohibited.
- Boundary consistency: generated environments remain local/untracked; evidence stays at the transfer root; the two application roots remain independent.
