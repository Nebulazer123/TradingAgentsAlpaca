# MiroFish Step 4 Enrichment Sprint Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve the accepted MiroFish Step 4 baseline from usable to as strong as practical for TradingAgents research without rerunning Stage 1, Stage 2, Stage 3, or touching trading execution.

**Architecture:** Treat `report_44fb26ddc574` as the accepted baseline. Fix only runtime/reporting defects that affect future reliability, then add external validation and enrichment handoff artifacts around the clean report rather than overwriting it. Keep simulated evidence, Zep evidence, local telemetry, and real-market validation as separate layers.

**Tech Stack:** Python/Flask backend, Markdown report artifacts, JSON diagnostics/evidence files, PowerShell verification commands, Python `zipfile` packet refresh.

---

## File Structure

- Modify: `backend/app/api/report.py`
  - Add status-resolution helper so `/api/report/generate/status` resolves a completed report from task metadata/result before returning stale task progress.
- Modify: `backend/tests/test_report_api_safe_defaults.py`
  - Add unit coverage for stale task metadata resolving to completed report status.
- Create: `docs/mirror_fish/MIRROR_FISH_STEP4_ENRICHMENT_DECISION.md`
  - Baseline quality decision, defect/enrichment classification, evidence-file audit, rerun decision.
- Create: `docs/mirror_fish/MIRROR_FISH_REAL_MARKET_VALIDATION_PACKET.md`
  - Concrete TradingAgents validation checklist with signal, true/false expectations, source, update rule, false-positive warning, usage, and priority.
- Create: `docs/mirror_fish/MIRROR_FISH_EXTERNAL_ENRICHMENT_PACKET.md`
  - Targeted current-source research notes for macro, options, WWDC, semiconductors/AI infrastructure, brokers/platforms, oil/geopolitics, and institutional liquidity context.
- Create: `docs/mirror_fish/MIRROR_FISH_OPTIONAL_ZEP_ENRICHMENT_PLAN.md`
  - Targeted Zep query packs, slow hydration command, rerun criteria, and waste criteria.
- Refresh: `backend/uploads/reports/report_44fb26ddc574/review_packet_report_44fb26ddc574.zip`
  - Include clean report, all section/evidence/diagnostics/log/telemetry/hydration files, launch audit, final audit, enrichment decision, validation packet, external enrichment packet, optional Zep plan, and machine-readable summary.

---

### Task 1: Verify Accepted Baseline

**Files:**
- Read: `backend/uploads/reports/report_44fb26ddc574/full_report.md`
- Read: `backend/uploads/reports/report_44fb26ddc574/step4_diagnostics.json`
- Read: `backend/uploads/reports/report_44fb26ddc574/section_*.md`
- Read: `backend/uploads/reports/report_44fb26ddc574/section_*_evidence.json`
- Read: `backend/uploads/simulations/sim_974459649906/postrun_telemetry.json`

- [ ] **Step 1: Run artifact inventory**

Run:

```powershell
python - <<'PY'
import json, pathlib, re
repo = pathlib.Path(r"C:/Users/Corbin/Documents/Coding projects/mirofish-main")
report = repo / "backend/uploads/reports/report_44fb26ddc574"
full = (report / "full_report.md").read_text(encoding="utf-8", errors="replace")
diag = json.loads((report / "step4_diagnostics.json").read_text(encoding="utf-8"))
tele = json.loads((repo / "backend/uploads/simulations/sim_974459649906/postrun_telemetry.json").read_text(encoding="utf-8"))
forbidden = ["unavailable_rate_limited", "source=pending", "Rate limit exceeded", "0 nodes", "0 edges", "status=stopped", "0 / 1000 interviewed", "真实API", "深度采访", "Section 01 Evidence"]
print({
  "full_chars": len(full),
  "full_headings": sum(1 for line in full.splitlines() if line.startswith("## ")),
  "forbidden_in_full": {pat: pat.lower() in full.lower() for pat in forbidden},
  "sections": len([p for p in report.glob("section_*.md") if re.fullmatch(r"section_\d+\.md", p.name)]),
  "evidence_json": len(list(report.glob("section_*_evidence.json"))),
  "evidence_md": len(list(report.glob("section_*_evidence.md"))),
  "diag_status": diag.get("status"),
  "outline": diag.get("required_outline_coverage"),
  "telemetry_rounds": tele.get("actual_total_rounds") or tele.get("effective_total_rounds"),
  "unique_active_agents": tele.get("unique_active_agents"),
})
PY
```

Expected:

- `full_headings` is `20`.
- All `forbidden_in_full` values are `False`.
- `sections`, `evidence_json`, and `evidence_md` are `20`.
- Diagnostics status is `completed`.
- Outline coverage is `expected=20`, `actual=20`, `passed=True`.
- Telemetry rounds are `30`.

- [ ] **Step 2: Classify defects versus enrichment gaps**

Record:

- Actual defects: stale task-only `/api/report/generate/status` can return stale progress after a report exists.
- No active full-report defect: clean report excludes evidence footers and raw provenance labels.
- Enrichment gaps: real-market validation not yet performed; company/executive-specific evidence is useful but can be deepened; graph-wide panorama remains intentionally deferred.

### Task 2: Patch Stale Generate Status Resolution

**Files:**
- Modify: `backend/app/api/report.py`
- Modify: `backend/tests/test_report_api_safe_defaults.py`

- [ ] **Step 1: Add failing unit test**

Append this test to `backend/tests/test_report_api_safe_defaults.py`:

```python
def test_report_status_prefers_completed_report_from_stale_task_metadata(monkeypatch):
    from app.api.report import _report_status_from_completed_report_reference
    from app.services.report_agent import Report, ReportStatus

    report = Report(
        report_id="report_done",
        simulation_id="sim_done",
        graph_id="graph_done",
        simulation_requirement="requirement",
        status=ReportStatus.COMPLETED,
        markdown_content="complete",
    )

    monkeypatch.setattr(
        "app.api.report.ReportManager.get_report",
        lambda report_id: report if report_id == "report_done" else None,
    )
    monkeypatch.setattr(
        "app.api.report.ReportManager.get_report_by_simulation",
        lambda simulation_id: report if simulation_id == "sim_done" else None,
    )

    task_payload = {
        "task_id": "task_stale",
        "status": "processing",
        "progress": 0,
        "metadata": {"simulation_id": "sim_done", "report_id": "report_done"},
    }

    resolved = _report_status_from_completed_report_reference(task_payload)

    assert resolved["status"] == "completed"
    assert resolved["progress"] == 100
    assert resolved["report_id"] == "report_done"
    assert resolved["task_id"] == "task_stale"
    assert resolved["already_completed"] is True
```

- [ ] **Step 2: Run the new test and confirm it fails**

Run:

```powershell
cd "C:\Users\Corbin\Documents\Coding projects\mirofish-main\backend"
uv run pytest tests/test_report_api_safe_defaults.py::test_report_status_prefers_completed_report_from_stale_task_metadata -q
```

Expected before implementation: import error or assertion failure because `_report_status_from_completed_report_reference` does not exist.

- [ ] **Step 3: Implement helper and use it in `/generate/status`**

Add helper near `_active_report_task_for_simulation()`:

```python
def _report_status_payload(report, task_id=None) -> dict:
    status = report.status.value if isinstance(report.status, ReportStatus) else report.status
    return {
        "task_id": task_id,
        "simulation_id": report.simulation_id,
        "report_id": report.report_id,
        "status": status,
        "progress": 100 if status == ReportStatus.COMPLETED.value else 0,
        "message": report.error or t('api.reportGenerated'),
        "already_completed": status == ReportStatus.COMPLETED.value,
    }
```

Add resolver:

```python
def _report_status_from_completed_report_reference(task_payload: dict) -> dict | None:
    metadata = task_payload.get("metadata") or {}
    result = task_payload.get("result") or {}
    report_id = metadata.get("report_id") or result.get("report_id") or task_payload.get("report_id")
    simulation_id = metadata.get("simulation_id") or result.get("simulation_id") or task_payload.get("simulation_id")

    report = ReportManager.get_report(report_id) if report_id else None
    if report is None and simulation_id:
        report = ReportManager.get_report_by_simulation(simulation_id)
    if report is None or report.status != ReportStatus.COMPLETED:
        return None

    return _report_status_payload(report, task_id=task_payload.get("task_id"))
```

Use the resolver:

- When `report_id` returns a report, call `_report_status_payload(report, task_id=task_id)`.
- When an active simulation task is found, return completed report payload if the resolver finds one; otherwise return active task.
- When a task_id task is found, return completed report payload if the resolver finds one; otherwise return `task.to_dict()`.

- [ ] **Step 4: Run focused tests**

Run:

```powershell
cd "C:\Users\Corbin\Documents\Coding projects\mirofish-main\backend"
uv run pytest tests/test_report_api_safe_defaults.py tests/test_report_agent_step4_safe.py tests/test_report_quality.py tests/test_zep_tools_safe_mode.py -q
```

Expected: all selected tests pass.

### Task 3: Create Enrichment Decision Doc

