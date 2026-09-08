"""Pure source-bound execution outcomes for economic counterfactuals."""

from __future__ import annotations

import dataclasses
import datetime as dt
import hashlib
import json
import re
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation

from tradingagents.dataflows.pit.adjusted_price_windows import (
    SourceBoundAdjustedPriceWindow,
    validate_five_session_adjusted_price_window,
)
from tradingagents.dataflows.pit.market_calendar import (
    MarketSessionCalendar,
    validate_market_session_calendar,
)
from tradingagents.dataflows.pit.records import (
    CorporateAction,
    PointInTimeDataError,
    SecurityIdentity,
    TerminalProceeds,
    validate_corporate_action,
    validate_security_identity,
    validate_terminal_proceeds,
)

__all__ = [
    "ExecutionPriceTwin",
    "SourceBoundExecutionOutcome",
    "build_source_bound_execution_outcome",
    "validate_execution_price_twin",
    "validate_source_bound_execution_outcome",
]


_SCHEMA = "source_bound_execution_outcome/v1"
_TWIN_SCHEMA = "execution_price_twin/v1"
_AUTHORITY = {
    "analysis_only": True,
    "execution_authority": "none",
    "can_submit_orders": False,
}
_TWIN_BASES = (
    "mid_price",
    "next_open",
    "executable_quote",
    "observed_paper_fill",
)
_SHA256 = re.compile(r"[0-9a-f]{64}")
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{2,255}")


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


def _identifier(value: object, *, label: str) -> str:
    if type(value) is not str or _IDENTIFIER.fullmatch(value) is None:
        raise PointInTimeDataError(f"{label} must be a canonical identifier")
    return value


def _date(value: object, *, label: str) -> str:
    if type(value) is not str:
        raise PointInTimeDataError(f"{label} must be an ISO date")
    try:
        parsed = dt.date.fromisoformat(value)
    except ValueError as exc:
        raise PointInTimeDataError(f"{label} must be an ISO date") from exc
    if parsed.isoformat() != value:
        raise PointInTimeDataError(f"{label} must be an ISO date")
    return value


def _timestamp(value: object, *, label: str) -> str:
    if type(value) is not str:
        raise PointInTimeDataError(f"{label} must be canonical UTC seconds")
    try:
        parsed = dt.datetime.fromisoformat(value)
    except ValueError as exc:
        raise PointInTimeDataError(f"{label} must be canonical UTC seconds") from exc
    if (
        parsed.tzinfo != dt.UTC
        or parsed.microsecond
        or parsed.isoformat(timespec="seconds") != value
    ):
        raise PointInTimeDataError(f"{label} must be canonical UTC seconds")
    return value


def _positive_decimal(value: object, *, label: str) -> str:
    if type(value) is not str:
        raise PointInTimeDataError(f"{label} must be a canonical positive decimal")
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise PointInTimeDataError(
            f"{label} must be a canonical positive decimal"
        ) from exc
    canonical = format(parsed.normalize(), "f")
    if not parsed.is_finite() or parsed <= 0 or value != canonical:
        raise PointInTimeDataError(f"{label} must be a canonical positive decimal")
    return value


def _decimal_text(value: Decimal) -> str:
    return "0" if value.is_zero() else format(value.normalize(), "f")


