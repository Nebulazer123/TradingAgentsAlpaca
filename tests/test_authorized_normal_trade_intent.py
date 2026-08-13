from __future__ import annotations

import datetime as dt
import hashlib
import json

import pytest

from tradingagents.execution.authorized_normal_trade_intent import (
    AuthorizedNormalTradeIntent,
)
from tradingagents.schemas.trading import TradeIntent
from tradingagents.strategy.paper_execution_authorization import (
    AuthorizedPaperOrderRequest,
)


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


def _recompute_bindings(payload: dict[str, object]) -> dict[str, object]:
    logical_material = dict(payload)
    for field in (
        "authorization_id",
        "logical_order_sha256",
        "client_order_id",
        "owner_role",
        "authorization_scope",
        "live_submit_authorized",
        "paper_submit_authorized",
    ):
        logical_material.pop(field, None)
    logical_order_sha256 = hashlib.sha256(_canonical(logical_material)).hexdigest()
    payload["logical_order_sha256"] = logical_order_sha256
    payload["client_order_id"] = f"ta-l-{logical_order_sha256[:40]}"
    authorization_material = dict(payload)
    authorization_material.pop("authorization_id", None)
    payload["authorization_id"] = (
        "authorized-normal-trade-intent-"
        + hashlib.sha256(_canonical(authorization_material)).hexdigest()
    )
    return payload


def _make_valid_paper_authorization() -> AuthorizedPaperOrderRequest:
    payload: dict[str, object] = {
        "schema_version": 1,
        "authorization_id": "",
        "staged_intent_id": "staged-paper-intent-" + _sha("a"),
        "staged_intent_sha256": _sha("b"),
        "promotion_evidence_id": "promotion-evidence-" + _sha("c"),
        "genome_id": "genome-current-aggressive-" + _sha("d"),
        "genome_canonical_sha256": _sha("e"),
        "evaluation_code_commit": "f" * 40,
        "evaluation_runtime_sha256": _sha("1"),
        "paper_account_fingerprint": _sha("2"),
        "session_date": "2026-07-28",
        "symbol": "MSFT",
        "side": "buy",
        "order_type": "limit",
        "tif": "day",
        "requested_notional_usd": "25.00",
        "requested_limit_price": "100.00",
        "logical_order_sha256": "",
        "client_order_id": "",
        "expires_at": "2026-07-28T12:15:00+00:00",
        "effective_at": "2026-07-28T12:00:00+00:00",
        "recorded_at": "2026-07-28T12:00:01+00:00",
        "owner_role": "execution_operator",
        "authorization_scope": "single_alpaca_paper_order",
        "paper_submit_authorized": True,
        "live_submit_authorized": False,
        "analysis_only": True,
        "paper_only": True,
        "execution_authority": "paper_order_request_only",
        "can_submit_orders": False,
    }
    logical_material = {
        field: payload[field]
        for field in (
            "staged_intent_id",
            "staged_intent_sha256",
            "paper_account_fingerprint",
            "session_date",
            "symbol",
            "side",
            "order_type",
            "tif",
            "requested_notional_usd",
            "requested_limit_price",
        )
    }
    logical_order_sha256 = hashlib.sha256(_canonical(logical_material)).hexdigest()
    payload["logical_order_sha256"] = logical_order_sha256
    payload["client_order_id"] = f"ta-p-{logical_order_sha256[:40]}"
    evidence_payload = {
        field: value
        for field, value in payload.items()
        if field not in {"authorization_id", "effective_at", "recorded_at"}
    }
    payload["authorization_id"] = (
        "paper-execution-authorization-"
        + hashlib.sha256(
            _canonical(
                {
                    "kind": "paper-execution-authorization",
                    "effective_at": payload["effective_at"],
                    "payload": evidence_payload,
                }
            )
        ).hexdigest()
    )
    return AuthorizedPaperOrderRequest.from_dict(payload)


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


def test_rejects_string_subclasses_for_order_fields() -> None:
    class SpoofedBuy(str):
        pass

    payload = _make_intent().to_dict()
    payload["side"] = SpoofedBuy("buy")
    with pytest.raises(ValueError):
        AuthorizedNormalTradeIntent.from_dict(_recompute_bindings(payload))


def test_rejects_boolean_forged_fixed_authorization_field() -> None:
    payload = _make_intent().to_dict()
    payload["live_submit_authorized"] = 1
    with pytest.raises(ValueError):
        AuthorizedNormalTradeIntent.from_dict(payload)


def test_verifier_rejects_actual_paper_authorization_object() -> None:
    paper_request = _make_valid_paper_authorization()
    assert paper_request.paper_submit_authorized is True
    assert paper_request.live_submit_authorized is False
    with pytest.raises(ValueError):
        _make_intent().verify_order_payload(
            paper_request,
            at=_at("2026-07-28T12:00:01Z"),
        )


def test_rejects_future_effective_intent_after_recomputing_bindings() -> None:
    payload = _make_intent().to_dict()
    payload["effective_at"] = "2026-07-28T12:00:01+00:00"
    with pytest.raises(ValueError, match="timestamps"):
        AuthorizedNormalTradeIntent.from_dict(_recompute_bindings(payload))
