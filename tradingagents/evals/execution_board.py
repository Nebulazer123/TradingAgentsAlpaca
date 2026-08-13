"""BOARD review for intraday execution quality and next-hour discipline."""

from __future__ import annotations

import datetime
import json
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from tradingagents.policy.decision_authority import (
    AUTHORITY_RECORD_FIELDS,
    bounded_exit_authority_record,
    resolve_exit_authority,
)

UTC = datetime.timezone.utc

CHASING_TERMS = ("green spike", "do not chase", "breakout chase", "after the move")
DIP_TERMS = ("controlled dip", "buy-the-dip", "pullback", "support", "reclaim")
LOSS_TERMS = ("loss", "breached loss", "drawdown")
PROFIT_TERMS = ("sell the spike", "profit", "profit-take", "take profit")
UNSAFE_STATUSES = {"rejected", "canceled", "cancelled", "expired", "failed"}


def _now_iso() -> str:
    return datetime.datetime.now(tz=UTC).isoformat(timespec="seconds")


def _as_decimal(value: Any, default: str = "0") -> Decimal:
    try:
        return Decimal(str(value if value not in {None, ""} else default))
    except (InvalidOperation, ValueError):
        return Decimal(default)


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _parse_generated_at(packet: Mapping[str, Any]) -> datetime.datetime:
    raw = str(packet.get("generated_at") or packet.get("started_at") or "")
    if raw:
        try:
            parsed = datetime.datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=UTC)
            return parsed.astimezone(UTC)
        except ValueError:
            pass
    return datetime.datetime.min.replace(tzinfo=UTC)


def load_hourly_packets(
    hourly_dir: str | Path = "results/hourly_supervisor",
    *,
    limit: int = 24,
) -> list[dict[str, Any]]:
    path = Path(hourly_dir)
    if not path.exists():
        return []
    packets: list[dict[str, Any]] = []
    for packet_path in path.glob("hourly-supervisor-*.json"):
        if packet_path.name == "latest.json" or packet_path.name.endswith(".compact.json"):
            continue
        packet = _read_json(packet_path)
        if packet is None:
            continue
        packet["_source_path"] = str(packet_path)
        packets.append(packet)
    packets.sort(key=_parse_generated_at)
    return packets[-limit:]


def _action_side(action: Mapping[str, Any]) -> str:
    side = str(action.get("side") or "").lower()
    if side:
        return side
    name = str(action.get("action") or "").lower()
    if name in {"close", "reduce", "sell"}:
        return "sell"
    if name == "buy":
        return "buy"
    if name in {"hold", "hold_cash"}:
        return "hold"
    return name


def _is_order_action(action: Mapping[str, Any]) -> bool:
    return _action_side(action) in {"buy", "sell"}


def _submitted_action_indexes(
    actions: Sequence[Mapping[str, Any]],
    submitted: Sequence[Mapping[str, Any]],
) -> set[int]:
    safe_order_indexes = {
        index
        for index, order in enumerate(submitted)
        if str(order.get("status") or "submitted").lower() not in UNSAFE_STATUSES
    }
    matched_actions: set[int] = set()

    for action_index, action in enumerate(actions):
        idempotency_key = str(action.get("idempotency_key") or "").strip()
        if not idempotency_key:
            continue
        for order_index in list(safe_order_indexes):
            client_order_id = str(submitted[order_index].get("client_order_id") or "").strip()
            if client_order_id == idempotency_key:
                matched_actions.add(action_index)
                safe_order_indexes.remove(order_index)
                break

    for order_index in list(safe_order_indexes):
        order = submitted[order_index]
        order_symbol = str(order.get("symbol") or "").upper()
        order_side = str(order.get("side") or "").lower()
        order_account = str(order.get("account") or "").lower()
        client_order_id = str(order.get("client_order_id") or "").lower()
        candidates = []
        for action_index, action in enumerate(actions):
            if action_index in matched_actions or action.get("idempotency_key"):
                continue
            if str(action.get("symbol") or "").upper() != order_symbol:
                continue
            if _action_side(action) != order_side:
                continue
            action_account = _action_account(action)
            if order_account and order_account != action_account:
                continue
            if client_order_id.startswith("ta-tiny-") and action_account != "live":
                continue
            if client_order_id.startswith("ta-hourly-") and action_account != "paper":
                continue
            candidates.append(action_index)
        if len(candidates) == 1:
            matched_actions.add(candidates[0])
            safe_order_indexes.remove(order_index)

    return matched_actions


