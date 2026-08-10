"""Hourly Alpaca portfolio supervisor guardrails and reporting."""

from __future__ import annotations

import datetime
import hashlib
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from decimal import ROUND_DOWN, Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from tradingagents.brokers.alpaca import AlpacaExecutionConfig, OrderIssue
from tradingagents.brokers.supervisor.alert import (
    classify_supervisor_alert,
    render_supervisor_alert_email,
    should_throttle_supervisor_alert,
    supervisor_alert_fingerprint,
    supervisor_issue_category,
)
from tradingagents.brokers.supervisor.candidates import (
    AGGRESSIVE_CANDIDATE_UNIVERSE,
    CROWDED_AI_BETA_SYMBOLS,
    DEEP_RESEARCH_EVENT_SENSITIVE_SYMBOLS,
    DEEP_RESEARCH_POSITIVE_RELATIVE_SYMBOLS,
    DEFAULT_LIVE_BUY_NOTIONAL,
    LIQUID_SP100_STYLE_UNIVERSE,
    MEGA_CAP_AI_UNIVERSE,
    MIN_LIVE_BUY_NOTIONAL,
    CandidateSignal,
    aggressive_limit_price,
    build_candidate_signals,
    choose_autonomous_live_buy_notional,
    is_buy_entry_candidate,
    is_chase_buy_candidate,
)
from tradingagents.brokers.supervisor.daily_report import render_daily_supervisor_report
from tradingagents.brokers.supervisor.hourly import (
    HourlyDecisionContext,
    build_buy_candidate_decision,
    build_hourly_decision_context,
    build_loss_review_decision,
    build_open_orders_review_decision,
    build_profit_take_decision,
    build_trailing_hold_decision,
    compact_hourly_supervisor_payload,
    find_latest_hourly_packet,
)
from tradingagents.brokers.supervisor.hourly import (
    build_hourly_decision as _build_hourly_decision,
)
from tradingagents.brokers.supervisor.hourly import (
    build_hourly_evidence as _build_hourly_evidence,
)
from tradingagents.brokers.supervisor.hourly import (
    serialize_hourly_decision as _serialize_hourly_decision,
)
from tradingagents.brokers.supervisor.hourly import (
    write_hourly_decision_packet as _write_hourly_decision_packet,
)
from tradingagents.brokers.supervisor.loss_review import loss_exit_review_packet
from tradingagents.brokers.supervisor.orders import (
    build_supervisor_order_payload,
    is_order_action,
    should_notify_supervisor,
)
from tradingagents.brokers.supervisor.overnight import (
    compact_overnight_plan_payload,
    load_latest_overnight_plan,
    render_overnight_plan_markdown,
    validate_overnight_plan_against_candidates,
    write_overnight_plan_packet,
)
from tradingagents.brokers.supervisor.premarket import (
    build_premarket_brief_packet,
    compact_premarket_brief_payload,
    is_expected_hourly_safety_lock,
    load_latest_premarket_brief,
    render_premarket_brief_markdown,
    validate_premarket_brief_against_candidates,
    write_premarket_brief_packet,
)
from tradingagents.brokers.supervisor.session import can_trade_session, market_session_label
from tradingagents.brokers.supervisor.sizing import (
    BASE_LIVE_CAP,
    MAX_DYNAMIC_LIVE_CAP,
    calculate_dynamic_live_cap,
    live_exposure_from_positions,
    total_unrealized_pl,
)
from tradingagents.brokers.supervisor.types import (
    HourlySupervisorAction,
    HourlySupervisorConfig,
    HourlySupervisorDecision,
)
from tradingagents.policy.live_gate import evaluate_go_live_guard

