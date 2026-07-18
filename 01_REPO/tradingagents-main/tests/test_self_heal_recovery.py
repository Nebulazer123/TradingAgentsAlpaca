import datetime as dt
import hashlib
import json
from pathlib import Path

import pytest

from tradingagents.orchestration.self_heal import (
    build_production_recovery_request,
    classify_recovery_signal,
    coordinate_verified_recovery,
    recovery_recipe,
)
from tradingagents.policy.live_control import load_live_control_state, write_live_control_state

NOW = dt.datetime(2026, 7, 18, 12, 0, tzinfo=dt.timezone.utc)
BINDINGS = {
    "incident_id": "inc-nflx-policy",
    "symbol": "NFLX",
    "broker_account": "paper",
    "environment": "test",
    "source_revision": "59ea344",
}


def _control(tmp_path: Path) -> Path:
    path = tmp_path / "live_control.json"
    if path.exists():
        return path
    write_live_control_state(
        path,
        frozen=True,
        reason="incident",
        dead_man_expires_at=NOW + dt.timedelta(days=1),
    )
    return path


def _adapters(calls: list[str], *, fail: dict[str, object] | None = None):
    packets = {
        "resolve_authority": {"root_cause_resolved": True},
        "regenerate_evidence": {"promotion_evidence_fresh": True},
        "sync_promotion": {"promotion_evidence_fresh": True, "issues": []},
        "reconcile": {
            "read_only": True,
            "execution_authority": "none",
            "can_submit_orders": False,
            "matched": True,
            "issues": [],
            "broker_write_calls": 0,
        },
        "focused_verify": {
            "focused_tests_passed": True,
            "passing_tests": ["tests/test_policy.py::test_nflx"],
            "verifier_run_id": "verify-nflx-1",
            "verifier_role_id": "independent_verifier",
        },
    }

    def adapter(phase):
        def run(arguments):
            assert arguments["phase"] == phase
            calls.append(phase)
            if fail and phase == fail["phase"]:
                return {
                    "outcome": "failed",
                    "failure_type": fail.get("failure_type", "permanent"),
                    "detail": fail.get("detail", "injected failure"),
                }
            return {"packet": packets[phase]}

        return run

    return {phase: adapter(phase) for phase in packets}


def _run(tmp_path: Path, calls: list[str], **overrides):
    return coordinate_verified_recovery(
        incident_id=BINDINGS["incident_id"],
        bindings=BINDINGS,
        adapters=overrides.pop("adapters", _adapters(calls)),
        owner_run_id=overrides.pop("owner_run_id", "repair-nflx-1"),
        recovery_run_id="recovery-nflx-1",
        control_path=_control(tmp_path),
        receipt_dir=tmp_path / "receipts",
        recovery_root=tmp_path / "results" / "control_plane" / "recovery",
        now=overrides.pop("now", NOW),
        **overrides,
    )


def test_policy_conflict_is_recoverable_not_manual_escalation():
    signal = classify_recovery_signal(
        {"label": "policy_rule_conflict", "reason": "approval_conflict", "symbol": "NFLX"}
    )

    assert signal["classification"] == "recoverable_integrity"
    assert signal["owner_role"] == "reliability_controller"
    assert signal["recipe"] == "resolve_policy_sync_reconcile_verify_rearm"


def test_unknown_broker_order_is_external_blocked():
    signal = classify_recovery_signal(
        {"label": "broker_reconciliation", "reason": "unknown_open_order"}
    )

    assert signal["classification"] == "external_blocked"
    assert signal["may_rearm"] is False


def test_recovery_recipe_cannot_submit_or_cancel_orders():
    recipe = recovery_recipe("resolve_policy_sync_reconcile_verify_rearm")

    assert "submit_order" in recipe["forbidden_effects"]
    assert "cancel_order" in recipe["forbidden_effects"]
    assert "replace_order" in recipe["forbidden_effects"]