def _action_account(action: Mapping[str, Any]) -> str:
    return str(action.get("account") or "live").lower()


def _action_reason(action: Mapping[str, Any]) -> str:
    return str(action.get("reason") or "")


def _contains_any(text: str, terms: Sequence[str]) -> bool:
    lowered = text.lower()
    return any(term in lowered for term in terms)


def _packet_live_unrealized(packet: Mapping[str, Any]) -> Decimal:
    portfolio = packet.get("portfolio") or {}
    if not isinstance(portfolio, Mapping):
        return Decimal("0")
    live = portfolio.get("live") or {}
    if not isinstance(live, Mapping):
        return Decimal("0")
    return _as_decimal(live.get("unrealized_pl"))


def _packet_key(packet: Mapping[str, Any]) -> str:
    return str(packet.get("_source_path") or packet.get("generated_at") or "unknown")


def _normalized_packet_ref(path_value: Any) -> str:
    text = str(path_value or "").strip()
    if text.startswith("local://"):
        text = text.removeprefix("local://")
    text = text.replace("/", "\\")
    try:
        candidate = Path(text)
        if candidate.is_absolute():
            text = str(candidate)
    except Exception:
        pass
    return text.lower()


def _latest_json_or_compact(directory: str | Path) -> tuple[Path, dict[str, Any]] | None:
    path = Path(directory)
    if not path.exists():
        return None
    for name in ("latest-compact.json", "latest.json"):
        candidate = path / name
        data = _read_json(candidate)
        if data is not None:
            return candidate, data
    candidates = sorted(path.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True)
    for candidate in candidates:
        data = _read_json(candidate)
        if data is not None:
            return candidate, data
    return None


def _loss_review_evidence_payload(packet: Mapping[str, Any]) -> Mapping[str, Any]:
    payload = packet.get("payload")
    if isinstance(payload, Mapping):
        return payload
    return packet


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value] if value.strip() else []
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return []
    return [str(item) for item in value if str(item).strip()]


def _latest_loss_review_evidence_summary(
    loss_review_evidence_dir: str | Path | None,
    packets: Sequence[Mapping[str, Any]],
) -> dict[str, Any] | None:
    if loss_review_evidence_dir is None:
        return None
    latest = _latest_json_or_compact(loss_review_evidence_dir)
    if latest is None:
        return None
    evidence_path, packet = latest
    payload = _loss_review_evidence_payload(packet)
    hourly_packet_path = str(payload.get("hourly_packet_path") or "")
    if not hourly_packet_path:
        return None
    remaining_blockers = _string_list(payload.get("remaining_blockers"))
    resolved_blockers = _string_list(payload.get("resolved_blockers_by_refresh"))
    advisory_summary = payload.get("advisory_summary")
    if not isinstance(advisory_summary, Mapping):
        advisory_summary = payload.get("advisory_analysis")
    if not isinstance(advisory_summary, Mapping):
        advisory_summary = {}
    loss_exit_candidate = advisory_summary.get("loss_exit_candidate")
    if not isinstance(loss_exit_candidate, Mapping):
        loss_exit_candidate = {}
    supervisor_review_allowed = payload.get("review_allowed")
    review_allowed_after_refresh = advisory_summary.get("review_allowed_after_refresh")
    source_bound, source_binding, supervisor_review = _source_binding(
        payload=payload,
        packets=packets,
        hourly_packet_path=hourly_packet_path,
    )
    authority = resolve_exit_authority(
        supervisor_review=supervisor_review,
        advisory_analysis=advisory_summary,
    )
    summary = {
        "evidence_path": str(evidence_path),
        "raw_packet_path": str(packet.get("raw_packet_path") or evidence_path),
        "hourly_packet_path": hourly_packet_path,
        "matches_review_window": source_bound,
        "source_binding": source_binding,
        "symbol": str(payload.get("symbol") or "").upper(),
        "review_allowed": authority.allowed if source_bound else False,
        "next_action": payload.get("next_action"),
        "remaining_blocker_count": len(remaining_blockers),
        "remaining_blockers": remaining_blockers[:8],
        "resolved_blocker_count": len(resolved_blockers),
        "resolved_blockers_by_refresh": resolved_blockers[:8],
    }
    if isinstance(review_allowed_after_refresh, bool):
        summary["supervisor_review_allowed"] = supervisor_review_allowed
        summary["review_allowed_after_refresh"] = review_allowed_after_refresh
    if loss_exit_candidate:
        summary["loss_exit_candidate"] = dict(loss_exit_candidate)
    return summary