@dataclasses.dataclass(frozen=True, slots=True)
class ExecutionPriceTwin:
    """One registered execution-price basis or an explicit unavailable twin."""

    price_basis: str
    status: str
    security_id: str
    session_date: str
    observed_at: str | None
    price: str | None
    adjustment_status: str | None
    source_artifact_id: str | None
    source_artifact_sha256: str | None
    unavailable_reason: str | None
    schema_version: str = dataclasses.field(init=False, default=_TWIN_SCHEMA)
    analysis_only: bool = dataclasses.field(init=False, default=True)
    execution_authority: str = dataclasses.field(init=False, default="none")
    can_submit_orders: bool = dataclasses.field(init=False, default=False)

    def __post_init__(self) -> None:
        if self.price_basis not in _TWIN_BASES:
            raise PointInTimeDataError("execution price basis is not registered")
        _identifier(self.security_id, label="execution twin security_id")
        session_date = _date(self.session_date, label="execution twin session_date")
        if self.status == "available":
            observed = _timestamp(self.observed_at, label="execution twin observed_at")
            if observed[:10] != session_date:
                raise PointInTimeDataError(
                    "execution twin timestamp must occur on its bound session"
                )
            _positive_decimal(self.price, label="execution twin price")
            if self.adjustment_status != "total_return_adjusted":
                raise PointInTimeDataError(
                    "execution twin must use the total-return-adjusted basis"
                )
            _identifier(
                self.source_artifact_id,
                label="execution twin source_artifact_id",
            )
            if (
                type(self.source_artifact_sha256) is not str
                or _SHA256.fullmatch(self.source_artifact_sha256) is None
            ):
                raise PointInTimeDataError(
                    "execution twin source digest is invalid"
                )
            if self.unavailable_reason is not None:
                raise PointInTimeDataError(
                    "available execution twin cannot carry an unavailable reason"
                )
        elif self.status == "unavailable":
            if any(
                item is not None
                for item in (
                    self.observed_at,
                    self.price,
                    self.adjustment_status,
                    self.source_artifact_id,
                    self.source_artifact_sha256,
                )
            ):
                raise PointInTimeDataError(
                    "unavailable execution twin cannot carry guessed evidence"
                )
            _identifier(
                self.unavailable_reason,
                label="execution twin unavailable_reason",
            )
        else:
            raise PointInTimeDataError(
                "execution twin status must be available or unavailable"
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "price_basis": self.price_basis,
            "status": self.status,
            "security_id": self.security_id,
            "session_date": self.session_date,
            "observed_at": self.observed_at,
            "price": self.price,
            "adjustment_status": self.adjustment_status,
            "source_artifact_id": self.source_artifact_id,
            "source_artifact_sha256": self.source_artifact_sha256,
            "unavailable_reason": self.unavailable_reason,
            **_AUTHORITY,
        }

    def canonical_json_bytes(self) -> bytes:
        return _canonical_json_bytes(self.to_dict())


_TWIN_FIELDS = frozenset(field.name for field in dataclasses.fields(ExecutionPriceTwin))


def validate_execution_price_twin(value: object) -> ExecutionPriceTwin:
    if not isinstance(value, Mapping) or set(value) != _TWIN_FIELDS:
        raise PointInTimeDataError("execution price twin fields are invalid")
    if value["schema_version"] != _TWIN_SCHEMA or any(
        value[key] != expected for key, expected in _AUTHORITY.items()
    ):
        raise PointInTimeDataError("execution price twin schema or authority is invalid")
    rebuilt = ExecutionPriceTwin(
        price_basis=value["price_basis"],
        status=value["status"],
        security_id=value["security_id"],
        session_date=value["session_date"],
        observed_at=value["observed_at"],
        price=value["price"],
        adjustment_status=value["adjustment_status"],
        source_artifact_id=value["source_artifact_id"],
        source_artifact_sha256=value["source_artifact_sha256"],
        unavailable_reason=value["unavailable_reason"],
    )
    if rebuilt.canonical_json_bytes() != _canonical_json_bytes(value):
        raise PointInTimeDataError(
            "execution price twin bytes do not match canonical rebuild"
        )
    return rebuilt