__all__ = [
    "AGGRESSIVE_CANDIDATE_UNIVERSE",
    "BASE_LIVE_CAP",
    "CROWDED_AI_BETA_SYMBOLS",
    "DEEP_RESEARCH_EVENT_SENSITIVE_SYMBOLS",
    "DEEP_RESEARCH_POSITIVE_RELATIVE_SYMBOLS",
    "DEFAULT_LIVE_BUY_NOTIONAL",
    "LIQUID_SP100_STYLE_UNIVERSE",
    "MEGA_CAP_AI_UNIVERSE",
    "MAX_DYNAMIC_LIVE_CAP",
    "MIN_LIVE_BUY_NOTIONAL",
    "CandidateSignal",
    "HourlyDecisionContext",
    "HourlySupervisorAction",
    "HourlySupervisorConfig",
    "HourlySupervisorDecision",
    "aggressive_limit_price",
    "build_candidate_signals",
    "build_buy_candidate_decision",
    "build_hourly_decision_context",
    "build_loss_review_decision",
    "build_open_orders_review_decision",
    "build_premarket_brief_packet",
    "build_profit_take_decision",
    "build_supervisor_order_payload",
    "build_trailing_hold_decision",
    "calculate_dynamic_live_cap",
    "can_trade_session",
    "choose_autonomous_live_buy_notional",
    "compact_hourly_supervisor_payload",
    "compact_overnight_plan_payload",
    "compact_premarket_brief_payload",
    "find_latest_hourly_packet",
    "is_buy_entry_candidate",
    "is_chase_buy_candidate",
    "is_expected_hourly_safety_lock",
    "is_order_action",
    "live_exposure_from_positions",
    "loss_exit_review_packet",
    "load_latest_overnight_plan",
    "load_latest_premarket_brief",
    "market_session_label",
    "render_daily_supervisor_report",
    "resolve_live_sleeve",
    "render_overnight_plan_markdown",
    "render_premarket_brief_markdown",
    "should_notify_supervisor",
    "supervisor_issue_category",
    "total_unrealized_pl",
    "validate_overnight_plan_against_candidates",
    "validate_premarket_brief_against_candidates",
    "write_overnight_plan_packet",
    "write_premarket_brief_packet",
]

UTC = datetime.timezone.utc
CENTRAL = ZoneInfo("America/Chicago")
LIVE_AGGRESSIVE_SLEEVE = "current-aggressive"
DEFAULT_ALERT_THROTTLE_WINDOW = datetime.timedelta(hours=4)


def resolve_live_sleeve(
    live_strategy_selection: Mapping | None,
    promotion_state: Mapping | None,
) -> tuple[str, str]:
    """Pick the sleeve identity stamped on live supervisor actions.

    The paper-tournament selection becomes binding only when the selected
    sleeve holds a live-enabled ``tiny_live_eligible`` promotion record.
    Otherwise fall back to any live-enabled sleeve from promotion state, and
    finally to the legacy default — which the unified live gate fails closed
    on when it has no promotion record.
    """
    sleeves: Mapping = {}
    if isinstance(promotion_state, Mapping):
        raw = promotion_state.get("sleeves")
        if isinstance(raw, Mapping):
            sleeves = raw

    def _live_enabled(sleeve_id: str) -> bool:
        record = sleeves.get(sleeve_id)
        return (
            isinstance(record, Mapping)
            and record.get("stage") == "tiny_live_eligible"
            and record.get("live_enabled") is True
        )

    selected = None
    if isinstance(live_strategy_selection, Mapping):
        selected = live_strategy_selection.get("strategy_id")
    if selected and _live_enabled(str(selected)):
        return (
            str(selected),
            "tournament selection with live-enabled promotion record",
        )
    enabled = sorted(sleeve for sleeve in sleeves if _live_enabled(str(sleeve)))
    if enabled:
        return (
            enabled[0],
            "promotion-state live-enabled sleeve; tournament selection is not live-enabled",
        )
    return (
        LIVE_AGGRESSIVE_SLEEVE,
        "fail-closed default; no live-enabled sleeve in promotion state",
    )

_SYMBOL_RE = re.compile(r"\b[A-Z][A-Z0-9.]{0,5}\b")
_NON_SYMBOL_WORDS = {
    "AI",
    "API",
    "ACTIVE",
    "ALPACA",
    "AND",
    "BUT",
    "CASH",
    "CAP",
    "CEO",
    "CFO",
    "CHECKS",
    "BUY",
    "DAY",
    "DELTA",
    "CME",
    "CLOSED",
    "DMA",
    "ECB",
    "EPS",
    "ETF",
    "EU",
    "EQUITY",
    "FED",
    "FIRST",
    "FALSE",
    "FOMC",
    "FOR",
    "FOUND",
    "FRESH",
    "FROM",
    "GDP",
    "GTC",
    "HOLD",
    "HOURLY",
    "HTTP",
    "IPO",
    "ISSUES",
    "JSON",
    "LIMIT",
    "LIVE",
    "LLM",
    "MACD",
    "MARKET",
    "MCP",
    "NEWS",
    "NONE",
    "NYSE",
    "OCR",
    "OPEN",
    "ORDER",
    "ORDERS",
    "PACKET",
    "PAPER",
    "PCE",
    "PDF",
    "PLAN",
    "PM",
    "PRICE",
    "PROFIT",
    "QQQ",
    "QTY",
    "RATIO",
    "REASON",
    "REVIEW",
    "RAM",
    "RISK",
    "ROI",
    "SCORE",
    "SEC",
    "SELL",
    "SMA",
    "SOURCE",
    "STATUS",
    "SYMBOL",
    "THIS",
    "TICK",
    "TIF",
    "TRUE",
    "URL",
    "USA",
    "USD",
    "UTC",
    "V2",
    "VOLUME",
    "WAS",
}


