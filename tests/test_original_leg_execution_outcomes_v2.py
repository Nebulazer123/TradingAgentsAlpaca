"""Additive outcome envelopes preserve unavailable coverage and original custody."""

from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json

import pytest

from tests.test_corporate_action_originals import (
    ACTION_URI,
    DATES,
    STAMP,
    offline,  # noqa: F401 -- block all network and model calls
    original,
    prices,
    record,
)
from tradingagents.dataflows.pit.action_originals import replay_alpaca_action_pages, value_covered_action_legs
from tradingagents.dataflows.pit.execution_outcomes_v2 import (
    SourceBoundExecutionOutcomeV2,
    build_original_leg_execution_outcome,
    validate_original_leg_execution_outcome,
    verify_original_leg_execution_outcome,
)
from tradingagents.dataflows.pit.market_calendar import build_market_session_calendar
from tradingagents.dataflows.pit.raw_artifacts import RawPointInTimeArtifactArchive
from tradingagents.dataflows.pit.records import PointInTimeDataError, SecurityIdentity
from tradingagents.evals.economic_evaluation_result import _canonical_execution_outcome_refs, _canonical_unavailable_outcomes
from tradingagents.evals.economic_tournament_evidence import EconomicTournamentInputEvidenceError, _outcome
from tradingagents.evals.economic_tournament_evidence_admission import _verify_execution_evidence

DECISION = "decision-event-" + "a" * 64
SESSIONS = ("2026-01-09", "2026-01-12", "2026-01-13", "2026-01-14", "2026-01-15", "2026-01-16")


@pytest.fixture
def archive(tmp_path):
    return RawPointInTimeArtifactArchive(tmp_path / "pit", clock=lambda: dt.datetime.fromisoformat(STAMP))


def inputs(archive):
    calendar_id = original(archive, [{"date": day, "open": "09:30", "close": "16:00"} for day in SESSIONS], "https://paper-api.alpaca.markets/v2/calendar")
    calendar = build_market_session_calendar(archive=archive, raw_artifact=archive.read_artifact(calendar_id))
    security = SecurityIdentity(security_id="security-old", symbol="OLD", cik=None, figi=None, exchange="NYSE", security_type="common_stock",
                                effective_from="2020-01-01", effective_to=None, status="active", successor_security_id=None, terminal_proceeds_artifact_id=None,
                                source_hashes={"security_master": hashlib.sha256(b"fixture security").hexdigest()})
    action_id = original(archive, {"corporate_actions": {"cash_mergers": [record(acquiree_symbol="OLD", effective_date="2026-01-15", rate="13", currency="USD")]}, "next_page_token": None}, ACTION_URI)
    action_set = replay_alpaca_action_pages(archive=archive, raw_artifact_ids=(action_id,))
    value = value_covered_action_legs(archive=archive, action_set=action_set, symbol="OLD", entry_session_date=DATES[0], exit_session_date=DATES[1], price_originals={"OLD": prices(archive, dates=(DATES[0],))})
    outcome = build_original_leg_execution_outcome(decision_event_id=DECISION, decision_market_date=SESSIONS[0], decision_cutoff="2026-01-09T20:55:00+00:00",
                                                  security=security, market_calendar=calendar, entry_session_open_at="2026-01-12T14:30:00+00:00", covered_action_valuation=value)
    return outcome, security, calendar


def test_all_cash_original_outcome_without_post_termination_bars_reopens_unavailable(archive):
    outcome, security, calendar = inputs(archive)
    assert type(outcome) is SourceBoundExecutionOutcomeV2
    assert outcome.holding_session_dates == SESSIONS[1:]
    assert outcome.gross_return is None and outcome.status == "unavailable"
    assert outcome.to_dict()["covered_action_valuation"]["remaining_security_legs"] == {}
    assert validate_original_leg_execution_outcome(json.loads(outcome.canonical_json_bytes()), security=security, market_calendar=calendar).outcome_id == outcome.outcome_id
    assert verify_original_leg_execution_outcome(archive=archive, value=outcome.to_dict(), security=security, market_calendar=calendar).outcome_id == outcome.outcome_id
    with pytest.raises(TypeError):
        outcome.record["gross_return"] = "0.3"


