"""Analysis-only evidence refresh for hourly loss-review holds."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from tradingagents.dataflows._official_common import evidence_packet, request_hash
from tradingagents.policy.decision_authority import (
    ExitAuthorityVerdict,
    bounded_exit_authority_record,
    resolve_exit_authority,
)
from tradingagents.research.provider_orchestrator import TickerProviderResearchResult
from tradingagents.schemas.research import SourceEvidencePacket

DEFAULT_LOSS_REVIEW_EVIDENCE_NEEDS: tuple[str, ...] = (
    "quote_price_context",
    "market_news",
    "fundamentals_profile",
    "earnings_transcripts",
)

LOSS_REVIEW_FORBIDDEN_EFFECTS: tuple[str, ...] = (
    "create_trade_intent",
    "size_position",
    "submit_order",
    "promote_sleeve",
    "waive_live_gate",
    "mark_loss_exit_allowed",
)


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _candidate_hourly_paths(path: Path) -> list[Path]:
    if path.is_file():
        return [path] if _is_raw_hourly_packet_path(path) else []
    return sorted(
        (
            packet_path
            for packet_path in path.glob("hourly-supervisor-*.json")
            if _is_raw_hourly_packet_path(packet_path)
        ),
        reverse=True,
    )


def _is_raw_hourly_packet_path(path: Path) -> bool:
    if not path.is_file() or path.suffix.lower() != ".json":
        return False
    return not path.name.lower().endswith(".compact.json")


def _parse_timestamp(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _trading_days_between(start: datetime | None, end: datetime | None) -> int | None:
    if start is None or end is None:
        return None
    start_date = start.astimezone(UTC).date()
    end_date = end.astimezone(UTC).date()
    if end_date < start_date:
        return None
    current = start_date
    days = 0
    while current < end_date:
        current += timedelta(days=1)
        if current.weekday() < 5:
            days += 1
    return days


def _loss_review_from_packet(packet: Mapping[str, Any]) -> Mapping[str, Any] | None:
    evidence = packet.get("evidence")
    if not isinstance(evidence, Mapping):
        return None
    review = evidence.get("loss_exit_review")
    return review if isinstance(review, Mapping) else None


def _entry_context_from_packet(
    *,
    path: Path,
    packet: Mapping[str, Any],
    symbol: str,
    review_at: datetime | None,
) -> dict[str, Any] | None:
    actions = packet.get("actions")
    submitted = packet.get("submitted")
    if not isinstance(actions, Sequence) or isinstance(actions, (str, bytes, bytearray)):
        actions = []
    if not isinstance(submitted, Sequence) or isinstance(submitted, (str, bytes, bytearray)):
        submitted = []

    matching_actions = [
        action
        for action in actions
        if isinstance(action, Mapping)
        and str(action.get("symbol") or "").strip().upper() == symbol
        and str(action.get("side") or "").strip().lower() == "buy"
        and str(action.get("account") or "").strip().lower() == "live"
    ]
    matching_orders = [
        order
        for order in submitted
        if isinstance(order, Mapping)
        and str(order.get("symbol") or "").strip().upper() == symbol
        and str(order.get("side") or "").strip().lower() == "buy"
    ]
    if not matching_actions and not matching_orders:
        return None

    action = matching_actions[-1] if matching_actions else {}
    order = matching_orders[-1] if matching_orders else {}
    packet_generated_at = _parse_timestamp(packet.get("generated_at"))
    submitted_at = _parse_timestamp(order.get("submitted_at"))
    created_at = _parse_timestamp(order.get("created_at"))
    opened_at = submitted_at or created_at or packet_generated_at
    entry_reason = str(action.get("reason") or "").strip()
    return {
        "source": "local_hourly_supervisor_history",
        "packet_path": str(path),
        "packet_generated_at": packet.get("generated_at"),
        "symbol": symbol,
        "account": str(action.get("account") or "live"),
        "entry_reason": entry_reason or None,
        "notional": action.get("notional") or order.get("notional"),
        "limit_price": action.get("limit_price") or order.get("limit_price"),
        "client_order_id": order.get("client_order_id"),
        "submitted_at": order.get("submitted_at"),
        "order_status": order.get("status"),
        "holding_period_trading_days": _trading_days_between(opened_at, review_at),
        "is_submitted_order_context": bool(order),
        "is_action_context": bool(action),
    }


def find_prior_live_entry_context(
    hourly_packet_path: str | Path,
    *,
    symbol: str,
    review_at: datetime | None = None,
) -> dict[str, Any] | None:
    """Find the newest prior same-symbol live buy context from local hourly history."""
    path = Path(hourly_packet_path)
    root = path.parent if path.is_file() else path
    if not root.exists():
        return None
    current_path = path.resolve() if path.exists() else None
    for candidate in _candidate_hourly_paths(root):
        if current_path is not None and candidate.resolve() == current_path:
            continue
        try:
            packet = _load_json(candidate)
        except (OSError, json.JSONDecodeError):
            continue
        packet_at = _parse_timestamp(packet.get("generated_at"))
        if review_at is not None and packet_at is not None and packet_at >= review_at:
            continue
        context = _entry_context_from_packet(
            path=candidate,
            packet=packet,
            symbol=symbol,
            review_at=review_at,
        )
        if context is not None:
            return context
    return None


def find_latest_loss_review_packet(hourly_dir: str | Path) -> tuple[Path, dict[str, Any], Mapping[str, Any]]:
    """Return the newest hourly packet with structured loss-review evidence."""
    root = Path(hourly_dir)
    for path in _candidate_hourly_paths(root):
        try:
            packet = _load_json(path)
        except (OSError, json.JSONDecodeError):
            continue
        review = _loss_review_from_packet(packet)
        if review is not None:
            return path, packet, review
    raise FileNotFoundError(f"no hourly loss-review packet found under {root}")


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [str(item) for item in value if str(item).strip()]
    return []


def _float_value(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(str(value).replace("%", "").strip())
    except ValueError:
        return None


def _source_packet_ids(provider_result: TickerProviderResearchResult) -> list[str]:
    ids = [packet.packet_id for packet in provider_result.packets]
    if provider_result.summary_packet is not None:
        ids.append(provider_result.summary_packet.packet_id)
    return ids


def _coverage_by_need(provider_result: TickerProviderResearchResult) -> dict[str, int]:
    coverage: dict[str, int] = {}
    for packet in provider_result.packets:
        coverage[packet.evidence_type] = coverage.get(packet.evidence_type, 0) + 1
    return coverage


def _has_coverage(coverage_by_need: Mapping[str, int], *needs: str) -> bool:
    return any(int(coverage_by_need.get(need) or 0) > 0 for need in needs)


def _find_symbol_entry(items: Any, symbol: str) -> Mapping[str, Any] | None:
    if not isinstance(items, Sequence) or isinstance(items, (str, bytes, bytearray)):
        return None
    for item in items:
        if not isinstance(item, Mapping):
            continue
        if str(item.get("symbol") or "").strip().upper() == symbol:
            return item
    return None


def _provider_packet_refs(provider_result: TickerProviderResearchResult) -> list[dict[str, str]]:
    refs: list[dict[str, str]] = []
    for packet in provider_result.packets:
        refs.append(
            {
                "packet_id": packet.packet_id,
                "source_name": packet.source_name,
                "evidence_type": packet.evidence_type,
                "quality": packet.quality,
            }
        )
    if provider_result.summary_packet is not None:
        packet = provider_result.summary_packet
        refs.append(
            {
                "packet_id": packet.packet_id,
                "source_name": packet.source_name,
                "evidence_type": packet.evidence_type,
                "quality": packet.quality,
            }
        )
    return refs


def _infer_current_thesis_status(
    *,
    review: Mapping[str, Any],
    ranked_reason: str,
    position: Mapping[str, Any] | None,
    entry_context: Mapping[str, Any] | None,
    has_refreshed_evidence: bool,
) -> tuple[str, dict[str, Any]]:
    current_thesis_status = str(review.get("current_thesis_status") or "").strip()
    if current_thesis_status:
        return current_thesis_status, {
            "status": current_thesis_status,
            "drivers": ["supervisor provided current_thesis_status"],
            "approval_effect": "advisory_only_not_loss_exit_approval",
            "requires_board_decision": True,
        }

    drivers: list[str] = []
    ranked_reason_lower = ranked_reason.lower()
    if "falling-knife" in ranked_reason_lower or "sharp drop" in ranked_reason_lower:
        drivers.append("current candidate is flagged as falling-knife/sharp-drop watch")

    entry_reason_lower = str((entry_context or {}).get("entry_reason") or "").lower()
    if any(
        marker in entry_reason_lower
        for marker in ("momentum", "time-sensitive", "high-conviction")
    ):
        drivers.append("prior entry thesis was momentum or time-sensitive")

    current_price = _float_value(
        review.get("current_price") or (position or {}).get("current_price")
    )
    average_entry = _float_value(
        review.get("average_entry_price") or (position or {}).get("avg_entry_price")
    )
    if (
        current_price is not None
        and average_entry is not None
        and current_price < average_entry
    ):
        drivers.append("position is below average entry price")

    if "current candidate is flagged as falling-knife/sharp-drop watch" in drivers:
        return "thesis_under_pressure_falling_knife_watch", {
            "status": "thesis_under_pressure_falling_knife_watch",
            "drivers": drivers,
            "approval_effect": "advisory_only_not_loss_exit_approval",
            "requires_board_decision": True,
        }

    unresolved_status = (
        "unresolved_from_refreshed_evidence; BOARD must decide whether the original thesis is broken"
        if has_refreshed_evidence
        else "unresolved_no_refreshed_evidence"
    )
    return unresolved_status, {
        "status": unresolved_status,
        "drivers": drivers,
        "approval_effect": "advisory_only_not_loss_exit_approval",
        "requires_board_decision": True,
    }


def _loss_exit_confidence_tier(confidence: float) -> str:
    if confidence >= 0.75:
        return "medium"
    if confidence >= 0.55:
        return "low"
    return "none"


def _infer_loss_exit_candidate(
    *,
    thesis_status_evidence: Mapping[str, Any],
    ranked_reason: str,
    entry_context: Mapping[str, Any] | None,
    position: Mapping[str, Any] | None,
    review: Mapping[str, Any],
    has_market_context: bool,
    has_company_context: bool,
    source_refs: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Infer a BOARD-only loss-exit candidate without granting approval."""
    drivers: list[str] = []
    status = str(thesis_status_evidence.get("status") or "")
    status_drivers = _strings(thesis_status_evidence.get("drivers"))
    ranked_reason_lower = ranked_reason.lower()
    entry_reason_lower = str((entry_context or {}).get("entry_reason") or "").lower()

    if (
        status == "thesis_under_pressure_falling_knife_watch"
        or "falling-knife" in ranked_reason_lower
        or "sharp drop" in ranked_reason_lower
    ):
        drivers.append("current candidate is flagged as falling-knife/sharp-drop watch")
    if (
        "prior entry thesis was momentum or time-sensitive" in status_drivers
        or any(marker in entry_reason_lower for marker in ("momentum", "time-sensitive"))
    ):
        drivers.append("prior entry thesis was momentum or time-sensitive")

    current_price = _float_value(
        review.get("current_price") or (position or {}).get("current_price")
    )
    average_entry = _float_value(
        review.get("average_entry_price") or (position or {}).get("avg_entry_price")
    )
    if (
        "position is below average entry price" in status_drivers
        or (
            current_price is not None
            and average_entry is not None
            and current_price < average_entry
        )
    ):
        drivers.append("position is below average entry price")
    if has_market_context and has_company_context and source_refs:
        drivers.append("refreshed market and company evidence attached")
    if (entry_context or {}).get("holding_period_trading_days") is not None:
        drivers.append("holding period is available")

    has_required_driver_set = all(
        item in drivers
        for item in (
            "current candidate is flagged as falling-knife/sharp-drop watch",
            "prior entry thesis was momentum or time-sensitive",
            "position is below average entry price",
            "refreshed market and company evidence attached",
        )
    )
    if not has_required_driver_set:
        return {
            "allowed_exit_reason_candidate": None,
            "allowed_exit_reason_source": None,
            "confidence": "0.00",
            "confidence_tier": "none",
            "reason_summary": (
                "No BOARD loss-exit candidate: refreshed evidence does not yet "
                "prove a thesis break or superior capital reuse."
            ),
            "drivers": drivers,
            "approval_effect": "board_review_input_not_loss_exit_approval",
            "requires_board_decision": True,
            "requires_tradeable_session": True,
            "can_submit_orders": False,
        }

    confidence = 0.42
    confidence += 0.08  # thesis status under pressure
    confidence += 0.07  # falling-knife/sharp-drop evidence
    confidence += 0.05  # entry thesis was momentum/time-sensitive
    confidence += 0.05  # below average entry
    confidence += 0.05  # refreshed market evidence
    confidence += 0.05  # refreshed company/filing evidence
    confidence += (
        0.03
        if (entry_context or {}).get("holding_period_trading_days") is not None
        else 0
    )
    confidence = min(confidence, 0.78)
    return {
        "allowed_exit_reason_candidate": "thesis_invalidated",
        "allowed_exit_reason_source": "refreshed_loss_review_evidence",
        "confidence": f"{confidence:.2f}",
        "confidence_tier": _loss_exit_confidence_tier(confidence),
        "reason_summary": (
            "Prior momentum/time-sensitive thesis is under pressure while the "
            "current candidate is a falling-knife watch below average entry."
        ),
        "drivers": drivers,
        "approval_effect": "board_review_input_not_loss_exit_approval",
        "requires_board_decision": True,
        "requires_tradeable_session": True,
        "can_submit_orders": False,
    }


