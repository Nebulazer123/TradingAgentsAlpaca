import datetime as dt
import hashlib
import json
import os
import threading
import time
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path

import pytest

from tradingagents.brokers import alpaca_reconciliation
from tradingagents.brokers.manual_action_attribution import (
    build_owner_manual_action_attribution,
    replay_suppression_key,
    write_owner_manual_action_attribution,
)
from tradingagents.orchestration import recovery as recovery_module
from tradingagents.orchestration import self_heal as self_heal_module
from tradingagents.orchestration.authority import (
    ActionClass,
)
from tradingagents.orchestration.authority import (
    authority_for as real_authority_for,
)
from tradingagents.orchestration.recovery import rearm_after_verified_recovery
from tradingagents.orchestration.self_heal import (
    RECOVERY_FOCUSED_TESTS,
    RECOVERY_PHASES,
    _classify_self_heal_signal,
    _valid_phase_packet,
    build_production_recovery_request,
    classify_recovery_signal,
    coordinate_verified_recovery,
    recovery_recipe,
)
from tradingagents.policy.live_control import load_live_control_state, write_live_control_state
from tradingagents.policy.live_gate import evaluate_go_live_guard
from tradingagents.policy.loss_board_decision import (
    record_autonomous_loss_board_decision,
)
from tradingagents.policy.promotion_sync import sync_promotion_state_file

NOW = dt.datetime(2026, 7, 18, 12, 0, tzinfo=dt.timezone.utc)
BINDINGS = {
    "incident_id": "inc-nflx-policy",
    "symbol": "NFLX",
    "broker_account": "paper",
    "environment": "test",
    "source_revision": "59ea344",
}


def _write_json_packet(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )
    return path


def _write_self_heal_context(root: Path, *, flags: list[dict]) -> None:
    context_dir = root / "results" / "_context"
    context_dir.mkdir(parents=True, exist_ok=True)
    _write_json_packet(context_dir / "latest-flags.json", {"flags": flags})
    _write_json_packet(
        context_dir / "latest-summary.json", {"generated_at": NOW.isoformat(), "latest_packets": []}
    )


