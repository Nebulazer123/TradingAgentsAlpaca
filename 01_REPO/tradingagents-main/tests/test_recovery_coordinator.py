import datetime as dt
import hashlib
import json
import tempfile
import threading
from dataclasses import replace
from pathlib import Path

import pytest
from typer.testing import CliRunner

import cli.main as cli_main
from cli.main import app
from tradingagents.orchestration import recovery as recovery_module
from tradingagents.orchestration.authority import ActionClass
from tradingagents.orchestration.authority import authority_for as real_authority_for
from tradingagents.orchestration.incidents import Incident, IncidentStage, transition_incident
from tradingagents.orchestration.recovery import (
    evaluate_rearm_readiness,
    load_recovery_evidence,
    rearm_after_verified_recovery,
    write_rearm_receipt,
)
from tradingagents.policy.live_control import load_live_control_state, write_live_control_state

NOW = dt.datetime(2026, 7, 18, 12, 0, tzinfo=dt.timezone.utc)


def _control_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _evidence(**overrides):
    source_dir = Path(tempfile.mkdtemp())
    bundle = _write_cli_recovery_bundle(source_dir, now=NOW)
    evidence = _loaded_bundle_evidence(bundle, now=NOW)
    return replace(evidence, **overrides)


def test_clean_independent_evidence_is_ready():
    verdict = evaluate_rearm_readiness(_evidence())

    assert verdict.ready is True
    assert verdict.issues == ()


