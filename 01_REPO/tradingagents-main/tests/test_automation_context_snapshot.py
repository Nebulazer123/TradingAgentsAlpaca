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
