import datetime as dt
import hashlib
import json
import tempfile
import threading
from dataclasses import replace
from pathlib import Path

import pytest
from typer.testing import CliRunner

from cli.main import app
from tradingagents.orchestration.incidents import Incident, IncidentStage, transition_incident
from tradingagents.orchestration.recovery import (
    RecoveryEvidence,
    evaluate_rearm_readiness,
    rearm_after_verified_recovery,
    write_rearm_receipt,
)
from tradingagents.policy.live_control import load_live_control_state, write_live_control_state

NOW = dt.datetime(2026, 7, 18, 12, 0, tzinfo=dt.timezone.utc)


def _evidence(**overrides):
    values = {
        "incident_id": "inc-nflx-rule-conflict",
        "repairer_run_id": "repair-1",
        "verifier_run_id": "verify-1",
        "repairer_role_id": "repairer",
        "verifier_role_id": "verifier",
        "root_cause_resolved": True,
        "focused_tests_passed": True,
        "promotion_evidence_fresh": True,
        "promotion_issues": (),
        "broker_reconciliation_matched": True,
        "broker_reconciliation_issues": (),
        "broker_write_calls": 0,
        "external_blockers": (),
    }
    source_dir = Path(tempfile.mkdtemp())
    source_paths = {}
    source_hashes = {}
    for name in ("incident", "reconciliation", "promotion", "focused"):
        path = source_dir / f"{name}.json"
        path.write_text("{}", encoding="utf-8")
        source_paths[name] = str(path.resolve())
        source_hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest_path = source_dir / "manifest.json"
    manifest_path.write_text("{}", encoding="utf-8")
    values.update({
        "source_bindings": {"incident_id": "inc-nflx-rule-conflict", "symbol": "NFLX", "broker_account": "live", "environment": "test", "source_revision": "abc"},
        "source_packet_paths": source_paths,
        "source_packet_sha256": source_hashes,
        "recovery_manifest_path": str(manifest_path.resolve()),
        "recovery_manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
    })
    values.update(overrides)
    return RecoveryEvidence(**values)


def test_clean_independent_evidence_is_ready():
    verdict = evaluate_rearm_readiness(_evidence())

    assert verdict.ready is True
    assert verdict.issues == ()


@pytest.mark.parametrize(
    "overrides",
    [
        {"verifier_run_id": "repair-1"},
        {"verifier_role_id": "repairer"},
        {"root_cause_resolved": False},
        {"focused_tests_passed": False},
        {"promotion_evidence_fresh": False},
        {"promotion_issues": ("rule conflict",)},
        {"broker_reconciliation_matched": False},
        {"broker_reconciliation_issues": ("unknown open order",)},
        {"broker_write_calls": 1},
        {"external_blockers": ("credentials",)},
    ],
)
def test_any_unresolved_integrity_condition_blocks_rearm(overrides):
    assert evaluate_rearm_readiness(_evidence(**overrides)).ready is False


def test_verified_recovery_writes_receipt_before_bounded_live_control(tmp_path):
    control_path = tmp_path / "live_control.json"
    receipt_dir = tmp_path / "rearm"
    write_live_control_state(
        control_path,
        frozen=True,
        reason="incident",
        dead_man_expires_at=NOW + dt.timedelta(days=1),
    )

    result = rearm_after_verified_recovery(
        evidence=_evidence(),
        control_path=control_path,
        receipt_dir=receipt_dir,
        ttl_minutes=15,
        now=NOW,
    )

    state, issues = load_live_control_state(control_path, now=NOW)
    assert issues == []
    assert state["frozen"] is False
    assert state["recovery_receipt_path"] == result["receipt_path"]
    assert state["recovery_receipt_sha256"] == result["receipt_sha256"]
    receipt = json.loads((receipt_dir / Path(result["receipt_path"]).name).read_text())
    assert receipt["can_submit_orders"] is False
    assert receipt["broker_write_calls"] == 0


