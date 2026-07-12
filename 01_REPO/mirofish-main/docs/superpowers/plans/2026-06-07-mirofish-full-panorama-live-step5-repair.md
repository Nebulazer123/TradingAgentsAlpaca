# MiroFish Full Panorama And Live Step 5 Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make MiroFish support true graph-wide Zep all-node/all-edge panorama and true live Step 5 interviews when the simulation runner is alive, with explicit diagnostics when either cannot be proven.

**Architecture:** Keep interactive Step 4 report generation throttle-safe by default, but add an explicit graph-wide panorama/backfill workflow that really calls `get_all_nodes` and `get_all_edges`, persists its output, and can be included in later reports. For Step 5, distinguish three states: live IPC interview available, stale/dead process despite stale `env_status=alive`, and replay-only fallback. Add tests proving the live path is not silently degraded and future completed runs preserve a real interview window.

**Tech Stack:** Python Flask backend, local filesystem IPC, Zep graph tools, pytest, Markdown/JSON artifacts.

---

## Root-Cause Findings

1. `backend/app/services/zep_tools.py::panorama_search(..., safe_mode=True)` intentionally never calls `get_all_nodes()` or `get_all_edges()`. It increments skipped graph-wide diagnostics and returns capped `graph.search` evidence.
2. `backend/app/services/report_agent.py` defaults MirrorFish chat/report mode to safe mode, so Step 4/5 ReportAgent chat inherits that graph-wide skip unless explicitly disabled.
3. True interviews already exist via `/api/simulation/interview/batch` and `SimulationRunner.interview_agents_batch`, but they require both a live runner process and IPC `env_status=alive`.
4. The real run reached command-wait mode, but the backend cleanup later terminated the runner and marked `run_state.runner_status=stopped`; `env_status.json` still says `alive`, creating stale positive status.
5. The system needs stronger status truth, an explicit live-interview readiness check, and a future-run preservation path so Stage 5 can run before cleanup kills the process.

---

### Task 1: Add A Real Graph-Wide Panorama Artifact Builder

**Files:**
- Create: `docs/mirror_fish/mirofish_zep_graph_panorama.py`
- Modify: `backend/tests/test_zep_tools_safe_mode.py`

- [ ] **Step 1: Write a focused test for non-safe panorama**

Add a test that monkeypatches `get_all_nodes` and `get_all_edges`, calls `panorama_search(..., safe_mode=False)`, and asserts both graph-wide methods are called and totals are populated.

- [ ] **Step 2: Add a CLI artifact builder**

Create `docs/mirror_fish/mirofish_zep_graph_panorama.py` that:
- accepts `--graph-id`, `--simulation-id`, `--output-dir`, `--include-temporal`, and `--limit-facts`
- calls `ZepToolsService.get_all_nodes(graph_id)` and `get_all_edges(graph_id, include_temporal=True)`
- writes `zep_graph_panorama.json` and `zep_graph_panorama.md`
- records `status`, node count, edge count, active/historical fact counts, errors, duration, and whether the call was truly graph-wide
- exits nonzero only if both node and edge fetches fail; partial output is still persisted

- [ ] **Step 3: Run targeted tests and py_compile**

Run:
`uv run pytest tests/test_zep_tools_safe_mode.py -q`
`python -m py_compile docs\mirror_fish\mirofish_zep_graph_panorama.py backend\app\services\zep_tools.py`

---

### Task 2: Add Strong Live Step 5 Readiness And Prevent Stale Alive Claims

**Files:**
- Modify: `backend/app/services/simulation_runner.py`
- Modify: `backend/app/api/simulation.py`
- Create or modify focused backend test file around env/interview status.

- [ ] **Step 1: Add `get_live_interview_readiness(simulation_id)`**

Return a dict with:
- `live_interviews_available`: true only when process exists/alive and IPC status is alive
- `runner_process_alive`
- `ipc_env_alive`
- `runner_status`
- `process_pid`
- `stale_env_status`: true when env says alive but process is gone
- `reason`