@pytest.mark.parametrize(
    "overrides",
    [
        {"verifier_run_id": "repair-1"},
        {"verifier_role_id": "reliability_controller"},
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


@pytest.mark.parametrize(
    ("repairer_role_id", "verifier_role_id"),
    [
        ("repair_team", "audit_team"),
        ("reliability_controller", "audit_team"),
        ("repair_team", "integrity_verifier"),
        ("integrity_verifier", "reliability_controller"),
        (" reliability_controller", "integrity_verifier"),
        ("reliability_controller ", "integrity_verifier"),
        ("RELIABILITY_CONTROLLER", "integrity_verifier"),
        ("reliability_controller", " integrity_verifier"),
        ("reliability_controller", "integrity_verifier "),
        ("reliability_controller", "Integrity_Verifier"),
    ],
)
def test_arbitrary_distinct_roles_cannot_request_or_issue_rearm(
    repairer_role_id,
    verifier_role_id,
):
    verdict = evaluate_rearm_readiness(
        _evidence(
            repairer_role_id=repairer_role_id,
            verifier_role_id=verifier_role_id,
        )
    )

    assert verdict.ready is False
    assert any("role" in issue for issue in verdict.issues)


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
        expected_control_preimage_sha256=_control_sha256(control_path),
    )

    state, issues = load_live_control_state(control_path, now=NOW)
    assert issues == []
    assert state["frozen"] is False
    assert state["recovery_receipt_path"] == result["receipt_path"]
    assert state["recovery_receipt_sha256"] == result["receipt_sha256"]
    receipt = json.loads((receipt_dir / Path(result["receipt_path"]).name).read_text())
    assert receipt["schema_version"] == 2
    assert receipt["authority"] == {
        "request_action": "rearm_request",
        "request_owner_role": "reliability_controller",
        "issue_action": "rearm_issue",
        "issue_owner_role": "integrity_verifier",
    }
    assert receipt["can_submit_orders"] is False
    assert receipt["broker_write_calls"] == 0


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("request_action", "repair"),
        ("request_owner_role", "repair_team"),
        ("issue_action", "verify"),
        ("issue_owner_role", "independent_verifier"),
    ],
)
def test_live_control_rejects_noncanonical_rearm_receipt_authority(
    tmp_path,
    field,
    value,
):
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
        expected_control_preimage_sha256=_control_sha256(control_path),
    )
    receipt_path = Path(result["receipt_path"])
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    expected_authority = {
        "request_action": "rearm_request",
        "request_owner_role": "reliability_controller",
        "issue_action": "rearm_issue",
        "issue_owner_role": "integrity_verifier",
    }
    assert receipt.get("authority") == expected_authority
    receipt["authority"][field] = value
    receipt_path.write_text(
        json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    control = json.loads(control_path.read_text(encoding="utf-8"))
    control["recovery_receipt_sha256"] = hashlib.sha256(
        receipt_path.read_bytes()
    ).hexdigest()
    control_path.write_text(json.dumps(control), encoding="utf-8")

    _state, issues = load_live_control_state(control_path, now=NOW)

    assert any("authority" in issue for issue in issues)


@pytest.mark.parametrize(
    ("mutation", "expected_issue"),
    [
        (lambda receipt: receipt.pop("authority"), "authority"),
        (lambda receipt: receipt.update({"authority": []}), "authority"),
        (
            lambda receipt: receipt["authority"].update({"unexpected": "owner"}),
            "authority",
        ),
        (lambda receipt: receipt.update({"schema_version": 1}), "schema"),
    ],
)
def test_live_control_rejects_malformed_or_wrong_schema_authority(
    tmp_path,
    mutation,
    expected_issue,
):
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
        expected_control_preimage_sha256=_control_sha256(control_path),
    )
    receipt_path = Path(result["receipt_path"])
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["schema_version"] == 2
    assert isinstance(receipt["authority"], dict)
    mutation(receipt)
    receipt_path.write_text(
        json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    control = json.loads(control_path.read_text(encoding="utf-8"))
    control["recovery_receipt_sha256"] = hashlib.sha256(
        receipt_path.read_bytes()
    ).hexdigest()
    control_path.write_text(json.dumps(control), encoding="utf-8")

    _state, issues = load_live_control_state(control_path, now=NOW)

    assert any(expected_issue in issue for issue in issues)


def test_legacy_v1_independent_verifier_receipt_stays_fail_closed(tmp_path):
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
        expected_control_preimage_sha256=_control_sha256(control_path),
    )
    receipt_path = Path(result["receipt_path"])
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["schema_version"] = 1
    receipt.pop("authority")
    receipt["verifier_role_id"] = "independent_verifier"
    receipt_path.write_text(
        json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    control = json.loads(control_path.read_text(encoding="utf-8"))
    control["recovery_receipt_sha256"] = hashlib.sha256(
        receipt_path.read_bytes()
    ).hexdigest()
    control_path.write_text(json.dumps(control), encoding="utf-8")
    control_before = control_path.read_bytes()
    receipt_before = receipt_path.read_bytes()

    _state, issues = load_live_control_state(control_path, now=NOW)

    assert any("schema" in issue or "authority" in issue for issue in issues)
    assert control_path.read_bytes() == control_before
    assert receipt_path.read_bytes() == receipt_before


def test_rearm_authority_lookup_denial_preserves_frozen_control(
    monkeypatch,
    tmp_path,
):
    control_path = tmp_path / "live_control.json"
    receipt_dir = tmp_path / "rearm"
    write_live_control_state(
        control_path,
        frozen=True,
        reason="incident",
        dead_man_expires_at=NOW + dt.timedelta(days=1),
    )
    control_before = control_path.read_bytes()
    calls: list[ActionClass] = []

    def deny_issue(action):
        verdict = real_authority_for(action)
        calls.append(verdict.action)
        if verdict.action is ActionClass.REARM_ISSUE:
            return replace(verdict, allowed=False)
        return verdict

    monkeypatch.setattr(recovery_module, "authority_for", deny_issue, raising=False)

    with pytest.raises(ValueError, match="authority"):
        rearm_after_verified_recovery(
            evidence=_evidence(),
            control_path=control_path,
            receipt_dir=receipt_dir,
            now=NOW,
            expected_control_preimage_sha256=_control_sha256(control_path),
        )

    assert calls == [ActionClass.REARM_REQUEST, ActionClass.REARM_ISSUE]
    assert control_path.read_bytes() == control_before
    assert not receipt_dir.exists()


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
            expected_control_preimage_sha256=_control_sha256(control_path),
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
            expected_control_preimage_sha256=_control_sha256(control_path),
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
        expected_control_preimage_sha256=_control_sha256(control_path),
    )
    receipt_path = Path(result["receipt_path"])
    receipt_path.write_text('{"tampered": true}', encoding="utf-8")

    _state, issues = load_live_control_state(control_path, now=NOW)

    assert any("receipt" in issue for issue in issues)


@pytest.mark.parametrize("tamper_mode", ["change", "delete"])
def test_missing_or_changed_promotion_closure_snapshot_closes_control(
    tmp_path,
    tamper_mode,
):
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
        expected_control_preimage_sha256=_control_sha256(control_path),
    )
    receipt = json.loads(Path(result["receipt_path"]).read_text())
    snapshot = Path(
        receipt["promotion_transaction_closure"]["promotion_report"][
            "snapshot_path"
        ]
    )
    if tamper_mode == "change":
        snapshot.write_bytes(snapshot.read_bytes() + b"changed")
    else:
        snapshot.unlink()

    _state, issues = load_live_control_state(control_path, now=NOW)

    assert any("closure" in issue for issue in issues)


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


