import datetime as dt
import hashlib
import json
from decimal import Decimal
from pathlib import Path

import pytest

from tests.test_self_heal_recovery import (
    NOW,
    _control,
    _production_recovery_harness,
)
from tradingagents.orchestration.recovery import rearm_after_verified_recovery
from tradingagents.orchestration.self_heal import (
    RECOVERY_FOCUSED_TESTS,
    coordinate_verified_recovery,
)
from tradingagents.policy.live_control import load_live_control_state
from tradingagents.policy.live_gate import evaluate_go_live_guard

REPO_ROOT = Path(__file__).resolve().parents[2]
PRODUCTION_AUTHORITY_PATHS = (
    REPO_ROOT / "results" / "policy" / "live_control.json",
    REPO_ROOT / "results" / "policy" / ".live_control.json.control.lock",
    REPO_ROOT / "results" / "policy" / "promotion_state.json",
    REPO_ROOT / ".env",
    REPO_ROOT / ".env.enterprise",
    REPO_ROOT / "config" / "research_integrations.json",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _snapshot_production_authority() -> dict[str, str | None]:
    paths = list(PRODUCTION_AUTHORITY_PATHS)
    credential_root = REPO_ROOT / "n8n" / "credentials"
    if credential_root.is_dir():
        paths.extend(path for path in credential_root.rglob("*") if path.is_file())
    return {
        str(path.relative_to(REPO_ROOT)): _sha256(path) if path.is_file() else None
        for path in sorted(set(paths))
    }


def _coordinator_args(request: dict) -> dict:
    args = dict(request)
    assert args.pop("ready") is True
    return args


def _live_buy_guard(*, root: Path, state_path: Path):
    return evaluate_go_live_guard(
        [
            {
                "action": "buy",
                "symbol": "NFLX",
                "notional": Decimal("20"),
                "limit_price": Decimal("100"),
                "side": "buy",
                "order_type": "limit",
                "account": "live",
                "execution_mode": "tiny_live",
                "asset_class": "stock",
                "sleeve": "pullback-support",
            }
        ],
        risk_envelope_path=root / "config" / "risk_envelope.yaml",
        promotion_state_path=state_path,
        control_state_path=root / "live_control.json",
        live_buying_power=Decimal("1000"),
        now=NOW,
    )


def test_clean_nflx_recovery_closes_the_exact_task6_task5_chain(tmp_path):
    production_before = _snapshot_production_authority()
    request, canonical_path, invocations, broker = _production_recovery_harness(
        tmp_path
    )
    args = _coordinator_args(request)
    control_path = _control(tmp_path)
    initial_promotion = json.loads(canonical_path.read_text(encoding="utf-8"))
    initial_promotion["sleeves"]["pullback-support"].update(
        {"stage": "paper_only", "live_enabled": False}
    )
    canonical_path.write_text(
        json.dumps(initial_promotion, indent=2),
        encoding="utf-8",
    )
    canonical_before_sha256 = _sha256(canonical_path)
    assert (
        json.loads(canonical_path.read_text(encoding="utf-8"))["sleeves"][
            "pullback-support"
        ]["live_enabled"]
        is False
    )
    receipt_dir = tmp_path / "receipts"
    recovery_root = tmp_path / "results" / "control_plane" / "recovery"
    run_root = (
        recovery_root / request["incident_id"] / request["recovery_run_id"]
    )
    immutable_inputs = {
        path: _sha256(path)
        for path in (
            tmp_path / "results" / "hourly_supervisor" / "supervisor.json",
            tmp_path / "results" / "hourly_supervisor" / "advisory.json",
            tmp_path / "results" / "paper_strategy_tournament" / "latest.json",
            tmp_path / "config" / "risk_envelope.yaml",
            tmp_path / "results" / "alpaca_reconciliation" / "latest.json",
        )
    }

    pre_promotion_observations = []

    def stop_before_receipt(boundary):
        if boundary["boundary"] == "before_promotion_adapter":
            pre_promotion = json.loads(
                canonical_path.read_text(encoding="utf-8")
            )
            pre_promotion_observations.append(
                {
                    "live_enabled": pre_promotion["sleeves"][
                        "pullback-support"
                    ]["live_enabled"],
                    "focused_exists": (
                        run_root / "packets" / "focused_verify.json"
                    ).is_file(),
                }
            )
        if (
            boundary["boundary"] == "after_phase_fsync"
            and boundary["phase"] == "manifest"
        ):
            raise SystemExit("inspect frozen live gate before Task 5")

    with pytest.raises(
        SystemExit, match="inspect frozen live gate before Task 5"
    ):
        coordinate_verified_recovery(
            **args,
            control_path=control_path,
            receipt_dir=receipt_dir,
            recovery_root=recovery_root,
            now=NOW,
            fault_hook=stop_before_receipt,
        )

    reconcile_invocations = [
        command for command in invocations if "reconcile-symbol-incident" in command
    ]
    focused_invocations = [command for command in invocations if "pytest" in command]
    promotion_invocations = [
        command for command in invocations if "sync-promotion" in command
    ]
    assert len(reconcile_invocations) == 1
    assert len(focused_invocations) == 1
    assert len(promotion_invocations) == 1
    assert set(RECOVERY_FOCUSED_TESTS).issubset(focused_invocations[0])
    assert invocations.index(reconcile_invocations[0]) < invocations.index(
        focused_invocations[0]
    ) < invocations.index(promotion_invocations[0])
    assert "--arm-live" in promotion_invocations[0]
    assert "--ci-green" in promotion_invocations[0]
    assert pre_promotion_observations == [
        {"live_enabled": False, "focused_exists": True}
    ]

    promoted = json.loads(canonical_path.read_text(encoding="utf-8"))
    assert promoted["sleeves"]["pullback-support"]["live_enabled"] is True
    frozen, frozen_issues = load_live_control_state(control_path, now=NOW)
    assert frozen_issues
    assert frozen["frozen"] is True
    assert list(receipt_dir.glob("verified-rearm-*.json")) == []
    blocked_guard = _live_buy_guard(root=tmp_path, state_path=canonical_path)
    assert blocked_guard.allowed is False
    assert blocked_guard.checks["live_not_frozen"] is False
    immutable_phase_packets = {
        path: _sha256(path)
        for path in (
            run_root / "packets" / "reconcile.json",
            run_root / "packets" / "focused_verify.json",
            run_root / "packets" / "promotion_prepare.json",
            run_root / "packets" / "promotion_commit.json",
            run_root / "packets" / "sync_promotion.json",
            run_root / "packets" / "ready_incident.json",
            run_root / "packets" / "manifest.json",
        )
    }

    task5_evidence = []

    def observed_task5(**kwargs):
        task5_evidence.append(kwargs["evidence"])
        return rearm_after_verified_recovery(**kwargs)

    resumed = coordinate_verified_recovery(
        **args,
        control_path=control_path,
        receipt_dir=receipt_dir,
        recovery_root=recovery_root,
        now=NOW,
        rearm=observed_task5,
    )

    assert resumed["status"] == "monitoring"
    assert len(task5_evidence) == 1
    evidence = task5_evidence[0]
    assert evidence.repairer_run_id != evidence.verifier_run_id
    assert evidence.repairer_role_id != evidence.verifier_role_id
    assert len(
        [
            command
            for command in invocations
            if "reconcile-symbol-incident" in command
        ]
    ) == 1
    assert broker.write_calls == []
    assert broker.read_calls
    assert (
        {path: _sha256(path) for path in immutable_phase_packets}
        == immutable_phase_packets
    )

    packets = run_root / "packets"
    incident_path = packets / "ready_incident.json"
    reconciliation_path = packets / "reconcile.json"
    focused_path = packets / "focused_verify.json"
    promotion_path = packets / "sync_promotion.json"
    manifest_path = packets / "manifest.json"
    prepare_path = packets / "promotion_prepare.json"
    commit_path = packets / "promotion_commit.json"
    promotion = json.loads(promotion_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    prepare = json.loads(prepare_path.read_text(encoding="utf-8"))
    commit = json.loads(commit_path.read_text(encoding="utf-8"))
    ready_incident = json.loads(incident_path.read_text(encoding="utf-8"))
    focused = json.loads(focused_path.read_text(encoding="utf-8"))
    reconciliation = json.loads(reconciliation_path.read_text(encoding="utf-8"))
    stage_path = Path(promotion["staged_state_path"])
    recovery_commit = promotion["recovery_commit"]

    assert ready_incident["schema_version"] == "tradingagents.incident.v1"
    assert ready_incident["stage"] == "ready"
    assert ready_incident["root_cause_resolved"] is True
    assert ready_incident["external_blockers"] == []
    assert any(
        event.get("to_stage") == "ready"
        for event in ready_incident["history"]
    )
    assert ready_incident["evidence_refs"] == [
        str(packets / f"{phase}.json")
        for phase in (
            "resolve_authority",
            "regenerate_evidence",
            "reconcile",
            "focused_verify",
            "sync_promotion",
        )
    ]
    expected_sources = {
        "incident": incident_path,
        "reconciliation": reconciliation_path,
        "promotion": promotion_path,
        "focused": focused_path,
    }
    assert manifest["packet_paths"] == {
        name: str(path.resolve()) for name, path in expected_sources.items()
    }
    assert manifest["packet_sha256"] == {
        name: _sha256(path) for name, path in expected_sources.items()
    }
    assert evidence.source_packet_paths == manifest["packet_paths"]
    assert evidence.source_packet_sha256 == manifest["packet_sha256"]
    assert evidence.recovery_manifest_path == str(manifest_path.resolve())
    assert evidence.recovery_manifest_sha256 == _sha256(manifest_path)
    assert focused["passing_tests"] == list(RECOVERY_FOCUSED_TESTS)
    assert reconciliation["matched"] is True
    assert reconciliation["read_only"] is True
    assert reconciliation["broker_write_calls"] == 0

    stage_sha256 = _sha256(stage_path)
    canonical_sha256 = _sha256(canonical_path)
    prepare_sha256 = _sha256(prepare_path)
    commit_sha256 = _sha256(commit_path)
    assert promotion["promotion_prepare"] == {
        "path": str(prepare_path.resolve()),
        "sha256": prepare_sha256,
    }
    assert promotion["promotion_commit"] == {
        "path": str(commit_path.resolve()),
        "sha256": commit_sha256,
    }
    assert prepare["recovery_commit"] == recovery_commit
    assert commit["recovery_commit"] == recovery_commit
    assert prepare["expected_stage_sha256"] == stage_sha256
    assert commit["staged_sha256"] == stage_sha256
    assert promotion["staged_state_sha256"] == stage_sha256
    assert promotion["canonical_after_sha256"] == canonical_sha256 == stage_sha256
    assert commit["canonical_after_sha256"] == canonical_sha256
    assert commit["canonical_before_sha256"] == recovery_commit[
        "canonical_before_sha256"
    ]
    assert recovery_commit["canonical_before_sha256"] == canonical_before_sha256
    assert recovery_commit["focused_sha256"] == _sha256(focused_path)
    assert recovery_commit["reconciliation_sha256"] == _sha256(
        reconciliation_path
    )
    assert recovery_commit["report_sha256"] == _sha256(
        tmp_path / "results" / "paper_strategy_tournament" / "latest.json"
    )
    assert recovery_commit["envelope_sha256"] == _sha256(
        tmp_path / "config" / "risk_envelope.yaml"
    )

    control, control_issues = load_live_control_state(control_path, now=NOW)
    assert control_issues == []
    assert control["frozen"] is False
    issued_at = dt.datetime.fromisoformat(
        json.loads(
            Path(control["recovery_receipt_path"]).read_text(encoding="utf-8")
        )["issued_at"]
    )
    expires_at = dt.datetime.fromisoformat(control["dead_man_expires_at"])
    assert dt.timedelta(0) < expires_at - issued_at <= dt.timedelta(minutes=90)
    receipt_path = Path(control["recovery_receipt_path"])
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert control["recovery_receipt_sha256"] == _sha256(receipt_path)
    assert control["dead_man_expires_at"] == receipt["expires_at"]
    assert control["recovery_incident_id"] == request["incident_id"]
    assert receipt["broker_write_calls"] == 0
    assert receipt["ttl_minutes"] <= 90
    expected_closure = {
        "incident": incident_path,
        "reconciliation": reconciliation_path,
        "promotion": promotion_path,
        "focused": focused_path,
        "manifest": manifest_path,
        "promotion_report": Path(recovery_commit["report_path"]),
        "promotion_envelope": Path(recovery_commit["envelope_path"]),
        "promotion_prepare": prepare_path,
        "promotion_stage": stage_path,
        "promotion_commit": commit_path,
        "promotion_canonical": canonical_path,
    }
    assert set(receipt["promotion_transaction_closure"]) == set(expected_closure)
    for name, source_path in expected_closure.items():
        closure = receipt["promotion_transaction_closure"][name]
        assert closure["source_path"] == str(source_path.resolve())
        assert closure["sha256"] == _sha256(source_path)
        assert _sha256(Path(closure["snapshot_path"])) == closure["sha256"]

    incident = json.loads(
        (
            tmp_path
            / "results"
            / "control_plane"
            / "incidents"
            / request["incident_id"]
            / "latest.json"
        ).read_text(encoding="utf-8")
    )
    assert incident["subject"] == "NFLX"
    assert incident["owner_role"] == "reliability_controller"
    assert incident["stage"] == "monitoring"
    assert any(
        event.get("to_stage") == "monitoring" for event in incident["history"]
    )

    receipt_before_duplicate = receipt_path.read_bytes()
    control_before_duplicate = control_path.read_bytes()
    duplicate = coordinate_verified_recovery(
        **args,
        control_path=control_path,
        receipt_dir=receipt_dir,
        recovery_root=recovery_root,
        now=NOW,
        rearm=observed_task5,
    )
    assert duplicate["status"] == "duplicate"
    assert len(task5_evidence) == 1
    assert receipt_path.read_bytes() == receipt_before_duplicate
    assert control_path.read_bytes() == control_before_duplicate
    assert len(list(receipt_dir.glob("verified-rearm-*.json"))) == 1
    assert len(
        [
            command
            for command in invocations
            if "reconcile-symbol-incident" in command
        ]
    ) == 1
    assert {path: _sha256(path) for path in immutable_inputs} == immutable_inputs
    assert _snapshot_production_authority() == production_before


def test_mismatched_broker_evidence_keeps_nflx_owned_and_frozen(tmp_path):
    production_before = _snapshot_production_authority()
    request, canonical_path, invocations, broker = _production_recovery_harness(
        tmp_path
    )
    args = _coordinator_args(request)
    canonical_before = canonical_path.read_bytes()
    broker.positions[0]["qty"] = "0"
    control_path = _control(tmp_path)
    recovery_root = tmp_path / "results" / "control_plane" / "recovery"

    result = coordinate_verified_recovery(
        **args,
        control_path=control_path,
        receipt_dir=tmp_path / "receipts",
        recovery_root=recovery_root,
        now=NOW,
    )

    assert result["status"] == "frozen"
    assert result["phase"] == "reconcile"
    assert canonical_path.read_bytes() == canonical_before
    assert not any("sync-promotion" in command for command in invocations)
    assert broker.write_calls == []
    assert broker.read_calls
    assert list((recovery_root / request["incident_id"]).rglob(
        "promotion_prepare.json"
    )) == []
    assert list((recovery_root / request["incident_id"]).rglob(
        "promotion_commit.json"
    )) == []
    assert list((tmp_path / "receipts").glob("verified-rearm-*.json")) == []
    control, _issues = load_live_control_state(control_path, now=NOW)
    assert control["frozen"] is True
    incident = json.loads(
        (
            tmp_path
            / "results"
            / "control_plane"
            / "incidents"
            / request["incident_id"]
            / "latest.json"
        ).read_text(encoding="utf-8")
    )
    assert incident["subject"] == "NFLX"
    assert incident["owner_role"] == "reliability_controller"
    assert incident["stage"] == "repairing"
    assert incident["repairer_run_id"] == request["owner_run_id"]
    assert dt.datetime.fromisoformat(incident["lease_expires_at"]) > NOW
    assert incident["recovery"]["phase"] == "reconcile"
    assert _snapshot_production_authority() == production_before
