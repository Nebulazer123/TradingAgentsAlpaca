"""Read-only reconciliation helpers for ORCL incident evidence."""

from __future__ import annotations

import datetime
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path

from tradingagents.brokers.alpaca import compact_alpaca_order, find_order_by_client_order_id
from tradingagents.execution.reconcile import reconcile_latest_packet_live_orders

UTC = datetime.timezone.utc
DEFAULT_ORCL_SYMBOL = "ORCL"
_EMPTY_TIME_FALLBACK = datetime.datetime(1970, 1, 1, tzinfo=UTC)

_FILLED_STATUSES = {
    "filled",
    "partially_filled",
    "partially_filled_paid",
}
_CANCELED_STATUSES = {
    "canceled",
    "cancelled",
    "expired",
    "rejected",
    "stopped",
    "suspended",
}
_CLOSED_STATUSES = {"closed"}
_OPEN_OR_UNKNOWN_STATUSES = {
    "new",
    "open",
    "accepted",
    "pending_cancel",
    "pending_new",
}
_SYMBOL_RE = re.compile(r"[A-Z][A-Z0-9.]{0,5}")


@dataclass(frozen=True)
class SymbolReconciliationResult:
    symbol: str
    matched: bool
    position: dict
    open_orders: list[dict]
    recent_fills: list[dict]
    checked_client_order_ids: list[str]
    issues: list[str] = field(default_factory=list)
    read_only: bool = True
    broker_write_calls: int = 0


def classify_orcl_old_sell_state(
    old_sell_orders: Sequence[Mapping],
) -> str:
    """Return the final ORCL sell state for evidence packets.

    Returns one of: ``closed``, ``filled``, ``canceled``, ``unknown``.
    """

    if not old_sell_orders:
        return "unknown"

    newest = max(old_sell_orders, key=_event_time)
    status = _normalize_status(newest.get("status"))
    filled_qty = _to_decimal(newest.get("filled_qty")) > 0

    if status in _FILLED_STATUSES or filled_qty:
        return "filled"
    if status in _CANCELED_STATUSES:
        return "canceled"
    if status in _CLOSED_STATUSES:
        return "closed"
    if status in _OPEN_OR_UNKNOWN_STATUSES:
        return "unknown"
    return "unknown"


def reconcile_orcl_sell_state(
    order_packet_paths: Sequence[Path | str],
    *,
    live_client,
    symbol: str = DEFAULT_ORCL_SYMBOL,
    max_recent_fills: int = 25,
) -> dict:
    """Build read-only ORCL reconciliation evidence from packets plus live broker state."""

    symbol = _normalize_symbol(symbol)
    generic_result = reconcile_symbol_incident(
        symbol=symbol,
        packet_paths=order_packet_paths,
        live_client=live_client,
    )
    packet_paths = [Path(path) for path in order_packet_paths]
    packet_orders: list[dict] = []
    packet_read_issues: list[dict] = []
    for packet_path in packet_paths:
        packet, issue = _read_packet_with_issue(packet_path)
        if issue:
            packet_read_issues.append({"path": str(packet_path), "issue": issue})
        packet_orders.extend(
            _iter_orcl_sell_orders_from_packet(
                packet,
                symbol=symbol,
                packet_path=packet_path,
            )
        )

    old_sell_orders = _dedupe_orders(packet_orders)
    reconciled_orders = [
        _enrich_order_from_live(order, live_client) for order in old_sell_orders
    ]

    final_state = classify_orcl_old_sell_state(reconciled_orders)

    return {
        "order_packet_paths": [str(path) for path in packet_paths],
        "old_sell_orders": reconciled_orders,
        "current_orcl_position": generic_result.position,
        "open_orcl_orders": generic_result.open_orders,
        "recent_orcl_fills": generic_result.recent_fills[:max_recent_fills],
        "final_old_sell_state": final_state,
        "packet_read_issues": packet_read_issues,
    }


