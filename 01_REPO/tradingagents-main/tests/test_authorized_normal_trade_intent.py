from __future__ import annotations

import datetime as dt
import hashlib
import json

import pytest

from tradingagents.execution.authorized_normal_trade_intent import (
    AuthorizedNormalTradeIntent,
)
from tradingagents.schemas.trading import TradeIntent


def _at(value: str) -> dt.datetime:
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def _sha(char: str) -> str:
    return char * 64


def _canonical(payload: object) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()


def _make_intent() -> AuthorizedNormalTradeIntent:
    payload: dict[str, object] = {
        "promotion_proposal_id": "promotion-proposal-" + _sha("a"),
        "promotion_proposal_sha256": _sha("b"),
        "promotion_state_sha256": _sha("c"),
        "promotion_sync_receipt_id": "promotion-sync-receipt-" + _sha("d"),
        "promotion_sync_receipt_sha256": _sha("e"),
        "staged_intent_id": "staged-live-intent-" + _sha("f"),
        "staged_intent_sha256": _sha("1"),
        "shadow_attestation_sha256": _sha("2"),
        "genome_id": "genome-core-" + _sha("3"),
        "genome_canonical_sha256": _sha("4"),
        "evaluation_code_commit": "5" * 40,
        "evaluation_runtime_sha256": _sha("6"),
        "market_observation_sha256": _sha("7"),
        "portfolio_snapshot_sha256": _sha("8"),
        "risk_snapshot_sha256": _sha("9"),
        "symbol": "MSFT", "side": "buy", "order_type": "limit", "tif": "day",
        "notional_usd": "25.00", "limit_price": "100.00",
        "effective_at": "2026-07-28T12:00:00+00:00",
        "expires_at": "2026-07-28T12:15:00+00:00",
        "recorded_at": "2026-07-28T12:00:00+00:00",
    }
    logical = hashlib.sha256(_canonical(payload)).hexdigest()
    payload["logical_order_sha256"] = logical
    payload["client_order_id"] = f"ta-l-{logical[:40]}"
    evidence = {**payload, "owner_role": "portfolio_executive", "authorization_scope": "single_alpaca_live_order", "live_submit_authorized": True, "paper_submit_authorized": False}
    authorization_id = "authorized-normal-trade-intent-" + hashlib.sha256(_canonical(evidence)).hexdigest()
    return AuthorizedNormalTradeIntent.from_dict({**evidence, "authorization_id": authorization_id})


def _bound_order(intent: AuthorizedNormalTradeIntent) -> dict[str, object]:
    return {"symbol": intent.symbol, "side": intent.side, "type": intent.order_type, "time_in_force": intent.tif, "notional": intent.notional_usd, "limit_price": intent.limit_price, "client_order_id": intent.client_order_id}


def _wrong_owner(payload: dict[str, object]) -> dict[str, object]:
    return {**payload, "owner_role": "execution_operator"}


def _wrong_digest(payload: dict[str, object]) -> dict[str, object]:
    return {**payload, "logical_order_sha256": _sha("0")}


def _wrong_notional(payload: dict[str, object]) -> dict[str, object]:
    return {**payload, "notional_usd": "26.00"}


def _wrong_client_id(payload: dict[str, object]) -> dict[str, object]:
    return {**payload, "client_order_id": "ta-l-forged"}


def test_normal_live_intent_binds_one_exact_payload_and_id() -> None:
    intent = _make_intent()
    intent.verify_order_payload(_bound_order(intent), at=_at("2026-07-28T12:00:01Z"))
    assert intent.owner_role == "portfolio_executive"
    assert intent.live_submit_authorized is True
    assert intent.paper_submit_authorized is False
    assert AuthorizedNormalTradeIntent.from_dict(intent.to_dict()).canonical_json_bytes() == intent.canonical_json_bytes()


@pytest.mark.parametrize("mutator", [_wrong_owner, _wrong_digest, _wrong_notional, _wrong_client_id])
def test_normal_live_intent_rejects_forged_or_changed_binding(mutator) -> None:
    with pytest.raises(ValueError):
        AuthorizedNormalTradeIntent.from_dict(mutator(_make_intent().to_dict()))


@pytest.mark.parametrize("field,value", [("symbol", "AAPL"), ("side", "sell"), ("order_type", "market"), ("tif", "gtc"), ("notional", "26.00"), ("limit_price", "101.00")])
def test_verify_order_payload_rejects_any_changed_order_binding(field: str, value: str) -> None:
    intent = _make_intent()
    order = _bound_order(intent)
    order[field] = value
    with pytest.raises(ValueError):
        intent.verify_order_payload(order, at=_at("2026-07-28T12:00:01Z"))


@pytest.mark.parametrize("field,value", [("notional_usd", "25.0"), ("limit_price", "0100.00")])
def test_rejects_noncanonical_decimals(field: str, value: str) -> None:
    payload = _make_intent().to_dict()
    payload[field] = value
    with pytest.raises(ValueError):
        AuthorizedNormalTradeIntent.from_dict(payload)


def test_rejects_trade_intent_paper_mapping_future_effective_and_expiry() -> None:
    intent = _make_intent()
    paper = TradeIntent(idempotency_key="x", symbol="MSFT", sleeve="x", environment="paper", limit_price="100.00", size_usd="25.00")
    with pytest.raises(ValueError):
        intent.verify_order_payload(paper, at=_at("2026-07-28T12:00:01Z"))
    with pytest.raises(ValueError):
        intent.verify_order_payload(_bound_order(intent), at=_at("2026-07-28T12:15:00Z"))
    payload = intent.to_dict()
    payload["effective_at"] = "2026-07-28T12:00:01+00:00"
    with pytest.raises(ValueError):
        AuthorizedNormalTradeIntent.from_dict(payload)