- [ ] **Step 2: Use readiness in interview guards**

Change `check_env_alive`, `interview_agent`, and `interview_agents_batch` to avoid trusting `env_status.json` alone and to produce clear errors when process is gone or stale.

- [ ] **Step 3: Surface readiness in env-status endpoint**

Extend `/api/simulation/env-status` response to include the readiness fields, so UI and Step 5 can tell live vs replay.

- [ ] **Step 4: Test stale env status**

Test case: run_state says stopped/dead PID, env_status says alive. Assert readiness says `live_interviews_available=false` and `stale_env_status=true`.

---

### Task 3: Make Future Stage 3 Runs Preserve Live Step 5 Interview Window

**Files:**
- Modify: `backend/app/services/simulation_runner.py`
- Modify: `backend/app/api/simulation.py` if start payload needs a flag
- Add focused tests.

- [ ] **Step 1: Add explicit preservation field**

Add `preserve_interview_window: bool = True` to launch state/start path where practical. The existing `run_parallel_simulation.py` default already waits for commands unless `--no-wait`; make this explicit in state and launch diagnostics.

- [ ] **Step 2: Prevent cleanup from silently invalidating the live interview window**

When cleanup terminates a runner that is in completed command-wait mode, write a clear close reason and set `env_status` to stopped so there is no stale alive status. Do not pretend live Step 5 remains possible.

- [ ] **Step 3: Document exact operational sequencing**

Create or update a short runbook section: after Stage 3 reaches 30 rounds and enters wait mode, run Step 5 live interviews before closing environment or restarting backend.

---

### Task 4: Add A Step 5 Live Interview Harness For Current/Future Runs

**Files:**
- Create: `docs/mirror_fish/mirofish_step5_live_interviews.py`
- Tests or dry checks around argument parsing and readiness handling.

- [ ] **Step 1: Implement the harness**

The harness should:
- select top targets from `postrun_telemetry.json` / profiles
- call `SimulationRunner.get_live_interview_readiness()` first
- if live unavailable, write `step5_live_interviews_<timestamp>.json/md` with `status=live_unavailable`, exact reason, and no fake transcript
- if live available, call `SimulationRunner.interview_agents_batch()` with the strongest Step 5 questions and persist transcripts

- [ ] **Step 2: Include exact questions**

Questions:
1. What is most likely wrong in this simulation?
2. Which branch would most change tomorrow's trading assumptions?
3. What real data would falsify the report fastest?
4. Which signals are most likely false positives?
5. What should TradingAgents watch first tomorrow?
6. What should TradingAgents explicitly ignore?
7. Which broker/API/macro/options evidence has the highest update value?

- [ ] **Step 3: Verify current run honestly**

Run the harness for `sim_974459649906`. Expected current output: live unavailable because process is gone; artifact proves why. This is not success for true live interviews, but it proves the system no longer lies or silently substitutes replay.

---

### Task 5: Update Final Audit Docs Without Rewriting History

**Files:**
- Create: `docs/mirror_fish/MIRROR_FISH_FULL_PANORAMA_AND_LIVE_STEP5_REPAIR.md`
- Optionally update final acceptance doc with a new postscript pointing to the repair artifacts.

- [ ] **Step 1: Document what is now fixed**

Include:
- why graph-wide panorama was skipped before
- how to run true graph-wide panorama now
- whether current graph-wide panorama succeeded or failed and where artifacts are
- why live Step 5 is unavailable for the old completed run
- how future runs must sequence Stage 3 -> live Step 5 -> close env

- [ ] **Step 2: Final verification**

Run focused tests only:
- Zep tools panorama test
- Simulation live-readiness tests
- py_compile new scripts
- Optional dry panorama if credentials/account allow
- Step 5 harness dry run on current completed/stopped sim
