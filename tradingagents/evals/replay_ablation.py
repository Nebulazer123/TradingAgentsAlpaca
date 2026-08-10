"""Replay and ablation planning for strategy/research overlays.

The packet built here is a test plan, not a backtest engine. It formalizes the
arms, metrics, and authority limits that must exist before advisory sources or
TradingAgents roles can earn more influence.
"""

from __future__ import annotations

import datetime
from collections.abc import Callable, Mapping, Sequence
from decimal import Decimal
from typing import Any, Literal

from tradingagents.agents.utils.rating import parse_rating
from tradingagents.evals.agent_intelligence_ledger import RATING_PROBABILITY, AgentForecast
from tradingagents.schemas.research import ResearchBatchRunPacket

FORBIDDEN_EFFECTS = [
    "create_trade_intent",
    "size_position",
    "submit_order",
    "promote_sleeve",
    "waive_live_gate",
]

POINT_IN_TIME_AUDIT_ROWS: tuple[dict[str, Any], ...] = (
    {
        "area": "price_ohlcv",
        "file": "tradingagents/dataflows/y_finance.py",
        "symbols": ["get_YFin_data_online", "get_stock_stats_indicators_window"],
        "status": "bounded",
        "evidence": "start_date/end_date or curr_date window is passed into the fetch/filter path.",
        "next_action": "Keep pinned in walk-forward fixtures.",
    },
    {
        "area": "technical_indicators",
        "file": "tradingagents/dataflows/stockstats_utils.py",
        "symbols": ["load_ohlcv", "filter_financials_by_date"],
        "status": "bounded_with_fetch_window_caveat",
        "evidence": "Rows after curr_date are filtered; the upstream fetch still uses today's date for cache fill.",
        "next_action": "For strict historical replay, fill cache from an explicit end date instead of wall clock.",
    },
    {
        "area": "fundamentals_yfinance_alpha_vantage",
        "file": "tradingagents/dataflows/y_finance.py; tradingagents/dataflows/alpha_vantage_fundamentals.py",
        "symbols": ["get_balance_sheet", "get_cashflow", "get_income_statement"],
        "status": "bounded",
        "evidence": "Financial statement dates after curr_date are filtered.",
        "next_action": "Add fixture tests that inject future-dated statement columns/reports.",
    },
    {
        "area": "fundamentals_sec_fmp_eodhd",
        "file": "tradingagents/dataflows/decision_vendor_adapters.py",
        "symbols": ["get_sec_fundamentals", "get_fmp_fundamentals", "get_eodhd_fundamentals"],
        "status": "bounded_rendered",
        "evidence": "Rendered analyst payloads drop rows/date-keyed sections after curr_date; raw vendor packets stay archived as latest evidence.",
        "next_action": "Keep profile/latest-only fields low-authority in replay and rely on dated filings/statements for scoring.",
    },
    {
        "area": "news",
        "file": "tradingagents/dataflows/decision_vendor_adapters.py",
        "symbols": ["get_marketaux_news", "get_finnhub_news", "get_newsapi_news", "get_eodhd_news", "get_alpaca_news_adapter", "get_tiingo_news_adapter"],
        "status": "bounded",
        "evidence": "Ticker news adapters pass start_date/end_date to vendors.",
        "next_action": "Keep fixture coverage for vendor date windows and stale-packet downranking.",
    },
    {
        "area": "google_news_rss",
        "file": "tradingagents/dataflows/decision_vendor_adapters.py",
        "symbols": ["get_google_news", "get_google_global_news"],
        "status": "bounded",
        "evidence": "RSS items are filtered by pubDate between start_date and end_date before rendering/scoring.",
        "next_action": "Keep Google News low-authority/fallback because RSS coverage and timestamps are not institutional-grade.",
    },
    {
        "area": "macro",
        "file": "tradingagents/dataflows/decision_vendor_adapters.py",
        "symbols": ["get_fred_macro_context", "get_bls_macro_context", "get_bea_macro_context", "get_eia_energy_macro_context", "get_treasury_macro_context"],
        "status": "bounded",
        "evidence": "FRED/BLS/BEA use date/year windows; EIA uses monthly start/end; Treasury uses record_date filters.",
        "next_action": "Keep macro replay fixtures pinned to explicit curr_date/as_of windows.",
    },
    {
        "area": "social_sentiment",
        "file": "tradingagents/dataflows/decision_vendor_adapters.py; tradingagents/dataflows/reddit.py; tradingagents/dataflows/stocktwits.py",
        "symbols": ["get_stocktwits_sentiment_context", "get_reddit_sentiment_context"],
        "status": "live_only_unscored_in_replay",
        "evidence": "Public Reddit/StockTwits routes return recent/live context; historical replay excludes them from scoring instead of treating them as as-of data.",
        "next_action": "Use social overlays for live/premarket anomaly context only unless a timestamped archive is added.",
    },
    {
        "area": "current_date_helper",
        "file": "tradingagents/dataflows/utils.py",
        "symbols": ["get_current_date"],
        "status": "wall_clock",
        "evidence": "Uses local date.today(); this is correct for live local runs but not a replay clock.",
        "next_action": "Historical replay must pass explicit trade_date and avoid calling this helper for as-of.",
    },
)


def _decimal(value: Any, default: str = "0") -> Decimal:
    try:
        if value is None or value == "":
            return Decimal(default)
        parsed = Decimal(str(value))
        return parsed if parsed.is_finite() else Decimal(default)
    except Exception:
        return Decimal(default)