**Files:**
- Create: `docs/mirror_fish/MIRROR_FISH_STEP4_ENRICHMENT_DECISION.md`

- [ ] **Step 1: Write baseline decision**

Include these answers:

- `report_44fb26ddc574` remains accepted baseline.
- Remaining actual bug: stale task-only status endpoint; patched in Task 2.
- Remaining enrichment gaps: real-market validation, company/executive deepening, optional Zep hydration.
- No section evidence files failed quality.
- Full report excludes evidence footers and raw provenance labels.
- Step 4 rerun is not recommended now.

### Task 4: Build Real-Market Validation Packet

**Files:**
- Create: `docs/mirror_fish/MIRROR_FISH_REAL_MARKET_VALIDATION_PACKET.md`

- [ ] **Step 1: Write validation checklist table**

For each domain, include rows with:

- `signal`
- `expected_if_simulation_true`
- `expected_if_simulation_false`
- `data_source_to_check`
- `confidence_update_rule`
- `false_positive_warning`
- `TradingAgents usage`
- `priority`

Domains:

- Broker/API validation
- Macro validation
- Options/microstructure validation
- Retail/social validation
- AI/bot/developer validation
- Company/executive validation
- Institutional validation

### Task 5: Build External Enrichment Packet

**Files:**
- Create: `docs/mirror_fish/MIRROR_FISH_EXTERNAL_ENRICHMENT_PACKET.md`

- [ ] **Step 1: Gather targeted current sources**

Use current/official sources where possible for:

- BLS jobs, CPI, PPI
- Treasury auction timing
- Cboe weekly expiration/options schedule
- Apple WWDC June 8-12, 2026
- Nvidia/semiconductors/AI infrastructure
- Oracle/AI cloud
- broker/platform public notices
- oil/geopolitical catalyst sources

- [ ] **Step 2: Write source-backed enrichment notes**

Each note must include:

- source URL
- relevance to MiroFish June 4-13 window
- how it updates or validates the Step 4 report
- whether it justifies a Step 4 rerun

### Task 6: Build Optional Zep Enrichment Plan

**Files:**
- Create: `docs/mirror_fish/MIRROR_FISH_OPTIONAL_ZEP_ENRICHMENT_PLAN.md`

- [ ] **Step 1: Write targeted query packs**

Include:

- company/executive query pack
- broker/platform query pack
- macro/options validation query pack
- institutional/liquidity query pack
- slow hydration command
- rerun criteria
- waste criteria

### Task 7: Refresh Review Packet

**Files:**
- Refresh: `backend/uploads/reports/report_44fb26ddc574/review_packet_report_44fb26ddc574.zip`

- [ ] **Step 1: Build zip from accepted artifacts**

Include:

- `report/full_report.md`
- `report/section_*.md`
- `report/section_*_evidence.json`
- `report/section_*_evidence.md`
- `report/step4_diagnostics.json`
- `report/step4_diagnostics.md`
- `report/console_log.txt`
- `report/agent_log.jsonl`
- `simulation/postrun_telemetry.json`
- `simulation/postrun_telemetry.md`
- `zep_cache/hydration_summary.json`
- `zep_cache/hydration_summary.md`
- `docs/MIRROR_FISH_STEP4_FINAL_QUALITY_AUDIT.md`
- `docs/MIRROR_FISH_STEP4_ENRICHMENT_DECISION.md`
- `docs/MIRROR_FISH_REAL_MARKET_VALIDATION_PACKET.md`
- `docs/MIRROR_FISH_EXTERNAL_ENRICHMENT_PACKET.md`
- `docs/MIRROR_FISH_OPTIONAL_ZEP_ENRICHMENT_PLAN.md`
- `docs/MIRROR_FISH_LAUNCH_PATH_INTEGRITY_AUDIT.md`
- `docs/MIRROR_FISH_STEP4_REPORT_RERUN_PLAN.md`

### Task 8: Final Verification

**Files:**
- Verify: report folder, docs, tests, zip

- [ ] **Step 1: Run tests and compile check**

Run:

```powershell
cd "C:\Users\Corbin\Documents\Coding projects\mirofish-main\backend"
uv run pytest tests/test_report_api_safe_defaults.py tests/test_report_agent_step4_safe.py tests/test_report_quality.py tests/test_zep_tools_safe_mode.py -q
uv run python -m compileall app -q
```

Expected: tests and compile pass.

- [ ] **Step 2: Run packet/report verification**

Run a Python check that confirms:

- full report has 20 headings
- forbidden raw strings are absent from `full_report.md`
- all required docs exist
- zip exists and contains the new docs
- status endpoint helper resolves stale task references

Expected: all checks pass.