@pytest.mark.parametrize("ttl", [True, 0, 91, 1.5, "15"])
def test_rearm_rejects_non_strict_or_out_of_range_ttl(tmp_path, ttl):
    control_path = tmp_path / "live_control.json"
    original = '{"frozen": true, "reason": "incident", "dead_man_expires_at": "2026-07-19T12:00:00+00:00"}'
    control_path.write_text(original, encoding="utf-8")

    with pytest.raises(ValueError, match="ttl_minutes"):
        rearm_after_verified_recovery(
            evidence=_evidence(),
            control_path=control_path,
            receipt_dir=tmp_path / "rearm",
            ttl_minutes=ttl,
            now=NOW,
        )

    assert control_path.read_text(encoding="utf-8") == original


def test_rearm_requires_existing_valid_frozen_control(tmp_path):
    control_path = tmp_path / "live_control.json"
    write_live_control_state(
        control_path,
        frozen=False,
        reason="healthy",
        dead_man_expires_at=NOW + dt.timedelta(minutes=30),
    )

    with pytest.raises(ValueError, match="currently frozen"):
        rearm_after_verified_recovery(
            evidence=_evidence(),
            control_path=control_path,
            receipt_dir=tmp_path / "rearm",
            now=NOW,
        )


def test_tampered_recovery_receipt_closes_live_control(tmp_path):
    control_path = tmp_path / "live_control.json"
    write_live_control_state(
        control_path,
        frozen=True,
        reason="incident",
        dead_man_expires_at=NOW + dt.timedelta(days=1),
    )
    result = rearm_after_verified_recovery(
        evidence=_evidence(),
        control_path=control_path,
        receipt_dir=tmp_path / "rearm",
        now=NOW,
    )
    receipt_path = Path(result["receipt_path"])
    receipt_path.write_text('{"tampered": true}', encoding="utf-8")

    _state, issues = load_live_control_state(control_path, now=NOW)

    assert any("receipt" in issue for issue in issues)


def test_recovery_cli_returns_fail_closed_json_for_malformed_packet(tmp_path):
    result = CliRunner().invoke(
        app,
        [
            "policy",
            "recover-incident",
            "--incident-path",
            str(tmp_path / "bad.json"),
            "--reconciliation-path",
            str(tmp_path / "missing.json"),
            "--promotion-sync-path",
            str(tmp_path / "missing-promotion.json"),
            "--focused-proof-path",
            str(tmp_path / "missing-proof.json"),
            "--repairer-run-id",
            "repair-1",
            "--verifier-run-id",
            "verify-1",
            "--json-output",
        ],
    )

    assert result.exit_code == 1, result.output
    assert json.loads(result.stdout)["ready"] is False


def test_refresh_live_control_cannot_unfreeze_frozen_state(tmp_path):
    control_path = tmp_path / "live_control.json"
    original = '{"frozen": true, "reason": "incident", "dead_man_expires_at": "2026-07-19T12:00:00+00:00"}'
    control_path.write_text(original, encoding="utf-8")

    result = CliRunner().invoke(
        app,
        ["policy", "refresh-live-control", "--reason", "bypass", "--control-path", str(control_path), "--json-output"],
    )

    assert result.exit_code == 1, result.output
    assert json.loads(result.stdout)["refreshed"] is False
    assert control_path.read_text(encoding="utf-8") == original