def _as_decimal(value: Decimal | int | float | str | None, default: str = "0") -> Decimal:
    if value is None or value == "":
        return Decimal(default)
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _positive_decimal_or_none(value: Decimal | int | float | str | None) -> Decimal | None:
    if value in (None, ""):
        return None
    parsed = _as_decimal(value)
    return parsed if parsed > 0 else None


def _money(value: Decimal | int | float | str) -> str:
    return str(_as_decimal(value).quantize(Decimal("0.01"), rounding=ROUND_DOWN))


def _loss_exit_review_packet(
    position: Mapping,
    *,
    generated_at: datetime.datetime,
    decision_id: str | None = None,
    side: str = "sell",
    proposed_order_id: str | None = None,
    proposed_limit_price: Decimal | int | float | str | None = None,
) -> dict:
    return loss_exit_review_packet(
        position,
        generated_at=generated_at,
        decision_id=decision_id,
        side=side,
        proposed_order_id=proposed_order_id,
        proposed_limit_price=proposed_limit_price,
    )


def _display_money(value: Decimal | int | float | str | None) -> str:
    amount = _as_decimal(value).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
    return f"{amount:,.2f}"


def _price(value: Decimal | int | float | str) -> str:
    return str(_as_decimal(value).quantize(Decimal("0.01"), rounding=ROUND_DOWN))

def _pct(value: Decimal | int | float | str | None) -> str:
    return str((_as_decimal(value) * Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_DOWN))


def _display_pct(value: Decimal | int | float | str | None) -> str:
    pct = _as_decimal(value).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
    return f"{pct:,.2f}"


def _portfolio_unrealized_plpc(portfolio_section: Mapping) -> str:
    exposure = _as_decimal(portfolio_section.get("exposure"))
    if exposure <= 0:
        return "0.00"
    return _display_pct(_as_decimal(portfolio_section.get("unrealized_pl")) / exposure * Decimal("100"))


def _normalize_symbol(value: object) -> str | None:
    raw = str(value or "").strip().upper()
    if not raw or raw in _NON_SYMBOL_WORDS:
        return None
    if not _SYMBOL_RE.fullmatch(raw):
        return None
    return raw


def _add_symbol(source_map: dict[str, set[str]], symbol: object, source: str) -> None:
    normalized = _normalize_symbol(symbol)
    if normalized:
        source_map.setdefault(normalized, set()).add(source)


def _add_position_symbols(
    source_map: dict[str, set[str]],
    positions: Iterable[Mapping],
    source: str,
) -> None:
    for position in positions:
        _add_symbol(source_map, position.get("symbol"), source)


def _add_order_symbols(
    source_map: dict[str, set[str]],
    orders: Iterable[Mapping],
    source: str,
) -> None:
    for order in orders:
        _add_symbol(source_map, order.get("symbol"), source)


def _add_packet_symbols(
    source_map: dict[str, set[str]],
    packet: Mapping,
    source: str,
) -> None:
    for candidate in packet.get("ranked_candidates") or []:
        if isinstance(candidate, Mapping):
            _add_symbol(source_map, candidate.get("symbol"), source)
    for action in packet.get("actions") or []:
        if isinstance(action, Mapping):
            _add_symbol(source_map, action.get("symbol"), source)
    portfolio = packet.get("portfolio") or {}
    if isinstance(portfolio, Mapping):
        for candidate in portfolio.get("ranked_candidates") or []:
            if isinstance(candidate, Mapping):
                _add_symbol(source_map, candidate.get("symbol"), source)
        for section_name in ("live", "paper"):
            section = portfolio.get(section_name) or {}
            if not isinstance(section, Mapping):
                continue
            _add_position_symbols(
                source_map,
                section.get("positions") or [],
                f"{source}:{section_name}_positions",
            )
            _add_order_symbols(
                source_map,
                section.get("open_orders") or [],
                f"{source}:{section_name}_open_orders",
            )