@dataclasses.dataclass(frozen=True, slots=True, init=False)
class SourceBoundExecutionOutcome:
    """One exact next-open, five-session, source-bound outcome."""

    outcome_id: str
    outcome_sha256: str
    decision_event_id: str
    security_id: str
    symbol: str
    decision_market_date: str
    decision_cutoff: str
    entry_session_date: str
    entry_session_open_at: str
    exit_session_date: str
    holding_session_dates: tuple[str, ...]
    market_calendar_id: str
    market_calendar_sha256: str
    market_calendar_raw_artifact_id: str
    market_calendar_raw_artifact_sha256: str
    adjusted_price_window_id: str
    adjusted_price_window_sha256: str
    security_identity_sha256: str
    successor_security_id: str | None
    successor_security_sha256: str | None
    corporate_action_set_id: str
    corporate_action_set_sha256: str
    corporate_actions: tuple[CorporateAction, ...]
    terminal_proceeds: TerminalProceeds | None
    price_twins: tuple[ExecutionPriceTwin, ...]
    status: str
    unavailable_reason: str | None
    exit_value: str | None
    gross_return: str | None

    def __init__(self, *args: object, **kwargs: object) -> None:
        raise TypeError("SourceBoundExecutionOutcome instances require its builder")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": _SCHEMA,
            "outcome_id": self.outcome_id,
            "outcome_sha256": self.outcome_sha256,
            "decision_event_id": self.decision_event_id,
            "security_id": self.security_id,
            "symbol": self.symbol,
            "decision_market_date": self.decision_market_date,
            "decision_cutoff": self.decision_cutoff,
            "entry_session_date": self.entry_session_date,
            "entry_session_open_at": self.entry_session_open_at,
            "exit_session_date": self.exit_session_date,
            "holding_session_dates": list(self.holding_session_dates),
            "market_calendar_id": self.market_calendar_id,
            "market_calendar_sha256": self.market_calendar_sha256,
            "market_calendar_raw_artifact_id": self.market_calendar_raw_artifact_id,
            "market_calendar_raw_artifact_sha256": self.market_calendar_raw_artifact_sha256,
            "adjusted_price_window_id": self.adjusted_price_window_id,
            "adjusted_price_window_sha256": self.adjusted_price_window_sha256,
            "security_identity_sha256": self.security_identity_sha256,
            "successor_security_id": self.successor_security_id,
            "successor_security_sha256": self.successor_security_sha256,
            "corporate_action_set_id": self.corporate_action_set_id,
            "corporate_action_set_sha256": self.corporate_action_set_sha256,
            "corporate_actions": [item.to_dict() for item in self.corporate_actions],
            "terminal_proceeds": (
                None if self.terminal_proceeds is None else self.terminal_proceeds.to_dict()
            ),
            "price_twins": [item.to_dict() for item in self.price_twins],
            "status": self.status,
            "unavailable_reason": self.unavailable_reason,
            "exit_value": self.exit_value,
            "gross_return": self.gross_return,
            **_AUTHORITY,
        }

    def canonical_json_bytes(self) -> bytes:
        return _canonical_json_bytes(self.to_dict())

    def price_for(self, basis: str) -> str | None:
        for twin in self.price_twins:
            if twin.price_basis == basis:
                return twin.price
        raise PointInTimeDataError("execution price basis is not registered")


_OUTCOME_FIELDS = frozenset(
    tuple(field.name for field in dataclasses.fields(SourceBoundExecutionOutcome))
    + ("schema_version",)
    + tuple(_AUTHORITY)
)


def _new_outcome(**fields: object) -> SourceBoundExecutionOutcome:
    value = object.__new__(SourceBoundExecutionOutcome)
    for field in dataclasses.fields(SourceBoundExecutionOutcome):
        object.__setattr__(value, field.name, fields[field.name])
    return value


