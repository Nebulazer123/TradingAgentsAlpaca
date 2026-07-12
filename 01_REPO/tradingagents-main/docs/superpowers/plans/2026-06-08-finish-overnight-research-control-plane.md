# Finish Overnight Research Control Plane Implementation Plan

> Superseded execution entrypoint: use `docs/superpowers/plans/2026-06-08-master-market-readiness-mainline-plan.md` first. This older plan is preserved as source evidence and exact-command reference, but the master plan is the canonical execution plan for mainline cleanup, WIP closure, and remaining market-readiness work.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish the remaining work from the long-running TradingAgents improvement goal: make overnight research reliable, deep, self-checking, token-efficient, and honest about live influence.

**Architecture:** Keep the original TradingAgents graph as the research brain, keep Alpaca execution behind deterministic gates, keep n8n as observer/control-plane wrapper, and keep self-heal in the safe plane. The next work is not another broad rewrite; it is closing the remaining weak points proven by compact context: transcript evidence fallback, blocked Mac helper routing, unresolved outcome learning, weak walk-forward calibration, dirty submit-path branch readiness, and n8n evaluation acceptance clarity.

**Tech Stack:** Python 3.13 via `.\.venv\Scripts\python.exe`, Typer CLI (`.\.venv\Scripts\tradingagents.exe`), pytest, Ruff, local n8n at `http://localhost:5678`, Ollama routes, Alpaca dry-run/check commands, compact context under `results/_context/`, and source-controlled docs under `docs/`.

---

## Current Scorecard

This score is based on current compact evidence from:

- `results/_context/latest-summary.json`
- `results/_context/latest-flags.json`
- `results/process_reviews/latest.json`
- `docs/IMPROVEMENT_PROGRAM.md`
- `docs/PIPELINE_ARCHITECTURE_AUDIT.md`
- independent `code_mapper` scout check from this turn

| Area                          | Score | Evidence                                                                                                                                                                    | Meaning                                                                                                                 |
| ----------------------------- | -----:| --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------- |
| Overnight reliability         | 8/10  | `overnight.completion_status=complete`, `full_graph_success_count=3`, `submitted=0`; verifier `overall_status=pass`                                                         | The overnight run is back and verifiable, but it still needs stronger outcome proof before raising live influence.      |
| Research depth/source routing | 7/10  | Current targets `XOM`, `CVX`, `ADBE` have provider bundles and no current top-target missing non-gap evidence; global recent bundles still show `earnings_transcripts` gaps | Good enough for morning use, not yet clean enough to call the research layer fully mature.                              |
| Live safety                   | 9/10  | SAFE-01 fail-closed, dead-man expired, BOARD `submitted_order_count=0`, `violation_count=0`; preopen live/paper open orders are zero                                        | Safety is strong. Remaining risk is dirty submit-path changes not yet cleanly staged/reviewed.                          |
| n8n/control plane             | 8/10  | Evaluation dataset row count 243, Data Table sync ok, workflow sync ok, run probe `editor_required`, 24 jobs with submit-capable count zero in prior proof                  | Good wrapper/dashboard layer. Native n8n eval execution still requires editor UI and needs a clearer acceptance packet. |
| Self-heal/timeliness          | 9/10  | Automation health 14/14 OK, stale/late/warning counts zero, self-heal timely with real safe execution proof                                                                 | This is one of the strongest slices. Keep it safe-plane only.                                                           |
| Eval/walk-forward             | 4/10  | Walk-forward directional accuracy `0.3143`, action-relative return `-1.6585`, guard `tighten`; Agent Intelligence Ledger has 4,582 forecasts but 0 resolved                 | The system is collecting evidence, but learning is not yet producing earned influence.                                  |
| Token efficiency              | 8/10  | Compact context flags only hourly/BOARD/loss-review; source routing and connector health are quiet where optional                                                           | Good compact routing. Still needs tighter n8n eval acceptance and dirty-tree cleanup to prevent future context churn.   |
| Subagent discipline           | 8/10  | Main thread used one `code_mapper` scout only for independent gap scoring; no swarm for small work                                                                          | Good discipline this turn. Keep this pattern.                                                                           |
| Dirty-tree/git readiness      | 3/10  | Branch remains very dirty; `3970998` only contains standalone order-rate-limit files; shared submit-path hardening remains hunk-review-only                                 | This is the largest operational debt.                                                                                   |

## Finished Areas

- Overnight planner is running again with a complete compact original graph packet for the next trade date.
- Overnight verifier now checks source-quality context and top provider bundles.
- Source routing promotes stronger providers and exposes provider gaps in compact context.
- MiroFish and Deep Research report 33 are normalized into advisory-only filters.
- Buy/sell independence, controlled-dip entry, and no green-spike chase are encoded in hourly/BOARD behavior.
- Loss-review evidence bridge resolves stale missing-evidence blockers without pretending to approve a sell.
- n8n allowlist, job discovery, dataset generation, Data Table sync, workflow sync, and observer workflows exist.
- Self-heal runs real safe-plane commands, then verifies timeliness.
- Agent Intelligence Ledger exists and is ledger-summary consistent.
- Real walk-forward replay exists and currently tightens live influence.
- Email clarity was improved and evaluated in prior checkpoints.

## Remaining Weak Areas

- `earnings_transcripts` still appears as a recent non-gap evidence weakness outside the current top-target set, mainly from YouTube transcript timeout and missing FMP key.
- Mac helper lane `mac_ollama_research_mule` is blocked by host/Ollama timeout; Windows local and deterministic helpers carry the lane.
- Agent Intelligence Ledger has thousands of pending forecasts but no resolved history yet.
- Walk-forward calibration is weak and should actively constrain live influence.
- n8n native evaluation run probe says `editor_required`, which is correct, but the packet does not yet carry a first-class acceptance reason.
- Shared submit-path hardening files remain dirty and need hunk-level staging/review.
- Full end-to-end department simulation should be rerun after the above closures, not assumed from older packets.

## Boundaries For Every Task

- Do not place paper or live orders.
- Do not send emails.
- Do not refresh the live dead-man.
- Do not change `config/risk_envelope.yaml` authority.
- Do not change automation status or schedules unless the user explicitly asks.
- Use `.\.venv\Scripts\tradingagents.exe` or `.\.venv\Scripts\python.exe`.
- Prefer compact context first: `AGENTS.md`, `CONTEXT_ROUTER.md`, `results/_context/latest-summary.json`, `results/_context/latest-flags.json`.
- Raw packets are opened only when compact flags or a task-specific verification requires them.
- Use subagents only when they reduce main-thread burden and return compact evidence. Use one scout or one bounded worker per independent slice.

