# MiroFish Launch Path Integrity Audit

Generated: 2026-06-03
Updated after approved Stage 03 run: 2026-06-03

Scope: launch-path integrity, runtime context visibility, telemetry, ReportAgent recovery, and TradingAgents handoff readiness for real Stage 03 `sim_974459649906`. No email was sent and no Google Drive update was made.

## Execution Thesis

The real run could only be trusted if the actual `/api/simulation/start` path, not just docs or seed files, proved that active agents received the predictive-quality plan at runtime. The launch path had to guarantee scheduled event beats, broad-market causal context, forecast ballot markers, `max_rounds=30`, and Zep graph memory for `mirofish_4a9df9ae8b184878`.

The approved Stage 03 run is now complete. The canonical data sources are the action logs, `run_state.json`, post-run telemetry, the Stage 04 report, and the TradingAgents handoff artifact.

## Checklist

- [x] Run starting git checkpoint and identify whether this folder is a repo.
- [x] Trace `/api/simulation/start` to `SimulationRunner.start_simulation` to `run_parallel_simulation.py`.
- [x] Verify whether `event_config.scheduled_events` reaches both Twitter/common and Reddit/boost agents.
- [x] Patch the smallest runtime path so both lanes receive per-round event context before LLM actions.
- [x] Lock the real launch to 30 rounds while preserving explicit stress caps.
- [x] Guarantee graph memory is enabled by launch payload/default and that the correct graph id reaches the updater.
- [x] Add telemetry-visible `round_event` / `event_beat_id` markers.
- [x] Verify broad-market context is runtime-visible: macro/rates, Treasury auctions, oil/geopolitics, AI/semiconductor catalysts, options-expiration mechanics, institutional liquidity response, and broker/platform rollout differences.
- [x] Run capped stress/no-run launch checks before the real run.
- [x] Start the real Stage 03 run only after explicit approval.
- [x] Monitor the real run through 30 rounds.
- [x] Run post-run telemetry and generate the Stage 04 ReportAgent report.
- [x] Patch ReportAgent/Zep error handling found during Stage 04.
- [x] Prepare downstream TradingAgents advisory handoff with no execution authority.

## Git Checkpoint

- `git status --short` returned `fatal: not a git repository (or any of the parent directories): .git`.
- `IS_GIT_REPO=0`.
- Because this folder is not a git repo, the changed-file list below is the manual checkpoint trail.

## Real Launch Path

1. Frontend `frontend/src/components/Step3Simulation.vue` sends `POST /api/simulation/start` with `simulation_id`, `platform: parallel`, `force: true`, and `enable_graph_memory_update: true`.
2. API `backend/app/api/simulation.py` validates state, resolves or validates `graph_id`, defaults graph memory on when the simulation/project has a graph, and forwards launch controls.
3. Service `backend/app/services/simulation_runner.py` loads `simulation_config.json`, resolves effective max rounds, creates `ZepGraphMemoryUpdater` when enabled, persists launch controls to `run_state.json`, and spawns `backend/scripts/run_parallel_simulation.py --config ... --max-rounds 30`.
4. Runner `backend/scripts/run_parallel_simulation.py` runs Twitter and Reddit in parallel. At each round it injects a compact runtime event context post before active `LLMAction()` calls, then logs both the context post and subsequent agent actions with `round_event` metadata.
5. Monitor reads `twitter/actions.jsonl` and `reddit/actions.jsonl`; graph memory receives action dictionaries when enabled.
6. `docs/mirror_fish/mirofish_postrun_telemetry.py` extracts round/event markers, ballot rounds, ticker/category mentions, causal counts, and Stage 05 interview targets after the run.
7. Stage 04 ReportAgent reads local action logs/telemetry plus graph tools. When Zep is rate-limited or unavailable, local evidence now keeps report generation usable.

## Approved Real Launch Payload

```json
{
  "simulation_id": "sim_974459649906",
  "platform": "parallel",
  "force": true,
  "max_rounds": 30,
  "enable_graph_memory_update": true,
  "graph_id": "mirofish_4a9df9ae8b184878"
}
```

Equivalent runner command spawned by the service:

```powershell
python backend\scripts\run_parallel_simulation.py --config backend\uploads\simulations\sim_974459649906\simulation_config.json --max-rounds 30
```

The API/service path was used because it starts graph memory through `SimulationRunner` and persists launch controls.

## Real Run Result

- Simulation: `sim_974459649906`
- Project: `proj_8ece728e49fe`
- Graph: `mirofish_4a9df9ae8b184878`
- Start time: `2026-06-03T07:35:53.452127`
- Completion evidence: `run_state.json`, action logs, API status, telemetry, and Stage 04 report artifacts.
- Total rounds requested: 30
- Total rounds completed: 30
- Twitter/common actions: 700 generated actions, 764 action-log rows including markers.
- Reddit/boost actions: 1025 generated actions, 1089 action-log rows including markers.
- Total generated actions: 1725.
- Unique active agents in telemetry: 657.
- Stage 04 report: `backend/uploads/reports/report_b4f2d893b2a2/full_report.md`.
- Post-run telemetry: `backend/uploads/simulations/sim_974459649906/postrun_telemetry.json` and `.md`.

