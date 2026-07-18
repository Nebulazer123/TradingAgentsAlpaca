from __future__ import annotations

import datetime as dt
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


def test_snapshot_exposes_only_compact_incident_status(tmp_path, monkeypatch):
    snapshot = _load_snapshot_module()
    monkeypatch.setattr(snapshot, "ROOT", tmp_path)
    incident_dir = (
        tmp_path
        / "results"
        / "control_plane"
        / "incidents"
        / "inc-nflx-rule-conflict"
    )
    incident_dir.mkdir(parents=True)
    (incident_dir / "latest.json").write_text(
        json.dumps(
            {
                "incident_id": "inc-nflx-rule-conflict",
                "stage": "external_blocked",
                "owner_role": "reliability_controller",
                "created_at": "2026-07-18T00:00:00+00:00",
                "history": [{"raw": "must not appear"}],
                "evidence_refs": ["private-evidence"],
            }
        ),
        encoding="utf-8",
    )

    summary = snapshot.summarize_incidents(
        now=dt.datetime(2026, 7, 18, 0, 12, tzinfo=dt.timezone.utc)
    )

    assert summary == {
        "active_incident_count": 1,
        "oldest_active_incident_minutes": 12,
        "unowned_incident_count": 0,
        "external_blocked_count": 1,
        "latest_incident_ref": "results/control_plane/incidents/inc-nflx-rule-conflict/latest.json",
    }


def test_snapshot_skips_malformed_or_invalid_incident_snapshots(tmp_path, monkeypatch):
    snapshot = _load_snapshot_module()
    monkeypatch.setattr(snapshot, "ROOT", tmp_path)
    incidents_root = tmp_path / "results" / "control_plane" / "incidents"
    for directory_name, payload in {
        "empty": {},
        "bad-stage": {
            "incident_id": "inc-bad-stage",
            "stage": "unknown",
            "created_at": "2026-07-18T00:00:00+00:00",
        },
        "bad-created-at": {
            "incident_id": "inc-bad-date",
            "stage": "detected",
            "created_at": "not-a-date",
        },
        "bad-id": {
            "incident_id": "../outside",
            "stage": "detected",
            "created_at": "2026-07-18T00:00:00+00:00",
        },
    }.items():
        incident_dir = incidents_root / directory_name
        incident_dir.mkdir(parents=True)
        (incident_dir / "latest.json").write_text(json.dumps(payload), encoding="utf-8")

    assert snapshot.summarize_incidents(
        now=dt.datetime(2026, 7, 18, 0, 12, tzinfo=dt.timezone.utc)
    ) == {
        "active_incident_count": 0,
        "oldest_active_incident_minutes": 0,
        "unowned_incident_count": 0,
        "external_blocked_count": 0,
        "latest_incident_ref": None,
    }