def build_source_bound_execution_outcome(
    *,
    decision_event_id: str,
    decision_market_date: str,
    decision_cutoff: str,
    security: SecurityIdentity,
    market_calendar: MarketSessionCalendar,
    adjusted_price_window: SourceBoundAdjustedPriceWindow,
    entry_session_open_at: str,
    corporate_actions: tuple[CorporateAction, ...],
    terminal_proceeds: TerminalProceeds | None,
    price_twins: tuple[ExecutionPriceTwin, ...],
    successor_security: SecurityIdentity | None = None,
) -> SourceBoundExecutionOutcome:
    """Build a deterministic outcome without filesystem or provider authority."""

    event_id = _identifier(decision_event_id, label="decision_event_id")
    if not event_id.startswith("decision-event-"):
        raise PointInTimeDataError("decision_event_id is not canonical")
    market_date = _date(decision_market_date, label="decision_market_date")
    cutoff = _timestamp(decision_cutoff, label="decision_cutoff")
    if cutoff[:10] != market_date:
        raise PointInTimeDataError("decision cutoff must occur on its market date")
    if type(security) is not SecurityIdentity:
        raise PointInTimeDataError("security must be an exact SecurityIdentity")
    identity = validate_security_identity(security.to_dict())
    if type(market_calendar) is not MarketSessionCalendar:
        raise PointInTimeDataError(
            "market_calendar must be an exact MarketSessionCalendar"
        )
    calendar = validate_market_session_calendar(market_calendar.to_dict())
    if type(adjusted_price_window) is not SourceBoundAdjustedPriceWindow:
        raise PointInTimeDataError(
            "adjusted_price_window must be an exact source-bound window"
        )
    window = validate_five_session_adjusted_price_window(
        value=adjusted_price_window.to_dict(),
        market_calendar=calendar,
        decision_market_date=market_date,
    )
    if window.security_id != identity.security_id or window.symbol != identity.symbol:
        raise PointInTimeDataError(
            "execution outcome must retain the feature security identity"
        )
    official_open = _timestamp(
        entry_session_open_at,
        label="entry_session_open_at",
    )
    if official_open[:10] != window.entry_date:
        raise PointInTimeDataError(
            "official entry-session open must occur on the entry session"
        )

    if type(corporate_actions) is not tuple:
        raise PointInTimeDataError("corporate_actions must be an exact tuple")
    actions = tuple(validate_corporate_action(item.to_dict()) for item in corporate_actions)
    if any(item.security_id != identity.security_id for item in actions):
        raise PointInTimeDataError(
            "corporate actions must retain the feature security identity"
        )
    action_order = tuple(
        (item.effective_date, item.action_type, item.source_artifact_id)
        for item in actions
    )
    if action_order != tuple(sorted(action_order)) or len(set(action_order)) != len(action_order):
        raise PointInTimeDataError("corporate actions must be canonical and unique")
    if any(
        not window.entry_date <= item.effective_date <= window.exit_date
        for item in actions
    ):
        raise PointInTimeDataError(
            "corporate actions must fall inside the five-session holding window"
        )

    terminal_actions = tuple(
        item
        for item in actions
        if item.action_type in {"merger", "acquisition", "delisting"}
    )
    transition_actions = tuple(
        item
        for item in actions
        if item.action_type
        in {"merger", "acquisition", "symbol_change", "delisting"}
    )
    if identity.effective_from > market_date:
        raise PointInTimeDataError(
            "security identity is not effective on the decision market date"
        )
    if identity.effective_to is None:
        if transition_actions or identity.successor_security_id is not None:
            raise PointInTimeDataError(
                "terminal or successor actions require a terminating identity"
            )
    else:
        transition_dates = {item.effective_date for item in transition_actions}
        if identity.effective_to not in transition_dates:
            raise PointInTimeDataError(
                "terminating security identity is not linked to a retained action"
            )
        if not window.entry_date <= identity.effective_to <= window.exit_date:
            raise PointInTimeDataError(
                "terminating security identity must cover entry through its action"
            )

    successor = None
    successor_digest = None
    if identity.successor_security_id is not None:
        if type(successor_security) is not SecurityIdentity:
            raise PointInTimeDataError(
                "successor identity evidence is required for a successor security"
            )
        successor = validate_security_identity(successor_security.to_dict())
        if (
            successor.security_id != identity.successor_security_id
            or successor.effective_from > window.exit_date
            or (
                successor.effective_to is not None
                and successor.effective_to < window.exit_date
            )
        ):
            raise PointInTimeDataError(
                "successor security identity does not cover the remaining window"
            )
        successor_digest = _sha256(successor.to_dict())
    elif successor_security is not None:
        raise PointInTimeDataError(
            "successor identity cannot be supplied without a bound successor"
        )

    action_set_material = {
        "security_id": identity.security_id,
        "entry_session_date": window.entry_date,
        "exit_session_date": window.exit_date,
        "actions": [item.to_dict() for item in actions],
        "completeness_status": "complete",
    }
    action_set_id = "corporate-action-set-" + _sha256(action_set_material)
    action_set_sha256 = _sha256(
        {**action_set_material, "corporate_action_set_id": action_set_id}
    )

    if type(price_twins) is not tuple or len(price_twins) != len(_TWIN_BASES):
        raise PointInTimeDataError("execution outcome requires the exact four price twins")
    twins = tuple(validate_execution_price_twin(item.to_dict()) for item in price_twins)
    if tuple(item.price_basis for item in twins) != _TWIN_BASES:
        raise PointInTimeDataError("execution price twins are not in registered order")
    if any(
        item.security_id != identity.security_id
        or item.session_date != window.entry_date
        for item in twins
    ):
        raise PointInTimeDataError(
            "execution price twins must bind the entry security and session"
        )
    next_open = twins[_TWIN_BASES.index("next_open")]
    if next_open.status == "available" and next_open.observed_at != official_open:
        raise PointInTimeDataError(
            "next-open observation must equal the official session open"
        )
    proceeds = None
    status = "completed"
    unavailable_reason = None
    exit_value: str | None = window.exit_close
    if terminal_proceeds is not None:
        if type(terminal_proceeds) is not TerminalProceeds:
            raise PointInTimeDataError(
                "terminal_proceeds must be an exact TerminalProceeds"
            )
        proceeds = validate_terminal_proceeds(terminal_proceeds.to_dict())
        if (
            proceeds.security_id != identity.security_id
            or not terminal_actions
            or proceeds.effective_date not in {
                item.effective_date for item in terminal_actions
            }
        ):
            raise PointInTimeDataError(
                "terminal proceeds do not match the retained terminal action"
            )
        if identity.terminal_proceeds_artifact_id != proceeds.source_artifact_id:
            raise PointInTimeDataError(
                "terminal proceeds artifact is not linked by the security identity"
            )
        exit_value = proceeds.amount_per_share
    elif terminal_actions:
        status = "unavailable"
        unavailable_reason = "required_terminal_proceeds_unproven"
        exit_value = None

    if next_open.status != "available" or next_open.price is None:
        status = "unavailable"
        unavailable_reason = (
            "required_next_open_and_terminal_proceeds_unproven"
            if terminal_actions and proceeds is None
            else "required_next_open_unproven"
        )
        exit_value = None

    gross_return = None
    if exit_value is not None and next_open.price is not None:
        gross_return = _decimal_text(
            (Decimal(exit_value) - Decimal(next_open.price))
            / Decimal(next_open.price)
        )
    material = {
        "schema_version": _SCHEMA,
        "decision_event_id": event_id,
        "security_id": identity.security_id,
        "symbol": identity.symbol,
        "decision_market_date": market_date,
        "decision_cutoff": cutoff,
        "entry_session_date": window.entry_date,
        "entry_session_open_at": official_open,
        "exit_session_date": window.exit_date,
        "holding_session_dates": [item[0] for item in window.daily_closes],
        "market_calendar_id": calendar.calendar_id,
        "market_calendar_sha256": calendar.calendar_sha256,
        "market_calendar_raw_artifact_id": calendar.raw_artifact_id,
        "market_calendar_raw_artifact_sha256": calendar.raw_artifact_sha256,
        "adjusted_price_window_id": window.window_id,
        "adjusted_price_window_sha256": window.window_sha256,
        "security_identity_sha256": _sha256(identity.to_dict()),
        "successor_security_id": None if successor is None else successor.security_id,
        "successor_security_sha256": successor_digest,
        "corporate_action_set_id": action_set_id,
        "corporate_action_set_sha256": action_set_sha256,
        "corporate_actions": [item.to_dict() for item in actions],
        "terminal_proceeds": None if proceeds is None else proceeds.to_dict(),
        "price_twins": [item.to_dict() for item in twins],
        "status": status,
        "unavailable_reason": unavailable_reason,
        "exit_value": exit_value,
        "gross_return": gross_return,
        **_AUTHORITY,
    }
    outcome_id = "source-bound-execution-outcome-" + _sha256(material)
    digest = _sha256({**material, "outcome_id": outcome_id})
    return _new_outcome(
        outcome_id=outcome_id,
        outcome_sha256=digest,
        decision_event_id=event_id,
        security_id=identity.security_id,
        symbol=identity.symbol,
        decision_market_date=market_date,
        decision_cutoff=cutoff,
        entry_session_date=window.entry_date,
        entry_session_open_at=official_open,
        exit_session_date=window.exit_date,
        holding_session_dates=tuple(item[0] for item in window.daily_closes),
        market_calendar_id=calendar.calendar_id,
        market_calendar_sha256=calendar.calendar_sha256,
        market_calendar_raw_artifact_id=calendar.raw_artifact_id,
        market_calendar_raw_artifact_sha256=calendar.raw_artifact_sha256,
        adjusted_price_window_id=window.window_id,
        adjusted_price_window_sha256=window.window_sha256,
        security_identity_sha256=_sha256(identity.to_dict()),
        successor_security_id=None if successor is None else successor.security_id,
        successor_security_sha256=successor_digest,
        corporate_action_set_id=action_set_id,
        corporate_action_set_sha256=action_set_sha256,
        corporate_actions=actions,
        terminal_proceeds=proceeds,
        price_twins=twins,
        status=status,
        unavailable_reason=unavailable_reason,
        exit_value=exit_value,
        gross_return=gross_return,
    )


