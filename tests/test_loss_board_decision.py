"""Contract tests for immutable, decision-only autonomous loss BOARD records."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

import tradingagents.policy.loss_board_decision as loss_board_decision
from tradingagents.brokers.supervisor.loss_review import ALLOWED_LOSS_EXIT_REASONS
from tradingagents.orchestration.decision_ledger import DecisionLedger
from tradingagents.policy.loss_board_decision import (
    record_autonomous_loss_board_decision,
    verify_autonomous_loss_board_decision,
)

NOW = datetime(2026, 8, 13, 15, 0, tzinfo=UTC)


def _write_json(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    return path


def _source(
    *,
    source_name: str,
    evidence_type: str,
    as_of: str = "2026-08-13T14:55:00+00:00",
    quality: str = "high",
) -> dict[str, str]:
    return {
        "source_name": source_name,
        "evidence_type": evidence_type,
        "source_ref": f"https://example.test/{source_name}",
        "as_of": as_of,
        "quality": quality,
    }


def _supervisor(*, symbol: str = "ORCL", **review_overrides: Any) -> dict[str, Any]:
    review: dict[str, Any] = {
        "symbol": symbol,
        "decision_id": "supervisor-loss-review-1",
        "allowed": True,
        "allowed_exit_reason": "thesis_invalidated",
        "allowed_exit_reason_source": None,
        "current_thesis_status": "Company guidance invalidated the original thesis.",
        "why_hold_is_worse_than_sell": "The catalyst broke and recovery odds are worse than cash.",
        "confidence": "0.82",
        "evidence_generated_at": "2026-08-13T14:55:00+00:00",
        "market_session": "regular",
        "blockers": [],
        "blocked_reasons": [],
        "broad_market_context": {"SPY": "0.1", "QQQ": "0.2"},
        "relative_performance_vs_SPY": "-0.031",
        "relative_performance_vs_QQQ": "-0.033",
        "sector_or_peer_context": {
            "sector": "software",
            "relative_performance": "-0.028",
        },
        "company_specific_negative_news_check": "Guidance cut confirmed.",
        "earnings_guidance_or_filing_check": "Earnings guidance cut broke the thesis.",
        "company_news_event_category": "guidance_cut",
        "company_news_direction": "adverse",
        "company_news_impact_fraction": "-0.08",
        "filing_event_category": "guidance_cut",
        "filing_direction": "adverse",
        "filing_change_fraction": "-0.12",
        "why_this_is_not_broad_market_red_day_noise": "SPY and QQQ are stable.",
    }
    review.update(review_overrides)
    return {
        "generated_at": "2026-08-13T14:55:00+00:00",
        "decision": "loss-review",
        "evidence": {"loss_exit_review": review},
    }


def _loss_evidence(*, symbol: str = "ORCL", **payload_overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "symbol": symbol,
        "remaining_blockers": [],
        "advisory_analysis": {
            "current_thesis_status_candidate": "Company guidance invalidated the original thesis.",
            "loss_exit_candidate": {
                "allowed_exit_reason_candidate": "thesis_invalidated",
                "allowed_exit_reason_source": None,
                "confidence": "0.82",
                "reason_summary": "The catalyst broke and recovery odds are worse than cash.",
                "approval_effect": "board_review_input_not_loss_exit_approval",
            },
        },
        "accepted_sources": [
            _source(source_name="market_data", evidence_type="market_context"),
            _source(source_name="company_news", evidence_type="company_news"),
            _source(source_name="sec_filing", evidence_type="earnings_guidance_filing"),
        ],
    }
    payload.update(payload_overrides)
    return {
        "schema_version": "1.0.0",
        "packet_id": "loss-evidence-1",
        "generated_at": "2026-08-13T14:55:00+00:00",
        "source_name": "loss_review_evidence",
        "evidence_type": "loss_review_evidence",
        "subject": symbol,
        "symbol": symbol,
        "quality": "high",
        "analysis_only": True,
        "execution_authority": "none",
        "can_submit_orders": False,
        "payload": payload,
    }


def _paths(tmp_path: Path, *, supervisor: dict[str, Any], loss: dict[str, Any]) -> tuple[Path, Path, Path]:
    evidence_root = tmp_path / "evidence"
    supervisor_path = _write_json(evidence_root / "supervisor.json", supervisor)
    payload = loss["payload"]
    payload["supervisor_packet_path"] = "supervisor.json"
    payload["supervisor_decision_id"] = supervisor["evidence"]["loss_exit_review"]["decision_id"]
    descriptors = []
    for index, source in enumerate(payload["accepted_sources"]):
        source_path = evidence_root / "sources" / f"{index}.json"
        packet = {
            "packet_id": f"source-{index}",
            "source_name": source["source_name"],
            "evidence_type": source["evidence_type"],
            "subject": payload["symbol"],
            "symbol": payload["symbol"],
            "as_of": source["as_of"],
            "quality": source["quality"],
            "payload": (
                {
                    "symbol": payload["symbol"],
                    "as_of": source["as_of"],
                    "event_category": "guidance_cut",
                    "direction": "adverse",
                    "impact_fraction": "-0.08",
                }
                if source["evidence_type"] == "company_news"
                else (
                    {
                        "symbol": payload["symbol"],
                        "as_of": source["as_of"],
                        "event_category": "guidance_cut",
                        "direction": "adverse",
                        "change_fraction": "-0.12",
                    }
                    if source["evidence_type"] == "earnings_guidance_filing"
                    else {
                        "symbol": payload["symbol"],
                        "as_of": source["as_of"],
                        "spy": {"symbol": "SPY", "value": "0.1", "as_of": source["as_of"]},
                        "qqq": {"symbol": "QQQ", "value": "0.2", "as_of": source["as_of"]},
                        "sector_relative": {"symbol": payload["symbol"], "value": "-0.028", "as_of": source["as_of"]},
                    }
                )
            ),
        }
        _write_json(source_path, packet)
        content = source_path.read_bytes()
        descriptors.append(
            {
                "path": source_path.relative_to(evidence_root).as_posix(),
                "sha256": hashlib.sha256(content).hexdigest(),
                "size_bytes": len(content),
                "packet_id": packet["packet_id"],
                "source_name": packet["source_name"],
                "evidence_type": packet["evidence_type"],
                "as_of": packet["as_of"],
                "quality": packet["quality"],
            }
        )
    payload["accepted_sources"] = descriptors
    if len(descriptors) >= 3:
        filing = descriptors[2]
        reference = {
            "packet_id": filing["packet_id"],
            "path": filing["path"],
            "sha256": filing["sha256"],
        }
        review = supervisor["evidence"]["loss_exit_review"]
        candidate = payload["advisory_analysis"]["loss_exit_candidate"]
        if review["allowed_exit_reason_source"] is None:
            review["allowed_exit_reason_source"] = reference
        if candidate.get("allowed_exit_reason_source") is None and "allowed_exit_reason_source" in candidate:
            candidate["allowed_exit_reason_source"] = reference
    _write_json(supervisor_path, supervisor)
    return (
        supervisor_path,
        _write_json(evidence_root / "loss.json", loss),
        evidence_root,
    )


def _record(tmp_path: Path, *, supervisor: dict[str, Any] | None = None, loss: dict[str, Any] | None = None):
    supervisor_path, loss_path, evidence_root = _paths(
        tmp_path,
        supervisor=supervisor or _supervisor(),
        loss=loss or _loss_evidence(),
    )
    return record_autonomous_loss_board_decision(
        supervisor_packet_path=supervisor_path,
        loss_evidence_packet_path=loss_path,
        source_revision="1" * 40,
        ledger_root=tmp_path / "ledger",
        evidence_root=evidence_root,
        now=NOW,
    )


def _rewrite_source_packet(loss_path: Path, source_path: Path, packet: dict[str, Any]) -> None:
    _write_json(source_path, packet)
    loss = json.loads(loss_path.read_text(encoding="utf-8"))
    content = source_path.read_bytes()
    for descriptor in loss["payload"]["accepted_sources"]:
        if descriptor["path"] == source_path.relative_to(loss_path.parent).as_posix():
            descriptor["sha256"] = hashlib.sha256(content).hexdigest()
            descriptor["size_bytes"] = len(content)
    _write_json(loss_path, loss)


def test_records_verified_sell_only_as_an_immutable_analysis_only_decision(tmp_path):
    recorded = _record(tmp_path)

    assert recorded.decision.decision == "SELL"
    assert recorded.decision.trade_decision_resolved is True
    assert recorded.decision.exit_allowed is True
    assert recorded.decision.execution_authority == "none"
    assert recorded.decision.can_submit_orders is False
    assert recorded.packet.kind == "portfolio_decision"
    assert recorded.packet.producer_role == "portfolio_executive"
    assert recorded.packet.allowed_effects == ("record_trade_decision",)
    assert recorded.packet.recommendation == "autonomous_sell_authorized_pending_execution_intent"
    assert DecisionLedger(tmp_path / "ledger").verify(evidence_root=tmp_path / "evidence")[-1].kind == "portfolio_decision"
    assert (
        verify_autonomous_loss_board_decision(
            recorded.decision_evidence_path,
            evidence_root=tmp_path / "evidence",
            now=NOW,
        )
        == recorded.decision
    )


def test_exit_reason_taxonomy_reuses_the_supervisor_contract():
    assert loss_board_decision.ALLOWED_LOSS_EXIT_REASONS is ALLOWED_LOSS_EXIT_REASONS
    assert {
        "thesis_invalidated",
        "company_specific_negative_news",
        "earnings_or_guidance_break",
    } == loss_board_decision.AUTONOMOUS_BOARD_ELIGIBLE_LOSS_EXIT_REASONS
    assert loss_board_decision.AUTONOMOUS_BOARD_ELIGIBLE_LOSS_EXIT_REASONS <= ALLOWED_LOSS_EXIT_REASONS


@pytest.mark.parametrize("reason", ["user_manual_override", "policy_stop_floor", "hard_stop_defined_before_entry"])
def test_non_board_canonical_reason_never_becomes_autonomous_sell(tmp_path, reason):
    recorded = _record(tmp_path, supervisor=_supervisor(allowed_exit_reason=reason))
    assert recorded.decision.decision == "HOLD"


@pytest.mark.parametrize(
    ("review_overrides", "loss_overrides", "packet_overrides"),
    [
        ({"allowed": "true"}, {}, {}),
        ({"symbol": "TSM"}, {}, {}),
        ({"evidence_generated_at": "2026-08-13T14:30:00+00:00"}, {}, {}),
        ({"broad_market_context": {"SPY": "0.1", "QQQ": "0.2"}, "sector_or_peer_context": ""}, {}, {}),
        ({"company_news_direction": "neutral"}, {}, {}),
        ({"filing_event_category": "unknown_event"}, {}, {}),
        ({}, {"accepted_sources": [_source(source_name="company_news", evidence_type="company_news", as_of="2026-08-13T14:30:00+00:00")]}, {}),
        ({}, {"accepted_sources": [_source(source_name="sec", evidence_type="submissions_index")]}, {}),
        ({}, {"accepted_sources": [_source(source_name="transcript_gap", evidence_type="earnings_transcripts_gap")]}, {}),
        ({}, {}, {"analysis_only": "true"}),
        ({}, {}, {"can_submit_orders": "false"}),
        ({}, {}, {"generated_at": "2026-08-13T14:30:00+00:00"}),
    ],
)
def test_incomplete_or_malformed_evidence_never_produces_sell(tmp_path, review_overrides, loss_overrides, packet_overrides):
    try:
        recorded = _record(
            tmp_path,
            supervisor=_supervisor(**review_overrides),
            loss={**_loss_evidence(**loss_overrides), **packet_overrides},
        )
    except ValueError:
        return

    assert recorded.decision.decision == "HOLD"
    assert recorded.decision.exit_allowed is False
    assert recorded.decision.execution_authority == "none"
    assert recorded.decision.can_submit_orders is False
    assert recorded.decision.reason_code in {"evidence_incomplete", "hold_preferred"}
    assert recorded.decision.evidence_gaps


def test_mutated_bound_evidence_fails_verification(tmp_path):
    recorded = _record(tmp_path)
    loss_path = tmp_path / "evidence" / "loss.json"
    loss_path.write_text("{}", encoding="utf-8")

    with pytest.raises(ValueError, match="verification|bound evidence|sha256"):
        verify_autonomous_loss_board_decision(
            recorded.decision_evidence_path,
            evidence_root=tmp_path / "evidence",
            now=NOW,
        )


def test_rejects_conflicting_immutable_decision_object(tmp_path):
    recorded = _record(tmp_path)
    payload = json.loads(recorded.decision_evidence_path.read_text(encoding="utf-8"))
    payload["decision"]["reason_code"] = "tampered"
    recorded.decision_evidence_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="decision_id|canonical"):
        verify_autonomous_loss_board_decision(
            recorded.decision_evidence_path,
            evidence_root=tmp_path / "evidence",
            now=NOW,
        )


@pytest.mark.parametrize(
    "review_override",
    [
        {"blockers": ["unresolved"]},
        {"blocked_reasons": ["unresolved"]},
        {"blockers": ""},
        {"blocked_reasons": ""},
    ],
)
def test_supervisor_blockers_fail_closed(review_override, tmp_path):
    recorded = _record(tmp_path, supervisor=_supervisor(**review_override))
    assert recorded.decision.decision == "HOLD"


def test_missing_raw_remaining_blockers_fails_closed(tmp_path):
    loss = _loss_evidence()
    del loss["payload"]["remaining_blockers"]

    recorded = _record(tmp_path, loss=loss)
    assert recorded.decision.decision == "HOLD"


def test_unrelated_same_symbol_loss_packet_is_rejected_before_recording(tmp_path):
    supervisor_path, loss_path, evidence_root = _paths(tmp_path, supervisor=_supervisor(), loss=_loss_evidence())
    loss = json.loads(loss_path.read_text(encoding="utf-8"))
    loss["payload"]["supervisor_decision_id"] = "other-supervisor-decision"
    _write_json(loss_path, loss)

    with pytest.raises(ValueError, match="exactly bound"):
        record_autonomous_loss_board_decision(
            supervisor_packet_path=supervisor_path,
            loss_evidence_packet_path=loss_path,
            source_revision="1" * 40,
            ledger_root=tmp_path / "ledger",
            evidence_root=evidence_root,
            now=NOW,
        )
    assert not (tmp_path / "ledger" / "events.jsonl").exists()


def test_immutable_collision_does_not_append_a_second_ledger_event(tmp_path):
    recorded = _record(tmp_path)
    recorded.decision_evidence_path.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="collision"):
        _record(tmp_path)
    assert len((tmp_path / "ledger" / "events.jsonl").read_text(encoding="utf-8").splitlines()) == 1


def test_source_packet_mutation_and_url_descriptor_fail_verification_or_sell(tmp_path):
    recorded = _record(tmp_path)
    source_path = tmp_path / "evidence" / "sources" / "1.json"
    source_path.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="bound evidence"):
        verify_autonomous_loss_board_decision(recorded.decision_evidence_path, evidence_root=tmp_path / "evidence", now=NOW)

    supervisor_path, loss_path, evidence_root = _paths(tmp_path / "second", supervisor=_supervisor(), loss=_loss_evidence())
    loss = json.loads(loss_path.read_text(encoding="utf-8"))
    loss["payload"]["accepted_sources"][0]["path"] = "https://example.test/source"
    _write_json(loss_path, loss)
    recorded = record_autonomous_loss_board_decision(
        supervisor_packet_path=supervisor_path,
        loss_evidence_packet_path=loss_path,
        source_revision="1" * 40,
        ledger_root=tmp_path / "second" / "ledger",
        evidence_root=evidence_root,
        now=NOW,
    )
    assert recorded.decision.decision == "HOLD"


@pytest.mark.parametrize(
    ("review_override", "payload_override"),
    [
        ({"allowed_exit_reason": "sell_now"}, {}),
        ({"company_news_event_category": "unknown_event"}, {}),
        ({}, {"advisory_analysis": {"current_thesis_status_candidate": "different", "loss_exit_candidate": {}}}),
    ],
)
def test_semantic_or_advisory_contradictions_force_hold(tmp_path, review_override, payload_override):
    recorded = _record(
        tmp_path,
        supervisor=_supervisor(**review_override),
        loss=_loss_evidence(**payload_override),
    )
    assert recorded.decision.decision == "HOLD"
    assert recorded.decision.evidence_gaps


def test_verifier_rejects_expired_and_noncanonical_decision_bytes(tmp_path):
    recorded = _record(tmp_path)
    with pytest.raises(ValueError, match="currently valid"):
        verify_autonomous_loss_board_decision(
            recorded.decision_evidence_path,
            evidence_root=tmp_path / "evidence",
            now=NOW.replace(hour=16),
        )
    payload = json.loads(recorded.decision_evidence_path.read_text(encoding="utf-8"))
    recorded.decision_evidence_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    with pytest.raises(ValueError, match="exact canonical"):
        verify_autonomous_loss_board_decision(recorded.decision_evidence_path, evidence_root=tmp_path / "evidence", now=NOW)


def test_unsafe_publication_collision_and_crash_never_append_ledger(tmp_path, monkeypatch):
    root = tmp_path / "evidence"
    supervisor_path, loss_path, _ = _paths(tmp_path, supervisor=_supervisor(), loss=_loss_evidence())
    unsafe_parent = root / "autonomous_loss_board_decisions"
    unsafe_parent.symlink_to(tmp_path)
    with pytest.raises(ValueError, match="unsafe|symlink|escapes"):
        record_autonomous_loss_board_decision(
            supervisor_packet_path=supervisor_path,
            loss_evidence_packet_path=loss_path,
            source_revision="1" * 40,
            ledger_root=tmp_path / "ledger",
            evidence_root=root,
            now=NOW,
        )
    assert not (tmp_path / "ledger" / "events.jsonl").exists()


@pytest.mark.parametrize(
    "source_payload",
    [
        {"symbol": "ORCL", "as_of": "2026-08-13T14:55:00+00:00", "event_category": "guidance_cut", "direction": "adverse", "impact_fraction": "0.08"},
        {"symbol": "ORCL", "as_of": "2026-08-13T14:55:00+00:00", "event_category": "guidance_raised", "direction": "adverse", "impact_fraction": "-0.08"},
        {"symbol": "ORCL", "as_of": "2026-08-13T14:55:00+00:00", "event_category": "unknown_event", "direction": "adverse", "impact_fraction": "-0.08"},
        {"symbol": "ORCL", "as_of": "2026-08-13T14:55:00+00:00", "event_category": "guidance_cut", "direction": "adverse", "impact_fraction": "-0.08", "headline": "strong beat"},
    ],
)
def test_company_news_source_must_prove_current_adverse_thesis_break(tmp_path, source_payload):
    supervisor_path, loss_path, evidence_root = _paths(tmp_path, supervisor=_supervisor(), loss=_loss_evidence())
    source_path = evidence_root / "sources" / "1.json"
    source = json.loads(source_path.read_text(encoding="utf-8"))
    source["payload"] = source_payload
    _rewrite_source_packet(loss_path, source_path, source)
    recorded = record_autonomous_loss_board_decision(
        supervisor_packet_path=supervisor_path,
        loss_evidence_packet_path=loss_path,
        source_revision="1" * 40,
        ledger_root=tmp_path / "ledger",
        evidence_root=evidence_root,
        now=NOW,
    )
    assert recorded.decision.decision == "HOLD"


def test_market_and_filing_sources_require_structured_current_adverse_facts(tmp_path):
    supervisor_path, loss_path, evidence_root = _paths(tmp_path, supervisor=_supervisor(), loss=_loss_evidence())
    market_path = evidence_root / "sources" / "0.json"
    market = json.loads(market_path.read_text(encoding="utf-8"))
    market["payload"] = {
        "symbol": "ORCL",
        "as_of": "2026-08-13T14:55:00+00:00",
        "spy": {"symbol": "SPY", "value": "0.1", "as_of": "2026-08-13T14:55:00+00:00"},
        "qqq": {"symbol": "QQQ", "value": "0.2", "as_of": "2026-08-13T14:55:00+00:00"},
        "sector_relative": {"symbol": "ORCL", "value": "0.028", "as_of": "2026-08-13T14:55:00+00:00"},
    }
    _rewrite_source_packet(loss_path, market_path, market)
    recorded = record_autonomous_loss_board_decision(
        supervisor_packet_path=supervisor_path,
        loss_evidence_packet_path=loss_path,
        source_revision="1" * 40,
        ledger_root=tmp_path / "ledger",
        evidence_root=evidence_root,
        now=NOW,
    )
    assert recorded.decision.decision == "HOLD"

    supervisor_path, loss_path, evidence_root = _paths(tmp_path / "filing", supervisor=_supervisor(), loss=_loss_evidence())
    filing_path = evidence_root / "sources" / "2.json"
    filing = json.loads(filing_path.read_text(encoding="utf-8"))
    filing["payload"] = {"symbol": "ORCL", "as_of": "2026-08-13T14:55:00+00:00", "event_category": "earnings_miss", "direction": "adverse", "change_fraction": "0.12"}
    _rewrite_source_packet(loss_path, filing_path, filing)
    recorded = record_autonomous_loss_board_decision(
        supervisor_packet_path=supervisor_path,
        loss_evidence_packet_path=loss_path,
        source_revision="1" * 40,
        ledger_root=tmp_path / "filing" / "ledger",
        evidence_root=evidence_root,
        now=NOW,
    )
    assert recorded.decision.decision == "HOLD"


@pytest.mark.parametrize("source_ref", ["nonexistent", "company_news"])
def test_exit_reason_source_must_exactly_resolve_one_accepted_binding(tmp_path, source_ref):
    supervisor = _supervisor(allowed_exit_reason_source=source_ref)
    recorded = _record(tmp_path, supervisor=supervisor)
    assert recorded.decision.decision == "HOLD"


def test_advisory_reason_source_must_match_the_exact_supervisor_binding(tmp_path):
    loss = _loss_evidence()
    loss["payload"]["advisory_analysis"]["loss_exit_candidate"]["allowed_exit_reason_source"] = "source-1"
    recorded = _record(tmp_path, loss=loss)
    assert recorded.decision.decision == "HOLD"


def test_exit_reason_source_reference_is_rejected_when_ambiguous(tmp_path):
    supervisor_path, loss_path, evidence_root = _paths(tmp_path, supervisor=_supervisor(), loss=_loss_evidence())
    loss = json.loads(loss_path.read_text(encoding="utf-8"))
    loss["payload"]["accepted_sources"].append(dict(loss["payload"]["accepted_sources"][2]))
    _write_json(loss_path, loss)

    with pytest.raises(ValueError, match="unique"):
        record_autonomous_loss_board_decision(
            supervisor_packet_path=supervisor_path,
            loss_evidence_packet_path=loss_path,
            source_revision="1" * 40,
            ledger_root=tmp_path / "ledger",
            evidence_root=evidence_root,
            now=NOW,
        )
    assert not (tmp_path / "ledger" / "events.jsonl").exists()


def test_new_loss_board_directory_fsync_failure_never_records_ledger(tmp_path, monkeypatch):
    supervisor_path, loss_path, evidence_root = _paths(tmp_path, supervisor=_supervisor(), loss=_loss_evidence())
    original_fsync = loss_board_decision.os.fsync
    original_close = loss_board_decision.os.close
    closed: list[int] = []
    calls: list[int] = []

    def fail_root_fsync(descriptor: int) -> None:
        calls.append(descriptor)
        original_fsync(descriptor)
        if len(calls) == 1:
            raise OSError("root mkdir fsync failed")

    def track_close(descriptor: int) -> None:
        closed.append(descriptor)
        original_close(descriptor)

    monkeypatch.setattr(loss_board_decision.os, "fsync", fail_root_fsync)
    monkeypatch.setattr(loss_board_decision.os, "close", track_close)
    with pytest.raises(OSError, match="root mkdir fsync failed"):
        record_autonomous_loss_board_decision(
            supervisor_packet_path=supervisor_path,
            loss_evidence_packet_path=loss_path,
            source_revision="1" * 40,
            ledger_root=tmp_path / "ledger",
            evidence_root=evidence_root,
            now=NOW,
        )
    assert calls[-1] in closed
    assert not (tmp_path / "ledger" / "events.jsonl").exists()


def test_directory_fsync_failure_closes_fd_and_never_records_ledger(tmp_path, monkeypatch):
    supervisor_path, loss_path, evidence_root = _paths(tmp_path, supervisor=_supervisor(), loss=_loss_evidence())
    original_fsync = loss_board_decision.os.fsync
    original_close = loss_board_decision.os.close
    calls: list[int] = []
    closed: list[int] = []

    def fail_directory_fsync(descriptor: int) -> None:
        calls.append(descriptor)
        if len(calls) == 3:
            raise OSError("directory fsync failed")
        original_fsync(descriptor)

    def record_close(descriptor: int) -> None:
        closed.append(descriptor)
        original_close(descriptor)

    monkeypatch.setattr(loss_board_decision.os, "fsync", fail_directory_fsync)
    monkeypatch.setattr(loss_board_decision.os, "close", record_close)
    with pytest.raises(OSError, match="directory fsync failed"):
        record_autonomous_loss_board_decision(
            supervisor_packet_path=supervisor_path,
            loss_evidence_packet_path=loss_path,
            source_revision="1" * 40,
            ledger_root=tmp_path / "ledger",
            evidence_root=evidence_root,
            now=NOW,
        )
    assert len(calls) == 3
    assert calls[-1] in closed
    assert not (tmp_path / "ledger" / "events.jsonl").exists()


def test_creation_captures_each_source_once_and_never_cross_binds_a_mutation(tmp_path, monkeypatch):
    supervisor_path, loss_path, evidence_root = _paths(tmp_path, supervisor=_supervisor(), loss=_loss_evidence())
    source_path = evidence_root / "sources" / "1.json"
    original_read = loss_board_decision._read_contained
    reads: dict[Path, int] = {}

    def capture_once(root, path, *, label):
        captured = original_read(root, path, label=label)
        target = captured[0]
        if target.parent.name == "sources":
            reads[target] = reads.get(target, 0) + 1
            if reads[target] > 1:
                raise AssertionError("source packet was opened a second time")
            if target == source_path:
                mutated = json.loads(target.read_text(encoding="utf-8"))
                mutated["payload"]["event_category"] = "unknown_event"
                _write_json(target, mutated)
        return captured

    monkeypatch.setattr(loss_board_decision, "_read_contained", capture_once)
    recorded = record_autonomous_loss_board_decision(
        supervisor_packet_path=supervisor_path,
        loss_evidence_packet_path=loss_path,
        source_revision="1" * 40,
        ledger_root=tmp_path / "ledger",
        evidence_root=evidence_root,
        now=NOW,
    )

    assert recorded.decision.decision == "SELL"
    assert reads == {evidence_root / "sources" / f"{index}.json": 1 for index in range(3)}


def test_verifier_opens_each_source_once(tmp_path, monkeypatch):
    recorded = _record(tmp_path)
    evidence_root = tmp_path / "evidence"
    original_open = loss_board_decision.os.open
    source_opens: dict[Path, int] = {}

    def open_once(path, *args, **kwargs):
        target = Path(path)
        if target.parent.name == "sources":
            source_opens[target] = source_opens.get(target, 0) + 1
            if source_opens[target] > 1:
                raise AssertionError("source packet was opened a second time")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(loss_board_decision.os, "open", open_once)
    verified = verify_autonomous_loss_board_decision(
        recorded.decision_evidence_path,
        evidence_root=evidence_root,
        now=NOW,
    )

    assert verified == recorded.decision
    assert source_opens == {evidence_root / "sources" / f"{index}.json": 1 for index in range(3)}