def test_full_recipe_writes_strict_manifest_uses_distinct_verifier_and_only_rearms_verified_control(tmp_path):
    calls: list[str] = []

    result = _run(tmp_path, calls, idempotency_key="delivery-1")

    assert result["status"] == "monitoring"
    assert calls == [
        "resolve_authority",
        "regenerate_evidence",
        "sync_promotion",
        "reconcile",
        "focused_verify",
    ]
    run_root = tmp_path / "results" / "control_plane" / "recovery" / BINDINGS["incident_id"] / "recovery-nflx-1"
    manifest_path = run_root / "packets" / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    assert manifest["schema_version"] == "tradingagents.recovery_manifest.v1"
    assert manifest["kind"] == "verified_recovery_manifest"
    assert manifest["incident_id"] == BINDINGS["incident_id"]
    assert set(manifest["packet_sha256"]) == {"incident", "reconciliation", "promotion", "focused"}
    assert set(manifest["packet_paths"]) == {"incident", "reconciliation", "promotion", "focused"}
    assert all(Path(value).is_absolute() for value in manifest["packet_paths"].values())
    assert all(len(value) == 64 for value in manifest["packet_sha256"].values())
    assert manifest["packet_sha256"]["focused"] == hashlib.sha256((run_root / "packets" / "focused_verify.json").read_bytes()).hexdigest()
    ready = json.loads((run_root / "packets" / "ready_incident.json").read_text())
    focused = json.loads((run_root / "packets" / "focused_verify.json").read_text())
    assert ready["repairer_run_id"] == "repair-nflx-1"
    assert focused["verifier_run_id"] != ready["repairer_run_id"]
    assert focused["verifier_role_id"] != ready["repairer_role_id"]
    state, issues = load_live_control_state(tmp_path / "live_control.json", now=NOW)
    assert issues == []
    assert state["frozen"] is False
    assert state["dead_man_expires_at"] == (NOW + dt.timedelta(minutes=90)).isoformat(timespec="seconds")
    incident = json.loads((tmp_path / "results" / "control_plane" / "incidents" / BINDINGS["incident_id"] / "latest.json").read_text())
    assert incident["stage"] == "monitoring"


def test_transient_failure_retries_at_bounded_backoff_and_then_resumes_same_phase(tmp_path):
    calls: list[str] = []
    adapters = _adapters(calls, fail={"phase": "resolve_authority", "failure_type": "transient"})
    first = _run(tmp_path, calls, adapters=adapters)

    assert first["status"] == "frozen"
    assert first["failure"]["kind"] == "transient"
    assert first["next_retry_at"] == (NOW + dt.timedelta(seconds=30)).isoformat()
    too_early = _run(tmp_path, calls, adapters=adapters, now=NOW + dt.timedelta(seconds=1))
    assert too_early["status"] == "retry_scheduled"
    recovered_adapters = _adapters(calls)
    second = _run(tmp_path, calls, adapters=recovered_adapters, now=NOW + dt.timedelta(seconds=30))
    assert second["status"] == "monitoring"
    assert calls.count("resolve_authority") == 2


def test_transient_retry_exhaustion_remains_owned_and_frozen_with_follow_on_time(tmp_path):
    calls: list[str] = []
    failing = _adapters(calls, fail={"phase": "resolve_authority", "failure_type": "transient"})

    first = _run(tmp_path, calls, adapters=failing)
    second = _run(tmp_path, calls, adapters=failing, now=NOW + dt.timedelta(seconds=30))
    third = _run(tmp_path, calls, adapters=failing, now=NOW + dt.timedelta(seconds=150))

    assert first["failure"]["kind"] == "transient"
    assert second["failure"]["kind"] == "transient"
    assert third["status"] == "frozen"
    assert third["failure"]["kind"] == "transient_exhausted"
    assert third["next_retry_at"] is None
    incident = json.loads((tmp_path / "results" / "control_plane" / "incidents" / BINDINGS["incident_id"] / "latest.json").read_text())
    assert incident["stage"] == "repairing"
    assert incident["owner_role"] == "reliability_controller"
    state = json.loads((tmp_path / "results" / "control_plane" / "recovery" / BINDINGS["incident_id"] / "state.json").read_text())
    assert state["follow_on_required"] is True
    follow_on = _run(tmp_path, calls, adapters=_adapters(calls), now=NOW + dt.timedelta(seconds=270))
    assert follow_on["status"] == "monitoring"
    assert follow_on["recovery_run_id"].endswith("-follow-1")


def test_permanent_and_forbidden_failures_stop_frozen_without_rearm(tmp_path):
    calls: list[str] = []
    failed = _run(tmp_path, calls, adapters=_adapters(calls, fail={"phase": "sync_promotion"}))

    assert failed["status"] == "frozen"
    assert failed["failure"]["kind"] == "permanent_integrity"
    assert calls == ["resolve_authority", "regenerate_evidence", "sync_promotion"]
    state, _issues = load_live_control_state(tmp_path / "live_control.json", now=NOW)
    assert state["frozen"] is True

    forbidden_calls: list[str] = []
    adapters = _adapters(forbidden_calls)
    adapters["reconcile"] = lambda _arguments: {"packet": {"requested_effects": ["cancel_order"]}}
    blocked = _run(tmp_path / "forbidden", forbidden_calls, adapters=adapters)
    assert blocked["failure"]["kind"] == "forbidden_effect"