def validate_source_bound_execution_outcome(
    value: object,
    *,
    security: SecurityIdentity,
    market_calendar: MarketSessionCalendar,
    adjusted_price_window: SourceBoundAdjustedPriceWindow,
    successor_security: SecurityIdentity | None = None,
) -> SourceBoundExecutionOutcome:
    """Canonical-rebuild an outcome against its separately retained receipts."""

    if not isinstance(value, Mapping) or set(value) != _OUTCOME_FIELDS:
        raise PointInTimeDataError("source-bound execution outcome fields are invalid")
    if value["schema_version"] != _SCHEMA or any(
        value[key] != expected for key, expected in _AUTHORITY.items()
    ):
        raise PointInTimeDataError(
            "source-bound execution outcome schema or authority is invalid"
        )
    raw_actions = value["corporate_actions"]
    raw_twins = value["price_twins"]
    if type(raw_actions) is not list or type(raw_twins) is not list:
        raise PointInTimeDataError("source-bound execution outcome evidence is invalid")
    actions = tuple(validate_corporate_action(item) for item in raw_actions)
    twins = tuple(validate_execution_price_twin(item) for item in raw_twins)
    proceeds = (
        None
        if value["terminal_proceeds"] is None
        else validate_terminal_proceeds(value["terminal_proceeds"])
    )
    rebuilt = build_source_bound_execution_outcome(
        decision_event_id=value["decision_event_id"],
        decision_market_date=value["decision_market_date"],
        decision_cutoff=value["decision_cutoff"],
        security=security,
        market_calendar=market_calendar,
        adjusted_price_window=adjusted_price_window,
        entry_session_open_at=value["entry_session_open_at"],
        corporate_actions=actions,
        terminal_proceeds=proceeds,
        price_twins=twins,
        successor_security=successor_security,
    )
    if rebuilt.canonical_json_bytes() != _canonical_json_bytes(value):
        raise PointInTimeDataError(
            "source-bound execution outcome bytes do not match canonical rebuild"
        )
    return rebuilt
