"""Contract tests for immutable, decision-only autonomous loss BOARD records."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

import tradingagents.policy.loss_board_decision as loss_board_decision
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
        "allowed_exit_reason_source": "earnings_guidance_packet",
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
            "sector": "Enterprise software peers remain stable while ORCL declines.",
            "relative_performance": "0.028",
        },
        "company_specific_negative_news_check": "Guidance cut confirmed.",
        "earnings_guidance_or_filing_check": "Earnings guidance cut broke the thesis.",
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
                "allowed_exit_reason_source": "earnings_guidance_packet",
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
                {"headline": "Company guidance was reduced after a material customer demand decline."}
                if source["evidence_type"] == "company_news"
                else ({"summary": "Current guidance and earnings filing substantively confirm the revenue outlook deterioration."} if source["evidence_type"] == "earnings_guidance_filing" else {"summary": "SPY and QQQ relative market observations are current and sector-normalized."})
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


@pytest.mark.parametrize(
    ("review_overrides", "loss_overrides", "packet_overrides"),
    [
        ({"allowed": "true"}, {}, {}),
        ({"symbol": "TSM"}, {}, {}),
        ({"evidence_generated_at": "2026-08-13T14:30:00+00:00"}, {}, {}),
        ({"broad_market_context": {"SPY": "0.1", "QQQ": "0.2"}, "sector_or_peer_context": ""}, {}, {}),
        ({"company_specific_negative_news_check": ""}, {}, {}),
        ({"earnings_guidance_or_filing_check": "SEC submissions index"}, {}, {}),
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
        ({"company_specific_negative_news_check": "News update available."}, {}),
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

    unsafe_parent.unlink()
    monkeypatch.setattr(
        loss_board_decision,
        "_after_decision_fsync",
        lambda _path: (_ for _ in ()).throw(RuntimeError("crash boundary")),
    )
    with pytest.raises(RuntimeError, match="crash boundary"):
        record_autonomous_loss_board_decision(
            supervisor_packet_path=supervisor_path,
            loss_evidence_packet_path=loss_path,
            source_revision="1" * 40,
            ledger_root=tmp_path / "ledger",
            evidence_root=root,
            now=NOW,
        )
    assert not (tmp_path / "ledger" / "events.jsonl").exists()