## Four Launch-Honor Gaps

| Gap | Result | Evidence |
| --- | --- | --- |
| Event beats prepared but not runtime-visible | Fixed and verified in the real run | Runner publishes per-round context for both Twitter and Reddit before active agents act. Action logs include `round_event` metadata through round 30. |
| Round count / launch parameter mismatch | Fixed and verified in the real run | Launch payload used `max_rounds=30`; service persisted `max_rounds_applied=30`, `max_rounds_source=request`; both lanes ended at 30 rounds. |
| Zep graph memory not guaranteed on | Fixed as a launch guarantee; runtime ingestion was partial | API/service enabled graph memory with graph id `mirofish_4a9df9ae8b184878`. Updater started and stopped for the real sim. Final updater summary: `items_sent=990`, `failed=147`, `skipped=2`. |
| Predictive-quality requirements only in docs/report | Fixed for high-value runtime items | Event beat map, forecast ballots, causal hints, options/microstructure brief, live context patch, broker/account segmentation cues, control branch, TradingAgents advisory purpose, and broad-market context are in per-round runtime context posts. |

## Runtime Visibility Matrix

| Requirement | Twitter/common | Reddit/boost | Notes |
| --- | --- | --- | --- |
| Event beat map | runtime-visible | runtime-visible | Per-round context post; logged as `round_event`. |
| State variables | runtime-visible | runtime-visible | Per-round state-variable focus plus all-state metadata. |
| Forecast ballots | runtime-visible | runtime-visible | Rounds 3, 6, 11, 18, 22, 25, and 30 request ballot-like branch probability updates. Telemetry detected 144 ballot-like actions. |
| Causal attribution | runtime-visible | runtime-visible | Agents compare PDT effects against macro/rates, Treasury auctions, oil/geopolitics, AI/semis, options expiry, broker friction, and institutional liquidity. |
| Options/microstructure brief | runtime-visible | runtime-visible | Includes 0DTE, SPY/QQQ/TSLA/AAPL, physical vs cash-settled confusion, assignment/exercise, IV/gamma/OI/volume/spread/liquidity, market-maker/dealer/ETF desk response. |
| Live context patch | runtime-visible | runtime-visible | June 4-13 window, fragmented rollout, macro gates, AI/semi, oil/geopolitics, advisory purpose. |
| Broker/account segmentation | runtime-visible | runtime-visible | Cash vs margin, equity buckets, options approval, API/bot access, broker rollout differences, buying-power/margin confusion. |
| Broad-market context | runtime-visible | runtime-visible | Macro/rates, Treasury auctions, oil/geopolitics, AI/semiconductor catalysts, options-expiration mechanics, institutional liquidity response, broker/platform rollout differences. |
| Validation thresholds | mostly report/telemetry | mostly report/telemetry | Agents receive branch/false-attribution cues; detailed schema stays post-run. |
| Control/counterfactual branch | runtime-visible | runtime-visible | Every round asks agents to compare against no meaningful retail-flow effect. |
| TradingAgents advisory purpose | runtime-visible | runtime-visible | Context post plus simulation requirement. |

## Runtime Instrumentation

Telemetry can inspect:

- unique active agents
- actions by platform
- actions by actor layer
- round/event beat markers
- ticker/category mentions by round
- narrative clusters by round
- forecast ballot / branch probability statements
- causal attribution statements
- broker confusion events
- buying-power/margin confusion events
- AI-bot/copycat events
- options/0DTE events
- macro override events
- institutional/liquidity events
- market-maker response events
- false-signal events
- top influential agents
- suggested Stage 05 interview targets

Post-run telemetry status is `ready`.

## Stress / Smoke Result

Pre-launch stress/smoke:

- Stress simulation: `sim_974459649906_stress2`
- Cap: 2 rounds
- Result: completed
- Actions: 24
- Zep graph memory: `failed=0`

Approved real run:

- Real simulation: `sim_974459649906`
- Cap: 30 rounds
- Result: completed
- Generated actions: 1725
- Round/event markers: present in both Twitter/common and Reddit/boost action logs
- Graph memory: enabled and partially flushed; `items_sent=990`, `failed=147`, `skipped=2`

## Verification Commands

| Command | Result |
| --- | --- |
| `python -m py_compile backend/app/services/zep_tools.py backend/app/services/report_agent.py backend/app/services/simulation_runner.py` | PASS |
| `npm run build` from `frontend` | PASS with existing bundle/dynamic-import warnings |
| `python docs\mirror_fish\mirofish_actor_population_audit.py` | PASS; 1000 agents |
| `python docs\mirror_fish\mirofish_active_coverage_estimator.py --config backend\uploads\simulations\sim_974459649906\simulation_config.json --max-rounds 30 --json` | PASS; expected dual-platform actions low 704, mid 1257, high 1786; expected unique active agents mid 647 |
| `python docs\mirror_fish\mirofish_cost_estimator.py --config backend\uploads\simulations\sim_974459649906\simulation_config.json --max-rounds 30` | PASS; mid `$1.0703`, worst `$3.13` |
| `python docs\mirror_fish\mirofish_postrun_telemetry.py --simulation-dir backend\uploads\simulations\sim_974459649906 --write` | PASS; wrote telemetry JSON and Markdown |
| `python docs\mirror_fish\mirofish_postrun_telemetry.py --simulation-dir backend\uploads\simulations\sim_974459649906 --json` | PASS; status `ready` |

