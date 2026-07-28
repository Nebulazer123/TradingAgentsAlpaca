"""Reconcile expected local tiny-live state with broker state."""

from __future__ import annotations

import datetime
import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal

from tradingagents.execution.authorized_normal_trade_intent import (
    AuthorizedNormalTradeIntent,
)

POSITION_QTY_TOLERANCE = Decimal("0.000001")
_NORMAL_LIVE_RECONCILIATION_MAX_AGE_SECONDS = 30


@dataclass(frozen=True)
class ReconciliationResult:
    matched: bool
    issues: list[str] = field(default_factory=list)
    checked_client_order_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class _NormalLiveReconciliationBinding:
    """Private proof that a real read-only reconciliation bound one intent."""

    intent_full_sha256: str
    order_payload_sha256: str
    client_order_id: str
    checked_at: datetime.datetime
    broker_read_adapter: object


_NORMAL_LIVE_RECONCILIATION_RESULTS: dict[
    int, tuple[ReconciliationResult, _NormalLiveReconciliationBinding]
] = {}
_NORMAL_LIVE_RECONCILIATION_CLAIMS: dict[
    int, tuple[_NormalLiveReconciliationBinding, object]
] = {}
_NORMAL_LIVE_BROKER_READ_ADAPTERS: dict[int, tuple[object, object]] = {}


def _register_normal_live_broker_read_adapter(client: object) -> object:
    """Create the private adapter that owns all normal-live broker reads.

    Only :class:`AlpacaRestClient` calls this during construction.  The opaque
    object is checked by identity below, so a caller cannot replace account,
    position, open-order, or client-id lookup data with a callback or a plain
    value object.
    """

    adapter = object()
    _NORMAL_LIVE_BROKER_READ_ADAPTERS[id(adapter)] = (adapter, client)
    return adapter


def _normal_live_reconciliation_clock() -> datetime.datetime:
    return datetime.datetime.now(tz=datetime.timezone.utc).replace(microsecond=0)


def _owned_normal_live_broker_read(
    adapter: object,
    *,
    client_order_id: str,
) -> tuple[dict[str, object], tuple[dict[str, object], ...], tuple[dict[str, object], ...], dict[str, object] | None, datetime.datetime]:
    """Collect one complete read-only broker snapshot through an owned client."""

    entry = _NORMAL_LIVE_BROKER_READ_ADAPTERS.get(id(adapter))
    if entry is None or entry[0] is not adapter:
        raise ValueError("normal live reconciliation requires an owned broker read adapter")
    client = entry[1]
    collect = getattr(client, "_collect_normal_live_reconciliation_reads", None)
    if not callable(collect):
        raise ValueError("normal live reconciliation broker read adapter is unavailable")
    try:
        raw = collect(client_order_id=client_order_id)
    except Exception as exc:
        raise ValueError("normal live reconciliation broker snapshot is unavailable") from exc
    if type(raw) is not tuple or len(raw) != 5:
        raise ValueError("normal live reconciliation broker snapshot is ambiguous")
    account, positions, open_orders, exact_order, collected_at = raw
    if type(account) is not dict:
        raise ValueError("normal live reconciliation account snapshot is ambiguous")
    if (
        type(positions) is not tuple
        or type(open_orders) is not tuple
        or any(type(item) is not dict for item in positions)
        or any(type(item) is not dict for item in open_orders)
        or (exact_order is not None and type(exact_order) is not dict)
    ):
        raise ValueError("normal live reconciliation broker snapshot is ambiguous")
    return account, positions, open_orders, exact_order, _normal_live_reconciliation_moment(collected_at)


def _owned_normal_live_broker_lookup(
    adapter: object, *, client_order_id: str
) -> dict[str, object] | None:
    """Read one exact idempotency key through the registered owned client."""

    entry = _NORMAL_LIVE_BROKER_READ_ADAPTERS.get(id(adapter))
    if entry is None or entry[0] is not adapter:
        raise ValueError("normal live broker adapter is unavailable")
    lookup = getattr(entry[1], "_lookup_live_order_by_client_order_id", None)
    if not callable(lookup):
        raise ValueError("normal live broker adapter is unavailable")
    result = lookup(client_order_id)
    if result is not None and type(result) is not dict:
        raise ValueError("normal live broker lookup is ambiguous")
    return result


