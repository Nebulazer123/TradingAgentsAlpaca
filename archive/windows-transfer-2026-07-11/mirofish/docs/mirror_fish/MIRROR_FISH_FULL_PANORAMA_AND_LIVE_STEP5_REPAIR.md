# MiroFish Full Panorama And Live Step 5 Repair

Generated: 2026-06-07

## Goal

Remove the remaining silent skips in the MiroFish post-run path:

- graph-wide Zep panorama must be runnable as a true all-node/all-edge fetch
- Step 5 live interviews must either run through the real simulation IPC path or fail with exact readiness evidence
- stale `env_status=alive` must not be treated as proof that live interviews are possible

## What Failed Before

1. Interactive Step 4 safe mode intentionally deferred all-node/all-edge calls and used capped `graph.search` only.
2. The real Stage 3 run entered command-wait mode, but the backend cleanup later killed the runner process.
3. `env_status.json` remained `alive` after the process was gone, so the system could imply live interviews were available when they were not.
4. Step 5 therefore used ReportAgent replay/deferred evidence rather than true live IPC interview transcripts.

## Fixes Added

- Added `docs/mirror_fish/mirofish_zep_graph_panorama.py`.
  - Calls `ZepToolsService.get_all_nodes()` and `get_all_edges()` directly.
  - Writes persisted JSON and Markdown panorama artifacts.
  - Does not use Step 4 safe-mode graph.search substitution.
- Added `SimulationRunner.get_live_interview_readiness()`.
  - Live interviews are available only when both the runner process and IPC environment are alive.
  - Stale `env_status=alive` with a missing process is flagged as stale, not live.
- Updated `SimulationRunner.check_env_alive()`, single-agent interviews, and batch interviews to use the stronger readiness check.
- Updated `/api/simulation/env-status` to return live-interview readiness fields.
- Updated stop/cleanup paths to write `env_status=stopped` when the backend terminates a runner.
- Added `docs/mirror_fish/mirofish_step5_live_interviews.py`.
  - Attempts true live Step 5 IPC interviews when readiness is positive.
  - Writes a no-transcript proof artifact when live interviews are unavailable.

## Current Graph-Wide Panorama Result

The accepted report now has a true graph-wide Zep panorama:

- JSON: `backend/uploads/reports/report_9c77ca2557ae/zep_graph_panorama/zep_graph_panorama.json`
- Markdown: `backend/uploads/reports/report_9c77ca2557ae/zep_graph_panorama/zep_graph_panorama.md`
- Status: `completed`
- Truly graph-wide: `true`
- Nodes fetched: `973`
- Edges fetched: `2678`
- Active facts: `1389`
- Historical facts: `1289`
- Errors: none

This proves the all-node/all-edge panorama was not skipped in the repaired path.

## Current Step 5 Live Interview Result

The old run cannot produce true live transcripts now because its runner process is gone:

- Latest JSON: `backend/uploads/reports/report_9c77ca2557ae/step5_live/step5_live_interviews_20260608T015304Z.json`
- Latest Markdown: `backend/uploads/reports/report_9c77ca2557ae/step5_live/step5_live_interviews_20260608T015304Z.md`
- Status: `live_unavailable`
- Reason: `runner process is not available`
- Selected targets: 5
- Transcript generated: no

The earlier live-attempt artifact also captured the stale-state bug:

- `backend/uploads/reports/report_9c77ca2557ae/step5_live/step5_live_interviews_20260608T014220Z.json`
- Reason: `stale env_status says alive but runner process is not available`

After the repair, the current `backend/uploads/simulations/sim_974459649906/env_status.json` was corrected to `stopped`.

## Live Step 5 Smoke Result

A separate capped smoke proved the live Step 5 path on an actual running OASIS command-window environment:

- Smoke simulation: `sim_763e1e31b320`
- Max rounds: `1`
- Platform: `parallel`
- Graph memory writes: disabled for the smoke
- Live readiness at interview time: `live_interviews_available=true`
- Interview command: `batch_interview`
- Returned live records: 4 platform-agent results (`twitter_0`, `twitter_1`, `reddit_0`, `reddit_1`)
- Close-env result: succeeded
- Summary: `backend/uploads/reports/report_9c77ca2557ae/step5_live_smoke/live_step5_smoke_summary.json`
- Transcript: `backend/uploads/reports/report_9c77ca2557ae/step5_live_smoke/step5_live/step5_live_interviews_20260608T022835Z.json`

This does not replace the accepted 1,000-agent report, but it proves the repaired system can execute true live Step 5 interviews when the runner is preserved.

## Live Step 5 Quality Smoke Result

The first smoke was useful as live-IPC proof, but some interview content was too noisy for final review. A second capped quality smoke was run after adding explicit Step 5 answer-quality instructions and explicit target selection:

- Smoke simulation: `sim_763e1e31b320`
- Max rounds: `1`
- Platform: `reddit`
- Explicit targets: `0` Fidelity, `3` systematic traders, `11` FINRA
- Live readiness at interview time: `live_interviews_available=true`
- Returned live records: 3
- Close-env result: succeeded
- Summary: `backend/uploads/reports/report_9c77ca2557ae/step5_live_smoke_quality/live_step5_smoke_summary.json`
- Transcript: `backend/uploads/reports/report_9c77ca2557ae/step5_live_smoke_quality/step5_live/step5_live_interviews_20260608T102145Z.json`

The quality transcript is English-only, contains no raw tool wrapper, no code fence, no Chinese prose, and no raw error leak. It supersedes the first smoke for interview-quality evidence while preserving the first smoke for traceability.

## Future Correct Step 5 Sequence

For future MiroFish runs:

1. Start Stage 3 normally with max rounds and graph memory enabled.
2. Let Stage 3 finish its rounds and enter command-wait mode.
3. Before restarting the backend or closing the environment, run:

```powershell
backend\.venv\Scripts\python.exe docs\mirror_fish\mirofish_step5_live_interviews.py --simulation-id <simulation_id> --max-agents 5
```

4. Confirm the output says `status=completed`.
5. Only after live Step 5 transcripts are saved, call close-env or stop/restart the backend.

If the process has already been killed, the script will not fake transcripts; it will write an availability proof explaining why true live interviews cannot run.

## Verification

- `uv run pytest tests/test_zep_tools_safe_mode.py tests/test_simulation_live_readiness.py -q` passed.
- `uv run pytest tests/test_step5_live_interviews.py tests/test_simulation_live_readiness.py -q` passed.
- `python -m py_compile` passed for the new scripts and patched backend modules.
- True graph-wide panorama completed against graph `mirofish_4a9df9ae8b184878`.
- Current completed/stopped run was checked through the live Step 5 harness and correctly reported live unavailable.
- A capped 1-round live smoke completed and produced true live Step 5 interview transcripts through IPC before close-env.
- A second capped quality smoke completed and produced cleaner live Step 5 interview transcripts for broker, systematic-trader, and regulatory targets.

Additional live-path proof:

- The Step 5 harness now has a positive-readiness regression showing it calls `SimulationRunner.interview_agents_batch()` with the selected Stage 5 targets and the full question set.
- `SimulationRunner.interview_agents_batch()` now has a readiness-positive regression showing it calls the IPC client's batch interview path rather than replay evidence.
- The filesystem IPC layer now has a batch-interview round-trip regression using command and response files, including cleanup of successful command/response artifacts.