Known stale pre-launch gates:

- `mirofish_preflight.py`, `mirofish_completion_audit.py`, `mirofish_readiness_bundle.py`, and `mirofish_launch_path_integrity.py` still contain pre-launch lock assumptions and can report stale gate failures after the real run has completed. Runtime action logs, `run_state.json`, telemetry, and the Stage 04 report are the current post-run evidence.

## Active Coverage And Cost

- Pre-run active coverage estimate for 30 rounds: dual-platform actions low 704, mid 1257, high 1786.
- Pre-run expected unique active agents: low 460 dual-platform, mid 647 dual-platform, high 807 dual-platform.
- Actual unique active agents: 657.
- Actual generated actions: 1725.
- Stage 03 active-agent LLM cost estimate: mid `$1.0703`, worst `$3.13`.

## Files Changed

- `backend/app/api/simulation.py`
  - Defaults graph memory on when a graph id exists.
  - Accepts optional explicit `graph_id` and rejects mismatches.
  - Reports resolved `max_rounds_applied` and graph settings from `SimulationRunState`.
- `backend/app/services/simulation_runner.py`
  - Resolves effective max rounds from explicit request or scheduled-event count.
  - Persists launch controls and graph settings.
  - Adds live-runner process checks so stale IPC status cannot masquerade as an active runner.
- `backend/app/services/zep_tools.py`
  - Truncates graph queries to Zep's query limit.
  - Adds rate-limit cooldown and degraded local fallback behavior.
  - Prevents graph-tool failures from collapsing report generation.
- `backend/app/services/report_agent.py`
  - Adds local Stage 03 action-log/telemetry fallback facts.
  - Prefers completed/newer reports for simulation report lookup.
  - Keeps report generation usable when graph tools are rate-limited.
- `backend/app/utils/round_event_context.py`
  - Adds scheduled-event cap resolution, per-round event metadata, context-post formatting, and deterministic context-poster selection.
- `backend/scripts/action_logger.py`
  - Adds optional `round_event` metadata to actions and round markers.
- `backend/scripts/run_parallel_simulation.py`
  - Injects per-round event context into Twitter/common and Reddit/boost before active `LLMAction()` calls.
  - Applies effective max-round cap in CLI and lane loops.
- `docs/mirror_fish/mirofish_postrun_telemetry.py`
  - Extracts event markers, ballot rounds, causal counts, active agents, and Stage 05 targets.
- `frontend/src/api/index.js`
  - Allows MacBook/Tailscale access by deriving API base URL from the current host when not on localhost.
- `frontend/src/components/Step3Simulation.vue`
  - Adds passive watch mode so the run can be watched without accidentally starting it.
- `frontend/src/views/SimulationRunView.vue`
  - Wires passive/watch query params into the simulation view.
- `docs/mirror_fish/MIRROR_FISH_LAUNCH_PATH_INTEGRITY_AUDIT.md`
  - Updated from pre-launch audit to post-run evidence record.
- `docs/mirror_fish/MIRROR_FISH_PRE_RUN_ACCURACY_AUDIT.md`
  - Notes scheduled events are runtime-visible.
- `docs/mirror_fish/MIRROR_FISH_PRE_START_APPROVAL_PACKET.md`
  - Notes event beats are runtime-visible and telemetry-marked.
- `docs/mirror_fish/MIRROR_FISH_TRADING_RUN_READINESS.md`
  - Notes the launch path injects scheduled-event context.

## Remaining Risks

- Zep graph memory was guaranteed on and partially flushed, but final ingestion was not clean: `failed=147`. Treat action logs, telemetry, and the Stage 04 report as canonical until a deliberate non-duplicating graph backfill is built.
- Stage 05 direct live IPC interviews were not available after the runner stopped. ReportAgent attempted interviews but fell back to local/graph evidence; future live interviews should be run before stopping the runner or through a new offline interview path.
- Stage 04 section 1 is short compared with later sections, but the full report completed and the local telemetry/handoff artifacts carry the operational evidence.
- Some pre-launch scripts still report stale gate language after completion and should be modernized before the next MiroFish campaign.
- Runtime context posts add manual context records across the dual-lane run. They should be interpreted as scheduled context, not organic agent behavior.

## Future Approval Phrase

For a future rerun only:

`Start the real MiroFish Stage 03 simulation for sim_974459649906 now, with max_rounds=30, graph memory enabled, and graph id mirofish_4a9df9ae8b184878.`