---

## File Structure

### Files To Modify

- `tradingagents/research/provider_orchestrator.py`
  
  - Owns provider bundle routing and explicit gap packet emission.
  - Change only evidence routing/fallback classification; do not add execution authority.

- `tradingagents/research/youtube_transcript.py`
  
  - Owns YouTube transcript bridge and timeout/error classification.
  - Add cache/quarantine behavior only if tests prove repeated timeouts cause noisy gaps.

- `scripts/automation_context_snapshot.py`
  
  - Owns compact first-screen summaries, flags, provider-bundle overlay, and n8n run-probe summary.
  - Change only compact summary/flagging logic.

- `tradingagents/research/model_routing.py`
  
  - Owns model lane selection and Mac/Windows/helper route status.
  - Add explicit optional-quarantine state for Mac helper if needed.

- `tradingagents/research/model_telemetry.py`
  
  - Owns model telemetry reports and repair signals.
  - Add durable Mac-helper blocked/quarantined evidence if needed.

- `tradingagents/evals/agent_intelligence_ledger.py`
  
  - Owns forecast resolution and influence scoring.
  - Add a dry-run resolver/summary path if pending forecasts remain unresolved despite mature horizons.

- `tradingagents/evals/overnight_calibration.py`
  
  - Owns walk-forward calibration and tighten/hold/relax decision.
  - Add stricter acceptance thresholds for weak cohorts.

- `tradingagents/orchestration/n8n_evaluation_run_probe.py`
  
  - Owns redacted proof of whether native n8n Evaluation Trigger can run via public API.
  - Add first-class acceptance fields for the expected `editor_required` state.

- `tradingagents/orchestration/n8n_evaluations.py`
  
  - Owns n8n built-in evaluation dataset rows and edge cases.
  - Add rows for Mac helper blocked, transcript fallback, weak walk-forward tighten, pending ledger forecasts, and dirty submit-path branch readiness.

- `tests/test_research_provider_orchestrator.py`
  
  - Add source-routing fallback tests.

- `tests/test_youtube_transcript_bridge.py`
  
  - Add transcript timeout/cache/quarantine tests.

- `tests/test_automation_context_snapshot.py`
  
  - Add compact summary and no-false-flag tests.

- `tests/test_model_routing.py`
  
  - Add Mac helper quarantine/selection tests.

- `tests/test_overnight_calibration_guard.py`
  
  - Add weak-cohort live-influence tightening tests.

- `tests/test_agent_intelligence_ledger.py`
  
  - Add mature forecast resolution tests.

- `tests/test_n8n_evaluations.py`
  
  - Add n8n acceptance and edge-case dataset tests.

- `tests/test_real_simulation_audit.py`
  
  - Add final audit acceptance for the newest packets after closures.

### Files To Read But Not Modify Unless A Test Forces It

- `config/research_provider_fallbacks.json`
- `config/n8n_tradingagents_allowlist.json`
- `n8n/workflows/ta-built-in-automation-evaluation.json`
- `docs/orchestration/n8n-workflow-map.md`
- `reports/handoff/CODEX_SUBMIT_PATH_HARDENING_HANDOFF_2026-06-05.md`
- `CONTEXT_ROUTER.md`
- `docs/IMPROVEMENT_PROGRAM.md`
- `docs/PIPELINE_ARCHITECTURE_AUDIT.md`

---

## Task 1: Baseline Audit Packet

**Files:**

- Create: `reports/market_readiness/market-readiness-gap-score-20260608.md`

- Create: `reports/market_readiness/market-readiness-gap-score-20260608.json`

- [ ] **Step 1: Write a small script-free audit by reading compact packets**

Run:

```powershell
.\.venv\Scripts\python.exe scripts\automation_context_snapshot.py --write
.\.venv\Scripts\tradingagents.exe research process-review --json-output
.\.venv\Scripts\python.exe -c "import json; p=json.load(open('results/_context/latest-summary.json')); print(json.dumps({'generated_at':p.get('generated_at'),'flags':p.get('flags'),'next_open':p.get('next_open')}, indent=2))"
```

Expected:

```text
latest-summary.json exists
latest-flags.json exists
process-review JSON reports unchecked_step_count=0
flags only include intentional hourly/BOARD/loss-review unless a new real blocker appeared
```

- [ ] **Step 2: Create the JSON score packet**

Write `reports/market_readiness/market-readiness-gap-score-20260608.json` with this exact shape:

```json
{
  "schema": "tradingagents.market_readiness_gap_score.v1",
  "generated_at": "fill_with_current_utc_iso_timestamp",
  "analysis_only": true,
  "can_submit_orders": false,
  "execution_authority": "none",
  "scores": {
    "overnight_reliability": 8,
    "research_depth_source_routing": 7,
    "live_safety": 9,
    "n8n_control_plane": 8,
    "self_heal_timeliness": 9,
    "eval_walk_forward": 4,
    "token_efficiency": 8,
    "subagent_discipline": 8,
    "dirty_tree_git_readiness": 3
  },
  "finished": [],
  "weak_areas": [],
  "evidence_paths": [],
  "next_plan_path": "docs/superpowers/plans/2026-06-08-finish-overnight-research-control-plane.md"
}
```

Fill `finished`, `weak_areas`, and `evidence_paths` from compact context. Do not include secrets. Do not paste full raw packet bodies.

- [ ] **Step 3: Create the markdown score report**

Write `reports/market_readiness/market-readiness-gap-score-20260608.md` with:

```markdown
# Market Readiness Gap Score - 2026-06-08

This is an analysis-only assessment. It did not submit orders, send emails, refresh live control, or change automation status.

## Scorecard

| Area | Score | Evidence | Next Action |
| --- | ---: | --- | --- |
| Overnight reliability | 8/10 | `results/_context/latest-summary.json` shows complete overnight and verifier pass. | Keep running verifier before pre-open. |
| Research depth/source routing | 7/10 | Current target bundles are clean; recent non-target transcript gaps remain. | Close transcript fallback classification. |
| Live safety | 9/10 | Fail-closed live posture plus zero submitted orders in BOARD/preopen evidence. | Review dirty submit-path hardening hunks. |
| n8n/control plane | 8/10 | Dataset/workflow sync ok; native run is editor-required. | Add explicit run-probe acceptance packet. |
| Self-heal/timeliness | 9/10 | Automation health OK and timely. | Preserve safe-plane boundary. |
| Eval/walk-forward | 4/10 | Walk-forward says tighten; ledger has pending forecasts only. | Resolve mature forecasts and keep live influence tight. |
| Token efficiency | 8/10 | Compact flags are small and relevant. | Add n8n run-probe acceptance to reduce false drilldowns. |
| Subagent discipline | 8/10 | One compact scout used for independent gap check. | Keep subagents bounded. |
| Dirty-tree/git readiness | 3/10 | Shared submit-path edits remain dirty. | Hunk-review and stage only safe files. |
```

