"""Additive original-leg outcome envelope with unavailable coverage kept explicit.

V1 parsing/replay is unchanged. V2 can retain an all-cash event without inventing
post-termination bars. Conditional covered-leg values are never gross returns;
the currently supported provider profiles do not establish full event coverage.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import re
from dataclasses import dataclass

from tradingagents.dataflows.pit.action_originals import (
    _canonical,
    verify_covered_action_valuation,
)
from tradingagents.dataflows.pit.execution_outcomes import _timestamp
from tradingagents.dataflows.pit.market_calendar import (
    MarketSessionCalendar,
    build_market_session_calendar,
    resolve_market_session_open,
    validate_market_session_calendar,
)
from tradingagents.dataflows.pit.raw_artifacts import RawPointInTimeArtifactArchive
from tradingagents.dataflows.pit.records import (
    PointInTimeDataError,
    SecurityIdentity,
    validate_security_identity,
)
from tradingagents.dataflows.pit.security_master import _freeze, _thaw

SCHEMA = "source_bound_execution_outcome/v2"
_AUTHORITY = {"analysis_only": True, "execution_authority": "none", "can_submit_orders": False}


@dataclass(frozen=True, slots=True, init=False)
class SourceBoundExecutionOutcomeV2:
    record: object

    def __init__(self, *args, **kwargs):
        raise TypeError("v2 execution outcomes require their original-leg builder")

    def to_dict(self) -> dict:
        return _thaw(self.record)

    def canonical_json_bytes(self) -> bytes:
        return _canonical(self.to_dict())

    @property
    def outcome_id(self):
        return self.record["outcome_id"]

    @property
    def outcome_sha256(self):
        return self.record["outcome_sha256"]

    @property
    def security_id(self):
        return self.record["security_id"]

    @property
    def symbol(self):
        return self.record["symbol"]

    @property
    def decision_event_id(self):
        return self.record["decision_event_id"]

    @property
    def decision_market_date(self):
        return self.record["decision_market_date"]

    @property
    def entry_session_date(self):
        return self.record["entry_session_date"]

    @property
    def exit_session_date(self):
        return self.record["exit_session_date"]

    @property
    def entry_session_open_at(self):
        return self.record["entry_session_open_at"]

    @property
    def holding_session_dates(self):
        return self.record["holding_session_dates"]

    @property
    def gross_return(self):
        return None

    @property
    def status(self):
        return "unavailable"

    @property
    def unavailable_reason(self):
        return self.record["unavailable_reason"]


def build_original_leg_execution_outcome(*, decision_event_id: str, decision_market_date: str, decision_cutoff: str,
                                        security: SecurityIdentity, market_calendar: MarketSessionCalendar,
                                        entry_session_open_at: str, covered_action_valuation: dict) -> SourceBoundExecutionOutcomeV2:
    if type(decision_event_id) is not str or re.fullmatch(r"decision-event-[0-9a-f]{64}", decision_event_id) is None:
        raise PointInTimeDataError("v2 outcome requires a registered decision event")
    if type(security) is not SecurityIdentity or type(market_calendar) is not MarketSessionCalendar:
        raise PointInTimeDataError("v2 outcome requires exact security and calendar records")
    identity = validate_security_identity(security.to_dict())
    calendar = validate_market_session_calendar(market_calendar.to_dict())
    cutoff = _timestamp(decision_cutoff, label="decision_cutoff")
    opened = _timestamp(entry_session_open_at, label="entry_session_open_at")
    if type(decision_market_date) is not str or decision_market_date not in calendar.market_dates or cutoff[:10] != decision_market_date:
        raise PointInTimeDataError("v2 outcome decision must bind its original calendar")
    dates = tuple(date for date in calendar.market_dates if date > decision_market_date)[:5]
    if len(dates) != 5 or opened[:10] != dates[0] or dt.datetime.fromisoformat(cutoff) >= dt.datetime.fromisoformat(opened):
        raise PointInTimeDataError("v2 outcome requires the exact next five sessions")
    if identity.effective_from > decision_market_date:
        raise PointInTimeDataError("v2 outcome security was not effective at decision")
    value = covered_action_valuation
    if type(value) is not dict or value.get("schema_version") != "covered_action_valuation/v2":
        raise PointInTimeDataError("v2 outcome requires its original-leg valuation")
    material = {key: item for key, item in value.items() if key not in {"valuation_id", "valuation_sha256"}}
    digest = hashlib.sha256(_canonical(material)).hexdigest()
    if (value.get("valuation_id") != f"valuation-{digest}" or value.get("valuation_sha256") != digest
            or value.get("symbol") != identity.symbol or value.get("entry_session_date") != dates[0] or value.get("exit_session_date") != dates[-1]
            or value.get("price_basis") != "raw_plus_explicit_legs" or value.get("gross_return") is not None
            or value.get("entry_price_basis") != "provider_daily_open_not_certified_session_open"
            or value.get("status") != "unavailable_for_economic_admission"
            or any(type(value.get(key)) is not type(expected) or value[key] != expected for key, expected in _AUTHORITY.items())
            or value.get("required_gaps") != ["complete_effective_event_coverage", "dated_security_alias_crosswalk", "official_session_open_price", "payment_or_delivery_outcomes_if_required"]):
        raise PointInTimeDataError("v2 outcome valuation identity or unavailable coverage differs")
    body = {"schema_version": SCHEMA, "decision_event_id": decision_event_id, "decision_market_date": decision_market_date,
            "decision_cutoff": cutoff, "security_id": identity.security_id, "symbol": identity.symbol,
            "security_identity_sha256": hashlib.sha256(identity.canonical_json_bytes()).hexdigest(),
            "market_calendar_id": calendar.calendar_id, "market_calendar_sha256": calendar.calendar_sha256,
            "entry_session_date": dates[0], "entry_session_open_at": opened, "exit_session_date": dates[-1],
            "holding_session_dates": list(dates), "covered_action_valuation": value,
            "status": "unavailable", "unavailable_reason": "effective_event_identity_open_price_and_delivery_coverage_unproven",
            "exit_value": None, "gross_return": None, **_AUTHORITY}
    digest = hashlib.sha256(_canonical(body)).hexdigest()
    row = {**body, "outcome_id": f"source-bound-execution-outcome-{digest}", "outcome_sha256": digest}
    outcome = object.__new__(SourceBoundExecutionOutcomeV2)
    object.__setattr__(outcome, "record", _freeze(row))
    return outcome


def validate_original_leg_execution_outcome(value: object, *, security: SecurityIdentity,
                                          market_calendar: MarketSessionCalendar) -> SourceBoundExecutionOutcomeV2:
    if type(value) is not dict:
        raise PointInTimeDataError("v2 execution outcome must be an object")
    try:
        rebuilt = build_original_leg_execution_outcome(decision_event_id=value["decision_event_id"], decision_market_date=value["decision_market_date"],
                                                       decision_cutoff=value["decision_cutoff"], security=security, market_calendar=market_calendar,
                                                       entry_session_open_at=value["entry_session_open_at"], covered_action_valuation=value["covered_action_valuation"])
    except KeyError as exc:
        raise PointInTimeDataError("v2 execution outcome fields are incomplete") from exc
    if rebuilt.canonical_json_bytes() != _canonical(value):
        raise PointInTimeDataError("v2 execution outcome does not match canonical rebuild")
    return rebuilt


def verify_original_leg_execution_outcome(*, archive: RawPointInTimeArtifactArchive, value: object, security: SecurityIdentity,
                                        market_calendar: MarketSessionCalendar) -> SourceBoundExecutionOutcomeV2:
    outcome = validate_original_leg_execution_outcome(value, security=security, market_calendar=market_calendar)
    original = archive.read_artifact(market_calendar.raw_artifact_id)
    calendar = build_market_session_calendar(archive=archive, raw_artifact=original)
    if calendar.canonical_json_bytes() != market_calendar.canonical_json_bytes():
        raise PointInTimeDataError("v2 outcome calendar does not replay from originals")
    opened = resolve_market_session_open(archive=archive, market_calendar=calendar, session_date=outcome.entry_session_date)
    if opened != outcome.entry_session_open_at:
        raise PointInTimeDataError("v2 outcome session open differs from original calendar")
    verify_covered_action_valuation(archive=archive, value=outcome.to_dict()["covered_action_valuation"])
    return outcome