def _loss_exit_review_for_symbol(packet: Mapping[str, Any], symbol: str) -> Mapping[str, Any] | None:
    evidence = packet.get("evidence")
    if not isinstance(evidence, Mapping):
        return None
    review = evidence.get("loss_exit_review")
    if not isinstance(review, Mapping):
        return None
    review_symbol = str(review.get("symbol") or "").upper()
    if review_symbol and review_symbol != symbol.upper():
        return None
    return review


def _source_binding(
    *,
    payload: Mapping[str, Any],
    packets: Sequence[Mapping[str, Any]],
    hourly_packet_path: str,
) -> tuple[bool, dict[str, Any], Mapping[str, Any]]:
    compact_record = payload.get("supervisor_review_authority")
    if not isinstance(compact_record, Mapping):
        return False, {"matched": False, "issue": "missing compact authority record"}, {}
    current_packet = next(
        (
            packet
            for packet in packets
            if _normalized_packet_ref(_packet_key(packet))
            == _normalized_packet_ref(hourly_packet_path)
        ),
        None,
    )
    if current_packet is None:
        return False, {"matched": False, "issue": "hourly packet is missing or stale"}, {}
    current_review = _loss_exit_review_for_symbol(
        current_packet,
        str(payload.get("symbol") or "").upper(),
    )
    if current_review is None:
        return False, {"matched": False, "issue": "current hourly loss_exit_review is missing or mixed-symbol"}, {}
    current_record = bounded_exit_authority_record(current_review)
    missing = [field for field in AUTHORITY_RECORD_FIELDS if field not in compact_record]
    if missing:
        return False, {
            "matched": False,
            "issue": "compact authority record is missing fields: " + ", ".join(missing),
        }, current_record
    if str(payload.get("symbol") or "").upper() != current_record["symbol"]:
        return False, {"matched": False, "issue": "payload symbol does not match current hourly review"}, current_record
    mismatches = [
        field
        for field in AUTHORITY_RECORD_FIELDS
        if compact_record.get(field) != current_record[field]
    ]
    if mismatches:
        return False, {
            "matched": False,
            "issue": "compact authority record does not match current hourly review: "
            + ", ".join(mismatches),
        }, current_record
    return True, {"matched": True, "issue": None}, current_review


def _summarize_roles(
    *,
    violations: list[dict[str, Any]],
    warnings: list[dict[str, Any]],
    metrics: Mapping[str, Any],
    new_buy_state: str = "allowed",
) -> list[dict[str, str]]:
    violation_types = {item.get("type") for item in violations}
    warning_types = {item.get("type") for item in warnings}
    roles: list[dict[str, str]] = []
    if new_buy_state == "paused":
        risk_view = "Pause new buys until the next clean dip setup and clean packet streak."
    elif new_buy_state == "probation_allowed":
        risk_view = "Earlier mistakes stay on watch, but new buys can resume only for clean controlled-dip/support setups."
    elif "loss_review_evidence_pending" in warning_types:
        risk_view = (
            "Loss-review evidence is attached but still pending final approval; "
            "keep HOLD/default cash posture until BOARD and normal live gates agree."
        )
    elif violation_types or "loss_exit" in warning_types:
        risk_view = "Risk posture needs caution; keep cash default when evidence is thin."
    else:
        risk_view = "Risk posture can continue, but keep cash default when evidence is thin."
    roles.append(
        {
            "role": "Risk Chair",
            "view": risk_view,
        }
    )
    roles.append(
        {
            "role": "Execution Auditor",
            "view": (
                "Inspect order status and reconciliation before any new live action."
                if "unsafe_order_status" in violation_types
                else "No rejected/canceled/expired order pattern found in reviewed packets."
            ),
        }
    )
    roles.append(
        {
            "role": "Strategy Researcher",
            "view": (
                "Reject chase buys; require controlled dip, support, or pullback evidence."
                if {"chase_buy", "buy_without_dip_evidence"} & violation_types
                else "Entry discipline is aligned with buy-the-dip rules in reviewed packets."
            ),
        }
    )
    roles.append(
        {
            "role": "Paper Tournament Scout",
            "view": (
                "Let paper sleeves keep exploring alternatives; live should not copy a strategy until gates and recent evidence agree."
            ),
        }
    )
    roles.append(
        {
            "role": "Operator Translator",
            "view": (
                f"Reviewed {metrics['packet_count']} hourly packet(s), "
                f"{metrics['submitted_order_count']} submitted order(s), "
                f"{len(violations)} hard issue(s), and {len(warnings)} warning(s)."
            ),
        }
    )
    return roles


