"""Daily supervisor report rendering helpers.

This module owns the daily digest body generation. It is intentionally
analysis/reporting-only and has no order submission authority.
"""

from __future__ import annotations

import datetime
import json
import zoneinfo
from collections.abc import Mapping, Sequence
from decimal import ROUND_DOWN, Decimal
from pathlib import Path

from tradingagents.brokers.supervisor.formatting import (
    email_reason_text as _email_reason_text,
)
from tradingagents.brokers.supervisor.formatting import (
    plain_language_reason,
    strategy_display_name,
)
from tradingagents.brokers.supervisor.session import UTC
from tradingagents.policy.io import atomic_write_text, unique_packet_path


def _as_decimal(value: Decimal | int | float | str | None, default: str = "0") -> Decimal:
    if value is None or value == "":
        return Decimal(default)
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _money(value: Decimal | int | float | str) -> str:
    return str(_as_decimal(value).quantize(Decimal("0.01"), rounding=ROUND_DOWN))


def _display_money(value: Decimal | int | float | str | None) -> str:
    amount = _as_decimal(value).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
    return f"{amount:,.2f}"


def _display_pct(value: Decimal | int | float | str | None) -> str:
    pct = _as_decimal(value).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
    return f"{pct:,.2f}"


def _parse_generated_at(value: object) -> datetime.datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _portfolio_unrealized_plpc(portfolio_section: Mapping) -> str:
    exposure = _as_decimal(portfolio_section.get("exposure"))
    if exposure <= 0:
        return "0.00"
    return _display_pct(_as_decimal(portfolio_section.get("unrealized_pl")) / exposure * Decimal("100"))


def _packet_action_account(packet: Mapping, submitted: Mapping) -> str:
    submitted_symbol = str(submitted.get("symbol", "")).upper()
    submitted_side = str(submitted.get("side", "")).lower()
    submitted_client_id = str(submitted.get("client_order_id", ""))
    for action in packet.get("actions") or []:
        if not isinstance(action, Mapping):
            continue
        if str(action.get("symbol", "")).upper() != submitted_symbol:
            continue
        if str(action.get("side", "")).lower() not in {"", submitted_side}:
            continue
        return str(action.get("account", "live")).lower()
    if "paper" in submitted_client_id.lower():
        return "paper"
    return "live"


def _submitted_spend_summary(packets: Sequence[Mapping]) -> dict:
    summary = {
        "live": Decimal("0"),
        "paper": Decimal("0"),
        "orders": [],
        "excluded_orders": [],
    }
    excluded_statuses = {"rejected", "canceled", "cancelled", "expired", "failed"}
    for packet in packets:
        for submitted in packet.get("submitted") or []:
            if not isinstance(submitted, Mapping):
                continue
            account = _packet_action_account(packet, submitted)
            side = str(submitted.get("side", "")).lower()
            notional = _as_decimal(submitted.get("notional"))
            status = str(submitted.get("status") or "submitted").lower()
            if account not in {"live", "paper"}:
                account = "live"
            order = {
                "account": account,
                "symbol": str(submitted.get("symbol", "")).upper(),
                "side": side,
                "notional": _money(notional),
                "qty": str(submitted.get("qty", "")),
                "limit_price": str(submitted.get("limit_price", "")),
                "status": status,
                "client_order_id": str(submitted.get("client_order_id", "")),
                "id": str(submitted.get("id", "")),
            }
            if status in excluded_statuses:
                summary["excluded_orders"].append(order)
                continue
            if side == "buy":
                summary[account] += notional
            summary["orders"].append(order)
    return summary


def _is_problem_packet(packet: Mapping) -> bool:
    return bool(packet.get("issues")) or packet.get("decision") == "blocked"


def _packet_problem_reason(packet: Mapping) -> str:
    for issue in packet.get("issues") or []:
        if isinstance(issue, Mapping) and issue.get("reason"):
            return str(issue.get("reason"))
    return str(packet.get("reason") or "unknown problem")