def _extract_symbols_from_text(text: str) -> set[str]:
    symbols = set()
    for match in _SYMBOL_RE.findall(text.upper()):
        normalized = _normalize_symbol(match)
        if normalized:
            symbols.add(normalized)
    return symbols


def build_overnight_candidate_universe(
    *,
    live_positions: Sequence[Mapping],
    paper_positions: Sequence[Mapping],
    live_open_orders: Sequence[Mapping],
    paper_open_orders: Sequence[Mapping],
    recent_supervisor_packets: Sequence[Mapping] = (),
    market_packet_paths: Sequence[str | Path] = (),
    watchlist_paths: Sequence[str | Path] = (),
    base_universe: Sequence[str] = AGGRESSIVE_CANDIDATE_UNIVERSE,
) -> list[dict]:
    source_map: dict[str, set[str]] = {}
    owned_symbols: set[str] = set()

    _add_position_symbols(source_map, live_positions, "live_positions")
    _add_position_symbols(source_map, paper_positions, "paper_positions")
    _add_order_symbols(source_map, live_open_orders, "live_open_orders")
    _add_order_symbols(source_map, paper_open_orders, "paper_open_orders")
    for position in list(live_positions) + list(paper_positions):
        normalized = _normalize_symbol(position.get("symbol") if isinstance(position, Mapping) else None)
        if normalized:
            owned_symbols.add(normalized)

    for symbol in base_universe:
        _add_symbol(source_map, symbol, "base_universe")

    for packet in recent_supervisor_packets:
        if isinstance(packet, Mapping):
            _add_packet_symbols(source_map, packet, "recent_supervisor_packet")

    for path_like in market_packet_paths:
        path = Path(path_like)
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        try:
            packet = json.loads(text)
        except json.JSONDecodeError:
            packet = None
        if isinstance(packet, Mapping):
            _add_packet_symbols(source_map, packet, f"market_packet:{path.name}")
            continue
        for symbol in _extract_symbols_from_text(text):
            _add_symbol(source_map, symbol, f"market_packet:{path.name}")

    for path_like in watchlist_paths:
        path = Path(path_like)
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for symbol in _extract_symbols_from_text(text):
            _add_symbol(source_map, symbol, f"watchlist:{path.name}")

    return [
        {
            "symbol": symbol,
            "sources": sorted(source_map[symbol]),
            "owned": symbol in owned_symbols,
            "research_weight": "equal",
        }
        for symbol in sorted(source_map)
    ]


def _position_snapshot(position: Mapping) -> dict:
    return {
        "symbol": str(position.get("symbol", "")).upper(),
        "qty": str(position.get("qty", "")),
        "market_value": _money(position.get("market_value", "0")),
        "cost_basis": _money(position.get("cost_basis", "0")),
        "unrealized_pl": _money(position.get("unrealized_pl", "0")),
        "unrealized_plpc": _pct(position.get("unrealized_plpc")),
        "unrealized_intraday_pl": _money(position.get("unrealized_intraday_pl", "0")),
        "unrealized_intraday_plpc": _pct(position.get("unrealized_intraday_plpc")),
        "current_price": _price(position.get("current_price", "0")),
        "avg_entry_price": _price(position.get("avg_entry_price", "0")),
    }


def _order_snapshot(order: Mapping) -> dict:
    return {
        "symbol": str(order.get("symbol", "")).upper(),
        "side": str(order.get("side", "")),
        "type": str(order.get("type", "")),
        "status": str(order.get("status", "")),
        "qty": str(order.get("qty", "")),
        "notional": str(order.get("notional", "")),
        "limit_price": str(order.get("limit_price", "")),
        "client_order_id": str(order.get("client_order_id", "")),
        "id": str(order.get("id", "")),
    }


def _client_order_component(value: object, *, max_length: int) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", str(value or "").lower()).strip("-")
    return (slug[:max_length].rstrip("-") or "x")


def supervisor_live_client_order_id(
    action: HourlySupervisorAction,
    *,
    generated_at: datetime.datetime,
) -> str:
    """Stable tiny-live broker id for retry-safe supervisor submits."""

    local_day = generated_at.astimezone(CENTRAL).strftime("%Y%m%d")
    raw = "|".join(
        [
            local_day,
            action.sleeve,
            action.symbol.upper(),
            action.action.lower(),
            action.normalized_side(),
            _money(action.notional),
            _price(action.limit_price),
        ]
    )
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:10]
    parts = [
        "ta-tiny",
        local_day,
        _client_order_component(action.sleeve, max_length=8),
        _client_order_component(action.symbol, max_length=6),
        _client_order_component(action.normalized_side(), max_length=4),
        digest,
    ]
    return "-".join(parts)[:48]


