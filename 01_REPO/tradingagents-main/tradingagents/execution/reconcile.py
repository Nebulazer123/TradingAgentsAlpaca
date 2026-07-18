"""Reconcile expected local tiny-live state with broker state."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal

from tradingagents.brokers.alpaca import compare_alpaca_order_to_intent

POSITION_QTY_TOLERANCE = Decimal("0.000001")


@dataclass(frozen=True)
class ReconciliationResult:
    matched: bool
    issues: list[str] = field(default_factory=list)
    checked_client_order_ids: list[str] = field(default_factory=list)


def _decimal(value) -> Decimal:
    return Decimal(str(value or "0"))


def _qty_close(left: Decimal, right: Decimal) -> bool:
    return abs(left - right) <= POSITION_QTY_TOLERANCE


def _positions_by_symbol(positions: Sequence[Mapping]) -> dict[str, Decimal]:
    result: dict[str, Decimal] = {}
    for position in positions:
        symbol = str(position.get("symbol", "")).upper()
        if not symbol:
            continue
        result[symbol] = _decimal(position.get("qty"))
    return result


def reconcile_live_state(
    *,
    expected_positions: Mapping[str, Decimal | int | float | str],
    broker_positions: Sequence[Mapping],
    expected_open_client_order_ids: set[str],
    broker_open_orders: Sequence[Mapping],
) -> ReconciliationResult:
    issues: list[str] = []
    broker_position_map = _positions_by_symbol(broker_positions)
    expected_symbols = {key.upper() for key in expected_positions}
    for symbol, expected_qty in expected_positions.items():
        normalized = symbol.upper()
        actual_qty = broker_position_map.get(normalized, Decimal("0"))
        expected_decimal = _decimal(expected_qty)
        if not _qty_close(actual_qty, expected_decimal):
            issues.append(
                f"position mismatch for {normalized}: expected {expected_decimal} got {actual_qty}"
            )
    for symbol, actual_qty in broker_position_map.items():
        if symbol not in expected_symbols and not _qty_close(actual_qty, Decimal("0")):
            issues.append(f"unexpected live position for {symbol}: {actual_qty}")

    actual_open_ids = {
        str(order.get("client_order_id", ""))
        for order in broker_open_orders
        if order.get("client_order_id")
    }
    missing = sorted(expected_open_client_order_ids - actual_open_ids)
    unexpected = sorted(actual_open_ids - expected_open_client_order_ids)
    for client_order_id in missing:
        issues.append(f"expected open order missing at broker: {client_order_id}")
    for client_order_id in unexpected:
        issues.append(f"unexpected open order at broker: {client_order_id}")

    return ReconciliationResult(
        matched=not issues,
        issues=issues,
        checked_client_order_ids=sorted(actual_open_ids | expected_open_client_order_ids),
    )


def _packet_order_account(packet: Mapping, order: Mapping) -> str:
    client_order_id = str(order.get("client_order_id") or "")
    symbol = str(order.get("symbol") or "").upper()
    side = str(order.get("side") or "").lower()
    for action in packet.get("actions") or []:
        if not isinstance(action, Mapping):
            continue
        if str(action.get("idempotency_key") or "") == client_order_id:
            return str(action.get("account") or "live").lower()
        if str(action.get("symbol") or "").upper() != symbol:
            continue
        if str(action.get("side") or "").lower() not in {"", side}:
            continue
        return str(action.get("account") or "live").lower()
    if "paper" in client_order_id.lower():
        return "paper"
    return "live" if client_order_id.startswith("ta-tiny-") else "unknown"


def _positive_int(value: object) -> int:
    try:
        return max(0, int(value or 0))
    except Exception:
        return 0


def _packet_submission_evidence_count(packet: Mapping) -> int:
    explicit_counts = [
        _positive_int(packet.get(key))
        for key in (
            "submitted_order_count",
            "submitted_count",
            "live_submitted_order_count",
        )
    ]
    metrics = packet.get("metrics")
    if isinstance(metrics, Mapping):
        explicit_counts.extend(
            _positive_int(metrics.get(key))
            for key in (
                "submitted_order_count",
                "submitted_count",
                "live_submitted_order_count",
            )
        )
    return max(explicit_counts or [0])


def _nested_live_order_record(submitted: Mapping) -> Mapping | None:
    for key in ("live_response", "live_order", "live"):
        order = submitted.get(key)
        if isinstance(order, Mapping) and order.get("client_order_id"):
            return order
    return None


def _latest_packet_live_order_records(packet: Mapping) -> list[dict]:
    records: list[dict] = []
    for submitted in packet.get("submitted") or []:
        if not isinstance(submitted, Mapping):
            continue
        nested_live = _nested_live_order_record(submitted)
        if nested_live is not None:
            records.append(
                {
                    "source": "submitted.live_response",
                    "client_order_id": str(nested_live.get("client_order_id")),
                    "intent": nested_live,
                    "expected_account": _packet_order_account(packet, nested_live),
                    "prior_intent_match": True,
                }
            )
            continue
        client_order_id = str(submitted.get("client_order_id") or "")
        if not client_order_id or _packet_order_account(packet, submitted) != "live":
            continue
        records.append(
            {
                "source": "submitted",
                "client_order_id": client_order_id,
                "intent": submitted,
                "expected_account": "live",
                "prior_intent_match": True,
            }
        )
    for reconciled in packet.get("reconciled_orders") or []:
        if not isinstance(reconciled, Mapping):
            continue
        if str(reconciled.get("account") or "").lower() != "live":
            continue
        order = reconciled.get("order")
        if not isinstance(order, Mapping):
            continue
        client_order_id = str(
            reconciled.get("client_order_id") or order.get("client_order_id") or ""
        )
        if not client_order_id:
            continue
        records.append(
            {
                "source": "reconciled_orders",
                "client_order_id": client_order_id,
                "intent": order,
                "expected_account": "live",
                "prior_intent_match": bool(reconciled.get("intent_match", True)),
                "prior_comparison_issues": list(reconciled.get("comparison_issues") or []),
            }
        )
    return records


def _dedupe_live_order_records(records: Sequence[Mapping]) -> tuple[list[dict], list[str]]:
    unique: dict[str, dict] = {}
    issues: list[str] = []
    for record in records:
        client_order_id = str(record.get("client_order_id") or "")
        if not client_order_id:
            continue
        normalized = dict(record)
        existing = unique.get(client_order_id)
        if existing is None:
            unique[client_order_id] = normalized
            continue
        if _live_order_records_conflict(existing, normalized):
            issues.append(f"conflicting packet evidence for {client_order_id}")
    return list(unique.values()), issues


def _live_order_records_conflict(left: Mapping, right: Mapping) -> bool:
    left_intent = left.get("intent") if isinstance(left.get("intent"), Mapping) else {}
    right_intent = right.get("intent") if isinstance(right.get("intent"), Mapping) else {}
    if (
        left.get("expected_account")
        and right.get("expected_account")
        and left.get("expected_account") != right.get("expected_account")
    ):
        return True
    return any(
        left_intent.get(field)
        and right_intent.get(field)
        and str(left_intent.get(field)) != str(right_intent.get(field))
        for field in ("symbol", "side", "type", "qty", "notional", "limit_price")
    )


def reconcile_latest_packet_live_orders(
    packet: Mapping,
    *,
    order_lookup: Callable[[str], Mapping | None],
) -> ReconciliationResult:
    issues: list[str] = []
    checked: list[str] = []
    records, record_issues = _dedupe_live_order_records(_latest_packet_live_order_records(packet))
    issues.extend(record_issues)
    evidence_count = _packet_submission_evidence_count(packet)
    if evidence_count > len(records):
        issues.append(
            "previous packet recorded live submission evidence without client_order_id; "
            "manual reconciliation required"
        )
    for record in records:
        client_order_id = record["client_order_id"]
        checked.append(client_order_id)
        if not record["prior_intent_match"]:
            prior_issues = "; ".join(record.get("prior_comparison_issues") or [])
            issues.append(
                f"previous packet already recorded duplicate order mismatch for {client_order_id}"
                + (f": {prior_issues}" if prior_issues else "")
            )
        try:
            broker_order = order_lookup(client_order_id)
        except Exception as exc:  # pragma: no cover - CLI path preserves concrete lookup text.
            issues.append(
                f"could not verify previous live order at broker: {client_order_id}: {exc}"
            )
            continue
        if not broker_order:
            issues.append(f"previous live order missing at broker: {client_order_id}")
            continue
        comparison_issues = compare_alpaca_order_to_intent(
            broker_order,
            record["intent"],
        )
        issues.extend(
            f"previous live order mismatch for {client_order_id}: {issue}"
            for issue in comparison_issues
        )
        expected_account = str(record.get("expected_account") or "").lower()
        broker_account = str(broker_order.get("account") or "").lower()
        if expected_account and broker_account and expected_account != broker_account:
            issues.append(
                f"previous live order account mismatch for {client_order_id}: "
                f"expected {expected_account} got {broker_account}"
            )
    return ReconciliationResult(
        matched=not issues,
        issues=issues,
        checked_client_order_ids=checked,
    )