def _write_cli_recovery_bundle(tmp_path, *, now):
    bindings = {
        "incident_id": "inc-1",
        "symbol": "NFLX",
        "broker_account": "live",
        "environment": "production",
        "source_revision": "abc123",
    }
    packets = {
        "incident": {
            **bindings,
            "schema_version": "tradingagents.incident.v1",
            "stage": "ready",
            "history": [{"to_stage": "ready"}],
            "evidence_refs": ["proof"],
            "repairer_run_id": "repair-1",
            "repairer_role_id": "reliability_controller",
            "generated_at": now.isoformat(),
        },
        "focused": {
            "focused_tests_passed": True,
            "passing_tests": ["tests/test_x.py::test_ok"],
            "verifier_run_id": "verify-1",
            "verifier_role_id": "integrity_verifier",
            "source_revision": "abc123",
            "generated_at": now.isoformat(),
        },
        "reconciliation": {
            "read_only": True,
            "execution_authority": "none",
            "can_submit_orders": False,
            "matched": True,
            "issues": [],
            "broker_write_calls": 0,
            "generated_at": now.isoformat(),
        },
    }
    paths = {}
    for name, packet in packets.items():
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps(packet), encoding="utf-8")
        paths[name] = path

    report_path = tmp_path / "paper_tournament.json"
    candidate = {
        "status": "candidate",
        "strategy_id": "pullback-support",
    }
    report_path.write_text(
        json.dumps({"live_strategy_candidate": candidate}),
        encoding="utf-8",
    )
    envelope_path = tmp_path / "risk_envelope.yaml"
    envelope_path.write_text(
        "tiny_live_tranche_usd: 25\n",
        encoding="utf-8",
    )
    canonical_path = tmp_path / "promotion_state.json"
    canonical_before_sha256 = hashlib.sha256(
        b'{"schema_version":"1.0.0","sleeves":{}}'
    ).hexdigest()
    commit_seed = {
        "schema_version": "tradingagents.promotion_recovery_commit.v1",
        "incident_id": bindings["incident_id"],
        "recovery_run_id": "recovery-1",
        "source_revision": bindings["source_revision"],
        "focused_path": str(paths["focused"].resolve()),
        "focused_sha256": hashlib.sha256(
            paths["focused"].read_bytes()
        ).hexdigest(),
        "verifier_run_id": "verify-1",
        "verifier_role_id": "integrity_verifier",
        "reconciliation_path": str(paths["reconciliation"].resolve()),
        "reconciliation_sha256": hashlib.sha256(
            paths["reconciliation"].read_bytes()
        ).hexdigest(),
        "report_path": str(report_path.resolve()),
        "report_sha256": hashlib.sha256(report_path.read_bytes()).hexdigest(),
        "envelope_path": str(envelope_path.resolve()),
        "envelope_sha256": hashlib.sha256(
            envelope_path.read_bytes()
        ).hexdigest(),
        "canonical_path": str(canonical_path.resolve()),
        "canonical_before_sha256": canonical_before_sha256,
        "candidate_payload_sha256": hashlib.sha256(
            (
                json.dumps(
                    candidate,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=True,
                )
                + "\n"
            ).encode("utf-8")
        ).hexdigest(),
    }
    recovery_commit = {
        **commit_seed,
        "commit_id": hashlib.sha256(
            (
                json.dumps(
                    commit_seed,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=True,
                )
                + "\n"
            ).encode("utf-8")
        ).hexdigest(),
    }
    raw_canonical_state = {
        "schema_version": "1.1.0",
        "generated_at": now.isoformat(),
        "source": {
            "kind": "paper_tournament_sync",
            "canonical_input_sha256": canonical_before_sha256,
            "arm_live": True,
            "ci_green": True,
        },
        "sleeves": {},
    }
    raw_stage_sha256 = hashlib.sha256(
        json.dumps(raw_canonical_state, indent=2).encode("utf-8")
    ).hexdigest()
    canonical_state = json.loads(json.dumps(raw_canonical_state))
    canonical_state["source"]["recovery_commit"] = recovery_commit
    canonical_bytes = json.dumps(
        canonical_state,
        indent=2,
        sort_keys=True,
    ).encode("utf-8")
    staged_path = tmp_path / "staging" / "promotion_state.json"
    staged_path.parent.mkdir()
    staged_path.write_bytes(canonical_bytes)
    canonical_path.write_bytes(canonical_bytes)
    canonical_after_sha256 = hashlib.sha256(canonical_bytes).hexdigest()

    prepare_path = tmp_path / "promotion_prepare.json"
    prepare = {
        "schema_version": "tradingagents.promotion_prepare.v1",
        "kind": "promotion_commit_prepare",
        "recovery_commit": recovery_commit,
        "stage_path": str(staged_path.resolve()),
        "generated_at": now.isoformat(),
        "arm_live": True,
        "ci_green": True,
        "expected_raw_stage_sha256": raw_stage_sha256,
        "expected_stage_sha256": canonical_after_sha256,
        "can_submit_orders": False,
        "execution_authority": "none",
    }
    prepare_path.write_text(json.dumps(prepare), encoding="utf-8")
    prepare_sha256 = hashlib.sha256(prepare_path.read_bytes()).hexdigest()
    commit_path = tmp_path / "promotion_commit.json"
    commit = {
        "schema_version": "tradingagents.promotion_commit.v1",
        "kind": "verified_promotion_commit",
        "recovery_commit": recovery_commit,
        "prepare_path": str(prepare_path.resolve()),
        "prepare_sha256": prepare_sha256,
        "staged_path": str(staged_path.resolve()),
        "staged_sha256": canonical_after_sha256,
        "canonical_path": str(canonical_path.resolve()),
        "canonical_before_sha256": canonical_before_sha256,
        "canonical_after_sha256": canonical_after_sha256,
        "can_submit_orders": False,
        "execution_authority": "none",
    }
    commit_path.write_text(json.dumps(commit), encoding="utf-8")
    packets["promotion"] = {
        "promotion_evidence_fresh": True,
        "issues": [],
        "generated_at": now.isoformat(),
        "recovery_commit": recovery_commit,
        "promotion_prepare": {
            "path": str(prepare_path.resolve()),
            "sha256": prepare_sha256,
        },
        "promotion_commit": {
            "path": str(commit_path.resolve()),
            "sha256": hashlib.sha256(commit_path.read_bytes()).hexdigest(),
        },
        "promotion_stage_request": {
            "commit_id": recovery_commit["commit_id"],
            "prepare_path": str(prepare_path.resolve()),
            "prepare_sha256": prepare_sha256,
            "stage_path": str(staged_path.resolve()),
            "expected_raw_stage_sha256": raw_stage_sha256,
            "expected_stage_sha256": canonical_after_sha256,
            "generated_at": now.isoformat(),
            "canonical_path": str(canonical_path.resolve()),
            "canonical_before_sha256": canonical_before_sha256,
            "report_sha256": recovery_commit["report_sha256"],
            "envelope_sha256": recovery_commit["envelope_sha256"],
            "focused_sha256": recovery_commit["focused_sha256"],
            "reconciliation_sha256": recovery_commit[
                "reconciliation_sha256"
            ],
            "arm_live": True,
            "ci_green": True,
        },
        "staged_state_path": str(staged_path.resolve()),
        "staged_state_sha256": canonical_after_sha256,
        "state_path": str(canonical_path.resolve()),
        "canonical_after_sha256": canonical_after_sha256,
        "state": canonical_state,
    }
    paths["promotion"] = tmp_path / "promotion.json"
    paths["promotion"].write_text(
        json.dumps(packets["promotion"]),
        encoding="utf-8",
    )
    manifest = {
        **bindings,
        "schema_version": "tradingagents.recovery_manifest.v1",
        "kind": "verified_recovery_manifest",
        "generated_at": now.isoformat(),
        "packet_sha256": {
            name: hashlib.sha256(path.read_bytes()).hexdigest()
            for name, path in paths.items()
        },
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    control_path = tmp_path / "control.json"
    write_live_control_state(
        control_path,
        frozen=True,
        reason="incident",
        dead_man_expires_at=now + dt.timedelta(days=1),
    )
    return {
        "paths": paths,
        "manifest_path": manifest_path,
        "control_path": control_path,
        "commit_path": commit_path,
    }


def _loaded_bundle_evidence(bundle, *, now):
    paths = bundle["paths"]
    evidence, issues = load_recovery_evidence(
        incident_path=paths["incident"],
        reconciliation_path=paths["reconciliation"],
        promotion_sync_path=paths["promotion"],
        focused_proof_path=paths["focused"],
        recovery_manifest_path=bundle["manifest_path"],
        repairer_run_id="repair-1",
        verifier_run_id="verify-1",
        now=now,
    )
    assert issues == ()
    assert evidence is not None
    return evidence


@pytest.mark.parametrize(
    "role_id",
    [
        " reliability_controller",
        "reliability_controller ",
        "RELIABILITY_CONTROLLER",
    ],
)
def test_evidence_loader_rejects_nonexact_repairer_role_strings(
    tmp_path,
    role_id,
):
    bundle = _write_cli_recovery_bundle(tmp_path, now=NOW)
    incident_path = bundle["paths"]["incident"]
    incident = json.loads(incident_path.read_text(encoding="utf-8"))
    incident["repairer_role_id"] = role_id
    incident_path.write_text(json.dumps(incident), encoding="utf-8")
    manifest_path = bundle["manifest_path"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["packet_sha256"]["incident"] = hashlib.sha256(
        incident_path.read_bytes()
    ).hexdigest()
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    evidence, issues = load_recovery_evidence(
        incident_path=incident_path,
        reconciliation_path=bundle["paths"]["reconciliation"],
        promotion_sync_path=bundle["paths"]["promotion"],
        focused_proof_path=bundle["paths"]["focused"],
        recovery_manifest_path=manifest_path,
        repairer_run_id="repair-1",
        verifier_run_id="verify-1",
        now=NOW,
    )

    assert evidence is None
    assert any("repairer_role_id" in issue for issue in issues)


@pytest.mark.parametrize("explicit_role", [None, ""])
def test_evidence_loader_requires_explicit_repairer_role_without_owner_fallback(
    tmp_path,
    explicit_role,
):
    bundle = _write_cli_recovery_bundle(tmp_path, now=NOW)
    incident_path = bundle["paths"]["incident"]
    incident = json.loads(incident_path.read_text(encoding="utf-8"))
    incident["owner_role"] = "reliability_controller"
    if explicit_role is None:
        incident.pop("repairer_role_id")
    else:
        incident["repairer_role_id"] = explicit_role
    incident_path.write_text(json.dumps(incident), encoding="utf-8")
    manifest_path = bundle["manifest_path"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["packet_sha256"]["incident"] = hashlib.sha256(
        incident_path.read_bytes()
    ).hexdigest()
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    evidence, issues = load_recovery_evidence(
        incident_path=incident_path,
        reconciliation_path=bundle["paths"]["reconciliation"],
        promotion_sync_path=bundle["paths"]["promotion"],
        focused_proof_path=bundle["paths"]["focused"],
        recovery_manifest_path=manifest_path,
        repairer_run_id="repair-1",
        verifier_run_id="verify-1",
        now=NOW,
    )

    assert evidence is None
    assert any("repairer_role_id" in issue for issue in issues)


def _invoke_cli_recovery(bundle, tmp_path):
    paths = bundle["paths"]
    return CliRunner().invoke(
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
            str(bundle["manifest_path"]),
            "--repairer-run-id",
            "repair-1",
            "--verifier-run-id",
            "verify-1",
            "--control-path",
            str(bundle["control_path"]),
            "--receipt-dir",
            str(tmp_path / "rearm"),
            "--json-output",
        ],
    )


@pytest.mark.parametrize(
    "promotion_payload",
    [
        "{}",
        "{not-json",
        json.dumps(
            {
                "promotion_evidence_fresh": True,
                "issues": [],
                "generated_at": NOW.isoformat(),
            }
        ),
    ],
    ids=["empty-object", "unparseable", "missing-state-reference"],
)
def test_direct_rearm_requires_full_promotion_transaction_revalidation(
    tmp_path,
    promotion_payload,
):
    evidence = _evidence()
    promotion_path = Path(evidence.source_packet_paths["promotion"])
    promotion_path.write_text(promotion_payload, encoding="utf-8")
    source_hashes = dict(evidence.source_packet_sha256)
    source_hashes["promotion"] = hashlib.sha256(
        promotion_path.read_bytes()
    ).hexdigest()
    evidence = replace(evidence, source_packet_sha256=source_hashes)
    control_path = tmp_path / "control.json"
    write_live_control_state(
        control_path,
        frozen=True,
        reason="incident",
        dead_man_expires_at=NOW + dt.timedelta(days=1),
        now=NOW,
    )
    original = control_path.read_bytes()

    with pytest.raises(ValueError, match="promotion"):
        rearm_after_verified_recovery(
            evidence=evidence,
            control_path=control_path,
            receipt_dir=tmp_path / "rearm",
            now=NOW,
            expected_control_preimage_sha256=hashlib.sha256(
                original
            ).hexdigest(),
        )

    assert control_path.read_bytes() == original
    assert not list((tmp_path / "rearm").glob("verified-rearm-*.json"))
    assert not (tmp_path / "rearm" / "latest.json").exists()


def test_direct_rearm_requires_explicit_frozen_control_preimage(tmp_path):
    now = dt.datetime.now(tz=dt.timezone.utc)
    bundle = _write_cli_recovery_bundle(tmp_path, now=now)
    evidence = _loaded_bundle_evidence(bundle, now=now)
    original = bundle["control_path"].read_bytes()

    with pytest.raises(ValueError, match="preimage"):
        rearm_after_verified_recovery(
            evidence=evidence,
            control_path=bundle["control_path"],
            receipt_dir=tmp_path / "rearm",
            now=now,
            expected_control_preimage_sha256=None,
        )

    assert bundle["control_path"].read_bytes() == original
    assert not (tmp_path / "rearm" / "latest.json").exists()


def test_recovery_cli_binds_control_preimage_before_evidence_parse(
    tmp_path,
    monkeypatch,
):
    now = dt.datetime.now(tz=dt.timezone.utc)
    bundle = _write_cli_recovery_bundle(tmp_path, now=now)
    control_path = bundle["control_path"]
    original_loader = cli_main.load_recovery_evidence

    def load_then_install_newer_freeze(*args, **kwargs):
        loaded = original_loader(*args, **kwargs)
        write_live_control_state(
            control_path,
            frozen=True,
            reason="newer independent safety freeze",
            dead_man_expires_at=now + dt.timedelta(days=1),
            now=now,
        )
        return loaded

    monkeypatch.setattr(
        cli_main,
        "load_recovery_evidence",
        load_then_install_newer_freeze,
    )

    result = _invoke_cli_recovery(bundle, tmp_path)

    assert result.exit_code == 1, result.output
    control, _issues = load_live_control_state(control_path, now=now)
    assert control["frozen"] is True
    assert control["reason"] == "newer independent safety freeze"
    assert "recovery_receipt_path" not in control
    assert not (tmp_path / "rearm" / "latest.json").exists()


@pytest.mark.parametrize("nested_input", ["report", "envelope"])
def test_rearm_snapshots_full_nested_promotion_closure_before_opening_control(
    tmp_path,
    monkeypatch,
    nested_input,
):
    now = dt.datetime.now(tz=dt.timezone.utc)
    bundle = _write_cli_recovery_bundle(tmp_path, now=now)
    evidence = _loaded_bundle_evidence(bundle, now=now)
    promotion = json.loads(
        bundle["paths"]["promotion"].read_text(encoding="utf-8")
    )
    recovery_commit = promotion["recovery_commit"]
    nested_path = Path(recovery_commit[f"{nested_input}_path"])
    original_loader = recovery_module.load_recovery_evidence

    def load_then_mutate_nested_input(*args, **kwargs):
        loaded = original_loader(*args, **kwargs)
        nested_path.write_bytes(nested_path.read_bytes() + b"\nchanged")
        return loaded

    monkeypatch.setattr(
        recovery_module,
        "load_recovery_evidence",
        load_then_mutate_nested_input,
    )
    original_control = bundle["control_path"].read_bytes()

    with pytest.raises(ValueError, match="promotion|closure|input"):
        rearm_after_verified_recovery(
            evidence=evidence,
            control_path=bundle["control_path"],
            receipt_dir=tmp_path / "rearm",
            now=now,
            expected_control_preimage_sha256=hashlib.sha256(
                original_control
            ).hexdigest(),
        )

    assert bundle["control_path"].read_bytes() == original_control
    assert not (tmp_path / "rearm" / "latest.json").exists()


def test_post_replace_control_fsync_error_adopts_exact_open_control(
    tmp_path,
    monkeypatch,
):
    now = dt.datetime.now(tz=dt.timezone.utc)
    bundle = _write_cli_recovery_bundle(tmp_path, now=now)
    evidence = _loaded_bundle_evidence(bundle, now=now)
    original_writer = recovery_module._write_live_control_state_locked

    def write_then_raise(*args, **kwargs):
        original_writer(*args, **kwargs)
        raise OSError("injected parent-directory fsync failure")

    monkeypatch.setattr(
        recovery_module,
        "_write_live_control_state_locked",
        write_then_raise,
    )

    result = rearm_after_verified_recovery(
        evidence=evidence,
        control_path=bundle["control_path"],
        receipt_dir=tmp_path / "rearm",
        now=now,
        expected_control_preimage_sha256=_control_sha256(
            bundle["control_path"]
        ),
    )

    control, issues = load_live_control_state(
        bundle["control_path"],
        now=now,
    )
    assert issues == []
    assert control["frozen"] is False
    assert control["recovery_receipt_path"] == result["receipt_path"]
    assert (tmp_path / "rearm" / "latest.json").exists()


def test_recovery_cli_rearms_from_hash_bound_manifest_packets(tmp_path):
    now = dt.datetime.now(tz=dt.timezone.utc)
    bundle = _write_cli_recovery_bundle(tmp_path, now=now)

    result = _invoke_cli_recovery(bundle, tmp_path)

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["ready"] is True


def test_recovery_cli_task5_cas_preserves_newer_safety_freeze(
    tmp_path,
    monkeypatch,
):
    now = dt.datetime.now(tz=dt.timezone.utc)
    bundle = _write_cli_recovery_bundle(tmp_path, now=now)
    control_path = bundle["control_path"]
    original_write_receipt = recovery_module.write_rearm_receipt

    def receipt_then_newer_freeze(*args, **kwargs):
        receipt_ref = original_write_receipt(*args, **kwargs)
        control_path.write_text(
            json.dumps(
                {
                    "frozen": True,
                    "reason": "newer independent safety freeze",
                    "dead_man_expires_at": (
                        now + dt.timedelta(days=1)
                    ).isoformat(timespec="seconds"),
                    "updated_at": now.isoformat(timespec="seconds"),
                }
            ),
            encoding="utf-8",
        )
        return receipt_ref

    monkeypatch.setattr(
        recovery_module,
        "write_rearm_receipt",
        receipt_then_newer_freeze,
    )
    result = _invoke_cli_recovery(bundle, tmp_path)

    assert result.exit_code == 1
    control, _issues = load_live_control_state(control_path, now=now)
    assert control["frozen"] is True
    assert control["reason"] == "newer independent safety freeze"
    assert "recovery_receipt_path" not in control
    assert not (tmp_path / "rearm" / "latest.json").exists()


def test_recovery_cli_rejects_coherently_rehashed_thin_promotion_receipt(
    tmp_path,
):
    now = dt.datetime.now(tz=dt.timezone.utc)
    bundle = _write_cli_recovery_bundle(tmp_path, now=now)
    commit_path = bundle["commit_path"]
    commit = json.loads(commit_path.read_text(encoding="utf-8"))
    commit.pop("staged_sha256")
    commit_path.write_text(json.dumps(commit), encoding="utf-8")
    promotion_path = bundle["paths"]["promotion"]
    promotion = json.loads(promotion_path.read_text(encoding="utf-8"))
    promotion["promotion_commit"]["sha256"] = hashlib.sha256(
        commit_path.read_bytes()
    ).hexdigest()
    promotion_path.write_text(json.dumps(promotion), encoding="utf-8")
    manifest = json.loads(
        bundle["manifest_path"].read_text(encoding="utf-8")
    )
    manifest["packet_sha256"]["promotion"] = hashlib.sha256(
        promotion_path.read_bytes()
    ).hexdigest()
    bundle["manifest_path"].write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )

    result = _invoke_cli_recovery(bundle, tmp_path)

    assert result.exit_code == 1
    assert json.loads(result.stdout)["ready"] is False


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
        rearm_after_verified_recovery(
            evidence=_evidence(),
            control_path=control_path,
            receipt_dir=tmp_path / "rearm",
            now=NOW,
            expected_control_preimage_sha256=_control_sha256(control_path),
        )

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
        rearm_after_verified_recovery(
            evidence=evidence,
            control_path=control_path,
            receipt_dir=tmp_path / "rearm",
            now=NOW,
            expected_control_preimage_sha256=_control_sha256(control_path),
        )


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

    result = rearm_after_verified_recovery(
        evidence=_evidence(),
        control_path=control_path,
        receipt_dir=tmp_path / "rearm",
        now=NOW,
        expected_control_preimage_sha256=_control_sha256(control_path),
    )

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


@pytest.mark.parametrize(
    "overrides",
    [
        {"recovery_manifest_path": None},
        {"source_bindings": {"incident_id": "", "symbol": "NFLX", "broker_account": "live", "environment": "test", "source_revision": "abc"}},
        {"source_packet_sha256": {"incident": "bad", "reconciliation": "bad", "promotion": "bad", "focused": "bad"}},
        {"source_packet_paths": {"incident": "relative", "reconciliation": "relative", "promotion": "relative", "focused": "relative"}},
    ],
)
def test_evidence_requires_manifest_and_complete_canonical_source_proof(overrides):
    assert evaluate_rearm_readiness(_evidence(**overrides)).ready is False


def test_hostile_mapping_evaluation_returns_blocked_verdict():
    class HostileMapping(dict):
        def __iter__(self):
            raise RuntimeError("hostile")

    verdict = evaluate_rearm_readiness(_evidence(source_bindings=HostileMapping()))
    assert verdict.ready is False


def test_explicit_root_cause_true_cannot_bypass_canonical_lifecycle(tmp_path):
    from tradingagents.orchestration.recovery import load_recovery_evidence

    now = dt.datetime.now(tz=dt.timezone.utc)
    files = {name: tmp_path / f"{name}.json" for name in ("incident", "reconciliation", "promotion", "focused")}
    files["incident"].write_text(json.dumps({"schema_version": "tradingagents.incident.v1", "stage": "ready", "root_cause_resolved": True, "repairer_run_id": "r", "repairer_role_id": "repair", "generated_at": now.isoformat()}))
    files["focused"].write_text(json.dumps({"focused_tests_passed": True, "passing_tests": ["x"], "verifier_run_id": "v", "verifier_role_id": "verify", "source_revision": "rev", "generated_at": now.isoformat()}))
    files["promotion"].write_text(json.dumps({"promotion_evidence_fresh": True, "issues": [], "generated_at": now.isoformat()}))
    files["reconciliation"].write_text(json.dumps({"read_only": True, "execution_authority": "none", "can_submit_orders": False, "matched": True, "issues": [], "broker_write_calls": 0, "generated_at": now.isoformat()}))
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "tradingagents.recovery_manifest.v1",
                "kind": "verified_recovery_manifest",
                "generated_at": now.isoformat(),
                "incident_id": "i",
                "symbol": "NFLX",
                "broker_account": "live",
                "environment": "prod",
                "source_revision": "rev",
                "packet_sha256": {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in files.items()},
            }
        )
    )
    evidence, issues = load_recovery_evidence(incident_path=files["incident"], reconciliation_path=files["reconciliation"], promotion_sync_path=files["promotion"], focused_proof_path=files["focused"], recovery_manifest_path=manifest, repairer_run_id="r", verifier_run_id="v")
    assert evidence is None
    assert any("lifecycle" in issue for issue in issues)