def build_portfolio_snapshot(
    *,
    live_account: Mapping,
    paper_account: Mapping,
    live_positions: Sequence[Mapping],
    live_open_orders: Sequence[Mapping],
    paper_positions: Sequence[Mapping] | None = None,
    paper_open_orders: Sequence[Mapping] | None = None,
    dynamic_live_cap: Decimal = BASE_LIVE_CAP,
    market_session: str = "regular",
    candidates: Sequence[CandidateSignal] = (),
) -> dict:
    paper_positions = paper_positions or []
    paper_open_orders = paper_open_orders or []
    live_unrealized = total_unrealized_pl(live_positions)
    paper_unrealized = total_unrealized_pl(paper_positions)
    return {
        "live": {
            "status": live_account.get("status"),
            "buying_power": _money(live_account.get("buying_power", "0")),
            "equity": _money(live_account.get("equity", "0")),
            "portfolio_value": _money(live_account.get("portfolio_value") or live_account.get("equity", "0")),
            "cash": _money(live_account.get("cash", "0")),
            "exposure": _money(live_exposure_from_positions(live_positions)),
            "dynamic_cap": _money(dynamic_live_cap),
            "unused_cap": _money(max(Decimal("0"), dynamic_live_cap - live_exposure_from_positions(live_positions))),
            "unrealized_pl": _money(live_unrealized),
            "positions": [_position_snapshot(position) for position in live_positions],
            "open_orders": [_order_snapshot(order) for order in live_open_orders],
        },
        "paper": {
            "status": paper_account.get("status"),
            "buying_power": _money(paper_account.get("buying_power", "0")),
            "equity": _money(paper_account.get("equity", "0")),
            "portfolio_value": _money(paper_account.get("portfolio_value") or paper_account.get("equity", "0")),
            "cash": _money(paper_account.get("cash", "0")),
            "unrealized_pl": _money(paper_unrealized),
            "positions": [_position_snapshot(position) for position in paper_positions],
            "open_orders": [_order_snapshot(order) for order in paper_open_orders],
        },
        "market_session": market_session,
        "ranked_candidates": [
            {
                "symbol": candidate.symbol,
                "score": str(candidate.score),
                "current_price": _price(candidate.current_price),
                "day_change_pct": _pct(candidate.day_change_pct),
                "volume_ratio": str(candidate.volume_ratio),
                "time_sensitive": candidate.time_sensitive,
                "source": candidate.source,
                "reason": candidate.reason,
            }
            for candidate in candidates
        ],
    }


def validate_hourly_supervisor_actions(
    actions: Sequence[HourlySupervisorAction],
    *,
    current_live_exposure: Decimal,
    config: AlpacaExecutionConfig,
    open_orders: Sequence[Mapping] = (),
) -> list[OrderIssue]:
    issues: list[OrderIssue] = []
    open_keys = {
        (
            str(order.get("symbol", "")).upper(),
            str(order.get("side", "")).lower(),
        )
        for order in open_orders
    }

    for action in actions:
        action_name = action.action.lower()
        order_type = action.order_type.lower()
        account = action.account.lower()
        if action_name == "hold_cash":
            if action.notional < 0:
                issues.append(OrderIssue(action.symbol, "notional cannot be negative"))
            continue
        if account not in {"live", "paper"}:
            issues.append(OrderIssue(action.symbol, "order actions must target live or paper"))
        if action.asset_class.lower() != "stock":
            issues.append(OrderIssue(action.symbol, "only stock orders are allowed"))
        if order_type != "limit":
            issues.append(OrderIssue(action.symbol, "market orders are not allowed"))
        if action.normalized_side() not in {"buy", "sell"}:
            issues.append(OrderIssue(action.symbol, "only buy/sell stock orders are allowed"))
        if action_name not in {"hold", "buy", "reduce", "close", "rotate", "cancel", "hold_cash"}:
            issues.append(OrderIssue(action.symbol, f"unsupported action {action.action}"))
        if action.notional < 0:
            issues.append(OrderIssue(action.symbol, "notional cannot be negative"))
        if action.limit_price <= 0 and action_name != "hold_cash":
            issues.append(OrderIssue(action.symbol, "limit price must be positive"))
        if (action.symbol.upper(), action.normalized_side()) in open_keys:
            issues.append(OrderIssue(action.symbol, "duplicate open order for symbol and side"))

    return issues