def test_adapter_cannot_invent_canonical_identity_in_a_phase_packet(tmp_path):
    calls: list[str] = []
    adapters = _adapters(calls)
    adapters["sync_promotion"] = lambda _arguments: {
        "packet": {"incident_id": "other-incident", "promotion_evidence_fresh": True, "issues": []}
    }

    blocked = _run(tmp_path, calls, adapters=adapters)

    assert blocked["status"] == "frozen"
    assert blocked["failure"]["kind"] == "permanent_integrity"
    assert "binding mismatch" in blocked["failure"]["detail"]


def test_external_dependency_is_the_only_external_blocked_path(tmp_path):
    calls: list[str] = []
    result = _run(
        tmp_path,
        calls,
        adapters=_adapters(calls, fail={"phase": "reconcile", "failure_type": "external_blocked", "detail": "broker confirmation required"}),
    )

    assert result["status"] == "external_blocked"
    incident = json.loads((tmp_path / "results" / "control_plane" / "incidents" / BINDINGS["incident_id"] / "latest.json").read_text())
    assert incident["stage"] == "external_blocked"
    assert incident["external_blockers"] == ["broker confirmation required"]


def test_competing_owner_is_noop_and_stale_lease_takeover_is_audited(tmp_path):
    calls: list[str] = []
    first = _run(tmp_path, calls, adapters=_adapters(calls, fail={"phase": "resolve_authority", "failure_type": "transient"}))
    assert first["status"] == "frozen"

    competing = _run(tmp_path, calls, owner_run_id="repair-nflx-2")
    assert competing["status"] == "owner_active"
    taken = _run(tmp_path, calls, owner_run_id="repair-nflx-2", now=NOW + dt.timedelta(minutes=31))
    assert taken["status"] == "monitoring"
    events = (tmp_path / "results" / "control_plane" / "recovery" / BINDINGS["incident_id"] / "events.jsonl").read_text()
    assert '"event":"lease_taken_over"' in events


def test_crash_after_durable_phase_packet_resumes_without_duplicate_adapter_call(tmp_path):
    calls: list[str] = []

    def crash(boundary):
        if boundary["phase"] == "resolve_authority":
            raise SystemExit("simulated crash")

    with pytest.raises(SystemExit, match="simulated crash"):
        _run(tmp_path, calls, fault_hook=crash)
    resumed = _run(tmp_path, calls)

    assert resumed["status"] == "monitoring"
    assert calls.count("resolve_authority") == 1


def test_duplicate_delivery_does_not_repeat_broker_read_or_rearm(tmp_path):
    calls: list[str] = []
    first = _run(tmp_path, calls, idempotency_key="delivery-1")
    second = _run(tmp_path, calls, idempotency_key="delivery-1")

    assert first["status"] == "monitoring"
    assert second["status"] == "duplicate"
    assert calls.count("reconcile") == 1
    assert len(list((tmp_path / "receipts").glob("verified-rearm-*.json"))) == 1


def test_tampered_completed_artifact_stays_frozen_without_repeating_broker_read(tmp_path):
    calls: list[str] = []
    _run(tmp_path, calls, adapters=_adapters(calls, fail={"phase": "focused_verify"}))
    reconciliation = tmp_path / "results" / "control_plane" / "recovery" / BINDINGS["incident_id"] / "recovery-nflx-1" / "packets" / "reconcile.json"
    reconciliation.write_text('{"tampered":true}', encoding="utf-8")

    result = _run(tmp_path, calls)

    assert result["status"] == "frozen"
    assert result["failure"]["kind"] == "permanent_integrity"
    assert calls.count("reconcile") == 1


def test_snapshot_exposes_recovery_ownership_without_raw_packet_or_secrets(tmp_path, monkeypatch):
    from tests.test_automation_context_snapshot import _load_snapshot_module

    calls: list[str] = []
    _run(tmp_path, calls, adapters=_adapters(calls, fail={"phase": "reconcile", "failure_type": "external_blocked", "detail": "broker approval"}))
    snapshot = _load_snapshot_module()
    monkeypatch.setattr(snapshot, "ROOT", tmp_path)

    summary = snapshot.summarize_incidents(now=NOW)

    assert summary["recovery_owner"] == "reliability_controller"
    assert summary["recovery_phase"] == "reconcile"
    assert summary["recovery_last_failure"] == "external_blocked"
    assert summary["recovery_external_blocker"] == "broker approval"
    assert "history" not in summary


def test_recovery_module_has_no_order_write_calls_or_shell_execution():
    source = Path(__import__("tradingagents.orchestration.self_heal", fromlist=["self_heal"]).__file__).read_text(encoding="utf-8")

    for forbidden_call in ("submit_order(", "cancel_order(", "replace_order(", "close_position(", "subprocess.run("):
        assert forbidden_call not in source