def _finite_decimal_or_none(value: Any) -> Decimal | None:
    try:
        if value is None or value == "":
            return None
        parsed = Decimal(str(value))
    except Exception:
        return None
    return parsed if parsed.is_finite() else None


def _rating_for_probability(probability: Any) -> str | None:
    value = _decimal(probability, "0.50")
    for rating, rating_probability in RATING_PROBABILITY.items():
        if value == rating_probability:
            return str(rating)
    return None


def _brier(probability: Decimal, outcome: bool) -> Decimal:
    target = Decimal("1") if outcome else Decimal("0")
    return ((probability - target) ** 2).quantize(Decimal("0.0001"))


def point_in_time_audit_table() -> list[dict[str, Any]]:
    """Return the static point-in-time audit rows for the current dataflow map."""

    return [dict(row) for row in POINT_IN_TIME_AUDIT_ROWS]


def calibrate_rating_probabilities(
    forecasts: Sequence[AgentForecast],
    *,
    prior_weight: int = 10,
    min_resolved: int = 1,
) -> dict[str, Any]:
    """Calibrate rating probabilities from resolved ledger forecasts.

    This is deliberately read-only and shrinkage-heavy. Sparse ratings stay
    close to the hardcoded prior so one lucky/unlucky sample cannot overfit the
    automation loop.
    """

    rows: dict[str, dict[str, Any]] = {
        rating: {
            "rating": rating,
            "prior_probability": str(probability),
            "resolved_count": 0,
            "wins": 0,
            "brier_before_total": Decimal("0"),
        }
        for rating, probability in RATING_PROBABILITY.items()
    }
    ignored_count = 0
    for forecast in forecasts:
        if not forecast.resolved or forecast.outcome is None:
            continue
        rating = _rating_for_probability(forecast.probability)
        if rating is None:
            ignored_count += 1
            continue
        prior_probability = RATING_PROBABILITY[rating]
        row = rows[rating]
        row["resolved_count"] += 1
        if forecast.outcome is True:
            row["wins"] += 1
        row["brier_before_total"] += _brier(prior_probability, bool(forecast.outcome))

    calibrated: dict[str, dict[str, Any]] = {}
    total_resolved = 0
    total_brier_before = Decimal("0")
    total_brier_after = Decimal("0")
    for rating, row in rows.items():
        prior_probability = RATING_PROBABILITY[rating]
        resolved_count = int(row["resolved_count"])
        wins = int(row["wins"])
        total_resolved += resolved_count
        if resolved_count >= max(1, int(min_resolved)):
            calibrated_probability = (
                Decimal(wins) + (prior_probability * Decimal(max(0, int(prior_weight))))
            ) / Decimal(resolved_count + max(0, int(prior_weight)))
            state = "calibrated_with_shrinkage"
        else:
            calibrated_probability = prior_probability
            state = "insufficient_history"
        calibrated_probability = calibrated_probability.quantize(Decimal("0.0001"))
        brier_before = row["brier_before_total"]
        brier_after = Decimal("0")
        if resolved_count:
            for forecast in forecasts:
                if (
                    forecast.resolved
                    and forecast.outcome is not None
                    and _rating_for_probability(forecast.probability) == rating
                ):
                    brier_after += _brier(calibrated_probability, bool(forecast.outcome))
        total_brier_before += brier_before
        total_brier_after += brier_after
        calibrated[rating] = {
            "prior_probability": str(prior_probability),
            "calibrated_probability": str(calibrated_probability),
            "resolved_count": resolved_count,
            "wins": wins,
            "empirical_win_rate": (
                str((Decimal(wins) / Decimal(resolved_count)).quantize(Decimal("0.0001")))
                if resolved_count
                else None
            ),
            "average_brier_before": (
                str((brier_before / Decimal(resolved_count)).quantize(Decimal("0.0001")))
                if resolved_count
                else None
            ),
            "average_brier_after": (
                str((brier_after / Decimal(resolved_count)).quantize(Decimal("0.0001")))
                if resolved_count
                else None
            ),
            "state": state,
        }

    return {
        "rating_probabilities": calibrated,
        "resolved_rating_forecast_count": total_resolved,
        "ignored_resolved_forecast_count": ignored_count,
        "prior_weight": max(0, int(prior_weight)),
        "min_resolved": max(1, int(min_resolved)),
        "average_brier_before": (
            str((total_brier_before / Decimal(total_resolved)).quantize(Decimal("0.0001")))
            if total_resolved
            else None
        ),
        "average_brier_after": (
            str((total_brier_after / Decimal(total_resolved)).quantize(Decimal("0.0001")))
            if total_resolved
            else None
        ),
        "execution_authority": "none",
        "forbidden_effects": FORBIDDEN_EFFECTS,
    }


def _symbols(value: str | list[str] | tuple[str, ...]) -> list[str]:
    if isinstance(value, str):
        raw = value.split(",")
    else:
        raw = list(value)
    return [str(symbol).strip().upper() for symbol in raw if str(symbol).strip()]