def reconcile_symbol_incident(
    *,
    symbol: str,
    packet_paths: Sequence[str | Path],
    live_client,
    expected_qty: Decimal | str | None = None,
) -> SymbolReconciliationResult:
    """Reconcile one symbol's packet evidence with live broker reads only."""

    target_symbol = _require_symbol(symbol)
    resolved_paths = [Path(path) for path in packet_paths]
    issues: list[str] = []
    checked_client_order_ids: list[str] = []

    for packet_path in resolved_paths:
        packet, packet_issue = _read_packet_with_issue(packet_path)
        if packet_issue:
            issues.append(f"packet read issue for {packet_path}: {packet_issue}")
            continue
        packet_result = reconcile_latest_packet_live_orders(
            _symbol_packet_for_idempotency(packet, target_symbol),
            order_lookup=lambda client_order_id: find_order_by_client_order_id(
                live_client,
                client_order_id,
            ),
        )
        issues.extend(packet_result.issues)
        checked_client_order_ids.extend(packet_result.checked_client_order_ids)

    positions = _safe_list_positions(live_client)
    raw_position = _extract_position(positions, target_symbol)
    open_orders = _filter_symbol_orders(_safe_list_orders(live_client, "open"), target_symbol)
    all_orders = _safe_list_orders(live_client, "all")
    recent_fills = _recent_fills(all_orders, symbol=target_symbol)

    _append_position_issues(
        issues,
        position=raw_position,
        symbol=target_symbol,
        expected_qty=expected_qty,
    )
    _append_unknown_order_issues(issues, open_orders, checked_client_order_ids)
    _append_unknown_fill_issues(issues, recent_fills, checked_client_order_ids)

    return SymbolReconciliationResult(
        symbol=target_symbol,
        matched=not issues,
        position=raw_position,
        open_orders=open_orders,
        recent_fills=recent_fills,
        checked_client_order_ids=checked_client_order_ids,
        issues=issues,
    )


def _iter_orcl_sell_orders_from_packet(
    packet: Mapping,
    *,
    symbol: str,
    packet_path: Path | None = None,
) -> Iterable[dict]:
    for submitted in packet.get("submitted") or []:
        if not isinstance(submitted, Mapping):
            continue

        order_payload = _extract_order_payload(
            submitted,
            fallback_keys=("live_response", "live_order", "intent", "order"),
        )
        if not _is_orcl_sell(order_payload, symbol=symbol):
            continue
        yield _extract_order_record(
            order_payload,
            packet_path=packet_path,
            source="submitted",
        )

    for reconciled in packet.get("reconciled_orders") or []:
        if not isinstance(reconciled, Mapping):
            continue
        account = str(reconciled.get("account") or "").lower()
        if account and account not in {"live", "unknown"}:
            continue

        reconciled_order = _extract_order_payload(
            reconciled,
            fallback_keys=("live_response", "live_order", "live", "order", "intent"),
        )
        if not _is_orcl_sell(reconciled_order, symbol=symbol):
            continue

        order_record = _extract_order_record(
            reconciled_order,
            packet_path=packet_path,
            source="reconciled_orders",
        )

        client_order_id = str(
            reconciled.get("client_order_id")
            or reconciled_order.get("client_order_id")
            or order_record.get("client_order_id")
            or ""
        ).strip()
        if client_order_id:
            order_record["client_order_id"] = client_order_id
        if account:
            order_record["account"] = account
        if "intent_match" in reconciled:
            order_record["intent_match"] = bool(reconciled.get("intent_match"))
        if "comparison_issues" in reconciled:
            order_record["comparison_issues"] = list(reconciled.get("comparison_issues") or [])
        yield order_record


def _extract_order_payload(order: Mapping, *, fallback_keys: tuple[str, ...]) -> Mapping:
    for key in fallback_keys:
        nested = order.get(key)
        if isinstance(nested, Mapping):
            return nested
    return order


def _symbol_packet_for_idempotency(packet: Mapping, symbol: str) -> dict:
    """Keep only the requested symbol before reusing generic idempotency checks."""

    result = {
        key: packet.get(key)
        for key in (
            "submitted_order_count",
            "submitted_count",
            "live_submitted_order_count",
            "metrics",
        )
        if key in packet
    }
    result["actions"] = [
        action
        for action in packet.get("actions") or []
        if isinstance(action, Mapping) and _normalize_symbol(action.get("symbol")) == symbol
    ]
    result["submitted"] = [
        submitted
        for submitted in packet.get("submitted") or []
        if isinstance(submitted, Mapping)
        and _normalize_symbol(
            _extract_order_payload(
                submitted,
                fallback_keys=("live_response", "live_order", "live", "intent", "order"),
            ).get("symbol")
        )
        == symbol
    ]
    result["reconciled_orders"] = [
        reconciled
        for reconciled in packet.get("reconciled_orders") or []
        if isinstance(reconciled, Mapping)
        and _normalize_symbol(
            _extract_order_payload(
                reconciled,
                fallback_keys=("live_response", "live_order", "live", "order", "intent"),
            ).get("symbol")
        )
        == symbol
    ]
    return result


def _append_position_issues(
    issues: list[str],
    *,
    position: Mapping,
    symbol: str,
    expected_qty: Decimal | str | None,
) -> None:
    actual_qty = _strict_decimal(position.get("qty"))
    if actual_qty is None:
        issues.append(f"malformed broker position quantity for {symbol}")
        return
    if expected_qty is None:
        if actual_qty != 0:
            issues.append(f"unexpected live position for {symbol}: {actual_qty}")
        return
    expected_decimal = _strict_decimal(expected_qty)
    if expected_decimal is None:
        raise ValueError("expected_qty must be a decimal value")
    if abs(actual_qty - expected_decimal) > Decimal("0.000001"):
        issues.append(
            f"position mismatch for {symbol}: expected {expected_decimal} got {actual_qty}"
        )


