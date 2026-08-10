# Zep-Backed Step 4 Report Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make MiroFish Step 4 report generation Zep-canonical, throttle-safe, cache-assisted, UI-rerunnable, and diagnostics-rich without rerunning Stage 3 or overwriting `report_e22efc97ca64`.

**Architecture:** Add a small Step 4 support layer around the existing report system: a report lock, a Zep graph-search cache/throttle client, deterministic Mirror Fish query/outline definitions, quality gates, evidence packet writers, and diagnostics. Interactive Step 4 uses Zep `graph.search` through the cache budget only; graph-wide all-node/all-edge calls are deferred outside the interactive report path.

**Tech Stack:** Python 3.11, Flask, existing `zep-cloud==3.13.0`, pytest, Vue/Vite frontend, local report artifacts under `backend/uploads/reports`.

---

## Ground Rules

- Do not rerun Stage 3.
- Do not rerun full Step 4 after implementation without explicit approval.
- Preserve `backend/uploads/reports/report_e22efc97ca64`.
- This directory is not a git repo; use file-change ledger reporting instead of commits.
- Zep remains the canonical graph/memory source. Local DB/log/telemetry evidence is support/fallback/provenance, not a replacement.
- Interactive Step 4 must never call graph-wide all-node/all-edge fetches.
- Browser rerun must be safe through the normal Step 4 button/path.

## File Structure

- Create `backend/app/services/zep_report_cache.py`: cache keys, rate-limit parsing, sequential graph-search execution, query pack, hydration, locks, diagnostics counters.
- Create `backend/app/services/report_quality.py`: full Mirror Fish outline, section-specific query templates, report quality gates, evidence packet helpers.
- Create `backend/scripts/hydrate_zep_report_cache.py`: resumable CLI hydration for the section-aware Zep query pack.
- Modify `backend/app/services/zep_tools.py`: safe-mode options for cached Zep search, interactive panorama behavior, quick search fallback, graph statistics, stopped-run replay interviews.
- Modify `backend/app/services/report_agent.py`: safe-mode constructor options, forced 20-section outline, safe tool prompt, evidence packets, diagnostics, quality-gated saves.
- Modify `backend/app/api/report.py`: safe defaults for `sim_974459649906`, per-simulation report locks, payload echo, and explicit in-progress/lock response.
- Modify `frontend/src/components/Step3Simulation.vue`: pass safe Step 4 options from browser button.
- Modify `frontend/src/api/report.js`: document accepted safe-mode payload shape.
- Create tests under `backend/tests/`: focused unit/API tests for cache, locks, quality gates, outline, safe tool behavior, and API defaults.
- Create `docs/mirror_fish/MIRROR_FISH_STEP4_REPORT_RERUN_PLAN.md`: short diagnosis and manual rerun/hydration instructions.

## Task 1: Preserve Artifacts And Write Diagnosis

**Files:**
- Create/modify: `docs/mirror_fish/MIRROR_FISH_STEP4_REPORT_RERUN_PLAN.md`

- [ ] **Step 1: Verify the old report is present**

Run:

```powershell
Test-Path -LiteralPath "backend\uploads\reports\report_e22efc97ca64"
```

Expected: `True`.

- [ ] **Step 2: Create the diagnosis document**

The document must include these exact sections:

```markdown
# Mirror Fish Step 4 Report Rerun Plan

## What Failed
## What Was Degraded But Usable
## What Must Be Fixed Before Manual Rerun
## Zep Account Action
## Artifacts Step 4 Will Use
## Browser Rerun Path
## API Fallback
## Hydration Command
## Non-Goals
```

Required facts:

- `report_e22efc97ca64` is preserved as failure evidence.
- Stage 3 appears usable: 30 rounds, 657 unique active agents, 1089 Reddit actions, 764 Twitter actions, 144 ballot-like actions.
- Zep is configured and `graph.search` works, but free-plan rate limits require throttling/cache.
- Account action is optional, only needed for faster full-graph panorama.
- Browser path should use the normal Step 4/generate report button after the patch.