def _human_problem_reason(reason: str, *, cleared: bool = False) -> str:
    lower = reason.lower()
    if (
        "paired live sell is not large enough" in lower
        or "new live buy would exceed live exposure limit" in lower
        or "live exposure limit" in lower
    ):
        if cleared:
            return (
                "An earlier real-money buy was stopped by a spending limit. "
                "Later checks came back clean."
            )
        return (
            "A real-money buy was stopped by a spending limit. The system "
            "will retry on its own and only stays stopped if the broker or "
            "a safety check still says no."
        )
    return plain_language_reason(reason, default=_email_reason_text(reason))


def _daily_packet_sort_key(packet: Mapping) -> datetime.datetime:
    return _parse_generated_at(packet.get("generated_at")) or datetime.datetime.min.replace(
        tzinfo=UTC
    )


def _submitted_order_line(order: Mapping) -> str:
    base = f"{order['account']} {order['symbol']} {order['side']}"
    qty = str(order.get("qty") or "")
    if str(order.get("side", "")).lower() == "sell" and qty:
        size = f"qty {qty}"
    else:
        size = f"${_display_money(order.get('notional'))}"
    return (
        f"{base} {size} limit {order['limit_price']} "
        f"status={order['status']}"
    )


def _position_lines(positions: Sequence[Mapping], *, limit: int = 6) -> list[str]:
    if not positions:
        return ["- Holdings: none"]
    lines_: list[str] = []
    for position in positions[:limit]:
        lines_.append(
            "- Holdings: "
            f"{position.get('symbol')}: value ${_display_money(position.get('market_value'))}, "
            f"P/L ${_display_money(position.get('unrealized_pl'))} "
            f"({_display_pct(position.get('unrealized_plpc'))}%), "
            f"current ${_display_money(position.get('current_price'))}"
        )
    if len(positions) > limit:
        lines_.append(f"- Holdings: {len(positions) - limit} more not shown")
    return lines_


def _open_order_lines(label: str, orders: Sequence[Mapping], *, limit: int = 5) -> list[str]:
    if not orders:
        return [f"- {label}: none"]
    lines_: list[str] = []
    for order in orders[:limit]:
        lines_.append(
            "- "
            f"{label}: {order.get('symbol')} {order.get('side')} "
            f"{order.get('type')} status={order.get('status')} "
            f"id={order.get('client_order_id') or 'unknown'}"
        )
    if len(orders) > limit:
        lines_.append(f"- {label}: {len(orders) - limit} more not shown")
    return lines_