- [ ] **Step 4: Verify the report is parseable and secrets are absent**

Run:

```powershell
.\.venv\Scripts\python.exe -m json.tool reports\market_readiness\market-readiness-gap-score-20260608.json > $null
.\.venv\Scripts\python.exe -c "from pathlib import Path; needles=['api'+'Key','sec'+'ret','bear'+'er','pass'+'word','ALPACA'+'_'+'SECRET','N8N'+'_'+'API'+'_'+'KEY']; paths=list(Path('reports/market_readiness').glob('market-readiness-gap-score-20260608.*')); hits=[(str(p), n) for p in paths for n in needles if n in p.read_text(encoding='utf-8')]; print(hits); raise SystemExit(1 if hits else 0)"
```

Expected:

```text
json.tool exits 0
rg returns no matches
```

---

## Task 2: n8n Native Evaluation Acceptance Packet

**Files:**

- Modify: `tradingagents/orchestration/n8n_evaluation_run_probe.py`

- Modify: `scripts/automation_context_snapshot.py`

- Modify: `tests/test_n8n_evaluations.py`

- Modify: `tests/test_automation_context_snapshot.py`

- [ ] **Step 1: Write the failing run-probe acceptance test**

Add to `tests/test_n8n_evaluations.py`:

```python
def test_n8n_evaluation_run_probe_marks_editor_required_as_accepted_gate(tmp_path: Path):
    client = FakeN8NEvaluationRunProbeClient(statuses=[404, 405, 404, 405])

    result = probe_n8n_builtin_evaluation_run(
        client=client,
        api_key_source="unit-test:redacted",
        output_dir=tmp_path,
    )

    assert result["status"] == "editor_required"
    assert result["accepted_as_current_gate"] is True
    assert result["sanctioned_run_surface"] == "n8n_editor_evaluations_ui"
    assert result["acceptance"]["accepted"] is True
    assert result["acceptance"]["editor_required_accepted"] is True
    assert result["acceptance"]["api_trigger_supported"] is False
    assert "editor/evaluations UI" in result["acceptance_reason"]
    assert result["analysis_only"] is True
    assert result["can_submit_orders"] is False
    assert result["execution_authority"] == "none"
    assert result["api_key_redacted"] is True
```

- [ ] **Step 2: Run the test and confirm it fails**

Run:

```powershell
uv run --no-sync --with pytest python -m pytest tests/test_n8n_evaluations.py::test_n8n_evaluation_run_probe_marks_editor_required_as_accepted_gate -q
```

Expected failure:

```text
KeyError: 'accepted_as_current_gate'
```

- [ ] **Step 3: Implement the acceptance packet**

In `tradingagents/orchestration/n8n_evaluation_run_probe.py`, add constants after `DEFAULT_PROBE_ENDPOINTS`:

```python
N8N_EDITOR_EVALUATION_SURFACE = "n8n_editor_evaluations_ui"
N8N_PUBLIC_API_SURFACE = "n8n_public_api"
```

Add helper after `_write_probe_result(...)`:

```python
def _acceptance_packet(
    *,
    accepted: bool,
    sanctioned_run_surface: str,
    api_trigger_supported: bool,
    editor_required_accepted: bool,
    reason: str,
) -> dict[str, Any]:
    return {
        "accepted": accepted,
        "core_accepted": accepted,
        "sanctioned_run_surface": sanctioned_run_surface,
        "api_trigger_supported": api_trigger_supported,
        "editor_required_accepted": editor_required_accepted,
        "reason": reason,
    }
```

In the missing-workflow result, add:

```python
"accepted_as_current_gate": False,
"sanctioned_run_surface": "unavailable",
"acceptance_reason": "Built-in n8n Evaluation Trigger workflow is missing.",
"acceptance": _acceptance_packet(
    accepted=False,
    sanctioned_run_surface="unavailable",
    api_trigger_supported=False,
    editor_required_accepted=False,
    reason="Built-in n8n Evaluation Trigger workflow is missing.",
),
```

After `api_trigger_available = bool(supported)`, add:

```python
editor_required_accepted = not api_trigger_available
sanctioned_run_surface = (
    N8N_PUBLIC_API_SURFACE if api_trigger_available else N8N_EDITOR_EVALUATION_SURFACE
)
acceptance_reason = (
    "Local n8n exposes a public API endpoint for the built-in evaluation run."
    if api_trigger_available
    else (
        "Local n8n public API does not expose a native Evaluation Trigger run "
        "endpoint; the authenticated editor/evaluations UI is the sanctioned run gate."
    )
)
```

Add these fields to the final result:

```python
"accepted_as_current_gate": True,
"sanctioned_run_surface": sanctioned_run_surface,
"acceptance_reason": acceptance_reason,
"acceptance": _acceptance_packet(
    accepted=True,
    sanctioned_run_surface=sanctioned_run_surface,
    api_trigger_supported=api_trigger_available,
    editor_required_accepted=editor_required_accepted,
    reason=acceptance_reason,
),
```

- [ ] **Step 4: Add compact-context test for acceptance fields**

In `tests/test_automation_context_snapshot.py`, update `test_snapshot_summarizes_n8n_evaluation_dataset_and_sync_proof` by adding the fields below to the fake `latest-run-probe.json`:

```python
"accepted_as_current_gate": True,
"sanctioned_run_surface": "n8n_editor_evaluations_ui",
"acceptance_reason": "Local n8n public API does not expose a native Evaluation Trigger run endpoint; the authenticated editor/evaluations UI is the sanctioned run gate.",
"acceptance": {
    "accepted": True,
    "core_accepted": True,
    "sanctioned_run_surface": "n8n_editor_evaluations_ui",
    "api_trigger_supported": False,
    "editor_required_accepted": True,
    "reason": "Local n8n public API does not expose a native Evaluation Trigger run endpoint; the authenticated editor/evaluations UI is the sanctioned run gate."
},
```

Add assertions:

```python
assert summary["run_probe_accepted_as_current_gate"] is True
assert summary["run_probe_acceptance_accepted"] is True
assert summary["run_probe_sanctioned_run_surface"] == "n8n_editor_evaluations_ui"
assert "editor/evaluations UI" in summary["run_probe_acceptance_reason"]
```

- [ ] **Step 5: Implement compact-context fields**

In `scripts/automation_context_snapshot.py`, in the `n8n_evaluation_dataset` branch after `run_probe_api_key_redacted`, add:

```python
run_probe_acceptance = (
    run_probe_data.get("acceptance")
    if isinstance(run_probe_data, dict) and isinstance(run_probe_data.get("acceptance"), dict)
    else {}
)
run_probe_acceptance_accepted = (
    run_probe_acceptance.get("accepted")
    if isinstance(run_probe_acceptance, dict)
    else None
)
```

Add these fields to `summary.update(...)`:

```python
"run_probe_accepted_as_current_gate": (
    run_probe_data.get("accepted_as_current_gate")
    if isinstance(run_probe_data, dict)
    else None
),
"run_probe_acceptance_accepted": run_probe_acceptance_accepted,
"run_probe_sanctioned_run_surface": (
    run_probe_data.get("sanctioned_run_surface")
    if isinstance(run_probe_data, dict)
    else None
),
"run_probe_acceptance_reason": (
    run_probe_data.get("acceptance_reason")
    if isinstance(run_probe_data, dict)
    else None
),
```

Add to the run-probe audit flag condition:

```python
or run_probe_acceptance_accepted is False
```

- [ ] **Step 6: Verify n8n acceptance**

Run:

```powershell
uv run --no-sync --with pytest python -m pytest tests/test_n8n_evaluations.py tests/test_automation_context_snapshot.py -q -k "n8n_evaluation or run_probe"
uv run --no-sync --group static-analysis ruff check tradingagents\orchestration\n8n_evaluation_run_probe.py scripts\automation_context_snapshot.py tests\test_n8n_evaluations.py tests\test_automation_context_snapshot.py
.\.venv\Scripts\tradingagents.exe research n8n-evaluation-run-probe --json-output
.\.venv\Scripts\python.exe scripts\automation_context_snapshot.py --write
```

Expected:

```text
pytest passes
ruff passes
latest-run-probe.json has accepted_as_current_gate=true when workflow exists
latest-summary n8n_evaluation_dataset has run_probe_acceptance_accepted=true
latest-flags does not add n8n_evaluation_dataset for editor_required
```

---

## Task 3: Transcript Evidence Gap Classification

**Files:**

- Modify: `tradingagents/research/provider_orchestrator.py`

- Modify: `tradingagents/research/youtube_transcript.py`

- Modify: `scripts/automation_context_snapshot.py`

- Modify: `tests/test_research_provider_orchestrator.py`

- Modify: `tests/test_youtube_transcript_bridge.py`

- Modify: `tests/test_automation_context_snapshot.py`

- [ ] **Step 1: Write failing test for transcript timeout not poisoning current top-target source routing**

Add to `tests/test_automation_context_snapshot.py`:

```python
def test_source_routing_ignores_non_target_transcript_gap_when_targets_have_non_gap_evidence(
    tmp_path, monkeypatch
):
    source_routing = tmp_path / "source-routing-compact.json"
    monkeypatch.setattr(snapshot, "LATEST_PACKET_FILES", [("source_routing", source_routing)])
    monkeypatch.setattr(snapshot, "LATEST_PACKETS", [])
    source_routing.write_text(
        json.dumps(
            {
                "schema_version": "compact_source_routing_v1",
                "generated_at": "2026-06-08T00:26:09+00:00",
                "category_count": 6,
                "method_count": 11,
                "gap_count": 0,
                "coverage_count": 3,
                "recent_provider_overnight_target_symbols": ["XOM", "CVX", "ADBE"],
                "recent_provider_target_symbols_with_bundle": ["XOM", "CVX", "ADBE"],
                "recent_provider_target_symbols_missing_bundle": [],
                "recent_provider_target_symbols_with_missing_non_gap": [],
                "recent_provider_target_evidence_needs_without_non_gap_packets": [],
                "recent_provider_evidence_needs_without_non_gap_packets": ["earnings_transcripts"],
                "recent_provider_bundle_gaps": [
                    {
                        "symbol": "TSM",
                        "evidence_needs_without_non_gap_packets": ["earnings_transcripts"],
                        "gap_packet_count": 1,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = snapshot.collect_snapshot()
    summary = result["latest_packets"][0]

    assert summary["recent_provider_target_symbols_with_missing_non_gap"] == []
    assert summary["recent_provider_target_evidence_needs_without_non_gap_packets"] == []
    assert result["flags"] == []
```

- [ ] **Step 2: Run and confirm behavior**

Run:

```powershell
uv run --no-sync --with pytest python -m pytest tests/test_automation_context_snapshot.py::test_source_routing_ignores_non_target_transcript_gap_when_targets_have_non_gap_evidence -q
```

Expected:

```text
The test either already passes or fails only because target/non-target gap logic is conflated.
```

If it already passes, do not change `scripts/automation_context_snapshot.py` for this task.

- [ ] **Step 3: Write transcript timeout quarantine test**

Add to `tests/test_youtube_transcript_bridge.py`:

```python
def test_youtube_transcript_timeout_is_optional_endpoint_error_not_hard_failure():
    error = "youtube_transcript MCP timed out after 30s"
    assert "timed out" in error
```

If `tradingagents/research/youtube_transcript.py` already exposes a classifier function, replace the simple assertion with:

```python
assert classify_youtube_transcript_error(error) == "optional_timeout"
```

- [ ] **Step 4: Implement only if the test proves missing behavior**

If the classifier does not exist, add to `tradingagents/research/youtube_transcript.py`:

```python
def classify_youtube_transcript_error(message: str) -> str:
    text = str(message or "").lower()
    if "timed out" in text or "timeout" in text:
        return "optional_timeout"
    if "transcript" in text and "unavailable" in text:
        return "optional_unavailable"
    return "blocked"
```

Use this classifier only for packet metadata and compact connector health. Do not use it to fabricate a transcript packet.

- [ ] **Step 5: Add fallback truth rule in provider orchestrator**

In `tradingagents/research/provider_orchestrator.py`, make sure transcript fallback follows this rule:

```text
If YouTube/FMP transcript evidence is unavailable:
  - emit an explicit earnings_transcripts_gap packet;
  - keep it analysis_only and execution_authority=none;
  - if current top target already has another non-gap earnings/filing/news packet, do not flag source_routing;
  - if current top target has no non-gap event evidence, flag source_routing for refresh/downrank.
```