def build_execution_board_review(
    hourly_dir: str | Path = "results/hourly_supervisor",
    *,
    max_packets: int = 24,
    clean_streak_required: int = 2,
    loss_review_evidence_dir: str | Path | None = "results/loss_review_evidence",
    now: datetime.datetime | None = None,
) -> dict[str, Any]:
    """Build a compact, analysis-only BOARD review from recent hourly packets."""

    packets = load_hourly_packets(hourly_dir, limit=max_packets)
    loss_review_evidence = _latest_loss_review_evidence_summary(loss_review_evidence_dir, packets)
    generated_at = (now or datetime.datetime.now(tz=UTC)).isoformat(timespec="seconds")
    violations: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    live_buy_count = 0
    live_sell_count = 0
    paper_buy_count = 0
    submitted_order_count = 0
    profit_sell_count = 0
    loss_exit_count = 0
    negative_live_pl_packets = 0
    packet_reviews: list[dict[str, Any]] = []

    for packet in packets:
        packet_key = _packet_key(packet)
        violation_count_before = len(violations)
        warning_count_before = len(warnings)
        actions = [
            action
            for action in (packet.get("actions") or [])
            if isinstance(action, Mapping) and _is_order_action(action)
        ]
        submitted = [
            order for order in (packet.get("submitted") or []) if isinstance(order, Mapping)
        ]
        submitted_order_count += len(submitted)

        live_buys = [
            action for action in actions if _action_side(action) == "buy" and _action_account(action) == "live"
        ]
        live_sells = [
            action for action in actions if _action_side(action) == "sell" and _action_account(action) == "live"
        ]
        paper_buys = [
            action for action in actions if _action_side(action) == "buy" and _action_account(action) == "paper"
        ]
        submitted_action_indexes = _submitted_action_indexes(actions, submitted)
        submitted_action_ids = {
            id(action) for index, action in enumerate(actions) if index in submitted_action_indexes
        }
        live_buy_count += sum(id(action) in submitted_action_ids for action in live_buys)
        live_sell_count += sum(id(action) in submitted_action_ids for action in live_sells)
        paper_buy_count += sum(id(action) in submitted_action_ids for action in paper_buys)

        if live_buys and live_sells:
            violations.append(
                {
                    "type": "paired_live_sell_and_buy",
                    "packet": packet_key,
                    "message": "A live sell and live buy were planned in the same hourly decision; sells and buys should be independent.",
                }
            )

        for action in [*live_buys, *paper_buys]:
            reason = _action_reason(action)
            symbol = str(action.get("symbol") or "").upper()
            if _contains_any(reason, CHASING_TERMS):
                violations.append(
                    {
                        "type": "chase_buy",
                        "packet": packet_key,
                        "symbol": symbol,
                        "message": "Buy action looks like a green-spike/chase entry.",
                    }
                )
            elif _action_account(action) == "live" and not _contains_any(reason, DIP_TERMS):
                violations.append(
                    {
                        "type": "buy_without_dip_evidence",
                        "packet": packet_key,
                        "symbol": symbol,
                        "message": "Live buy does not name controlled dip, support, pullback, or buy-the-dip evidence.",
                    }
                )

        for action in live_sells:
            reason = _action_reason(action)
            symbol = str(action.get("symbol") or "").upper()
            submitted_match = id(action) in submitted_action_ids
            if submitted_match and _contains_any(reason, PROFIT_TERMS):
                profit_sell_count += 1
            if _contains_any(reason, LOSS_TERMS):
                loss_review = _loss_exit_review_for_symbol(packet, symbol)
                if loss_review is None:
                    violations.append(
                        {
                            "type": "loss_exit_without_approval_evidence",
                            "packet": packet_key,
                            "symbol": symbol,
                            "message": "Live loss sell lacks structured evidence.loss_exit_review approval.",
                        }
                    )
                elif loss_review.get("allowed") is not True:
                    violations.append(
                        {
                            "type": "loss_exit_disallowed_by_review",
                            "packet": packet_key,
                            "symbol": symbol,
                            "message": "Live loss sell has loss_exit_review evidence but allowed is not true.",
                        }
                    )
                if submitted_match:
                    loss_exit_count += 1
                    warnings.append(
                        {
                            "type": "loss_exit",
                            "packet": packet_key,
                            "symbol": symbol,
                            "message": "A loss exit occurred; freed cash should wait for a separate clean entry.",
                        }
                    )

        for order in submitted:
            status = str(order.get("status") or "submitted").lower()
            if status in UNSAFE_STATUSES:
                violations.append(
                    {
                        "type": "unsafe_order_status",
                        "packet": packet_key,
                        "symbol": str(order.get("symbol") or "").upper(),
                        "status": status,
                        "message": "Submitted order had a rejected/canceled/expired-style status.",
                    }
                )

        if _packet_live_unrealized(packet) < Decimal("0"):
            negative_live_pl_packets += 1

        packet_review = {
            "packet": packet_key,
            "generated_at": _parse_generated_at(packet).isoformat(timespec="seconds"),
            "decision": packet.get("decision"),
            "violation_count": len(violations) - violation_count_before,
            "warning_count": len(warnings) - warning_count_before,
            "submitted_order_count": len(submitted),
        }
        if (
            loss_review_evidence
            and loss_review_evidence.get("matches_review_window") is True
            and _normalized_packet_ref(loss_review_evidence.get("hourly_packet_path"))
            == _normalized_packet_ref(packet_key)
        ):
            packet_review["loss_review_evidence_remaining_blocker_count"] = (
                loss_review_evidence.get("remaining_blocker_count")
            )
            packet_review["loss_review_evidence_review_allowed"] = (
                loss_review_evidence.get("review_allowed")
            )
        packet_reviews.append(packet_review)

    if negative_live_pl_packets:
        warnings.append(
            {
                "type": "negative_live_unrealized_pl",
                "packet_count": negative_live_pl_packets,
                "message": "Live unrealized P/L was negative in one or more reviewed packets.",
            }
        )
    loss_review_evidence_pending = bool(
        loss_review_evidence
        and (
            loss_review_evidence.get("review_allowed") is not True
            or int(loss_review_evidence.get("remaining_blocker_count") or 0) > 0
        )
    )
    if loss_review_evidence_pending:
        pending_message = (
            "Refreshed loss-review evidence is attached, but BOARD still lacks "
            "enough thesis-break confidence to approve a loss exit."
        )
        remaining_blockers = list(loss_review_evidence.get("remaining_blockers") or [])
        candidate = loss_review_evidence.get("loss_exit_candidate")
        if not isinstance(candidate, Mapping):
            candidate = {}
        candidate_reason = str(candidate.get("allowed_exit_reason_candidate") or "").strip()
        candidate_confidence = str(candidate.get("confidence") or "").strip()
        if candidate_reason and remaining_blockers == [
            "market session is not tradeable for a live loss exit"
        ]:
            pending_message = (
                "Refreshed loss-review evidence has a BOARD-only "
                f"{candidate_reason} candidate"
                + (f" at confidence {candidate_confidence}" if candidate_confidence else "")
                + "; live exit remains blocked until a tradeable market session "
                "and the normal live gates pass."
            )
        elif candidate_reason:
            blockers_preview = "; ".join(str(item) for item in remaining_blockers[:3])
            pending_message = (
                "Refreshed loss-review evidence has a BOARD-only "
                f"{candidate_reason} candidate, but remaining blockers still need "
                f"review: {blockers_preview}."
            )
        warnings.append(
            {
                "type": "loss_review_evidence_pending",
                "packet": loss_review_evidence.get("hourly_packet_path"),
                "symbol": loss_review_evidence.get("symbol"),
                "message": pending_message,
            }
        )

    latest_violation_index = next(
        (
            index
            for index in range(len(packet_reviews) - 1, -1, -1)
            if packet_reviews[index]["violation_count"] > 0
        ),
        None,
    )
    clean_packets_since_last_violation = (
        len(packet_reviews) - latest_violation_index - 1
        if latest_violation_index is not None
        else len(packet_reviews)
    )
    latest_violation_packet = (
        packet_reviews[latest_violation_index]["packet"]
        if latest_violation_index is not None
        else None
    )
    if violations and clean_packets_since_last_violation < clean_streak_required:
        recommendation = "pause_new_buys_and_review"
        new_buy_state = "paused"
    elif violations:
        recommendation = "continue_with_guardrails_after_clean_streak"
        new_buy_state = "probation_allowed"
    elif loss_exit_count or negative_live_pl_packets or loss_review_evidence_pending:
        recommendation = "review_underperformers_before_new_buys"
        new_buy_state = "caution"
    elif submitted_order_count:
        recommendation = "continue_with_guardrails"
        new_buy_state = "allowed"
    else:
        recommendation = "no_action_needed"
        new_buy_state = "allowed"

    metrics = {
        "packet_count": len(packets),
        "submitted_order_count": submitted_order_count,
        "live_buy_count": live_buy_count,
        "live_sell_count": live_sell_count,
        "paper_buy_count": paper_buy_count,
        "profit_sell_count": profit_sell_count,
        "loss_exit_count": loss_exit_count,
        "negative_live_pl_packets": negative_live_pl_packets,
        "clean_packets_since_last_violation": clean_packets_since_last_violation,
    }
    new_buy_policy = {
        "state": new_buy_state,
        "clean_packets_since_last_violation": clean_packets_since_last_violation,
        "required_clean_packets": clean_streak_required,
        "latest_violation_packet": latest_violation_packet,
        "plain_english": (
            "New buys are paused because the latest BOARD issue is still too recent."
            if new_buy_state == "paused"
            else "Earlier BOARD issues remain on the lesson list, but newer packets are clean enough to allow only controlled dip/support buys."
            if new_buy_state == "probation_allowed"
            else (
                "Loss-review evidence is still pending; new buys remain limited to separate controlled dip/support setups."
                if loss_review_evidence_pending
                else "New buys are allowed only inside the usual controlled dip/support guardrails."
            )
        ),
    }

    review = {
        "kind": "execution_board_review",
        "schema_version": 1,
        "generated_at": generated_at,
        "analysis_only": True,
        "can_submit_orders": False,
        "review_window": {
            "hourly_dir": str(hourly_dir),
            "max_packets": max_packets,
            "oldest_packet": packets[0].get("_source_path") if packets else None,
            "newest_packet": packets[-1].get("_source_path") if packets else None,
        },
        "metrics": metrics,
        "violations": violations,
        "warnings": warnings,
        "packet_reviews": packet_reviews,
        "board_roles": _summarize_roles(
            violations=violations,
            warnings=warnings,
            metrics=metrics,
            new_buy_state=new_buy_state,
        ),
        "recommendation": recommendation,
        "new_buy_policy": new_buy_policy,
        "next_hour_policy": {
            "sell_side": "Sells are independent: take profit at threshold; loss exits free cash and do not force a same-run replacement buy.",
            "buy_side": "New buys require a separate controlled-dip/support setup with no green-spike chase language.",
            "review_trigger": "Any chase buy, paired live sell+buy, rejected order, loss exit, or negative live P/L should trigger BOARD review before expanding live risk.",
            "paper_side": "Paper sleeves keep exploring strategy variants and feed promotion evidence; paper results do not bypass live gates.",
        },
    }
    if loss_review_evidence is not None:
        review["loss_review_evidence"] = loss_review_evidence
    return review