def render_daily_supervisor_report(
    *,
    portfolio: Mapping,
    packets: Sequence[Mapping],
    email_to: str,
) -> str:
    ordered_packets = sorted(
        [packet for packet in packets if isinstance(packet, Mapping)],
        key=_daily_packet_sort_key,
    )
    live = portfolio.get("live", {})
    paper = portfolio.get("paper", {})
    submitted = [
        submitted
        for packet in ordered_packets
        for submitted in packet.get("submitted", [])
    ]
    spend = _submitted_spend_summary(ordered_packets)
    material_packets = [
        packet
        for packet in ordered_packets
        if packet.get("material") or packet.get("issues") or packet.get("submitted")
    ]
    latest_packet = ordered_packets[-1] if ordered_packets else {}
    latest_material = material_packets[-1] if material_packets else latest_packet
    current_problem_packet = latest_packet if _is_problem_packet(latest_packet) else None
    problem_packets = [packet for packet in ordered_packets if _is_problem_packet(packet)]
    cleared_problem_packets = (
        problem_packets[:-1]
        if current_problem_packet is not None
        else problem_packets
    )
    problem_reason = (
        _human_problem_reason(_packet_problem_reason(current_problem_packet))
        if current_problem_packet is not None
        else "none"
    )
    if current_problem_packet is not None:
        plain_english = "The bot found a safety problem and kept live trading blocked."
    elif submitted:
        plain_english = "Orders were sent today. The dollars and accounts are listed below."
    else:
        plain_english = "Nothing urgent happened. The bot kept watching and stayed inside the rules."
    # --- Why it matters / next action -------------------------------------
    if current_problem_packet is not None:
        why_it_matters = (
            "- While a safety problem is open, the system stops buying and "
            "keeps your money where it is. Nothing is lost by the block "
            "itself, but no new opportunities are taken until it clears."
        )
        next_action = (
            "- Reply to this email or open the app and approve the safe "
            "auto-repair. If the problem needs an owner decision (renewing "
            "the real-money safety timer, or a freeze/unfreeze call), it "
            "will be asked as one question. Trading stays paused until then."
        )
    elif submitted:
        why_it_matters = (
            "- Money moved today. The amounts above are what was spent, and "
            "every order stayed inside the safety limits."
        )
        next_action = (
            "- Nothing needed from you today. Skim the order list above and "
            "reply if anything looks unfamiliar."
        )
    else:
        why_it_matters = (
            "- A quiet day means the rules did not find anything worth "
            "buying or selling, so your money stayed where it was."
        )
        next_action = "- Nothing needed from you today."

    positions = live.get("positions") or []
    best = max(positions, key=lambda p: float(p.get("unrealized_pl") or 0), default=None)
    worst = min(positions, key=lambda p: float(p.get("unrealized_pl") or 0), default=None)

    lines = [
        "Plain English",
        f"- {plain_english}",
        "",
        "Where you stand",
        (
            "- Real-money account: "
            f"${_display_money(live.get('equity'))} total; "
            f"overall position P/L ${_display_money(live.get('unrealized_pl'))} "
            f"({_portfolio_unrealized_plpc(live)}%); Holdings: {len(positions)}"
        ),
    ]
    if best is not None and worst is not None and best is not worst:
        lines.append(
            f"- Best holding: {best.get('symbol')} "
            f"${_display_money(best.get('unrealized_pl'))}; worst: "
            f"{worst.get('symbol')} ${_display_money(worst.get('unrealized_pl'))}"
        )
    elif best is not None:
        lines.append(
            f"- Largest holding: {best.get('symbol')} "
            f"${_display_money(best.get('unrealized_pl'))}"
        )
    lines.extend(
        [
            f"- Spent today: ${_display_money(spend['live'])} real money, "
            f"${_display_money(spend['paper'])} practice",
            (
                "- Practice account P/L: "
                f"${_display_money(paper.get('unrealized_pl'))} "
                f"(practice trades test ideas with no real money)"
            ),
            "",
            "What happened",
            f"- {plain_language_reason(latest_material.get('reason'), default='Routine checks ran on schedule.')}",
            (
                "- Checks today: "
                f"{len(ordered_packets)} routine, "
                f"{len(material_packets)} needed attention, "
                f"{len(submitted)} order(s) sent"
            ),
            f"- Problem: {problem_reason}",
        ]
    )
    if spend["orders"]:
        for order in spend["orders"][:4]:
            lines.append(f"- Order: {_submitted_order_line(order)}")
        remaining_orders = len(spend["orders"]) - min(len(spend["orders"]), 4)
        if remaining_orders > 0:
            lines.append(f"- {remaining_orders} more order(s) not shown in this short email")
    if spend["excluded_orders"]:
        lines.append(
            f"- {len(spend['excluded_orders'])} order(s) were rejected or "
            "canceled before any money moved"
        )
    open_order_count = len(live.get("open_orders") or []) + len(paper.get("open_orders") or [])
    lines.append(
        f"- Waiting orders: {open_order_count if open_order_count else 'none'}"
    )
    if cleared_problem_packets and current_problem_packet is None:
        lines.append(
            "- An earlier issue cleared on its own: "
            f"{_human_problem_reason(_packet_problem_reason(cleared_problem_packets[-1]), cleared=True)}"
        )
    candidates = portfolio.get("ranked_candidates") or []
    if candidates:
        candidate_bits = [
            f"{candidate.get('symbol')} ({candidate.get('day_change_pct')}% today)"
            for candidate in candidates[:3]
        ]
        lines.append(
            f"- Stocks being watched for a possible dip buy: {', '.join(candidate_bits)}"
        )
    lines.extend(
        [
            "",
            "Why it matters",
            why_it_matters,
            "",
            "What to do next",
            next_action,
        ]
    )
    return "\n".join(lines)


def _format_count_map(values: Mapping | None) -> str:
    if not values:
        return "none"
    return ", ".join(f"{key}={value}" for key, value in values.items())


