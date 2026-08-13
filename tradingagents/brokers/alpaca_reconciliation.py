"""Read-only symbol reconciliation with ORCL incident compatibility helpers."""

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
    normalized_expected_qty, expected_issue = _validate_expected_qty(expected_qty)
    if expected_issue:
        return SymbolReconciliationResult(
            symbol=target_symbol,
            matched=False,
            position=_empty_position(target_symbol),
            open_orders=[],
            recent_fills=[],
            checked_client_order_ids=[],
            issues=[expected_issue],
        )

    resolved_paths = [Path(path) for path in packet_paths]
    issues: list[str] = []
    checked_client_order_ids: list[str] = []
    packet_evidence: dict[str, dict] = {}
    combined_packet = {"actions": [], "submitted": [], "reconciled_orders": []}

    for packet_path in resolved_paths:
        packet, packet_issue = _read_packet_with_issue(packet_path)
        if packet_issue:
            issues.append(f"packet read issue for {packet_path}: {packet_issue}")
            continue
        symbol_packet, packet_count_issues = _symbol_packet_for_idempotency(packet, target_symbol)
        issues.extend(packet_count_issues)
        _append_packet_evidence_conflicts(
            issues,
            packet_evidence,
            symbol_packet,
        )
        _append_target_submission_count_issues(issues, symbol_packet)
        for key in combined_packet:
            combined_packet[key].extend(symbol_packet[key])

    packet_result = reconcile_latest_packet_live_orders(
        combined_packet,
        order_lookup=lambda client_order_id: _lookup_live_order(live_client, client_order_id),
    )
    issues.extend(packet_result.issues)
    checked_client_order_ids.extend(packet_result.checked_client_order_ids)

    positions, position_issue = _read_broker_collection(
        live_client,
        method_name="list_positions",
        label="broker positions",
    )
    open_order_rows, open_orders_issue = _read_broker_collection(
        live_client,
        method_name="list_orders",
        label="broker open orders",
        status="open",
    )
    all_order_rows, all_orders_issue = _read_broker_collection(
        live_client,
        method_name="list_orders",
        label="broker all orders",
        status="all",
    )
    issues.extend(
        issue
        for issue in (position_issue, open_orders_issue, all_orders_issue)
        if issue is not None
    )

    matching_positions = _matching_positions(positions, target_symbol)
    raw_position = _extract_position(matching_positions, target_symbol)
    if len(matching_positions) > 1:
        raw_position["duplicate_count"] = len(matching_positions)
        issues.append(f"duplicate broker positions for {target_symbol}: {len(matching_positions)}")
    target_open_orders = _matching_orders(open_order_rows, target_symbol)
    target_all_orders = _matching_orders(all_order_rows, target_symbol)
    open_orders = [compact_alpaca_order(order) for order in target_open_orders]
    recent_fills = _recent_fills(target_all_orders, symbol=target_symbol)

    _append_position_issues(
        issues,
        position=raw_position,
        symbol=target_symbol,
        expected_qty=normalized_expected_qty,
    )
    _append_unknown_order_issues(issues, open_orders, checked_client_order_ids)
    _append_unknown_fill_issues(issues, recent_fills, checked_client_order_ids)
    _append_order_quantity_issues(issues, target_open_orders, kind="open order")
    _append_order_quantity_issues(issues, target_all_orders, kind="order")

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


def _symbol_packet_for_idempotency(packet: Mapping, symbol: str) -> tuple[dict, list[str]]:
    """Keep only the requested symbol before reusing generic idempotency checks."""

    issues: list[str] = []
    result: dict = {}
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
    all_records = [
        entry
        for key in ("submitted", "reconciled_orders")
        for entry in packet.get(key) or []
        if isinstance(entry, Mapping)
        and _packet_record_client_order_id(entry)
    ]
    all_symbols = {
        _normalize_symbol(
            _extract_order_payload(
                entry,
                fallback_keys=("live_response", "live_order", "live", "order", "intent"),
            ).get("symbol")
        )
        for entry in all_records
    }
    explicit_count = _packet_explicit_submission_count(packet)
    if explicit_count is not None:
        if all_symbols <= {symbol}:
            result["submitted_order_count"] = explicit_count
        elif explicit_count != len({_packet_record_client_order_id(entry) for entry in all_records}):
            issues.append(
                "ambiguous cross-symbol packet submission count cannot be allocated to "
                f"{symbol}"
            )
    return result, issues


def _packet_record_client_order_id(entry: Mapping) -> str:
    payload = _extract_order_payload(
        entry,
        fallback_keys=("live_response", "live_order", "live", "order", "intent"),
    )
    return _stringify(entry.get("client_order_id") or payload.get("client_order_id"))


def _append_target_submission_count_issues(issues: list[str], packet: Mapping) -> None:
    count = _packet_explicit_submission_count(packet)
    if count is None:
        return
    live_ids = {
        record["client_order_id"]
        for record in _packet_evidence_records(packet)
        if record.get("account") != "paper"
    }
    if count > len(live_ids):
        issues.append(
            "previous packet recorded live submission evidence without client_order_id; "
            "manual reconciliation required"
        )


def _validate_expected_qty(value: Decimal | str | None) -> tuple[Decimal | None, str | None]:
    if value is None:
        return None, None
    quantity = _nonnegative_decimal(value)
    if quantity is None:
        return None, f"invalid expected quantity: {value}"
    return quantity, None