- [ ] **Step 3: Verify the diagnosis document**

Run:

```powershell
Select-String -LiteralPath "docs\mirror_fish\MIRROR_FISH_STEP4_REPORT_RERUN_PLAN.md" -Pattern "Zep-canonical|report_e22efc97ca64|sim_974459649906|hydrate_zep_report_cache.py"
```

Expected: all patterns are found.

## Task 2: Add Zep Cache, Throttle, Query Pack, And Locks

**Files:**
- Create: `backend/app/services/zep_report_cache.py`
- Test: `backend/tests/test_zep_report_cache.py`

- [ ] **Step 1: Write failing cache/rate-limit tests**

Create `backend/tests/test_zep_report_cache.py` with tests for:

```python
from pathlib import Path

from app.services.zep_report_cache import (
    MirrorFishQueryPack,
    ReportLock,
    ZepCacheConfig,
    ZepReportCache,
    parse_retry_after_seconds,
    parse_rate_limit_reset_epoch,
)


def test_cache_key_is_deterministic(tmp_path):
    cache = ZepReportCache(ZepCacheConfig(cache_root=tmp_path, graph_id="g1"))
    a = cache.cache_key(tool_name="quick_search", query="Macro rates", limit=10, scope="edges")
    b = cache.cache_key(tool_name="quick_search", query="  Macro   rates  ", limit=10, scope="edges")
    assert a == b


def test_retry_after_parser_reads_header_text():
    text = "headers: {'retry-after': '46'}, status_code: 429"
    assert parse_retry_after_seconds(text) == 46


def test_rate_limit_reset_parser_reads_epoch():
    text = "headers: {'x-ratelimit-reset': '1780509000'}"
    assert parse_rate_limit_reset_epoch(text) == 1780509000


def test_query_pack_has_required_twenty_sections():
    pack = MirrorFishQueryPack.default()
    assert len(pack.required_sections) == 20
    assert pack.required_sections[0] == "Executive summary"
    assert "Machine-readable summary if practical" in pack.required_sections
    assert all(len(q) <= 260 for q in pack.all_queries())


def test_report_lock_blocks_duplicate_owner(tmp_path):
    lock_path = tmp_path / "sim.lock"
    first = ReportLock.acquire(lock_path, owner="report_a")
    assert first.acquired
    second = ReportLock.acquire(lock_path, owner="report_b")
    assert not second.acquired
    assert second.current_owner["owner"] == "report_a"
    first.release()
```

- [ ] **Step 2: Run tests to confirm they fail**

Run:

```powershell
cd backend
uv run pytest tests/test_zep_report_cache.py -q
```

Expected: import errors because `zep_report_cache.py` does not exist.

- [ ] **Step 3: Implement `zep_report_cache.py`**

Create the module with:

- `ZepCacheConfig`
- `ZepCacheEntry`
- `ZepSearchOutcome`
- `ZepBudget`
- `ZepDiagnostics`
- `ReportLock`
- `MirrorFishQueryPack`
- `ZepReportCache`
- `parse_retry_after_seconds`
- `parse_rate_limit_reset_epoch`

Required behavior:

- Cache path: `backend/uploads/reports/_zep_cache/<graph_id>/`.
- Cache key uses normalized compact query, graph id, tool, scope, and limit.
- Default spacing is 20 seconds.
- Default total live call cap is 50.
- Default per-section live cap is 3.
- Query limit is capped at 15.
- All cache writes are immediate JSON writes.
- Duplicate queries are served from memory/cache.
- Rate-limit failures produce `unavailable_rate_limited` or `stale_cache`, not fake empty graph state.
- `ReportLock.acquire()` writes JSON containing `owner`, `pid`, `started_at`, and `safe_next_action`.
- `ReportLock.release()` removes only its own lock.