@pytest.mark.parametrize("field,replacement", [("gross_return", "0.3"), ("status", "completed"), ("can_submit_orders", 0), ("entry_session_open_at", "2026-01-12T15:30:00+00:00"), ("holding_session_dates", list(SESSIONS[1:4])), ("security_id", "security-other")])
def test_altered_outcome_fields_cannot_replay(archive, field, replacement):
    outcome, security, calendar = inputs(archive)
    changed = outcome.to_dict()
    changed[field] = replacement
    with pytest.raises(PointInTimeDataError):
        verify_original_leg_execution_outcome(archive=archive, value=changed, security=security, market_calendar=calendar)


def test_original_terms_and_calendar_bytes_are_reopened(archive):
    outcome, security, calendar = inputs(archive)
    identifier = outcome.to_dict()["covered_action_valuation"]["action_set"]["original_pages"][0]["raw_artifact_id"]
    (archive.root / "objects" / f"{identifier}.raw").write_bytes(b'{}')
    with pytest.raises(PointInTimeDataError):
        verify_original_leg_execution_outcome(archive=archive, value=outcome.to_dict(), security=security, market_calendar=calendar)


def test_tournament_bridge_allows_no_adjusted_window_only_for_v2(archive):
    outcome, security, calendar = inputs(archive)
    payload = {"execution_outcome": outcome.to_dict(), "price_window": None}
    rebuilt, canonical = _outcome(payload, security=security, market_calendar=calendar.to_dict(), event_market_date=SESSIONS[0], expected_decision_event_id=DECISION, label="fixture")
    assert rebuilt.outcome_id == outcome.outcome_id and canonical["price_window"] is None
    changed = copy.deepcopy(payload)
    changed["price_window"] = {"adjustment": "all"}
    with pytest.raises(EconomicTournamentInputEvidenceError, match="mix adjusted"):
        _outcome(changed, security=security, market_calendar=calendar.to_dict(), event_market_date=SESSIONS[0], expected_decision_event_id=DECISION, label="fixture")
    with pytest.raises(EconomicTournamentInputEvidenceError, match="event"):
        _outcome(payload, security=security, market_calendar=calendar.to_dict(), event_market_date=SESSIONS[0], expected_decision_event_id="decision-event-" + "b" * 64, label="fixture")


def test_null_result_helpers_bind_v2_ids_without_numeric_metric_claim(archive):
    outcome, _, _ = inputs(archive)
    refs = _canonical_execution_outcome_refs((outcome,))
    unavailable = _canonical_unavailable_outcomes((outcome,))
    assert refs[0]["outcome_id"] == outcome.outcome_id
    assert unavailable[0]["unavailable_reason"] == outcome.unavailable_reason
    assert "coverage_unproven" in outcome.unavailable_reason


def test_actual_tournament_admission_reopener_uses_v2_originals_and_never_adjusted_window(archive):
    outcome, security, calendar = inputs(archive)
    payload = {"execution_outcome": outcome.to_dict(), "price_window": None}
    assert _verify_execution_evidence(archive=archive, value=payload, security=security, calendar=calendar).outcome_id == outcome.outcome_id
    changed = copy.deepcopy(payload)
    changed["price_window"] = {}
    with pytest.raises(EconomicTournamentInputEvidenceError, match="mix adjusted"):
        _verify_execution_evidence(archive=archive, value=changed, security=security, calendar=calendar)
    identifier = calendar.raw_artifact_id
    (archive.root / "objects" / f"{identifier}.raw").write_bytes(b'[]')
    with pytest.raises(PointInTimeDataError):
        _verify_execution_evidence(archive=archive, value=payload, security=security, calendar=calendar)