def test_recovery_cli_rearms_from_hash_bound_manifest_packets(tmp_path):
    now = dt.datetime.now(tz=dt.timezone.utc)
    bindings = {"incident_id": "inc-1", "symbol": "NFLX", "broker_account": "live", "environment": "production", "source_revision": "abc123"}
    packets = {
        "incident": {**bindings, "schema_version": "tradingagents.incident.v1", "stage": "ready", "history": [{"to_stage": "ready"}], "evidence_refs": ["proof"], "repairer_run_id": "repair-1", "repairer_role_id": "repair", "generated_at": now.isoformat()},
        "focused": {"focused_tests_passed": True, "passing_tests": ["tests/test_x.py::test_ok"], "verifier_run_id": "verify-1", "verifier_role_id": "verify", "source_revision": "abc123", "generated_at": now.isoformat()},
        "promotion": {"promotion_evidence_fresh": True, "issues": [], "generated_at": now.isoformat()},
        "reconciliation": {"read_only": True, "execution_authority": "none", "can_submit_orders": False, "matched": True, "issues": [], "broker_write_calls": 0, "generated_at": now.isoformat()},
    }
    paths = {}
    for name, packet in packets.items():
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps(packet), encoding="utf-8")
        paths[name] = path
    manifest = {**bindings, "schema_version": "tradingagents.recovery_manifest.v1", "kind": "verified_recovery_manifest", "generated_at": now.isoformat(), "packet_sha256": {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in paths.items()}}
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    control_path = tmp_path / "control.json"
    write_live_control_state(control_path, frozen=True, reason="incident", dead_man_expires_at=now + dt.timedelta(days=1))

    result = CliRunner().invoke(
        app,
        [
            "policy",
            "recover-incident",
            "--incident-path",
            str(paths["incident"]),
            "--reconciliation-path",
            str(paths["reconciliation"]),
            "--promotion-sync-path",
            str(paths["promotion"]),
            "--focused-proof-path",
            str(paths["focused"]),
            "--recovery-manifest-path",
            str(manifest_path),
            "--repairer-run-id",
            "repair-1",
            "--verifier-run-id",
            "verify-1",
            "--control-path",
            str(control_path),
            "--receipt-dir",
            str(tmp_path / "rearm"),
            "--json-output",
        ],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["ready"] is True


def test_recovery_manifest_packet_swap_blocks_without_changing_frozen_control(tmp_path):
    control_path = tmp_path / "control.json"
    original = '{"frozen": true, "reason": "incident", "dead_man_expires_at": "2099-01-01T00:00:00+00:00"}'
    control_path.write_text(original, encoding="utf-8")
    packets = {name: tmp_path / f"{name}.json" for name in ("incident", "focused", "promotion", "reconciliation")}
    now = dt.datetime.now(tz=dt.timezone.utc).isoformat()
    packets["incident"].write_text(json.dumps({"stage": "ready", "root_cause_resolved": True, "repairer_role_id": "repair", "generated_at": now}), encoding="utf-8")
    packets["focused"].write_text(json.dumps({"focused_tests_passed": True, "passing_tests": ["x"], "verifier_role_id": "verify", "generated_at": now}), encoding="utf-8")
    packets["promotion"].write_text(json.dumps({"promotion_evidence_fresh": True, "issues": [], "generated_at": now}), encoding="utf-8")
    packets["reconciliation"].write_text(json.dumps({"read_only": True, "execution_authority": "none", "can_submit_orders": False, "matched": True, "issues": [], "broker_write_calls": 0, "generated_at": now}), encoding="utf-8")
    manifest = {"incident_id": "i", "symbol": "NFLX", "broker_account": "live", "environment": "prod", "source_revision": "rev", "packet_sha256": {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in packets.items()}}
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    packets["focused"].write_text('{"swapped": true}', encoding="utf-8")

    result = CliRunner().invoke(
        app,
        [
            "policy",
            "recover-incident",
            "--incident-path",
            str(packets["incident"]),
            "--reconciliation-path",
            str(packets["reconciliation"]),
            "--promotion-sync-path",
            str(packets["promotion"]),
            "--focused-proof-path",
            str(packets["focused"]),
            "--recovery-manifest-path",
            str(manifest_path),
            "--repairer-run-id",
            "r",
            "--verifier-run-id",
            "v",
            "--control-path",
            str(control_path),
            "--json-output",
        ],
    )

    assert result.exit_code == 1
    assert json.loads(result.stdout)["ready"] is False
    assert control_path.read_text(encoding="utf-8") == original


def test_receipt_latest_failure_keeps_frozen_control_byte_identical(monkeypatch, tmp_path):
    control_path = tmp_path / "control.json"
    original = '{"frozen": true, "reason": "incident", "dead_man_expires_at": "2026-07-19T12:00:00+00:00"}'
    control_path.write_text(original, encoding="utf-8")
    monkeypatch.setattr("tradingagents.orchestration.recovery.atomic_write_text", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("latest failed")))

    with pytest.raises(OSError, match="latest failed"):
        rearm_after_verified_recovery(evidence=_evidence(), control_path=control_path, receipt_dir=tmp_path / "rearm", now=NOW)

    assert control_path.read_text(encoding="utf-8") == original