def _append_unknown_order_issues(
    issues: list[str],
    open_orders: Sequence[Mapping],
    checked_client_order_ids: Sequence[str],
) -> None:
    known_ids = set(checked_client_order_ids)
    for order in open_orders:
        client_order_id = _stringify(order.get("client_order_id"))
        if not client_order_id or client_order_id not in known_ids:
            label = client_order_id or "missing client_order_id"
            issues.append(f"unexpected open order at broker: {label}")


def _append_unknown_fill_issues(
    issues: list[str],
    recent_fills: Sequence[Mapping],
    checked_client_order_ids: Sequence[str],
) -> None:
    known_ids = set(checked_client_order_ids)
    for fill in recent_fills:
        client_order_id = _stringify(fill.get("client_order_id"))
        if not client_order_id or client_order_id not in known_ids:
            label = client_order_id or "missing client_order_id"
            issues.append(f"unexpected recent fill at broker: {label}")


def _extract_order_record(
    order: Mapping,
    *,
    packet_path: Path | None,
    source: str,
) -> dict:
    return {
        "source": source,
        "packet_path": str(packet_path) if packet_path else "",
        "client_order_id": _stringify(order.get("client_order_id")),
        "submitted_at": _stringify_timestamp(order.get("submitted_at")),
        "status": _normalize_status(order.get("status")),
        "filled_at": _stringify_timestamp(order.get("filled_at")),
        "filled_avg_price": _stringify(order.get("filled_avg_price")),
        "filled_qty": _stringify(order.get("filled_qty")),
        "qty": _stringify(order.get("qty")),
        "notional": _stringify(order.get("notional")),
    }


def _enrich_order_from_live(order: Mapping, live_client) -> dict:
    client_order_id = _stringify(order.get("client_order_id"))
    if not client_order_id:
        return dict(order)

    try:
        broker_order = find_order_by_client_order_id(live_client, client_order_id)
    except Exception:
        broker_order = None
    if not isinstance(broker_order, Mapping):
        return dict(order)

    result = {
        **order,
        "status": _normalize_status(
            broker_order.get("status") if broker_order.get("status") is not None else order.get("status")
        ),
        "submitted_at": _stringify_timestamp(
            broker_order.get("submitted_at") or order.get("submitted_at")
        ),
        "filled_at": _stringify_timestamp(
            broker_order.get("filled_at") or order.get("filled_at")
        ),
        "filled_avg_price": _stringify(
            broker_order.get("filled_avg_price")
            if broker_order.get("filled_avg_price") is not None
            else order.get("filled_avg_price")
        ),
        "filled_qty": _stringify(
            broker_order.get("filled_qty")
            if broker_order.get("filled_qty") is not None
            else order.get("filled_qty")
        ),
        "qty": _stringify(
            broker_order.get("qty")
            if broker_order.get("qty") is not None
            else order.get("qty")
        ),
        "notional": _stringify(
            broker_order.get("notional")
            if broker_order.get("notional") is not None
            else order.get("notional")
        ),
        "broker_order": compact_alpaca_order(broker_order),
    }
    return result


def _extract_position(positions: Sequence[Mapping], symbol: str) -> dict:
    target_symbol = _normalize_symbol(symbol)
    for position in positions:
        if not isinstance(position, Mapping):
            continue
        if _normalize_symbol(position.get("symbol")) != target_symbol:
            continue
        return {
            "symbol": target_symbol,
            "qty": _stringify(position.get("qty", "0")),
            "notional": _stringify(position.get("notional", "0")),
            "market_value": _stringify(position.get("market_value", "0")),
            "avg_entry_price": _stringify(position.get("avg_entry_price", "")),
            "avg_entry_price_hint": _stringify(position.get("average_entry_price", "")),
        }

    return {
        "symbol": target_symbol,
        "qty": "0",
        "notional": "0",
        "market_value": "0",
        "avg_entry_price": "0",
    }


def _filter_symbol_orders(orders: Sequence[Mapping], symbol: str) -> list[dict]:
    target_symbol = _normalize_symbol(symbol)
    return [
        compact_alpaca_order(order)
        for order in orders
        if isinstance(order, Mapping)
        and _normalize_symbol(order.get("symbol")) == target_symbol
    ]


