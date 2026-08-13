"""Strict, non-authorizing attribution for owner-initiated broker actions."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from pathlib import Path

SCHEMA_VERSION = "tradingagents.owner_manual_broker_action.v1"
KIND = "owner_manual_broker_action"
_TOP_LEVEL_KEYS = {
    "schema_version",
    "kind",
    "attested_by_role",
    "attested_at",
    "environment",
    "symbol",
    "originating_order",
    "manual_fill",
    "analysis_only",
    "execution_authority",
    "can_submit_orders",
    "resolution_id",
}
_ORIGIN_KEYS = {
    "client_order_id",
    "side",
    "filled_qty",
    "source_packet_path",
    "source_packet_sha256",
    "source_order",
}
_SOURCE_ORDER_KEYS = {
    "client_order_id", "symbol", "side", "account", "qty", "notional",
    "type", "limit_price",
}
_FILL_KEYS = {
    "client_order_id",
    "side",
    "status",
    "filled_qty",
    "filled_avg_price",
    "submitted_at",
    "updated_at",
}


def _canonical_json(value: Mapping[str, object]) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def _captured_json(path: str | Path, *, label: str) -> tuple[dict[str, object], bytes, str]:
    candidate = Path(path)
    try:
        raw = candidate.read_bytes()
        value = json.loads(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise ValueError(f"{label} is unreadable") from None
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value, raw, hashlib.sha256(raw).hexdigest()


def _aware_time(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("owner manual action timestamp is required")
    text = value.strip()
    parsed = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("owner manual action timestamp must be timezone-aware")
    return text


def _positive_decimal(value: object, *, label: str) -> str:
    try:
        decimal = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError(f"owner manual action {label} is invalid") from None
    if not decimal.is_finite() or decimal <= 0:
        raise ValueError(f"owner manual action {label} must be finite and positive")
    return str(value)


def _nonempty(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"owner manual action {label} is required")
    return value.strip()


def _find_fill(packet: Mapping[str, object], client_order_id: str) -> Mapping[str, object]:
    matches = [
        row
        for row in packet.get("recent_fills", [])  # type: ignore[arg-type]
        if isinstance(row, Mapping)
        and row.get("client_order_id") == client_order_id
    ]
    if len(matches) != 1:
        raise ValueError("owner manual action requires one exact broker fill")
    return matches[0]


def source_autonomous_order(
    path: str | Path, client_order_id: str, *, symbol: str | None = None
) -> dict[str, object]:
    packet, _raw, _digest_value = _captured_json(
        path, label="owner manual action source packet"
    )
    return source_autonomous_order_from_packet(
        packet, client_order_id, symbol=symbol
    )


def source_autonomous_order_from_packet(
    packet: Mapping[str, object],
    client_order_id: str,
    *,
    symbol: str | None = None,
) -> dict[str, object]:
    records: list[dict[str, object]] = []
    for collection in ("actions", "submitted"):
        for row in packet.get(collection) or []:
            if not isinstance(row, Mapping):
                continue
            candidate = row.get("client_order_id") or row.get("idempotency_key")
            if candidate != client_order_id:
                continue
            records.append(
                {
                    "client_order_id": str(candidate),
                    "symbol": str(row.get("symbol") or "").upper(),
                    "side": str(row.get("side") or "").lower(),
                    "account": str(row.get("account") or "").lower(),
                    "qty": str(row.get("qty") or ""),
                    "notional": str(row.get("notional") or ""),
                    "type": str(row.get("type") or row.get("order_type") or "").lower(),
                    "limit_price": str(row.get("limit_price") or ""),
                    "collection": collection,
                }
            )
    if not records:
        raise ValueError("originating autonomous order is absent from source packet")
    selected = dict(records[0])
    for record in records[1:]:
        for field in (
            "client_order_id", "symbol", "side", "account", "qty", "notional",
            "type", "limit_price",
        ):
            existing = str(selected.get(field) or "")
            incoming = str(record.get(field) or "")
            if existing and incoming and existing != incoming:
                raise ValueError(
                    "originating autonomous order conflicts inside source packet"
                )
            if not existing and incoming:
                selected[field] = incoming
    if (
        selected["side"] != "buy"
        or not selected["symbol"]
        or symbol is not None
        and selected["symbol"] != symbol.upper()
        or selected["account"] not in {"", "live"}
    ):
        raise ValueError("originating source order is not the exact autonomous live buy")
    return {key: selected[key] for key in _SOURCE_ORDER_KEYS}


def capture_source_autonomous_order(
    path: str | Path, client_order_id: str, *, symbol: str | None = None
) -> tuple[dict[str, object], str]:
    packet, _raw, digest = _captured_json(
        path, label="owner manual action source packet"
    )
    return (
        source_autonomous_order_from_packet(
            packet, client_order_id, symbol=symbol
        ),
        digest,
    )


def _resolution_material(payload: Mapping[str, object]) -> dict[str, object]:
    return {key: payload[key] for key in sorted(_TOP_LEVEL_KEYS - {"resolution_id"})}


def _resolution_id(payload: Mapping[str, object]) -> str:
    digest = hashlib.sha256(_canonical_json(_resolution_material(payload))).hexdigest()
    return f"owner-manual-action-{digest}"


def build_owner_manual_action_attribution(
    *,
    source_packet_path: str | Path,
    reconciliation_packet: Mapping[str, object],
    originating_client_order_id: str,
    manual_fill_client_order_id: str,
    attested_at: str,
) -> dict[str, object]:
    """Build a local attestation from captured evidence; performs no broker I/O."""

    source = Path(source_packet_path).resolve()
    origin_id = _nonempty(originating_client_order_id, label="originating client order ID")
    manual_id = _nonempty(manual_fill_client_order_id, label="manual fill client order ID")
    if origin_id == manual_id:
        raise ValueError("manual fill must differ from originating order")
    origin = _find_fill(reconciliation_packet, origin_id)
    manual = _find_fill(reconciliation_packet, manual_id)
    symbol = _nonempty(reconciliation_packet.get("symbol"), label="symbol").upper()
    source_order, source_digest = capture_source_autonomous_order(
        source, origin_id, symbol=symbol
    )
    if (
        str(origin.get("symbol") or "").upper() != symbol
        or str(manual.get("symbol") or "").upper() != symbol
        or str(origin.get("side") or "").lower() != "buy"
        or str(manual.get("side") or "").lower() != "sell"
        or str(origin.get("status") or "").lower() != "filled"
        or str(manual.get("status") or "").lower() != "filled"
    ):
        raise ValueError("owner manual action does not describe a filled buy/sell chain")
    origin_qty = _positive_decimal(origin.get("filled_qty"), label="originating filled quantity")
    manual_qty = _positive_decimal(manual.get("filled_qty"), label="manual filled quantity")
    if Decimal(origin_qty) != Decimal(manual_qty):
        raise ValueError("manual fill quantity does not close the originating order")
    payload: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "kind": KIND,
        "attested_by_role": "account_owner",
        "attested_at": _aware_time(attested_at),
        "environment": "live",
        "symbol": symbol,
        "originating_order": {
            "client_order_id": origin_id,
            "side": "buy",
            "filled_qty": origin_qty,
            "source_packet_path": str(source),
            "source_packet_sha256": source_digest,
            "source_order": source_order,
        },
        "manual_fill": {
            "client_order_id": manual_id,
            "side": "sell",
            "status": "filled",
            "filled_qty": manual_qty,
            "filled_avg_price": _positive_decimal(
                manual.get("filled_avg_price"), label="manual fill average price"
            ),
            "submitted_at": _aware_time(manual.get("submitted_at")),
            "updated_at": _aware_time(manual.get("updated_at")),
        },
        "analysis_only": True,
        "execution_authority": "none",
        "can_submit_orders": False,
    }
    payload["resolution_id"] = _resolution_id(payload)
    return payload


def validate_owner_manual_action_attribution(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping) or set(value) != _TOP_LEVEL_KEYS:
        raise ValueError("owner manual action attribution has an invalid schema")
    payload = dict(value)
    origin = payload.get("originating_order")
    manual = payload.get("manual_fill")
    if (
        payload.get("schema_version") != SCHEMA_VERSION
        or payload.get("kind") != KIND
        or payload.get("attested_by_role") != "account_owner"
        or payload.get("environment") != "live"
        or payload.get("analysis_only") is not True
        or payload.get("execution_authority") != "none"
        or payload.get("can_submit_orders") is not False
        or not isinstance(origin, Mapping)
        or set(origin) != _ORIGIN_KEYS
        or not isinstance(manual, Mapping)
        or set(manual) != _FILL_KEYS
    ):
        raise ValueError("owner manual action attribution has invalid fixed fields")
    _aware_time(payload.get("attested_at"))
    _nonempty(payload.get("symbol"), label="symbol")
    origin_id = _nonempty(origin.get("client_order_id"), label="originating client order ID")
    manual_id = _nonempty(manual.get("client_order_id"), label="manual fill client order ID")
    if origin_id == manual_id or origin.get("side") != "buy":
        raise ValueError("owner manual action origin is invalid")
    if manual.get("side") != "sell" or manual.get("status") != "filled":
        raise ValueError("owner manual action fill is invalid")
    origin_qty = _positive_decimal(origin.get("filled_qty"), label="originating filled quantity")
    manual_qty = _positive_decimal(manual.get("filled_qty"), label="manual filled quantity")
    if Decimal(origin_qty) != Decimal(manual_qty):
        raise ValueError("manual fill quantity does not close the originating order")
    _positive_decimal(manual.get("filled_avg_price"), label="manual fill average price")
    _aware_time(manual.get("submitted_at"))
    _aware_time(manual.get("updated_at"))
    source_path = Path(_nonempty(origin.get("source_packet_path"), label="source packet path"))
    source_sha = _nonempty(origin.get("source_packet_sha256"), label="source packet digest")
    if not source_path.is_absolute() or len(source_sha) != 64 or any(c not in "0123456789abcdef" for c in source_sha):
        raise ValueError("owner manual action source binding is invalid")
    source_order = origin.get("source_order")
    if (
        not isinstance(source_order, Mapping)
        or set(source_order) != _SOURCE_ORDER_KEYS
        or source_order.get("client_order_id") != origin_id
        or source_order.get("symbol") != payload.get("symbol")
        or source_order.get("side") != "buy"
        or source_order.get("account") not in {"", "live"}
        or any(not isinstance(source_order.get(key), str) for key in _SOURCE_ORDER_KEYS)
    ):
        raise ValueError("owner manual action source order binding is invalid")
    if payload.get("resolution_id") != _resolution_id(payload):
        raise ValueError("owner manual action resolution identity is invalid")
    return payload


def load_owner_manual_action_attribution(path: str | Path) -> dict[str, object]:
    value, _raw, _digest_value = _captured_json(
        path, label="owner manual action attribution"
    )
    return validate_owner_manual_action_attribution(value)


def capture_owner_manual_action_attribution(
    path: str | Path,
) -> tuple[dict[str, object], str]:
    value, _raw, digest = _captured_json(
        path, label="owner manual action attribution"
    )
    return validate_owner_manual_action_attribution(value), digest


def write_owner_manual_action_attribution(
    path: str | Path, payload: Mapping[str, object]
) -> Path:
    validated = validate_owner_manual_action_attribution(payload)
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(validated, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    descriptor = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        written = 0
        while written < len(encoded):
            count = os.write(descriptor, encoded[written:])
            if count <= 0:
                raise OSError("incomplete owner manual action attribution write")
            written += count
        os.fsync(descriptor)
        completed_descriptor = descriptor
        descriptor = -1
        os.close(completed_descriptor)
        parent = os.open(destination.parent, os.O_RDONLY)
        try:
            os.fsync(parent)
        finally:
            os.close(parent)
    except Exception:
        if descriptor >= 0:
            os.close(descriptor)
        destination.unlink(missing_ok=True)
        try:
            parent = os.open(destination.parent, os.O_RDONLY)
            try:
                os.fsync(parent)
            finally:
                os.close(parent)
        except OSError:
            pass
        raise
    return destination


def replay_suppression_key(
    *, attribution_sha256: str, resolution_id: str, symbol: str,
    originating_client_order_id: str, resolved_by_client_order_id: str,
    filled_qty: str, source_packet_sha256: str,
) -> str:
    material = {
        "schema_version": "tradingagents.replay_suppression.v1",
        "scope": "exact_incident_exit_chain",
        "attestation_sha256": attribution_sha256,
        "resolution_id": resolution_id,
        "symbol": symbol,
        "originating_client_order_id": originating_client_order_id,
        "resolved_by_client_order_id": resolved_by_client_order_id,
        "filled_qty": filled_qty,
        "source_packet_sha256": source_packet_sha256,
    }
    return hashlib.sha256(_canonical_json(material)).hexdigest()