def validate_supervisor_live_submit_allowed(
    actions: Sequence[HourlySupervisorAction],
    *,
    risk_envelope_path: str | Path = "config/risk_envelope.yaml",
    promotion_state_path: str | Path = "results/policy/promotion_state.json",
    control_state_path: str | Path = "results/policy/live_control.json",
    current_live_exposure: Decimal = Decimal("0"),
    current_daily_loss_usd: Decimal | None = None,
    current_drawdown_pct: Decimal | None = None,
    live_account: Mapping | None = None,
    live_positions: Sequence[Mapping] = (),
    decision_evidence: Mapping | None = None,
    now: datetime.datetime | None = None,
) -> list[OrderIssue]:
    live_buying_power = None
    if isinstance(live_account, Mapping):
        try:
            live_buying_power = _as_decimal(live_account.get("buying_power"))
        except Exception:
            live_buying_power = None
    result = evaluate_go_live_guard(
        actions=actions,
        risk_envelope_path=risk_envelope_path,
        promotion_state_path=promotion_state_path,
        control_state_path=control_state_path,
        current_live_exposure=current_live_exposure,
        current_daily_loss_usd=current_daily_loss_usd,
        current_drawdown_pct=current_drawdown_pct,
        live_buying_power=live_buying_power,
        live_positions=live_positions,
        decision_evidence=decision_evidence,
        now=now,
    )
    return result.issues


def build_hourly_decision(
    *,
    live_positions: Sequence[Mapping],
    live_open_orders: Sequence[Mapping],
    config: HourlySupervisorConfig,
    candidate_signals: Sequence[CandidateSignal] = (),
    market_session: str = "regular",
    dynamic_live_cap: Decimal = BASE_LIVE_CAP,
    new_buys_suspended_reason: str | None = None,
    live_sleeve: str | None = None,
) -> HourlySupervisorDecision:
    return _build_hourly_decision(
        live_positions=live_positions,
        live_open_orders=live_open_orders,
        config=config,
        candidate_signals=candidate_signals,
        market_session=market_session,
        dynamic_live_cap=dynamic_live_cap,
        new_buys_suspended_reason=new_buys_suspended_reason,
        can_trade_session=can_trade_session,
        positive_decimal_or_none=_positive_decimal_or_none,
        live_sleeve=live_sleeve or LIVE_AGGRESSIVE_SLEEVE,
    )


def build_hourly_evidence(
    *,
    live_account: Mapping,
    paper_account: Mapping,
    live_positions: Sequence[Mapping],
    live_open_orders: Sequence[Mapping],
    previous_packet: Path | None = None,
    overnight_validation: Mapping | None = None,
    premarket_brief_validation: Mapping | None = None,
) -> dict:
    return _build_hourly_evidence(
        live_account=live_account,
        paper_account=paper_account,
        live_positions=live_positions,
        live_open_orders=live_open_orders,
        previous_packet=previous_packet,
        overnight_validation=overnight_validation,
        premarket_brief_validation=premarket_brief_validation,
    )


def serialize_hourly_decision(
    decision: HourlySupervisorDecision,
    *,
    recent_packets: Sequence[Mapping] = (),
    alert_throttle_window: datetime.timedelta = DEFAULT_ALERT_THROTTLE_WINDOW,
) -> dict:
    return _serialize_hourly_decision(
        decision,
        recent_packets=recent_packets,
        alert_throttle_window=alert_throttle_window,
        classify_alert=classify_supervisor_alert,
        alert_fingerprint=supervisor_alert_fingerprint,
        should_throttle_alert=should_throttle_supervisor_alert,
        render_alert_email=render_supervisor_alert_email,
        client_order_id=supervisor_live_client_order_id,
        is_order_action=is_order_action,
    )


def write_hourly_decision_packet(
    decision: HourlySupervisorDecision,
    *,
    output_dir: str | Path = "results/hourly_supervisor",
    recent_packets: Sequence[Mapping] = (),
    alert_throttle_window: datetime.timedelta = DEFAULT_ALERT_THROTTLE_WINDOW,
) -> Path:
    return _write_hourly_decision_packet(
        decision,
        serialize_decision=serialize_hourly_decision,
        output_dir=output_dir,
        recent_packets=recent_packets,
        alert_throttle_window=alert_throttle_window,
    )
