import importlib.util
import json
from pathlib import Path

from tradingagents.orchestration.token_context import (
    classify_pre_tool_use_warning,
    classify_raw_context_need,
    load_compact_context,
    redact_hook_payload,
    write_hook_event,
)


def _load_token_context_hook_module():
    hook_path = Path(__file__).resolve().parents[1] / ".codex" / "hooks" / "token_context_hook.py"
    spec = importlib.util.spec_from_file_location("token_context_hook", hook_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_compact_context_loads_summary_and_flags(tmp_path: Path):
    context_dir = tmp_path / "results" / "_context"
    context_dir.mkdir(parents=True)
    (context_dir / "latest-summary.json").write_text(
        json.dumps({"generated_at": "2026-06-02T12:00:00+00:00", "latest_packets": [{"label": "hourly"}]}),
        encoding="utf-8",
    )
    (context_dir / "latest-flags.json").write_text(
        json.dumps({"flags": [{"reason": "issues", "path": "results/hourly/latest.json"}]}),
        encoding="utf-8",
    )

    compact = load_compact_context(tmp_path)

    assert compact.summary["latest_packets"][0]["label"] == "hourly"
    assert compact.flags["flags"][0]["reason"] == "issues"
    assert compact.summary_path.name == "latest-summary.json"


def test_raw_context_needed_for_trade_and_safety_flags():
    decision = classify_raw_context_need(
        {
            "flags": [
                {"reason": "submitted", "path": "results/hourly/a.json"},
                {"reason": "candidate_change", "path": "results/paper/latest.json"},
                {"reason": "quality", "path": "results/research/latest.json"},
            ]
        }
    )

    assert decision.required is True
    assert decision.reasons == ["submitted", "candidate_change", "quality"]
    assert decision.paths == [
        "results/hourly/a.json",
        "results/paper/latest.json",
        "results/research/latest.json",
    ]


def test_pre_tool_warning_flags_broad_raw_context_reads():
    decision = classify_raw_context_need({"flags": []})

    warning = classify_pre_tool_use_warning(
        {
            "hook_event_name": "PreToolUse",
            "tool_name": "exec_command",
            "tool_input": {"cmd": 'rg "submitted" results'},
        },
        decision=decision,
    )

    assert warning.warning_only is True
    assert warning.should_warn is True
    assert "broad_results_search" in warning.reasons
    assert warning.block_execution is False


def test_pre_tool_warning_allows_snapshot_refresh_and_flagged_packet_read():
    decision = classify_raw_context_need(
        {"flags": [{"reason": "blocker", "path": "results/hourly/blocker.json"}]}
    )

    snapshot = classify_pre_tool_use_warning(
        {
            "hook_event_name": "PreToolUse",
            "tool_name": "exec_command",
            "tool_input": {"cmd": "python scripts/automation_context_snapshot.py --write"},
        },
        decision=decision,
    )
    focused = classify_pre_tool_use_warning(
        {
            "hook_event_name": "PreToolUse",
            "tool_name": "exec_command",
            "tool_input": {"cmd": "Get-Content results\\hourly\\blocker.json"},
        },
        decision=decision,
    )

    assert snapshot.should_warn is False
    assert focused.should_warn is False


def test_pre_tool_warning_flags_deep_research_env_and_automation_memory_reads():
    decision = classify_raw_context_need({"flags": []})
    commands = [
        "Get-Content C:\\Users\\Corbin\\Downloads\\deep-research-report (31).md",
        "Get-Content .env",
        "Get-Content C:\\cm\\automations\\hourly\\memory.md",
    ]

    warnings = [
        classify_pre_tool_use_warning(
            {"hook_event_name": "PreToolUse", "tool_name": "exec_command", "tool_input": {"cmd": command}},
            decision=decision,
        )
        for command in commands
    ]

    assert all(warning.warning_only for warning in warnings)
    assert all(warning.should_warn for warning in warnings)
    assert [warning.reasons[0] for warning in warnings] == [
        "deep_research_report",
        "env_file",
        "automation_memory",
    ]


def test_hook_payload_redaction_removes_secret_values_and_truncates():
    payload = {
        "api_key": "abc123",
        "nested": {"bearer_token": "secret-token", "normal": "ok"},
        "prompt": "x" * 500,
    }

    redacted = redact_hook_payload(payload)

    assert redacted["api_key"] == "[REDACTED]"
    assert redacted["nested"]["bearer_token"] == "[REDACTED]"
    assert redacted["nested"]["normal"] == "ok"
    assert redacted["prompt"].endswith("...[truncated]")
    assert len(redacted["prompt"]) < 340


def test_write_hook_event_packet_stays_compact(tmp_path: Path):
    context_dir = tmp_path / "results" / "_context"
    context_dir.mkdir(parents=True)
    (context_dir / "latest-summary.json").write_text(json.dumps({"generated_at": "now"}), encoding="utf-8")
    (context_dir / "latest-flags.json").write_text(
        json.dumps({"flags": [{"reason": "blocker", "path": "results/hourly/blocker.json"}]}),
        encoding="utf-8",
    )
    decision = classify_raw_context_need(json.loads((context_dir / "latest-flags.json").read_text()))

    out_path = write_hook_event(
        tmp_path,
        event="SessionStart",
        payload={"token": "dont-store-me", "large": "z" * 1000},
        decision=decision,
    )

    packet = json.loads(out_path.read_text(encoding="utf-8"))
    assert packet["event"] == "SessionStart"
    assert packet["raw_context"]["required"] is True
    assert packet["payload_sample"]["token"] == "[REDACTED]"
    assert len(out_path.read_text(encoding="utf-8")) < 5000


def test_write_hook_event_records_goal_agent_metadata_and_latest_pointer(tmp_path: Path):
    context_dir = tmp_path / "results" / "_context"
    context_dir.mkdir(parents=True)
    (context_dir / "latest-summary.json").write_text(json.dumps({"generated_at": "now"}), encoding="utf-8")
    (context_dir / "latest-flags.json").write_text(json.dumps({"flags": []}), encoding="utf-8")

    payload = {
        "hook_event": "SubagentStart",
        "thread_id": "thread-123",
        "goal": {
            "status": "active",
            "objective": "Continue the TradingAgents autonomous revision work. " * 20,
        },
        "subagent": {
            "id": "agent-456",
            "name": "Sentinel",
            "role": "reviewer",
        },
        "run": {"id": "run-789"},
        "api_key": "dont-store-me",
    }

    out_path = write_hook_event(
        tmp_path,
        event="SubagentStart",
        payload=payload,
        decision=classify_raw_context_need({"flags": []}),
    )

    packet = json.loads(out_path.read_text(encoding="utf-8"))
    latest = json.loads((context_dir / "hook-events" / "latest.json").read_text(encoding="utf-8"))

    assert packet["hook_context"]["thread_id"] == "thread-123"
    assert packet["hook_context"]["goal_status"] == "active"
    assert packet["hook_context"]["goal_objective_excerpt"].startswith("Continue the TradingAgents")
    assert packet["hook_context"]["goal_objective_truncated"] is True
    assert packet["hook_context"]["agent_id"] == "agent-456"
    assert packet["hook_context"]["agent_name"] == "Sentinel"
    assert packet["hook_context"]["agent_role"] == "reviewer"
    assert packet["hook_context"]["run_id"] == "run-789"
    assert packet["payload_sample"]["api_key"] == "[REDACTED]"
    assert latest["packet_path"] == str(out_path)
    assert latest["hook_context"] == packet["hook_context"]


def test_write_hook_event_records_warning_only_pre_tool_guidance(tmp_path: Path):
    context_dir = tmp_path / "results" / "_context"
    context_dir.mkdir(parents=True)
    (context_dir / "latest-summary.json").write_text(json.dumps({"generated_at": "now"}), encoding="utf-8")
    (context_dir / "latest-flags.json").write_text(json.dumps({"flags": []}), encoding="utf-8")
    payload = {
        "hook_event_name": "PreToolUse",
        "tool_name": "exec_command",
        "tool_input": {"cmd": "Get-Content results\\hourly_supervisor\\old-big-packet.json"},
    }
    decision = classify_raw_context_need({"flags": []})
    warning = classify_pre_tool_use_warning(payload, decision=decision)

    out_path = write_hook_event(
        tmp_path,
        event="PreToolUse",
        payload=payload,
        decision=decision,
        pre_tool_warning=warning,
    )

    packet = json.loads(out_path.read_text(encoding="utf-8"))
    assert packet["pre_tool_warning"]["warning_only"] is True
    assert packet["pre_tool_warning"]["should_warn"] is True
    assert packet["pre_tool_warning"]["block_execution"] is False
    assert "raw_context_packet_read" in packet["pre_tool_warning"]["reasons"]


def test_hook_script_detects_native_hook_event_payload_names(monkeypatch):
    module = _load_token_context_hook_module()
    monkeypatch.delenv("CODEX_HOOK_EVENT", raising=False)

    assert module._detect_event({"hook_event_name": "SubagentStop"}) == "SubagentStop"
    assert module._detect_event({"hookEventName": "PreCompact"}) == "PreCompact"
    assert module._detect_event({"hook": {"name": "UserPromptSubmit"}}) == "UserPromptSubmit"


def test_hook_script_env_event_takes_precedence(monkeypatch):
    module = _load_token_context_hook_module()
    monkeypatch.setenv("CODEX_HOOK_EVENT", "Stop")

    assert module._detect_event({"hook_event_name": "SessionStart"}) == "Stop"


def test_goal_agent_context_contract_documents_states_and_output_rules():
    doc_path = Path("docs/orchestration/goal-agent-context-contract.md")
    text = doc_path.read_text(encoding="utf-8")

    for state in (
        "goal_absent",
        "goal_active",
        "goal_waiting_for_user",
        "goal_blocked",
        "goal_complete",
    ):
        assert state in text
    for phrase in (
        "exact files inspected",
        "exact files changed",
        "tests or commands run",
        "raw packets opened and why",
        "must not create, complete, block, or rewrite goals",
    ):
        assert phrase in text
