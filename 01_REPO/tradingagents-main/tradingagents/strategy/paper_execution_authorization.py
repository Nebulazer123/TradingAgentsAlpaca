"""Bounded immutable paper-order authorization evidence."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from tradingagents.orchestration.authority import ActionClass, authority_for
from tradingagents.strategy._immutable_evidence_store import (
    PAPER_EXECUTION_AUTHORIZATION_KIND,
    STAGED_PAPER_INTENT_KIND,
    EvidenceCandidate,
    EvidenceEnvelope,
    ImmutableStrategyEvidenceStore,
)
from tradingagents.strategy.compiler import PaperDecisionAction
from tradingagents.strategy.promotion_evidence import (
    StrategyEvaluationRegistration,
    require_active_evaluation_runtime,
)
from tradingagents.strategy.staged_intent import (
    StagedPaperIntent,
    _staged_intent_from_envelope,
)

_ACCOUNT_FINGERPRINT_DOMAIN = (
    b"tradingagents:alpaca-paper-account:v1\0"
)
_ASCII_WHITESPACE = " \t\n\r\v\f"
_PAPER_ACCOUNT_ID_MAX_UTF8_BYTES = 256
PAPER_EXECUTION_AUTHORIZATION_SCHEMA_VERSION = 1
PAPER_EXECUTION_AUTHORIZATION_MAX_TTL_SECONDS = 900

_DIGEST_PATTERN = re.compile(r"[0-9a-f]{64}")
_COMMIT_PATTERN = re.compile(r"[0-9a-f]{40}")
_DATE_PATTERN = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_GENOME_ID_PATTERN = re.compile(r"genome-[a-z0-9-]+-[0-9a-f]{64}")
_AUTHORIZATION_KIND = PAPER_EXECUTION_AUTHORIZATION_KIND
_AUTHORIZATION_KEYS = frozenset(
    {
        "schema_version",
        "authorization_id",
        "staged_intent_id",
        "staged_intent_sha256",
        "promotion_evidence_id",
        "genome_id",
        "genome_canonical_sha256",
        "evaluation_code_commit",
        "evaluation_runtime_sha256",
        "paper_account_fingerprint",
        "session_date",
        "symbol",
        "side",
        "order_type",
        "tif",
        "requested_notional_usd",
        "requested_limit_price",
        "logical_order_sha256",
        "client_order_id",
        "expires_at",
        "effective_at",
        "recorded_at",
        "owner_role",
        "authorization_scope",
        "paper_submit_authorized",
        "live_submit_authorized",
        "analysis_only",
        "paper_only",
        "execution_authority",
        "can_submit_orders",
    }
)


def _canonical_json_bytes(payload: object) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _require_exact_fields(
    payload: object,
    expected: frozenset[str],
    *,
    label: str,
) -> Mapping[str, object]:
    if not isinstance(payload, Mapping):
        raise TypeError(f"{label} must be an object")
    if not all(type(key) is str for key in payload):
        raise TypeError(f"{label} field names must be exact strings")
    actual = set(payload)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise ValueError(
            f"{label} fields do not match; missing={missing}, extra={extra}"
        )
    return payload


def _require_digest(value: object, *, label: str) -> str:
    if type(value) is not str or _DIGEST_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{label} must be lowercase 64-hex")
    return value


def _require_object_id(value: object, *, kind: str, label: str) -> str:
    if (
        type(value) is not str
        or not value.startswith(f"{kind}-")
        or _DIGEST_PATTERN.fullmatch(
            value.removeprefix(f"{kind}-")
        )
        is None
    ):
        raise ValueError(f"{label} must be a {kind} object ID")
    return value


def _require_canonical_utc(value: object, *, label: str) -> dt.datetime:
    if type(value) is not str:
        raise TypeError(f"{label} must be a timestamp string")
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


def _datetime_text(value: object, *, label: str) -> str:
    if type(value) is not dt.datetime:
        raise TypeError(f"{label} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")
    if value.microsecond != 0:
        raise ValueError(f"{label} must use whole seconds")
    return value.astimezone(dt.timezone.utc).isoformat(timespec="seconds")


def _require_session_date(value: object) -> str:
    if type(value) is not str or _DATE_PATTERN.fullmatch(value) is None:
        raise ValueError("session_date must use YYYY-MM-DD")
    try:
        parsed = dt.date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("session_date must use YYYY-MM-DD") from exc
    if parsed.isoformat() != value:
        raise ValueError("session_date must use YYYY-MM-DD")
    return value


def _require_symbol(value: object) -> str:
    if type(value) is not str:
        raise TypeError("symbol must be a string")
    if value.strip() != value:
        raise ValueError("symbol must not contain surrounding whitespace")
    if not 1 <= len(value) <= 15 or not "A" <= value[0] <= "Z":
        raise ValueError("symbol must be an uppercase ASCII ticker token")
    if any(
        not (
            "A" <= character <= "Z"
            or "0" <= character <= "9"
            or character in ".-"
        )
        for character in value[1:]
    ):
        raise ValueError("symbol must be an uppercase ASCII ticker token")
    return value


def _require_canonical_money(value: object, *, label: str) -> str:
    if type(value) is not str:
        raise TypeError(f"{label} must be a string")
    pieces = value.split(".")
    if len(pieces) != 2:
        raise ValueError(f"{label} must contain exactly two decimals")
    whole, cents = pieces
    if (
        (whole != "0" and (not whole or whole[0] == "0"))
        or not whole.isascii()
        or not whole.isdigit()
        or len(cents) != 2
        or not cents.isascii()
        or not cents.isdigit()
    ):
        raise ValueError(f"{label} must be a canonical money string")
    if Decimal(value) <= 0:
        raise ValueError(f"{label} must be positive")
    return value


def _logical_order_material(
    request: AuthorizedPaperOrderRequest,
) -> dict[str, object]:
    return {
        "staged_intent_id": request.staged_intent_id,
        "staged_intent_sha256": request.staged_intent_sha256,
        "paper_account_fingerprint": request.paper_account_fingerprint,
        "session_date": request.session_date,
        "symbol": request.symbol,
        "side": request.side,
        "order_type": request.order_type,
        "tif": request.tif,
        "requested_notional_usd": request.requested_notional_usd,
        "requested_limit_price": request.requested_limit_price,
    }


@dataclass(frozen=True, slots=True)
class AuthorizedPaperOrderRequest:
    authorization_id: str
    staged_intent_id: str
    staged_intent_sha256: str
    promotion_evidence_id: str
    genome_id: str
    genome_canonical_sha256: str
    evaluation_code_commit: str
    evaluation_runtime_sha256: str
    paper_account_fingerprint: str
    session_date: str
    symbol: str
    side: str
    order_type: str
    tif: str
    requested_notional_usd: str
    requested_limit_price: str
    logical_order_sha256: str
    client_order_id: str
    expires_at: str
    effective_at: str
    recorded_at: str
    owner_role: str = field(init=False, default="execution_operator")
    authorization_scope: str = field(
        init=False,
        default="single_alpaca_paper_order",
    )
    paper_submit_authorized: bool = field(init=False, default=True)
    live_submit_authorized: bool = field(init=False, default=False)
    analysis_only: bool = field(init=False, default=True)
    paper_only: bool = field(init=False, default=True)
    execution_authority: str = field(
        init=False,
        default="paper_order_request_only",
    )
    can_submit_orders: bool = field(init=False, default=False)
    schema_version: int = field(
        init=False,
        default=PAPER_EXECUTION_AUTHORIZATION_SCHEMA_VERSION,
    )

    def __post_init__(self) -> None:
        _require_object_id(
            self.authorization_id,
            kind=_AUTHORIZATION_KIND,
            label="authorization_id",
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
        if (
            type(self.genome_id) is not str
            or _GENOME_ID_PATTERN.fullmatch(self.genome_id) is None
        ):
            raise ValueError("genome_id must be a canonical genome identity")
        _require_digest(
            self.genome_canonical_sha256,
            label="genome_canonical_sha256",
        )
        if (
            type(self.evaluation_code_commit) is not str
            or _COMMIT_PATTERN.fullmatch(self.evaluation_code_commit) is None
        ):
            raise ValueError(
                "evaluation_code_commit must be lowercase 40-hex commit"
            )
        _require_digest(
            self.evaluation_runtime_sha256,
            label="evaluation_runtime_sha256",
        )
        _require_digest(
            self.paper_account_fingerprint,
            label="paper_account_fingerprint",
        )
        _require_session_date(self.session_date)
        _require_symbol(self.symbol)
        for field_name in ("side", "order_type", "tif", "client_order_id"):
            if type(getattr(self, field_name)) is not str:
                raise TypeError(f"{field_name} must be an exact string")
        if self.side != "buy":
            raise ValueError("side must be buy")
        if self.order_type != "limit":
            raise ValueError("order_type must be limit")
        if self.tif != "day":
            raise ValueError("tif must be day")
        _require_canonical_money(
            self.requested_notional_usd,
            label="requested_notional_usd",
        )
        _require_canonical_money(
            self.requested_limit_price,
            label="requested_limit_price",
        )
        _require_digest(
            self.logical_order_sha256,
            label="logical_order_sha256",
        )
        expected_logical_digest = hashlib.sha256(
            _canonical_json_bytes(_logical_order_material(self))
        ).hexdigest()
        if self.logical_order_sha256 != expected_logical_digest:
            raise ValueError(
                "logical_order_sha256 does not match logical order material"
            )
        if self.client_order_id != (
            f"ta-p-{self.logical_order_sha256[:40]}"
        ):
            raise ValueError(
                "client_order_id does not match full logical order digest"
            )
        expires_at = _require_canonical_utc(
            self.expires_at,
            label="expires_at",
        )
        effective_at = _require_canonical_utc(
            self.effective_at,
            label="effective_at",
        )
        recorded_at = _require_canonical_utc(
            self.recorded_at,
            label="recorded_at",
        )
        if effective_at > recorded_at:
            raise ValueError("future-effective authorization is not allowed")
        if recorded_at >= expires_at:
            raise ValueError("authorization is expired on first admission")
        ttl = expires_at - effective_at
        if (
            ttl <= dt.timedelta(0)
            or ttl
            > dt.timedelta(
                seconds=PAPER_EXECUTION_AUTHORIZATION_MAX_TTL_SECONDS
            )
        ):
            raise ValueError("authorization TTL must be at most 900 seconds")
        if self.schema_version != PAPER_EXECUTION_AUTHORIZATION_SCHEMA_VERSION:
            raise ValueError("authorization schema_version is fixed")
        if self.owner_role != "execution_operator":
            raise ValueError("authorization owner_role is fixed")
        if self.authorization_scope != "single_alpaca_paper_order":
            raise ValueError("authorization_scope is fixed")
        if self.paper_submit_authorized is not True:
            raise ValueError("paper_submit_authorized is fixed")
        if self.live_submit_authorized is not False:
            raise ValueError("live_submit_authorized is fixed")
        if self.analysis_only is not True:
            raise ValueError("analysis_only is fixed")
        if self.paper_only is not True:
            raise ValueError("paper_only is fixed")
        if self.execution_authority != "paper_order_request_only":
            raise ValueError("execution_authority is fixed")
        if self.can_submit_orders is not False:
            raise ValueError("can_submit_orders is fixed")
        expected_id = (
            f"{_AUTHORIZATION_KIND}-"
            + hashlib.sha256(
                _canonical_json_bytes(
                    {
                        "kind": _AUTHORIZATION_KIND,
                        "effective_at": self.effective_at,
                        "payload": self._evidence_payload(),
                    }
                )
            ).hexdigest()
        )
        if self.authorization_id != expected_id:
            raise ValueError(
                "authorization_id does not match evidence identity"
            )

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, object],
    ) -> AuthorizedPaperOrderRequest:
        values = _require_exact_fields(
            payload,
            _AUTHORIZATION_KEYS,
            label="authorized paper order request",
        )
        if (
            type(values["schema_version"]) is not int
            or values["schema_version"]
            != PAPER_EXECUTION_AUTHORIZATION_SCHEMA_VERSION
        ):
            raise ValueError("authorization schema_version does not match")
        fixed = {
            "owner_role": "execution_operator",
            "authorization_scope": "single_alpaca_paper_order",
            "paper_submit_authorized": True,
            "live_submit_authorized": False,
            "analysis_only": True,
            "paper_only": True,
            "execution_authority": "paper_order_request_only",
            "can_submit_orders": False,
        }
        for name, expected in fixed.items():
            if type(expected) is bool:
                if values[name] is not expected:
                    raise ValueError(f"{name} does not match")
            elif type(values[name]) is not str or values[name] != expected:
                raise ValueError(f"{name} does not match")
        request = cls(
            authorization_id=values["authorization_id"],  # type: ignore[arg-type]
            staged_intent_id=values["staged_intent_id"],  # type: ignore[arg-type]
            staged_intent_sha256=values["staged_intent_sha256"],  # type: ignore[arg-type]
            promotion_evidence_id=values["promotion_evidence_id"],  # type: ignore[arg-type]
            genome_id=values["genome_id"],  # type: ignore[arg-type]
            genome_canonical_sha256=values["genome_canonical_sha256"],  # type: ignore[arg-type]
            evaluation_code_commit=values["evaluation_code_commit"],  # type: ignore[arg-type]
            evaluation_runtime_sha256=values["evaluation_runtime_sha256"],  # type: ignore[arg-type]
            paper_account_fingerprint=values["paper_account_fingerprint"],  # type: ignore[arg-type]
            session_date=values["session_date"],  # type: ignore[arg-type]
            symbol=values["symbol"],  # type: ignore[arg-type]
            side=values["side"],  # type: ignore[arg-type]
            order_type=values["order_type"],  # type: ignore[arg-type]
            tif=values["tif"],  # type: ignore[arg-type]
            requested_notional_usd=values["requested_notional_usd"],  # type: ignore[arg-type]
            requested_limit_price=values["requested_limit_price"],  # type: ignore[arg-type]
            logical_order_sha256=values["logical_order_sha256"],  # type: ignore[arg-type]
            client_order_id=values["client_order_id"],  # type: ignore[arg-type]
            expires_at=values["expires_at"],  # type: ignore[arg-type]
            effective_at=values["effective_at"],  # type: ignore[arg-type]
            recorded_at=values["recorded_at"],  # type: ignore[arg-type]
        )
        if request.to_dict() != dict(values):
            raise ValueError("authorization canonical round trip is not exact")
        return request

    def _evidence_payload(self) -> dict[str, object]:
        payload = self.to_dict()
        for field_name in (
            "authorization_id",
            "effective_at",
            "recorded_at",
        ):
            del payload[field_name]
        return payload

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "authorization_id": self.authorization_id,
            "staged_intent_id": self.staged_intent_id,
            "staged_intent_sha256": self.staged_intent_sha256,
            "promotion_evidence_id": self.promotion_evidence_id,
            "genome_id": self.genome_id,
            "genome_canonical_sha256": self.genome_canonical_sha256,
            "evaluation_code_commit": self.evaluation_code_commit,
            "evaluation_runtime_sha256": self.evaluation_runtime_sha256,
            "paper_account_fingerprint": self.paper_account_fingerprint,
            "session_date": self.session_date,
            "symbol": self.symbol,
            "side": self.side,
            "order_type": self.order_type,
            "tif": self.tif,
            "requested_notional_usd": self.requested_notional_usd,
            "requested_limit_price": self.requested_limit_price,
            "logical_order_sha256": self.logical_order_sha256,
            "client_order_id": self.client_order_id,
            "expires_at": self.expires_at,
            "effective_at": self.effective_at,
            "recorded_at": self.recorded_at,
            "owner_role": self.owner_role,
            "authorization_scope": self.authorization_scope,
            "paper_submit_authorized": self.paper_submit_authorized,
            "live_submit_authorized": self.live_submit_authorized,
            "analysis_only": self.analysis_only,
            "paper_only": self.paper_only,
            "execution_authority": self.execution_authority,
            "can_submit_orders": self.can_submit_orders,
        }

    def canonical_json_bytes(self) -> bytes:
        return _canonical_json_bytes(self.to_dict())

    def is_active(self, *, at: dt.datetime) -> bool:
        active_at = _require_canonical_utc(
            _datetime_text(at, label="at"),
            label="at",
        )
        recorded_at = _require_canonical_utc(
            self.recorded_at,
            label="recorded_at",
        )
        expires_at = _require_canonical_utc(
            self.expires_at,
            label="expires_at",
        )
        return recorded_at <= active_at < expires_at


def _authorization_from_envelope(
    envelope: EvidenceEnvelope,
) -> AuthorizedPaperOrderRequest:
    if type(envelope) is not EvidenceEnvelope:
        raise TypeError("authorization envelope type does not match")
    if envelope.kind != PAPER_EXECUTION_AUTHORIZATION_KIND:
        raise ValueError("envelope kind is not paper execution authorization")
    raw_payload = _thaw_json(envelope.payload)
    if type(raw_payload) is not dict:
        raise ValueError("authorization payload is not an object")
    full = {
        **raw_payload,
        "authorization_id": envelope.object_id,
        "effective_at": envelope.effective_at,
        "recorded_at": envelope.recorded_at,
    }
    request = AuthorizedPaperOrderRequest.from_dict(full)
    if request._evidence_payload() != raw_payload:
        raise ValueError("authorization payload round trip is not exact")
    return request


def _registration_from_prefix(
    prefix: Sequence[EvidenceEnvelope],
    registration_id: str,
) -> StrategyEvaluationRegistration:
    matches = tuple(
        StrategyEvaluationRegistration.from_envelope(envelope)
        for envelope in prefix
        if envelope.kind == "evaluation-registration"
        and envelope.object_id == registration_id
    )
    if len(matches) != 1:
        raise ValueError(
            "staged registration must already be durable in this store"
        )
    return matches[0]


def _staged_with_registration_from_snapshot(
    snapshot: Sequence[EvidenceEnvelope],
    staged_intent_id: str,
) -> tuple[StagedPaperIntent, StrategyEvaluationRegistration]:
    for index, envelope in enumerate(snapshot):
        if (
            envelope.kind == STAGED_PAPER_INTENT_KIND
            and envelope.object_id == staged_intent_id
        ):
            staged_intent = _staged_intent_from_envelope(envelope)
            registration = _registration_from_prefix(
                snapshot[:index],
                staged_intent.registration_id,
            )
            return staged_intent, registration
    raise ValueError("staged intent must already be durable in this store")


def _required_execution_owner(actor_role: object) -> str:
    verdict = authority_for(ActionClass.ORDER_SUBMIT)
    if (
        not verdict.allowed
        or verdict.human_required
        or verdict.owner_role != "execution_operator"
    ):
        raise ValueError("ORDER_SUBMIT authority is not execution_operator")
    if type(actor_role) is not str or actor_role != verdict.owner_role:
        raise ValueError("actor_role must be execution_operator")
    return verdict.owner_role


def _require_buy_staged_intent(staged_intent: StagedPaperIntent) -> None:
    if staged_intent.decision.action is not PaperDecisionAction.BUY:
        raise ValueError("only a staged BUY may be authorized")
    if (
        staged_intent.decision.symbol is None
        or staged_intent.decision.limit_price is None
    ):
        raise ValueError("staged BUY economics are incomplete")


def _authorization_payload(
    *,
    staged_intent: StagedPaperIntent,
    account_fingerprint: str,
    owner_role: str,
    expires_at: str,
) -> dict[str, object]:
    _require_buy_staged_intent(staged_intent)
    symbol = staged_intent.decision.symbol
    limit_price = staged_intent.decision.limit_price
    if symbol is None or limit_price is None:
        raise ValueError("staged BUY economics are incomplete")
    staged_digest = hashlib.sha256(
        staged_intent.canonical_json_bytes()
    ).hexdigest()
    logical_material = {
        "staged_intent_id": staged_intent.staged_intent_id,
        "staged_intent_sha256": staged_digest,
        "paper_account_fingerprint": account_fingerprint,
        "session_date": staged_intent.session_date,
        "symbol": symbol,
        "side": "buy",
        "order_type": "limit",
        "tif": "day",
        "requested_notional_usd": staged_intent.decision.notional_usd,
        "requested_limit_price": limit_price,
    }
    logical_digest = hashlib.sha256(
        _canonical_json_bytes(logical_material)
    ).hexdigest()
    return {
        "schema_version": PAPER_EXECUTION_AUTHORIZATION_SCHEMA_VERSION,
        "staged_intent_id": staged_intent.staged_intent_id,
        "staged_intent_sha256": staged_digest,
        "promotion_evidence_id": staged_intent.promotion_evidence_id,
        "genome_id": staged_intent.genome.genome_id,
        "genome_canonical_sha256": staged_intent.genome_canonical_sha256,
        "evaluation_code_commit": staged_intent.evaluation_code_commit,
        "evaluation_runtime_sha256": (
            staged_intent.evaluation_runtime_sha256
        ),
        "paper_account_fingerprint": account_fingerprint,
        "session_date": staged_intent.session_date,
        "symbol": symbol,
        "side": "buy",
        "order_type": "limit",
        "tif": "day",
        "requested_notional_usd": staged_intent.decision.notional_usd,
        "requested_limit_price": limit_price,
        "logical_order_sha256": logical_digest,
        "client_order_id": f"ta-p-{logical_digest[:40]}",
        "expires_at": expires_at,
        "owner_role": owner_role,
        "authorization_scope": "single_alpaca_paper_order",
        "paper_submit_authorized": True,
        "live_submit_authorized": False,
        "analysis_only": True,
        "paper_only": True,
        "execution_authority": "paper_order_request_only",
        "can_submit_orders": False,
    }


def _require_request_bindings(
    request: AuthorizedPaperOrderRequest,
    *,
    staged_intent: StagedPaperIntent,
    registration: StrategyEvaluationRegistration,
    owner_role: str,
) -> None:
    _require_buy_staged_intent(staged_intent)
    if staged_intent.registration_id != registration.registration_id:
        raise ValueError("staged registration dependency does not match")
    if staged_intent.genome.canonical_json_bytes() != (
        registration.genome.canonical_json_bytes()
    ):
        raise ValueError("staged genome does not match registration")
    if (
        staged_intent.genome_canonical_sha256
        != registration.genome_canonical_sha256
    ):
        raise ValueError("staged genome digest does not match registration")
    if (
        staged_intent.evaluation_code_commit
        != registration.evaluation_code_commit
    ):
        raise ValueError("staged evaluation commit does not match registration")
    if (
        staged_intent.evaluation_runtime_sha256
        != registration.evaluation_runtime_sha256
    ):
        raise ValueError(
            "staged evaluation runtime does not match registration"
        )
    expected_payload = _authorization_payload(
        staged_intent=staged_intent,
        account_fingerprint=request.paper_account_fingerprint,
        owner_role=owner_role,
        expires_at=request.expires_at,
    )
    if request._evidence_payload() != expected_payload:
        raise ValueError(
            "authorization does not match durable staged BUY bytes"
        )
    staged_recorded = _require_canonical_utc(
        staged_intent.recorded_at,
        label="staged recorded_at",
    )
    staged_expires = _require_canonical_utc(
        staged_intent.expires_at,
        label="staged expires_at",
    )
    effective_at = _require_canonical_utc(
        request.effective_at,
        label="effective_at",
    )
    expires_at = _require_canonical_utc(
        request.expires_at,
        label="expires_at",
    )
    if effective_at < staged_recorded:
        raise ValueError("authorization predates durable staged intent")
    if expires_at > staged_expires:
        raise ValueError("authorization expires after staged intent")


def _authorization_logical_bytes(
    request: AuthorizedPaperOrderRequest,
) -> bytes:
    return _canonical_json_bytes(_logical_order_material(request))


def _require_global_authorization_uniqueness(
    envelopes: Sequence[EvidenceEnvelope],
    candidate: AuthorizedPaperOrderRequest,
    *,
    tolerate_invalid_orphans: bool = False,
) -> None:
    for envelope in envelopes:
        if (
            envelope.kind != PAPER_EXECUTION_AUTHORIZATION_KIND
            or envelope.object_id == candidate.authorization_id
        ):
            continue
        try:
            existing = _authorization_from_envelope(envelope)
        except (TypeError, ValueError):
            if tolerate_invalid_orphans:
                continue
            raise
        if existing.staged_intent_id == candidate.staged_intent_id:
            raise ValueError(
                "staged intent already has a different authorization"
            )
        if existing.logical_order_sha256 == candidate.logical_order_sha256:
            if _authorization_logical_bytes(
                existing
            ) != _authorization_logical_bytes(candidate):
                raise ValueError(
                    "logical order digest maps to different material"
                )
            raise ValueError(
                "logical order digest maps to a different authorization"
            )
        if existing.client_order_id == candidate.client_order_id:
            raise ValueError(
                "client_order_id maps to a different logical order digest"
            )


class StrategyPaperExecutionAuthorizationLedger:
    def __init__(
        self,
        root: str | Path,
        *,
        repo_root: str | Path,
        clock: Callable[[], dt.datetime] | None = None,
    ):
        self._repo_root = Path(repo_root)
        self._store = ImmutableStrategyEvidenceStore(root, clock=clock)

    def authorize_buy(
        self,
        *,
        staged_intent: StagedPaperIntent,
        paper_account_id: str,
        actor_role: str,
        effective_at: dt.datetime,
        expires_at: dt.datetime,
    ) -> AuthorizedPaperOrderRequest:
        if type(staged_intent) is not StagedPaperIntent:
            raise TypeError("staged_intent must be a StagedPaperIntent")
        owner_role = _required_execution_owner(actor_role)
        effective_text = _datetime_text(effective_at, label="effective_at")
        expires_text = _datetime_text(expires_at, label="expires_at")

        snapshot = self._store.rebuild()
        durable_staged, durable_registration = (
            _staged_with_registration_from_snapshot(
                snapshot,
                staged_intent.staged_intent_id,
            )
        )
        if staged_intent.canonical_json_bytes() != (
            durable_staged.canonical_json_bytes()
        ):
            raise ValueError("caller staged intent does not match durable bytes")
        _require_buy_staged_intent(durable_staged)

        manifest_before = require_active_evaluation_runtime(
            self._repo_root,
            durable_registration,
        )
        account_fingerprint = paper_account_fingerprint(paper_account_id)
        candidate = EvidenceCandidate(
            kind=PAPER_EXECUTION_AUTHORIZATION_KIND,
            effective_at=effective_text,
            payload=_authorization_payload(
                staged_intent=durable_staged,
                account_fingerprint=account_fingerprint,
                owner_role=owner_role,
                expires_at=expires_text,
            ),
        )
        manifest_after = require_active_evaluation_runtime(
            self._repo_root,
            durable_registration,
        )
        if manifest_before.canonical_json_bytes() != (
            manifest_after.canonical_json_bytes()
        ):
            raise ValueError(
                "active evaluation runtime changed during authorization"
            )

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
            if locked_staged.canonical_json_bytes() != (
                durable_staged.canonical_json_bytes()
            ):
                raise ValueError(
                    "durable staged intent changed during authorization"
                )
            if locked_registration.canonical_json_bytes() != (
                durable_registration.canonical_json_bytes()
            ):
                raise ValueError(
                    "durable registration changed during authorization"
                )
            request = _authorization_from_envelope(envelope)
            _require_request_bindings(
                request,
                staged_intent=locked_staged,
                registration=locked_registration,
                owner_role=owner_role,
            )
            _require_global_authorization_uniqueness(admitted, request)

        def validate_orphans(
            orphans: tuple[EvidenceEnvelope, ...],
            envelope: EvidenceEnvelope,
        ) -> None:
            _require_global_authorization_uniqueness(
                orphans,
                _authorization_from_envelope(envelope),
                tolerate_invalid_orphans=True,
            )

        admission = self._store.admit_checked(
            candidate,
            validate=validate,
            validate_orphans=validate_orphans,
        )
        return _authorization_from_envelope(admission.envelope)

    def verify(self) -> tuple[AuthorizedPaperOrderRequest, ...]:
        return self._replay(self._store.verify())

    def rebuild(self) -> tuple[AuthorizedPaperOrderRequest, ...]:
        return self._replay(self._store.rebuild())

    def _replay(
        self,
        snapshot: tuple[EvidenceEnvelope, ...],
    ) -> tuple[AuthorizedPaperOrderRequest, ...]:
        authorizations: list[AuthorizedPaperOrderRequest] = []
        prefix: list[EvidenceEnvelope] = []
        owner_role = _required_execution_owner("execution_operator")
        for envelope in snapshot:
            if envelope.kind != PAPER_EXECUTION_AUTHORIZATION_KIND:
                prefix.append(envelope)
                continue
            request = _authorization_from_envelope(envelope)
            staged_intent, registration = (
                _staged_with_registration_from_snapshot(
                    prefix,
                    request.staged_intent_id,
                )
            )
            manifest_before = require_active_evaluation_runtime(
                self._repo_root,
                registration,
            )
            _require_request_bindings(
                request,
                staged_intent=staged_intent,
                registration=registration,
                owner_role=owner_role,
            )
            _require_global_authorization_uniqueness(prefix, request)
            manifest_after = require_active_evaluation_runtime(
                self._repo_root,
                registration,
            )
            if manifest_before.canonical_json_bytes() != (
                manifest_after.canonical_json_bytes()
            ):
                raise ValueError(
                    "active evaluation runtime changed during replay"
                )
            authorizations.append(request)
            prefix.append(envelope)
        return tuple(authorizations)


def paper_account_fingerprint(paper_account_id: str) -> str:
    """Return the non-secret digest of one normalized paper account ID."""

    if type(paper_account_id) is not str:
        raise TypeError("paper_account_id must be an exact string")
    normalized = paper_account_id.strip(_ASCII_WHITESPACE)
    if not normalized:
        raise ValueError("paper_account_id must not be blank")
    if not normalized.isprintable():
        raise ValueError("paper_account_id must contain only printable text")
    encoded = normalized.encode("utf-8")
    if len(encoded) > _PAPER_ACCOUNT_ID_MAX_UTF8_BYTES:
        raise ValueError("paper_account_id must be at most 256 UTF-8 bytes")
    return hashlib.sha256(_ACCOUNT_FINGERPRINT_DOMAIN + encoded).hexdigest()


def _thaw_json(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _thaw_json(item) for key, item in value.items()}
    if type(value) is tuple:
        return [_thaw_json(item) for item in value]
    return value