def test_production_recovery_request_uses_fixed_structured_adapters(tmp_path):
    request = build_production_recovery_request(
        {
            "label": "policy_rule_conflict",
            "reason": "approval_conflict",
            "symbol": "NFLX",
            "path": "results/policy/latest.json",
        },
        repo_root=tmp_path,
    )

    assert request["incident_id"].startswith("self-heal-")
    assert request["bindings"]["symbol"] == "NFLX"
    assert set(request["adapters"]) == {
        "resolve_authority",
        "regenerate_evidence",
        "sync_promotion",
        "reconcile",
        "focused_verify",
    }
    assert request["adapters"]["resolve_authority"]({"phase": "resolve_authority"})["outcome"] == "failed"


def test_production_request_preserves_msft_and_rejects_preassembled_packets(tmp_path):
    source = tmp_path / "source.json"
    source.write_text(json.dumps({"recovery_packets": {"reconcile": {"matched": True}}}), encoding="utf-8")
    context = {
        "symbol": "MSFT",
        "broker_account": "paper-a",
        "environment": "test",
        "source_revision": "abc123",
        "supervisor_path": "missing-supervisor.json",
        "advisory_path": "missing-advisory.json",
        "hourly_dir": "missing-hourly",
        "report_path": "missing-report.json",
        "envelope_path": "missing-envelope.yaml",
        "promotion_state_path": "missing-state.json",
        "reconciliation_packet_paths": ["source.json"],
    }
    request = build_production_recovery_request(
        {"label": "policy_rule_conflict", "reason": "approval_conflict", "symbol": "MSFT", "path": "source.json", "recovery_context": context}, repo_root=tmp_path
    )

    assert request["bindings"]["symbol"] == "MSFT"
    assert request["bindings"]["broker_account"] == "paper-a"
    assert request["adapters"]["resolve_authority"]({"phase": "resolve_authority"})["outcome"] == "failed"


def test_existing_corrupt_state_fails_closed_without_reinitializing(tmp_path):
    recovery_root = tmp_path / "results" / "control_plane" / "recovery"
    state_path = recovery_root / BINDINGS["incident_id"] / "state.json"
    state_path.parent.mkdir(parents=True)
    state_path.write_text("{bad", encoding="utf-8")

    result = _run(tmp_path, [])

    assert result["status"] == "corrupt_state"
    assert state_path.read_text(encoding="utf-8") == "{bad"


def test_malformed_orphan_packet_is_not_recovered_as_completed(tmp_path):
    calls: list[str] = []
    _run(tmp_path, calls, adapters=_adapters(calls, fail={"phase": "regenerate_evidence"}))
    orphan = tmp_path / "results" / "control_plane" / "recovery" / BINDINGS["incident_id"] / "recovery-nflx-1" / "packets" / "regenerate_evidence.json"
    orphan.write_text(json.dumps({"generated_at": NOW.isoformat()}), encoding="utf-8")

    result = _run(tmp_path, calls)

    assert result["status"] == "frozen"
    assert result["failure"]["kind"] == "permanent_integrity"


def test_expired_persisted_owner_lock_is_quarantined_and_taken_over(tmp_path):
    calls: list[str] = []
    _run(tmp_path, calls, adapters=_adapters(calls, fail={"phase": "resolve_authority", "failure_type": "transient"}))
    lock = tmp_path / "results" / "control_plane" / "recovery" / BINDINGS["incident_id"] / ".owner.lock"
    lock.write_text(json.dumps({"schema_version": "tradingagents.recovery_lock.v1", "incident_id": BINDINGS["incident_id"], "owner_run_id": "repair-old", "lease_expires_at": (NOW - dt.timedelta(minutes=1)).isoformat(), "token": "old-owner-token"}), encoding="utf-8")

    result = _run(tmp_path, calls, owner_run_id="repair-new", now=NOW + dt.timedelta(minutes=31))

    assert result["status"] == "monitoring"
    assert list(lock.parent.glob(".owner.stale-*"))


def test_rearm_return_crash_recovers_active_task5_control_without_second_rearm(tmp_path):
    calls: list[str] = []
    rearm_calls = []

    from tradingagents.orchestration.recovery import rearm_after_verified_recovery

    def counted_rearm(**kwargs):
        rearm_calls.append(kwargs)
        return rearm_after_verified_recovery(**kwargs)

    def crash(boundary):
        if boundary["boundary"] == "after_rearm_return":
            raise SystemExit("after rearm")

    with pytest.raises(SystemExit, match="after rearm"):
        _run(tmp_path, calls, rearm=counted_rearm, fault_hook=crash)
    resumed = _run(tmp_path, calls, rearm=counted_rearm)

    assert resumed["status"] == "monitoring"
    assert len(rearm_calls) == 1