def _recent_fills(orders: Sequence[Mapping], *, symbol: str, limit: int = 25) -> list[dict]:
    target_symbol = _normalize_symbol(symbol)
    if limit <= 0:
        return []

    fills: list[dict] = []
    for order in orders:
        if not isinstance(order, Mapping):
            continue
        if _normalize_symbol(order.get("symbol")) != target_symbol:
            continue
        filled_qty = _to_decimal(order.get("filled_qty"))
        status = _normalize_status(order.get("status"))
        if status not in _FILLED_STATUSES and filled_qty <= 0:
            continue

        fills.append(
            compact_alpaca_order(
                {
                    "client_order_id": order.get("client_order_id"),
                    "symbol": order.get("symbol"),
                    "side": order.get("side"),
                    "status": status,
                    "qty": order.get("qty"),
                    "notional": order.get("notional"),
                    "filled_qty": order.get("filled_qty"),
                    "filled_avg_price": order.get("filled_avg_price"),
                    "filled_at": order.get("filled_at"),
                    "submitted_at": order.get("submitted_at"),
                    "updated_at": order.get("updated_at"),
                }
            )
        )

    fills.sort(
        key=lambda item: _parse_timestamp(item.get("filled_at"))
        or _parse_timestamp(item.get("submitted_at"))
        or _EMPTY_TIME_FALLBACK,
        reverse=True,
    )
    return fills[:limit]


def _safe_list_orders(client, status: str) -> list[dict]:
    list_orders = getattr(client, "list_orders", None)
    if not callable(list_orders):
        return []
    try:
        orders = list_orders(status=status)
    except TypeError:
        orders = list_orders()
    return [order for order in orders if isinstance(order, Mapping)]


def _safe_list_positions(client) -> list[dict]:
    list_positions = getattr(client, "list_positions", None)
    if not callable(list_positions):
        return []
    positions = list_positions()
    return [position for position in positions if isinstance(position, Mapping)]


def _read_packet(path: Path | str) -> dict:
    payload, _issue = _read_packet_with_issue(path)
    return payload


def _read_packet_with_issue(path: Path | str) -> tuple[dict, str | None]:
    packet_path = Path(path)
    if not packet_path.exists():
        return {}, "missing_packet"
    try:
        payload_text = packet_path.read_text(encoding="utf-8")
        if not payload_text.strip():
            return {}, "empty_packet"
        payload = json.loads(payload_text)
    except OSError as exc:
        return {}, f"read_error:{type(exc).__name__}"
    except ValueError:
        return {}, "invalid_json"
    if isinstance(payload, Mapping):
        return dict(payload), None
    return {}, "non_object_json"


def _is_orcl_sell(order: Mapping, *, symbol: str) -> bool:
    return (
        _normalize_symbol(order.get("symbol")) == symbol
        and _normalize_status(order.get("side")) == "sell"
    )


def _dedupe_orders(orders: Sequence[Mapping]) -> list[dict]:
    latest: dict[str, dict] = {}
    for order in orders:
        if not isinstance(order, Mapping):
            continue
        client_order_id = _stringify(order.get("client_order_id"))
        if not client_order_id:
            continue
        candidate = dict(order)
        existing = latest.get(client_order_id)
        if existing is None or _event_time(candidate) >= _event_time(existing):
            latest[client_order_id] = candidate

    return sorted(
        latest.values(),
        key=lambda item: _event_time(item),
        reverse=True,
    )


def _event_time(order: Mapping) -> datetime.datetime:
    return (
        _parse_timestamp(order.get("submitted_at"))
        or _parse_timestamp(order.get("filled_at"))
        or _EMPTY_TIME_FALLBACK
    )


def _parse_timestamp(value: object) -> datetime.datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime.datetime):
        dt = value
    else:
        text = str(value).strip()
        if not text:
            return None
        # `fromisoformat` handles many broker timestamp shapes and offsets.
        text = text.replace("Z", "+00:00")
        try:
            dt = datetime.datetime.fromisoformat(text)
        except ValueError:
            for fmt in (
                "%Y-%m-%d %H:%M:%S%z",
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%dT%H:%M:%S%z",
                "%Y-%m-%dT%H:%M:%S",
            ):
                try:
                    dt = datetime.datetime.strptime(text, fmt)
                    break
                except ValueError:
                    continue
            else:
                return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _stringify(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _stringify_timestamp(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime.datetime):
        return value.isoformat()
    return _stringify(value)


def _normalize_status(value: object) -> str:
    return str(value or "").lower().strip()


def _to_decimal(value: object) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")


def _strict_decimal(value: object) -> Decimal | None:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _require_symbol(value: object) -> str:
    symbol = _normalize_symbol(value)
    if not _SYMBOL_RE.fullmatch(symbol):
        raise ValueError("invalid symbol")
    return symbol


def _normalize_symbol(value: object) -> str:
    return str(value or "").upper().strip()