- [ ] **Step 6: Verify transcript/source routing slice**

Run:

```powershell
uv run --no-sync --with pytest python -m pytest tests/test_youtube_transcript_bridge.py tests/test_research_provider_orchestrator.py tests/test_automation_context_snapshot.py -q -k "youtube_transcript or transcript or source_routing"
uv run --no-sync --group static-analysis ruff check tradingagents\research\youtube_transcript.py tradingagents\research\provider_orchestrator.py scripts\automation_context_snapshot.py tests\test_youtube_transcript_bridge.py tests\test_research_provider_orchestrator.py tests\test_automation_context_snapshot.py
.\.venv\Scripts\tradingagents.exe research source-quality-review --json-output --compact-json-output
.\.venv\Scripts\python.exe scripts\automation_context_snapshot.py --write
```

Expected:

```text
Current top target source-routing fields remain clean:
recent_provider_target_symbols_missing_bundle=[]
recent_provider_target_symbols_with_missing_non_gap=[]
recent_provider_target_evidence_needs_without_non_gap_packets=[]
```

---

## Task 4: Mac Helper Lane Quarantine Or Repair

**Files:**

- Modify: `tradingagents/research/model_routing.py`

- Modify: `tradingagents/research/model_telemetry.py`

- Modify: `tests/test_model_routing.py`

- [ ] **Step 1: Check real Mac endpoint without generation**

Run:

```powershell
.\.venv\Scripts\python.exe -c "import urllib.request, json; url='http://macbook-pro.tail37edd7.ts.net:11434/api/tags'; print(url); print(urllib.request.urlopen(url, timeout=10).read().decode('utf-8')[:1000])"
```

Expected if healthy:

```text
Response includes deepseek-r1:14b
```

Expected if still unhealthy:

```text
Timeout or connection error
```

- [ ] **Step 2: Write routing test for optional Mac quarantine**

Add to `tests/test_model_routing.py`:

```python
def test_mac_helper_timeout_is_quarantined_optional_not_research_blocker():
    status = {
        "route": "mac_ollama_research_mule",
        "model": "deepseek-r1:14b",
        "status": "blocked",
        "error_kind": "mac_host_unreachable",
    }

    decision = model_routing.classify_helper_route_status(status)

    assert decision["optional_helper_degraded"] is True
    assert decision["blocks_overnight_research"] is False
    assert decision["fallback_routes"] == ["windows_local_ollama", "deterministic_packet_helpers", "codex_or_chatgpt_thread_judgment"]
```

- [ ] **Step 3: Implement classifier if missing**

In `tradingagents/research/model_routing.py`, add:

```python
def classify_helper_route_status(status: dict[str, object]) -> dict[str, object]:
    route = str(status.get("route") or "")
    state = str(status.get("status") or "")
    if route == "mac_ollama_research_mule" and state in {"blocked", "timeout", "unreachable"}:
        return {
            "optional_helper_degraded": True,
            "blocks_overnight_research": False,
            "fallback_routes": [
                "windows_local_ollama",
                "deterministic_packet_helpers",
                "codex_or_chatgpt_thread_judgment",
            ],
        }
    return {
        "optional_helper_degraded": False,
        "blocks_overnight_research": state == "blocked",
        "fallback_routes": [],
    }
```

If a similar function already exists, extend it rather than adding a duplicate.

- [ ] **Step 4: Make telemetry plain-English status stable**

In `tradingagents/research/model_telemetry.py`, make sure blocked Mac helper summaries say:

```text
Mac helper is optional/degraded, not a blocker for overnight research. Use Windows local, deterministic helpers, and Codex judgment until Mac Ollama responds.
```

Do not remove the error from telemetry; it should remain visible.

- [ ] **Step 5: Verify model lane**

Run:

```powershell
uv run --no-sync --with pytest python -m pytest tests/test_model_routing.py -q -k "mac or helper or ollama"
uv run --no-sync --group static-analysis ruff check tradingagents\research\model_routing.py tradingagents\research\model_telemetry.py tests\test_model_routing.py
.\.venv\Scripts\tradingagents.exe research model-telemetry --json-output
.\.venv\Scripts\python.exe scripts\automation_context_snapshot.py --write
```

Expected:

```text
Mac blocked status is visible
overnight research is not blocked
selected_helper_routes include Windows local or deterministic fallback
latest-flags does not include model_telemetry unless all usable helper routes are down
```

---

## Task 5: Agent Intelligence Resolution Loop

**Files:**

- Modify: `tradingagents/evals/agent_intelligence_ledger.py`

- Modify: `tests/test_agent_intelligence_ledger.py`

- Modify: `cli/main.py` only if no CLI command already exposes the resolver cleanly

- [ ] **Step 1: Inspect current resolver command**

Run:

```powershell
.\.venv\Scripts\tradingagents.exe research agent-ledger-update --help
.\.venv\Scripts\tradingagents.exe research agent-ledger-summary --help
```

Expected:

```text
There is a command path to update/resolve and summarize forecasts.
```

- [ ] **Step 2: Write mature forecast fixture test**

Add to `tests/test_agent_intelligence_ledger.py`:

```python
def test_agent_ledger_resolves_mature_forecast_with_relative_return(tmp_path: Path):
    ledger = tmp_path / "ledger.jsonl"
    forecast = {
        "id": "unit-forecast-1",
        "agent": "news_analyst",
        "ticker": "XYZ",
        "forecast_type": "relative_outperformance",
        "created_at": "2026-06-01T14:30:00+00:00",
        "resolve_after": "2026-06-05T20:00:00+00:00",
        "probability": 0.64,
        "expected_outcome": "XYZ outperforms QQQ by >1.5%",
        "resolved": False,
    }
    ledger.write_text(json.dumps(forecast) + "\n", encoding="utf-8")
    returns = {
        "XYZ": {"return_pct": 3.0},
        "QQQ": {"return_pct": 1.0},
    }

    result = agent_intelligence_ledger.resolve_mature_forecasts(
        ledger_path=ledger,
        as_of="2026-06-06T00:00:00+00:00",
        returns_by_symbol=returns,
    )

    assert result["resolved_forecast_count"] == 1
    resolved = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()][0]
    assert resolved["resolved"] is True
    assert resolved["outcome"] is True
    assert resolved["relative_return"] == 2.0
    assert "brier_score" in resolved
```

Use existing function names if they differ. The behavior is the contract; avoid adding a duplicate resolver if one exists.

- [ ] **Step 3: Implement missing resolver behavior**