def daily_model_telemetry_line(report: Mapping | None) -> str | None:
    if not report:
        return None
    operator_summary = str(report.get("operator_summary") or "").strip()
    if operator_summary:
        return f"Model telemetry: {operator_summary}"
    return (
        "Model telemetry: "
        f"{report.get('packet_count', 0)} run packet(s), "
        f"usefulness {_format_count_map(report.get('usefulness_counts'))}, "
        f"outcomes {_format_count_map(report.get('outcome_counts'))}, "
        f"resolved {report.get('resolved_model_run_count', 0)}, "
        f"estimated spend ${report.get('estimated_cost_total_usd', '0.0000')}"
    )


def daily_execution_board_line(review: Mapping | None) -> str | None:
    if not review:
        return None
    recommendation = str(review.get("recommendation") or "unknown")
    metrics = review.get("metrics") if isinstance(review.get("metrics"), Mapping) else {}
    new_buy_policy = (
        review.get("new_buy_policy")
        if isinstance(review.get("new_buy_policy"), Mapping)
        else {}
    )
    violation_count = len(review.get("violations") or [])
    warning_count = len(review.get("warnings") or [])
    submitted_count = metrics.get("submitted_order_count", 0)
    if recommendation == "pause_new_buys_and_review":
        return (
            "BOARD review: new buys are paused for review; sells still work independently. "
            "Reason: recent history showed "
            f"{violation_count} hard issue(s), {warning_count} warning(s), "
            f"and {submitted_count} submitted order(s). "
            "Next action: wait for cleaner dip/support evidence before fresh buys."
        )
    if recommendation == "continue_with_guardrails_after_clean_streak":
        return (
            "BOARD review: earlier mistakes are still being watched, but new controlled-dip buys are allowed again. "
            f"Clean packets since latest hard issue: {new_buy_policy.get('clean_packets_since_last_violation', 0)}. "
            "Sells still work independently."
        )
    return (
        "BOARD review: "
        f"{recommendation}; {violation_count} hard issue(s), "
        f"{warning_count} warning(s), {submitted_count} submitted order(s)."
    )


def build_supervisor_daily_report_payload(
    *,
    portfolio: Mapping,
    packets: Sequence[Mapping],
    email_to: str,
    paper_tournament_report: Mapping | None = None,
    premarket_brief: Mapping | None = None,
    premarket_brief_validation: Mapping | None = None,
    premarket_brief_path: Path | str | None = None,
    model_telemetry_report: Mapping | None = None,
    execution_board_review: Mapping | None = None,
    alpaca_reference_summary: Mapping | None = None,
) -> dict:
    premarket_brief_path_text = (
        premarket_brief_path.as_posix()
        if isinstance(premarket_brief_path, Path)
        else str(premarket_brief_path)
        if premarket_brief_path
        else None
    )
    body = render_daily_supervisor_report(
        portfolio=portfolio,
        packets=packets,
        email_to=email_to,
    )
    daily_context_lines: list[str] = []
    if paper_tournament_report and paper_tournament_report.get("rankings"):
        leader = paper_tournament_report["rankings"][0]
        daily_context_lines.append(
            "Practice-strategy race: "
            f"{strategy_display_name(leader.get('strategy_id'))} is leading "
            f"with a {leader.get('total_return_pct')}% return."
        )
    if premarket_brief:
        instructions = premarket_brief.get("premarket_instructions") or {}
        top_symbol = instructions.get("top_symbol")
        if top_symbol:
            daily_context_lines.append(
                f"Tomorrow's top stock to watch: {top_symbol}."
            )
    if daily_context_lines:
        body = "\n".join([body, "", *daily_context_lines])
    if alpaca_reference_summary and alpaca_reference_summary.get("material"):
        material_summary = str(
            alpaca_reference_summary.get("material_summary") or ""
        ).strip()
        if material_summary:
            body = "\n".join([body, "", material_summary])

    has_problem = any(
        packet.get("issues") or packet.get("decision") == "blocked"
        for packet in packets
        if isinstance(packet, Mapping)
    )
    submitted_count = sum(
        len(packet.get("submitted") or []) for packet in packets if isinstance(packet, Mapping)
    )
    if has_problem:
        status_phrase = "a safety check needs attention"
    elif submitted_count:
        status_phrase = f"{submitted_count} trade(s) made"
    else:
        status_phrase = "quiet day, no trades"
    # Owner-local date (America/Chicago), not UTC — a 3:30pm report must not
    # carry tomorrow's date.
    today = datetime.datetime.now(tz=zoneinfo.ZoneInfo("America/Chicago"))
    subject = (
        f"Your trading update for {today:%A, %B %-d}: {status_phrase} [TradingAgents]"
    )

    return {
        "email_to": email_to,
        "subject": subject,
        "body": body,
        "portfolio": portfolio,
        "paper_tournament": paper_tournament_report,
        "premarket_brief": premarket_brief,
        "model_telemetry_report": model_telemetry_report,
        "execution_board_review": execution_board_review,
        "alpaca_reference_summary": dict(alpaca_reference_summary or {}),
        "premarket_brief_status": premarket_brief_validation,
        "premarket_brief_path": premarket_brief_path_text,
        "packet_count": len(packets),
        "material_count": sum(
            1
            for packet in packets
            if packet.get("material") or packet.get("issues") or packet.get("submitted")
        ),
    }