def _record_strict_hold_board(tmp_path: Path, *, symbol: str = "TSM") -> dict:
    """Create a real Task 1 ledger decision and its exact BOARD projection."""
    evidence_root = tmp_path / "results"
    supervisor_path = evidence_root / "hourly_supervisor" / "hourly.json"
    supervisor = {
        "generated_at": NOW.isoformat(),
        "decision": "loss-review",
        "evidence": {
            "loss_exit_review": {
                "symbol": symbol,
                "decision_id": f"loss-review-{symbol.lower()}-1",
                "allowed": False,
                "policy_rule_exit": False,
                "allowed_exit_reason": "",
                "allowed_exit_reason_source": "",
                "blockers": ["company evidence incomplete"],
                "blocked_reasons": ["company evidence incomplete"],
                "confidence": "0.00",
                "evidence_generated_at": NOW.isoformat(),
            }
        },
    }
    _write_json_packet(supervisor_path, supervisor)
    loss_path = evidence_root / "loss_review_evidence" / "loss.json"
    loss = {
        "schema_version": "1.0.0",
        "packet_id": f"loss-evidence-{symbol.lower()}-1",
        "generated_at": NOW.isoformat(),
        "source_name": "loss_review_evidence",
        "evidence_type": "loss_review_evidence",
        "subject": symbol,
        "symbol": symbol,
        "analysis_only": True,
        "execution_authority": "none",
        "can_submit_orders": False,
        "payload": {
            "symbol": symbol,
            "supervisor_packet_path": supervisor_path.relative_to(evidence_root).as_posix(),
            "supervisor_decision_id": supervisor["evidence"]["loss_exit_review"]["decision_id"],
            "remaining_blockers": ["company evidence incomplete"],
            "accepted_sources": [],
            "advisory_analysis": {"requires_board_decision": True},
        },
    }
    _write_json_packet(loss_path, loss)
    recorded = record_autonomous_loss_board_decision(
        supervisor_packet_path=supervisor_path,
        loss_evidence_packet_path=loss_path,
        source_revision="1" * 40,
        ledger_root=tmp_path / "state" / "decision_ledger",
        evidence_root=evidence_root,
        now=NOW,
    )
    decision = recorded.decision
    decision_projection = {
        "decision": decision.decision,
        "decision_id": decision.decision_id,
        "ledger_packet_id": recorded.packet.packet_id,
        "symbol": decision.symbol,
        "supervisor_decision_id": decision.supervisor_decision_id,
        "source_revision": decision.source_revision,
        "trade_decision_resolved": decision.trade_decision_resolved,
        "exit_allowed": decision.exit_allowed,
        "analysis_only": decision.analysis_only,
        "execution_authority": decision.execution_authority,
        "can_submit_orders": decision.can_submit_orders,
        "recommendation": recorded.packet.recommendation,
    }
    decision_ref, supervisor_ref, loss_ref = recorded.packet.evidence_refs
    decision_projection.update(
        {
            "decision_evidence": {
                "path": decision_ref.path,
                "sha256": decision_ref.sha256,
                "size_bytes": decision_ref.size_bytes,
            },
            "supervisor_packet": {
                "path": supervisor_ref.path,
                "sha256": supervisor_ref.sha256,
                "size_bytes": supervisor_ref.size_bytes,
            },
            "loss_evidence_packet": {
                "packet_id": loss["packet_id"],
                "path": loss_ref.path,
                "sha256": loss_ref.sha256,
                "size_bytes": loss_ref.size_bytes,
            },
            "accepted_sources_sha256": hashlib.sha256(
                json.dumps([], sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest(),
            "accepted_source_count": 0,
        }
    )
    board = {
        "kind": "execution_board_review",
        "schema_version": 1,
        "generated_at": NOW.isoformat(),
        "analysis_only": True,
        "can_submit_orders": False,
        "execution_authority": "none",
        "autonomous_loss_decision": decision_projection,
        "loss_review_evidence": {
            "symbol": symbol,
            "supervisor_packet_path": decision.supervisor_packet.path,
            "raw_packet_path": decision.loss_evidence_packet.path,
            "next_action": recorded.packet.recommendation,
            "source_binding": {
                "matched": True,
                "bindings": {
                    "supervisor": {
                        "path": decision.supervisor_packet.path,
                        "sha256": decision.supervisor_packet.sha256,
                        "size_bytes": decision.supervisor_packet.size_bytes,
                        "decision_id": decision.supervisor_decision_id,
                        "symbol": symbol,
                    },
                    "raw_loss": {
                        "path": decision.loss_evidence_packet.path,
                        "sha256": decision.loss_evidence_packet.sha256,
                        "size_bytes": decision.loss_evidence_packet.size_bytes,
                        "packet_id": loss["packet_id"],
                        "symbol": symbol,
                        "source_revision": decision.source_revision,
                    },
                },
            },
        },
    }
    board_path = evidence_root / "execution_board" / "latest.json"
    _write_json_packet(board_path, board)
    return {"board_path": board_path, "board": board, "decision": decision}


def _write_bound_board_compact(tmp_path: Path, fixture: dict) -> Path:
    """Write the production scalar-only sidecar bound to immutable Board bytes."""
    full_path = (
        tmp_path
        / "results"
        / "execution_board"
        / "execution-board-review-fixture-20260813-120000.json"
    )
    full_bytes = fixture["board_path"].read_bytes()
    full_path.write_bytes(full_bytes)
    return _write_json_packet(
        tmp_path / "results" / "execution_board" / "latest-compact.json",
        {
            "schema": "autonomous_loss_board_sidecar_v1",
            "generated_at": NOW.isoformat(),
            "raw_packet_path": str(full_path.relative_to(tmp_path)),
            "raw_packet_sha256": hashlib.sha256(full_bytes).hexdigest(),
            "symbol": fixture["decision"].symbol,
            "decision": fixture["decision"].decision,
            "decision_id": fixture["decision"].decision_id,
            "ledger_packet_id": fixture["board"]["autonomous_loss_decision"]["ledger_packet_id"],
            "supervisor_decision_id": fixture["decision"].supervisor_decision_id,
            "source_revision": fixture["decision"].source_revision,
            "trade_decision_resolved": True,
            "exit_allowed": fixture["decision"].exit_allowed,
            "analysis_only": True,
            "can_submit_orders": False,
            "execution_authority": "none",
            "accepted_source_count": 0,
            "accepted_sources_sha256": hashlib.sha256(b"[]").hexdigest(),
        },
    )


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
        "source_identity": "hourly_supervisor.loss_exit_review",
    }
    advisory = {
        "symbol": symbol,
        "review_allowed_after_refresh": True,
        "authority_source": "pre_registered_policy_rule",
        "requires_board_decision": False,
        "decision_owner": "execution_operator",
        "loss_exit_candidate": {
            "allowed_exit_reason_candidate": "policy_stop_floor",
            "allowed_exit_reason_source": "pre-registered exit policy rule",
            "confidence": None,
            "confidence_tier": "pre_registered_policy",
            "reason_summary": "The pre-registered rule fired.",
            "drivers": [
                "pre-registered exit rule remains authoritative: policy_stop_floor"
            ],
            "approval_effect": "preserves_pre_registered_policy_approval",
            "requires_board_decision": False,
            "requires_tradeable_session": True,
            "can_submit_orders": False,
        },
        "forbidden_effects": [
            "create_trade_intent",
            "size_position",
            "submit_order",
            "promote_sleeve",
            "waive_live_gate",
            "mark_loss_exit_allowed",
        ],
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
            "next_action": "pre_registered_policy_approval_preserved",
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
        "promoted": ["pullback-support"],
        "demoted": [],
        "issues_by_sleeve": {"pullback-support": []},
        "state_path": "/tmp/promotion-state.json",
        "report_path": "/tmp/paper-tournament.json",
        "arm_live": True,
        "ci_green": True,
        "can_submit_orders": False,
        "execution_authority": "none",
        "state": {
            "schema_version": "1.1.0",
            "generated_at": NOW.isoformat(),
            "source": {
                "kind": "paper_tournament_sync",
                "tournament_id": "tournament-20260718",
                "report_generated_at": NOW.isoformat(),
                "arm_live": True,
                "ci_green": True,
            },
            "sleeves": {
                "pullback-support": {
                    "stage": "tiny_live_eligible",
                    "live_enabled": True,
                    "ci_green": True,
                    "shadow_confirmed": True,
                    "preregistered": True,
                    "benchmark_gate_passed": True,
                    "cost_gate_passed": True,
                    "recent_alpha_gate_passed": True,
                    "capacity_gate_passed": True,
                    "validation_report_ref": "results/paper_strategy_tournament/latest.json",
                    "risk_envelope_ref": "config/risk_envelope.yaml",
                    "promoted_at": NOW.isoformat(),
                    "metrics": {
                        "benchmark_excess_return": "3.53",
                        "cost_adjusted_alpha": "3.53",
                        "recent_alpha": "3.53",
                        "capacity_usd": "10353.62",
                        "requested_tiny_live_tranche_usd": "25.00",
                    },
                    "issues": [],
                    "source": {
                        "kind": "paper_tournament",
                        "tournament_id": "tournament-20260718",
                        "report_generated_at": NOW.isoformat(),
                        "candidate_reason": "positive paper strategy",
                    },
                    "evidence_metrics": {
                        "total_return": "353.62",
                        "total_return_pct": "3.53",
                        "max_drawdown_pct": "-1.91",
                        "win_rate_pct": "71.42",
                        "tracked_days": 14,
                    },
                }
            },
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
        "open_orders": [
            {
                "id": "broker-open-nflx-1",
                "client_order_id": "open-nflx-1",
                "symbol": symbol,
                "side": "sell",
                "type": "limit",
                "time_in_force": "day",
                "qty": "1",
                "limit_price": "100",
                "status": "accepted",
                "submitted_at": NOW.isoformat(),
                "updated_at": NOW.isoformat(),
            }
        ],
        "recent_fills": [
            {
                "id": "broker-fill-nflx-1",
                "client_order_id": "fill-nflx-1",
                "symbol": symbol,
                "side": "buy",
                "type": "market",
                "time_in_force": "day",
                "qty": "1",
                "status": "filled",
                "filled_qty": "1",
                "filled_avg_price": "100",
                "submitted_at": NOW.isoformat(),
                "updated_at": NOW.isoformat(),
            }
        ],
        "checked_client_order_ids": ["open-nflx-1", "fill-nflx-1"],
        "issues": [],
        "broker_write_calls": 0,
    }


def test_recovery_recomputes_exact_manual_exit_suppression_and_rejects_label_only(tmp_path):
    source_path = tmp_path / "source.json"
    source_path.write_text(json.dumps({
        "actions": [{
            "symbol": "NFLX", "side": "buy", "account": "live",
            "idempotency_key": "autonomous-buy",
        }],
        "submitted": [{
            "symbol": "NFLX", "side": "buy", "client_order_id": "autonomous-buy",
        }],
    }), encoding="utf-8")
    source_sha = hashlib.sha256(source_path.read_bytes()).hexdigest()
    buy_fill = {
        "client_order_id": "autonomous-buy", "symbol": "NFLX",
        "side": "buy", "status": "filled", "filled_qty": "1",
        "filled_avg_price": "10", "submitted_at": NOW.isoformat(),
        "updated_at": NOW.isoformat(),
    }
    manual_fill = {
        "client_order_id": "owner-sell", "symbol": "NFLX",
        "side": "sell", "status": "filled", "filled_qty": "1",
        "filled_avg_price": "9.5", "submitted_at": NOW.isoformat(),
        "updated_at": NOW.isoformat(),
    }
    attestation_payload = build_owner_manual_action_attribution(
        source_packet_path=source_path,
        reconciliation_packet={
            "symbol": "NFLX", "recent_fills": [manual_fill, buy_fill]
        },
        originating_client_order_id="autonomous-buy",
        manual_fill_client_order_id="owner-sell",
        attested_at=NOW.isoformat(),
    )
    attestation_path = tmp_path / "owner.json"
    write_owner_manual_action_attribution(attestation_path, attestation_payload)
    attestation_sha = hashlib.sha256(attestation_path.read_bytes()).hexdigest()
    resolution_id = str(attestation_payload["resolution_id"])
    suppression_key = replay_suppression_key(
        attribution_sha256=attestation_sha,
        resolution_id=resolution_id,
        symbol="NFLX",
        originating_client_order_id="autonomous-buy",
        resolved_by_client_order_id="owner-sell",
        filled_qty="1",
        source_packet_sha256=source_sha,
    )
    packet = {
        **_reconciliation_source_packet(),
        "schema_version": "tradingagents.recovery_phase.v1",
        "source_schema_version": 1,
        "source_identity": "alpaca_symbol_incident_reconciliation",
        "open_orders": [],
        "recent_fills": [manual_fill, buy_fill],
        "checked_client_order_ids": ["autonomous-buy", "owner-sell"],
        "resolved_external_actions": [{
            "resolution_id": resolution_id,
            "attestation_path": str(attestation_path.resolve()),
            "attestation_sha256": attestation_sha,
            "source_packet_path": str(source_path.resolve()),
            "source_packet_sha256": source_sha,
            "symbol": "NFLX", "filled_qty": "1",
            "originating_client_order_id": "autonomous-buy",
            "resolved_by_client_order_id": "owner-sell",
        }],
        "replay_suppressions": [{
            "scope": "exact_incident_exit_chain",
            "suppression_key": suppression_key,
            "resolution_id": resolution_id,
            "attestation_sha256": attestation_sha,
            "source_packet_sha256": source_sha,
            "symbol": "NFLX", "filled_qty": "1",
            "originating_client_order_id": "autonomous-buy",
            "resolved_by_client_order_id": "owner-sell",
            "active": True,
        }],
    }

    assert self_heal_module._valid_reconciliation_phase_packet(packet, BINDINGS)
    for mutate in (
        lambda candidate: candidate["replay_suppressions"][0].update(
            {"suppression_key": "b" * 64}
        ),
        lambda candidate: candidate["resolved_external_actions"][0].update(
            {"attestation_sha256": "c" * 64}
        ),
        lambda candidate: candidate.update({"replay_suppressions": []}),
        lambda candidate: candidate["position"].update({"qty": "1"}),
    ):
        candidate = json.loads(json.dumps(packet))
        mutate(candidate)
        assert not self_heal_module._valid_reconciliation_phase_packet(
            candidate, BINDINGS
        )
    attestation_path.write_text('{"owner":"forged"}\n', encoding="utf-8")
    forged = json.loads(json.dumps(packet))
    forged_sha = hashlib.sha256(attestation_path.read_bytes()).hexdigest()
    forged["resolved_external_actions"][0]["attestation_sha256"] = forged_sha
    forged["replay_suppressions"][0]["attestation_sha256"] = forged_sha
    forged["replay_suppressions"][0]["suppression_key"] = replay_suppression_key(
        attribution_sha256=forged_sha,
        resolution_id=resolution_id,
        symbol="NFLX",
        originating_client_order_id="autonomous-buy",
        resolved_by_client_order_id="owner-sell",
        filled_qty="1",
        source_packet_sha256=source_sha,
    )
    assert not self_heal_module._valid_reconciliation_phase_packet(
        forged, BINDINGS
    )


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
            "passing_tests": list(RECOVERY_FOCUSED_TESTS),
            "verifier_run_id": "verify-nflx-1",
            "verifier_role_id": "integrity_verifier",
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
                run_root = Path(arguments["run_root"])
                staging_dir = Path(arguments["staging_dir"])
                packet_dir = run_root / "packets"
                input_dir = run_root / "test-promotion-inputs"
                input_dir.mkdir(parents=True, exist_ok=True)
                report_path = input_dir / "paper-tournament.json"
                envelope_path = input_dir / "risk-envelope.yaml"
                canonical_path = input_dir / "promotion-state.json"
                report_path.write_text(
                    json.dumps(_current_like_tournament_report()),
                    encoding="utf-8",
                )
                envelope_path.write_text(
                    "tiny_live_tranche_usd: 25\n", encoding="utf-8"
                )
                if not canonical_path.exists():
                    canonical_path.write_text(
                        json.dumps({"schema_version": "1.0.0", "sleeves": {}}),
                        encoding="utf-8",
                    )
                focused_record = arguments["phase_outputs"]["focused_verify"]
                reconciliation_record = arguments["phase_outputs"]["reconcile"]
                focused = json.loads(
                    Path(focused_record["path"]).read_text(encoding="utf-8")
                )
                before_sha256 = hashlib.sha256(
                    canonical_path.read_bytes()
                ).hexdigest()
                candidate = _current_like_tournament_report()[
                    "live_strategy_candidate"
                ]
                commit_seed = {
                    "schema_version": "tradingagents.promotion_recovery_commit.v1",
                    "incident_id": arguments["bindings"]["incident_id"],
                    "recovery_run_id": arguments["recovery_run_id"],
                    "source_revision": arguments["bindings"]["source_revision"],
                    "focused_path": str(Path(focused_record["path"]).resolve()),
                    "focused_sha256": focused_record["sha256"],
                    "verifier_run_id": focused["verifier_run_id"],
                    "verifier_role_id": focused["verifier_role_id"],
                    "reconciliation_path": str(
                        Path(reconciliation_record["path"]).resolve()
                    ),
                    "reconciliation_sha256": reconciliation_record["sha256"],
                    "report_path": str(report_path.resolve()),
                    "report_sha256": hashlib.sha256(
                        report_path.read_bytes()
                    ).hexdigest(),
                    "envelope_path": str(envelope_path.resolve()),
                    "envelope_sha256": hashlib.sha256(
                        envelope_path.read_bytes()
                    ).hexdigest(),
                    "canonical_path": str(canonical_path.resolve()),
                    "canonical_before_sha256": before_sha256,
                    "candidate_payload_sha256": hashlib.sha256(
                        (
                            json.dumps(
                                candidate,
                                sort_keys=True,
                                separators=(",", ":"),
                                ensure_ascii=True,
                            )
                            + "\n"
                        ).encode()
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
                        ).encode()
                    ).hexdigest(),
                }
                packet["state"]["source"].update(
                    {"canonical_input_sha256": before_sha256}
                )
                raw_stage_sha256 = hashlib.sha256(
                    json.dumps(packet["state"], indent=2).encode("utf-8")
                ).hexdigest()
                packet["state"]["source"]["recovery_commit"] = recovery_commit
                stage_path = staging_dir / "promotion_state.json"
                stage_path.parent.mkdir(parents=True, exist_ok=True)
                stage_text = json.dumps(packet["state"], indent=2, sort_keys=True)
                stage_path.write_text(stage_text, encoding="utf-8")
                canonical_path.write_text(stage_text, encoding="utf-8")
                staged_sha256 = hashlib.sha256(stage_path.read_bytes()).hexdigest()
                prepare_path = packet_dir / "promotion_prepare.json"
                prepare = {
                    "schema_version": "tradingagents.promotion_prepare.v1",
                    "kind": "promotion_commit_prepare",
                    "recovery_commit": recovery_commit,
                    "stage_path": str(stage_path.resolve()),
                    "generated_at": generated_at,
                    "arm_live": True,
                    "ci_green": True,
                    "expected_raw_stage_sha256": raw_stage_sha256,
                    "expected_stage_sha256": staged_sha256,
                    "can_submit_orders": False,
                    "execution_authority": "none",
                }
                prepare_path.write_text(
                    json.dumps(
                        prepare,
                        sort_keys=True,
                        separators=(",", ":"),
                        ensure_ascii=True,
                    )
                    + "\n",
                    encoding="utf-8",
                )
                prepare_record = {
                    "path": str(prepare_path.resolve()),
                    "sha256": hashlib.sha256(prepare_path.read_bytes()).hexdigest(),
                }
                intent = {
                    "commit_id": recovery_commit["commit_id"],
                    "prepare_path": prepare_record["path"],
                    "prepare_sha256": prepare_record["sha256"],
                    "staged_path": str(stage_path.resolve()),
                    "staged_sha256": staged_sha256,
                    "canonical_path": str(canonical_path.resolve()),
                    "canonical_before_sha256": before_sha256,
                }
                stage_request = {
                    "commit_id": recovery_commit["commit_id"],
                    "prepare_path": prepare_record["path"],
                    "prepare_sha256": prepare_record["sha256"],
                    "stage_path": str(stage_path.resolve()),
                    "expected_raw_stage_sha256": raw_stage_sha256,
                    "expected_stage_sha256": staged_sha256,
                    "generated_at": generated_at,
                    "canonical_path": str(canonical_path.resolve()),
                    "canonical_before_sha256": before_sha256,
                    "report_sha256": recovery_commit["report_sha256"],
                    "envelope_sha256": recovery_commit["envelope_sha256"],
                    "focused_sha256": recovery_commit["focused_sha256"],
                    "reconciliation_sha256": recovery_commit[
                        "reconciliation_sha256"
                    ],
                    "arm_live": True,
                    "ci_green": True,
                }
                arguments["_persist_promotion_stage_request"](
                    stage_request
                )
                arguments["_persist_promotion_commit_intent"](intent)
                receipt_path = packet_dir / "promotion_commit.json"
                receipt = {
                    "schema_version": "tradingagents.promotion_commit.v1",
                    "kind": "verified_promotion_commit",
                    "recovery_commit": recovery_commit,
                    "prepare_path": prepare_record["path"],
                    "prepare_sha256": prepare_record["sha256"],
                    "staged_path": str(stage_path.resolve()),
                    "staged_sha256": staged_sha256,
                    "canonical_path": str(canonical_path.resolve()),
                    "canonical_before_sha256": before_sha256,
                    "canonical_after_sha256": staged_sha256,
                    "can_submit_orders": False,
                    "execution_authority": "none",
                }
                receipt_path.write_text(
                    json.dumps(
                        receipt,
                        sort_keys=True,
                        separators=(",", ":"),
                        ensure_ascii=True,
                    )
                    + "\n",
                    encoding="utf-8",
                )
                receipt_record = {
                    "path": str(receipt_path.resolve()),
                    "sha256": hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
                }
                packet.update(
                    {
                        "state_path": str(canonical_path.resolve()),
                        "canonical_state_path": str(canonical_path.resolve()),
                        "report_path": str(report_path.resolve()),
                        "staged_state_path": str(stage_path.resolve()),
                        "staged_state_sha256": staged_sha256,
                        "canonical_after_sha256": staged_sha256,
                        "recovery_commit": recovery_commit,
                        "promotion_prepare": prepare_record,
                        "promotion_commit": receipt_record,
                        "promotion_commit_intent": intent,
                        "promotion_stage_request": stage_request,
                    }
                )
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


def _current_like_tournament_report() -> dict:
    return {
        "generated_at": NOW.isoformat(),
        "tournament_id": "tournament-20260718",
        "rankings": [
            {
                "strategy_id": "pullback-support",
                "name": "pullback-support",
                "equity": "10353.62",
                "total_return": "353.62",
                "total_return_pct": "3.53",
                "max_drawdown_pct": "-1.91",
                "win_rate_pct": "71.42",
                "tracked_days": 14,
            }
        ],
        "live_strategy_candidate": {
            "status": "candidate",
            "strategy_id": "pullback-support",
            "reason": "best positive paper strategy after 14 tracked day(s)",
        },
    }


def _production_recovery_harness(
    tmp_path: Path, *, fail_phase: str | None = None
) -> tuple[dict, Path, list[list[str]], object]:
    evidence = _loss_review_source_packet(
        account="paper",
        packet_path=str(tmp_path / "results" / "loss_review_evidence" / "latest.json"),
        hourly_packet_path="results/hourly_supervisor/hourly-supervisor-nflx.json",
    )
    supervisor_path = tmp_path / "results" / "hourly_supervisor" / "supervisor.json"
    advisory_path = tmp_path / "results" / "hourly_supervisor" / "advisory.json"
    hourly_dir = tmp_path / "results" / "hourly_supervisor"
    report_path = tmp_path / "results" / "paper_strategy_tournament" / "latest.json"
    state_path = tmp_path / "results" / "policy" / "promotion_state.json"
    envelope_path = tmp_path / "config" / "risk_envelope.yaml"
    reconciliation_path = tmp_path / "results" / "alpaca_reconciliation" / "latest.json"
    for path, content in (
        (
            supervisor_path,
            json.dumps(evidence["payload"]["supervisor_review_authority"]),
        ),
        (advisory_path, json.dumps(evidence["payload"]["advisory_analysis"])),
        (report_path, json.dumps(_current_like_tournament_report())),
        (state_path, json.dumps(_promotion_source_packet()["state"], indent=2)),
        (
            envelope_path,
            "\n".join(
                (
                    "account_max_capital_at_risk_usd: 250.00",
                    "per_name_cap_usd: 50.00",
                    "per_sector_cap_pct: 0.20",
                    "aggregate_beta_cap: 1.25",
                    "daily_loss_halt_usd: 25.00",
                    "max_drawdown_halt_pct: 0.05",
                    "tiny_live_tranche_usd: 25.00",
                    "tiny_live_max_loss_usd: 5.00",
                    "new_sleeve_auto_promote: false",
                    "alert_email: ops@example.com",
                )
            ),
        ),
        (
            reconciliation_path,
            json.dumps(
                {
                    "actions": [
                        {
                            "symbol": "NFLX",
                            "side": "buy",
                            "account": "live",
                            "idempotency_key": "open-nflx-1",
                        }
                    ],
                    "submitted": [
                        {
                            "client_order_id": "open-nflx-1",
                            "symbol": "NFLX",
                            "side": "buy",
                            "type": "limit",
                            "qty": "1",
                            "limit_price": "100",
                            "status": "accepted",
                        }
                    ],
                }
            ),
        ),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    invocations: list[list[str]] = []

    class BrokerSpy:
        def __init__(self):
            self.write_calls: list[tuple] = []
            self.read_calls: list[tuple] = []
            self.positions = [
                {
                    "symbol": "NFLX",
                    "qty": "1",
                    "notional": "100",
                    "market_value": "100",
                    "avg_entry_price": "100",
                }
            ]
            self.orders = [
                {
                    "id": "broker-open-nflx-1",
                    "client_order_id": "open-nflx-1",
                    "symbol": "NFLX",
                    "side": "buy",
                    "type": "limit",
                    "time_in_force": "day",
                    "qty": "1",
                    "limit_price": "100",
                    "status": "accepted",
                    "filled_qty": "0",
                    "submitted_at": NOW.isoformat(),
                    "updated_at": NOW.isoformat(),
                }
            ]

        def list_positions(self):
            self.read_calls.append(("list_positions",))
            return self.positions

        def list_orders(self, status="all"):
            self.read_calls.append(("list_orders", status))
            return self.orders

        def get_order_by_client_order_id(self, client_order_id):
            self.read_calls.append(("get_order_by_client_order_id", client_order_id))
            return next(
                (
                    order
                    for order in self.orders
                    if order["client_order_id"] == client_order_id
                ),
                None,
            )

        def _reject_write(self, name, args, kwargs):
            self.write_calls.append((name, args, kwargs))
            raise AssertionError("recovery reconciliation attempted a broker write")

        def submit_order(self, *args, **kwargs):
            return self._reject_write("submit", args, kwargs)

        def cancel_order(self, *args, **kwargs):
            return self._reject_write("cancel", args, kwargs)

        def replace_order(self, *args, **kwargs):
            return self._reject_write("replace", args, kwargs)

        def close_position(self, *args, **kwargs):
            return self._reject_write("close_position", args, kwargs)

    broker_spy = BrokerSpy()

    class Result:
        def __init__(self, *, stdout: str = "", stderr: str = "", returncode: int = 0):
            self.stdout = stdout
            self.stderr = stderr
            self.returncode = returncode

    def runner(argv, **_kwargs):
        command = list(argv)
        invocations.append(command)
        if command[:3] == ["git", "rev-parse", "HEAD"]:
            return Result(stdout="source-revision\n")
        if "loss-review-evidence" in command:
            return Result(stdout=json.dumps(evidence))
        if "reconcile-symbol-incident" in command:
            if fail_phase == "reconcile":
                return Result(stderr="read-only reconciliation failed", returncode=1)
            reconciliation = alpaca_reconciliation.reconcile_symbol_incident(
                symbol="NFLX",
                packet_paths=[reconciliation_path],
                live_client=broker_spy,
                expected_qty=Decimal("1"),
            )
            return Result(
                stdout=json.dumps(
                    {
                        "schema_version": 1,
                        "kind": "symbol_broker_reconciliation",
                        "generated_at": NOW.isoformat(),
                        "read_only": True,
                        "analysis_only": True,
                        "can_submit_orders": False,
                        "execution_authority": "none",
                        **asdict(reconciliation),
                    }
                )
            )
        if "pytest" in command:
            if fail_phase == "focused_verify":
                return Result(stderr="focused verification failed", returncode=1)
            return Result(stdout="passed")
        if "sync-promotion" in command:
            arm_live = "--arm-live" in command and "--no-arm-live" not in command
            ci_green = "--ci-green" in command and "--no-ci-green" not in command
            promotion_now = (
                dt.datetime.fromisoformat(
                    command[command.index("--generated-at") + 1]
                )
                if "--generated-at" in command
                else NOW
            )
            canonical_input_path = command[command.index("--state-path") + 1]
            output_state_path = (
                command[command.index("--output-state-path") + 1]
                if "--output-state-path" in command
                else canonical_input_path
            )
            result = sync_promotion_state_file(
                command[command.index("--report-path") + 1],
                canonical_input_path,
                output_state_path=output_state_path,
                tiny_live_tranche_usd=Decimal("25.00"),
                arm_live=arm_live,
                ci_green=ci_green,
                now=promotion_now,
            )
            if fail_phase == "promotion_after_stage_write":
                raise SystemExit("promotion state written before adapter return")
            return Result(
                stdout=json.dumps(
                    {
                        "summary": result.summary,
                        "promoted": result.promoted,
                        "demoted": result.demoted,
                        "issues_by_sleeve": result.issues_by_sleeve,
                        "state_path": output_state_path,
                        "canonical_state_path": canonical_input_path,
                        "report_path": command[command.index("--report-path") + 1],
                        "arm_live": arm_live,
                        "ci_green": ci_green,
                        "can_submit_orders": False,
                        "execution_authority": "none",
                        "state": result.state,
                    }
                )
            )
        raise AssertionError(command)

    context = {
        "symbol": "NFLX",
        "broker_account": "paper",
        "environment": "test",
        "source_revision": "source-revision",
        "supervisor_path": str(supervisor_path),
        "advisory_path": str(advisory_path),
        "hourly_dir": str(hourly_dir),
        "report_path": str(report_path),
        "envelope_path": str(envelope_path),
        "promotion_state_path": str(state_path),
        "reconciliation_packet_paths": [str(reconciliation_path)],
        "supervisor_record": evidence["payload"]["supervisor_review_authority"],
        "advisory_record": evidence["payload"]["advisory_analysis"],
    }
    request = build_production_recovery_request(
        {
            "label": "policy_rule_conflict",
            "reason": "approval_conflict",
            "symbol": "NFLX",
            "recovery_context": context,
        },
        repo_root=tmp_path,
        command_runner=runner,
    )
    assert request["ready"] is True
    return request, state_path, invocations, broker_spy


def test_recovery_phase_order_proves_before_mutating_promotion():
    assert RECOVERY_PHASES == (
        "resolve_authority",
        "regenerate_evidence",
        "reconcile",
        "focused_verify",
        "sync_promotion",
        "ready_incident",
        "manifest",
        "rearm",
    )


def test_production_promotion_adapter_requires_prior_focused_proof(tmp_path):
    request, state_path, invocations, _broker_spy = _production_recovery_harness(
        tmp_path
    )
    original = state_path.read_bytes()

    result = request["adapters"]["sync_promotion"](
        {"phase": "sync_promotion", "phase_outputs": {}}
    )

    assert result["outcome"] == "failed"
    assert state_path.read_bytes() == original
    assert not any("sync-promotion" in argv for argv in invocations)


def test_production_focused_adapter_uses_the_canonical_integrity_owner(
    tmp_path,
    monkeypatch,
):
    request, _state_path, _invocations, _broker_spy = (
        _production_recovery_harness(tmp_path)
    )
    calls: list[ActionClass] = []

    def record(action):
        verdict = real_authority_for(action)
        calls.append(verdict.action)
        return verdict

    monkeypatch.setattr(self_heal_module, "authority_for", record, raising=False)

    result = request["adapters"]["focused_verify"](
        {"phase": "focused_verify"}
    )

    assert result["packet"]["verifier_role_id"] == "integrity_verifier"
    assert calls == [ActionClass.VERIFY]


def test_promotion_validation_requires_hash_bound_focused_proof(tmp_path):
    calls: list[str] = []
    result = _run(tmp_path, calls, idempotency_key="delivery-1")
    assert result["status"] == "monitoring"
    state_path = (
        tmp_path
        / "results"
        / "control_plane"
        / "recovery"
        / BINDINGS["incident_id"]
        / "state.json"
    )
    state = json.loads(state_path.read_text(encoding="utf-8"))
    promotion_path = Path(state["phase_outputs"]["sync_promotion"]["path"])
    validation_kwargs = {
        "state": state,
        "control_path": tmp_path / "live_control.json",
        "now": NOW,
        "idempotency_key": "delivery-1",
    }
    assert _valid_phase_packet(
        promotion_path,
        "sync_promotion",
        BINDINGS,
        phase_outputs=state["phase_outputs"],
        **validation_kwargs,
    )

    missing = dict(state["phase_outputs"])
    missing.pop("focused_verify")
    assert not _valid_phase_packet(
        promotion_path,
        "sync_promotion",
        BINDINGS,
        phase_outputs=missing,
        **validation_kwargs,
    )

    bad_digest = json.loads(json.dumps(state["phase_outputs"]))
    bad_digest["focused_verify"]["sha256"] = "0" * 64
    assert not _valid_phase_packet(
        promotion_path,
        "sync_promotion",
        BINDINGS,
        phase_outputs=bad_digest,
        **validation_kwargs,
    )

    focused_path = Path(state["phase_outputs"]["focused_verify"]["path"])
    original_focused = focused_path.read_text(encoding="utf-8")
    for field, value in (
        ("recovery_run_id", "other-recovery"),
        ("source_revision", "other-revision"),
        ("verifier_run_id", "repair-nflx-1"),
    ):
        focused = json.loads(original_focused)
        focused[field] = value
        focused_path.write_text(json.dumps(focused), encoding="utf-8")
        assert not _valid_phase_packet(
            promotion_path,
            "sync_promotion",
            BINDINGS,
            phase_outputs=state["phase_outputs"],
            **validation_kwargs,
        ), field
    focused_path.write_text(original_focused, encoding="utf-8")


def test_focused_phase_rejects_a_distinct_but_noncanonical_verifier_role(
    tmp_path,
):
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
    focused_path = Path(state["phase_outputs"]["focused_verify"]["path"])
    focused = json.loads(focused_path.read_text(encoding="utf-8"))
    focused["verifier_role_id"] = "audit_team"
    focused_path.write_text(json.dumps(focused), encoding="utf-8")

    assert not _valid_phase_packet(
        focused_path,
        "focused_verify",
        BINDINGS,
        state=state,
        phase_outputs=state["phase_outputs"],
        control_path=tmp_path / "live_control.json",
        now=NOW,
        idempotency_key="delivery-1",
    )


def test_ready_incident_rejects_a_distinct_but_noncanonical_repairer_role(
    tmp_path,
):
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
    ready_path = Path(state["phase_outputs"]["ready_incident"]["path"])
    ready = json.loads(ready_path.read_text(encoding="utf-8"))
    ready["repairer_role_id"] = "repair_team"
    ready["owner_role"] = "repair_team"
    ready_path.write_text(json.dumps(ready), encoding="utf-8")

    assert not _valid_phase_packet(
        ready_path,
        "ready_incident",
        BINDINGS,
        state=state,
        phase_outputs=state["phase_outputs"],
        control_path=tmp_path / "live_control.json",
        now=NOW,
        idempotency_key="delivery-1",
    )


def test_coordinator_authority_denial_preserves_frozen_control_and_no_receipt(
    tmp_path,
    monkeypatch,
):
    control_path = _control(tmp_path)
    control_before = control_path.read_bytes()
    authority_calls: list[ActionClass] = []

    def deny_issue(action):
        verdict = real_authority_for(action)
        authority_calls.append(verdict.action)
        if verdict.action is ActionClass.REARM_ISSUE:
            return type(verdict)(
                action=verdict.action,
                allowed=False,
                human_required=verdict.human_required,
                owner_role=verdict.owner_role,
                reason="test denial",
            )
        return verdict

    monkeypatch.setattr(
        self_heal_module,
        "authority_for",
        deny_issue,
        raising=False,
    )

    with pytest.raises(ValueError, match="authority"):
        _run(tmp_path, [])

    assert authority_calls == [
        ActionClass.REARM_REQUEST,
        ActionClass.REARM_ISSUE,
    ]
    assert control_path.read_bytes() == control_before
    assert not (tmp_path / "receipts").exists()


@pytest.mark.parametrize("fail_phase", ["reconcile", "focused_verify"])
def test_failed_immutable_proof_leaves_promotion_state_byte_identical(
    tmp_path, fail_phase
):
    request, state_path, invocations, broker_spy = _production_recovery_harness(
        tmp_path, fail_phase=fail_phase
    )
    original = state_path.read_bytes()
    coordinator_args = dict(request)
    coordinator_args.pop("ready")

    result = coordinate_verified_recovery(
        **coordinator_args,
        control_path=_control(tmp_path),
        receipt_dir=tmp_path / "receipts",
        recovery_root=tmp_path / "results" / "control_plane" / "recovery",
        now=NOW,
    )

    assert result["status"] == "frozen"
    assert result["phase"] == fail_phase
    assert state_path.read_bytes() == original
    assert not any("sync-promotion" in argv for argv in invocations)
    assert broker_spy.write_calls == []
    control, _issues = load_live_control_state(tmp_path / "live_control.json", now=NOW)
    assert control["frozen"] is True


def test_production_recovery_promotes_only_after_focused_proof(tmp_path):
    request, state_path, invocations, broker_spy = _production_recovery_harness(
        tmp_path
    )
    coordinator_args = dict(request)
    coordinator_args.pop("ready")

    result = coordinate_verified_recovery(
        **coordinator_args,
        control_path=_control(tmp_path),
        receipt_dir=tmp_path / "receipts",
        recovery_root=tmp_path / "results" / "control_plane" / "recovery",
        now=NOW,
    )

    assert result["status"] == "monitoring"
    reconcile_index = next(
        index
        for index, argv in enumerate(invocations)
        if "reconcile-symbol-incident" in argv
    )
    focused_index = next(
        index for index, argv in enumerate(invocations) if "pytest" in argv
    )
    promotion_indexes = [
        index for index, argv in enumerate(invocations) if "sync-promotion" in argv
    ]
    assert reconcile_index < focused_index < promotion_indexes[0]
    assert len(promotion_indexes) == 1
    promotion_argv = invocations[promotion_indexes[0]]
    assert "--arm-live" in promotion_argv
    assert "--ci-green" in promotion_argv
    assert "--no-arm-live" not in promotion_argv
    assert "--no-ci-green" not in promotion_argv
    assert set(RECOVERY_FOCUSED_TESTS).issubset(invocations[focused_index])
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["source"]["arm_live"] is True
    assert state["source"]["ci_green"] is True
    assert state["sleeves"]["pullback-support"]["live_enabled"] is True
    reconciliation_packet = json.loads(
        (
            tmp_path
            / "results"
            / "control_plane"
            / "recovery"
            / request["incident_id"]
            / request["recovery_run_id"]
            / "packets"
            / "reconcile.json"
        ).read_text(encoding="utf-8")
    )
    assert reconciliation_packet["broker_write_calls"] == 0
    assert reconciliation_packet["can_submit_orders"] is False
    assert broker_spy.write_calls == []


def test_task5_revalidates_canonical_after_injected_pre_rearm_mutation(
    tmp_path,
):
    request, canonical_path, invocations, broker_spy = (
        _production_recovery_harness(tmp_path)
    )
    coordinator_args = dict(request)
    coordinator_args.pop("ready")

    def mutate_then_rearm(**kwargs):
        canonical = json.loads(canonical_path.read_text(encoding="utf-8"))
        canonical["sleeves"]["pullback-support"]["metrics"][
            "benchmark_excess_return"
        ] = "888888.00"
        canonical_path.write_text(
            json.dumps(canonical, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return rearm_after_verified_recovery(**kwargs)

    result = coordinate_verified_recovery(
        **coordinator_args,
        control_path=_control(tmp_path),
        receipt_dir=tmp_path / "receipts",
        recovery_root=tmp_path / "results" / "control_plane" / "recovery",
        now=NOW,
        rearm=mutate_then_rearm,
    )

    assert result["status"] == "frozen"
    assert result["phase"] == "rearm"
    control, _issues = load_live_control_state(
        tmp_path / "live_control.json",
        now=NOW,
    )
    assert control["frozen"] is True
    assert list((tmp_path / "receipts").glob("verified-rearm-*.json")) == []
    assert broker_spy.write_calls == []
    assert sum("sync-promotion" in argv for argv in invocations) == 1


def test_coordinator_task5_cas_preserves_newer_safety_freeze(
    tmp_path,
    monkeypatch,
):
    request, _canonical_path, invocations, broker_spy = (
        _production_recovery_harness(tmp_path)
    )
    control_path = _control(tmp_path)
    coordinator_args = dict(request)
    coordinator_args.pop("ready")
    original_write_receipt = recovery_module.write_rearm_receipt

    def receipt_then_newer_freeze(*args, **kwargs):
        receipt_ref = original_write_receipt(*args, **kwargs)
        control_path.write_text(
            json.dumps(
                {
                    "frozen": True,
                    "reason": "newer independent safety freeze",
                    "dead_man_expires_at": (
                        NOW + dt.timedelta(days=1)
                    ).isoformat(timespec="seconds"),
                    "updated_at": NOW.isoformat(timespec="seconds"),
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
    result = coordinate_verified_recovery(
        **coordinator_args,
        control_path=control_path,
        receipt_dir=tmp_path / "receipts",
        recovery_root=tmp_path / "results" / "control_plane" / "recovery",
        now=NOW,
    )

    assert result["status"] == "frozen"
    assert result["phase"] == "rearm"
    control, _issues = load_live_control_state(control_path, now=NOW)
    assert control["frozen"] is True
    assert control["reason"] == "newer independent safety freeze"
    assert "recovery_receipt_path" not in control
    assert not (tmp_path / "receipts" / "latest.json").exists()
    assert broker_spy.write_calls == []
    assert sum("sync-promotion" in argv for argv in invocations) == 1


def test_post_promotion_manifest_fault_stays_frozen_until_receipt(tmp_path):
    request, state_path, invocations, broker_spy = _production_recovery_harness(
        tmp_path
    )
    coordinator_args = dict(request)
    coordinator_args.pop("ready")

    def crash(boundary):
        if (
            boundary["boundary"] == "after_phase_fsync"
            and boundary["phase"] == "manifest"
        ):
            raise SystemExit("post-promotion manifest fault")

    with pytest.raises(SystemExit, match="post-promotion manifest fault"):
        coordinate_verified_recovery(
            **coordinator_args,
            control_path=_control(tmp_path),
            receipt_dir=tmp_path / "receipts",
            recovery_root=tmp_path / "results" / "control_plane" / "recovery",
            now=NOW,
            fault_hook=crash,
        )

    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["sleeves"]["pullback-support"]["live_enabled"] is True
    assert sum("sync-promotion" in argv for argv in invocations) == 1
    control, _issues = load_live_control_state(tmp_path / "live_control.json", now=NOW)
    assert control["frozen"] is True
    assert list((tmp_path / "receipts").glob("verified-rearm-*.json")) == []
    reconciliation_packet = json.loads(
        (
            tmp_path
            / "results"
            / "control_plane"
            / "recovery"
            / request["incident_id"]
            / request["recovery_run_id"]
            / "packets"
            / "reconcile.json"
        ).read_text(encoding="utf-8")
    )
    assert reconciliation_packet["broker_write_calls"] == 0
    assert reconciliation_packet["can_submit_orders"] is False
    assert broker_spy.write_calls == []
    live_gate = evaluate_go_live_guard(
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
        risk_envelope_path=tmp_path / "config" / "risk_envelope.yaml",
        promotion_state_path=state_path,
        control_state_path=tmp_path / "live_control.json",
        live_buying_power=Decimal("1000"),
        now=NOW,
    )
    assert live_gate.allowed is False
    assert live_gate.checks["live_not_frozen"] is False


def test_stage_write_crash_resumes_without_reinvoking_promotion(tmp_path):
    request, state_path, invocations, broker_spy = _production_recovery_harness(
        tmp_path, fail_phase="promotion_after_stage_write"
    )
    original = state_path.read_bytes()
    coordinator_args = dict(request)
    coordinator_args.pop("ready")

    with pytest.raises(
        SystemExit, match="promotion state written before adapter return"
    ):
        coordinate_verified_recovery(
            **coordinator_args,
            control_path=_control(tmp_path),
            receipt_dir=tmp_path / "receipts",
            recovery_root=tmp_path / "results" / "control_plane" / "recovery",
            now=NOW,
        )

    assert state_path.read_bytes() == original
    assert sum("sync-promotion" in argv for argv in invocations) == 1
    control, _issues = load_live_control_state(tmp_path / "live_control.json", now=NOW)
    assert control["frozen"] is True
    assert broker_spy.write_calls == []

    resumed = coordinate_verified_recovery(
        **coordinator_args,
        control_path=_control(tmp_path),
        receipt_dir=tmp_path / "receipts",
        recovery_root=tmp_path / "results" / "control_plane" / "recovery",
        now=NOW,
    )

    assert resumed["status"] == "monitoring"
    assert sum("sync-promotion" in argv for argv in invocations) == 1
    committed = json.loads(state_path.read_text(encoding="utf-8"))
    assert committed["sleeves"]["pullback-support"]["live_enabled"] is True


def test_stage_orphan_rejects_semantically_valid_metric_tamper(tmp_path):
    request, canonical_path, invocations, broker_spy = (
        _production_recovery_harness(
            tmp_path,
            fail_phase="promotion_after_stage_write",
        )
    )
    original_canonical = canonical_path.read_bytes()
    coordinator_args = dict(request)
    coordinator_args.pop("ready")

    with pytest.raises(
        SystemExit,
        match="promotion state written before adapter return",
    ):
        coordinate_verified_recovery(
            **coordinator_args,
            control_path=_control(tmp_path),
            receipt_dir=tmp_path / "receipts",
            recovery_root=tmp_path / "results" / "control_plane" / "recovery",
            now=NOW,
        )

    stage_path = (
        tmp_path
        / "results"
        / "control_plane"
        / "recovery"
        / request["incident_id"]
        / request["recovery_run_id"]
        / "staging"
        / "promotion_state.json"
    )
    staged = json.loads(stage_path.read_text(encoding="utf-8"))
    staged["sleeves"]["pullback-support"]["metrics"][
        "benchmark_excess_return"
    ] = "999999.00"
    stage_path.write_text(
        json.dumps(staged, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    resumed = coordinate_verified_recovery(
        **coordinator_args,
        control_path=_control(tmp_path),
        receipt_dir=tmp_path / "receipts",
        recovery_root=tmp_path / "results" / "control_plane" / "recovery",
        now=NOW,
    )

    assert resumed["status"] == "frozen"
    assert resumed["phase"] == "sync_promotion"
    assert resumed["failure"]["kind"] == "permanent_integrity"
    assert canonical_path.read_bytes() == original_canonical
    assert sum("sync-promotion" in argv for argv in invocations) == 1
    assert broker_spy.write_calls == []
    assert list((tmp_path / "receipts").glob("verified-rearm-*.json")) == []


@pytest.mark.parametrize("mutation", ["extra_field", "raw_hash"])
def test_stage_orphan_rejects_arbitrary_content_or_hash_mutation(
    tmp_path,
    mutation,
):
    request, canonical_path, invocations, broker_spy = (
        _production_recovery_harness(
            tmp_path,
            fail_phase="promotion_after_stage_write",
        )
    )
    original_canonical = canonical_path.read_bytes()
    coordinator_args = dict(request)
    coordinator_args.pop("ready")

    with pytest.raises(
        SystemExit,
        match="promotion state written before adapter return",
    ):
        coordinate_verified_recovery(
            **coordinator_args,
            control_path=_control(tmp_path),
            receipt_dir=tmp_path / "receipts",
            recovery_root=tmp_path / "results" / "control_plane" / "recovery",
            now=NOW,
        )

    stage_path = (
        tmp_path
        / "results"
        / "control_plane"
        / "recovery"
        / request["incident_id"]
        / request["recovery_run_id"]
        / "staging"
        / "promotion_state.json"
    )
    if mutation == "extra_field":
        staged = json.loads(stage_path.read_text(encoding="utf-8"))
        staged["authenticated_extension"] = {"forged": True}
        stage_path.write_text(
            json.dumps(staged, indent=2),
            encoding="utf-8",
        )
    else:
        stage_path.write_bytes(stage_path.read_bytes() + b"\n")

    resumed = coordinate_verified_recovery(
        **coordinator_args,
        control_path=_control(tmp_path),
        receipt_dir=tmp_path / "receipts",
        recovery_root=tmp_path / "results" / "control_plane" / "recovery",
        now=NOW,
    )

    assert resumed["status"] == "frozen"
    assert resumed["phase"] == "sync_promotion"
    assert canonical_path.read_bytes() == original_canonical
    assert sum("sync-promotion" in argv for argv in invocations) == 1
    assert broker_spy.write_calls == []


def test_recovery_freezes_initially_open_control_before_promotion_replace(
    tmp_path,
):
    request, promotion_path, invocations, broker_spy = (
        _production_recovery_harness(tmp_path)
    )
    control_path = _control(tmp_path)
    write_live_control_state(
        control_path,
        frozen=False,
        reason="healthy before recovery",
        dead_man_expires_at=NOW + dt.timedelta(minutes=30),
    )
    coordinator_args = dict(request)
    coordinator_args.pop("ready")

    def crash(event):
        if event["boundary"] == "after_promotion_canonical_replace":
            raise SystemExit("canonical replaced while recovery is open")

    with pytest.raises(
        SystemExit,
        match="canonical replaced while recovery is open",
    ):
        coordinate_verified_recovery(
            **coordinator_args,
            control_path=control_path,
            receipt_dir=tmp_path / "receipts",
            recovery_root=tmp_path / "results" / "control_plane" / "recovery",
            now=NOW,
            fault_hook=crash,
        )

    promotion = json.loads(promotion_path.read_text(encoding="utf-8"))
    assert promotion["sleeves"]["pullback-support"]["live_enabled"] is True
    control, _issues = load_live_control_state(control_path, now=NOW)
    assert control["frozen"] is True
    assert list((tmp_path / "receipts").glob("verified-rearm-*.json")) == []
    assert broker_spy.write_calls == []
    gate = evaluate_go_live_guard(
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
        risk_envelope_path=tmp_path / "config" / "risk_envelope.yaml",
        promotion_state_path=promotion_path,
        control_state_path=control_path,
        live_buying_power=Decimal("1000"),
        now=NOW,
    )
    assert gate.allowed is False
    assert gate.checks["live_not_frozen"] is False
    assert sum("sync-promotion" in argv for argv in invocations) == 1


@pytest.mark.parametrize(
    "boundary",
    [
        "before_promotion_adapter",
        "after_promotion_stage_request_fsync",
        "after_promotion_prepare_fsync",
        "after_promotion_intent_fsync",
        "after_promotion_canonical_replace",
        "after_promotion_commit_receipt_fsync",
        "after_promotion_adapter_return",
    ],
)
def test_promotion_transaction_faults_resume_exactly_once(tmp_path, boundary):
    request, state_path, invocations, broker_spy = _production_recovery_harness(
        tmp_path
    )
    original = state_path.read_bytes()
    coordinator_args = dict(request)
    coordinator_args.pop("ready")
    fired = False

    def crash(event):
        nonlocal fired
        if event["boundary"] == boundary and not fired:
            fired = True
            raise SystemExit(boundary)

    with pytest.raises(SystemExit, match=boundary):
        coordinate_verified_recovery(
            **coordinator_args,
            control_path=_control(tmp_path),
            receipt_dir=tmp_path / "receipts",
            recovery_root=tmp_path / "results" / "control_plane" / "recovery",
            now=NOW,
            fault_hook=crash,
        )

    control, _issues = load_live_control_state(tmp_path / "live_control.json", now=NOW)
    assert control["frozen"] is True
    assert list((tmp_path / "receipts").glob("verified-rearm-*.json")) == []
    assert broker_spy.write_calls == []
    if boundary in {
        "before_promotion_adapter",
        "after_promotion_stage_request_fsync",
        "after_promotion_prepare_fsync",
        "after_promotion_intent_fsync",
    }:
        assert state_path.read_bytes() == original

    resumed = coordinate_verified_recovery(
        **coordinator_args,
        control_path=_control(tmp_path),
        receipt_dir=tmp_path / "receipts",
        recovery_root=tmp_path / "results" / "control_plane" / "recovery",
        now=NOW,
    )

    assert resumed["status"] == "monitoring"
    assert sum("sync-promotion" in argv for argv in invocations) == 1
    commit_receipts = list(
        (
            tmp_path
            / "results"
            / "control_plane"
            / "recovery"
            / request["incident_id"]
            / request["recovery_run_id"]
            / "packets"
        ).glob("promotion_commit.json")
    )
    assert len(commit_receipts) == 1
    committed = json.loads(state_path.read_text(encoding="utf-8"))
    assert committed["sleeves"]["pullback-support"]["live_enabled"] is True


def test_promotion_phase_packet_orphan_resumes_without_reinvoking_sync(tmp_path):
    request, state_path, invocations, broker_spy = _production_recovery_harness(
        tmp_path
    )
    coordinator_args = dict(request)
    coordinator_args.pop("ready")

    def crash(event):
        if (
            event["boundary"] == "after_phase_fsync"
            and event["phase"] == "sync_promotion"
        ):
            raise SystemExit("promotion phase packet fsynced")

    with pytest.raises(SystemExit, match="promotion phase packet fsynced"):
        coordinate_verified_recovery(
            **coordinator_args,
            control_path=_control(tmp_path),
            receipt_dir=tmp_path / "receipts",
            recovery_root=tmp_path / "results" / "control_plane" / "recovery",
            now=NOW,
            fault_hook=crash,
        )

    assert sum("sync-promotion" in argv for argv in invocations) == 1
    assert broker_spy.write_calls == []
    control, _issues = load_live_control_state(tmp_path / "live_control.json", now=NOW)
    assert control["frozen"] is True
    assert list((tmp_path / "receipts").glob("verified-rearm-*.json")) == []

    resumed = coordinate_verified_recovery(
        **coordinator_args,
        control_path=_control(tmp_path),
        receipt_dir=tmp_path / "receipts",
        recovery_root=tmp_path / "results" / "control_plane" / "recovery",
        now=NOW,
    )

    assert resumed["status"] == "monitoring"
    assert sum("sync-promotion" in argv for argv in invocations) == 1
    assert json.loads(state_path.read_text(encoding="utf-8"))["sleeves"][
        "pullback-support"
    ]["live_enabled"] is True


@pytest.mark.parametrize(
    ("target", "boundary", "expected_sync_calls"),
    [
        ("intent", "after_promotion_intent_fsync", 1),
        ("stage", "promotion_after_stage_write", 1),
        ("prepare", "after_promotion_prepare_fsync", 0),
        ("receipt", "after_promotion_commit_receipt_fsync", 1),
    ],
)
def test_promotion_transaction_tamper_stays_frozen(
    tmp_path,
    target,
    boundary,
    expected_sync_calls,
):
    fail_phase = boundary if target == "stage" else None
    request, canonical_path, invocations, broker_spy = (
        _production_recovery_harness(tmp_path, fail_phase=fail_phase)
    )
    original_canonical = canonical_path.read_bytes()
    coordinator_args = dict(request)
    coordinator_args.pop("ready")
    run_root = (
        tmp_path
        / "results"
        / "control_plane"
        / "recovery"
        / request["incident_id"]
        / request["recovery_run_id"]
    )

    def crash(event):
        if target != "stage" and event["boundary"] == boundary:
            raise SystemExit(boundary)

    expected_crash = (
        "promotion state written before adapter return"
        if target == "stage"
        else boundary
    )
    with pytest.raises(SystemExit, match=expected_crash):
        coordinate_verified_recovery(
            **coordinator_args,
            control_path=_control(tmp_path),
            receipt_dir=tmp_path / "receipts",
            recovery_root=tmp_path / "results" / "control_plane" / "recovery",
            now=NOW,
            fault_hook=crash,
        )

    if target == "intent":
        artifact_path = run_root.parent / "state.json"
        artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
        artifact["promotion_commit_intent"]["commit_id"] = "0" * 64
    elif target == "stage":
        artifact_path = run_root / "staging" / "promotion_state.json"
        artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
        artifact["source"]["arm_live"] = False
    elif target == "prepare":
        artifact_path = run_root / "packets" / "promotion_prepare.json"
        artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
        artifact["kind"] = "tampered_prepare"
    else:
        artifact_path = run_root / "packets" / "promotion_commit.json"
        artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
        artifact["kind"] = "tampered_commit"
    artifact_path.write_text(json.dumps(artifact), encoding="utf-8")

    result = coordinate_verified_recovery(
        **coordinator_args,
        control_path=_control(tmp_path),
        receipt_dir=tmp_path / "receipts",
        recovery_root=tmp_path / "results" / "control_plane" / "recovery",
        now=NOW,
    )

    assert result["status"] == "frozen"
    assert result["phase"] == "sync_promotion"
    assert result["failure"]["kind"] == "permanent_integrity"
    assert (
        sum("sync-promotion" in argv for argv in invocations)
        == expected_sync_calls
    )
    if target != "receipt":
        assert canonical_path.read_bytes() == original_canonical
    control, _issues = load_live_control_state(
        tmp_path / "live_control.json", now=NOW
    )
    assert control["frozen"] is True
    assert broker_spy.write_calls == []
    assert list((tmp_path / "receipts").glob("verified-rearm-*.json")) == []


@pytest.mark.parametrize(
    ("prepare_boundary", "stale_sync_calls"),
    [
        ("after_promotion_stage_request_fsync", 0),
        ("after_promotion_prepare_fsync", 1),
    ],
)
def test_coherent_stale_preimage_preserves_foreign_bytes_then_uses_fresh_follow_on(
    tmp_path,
    prepare_boundary,
    stale_sync_calls,
):
    request, canonical_path, invocations, broker_spy = (
        _production_recovery_harness(tmp_path)
    )
    coordinator_args = dict(request)
    coordinator_args.pop("ready")

    def crash(event):
        if event["boundary"] == prepare_boundary:
            raise SystemExit("prepared before foreign writer")

    with pytest.raises(SystemExit, match="prepared before foreign writer"):
        coordinate_verified_recovery(
            **coordinator_args,
            control_path=_control(tmp_path),
            receipt_dir=tmp_path / "receipts",
            recovery_root=tmp_path / "results" / "control_plane" / "recovery",
            now=NOW,
            fault_hook=crash,
        )

    foreign_state = {
        "schema_version": "1.0.0",
        "sleeves": {},
    }
    foreign_bytes = json.dumps(foreign_state, sort_keys=True).encode("utf-8")
    canonical_path.write_bytes(foreign_bytes)
    foreign_sha256 = hashlib.sha256(foreign_bytes).hexdigest()

    stale = coordinate_verified_recovery(
        **coordinator_args,
        control_path=_control(tmp_path),
        receipt_dir=tmp_path / "receipts",
        recovery_root=tmp_path / "results" / "control_plane" / "recovery",
        now=NOW,
    )

    assert stale["status"] == "frozen"
    assert stale["failure"]["kind"] == "transient"
    assert stale["next_retry_at"] == (
        NOW + dt.timedelta(seconds=120)
    ).isoformat()
    assert canonical_path.read_bytes() == foreign_bytes
    assert (
        sum("sync-promotion" in argv for argv in invocations)
        == stale_sync_calls
    )

    exhausted = coordinate_verified_recovery(
        **coordinator_args,
        control_path=_control(tmp_path),
        receipt_dir=tmp_path / "receipts",
        recovery_root=tmp_path / "results" / "control_plane" / "recovery",
        now=NOW + dt.timedelta(seconds=120),
    )

    assert exhausted["failure"]["kind"] == "transient_exhausted"
    assert canonical_path.read_bytes() == foreign_bytes

    recovered = coordinate_verified_recovery(
        **coordinator_args,
        control_path=_control(tmp_path),
        receipt_dir=tmp_path / "receipts",
        recovery_root=tmp_path / "results" / "control_plane" / "recovery",
        now=NOW + dt.timedelta(seconds=240),
    )

    assert recovered["status"] == "monitoring"
    assert recovered["recovery_run_id"].endswith("-follow-1")
    assert (
        sum("sync-promotion" in argv for argv in invocations)
        == stale_sync_calls + 1
    )
    follow_on_prepare = json.loads(
        (
            tmp_path
            / "results"
            / "control_plane"
            / "recovery"
            / request["incident_id"]
            / recovered["recovery_run_id"]
            / "packets"
            / "promotion_prepare.json"
        ).read_text(encoding="utf-8")
    )
    assert (
        follow_on_prepare["recovery_commit"]["canonical_before_sha256"]
        == foreign_sha256
    )
    assert broker_spy.write_calls == []


def test_invalid_v1_1_foreign_preimage_stays_frozen_and_byte_identical(tmp_path):
    request, canonical_path, _invocations, broker_spy = (
        _production_recovery_harness(tmp_path)
    )
    coordinator_args = dict(request)
    coordinator_args.pop("ready")

    def crash(event):
        if event["boundary"] == "after_promotion_prepare_fsync":
            raise SystemExit("prepared before invalid foreign writer")

    with pytest.raises(SystemExit, match="prepared before invalid foreign writer"):
        coordinate_verified_recovery(
            **coordinator_args,
            control_path=_control(tmp_path),
            receipt_dir=tmp_path / "receipts",
            recovery_root=tmp_path / "results" / "control_plane" / "recovery",
            now=NOW,
            fault_hook=crash,
        )

    foreign_bytes = json.dumps(
        {
            "schema_version": "1.1.0",
            "generated_at": NOW.isoformat(),
            "source": {"kind": "foreign_canonical_writer"},
            "sleeves": {},
        },
        sort_keys=True,
    ).encode("utf-8")
    canonical_path.write_bytes(foreign_bytes)

    result = coordinate_verified_recovery(
        **coordinator_args,
        control_path=_control(tmp_path),
        receipt_dir=tmp_path / "receipts",
        recovery_root=tmp_path / "results" / "control_plane" / "recovery",
        now=NOW,
    )

    assert result["status"] == "frozen"
    assert result["failure"]["kind"] == "permanent_integrity"
    assert canonical_path.read_bytes() == foreign_bytes
    assert broker_spy.write_calls == []
    assert list((tmp_path / "receipts").glob("verified-rearm-*.json")) == []


def test_policy_conflict_is_recoverable_not_manual_escalation():
    signal = classify_recovery_signal(
        {"label": "policy_rule_conflict", "reason": "approval_conflict", "symbol": "NFLX"}
    )

    assert signal["classification"] == "recoverable_integrity"
    assert signal["owner_role"] == "reliability_controller"
    assert signal["recipe"] == "resolve_policy_sync_reconcile_verify_rearm"


def test_exact_board_reviews_are_portfolio_business_decisions_not_recovery():
    exact = {
        "label": "hourly",
        "reason": "board_review",
        "path": "results/hourly_supervisor/latest-compact.json",
    }

    classified = classify_recovery_signal(exact)

    assert classified["classification"] == "business_decision_pending"
    assert classified["status"] == "retryable"
    assert classified["owner_role"] == "portfolio_executive"
    assert classified["allowed_effects"] == ["trade_decision"]
    assert classified["may_rearm"] is False
    assert classified["recipe"] is None

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

    assert other_order_adjacent["classification"] == "business_decision_pending"
    assert other_order_adjacent["status"] == "retryable"
    assert other_order_adjacent["owner_role"] == "portfolio_executive"
    assert other_order_adjacent["may_rearm"] is False
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
        "reconcile",
        "focused_verify",
        "sync_promotion",
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
    assert ready["repairer_role_id"] == "reliability_controller"
    assert focused["verifier_run_id"] != ready["repairer_run_id"]
    assert focused["verifier_role_id"] == "integrity_verifier"
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
    assert calls == [
        "resolve_authority",
        "regenerate_evidence",
        "reconcile",
        "focused_verify",
        "sync_promotion",
    ]
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
    assert summary["recovery_external_blocker"] == "external_action_required"
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


def test_production_reconciliation_forwards_repo_bound_owner_attribution(tmp_path):
    source = tmp_path / "source.json"
    source.write_text("{}", encoding="utf-8")
    attribution = tmp_path / "owner.json"
    attribution.write_text("{}", encoding="utf-8")
    invocations = []

    class Result:
        returncode = 0
        stderr = ""
        stdout = json.dumps({
            "read_only": True, "execution_authority": "none",
            "can_submit_orders": False, "matched": False,
            "issues": ["test"], "broker_write_calls": 0,
        })

    def runner(argv, **_kwargs):
        invocations.append(list(argv))
        return Result()

    context = {
        "symbol": "NFLX", "broker_account": "live", "environment": "production",
        "source_revision": "abc123", "supervisor_path": "missing.json",
        "advisory_path": "missing.json", "hourly_dir": "missing",
        "report_path": "missing.json", "envelope_path": "missing.yaml",
        "promotion_state_path": "missing-state.json",
        "reconciliation_packet_paths": ["source.json"],
        "owner_action_attestation_paths": ["owner.json"],
    }
    request = build_production_recovery_request(
        {"label": "policy_rule_conflict", "reason": "approval_conflict",
         "symbol": "NFLX", "path": "source.json", "recovery_context": context},
        repo_root=tmp_path,
        command_runner=runner,
    )

    response = request["adapters"]["reconcile"]({"phase": "reconcile"})

    assert "packet" in response
    command = invocations[-1]
    flag = command.index("--owner-action-attestation")
    assert command[flag + 1] == str(attribution.resolve())


@pytest.mark.parametrize(
    "scenario",
    [
        "bad_bindings",
        "blank_owner",
        "unsafe_owner",
        "unsafe_idempotency",
        "path_escape",
        "corrupt_lock",
        "owner_busy",
        "legacy_identity_mismatch",
    ],
)
def test_every_ambiguous_recovery_entry_exit_freezes_open_control(
    tmp_path,
    scenario,
):
    control_path = tmp_path / "live_control.json"
    write_live_control_state(
        control_path,
        frozen=False,
        reason="unsafe open control before ambiguous recovery",
        dead_man_expires_at=NOW + dt.timedelta(hours=1),
        now=NOW,
    )
    recovery_root = tmp_path / "recovery"
    incident_root = recovery_root / BINDINGS["incident_id"]
    bindings = dict(BINDINGS)
    owner_run_id = "repair-nflx-1"
    idempotency_key = None
    expect_error = False

    if scenario == "bad_bindings":
        bindings.pop("source_revision")
        expect_error = True
    elif scenario == "blank_owner":
        owner_run_id = ""
        expect_error = True
    elif scenario == "unsafe_owner":
        owner_run_id = "../unsafe-owner"
    elif scenario == "unsafe_idempotency":
        idempotency_key = "../unsafe-delivery"
    elif scenario == "path_escape":
        recovery_root.mkdir(parents=True)
        outside = tmp_path / "outside"
        outside.mkdir()
        incident_root.symlink_to(outside, target_is_directory=True)
    elif scenario == "corrupt_lock":
        incident_root.mkdir(parents=True)
        (incident_root / ".owner.lock").write_text("{bad", encoding="utf-8")
    elif scenario == "owner_busy":
        incident_root.mkdir(parents=True)
        (incident_root / ".owner.lock").write_text(
            json.dumps(
                {
                    "schema_version": "tradingagents.recovery_lock.v1",
                    "incident_id": BINDINGS["incident_id"],
                    "owner_run_id": "other-owner",
                    "lease_expires_at": (
                        NOW + dt.timedelta(minutes=10)
                    ).isoformat(),
                    "token": "other-owner-token",
                }
            ),
            encoding="utf-8",
        )
    elif scenario == "legacy_identity_mismatch":
        incident_root.mkdir(parents=True)
        (incident_root / "state.json").write_text(
            json.dumps(
                {
                    "schema_version": "tradingagents.self_heal_recovery.v1",
                    "incident_id": "different-incident",
                    "bindings": bindings,
                    "recovery_run_id": "recovery-nflx-1",
                }
            ),
            encoding="utf-8",
        )

    arguments = {
        "incident_id": BINDINGS["incident_id"],
        "bindings": bindings,
        "adapters": _adapters([]),
        "owner_run_id": owner_run_id,
        "recovery_run_id": "recovery-nflx-1",
        "control_path": control_path,
        "receipt_dir": tmp_path / "receipts",
        "recovery_root": recovery_root,
        "idempotency_key": idempotency_key,
        "now": NOW,
    }
    if expect_error:
        with pytest.raises(ValueError):
            coordinate_verified_recovery(**arguments)
    else:
        coordinate_verified_recovery(**arguments)

    control, _issues = load_live_control_state(control_path, now=NOW)
    assert control["frozen"] is True


@pytest.mark.parametrize("scenario", ["identity_mismatch", "owner_active"])
def test_ambiguous_persisted_recovery_exit_freezes_reopened_control(
    tmp_path,
    scenario,
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
    control_path = tmp_path / "live_control.json"
    write_live_control_state(
        control_path,
        frozen=False,
        reason="unsafe reopened control",
        dead_man_expires_at=NOW + dt.timedelta(hours=1),
        now=NOW,
    )
    arguments = {
        "incident_id": BINDINGS["incident_id"],
        "bindings": (
            {**BINDINGS, "symbol": "MSFT"}
            if scenario == "identity_mismatch"
            else BINDINGS
        ),
        "adapters": _adapters(calls),
        "owner_run_id": (
            "repair-nflx-1"
            if scenario == "identity_mismatch"
            else "repair-nflx-2"
        ),
        "recovery_run_id": "recovery-nflx-1",
        "control_path": control_path,
        "receipt_dir": tmp_path / "receipts",
        "recovery_root": (
            tmp_path / "results" / "control_plane" / "recovery"
        ),
        "now": NOW + dt.timedelta(seconds=1),
    }

    result = coordinate_verified_recovery(**arguments)

    assert result["status"] in {"identity_mismatch_frozen", "owner_active"}
    control, _issues = load_live_control_state(
        control_path,
        now=NOW + dt.timedelta(seconds=1),
    )
    assert control["frozen"] is True


def test_owner_busy_preserves_existing_recovery_freeze_byte_for_byte(tmp_path):
    control_path = _control(tmp_path)
    original = control_path.read_bytes()
    incident_root = (
        tmp_path
        / "results"
        / "control_plane"
        / "recovery"
        / BINDINGS["incident_id"]
    )
    incident_root.mkdir(parents=True)
    (incident_root / ".owner.lock").write_text(
        json.dumps(
            {
                "schema_version": "tradingagents.recovery_lock.v1",
                "incident_id": BINDINGS["incident_id"],
                "owner_run_id": "other-owner",
                "lease_expires_at": (NOW + dt.timedelta(minutes=10)).isoformat(),
                "token": "other-owner-token",
            }
        ),
        encoding="utf-8",
    )

    result = _run(tmp_path, [])

    assert result["status"] == "owner_busy"
    assert control_path.read_bytes() == original


@pytest.mark.parametrize("delivery_mode", ["duplicate", "monitoring"])
@pytest.mark.parametrize("tamper_receipt", [False, True])
def test_completed_early_return_preserves_open_only_for_exact_active_receipt(
    tmp_path,
    delivery_mode,
    tamper_receipt,
):
    calls: list[str] = []
    idempotency_key = "delivery-1" if delivery_mode == "duplicate" else None
    first = _run(tmp_path, calls, idempotency_key=idempotency_key)
    assert first["status"] == "monitoring"
    control_path = tmp_path / "live_control.json"
    before = control_path.read_bytes()
    if tamper_receipt:
        control = json.loads(before)
        Path(control["recovery_receipt_path"]).write_text(
            '{"tampered":true}',
            encoding="utf-8",
        )

    result = _run(tmp_path, calls, idempotency_key=idempotency_key)

    assert result["status"] == delivery_mode
    control, _issues = load_live_control_state(control_path, now=NOW)
    if tamper_receipt:
        assert control["frozen"] is True
    else:
        assert control["frozen"] is False
        assert control_path.read_bytes() == before


def test_existing_corrupt_state_fails_closed_without_reinitializing(tmp_path):
    recovery_root = tmp_path / "results" / "control_plane" / "recovery"
    state_path = recovery_root / BINDINGS["incident_id"] / "state.json"
    state_path.parent.mkdir(parents=True)
    state_path.write_text("{bad", encoding="utf-8")
    write_live_control_state(
        tmp_path / "live_control.json",
        frozen=False,
        reason="unsafe open control before corrupt recovery state",
        dead_man_expires_at=NOW + dt.timedelta(hours=1),
        now=NOW,
    )

    result = _run(tmp_path, [])

    assert result["status"] == "corrupt_state"
    assert state_path.read_text(encoding="utf-8") == "{bad"
    control, _issues = load_live_control_state(
        tmp_path / "live_control.json",
        now=NOW,
    )
    assert control["frozen"] is True


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


def test_stale_owner_lock_allows_exactly_one_two_contender_takeover(
    tmp_path,
    monkeypatch,
):
    lock_path = tmp_path / "recovery" / "incident-1" / ".owner.lock"
    lock_path.parent.mkdir(parents=True)
    stale = {
        "schema_version": "tradingagents.recovery_lock.v1",
        "incident_id": "incident-1",
        "owner_run_id": "old-owner",
        "lease_expires_at": (NOW - dt.timedelta(minutes=1)).isoformat(),
        "token": "old-token",
    }
    lock_path.write_text(json.dumps(stale), encoding="utf-8")
    original_replace = self_heal_module.os.replace
    first_replace_done = threading.Event()
    replace_order_lock = threading.Lock()
    replace_count = 0

    def force_old_aba_window(source, destination):
        nonlocal replace_count
        with replace_order_lock:
            replace_count += 1
            order = replace_count
        if order == 1:
            result = original_replace(source, destination)
            first_replace_done.set()
            return result
        assert first_replace_done.wait(timeout=2)
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            try:
                current = json.loads(lock_path.read_text(encoding="utf-8"))
            except (FileNotFoundError, json.JSONDecodeError):
                time.sleep(0.001)
                continue
            if current.get("token") != stale["token"]:
                break
            time.sleep(0.001)
        else:  # pragma: no cover - makes a failed deterministic setup explicit
            raise AssertionError("first contender did not publish its lock")
        return original_replace(source, destination)

    monkeypatch.setattr(self_heal_module.os, "replace", force_old_aba_window)
    start = threading.Barrier(2)
    results: list[tuple[int | None, str, str | None]] = []

    def contend(owner_run_id):
        start.wait()
        results.append(
            self_heal_module._recovery_lock(
                lock_path,
                incident_id="incident-1",
                owner_run_id=owner_run_id,
                lease_expires_at=(NOW + dt.timedelta(minutes=10)).isoformat(),
                now=NOW,
            )
        )

    contenders = [
        threading.Thread(target=contend, args=(f"owner-{index}",))
        for index in range(2)
    ]
    for contender in contenders:
        contender.start()
    for contender in contenders:
        contender.join(timeout=5)
        assert not contender.is_alive()

    acquired = [result for result in results if result[0] is not None]
    busy = [result for result in results if result[0] is None]
    try:
        assert len(acquired) == 1
        assert len(busy) == 1
        assert busy[0][1] == "owner_busy"
    finally:
        for descriptor, _status, token in acquired:
            assert descriptor is not None
            self_heal_module._release_recovery_lock(
                lock_path,
                descriptor,
                token,
            )


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
    latest_path = tmp_path / "receipts" / "latest.json"
    latest_path.unlink()
    resumed = _run(tmp_path, calls, rearm=counted_rearm)

    assert resumed["status"] == "monitoring"
    assert len(rearm_calls) == 1
    assert latest_path.exists()


@pytest.mark.parametrize(
    "failure_mode",
    [
        "after_rearm_runtime",
        "rearm_packet_before_write",
        "rearm_packet_after_write",
    ],
)
def test_exact_active_rearm_exception_is_adopted_truthfully_without_second_rearm(
    tmp_path,
    monkeypatch,
    failure_mode,
):
    calls: list[str] = []
    rearm_calls: list[dict] = []
    original_rearm = recovery_module.rearm_after_verified_recovery
    original_packet_writer = self_heal_module._write_phase_packet
    injected = False

    def counted_rearm(**kwargs):
        rearm_calls.append(kwargs)
        return original_rearm(**kwargs)

    def fault_hook(boundary):
        if (
            failure_mode == "after_rearm_runtime"
            and boundary["boundary"] == "after_rearm_return"
        ):
            raise RuntimeError("ordinary failure after Task5 return")

    def one_shot_rearm_packet_failure(path, packet):
        nonlocal injected
        if path.name == "rearm.json" and not injected:
            injected = True
            if failure_mode == "rearm_packet_before_write":
                raise RuntimeError("rearm packet failed before write")
            if failure_mode == "rearm_packet_after_write":
                original_packet_writer(path, packet)
                raise RuntimeError("rearm packet write completed then failed")
        return original_packet_writer(path, packet)

    if failure_mode != "after_rearm_runtime":
        monkeypatch.setattr(
            self_heal_module,
            "_write_phase_packet",
            one_shot_rearm_packet_failure,
        )

    first = _run(
        tmp_path,
        calls,
        idempotency_key="delivery-1",
        rearm=counted_rearm,
        fault_hook=fault_hook,
    )
    second = _run(
        tmp_path,
        calls,
        idempotency_key="delivery-1",
        rearm=counted_rearm,
    )

    assert first["status"] == "monitoring"
    assert second["status"] == "duplicate"
    assert len(rearm_calls) == 1
    assert calls.count("sync_promotion") == 1
    control, issues = load_live_control_state(
        tmp_path / "live_control.json",
        now=NOW,
    )
    assert issues == []
    assert control["frozen"] is False
    state = json.loads(
        (
            tmp_path
            / "results"
            / "control_plane"
            / "recovery"
            / BINDINGS["incident_id"]
            / "state.json"
        ).read_text(encoding="utf-8")
    )
    assert state["phase"] == "monitoring"
    assert state["last_failure"] is None
    assert "rearm" in state["phase_outputs"]
    assert (tmp_path / "receipts" / "latest.json").exists()


def test_persisted_terminal_failure_with_exact_active_receipt_is_adopted(
    tmp_path,
):
    calls: list[str] = []
    rearm_calls: list[dict] = []
    original_rearm = recovery_module.rearm_after_verified_recovery

    def counted_rearm(**kwargs):
        rearm_calls.append(kwargs)
        return original_rearm(**kwargs)

    def crash_after_return(boundary):
        if boundary["boundary"] == "after_rearm_return":
            raise SystemExit("leave exact active receipt before state commit")

    with pytest.raises(SystemExit, match="leave exact active receipt"):
        _run(
            tmp_path,
            calls,
            idempotency_key="delivery-1",
            rearm=counted_rearm,
            fault_hook=crash_after_return,
        )
    state_path = (
        tmp_path
        / "results"
        / "control_plane"
        / "recovery"
        / BINDINGS["incident_id"]
        / "state.json"
    )
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["last_failure"] = {
        "kind": "permanent_integrity",
        "detail": "old coordinator persisted a false terminal failure",
        "external": False,
    }
    state["incident_stage"] = "repairing"
    state_path.write_text(json.dumps(state), encoding="utf-8")

    resumed = _run(
        tmp_path,
        calls,
        idempotency_key="delivery-1",
        rearm=counted_rearm,
    )

    assert resumed["status"] == "monitoring"
    assert len(rearm_calls) == 1
    persisted = json.loads(state_path.read_text(encoding="utf-8"))
    assert persisted["last_failure"] is None
    assert persisted["phase"] == "monitoring"


def test_rearm_exception_with_invalid_active_receipt_forces_control_frozen(
    tmp_path,
):
    calls: list[str] = []

    def tamper_receipt_then_fail(boundary):
        if boundary["boundary"] != "after_rearm_return":
            return
        control = json.loads(
            (tmp_path / "live_control.json").read_text(encoding="utf-8")
        )
        Path(control["recovery_receipt_path"]).write_text(
            '{"tampered":true}',
            encoding="utf-8",
        )
        raise RuntimeError("receipt became invalid after Task5 return")

    result = _run(
        tmp_path,
        calls,
        fault_hook=tamper_receipt_then_fail,
    )

    assert result["status"] == "frozen"
    control, _issues = load_live_control_state(
        tmp_path / "live_control.json",
        now=NOW,
    )
    assert control["frozen"] is True


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
        "sync_promotion": lambda packet: packet.update({"arm_live": False}),
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
            "supervisor allowed authority",
            lambda packet: packet["payload"]["supervisor_review_authority"].update(
                {"allowed": False}
            ),
        ),
        (
            "regenerate_evidence",
            "supervisor additional decision",
            lambda packet: packet["payload"]["supervisor_review_authority"].update(
                {"requires_additional_decision": True}
            ),
        ),
        (
            "regenerate_evidence",
            "supervisor blockers",
            lambda packet: packet["payload"]["supervisor_review_authority"].update(
                {"blockers": ["manual approval required"]}
            ),
        ),
        (
            "regenerate_evidence",
            "supervisor blocked reasons",
            lambda packet: packet["payload"]["supervisor_review_authority"].update(
                {"blocked_reasons": ["policy authority unresolved"]}
            ),
        ),
        (
            "regenerate_evidence",
            "pre-registered policy authority",
            lambda packet: packet["payload"]["supervisor_review_authority"].update(
                {"policy_rule_exit": False}
            ),
        ),
        (
            "regenerate_evidence",
            "policy rule binding",
            lambda packet: packet["payload"]["supervisor_review_authority"].update(
                {"exit_policy_rule": "time_stop"}
            ),
        ),
        (
            "regenerate_evidence",
            "advisory board decision",
            lambda packet: packet["payload"]["advisory_analysis"].update(
                {"requires_board_decision": True}
            ),
        ),
        (
            "regenerate_evidence",
            "advisory decision owner",
            lambda packet: packet["payload"]["advisory_analysis"].update(
                {"decision_owner": "portfolio_executive"}
            ),
        ),
        (
            "regenerate_evidence",
            "advisory authority source",
            lambda packet: packet["payload"]["advisory_analysis"].update(
                {"authority_source": "advisory_research"}
            ),
        ),
        (
            "regenerate_evidence",
            "advisory preserved approval",
            lambda packet: packet["payload"]["advisory_analysis"][
                "loss_exit_candidate"
            ].update({"approval_effect": "board_review_input_not_loss_exit_approval"}),
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
            "live arming attestation",
            lambda packet: packet.update({"arm_live": False}),
        ),
        (
            "sync_promotion",
            "focused CI attestation",
            lambda packet: packet.update({"ci_green": False}),
        ),
        (
            "sync_promotion",
            "state source kind",
            lambda packet: packet["state"]["source"].update({"kind": "other"}),
        ),
        (
            "sync_promotion",
            "state live arming attestation",
            lambda packet: packet["state"]["source"].update({"arm_live": False}),
        ),
        (
            "sync_promotion",
            "state focused CI attestation",
            lambda packet: packet["state"]["source"].update({"ci_green": False}),
        ),
        (
            "sync_promotion",
            "promoted string ids",
            lambda packet: packet.update({"promoted": [True]}),
        ),
        (
            "sync_promotion",
            "demoted string ids",
            lambda packet: packet.update({"demoted": [7]}),
        ),
        (
            "sync_promotion",
            "sleeve record shape",
            lambda packet: packet["state"].update(
                {"sleeves": {"default": "not-a-record"}}
            ),
        ),
        (
            "sync_promotion",
            "sleeve symbol binding",
            lambda packet: packet["state"]["sleeves"]["pullback-support"].update(
                {"symbol": "TSLA"}
            ),
        ),
        (
            "sync_promotion",
            "sleeve stage",
            lambda packet: packet["state"]["sleeves"]["pullback-support"].update(
                {"stage": "live"}
            ),
        ),
        (
            "sync_promotion",
            "sleeve live flag",
            lambda packet: packet["state"]["sleeves"]["pullback-support"].update(
                {"live_enabled": "false"}
            ),
        ),
        (
            "sync_promotion",
            "promoted sleeve is live enabled",
            lambda packet: packet["state"]["sleeves"]["pullback-support"].update(
                {"live_enabled": False}
            ),
        ),
        (
            "sync_promotion",
            "sleeve gate consistency",
            lambda packet: packet["state"]["sleeves"]["pullback-support"].update(
                {"preregistered": False}
            ),
        ),
        (
            "sync_promotion",
            "sleeve source identity",
            lambda packet: packet["state"]["sleeves"]["pullback-support"][
                "source"
            ].update({"kind": "self_attested"}),
        ),
        (
            "sync_promotion",
            "sleeve metrics",
            lambda packet: packet["state"]["sleeves"]["pullback-support"][
                "metrics"
            ].update({"capacity_usd": "NaN"}),
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
            "position quantity",
            lambda packet: packet["position"].update({"qty": "NaN"}),
        ),
        (
            "reconcile",
            "position required numeric field",
            lambda packet: packet["position"].pop("notional"),
        ),
        (
            "reconcile",
            "position finite market value",
            lambda packet: packet["position"].update({"market_value": "Infinity"}),
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
            "minimal open order",
            lambda packet: packet.update(
                {
                    "open_orders": [
                        {
                            "symbol": "NFLX",
                            "client_order_id": "open-nflx-1",
                        }
                    ]
                }
            ),
        ),
        (
            "reconcile",
            "open order status",
            lambda packet: packet["open_orders"][0].update({"status": "filled"}),
        ),
        (
            "reconcile",
            "open order side",
            lambda packet: packet["open_orders"][0].pop("side"),
        ),
        (
            "reconcile",
            "open order finite quantity",
            lambda packet: packet["open_orders"][0].update({"qty": "NaN"}),
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
            "recent fill open status",
            lambda packet: packet["recent_fills"][0].update({"status": "open"}),
        ),
        (
            "reconcile",
            "recent fill positive quantity",
            lambda packet: packet["recent_fills"][0].update({"filled_qty": "0"}),
        ),
        (
            "reconcile",
            "recent fill finite quantity",
            lambda packet: packet["recent_fills"][0].update({"filled_qty": "NaN"}),
        ),
        (
            "reconcile",
            "recent fill timestamp",
            lambda packet: (
                packet["recent_fills"][0].pop("submitted_at"),
                packet["recent_fills"][0].pop("updated_at"),
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

    promotion_path = Path(state["phase_outputs"]["sync_promotion"]["path"])
    promotion_original = promotion_path.read_text(encoding="utf-8")
    empty_promotion = json.loads(promotion_original)
    empty_promotion["promoted"] = []
    empty_promotion["demoted"] = []
    empty_promotion["issues_by_sleeve"] = {}
    empty_promotion["state"]["sleeves"] = {}
    staged_path = Path(empty_promotion["staged_state_path"])
    canonical_path = Path(empty_promotion["state_path"])
    prepare_path = Path(empty_promotion["promotion_prepare"]["path"])
    receipt_path = Path(empty_promotion["promotion_commit"]["path"])
    staged_original = staged_path.read_bytes()
    canonical_original = canonical_path.read_bytes()
    prepare_original = prepare_path.read_bytes()
    receipt_original = receipt_path.read_bytes()
    intent_original = state["promotion_commit_intent"]
    stage_request_original = state["promotion_stage_request"]
    empty_state_bytes = json.dumps(
        empty_promotion["state"],
        indent=2,
        sort_keys=True,
    ).encode("utf-8")
    staged_path.write_bytes(empty_state_bytes)
    canonical_path.write_bytes(empty_state_bytes)
    empty_sha256 = hashlib.sha256(empty_state_bytes).hexdigest()
    empty_promotion["staged_state_sha256"] = empty_sha256
    empty_promotion["canonical_after_sha256"] = empty_sha256
    empty_promotion["promotion_commit_intent"]["staged_sha256"] = (
        empty_sha256
    )
    prepare = json.loads(prepare_original)
    prepare["expected_stage_sha256"] = empty_sha256
    prepare_path.write_text(
        json.dumps(
            prepare,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )
        + "\n",
        encoding="utf-8",
    )
    prepare_sha256 = hashlib.sha256(prepare_path.read_bytes()).hexdigest()
    empty_promotion["promotion_prepare"]["sha256"] = prepare_sha256
    empty_promotion["promotion_commit_intent"]["prepare_sha256"] = (
        prepare_sha256
    )
    empty_promotion["promotion_stage_request"].update(
        {
            "prepare_sha256": prepare_sha256,
            "expected_stage_sha256": empty_sha256,
        }
    )
    state["promotion_commit_intent"] = dict(
        empty_promotion["promotion_commit_intent"]
    )
    state["promotion_stage_request"] = dict(
        empty_promotion["promotion_stage_request"]
    )
    receipt = json.loads(receipt_original)
    receipt["prepare_sha256"] = prepare_sha256
    receipt["staged_sha256"] = empty_sha256
    receipt["canonical_after_sha256"] = empty_sha256
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    empty_promotion["promotion_commit"]["sha256"] = hashlib.sha256(
        receipt_path.read_bytes()
    ).hexdigest()
    promotion_path.write_text(json.dumps(empty_promotion), encoding="utf-8")
    assert _valid_phase_packet(
        promotion_path,
        "sync_promotion",
        BINDINGS,
        state=state,
        phase_outputs=state["phase_outputs"],
        control_path=tmp_path / "live_control.json",
        now=NOW,
        idempotency_key="delivery-1",
    )
    promotion_path.write_text(promotion_original, encoding="utf-8")
    staged_path.write_bytes(staged_original)
    canonical_path.write_bytes(canonical_original)
    prepare_path.write_bytes(prepare_original)
    receipt_path.write_bytes(receipt_original)
    state["promotion_commit_intent"] = intent_original
    state["promotion_stage_request"] = stage_request_original

    reconciliation_path = Path(state["phase_outputs"]["reconcile"]["path"])
    reconciliation_original = reconciliation_path.read_text(encoding="utf-8")
    canceled_partial_fill = json.loads(reconciliation_original)
    canceled_partial_fill["recent_fills"][0]["status"] = "canceled"
    canceled_partial_fill["recent_fills"][0]["filled_qty"] = "0.5"
    reconciliation_path.write_text(
        json.dumps(canceled_partial_fill), encoding="utf-8"
    )
    assert _valid_phase_packet(
        reconciliation_path,
        "reconcile",
        BINDINGS,
        state=state,
        phase_outputs=state["phase_outputs"],
        control_path=tmp_path / "live_control.json",
        now=NOW,
        idempotency_key="delivery-1",
    )
    empty_reconciliation = json.loads(reconciliation_original)
    empty_reconciliation["open_orders"] = []
    empty_reconciliation["recent_fills"] = []
    empty_reconciliation["checked_client_order_ids"] = []
    reconciliation_path.write_text(
        json.dumps(empty_reconciliation), encoding="utf-8"
    )
    assert _valid_phase_packet(
        reconciliation_path,
        "reconcile",
        BINDINGS,
        state=state,
        phase_outputs=state["phase_outputs"],
        control_path=tmp_path / "live_control.json",
        now=NOW,
        idempotency_key="delivery-1",
    )
    reconciliation_path.write_text(reconciliation_original, encoding="utf-8")


@pytest.mark.parametrize(
    "mutate",
    [
        lambda state: state["bindings"].update({"extra": "not-canonical"}),
        lambda state: state.update({"owner_role": "repair_team"}),
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


def test_legacy_v1_state_is_archived_and_restarted_as_frozen_v2_follow_on(
    tmp_path,
):
    initial_calls: list[str] = []
    assert _run(tmp_path, initial_calls)["status"] == "monitoring"
    state_path = (
        tmp_path
        / "results"
        / "control_plane"
        / "recovery"
        / BINDINGS["incident_id"]
        / "state.json"
    )
    completed = json.loads(state_path.read_text(encoding="utf-8"))
    legacy = dict(completed)
    legacy["schema_version"] = "tradingagents.self_heal_recovery.v1"
    legacy["phase_outputs"] = {
        name: completed["phase_outputs"][name]
        for name in (
            "resolve_authority",
            "regenerate_evidence",
            "sync_promotion",
        )
    }
    legacy["phase"] = "reconcile"
    legacy["last_artifact"] = legacy["phase_outputs"]["sync_promotion"]
    legacy["incident_stage"] = "repairing"
    legacy["idempotency_keys"] = []
    for key in (
        "rearm_intent",
        "promotion_commit_intent",
        "verifier_run_id",
        "parent_recovery_run_id",
        "follow_on_count",
        "follow_on_required",
        "follow_on_not_before",
    ):
        legacy.pop(key, None)
    legacy_bytes = json.dumps(legacy, sort_keys=True).encode("utf-8")
    state_path.write_bytes(legacy_bytes)
    legacy_sha256 = hashlib.sha256(legacy_bytes).hexdigest()

    migration_calls: list[str] = []
    adapters = _adapters(migration_calls)

    def stop_at_phase_zero(arguments):
        migration_calls.append(arguments["phase"])
        raise SystemExit("inspect migrated phase zero")

    adapters["resolve_authority"] = stop_at_phase_zero
    with pytest.raises(SystemExit, match="inspect migrated phase zero"):
        _run(
            tmp_path,
            migration_calls,
            adapters=adapters,
            now=NOW + dt.timedelta(seconds=1),
        )

    migrated = json.loads(state_path.read_text(encoding="utf-8"))
    assert migrated["schema_version"] == "tradingagents.self_heal_recovery.v2"
    assert migrated["parent_recovery_run_id"] == "recovery-nflx-1"
    assert migrated["recovery_run_id"] == "recovery-nflx-1-v2-follow-1"
    assert migrated["phase"] == "resolve_authority"
    assert migrated["phase_outputs"] == {}
    assert migrated["legacy_v1_state_sha256"] == legacy_sha256
    archive_path = Path(migrated["legacy_v1_state_path"])
    assert archive_path.read_bytes() == legacy_bytes
    assert migration_calls == ["resolve_authority"]
    frozen, _issues = load_live_control_state(
        tmp_path / "live_control.json",
        now=NOW + dt.timedelta(seconds=1),
    )
    assert frozen["frozen"] is True

    resumed_calls: list[str] = []
    resumed = _run(
        tmp_path,
        resumed_calls,
        adapters=_adapters(resumed_calls),
        now=NOW + dt.timedelta(seconds=2),
    )

    assert resumed["status"] == "monitoring"
    assert resumed["recovery_run_id"] == "recovery-nflx-1-v2-follow-1"
    assert resumed_calls == list(RECOVERY_PHASES[:5])


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
        "reconcile",
        "focused_verify",
    ):
        assert request["adapters"][phase]({"phase": phase}).get("packet")
    promotion_without_proof = request["adapters"]["sync_promotion"](
        {"phase": "sync_promotion"}
    )
    assert promotion_without_proof["outcome"] == "failed"
    assert promotion_without_proof["failure_type"] == "transient"
    assert all(isinstance(argv, list) for argv in invocations)
    assert not any("sync-promotion" in argv for argv in invocations)
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


@pytest.mark.parametrize(
    ("decision", "expected_classification"),
    [
        ("HOLD", "resolved_no_action"),
        ("SELL", "decision_resolved_execution_pending"),
    ],
)
def test_board_decision_never_dispatches_recovery_or_changes_frozen_control(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    decision: str,
    expected_classification: str,
) -> None:
    context_dir = tmp_path / "results" / "_context"
    context_dir.mkdir(parents=True)
    (context_dir / "latest-flags.json").write_text(
        json.dumps(
            {
                "flags": [
                    {
                        "label": "hourly",
                        "reason": "board_review",
                        "path": "results/hourly_supervisor/latest-compact.json",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (context_dir / "latest-summary.json").write_text(
        json.dumps({"latest_packets": []}), encoding="utf-8"
    )
    control_path = tmp_path / "results" / "policy" / "live_control.json"
    write_live_control_state(
        control_path,
        frozen=True,
        reason="remain frozen",
        dead_man_expires_at=NOW + dt.timedelta(hours=1),
        now=NOW,
    )
    frozen_before = control_path.read_bytes()
    recovery_calls: list[dict] = []
    runner_calls: list[list[str]] = []

    monkeypatch.setattr(
        self_heal_module,
        "_authenticated_latest_board_decision",
        lambda *_args, **_kwargs: {
            "decision": decision,
            "decision_id": "a" * 64,
            "ledger_packet_id": "packet-1",
        },
    )
    monkeypatch.setattr(
        self_heal_module,
        "coordinate_verified_recovery",
        lambda **kwargs: recovery_calls.append(kwargs),
    )
    monkeypatch.setattr(
        self_heal_module,
        "_board_decision_matches_trigger",
        lambda *_args, **_kwargs: True,
    )

    plan = self_heal_module.build_self_heal_plan(tmp_path, now=NOW)
    signal = plan["signals"][0]
    assert signal["classification"] == expected_classification
    assert signal["owner_role"] == "portfolio_executive"
    assert signal["may_rearm"] is False
    assert signal["forbidden_effects"] == list(self_heal_module.FORBIDDEN_EFFECTS)

    result = self_heal_module.execute_self_heal_plan(
        plan,
        repo_root=tmp_path,
        runner=lambda argv, **_kwargs: runner_calls.append(list(argv)),
    )

    assert result["owned_recovery_count"] == 0
    assert recovery_calls == []
    assert runner_calls == []
    assert control_path.read_bytes() == frozen_before
    assert not (tmp_path / "results" / "control_plane" / "recovery").exists()
    assert not (tmp_path / "results" / "control_plane" / "rearm_receipts").exists()


def test_missing_or_invalid_board_decision_is_retryable_business_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        self_heal_module,
        "_authenticated_latest_board_decision",
        lambda *_args, **_kwargs: None,
    )
    signal = self_heal_module._classify_self_heal_signal(
        {"label": "execution_board_review", "reason": "board_review"},
        prior_signatures=set(),
        repo_root=tmp_path,
        now=NOW,
    )

    assert signal["classification"] == "business_decision_pending"
    assert signal["status"] == "retryable"
    assert signal["owner_role"] == "portfolio_executive"
    assert signal["may_rearm"] is False
    assert signal["recipe"] is None
    request = build_production_recovery_request(
        {"label": "hourly", "reason": "board_review"}, repo_root=tmp_path
    )
    assert request == {
        "ready": False,
        "outcome": "not_recovery_work",
        "detail": "signal is not an integrity recovery and cannot create a recovery run",
    }


def test_real_ledger_bound_board_hold_resolves_without_recovery_side_effects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _record_strict_hold_board(tmp_path)
    _write_self_heal_context(
        tmp_path,
        flags=[
            {
                "label": "execution_board_review",
                "reason": "board_review",
                "path": "results/execution_board/latest.json",
            }
        ],
    )
    control_path = tmp_path / "results" / "policy" / "live_control.json"
    write_live_control_state(
        control_path,
        frozen=True,
        reason="remain frozen",
        dead_man_expires_at=NOW + dt.timedelta(hours=1),
        now=NOW,
    )
    frozen_before = control_path.read_bytes()
    recovery_calls: list[dict] = []
    monkeypatch.setattr(
        self_heal_module,
        "coordinate_verified_recovery",
        lambda **kwargs: recovery_calls.append(kwargs),
    )

    plan = self_heal_module.build_self_heal_plan(tmp_path, now=NOW)
    signal = plan["signals"][0]

    assert fixture["decision"].decision == "HOLD"
    assert signal["classification"] == "resolved_no_action"
    assert signal["decision_reference"]["decision_id"] == fixture["decision"].decision_id
    result = self_heal_module.execute_self_heal_plan(plan, repo_root=tmp_path)
    assert result["owned_recovery_count"] == 0
    assert recovery_calls == []
    assert control_path.read_bytes() == frozen_before
    assert not (tmp_path / "results" / "control_plane" / "recovery").exists()
    assert not (tmp_path / "results" / "control_plane" / "rearm_receipts").exists()


def test_authenticated_board_decision_requires_matching_trigger_symbol_and_provenance(
    tmp_path: Path,
) -> None:
    fixture = _record_strict_hold_board(tmp_path, symbol="TSM")
    board_trigger = {
        "label": "execution_board_review",
        "reason": "board_review",
        "symbol": "TSM",
        "path": str(fixture["board_path"].relative_to(tmp_path)),
    }
    supervisor_trigger = {
        "label": "hourly",
        "reason": "board_review",
        "symbol": "TSM",
        "path": "results/hourly_supervisor/hourly.json",
    }

    for trigger in (board_trigger, supervisor_trigger):
        signal = self_heal_module._classify_self_heal_signal(
            trigger, prior_signatures=set(), repo_root=tmp_path, now=NOW
        )
        assert signal["classification"] == "resolved_no_action"

    for bad_symbol in ("NFLX", "AAPL"):
        signal = self_heal_module._classify_self_heal_signal(
            {**board_trigger, "symbol": bad_symbol},
            prior_signatures=set(),
            repo_root=tmp_path,
            now=NOW,
        )
        assert signal["classification"] == "business_decision_pending"
        assert signal["decision_reference"] is None

    copied_hourly = _write_json_packet(
        tmp_path / "results" / "hourly_supervisor" / "copied.json",
        json.loads((tmp_path / "results" / "hourly_supervisor" / "hourly.json").read_bytes()),
    )
    signal = self_heal_module._classify_self_heal_signal(
        {**supervisor_trigger, "path": str(copied_hourly.relative_to(tmp_path))},
        prior_signatures=set(),
        repo_root=tmp_path,
        now=NOW,
    )
    assert signal["classification"] == "business_decision_pending"
    assert signal["decision_reference"] is None


def test_scheduled_compact_board_and_hourly_sidecars_bind_exact_raw_provenance(
    tmp_path: Path,
) -> None:
    fixture = _record_strict_hold_board(tmp_path, symbol="TSM")
    board_compact_path = _write_bound_board_compact(tmp_path, fixture)
    hourly_compact_path = tmp_path / "results" / "hourly_supervisor" / "latest-compact.json"
    _write_json_packet(
        hourly_compact_path,
        {
            "schema": "compact_hourly_supervisor_v1",
            "generated_at": NOW.isoformat(),
            "decision": "loss-review",
            "analysis_only": True,
            "can_submit_orders": False,
            "execution_authority": "none",
            "raw_packet_path": str(
                tmp_path / "results" / "hourly_supervisor" / "hourly.json"
            ),
        },
    )
    for label, path in (
        ("execution_board_review", board_compact_path),
        ("hourly", hourly_compact_path),
    ):
        signal = self_heal_module._classify_self_heal_signal(
            {
                "label": label,
                "reason": "board_review",
                "symbol": "TSM",
                "path": str(path.relative_to(tmp_path)),
            },
            prior_signatures=set(),
            repo_root=tmp_path,
            now=NOW,
        )
        assert signal["classification"] == "resolved_no_action"


@pytest.mark.parametrize(
    ("label", "reason"),
    [
        ("policy_rule_conflict", "approval_conflict"),
        ("promotion_state", "policy_conflict"),
        ("broker_reconciliation", "reconciliation_mismatch"),
    ],
)
def test_board_origin_blocks_recovery_even_when_its_decision_is_malformed(
    tmp_path: Path, label: str, reason: str
) -> None:
    """A caller cannot turn a malformed Board packet into repair authority."""
    board_path = _write_json_packet(
        tmp_path / "results" / "execution_board" / "latest.json",
        {
            "kind": "execution_board_review",
            "schema_version": 1,
            "generated_at": NOW.isoformat(),
            "analysis_only": True,
            "can_submit_orders": False,
            "execution_authority": "none",
            "autonomous_loss_decision": "malformed-on-purpose",
        },
    )

    request = build_production_recovery_request(
        {
            "label": label,
            "reason": reason,
            "path": str(board_path.relative_to(tmp_path)),
        },
        repo_root=tmp_path,
    )

    assert request == {
        "ready": False,
        "outcome": "not_recovery_work",
        "detail": "BOARD packet provenance cannot create an integrity recovery run",
    }


@pytest.mark.parametrize(
    ("mutation", "replacement"),
    [
        ("schema", "compact_execution_board_review_v0"),
        ("raw_packet_path", "results/policy/not-board.json"),
        ("can_submit_orders", True),
    ],
)
def test_compact_board_sidecar_rejects_malformed_or_wrong_raw_path(
    tmp_path: Path, mutation: str, replacement: object
) -> None:
    fixture = _record_strict_hold_board(tmp_path)
    sidecar_path = tmp_path / "results" / "execution_board" / "latest-compact.json"
    sidecar = {
        "schema": "compact_execution_board_review_v1",
        "kind": "execution_board_review",
        "analysis_only": True,
        "can_submit_orders": False,
        "execution_authority": "none",
        "raw_packet_path": str(fixture["board_path"]),
    }
    sidecar[mutation] = replacement
    _write_json_packet(sidecar_path, sidecar)
    if mutation == "raw_packet_path":
        _write_json_packet(tmp_path / "results" / "policy" / "not-board.json", {})

    signal = self_heal_module._classify_self_heal_signal(
        {
            "label": "execution_board_review",
            "reason": "board_review",
            "symbol": "TSM",
            "path": str(sidecar_path.relative_to(tmp_path)),
        },
        prior_signatures=set(),
        repo_root=tmp_path,
        now=NOW,
    )
    assert signal["classification"] == "business_decision_pending"


def test_compact_sidecar_rejects_copied_root_and_replaced_raw_hourly(
    tmp_path: Path,
) -> None:
    fixture = _record_strict_hold_board(tmp_path)
    copied_sidecar = tmp_path / "outside" / "latest-compact.json"
    _write_json_packet(
        copied_sidecar,
        {
            "schema": "compact_hourly_supervisor_v1",
            "can_submit_orders": False,
            "execution_authority": "none",
            "raw_packet_path": "results/hourly_supervisor/hourly.json",
        },
    )
    signal = self_heal_module._classify_self_heal_signal(
        {
            "label": "hourly",
            "reason": "board_review",
            "symbol": "TSM",
            "path": str(copied_sidecar.relative_to(tmp_path)),
        },
        prior_signatures=set(),
        repo_root=tmp_path,
        now=NOW,
    )
    assert signal["classification"] == "business_decision_pending"

    sidecar_path = tmp_path / "results" / "hourly_supervisor" / "latest-compact.json"
    replacement = _write_json_packet(
        tmp_path / "results" / "hourly_supervisor" / "replacement.json",
        {"evidence": {"loss_exit_review": {"symbol": "TSM", "decision_id": "other"}}},
    )
    _write_json_packet(
        sidecar_path,
        {
            "schema": "compact_hourly_supervisor_v1",
            "can_submit_orders": False,
            "execution_authority": "none",
            "raw_packet_path": str(replacement),
        },
    )
    signal = self_heal_module._classify_self_heal_signal(
        {
            "label": "hourly",
            "reason": "board_review",
            "symbol": "TSM",
            "path": str(sidecar_path.relative_to(tmp_path)),
        },
        prior_signatures=set(),
        repo_root=tmp_path,
        now=NOW,
    )
    assert fixture["decision"].decision == "HOLD"
    assert signal["classification"] == "business_decision_pending"


def test_compact_sidecar_rejects_label_mismatch_and_symlink(tmp_path: Path) -> None:
    fixture = _record_strict_hold_board(tmp_path)
    board_sidecar = tmp_path / "results" / "execution_board" / "latest-compact.json"
    _write_json_packet(
        board_sidecar,
        {
            "schema": "compact_execution_board_review_v1",
            "kind": "execution_board_review",
            "analysis_only": True,
            "can_submit_orders": False,
            "execution_authority": "none",
            "raw_packet_path": str(fixture["board_path"]),
        },
    )
    wrong_label = self_heal_module._classify_self_heal_signal(
        {
            "label": "hourly",
            "reason": "board_review",
            "symbol": "TSM",
            "path": str(board_sidecar.relative_to(tmp_path)),
        },
        prior_signatures=set(),
        repo_root=tmp_path,
        now=NOW,
    )
    assert wrong_label["classification"] == "business_decision_pending"

    linked = tmp_path / "results" / "execution_board" / "linked-compact.json"
    linked.symlink_to(board_sidecar)
    symlink_signal = self_heal_module._classify_self_heal_signal(
        {
            "label": "execution_board_review",
            "reason": "board_review",
            "symbol": "TSM",
            "path": str(linked.relative_to(tmp_path)),
        },
        prior_signatures=set(),
        repo_root=tmp_path,
        now=NOW,
    )
    assert symlink_signal["classification"] == "business_decision_pending"


def test_direct_raw_paths_reject_wrong_label_pairing(tmp_path: Path) -> None:
    fixture = _record_strict_hold_board(tmp_path)
    for label, path in (
        ("hourly", fixture["board_path"]),
        ("execution_board_review", tmp_path / "results" / "hourly_supervisor" / "hourly.json"),
    ):
        signal = self_heal_module._classify_self_heal_signal(
            {
                "label": label,
                "reason": "board_review",
                "symbol": "TSM",
                "path": str(path.relative_to(tmp_path)),
            },
            prior_signatures=set(),
            repo_root=tmp_path,
            now=NOW,
        )
        assert signal["classification"] == "business_decision_pending"


def test_compact_sidecar_requires_analysis_only_and_rejects_symlink_raw_path(
    tmp_path: Path,
) -> None:
    fixture = _record_strict_hold_board(tmp_path)
    sidecar_path = tmp_path / "results" / "hourly_supervisor" / "latest-compact.json"
    base = {
        "schema": "compact_hourly_supervisor_v1",
        "analysis_only": True,
        "can_submit_orders": False,
        "execution_authority": "none",
        "raw_packet_path": "results/hourly_supervisor/hourly.json",
    }
    for mutation in ({"analysis_only": False}, {"analysis_only": None}):
        _write_json_packet(sidecar_path, {**base, **mutation})
        signal = self_heal_module._classify_self_heal_signal(
            {
                "label": "hourly",
                "reason": "board_review",
                "symbol": "TSM",
                "path": str(sidecar_path.relative_to(tmp_path)),
            },
            prior_signatures=set(),
            repo_root=tmp_path,
            now=NOW,
        )
        assert signal["classification"] == "business_decision_pending"

    board_sidecar = tmp_path / "results" / "execution_board" / "latest-compact.json"
    _write_json_packet(
        board_sidecar,
        {
            "schema": "compact_execution_board_review_v1",
            "kind": "execution_board_review",
            "analysis_only": False,
            "can_submit_orders": False,
            "execution_authority": "none",
            "raw_packet_path": "results/execution_board/latest.json",
        },
    )
    board_signal = self_heal_module._classify_self_heal_signal(
        {
            "label": "execution_board_review",
            "reason": "board_review",
            "symbol": "TSM",
            "path": str(board_sidecar.relative_to(tmp_path)),
        },
        prior_signatures=set(),
        repo_root=tmp_path,
        now=NOW,
    )
    assert board_signal["classification"] == "business_decision_pending"

    raw = tmp_path / "results" / "hourly_supervisor" / "hourly.json"
    target = tmp_path / "results" / "hourly_supervisor" / "actual.json"
    raw.rename(target)
    raw.symlink_to(target)
    _write_json_packet(sidecar_path, base)
    signal = self_heal_module._classify_self_heal_signal(
        {
            "label": "hourly",
            "reason": "board_review",
            "symbol": "TSM",
            "path": str(sidecar_path.relative_to(tmp_path)),
        },
        prior_signatures=set(),
        repo_root=tmp_path,
        now=NOW,
    )
    assert fixture["decision"].decision == "HOLD"
    assert signal["classification"] == "business_decision_pending"

    raw.unlink()
    target.rename(raw)
    linked_parent = tmp_path / "results" / "linked-hourly"
    linked_parent.symlink_to(raw.parent, target_is_directory=True)
    _write_json_packet(
        sidecar_path,
        {**base, "raw_packet_path": "results/linked-hourly/hourly.json"},
    )
    parent_symlink_signal = self_heal_module._classify_self_heal_signal(
        {
            "label": "hourly",
            "reason": "board_review",
            "symbol": "TSM",
            "path": str(sidecar_path.relative_to(tmp_path)),
        },
        prior_signatures=set(),
        repo_root=tmp_path,
        now=NOW,
    )
    assert parent_symlink_signal["classification"] == "business_decision_pending"


def test_descriptor_capture_rejects_parent_symlink_swap_race(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A parent replaced after lexical normalization cannot redirect a capture."""
    raw = _write_json_packet(
        tmp_path / "results" / "execution_board" / "latest.json",
        {"kind": "execution_board_review"},
    )
    outside = tmp_path / "outside"
    _write_json_packet(outside / "execution_board" / "latest.json", {"attacker": True})
    original_open = os.open
    swapped = False

    def swap_parent(path, flags, mode=0o777, *, dir_fd=None):
        nonlocal swapped
        if path == "results" and dir_fd is not None and not swapped:
            swapped = True
            original_open_path = tmp_path / "results"
            original_open_path.rename(tmp_path / "original-results")
            original_open_path.symlink_to(outside, target_is_directory=True)
        return original_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(self_heal_module.os, "open", swap_parent)
    captured = self_heal_module._captured_signal_packet(
        {"path": str(raw.relative_to(tmp_path))}, root=tmp_path
    )

    assert swapped is True
    assert captured is None


def test_unexpected_redundant_board_paths_are_rejected(tmp_path: Path) -> None:
    fixture = _record_strict_hold_board(tmp_path)
    board = fixture["board"]
    board["autonomous_loss_decision"]["ledger_packet_path"] = "/not/a/ledger/object"
    _write_json_packet(fixture["board_path"], board)

    signal = self_heal_module._classify_self_heal_signal(
        {
            "label": "execution_board_review",
            "reason": "board_review",
            "symbol": "TSM",
            "path": str(fixture["board_path"].relative_to(tmp_path)),
        },
        prior_signatures=set(),
        repo_root=tmp_path,
        now=NOW,
    )

    assert signal["classification"] == "business_decision_pending"


def test_unicode_accepted_source_digest_uses_producer_canonical_encoding(
    tmp_path: Path,
) -> None:
    fixture = _record_strict_hold_board(tmp_path)
    source = {
        "packet": {"path": "sources/évidence.json", "sha256": "a" * 64, "size_bytes": 1},
        "packet_id": "source-unicode",
        "source_name": "résumé",
        "evidence_type": "company_news",
        "as_of": NOW.isoformat(),
        "quality": "high",
    }
    class Source:
        def compact(self) -> dict:
            return source

    digest = self_heal_module._accepted_sources_digest((Source(),))
    expected = hashlib.sha256(
        json.dumps(
            [source], sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
    ).hexdigest()
    escaped_digest = hashlib.sha256(
        json.dumps(
            [source], sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode("utf-8")
    ).hexdigest()

    assert digest == expected
    assert digest != escaped_digest
    assert fixture["decision"].accepted_sources == ()


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        (("loss_review_evidence", "symbol"), "MSFT"),
        (("loss_review_evidence", "source_binding", "bindings", "raw_loss", "sha256"), "f" * 64),
        (("loss_review_evidence", "source_binding", "bindings", "supervisor", "decision_id"), "other-review"),
    ],
)
def test_cross_subject_or_evidence_board_projection_is_retryable(
    tmp_path: Path, field: tuple[str, ...], replacement: str
) -> None:
    fixture = _record_strict_hold_board(tmp_path)
    board = fixture["board"]
    target = board
    for key in field[:-1]:
        target = target[key]
    target[field[-1]] = replacement
    _write_json_packet(fixture["board_path"], board)
    _write_self_heal_context(
        tmp_path,
        flags=[
            {
                "label": "hourly",
                "reason": "board_review",
                "path": "results/hourly_supervisor/latest-compact.json",
            }
        ],
    )

    signal = self_heal_module.build_self_heal_plan(tmp_path, now=NOW)["signals"][0]

    assert signal["classification"] == "business_decision_pending"
    assert signal["status"] == "retryable"
    assert signal["decision_reference"] is None
    assert signal["may_rearm"] is False


def test_relabelled_board_packet_cannot_become_policy_recovery(tmp_path: Path) -> None:
    fixture = _record_strict_hold_board(tmp_path)

    request = build_production_recovery_request(
        {
            "label": "policy_rule_conflict",
            "reason": "approval_conflict",
            "path": str(fixture["board_path"].relative_to(tmp_path)),
        },
        repo_root=tmp_path,
    )

    assert request == {
        "ready": False,
        "outcome": "not_recovery_work",
        "detail": "BOARD packet provenance cannot create an integrity recovery run",
    }


def test_copied_strict_board_packet_cannot_become_policy_recovery(tmp_path: Path) -> None:
    fixture = _record_strict_hold_board(tmp_path)
    copied_path = _write_json_packet(
        tmp_path / "results" / "policy" / "relabelled.json", fixture["board"]
    )

    request = build_production_recovery_request(
        {
            "label": "policy_rule_conflict",
            "reason": "approval_conflict",
            "path": str(copied_path.relative_to(tmp_path)),
        },
        repo_root=tmp_path,
    )

    assert request["outcome"] == "not_recovery_work"
    assert "BOARD packet provenance" in request["detail"]


@pytest.mark.parametrize("label", ["policy_rule_conflict", "promotion_state", "broker_reconciliation"])
def test_relabelled_bound_board_compact_cannot_become_integrity_recovery(
    tmp_path: Path, label: str
) -> None:
    fixture = _record_strict_hold_board(tmp_path)
    sidecar = _write_bound_board_compact(tmp_path, fixture)

    request = build_production_recovery_request(
        {
            "label": label,
            "reason": "approval_conflict",
            "path": str(sidecar.relative_to(tmp_path)),
        },
        repo_root=tmp_path,
    )

    assert request == {
        "ready": False,
        "outcome": "not_recovery_work",
        "detail": "BOARD packet provenance cannot create an integrity recovery run",
    }


def test_genuine_non_board_policy_packet_is_not_rejected_as_board(tmp_path: Path) -> None:
    policy_path = _write_json_packet(
        tmp_path / "results" / "policy" / "conflict.json",
        {"kind": "policy_conflict", "schema_version": 1, "symbol": "NFLX"},
    )

    request = build_production_recovery_request(
        {
            "label": "policy_rule_conflict",
            "reason": "approval_conflict",
            "path": str(policy_path.relative_to(tmp_path)),
        },
        repo_root=tmp_path,
    )

    assert request["outcome"] != "not_recovery_work"


def test_immutable_strategy_promotion_sleeve_record_is_accepted() -> None:
    digest = "a" * 64
    record = {
        "stage": "tiny_live_eligible",
        "live_enabled": False,
        "preregistered": True,
        "ci_green": True,
        "shadow_sessions_sufficient": True,
        "reconciliation_confirmed": True,
        "shadow_confirmed": True,
        "benchmark_gate_passed": True,
        "cost_gate_passed": True,
        "recent_alpha_gate_passed": True,
        "capacity_gate_passed": True,
        "validation_report_ref": "artifacts/validation.json",
        "risk_envelope_ref": "config/risk_envelope.yaml",
        "eligible_at": "2026-07-28T12:00:00+00:00",
        "metrics": {
            "benchmark_excess_return": "0.01",
            "cost_adjusted_alpha": "0.01",
            "recent_alpha": "0.01",
            "capacity_usd": "300",
            "requested_tiny_live_tranche_usd": "100",
        },
        "source": {
            "kind": "immutable_strategy_evidence",
            "proposal_id": "strategy-promotion-proposal-" + digest,
            "proposal_sha256": digest,
            "registration_id": "evaluation-registration-" + digest,
            "promotion_evidence_id": "promotion-evidence-" + digest,
            "promotion_evidence_sha256": digest,
            "shadow_attestation_id": "paper-shadow-attestation-" + digest,
            "shadow_attestation_sha256": digest,
            "validation_attestation_sha256": digest,
            "risk_attestation_sha256": digest,
            "genome_id": "genome-current-aggressive-" + "b" * 32,
            "genome_canonical_sha256": digest,
            "evaluation_code_commit": "c" * 40,
            "evaluation_runtime_sha256": digest,
            "promotion_runtime_commit": "d" * 40,
            "risk_budget_mode": "fixed_tranche",
            "account_hard_ceiling_usd": None,
            "new_sleeve_auto_promote": True,
            "proposal_effective_at": "2026-07-28T11:59:00+00:00",
            "proposal_recorded_at": "2026-07-28T12:00:00+00:00",
            "proposal_expires_at": "2026-07-28T12:05:00+00:00",
        },
        "evidence_metrics": {
            "pooled_net_return_fraction": "0.02",
            "pooled_benchmark_return_fraction": "0.01",
            "pooled_benchmark_excess_fraction": "0.01",
            "latest_window_net_return_fraction": "0.01",
            "latest_window_benchmark_excess_fraction": "0.01",
            "worst_max_drawdown_fraction": "-0.05",
            "total_tracked_sessions": 10,
            "total_closed_trades": 2,
            "shadow_tracked_sessions": 6,
            "shadow_reconciled_buy_intents": 1,
        },
        "issues": [],
    }
    assert self_heal_module._valid_promotion_sleeve_record(
        record, symbol="NFLX"
    )

    # These are direct, fully-shaped corruption checks.  A recovery adapter
    # must reject them before treating a tiny eligibility record as safe.
    corruptions = (
        ("live_enabled", True),
        ("source.proposal_id", "strategy-promotion-proposal-" + "B" * 64),
        ("source.promotion_evidence_id", "promotion-evidence-" + "B" * 64),
        ("source.shadow_attestation_id", "paper-shadow-attestation-" + "B" * 64),
        ("source.evaluation_code_commit", "C" * 40),
        ("source.promotion_runtime_commit", "D" * 40),
        ("source.proposal_recorded_at", "2026-07-28T11:58:59+00:00"),
        ("source.proposal_expires_at", "2026-07-28T12:00:00+00:00"),
    )
    for dotted_name, corrupted_value in corruptions:
        candidate = json.loads(json.dumps(record))
        target = candidate
        *parents, leaf = dotted_name.split(".")
        for parent in parents:
            target = target[parent]
        target[leaf] = corrupted_value
        assert not self_heal_module._valid_promotion_sleeve_record(
            candidate, symbol="NFLX"
        ), dotted_name


def test_immutable_strategy_promotion_sleeve_record_rejects_unbound_projections() -> None:
    """Catch a recovery validator that accepts altered evidence projections."""
    digest = "a" * 64
    record = {
        "stage": "tiny_live_eligible",
        "live_enabled": False,
        "preregistered": True,
        "ci_green": True,
        "shadow_sessions_sufficient": True,
        "reconciliation_confirmed": True,
        "shadow_confirmed": True,
        "benchmark_gate_passed": True,
        "cost_gate_passed": True,
        "recent_alpha_gate_passed": True,
        "capacity_gate_passed": True,
        "validation_report_ref": "artifacts/validation.json",
        "risk_envelope_ref": "config/risk_envelope.yaml",
        "eligible_at": "2026-07-28T12:00:00+00:00",
        "metrics": {
            "benchmark_excess_return": "0.01",
            "cost_adjusted_alpha": "0.01",
            "recent_alpha": "0.01",
            "capacity_usd": "300",
            "requested_tiny_live_tranche_usd": "100",
        },
        "source": {
            "kind": "immutable_strategy_evidence",
            "proposal_id": "strategy-promotion-proposal-" + digest,
            "proposal_sha256": digest,
            "registration_id": "evaluation-registration-" + digest,
            "promotion_evidence_id": "promotion-evidence-" + digest,
            "promotion_evidence_sha256": digest,
            "shadow_attestation_id": "paper-shadow-attestation-" + digest,
            "shadow_attestation_sha256": digest,
            "validation_attestation_sha256": digest,
            "risk_attestation_sha256": digest,
            "genome_id": "genome-current-aggressive-" + "b" * 32,
            "genome_canonical_sha256": digest,
            "evaluation_code_commit": "c" * 40,
            "evaluation_runtime_sha256": digest,
            "promotion_runtime_commit": "d" * 40,
            "risk_budget_mode": "fixed_tranche",
            "account_hard_ceiling_usd": None,
            "new_sleeve_auto_promote": True,
            "proposal_effective_at": "2026-07-28T11:59:00+00:00",
            "proposal_recorded_at": "2026-07-28T12:00:00+00:00",
            "proposal_expires_at": "2026-07-28T12:05:00+00:00",
        },
        "evidence_metrics": {
            "pooled_net_return_fraction": "0.02",
            "pooled_benchmark_return_fraction": "0.01",
            "pooled_benchmark_excess_fraction": "0.01",
            "latest_window_net_return_fraction": "0.01",
            "latest_window_benchmark_excess_fraction": "0.01",
            "worst_max_drawdown_fraction": "-0.05",
            "total_tracked_sessions": 10,
            "total_closed_trades": 2,
            "shadow_tracked_sessions": 6,
            "shadow_reconciled_buy_intents": 1,
        },
        "issues": [],
    }
    assert self_heal_module._valid_promotion_sleeve_record(record, symbol="NFLX")

    corruptions = (
        ("metrics.benchmark_excess_return", "0.02"),
        ("metrics.cost_adjusted_alpha", "0.02"),
        ("metrics.recent_alpha", "0.02"),
        ("evidence_metrics.pooled_benchmark_excess_fraction", "0.02"),
        ("evidence_metrics.latest_window_benchmark_excess_fraction", "0.02"),
        ("metrics.capacity_usd", "99"),
        ("capacity_gate_passed", False),
    )
    for dotted_name, corrupted_value in corruptions:
        candidate = json.loads(json.dumps(record))
        target = candidate
        *parents, leaf = dotted_name.split(".")
        for parent in parents:
            target = target[parent]
        target[leaf] = corrupted_value
        assert not self_heal_module._valid_promotion_sleeve_record(
            candidate, symbol="NFLX"
        ), dotted_name


def test_immutable_strategy_promotion_paper_record_rejects_structural_gate_failures() -> None:
    """Catch paper-only records that pretend immutable evidence was incomplete."""
    digest = "a" * 64
    record = {
        "stage": "paper_only",
        "live_enabled": False,
        "preregistered": True,
        "ci_green": True,
        "shadow_sessions_sufficient": False,
        "reconciliation_confirmed": True,
        "shadow_confirmed": False,
        "benchmark_gate_passed": True,
        "cost_gate_passed": True,
        "recent_alpha_gate_passed": True,
        "capacity_gate_passed": True,
        "validation_report_ref": "artifacts/validation.json",
        "risk_envelope_ref": "config/risk_envelope.yaml",
        "ineligible_at": "2026-07-28T12:00:00+00:00",
        "metrics": {
            "benchmark_excess_return": "0.01",
            "cost_adjusted_alpha": "0.01",
            "recent_alpha": "0.01",
            "capacity_usd": "300",
            "requested_tiny_live_tranche_usd": "100",
        },
        "source": {
            "kind": "immutable_strategy_evidence",
            "proposal_id": "strategy-promotion-proposal-" + digest,
            "proposal_sha256": digest,
            "registration_id": "evaluation-registration-" + digest,
            "promotion_evidence_id": "promotion-evidence-" + digest,
            "promotion_evidence_sha256": digest,
            "shadow_attestation_id": "paper-shadow-attestation-" + digest,
            "shadow_attestation_sha256": digest,
            "validation_attestation_sha256": digest,
            "risk_attestation_sha256": digest,
            "genome_id": "genome-current-aggressive-" + "b" * 32,
            "genome_canonical_sha256": digest,
            "evaluation_code_commit": "c" * 40,
            "evaluation_runtime_sha256": digest,
            "promotion_runtime_commit": "d" * 40,
            "risk_budget_mode": "fixed_tranche",
            "account_hard_ceiling_usd": None,
            "new_sleeve_auto_promote": True,
            "proposal_effective_at": "2026-07-28T11:59:00+00:00",
            "proposal_recorded_at": "2026-07-28T12:00:00+00:00",
            "proposal_expires_at": "2026-07-28T12:05:00+00:00",
        },
        "evidence_metrics": {
            "pooled_net_return_fraction": "0.02",
            "pooled_benchmark_return_fraction": "0.01",
            "pooled_benchmark_excess_fraction": "0.01",
            "latest_window_net_return_fraction": "0.01",
            "latest_window_benchmark_excess_fraction": "0.01",
            "worst_max_drawdown_fraction": "-0.05",
            "total_tracked_sessions": 10,
            "total_closed_trades": 2,
            "shadow_tracked_sessions": 6,
            "shadow_reconciled_buy_intents": 1,
        },
        "issues": ["shadow_sessions_sufficient"],
    }
    assert self_heal_module._valid_promotion_sleeve_record(record, symbol="NFLX")

    for gate in (
        "preregistered",
        "benchmark_gate_passed",
        "cost_gate_passed",
        "recent_alpha_gate_passed",
    ):
        candidate = json.loads(json.dumps(record))
        candidate[gate] = False
        assert not self_heal_module._valid_promotion_sleeve_record(
            candidate, symbol="NFLX"
        ), gate


def test_legacy_recovery_refuses_immutable_strategy_canonical_preimage(
    tmp_path,
) -> None:
    request, state_path, _invocations, _broker_spy = _production_recovery_harness(
        tmp_path
    )
    canonical = json.loads(state_path.read_text(encoding="utf-8"))
    canonical["source"] = {"kind": "immutable_strategy_evidence_sync"}
    state_path.write_text(json.dumps(canonical), encoding="utf-8")
    immutable_preimage = state_path.read_bytes()

    result = coordinate_verified_recovery(
        **{key: value for key, value in request.items() if key != "ready"},
        control_path=_control(tmp_path / "immutable-source-control"),
        receipt_dir=tmp_path / "immutable-source-receipts",
        recovery_root=tmp_path / "immutable-source-recovery",
        now=NOW,
    )

    assert result["status"] == "frozen"
    assert (
        "immutable strategy promotion requires proposal-aware recovery"
        in result["failure"]["detail"]
    )
    assert state_path.read_bytes() == immutable_preimage


def test_legacy_prepared_transaction_cannot_resume_over_immutable_strategy_state(
    tmp_path,
) -> None:
    request, state_path, invocations, _broker_spy = _production_recovery_harness(
        tmp_path
    )
    coordinator_args = {key: value for key, value in request.items() if key != "ready"}
    recovery_root = tmp_path / "prepared-immutable-recovery"

    def crash_after_prepare(event) -> None:
        if event["boundary"] == "after_promotion_prepare_fsync":
            raise SystemExit("prepared tournament transaction")

    with pytest.raises(SystemExit, match="prepared tournament transaction"):
        coordinate_verified_recovery(
            **coordinator_args,
            control_path=_control(tmp_path / "prepared-immutable-control"),
            receipt_dir=tmp_path / "prepared-immutable-receipts",
            recovery_root=recovery_root,
            now=NOW,
            fault_hook=crash_after_prepare,
        )

    canonical = json.loads(state_path.read_text(encoding="utf-8"))
    canonical["source"] = {"kind": "immutable_strategy_evidence_sync"}
    state_path.write_text(json.dumps(canonical), encoding="utf-8")
    immutable_preimage = state_path.read_bytes()
    resumed = coordinate_verified_recovery(
        **coordinator_args,
        control_path=_control(tmp_path / "prepared-immutable-control"),
        receipt_dir=tmp_path / "prepared-immutable-receipts",
        recovery_root=recovery_root,
        now=NOW,
    )

    assert resumed["status"] == "frozen"
    assert resumed["phase"] == "sync_promotion"
    assert "immutable strategy promotion requires proposal-aware recovery" in resumed["failure"]["detail"]
    assert state_path.read_bytes() == immutable_preimage
    assert sum("sync-promotion" in argv for argv in invocations) == 0
