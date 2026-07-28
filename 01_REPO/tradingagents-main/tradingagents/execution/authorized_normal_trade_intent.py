"""Immutable, single-order authorization evidence for normal Alpaca live intent.

This module intentionally has no broker dependency.  Its verifier rejects any
unbound order locally, before a caller could make a broker request.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal

AUTHORIZED_NORMAL_TRADE_INTENT_SCHEMA_VERSION = 1
AUTHORIZED_NORMAL_TRADE_INTENT_MAX_TTL_SECONDS = 900

_DIGEST = re.compile(r"[0-9a-f]{64}")
_COMMIT = re.compile(r"[0-9a-f]{40}")
_SYMBOL = re.compile(r"[A-Z][A-Z0-9.-]{0,14}")
_MONEY = re.compile(r"(?:0|[1-9][0-9]*)\.[0-9]{2}")
_ID = re.compile(r"[a-z][a-z0-9-]*-[0-9a-f]{64}")
_FIXED = {
    "owner_role": "portfolio_executive",
    "authorization_scope": "single_alpaca_live_order",
    "live_submit_authorized": True,
    "paper_submit_authorized": False,
}
_INPUT_FIELDS = frozenset(
    {
        "authorization_id", "promotion_proposal_id", "promotion_proposal_sha256",
        "promotion_state_sha256", "promotion_sync_receipt_id",
        "promotion_sync_receipt_sha256", "staged_intent_id", "staged_intent_sha256",
        "shadow_attestation_sha256", "genome_id", "genome_canonical_sha256",
        "evaluation_code_commit", "evaluation_runtime_sha256",
        "market_observation_sha256", "portfolio_snapshot_sha256", "risk_snapshot_sha256",
        "symbol", "side", "order_type", "tif", "notional_usd", "limit_price",
        "logical_order_sha256", "client_order_id", "effective_at", "expires_at",
        "recorded_at", *_FIXED,
    }
)


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _timestamp(value: object, label: str) -> dt.datetime:
    if type(value) is not str:
        raise TypeError(f"{label} must be a timestamp string")
    try:
        parsed = dt.datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{label} must be canonical UTC") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != dt.timedelta() or parsed.microsecond or parsed.isoformat(timespec="seconds") != value:
        raise ValueError(f"{label} must be canonical whole-second UTC")
    return parsed


def _at(value: object) -> dt.datetime:
    if type(value) is not dt.datetime or value.tzinfo is None or value.utcoffset() is None or value.microsecond:
        raise ValueError("at must be a timezone-aware whole-second datetime")
    return value.astimezone(dt.timezone.utc)


def _digest(value: object, label: str) -> str:
    if type(value) is not str or _DIGEST.fullmatch(value) is None:
        raise ValueError(f"{label} must be lowercase 64-hex")
    return value


def _id(value: object, label: str) -> str:
    if type(value) is not str or _ID.fullmatch(value) is None:
        raise ValueError(f"{label} must be a digest-suffixed object ID")
    return value


def _money(value: object, label: str) -> str:
    if type(value) is not str or _MONEY.fullmatch(value) is None or Decimal(value) <= 0:
        raise ValueError(f"{label} must be positive canonical money with two decimals")
    return value


@dataclass(frozen=True, slots=True)
class AuthorizedNormalTradeIntent:
    authorization_id: str
    promotion_proposal_id: str
    promotion_proposal_sha256: str
    promotion_state_sha256: str
    promotion_sync_receipt_id: str
    promotion_sync_receipt_sha256: str
    staged_intent_id: str
    staged_intent_sha256: str
    shadow_attestation_sha256: str
    genome_id: str
    genome_canonical_sha256: str
    evaluation_code_commit: str
    evaluation_runtime_sha256: str
    market_observation_sha256: str
    portfolio_snapshot_sha256: str
    risk_snapshot_sha256: str
    symbol: str
    side: str
    order_type: str
    tif: str
    notional_usd: str
    limit_price: str
    logical_order_sha256: str
    client_order_id: str
    effective_at: str
    expires_at: str
    recorded_at: str
    owner_role: str = field(init=False, default="portfolio_executive")
    authorization_scope: str = field(init=False, default="single_alpaca_live_order")
    live_submit_authorized: bool = field(init=False, default=True)
    paper_submit_authorized: bool = field(init=False, default=False)
    schema_version: int = field(init=False, default=AUTHORIZED_NORMAL_TRADE_INTENT_SCHEMA_VERSION)

    def __post_init__(self) -> None:
        _id(self.authorization_id, "authorization_id")
        for name in ("promotion_proposal_id", "promotion_sync_receipt_id", "staged_intent_id", "genome_id"):
            _id(getattr(self, name), name)
        for name in (
            "promotion_proposal_sha256",
            "promotion_state_sha256",
            "promotion_sync_receipt_sha256",
            "staged_intent_sha256",
            "shadow_attestation_sha256",
            "genome_canonical_sha256",
            "evaluation_runtime_sha256",
            "market_observation_sha256",
            "portfolio_snapshot_sha256",
            "risk_snapshot_sha256",
            "logical_order_sha256",
        ):
            _digest(getattr(self, name), name)
        if type(self.evaluation_code_commit) is not str or _COMMIT.fullmatch(self.evaluation_code_commit) is None:
            raise ValueError("evaluation_code_commit must be lowercase 40-hex")
        if type(self.symbol) is not str or _SYMBOL.fullmatch(self.symbol) is None:
            raise ValueError("symbol must be an uppercase ticker token")
        for name in ("side", "order_type", "tif"):
            if type(getattr(self, name)) is not str:
                raise ValueError(f"{name} must be an exact string")
        if (self.side, self.order_type, self.tif) != ("buy", "limit", "day"):
            raise ValueError("only buy limit day orders are eligible")
        _money(self.notional_usd, "notional_usd")
        _money(self.limit_price, "limit_price")
        effective, expires, recorded = (_timestamp(value, name) for name, value in (("effective_at", self.effective_at), ("expires_at", self.expires_at), ("recorded_at", self.recorded_at)))
        if effective > recorded or recorded >= expires or expires - effective > dt.timedelta(seconds=900):
            raise ValueError("authorization timestamps are inactive or exceed 900 seconds")
        expected_logical = hashlib.sha256(_canonical(self._logical_material())).hexdigest()
        if self.logical_order_sha256 != expected_logical:
            raise ValueError("logical_order_sha256 does not match bound material")
        if self.client_order_id != f"ta-l-{self.logical_order_sha256[:40]}":
            raise ValueError("client_order_id does not match logical order digest")
        if self.authorization_id != "authorized-normal-trade-intent-" + hashlib.sha256(_canonical(self._authorization_material())).hexdigest():
            raise ValueError("authorization_id does not match canonical authorization material")

    def _logical_material(self) -> dict[str, object]:
        payload = self.to_dict()
        for name in ("authorization_id", "logical_order_sha256", "client_order_id", "schema_version", *_FIXED):
            payload.pop(name, None)
        return payload

    def _authorization_material(self) -> dict[str, object]:
        payload = self.to_dict()
        payload.pop("authorization_id")
        payload.pop("schema_version", None)
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> AuthorizedNormalTradeIntent:
        if not isinstance(payload, Mapping) or not all(type(name) is str for name in payload):
            raise TypeError("authorized normal trade intent must be an object with string keys")
        actual = set(payload)
        if actual != _INPUT_FIELDS:
            raise ValueError(f"authorized normal trade intent fields do not match; missing={sorted(_INPUT_FIELDS - actual)}, extra={sorted(actual - _INPUT_FIELDS)}")
        for name, expected in _FIXED.items():
            if payload[name] is not expected:
                raise ValueError(f"{name} does not match fixed authorization")
        intent = cls(**{
            name: payload[name]
            for name, definition in cls.__dataclass_fields__.items()
            if name in payload and definition.init
        })  # type: ignore[arg-type]
        if intent.to_dict() != dict(payload):
            raise ValueError("authorization canonical round trip is not exact")
        return intent

    def to_dict(self) -> dict[str, object]:
        return {
            name: getattr(self, name)
            for name in self.__dataclass_fields__
            if name != "schema_version"
        }

    def canonical_json_bytes(self) -> bytes:
        return _canonical(self.to_dict())

    def is_active(self, *, at: dt.datetime) -> bool:
        active = _at(at)
        return _timestamp(self.recorded_at, "recorded_at") <= active < _timestamp(self.expires_at, "expires_at")

    def verify_order_payload(self, order: object, *, at: dt.datetime) -> None:
        if not self.is_active(at=at):
            raise ValueError("authorization is not active")
        if not isinstance(order, Mapping):
            raise ValueError("order must be an exact mapping, not a generic intent")
        expected = {"symbol": self.symbol, "side": self.side, "type": self.order_type, "time_in_force": self.tif, "notional": self.notional_usd, "limit_price": self.limit_price, "client_order_id": self.client_order_id}
        if dict(order) != expected:
            raise ValueError("order payload does not exactly match authorized binding")