def _pre_registered_policy_candidate(
    review: Mapping[str, Any],
    authority: ExitAuthorityVerdict,
) -> dict[str, Any] | None:
    if authority.authority_source != "pre_registered_policy_rule":
        return None
    return {
        "allowed_exit_reason_candidate": review.get("allowed_exit_reason"),
        "allowed_exit_reason_source": review.get("allowed_exit_reason_source"),
        "confidence": None,
        "confidence_tier": "pre_registered_policy",
        "reason_summary": review.get("exit_policy_rationale"),
        "drivers": [authority.reason],
        "approval_effect": "preserves_pre_registered_policy_approval",
        "requires_board_decision": False,
        "requires_tradeable_session": True,
        "can_submit_orders": False,
    }


def _build_advisory_analysis(
    *,
    symbol: str,
    review: Mapping[str, Any],
    hourly_packet: Mapping[str, Any],
    provider_result: TickerProviderResearchResult,
    coverage_by_need: Mapping[str, int],
    entry_context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    portfolio = hourly_packet.get("portfolio")
    live = portfolio.get("live") if isinstance(portfolio, Mapping) else {}
    position = (
        _find_symbol_entry(live.get("positions"), symbol)
        if isinstance(live, Mapping)
        else None
    )
    ranked = hourly_packet.get("ranked_candidates")
    if not ranked and isinstance(portfolio, Mapping):
        ranked = portfolio.get("ranked_candidates")
    ranked_entry = _find_symbol_entry(ranked, symbol)
    source_refs = _provider_packet_refs(provider_result)
    route_summary = [
        {
            "evidence_need": str(attempt.get("evidence_need") or ""),
            "source_name": str(attempt.get("source_name") or ""),
            "status": str(attempt.get("status") or ""),
            "packet_id": str(attempt.get("packet_id") or ""),
            "blocked": bool(attempt.get("blocked")),
        }
        for attempt in provider_result.route_attempts
        if isinstance(attempt, Mapping)
    ]

    has_market_context = _has_coverage(
        coverage_by_need,
        "market_sentiment_watchlist",
        "market_news",
        "quote_price_context",
    )
    has_fundamental_context = _has_coverage(
        coverage_by_need,
        "fundamentals_profile",
        "submissions",
        "earnings_transcripts",
    )
    has_news_context = _has_coverage(coverage_by_need, "market_news", "news_rss")
    ranked_reason = str((ranked_entry or {}).get("reason") or "").strip()
    current_thesis_status, thesis_status_evidence = _infer_current_thesis_status(
        review=review,
        ranked_reason=ranked_reason,
        position=position,
        entry_context=entry_context,
        has_refreshed_evidence=bool(source_refs),
    )
    loss_exit_candidate = _infer_loss_exit_candidate(
        thesis_status_evidence=thesis_status_evidence,
        ranked_reason=ranked_reason,
        entry_context=entry_context,
        position=position,
        review=review,
        has_market_context=has_market_context,
        has_company_context=has_news_context or has_fundamental_context,
        source_refs=source_refs,
    )

    advisory_analysis = {
        "purpose": (
            "advisory context for BOARD/manual loss review; not a loss-exit approval"
        ),
        "symbol": symbol,
        "position_snapshot": {
            "qty": (position or {}).get("qty"),
            "market_value": (position or {}).get("market_value"),
            "current_price": review.get("current_price") or (position or {}).get("current_price"),
            "average_entry_price": review.get("average_entry_price")
            or (position or {}).get("avg_entry_price"),
            "unrealized_pl": review.get("unrealized_pl") or (position or {}).get("unrealized_pl"),
            "unrealized_pnl_percent": review.get("unrealized_pnl_percent")
            or (position or {}).get("unrealized_plpc"),
        },
        "entry_context": dict(entry_context or {}),
        "current_candidate_context": {
            "ranked_score": (ranked_entry or {}).get("score"),
            "day_change_pct": (ranked_entry or {}).get("day_change_pct"),
            "volume_ratio": (ranked_entry or {}).get("volume_ratio"),
            "reason": ranked_reason or None,
            "falling_knife_watch": "falling-knife" in ranked_reason.lower()
            or "sharp drop" in ranked_reason.lower(),
        },
        "market_context_attached": has_market_context,
        "company_context_attached": has_news_context or has_fundamental_context,
        "hold_vs_sell_frame": (
            "SELL is better only if BOARD can prove thesis break, invalidator, or superior capital reuse; otherwise HOLD remains the default because this packet cannot approve a loss exit."
            if source_refs
            else "No refreshed source packet is attached, so HOLD remains the default."
        ),
        "broad_market_noise_frame": (
            "Refreshed market/news context is attached for BOARD to decide whether the drawdown is broad/sector noise or company-specific damage; broad weakness alone remains insufficient."
            if has_market_context
            else "No refreshed market/sector context is attached, so broad-market noise has not been ruled out."
        ),
        "current_thesis_status_candidate": current_thesis_status,
        "thesis_status_evidence": thesis_status_evidence,
        "loss_exit_candidate": loss_exit_candidate,
        "source_refs": source_refs,
        "route_summary": route_summary,
        "review_allowed_after_refresh": False,
        "forbidden_effects": list(LOSS_REVIEW_FORBIDDEN_EFFECTS),
    }
    authority = resolve_exit_authority(
        supervisor_review=review,
        advisory_analysis=advisory_analysis,
    )
    policy_candidate = _pre_registered_policy_candidate(review, authority)
    if policy_candidate is not None:
        advisory_analysis["loss_exit_candidate"] = policy_candidate
    advisory_analysis["review_allowed_after_refresh"] = authority.allowed
    advisory_analysis["authority_source"] = authority.authority_source
    advisory_analysis["requires_board_decision"] = authority.requires_additional_decision
    advisory_analysis["decision_owner"] = authority.decision_owner
    advisory_analysis["policy_rule_conflict"] = (
        authority.authority_source == "invalid_pre_registered_policy_rule"
    )
    return advisory_analysis


def _refresh_resolved_blockers(
    blockers: Sequence[str],
    *,
    source_packet_ids: Sequence[str],
    coverage_by_need: Mapping[str, int],
    entry_context: Mapping[str, Any] | None = None,
    thesis_status_candidate: str | None = None,
    loss_exit_candidate: Mapping[str, Any] | None = None,
) -> list[str]:
    """Return loss-review blockers addressed by this read-only evidence refresh."""
    resolved: list[str] = []
    has_sources = bool(source_packet_ids)
    has_news = bool(
        int(coverage_by_need.get("market_news") or 0)
        or int(coverage_by_need.get("news_rss") or 0)
    )
    has_earnings_or_filings = bool(
        int(coverage_by_need.get("earnings_transcripts") or 0)
        or int(coverage_by_need.get("fundamentals_profile") or 0)
        or int(coverage_by_need.get("submissions") or 0)
    )
    has_market_context = _has_coverage(
        coverage_by_need,
        "market_sentiment_watchlist",
        "market_news",
        "quote_price_context",
    )
    has_hold_sell_context = has_sources and has_news and has_earnings_or_filings
    has_entry_reason = bool(str((entry_context or {}).get("entry_reason") or "").strip())
    has_holding_period = (entry_context or {}).get("holding_period_trading_days") is not None
    has_current_thesis_status = bool(
        thesis_status_candidate
        and not str(thesis_status_candidate).startswith("unresolved_")
    )
    has_loss_exit_reason = bool(
        str((loss_exit_candidate or {}).get("allowed_exit_reason_candidate") or "").strip()
    )
    has_loss_exit_reason_source = bool(
        str((loss_exit_candidate or {}).get("allowed_exit_reason_source") or "").strip()
    )
    has_loss_exit_confidence = (
        _float_value((loss_exit_candidate or {}).get("confidence")) or 0
    ) > 0
    for blocker in blockers:
        normalized = blocker.lower()
        if (
            ("allowed loss-exit reason source" in normalized and has_loss_exit_reason_source)
            or ("allowed loss-exit reason" in normalized and has_loss_exit_reason)
            or ("loss-exit confidence" in normalized and has_loss_exit_confidence)
            or ("source packet ids" in normalized and has_sources)
            or ("original buy thesis" in normalized and has_entry_reason)
            or ("holding period evidence" in normalized and has_holding_period)
            or ("current thesis status" in normalized and has_current_thesis_status)
            or ("company-specific news check" in normalized and has_news)
            or (
                "earnings/guidance/filing check" in normalized
                and has_earnings_or_filings
            )
            or ("spy/qqq/sector context" in normalized and has_market_context)
            or ("why hold is worse than sell" in normalized and has_hold_sell_context)
            or (
                "why this is not broad-market red-day noise" in normalized
                and has_market_context
            )
        ):
            resolved.append(blocker)
    return resolved


def build_loss_review_evidence_packet(
    *,
    hourly_packet_path: str | Path,
    hourly_packet: Mapping[str, Any],
    provider_result: TickerProviderResearchResult,
    evidence_needs: Sequence[str] = DEFAULT_LOSS_REVIEW_EVIDENCE_NEEDS,
    entry_context: Mapping[str, Any] | None = None,
) -> SourceEvidencePacket:
    """Build an advisory packet for BOARD/manual loss-review analysis.

    The packet attaches fresh research references to the current hold, but it
    deliberately does not mutate the supervisor's loss_exit_review or approve a
    loss exit.
    """
    review = _loss_review_from_packet(hourly_packet)
    if review is None:
        raise ValueError("hourly packet does not contain evidence.loss_exit_review")
    symbol = str(review.get("symbol") or provider_result.symbol).strip().upper()
    source_ids = _source_packet_ids(provider_result)
    blockers = _strings(review.get("blockers")) or _strings(review.get("blocked_reasons"))
    coverage_by_need = _coverage_by_need(provider_result)
    review_at = _parse_timestamp(
        review.get("evidence_generated_at") or hourly_packet.get("generated_at")
    )
    if entry_context is None:
        entry_context = find_prior_live_entry_context(
            hourly_packet_path,
            symbol=symbol,
            review_at=review_at,
        )
    advisory_analysis = _build_advisory_analysis(
        symbol=symbol,
        review=review,
        hourly_packet=hourly_packet,
        provider_result=provider_result,
        coverage_by_need=coverage_by_need,
        entry_context=entry_context,
    )
    resolved_blockers = _refresh_resolved_blockers(
        blockers,
        source_packet_ids=source_ids,
        coverage_by_need=coverage_by_need,
        entry_context=entry_context,
        thesis_status_candidate=advisory_analysis.get("current_thesis_status_candidate"),
        loss_exit_candidate=advisory_analysis.get("loss_exit_candidate"),
    )
    resolved_set = set(resolved_blockers)
    remaining_blockers = [blocker for blocker in blockers if blocker not in resolved_set]
    hourly_path = Path(hourly_packet_path)
    source_ref = f"local://{hourly_path.as_posix()}"
    payload = {
        "symbol": symbol,
        "hourly_packet_path": str(hourly_path),
        "hourly_generated_at": hourly_packet.get("generated_at"),
        "hourly_decision": hourly_packet.get("decision"),
        "submitted_order_count": len(hourly_packet.get("submitted") or []),
        "review_allowed": review.get("allowed") is True,
        "supervisor_review_authority": bounded_exit_authority_record(review),
        "supervisor_review_source_packet_ids": _strings(review.get("source_packet_ids")),
        "source_packet_ids": source_ids,
        "provider_summary_packet_id": (
            provider_result.summary_packet.packet_id
            if provider_result.summary_packet is not None
            else None
        ),
        "evidence_needs": [need for need in evidence_needs if need],
        "evidence_coverage_by_need": coverage_by_need,
        "route_attempt_count": len(provider_result.route_attempts),
        "entry_context": dict(entry_context or {}),
        "entry_context_found": bool(entry_context),
        "advisory_analysis": advisory_analysis,
        "remaining_blockers_before_refresh": blockers,
        "resolved_blockers_by_refresh": resolved_blockers,
        "remaining_blockers": remaining_blockers,
        "review_snapshot": {
            "current_price": review.get("current_price"),
            "average_entry_price": review.get("average_entry_price"),
            "unrealized_pl": review.get("unrealized_pl"),
            "unrealized_pnl_percent": review.get("unrealized_pnl_percent"),
            "market_session": review.get("market_session"),
        },
        "next_action": (
            "pre_registered_policy_approval_preserved"
            if advisory_analysis.get("authority_source")
            == "pre_registered_policy_rule"
            else (
                "manual_board_review_with_refreshed_evidence_required"
                if resolved_blockers
                else "manual_board_review_required"
            )
        ),
        "analysis_only": True,
        "execution_authority": "none",
        "forbidden_effects": list(LOSS_REVIEW_FORBIDDEN_EFFECTS),
    }
    return evidence_packet(
        source_name="loss_review_evidence",
        evidence_type="loss_review_evidence",
        subject=symbol,
        symbol=symbol,
        source_ref=source_ref,
        payload=payload,
        quality="medium" if source_ids else "unknown",
        request_fingerprint=request_hash(
            "LOCAL",
            source_ref,
            None,
            {
                "symbol": symbol,
                "hourly_generated_at": hourly_packet.get("generated_at"),
                "evidence_needs": [need for need in evidence_needs if need],
                "source_packet_ids": source_ids,
            },
        ),
        tool_route="local_loss_review_evidence",
        redaction_status="no_secrets_seen",
        freshness_extra={
            "read_only": True,
            "can_submit_orders": False,
            "source_packet_count": len(source_ids),
        },
    )