def write_execution_board_review(
    review: dict[str, Any],
    output_dir: str | Path,
) -> tuple[Path, Path]:
    path = Path(output_dir)
    path.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.datetime.now(tz=UTC).strftime("%Y%m%d-%H%M%S")
    json_path = path / f"execution-board-review-{timestamp}.json"
    md_path = path / f"execution-board-review-{timestamp}.md"
    json_path.write_text(json.dumps(review, indent=2, sort_keys=True), encoding="utf-8")
    md_lines = [
        "# TradingAgents BOARD Execution Review",
        "",
        f"- Generated: {review['generated_at']}",
        f"- Recommendation: {review['recommendation']}",
        f"- New-buy state: {(review.get('new_buy_policy') or {}).get('state', 'unknown')}",
        f"- Packets reviewed: {review['metrics']['packet_count']}",
        f"- Submitted orders: {review['metrics']['submitted_order_count']}",
        f"- Hard issues: {len(review['violations'])}",
        f"- Warnings: {len(review['warnings'])}",
        "",
        "## BOARD Views",
        "",
    ]
    for role in review["board_roles"]:
        md_lines.append(f"- {role['role']}: {role['view']}")
    md_lines.extend(["", "## Hard Issues", ""])
    if review["violations"]:
        md_lines.extend(f"- {item['type']}: {item['message']}" for item in review["violations"])
    else:
        md_lines.append("- none")
    policy = review.get("new_buy_policy") or {}
    if policy:
        md_lines.extend(
            [
                "",
                "## New-Buy Policy",
                "",
                f"- State: {policy.get('state', 'unknown')}",
                f"- Clean packets since latest hard issue: {policy.get('clean_packets_since_last_violation', 0)} / {policy.get('required_clean_packets', 0)}",
                f"- Plain English: {policy.get('plain_english', '')}",
            ]
        )
    loss_review_evidence = review.get("loss_review_evidence") or {}
    if loss_review_evidence:
        md_lines.extend(
            [
                "",
                "## Loss-Review Evidence",
                "",
                f"- Symbol: {loss_review_evidence.get('symbol', '')}",
                f"- Review allowed: {loss_review_evidence.get('review_allowed')}",
                f"- Remaining blockers: {loss_review_evidence.get('remaining_blocker_count', 0)}",
                f"- Resolved blockers by refresh: {loss_review_evidence.get('resolved_blocker_count', 0)}",
                f"- Next action: {loss_review_evidence.get('next_action', '')}",
            ]
        )
    md_lines.extend(["", "## Next Hour Policy", ""])
    for key, value in review["next_hour_policy"].items():
        md_lines.append(f"- {key}: {value}")
    md_path.write_text("\n".join(md_lines) + "\n", encoding="utf-8")
    (path / "latest.json").write_text(
        json.dumps(review, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    (path / "latest.md").write_text(md_path.read_text(encoding="utf-8"), encoding="utf-8")
    compact = compact_execution_board_review(review, raw_packet_path=json_path, markdown_path=md_path)
    compact_text = json.dumps(compact, indent=2, sort_keys=True)
    compact_path = json_path.with_name(f"{json_path.stem}.compact.json")
    compact_path.write_text(compact_text, encoding="utf-8")
    (path / "latest-compact.json").write_text(compact_text, encoding="utf-8")
    return json_path, md_path


def _compact_issue(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        return {"message": str(item)[:240]}
    return {
        key: item.get(key)
        for key in ("type", "message", "packet", "symbol", "side", "status")
        if item.get(key) is not None
    }


def _compact_packet_review(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        return {"packet": str(item)[:240]}
    return {
        key: item.get(key)
        for key in (
            "packet",
            "generated_at",
            "decision",
            "submitted_order_count",
            "violation_count",
            "warning_count",
            "loss_review_evidence_remaining_blocker_count",
            "loss_review_evidence_review_allowed",
        )
        if item.get(key) is not None
    }


def compact_execution_board_review(
    review: dict[str, Any],
    *,
    raw_packet_path: str | Path,
    markdown_path: str | Path | None = None,
) -> dict[str, Any]:
    """Return a compact BOARD review summary with a raw-packet drilldown pointer."""
    violations = review.get("violations") or []
    warnings = review.get("warnings") or []
    packet_reviews = review.get("packet_reviews") or []
    compact: dict[str, Any] = {
        "schema": "compact_execution_board_review_v1",
        "kind": review.get("kind", "execution_board_review"),
        "generated_at": review.get("generated_at"),
        "analysis_only": review.get("analysis_only") is True,
        "can_submit_orders": False,
        "execution_authority": "none",
        "recommendation": review.get("recommendation"),
        "new_buy_policy": review.get("new_buy_policy") or {},
        "loss_review_evidence": review.get("loss_review_evidence") or {},
        "next_hour_policy": review.get("next_hour_policy") or {},
        "metrics": review.get("metrics") or {},
        "violation_count": len(violations),
        "warning_count": len(warnings),
        "violations": [_compact_issue(item) for item in violations[:10]],
        "warnings": [_compact_issue(item) for item in warnings[:10]],
        "packet_reviews": [_compact_packet_review(item) for item in packet_reviews[-5:]],
        "raw_packet_path": str(raw_packet_path),
    }
    if markdown_path is not None:
        compact["markdown_path"] = str(markdown_path)
    return compact
