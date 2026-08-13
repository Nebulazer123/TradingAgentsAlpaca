from __future__ import annotations

import datetime as dt
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import tomllib

from tradingagents.orchestration.work_packets import build_packet_id


def _load_snapshot_module():
    module_path = Path("scripts/automation_context_snapshot.py")
    spec = importlib.util.spec_from_file_location("automation_context_snapshot", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_snapshot_script_runs_directly_from_canonical_root():
    result = subprocess.run(
        [sys.executable, "scripts/automation_context_snapshot.py", "--help"],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "usage:" in result.stdout.lower()


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


def _write_valid_autonomous_contract(config_dir):
    (config_dir / "automation_roles.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "roles": {
                    "execution_operator": {
                        "allowed_actions": ["order_submit"],
                        "forbidden_effects": ["trade_decision"],
                    }
                },
                "automations": {"tradingagents-market-supervisor": "execution_operator"},
            }
        ),
        encoding="utf-8",
    )
    (config_dir / "autonomous_firm.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "machine_actions": ["order_submit"],
                "human_actions": ["credential_change"],
            }
        ),
        encoding="utf-8",
    )


def _compact_context(tmp_path, monkeypatch, *, authority="paper"):
    snapshot = _load_snapshot_module()
    packet_path = tmp_path / "results" / "packets" / "latest.json"
    packet_path.parent.mkdir(parents=True)
    packet_path.write_text(
        json.dumps(
            {
                "generated_at": "2026-08-13T12:00:00+00:00",
                "analysis_only": True,
                "execution_authority": authority,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(snapshot, "ROOT", tmp_path)
    monkeypatch.setattr(snapshot, "LATEST_PACKETS", [("synthetic", packet_path.parent)])
    monkeypatch.setattr(snapshot, "LATEST_PACKET_FILES", [])
    return snapshot.collect_snapshot(refresh=False)


def test_compact_context_includes_packet_and_autonomous_contract_status(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    _write_valid_autonomous_contract(config_dir)

    summary = _compact_context(tmp_path, monkeypatch)

    assert summary["latest_packets"]
    assert summary["automation_role_contract_status"] in {"pass", "warn", "fail"}
    assert summary["execution_authority"] in {"none", "paper", "normal_live"}
    assert summary["automation_role_contract_status"] == "pass"
    assert summary["execution_authority"] == "paper"
    assert summary["recovery_owner"] is None
    assert summary["recovery_phase"] is None
    assert summary["recovery_last_failure"] is None
    assert summary["recovery_external_blocker"] is None


def test_compact_context_fails_closed_when_contract_config_is_missing(tmp_path, monkeypatch):
    summary = _compact_context(tmp_path, monkeypatch)

    assert summary["automation_role_contract_status"] == "fail"
    assert set(summary["automation_role_contract_issues"]) == {
        "automation_roles_unreadable",
        "autonomous_firm_unreadable",
    }
    assert summary["execution_authority"] == "paper"


def test_compact_context_fails_closed_when_contract_config_is_unreadable(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "automation_roles.json").write_text("{bad", encoding="utf-8")
    (config_dir / "autonomous_firm.json").write_text("[bad", encoding="utf-8")

    summary = _compact_context(tmp_path, monkeypatch)

    assert summary["automation_role_contract_status"] == "fail"
    assert set(summary["automation_role_contract_issues"]) == {
        "automation_roles_unreadable",
        "autonomous_firm_unreadable",
    }


def test_compact_context_fails_closed_on_malformed_role_and_assignment_shapes(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "automation_roles.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "roles": {"execution_operator": {"allowed_actions": "order_submit"}},
                "automations": {"tradingagents-market-supervisor": "unknown_role"},
            }
        ),
        encoding="utf-8",
    )
    (config_dir / "autonomous_firm.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "machine_actions": ["order_submit"],
                "human_actions": ["credential_change"],
            }
        ),
        encoding="utf-8",
    )

    summary = _compact_context(tmp_path, monkeypatch)

    assert summary["automation_role_contract_status"] == "fail"
    assert set(summary["automation_role_contract_issues"]) == {
        "automation_roles_malformed",
        "automation_assignments_malformed",
    }