def write_supervisor_daily_report_packet(packet: dict, output_dir: Path | str) -> Path:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.datetime.now(tz=UTC)
    packet.setdefault("generated_at", generated_at.isoformat(timespec="seconds"))
    packet_path = unique_packet_path(
        output_path,
        f"supervisor-daily-report-{generated_at:%Y%m%d-%H%M%S-%f}",
    )
    packet["packet_path"] = str(packet_path)
    packet_text = json.dumps(packet, indent=2)
    atomic_write_text(packet_path, packet_text)
    atomic_write_text(output_path / "latest.json", packet_text)
    return packet_path


def compact_supervisor_daily_report_payload(packet: Mapping, packet_path: Path | str) -> dict:
    portfolio = packet.get("portfolio") or {}
    live = portfolio.get("live") or {}
    paper = portfolio.get("paper") or {}
    ranked_candidates = portfolio.get("ranked_candidates") or []
    body = str(packet.get("body") or "")
    paper_tournament = packet.get("paper_tournament") or {}
    rankings = paper_tournament.get("rankings") if isinstance(paper_tournament, dict) else []
    tournament_leader = (
        rankings[0]
        if isinstance(rankings, list) and rankings and isinstance(rankings[0], dict)
        else {}
    )
    live_candidate = (
        paper_tournament.get("live_strategy_candidate")
        if isinstance(paper_tournament, dict)
        else {}
    )
    premarket_brief = packet.get("premarket_brief") or {}
    premarket_status = packet.get("premarket_brief_status") or {}
    premarket_instructions = (
        premarket_brief.get("premarket_instructions")
        if isinstance(premarket_brief, dict)
        else {}
    )
    model_telemetry = packet.get("model_telemetry_report") or {}
    execution_board = packet.get("execution_board_review") or {}
    alpaca_reference = packet.get("alpaca_reference_summary") or {}
    top_candidate = (
        ranked_candidates[0]
        if isinstance(ranked_candidates, list) and ranked_candidates and isinstance(ranked_candidates[0], dict)
        else {}
    )

    return {
        "schema": "compact_supervisor_daily_report_v1",
        "raw_packet_path": str(packet_path),
        "generated_at": packet.get("generated_at"),
        "email_to": packet.get("email_to"),
        "subject": packet.get("subject"),
        "body_summary": {
            "char_count": len(body),
            "line_count": len(body.splitlines()) if body else 0,
            "body_ref": "raw_packet_path.body",
        },
        "counts": {
            "hourly_packets": packet.get("packet_count"),
            "material_hourly_packets": packet.get("material_count"),
            "ranked_candidates": len(ranked_candidates) if isinstance(ranked_candidates, list) else 0,
        },
        "portfolio_summary": {
            "live": {
                "status": live.get("status") if isinstance(live, dict) else None,
                "equity": live.get("equity") if isinstance(live, dict) else None,
                "buying_power": live.get("buying_power") if isinstance(live, dict) else None,
                "cash": live.get("cash") if isinstance(live, dict) else None,
                "exposure": live.get("exposure") if isinstance(live, dict) else None,
                "unrealized_pl": live.get("unrealized_pl") if isinstance(live, dict) else None,
                "position_count": len(live.get("positions") or []) if isinstance(live, dict) else 0,
                "open_order_count": len(live.get("open_orders") or []) if isinstance(live, dict) else 0,
            },
            "paper": {
                "status": paper.get("status") if isinstance(paper, dict) else None,
                "equity": paper.get("equity") if isinstance(paper, dict) else None,
                "buying_power": paper.get("buying_power") if isinstance(paper, dict) else None,
                "unrealized_pl": paper.get("unrealized_pl") if isinstance(paper, dict) else None,
                "position_count": len(paper.get("positions") or []) if isinstance(paper, dict) else 0,
                "open_order_count": len(paper.get("open_orders") or []) if isinstance(paper, dict) else 0,
            },
        },
        "top_candidate": {
            "symbol": top_candidate.get("symbol"),
            "score": top_candidate.get("score"),
            "day_change_pct": top_candidate.get("day_change_pct"),
            "source": top_candidate.get("source"),
        }
        if top_candidate
        else {},
        "context_summary": {
            "paper_tournament": {
                "leader": tournament_leader.get("strategy_id") if tournament_leader else None,
                "leader_return": tournament_leader.get("total_return") if tournament_leader else None,
                "leader_return_pct": tournament_leader.get("total_return_pct") if tournament_leader else None,
                "live_candidate_status": live_candidate.get("status") if isinstance(live_candidate, dict) else None,
                "live_candidate_strategy": live_candidate.get("strategy_id") if isinstance(live_candidate, dict) else None,
            },
            "premarket_brief": {
                "generated_at": premarket_brief.get("generated_at") if isinstance(premarket_brief, dict) else None,
                "top_symbol": premarket_instructions.get("top_symbol")
                if isinstance(premarket_instructions, dict)
                else None,
                "status": premarket_status.get("status") if isinstance(premarket_status, dict) else None,
                "source_packet_count": len(premarket_brief.get("source_packets") or [])
                if isinstance(premarket_brief, dict)
                else 0,
                "packet_path": packet.get("premarket_brief_path"),
            },
            "model_telemetry": {
                "status": model_telemetry.get("status") if isinstance(model_telemetry, dict) else None,
                "packet_count": model_telemetry.get("packet_count") if isinstance(model_telemetry, dict) else None,
                "pending_count": model_telemetry.get("pending_count") if isinstance(model_telemetry, dict) else None,
                "auto_upgrade_allowed": model_telemetry.get("auto_upgrade_allowed")
                if isinstance(model_telemetry, dict)
                else None,
            },
            "execution_board": {
                "recommendation": execution_board.get("recommendation") if isinstance(execution_board, dict) else None,
                "generated_at": execution_board.get("generated_at") if isinstance(execution_board, dict) else None,
                "can_submit_orders": execution_board.get("can_submit_orders") if isinstance(execution_board, dict) else None,
            },
            "alpaca_reference": {
                "status": alpaca_reference.get("status")
                if isinstance(alpaca_reference, dict)
                else None,
                "material": alpaca_reference.get("material")
                if isinstance(alpaca_reference, dict)
                else None,
                "path_count": alpaca_reference.get("path_count")
                if isinstance(alpaca_reference, dict)
                else None,
                "operation_count": alpaca_reference.get("operation_count")
                if isinstance(alpaca_reference, dict)
                else None,
                "method_counts": alpaca_reference.get("method_counts", {})
                if isinstance(alpaca_reference, dict)
                else {},
                "route_statuses": alpaca_reference.get("route_statuses", {})
                if isinstance(alpaca_reference, dict)
                else {},
                "execution_authority": alpaca_reference.get(
                    "execution_authority", "none"
                )
                if isinstance(alpaca_reference, dict)
                else "none",
            },
        },
        "raw_field_groups": [
            "body",
            "portfolio",
            "paper_tournament",
            "premarket_brief",
            "model_telemetry_report",
            "execution_board_review",
            "alpaca_reference_summary",
            "premarket_brief_status",
        ],
    }
