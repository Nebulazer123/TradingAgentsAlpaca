import datetime as dt
import hashlib
import json
from pathlib import Path

import pytest

from tradingagents.orchestration.self_heal import (
    RECOVERY_PHASES,
    _classify_self_heal_signal,
    _valid_phase_packet,
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


def _loss_review_source_packet(
    *,
    symbol: str = "NFLX",
    account: str = "paper",
    packet_path: str = "/tmp/loss-review-evidence.json",
    hourly_packet_path: str = "/tmp/hourly-supervisor.json",
) -> dict:
    supervisor = {
        "symbol": symbol,
        "decision_id": f"loss-exit-{symbol}-20260718",
        "allowed": True,
        "policy_rule_exit": True,
        "allowed_exit_reason": "policy_stop_floor",
        "allowed_exit_reason_source": "pre-registered exit policy rule",
        "exit_policy_rule": "catastrophic_stop",
        "exit_policy_rationale": "The pre-registered rule fired.",
        "blockers": [],
        "blocked_reasons": [],
        "source_packet_ids": [f"supervisor-{symbol.lower()}"],
    }
    advisory = {
        "symbol": symbol,
        "requires_board_decision": False,
        "decision_owner": "execution_operator",
    }
    source_ref = f"local://{hourly_packet_path}"
    return {
        "schema_version": "1.0.0",
        "packet_id": f"source-evidence-{symbol.lower()}-loss-review",
        "generated_at": NOW.isoformat(),
        "analysis_only": True,
        "sources": [
            {
                "schema_version": "1.0.0",
                "source": "loss_review_evidence",
                "as_of": NOW.isoformat(),
                "path": source_ref,
                "quality": "high",
            }
        ],
        "source_refs": [source_ref],
        "input_hashes": {"request": "a" * 64},
        "freshness": {
            "as_of": NOW.isoformat(),
            "stale": False,
            "read_only": True,
            "can_submit_orders": False,
            "source_packet_count": 2,
        },
        "tool_route": "local_loss_review_evidence",
        "redaction_status": "no_secrets_seen",
        "source_name": "loss_review_evidence",
        "evidence_type": "loss_review_evidence",
        "subject": symbol,
        "symbol": symbol,
        "payload": {
            "symbol": symbol,
            "hourly_packet_path": hourly_packet_path,
            "hourly_decision": "loss-review",
            "review_allowed": True,
            "supervisor_review_authority": supervisor,
            "entry_context": {"symbol": symbol, "account": account},
            "entry_context_found": True,
            "advisory_analysis": advisory,
            "analysis_only": True,
            "execution_authority": "none",
            "forbidden_effects": [
                "create_trade_intent",
                "size_position",
                "submit_order",
                "promote_sleeve",
                "waive_live_gate",
                "mark_loss_exit_allowed",
            ],
        },
        "quality": "medium",
        "packet_path": packet_path,
        "can_submit_orders": False,
        "execution_authority": "none",
        "hourly_packet_path": hourly_packet_path,
        "hourly_decision": "loss-review",
        "review_allowed": True,
        "entry_context_found": True,
        "entry_context": {"symbol": symbol, "account": account},
        "evidence_needs": ["company_specific_news"],
        "evidence_coverage_by_need": {"company_specific_news": True},
        "remaining_blockers_before_refresh_count": 1,
        "resolved_blockers_by_refresh": ["company-specific news check"],
        "remaining_blocker_count": 0,
        "resolved_blocker_count": 1,
        "next_action": "pre_registered_policy_approval_preserved",
        "source_packet_count": 1,
        "source_packet_paths": {
            f"provider-{symbol.lower()}": f"/tmp/provider-{symbol.lower()}.json"
        },
        "summary_packet_path": f"/tmp/provider-{symbol.lower()}-summary.json",
    }


def _promotion_source_packet(*, symbol: str = "NFLX") -> dict:
    return {
        "summary": "promotion state synchronized",
        "promoted": [],
        "demoted": [],
        "issues_by_sleeve": {"default": []},
        "state_path": "/tmp/promotion-state.json",
        "report_path": "/tmp/paper-tournament.json",
        "arm_live": False,
        "ci_green": False,
        "can_submit_orders": False,
        "execution_authority": "none",
        "state": {
            "schema_version": "1.1.0",
            "generated_at": NOW.isoformat(),
            "source": {
                "kind": "paper_tournament_sync",
                "tournament_id": "tournament-20260718",
                "report_generated_at": NOW.isoformat(),
                "arm_live": False,
                "ci_green": False,
            },
            "sleeves": {"default": {"symbol": symbol, "live_enabled": False}},
        },
    }


def _reconciliation_source_packet(*, symbol: str = "NFLX") -> dict:
    return {
        "schema_version": 1,
        "kind": "symbol_broker_reconciliation",
        "generated_at": NOW.isoformat(),
        "read_only": True,
        "analysis_only": True,
        "can_submit_orders": False,
        "execution_authority": "none",
        "symbol": symbol,
        "matched": True,
        "position": {
            "symbol": symbol,
            "qty": "0",
            "notional": "0",
            "market_value": "0",
            "avg_entry_price": "0",
        },
        "open_orders": [],
        "recent_fills": [],
        "checked_client_order_ids": [],
        "issues": [],
        "broker_write_calls": 0,
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
        "resolve_authority": {
            "kind": "recovery_authority",
            "allowed": True,
            "requires_additional_decision": False,
            "authority_source": "pre_registered_policy_rule",
            "decision_owner": "execution_operator",
        },
        "regenerate_evidence": {
            **_loss_review_source_packet(),
        },
        "sync_promotion": {
            **_promotion_source_packet(),
            "promotion_evidence_fresh": True,
            "issues": [],
        },
        "reconcile": {
            **_reconciliation_source_packet(),
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
            packet = json.loads(json.dumps(packets[phase]))
            generated_at = arguments.get("generated_at", NOW.isoformat())
            packet["generated_at"] = generated_at
            if phase == "regenerate_evidence":
                packet["freshness"]["as_of"] = generated_at
                for source in packet["sources"]:
                    source["as_of"] = generated_at
            elif phase == "sync_promotion":
                packet["state"]["generated_at"] = generated_at
                packet["state"]["source"]["report_generated_at"] = generated_at
            return {"packet": packet}

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


def test_only_exact_hourly_board_review_is_owned_recovery():
    exact = {
        "label": "hourly",
        "reason": "board_review",
        "path": "results/hourly_supervisor/latest-compact.json",
    }

    classified = classify_recovery_signal(exact)

    assert classified["classification"] == "recoverable_integrity"
    assert classified["status"] == "owned_recovery_ready"
    assert classified["may_rearm"] is True

    other_order_adjacent = _classify_self_heal_signal(
        {
            "label": "execution_board_review",
            "reason": "board_review",
            "path": "results/execution_board/latest.json",
        },
        prior_signatures=set(),
    )
    malformed_label = _classify_self_heal_signal(
        {
            "label": "hourly-review",
            "reason": "board_review",
            "path": "results/hourly_supervisor/latest-compact.json",
        },
        prior_signatures=set(),
    )

    assert other_order_adjacent["classification"] == "escalate_order_adjacent"
    assert other_order_adjacent["status"] == "escalated"
    assert malformed_label["classification"] == "observe_only"
    assert malformed_label["status"] == "observed"


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


def test_stale_takeover_revalidates_prior_phase_owner_without_rewriting_it(tmp_path):
    calls: list[str] = []
    first = _run(
        tmp_path,
        calls,
        adapters=_adapters(
            calls,
            fail={"phase": "focused_verify", "failure_type": "transient"},
        ),
    )
    assert first["status"] == "frozen"
    resolve_path = (
        tmp_path
        / "results"
        / "control_plane"
        / "recovery"
        / BINDINGS["incident_id"]
        / "recovery-nflx-1"
        / "packets"
        / "resolve_authority.json"
    )
    original_owner = json.loads(resolve_path.read_text(encoding="utf-8"))[
        "owner_run_id"
    ]

    resumed = _run(
        tmp_path,
        calls,
        adapters=_adapters(calls),
        owner_run_id="repair-nflx-2",
        now=NOW + dt.timedelta(minutes=30),
    )

    assert resumed["status"] == "monitoring", resumed
    assert (
        json.loads(resolve_path.read_text(encoding="utf-8"))["owner_run_id"]
        == original_owner
    )


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

    assert request == {
        "ready": False,
        "outcome": "transient",
        "detail": "canonical recovery context is incomplete",
    }


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


def test_all_phase_packet_validators_reject_metadata_complete_false_greens(tmp_path):
    common = {
        **BINDINGS,
        "generated_at": NOW.isoformat(),
        "recovery_run_id": "recovery-nflx-1",
        "owner_run_id": "repair-nflx-1",
        "owner_role": "reliability_controller",
    }
    state = {
        "bindings": dict(BINDINGS),
        "recovery_run_id": "recovery-nflx-1",
        "owner_run_id": "repair-nflx-1",
        "owner_role": "reliability_controller",
        "phase_outputs": {},
    }

    for phase in RECOVERY_PHASES:
        packet_path = tmp_path / f"{phase}.json"
        packet_path.write_text(
            json.dumps(
                {
                    **common,
                    "phase": phase,
                    "schema_version": (
                        "tradingagents.incident.v1"
                        if phase == "ready_incident"
                        else (
                            "tradingagents.recovery_manifest.v1"
                            if phase == "manifest"
                            else "tradingagents.recovery_phase.v1"
                        )
                    ),
                }
            ),
            encoding="utf-8",
        )
        assert (
            _valid_phase_packet(
                packet_path,
                phase,
                BINDINGS,
                state=state,
                phase_outputs={},
                control_path=tmp_path / "live_control.json",
                now=NOW,
                idempotency_key="delivery-1",
            )
            is False
        ), phase

    unknown = tmp_path / "unknown.json"
    unknown.write_text(
        json.dumps(
            {
                **common,
                "phase": "unknown",
                "schema_version": "tradingagents.recovery_phase.v1",
            }
        ),
        encoding="utf-8",
    )
    assert (
        _valid_phase_packet(
            unknown,
            "unknown",
            BINDINGS,
            state=state,
            phase_outputs={},
            control_path=tmp_path / "live_control.json",
            now=NOW,
            idempotency_key="delivery-1",
        )
        is False
    )


def test_each_valid_phase_packet_passes_then_one_invariant_mutation_fails(tmp_path):
    calls: list[str] = []
    assert _run(tmp_path, calls, idempotency_key="delivery-1")["status"] == "monitoring"
    state_path = (
        tmp_path
        / "results"
        / "control_plane"
        / "recovery"
        / BINDINGS["incident_id"]
        / "state.json"
    )
    state = json.loads(state_path.read_text(encoding="utf-8"))
    mutations = {
        "resolve_authority": lambda packet: packet.update({"allowed": False}),
        "regenerate_evidence": lambda packet: packet.update(
            {"analysis_only": False}
        ),
        "sync_promotion": lambda packet: packet.update({"arm_live": True}),
        "reconcile": lambda packet: packet.update({"matched": False}),
        "focused_verify": lambda packet: packet.update(
            {"verifier_run_id": packet["owner_run_id"]}
        ),
        "ready_incident": lambda packet: packet.update({"evidence_refs": []}),
        "manifest": lambda packet: packet.update({"packet_paths": {}}),
        "rearm": lambda packet: packet.update({"receipt_sha256": "0" * 64}),
    }

    for phase in RECOVERY_PHASES:
        phase_path = Path(state["phase_outputs"][phase]["path"])
        original = phase_path.read_text(encoding="utf-8")
        assert _valid_phase_packet(
            phase_path,
            phase,
            BINDINGS,
            state=state,
            phase_outputs=state["phase_outputs"],
            control_path=tmp_path / "live_control.json",
            now=NOW,
            idempotency_key="delivery-1",
        ), phase
        packet = json.loads(original)
        mutations[phase](packet)
        phase_path.write_text(json.dumps(packet), encoding="utf-8")
        assert (
            _valid_phase_packet(
                phase_path,
                phase,
                BINDINGS,
                state=state,
                phase_outputs=state["phase_outputs"],
                control_path=tmp_path / "live_control.json",
                now=NOW,
                idempotency_key="delivery-1",
            )
            is False
        ), phase
        phase_path.write_text(original, encoding="utf-8")


def test_real_shaped_owned_packets_reject_each_source_invariant_mutation(tmp_path):
    calls: list[str] = []
    assert _run(tmp_path, calls, idempotency_key="delivery-1")["status"] == "monitoring"
    state_path = (
        tmp_path
        / "results"
        / "control_plane"
        / "recovery"
        / BINDINGS["incident_id"]
        / "state.json"
    )
    state = json.loads(state_path.read_text(encoding="utf-8"))
    mutations = [
        (
            "regenerate_evidence",
            "canonical kind",
            lambda packet: packet.update({"kind": "self_attested_evidence"}),
        ),
        (
            "regenerate_evidence",
            "source schema",
            lambda packet: packet.update({"source_schema_version": 1}),
        ),
        (
            "regenerate_evidence",
            "packet identity",
            lambda packet: packet.update({"packet_id": ""}),
        ),
        (
            "regenerate_evidence",
            "source name",
            lambda packet: packet.update({"source_name": "other"}),
        ),
        (
            "regenerate_evidence",
            "evidence type",
            lambda packet: packet.update({"evidence_type": "other"}),
        ),
        (
            "regenerate_evidence",
            "subject binding",
            lambda packet: packet.update({"subject": "TSLA"}),
        ),
        (
            "regenerate_evidence",
            "tool route",
            lambda packet: packet.update({"tool_route": "self_attested"}),
        ),
        (
            "regenerate_evidence",
            "source refs",
            lambda packet: packet.update({"source_refs": []}),
        ),
        (
            "regenerate_evidence",
            "provenance sources",
            lambda packet: packet.update({"sources": []}),
        ),
        (
            "regenerate_evidence",
            "provenance source path",
            lambda packet: packet["sources"][0].update(
                {"path": "local://other-hourly.json"}
            ),
        ),
        (
            "regenerate_evidence",
            "input hashes",
            lambda packet: packet.update({"input_hashes": []}),
        ),
        (
            "regenerate_evidence",
            "request digest",
            lambda packet: packet.update({"input_hashes": {"request": "not-a-digest"}}),
        ),
        (
            "regenerate_evidence",
            "freshness authority",
            lambda packet: packet["freshness"].update({"read_only": False}),
        ),
        (
            "regenerate_evidence",
            "freshness source count",
            lambda packet: packet["freshness"].update({"source_packet_count": 1}),
        ),
        (
            "regenerate_evidence",
            "source packet paths",
            lambda packet: packet.update({"source_packet_paths": []}),
        ),
        (
            "regenerate_evidence",
            "canonical payload envelope",
            lambda packet: packet.update({"payload": {}}),
        ),
        (
            "regenerate_evidence",
            "forbidden effect rails",
            lambda packet: packet["payload"].update({"forbidden_effects": []}),
        ),
        (
            "regenerate_evidence",
            "entry account binding",
            lambda packet: packet["payload"]["entry_context"].update(
                {"account": "live"}
            ),
        ),
        (
            "sync_promotion",
            "canonical kind",
            lambda packet: packet.update({"kind": "self_attested_promotion"}),
        ),
        (
            "sync_promotion",
            "source identity",
            lambda packet: packet.update({"source_identity": "other"}),
        ),
        (
            "sync_promotion",
            "issues mapping",
            lambda packet: packet.update({"issues_by_sleeve": []}),
        ),
        (
            "sync_promotion",
            "nonempty sleeve issues",
            lambda packet: packet.update(
                {"issues_by_sleeve": {"default": ["not synchronized"]}}
            ),
        ),
        (
            "sync_promotion",
            "state source kind",
            lambda packet: packet["state"]["source"].update({"kind": "other"}),
        ),
        (
            "sync_promotion",
            "source state path",
            lambda packet: packet.update({"state_path": ""}),
        ),
        (
            "reconcile",
            "canonical kind",
            lambda packet: packet.update({"kind": "self_attested_reconciliation"}),
        ),
        (
            "reconcile",
            "source identity",
            lambda packet: packet.update({"source_identity": "other"}),
        ),
        (
            "reconcile",
            "analysis only",
            lambda packet: packet.update({"analysis_only": False}),
        ),
        (
            "reconcile",
            "position shape",
            lambda packet: packet.update({"position": []}),
        ),
        (
            "reconcile",
            "position symbol",
            lambda packet: packet["position"].update({"symbol": "TSLA"}),
        ),
        (
            "reconcile",
            "open orders shape",
            lambda packet: packet.update({"open_orders": {}}),
        ),
        (
            "reconcile",
            "open order identity",
            lambda packet: packet.update(
                {"open_orders": [{"symbol": "NFLX", "status": "open"}]}
            ),
        ),
        (
            "reconcile",
            "recent fill identity",
            lambda packet: packet.update(
                {
                    "recent_fills": [
                        {
                            "symbol": "NFLX",
                            "client_order_id": "unknown-fill",
                            "status": "filled",
                        }
                    ]
                }
            ),
        ),
        (
            "reconcile",
            "checked client ids",
            lambda packet: packet.update({"checked_client_order_ids": [True]}),
        ),
    ]

    for phase, invariant, mutate in mutations:
        phase_path = Path(state["phase_outputs"][phase]["path"])
        original = phase_path.read_text(encoding="utf-8")
        assert _valid_phase_packet(
            phase_path,
            phase,
            BINDINGS,
            state=state,
            phase_outputs=state["phase_outputs"],
            control_path=tmp_path / "live_control.json",
            now=NOW,
            idempotency_key="delivery-1",
        ), (phase, invariant, "valid baseline")
        packet = json.loads(original)
        mutate(packet)
        phase_path.write_text(json.dumps(packet), encoding="utf-8")
        assert (
            _valid_phase_packet(
                phase_path,
                phase,
                BINDINGS,
                state=state,
                phase_outputs=state["phase_outputs"],
                control_path=tmp_path / "live_control.json",
                now=NOW,
                idempotency_key="delivery-1",
            )
            is False
        ), (phase, invariant)
        phase_path.write_text(original, encoding="utf-8")


@pytest.mark.parametrize(
    "mutate",
    [
        lambda state: state["bindings"].update({"extra": "not-canonical"}),
        lambda state: state.update({"follow_on_count": True}),
        lambda state: state.update(
            {
                "follow_on_required": True,
                "follow_on_not_before": "2026-07-18T12:05:00",
                "parent_recovery_run_id": "../unsafe",
            }
        ),
        lambda state: state["phase_outputs"].update(
            {
                "reconcile": {
                    "path": "/tmp/out-of-order.json",
                    "sha256": "a" * 64,
                }
            }
        ),
    ],
)
def test_malformed_persisted_state_schema_is_corrupt_and_never_raises(
    tmp_path, mutate
):
    calls: list[str] = []
    first = _run(
        tmp_path,
        calls,
        adapters=_adapters(
            calls,
            fail={"phase": "resolve_authority", "failure_type": "transient"},
        ),
    )
    assert first["status"] == "frozen"
    state_path = (
        tmp_path
        / "results"
        / "control_plane"
        / "recovery"
        / BINDINGS["incident_id"]
        / "state.json"
    )
    state = json.loads(state_path.read_text(encoding="utf-8"))
    mutate(state)
    state_path.write_text(json.dumps(state), encoding="utf-8")

    result = _run(tmp_path, calls, now=NOW + dt.timedelta(seconds=30))

    assert result["status"] == "corrupt_state"
    control, _issues = load_live_control_state(_control(tmp_path), now=NOW)
    assert control["frozen"] is True


def test_crash_resume_rejects_changed_receipt_identity_and_idempotency(tmp_path):
    calls: list[str] = []
    rearm_calls: list[dict] = []
    from tradingagents.orchestration.recovery import rearm_after_verified_recovery

    def counted_rearm(**kwargs):
        rearm_calls.append(kwargs)
        return rearm_after_verified_recovery(**kwargs)

    def crash(boundary):
        if boundary["boundary"] == "after_rearm_return":
            raise SystemExit("after rearm")

    with pytest.raises(SystemExit, match="after rearm"):
        _run(
            tmp_path,
            calls,
            idempotency_key="delivery-1",
            fault_hook=crash,
            rearm=counted_rearm,
        )

    control_path = tmp_path / "live_control.json"
    control = json.loads(control_path.read_text(encoding="utf-8"))
    receipt_path = Path(control["recovery_receipt_path"])
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["repairer_run_id"] = "other-repairer"
    receipt_path.write_text(
        json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    control["recovery_receipt_sha256"] = hashlib.sha256(
        receipt_path.read_bytes()
    ).hexdigest()
    control_path.write_text(json.dumps(control), encoding="utf-8")

    changed_identity = _run(
        tmp_path,
        calls,
        idempotency_key="delivery-1",
        rearm=counted_rearm,
    )
    assert changed_identity["status"] == "frozen"
    assert changed_identity["phase"] == "rearm"
    assert len(rearm_calls) == 1
    assert calls.count("reconcile") == 1
    frozen_control, _issues = load_live_control_state(control_path, now=NOW)
    assert frozen_control["frozen"] is True

    other_tmp = tmp_path / "idempotency"
    other_calls: list[str] = []
    other_rearm_calls: list[dict] = []

    def other_counted_rearm(**kwargs):
        other_rearm_calls.append(kwargs)
        return rearm_after_verified_recovery(**kwargs)

    with pytest.raises(SystemExit, match="after rearm"):
        _run(
            other_tmp,
            other_calls,
            idempotency_key="delivery-1",
            fault_hook=crash,
            rearm=other_counted_rearm,
        )
    changed_delivery = _run(
        other_tmp,
        other_calls,
        idempotency_key="delivery-2",
        rearm=other_counted_rearm,
    )
    assert changed_delivery["status"] == "frozen"
    assert changed_delivery["phase"] == "rearm"
    assert len(other_rearm_calls) == 1
    assert other_calls.count("reconcile") == 1
    frozen_other, _issues = load_live_control_state(
        other_tmp / "live_control.json", now=NOW
    )
    assert frozen_other["frozen"] is True


def test_rearm_intent_requires_exact_schema_and_rearm_orphan_needs_active_receipt(
    tmp_path,
):
    calls: list[str] = []

    def crash_after_return(boundary):
        if boundary["boundary"] == "after_rearm_return":
            raise SystemExit("after rearm")

    with pytest.raises(SystemExit, match="after rearm"):
        _run(
            tmp_path / "intent",
            calls,
            idempotency_key="delivery-1",
            fault_hook=crash_after_return,
        )
    state_path = (
        tmp_path
        / "intent"
        / "results"
        / "control_plane"
        / "recovery"
        / BINDINGS["incident_id"]
        / "state.json"
    )
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["rearm_intent"]["unexpected"] = "false-green"
    state_path.write_text(json.dumps(state), encoding="utf-8")
    malformed_intent = _run(
        tmp_path / "intent",
        calls,
        idempotency_key="delivery-1",
    )
    assert malformed_intent["status"] == "corrupt_state"

    orphan_calls: list[str] = []

    def crash_after_manifest_packet(boundary):
        if (
            boundary["boundary"] == "after_phase_fsync"
            and boundary["phase"] == "manifest"
        ):
            raise SystemExit("manifest packet orphan")

    with pytest.raises(SystemExit, match="manifest packet orphan"):
        _run(
            tmp_path / "orphan",
            orphan_calls,
            idempotency_key="delivery-1",
            fault_hook=crash_after_manifest_packet,
        )
    orphan = (
        tmp_path
        / "orphan"
        / "results"
        / "control_plane"
        / "recovery"
        / BINDINGS["incident_id"]
        / "recovery-nflx-1"
        / "packets"
        / "rearm.json"
    )
    packet = {
        **BINDINGS,
        "generated_at": NOW.isoformat(),
        "phase": "rearm",
        "recovery_run_id": "recovery-nflx-1",
        "owner_run_id": "repair-nflx-1",
        "owner_role": "reliability_controller",
        "schema_version": "tradingagents.recovery_phase.v1",
    }
    orphan.write_text(
        json.dumps(packet),
        encoding="utf-8",
    )
    rearm_calls: list[dict] = []

    def counted_rearm(**kwargs):
        rearm_calls.append(kwargs)
        raise AssertionError("fake rearm orphan must not call rearm")

    orphan_result = _run(
        tmp_path / "orphan",
        orphan_calls,
        idempotency_key="delivery-1",
        rearm=counted_rearm,
    )
    assert orphan_result["status"] == "frozen"
    assert orphan_result["phase"] == "rearm"
    assert rearm_calls == []
    orphan_control, _issues = load_live_control_state(
        tmp_path / "orphan" / "live_control.json", now=NOW
    )
    assert orphan_control["frozen"] is True


def test_thin_manifest_orphan_stops_before_rearm_and_keeps_control_frozen(tmp_path):
    calls: list[str] = []

    def crash(boundary):
        if (
            boundary["boundary"] == "after_phase_fsync"
            and boundary["phase"] == "manifest"
        ):
            raise SystemExit("manifest orphan")

    with pytest.raises(SystemExit, match="manifest orphan"):
        _run(tmp_path, calls, fault_hook=crash)
    manifest = (
        tmp_path
        / "results"
        / "control_plane"
        / "recovery"
        / BINDINGS["incident_id"]
        / "recovery-nflx-1"
        / "packets"
        / "manifest.json"
    )
    packet = json.loads(manifest.read_text(encoding="utf-8"))
    packet["packet_paths"] = {}
    packet["packet_sha256"] = {}
    manifest.write_text(json.dumps(packet), encoding="utf-8")
    rearm_calls: list[dict] = []

    def counted_rearm(**kwargs):
        rearm_calls.append(kwargs)
        raise AssertionError("thin manifest must stop before rearm")

    result = _run(tmp_path, calls, rearm=counted_rearm)

    assert result["status"] == "frozen"
    assert result["phase"] == "manifest"
    assert rearm_calls == []
    control, _issues = load_live_control_state(tmp_path / "live_control.json", now=NOW)
    assert control["frozen"] is True


def test_real_loss_review_envelope_derives_nested_account_and_fixed_adapters(
    tmp_path,
):
    hourly_path = (
        tmp_path
        / "results"
        / "hourly_supervisor"
        / "hourly-supervisor-nflx.json"
    )
    hourly_path.parent.mkdir(parents=True)
    supervisor = {
        "symbol": "NFLX",
        "decision_id": "loss-exit-NFLX-20260718",
        "allowed": True,
        "policy_rule_exit": True,
        "allowed_exit_reason": "policy_stop_floor",
        "allowed_exit_reason_source": "pre-registered exit policy rule",
        "exit_policy_rule": "catastrophic_stop",
        "exit_policy_rationale": "The pre-registered rule fired.",
        "blockers": [],
        "blocked_reasons": [],
        "source_packet_ids": ["supervisor-nflx"],
    }
    advisory = {
        "symbol": "NFLX",
        "requires_board_decision": False,
        "decision_owner": "execution_operator",
    }
    hourly_path.write_text(
        json.dumps(
            {
                "generated_at": NOW.isoformat(),
                "decision": "loss-review",
                "evidence": {"loss_exit_review": supervisor},
            }
        ),
        encoding="utf-8",
    )
    evidence_path = tmp_path / "results" / "loss_review_evidence" / "latest.json"
    evidence_path.parent.mkdir(parents=True)
    evidence_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "source_name": "loss_review_evidence",
                "evidence_type": "loss_review_evidence",
                "subject": "NFLX",
                "symbol": "NFLX",
                "payload": {
                    "symbol": "NFLX",
                    "entry_context": {"symbol": "NFLX", "account": "live"},
                    "hourly_packet_path": str(hourly_path.relative_to(tmp_path)),
                    "supervisor_review_authority": supervisor,
                    "advisory_analysis": advisory,
                },
            }
        ),
        encoding="utf-8",
    )
    report = tmp_path / "results" / "paper_strategy_tournament" / "latest.json"
    promotion = tmp_path / "results" / "policy" / "promotion_state.json"
    envelope = tmp_path / "config" / "risk_envelope.yaml"
    for path, content in (
        (report, "{}"),
        (promotion, "{}"),
        (envelope, "tiny_live_tranche_usd: 25\n"),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    invocations: list[list[str]] = []

    class Result:
        def __init__(self, *, stdout="", stderr="", returncode=0):
            self.stdout = stdout
            self.stderr = stderr
            self.returncode = returncode

    def runner(argv, **_kwargs):
        invocations.append(list(argv))
        if argv[:3] == ["git", "rev-parse", "HEAD"]:
            return Result(stdout="source-revision\n")
        if "loss-review-evidence" in argv:
            return Result(
                stdout=json.dumps(
                    {
                        "symbol": "NFLX",
                        "analysis_only": True,
                        "can_submit_orders": False,
                        "execution_authority": "none",
                        "packet_path": str(evidence_path),
                        "hourly_packet_path": str(hourly_path),
                    }
                )
            )
        if "sync-promotion" in argv:
            return Result(
                stdout=json.dumps(
                    {
                        "issues_by_sleeve": {},
                        "arm_live": False,
                        "ci_green": False,
                        "can_submit_orders": False,
                        "execution_authority": "none",
                    }
                )
            )
        if "reconcile-symbol-incident" in argv:
            return Result(
                stdout=json.dumps(
                    {
                        "read_only": True,
                        "execution_authority": "none",
                        "can_submit_orders": False,
                        "matched": True,
                        "issues": [],
                        "broker_write_calls": 0,
                    }
                )
            )
        if "pytest" in argv:
            return Result(stdout="passed")
        raise AssertionError(argv)

    request = build_production_recovery_request(
        {
            "label": "policy_rule_conflict",
            "reason": "approval_conflict",
            "symbol": "NFLX",
            "path": str(evidence_path.relative_to(tmp_path)),
        },
        repo_root=tmp_path,
        command_runner=runner,
    )

    assert request["ready"] is True
    assert request["bindings"]["broker_account"] == "live"
    authority = request["adapters"]["resolve_authority"](
        {"phase": "resolve_authority"}
    )
    assert authority["packet"]["authority_source"] == "pre_registered_policy_rule"
    for phase in (
        "regenerate_evidence",
        "sync_promotion",
        "reconcile",
        "focused_verify",
    ):
        assert request["adapters"][phase]({"phase": phase}).get("packet")
    assert all(isinstance(argv, list) for argv in invocations)
    assert any("--no-arm-live" in argv and "--no-ci-green" in argv for argv in invocations)
    assert any("reconcile-symbol-incident" in argv for argv in invocations)

    conflicting = json.loads(evidence_path.read_text(encoding="utf-8"))
    conflicting["payload"]["entry_context"]["account"] = "paper"
    evidence_path.write_text(json.dumps(conflicting), encoding="utf-8")
    rejected = build_production_recovery_request(
        {
            "label": "policy_rule_conflict",
            "reason": "approval_conflict",
            "symbol": "NFLX",
            "path": str(evidence_path.relative_to(tmp_path)),
        },
        repo_root=tmp_path,
        command_runner=runner,
    )
    assert rejected["ready"] is False

    missing = json.loads(evidence_path.read_text(encoding="utf-8"))
    missing["payload"]["entry_context"].pop("account")
    evidence_path.write_text(json.dumps(missing), encoding="utf-8")
    missing_account = build_production_recovery_request(
        {
            "label": "policy_rule_conflict",
            "reason": "approval_conflict",
            "symbol": "NFLX",
            "path": str(evidence_path.relative_to(tmp_path)),
        },
        repo_root=tmp_path,
        command_runner=runner,
    )
    assert missing_account["ready"] is False

    signal_conflict = missing
    signal_conflict["payload"]["entry_context"]["account"] = "live"
    evidence_path.write_text(json.dumps(signal_conflict), encoding="utf-8")
    paper_signal = build_production_recovery_request(
        {
            "label": "policy_rule_conflict",
            "reason": "approval_conflict",
            "symbol": "NFLX",
            "broker_account": "paper",
            "path": str(evidence_path.relative_to(tmp_path)),
        },
        repo_root=tmp_path,
        command_runner=runner,
    )
    assert paper_signal["ready"] is False


def test_hourly_board_review_without_symbol_uses_canonical_evidence_and_completes(
    tmp_path,
):
    hourly_path = (
        tmp_path
        / "results"
        / "hourly_supervisor"
        / "hourly-supervisor-nflx.json"
    )
    hourly_path.parent.mkdir(parents=True)
    source_packet = _loss_review_source_packet(
        account="live",
        packet_path=str(
            tmp_path / "results" / "loss_review_evidence" / "latest.json"
        ),
        hourly_packet_path=str(hourly_path.relative_to(tmp_path)),
    )
    supervisor = source_packet["payload"]["supervisor_review_authority"]
    hourly_path.write_text(
        json.dumps(
            {
                "generated_at": NOW.isoformat(),
                "decision": "loss-review",
                "evidence": {"loss_exit_review": supervisor},
            }
        ),
        encoding="utf-8",
    )
    compact_path = (
        tmp_path / "results" / "hourly_supervisor" / "latest-compact.json"
    )
    compact_path.write_text(
        json.dumps(
            {
                "label": "hourly",
                "reason": "board_review",
                "path": str(compact_path.relative_to(tmp_path)),
            }
        ),
        encoding="utf-8",
    )
    evidence_path = tmp_path / "results" / "loss_review_evidence" / "latest.json"
    evidence_path.parent.mkdir(parents=True)
    evidence_path.write_text(json.dumps(source_packet), encoding="utf-8")
    for path, content in (
        (
            tmp_path / "results" / "paper_strategy_tournament" / "latest.json",
            "{}",
        ),
        (
            tmp_path / "results" / "policy" / "promotion_state.json",
            "{}",
        ),
        (tmp_path / "config" / "risk_envelope.yaml", "tiny_live_tranche_usd: 25\n"),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    invocations: list[list[str]] = []

    class Result:
        def __init__(self, *, stdout="", stderr="", returncode=0):
            self.stdout = stdout
            self.stderr = stderr
            self.returncode = returncode

    def runner(argv, **_kwargs):
        invocations.append(list(argv))
        if argv[:3] == ["git", "rev-parse", "HEAD"]:
            return Result(stdout="source-revision\n")
        if "loss-review-evidence" in argv:
            return Result(stdout=json.dumps(source_packet))
        if "sync-promotion" in argv:
            return Result(stdout=json.dumps(_promotion_source_packet()))
        if "reconcile-symbol-incident" in argv:
            return Result(stdout=json.dumps(_reconciliation_source_packet()))
        if "pytest" in argv:
            return Result(stdout="passed")
        raise AssertionError(argv)

    exact_signal = {
        "label": "hourly",
        "reason": "board_review",
        "path": "results/hourly_supervisor/latest-compact.json",
    }
    assert (
        classify_recovery_signal(exact_signal)["classification"]
        == "recoverable_integrity"
    )
    request = build_production_recovery_request(
        exact_signal,
        repo_root=tmp_path,
        command_runner=runner,
    )

    assert request["ready"] is True
    assert request["bindings"]["symbol"] == "NFLX"
    assert request["bindings"]["broker_account"] == "live"
    coordinator_args = dict(request)
    coordinator_args.pop("ready")
    result = coordinate_verified_recovery(
        **coordinator_args,
        control_path=_control(tmp_path / "production-control"),
        receipt_dir=tmp_path / "production-receipts",
        recovery_root=tmp_path / "production-recovery",
        now=NOW,
    )

    assert result["status"] == "monitoring"
    state_path = (
        tmp_path
        / "production-recovery"
        / request["incident_id"]
        / "state.json"
    )
    state = json.loads(state_path.read_text(encoding="utf-8"))
    expected_source_schemas = {
        "regenerate_evidence": "1.0.0",
        "sync_promotion": "1.1.0",
        "reconcile": 1,
    }
    for phase, source_schema in expected_source_schemas.items():
        packet = json.loads(
            Path(state["phase_outputs"][phase]["path"]).read_text(encoding="utf-8")
        )
        assert packet["schema_version"] == "tradingagents.recovery_phase.v1"
        assert packet["source_schema_version"] == source_schema
    assert any("loss-review-evidence" in argv for argv in invocations)
    assert any("reconcile-symbol-incident" in argv for argv in invocations)
    assert sum("pytest" in argv for argv in invocations) == 1

    conflict = build_production_recovery_request(
        {**exact_signal, "symbol": "TSLA"},
        repo_root=tmp_path,
        command_runner=runner,
    )
    assert conflict["ready"] is False
