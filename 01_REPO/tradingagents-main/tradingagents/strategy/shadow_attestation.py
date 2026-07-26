"""Immutable reconciled paper/shadow strategy evidence."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import (
    ROUND_DOWN,
    ROUND_HALF_EVEN,
    Context,
    Decimal,
    DecimalException,
    DivisionByZero,
    InvalidOperation,
    Overflow,
    localcontext,
)
from pathlib import Path
from zoneinfo import ZoneInfo

from tradingagents.orchestration.authority import ActionClass, authority_for
from tradingagents.strategy._immutable_evidence_store import (
    PAPER_EXECUTION_AUTHORIZATION_KIND,
    PAPER_SHADOW_ATTESTATION_KIND,
    PAPER_SHADOW_OBSERVATION_KIND,
    EvidenceCandidate,
    EvidenceEnvelope,
    ImmutableStrategyEvidenceStore,
)
from tradingagents.strategy.compiler import PaperDecisionAction
from tradingagents.strategy.paper_execution_authorization import (
    AuthorizedPaperOrderRequest,
    _authorization_from_envelope,
    _staged_with_registration_from_snapshot,
)
from tradingagents.strategy.promotion_evidence import (
    StrategyPromotionEvidence,
    require_active_evaluation_runtime,
)
from tradingagents.strategy.staged_intent import StagedPaperIntent, _promotion_from_snapshot

PAPER_ORDER_RECEIPT_SCHEMA_VERSION = 1
PAPER_RECONCILIATION_RECEIPT_SCHEMA_VERSION = 1
ADMITTED_PAPER_SHADOW_OBSERVATION_SCHEMA_VERSION = 1
STRATEGY_SHADOW_ATTESTATION_SCHEMA_VERSION = 1
SHADOW_DECIMAL_PRECISION = 80
SHADOW_MONEY_DECIMAL_PRECISION = 96
SHADOW_DECIMAL_EMIN = -999
SHADOW_DECIMAL_EMAX = 999
SHADOW_DECIMAL_MAX_UTF8_BYTES = 128
SHADOW_DECIMAL_MAX_SIGNIFICANT_DIGITS = 34
SHADOW_DECIMAL_MAX_DECIMAL_PLACES = 12
SHADOW_DECIMAL_MAX_ADJUSTED_EXPONENT = 33
SHADOW_DERIVED_FRACTION_MAX_UTF8_BYTES = 128
SHADOW_DERIVED_FRACTION_MAX_COEFFICIENT_DIGITS = 80
SHADOW_DERIVED_FRACTION_MAX_DECIMAL_PLACES = 125
SHADOW_DERIVED_FRACTION_MIN_ADJUSTED_EXPONENT = -46
SHADOW_DERIVED_FRACTION_MAX_ADJUSTED_EXPONENT = 45
SHADOW_DERIVED_MONEY_MAX_UTF8_BYTES = 128
SHADOW_DERIVED_MONEY_MAX_COEFFICIENT_DIGITS = 74
SHADOW_DERIVED_MONEY_MAX_DECIMAL_PLACES = 2
SHADOW_DERIVED_MONEY_MAX_ADJUSTED_EXPONENT = 71
SHADOW_ATTESTATION_MAX_OBSERVATIONS = 4096

HOLD_SHADOW_OBSERVATION_GATE_ORDER = ("no_order_expected",)
BUY_SHADOW_OBSERVATION_GATE_ORDER = (
    "terminal_filled",
    "fill_respected_limit",
    "operationally_reconciled",
)
SHADOW_GATE_ORDER = (
    "internal_evidence_complete",
    "minimum_tracked_sessions",
    "all_intents_current_when_observed",
    "all_buy_intents_paper_only",
    "all_order_fields_match",
    "all_buy_intents_terminal_filled",
    "all_reconciliations_clean",
    "at_least_one_reconciled_buy",
)
SHADOW_OBSERVATION_ISSUE_BY_GATE = {
    "terminal_filled": "buy_not_terminal_filled",
    "fill_respected_limit": "fill_above_staged_limit",
    "operationally_reconciled": "reconciliation_not_clean",
}
SHADOW_ATTESTATION_ISSUE_BY_GATE = {
    "internal_evidence_complete": "internal_evidence_incomplete",
    "minimum_tracked_sessions": "insufficient_shadow_sessions",
    "all_intents_current_when_observed": "intent_not_current_when_observed",
    "all_buy_intents_paper_only": "non_paper_buy_intent",
    "all_order_fields_match": "order_fields_mismatch",
    "all_buy_intents_terminal_filled": "buy_intent_not_terminal_filled",
    "all_reconciliations_clean": "reconciliation_not_clean",
    "at_least_one_reconciled_buy": "no_reconciled_buy",
}
_ASCII_WHITESPACE = " \t\n\r\v\f"
_SESSION_DATE_PATTERN = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_CANONICAL_MONEY_PATTERN = re.compile(r"(?:0|[1-9][0-9]*)\.[0-9]{2}")
_LOWER_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
_LOWER_COMMIT_PATTERN = re.compile(r"[0-9a-f]{40}")
_CLIENT_ORDER_ID_PATTERN = re.compile(r"ta-p-[0-9a-f]{40}")
_GENOME_ID_PATTERN = re.compile(
    r"genome-(?:current-aggressive|pullback-support|"
    r"catalyst-relative-strength)-[0-9a-f]{64}"
)

_PAPER_ORDER_RECEIPT_STRING_FIELDS = (
    "authorization_id",
    "authorization_sha256",
    "logical_order_sha256",
    "client_order_id",
    "broker_order_id",
    "paper_account_fingerprint",
    "account_environment",
    "symbol",
    "side",
    "order_type",
    "tif",
    "requested_notional_usd",
    "requested_limit_price",
    "status",
    "filled_qty",
    "filled_avg_price",
    "fees_usd",
    "submitted_at",
    "last_seen_at",
    "submitted_by_role",
)
_PAPER_ORDER_RECEIPT_KEYS = frozenset(
    (
        "schema_version",
        *_PAPER_ORDER_RECEIPT_STRING_FIELDS,
        "analysis_only",
        "paper_only",
        "execution_authority",
        "can_submit_orders",
    )
)
_PAPER_RECONCILIATION_RECEIPT_STRING_FIELDS = (
    "authorization_id",
    "authorization_sha256",
    "logical_order_sha256",
    "client_order_id",
    "broker_order_id",
    "paper_account_fingerprint",
    "observed_status",
    "observed_symbol",
    "observed_side",
    "observed_order_type",
    "observed_tif",
    "observed_requested_notional_usd",
    "observed_requested_limit_price",
    "observed_filled_qty",
    "observed_filled_avg_price",
    "observed_fees_usd",
    "checked_at",
    "verified_by_role",
)
_PAPER_RECONCILIATION_RECEIPT_KEYS = frozenset(
    (
        "schema_version",
        *_PAPER_RECONCILIATION_RECEIPT_STRING_FIELDS,
        "read_only",
        "broker_write_calls",
        "analysis_only",
        "paper_only",
        "execution_authority",
        "can_submit_orders",
    )
)
_OBSERVATION_STRING_FIELDS = (
    "shadow_observation_id",
    "staged_intent_id",
    "staged_intent_sha256",
    "promotion_evidence_id",
    "genome_id",
    "genome_canonical_sha256",
    "evaluation_code_commit",
    "evaluation_runtime_sha256",
    "session_date",
    "observed_at",
    "decision_action",
    "adverse_fill_vs_reference_fraction",
    "verified_by_role",
    "effective_at",
    "recorded_at",
)
_OBSERVATION_OPTIONAL_STRING_FIELDS = (
    "authorization_id",
    "authorization_sha256",
    "paper_account_fingerprint",
    "receipt_sha256",
    "reconciliation_sha256",
)
_OBSERVATION_KEYS = frozenset(
    (
        "schema_version",
        *_OBSERVATION_STRING_FIELDS,
        *_OBSERVATION_OPTIONAL_STRING_FIELDS,
        "paper_order_receipt",
        "reconciliation_receipt",
        "gates",
        "issues",
        "operationally_reconciled",
        "analysis_only",
        "paper_only",
        "execution_authority",
        "can_submit_orders",
    )
)
_ATTESTATION_STRING_FIELDS = (
    "shadow_attestation_id",
    "registration_id",
    "promotion_evidence_id",
    "promotion_evidence_sha256",
    "genome_id",
    "genome_canonical_sha256",
    "evaluation_code_commit",
    "evaluation_runtime_sha256",
    "first_session_date",
    "last_session_date",
    "total_requested_notional_usd",
    "total_filled_notional_usd",
    "total_fees_usd",
    "worst_adverse_fill_vs_reference_fraction",
    "assembled_by_role",
    "effective_at",
    "recorded_at",
)
_ATTESTATION_COUNT_FIELDS = (
    "tracked_sessions",
    "total_intents",
    "hold_intents",
    "buy_intents",
    "reconciled_buy_intents",
    "filled_buy_intents",
)
_ATTESTATION_KEYS = frozenset(
    (
        "schema_version",
        *_ATTESTATION_STRING_FIELDS,
        *_ATTESTATION_COUNT_FIELDS,
        "paper_account_fingerprint",
        "shadow_observation_ids",
        "shadow_observation_sha256s",
        "gates",
        "issues",
        "shadow_sessions_sufficient",
        "reconciliation_confirmed",
        "analysis_only",
        "paper_only",
        "execution_authority",
        "can_submit_orders",
    )
)


def _canonical_json_bytes(payload: Mapping[str, object]) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _require_exact_fields(
    payload: Mapping[str, object],
    expected: frozenset[str],
    *,
    label: str,
) -> dict[str, object]:
    if not isinstance(payload, Mapping):
        raise TypeError(f"{label} must be a mapping")
    values = dict(payload)
    if set(values) != expected:
        raise ValueError(f"{label} fields do not match schema")
    if any(type(key) is not str for key in values):
        raise TypeError(f"{label} keys must be exact strings")
    return values


def _require_exact_string(value: object, *, label: str) -> str:
    if type(value) is not str:
        raise TypeError(f"{label} must be an exact string")
    return value


def _require_fixed_bool(value: object, expected: bool, *, label: str) -> None:
    if value is not expected:
        raise ValueError(f"{label} is fixed")


def _require_optional_exact_string(
    value: object,
    *,
    label: str,
) -> str | None:
    if value is None:
        return None
    return _require_exact_string(value, label=label)


def _require_digest(value: object, *, label: str) -> str:
    if (
        type(value) is not str
        or _LOWER_SHA256_PATTERN.fullmatch(value) is None
    ):
        raise ValueError(f"{label} must be a full lowercase SHA-256")
    return value


def _require_optional_digest(
    value: object,
    *,
    label: str,
) -> str | None:
    if value is None:
        return None
    return _require_digest(value, label=label)


def _require_object_id(value: object, *, kind: str, label: str) -> str:
    if (
        type(value) is not str
        or re.fullmatch(rf"{re.escape(kind)}-[0-9a-f]{{64}}", value) is None
    ):
        raise ValueError(f"{label} must be a full {kind} object ID")
    return value


def _require_optional_object_id(
    value: object,
    *,
    kind: str,
    label: str,
) -> str | None:
    if value is None:
        return None
    return _require_object_id(value, kind=kind, label=label)


def _require_commit(value: object, *, label: str) -> str:
    if (
        type(value) is not str
        or _LOWER_COMMIT_PATTERN.fullmatch(value) is None
    ):
        raise ValueError(f"{label} must be a lowercase 40-hex commit")
    return value


def _require_genome_id(value: object, *, label: str) -> str:
    if type(value) is not str or _GENOME_ID_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{label} must be a full strategy genome ID")
    return value


def _require_client_order_id(
    value: object,
    *,
    logical_order_sha256: str,
) -> str:
    if (
        type(value) is not str
        or _CLIENT_ORDER_ID_PATTERN.fullmatch(value) is None
        or value != f"ta-p-{logical_order_sha256[:40]}"
    ):
        raise ValueError("client_order_id does not match logical order digest")
    return value


def _require_symbol(value: object, *, label: str) -> str:
    if type(value) is not str:
        raise TypeError(f"{label} must be an exact string")
    if (
        value.strip() != value
        or not 1 <= len(value) <= 15
        or not "A" <= value[0] <= "Z"
        or any(
            not (
                "A" <= character <= "Z"
                or "0" <= character <= "9"
                or character in ".-"
            )
            for character in value[1:]
        )
    ):
        raise ValueError(f"{label} must be an uppercase ASCII ticker token")
    return value


def _require_role(value: object, *, expected: str, label: str) -> str:
    if type(value) is not str or value != expected:
        raise ValueError(f"{label} must be {expected!r}")
    return value


def _expected_object_id(
    *,
    kind: str,
    effective_at: str,
    payload: Mapping[str, object],
) -> str:
    digest = hashlib.sha256(
        _canonical_json_bytes(
            {
                "kind": kind,
                "effective_at": effective_at,
                "payload": payload,
            }
        )
    ).hexdigest()
    return f"{kind}-{digest}"


def _require_exact_int(value: object, *, label: str) -> int:
    if type(value) is not int:
        raise TypeError(f"{label} must be an exact integer")
    if value < 0:
        raise ValueError(f"{label} must be nonnegative")
    return value


def _require_constructor_gates(
    gates: object,
    *,
    order: tuple[str, ...],
) -> tuple[tuple[str, bool], ...]:
    if type(gates) is not tuple:
        raise TypeError("gates must be an exact tuple")
    if any(type(gate) is not tuple or len(gate) != 2 for gate in gates):
        raise TypeError("each gate must be an exact two-tuple")
    normalized: list[tuple[str, bool]] = []
    for name, passed in gates:
        if type(name) is not str or type(passed) is not bool:
            raise TypeError("gate values must be exact string and bool")
        normalized.append((name, passed))
    result = tuple(normalized)
    if tuple(name for name, _ in result) != order:
        raise ValueError("gates do not match frozen order")
    return result


def _gates_from_json(
    value: object,
    *,
    order: tuple[str, ...],
) -> tuple[tuple[str, bool], ...]:
    if type(value) is not list:
        raise TypeError("serialized gates must be an exact list")
    gates: list[tuple[str, bool]] = []
    for gate in value:
        if type(gate) is not list or len(gate) != 2:
            raise TypeError("serialized gate must be an exact two-list")
        name, passed = gate
        if type(name) is not str or type(passed) is not bool:
            raise TypeError("serialized gate values have wrong types")
        gates.append((name, passed))
    return _require_constructor_gates(tuple(gates), order=order)


def _issues_from_json(value: object) -> tuple[str, ...]:
    if type(value) is not list:
        raise TypeError("serialized issues must be an exact list")
    if any(type(issue) is not str for issue in value):
        raise TypeError("serialized issues must contain exact strings")
    return tuple(value)


def _require_constructor_issues(
    issues: object,
    *,
    expected: tuple[str, ...],
) -> tuple[str, ...]:
    if type(issues) is not tuple:
        raise TypeError("issues must be an exact tuple")
    if any(type(issue) is not str for issue in issues):
        raise TypeError("issues must contain exact strings")
    if issues != expected:
        raise ValueError("issues do not match failed gates in frozen order")
    return issues


def _string_tuple_from_json(value: object, *, label: str) -> tuple[str, ...]:
    if type(value) is not list:
        raise TypeError(f"serialized {label} must be an exact list")
    if any(type(item) is not str for item in value):
        raise TypeError(f"serialized {label} must contain exact strings")
    return tuple(value)


def _require_constructor_string_tuple(
    value: object,
    *,
    label: str,
) -> tuple[str, ...]:
    if type(value) is not tuple:
        raise TypeError(f"{label} must be an exact tuple")
    if any(type(item) is not str for item in value):
        raise TypeError(f"{label} must contain exact strings")
    return value


def _require_broker_order_id(value: object) -> str:
    broker_order_id = _require_exact_string(
        value,
        label="broker_order_id",
    )
    if (
        not broker_order_id
        or broker_order_id[0] in _ASCII_WHITESPACE
        or broker_order_id[-1] in _ASCII_WHITESPACE
        or not broker_order_id.isprintable()
    ):
        raise ValueError("broker_order_id must be nonblank printable text")
    try:
        encoded = broker_order_id.encode("utf-8")
    except UnicodeEncodeError:
        raise ValueError("broker_order_id must be valid UTF-8 text") from None
    if len(encoded) > 128:
        raise ValueError("broker_order_id exceeds 128 UTF-8 bytes")
    return broker_order_id


def _fraction_context() -> Context:
    context = Context(
        prec=SHADOW_DECIMAL_PRECISION,
        rounding=ROUND_HALF_EVEN,
        Emin=SHADOW_DECIMAL_EMIN,
        Emax=SHADOW_DECIMAL_EMAX,
    )
    for signal in (InvalidOperation, DivisionByZero, Overflow):
        context.traps[signal] = True
    return context


def _money_context() -> Context:
    context = Context(
        prec=SHADOW_MONEY_DECIMAL_PRECISION,
        rounding=ROUND_HALF_EVEN,
        Emin=SHADOW_DECIMAL_EMIN,
        Emax=SHADOW_DECIMAL_EMAX,
    )
    for signal in (InvalidOperation, DivisionByZero, Overflow):
        context.traps[signal] = True
    return context


def _plain_decimal(value: Decimal) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text in {"", "-0"} else text


def _require_decimal_text(value: object, *, label: str) -> str:
    text = _require_exact_string(value, label=label)
    try:
        encoded = text.encode("utf-8")
    except UnicodeEncodeError:
        raise ValueError(f"{label} must be valid UTF-8 text") from None
    if len(encoded) > SHADOW_DECIMAL_MAX_UTF8_BYTES:
        raise ValueError(f"{label} exceeds decimal byte bound")
    if not text or "e" in text.lower() or text.startswith("+"):
        raise ValueError(f"{label} must be canonical fixed-point")
    return text


def _decimal_from_text(value: object, *, label: str) -> tuple[str, Decimal]:
    text = _require_decimal_text(value, label=label)
    try:
        number = Decimal(text)
    except DecimalException:
        raise ValueError(f"{label} must be a decimal string") from None
    if not number.is_finite():
        raise ValueError(f"{label} must be finite")
    return text, number


def _require_operand_decimal(
    value: object,
    *,
    label: str,
    positive: bool = False,
    canonical_money: bool = False,
) -> Decimal:
    text, number = _decimal_from_text(value, label=label)
    if canonical_money:
        if _CANONICAL_MONEY_PATTERN.fullmatch(text) is None:
            raise ValueError(f"{label} must contain exactly two decimals")
    elif _plain_decimal(number) != text:
        raise ValueError(f"{label} must be canonical fixed-point")
    decimal_tuple = number.as_tuple()
    exponent = decimal_tuple.exponent
    if (
        not isinstance(exponent, int)
        or len(decimal_tuple.digits)
        > SHADOW_DECIMAL_MAX_SIGNIFICANT_DIGITS
        or max(0, -exponent) > SHADOW_DECIMAL_MAX_DECIMAL_PLACES
        or number.adjusted() > SHADOW_DECIMAL_MAX_ADJUSTED_EXPONENT
    ):
        raise ValueError(f"{label} exceeds operand decimal bounds")
    if positive:
        if number <= 0:
            raise ValueError(f"{label} must be positive")
    elif number < 0:
        raise ValueError(f"{label} must be nonnegative")
    return number


def _require_derived_fraction(value: object, *, label: str) -> Decimal:
    text, number = _decimal_from_text(value, label=label)
    if _plain_decimal(number) != text:
        raise ValueError(f"{label} must be canonical fixed-point")
    decimal_tuple = number.as_tuple()
    exponent = decimal_tuple.exponent
    if (
        not isinstance(exponent, int)
        or len(decimal_tuple.digits)
        > SHADOW_DERIVED_FRACTION_MAX_COEFFICIENT_DIGITS
        or max(0, -exponent)
        > SHADOW_DERIVED_FRACTION_MAX_DECIMAL_PLACES
        or number.adjusted()
        < SHADOW_DERIVED_FRACTION_MIN_ADJUSTED_EXPONENT
        or number.adjusted()
        > SHADOW_DERIVED_FRACTION_MAX_ADJUSTED_EXPONENT
        or number < 0
    ):
        raise ValueError(f"{label} exceeds derived fraction bounds")
    return number


def _require_derived_money(value: object, *, label: str) -> Decimal:
    text, number = _decimal_from_text(value, label=label)
    if _plain_decimal(number) != text:
        raise ValueError(f"{label} must be canonical fixed-point")
    decimal_tuple = number.as_tuple()
    exponent = decimal_tuple.exponent
    if (
        not isinstance(exponent, int)
        or len(decimal_tuple.digits)
        > SHADOW_DERIVED_MONEY_MAX_COEFFICIENT_DIGITS
        or max(0, -exponent) > SHADOW_DERIVED_MONEY_MAX_DECIMAL_PLACES
        or number.adjusted() > SHADOW_DERIVED_MONEY_MAX_ADJUSTED_EXPONENT
        or number < 0
    ):
        raise ValueError(f"{label} exceeds derived money bounds")
    return number


def _require_status_matrix(
    *,
    status: str,
    filled_qty: str,
    filled_avg_price: str,
    fees_usd: str,
) -> None:
    if status not in {
        "filled",
        "partially_filled",
        "rejected",
        "canceled",
        "expired",
    }:
        raise ValueError("paper order status is not supported")
    quantity = _require_operand_decimal(filled_qty, label="filled_qty")
    average = _require_operand_decimal(
        filled_avg_price,
        label="filled_avg_price",
    )
    fees = _require_operand_decimal(fees_usd, label="fees_usd")
    if (quantity == 0) is not (average == 0):
        raise ValueError("filled quantity is zero iff average price is zero")
    if status in {"filled", "partially_filled"}:
        if quantity <= 0 or average <= 0:
            raise ValueError(f"{status} requires a positive fill")
    elif status == "rejected":
        if quantity != 0 or average != 0 or fees != 0:
            raise ValueError("rejected requires zero fill and fees")
    elif quantity == 0 and fees != 0:
        raise ValueError(f"{status} without a fill requires zero fees")


def _datetime_text(value: object, *, label: str) -> str:
    if type(value) is not dt.datetime:
        raise TypeError(f"{label} must be an exact datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")
    if value.microsecond != 0:
        raise ValueError(f"{label} must be whole-second normalized")
    utc_value = value.astimezone(dt.timezone.utc)
    return utc_value.isoformat(timespec="seconds")


def _required_verify_owner(actor_role: object) -> str:
    verdict = authority_for(ActionClass.VERIFY)
    if (
        not verdict.allowed
        or verdict.human_required
        or type(verdict.owner_role) is not str
    ):
        raise ValueError("VERIFY authority is not an allowed nonhuman role")
    if type(actor_role) is not str or actor_role != verdict.owner_role:
        raise ValueError(f"actor_role must be {verdict.owner_role}")
    return verdict.owner_role


def _required_submit_owner() -> str:
    verdict = authority_for(ActionClass.ORDER_SUBMIT)
    if (
        not verdict.allowed
        or verdict.human_required
        or type(verdict.owner_role) is not str
    ):
        raise ValueError(
            "ORDER_SUBMIT authority is not an allowed nonhuman role"
        )
    return verdict.owner_role


def _require_canonical_utc(value: object, *, label: str) -> dt.datetime:
    if type(value) is not str:
        raise TypeError(f"{label} must be an exact timestamp string")
    try:
        parsed = dt.datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{label} must be canonical UTC") from exc
    if (
        parsed.tzinfo is None
        or parsed.utcoffset() != dt.timedelta(0)
        or parsed.microsecond != 0
        or parsed.isoformat(timespec="seconds") != value
    ):
        raise ValueError(f"{label} must be canonical whole-second UTC")
    return parsed


def _require_session_date(value: object, *, label: str) -> str:
    if type(value) is not str or _SESSION_DATE_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{label} must use YYYY-MM-DD")
    try:
        parsed = dt.date.fromisoformat(value)
    except ValueError:
        raise ValueError(f"{label} must use YYYY-MM-DD") from None
    if parsed.isoformat() != value:
        raise ValueError(f"{label} must use YYYY-MM-DD")
    return value


def _thaw_json(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _thaw_json(item) for key, item in value.items()}
    if type(value) is tuple:
        return [_thaw_json(item) for item in value]
    return value


@dataclass(frozen=True, slots=True)
class PaperOrderReceipt:
    authorization_id: str
    authorization_sha256: str
    logical_order_sha256: str
    client_order_id: str
    broker_order_id: str
    paper_account_fingerprint: str
    account_environment: str
    symbol: str
    side: str
    order_type: str
    tif: str
    requested_notional_usd: str
    requested_limit_price: str
    status: str
    filled_qty: str
    filled_avg_price: str
    fees_usd: str
    submitted_at: str
    last_seen_at: str
    submitted_by_role: str
    schema_version: int = field(
        init=False,
        default=PAPER_ORDER_RECEIPT_SCHEMA_VERSION,
    )
    analysis_only: bool = field(init=False, default=True)
    paper_only: bool = field(init=False, default=True)
    execution_authority: str = field(init=False, default="none")
    can_submit_orders: bool = field(init=False, default=False)

    def __post_init__(self) -> None:
        for name in _PAPER_ORDER_RECEIPT_STRING_FIELDS:
            _require_exact_string(getattr(self, name), label=name)
        _require_object_id(
            self.authorization_id,
            kind=PAPER_EXECUTION_AUTHORIZATION_KIND,
            label="authorization_id",
        )
        _require_digest(
            self.authorization_sha256,
            label="authorization_sha256",
        )
        logical_digest = _require_digest(
            self.logical_order_sha256,
            label="logical_order_sha256",
        )
        _require_client_order_id(
            self.client_order_id,
            logical_order_sha256=logical_digest,
        )
        _require_broker_order_id(self.broker_order_id)
        _require_digest(
            self.paper_account_fingerprint,
            label="paper_account_fingerprint",
        )
        _require_symbol(self.symbol, label="symbol")
        _require_role(
            self.submitted_by_role,
            expected="execution_operator",
            label="submitted_by_role",
        )
        _require_operand_decimal(
            self.requested_notional_usd,
            label="requested_notional_usd",
            positive=True,
            canonical_money=True,
        )
        _require_operand_decimal(
            self.requested_limit_price,
            label="requested_limit_price",
            positive=True,
            canonical_money=True,
        )
        _require_status_matrix(
            status=self.status,
            filled_qty=self.filled_qty,
            filled_avg_price=self.filled_avg_price,
            fees_usd=self.fees_usd,
        )
        submitted = _require_canonical_utc(
            self.submitted_at,
            label="submitted_at",
        )
        last_seen = _require_canonical_utc(
            self.last_seen_at,
            label="last_seen_at",
        )
        if submitted > last_seen:
            raise ValueError("submitted_at must not exceed last_seen_at")
        if self.schema_version != PAPER_ORDER_RECEIPT_SCHEMA_VERSION:
            raise ValueError("paper order receipt schema_version is fixed")
        if self.account_environment != "paper":
            raise ValueError("account_environment must be paper")
        if self.side != "buy":
            raise ValueError("side must be buy")
        if self.order_type != "limit":
            raise ValueError("order_type must be limit")
        if self.tif != "day":
            raise ValueError("tif must be day")
        _require_fixed_bool(self.analysis_only, True, label="analysis_only")
        _require_fixed_bool(self.paper_only, True, label="paper_only")
        if self.execution_authority != "none":
            raise ValueError("execution_authority is fixed")
        _require_fixed_bool(
            self.can_submit_orders,
            False,
            label="can_submit_orders",
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> PaperOrderReceipt:
        values = _require_exact_fields(
            payload,
            _PAPER_ORDER_RECEIPT_KEYS,
            label="paper order receipt",
        )
        if (
            type(values["schema_version"]) is not int
            or values["schema_version"] != PAPER_ORDER_RECEIPT_SCHEMA_VERSION
        ):
            raise ValueError("paper order receipt schema_version does not match")
        _require_fixed_bool(
            values["analysis_only"],
            True,
            label="analysis_only",
        )
        _require_fixed_bool(values["paper_only"], True, label="paper_only")
        if (
            type(values["execution_authority"]) is not str
            or values["execution_authority"] != "none"
        ):
            raise ValueError("execution_authority does not match")
        _require_fixed_bool(
            values["can_submit_orders"],
            False,
            label="can_submit_orders",
        )
        strings = {
            name: _require_exact_string(values[name], label=name)
            for name in _PAPER_ORDER_RECEIPT_STRING_FIELDS
        }
        receipt = cls(**strings)
        if receipt.to_dict() != values:
            raise ValueError("paper order receipt canonical round trip is not exact")
        return receipt

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "authorization_id": self.authorization_id,
            "authorization_sha256": self.authorization_sha256,
            "logical_order_sha256": self.logical_order_sha256,
            "client_order_id": self.client_order_id,
            "broker_order_id": self.broker_order_id,
            "paper_account_fingerprint": self.paper_account_fingerprint,
            "account_environment": self.account_environment,
            "symbol": self.symbol,
            "side": self.side,
            "order_type": self.order_type,
            "tif": self.tif,
            "requested_notional_usd": self.requested_notional_usd,
            "requested_limit_price": self.requested_limit_price,
            "status": self.status,
            "filled_qty": self.filled_qty,
            "filled_avg_price": self.filled_avg_price,
            "fees_usd": self.fees_usd,
            "submitted_at": self.submitted_at,
            "last_seen_at": self.last_seen_at,
            "submitted_by_role": self.submitted_by_role,
            "analysis_only": self.analysis_only,
            "paper_only": self.paper_only,
            "execution_authority": self.execution_authority,
            "can_submit_orders": self.can_submit_orders,
        }

    def canonical_json_bytes(self) -> bytes:
        return _canonical_json_bytes(self.to_dict())


@dataclass(frozen=True, slots=True)
class PaperReconciliationReceipt:
    authorization_id: str
    authorization_sha256: str
    logical_order_sha256: str
    client_order_id: str
    broker_order_id: str
    paper_account_fingerprint: str
    observed_status: str
    observed_symbol: str
    observed_side: str
    observed_order_type: str
    observed_tif: str
    observed_requested_notional_usd: str
    observed_requested_limit_price: str
    observed_filled_qty: str
    observed_filled_avg_price: str
    observed_fees_usd: str
    checked_at: str
    verified_by_role: str
    read_only: bool = field(init=False, default=True)
    broker_write_calls: int = field(init=False, default=0)
    schema_version: int = field(
        init=False,
        default=PAPER_RECONCILIATION_RECEIPT_SCHEMA_VERSION,
    )
    analysis_only: bool = field(init=False, default=True)
    paper_only: bool = field(init=False, default=True)
    execution_authority: str = field(init=False, default="none")
    can_submit_orders: bool = field(init=False, default=False)

    def __post_init__(self) -> None:
        for name in _PAPER_RECONCILIATION_RECEIPT_STRING_FIELDS:
            _require_exact_string(getattr(self, name), label=name)
        _require_object_id(
            self.authorization_id,
            kind=PAPER_EXECUTION_AUTHORIZATION_KIND,
            label="authorization_id",
        )
        _require_digest(
            self.authorization_sha256,
            label="authorization_sha256",
        )
        logical_digest = _require_digest(
            self.logical_order_sha256,
            label="logical_order_sha256",
        )
        _require_client_order_id(
            self.client_order_id,
            logical_order_sha256=logical_digest,
        )
        _require_broker_order_id(self.broker_order_id)
        _require_digest(
            self.paper_account_fingerprint,
            label="paper_account_fingerprint",
        )
        _require_symbol(self.observed_symbol, label="observed_symbol")
        _require_role(
            self.verified_by_role,
            expected="integrity_verifier",
            label="verified_by_role",
        )
        if self.observed_side != "buy":
            raise ValueError("observed_side must be buy")
        if self.observed_order_type != "limit":
            raise ValueError("observed_order_type must be limit")
        if self.observed_tif != "day":
            raise ValueError("observed_tif must be day")
        _require_operand_decimal(
            self.observed_requested_notional_usd,
            label="observed_requested_notional_usd",
            positive=True,
            canonical_money=True,
        )
        _require_operand_decimal(
            self.observed_requested_limit_price,
            label="observed_requested_limit_price",
            positive=True,
            canonical_money=True,
        )
        _require_status_matrix(
            status=self.observed_status,
            filled_qty=self.observed_filled_qty,
            filled_avg_price=self.observed_filled_avg_price,
            fees_usd=self.observed_fees_usd,
        )
        _require_canonical_utc(self.checked_at, label="checked_at")
        if (
            self.schema_version
            != PAPER_RECONCILIATION_RECEIPT_SCHEMA_VERSION
        ):
            raise ValueError(
                "paper reconciliation receipt schema_version is fixed"
            )
        _require_fixed_bool(self.read_only, True, label="read_only")
        if type(self.broker_write_calls) is not int:
            raise TypeError("broker_write_calls must be an exact integer")
        if self.broker_write_calls != 0:
            raise ValueError("broker_write_calls is fixed")
        _require_fixed_bool(self.analysis_only, True, label="analysis_only")
        _require_fixed_bool(self.paper_only, True, label="paper_only")
        if self.execution_authority != "none":
            raise ValueError("execution_authority is fixed")
        _require_fixed_bool(
            self.can_submit_orders,
            False,
            label="can_submit_orders",
        )

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, object],
    ) -> PaperReconciliationReceipt:
        values = _require_exact_fields(
            payload,
            _PAPER_RECONCILIATION_RECEIPT_KEYS,
            label="paper reconciliation receipt",
        )
        if (
            type(values["schema_version"]) is not int
            or values["schema_version"]
            != PAPER_RECONCILIATION_RECEIPT_SCHEMA_VERSION
        ):
            raise ValueError(
                "paper reconciliation receipt schema_version does not match"
            )
        _require_fixed_bool(values["read_only"], True, label="read_only")
        if (
            type(values["broker_write_calls"]) is not int
            or values["broker_write_calls"] != 0
        ):
            raise ValueError("broker_write_calls does not match")
        _require_fixed_bool(
            values["analysis_only"],
            True,
            label="analysis_only",
        )
        _require_fixed_bool(values["paper_only"], True, label="paper_only")
        if (
            type(values["execution_authority"]) is not str
            or values["execution_authority"] != "none"
        ):
            raise ValueError("execution_authority does not match")
        _require_fixed_bool(
            values["can_submit_orders"],
            False,
            label="can_submit_orders",
        )
        strings = {
            name: _require_exact_string(values[name], label=name)
            for name in _PAPER_RECONCILIATION_RECEIPT_STRING_FIELDS
        }
        receipt = cls(**strings)
        if receipt.to_dict() != values:
            raise ValueError(
                "paper reconciliation receipt canonical round trip is not exact"
            )
        return receipt

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "authorization_id": self.authorization_id,
            "authorization_sha256": self.authorization_sha256,
            "logical_order_sha256": self.logical_order_sha256,
            "client_order_id": self.client_order_id,
            "broker_order_id": self.broker_order_id,
            "paper_account_fingerprint": self.paper_account_fingerprint,
            "observed_status": self.observed_status,
            "observed_symbol": self.observed_symbol,
            "observed_side": self.observed_side,
            "observed_order_type": self.observed_order_type,
            "observed_tif": self.observed_tif,
            "observed_requested_notional_usd": (
                self.observed_requested_notional_usd
            ),
            "observed_requested_limit_price": (
                self.observed_requested_limit_price
            ),
            "observed_filled_qty": self.observed_filled_qty,
            "observed_filled_avg_price": self.observed_filled_avg_price,
            "observed_fees_usd": self.observed_fees_usd,
            "checked_at": self.checked_at,
            "verified_by_role": self.verified_by_role,
            "read_only": self.read_only,
            "broker_write_calls": self.broker_write_calls,
            "analysis_only": self.analysis_only,
            "paper_only": self.paper_only,
            "execution_authority": self.execution_authority,
            "can_submit_orders": self.can_submit_orders,
        }

    def canonical_json_bytes(self) -> bytes:
        return _canonical_json_bytes(self.to_dict())


@dataclass(frozen=True, slots=True)
class AdmittedPaperShadowObservation:
    shadow_observation_id: str
    staged_intent_id: str
    staged_intent_sha256: str
    authorization_id: str | None
    authorization_sha256: str | None
    paper_account_fingerprint: str | None
    promotion_evidence_id: str
    genome_id: str
    genome_canonical_sha256: str
    evaluation_code_commit: str
    evaluation_runtime_sha256: str
    session_date: str
    observed_at: str
    decision_action: str
    paper_order_receipt: PaperOrderReceipt | None
    reconciliation_receipt: PaperReconciliationReceipt | None
    receipt_sha256: str | None
    reconciliation_sha256: str | None
    adverse_fill_vs_reference_fraction: str
    gates: tuple[tuple[str, bool], ...]
    issues: tuple[str, ...]
    operationally_reconciled: bool
    verified_by_role: str
    effective_at: str
    recorded_at: str
    schema_version: int = field(
        init=False,
        default=ADMITTED_PAPER_SHADOW_OBSERVATION_SCHEMA_VERSION,
    )
    analysis_only: bool = field(init=False, default=True)
    paper_only: bool = field(init=False, default=True)
    execution_authority: str = field(init=False, default="none")
    can_submit_orders: bool = field(init=False, default=False)

    def __post_init__(self) -> None:
        for name in _OBSERVATION_STRING_FIELDS:
            _require_exact_string(getattr(self, name), label=name)
        _require_object_id(
            self.shadow_observation_id,
            kind=PAPER_SHADOW_OBSERVATION_KIND,
            label="shadow_observation_id",
        )
        _require_object_id(
            self.staged_intent_id,
            kind="staged-paper-intent",
            label="staged_intent_id",
        )
        _require_digest(
            self.staged_intent_sha256,
            label="staged_intent_sha256",
        )
        _require_object_id(
            self.promotion_evidence_id,
            kind="promotion-evidence",
            label="promotion_evidence_id",
        )
        _require_genome_id(self.genome_id, label="genome_id")
        _require_digest(
            self.genome_canonical_sha256,
            label="genome_canonical_sha256",
        )
        _require_commit(
            self.evaluation_code_commit,
            label="evaluation_code_commit",
        )
        _require_digest(
            self.evaluation_runtime_sha256,
            label="evaluation_runtime_sha256",
        )
        _require_role(
            self.verified_by_role,
            expected="integrity_verifier",
            label="verified_by_role",
        )
        _require_derived_fraction(
            self.adverse_fill_vs_reference_fraction,
            label="adverse_fill_vs_reference_fraction",
        )
        for name in _OBSERVATION_OPTIONAL_STRING_FIELDS:
            _require_optional_exact_string(getattr(self, name), label=name)
        _require_optional_object_id(
            self.authorization_id,
            kind=PAPER_EXECUTION_AUTHORIZATION_KIND,
            label="authorization_id",
        )
        _require_optional_digest(
            self.authorization_sha256,
            label="authorization_sha256",
        )
        _require_optional_digest(
            self.paper_account_fingerprint,
            label="paper_account_fingerprint",
        )
        _require_optional_digest(self.receipt_sha256, label="receipt_sha256")
        _require_optional_digest(
            self.reconciliation_sha256,
            label="reconciliation_sha256",
        )
        if self.decision_action not in {"hold-cash", "buy"}:
            raise ValueError("decision_action must be hold-cash or buy")
        _require_session_date(self.session_date, label="session_date")
        observed = _require_canonical_utc(
            self.observed_at,
            label="observed_at",
        )
        effective = _require_canonical_utc(
            self.effective_at,
            label="effective_at",
        )
        recorded = _require_canonical_utc(
            self.recorded_at,
            label="recorded_at",
        )
        if effective != observed:
            raise ValueError("observation effective_at must equal observed_at")
        if observed > recorded:
            raise ValueError("future observation is not allowed")
        expected_order = (
            HOLD_SHADOW_OBSERVATION_GATE_ORDER
            if self.decision_action == "hold-cash"
            else BUY_SHADOW_OBSERVATION_GATE_ORDER
        )
        gates = _require_constructor_gates(self.gates, order=expected_order)
        expected_issues = tuple(
            SHADOW_OBSERVATION_ISSUE_BY_GATE[name]
            for name, passed in gates
            if not passed and name in SHADOW_OBSERVATION_ISSUE_BY_GATE
        )
        _require_constructor_issues(self.issues, expected=expected_issues)
        if type(self.operationally_reconciled) is not bool:
            raise TypeError("operationally_reconciled must be an exact bool")
        gate_map = dict(gates)
        if self.decision_action == "hold-cash":
            if any(
                value is not None
                for value in (
                    self.authorization_id,
                    self.authorization_sha256,
                    self.paper_account_fingerprint,
                    self.paper_order_receipt,
                    self.reconciliation_receipt,
                    self.receipt_sha256,
                    self.reconciliation_sha256,
                )
            ):
                raise ValueError("hold observation cannot contain order facts")
            if gate_map["no_order_expected"] is not True:
                raise ValueError("hold no_order_expected gate is invariant")
            if self.operationally_reconciled is not True:
                raise ValueError("hold reconciliation flag is invariant")
        else:
            if (
                self.authorization_id is None
                or self.authorization_sha256 is None
                or self.paper_account_fingerprint is None
                or type(self.paper_order_receipt) is not PaperOrderReceipt
                or type(self.reconciliation_receipt)
                is not PaperReconciliationReceipt
                or self.receipt_sha256 is None
                or self.reconciliation_sha256 is None
            ):
                raise ValueError("buy observation requires complete order facts")
            if (
                self.paper_order_receipt.broker_order_id
                != self.reconciliation_receipt.broker_order_id
            ):
                raise ValueError(
                    "buy receipt broker_order_id values must match"
                )
            expected_receipt_digest = hashlib.sha256(
                self.paper_order_receipt.canonical_json_bytes()
            ).hexdigest()
            expected_reconciliation_digest = hashlib.sha256(
                self.reconciliation_receipt.canonical_json_bytes()
            ).hexdigest()
            if self.receipt_sha256 != expected_receipt_digest:
                raise ValueError("paper receipt digest does not match")
            if (
                self.reconciliation_sha256
                != expected_reconciliation_digest
            ):
                raise ValueError("reconciliation receipt digest does not match")
            if gate_map["operationally_reconciled"] is not True:
                raise ValueError(
                    "buy operationally_reconciled gate is invariant"
                )
            if self.operationally_reconciled is not True:
                raise ValueError("buy reconciliation flag is invariant")
        if (
            self.schema_version
            != ADMITTED_PAPER_SHADOW_OBSERVATION_SCHEMA_VERSION
        ):
            raise ValueError("shadow observation schema_version is fixed")
        _require_fixed_bool(self.analysis_only, True, label="analysis_only")
        _require_fixed_bool(self.paper_only, True, label="paper_only")
        if self.execution_authority != "none":
            raise ValueError("execution_authority is fixed")
        _require_fixed_bool(
            self.can_submit_orders,
            False,
            label="can_submit_orders",
        )
        if self.shadow_observation_id != _expected_object_id(
            kind=PAPER_SHADOW_OBSERVATION_KIND,
            effective_at=self.effective_at,
            payload=self._evidence_payload(),
        ):
            raise ValueError(
                "shadow_observation_id does not match evidence identity"
            )

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, object],
    ) -> AdmittedPaperShadowObservation:
        values = _require_exact_fields(
            payload,
            _OBSERVATION_KEYS,
            label="admitted paper shadow observation",
        )
        if (
            type(values["schema_version"]) is not int
            or values["schema_version"]
            != ADMITTED_PAPER_SHADOW_OBSERVATION_SCHEMA_VERSION
        ):
            raise ValueError("shadow observation schema_version does not match")
        for name in (
            "analysis_only",
            "paper_only",
        ):
            _require_fixed_bool(values[name], True, label=name)
        if (
            type(values["execution_authority"]) is not str
            or values["execution_authority"] != "none"
        ):
            raise ValueError("execution_authority does not match")
        _require_fixed_bool(
            values["can_submit_orders"],
            False,
            label="can_submit_orders",
        )
        if type(values["operationally_reconciled"]) is not bool:
            raise TypeError("operationally_reconciled must be an exact bool")
        strings = {
            name: _require_exact_string(values[name], label=name)
            for name in _OBSERVATION_STRING_FIELDS
        }
        optionals = {
            name: _require_optional_exact_string(values[name], label=name)
            for name in _OBSERVATION_OPTIONAL_STRING_FIELDS
        }
        action = strings["decision_action"]
        order = (
            HOLD_SHADOW_OBSERVATION_GATE_ORDER
            if action == "hold-cash"
            else BUY_SHADOW_OBSERVATION_GATE_ORDER
        )
        paper_receipt_value = values["paper_order_receipt"]
        reconciliation_value = values["reconciliation_receipt"]
        paper_receipt = (
            None
            if paper_receipt_value is None
            else PaperOrderReceipt.from_dict(paper_receipt_value)  # type: ignore[arg-type]
        )
        reconciliation = (
            None
            if reconciliation_value is None
            else PaperReconciliationReceipt.from_dict(  # type: ignore[arg-type]
                reconciliation_value
            )
        )
        observation = cls(
            **strings,
            **optionals,
            paper_order_receipt=paper_receipt,
            reconciliation_receipt=reconciliation,
            gates=_gates_from_json(values["gates"], order=order),
            issues=_issues_from_json(values["issues"]),
            operationally_reconciled=values["operationally_reconciled"],
        )
        if observation.to_dict() != values:
            raise ValueError(
                "shadow observation canonical round trip is not exact"
            )
        return observation

    def _evidence_payload(self) -> dict[str, object]:
        payload = self.to_dict()
        for name in (
            "shadow_observation_id",
            "effective_at",
            "recorded_at",
        ):
            del payload[name]
        return payload

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "shadow_observation_id": self.shadow_observation_id,
            "staged_intent_id": self.staged_intent_id,
            "staged_intent_sha256": self.staged_intent_sha256,
            "authorization_id": self.authorization_id,
            "authorization_sha256": self.authorization_sha256,
            "paper_account_fingerprint": self.paper_account_fingerprint,
            "promotion_evidence_id": self.promotion_evidence_id,
            "genome_id": self.genome_id,
            "genome_canonical_sha256": self.genome_canonical_sha256,
            "evaluation_code_commit": self.evaluation_code_commit,
            "evaluation_runtime_sha256": self.evaluation_runtime_sha256,
            "session_date": self.session_date,
            "observed_at": self.observed_at,
            "decision_action": self.decision_action,
            "paper_order_receipt": (
                None
                if self.paper_order_receipt is None
                else self.paper_order_receipt.to_dict()
            ),
            "reconciliation_receipt": (
                None
                if self.reconciliation_receipt is None
                else self.reconciliation_receipt.to_dict()
            ),
            "receipt_sha256": self.receipt_sha256,
            "reconciliation_sha256": self.reconciliation_sha256,
            "adverse_fill_vs_reference_fraction": (
                self.adverse_fill_vs_reference_fraction
            ),
            "gates": [[name, passed] for name, passed in self.gates],
            "issues": list(self.issues),
            "operationally_reconciled": self.operationally_reconciled,
            "verified_by_role": self.verified_by_role,
            "effective_at": self.effective_at,
            "recorded_at": self.recorded_at,
            "analysis_only": self.analysis_only,
            "paper_only": self.paper_only,
            "execution_authority": self.execution_authority,
            "can_submit_orders": self.can_submit_orders,
        }

    def canonical_json_bytes(self) -> bytes:
        return _canonical_json_bytes(self.to_dict())


@dataclass(frozen=True, slots=True)
class StrategyShadowAttestation:
    shadow_attestation_id: str
    registration_id: str
    promotion_evidence_id: str
    promotion_evidence_sha256: str
    genome_id: str
    genome_canonical_sha256: str
    evaluation_code_commit: str
    evaluation_runtime_sha256: str
    paper_account_fingerprint: str | None
    shadow_observation_ids: tuple[str, ...]
    shadow_observation_sha256s: tuple[str, ...]
    first_session_date: str
    last_session_date: str
    tracked_sessions: int
    total_intents: int
    hold_intents: int
    buy_intents: int
    reconciled_buy_intents: int
    filled_buy_intents: int
    total_requested_notional_usd: str
    total_filled_notional_usd: str
    total_fees_usd: str
    worst_adverse_fill_vs_reference_fraction: str
    gates: tuple[tuple[str, bool], ...]
    issues: tuple[str, ...]
    shadow_sessions_sufficient: bool
    reconciliation_confirmed: bool
    assembled_by_role: str
    effective_at: str
    recorded_at: str
    schema_version: int = field(
        init=False,
        default=STRATEGY_SHADOW_ATTESTATION_SCHEMA_VERSION,
    )
    analysis_only: bool = field(init=False, default=True)
    paper_only: bool = field(init=False, default=True)
    execution_authority: str = field(init=False, default="none")
    can_submit_orders: bool = field(init=False, default=False)

    def __post_init__(self) -> None:
        for name in _ATTESTATION_STRING_FIELDS:
            _require_exact_string(getattr(self, name), label=name)
        _require_object_id(
            self.shadow_attestation_id,
            kind=PAPER_SHADOW_ATTESTATION_KIND,
            label="shadow_attestation_id",
        )
        _require_object_id(
            self.registration_id,
            kind="evaluation-registration",
            label="registration_id",
        )
        _require_object_id(
            self.promotion_evidence_id,
            kind="promotion-evidence",
            label="promotion_evidence_id",
        )
        _require_digest(
            self.promotion_evidence_sha256,
            label="promotion_evidence_sha256",
        )
        _require_genome_id(self.genome_id, label="genome_id")
        _require_digest(
            self.genome_canonical_sha256,
            label="genome_canonical_sha256",
        )
        _require_commit(
            self.evaluation_code_commit,
            label="evaluation_code_commit",
        )
        _require_digest(
            self.evaluation_runtime_sha256,
            label="evaluation_runtime_sha256",
        )
        _require_role(
            self.assembled_by_role,
            expected="integrity_verifier",
            label="assembled_by_role",
        )
        for name in (
            "total_requested_notional_usd",
            "total_filled_notional_usd",
            "total_fees_usd",
        ):
            _require_derived_money(getattr(self, name), label=name)
        _require_derived_fraction(
            self.worst_adverse_fill_vs_reference_fraction,
            label="worst_adverse_fill_vs_reference_fraction",
        )
        _require_optional_exact_string(
            self.paper_account_fingerprint,
            label="paper_account_fingerprint",
        )
        _require_optional_digest(
            self.paper_account_fingerprint,
            label="paper_account_fingerprint",
        )
        first_session = _require_session_date(
            self.first_session_date,
            label="first_session_date",
        )
        last_session = _require_session_date(
            self.last_session_date,
            label="last_session_date",
        )
        if first_session > last_session:
            raise ValueError("first_session_date must not exceed last_session_date")
        effective = _require_canonical_utc(
            self.effective_at,
            label="effective_at",
        )
        recorded = _require_canonical_utc(
            self.recorded_at,
            label="recorded_at",
        )
        if effective > recorded:
            raise ValueError("future attestation is not allowed")
        ids = _require_constructor_string_tuple(
            self.shadow_observation_ids,
            label="shadow_observation_ids",
        )
        digests = _require_constructor_string_tuple(
            self.shadow_observation_sha256s,
            label="shadow_observation_sha256s",
        )
        if not ids or len(ids) != len(digests):
            raise ValueError("attestation observation bindings are incomplete")
        if len(ids) > SHADOW_ATTESTATION_MAX_OBSERVATIONS:
            raise ValueError("too many shadow observations")
        if len(set(ids)) != len(ids):
            raise ValueError("shadow observation IDs must be unique")
        for object_id in ids:
            _require_object_id(
                object_id,
                kind=PAPER_SHADOW_OBSERVATION_KIND,
                label="shadow_observation_ids",
            )
        for digest in digests:
            _require_digest(digest, label="shadow_observation_sha256s")
        for name in _ATTESTATION_COUNT_FIELDS:
            _require_exact_int(getattr(self, name), label=name)
        if self.total_intents != self.hold_intents + self.buy_intents:
            raise ValueError("intent counts do not add up")
        if self.total_intents != len(ids):
            raise ValueError("total_intents does not match observations")
        if self.reconciled_buy_intents > self.buy_intents:
            raise ValueError("reconciled buy count exceeds buy count")
        if self.filled_buy_intents > self.buy_intents:
            raise ValueError("filled buy count exceeds buy count")
        gates = _require_constructor_gates(self.gates, order=SHADOW_GATE_ORDER)
        expected_issues = tuple(
            SHADOW_ATTESTATION_ISSUE_BY_GATE[name]
            for name, passed in gates
            if not passed
        )
        _require_constructor_issues(self.issues, expected=expected_issues)
        if type(self.shadow_sessions_sufficient) is not bool:
            raise TypeError("shadow_sessions_sufficient must be an exact bool")
        if type(self.reconciliation_confirmed) is not bool:
            raise TypeError("reconciliation_confirmed must be an exact bool")
        gate_map = dict(gates)
        if (
            self.shadow_sessions_sufficient
            is not gate_map["minimum_tracked_sessions"]
        ):
            raise ValueError("shadow session sufficiency does not match gate")
        if self.buy_intents == 0 and self.paper_account_fingerprint is not None:
            raise ValueError("hold-only attestation cannot bind an account")
        if self.buy_intents > 0 and self.paper_account_fingerprint is None:
            raise ValueError("buy attestation requires an account fingerprint")
        expected_reconciliation = (
            self.buy_intents > 0
            and gate_map["all_buy_intents_paper_only"]
            and gate_map["all_order_fields_match"]
            and gate_map["all_buy_intents_terminal_filled"]
            and gate_map["all_reconciliations_clean"]
        )
        if self.reconciliation_confirmed is not expected_reconciliation:
            raise ValueError("reconciliation_confirmed does not match gates")
        if (
            self.schema_version
            != STRATEGY_SHADOW_ATTESTATION_SCHEMA_VERSION
        ):
            raise ValueError("shadow attestation schema_version is fixed")
        _require_fixed_bool(self.analysis_only, True, label="analysis_only")
        _require_fixed_bool(self.paper_only, True, label="paper_only")
        if self.execution_authority != "none":
            raise ValueError("execution_authority is fixed")
        _require_fixed_bool(
            self.can_submit_orders,
            False,
            label="can_submit_orders",
        )
        if self.shadow_attestation_id != _expected_object_id(
            kind=PAPER_SHADOW_ATTESTATION_KIND,
            effective_at=self.effective_at,
            payload=self._evidence_payload(),
        ):
            raise ValueError(
                "shadow_attestation_id does not match evidence identity"
            )

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, object],
    ) -> StrategyShadowAttestation:
        values = _require_exact_fields(
            payload,
            _ATTESTATION_KEYS,
            label="strategy shadow attestation",
        )
        if (
            type(values["schema_version"]) is not int
            or values["schema_version"]
            != STRATEGY_SHADOW_ATTESTATION_SCHEMA_VERSION
        ):
            raise ValueError("shadow attestation schema_version does not match")
        for name in ("analysis_only", "paper_only"):
            _require_fixed_bool(values[name], True, label=name)
        if (
            type(values["execution_authority"]) is not str
            or values["execution_authority"] != "none"
        ):
            raise ValueError("execution_authority does not match")
        _require_fixed_bool(
            values["can_submit_orders"],
            False,
            label="can_submit_orders",
        )
        if type(values["shadow_sessions_sufficient"]) is not bool:
            raise TypeError("shadow_sessions_sufficient must be an exact bool")
        if type(values["reconciliation_confirmed"]) is not bool:
            raise TypeError("reconciliation_confirmed must be an exact bool")
        strings = {
            name: _require_exact_string(values[name], label=name)
            for name in _ATTESTATION_STRING_FIELDS
        }
        counts = {
            name: _require_exact_int(values[name], label=name)
            for name in _ATTESTATION_COUNT_FIELDS
        }
        attestation = cls(
            **strings,
            **counts,
            paper_account_fingerprint=_require_optional_exact_string(
                values["paper_account_fingerprint"],
                label="paper_account_fingerprint",
            ),
            shadow_observation_ids=_string_tuple_from_json(
                values["shadow_observation_ids"],
                label="shadow_observation_ids",
            ),
            shadow_observation_sha256s=_string_tuple_from_json(
                values["shadow_observation_sha256s"],
                label="shadow_observation_sha256s",
            ),
            gates=_gates_from_json(values["gates"], order=SHADOW_GATE_ORDER),
            issues=_issues_from_json(values["issues"]),
            shadow_sessions_sufficient=values["shadow_sessions_sufficient"],
            reconciliation_confirmed=values["reconciliation_confirmed"],
        )
        if attestation.to_dict() != values:
            raise ValueError(
                "shadow attestation canonical round trip is not exact"
            )
        return attestation

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "shadow_attestation_id": self.shadow_attestation_id,
            "registration_id": self.registration_id,
            "promotion_evidence_id": self.promotion_evidence_id,
            "promotion_evidence_sha256": self.promotion_evidence_sha256,
            "genome_id": self.genome_id,
            "genome_canonical_sha256": self.genome_canonical_sha256,
            "evaluation_code_commit": self.evaluation_code_commit,
            "evaluation_runtime_sha256": self.evaluation_runtime_sha256,
            "paper_account_fingerprint": self.paper_account_fingerprint,
            "shadow_observation_ids": list(self.shadow_observation_ids),
            "shadow_observation_sha256s": list(
                self.shadow_observation_sha256s
            ),
            "first_session_date": self.first_session_date,
            "last_session_date": self.last_session_date,
            "tracked_sessions": self.tracked_sessions,
            "total_intents": self.total_intents,
            "hold_intents": self.hold_intents,
            "buy_intents": self.buy_intents,
            "reconciled_buy_intents": self.reconciled_buy_intents,
            "filled_buy_intents": self.filled_buy_intents,
            "total_requested_notional_usd": (
                self.total_requested_notional_usd
            ),
            "total_filled_notional_usd": self.total_filled_notional_usd,
            "total_fees_usd": self.total_fees_usd,
            "worst_adverse_fill_vs_reference_fraction": (
                self.worst_adverse_fill_vs_reference_fraction
            ),
            "gates": [[name, passed] for name, passed in self.gates],
            "issues": list(self.issues),
            "shadow_sessions_sufficient": self.shadow_sessions_sufficient,
            "reconciliation_confirmed": self.reconciliation_confirmed,
            "assembled_by_role": self.assembled_by_role,
            "effective_at": self.effective_at,
            "recorded_at": self.recorded_at,
            "analysis_only": self.analysis_only,
            "paper_only": self.paper_only,
            "execution_authority": self.execution_authority,
            "can_submit_orders": self.can_submit_orders,
        }

    def _evidence_payload(self) -> dict[str, object]:
        payload = self.to_dict()
        for name in (
            "shadow_attestation_id",
            "effective_at",
            "recorded_at",
        ):
            del payload[name]
        return payload

    def canonical_json_bytes(self) -> bytes:
        return _canonical_json_bytes(self.to_dict())


def _observation_from_envelope(
    envelope: EvidenceEnvelope,
) -> AdmittedPaperShadowObservation:
    if type(envelope) is not EvidenceEnvelope:
        raise TypeError("shadow observation envelope type does not match")
    if envelope.kind != PAPER_SHADOW_OBSERVATION_KIND:
        raise ValueError("envelope kind is not paper shadow observation")
    raw_payload = _thaw_json(envelope.payload)
    if type(raw_payload) is not dict:
        raise ValueError("shadow observation payload is not an object")
    observation = AdmittedPaperShadowObservation.from_dict(
        {
            **raw_payload,
            "shadow_observation_id": envelope.object_id,
            "effective_at": envelope.effective_at,
            "recorded_at": envelope.recorded_at,
        }
    )
    if observation._evidence_payload() != raw_payload:
        raise ValueError("shadow observation payload round trip is not exact")
    return observation


def _attestation_from_envelope(
    envelope: EvidenceEnvelope,
) -> StrategyShadowAttestation:
    if type(envelope) is not EvidenceEnvelope:
        raise TypeError("shadow attestation envelope type does not match")
    if envelope.kind != PAPER_SHADOW_ATTESTATION_KIND:
        raise ValueError("envelope kind is not paper shadow attestation")
    raw_payload = _thaw_json(envelope.payload)
    if type(raw_payload) is not dict:
        raise ValueError("shadow attestation payload is not an object")
    attestation = StrategyShadowAttestation.from_dict(
        {
            **raw_payload,
            "shadow_attestation_id": envelope.object_id,
            "effective_at": envelope.effective_at,
            "recorded_at": envelope.recorded_at,
        }
    )
    if attestation._evidence_payload() != raw_payload:
        raise ValueError("shadow attestation payload round trip is not exact")
    return attestation


def _authorization_from_prefix(
    prefix: Sequence[EvidenceEnvelope],
    authorization_id: str,
) -> AuthorizedPaperOrderRequest:
    matches = tuple(
        _authorization_from_envelope(envelope)
        for envelope in prefix
        if envelope.kind == PAPER_EXECUTION_AUTHORIZATION_KIND
        and envelope.object_id == authorization_id
    )
    if len(matches) != 1:
        raise ValueError(
            "paper authorization must already be durable in this store"
        )
    return matches[0]


def _selected_reference_price(staged_intent: StagedPaperIntent) -> Decimal:
    symbol = staged_intent.decision.symbol
    matches = tuple(
        observation
        for observation in staged_intent.observations
        if observation.symbol == symbol
    )
    if len(matches) != 1:
        raise ValueError("BUY staged reference observation is not unique")
    return _require_operand_decimal(
        matches[0].current_price,
        label="staged reference price",
        positive=True,
    )


def _require_buy_receipt_structure(
    *,
    staged_intent: StagedPaperIntent,
    authorization: AuthorizedPaperOrderRequest,
    paper_order_receipt: PaperOrderReceipt,
    reconciliation_receipt: PaperReconciliationReceipt,
    observed_at: str,
    verified_by_role: str,
) -> None:
    if staged_intent.decision.action is not PaperDecisionAction.BUY:
        raise ValueError("BUY observation requires a staged BUY")
    if (
        authorization.staged_intent_id != staged_intent.staged_intent_id
        or authorization.staged_intent_sha256
        != hashlib.sha256(staged_intent.canonical_json_bytes()).hexdigest()
    ):
        raise ValueError("authorization does not match staged intent")
    authorization_sha256 = hashlib.sha256(
        authorization.canonical_json_bytes()
    ).hexdigest()
    for receipt in (paper_order_receipt, reconciliation_receipt):
        if receipt.authorization_id != authorization.authorization_id:
            raise ValueError("receipt authorization identity does not match")
        if receipt.authorization_sha256 != authorization_sha256:
            raise ValueError("receipt authorization digest does not match")
        if (
            receipt.logical_order_sha256
            != authorization.logical_order_sha256
        ):
            raise ValueError("receipt logical order digest does not match")
        if receipt.client_order_id != authorization.client_order_id:
            raise ValueError("receipt client order ID does not match")
        if (
            receipt.paper_account_fingerprint
            != authorization.paper_account_fingerprint
        ):
            raise ValueError("receipt paper account fingerprint does not match")
    if (
        paper_order_receipt.submitted_by_role != _required_submit_owner()
    ):
        raise ValueError("submitted_by_role must be execution_operator")
    if reconciliation_receipt.verified_by_role != verified_by_role:
        raise ValueError("verified_by_role must be integrity_verifier")
    expected_order = (
        authorization.symbol,
        authorization.side,
        authorization.order_type,
        authorization.tif,
        authorization.requested_notional_usd,
        authorization.requested_limit_price,
    )
    receipt_order = (
        paper_order_receipt.symbol,
        paper_order_receipt.side,
        paper_order_receipt.order_type,
        paper_order_receipt.tif,
        paper_order_receipt.requested_notional_usd,
        paper_order_receipt.requested_limit_price,
    )
    reconciliation_order = (
        reconciliation_receipt.observed_symbol,
        reconciliation_receipt.observed_side,
        reconciliation_receipt.observed_order_type,
        reconciliation_receipt.observed_tif,
        reconciliation_receipt.observed_requested_notional_usd,
        reconciliation_receipt.observed_requested_limit_price,
    )
    if receipt_order != expected_order or reconciliation_order != expected_order:
        raise ValueError("receipt order fields do not match authorization")
    receipt_outcome = (
        paper_order_receipt.status,
        paper_order_receipt.filled_qty,
        paper_order_receipt.filled_avg_price,
        paper_order_receipt.fees_usd,
        paper_order_receipt.broker_order_id,
    )
    reconciliation_outcome = (
        reconciliation_receipt.observed_status,
        reconciliation_receipt.observed_filled_qty,
        reconciliation_receipt.observed_filled_avg_price,
        reconciliation_receipt.observed_fees_usd,
        reconciliation_receipt.broker_order_id,
    )
    if receipt_outcome != reconciliation_outcome:
        raise ValueError("receipt and reconciliation outcomes do not match")
    submitted = _require_canonical_utc(
        paper_order_receipt.submitted_at,
        label="submitted_at",
    )
    last_seen = _require_canonical_utc(
        paper_order_receipt.last_seen_at,
        label="last_seen_at",
    )
    checked = _require_canonical_utc(
        reconciliation_receipt.checked_at,
        label="checked_at",
    )
    observed = _require_canonical_utc(observed_at, label="observed_at")
    authorization_recorded = _require_canonical_utc(
        authorization.recorded_at,
        label="authorization.recorded_at",
    )
    authorization_expires = _require_canonical_utc(
        authorization.expires_at,
        label="authorization.expires_at",
    )
    staged_recorded = _require_canonical_utc(
        staged_intent.recorded_at,
        label="staged_intent.recorded_at",
    )
    staged_expires = _require_canonical_utc(
        staged_intent.expires_at,
        label="staged_intent.expires_at",
    )
    if not staged_recorded <= authorization_recorded:
        raise ValueError("authorization predates staged intent")
    if not authorization_recorded <= submitted <= last_seen <= checked:
        raise ValueError("BUY receipt timestamps are reversed")
    if checked != observed:
        raise ValueError("checked_at must equal observed_at")
    if not submitted < staged_expires or not submitted < authorization_expires:
        raise ValueError("BUY submission occurred after expiry")
    if checked - submitted > dt.timedelta(seconds=86400):
        raise ValueError("BUY reconciliation exceeds 86400 seconds")
    for label, value in (
        ("submitted_at", submitted),
        ("last_seen_at", last_seen),
        ("checked_at", checked),
    ):
        if (
            value.astimezone(ZoneInfo("America/New_York")).date().isoformat()
            != staged_intent.session_date
        ):
            raise ValueError(f"{label} does not match session_date")


def _observation_payload(
    *,
    staged_intent: StagedPaperIntent,
    observed_at: str,
    verified_by_role: str,
    authorization: AuthorizedPaperOrderRequest | None = None,
    paper_order_receipt: PaperOrderReceipt | None = None,
    reconciliation_receipt: PaperReconciliationReceipt | None = None,
) -> dict[str, object]:
    if staged_intent.decision.action is PaperDecisionAction.HOLD_CASH:
        return {
            "schema_version": ADMITTED_PAPER_SHADOW_OBSERVATION_SCHEMA_VERSION,
            "staged_intent_id": staged_intent.staged_intent_id,
            "staged_intent_sha256": hashlib.sha256(
                staged_intent.canonical_json_bytes()
            ).hexdigest(),
            "authorization_id": None,
            "authorization_sha256": None,
            "paper_account_fingerprint": None,
            "promotion_evidence_id": staged_intent.promotion_evidence_id,
            "genome_id": staged_intent.genome.genome_id,
            "genome_canonical_sha256": (
                staged_intent.genome_canonical_sha256
            ),
            "evaluation_code_commit": staged_intent.evaluation_code_commit,
            "evaluation_runtime_sha256": (
                staged_intent.evaluation_runtime_sha256
            ),
            "session_date": staged_intent.session_date,
            "observed_at": observed_at,
            "decision_action": staged_intent.decision.action.value,
            "paper_order_receipt": None,
            "reconciliation_receipt": None,
            "receipt_sha256": None,
            "reconciliation_sha256": None,
            "adverse_fill_vs_reference_fraction": "0",
            "gates": [["no_order_expected", True]],
            "issues": [],
            "operationally_reconciled": True,
            "verified_by_role": verified_by_role,
            "analysis_only": True,
            "paper_only": True,
            "execution_authority": "none",
            "can_submit_orders": False,
        }
    if (
        staged_intent.decision.action is not PaperDecisionAction.BUY
        or authorization is None
        or paper_order_receipt is None
        or reconciliation_receipt is None
    ):
        raise ValueError("BUY observation requires complete order facts")
    reference = _selected_reference_price(staged_intent)
    filled_average = _require_operand_decimal(
        paper_order_receipt.filled_avg_price,
        label="filled_avg_price",
    )
    with localcontext(_fraction_context()):
        adverse = (
            max(Decimal(0), filled_average - reference) / reference
            if filled_average > 0
            else Decimal(0)
        )
    adverse_text = _plain_decimal(adverse)
    _require_derived_fraction(
        adverse_text,
        label="adverse_fill_vs_reference_fraction",
    )
    terminal_filled = paper_order_receipt.status == "filled"
    fill_respected_limit = (
        filled_average
        <= _require_operand_decimal(
            authorization.requested_limit_price,
            label="authorization.requested_limit_price",
            positive=True,
            canonical_money=True,
        )
    )
    gates = (
        ("terminal_filled", terminal_filled),
        ("fill_respected_limit", fill_respected_limit),
        ("operationally_reconciled", True),
    )
    issues = [
        SHADOW_OBSERVATION_ISSUE_BY_GATE[name]
        for name, passed in gates
        if not passed
    ]
    return {
        "schema_version": ADMITTED_PAPER_SHADOW_OBSERVATION_SCHEMA_VERSION,
        "staged_intent_id": staged_intent.staged_intent_id,
        "staged_intent_sha256": hashlib.sha256(
            staged_intent.canonical_json_bytes()
        ).hexdigest(),
        "authorization_id": authorization.authorization_id,
        "authorization_sha256": hashlib.sha256(
            authorization.canonical_json_bytes()
        ).hexdigest(),
        "paper_account_fingerprint": (
            authorization.paper_account_fingerprint
        ),
        "promotion_evidence_id": staged_intent.promotion_evidence_id,
        "genome_id": staged_intent.genome.genome_id,
        "genome_canonical_sha256": (
            staged_intent.genome_canonical_sha256
        ),
        "evaluation_code_commit": staged_intent.evaluation_code_commit,
        "evaluation_runtime_sha256": (
            staged_intent.evaluation_runtime_sha256
        ),
        "session_date": staged_intent.session_date,
        "observed_at": observed_at,
        "decision_action": staged_intent.decision.action.value,
        "paper_order_receipt": paper_order_receipt.to_dict(),
        "reconciliation_receipt": reconciliation_receipt.to_dict(),
        "receipt_sha256": hashlib.sha256(
            paper_order_receipt.canonical_json_bytes()
        ).hexdigest(),
        "reconciliation_sha256": hashlib.sha256(
            reconciliation_receipt.canonical_json_bytes()
        ).hexdigest(),
        "adverse_fill_vs_reference_fraction": adverse_text,
        "gates": [[name, passed] for name, passed in gates],
        "issues": issues,
        "operationally_reconciled": True,
        "verified_by_role": verified_by_role,
        "analysis_only": True,
        "paper_only": True,
        "execution_authority": "none",
        "can_submit_orders": False,
    }


def _require_hold_observation_bindings(
    observation: AdmittedPaperShadowObservation,
    *,
    staged_intent: StagedPaperIntent,
    verified_by_role: str,
) -> None:
    if staged_intent.decision.action is not PaperDecisionAction.HOLD_CASH:
        raise ValueError("HOLD observation requires a staged HOLD")
    expected_payload = _observation_payload(
        staged_intent=staged_intent,
        observed_at=observation.observed_at,
        verified_by_role=verified_by_role,
    )
    if observation._evidence_payload() != expected_payload:
        raise ValueError("HOLD observation does not match durable staged intent")
    observed = _require_canonical_utc(
        observation.observed_at,
        label="observed_at",
    )
    recorded = _require_canonical_utc(
        observation.recorded_at,
        label="recorded_at",
    )
    staged_recorded = _require_canonical_utc(
        staged_intent.recorded_at,
        label="staged_intent.recorded_at",
    )
    staged_expires = _require_canonical_utc(
        staged_intent.expires_at,
        label="staged_intent.expires_at",
    )
    if not staged_recorded <= observed < staged_expires:
        raise ValueError("HOLD observed_at must fall within staged activity")
    if observed > recorded:
        raise ValueError("future HOLD observation is not allowed")
    if observation.effective_at != observation.observed_at:
        raise ValueError("HOLD effective_at must equal observed_at")
    if (
        observed.astimezone(ZoneInfo("America/New_York")).date().isoformat()
        != staged_intent.session_date
    ):
        raise ValueError("HOLD observed_at does not match session_date")


def _require_buy_observation_bindings(
    observation: AdmittedPaperShadowObservation,
    *,
    staged_intent: StagedPaperIntent,
    authorization: AuthorizedPaperOrderRequest,
    verified_by_role: str,
) -> None:
    receipt = observation.paper_order_receipt
    reconciliation = observation.reconciliation_receipt
    if (
        type(receipt) is not PaperOrderReceipt
        or type(reconciliation) is not PaperReconciliationReceipt
    ):
        raise ValueError("BUY observation requires both receipt types")
    _require_buy_receipt_structure(
        staged_intent=staged_intent,
        authorization=authorization,
        paper_order_receipt=receipt,
        reconciliation_receipt=reconciliation,
        observed_at=observation.observed_at,
        verified_by_role=verified_by_role,
    )
    if receipt.status == "partially_filled":
        raise ValueError("partial shadow evidence cannot be durable")
    expected_payload = _observation_payload(
        staged_intent=staged_intent,
        observed_at=observation.observed_at,
        verified_by_role=verified_by_role,
        authorization=authorization,
        paper_order_receipt=receipt,
        reconciliation_receipt=reconciliation,
    )
    if observation._evidence_payload() != expected_payload:
        raise ValueError("BUY observation does not match durable order facts")
    observed = _require_canonical_utc(
        observation.observed_at,
        label="observed_at",
    )
    recorded = _require_canonical_utc(
        observation.recorded_at,
        label="recorded_at",
    )
    if observed > recorded:
        raise ValueError("future BUY observation is not allowed")
    if observation.effective_at != observation.observed_at:
        raise ValueError("BUY effective_at must equal observed_at")


def _order_identity(
    *,
    staged_intent_id: str,
    authorization_id: str,
    paper_account_fingerprint: str,
) -> tuple[str, str, str]:
    return (
        staged_intent_id,
        authorization_id,
        paper_account_fingerprint,
    )


def _require_observation_uniqueness(
    snapshot: Sequence[EvidenceEnvelope],
    observation: AdmittedPaperShadowObservation,
    *,
    tolerate_invalid: bool = False,
    orphan_snapshot: Sequence[EvidenceEnvelope] = (),
) -> None:
    slot_by_staged: dict[str, str] = {}
    logical_by_value: dict[str, tuple[str, str, str]] = {}
    client_by_value: dict[str, tuple[str, str, str]] = {}
    broker_by_value: dict[str, tuple[str, str, str]] = {}

    def bind(
        index: dict[str, tuple[str, str, str]],
        value: str,
        identity: tuple[str, str, str],
        *,
        label: str,
    ) -> None:
        prior = index.setdefault(value, identity)
        if prior != identity:
            raise ValueError(f"global {label} collision")

    for source, suppress_domain_errors in (
        (snapshot, tolerate_invalid),
        (orphan_snapshot, True),
    ):
        for envelope in source:
            if envelope.object_id == observation.shadow_observation_id:
                continue
            authorization: AuthorizedPaperOrderRequest | None = None
            existing: AdmittedPaperShadowObservation | None = None
            try:
                if envelope.kind == PAPER_EXECUTION_AUTHORIZATION_KIND:
                    authorization = _authorization_from_envelope(envelope)
                elif envelope.kind == PAPER_SHADOW_OBSERVATION_KIND:
                    existing = _observation_from_envelope(envelope)
                else:
                    continue
            except (TypeError, ValueError):
                if suppress_domain_errors:
                    continue
                raise
            if authorization is not None:
                identity = _order_identity(
                    staged_intent_id=authorization.staged_intent_id,
                    authorization_id=authorization.authorization_id,
                    paper_account_fingerprint=(
                        authorization.paper_account_fingerprint
                    ),
                )
                bind(
                    logical_by_value,
                    authorization.logical_order_sha256,
                    identity,
                    label="logical_order_sha256",
                )
                bind(
                    client_by_value,
                    authorization.client_order_id,
                    identity,
                    label="client_order_id",
                )
                continue
            assert existing is not None
            prior_observation = slot_by_staged.setdefault(
                existing.staged_intent_id,
                existing.shadow_observation_id,
            )
            if prior_observation != existing.shadow_observation_id:
                raise ValueError(
                    "one shadow observation may bind one staged intent"
                )
            if (
                existing.authorization_id is None
                or existing.paper_account_fingerprint is None
                or existing.paper_order_receipt is None
            ):
                continue
            identity = _order_identity(
                staged_intent_id=existing.staged_intent_id,
                authorization_id=existing.authorization_id,
                paper_account_fingerprint=existing.paper_account_fingerprint,
            )
            bind(
                logical_by_value,
                existing.paper_order_receipt.logical_order_sha256,
                identity,
                label="logical_order_sha256",
            )
            bind(
                client_by_value,
                existing.paper_order_receipt.client_order_id,
                identity,
                label="client_order_id",
            )
            bind(
                broker_by_value,
                existing.paper_order_receipt.broker_order_id,
                identity,
                label="broker_order_id",
            )

    prior_observation = slot_by_staged.setdefault(
        observation.staged_intent_id,
        observation.shadow_observation_id,
    )
    if prior_observation != observation.shadow_observation_id:
        raise ValueError("one shadow observation may bind one staged intent")
    if (
        observation.authorization_id is None
        or observation.paper_account_fingerprint is None
        or observation.paper_order_receipt is None
    ):
        return
    identity = _order_identity(
        staged_intent_id=observation.staged_intent_id,
        authorization_id=observation.authorization_id,
        paper_account_fingerprint=observation.paper_account_fingerprint,
    )
    bind(
        logical_by_value,
        observation.paper_order_receipt.logical_order_sha256,
        identity,
        label="logical_order_sha256",
    )
    bind(
        client_by_value,
        observation.paper_order_receipt.client_order_id,
        identity,
        label="client_order_id",
    )
    bind(
        broker_by_value,
        observation.paper_order_receipt.broker_order_id,
        identity,
        label="broker_order_id",
    )


def _require_full_staged_lineage(
    *,
    staged_intent: StagedPaperIntent,
    registration: object,
    promotion_evidence: StrategyPromotionEvidence,
) -> None:
    registration_id = getattr(registration, "registration_id", None)
    registration_genome = getattr(registration, "genome", None)
    registration_policy = getattr(registration, "evolution_policy", None)
    registration_policy_sha256 = getattr(
        registration,
        "evolution_policy_sha256",
        None,
    )
    promotion_sha256 = hashlib.sha256(
        promotion_evidence.canonical_json_bytes()
    ).hexdigest()
    if (
        staged_intent.registration_id != registration_id
        or staged_intent.promotion_evidence_id != promotion_evidence.evidence_id
        or staged_intent.promotion_evidence_sha256 != promotion_sha256
        or promotion_evidence.registration_id != registration_id
        or getattr(registration_genome, "genome_id", None)
        != staged_intent.genome.genome_id
        or staged_intent.genome.canonical_json_bytes()
        != registration_genome.canonical_json_bytes()
        or staged_intent.genome.genome_id != promotion_evidence.genome_id
        or staged_intent.genome_canonical_sha256
        != getattr(registration, "genome_canonical_sha256", None)
        or staged_intent.genome_canonical_sha256
        != promotion_evidence.genome_canonical_sha256
        or staged_intent.evaluation_code_commit
        != getattr(registration, "evaluation_code_commit", None)
        or staged_intent.evaluation_code_commit
        != promotion_evidence.evaluation_code_commit
        or staged_intent.evaluation_runtime_sha256
        != getattr(registration, "evaluation_runtime_sha256", None)
        or staged_intent.evaluation_runtime_sha256
        != promotion_evidence.evaluation_runtime_sha256
        or registration_policy is None
        or staged_intent.evolution_policy.canonical_json_bytes()
        != registration_policy.canonical_json_bytes()
        or staged_intent.evolution_policy_sha256
        != registration_policy_sha256
        or staged_intent.evolution_policy_sha256
        != hashlib.sha256(
            staged_intent.evolution_policy.canonical_json_bytes()
        ).hexdigest()
    ):
        raise ValueError("full staged lineage does not match")
    if not promotion_evidence.complete_internal_evidence:
        raise ValueError("internal promotion evidence is incomplete")


def _require_observation_lineage(
    observation: AdmittedPaperShadowObservation,
    *,
    staged_intent: StagedPaperIntent,
    registration: object,
    promotion_evidence: StrategyPromotionEvidence,
) -> None:
    _require_full_staged_lineage(
        staged_intent=staged_intent,
        registration=registration,
        promotion_evidence=promotion_evidence,
    )
    expected = (
        staged_intent.promotion_evidence_id,
        staged_intent.genome.genome_id,
        staged_intent.genome_canonical_sha256,
        staged_intent.evaluation_code_commit,
        staged_intent.evaluation_runtime_sha256,
    )
    actual = (
        observation.promotion_evidence_id,
        observation.genome_id,
        observation.genome_canonical_sha256,
        observation.evaluation_code_commit,
        observation.evaluation_runtime_sha256,
    )
    if expected != actual:
        raise ValueError("shadow observation lineage does not match")


def _validate_observation_from_prefix(
    prefix: Sequence[EvidenceEnvelope],
    envelope: EvidenceEnvelope,
) -> tuple[
    AdmittedPaperShadowObservation,
    StagedPaperIntent,
    object,
    StrategyPromotionEvidence,
]:
    observation = _observation_from_envelope(envelope)
    staged_intent, registration = _staged_with_registration_from_snapshot(
        prefix,
        observation.staged_intent_id,
    )
    promotion_evidence = _promotion_from_snapshot(
        prefix,
        observation.promotion_evidence_id,
    )
    verified_by_role = _required_verify_owner(observation.verified_by_role)
    _require_observation_lineage(
        observation,
        staged_intent=staged_intent,
        registration=registration,
        promotion_evidence=promotion_evidence,
    )
    if staged_intent.decision.action is PaperDecisionAction.HOLD_CASH:
        _require_hold_observation_bindings(
            observation,
            staged_intent=staged_intent,
            verified_by_role=verified_by_role,
        )
    else:
        if observation.authorization_id is None:
            raise ValueError("BUY observation authorization is missing")
        authorization = _authorization_from_prefix(
            prefix,
            observation.authorization_id,
        )
        _require_buy_observation_bindings(
            observation,
            staged_intent=staged_intent,
            authorization=authorization,
            verified_by_role=verified_by_role,
        )
    _require_observation_uniqueness(prefix, observation)
    return observation, staged_intent, registration, promotion_evidence


def _durable_observations_from_prefix(
    prefix: Sequence[EvidenceEnvelope],
    observations: Sequence[AdmittedPaperShadowObservation],
) -> tuple[AdmittedPaperShadowObservation, ...]:
    result: list[AdmittedPaperShadowObservation] = []
    for caller in observations:
        matches = tuple(
            (index, envelope)
            for index, envelope in enumerate(prefix)
            if envelope.kind == PAPER_SHADOW_OBSERVATION_KIND
            and envelope.object_id == caller.shadow_observation_id
        )
        if len(matches) != 1:
            raise ValueError(
                "shadow observation must already be durable in this store"
            )
        index, envelope = matches[0]
        durable, _, _, _ = _validate_observation_from_prefix(
            prefix[:index],
            envelope,
        )
        if caller.canonical_json_bytes() != durable.canonical_json_bytes():
            raise ValueError("caller observation does not match durable bytes")
        result.append(durable)
    return tuple(result)


def _require_common_aggregate_lineage(
    *,
    promotion_evidence: StrategyPromotionEvidence,
    registration: object,
    observations: Sequence[AdmittedPaperShadowObservation],
) -> None:
    expected = (
        promotion_evidence.evidence_id,
        promotion_evidence.genome_id,
        promotion_evidence.genome_canonical_sha256,
        promotion_evidence.evaluation_code_commit,
        promotion_evidence.evaluation_runtime_sha256,
    )
    for observation in observations:
        actual = (
            observation.promotion_evidence_id,
            observation.genome_id,
            observation.genome_canonical_sha256,
            observation.evaluation_code_commit,
            observation.evaluation_runtime_sha256,
        )
        if actual != expected:
            raise ValueError("observations do not share aggregate lineage")
    if (
        getattr(registration, "registration_id", None)
        != promotion_evidence.registration_id
    ):
        raise ValueError("promotion registration does not match")


def _aggregate_payload(
    *,
    promotion_evidence: StrategyPromotionEvidence,
    registration: object,
    observations: Sequence[AdmittedPaperShadowObservation],
    assembled_by_role: str,
) -> tuple[str, dict[str, object]]:
    if not observations:
        raise ValueError("at least one shadow observation is required")
    if len(observations) > SHADOW_ATTESTATION_MAX_OBSERVATIONS:
        raise ValueError("too many shadow observations")
    ordered = tuple(
        sorted(
            observations,
            key=lambda item: (item.session_date, item.staged_intent_id),
        )
    )
    ids = tuple(item.shadow_observation_id for item in ordered)
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate shadow observation IDs are not allowed")
    _require_common_aggregate_lineage(
        promotion_evidence=promotion_evidence,
        registration=registration,
        observations=ordered,
    )
    account_values = {
        item.paper_account_fingerprint
        for item in ordered
        if item.decision_action == "buy"
    }
    if None in account_values or len(account_values) > 1:
        raise ValueError("BUY observations require one stable paper account")
    account = next(iter(account_values), None)
    hold_count = sum(item.decision_action == "hold-cash" for item in ordered)
    buy_observations = tuple(
        item for item in ordered if item.decision_action == "buy"
    )
    filled_count = sum(
        item.paper_order_receipt is not None
        and item.paper_order_receipt.status == "filled"
        for item in buy_observations
    )
    reconciled_count = sum(
        item.operationally_reconciled for item in buy_observations
    )
    with localcontext(_money_context()):
        requested_total = Decimal(0)
        filled_total = Decimal(0)
        fees_total = Decimal(0)
        for observation in buy_observations:
            receipt = observation.paper_order_receipt
            if receipt is None:
                raise ValueError("BUY aggregate observation lacks a receipt")
            requested = _require_operand_decimal(
                receipt.requested_notional_usd,
                label="requested_notional_usd",
                positive=True,
                canonical_money=True,
            )
            quantity = _require_operand_decimal(
                receipt.filled_qty,
                label="filled_qty",
            )
            average = _require_operand_decimal(
                receipt.filled_avg_price,
                label="filled_avg_price",
            )
            fees = _require_operand_decimal(
                receipt.fees_usd,
                label="fees_usd",
            )
            requested_total += requested
            filled_total += quantity * average
            fees_total += fees
        quantum = Decimal("0.01")
        requested_text = _plain_decimal(
            requested_total.quantize(quantum, rounding=ROUND_DOWN)
        )
        filled_text = _plain_decimal(
            filled_total.quantize(quantum, rounding=ROUND_DOWN)
        )
        fees_text = _plain_decimal(
            fees_total.quantize(quantum, rounding=ROUND_DOWN)
        )
    for label, value in (
        ("total_requested_notional_usd", requested_text),
        ("total_filled_notional_usd", filled_text),
        ("total_fees_usd", fees_text),
    ):
        _require_derived_money(value, label=label)
    with localcontext(_fraction_context()):
        adverse_values = tuple(
            _require_derived_fraction(
                item.adverse_fill_vs_reference_fraction,
                label="adverse_fill_vs_reference_fraction",
            )
            for item in ordered
        )
        worst_text = _plain_decimal(max(adverse_values))
    _require_derived_fraction(
        worst_text,
        label="worst_adverse_fill_vs_reference_fraction",
    )
    tracked_sessions = len({item.session_date for item in ordered})
    minimum_days = getattr(
        getattr(registration, "evolution_policy", None),
        "minimum_tracked_days",
        None,
    )
    if type(minimum_days) is not int:
        raise ValueError("registration evolution policy is unavailable")
    all_terminal = all(
        item.paper_order_receipt is not None
        and item.paper_order_receipt.status == "filled"
        for item in buy_observations
    )
    all_clean = all(
        item.operationally_reconciled
        and item.reconciliation_receipt is not None
        and item.reconciliation_receipt.read_only
        and item.reconciliation_receipt.broker_write_calls == 0
        for item in buy_observations
    )
    gates = (
        ("internal_evidence_complete", True),
        ("minimum_tracked_sessions", tracked_sessions >= minimum_days),
        ("all_intents_current_when_observed", True),
        ("all_buy_intents_paper_only", True),
        ("all_order_fields_match", True),
        ("all_buy_intents_terminal_filled", all_terminal),
        ("all_reconciliations_clean", all_clean),
        (
            "at_least_one_reconciled_buy",
            any(
                item.paper_order_receipt is not None
                and item.paper_order_receipt.status == "filled"
                and item.operationally_reconciled
                for item in buy_observations
            ),
        ),
    )
    invariant_names = {
        "internal_evidence_complete",
        "all_intents_current_when_observed",
        "all_buy_intents_paper_only",
        "all_order_fields_match",
        "all_reconciliations_clean",
    }
    if any(not passed and name in invariant_names for name, passed in gates):
        raise ValueError("shadow aggregate admission invariant failed")
    issues = [
        SHADOW_ATTESTATION_ISSUE_BY_GATE[name]
        for name, passed in gates
        if not passed
    ]
    effective_at = max(item.observed_at for item in ordered)
    return effective_at, {
        "schema_version": STRATEGY_SHADOW_ATTESTATION_SCHEMA_VERSION,
        "registration_id": promotion_evidence.registration_id,
        "promotion_evidence_id": promotion_evidence.evidence_id,
        "promotion_evidence_sha256": hashlib.sha256(
            promotion_evidence.canonical_json_bytes()
        ).hexdigest(),
        "genome_id": promotion_evidence.genome_id,
        "genome_canonical_sha256": (
            promotion_evidence.genome_canonical_sha256
        ),
        "evaluation_code_commit": promotion_evidence.evaluation_code_commit,
        "evaluation_runtime_sha256": (
            promotion_evidence.evaluation_runtime_sha256
        ),
        "paper_account_fingerprint": account,
        "shadow_observation_ids": list(ids),
        "shadow_observation_sha256s": [
            hashlib.sha256(item.canonical_json_bytes()).hexdigest()
            for item in ordered
        ],
        "first_session_date": ordered[0].session_date,
        "last_session_date": ordered[-1].session_date,
        "tracked_sessions": tracked_sessions,
        "total_intents": len(ordered),
        "hold_intents": hold_count,
        "buy_intents": len(buy_observations),
        "reconciled_buy_intents": reconciled_count,
        "filled_buy_intents": filled_count,
        "total_requested_notional_usd": requested_text,
        "total_filled_notional_usd": filled_text,
        "total_fees_usd": fees_text,
        "worst_adverse_fill_vs_reference_fraction": worst_text,
        "gates": [[name, passed] for name, passed in gates],
        "issues": issues,
        "shadow_sessions_sufficient": dict(gates)[
            "minimum_tracked_sessions"
        ],
        "reconciliation_confirmed": (
            bool(buy_observations) and all_terminal and all_clean
        ),
        "assembled_by_role": assembled_by_role,
        "analysis_only": True,
        "paper_only": True,
        "execution_authority": "none",
        "can_submit_orders": False,
    }


def _require_attestation_tuple_unique(
    snapshot: Sequence[EvidenceEnvelope],
    attestation: StrategyShadowAttestation,
    *,
    orphan_snapshot: Sequence[EvidenceEnvelope] = (),
) -> None:
    meanings_by_tuple: dict[tuple[str, ...], bytes] = {}

    def bind(existing: StrategyShadowAttestation) -> None:
        observation_ids = existing.shadow_observation_ids
        meaning = existing.canonical_json_bytes()
        prior_meaning = meanings_by_tuple.get(observation_ids)
        if prior_meaning is not None and prior_meaning != meaning:
            raise ValueError("shadow attestation observation tuple collision")
        meanings_by_tuple[observation_ids] = meaning

    for envelope in snapshot:
        if envelope.kind != PAPER_SHADOW_ATTESTATION_KIND:
            continue
        bind(_attestation_from_envelope(envelope))

    for envelope in orphan_snapshot:
        if (
            envelope.kind != PAPER_SHADOW_ATTESTATION_KIND
            or envelope.object_id == attestation.shadow_attestation_id
        ):
            continue
        try:
            orphan = _attestation_from_envelope(envelope)
        except (TypeError, ValueError):
            continue
        bind(orphan)

    bind(attestation)


class StrategyShadowEvidenceLedger:
    def __init__(
        self,
        root: str | Path,
        *,
        repo_root: str | Path,
        clock: Callable[[], dt.datetime] | None = None,
    ):
        self._repo_root = Path(repo_root)
        self._store = ImmutableStrategyEvidenceStore(root, clock=clock)

    def admit_observation(
        self,
        *,
        staged_intent: StagedPaperIntent,
        authorization: AuthorizedPaperOrderRequest | None,
        observed_at: dt.datetime,
        paper_order_receipt: PaperOrderReceipt | None,
        reconciliation_receipt: PaperReconciliationReceipt | None,
        actor_role: str,
    ) -> AdmittedPaperShadowObservation | None:
        if type(staged_intent) is not StagedPaperIntent:
            raise TypeError("staged_intent must be a StagedPaperIntent")
        if (
            authorization is not None
            and type(authorization) is not AuthorizedPaperOrderRequest
        ):
            raise TypeError(
                "authorization must be an AuthorizedPaperOrderRequest or None"
            )
        if (
            paper_order_receipt is not None
            and type(paper_order_receipt) is not PaperOrderReceipt
        ):
            raise TypeError(
                "paper_order_receipt must be a PaperOrderReceipt or None"
            )
        if (
            reconciliation_receipt is not None
            and type(reconciliation_receipt)
            is not PaperReconciliationReceipt
        ):
            raise TypeError(
                "reconciliation_receipt must be a "
                "PaperReconciliationReceipt or None"
            )
        verified_by_role = _required_verify_owner(actor_role)
        observed_text = _datetime_text(observed_at, label="observed_at")
        snapshot = self._store.rebuild()
        durable_staged, registration = _staged_with_registration_from_snapshot(
            snapshot,
            staged_intent.staged_intent_id,
        )
        if (
            staged_intent.canonical_json_bytes()
            != durable_staged.canonical_json_bytes()
        ):
            raise ValueError("caller staged intent does not match durable bytes")
        durable_promotion = _promotion_from_snapshot(
            snapshot,
            durable_staged.promotion_evidence_id,
        )
        _require_full_staged_lineage(
            staged_intent=durable_staged,
            registration=registration,
            promotion_evidence=durable_promotion,
        )
        durable_authorization: AuthorizedPaperOrderRequest | None = None
        if durable_staged.decision.action is PaperDecisionAction.BUY:
            if (
                authorization is None
                or paper_order_receipt is None
                or reconciliation_receipt is None
            ):
                raise ValueError(
                    "BUY observation requires authorization and both receipts"
                )
            durable_authorization = _authorization_from_prefix(
                snapshot,
                authorization.authorization_id,
            )
            if (
                authorization.canonical_json_bytes()
                != durable_authorization.canonical_json_bytes()
            ):
                raise ValueError(
                    "caller authorization does not match durable bytes"
                )
        manifest_before = require_active_evaluation_runtime(
            self._repo_root,
            registration,
        )
        candidate: EvidenceCandidate | None = None
        if durable_staged.decision.action is PaperDecisionAction.HOLD_CASH:
            if any(
                value is not None
                for value in (
                    authorization,
                    paper_order_receipt,
                    reconciliation_receipt,
                )
            ):
                raise ValueError("HOLD observation cannot contain order facts")
            candidate = EvidenceCandidate(
                kind=PAPER_SHADOW_OBSERVATION_KIND,
                effective_at=observed_text,
                payload=_observation_payload(
                    staged_intent=durable_staged,
                    observed_at=observed_text,
                    verified_by_role=verified_by_role,
                ),
            )
        elif durable_staged.decision.action is PaperDecisionAction.BUY:
            assert durable_authorization is not None
            assert paper_order_receipt is not None
            assert reconciliation_receipt is not None
            _require_buy_receipt_structure(
                staged_intent=durable_staged,
                authorization=durable_authorization,
                paper_order_receipt=paper_order_receipt,
                reconciliation_receipt=reconciliation_receipt,
                observed_at=observed_text,
                verified_by_role=verified_by_role,
            )
            if paper_order_receipt.status != "partially_filled":
                candidate = EvidenceCandidate(
                    kind=PAPER_SHADOW_OBSERVATION_KIND,
                    effective_at=observed_text,
                    payload=_observation_payload(
                        staged_intent=durable_staged,
                        observed_at=observed_text,
                        verified_by_role=verified_by_role,
                        authorization=durable_authorization,
                        paper_order_receipt=paper_order_receipt,
                        reconciliation_receipt=reconciliation_receipt,
                    ),
                )
        if (
            durable_staged.decision.action is PaperDecisionAction.BUY
            and paper_order_receipt is not None
            and paper_order_receipt.status == "partially_filled"
        ):
            assert durable_authorization is not None
            assert reconciliation_receipt is not None

            def validate_partial(
                admitted: tuple[EvidenceEnvelope, ...],
                orphans: tuple[EvidenceEnvelope, ...],
                recorded_at: str,
            ) -> None:
                locked_staged, locked_registration = (
                    _staged_with_registration_from_snapshot(
                        admitted,
                        durable_staged.staged_intent_id,
                    )
                )
                locked_promotion = _promotion_from_snapshot(
                    admitted,
                    durable_promotion.evidence_id,
                )
                locked_authorization = _authorization_from_prefix(
                    admitted,
                    durable_authorization.authorization_id,
                )
                if (
                    locked_staged.canonical_json_bytes()
                    != durable_staged.canonical_json_bytes()
                    or locked_registration.canonical_json_bytes()
                    != registration.canonical_json_bytes()
                    or locked_promotion.canonical_json_bytes()
                    != durable_promotion.canonical_json_bytes()
                    or locked_authorization.canonical_json_bytes()
                    != durable_authorization.canonical_json_bytes()
                ):
                    raise ValueError(
                        "durable dependency changed during partial validation"
                    )
                locked_verify_owner = _required_verify_owner(
                    verified_by_role
                )
                _require_full_staged_lineage(
                    staged_intent=locked_staged,
                    registration=locked_registration,
                    promotion_evidence=locked_promotion,
                )
                _require_buy_receipt_structure(
                    staged_intent=locked_staged,
                    authorization=locked_authorization,
                    paper_order_receipt=paper_order_receipt,
                    reconciliation_receipt=reconciliation_receipt,
                    observed_at=observed_text,
                    verified_by_role=locked_verify_owner,
                )
                payload = _observation_payload(
                    staged_intent=locked_staged,
                    observed_at=observed_text,
                    verified_by_role=locked_verify_owner,
                    authorization=locked_authorization,
                    paper_order_receipt=paper_order_receipt,
                    reconciliation_receipt=reconciliation_receipt,
                )
                object_id = _expected_object_id(
                    kind=PAPER_SHADOW_OBSERVATION_KIND,
                    effective_at=observed_text,
                    payload=payload,
                )
                partial_observation = (
                    AdmittedPaperShadowObservation.from_dict(
                        {
                            **payload,
                            "shadow_observation_id": object_id,
                            "effective_at": observed_text,
                            "recorded_at": recorded_at,
                        }
                    )
                )
                _require_observation_lineage(
                    partial_observation,
                    staged_intent=locked_staged,
                    registration=locked_registration,
                    promotion_evidence=locked_promotion,
                )
                _require_observation_uniqueness(
                    admitted,
                    partial_observation,
                    orphan_snapshot=orphans,
                )

            self._store.validate_read_only(validate_partial)
            manifest_after = require_active_evaluation_runtime(
                self._repo_root,
                registration,
            )
            if (
                manifest_before.canonical_json_bytes()
                != manifest_after.canonical_json_bytes()
            ):
                raise ValueError(
                    "active evaluation runtime changed during shadow observation"
                )
            return None
        manifest_after = require_active_evaluation_runtime(
            self._repo_root,
            registration,
        )
        if (
            manifest_before.canonical_json_bytes()
            != manifest_after.canonical_json_bytes()
        ):
            raise ValueError(
                "active evaluation runtime changed during shadow observation"
            )
        if candidate is None:
            raise ValueError("staged decision action is not supported")

        def validate(
            admitted: tuple[EvidenceEnvelope, ...],
            envelope: EvidenceEnvelope,
        ) -> None:
            locked_staged, locked_registration = (
                _staged_with_registration_from_snapshot(
                    admitted,
                    durable_staged.staged_intent_id,
                )
            )
            if (
                locked_staged.canonical_json_bytes()
                != durable_staged.canonical_json_bytes()
            ):
                raise ValueError(
                    "durable staged intent changed during shadow admission"
                )
            if (
                locked_registration.canonical_json_bytes()
                != registration.canonical_json_bytes()
            ):
                raise ValueError(
                    "durable registration changed during shadow admission"
                )
            locked_promotion = _promotion_from_snapshot(
                admitted,
                durable_promotion.evidence_id,
            )
            if (
                locked_promotion.canonical_json_bytes()
                != durable_promotion.canonical_json_bytes()
            ):
                raise ValueError(
                    "durable promotion changed during shadow admission"
                )
            locked_verify_owner = _required_verify_owner(verified_by_role)
            observation = _observation_from_envelope(envelope)
            _require_observation_lineage(
                observation,
                staged_intent=locked_staged,
                registration=locked_registration,
                promotion_evidence=locked_promotion,
            )
            if locked_staged.decision.action is PaperDecisionAction.HOLD_CASH:
                _require_hold_observation_bindings(
                    observation,
                    staged_intent=locked_staged,
                    verified_by_role=locked_verify_owner,
                )
            else:
                if durable_authorization is None:
                    raise ValueError("durable BUY authorization is missing")
                locked_authorization = _authorization_from_prefix(
                    admitted,
                    durable_authorization.authorization_id,
                )
                if (
                    locked_authorization.canonical_json_bytes()
                    != durable_authorization.canonical_json_bytes()
                ):
                    raise ValueError(
                        "durable authorization changed during shadow admission"
                    )
                _require_buy_observation_bindings(
                    observation,
                    staged_intent=locked_staged,
                    authorization=locked_authorization,
                    verified_by_role=locked_verify_owner,
                )

        def validate_combined(
            admitted: tuple[EvidenceEnvelope, ...],
            orphans: tuple[EvidenceEnvelope, ...],
            envelope: EvidenceEnvelope,
        ) -> None:
            observation = _observation_from_envelope(envelope)
            _require_observation_uniqueness(
                admitted,
                observation,
                orphan_snapshot=orphans,
            )

        admission = self._store.admit_checked(
            candidate,
            validate=validate,
            validate_combined=validate_combined,
        )
        return _observation_from_envelope(admission.envelope)

    def assemble(
        self,
        *,
        promotion_evidence: StrategyPromotionEvidence,
        observations: Sequence[AdmittedPaperShadowObservation],
        actor_role: str,
    ) -> StrategyShadowAttestation:
        if type(promotion_evidence) is not StrategyPromotionEvidence:
            raise TypeError(
                "promotion_evidence must be a StrategyPromotionEvidence"
            )
        if isinstance(observations, (str, bytes)) or not isinstance(
            observations,
            Sequence,
        ):
            raise TypeError("observations must be a sequence")
        observation_count = len(observations)
        if observation_count == 0:
            raise ValueError("at least one shadow observation is required")
        if observation_count > SHADOW_ATTESTATION_MAX_OBSERVATIONS:
            raise ValueError("too many shadow observations")
        caller_observations = tuple(observations)
        if len(caller_observations) != observation_count:
            raise ValueError("observation sequence changed during snapshot")
        if any(
            type(item) is not AdmittedPaperShadowObservation
            for item in caller_observations
        ):
            raise TypeError(
                "observations must contain admitted shadow observations"
            )
        if len(
            {item.shadow_observation_id for item in caller_observations}
        ) != len(caller_observations):
            raise ValueError("duplicate shadow observation IDs are not allowed")
        assembled_by_role = _required_verify_owner(actor_role)
        snapshot = self._store.rebuild()
        durable_promotion = _promotion_from_snapshot(
            snapshot,
            promotion_evidence.evidence_id,
        )
        if (
            promotion_evidence.canonical_json_bytes()
            != durable_promotion.canonical_json_bytes()
        ):
            raise ValueError(
                "caller promotion evidence does not match durable bytes"
            )
        durable_observations = _durable_observations_from_prefix(
            snapshot,
            caller_observations,
        )
        _, registration = _staged_with_registration_from_snapshot(
            snapshot,
            durable_observations[0].staged_intent_id,
        )
        manifest_before = require_active_evaluation_runtime(
            self._repo_root,
            registration,
        )
        effective_at, payload = _aggregate_payload(
            promotion_evidence=durable_promotion,
            registration=registration,
            observations=durable_observations,
            assembled_by_role=assembled_by_role,
        )
        candidate = EvidenceCandidate(
            kind=PAPER_SHADOW_ATTESTATION_KIND,
            effective_at=effective_at,
            payload=payload,
        )
        manifest_after = require_active_evaluation_runtime(
            self._repo_root,
            registration,
        )
        if (
            manifest_before.canonical_json_bytes()
            != manifest_after.canonical_json_bytes()
        ):
            raise ValueError(
                "active evaluation runtime changed during shadow assembly"
            )

        def validate(
            admitted: tuple[EvidenceEnvelope, ...],
            envelope: EvidenceEnvelope,
        ) -> None:
            locked_promotion = _promotion_from_snapshot(
                admitted,
                durable_promotion.evidence_id,
            )
            if (
                locked_promotion.canonical_json_bytes()
                != durable_promotion.canonical_json_bytes()
            ):
                raise ValueError(
                    "durable promotion changed during shadow assembly"
                )
            locked_observations = _durable_observations_from_prefix(
                admitted,
                durable_observations,
            )
            _, locked_registration = (
                _staged_with_registration_from_snapshot(
                    admitted,
                    locked_observations[0].staged_intent_id,
                )
            )
            locked_assembled_by_role = _required_verify_owner(
                assembled_by_role
            )
            locked_effective, locked_payload = _aggregate_payload(
                promotion_evidence=locked_promotion,
                registration=locked_registration,
                observations=locked_observations,
                assembled_by_role=locked_assembled_by_role,
            )
            attestation = _attestation_from_envelope(envelope)
            if (
                envelope.effective_at != locked_effective
                or attestation._evidence_payload() != locked_payload
            ):
                raise ValueError(
                    "shadow attestation does not match locked aggregate"
                )

        def validate_combined(
            admitted: tuple[EvidenceEnvelope, ...],
            orphans: tuple[EvidenceEnvelope, ...],
            envelope: EvidenceEnvelope,
        ) -> None:
            attestation = _attestation_from_envelope(envelope)
            _require_attestation_tuple_unique(
                admitted,
                attestation,
                orphan_snapshot=orphans,
            )

        admission = self._store.admit_checked(
            candidate,
            validate=validate,
            validate_combined=validate_combined,
        )
        return _attestation_from_envelope(admission.envelope)

    def _verify_snapshot(
        self,
        snapshot: Sequence[EvidenceEnvelope],
    ) -> tuple[StrategyShadowAttestation, ...]:
        attestations: list[StrategyShadowAttestation] = []
        for index, envelope in enumerate(snapshot):
            prefix = snapshot[:index]
            if envelope.kind == PAPER_SHADOW_OBSERVATION_KIND:
                observation = _observation_from_envelope(envelope)
                _, registration = _staged_with_registration_from_snapshot(
                    prefix,
                    observation.staged_intent_id,
                )
                manifest_before = require_active_evaluation_runtime(
                    self._repo_root,
                    registration,
                )
                _validate_observation_from_prefix(prefix, envelope)
                manifest_after = require_active_evaluation_runtime(
                    self._repo_root,
                    registration,
                )
                if (
                    manifest_before.canonical_json_bytes()
                    != manifest_after.canonical_json_bytes()
                ):
                    raise ValueError(
                        "active evaluation runtime changed during replay"
                    )
                continue
            if envelope.kind != PAPER_SHADOW_ATTESTATION_KIND:
                continue
            attestation = _attestation_from_envelope(envelope)
            assembled_by_role = _required_verify_owner(
                attestation.assembled_by_role
            )
            promotion = _promotion_from_snapshot(
                prefix,
                attestation.promotion_evidence_id,
            )
            caller_observations = tuple(
                _observation_from_envelope(item)
                for item in prefix
                if item.kind == PAPER_SHADOW_OBSERVATION_KIND
                and item.object_id in attestation.shadow_observation_ids
            )
            if len(caller_observations) != len(
                attestation.shadow_observation_ids
            ):
                raise ValueError(
                    "attestation observation dependency is incomplete"
                )
            durable_observations = _durable_observations_from_prefix(
                prefix,
                caller_observations,
            )
            _, registration = _staged_with_registration_from_snapshot(
                prefix,
                durable_observations[0].staged_intent_id,
            )
            manifest_before = require_active_evaluation_runtime(
                self._repo_root,
                registration,
            )
            effective_at, payload = _aggregate_payload(
                promotion_evidence=promotion,
                registration=registration,
                observations=durable_observations,
                assembled_by_role=assembled_by_role,
            )
            manifest_after = require_active_evaluation_runtime(
                self._repo_root,
                registration,
            )
            if (
                manifest_before.canonical_json_bytes()
                != manifest_after.canonical_json_bytes()
            ):
                raise ValueError(
                    "active evaluation runtime changed during replay"
                )
            if (
                envelope.effective_at != effective_at
                or attestation._evidence_payload() != payload
            ):
                raise ValueError(
                    "shadow attestation does not match replayed aggregate"
                )
            _require_attestation_tuple_unique(prefix, attestation)
            attestations.append(attestation)
        return tuple(attestations)

    def verify(self) -> tuple[StrategyShadowAttestation, ...]:
        return self._verify_snapshot(self._store.verify())

    def rebuild(self) -> tuple[StrategyShadowAttestation, ...]:
        return self._verify_snapshot(self._store.rebuild())