- [ ] **Step 4: Run cache tests**

Run:

```powershell
cd backend
uv run pytest tests/test_zep_report_cache.py -q
```

Expected: pass.

## Task 3: Add Report Quality Gates And Evidence Helpers

**Files:**
- Create: `backend/app/services/report_quality.py`
- Test: `backend/tests/test_report_quality.py`

- [ ] **Step 1: Write failing quality tests**

Create `backend/tests/test_report_quality.py` with tests for:

```python
from app.services.report_quality import (
    MIRROR_FISH_REQUIRED_SECTIONS,
    QualityGateResult,
    build_section_queries,
    evaluate_section_quality,
)


def test_required_outline_has_twenty_sections():
    assert len(MIRROR_FISH_REQUIRED_SECTIONS) == 20
    assert MIRROR_FISH_REQUIRED_SECTIONS[7] == "Broker/platform confusion patterns"


def test_section_queries_are_compact_english():
    queries = build_section_queries("Macro override risks")
    assert queries
    assert all(len(q) <= 260 for q in queries)
    assert not any("模拟" in q or "报告" in q for q in queries)


def test_quality_rejects_raw_rate_limit_error():
    result = evaluate_section_quality(
        "Executive summary",
        "This section says Rate limit exceeded for FREE plan.",
        evidence_labels=["live_zep"],
    )
    assert not result.passed
    assert "raw_error_leak" in result.failure_codes


def test_quality_rejects_chinese_final_prose():
    result = evaluate_section_quality(
        "Executive summary",
        "这是中文最终报告正文，应该被拒绝。",
        evidence_labels=["live_zep"],
    )
    assert not result.passed
    assert "non_english_final_prose" in result.failure_codes


def test_quality_rejects_fake_empty_graph():
    result = evaluate_section_quality(
        "Ticker/category attention map",
        "The graph has 0 nodes and 0 edges.",
        evidence_labels=["unavailable_rate_limited"],
    )
    assert not result.passed
    assert "fake_empty_graph_claim" in result.failure_codes
```

- [ ] **Step 2: Run tests to confirm they fail**

Run:

```powershell
cd backend
uv run pytest tests/test_report_quality.py -q
```

Expected: import errors because `report_quality.py` does not exist.

- [ ] **Step 3: Implement `report_quality.py`**

Implement:

- `MIRROR_FISH_REQUIRED_SECTIONS` with the 20 exact required section titles in English.
- `build_section_queries(section_title)` returning compact deterministic English queries.
- `QualityGateResult`.
- `evaluate_section_quality(section_title, content, evidence_labels, min_chars=1200)`.
- `write_section_evidence_files(report_id, section_index, evidence_packet)`.

Failure codes must include:

- `too_short`
- `non_english_final_prose`
- `raw_error_leak`
- `stopped_interview_claim`
- `failed_interview_claim`
- `fake_empty_graph_claim`
- `missing_evidence_labels`
- `missing_uncertainty`
- `missing_validation_tasks`

- [ ] **Step 4: Run quality tests**

Run:

```powershell
cd backend
uv run pytest tests/test_report_quality.py -q
```

Expected: pass.

## Task 4: Patch Zep Tools For Safe Report Mode

**Files:**
- Modify: `backend/app/services/zep_tools.py`
- Test: `backend/tests/test_zep_tools_safe_mode.py`

- [ ] **Step 1: Write failing safe-mode tests**

Create `backend/tests/test_zep_tools_safe_mode.py` with monkeypatch tests that verify:

- `panorama_search(..., safe_mode=True)` does not call `get_all_nodes`.
- `panorama_search(..., safe_mode=True)` does not call `get_all_edges`.
- `quick_search(..., safe_mode=True)` does not call `_local_search` after rate limit.
- `get_graph_statistics(..., safe_mode=True)` returns `graph_wide_fetch_deferred=True`.
- `interview_agents(..., report_mode="zep_throttle_cached")` returns replay/deferred evidence when `run_state.runner_status == "stopped"`.