def test_compact_context_rejects_board_scope_outside_its_owner_role(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    _write_valid_autonomous_contract(config_dir)
    roles_path = config_dir / "automation_roles.json"
    contract = json.loads(roles_path.read_text(encoding="utf-8"))
    contract["automation_constraints"] = {
        "tradingagents-market-supervisor": {
            "allowed_actions": ["trade_decision"],
            "required_outputs": ["portfolio_decision"],
            "forbidden_effects": [],
        }
    }
    roles_path.write_text(json.dumps(contract), encoding="utf-8")

    summary = _compact_context(tmp_path, monkeypatch)

    assert summary["automation_role_contract_status"] == "fail"
    assert summary["automation_role_contract_issues"] == [
        "automation_constraints_malformed"
    ]


def test_compact_context_warns_and_does_not_elevate_invalid_packet_authority(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    _write_valid_autonomous_contract(config_dir)

    summary = _compact_context(tmp_path, monkeypatch, authority="unbounded_live")

    assert summary["automation_role_contract_status"] == "pass"
    assert summary["execution_authority_status"] == "warn"
    assert summary["execution_authority"] == "none"
    assert summary["execution_authority_invalid_labels"] == ["synthetic"]


def test_execution_board_compact_context_projects_a_resolved_autonomous_hold(tmp_path):
    snapshot = _load_snapshot_module()
    packet = {
        "generated_at": "2026-08-13T12:00:00+00:00",
        "analysis_only": True,
        "can_submit_orders": False,
        "execution_authority": "none",
        "recommendation": "no_action_needed",
        "metrics": {},
        "packet_reviews": [{"decision": "loss-review", "packet": "results/hourly.json"}],
        "autonomous_loss_decision": {
            "decision": "HOLD",
            "symbol": "SIXTEENCHARS.TSM",
            "decision_id": "a" * 64,
            "ledger_packet_id": build_packet_id("a" * 64, "portfolio_decision"),
            "trade_decision_resolved": True,
            "exit_allowed": False,
            "analysis_only": True,
            "execution_authority": "none",
            "can_submit_orders": False,
        },
    }
    path = tmp_path / "execution-board.json"
    path.write_text(json.dumps(packet), encoding="utf-8")

    summary = snapshot.summarize_packet("execution_board_review", path)

    assert summary["autonomous_loss_decision_status"] == "autonomous_hold"
    assert summary["autonomous_loss_decision_plain_english"] == (
        "Autonomous HOLD: the Portfolio Executive decided to keep SIXTEENCHARS.TSM; no order was created."
    )
    assert summary["latest_packet_needs_review"] is False
    assert "board_review" not in summary["drilldown_reasons"]
    assert "manual_board_review" not in json.dumps(summary)


def test_execution_board_compact_context_projects_scalar_only_autonomous_sell():
    """The phone-sized view accepts the producer's scalar-only sidecar receipt."""
    snapshot = _load_snapshot_module()
    decision = {
        "decision": "SELL",
        "symbol": "TSM",
        "decision_id": "b" * 64,
        "ledger_packet_id": build_packet_id("b" * 64, "portfolio_decision"),
        "trade_decision_resolved": True,
        "exit_allowed": True,
        "analysis_only": True,
        "execution_authority": "none",
        "can_submit_orders": False,
    }

    compact = snapshot.compact_autonomous_loss_decision(decision)

    assert compact["status"] == "autonomous_sell"
    assert compact["decision"] == "SELL"
    assert compact["symbol"] == "TSM"
    assert compact["plain_english"].endswith("no order was created.")


@pytest.mark.parametrize(
    "ledger_packet_id",
    [
        "b" * 64,
        build_packet_id("b" * 64, "portfolio_decision"),
        build_packet_id("a" * 63, "portfolio_decision"),
    ],
)
def test_execution_board_compact_context_rejects_noncanonical_ledger_receipts(
    tmp_path, ledger_packet_id
):
    snapshot = _load_snapshot_module()
    packet = {
        "analysis_only": True,
        "can_submit_orders": False,
        "execution_authority": "none",
        "autonomous_loss_decision": {
            "decision": "HOLD",
            "symbol": "TSM",
            "decision_id": "a" * 64,
            "ledger_packet_id": ledger_packet_id,
            "decision_evidence": {
                "path": "loss_board_decisions/decision.json",
                "sha256": "c" * 64,
                "size_bytes": 1,
            },
            "trade_decision_resolved": True,
            "exit_allowed": False,
            "analysis_only": True,
            "execution_authority": "none",
            "can_submit_orders": False,
        },
    }
    path = tmp_path / "execution-board.json"
    path.write_text(json.dumps(packet), encoding="utf-8")

    summary = snapshot.summarize_packet("execution_board_review", path)

    assert summary["autonomous_loss_decision_status"] == "business_decision_pending"


def test_execution_board_compact_context_keeps_invalid_decision_pending(tmp_path):
    snapshot = _load_snapshot_module()
    packet = {
        "generated_at": "2026-08-13T12:00:00+00:00",
        "analysis_only": True,
        "can_submit_orders": False,
        "execution_authority": "none",
        "metrics": {},
        "packet_reviews": [{"decision": "loss-review", "packet": "results/hourly.json"}],
        "autonomous_loss_decision": {
            "decision": "HOLD",
            "symbol": "TSM",
            "trade_decision_resolved": True,
            "analysis_only": True,
            "execution_authority": "none",
            "can_submit_orders": False,
        },
    }
    path = tmp_path / "execution-board.json"
    path.write_text(json.dumps(packet), encoding="utf-8")

    summary = snapshot.summarize_packet("execution_board_review", path)

    assert summary["autonomous_loss_decision_status"] == "business_decision_pending"
    assert summary["latest_packet_needs_review"] is True
    assert "manual_board_review" not in json.dumps(summary)


def test_installed_execution_board_prompt_owns_decision_but_not_execution():
    path = (
        Path.home()
        / ".codex"
        / "automations"
        / "tradingagents-autonomous-execution-board"
        / "automation.toml"
    )
    if not path.exists():
        pytest.skip("installed execution BOARD automation is unavailable")

    automation = tomllib.loads(path.read_text(encoding="utf-8"))
    prompt = automation["prompt"]

    assert "own HOLD-versus-SELL trade decisions" in prompt
    assert "do not own execution or order submission" in prompt
    assert "missing, stale, malformed, contradictory" in prompt
    assert "record autonomous HOLD" in prompt
    assert "separate execution intent" in prompt
    assert "Never change strategy, risk, or promotion settings" in prompt
    assert "Never freeze, refresh, re-arm, or unfreeze live control" in prompt
    assert "freeze live trading" not in prompt
    assert automation["notification_policy"] == "failed_runs_only"
    assert automation["rrule"] == (
        "RRULE:FREQ=WEEKLY;BYHOUR=9,10,11,12,13,14,15;BYMINUTE=50;BYDAY=MO,TU,WE,TH,FR"
    )


def test_incident_summary_projects_only_structural_blocker_presence(
    tmp_path, monkeypatch
):
    snapshot = _load_snapshot_module()
    incident_root = tmp_path / "results" / "control_plane" / "incidents"
    valid = incident_root / "recovery-nflx" / "latest.json"
    valid.parent.mkdir(parents=True)
    valid.write_text(
        json.dumps(
            {
                "schema_version": "tradingagents.incident.v1",
                "incident_id": "recovery-nflx",
                "owner_role": "reliability_controller",
                "updated_at": "2026-08-13T12:00:00+00:00",
                "external_blockers": ["broker rejected Authorization: Bearer test-secret-token"],
                "recovery": {
                    "phase": "reconcile",
                    "last_failure": {"kind": "external_blocked"},
                },
                "history": [{"secret": "must-not-leak"}],
                "evidence_refs": ["/private/raw-packet.json"],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(snapshot, "ROOT", tmp_path)

    summary = snapshot.summarize_incidents(
        now=dt.datetime(2026, 8, 13, 12, 0, tzinfo=dt.timezone.utc)
    )

    assert summary == {
        "recovery_owner": "reliability_controller",
        "recovery_phase": "reconcile",
        "recovery_last_failure": "external_blocked",
        "recovery_external_blocker": "external_action_required",
    }


def _write_incident_latest(
    root: Path,
    incident_id: str,
    *,
    owner_role: str = "reliability_controller",
    phase: str = "reconcile",
    failure_kind: str = "external_blocked",
    blockers: list[str] | None = None,
    schema_version: str = "tradingagents.incident.v1",
    record_incident_id: str | None = None,
) -> Path:
    path = root / incident_id / "latest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": schema_version,
                "incident_id": (
                    incident_id if record_incident_id is None else record_incident_id
                ),
                "owner_role": owner_role,
                "updated_at": "2026-08-13T12:00:00+00:00",
                "external_blockers": blockers if blockers is not None else [],
                "recovery": {
                    "phase": phase,
                    "last_failure": {"kind": failure_kind},
                },
            }
        ),
        encoding="utf-8",
    )
    return path


def test_incident_summary_never_projects_hostile_blocker_content(tmp_path, monkeypatch):
    snapshot = _load_snapshot_module()
    incident_root = tmp_path / "results" / "control_plane" / "incidents"
    secrets = [
        "Authorization: Basic QWxhZGRpbjpvcGVuIHNlc2FtZQ==",
        "Cookie: sessionid=very-secret-session-cookie",
        "AKIAIOSFODNN7EXAMPLE",
        "-----BEGIN PRIVATE KEY-----\nprivate-key-material\n-----END PRIVATE KEY-----",
        "https://username:password@example.invalid/raw-response?token=secret-token",
        '{"raw_response":"super-secret-response-body"}',
    ]
    _write_incident_latest(
        incident_root,
        "hostile-blockers",
        blockers=secrets,
    )
    monkeypatch.setattr(snapshot, "ROOT", tmp_path)

    summary = snapshot.summarize_incidents(
        now=dt.datetime(2026, 8, 13, 12, 0, tzinfo=dt.timezone.utc)
    )

    assert summary["recovery_external_blocker"] == "external_action_required"
    rendered = json.dumps(summary)
    for secret in secrets:
        assert secret not in rendered


def test_incident_summary_uses_newest_metadata_not_first_32_names(tmp_path, monkeypatch):
    snapshot = _load_snapshot_module()
    incident_root = tmp_path / "results" / "control_plane" / "incidents"
    base = 1_700_000_000
    for index in range(33):
        path = _write_incident_latest(
            incident_root,
            f"a-{index:02d}",
            phase="reconcile",
            failure_kind="transient",
        )
        os.utime(path, (base + index, base + index))
    newest = _write_incident_latest(
        incident_root,
        "z-newest",
        phase="rearm",
        failure_kind="external_blocked",
        blockers=["human broker confirmation required"],
    )
    os.utime(newest, (base + 100, base + 100))
    monkeypatch.setattr(snapshot, "ROOT", tmp_path)

    summary = snapshot.summarize_incidents(
        now=dt.datetime(2026, 8, 13, 12, 0, tzinfo=dt.timezone.utc)
    )

    assert summary == {
        "recovery_owner": "reliability_controller",
        "recovery_phase": "rearm",
        "recovery_last_failure": "external_blocked",
        "recovery_external_blocker": "external_action_required",
    }


def test_incident_summary_fails_closed_for_malformed_newest_record(tmp_path, monkeypatch):
    snapshot = _load_snapshot_module()
    incident_root = tmp_path / "results" / "control_plane" / "incidents"
    older = _write_incident_latest(incident_root, "old-valid")
    newest = incident_root / "new-malformed" / "latest.json"
    newest.parent.mkdir(parents=True)
    newest.write_text("{not-json", encoding="utf-8")
    os.utime(older, (1_700_000_000, 1_700_000_000))
    os.utime(newest, (1_700_000_100, 1_700_000_100))
    monkeypatch.setattr(snapshot, "ROOT", tmp_path)

    assert snapshot.summarize_incidents(
        now=dt.datetime(2026, 8, 13, 12, 0, tzinfo=dt.timezone.utc)
    ) == {
        "recovery_owner": None,
        "recovery_phase": None,
        "recovery_last_failure": None,
        "recovery_external_blocker": "recovery_incident_unknown",
    }


def test_incident_summary_fails_closed_for_oversized_newest_record(tmp_path, monkeypatch):
    snapshot = _load_snapshot_module()
    incident_root = tmp_path / "results" / "control_plane" / "incidents"
    older = _write_incident_latest(incident_root, "old-valid")
    newest = incident_root / "new-oversized" / "latest.json"
    newest.parent.mkdir(parents=True)
    newest.write_bytes(b"{" + b"x" * 65_537)
    os.utime(older, (1_700_000_000, 1_700_000_000))
    os.utime(newest, (1_700_000_100, 1_700_000_100))
    monkeypatch.setattr(snapshot, "ROOT", tmp_path)

    assert snapshot.summarize_incidents(
        now=dt.datetime(2026, 8, 13, 12, 0, tzinfo=dt.timezone.utc)
    ) == {
        "recovery_owner": None,
        "recovery_phase": None,
        "recovery_last_failure": None,
        "recovery_external_blocker": "recovery_incident_unknown",
    }


def test_incident_summary_rejects_unknown_recovery_owner_or_phase(tmp_path, monkeypatch):
    snapshot = _load_snapshot_module()
    incident_root = tmp_path / "results" / "control_plane" / "incidents"
    path = _write_incident_latest(
        incident_root,
        "unknown-contract-value",
        owner_role="untrusted_owner",
        phase="skip_the_checks",
    )
    os.utime(path, (1_700_000_100, 1_700_000_100))
    monkeypatch.setattr(snapshot, "ROOT", tmp_path)

    assert snapshot.summarize_incidents(
        now=dt.datetime(2026, 8, 13, 12, 0, tzinfo=dt.timezone.utc)
    ) == {
        "recovery_owner": None,
        "recovery_phase": None,
        "recovery_last_failure": None,
        "recovery_external_blocker": "recovery_incident_unknown",
    }


@pytest.mark.parametrize(
    "shape",
    ["foreign_schema", "minimal_legacy_shape", "mismatched_incident_id"],
)
def test_incident_summary_requires_exact_schema_and_directory_bound_incident_id(
    tmp_path, monkeypatch, shape
):
    snapshot = _load_snapshot_module()
    incident_root = tmp_path / "results" / "control_plane" / "incidents"
    path = _write_incident_latest(incident_root, "bound-incident")
    record = json.loads(path.read_text(encoding="utf-8"))
    if shape == "foreign_schema":
        record["schema_version"] = "foreign.incident.v1"
    elif shape == "minimal_legacy_shape":
        record.pop("schema_version")
        record.pop("incident_id")
    else:
        record["incident_id"] = "different-incident"
    path.write_text(json.dumps(record), encoding="utf-8")
    monkeypatch.setattr(snapshot, "ROOT", tmp_path)

    assert snapshot.summarize_incidents(
        now=dt.datetime(2026, 8, 13, 12, 0, tzinfo=dt.timezone.utc)
    ) == {
        "recovery_owner": None,
        "recovery_phase": None,
        "recovery_last_failure": None,
        "recovery_external_blocker": "recovery_incident_unknown",
    }


def test_incident_summary_fails_closed_when_candidate_cap_is_exceeded(
    tmp_path, monkeypatch
):
    snapshot = _load_snapshot_module()
    incident_root = tmp_path / "results" / "control_plane" / "incidents"
    for index in range(snapshot.INCIDENT_SUMMARY_STAT_LIMIT + 1):
        _write_incident_latest(incident_root, f"adversarial-{index:03d}")
    monkeypatch.setattr(snapshot, "ROOT", tmp_path)

    assert snapshot.summarize_incidents(
        now=dt.datetime(2026, 8, 13, 12, 0, tzinfo=dt.timezone.utc)
    ) == {
        "recovery_owner": None,
        "recovery_phase": None,
        "recovery_last_failure": None,
        "recovery_external_blocker": "recovery_incident_unknown",
    }


def test_incident_summary_fails_closed_when_incident_root_is_unreadable(
    tmp_path, monkeypatch
):
    snapshot = _load_snapshot_module()
    monkeypatch.setattr(snapshot, "ROOT", tmp_path)

    def unreadable_scandir(_path):
        raise PermissionError("test-only unreadable incident root")

    monkeypatch.setattr(snapshot.os, "scandir", unreadable_scandir)

    assert snapshot.summarize_incidents(
        now=dt.datetime(2026, 8, 13, 12, 0, tzinfo=dt.timezone.utc)
    ) == {
        "recovery_owner": None,
        "recovery_phase": None,
        "recovery_last_failure": None,
        "recovery_external_blocker": "recovery_incident_unknown",
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        pytest.param("owner_role", [], id="owner-list"),
        pytest.param("owner_role", {}, id="owner-dict"),
        pytest.param("owner_role", None, id="owner-null"),
        pytest.param("owner_role", 7, id="owner-number"),
        pytest.param("phase", [], id="phase-list"),
        pytest.param("phase", {}, id="phase-dict"),
        pytest.param("phase", None, id="phase-null"),
        pytest.param("phase", 7, id="phase-number"),
        pytest.param("failure_kind", [], id="failure-kind-list"),
        pytest.param("failure_kind", {}, id="failure-kind-dict"),
        pytest.param("failure_kind", None, id="failure-kind-null"),
        pytest.param("failure_kind", 7, id="failure-kind-number"),
    ],
)
def test_incident_summary_rejects_nonstring_membership_values(
    tmp_path, monkeypatch, field, value
):
    snapshot = _load_snapshot_module()
    incident_root = tmp_path / "results" / "control_plane" / "incidents"
    path = _write_incident_latest(incident_root, "typed-incident")
    record = json.loads(path.read_text(encoding="utf-8"))
    if field == "owner_role":
        record["owner_role"] = value
    elif field == "phase":
        record["recovery"]["phase"] = value
    else:
        record["recovery"]["last_failure"]["kind"] = value
    path.write_text(json.dumps(record), encoding="utf-8")
    monkeypatch.setattr(snapshot, "ROOT", tmp_path)

    assert snapshot.summarize_incidents(
        now=dt.datetime(2026, 8, 13, 12, 0, tzinfo=dt.timezone.utc)
    ) == {
        "recovery_owner": None,
        "recovery_phase": None,
        "recovery_last_failure": None,
        "recovery_external_blocker": "recovery_incident_unknown",
    }
