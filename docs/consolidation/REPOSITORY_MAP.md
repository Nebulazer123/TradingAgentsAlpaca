# TradingAgents Repository Map

## Canonical root

`/Users/corbinfloyd/Documents/TradingAgents`

The root is simultaneously the Git checkout, Python application root, Codex
workspace, Mac automation root, runtime evidence store, and recovery catalog.

## Authored implementation

The consolidation inventory classified 234 authored source files, 100 test
files, 88 documentation files, and 39 configuration files. The Python package
architecture contains 189 files under `tradingagents/`, with the largest domains
in research, brokers, orchestration, policy, agents, dataflows, graph, execution,
evaluation, schemas, and storage.

| Domain | Primary paths | Main responsibility |
| --- | --- | --- |
| Command surface | `cli/main.py` | Typer commands and subsystem composition |
| Agent workflow | `tradingagents/graph/`, `tradingagents/agents/` | Analyst-to-researcher-to-trader-to-risk workflow |
| Broker/supervisor | `tradingagents/brokers/` | Account state, decisions, Alpaca calls, paper competition |
| Policy/execution | `tradingagents/policy/`, `tradingagents/execution/` | Current authority evaluation, control state, locks, reconciliation |
| Research | `tradingagents/research/`, `tradingagents/dataflows/` | Evidence collection, routing, provenance, provider fallback |
| Orchestration | `tradingagents/orchestration/`, `n8n/`, `config/n8n*` | Allowlisted local jobs and n8n adapter |
| Evaluation | `tradingagents/evals/` | Calibration, outcomes, source quality, telemetry |
| Persistence | `tradingagents/storage/`, `results/` | Durable local state and generated packets |
| Verification | `tests/` | Unit, integration, policy, orchestration, and CLI checks |

The code graph recorded 8,147 nodes and 39,974 edges for the full canonical
checkout. Within `tradingagents/`, it recorded 2,582 nodes and 8,272 edges. Key
cross-package boundaries include research into dataflows, graph into agents,
brokers into policy, and execution into brokers.

## Operational entrypoints

| Need | Entrypoint |
| --- | --- |
| General CLI | `.venv/bin/python -m cli.main --help` |
| Alpaca commands | `.venv/bin/python -m cli.main alpaca --help` |
| Context refresh | `.venv/bin/python scripts/automation_context_snapshot.py --write` |
| n8n runner | `.venv/bin/python -m tradingagents.orchestration.n8n_runner` |
| Mac scheduled job | `scripts/mac/ta_job.sh <job>` |
| launchd installation | `scripts/mac/install_launchd.sh` |
| Focused tests | `.venv/bin/python -m pytest <test paths> -q` |
| Static checks | `.venv/bin/ruff check cli tradingagents scripts tests` |

The n8n allowlist currently contains 24 local jobs. Its service launch path is
the canonical root and its local health endpoint is `127.0.0.1:8765/health`.

## Runtime evidence

`results/` is generated state rather than application source. The compact files
under `results/_context/` summarize larger packet families and name the raw file
to open when a drilldown flag is present. The newest preserved packet families
at consolidation time were outbox, premarket brief, hourly supervisor,
self-heal, safety sentinel, automation health, preopen validation, policy,
execution-board, research evidence, and loss-review evidence.

The current live-control file is `results/policy/live_control.json`. At the
consolidation checkpoint it recorded `frozen=true`. Runtime claims should be
refreshed from disk because operational state changes independently of Git.

## Local and generated material

The full file classification also found 16,185 runtime/result files, 20,938
dependency-environment files, 391 cache files, 713 Git metadata files, and
40,727 archive files. These categories explain the size of the directory while
keeping the authored implementation relatively navigable.

- `.venv/` is the working Mac Python environment.
- `.env` is the local credential file and retains mode `0600`.
- `results/` contains current and historical generated evidence.
- cache directories accelerate local tools and tests.
- `archive/` contains recovery material and consolidation manifests.

## Recovery catalog

`archive/inactive-checkouts/` contains complete dated archives of the former
autonomous-firm worktree, fable worktree, and standalone public clone. A Git
bundle preserves the public clone refs and history. `SHA256SUMS.txt` verifies the
archive payloads, and its README records restoration mappings.

`archive/windows-transfer-2026-07-11/` groups the imported Windows context,
automation snapshots, setup material, validation artifacts, and MiroFish copy.
It is historical reference material supporting the Mac runtime.

`archive/consolidation-manifests/2026-08-10/` records pre-move and post-move file
inventories, hashes, Git state, runtime state, path references, credential
metadata, active-config backups, and the authored-text review ledger.

## Documentation order

1. `START_HERE.md`
2. `AGENTS.md`
3. `CONTEXT_ROUTER.md`
4. This repository map
5. `REPO_OVERVIEW.md` and `TRADING_METHODS_AND_AUTOMATIONS.md`
6. Topic-specific files under `docs/`
7. Historical plans, reports, and archived transfer material