- [ ] **Step 2: Run tests to confirm they fail**

Run:

```powershell
cd backend
uv run pytest tests/test_zep_tools_safe_mode.py -q
```

Expected: fails because safe-mode parameters are not implemented.

- [ ] **Step 3: Modify `ZepToolsService` constructor**

Add optional fields:

```python
def __init__(self, api_key=None, llm_client=None, report_cache=None, report_mode=None):
    self.report_cache = report_cache
    self.report_mode = report_mode or "standard"
```

- [ ] **Step 4: Route `search_graph` through cache when present**

If `self.report_cache` is set, call its `search(...)` method and convert the outcome into `SearchResult`. Preserve provenance metadata on the `SearchResult` object via a dynamic attribute such as `provenance`.

- [ ] **Step 5: Add safe-mode parameters**

Add `safe_mode: bool = False` to:

- `panorama_search`
- `quick_search`
- `get_graph_statistics`
- `get_simulation_context`
- `insight_forge`

In safe mode:

- no `get_all_nodes`
- no `get_all_edges`
- no `_local_search` if rate-limited/cooling down
- no graph-wide fetches in `get_graph_statistics`
- `panorama_search` returns explicit unavailable/deferred provenance text, not `0 nodes / 0 edges`.

- [ ] **Step 6: Add completed-run interview replay/defer behavior**

When report mode is safe and `run_state.json` shows stopped/completed:

- do not call `SimulationRunner.interview_agents_batch`
- select/preserve Stage 5 targets/questions
- return result text labeled `Replay evidence / Stage 5 interview targets`, not live transcript
- do not emit `0 / 1000 interviewed` as a successful result

- [ ] **Step 7: Run safe-mode tests**

Run:

```powershell
cd backend
uv run pytest tests/test_zep_tools_safe_mode.py -q
```

Expected: pass.

## Task 5: Patch Report Agent For Full Outline, Evidence, Diagnostics, Quality

**Files:**
- Modify: `backend/app/services/report_agent.py`
- Test: `backend/tests/test_report_agent_step4_safe.py`

- [ ] **Step 1: Write failing report-agent tests**

Create tests that verify:

- `ReportAgent(..., report_mode="zep_throttle_cached", outline_mode="mirror_fish_full")` returns the 20 required sections.
- `_define_tools()` in safe mode excludes live `interview_agents` or describes it as replay/deferred only.
- `_generate_section_react()` cannot save content that fails `evaluate_section_quality`.
- `ReportManager.save_section()` companion evidence files are created in safe mode.
- diagnostics contain mode, old report path, payload, hydration, Zep counters, quality status, and evidence paths.

- [ ] **Step 2: Run tests to confirm they fail**

Run:

```powershell
cd backend
uv run pytest tests/test_report_agent_step4_safe.py -q
```

Expected: fails because safe-mode constructor/options do not exist.

- [ ] **Step 3: Add safe-mode constructor options**

Extend `ReportAgent.__init__` with:

```python
report_mode: str = "standard"
language: str = "english"
outline_mode: str = "llm"
zep_safe_mode: bool | None = None
zep_interval_seconds: float = 20.0
max_live_zep_calls: int = 50
max_live_zep_calls_per_section: int = 3
```

Initialize `ZepReportCache` when `report_mode == "zep_throttle_cached"`.

- [ ] **Step 4: Force required outline in safe mode**

In `plan_outline`, if `outline_mode == "mirror_fish_full"`, bypass the LLM outline planner and return a `ReportOutline` with the 20 required section titles. The API can still map legacy `outline="mirror_fish_required_sections"` to `mirror_fish_full`.

- [ ] **Step 5: Change safe-mode prompts**

In safe mode:

- remove the 2-5 section cap language
- require English final prose
- require section-specific evidence labels
- require uncertainty and real-market validation framing
- do not recommend live interviews
- allow 1-3 tool calls per section, capped by global budget

- [ ] **Step 6: Add evidence packet collection**

For each section, collect:

- section name
- canonical queries
- live Zep facts
- fresh/stale cache facts
- local telemetry facts
- DB/log snippets
- skipped/pending graph calls
- provenance labels
- retry count
- uncertainty notes
- quality gate result

Save:

- `section_XX_evidence.json`
- `section_XX_evidence.md`

- [ ] **Step 7: Add quality-gated section saving**

Before saving a section:

- run `evaluate_section_quality`
- if failed, retry once with no new live Zep calls and cache/local evidence only
- if still failed, save diagnostics and mark report failed instead of accepting bad final prose

- [ ] **Step 8: Add mandatory report diagnostics**

Create:

- `step4_diagnostics.json`
- `step4_diagnostics.md`

Include all required user fields:

- report id
- old report preserved path
- mode
- UI/API payload
- lock status
- hydration status
- Zep counters
- Retry-After sleeps
- cache hits/misses
- skipped all-node/all-edge
- graph.search status
- interview mode
- Stage 5 targets/questions
- outline coverage
- section quality status
- evidence packet paths
- artifacts created
- remaining risks

- [ ] **Step 9: Run report-agent tests**

Run:

```powershell
cd backend
uv run pytest tests/test_report_agent_step4_safe.py -q
```

Expected: pass.

## Task 6: Add Hydration CLI

**Files:**
- Create: `backend/scripts/hydrate_zep_report_cache.py`
- Test: `backend/tests/test_hydrate_zep_report_cache.py`

- [ ] **Step 1: Write failing hydration tests**

Tests must verify:

- CLI imports without executing hydration.
- query list comes from the 20 sections and scenario branches.
- `--max-queries 2` hydrates at most 2 queries.
- summary files are written.
- all-node/all-edge APIs are never called.

- [ ] **Step 2: Implement hydration script**

CLI:

```powershell
.\backend\.venv\Scripts\python.exe backend\scripts\hydrate_zep_report_cache.py --simulation-id sim_974459649906 --graph-id mirofish_4a9df9ae8b184878 --interval-seconds 20 --limit 10 --max-queries 40
```

Behavior:

- uses `MirrorFishQueryPack.default().all_queries()`
- graph.search only
- sequential
- checkpoint after each success
- resume by reading cache and hydration summary
- writes `hydration_summary.json`
- writes `hydration_summary.md`
- exits without blocking forever

- [ ] **Step 3: Run hydration tests**

Run:

```powershell
cd backend
uv run pytest tests/test_hydrate_zep_report_cache.py -q
```

Expected: pass.

## Task 7: Patch API And Browser Safe Defaults

**Files:**
- Modify: `backend/app/api/report.py`
- Modify: `frontend/src/components/Step3Simulation.vue`
- Modify: `frontend/src/api/report.js`
- Test: `backend/tests/test_report_api_safe_defaults.py`

- [ ] **Step 1: Write failing API/default tests**

Tests must verify:

- For `simulation_id == "sim_974459649906"` and `force_regenerate=true`, missing options default to:
  - `report_mode="zep_throttle_cached"`
  - `language="english"`
  - `outline_mode="mirror_fish_full"` with legacy `outline="mirror_fish_required_sections"` accepted
- Existing completed report does not block `force_regenerate=true`.
- New `report_id` is generated.
- Active task conflict returns an explicit `report_in_progress` response with existing task/report identifiers.

- [ ] **Step 2: Patch backend route**

In `/api/report/generate`:

- merge safe defaults for the real Mirror Fish simulation
- pass options into `ReportAgent`
- acquire per-simulation report lock before spawning thread
- return an explicit `report_in_progress` response if duplicate
- release lock in `finally`
- include payload/mode in task metadata and diagnostics

