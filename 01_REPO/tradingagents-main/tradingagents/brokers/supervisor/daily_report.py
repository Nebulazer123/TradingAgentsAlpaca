"""Daily supervisor report rendering helpers.

This module owns the daily digest body generation. It is intentionally
analysis/reporting-only and has no order submission authority.
"""

from __future__ import annotations

import datetime
import json
from collections.abc import Mapping, Sequence
from decimal import ROUND_DOWN, Decimal
from pathlib import Path

from tradingagents.brokers.supervisor.formatting import email_reason_text as _email_reason_text
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
                "Earlier live buy was blocked by the old dollar-cap guard. "
                "Later clean packets cleared it."
            )
        return (
            "This looks like an old dollar-cap style blocker. "
            "Current uncapped mode ignores repo dollar caps, so Codex should rerun "
            "the supervisor and only stop if broker buying power or the live gate still blocks it."
        )
    return reason


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
    live_budget_mode = ""
    for packet in reversed(ordered_packets):
        evidence = packet.get("evidence") if isinstance(packet, Mapping) else None
        if not isinstance(evidence, Mapping):
            continue
        live_budget = evidence.get("live_budget")
        if isinstance(live_budget, Mapping) and live_budget.get("mode"):
            live_budget_mode = str(live_budget.get("mode"))
            break
    live_sizing_lines = [
        (
            "- Live sizing mode: configured limit; "
            f"Live reference limit: ${_display_money(live.get('dynamic_cap'))}; "
            f"Unused live reference: ${_display_money(live.get('unused_cap'))}"
        ),
    ]
    if live_budget_mode == "autonomous_uncapped":
        live_sizing_lines = [
            (
                "- Live sizing mode: autonomous uncapped; Live buying power available: "
                f"${_display_money(live.get('buying_power'))}"
            ),
        ]

    lines = [
        "Plain English",
        f"- {plain_english}",
        "",
        "What happened",
        (
            "- "
            f"Latest decision: {latest_material.get('decision', 'none')} - "
            f"{_email_reason_text(latest_material.get('reason'))}"
        ),
        (
            "- Checks today: "
            f"{len(ordered_packets)} supervisor, "
            f"{len(material_packets)} material, "
            f"{len(submitted)} submitted order(s)"
        ),
        "",
        f"Problem: {problem_reason}",
        "",
        "Money today",
        f"- Live spent today: ${_display_money(spend['live'])}",
        f"- Paper spent today: ${_display_money(spend['paper'])}",
        "",
        "Live account",
        (
            f"- Live equity: ${_display_money(live.get('equity'))}; "
            f"Live unrealized P/L: ${_display_money(live.get('unrealized_pl'))} "
            f"({_portfolio_unrealized_plpc(live)}%)"
        ),
        *live_sizing_lines,
    ]
    lines.extend(_position_lines(live.get("positions") or [], limit=5))
    lines.extend(
        [
            "",
            "Paper account",
            f"- Paper unrealized P/L: ${_display_money(paper.get('unrealized_pl'))}",
        ]
    )
    lines.extend(_position_lines(paper.get("positions") or [], limit=4))
    lines.extend(["", "Open orders"])
    lines.extend(_open_order_lines("Live", live.get("open_orders") or []))
    lines.extend(_open_order_lines("Paper", paper.get("open_orders") or []))
    lines.extend(["", "Submitted orders"])
    if spend["orders"]:
        shown_orders = spend["orders"][:5]
        for order in shown_orders:
            lines.append(f"- {_submitted_order_line(order)}")
        remaining_orders = len(spend["orders"]) - len(shown_orders)
        if remaining_orders > 0:
            lines.append(f"- {remaining_orders} more submitted order(s) not shown in this short email.")
    else:
        lines.append("- none")
    if spend["excluded_orders"]:
        lines.extend(["", "Rejected/canceled orders"])
        for order in spend["excluded_orders"]:
            lines.append(f"- {_submitted_order_line(order)}")
    if cleared_problem_packets and current_problem_packet is None:
        cleared_reason = _human_problem_reason(
            _packet_problem_reason(cleared_problem_packets[-1]),
            cleared=True,
        )
        lines.extend(["", f"Earlier issue cleared: {cleared_reason}"])
    overnight_items = [
        packet.get("evidence", {}).get("overnight_plan")
        for packet in ordered_packets
        if isinstance(packet.get("evidence"), Mapping)
        and packet.get("evidence", {}).get("overnight_plan")
    ]
    if overnight_items:
        latest_overnight = overnight_items[-1]
        lines.extend(
            [
                "",
                (
                    "Overnight validation: "
                    f"{latest_overnight.get('status', 'unknown')} "
                    f"(overnight top {latest_overnight.get('overnight_top_symbol', 'none')}, "
                    f"current top {latest_overnight.get('current_top_symbol', 'none')})"
                ),
            ]
        )
    candidates = portfolio.get("ranked_candidates") or []
    if candidates:
        candidate_bits = [
            f"{candidate.get('symbol')} {candidate.get('day_change_pct')}%"
            for candidate in candidates[:3]
        ]
        lines.extend(["", f"Top dip candidates: {', '.join(candidate_bits)}"])
    if len(material_packets) > 1 and not submitted:
        lines.append("")
        lines.append("Material decisions")
        for packet in material_packets[-2:]:
            lines.append(
                "- "
                f"{packet.get('generated_at', 'unknown')}: "
                f"{packet.get('decision', 'unknown')} - "
                f"{packet.get('reason', '')}"
            )
        if len(material_packets) > 2:
            lines.append(f"- {len(material_packets) - 2} earlier material decisions not shown")
    lines.extend(
        [
            "",
            "Need from you",
        ]
    )
    if current_problem_packet is not None:
        lines.append(
            "- Please approve Codex to self-heal the blocker if it can do that safely. If this needs a credential, risk-envelope arming, or kill/freeze decision, the bot will ask that one owner-level question and keep trading blocked until answered."
        )
    else:
        lines.append("- No approval needed. Routine trades and promotions stay autonomous inside the configured envelope.")
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
        candidate = paper_tournament_report.get("live_strategy_candidate") or {}
        daily_context_lines.append(
            f"Paper tournament leader: {leader.get('strategy_id')} "
            f"return ${leader.get('total_return')} / {leader.get('total_return_pct')}%; "
            f"candidate {candidate.get('status', 'unknown')} "
            f"{candidate.get('strategy_id') or 'none'}."
        )
    if premarket_brief:
        instructions = premarket_brief.get("premarket_instructions") or {}
        daily_context_lines.append(
            "Premarket brief: "
            f"{premarket_brief.get('generated_at', 'unknown')}, "
            f"top {instructions.get('top_symbol') or 'none'}, "
            f"status {premarket_brief_validation.get('status') if premarket_brief_validation else None}, "
            f"sources {len(premarket_brief.get('source_packets') or [])}, "
            f"path {premarket_brief_path_text or 'unknown'}"
        )
    model_telemetry = daily_model_telemetry_line(model_telemetry_report)
    if model_telemetry:
        daily_context_lines.append(model_telemetry)
    execution_board = daily_execution_board_line(execution_board_review)
    if execution_board:
        daily_context_lines.append(execution_board)
    if daily_context_lines:
        body = "\n".join([body, "", *daily_context_lines])

    return {
        "email_to": email_to,
        "subject": "TradingAgents Daily Market Supervisor Report",
        "body": body,
        "portfolio": portfolio,
        "paper_tournament": paper_tournament_report,
        "premarket_brief": premarket_brief,
        "model_telemetry_report": model_telemetry_report,
        "execution_board_review": execution_board_review,
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
        },
        "raw_field_groups": [
            "body",
            "portfolio",
            "paper_tournament",
            "premarket_brief",
            "model_telemetry_report",
            "execution_board_review",
            "premarket_brief_status",
        ],
    }