def _owned_normal_live_broker_post(
    adapter: object, *, order_payload: Mapping[str, str]
) -> dict[str, object]:
    """Use the exact registered client for the one bound normal-live POST."""

    entry = _NORMAL_LIVE_BROKER_READ_ADAPTERS.get(id(adapter))
    if entry is None or entry[0] is not adapter:
        raise ValueError("normal live broker adapter is unavailable")
    post = getattr(entry[1], "_post_normal_live_order_payload", None)
    if not callable(post):
        raise ValueError("normal live broker adapter is unavailable")
    result = post(order_payload)
    if type(result) is not dict:
        raise ValueError("normal live broker result is ambiguous")
    return result


def _normal_live_reconciliation_payload_sha256(payload: Mapping[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(
            dict(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
    ).hexdigest()


def _normal_live_reconciliation_moment(value: datetime.datetime) -> datetime.datetime:
    if (
        type(value) is not datetime.datetime
        or value.tzinfo is None
        or value.utcoffset() is None
        or value.microsecond
    ):
        raise ValueError("normal live reconciliation requires an aware whole-second time")
    return value.astimezone(datetime.timezone.utc)


def reconcile_normal_live_submit(
    *,
    intent: AuthorizedNormalTradeIntent,
    order_payload: Mapping[str, object],
    broker_read_adapter: object,
) -> ReconciliationResult:
    """Run and bind the final read-only reconciliation for one live intent.

    This is intentionally the only path that makes a clean
    :class:`ReconciliationResult` usable for normal-live admission.  A plain
    public result object has no process-local binding and cannot stand in for
    the real account/order reads performed here.
    """

    if type(intent) is not AuthorizedNormalTradeIntent:
        raise ValueError("normal live reconciliation requires exact typed inputs")
    payload = dict(order_payload)
    account, positions, open_orders, existing, moment = _owned_normal_live_broker_read(
        broker_read_adapter,
        client_order_id=intent.client_order_id,
    )
    try:
        intent.verify_order_payload(payload, at=moment)
    except (TypeError, ValueError) as exc:
        raise ValueError("normal live reconciliation payload does not bind the intent") from exc

    # A normal live submission has no independently reconciled local position
    # ledger at this boundary.  Treat any unknown live position/open order as a
    # hard discrepancy rather than allowing a caller-provided snapshot to
    # bless it.  The exact candidate order itself may already exist and is
    # handled below as an idempotent replay.
    expected_open_client_order_ids = (
        {intent.client_order_id} if existing is not None else set()
    )
    baseline = reconcile_live_state(
        expected_positions={},
        broker_positions=positions,
        expected_open_client_order_ids=expected_open_client_order_ids,
        broker_open_orders=open_orders,
    )
    issues = list(baseline.issues)
    checked = sorted({*baseline.checked_client_order_ids, intent.client_order_id})
    if existing is not None:
        from tradingagents.brokers.alpaca import compare_alpaca_order_to_intent

        issues.extend(
            f"normal live reconciliation mismatch for {intent.client_order_id}: {issue}"
            for issue in compare_alpaca_order_to_intent(existing, payload)
        )

    result = ReconciliationResult(
        matched=not issues,
        issues=issues,
        checked_client_order_ids=checked,
    )
    _NORMAL_LIVE_RECONCILIATION_RESULTS[id(result)] = (
        result,
        _NormalLiveReconciliationBinding(
            intent_full_sha256=hashlib.sha256(intent.canonical_json_bytes()).hexdigest(),
            order_payload_sha256=_normal_live_reconciliation_payload_sha256(payload),
            client_order_id=intent.client_order_id,
            checked_at=moment,
            broker_read_adapter=broker_read_adapter,
        ),
    )
    return result


def _claim_normal_live_submit_reconciliation(
    reconciliation: object,
    *,
    intent: AuthorizedNormalTradeIntent,
    order_payload_sha256: str,
    claimed_at: datetime.datetime,
) -> object:
    """Consume one genuine reconciliation result into a policy-only claim."""

    if type(reconciliation) is not ReconciliationResult:
        raise ValueError("normal live admission requires trusted bound reconciliation")
    moment = _normal_live_reconciliation_moment(claimed_at)
    entry = _NORMAL_LIVE_RECONCILIATION_RESULTS.pop(id(reconciliation), None)
    if entry is None or entry[0] is not reconciliation:
        raise ValueError("normal live admission requires trusted bound reconciliation")
    binding = entry[1]
    if (
        reconciliation.matched is not True
        or reconciliation.issues
        or binding.intent_full_sha256
        != hashlib.sha256(intent.canonical_json_bytes()).hexdigest()
        or binding.order_payload_sha256 != order_payload_sha256
        or binding.client_order_id != intent.client_order_id
        or intent.client_order_id not in reconciliation.checked_client_order_ids
        or moment < binding.checked_at
        or moment - binding.checked_at
        > datetime.timedelta(seconds=_NORMAL_LIVE_RECONCILIATION_MAX_AGE_SECONDS)
    ):
        raise ValueError("normal live admission reconciliation is not bound to the exact order")
    claim = object()
    _NORMAL_LIVE_RECONCILIATION_CLAIMS[id(claim)] = (binding, claim)
    return claim


def _revalidate_normal_live_submit_reconciliation(
    claim: object,
    *,
    intent: AuthorizedNormalTradeIntent,
    order_payload_sha256: str,
) -> None:
    """Require the last owned read snapshot to remain within its 30-second lease."""

    entry = _NORMAL_LIVE_RECONCILIATION_CLAIMS.get(id(claim))
    if entry is None or entry[1] is not claim:
        raise ValueError("normal live admission reconciliation claim is unavailable")
    binding = entry[0]
    moment = _normal_live_reconciliation_moment(_normal_live_reconciliation_clock())
    if (
        binding.intent_full_sha256
        != hashlib.sha256(intent.canonical_json_bytes()).hexdigest()
        or binding.order_payload_sha256 != order_payload_sha256
        or binding.client_order_id != intent.client_order_id
        or moment < binding.checked_at
        or moment - binding.checked_at
        > datetime.timedelta(seconds=_NORMAL_LIVE_RECONCILIATION_MAX_AGE_SECONDS)
    ):
        raise ValueError("normal live admission reconciliation is not current")


def _refresh_normal_live_submit_reconciliation(
    claim: object,
    *,
    intent: AuthorizedNormalTradeIntent,
    order_payload: Mapping[str, object],
) -> tuple[dict[str, object], tuple[dict[str, object], ...], dict[str, object] | None]:
    """Take a new owned complete snapshot before the one irrevocable commit.

    This re-runs account, positions, open-order, and exact-client-order reads;
    therefore no final authority phase can rely on caller-controlled broker
    data or a snapshot older than the reconciliation lease.
    """

    entry = _NORMAL_LIVE_RECONCILIATION_CLAIMS.get(id(claim))
    if entry is None or entry[1] is not claim:
        raise ValueError("normal live admission reconciliation claim is unavailable")
    binding = entry[0]
    digest = _normal_live_reconciliation_payload_sha256(order_payload)
    if (
        binding.intent_full_sha256
        != hashlib.sha256(intent.canonical_json_bytes()).hexdigest()
        or binding.order_payload_sha256 != digest
        or binding.client_order_id != intent.client_order_id
    ):
        raise ValueError("normal live admission reconciliation is not bound to the exact order")
    account, positions, open_orders, existing, checked_at = _owned_normal_live_broker_read(
        binding.broker_read_adapter,
        client_order_id=intent.client_order_id,
    )
    expected_open_client_order_ids = (
        {intent.client_order_id} if existing is not None else set()
    )
    baseline = reconcile_live_state(
        expected_positions={},
        broker_positions=positions,
        expected_open_client_order_ids=expected_open_client_order_ids,
        broker_open_orders=open_orders,
    )
    if baseline.issues:
        raise ValueError(
            "normal live admission reconciliation snapshot is not clean: "
            + "; ".join(baseline.issues)
        )
    if existing is not None:
        from tradingagents.brokers.alpaca import compare_alpaca_order_to_intent

        issues = compare_alpaca_order_to_intent(existing, dict(order_payload))
        if issues:
            raise ValueError(
                "normal live admission reconciliation lookup does not match intent"
            )
    _NORMAL_LIVE_RECONCILIATION_CLAIMS[id(claim)] = (
        _NormalLiveReconciliationBinding(
            intent_full_sha256=binding.intent_full_sha256,
            order_payload_sha256=binding.order_payload_sha256,
            client_order_id=binding.client_order_id,
            checked_at=checked_at,
            broker_read_adapter=binding.broker_read_adapter,
        ),
        claim,
    )
    return account, positions, existing


def _release_normal_live_submit_reconciliation(claim: object) -> None:
    """Discard the one-use reconciliation claim after terminal handling."""

    _NORMAL_LIVE_RECONCILIATION_CLAIMS.pop(id(claim), None)


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
    from tradingagents.brokers.alpaca import compare_alpaca_order_to_intent

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