- [ ] **Step 3: Patch frontend button payload**

In `Step3Simulation.vue`, change Step 4 button call to:

```javascript
const res = await generateReport({
  simulation_id: props.simulationId,
  force_regenerate: true,
  report_mode: 'zep_throttle_cached',
  outline_mode: 'mirror_fish_full',
  language: 'english',
  zep_safe_mode: true,
  zep_interval_seconds: 20,
  max_live_zep_calls: 50,
  max_live_zep_calls_per_section: 3
})
```

- [ ] **Step 4: Run API tests**

Run:

```powershell
cd backend
uv run pytest tests/test_report_api_safe_defaults.py -q
```

Expected: pass.

## Task 8: Run Integrated Dry Checks Only

**Files:**
- No new code unless fixing test failures.

- [ ] **Step 1: Run all focused tests**

Run:

```powershell
cd backend
uv run pytest tests/test_zep_report_cache.py tests/test_report_quality.py tests/test_zep_tools_safe_mode.py tests/test_report_agent_step4_safe.py tests/test_hydrate_zep_report_cache.py tests/test_report_api_safe_defaults.py -q
```

Expected: pass.

- [ ] **Step 2: Run import/compile check**

Run:

```powershell
cd backend
uv run python -m compileall app scripts -q
```

Expected: exit code 0.

- [ ] **Step 3: Run a no-live-call hydration dry sample**

Run with a tiny max:

```powershell
.\backend\.venv\Scripts\python.exe backend\scripts\hydrate_zep_report_cache.py --simulation-id sim_974459649906 --graph-id mirofish_4a9df9ae8b184878 --interval-seconds 0 --limit 3 --max-queries 0
```

Expected: writes/prints a summary without calling Zep and without starting Stage 3 or full Step 4.

- [ ] **Step 4: Confirm old report still exists**

Run:

```powershell
Test-Path -LiteralPath "backend\uploads\reports\report_e22efc97ca64"
```

Expected: `True`.

- [ ] **Step 5: Confirm browser path is safe**

Run:

```powershell
Select-String -LiteralPath "frontend\src\components\Step3Simulation.vue" -Pattern "zep_throttle_cached|mirror_fish_full|zep_safe_mode"
```

Expected: all patterns are found.

## Task 9: Final Report To User

**Files:**
- No edits.

- [ ] **Step 1: Summarize changed files**

Include every file changed and a concise diff summary.

- [ ] **Step 2: Provide exact manual paths/commands**

Include:

Browser path/button:

```text
Open the app in the in-app browser, go to the simulation/Step 3 screen for sim_974459649906, and click the Step 4 / Generate Report button.
```

API fallback:

```powershell
Invoke-RestMethod -Uri "http://localhost:5001/api/report/generate" -Method POST -ContentType "application/json" -Body '{"simulation_id":"sim_974459649906","force_regenerate":true,"report_mode":"zep_throttle_cached","outline_mode":"mirror_fish_full","language":"english","zep_safe_mode":true,"zep_interval_seconds":20,"max_live_zep_calls":50,"max_live_zep_calls_per_section":3}'
```

Hydration command:

```powershell
.\backend\.venv\Scripts\python.exe backend\scripts\hydrate_zep_report_cache.py --simulation-id sim_974459649906 --graph-id mirofish_4a9df9ae8b184878 --interval-seconds 20 --limit 10 --max-queries 40
```

- [ ] **Step 3: State constraints honored**

Report:

- Stage 3 was not rerun.
- Full Step 4 was not rerun.
- Email was not sent.
- Google Drive was not updated.
- Zep remains canonical.
- Browser route now uses safe mode.
- Account action is optional, not required.

- [ ] **Step 4: Mark goal complete only after checks pass**

Run:

```text
update_goal(status="complete")
```

Only do this after implementation and verification are done.