def _read_broker_collection(
    client,
    *,
    method_name: str,
    label: str,
    status: str | None = None,
) -> tuple[list[dict], str | None]:
    method = getattr(client, method_name, None)
    if not callable(method):
        return [], f"{label} read unavailable"
    try:
        rows = method() if status is None else method(status=status)
    except TypeError:
        if status is None:
            return [], f"{label} read failed: TypeError"
        try:
            rows = method()
        except Exception as exc:
            return [], f"{label} read failed: {type(exc).__name__}"
    except Exception as exc:
        return [], f"{label} read failed: {type(exc).__name__}"
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        return [], f"{label} read returned non-sequence"
    if any(not isinstance(row, Mapping) for row in rows):
        return [], f"{label} read returned malformed rows"
    return [dict(row) for row in rows], None


def _lookup_live_order(client, client_order_id: str) -> Mapping | None:
    lookup = getattr(client, "get_order_by_client_order_id", None)
    if callable(lookup):
        order = lookup(client_order_id)
        return dict(order) if isinstance(order, Mapping) else None
    return find_order_by_client_order_id(client, client_order_id)


def _matching_positions(positions: Sequence[Mapping], symbol: str) -> list[dict]:
    return [
        dict(position)
        for position in positions
        if _normalize_symbol(position.get("symbol")) == symbol
    ]


def _matching_orders(orders: Sequence[Mapping], symbol: str) -> list[dict]:
    return [
        dict(order)
        for order in orders
        if _normalize_symbol(order.get("symbol")) == symbol
    ]


def _packet_explicit_submission_count(packet: Mapping) -> int | None:
    values = [
        packet.get(key)
        for key in ("submitted_order_count", "submitted_count", "live_submitted_order_count")
        if key in packet
    ]
    metrics = packet.get("metrics")
    if isinstance(metrics, Mapping):
        values.extend(
            metrics.get(key)
            for key in ("submitted_order_count", "submitted_count", "live_submitted_order_count")
            if key in metrics
        )
    counts = [_positive_int(value) for value in values]
    return max(counts) if counts else None


def _append_packet_evidence_conflicts(
    issues: list[str],
    known_evidence: dict[str, dict],
    packet: Mapping,
) -> None:
    for record in _packet_evidence_records(packet):
        client_order_id = record["client_order_id"]
        previous = known_evidence.get(client_order_id)
        if previous is None:
            known_evidence[client_order_id] = record
            continue
        if _packet_evidence_conflicts(previous, record):
            issues.append(f"conflicting packet evidence for {client_order_id}")


def _packet_evidence_records(packet: Mapping) -> Iterable[dict]:
    action_accounts = {
        _stringify(action.get("idempotency_key")): _normalize_status(action.get("account"))
        for action in packet.get("actions") or []
        if isinstance(action, Mapping)
    }
    for collection_key in ("submitted", "reconciled_orders"):
        for entry in packet.get(collection_key) or []:
            if not isinstance(entry, Mapping):
                continue
            payload = _extract_order_payload(
                entry,
                fallback_keys=("live_response", "live_order", "live", "order", "intent"),
            )
            client_order_id = _stringify(
                entry.get("client_order_id") or payload.get("client_order_id")
            )
            if not client_order_id:
                continue
            yield {
                "client_order_id": client_order_id,
                "symbol": _normalize_symbol(payload.get("symbol")),
                "side": _normalize_status(payload.get("side")),
                "type": _normalize_status(payload.get("type")),
                "account": _normalize_status(
                    entry.get("account") or action_accounts.get(client_order_id)
                ),
                "qty": _stringify(payload.get("qty")),
                "notional": _stringify(payload.get("notional")),
                "limit_price": _stringify(payload.get("limit_price")),
            }


def _packet_evidence_conflicts(left: Mapping, right: Mapping) -> bool:
    return any(
        left.get(key) and right.get(key) and left.get(key) != right.get(key)
        for key in ("symbol", "side", "type", "account", "qty", "notional", "limit_price")
    )


def _append_order_quantity_issues(
    issues: list[str],
    orders: Sequence[Mapping],
    *,
    kind: str,
) -> None:
    for order in orders:
        client_order_id = _stringify(order.get("client_order_id")) or "missing client_order_id"
        for field_name in ("qty", "filled_qty"):
            value = order.get(field_name)
            if value in (None, ""):
                continue
            if _nonnegative_decimal(value) is None:
                issues.append(f"invalid broker {kind} {field_name} for {client_order_id}")


def _append_position_issues(
    issues: list[str],
    *,
    position: Mapping,
    symbol: str,
    expected_qty: Decimal | str | None,
) -> None:
    actual_qty = _nonnegative_decimal(position.get("qty"))
    if actual_qty is None:
        issues.append(f"invalid broker position quantity for {symbol}")
        return
    if expected_qty is None:
        if actual_qty != 0:
            issues.append(f"unexpected live position for {symbol}: {actual_qty}")
        return
    if abs(actual_qty - expected_qty) > Decimal("0.000001"):
        issues.append(
            f"position mismatch for {symbol}: expected {expected_qty} got {actual_qty}"
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

    return _empty_position(target_symbol)


def _empty_position(symbol: str) -> dict:
    return {
        "symbol": symbol,
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


def _nonnegative_decimal(value: object) -> Decimal | None:
    parsed = _strict_decimal(value)
    if parsed is None or not parsed.is_finite() or parsed < 0:
        return None
    return parsed


def _strict_decimal(value: object) -> Decimal | None:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _positive_int(value: object) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _require_symbol(value: object) -> str:
    symbol = _normalize_symbol(value)
    if not _SYMBOL_RE.fullmatch(symbol):
        raise ValueError("invalid symbol")
    return symbol


def _normalize_symbol(value: object) -> str:
    return str(value or "").upper().strip()