def test_rearm_rejects_control_receipt_latest_collision_without_mutating_frozen_file(tmp_path):
    control_path = tmp_path / "rearm" / "latest.json"
    control_path.parent.mkdir()
    original = '{"frozen": true, "reason": "incident", "dead_man_expires_at": "2026-07-19T12:00:00+00:00"}'
    control_path.write_text(original)
    with pytest.raises(ValueError, match="collides"):
        rearm_after_verified_recovery(
            evidence=_evidence(),
            control_path=control_path,
            receipt_dir=control_path.parent,
            now=NOW,
            expected_control_preimage_sha256=_control_sha256(control_path),
        )
    assert control_path.read_text() == original


@pytest.mark.parametrize(
    "state",
    [
        {"frozen": False, "recovery_mode": "verified_recovery"},
        {"frozen": "false", "reason": "legacy", "dead_man_expires_at": "2026-07-19T12:00:00+00:00"},
        {"frozen": True, "recovery_mode": "verified_recovery", "recovery_incident_id": "i", "recovery_receipt_path": "/tmp/nope", "recovery_receipt_sha256": "a" * 64},
    ],
)
def test_partial_or_unsafe_recovery_markers_close_active_control(tmp_path, state):
    state.setdefault("reason", "verified recovery i")
    state.setdefault("dead_man_expires_at", "2026-07-19T12:00:00+00:00")
    control_path = tmp_path / "control.json"
    control_path.write_text(json.dumps(state))
    _state, issues = load_live_control_state(control_path, now=NOW)
    assert issues