def _iso_date(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.date.fromisoformat(text[:10]).isoformat()
    except ValueError:
        return text


def _rate(value: Decimal | int, denominator: int) -> str | None:
    if denominator <= 0:
        return None
    return (Decimal(value) / Decimal(denominator)).quantize(Decimal("0.0001")).to_eng_string()


def _metric_decimal(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return value.quantize(Decimal("0.0001")).to_eng_string()


def _return_pct(start_price: Any, end_price: Any) -> Decimal | None:
    start = _finite_decimal_or_none(start_price)
    end = _finite_decimal_or_none(end_price)
    if start is None or end is None or start <= 0:
        return None
    return ((end - start) / start * Decimal("100")).quantize(Decimal("0.01"))


def _relative_action_return(action: str, relative_return: Decimal) -> Decimal:
    normalized = action.strip().lower()
    if normalized == "buy":
        return relative_return
    if normalized == "sell":
        return -relative_return
    if normalized == "hold":
        return -abs(relative_return)
    return Decimal("0")


def _cost_model_packet(
    *,
    commission_bps: Decimal,
    half_spread_bps: Decimal,
    slippage_bps: Decimal,
    latency_bps_per_second: Decimal,
    round_trip_sides: int,
) -> dict[str, Any]:
    return {
        "commission_bps": commission_bps.quantize(Decimal("0.0001")).to_eng_string(),
        "half_spread_bps": half_spread_bps.quantize(Decimal("0.0001")).to_eng_string(),
        "slippage_bps": slippage_bps.quantize(Decimal("0.0001")).to_eng_string(),
        "latency_bps_per_second": latency_bps_per_second.quantize(Decimal("0.0001")).to_eng_string(),
        "round_trip_sides": max(1, int(round_trip_sides)),
    }


def _decision_latency_seconds(row: Mapping[str, Any], decision: Mapping[str, Any]) -> Decimal:
    for source in (decision, row):
        latency = _finite_decimal_or_none(source.get("latency_seconds"))
        if latency is not None:
            return max(Decimal("0"), latency)
    return Decimal("0")


def _transaction_cost_return(
    action: str,
    *,
    row: Mapping[str, Any],
    decision: Mapping[str, Any],
    commission_bps: Decimal,
    half_spread_bps: Decimal,
    slippage_bps: Decimal,
    latency_bps_per_second: Decimal,
    round_trip_sides: int,
) -> Decimal:
    if action.strip().lower() not in {"buy", "sell"}:
        return Decimal("0")
    latency_seconds = _decision_latency_seconds(row, decision)
    per_side_bps = (
        commission_bps
        + half_spread_bps
        + slippage_bps
        + (latency_seconds * latency_bps_per_second)
    )
    return (
        per_side_bps
        * Decimal(max(1, int(round_trip_sides)))
        / Decimal("10000")
    ).quantize(Decimal("0.0001"))


def _walk_forward_outcome(action: str, relative_return: Decimal, hold_band: Decimal) -> bool:
    normalized = action.strip().lower()
    if normalized == "buy":
        return relative_return > Decimal("0")
    if normalized == "sell":
        return relative_return < Decimal("0")
    if normalized == "hold":
        return abs(relative_return) <= hold_band
    return False


def _walk_forward_arm_decision(
    row: dict[str, Any],
    arm_id: str,
) -> dict[str, Any] | None:
    if arm_id == "deterministic_sleeve_only":
        return {
            "action": row.get("baseline_action") or row.get("action"),
            "probability": row.get("baseline_probability") or row.get("probability"),
        }
    overlays = row.get("overlays")
    if not isinstance(overlays, dict):
        return None
    overlay = overlays.get(arm_id)
    if not isinstance(overlay, dict) or overlay.get("available") is False:
        return None
    return overlay


def _rating_action_and_probability(rating_text: Any) -> tuple[str, Decimal, str]:
    rating = parse_rating(str(rating_text or ""), default="Hold")
    probability = RATING_PROBABILITY.get(rating, RATING_PROBABILITY["Hold"])
    if rating in {"Buy", "Overweight"}:
        action = "buy"
    elif rating in {"Sell", "Underweight"}:
        action = "sell"
    else:
        action = "hold"
    return action, probability, rating


def _packet_as_of(packet: Mapping[str, Any]) -> str | None:
    for key in ("as_of", "trade_date", "decision_date", "generated_at", "created_at", "timestamp"):
        as_of = _iso_date(packet.get(key))
        if as_of:
            return as_of
    return None


PriceLookup = Callable[[str, str, str], tuple[Any, Any] | None]


def build_walk_forward_return_rows_from_overnight_packets(
    overnight_packets: Sequence[Mapping[str, Any]],
    *,
    price_lookup: PriceLookup,
    horizon_days: int = 5,
    benchmark: str = "SPY",
) -> dict[str, Any]:
    """Collect later ticker and benchmark returns for captured overnight decisions."""

    horizon = max(1, int(horizon_days))
    benchmark_symbol = benchmark.strip().upper() or "SPY"
    rows: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    source_packet_refs: list[str] = []

    for packet_index, packet in enumerate(overnight_packets):
        packet_as_of = _packet_as_of(packet)
        packet_ref = str(packet.get("packet_id") or packet.get("packet_path") or f"overnight_packet_{packet_index}")
        source_packet_refs.append(packet_ref)
        ticker_results = packet.get("ticker_results") or []
        if not isinstance(ticker_results, Sequence) or isinstance(ticker_results, (str, bytes)):
            skipped.append({"packet_ref": packet_ref, "reason": "ticker_results_missing_or_not_list"})
            continue
        for result_index, ticker_result in enumerate(ticker_results):
            if not isinstance(ticker_result, Mapping):
                skipped.append(
                    {
                        "packet_ref": packet_ref,
                        "result_index": result_index,
                        "reason": "ticker_result_not_object",
                    }
                )
                continue
            symbol = str(ticker_result.get("symbol", "")).strip().upper()
            as_of = _iso_date(ticker_result.get("as_of") or ticker_result.get("decision_as_of")) or packet_as_of
            if not symbol or not as_of:
                skipped.append(
                    {
                        "packet_ref": packet_ref,
                        "result_index": result_index,
                        "symbol": symbol or None,
                        "as_of": as_of,
                        "reason": "symbol_or_as_of_missing",
                    }
                )
                continue
            if (symbol, as_of) in seen:
                continue
            seen.add((symbol, as_of))
            end_date = (
                datetime.date.fromisoformat(as_of) + datetime.timedelta(days=horizon)
            ).isoformat()
            ticker_prices = price_lookup(symbol, as_of, end_date)
            benchmark_prices = price_lookup(benchmark_symbol, as_of, end_date)
            if ticker_prices is None or benchmark_prices is None:
                skipped.append(
                    {
                        "packet_ref": packet_ref,
                        "symbol": symbol,
                        "as_of": as_of,
                        "end_date": end_date,
                        "reason": "price_lookup_missing",
                        "ticker_price_found": ticker_prices is not None,
                        "benchmark_price_found": benchmark_prices is not None,
                    }
                )
                continue
            actual_return = _return_pct(ticker_prices[0], ticker_prices[1])
            benchmark_return = _return_pct(benchmark_prices[0], benchmark_prices[1])
            if actual_return is None or benchmark_return is None:
                skipped.append(
                    {
                        "packet_ref": packet_ref,
                        "symbol": symbol,
                        "as_of": as_of,
                        "end_date": end_date,
                        "reason": "invalid_price_window",
                    }
                )
                continue
            rows.append(
                {
                    "symbol": symbol,
                    "as_of": as_of,
                    "end_date": end_date,
                    "horizon_days": horizon,
                    "actual_return": actual_return.to_eng_string(),
                    "benchmark_return": benchmark_return.to_eng_string(),
                    "benchmark": benchmark_symbol,
                    "source_packet_ref": packet_ref,
                }
            )

    rows.sort(key=lambda item: (str(item.get("as_of", "")), str(item.get("symbol", ""))))
    generated = datetime.datetime.now(tz=datetime.timezone.utc).isoformat(timespec="seconds")
    return {
        "kind": "walk_forward_return_rows",
        "schema_version": "1.0.0",
        "generated_at": generated,
        "analysis_only": True,
        "can_submit_orders": False,
        "rows": rows,
        "row_count": len(rows),
        "skipped": skipped,
        "skipped_count": len(skipped),
        "source_packet_refs": source_packet_refs,
        "benchmark": benchmark_symbol,
        "horizon_days": horizon,
        "execution_authority": "none",
        "forbidden_effects": FORBIDDEN_EFFECTS,
        "plain_english": (
            "Later ticker and benchmark returns were collected for captured "
            "overnight decisions. Missing price windows were skipped."
        ),
    }


def _return_rows_by_key(
    return_rows: Sequence[Mapping[str, Any]],
) -> tuple[dict[tuple[str, str], Mapping[str, Any]], dict[str, Mapping[str, Any]]]:
    by_symbol_date: dict[tuple[str, str], Mapping[str, Any]] = {}
    by_symbol: dict[str, Mapping[str, Any]] = {}
    for row in return_rows:
        symbol = str(row.get("symbol", "")).strip().upper()
        if not symbol:
            continue
        as_of = _iso_date(row.get("as_of") or row.get("decision_as_of") or row.get("date"))
        if as_of:
            by_symbol_date[(symbol, as_of)] = row
        by_symbol.setdefault(symbol, row)
    return by_symbol_date, by_symbol


def build_walk_forward_fixture_from_overnight_packets(
    overnight_packets: Sequence[Mapping[str, Any]],
    return_rows: Sequence[Mapping[str, Any]],
    *,
    benchmark: str = "SPY",
) -> dict[str, Any]:
    """Convert captured overnight ticker decisions into walk-forward fixture rows.

    Return rows provide later performance. Overnight packets provide the
    fixed-as-of decision. Missing returns are skipped and reported instead of
    fabricating outcomes.
    """

    returns_by_key, returns_by_symbol = _return_rows_by_key(return_rows)
    rows: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    source_packet_refs: list[str] = []
    seen_decision_keys: dict[tuple[str, str], str] = {}

    for packet_index, packet in enumerate(overnight_packets):
        packet_as_of = _packet_as_of(packet)
        packet_ref = str(packet.get("packet_id") or packet.get("packet_path") or f"overnight_packet_{packet_index}")
        source_packet_refs.append(packet_ref)
        ticker_results = packet.get("ticker_results") or []
        if not isinstance(ticker_results, Sequence) or isinstance(ticker_results, (str, bytes)):
            skipped.append(
                {
                    "packet_ref": packet_ref,
                    "reason": "ticker_results_missing_or_not_list",
                }
            )
            continue
        for result_index, ticker_result in enumerate(ticker_results):
            if not isinstance(ticker_result, Mapping):
                skipped.append(
                    {
                        "packet_ref": packet_ref,
                        "result_index": result_index,
                        "reason": "ticker_result_not_object",
                    }
                )
                continue
            symbol = str(ticker_result.get("symbol", "")).strip().upper()
            if not symbol:
                skipped.append(
                    {
                        "packet_ref": packet_ref,
                        "result_index": result_index,
                        "reason": "symbol_missing",
                    }
                )
                continue
            as_of = _iso_date(ticker_result.get("as_of") or ticker_result.get("decision_as_of")) or packet_as_of
            return_row = returns_by_key.get((symbol, as_of or "")) or returns_by_symbol.get(symbol)
            if return_row is None:
                skipped.append(
                    {
                        "packet_ref": packet_ref,
                        "symbol": symbol,
                        "as_of": as_of,
                        "reason": "return_row_missing",
                    }
                )
                continue
            final_as_of = as_of or _iso_date(return_row.get("as_of")) or ""
            dedupe_key = (symbol, final_as_of)
            first_packet_ref = seen_decision_keys.get(dedupe_key)
            if first_packet_ref is not None:
                skipped.append(
                    {
                        "packet_ref": packet_ref,
                        "first_packet_ref": first_packet_ref,
                        "result_index": result_index,
                        "symbol": symbol,
                        "as_of": final_as_of,
                        "reason": "duplicate_symbol_as_of",
                    }
                )
                continue
            seen_decision_keys[dedupe_key] = packet_ref
            action, probability, rating = _rating_action_and_probability(
                ticker_result.get("rating") or ticker_result.get("final_trade_decision")
            )
            actual_return = _decimal(return_row.get("actual_return"), "0")
            benchmark_return = _decimal(return_row.get("benchmark_return"), "0")
            overlays: dict[str, dict[str, str]] = {}
            method = str(ticker_result.get("method", "")).strip()
            status = str(ticker_result.get("status", "")).strip()
            if method == "full_graph" or status == "ok":
                overlays["tradingagents_advisory_overlay"] = {
                    "action": action,
                    "probability": probability.quantize(Decimal("0.0001")).to_eng_string(),
                    "rating": rating,
                }
            rows.append(
                {
                    "symbol": symbol,
                    "as_of": final_as_of,
                    "baseline_action": action,
                    "baseline_probability": probability.quantize(Decimal("0.0001")).to_eng_string(),
                    "actual_return": _metric_decimal(actual_return),
                    "benchmark_return": _metric_decimal(benchmark_return),
                    "source_packet_ref": packet_ref,
                    "source_method": method or status or "unknown",
                    "rating": rating,
                    "benchmark": benchmark.upper(),
                    "overlays": overlays,
                }
            )

    rows.sort(key=lambda item: (str(item.get("as_of", "")), str(item.get("symbol", ""))))
    return {
        "rows": rows,
        "row_count": len(rows),
        "skipped": skipped,
        "skipped_count": len(skipped),
        "duplicate_skipped_count": sum(
            1 for row in skipped if row.get("reason") == "duplicate_symbol_as_of"
        ),
        "source_packet_refs": source_packet_refs,
        "benchmark": benchmark.upper(),
        "execution_authority": "none",
        "forbidden_effects": FORBIDDEN_EFFECTS,
        "plain_english": (
            "Captured overnight decisions were converted into walk-forward "
            "fixture rows only where later returns were supplied; duplicate "
            "symbol/as-of decisions are skipped so calibration is not inflated."
        ),
    }


def _walk_forward_arms() -> list[dict[str, Any]]:
    return [
        _lane(
            "deterministic_sleeve_only",
            description="Baseline: score the deterministic sleeve decision captured in the fixed-as-of row.",
            inputs=["fixed_as_of_fixture_rows", "baseline_action", "actual_return", "benchmark_return"],
            authority="baseline_only",
        ),
        _lane(
            "official_context_overlay",
            description="Score official-source overlay decisions only where the fixture captured them at the same as-of time.",
            inputs=["fixed_as_of_fixture_rows", "official_context_overlay"],
            authority="advisory_replay_only",
        ),
        _lane(
            "news_social_crawler_overlay",
            description="Score broad news/crawler overlays where timestamped fixtures exist; public social live-only context stays unavailable.",
            inputs=["fixed_as_of_fixture_rows", "news_social_crawler_overlay"],
            authority="advisory_replay_only",
        ),
        _lane(
            "tradingagents_advisory_overlay",
            description="Score TradingAgents advisory role outputs captured in the fixed-as-of fixture.",
            inputs=["fixed_as_of_fixture_rows", "tradingagents_advisory_overlay"],
            authority="advisory_replay_only",
        ),
        _lane(
            "deep_research_methodology_overlay",
            description="Score Deep Research methodology overlays only when the fixture contains a timestamped captured decision.",
            inputs=["fixed_as_of_fixture_rows", "deep_research_methodology_overlay"],
            authority="advisory_replay_only",
        ),
    ]


def _lane(
    lane_id: str,
    *,
    description: str,
    inputs: list[str],
    authority: str,
) -> dict[str, Any]:
    return {
        "lane_id": lane_id,
        "description": description,
        "inputs": inputs,
        "authority": authority,
        "output": "scored_replay_rows_only",
        "forbidden_effects": FORBIDDEN_EFFECTS,
    }


def build_replay_ablation_plan_packet(
    *,
    candidate_symbols: str | list[str] | tuple[str, ...] = "",
    sleeve: str = "pullback-support",
    benchmark: str = "SPY",
    minimum_decisions_per_arm: int = 30,
    holdout_window: str = "next_unseen_paper_cohort",
) -> ResearchBatchRunPacket:
    symbols = _symbols(candidate_symbols)
    generated = datetime.datetime.now(tz=datetime.timezone.utc).isoformat(timespec="seconds")
    return ResearchBatchRunPacket(
        batch_id=f"replay-ablation-{sleeve}-{generated}",
        status="success",
        candidate_symbols=symbols,
        orchestration_lanes=[
            _lane(
                "deterministic_sleeve_only",
                description="Baseline: run the sleeve from formal feature packets only.",
                inputs=[
                    "candidate_packet",
                    "feature_packet",
                    "risk_gate_packet",
                    "broker_cost_model",
                ],
                authority="baseline_only",
            ),
            _lane(
                "official_context_overlay",
                description="Add SEC/FRED/BLS/BEA/EIA/Treasury context as veto/downrank-only overlays.",
                inputs=[
                    "official_source_evidence_packets",
                    "release_calendar_packets",
                ],
                authority="advisory_veto_or_downrank_only",
            ),
            _lane(
                "news_social_crawler_overlay",
                description="Add broad news, Reddit/social, and crawler context as anomaly flags only.",
                inputs=[
                    "provider_bundle_packets",
                    "reddit_watchlist_packets",
                    "social_watchlist_packets",
                    "crawler_run_packets",
                ],
                authority="advisory_only",
            ),
            _lane(
                "tradingagents_advisory_overlay",
                description="Add schema-constrained TradingAgents role outputs and ledger weights.",
                inputs=[
                    "agent_intelligence_ledger",
                    "tradingagents_role_memos",
                    "contradiction_reports",
                ],
                authority="advisory_only",
            ),
            _lane(
                "deep_research_methodology_overlay",
                description="Add ChatGPT Deep Research recommendations as implementation/review context.",
                inputs=[
                    "chatgpt_deep_research_protocol_packet",
                    "captured_deep_research_reports",
                    "strategy_methodology_cards",
                ],
                authority="advisory_only",
            ),
        ],
        quality_gates={
            "sleeve": sleeve,
            "benchmark": benchmark.upper(),
            "holdout_window": holdout_window,
            "minimum_decisions_per_arm": int(minimum_decisions_per_arm),
            "required_metrics": [
                "directional_accuracy",
                "relative_return_vs_benchmark",
                "max_drawdown",
                "false_positive_rate",
                "token_or_api_cost_per_useful_signal",
            ],
            "required_controls": [
                "fixed_as_of_dataset",
                "same_candidate_universe_per_arm",
                "same_cost_model_per_arm",
                "no_live_orders",
                "all_hold_cash_decisions_recorded",
            ],
            "forbidden_success_criteria": [
                "submit_order",
                "promote_sleeve",
                "waive_live_gate",
                "ignore_stale_data",
                "hide_failed_runs",
            ],
            "plain_english": (
                "This compares the boring baseline against each extra research "
                "layer. If an extra layer does not beat the baseline after costs "
                "and false positives, it does not earn influence."
            ),
        },
        fallback_actions=[
            "If a source is unavailable, mark that arm partial and keep the baseline.",
            "If replay rows are too few, do not infer agent/source skill yet.",
            "If overlay data is stale, score it as unavailable rather than guessing.",
        ],
        execution_authority="none",
        forbidden_effects=FORBIDDEN_EFFECTS,
    )


def build_walk_forward_replay_packet(
    fixture_rows: Sequence[Mapping[str, Any]],
    *,
    candidate_symbols: str | list[str] | tuple[str, ...] = "",
    sleeve: str = "pullback-support",
    benchmark: str = "SPY",
    minimum_decisions_per_arm: int = 10,
    hold_band: str | Decimal = "0.0025",
    commission_bps: str | Decimal = "0",
    half_spread_bps: str | Decimal = "0",
    slippage_bps: str | Decimal = "0",
    latency_bps_per_second: str | Decimal = "0",
    round_trip_sides: int = 2,
) -> ResearchBatchRunPacket:
    """Score fixed-as-of walk-forward fixture rows without touching execution.

    The harness is intentionally fixture-first. It does not fetch live data,
    submit orders, or infer unavailable overlays. Rows missing an overlay are
    counted as unavailable so advisory lanes must earn influence with real
    timestamped evidence.
    """

    requested_symbols = _symbols(candidate_symbols)
    requested_symbol_set = set(requested_symbols)
    hold_band_decimal = abs(_decimal(hold_band, "0.0025"))
    commission_bps_decimal = max(Decimal("0"), _decimal(commission_bps, "0"))
    half_spread_bps_decimal = max(Decimal("0"), _decimal(half_spread_bps, "0"))
    slippage_bps_decimal = max(Decimal("0"), _decimal(slippage_bps, "0"))
    latency_bps_decimal = max(Decimal("0"), _decimal(latency_bps_per_second, "0"))
    cost_model = _cost_model_packet(
        commission_bps=commission_bps_decimal,
        half_spread_bps=half_spread_bps_decimal,
        slippage_bps=slippage_bps_decimal,
        latency_bps_per_second=latency_bps_decimal,
        round_trip_sides=round_trip_sides,
    )
    validation_errors: list[str] = []
    normalized_rows: list[dict[str, Any]] = []
    discovered_symbols: list[str] = []

    for index, raw_row in enumerate(fixture_rows):
        if not isinstance(raw_row, Mapping):
            validation_errors.append(f"row {index} is not an object")
            continue
        row = dict(raw_row)
        symbol = str(row.get("symbol", "")).strip().upper()
        as_of = _iso_date(row.get("as_of"))
        if not symbol:
            validation_errors.append(f"row {index} missing symbol")
            continue
        if not as_of:
            validation_errors.append(f"row {index} missing as_of")
            continue
        if requested_symbol_set and symbol not in requested_symbol_set:
            continue
        row["symbol"] = symbol
        row["as_of"] = as_of
        normalized_rows.append(row)
        if symbol not in discovered_symbols:
            discovered_symbols.append(symbol)

    normalized_rows.sort(key=lambda item: (str(item.get("as_of", "")), str(item.get("symbol", ""))))
    arms = _walk_forward_arms()
    metrics: list[dict[str, Any]] = []
    scored_row_sample: list[dict[str, Any]] = []
    for arm in arms:
        arm_id = arm["lane_id"]
        scored_count = 0
        unavailable_count = 0
        hit_count = 0
        false_positive_count = 0
        brier_total = Decimal("0")
        action_return_total = Decimal("0")
        gross_action_return_total = Decimal("0")
        relative_return_total = Decimal("0")
        transaction_cost_total = Decimal("0")
        latency_seconds_total = Decimal("0")
        for row in normalized_rows:
            decision = _walk_forward_arm_decision(row, arm_id)
            action = str((decision or {}).get("action", "")).strip().lower()
            if action not in {"buy", "hold", "sell"}:
                unavailable_count += 1
                continue
            probability = _decimal((decision or {}).get("probability"), "0.50")
            actual_return = _decimal(row.get("actual_return"), "0")
            benchmark_return = _decimal(row.get("benchmark_return"), "0")
            relative_return = actual_return - benchmark_return
            outcome = _walk_forward_outcome(action, relative_return, hold_band_decimal)
            gross_action_return = _relative_action_return(action, relative_return)
            latency_seconds = _decision_latency_seconds(row, decision or {})
            transaction_cost = _transaction_cost_return(
                action,
                row=row,
                decision=decision or {},
                commission_bps=commission_bps_decimal,
                half_spread_bps=half_spread_bps_decimal,
                slippage_bps=slippage_bps_decimal,
                latency_bps_per_second=latency_bps_decimal,
                round_trip_sides=round_trip_sides,
            )
            action_return = gross_action_return - transaction_cost
            scored_count += 1
            if outcome:
                hit_count += 1
            if action in {"buy", "sell"} and not outcome:
                false_positive_count += 1
            brier = _brier(probability, outcome)
            brier_total += brier
            action_return_total += action_return
            gross_action_return_total += gross_action_return
            relative_return_total += relative_return
            transaction_cost_total += transaction_cost
            latency_seconds_total += latency_seconds
            if len(scored_row_sample) < 25:
                scored_row_sample.append(
                    {
                        "arm_id": arm_id,
                        "symbol": row["symbol"],
                        "as_of": row["as_of"],
                        "action": action,
                        "probability": probability.quantize(Decimal("0.0001")).to_eng_string(),
                        "actual_return": _metric_decimal(actual_return),
                        "benchmark_return": _metric_decimal(benchmark_return),
                        "relative_return": _metric_decimal(relative_return),
                        "gross_action_relative_return": _metric_decimal(gross_action_return),
                        "transaction_cost": _metric_decimal(transaction_cost),
                        "net_action_relative_return": _metric_decimal(action_return),
                        "action_relative_return": _metric_decimal(action_return),
                        "latency_seconds": _metric_decimal(latency_seconds),
                        "outcome": outcome,
                        "brier": _metric_decimal(brier),
                    }
                )
        metrics.append(
            {
                "arm_id": arm_id,
                "scored_count": scored_count,
                "unavailable_count": unavailable_count,
                "directional_hit_count": hit_count,
                "directional_accuracy": _rate(hit_count, scored_count),
                "false_positive_count": false_positive_count,
                "false_positive_rate": _rate(false_positive_count, scored_count),
                "average_brier": _rate(brier_total, scored_count),
                "average_relative_return_vs_benchmark": _rate(relative_return_total, scored_count),
                "average_gross_action_relative_return": _rate(gross_action_return_total, scored_count),
                "average_transaction_cost": _rate(transaction_cost_total, scored_count),
                "average_latency_seconds": _rate(latency_seconds_total, scored_count),
                "average_action_relative_return": _rate(action_return_total, scored_count),
                "sample_floor_met": scored_count >= int(minimum_decisions_per_arm),
                "status": "scored" if scored_count else "unavailable",
                "authority": arm["authority"],
            }
        )

    baseline_metric = next(
        (row for row in metrics if row["arm_id"] == "deterministic_sleeve_only"),
        None,
    )
    baseline_average = _finite_decimal_or_none(
        (baseline_metric or {}).get("average_action_relative_return")
    )
    for metric in metrics:
        metric["baseline_arm_id"] = "deterministic_sleeve_only"
        if baseline_average is None:
            metric["net_edge_vs_baseline"] = None
            metric["beats_baseline_after_costs"] = None
            continue
        arm_average = _finite_decimal_or_none(metric.get("average_action_relative_return"))
        if arm_average is None:
            metric["net_edge_vs_baseline"] = None
            metric["beats_baseline_after_costs"] = None
            continue
        edge = arm_average - baseline_average
        metric["net_edge_vs_baseline"] = _metric_decimal(edge)
        metric["beats_baseline_after_costs"] = edge >= Decimal("0")

    minimum_decisions = max(1, int(minimum_decisions_per_arm))
    baseline_scored_count = next(
        (row["scored_count"] for row in metrics if row["arm_id"] == "deterministic_sleeve_only"),
        0,
    )
    sample_floor_met = baseline_scored_count >= minimum_decisions
    blockers: list[str] = []
    if validation_errors:
        blockers.append(f"validation_errors={len(validation_errors)}")
    if not sample_floor_met:
        blockers.append(
            f"minimum_decisions_per_arm not met for baseline: {baseline_scored_count}/{minimum_decisions}"
        )
    status: Literal["success", "partial", "failed"]
    if not normalized_rows:
        status = "failed"
    elif blockers:
        status = "partial"
    else:
        status = "success"

    generated = datetime.datetime.now(tz=datetime.timezone.utc).isoformat(timespec="seconds")
    return ResearchBatchRunPacket(
        batch_id=f"walk-forward-{sleeve}-{generated}",
        status=status,
        candidate_symbols=requested_symbols or discovered_symbols,
        orchestration_lanes=arms,
        quality_gates={
            "sleeve": sleeve,
            "benchmark": benchmark.upper(),
            "walk_forward_row_count": len(normalized_rows),
            "minimum_decisions_per_arm": minimum_decisions,
            "sample_floor_met": sample_floor_met,
            "hold_band": hold_band_decimal.quantize(Decimal("0.0001")).to_eng_string(),
            "cost_model": cost_model,
            "walk_forward_metrics": metrics,
            "scored_row_sample": scored_row_sample,
            "validation_errors": validation_errors[:50],
            "required_controls": [
                "fixed_as_of_dataset",
                "same_candidate_universe_per_arm",
                "same_cost_model_per_arm",
                "no_live_orders",
                "unavailable_overlays_are_not_guessed",
            ],
            "point_in_time_audit_statuses": {
                row["area"]: row["status"] for row in point_in_time_audit_table()
            },
            "plain_english": (
                "This scores captured fixed-as-of decisions against later returns. "
                "It is evidence for which advisory layers deserve influence; it is "
                "not an execution signal."
            ),
        },
        fallback_actions=[
            "If a fixture row is missing an overlay, count that overlay unavailable.",
            "If the baseline sample floor is not met, keep live influence unchanged.",
            "If public social evidence lacks timestamped archives, keep it live-only advisory.",
        ],
        blockers=blockers,
        execution_authority="none",
        forbidden_effects=FORBIDDEN_EFFECTS,
    )


def build_decision_quality_report_packet(
    forecasts: Sequence[AgentForecast],
    *,
    candidate_symbols: str | list[str] | tuple[str, ...] = "",
    sleeve: str = "pullback-support",
    benchmark: str = "SPY",
    prior_weight: int = 10,
    min_resolved: int = 1,
) -> ResearchBatchRunPacket:
    """Build the first P2 decision-quality packet.

    This packet does not run the graph or submit orders. It makes replay
    readiness visible: which data routes are safe for historical as-of use, and
    what the resolved ledger says about the current hardcoded rating
    probabilities.
    """

    symbols = _symbols(candidate_symbols)
    generated = datetime.datetime.now(tz=datetime.timezone.utc).isoformat(timespec="seconds")
    audit_rows = point_in_time_audit_table()
    calibration = calibrate_rating_probabilities(
        forecasts,
        prior_weight=prior_weight,
        min_resolved=min_resolved,
    )
    gap_count = sum(1 for row in audit_rows if str(row.get("status", "")).startswith("gap"))
    mixed_count = sum(1 for row in audit_rows if row.get("status") == "mixed")
    return ResearchBatchRunPacket(
        batch_id=f"decision-quality-{sleeve}-{generated}",
        status="partial" if gap_count or mixed_count else "success",
        candidate_symbols=symbols,
        orchestration_lanes=[
            _lane(
                "point_in_time_audit",
                description="Audit analyst data routes for historical as-of safety before walk-forward scoring.",
                inputs=["dataflows", "agent_tool_date_arguments", "decision_vendor_adapters"],
                authority="analysis_only",
            ),
            _lane(
                "rating_probability_calibration",
                description="Calibrate 5-tier rating probabilities from resolved Agent Intelligence Ledger forecasts with shrinkage.",
                inputs=["agent_intelligence_ledger_resolved_forecasts"],
                authority="advisory_only",
            ),
            _lane(
                "walk_forward_harness_next",
                description="Next step: replay TradingAgentsGraph over fixed as-of historical cohorts after gap routes are filtered or marked partial.",
                inputs=["fixed_as_of_dataset", "same_candidate_universe_per_arm", "same_cost_model_per_arm"],
                authority="not_yet_order_wired",
            ),
        ],
        quality_gates={
            "sleeve": sleeve,
            "benchmark": benchmark.upper(),
            "point_in_time_audit": audit_rows,
            "point_in_time_gap_count": gap_count,
            "point_in_time_mixed_count": mixed_count,
            "rating_calibration": calibration,
            "required_before_live_influence": [
                "historical replay must pass explicit trade_date/as_of",
                "latest-fetch routes must be filtered or excluded from replay scoring",
                "calibration remains advisory until min sample floors are met",
                "no order path consumes this packet directly",
            ],
            "next_patch_set": [
                "add walk-forward CLI over fixed as-of fixture cohorts",
            ],
        },
        fallback_actions=[
            "If the ledger has no resolved rating forecasts, keep prior probabilities.",
            "If a data route is latest-only, score that overlay as unavailable in historical replay.",
            "If calibration worsens Brier on sparse samples, keep the prior probability.",
        ],
        execution_authority="none",
        forbidden_effects=FORBIDDEN_EFFECTS,
    )