def test_concurrent_receipt_writes_allocate_distinct_immutable_files(tmp_path):
    results, errors = [], []

    def write():
        try:
            results.append(write_rearm_receipt({"kind": "verified_rearm_receipt", "can_submit_orders": False}, tmp_path / "rearm", now=NOW))
        except Exception as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    writers = [threading.Thread(target=write) for _ in range(2)]
    for writer in writers:
        writer.start()
    for writer in writers:
        writer.join()
    assert errors == []
    assert len({result["receipt_path"] for result in results}) == 2


def test_recovery_module_has_no_broker_or_order_imports():
    source = Path(__import__("tradingagents.orchestration.recovery", fromlist=["recovery"]).__file__).read_text(encoding="utf-8")
    assert "tradingagents.brokers" not in source
    assert "submit_order(" not in source


def test_direct_evidence_cannot_bypass_source_packet_proof(tmp_path):
    control_path = tmp_path / "control.json"
    write_live_control_state(control_path, frozen=True, reason="incident", dead_man_expires_at=NOW + dt.timedelta(days=1))

    evidence = _evidence(source_bindings={}, source_packet_paths={}, source_packet_sha256={})
    with pytest.raises(ValueError, match="source"):
        rearm_after_verified_recovery(evidence=evidence, control_path=control_path, receipt_dir=tmp_path / "rearm", now=NOW)


def test_relative_receipt_and_boolean_write_count_close_control(tmp_path):
    control_path = tmp_path / "control.json"
    receipt = tmp_path / "receipt.json"
    receipt.write_text(json.dumps({"schema_version": 1, "kind": "verified_rearm_receipt", "effective_only_when_control_matches_receipt_digest": True, "can_submit_orders": False, "broker_write_calls": False, "issued_at": NOW.isoformat(), "expires_at": (NOW + dt.timedelta(minutes=1)).isoformat()}), encoding="utf-8")
    control_path.write_text(json.dumps({"frozen": False, "reason": "verified recovery inc", "dead_man_expires_at": (NOW + dt.timedelta(minutes=1)).isoformat(), "recovery_receipt_path": "receipt.json", "recovery_receipt_sha256": hashlib.sha256(receipt.read_bytes()).hexdigest()}), encoding="utf-8")

    _state, issues = load_live_control_state(control_path, now=NOW)

    assert any("receipt" in issue for issue in issues)


def test_expired_frozen_control_can_recover_with_current_evidence(tmp_path):
    control_path = tmp_path / "control.json"
    write_live_control_state(control_path, frozen=True, reason="safe expired freeze", dead_man_expires_at=NOW - dt.timedelta(days=1))

    result = rearm_after_verified_recovery(evidence=_evidence(), control_path=control_path, receipt_dir=tmp_path / "rearm", now=NOW)

    assert result["can_submit_orders"] is False


def test_actual_incident_lifecycle_ready_shape_establishes_resolution():
    incident = Incident.open(incident_id="inc-actual", kind="rule", subject="NFLX", owner_role="repair", now=NOW)
    incident = transition_incident(incident, IncidentStage.DIAGNOSING, now=NOW)
    incident = transition_incident(incident, IncidentStage.VERIFYING, now=NOW)
    incident = transition_incident(incident, IncidentStage.READY, now=NOW)
    incident = replace(incident, evidence_refs=("evidence.json",))
    payload = incident.to_dict()

    assert payload["stage"] == "ready"
    assert any(event["to_stage"] == "ready" for event in payload["history"])
    assert payload["subject"] == "NFLX"