def test_receipt_ttl_and_future_issued_time_close_control(tmp_path):
    receipt = tmp_path / "receipt.json"
    control = tmp_path / "control.json"
    receipt.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "kind": "verified_rearm_receipt",
                "effective_only_when_control_matches_receipt_digest": True,
                "can_submit_orders": False,
                "broker_write_calls": 0,
                "source_bindings": {"incident_id": "i", "symbol": "NFLX", "broker_account": "live", "environment": "prod", "source_revision": "r"},
                "source_packet_sha256": {key: "a" * 64 for key in ("incident", "reconciliation", "promotion", "focused")},
                "source_packet_paths": {key: str((tmp_path / f"{key}.json").resolve()) for key in ("incident", "reconciliation", "promotion", "focused")},
                "issued_at": (NOW + dt.timedelta(minutes=1)).isoformat(),
                "expires_at": (NOW + dt.timedelta(minutes=92)).isoformat(),
                "ttl_minutes": 91,
                "control_binding": {"control_path": str(control.resolve()), "incident_id": "i", "reason": "verified recovery i", "dead_man_expires_at": (NOW + dt.timedelta(minutes=92)).isoformat(timespec="seconds"), "frozen": False, "mode": "verified_recovery", "receipt_path": str(receipt.resolve())},
            }
        )
    )
    control.write_text(
        json.dumps(
            {
                "frozen": False,
                "reason": "verified recovery i",
                "dead_man_expires_at": (NOW + dt.timedelta(minutes=92)).isoformat(timespec="seconds"),
                "recovery_mode": "verified_recovery",
                "recovery_incident_id": "i",
                "recovery_receipt_path": str(receipt.resolve()),
                "recovery_receipt_sha256": hashlib.sha256(receipt.read_bytes()).hexdigest(),
            }
        )
    )
    _state, issues = load_live_control_state(control, now=NOW)
    assert issues


def test_hostile_mapping_get_and_noncanonical_source_path_fail_closed():
    class HostileGet(dict):
        def get(self, _key, _default=None):
            raise RuntimeError("hostile get")

    hostile = _evidence(source_packet_sha256=HostileGet())
    assert evaluate_rearm_readiness(hostile).ready is False
    evidence = _evidence()
    paths = dict(evidence.source_packet_paths)
    paths["incident"] = str(Path(paths["incident"]).parent / ".." / Path(paths["incident"]).parent.name / "incident.json")
    assert evaluate_rearm_readiness(_evidence(source_packet_paths=paths)).ready is False


def test_source_binding_incident_mismatch_and_verified_reason_without_markers_close(tmp_path):
    bindings = {"incident_id": "other", "symbol": "NFLX", "broker_account": "live", "environment": "test", "source_revision": "abc"}
    assert evaluate_rearm_readiness(_evidence(source_bindings=bindings)).ready is False
    control = tmp_path / "control.json"
    control.write_text(json.dumps({"frozen": False, "reason": "verified recovery inc", "dead_man_expires_at": "2026-07-19T12:00:00+00:00"}))
    _state, issues = load_live_control_state(control, now=NOW)
    assert any("markers" in issue for issue in issues)