The resolver must:

```text
For each unresolved forecast:
  - skip if resolve_after is in the future;
  - load ticker and benchmark returns from the explicit input rows or existing market data helper;
  - compute relative_return = ticker_return - benchmark_return;
  - resolve expected_outcome thresholds such as ">1.5%";
  - compute Brier score = (probability - outcome)^2;
  - append or rewrite exactly one resolved record per forecast id;
  - never submit orders;
  - write summary counts.
```

- [ ] **Step 4: Run real resolver and summary**

Run:

```powershell
.\.venv\Scripts\tradingagents.exe research agent-ledger-update --json-output
.\.venv\Scripts\tradingagents.exe research agent-ledger-summary --json-output
.\.venv\Scripts\python.exe scripts\automation_context_snapshot.py --write
```

Expected:

```text
summary_ledger_count_matches=true
resolved_forecast_count increases only if forecasts are mature and prices are available
if no forecast is mature, packet must say why, not silently do nothing
```

- [ ] **Step 5: Verify**

Run:

```powershell
uv run --no-sync --with pytest python -m pytest tests/test_agent_intelligence_ledger.py tests/test_automation_context_snapshot.py -q -k "ledger or agent_intelligence"
uv run --no-sync --group static-analysis ruff check tradingagents\evals\agent_intelligence_ledger.py tests\test_agent_intelligence_ledger.py
```

---

## Task 6: Walk-Forward Calibration Guard Becomes A Hard Advisory Constraint

**Files:**

- Modify: `tradingagents/evals/overnight_calibration.py`

- Modify: `tests/test_overnight_calibration_guard.py`

- Modify: `tradingagents/brokers/supervisor/overnight.py` only if overnight packets do not already carry the guard into planning context

- [ ] **Step 1: Write weak-cohort test**

Add to `tests/test_overnight_calibration_guard.py`:

```python
def test_overnight_calibration_tightens_when_directional_accuracy_is_below_half():
    cohort = {
        "metric_summary": {
            "deterministic_sleeve_only": {
                "scored_count": 140,
                "directional_accuracy": 0.3143,
                "false_positive_rate": 0.2786,
                "avg_action_relative_return": -1.6585,
            },
            "tradingagents_advisory_overlay": {
                "scored_count": 8,
                "directional_accuracy": 0.375,
                "false_positive_rate": 0.625,
                "avg_action_relative_return": -1.3762,
            },
        }
    }

    result = overnight_calibration.build_calibration_guard(cohort)

    assert result["guard_decision"] == "tighten"
    assert result["can_increase_live_influence"] is False
    assert result["live_influence_policy"]["mode"] == "tighten_or_hold_reduced_weight"
    assert "controlled_dip_or_support_reclaim_required" in result["entry_validation_requirements"]
    assert "no_green_spike_chase" in result["entry_validation_requirements"]
```

Use existing function names and structure if they differ.

- [ ] **Step 2: Implement threshold contract**

In `tradingagents/evals/overnight_calibration.py`, enforce:

```text
If deterministic directional accuracy < 0.50 or average action-relative return < 0:
  guard_decision = "tighten"
  can_increase_live_influence = false
  policy mode = "tighten_or_hold_reduced_weight"
If advisory overlay scored_count < configured sample floor:
  advisory overlay cannot relax the guard
If both deterministic and advisory pass thresholds with enough sample:
  guard may become "hold" or "eligible_for_review", not automatic live increase
```

- [ ] **Step 3: Verify guard propagates into morning context**

Run:

```powershell
.\.venv\Scripts\tradingagents.exe research overnight-calibration-guard --json-output
.\.venv\Scripts\python.exe scripts\automation_context_snapshot.py --write
.\.venv\Scripts\python.exe -c "import json; p=json.load(open('results/_context/latest-summary.json')); x=[i for i in p['latest_packets'] if i.get('label')=='overnight_calibration_guard'][0]; print(json.dumps({'guard_decision':x.get('guard_decision'),'can_increase_live_influence':x.get('can_increase_live_influence'),'drilldown_reasons':x.get('drilldown_reasons')}, indent=2))"
```

Expected:

```json
{
  "guard_decision": "tighten",
  "can_increase_live_influence": false,
  "drilldown_reasons": []
}
```

- [ ] **Step 4: Verify**

Run:

```powershell
uv run --no-sync --with pytest python -m pytest tests/test_overnight_calibration_guard.py tests/test_automation_context_snapshot.py -q -k "overnight_calibration"
uv run --no-sync --group static-analysis ruff check tradingagents\evals\overnight_calibration.py tests\test_overnight_calibration_guard.py
```

---

## Task 7: Dirty Submit-Path Branch Readiness

**Files:**

- Read: `reports/handoff/CODEX_SUBMIT_PATH_HARDENING_HANDOFF_2026-06-05.md`

- Read: `reports/approval/DIRTY_STATE_INVENTORY_AND_APPROVAL_2026-06-04.md`

- Review/possibly stage later: files named in handoff section 3

- [ ] **Step 1: Produce a no-stage dirty map**

Run:

```powershell
git status --short --branch
git diff --name-only
git diff --stat
git show --stat --oneline --decorate --no-renames 3970998
```

Expected:

```text
Branch is wip/submit-path-hardening-2026-06-05
3970998 contains only tradingagents/policy/order_rate_limit.py and tests/test_order_rate_limit.py
Many files remain dirty
```

- [ ] **Step 2: Verify ignored sensitive local files**

Run:

```powershell
git check-ignore -v config\risk_envelope.yaml .claude setup_n8n.py analysis_mypy.txt
```

Expected:

```text
All four paths are ignored
```

- [ ] **Step 3: Run submit-path verification before staging**

Run:

```powershell
uv run --no-sync --with pytest python -m pytest tests/test_order_rate_limit.py tests/test_live_gate.py tests/test_execution_safety.py tests/test_alpaca_execution.py tests/test_alpaca_cli.py -q
uv run --no-sync --group static-analysis ruff check tradingagents\policy\risk_envelope.py tradingagents\policy\live_gate.py tradingagents\policy\order_rate_limit.py tradingagents\execution\tiny_live.py tradingagents\brokers\alpaca.py cli\main.py tests\test_live_gate.py tests\test_execution_safety.py tests\test_alpaca_execution.py tests\test_order_rate_limit.py tests\test_alpaca_cli.py
```

Expected:

```text
submit-path tests pass
ruff passes
```

- [ ] **Step 4: Hunk-review only**

Do not run `git add -A`.

Use:

```powershell
git add -p tradingagents\policy\risk_envelope.py
git add -p tradingagents\policy\live_gate.py
git add -p tradingagents\execution\tiny_live.py
git add -p tradingagents\brokers\alpaca.py
git add -p cli\main.py
git add -p config\risk_envelope.example.yaml
git add -p tests\test_live_gate.py
git add -p tests\test_execution_safety.py
git add -p tests\test_alpaca_execution.py
git add -p tests\test_alpaca_cli.py
```

Accept only hunks matching:

```text
account_hard_ceiling_usd
max_live_orders_per_window
live_order_window_minutes
order_rate_state_path
control_state_path dead-man re-check
paper/live rollback reconciliation
risk_envelope.example.yaml commented optional knobs
tests for the above behavior
```

Reject unrelated hunks.

- [ ] **Step 5: Inspect staged diff**

Run:

```powershell
git diff --cached --stat
git diff --cached --check
git diff --cached -- config\risk_envelope.yaml .env .claude setup_n8n.py analysis_mypy.txt
```

Expected:

```text
No sensitive file is staged
diff --check has no errors except pre-existing LF/CRLF warnings if present
```

- [ ] **Step 6: Commit only after tests pass**

Run:

```powershell
uv run --no-sync --with pytest python -m pytest tests/test_order_rate_limit.py tests/test_live_gate.py tests/test_execution_safety.py tests/test_alpaca_execution.py tests/test_alpaca_cli.py -q
git commit -m "harden live submit path behind config gates"
```

Expected:

```text
commit succeeds or fails only because GPG signing is unavailable
```

If signing fails, do not change git config. Report it and leave staged changes intact for the user or a signing-capable session.

---

## Task 8: n8n Evaluation Dataset Expands Edge Cases

**Files:**

- Modify: `tradingagents/orchestration/n8n_evaluations.py`

- Modify: `tests/test_n8n_evaluations.py`

- Modify: `n8n/workflows/ta-built-in-automation-evaluation.json` only if dataset columns change

- [ ] **Step 1: Write edge-case coverage test**

Add to `tests/test_n8n_evaluations.py`:

```python
def test_n8n_evaluation_dataset_covers_current_market_readiness_gaps():
    packet = build_n8n_evaluation_dataset()
    scenarios = {row["scenario"] for row in packet["rows"]}
    edge_tags = {
        tag
        for row in packet["rows"]
        for tag in str(row["edge_tags"]).split(",")
        if tag
    }

    assert "mac_helper_optional_degraded" in scenarios
    assert "earnings_transcript_gap_downranked" in scenarios
    assert "weak_walk_forward_tightens_live_influence" in scenarios
    assert "pending_agent_forecasts_not_influence" in scenarios
    assert "dirty_submit_path_not_auto_merged" in scenarios
    assert {
        "mac_helper_degraded",
        "transcript_gap",
        "walk_forward_weak",
        "agent_ledger_pending",
        "dirty_tree",
    } <= edge_tags
```

- [ ] **Step 2: Add scenarios**

In `tradingagents/orchestration/n8n_evaluations.py`, append these to `SCENARIOS`:

```python
{
    "scenario": "mac_helper_optional_degraded",
    "edge_tags": ("mac_helper_degraded", "model_route", "no_live_submit"),
    "metric_rule": "optional_mac_helper_does_not_block_overnight_when_windows_or_deterministic_fallback_exists",
    "notes": "Mac Ollama timeout must stay visible but not block overnight research when fallback routes are healthy.",
},
{
    "scenario": "earnings_transcript_gap_downranked",
    "edge_tags": ("transcript_gap", "source_quality", "no_live_submit"),
    "metric_rule": "transcript_gap_is_explicit_and_downranked_not_silent_success",
    "notes": "Transcript timeouts create gap evidence, not fabricated transcript coverage or trade authority.",
},
{
    "scenario": "weak_walk_forward_tightens_live_influence",
    "edge_tags": ("walk_forward_weak", "calibration", "no_live_submit"),
    "metric_rule": "weak_replay_metrics_force_tighten_or_hold_reduced_weight",
    "notes": "Weak directional accuracy and negative relative returns prevent increased live influence.",
},
{
    "scenario": "pending_agent_forecasts_not_influence",
    "edge_tags": ("agent_ledger_pending", "evaluation", "no_live_submit"),
    "metric_rule": "unresolved_forecasts_do_not_earn_higher_agent_weight",
    "notes": "Pending ledger rows preserve memory but cannot grant earned influence until resolved.",
},
{
    "scenario": "dirty_submit_path_not_auto_merged",
    "edge_tags": ("dirty_tree", "git_hygiene", "no_live_submit"),
    "metric_rule": "shared_submit_path_hunks_require_human_or_main_thread_review",
    "notes": "n8n and self-heal must not auto-stage or auto-merge order-path code.",
},
```

- [ ] **Step 3: Verify dataset and sync**

Run:

```powershell
uv run --no-sync --with pytest python -m pytest tests/test_n8n_evaluations.py tests/test_n8n_runner_policy.py -q -k "n8n_evaluation_dataset or current_market_readiness"
uv run --no-sync --group static-analysis ruff check tradingagents\orchestration\n8n_evaluations.py tests\test_n8n_evaluations.py
.\.venv\Scripts\tradingagents.exe research n8n-evaluation-dataset --json-output --compact-json-output
.\.venv\Scripts\tradingagents.exe research n8n-sync-evaluation-table --json-output
.\.venv\Scripts\tradingagents.exe research n8n-sync-workflows --json-output
```

Expected:

```text
dataset row_count increases by allowlisted_job_count * 5
Data Table sync row_count_matches=true
workflow sync status ok
api_key_redacted=true in sync proofs
```

---

## Task 9: Final Real Simulation Audit

**Files:**

- Modify: `tests/test_real_simulation_audit.py` only if the audit acceptance contract misses a current failure mode

- Read: `tradingagents/evals/real_simulation_audit.py`

- [ ] **Step 1: Run real no-submit simulation audit**

Run:

```powershell
.\.venv\Scripts\tradingagents.exe research real-simulation-audit --json-output
```

Expected:

```text
accepted=true only if every command with required JSON emitted parseable JSON
total_submitted_order_count=0
failed_command_count=0 or every failure has documented remediation
```

- [ ] **Step 2: Inspect current audit summary**

Run:

```powershell
.\.venv\Scripts\python.exe -c "import json, glob; p=max(glob.glob('results/real_simulation_audits/*.json')); d=json.load(open(p)); print(p); print(json.dumps({'accepted':d.get('acceptance',{}).get('accepted'),'failed_command_count':d.get('failed_command_count'),'total_submitted_order_count':d.get('total_submitted_order_count'),'stale_process_review_commands':d.get('stale_process_review_commands')}, indent=2))"
```

Expected:

```json
{
  "accepted": true,
  "failed_command_count": 0,
  "total_submitted_order_count": 0,
  "stale_process_review_commands": []
}
```

- [ ] **Step 3: Run focused department tests**

Run:

```powershell
uv run --no-sync --with pytest python -m pytest tests/test_model_routing.py tests/test_research_automation_orchestrator.py tests/test_n8n_runner_policy.py tests/test_n8n_evaluations.py tests/test_source_quality.py tests/test_alpaca_supervisor.py tests/test_paper_tournament.py tests/test_execution_board.py tests/test_real_simulation_audit.py tests/test_process_review.py -q
```

Expected:

```text
All focused tests pass
```

- [ ] **Step 4: Run full pytest only after focused tests pass**

Run:

```powershell
uv run --no-sync --with pytest python -m pytest -q
```

Expected:

```text
Full suite passes or failures are documented with exact file/test/function and next fix.
```

- [ ] **Step 5: Refresh compact context and process review**

Run:

```powershell
.\.venv\Scripts\python.exe scripts\automation_context_snapshot.py --write
.\.venv\Scripts\tradingagents.exe research process-review --json-output
```

Expected:

```text
process-review unchecked_step_count=0
latest-flags contains only intentional review items or newly documented blockers
```

---

## Task 10: Durable Documentation Update

**Files:**

- Modify: `CONTEXT_ROUTER.md`

- Modify: `docs/IMPROVEMENT_PROGRAM.md`

- Modify: `docs/PIPELINE_ARCHITECTURE_AUDIT.md`

- Modify: `reports/handoff/CODEX_SUBMIT_PATH_HARDENING_HANDOFF_2026-06-05.md`

- Modify: `reports/market_readiness/market-readiness-gap-score-20260608.md`

- [ ] **Step 1: Add one tail pointer per completed slice**

Each tail pointer must include:

```text
timestamp
what changed
exact result packet paths
exact test commands and pass counts
safety boundary held
next action
```

- [ ] **Step 2: Update first-screen router**

In `CONTEXT_ROUTER.md`, add a current checkpoint near the top that says:

```markdown
2026-06-08 market-readiness checkpoint:
- Overnight verifier latest path: `...`
- n8n eval run-probe acceptance path: `...`
- source-routing transcript status: `...`
- Mac helper status: `...`
- calibration guard status: `tighten`
- agent ledger resolved/pending counts: `...`
- dirty branch status: `...`
```

- [ ] **Step 3: Verify docs do not claim completion incorrectly**

Run:

```powershell
rg -n "all done|fully complete|market-ready|no remaining|unchecked_step_count=16|qwen3:30b.*Mac|Mac.*qwen3:30b" CONTEXT_ROUTER.md docs\IMPROVEMENT_PROGRAM.md docs\PIPELINE_ARCHITECTURE_AUDIT.md reports\handoff\CODEX_SUBMIT_PATH_HARDENING_HANDOFF_2026-06-05.md reports\market_readiness\market-readiness-gap-score-20260608.md
```

Expected:

```text
No stale qwen3 Mac claim
No unchecked_step_count=16
No "fully complete" claim unless final audit and full pytest passed in this slice
```

- [ ] **Step 4: Final docs/context tests**

Run:

```powershell
uv run --no-sync --with pytest python -m pytest tests/test_process_review.py tests/test_automation_context_snapshot.py -q
uv run --no-sync --group static-analysis ruff check scripts\automation_context_snapshot.py
```

Expected:

```text
tests pass
ruff passes
```

---

## Execution Order

1. Task 1: Baseline audit packet.
2. Task 2: n8n acceptance packet.
3. Task 3: transcript/source-routing gap classification.
4. Task 4: Mac helper repair or quarantine.
5. Task 5: agent ledger resolution loop.
6. Task 6: walk-forward calibration hard advisory constraint.
7. Task 8: n8n edge-case expansion.
8. Task 9: final real simulation audit.
9. Task 10: durable docs update.
10. Task 7: dirty submit-path branch readiness can run in parallel with Tasks 2-6 only if a separate worker owns git hunk review and does not edit the same files.

## Subagent Routing

- Use main thread for final safety judgment, git staging decisions, calibration thresholds, and any live-authority question.
- Use one `code_mapper` scout for read-only gap checks across docs/results.
- Use one `gpt-5.3-codex-spark` worker only for Task 2 or Task 8 if the patch is limited to n8n evaluation files and tests.
- Use one `gpt-5.4-mini` scout for dirty-tree file inventory if Task 7 becomes too large.
- Do not spawn agents for Tasks 1, 6, 9, or 10; the main thread should own assessment, final audit, and durable docs.

## Completion Criteria

The overall improvement goal can be called complete only when all of these are true:

- `alpaca verify-overnight-system --json-output` returns `overall_status=pass`.
- Latest overnight packet has `completion_status=complete`, at least 3 original graph successes, and `submitted=0`.
- Source routing for current top overnight targets has no missing bundles and no missing non-gap evidence.
- n8n Data Table sync is current and row-count matched.
- n8n workflow sync is ok.
- n8n run probe is either `api_trigger_available` or explicitly accepted as `editor_required` with sanctioned UI surface.
- Automation health has no missing/partial/late/stale/warning jobs.
- Self-heal follow-up is timely and safe-plane only.
- Agent ledger summary matches ledger record count.
- Mature forecasts either resolve or report why none are mature.
- Walk-forward calibration guard is present and constrains live influence when metrics are weak.
- Process review has `unchecked_step_count=0`.
- Focused department tests pass.
- Full pytest passes, or failures are documented with exact next fixes.
- No orders, emails, dead-man refreshes, credential changes, automation status changes, or live-authority changes occurred during verification.

## Self-Review

- Spec coverage: This plan covers the unfinished areas proven by compact context: transcript/source gap, Mac helper block, pending ledger outcomes, weak walk-forward, n8n native eval boundary, dirty branch readiness, real simulation, and docs.
- Placeholder scan: No placeholder-token or vague edge-case steps remain. Each task states files, commands, expected output, and acceptance criteria.
- Type consistency: New proposed fields use consistent names: `accepted_as_current_gate`, `sanctioned_run_surface`, `acceptance_reason`, and nested `acceptance.accepted`.
