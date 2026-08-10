from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def _load_snapshot_module():
    module_path = Path("scripts/automation_context_snapshot.py")
    spec = importlib.util.spec_from_file_location("automation_context_snapshot", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_overnight_summary_exposes_original_graph_tickers(tmp_path):
    snapshot = _load_snapshot_module()
    packet = {
        "generated_at": "2026-06-08T10:00:00+00:00",
        "analysis_only": True,
        "ranked_candidates": [{"symbol": "MSFT"}, {"symbol": "ORCL"}],
        "submitted": [],
        "overnight_quality": {
            "full_graph_count": 1,
            "fallback_count": 1,
            "graph_failure_count": 0,
            "graph_config": {"graph_profile": "compact"},
        },
        "original_tradingagents_graph": {
            "selected_tickers": ["MSFT"],
            "successful_tickers": ["MSFT"],
            "failed_tickers": [],
        },
    }
    path = tmp_path / "overnight.json"
    path.write_text(json.dumps(packet), encoding="utf-8")

    summary = snapshot.summarize_packet("overnight", path)

    assert summary["full_graph_count"] == 1
    assert summary["original_graph_selected_tickers"] == ["MSFT"]
    assert summary["original_graph_successful_tickers"] == ["MSFT"]
    assert summary["original_graph_failed_tickers"] == []


def test_preopen_summary_does_not_mark_intentional_live_freeze_as_stale(tmp_path):
    snapshot = _load_snapshot_module()
    packet = {
        "schema": "compact_preopen_validation_v1",
        "generated_at": "2026-07-15T19:03:32+00:00",
        "analysis_only": True,
        "can_submit_orders": False,
        "execution_authority": "none",
        "overall_status": "pass_with_warnings",
        "market_session": "regular",
        "status_counts": {"pass": 4, "warn": 1},
        "failed_check_ids": [],
        "warned_check_ids": ["live_sizing_room_and_buying_power"],
        "skipped_check_ids": [],
        "account_summary": {
            "live": {"position_count": 4, "open_order_count": 0},
            "paper": {"position_count": 14, "open_order_count": 0},
        },
    }
    path = tmp_path / "preopen-validation.json"
    path.write_text(json.dumps(packet), encoding="utf-8")

    summary = snapshot.summarize_packet("preopen_validation", path)

    assert summary["fail_closed_live_control_warning_only"] is True
    assert "stale" not in summary["drilldown_reasons"]


def test_automation_root_uses_codex_home(tmp_path, monkeypatch):
    codex_home = tmp_path / ".codex"
    monkeypatch.setenv("CODEX_HOME", str(codex_home))

    snapshot = _load_snapshot_module()

    assert codex_home / "automations" == snapshot.AUTOMATION_ROOT


def test_automation_index_uses_discovered_ids_as_current_authority(tmp_path, monkeypatch):
    automation_root = tmp_path / "automations"
    definitions = {
        "tradingagents-autonomous-self-healer": "TradingAgents autonomous self-healer",
        "tradingagents-market-supervisor": "TradingAgents market supervisor",
    }
    for automation_id, name in definitions.items():
        directory = automation_root / automation_id
        directory.mkdir(parents=True)
        (directory / "automation.toml").write_text(
            "\n".join(
                [
                    f'name = "{name}"',
                    'status = "ACTIVE"',
                    'model = "gpt-5.6-sol"',
                    'reasoning_effort = "high"',
                    'rrule = "RRULE:FREQ=HOURLY"',
                    'prompt = "Operate TradingAgents safely."',
                ]
            ),
            encoding="utf-8",
        )

    snapshot = _load_snapshot_module()
    monkeypatch.setattr(snapshot, "AUTOMATION_ROOT", automation_root)

    index = snapshot.collect_automation_index()

    assert index["automation_count"] == 2
    assert [item["id"] for item in index["automations"]] == sorted(definitions)
    assert all(not item.get("missing") for item in index["automations"])
    assert index["known_managed_ids"] == sorted(definitions)


def test_automation_index_excludes_non_tradingagents_automations(tmp_path, monkeypatch):
    automation_root = tmp_path / "automations"
    definitions = {
        "tradingagents-daily-report": "Run the TradingAgents daily report.",
        "weekly-review": "Summarize unrelated weekly work.",
    }
    for automation_id, prompt in definitions.items():
        directory = automation_root / automation_id
        directory.mkdir(parents=True)
        (directory / "automation.toml").write_text(
            "\n".join(
                [
                    f'name = "{automation_id}"',
                    'status = "ACTIVE"',
                    'rrule = "RRULE:FREQ=WEEKLY"',
                    f'prompt = "{prompt}"',
                ]
            ),
            encoding="utf-8",
        )

    snapshot = _load_snapshot_module()
    monkeypatch.setattr(snapshot, "AUTOMATION_ROOT", automation_root)

    index = snapshot.collect_automation_index()

    assert [item["id"] for item in index["automations"]] == ["tradingagents-daily-report"]
