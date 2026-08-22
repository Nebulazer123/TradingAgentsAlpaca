"""Agent Intelligence Ledger.

The ledger turns TradingAgents role outputs into scoreable forecasts and later
resolves them against market outcomes. It measures which agents are actually
useful by setup, regime, symbol, sector, and evidence type.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field, replace
from decimal import Decimal
from pathlib import Path
from typing import Any

from tradingagents.agents.utils.rating import parse_rating
from tradingagents.evals.resolution_quality import (
    DEFER_INVALID_WINDOW,
    LABEL_QUALITY_DEGRADED,
    LABEL_QUALITY_HIGH,
    LABEL_QUALITY_SUSPECT,
    STATUS_DEFERRED,
    STATUS_RESOLVABLE,
    ResolutionQualityReport,
    WindowLookup,
    audit_resolution_window,
)

UTC = datetime.timezone.utc
DEFAULT_LEDGER_PATH = Path("results/agent_intelligence/ledger.jsonl")
DEFAULT_SUMMARY_PATH = Path("results/agent_intelligence/summary.json")
DEFAULT_RATING_CALIBRATION_PATH = Path("results/agent_intelligence/rating_calibration.json")
DEFAULT_BENCHMARK = "SPY"
DEFAULT_AGENT_WEIGHT_FLOOR = Decimal("0.50")
DEFAULT_AGENT_WEIGHT_CEILING = Decimal("1.50")
DEFER_INVALID_FORECAST_TIMESTAMPS = "invalid_forecast_timestamps"
LEDGER_FORBIDDEN_EFFECTS = (
    "submit_order",
    "waive_live_gate",
    "promote_sleeve",
    "ignore_risk_envelope",
)


AGENT_REPORT_KEYS = {
    "market_analyst": "market",
    "sentiment_analyst": "sentiment",
    "news_analyst": "news",
    "fundamentals_analyst": "fundamentals",
}
RATING_PROBABILITY = {
    "Buy": Decimal("0.66"),
    "Overweight": Decimal("0.58"),
    "Hold": Decimal("0.50"),
    "Underweight": Decimal("0.42"),
    "Sell": Decimal("0.34"),
}
MIN_CALIBRATED_RATING_SAMPLES = 3
BULLISH_WORDS = (
    "bullish",
    "positive",
    "upside",
    "breakout",
    "outperform",
    "strong momentum",
    "accumulation",
)
BEARISH_WORDS = (
    "bearish",
    "negative",
    "downside",
    "selloff",
    "underperform",
    "weak momentum",
    "falling knife",
)


@dataclass(frozen=True)
class AgentForecast:
    forecast_id: str
    agent: str
    ticker: str
    claim: str
    forecast_type: str
    horizon: str
    probability: str
    expected_outcome: str
    direction: str
    benchmark: str = DEFAULT_BENCHMARK
    sector: str = "unknown"
    evidence_sources: list[str] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)
    thesis_pillars: list[str] = field(default_factory=list)
    variant_wedge: str = ""
    priced_in_view: str = "unknown"
    catalyst_path: list[str] = field(default_factory=list)
    invalidators: list[str] = field(default_factory=list)
    action_thresholds: list[str] = field(default_factory=list)
    scenario_skew: str = "neutral"
    pm_action: str = "wait_for_confirmation"
    setup: str = "overnight_tradingagents"
    regime: str = "unknown"
    confidence: str = "0.50"
    created_at: str = ""
    resolve_after: str = ""
    source_packet_id: str | None = None
    resolved: bool = False
    outcome: bool | None = None
    actual_return: str | None = None
    benchmark_return: str | None = None
    relative_return: str | None = None
    brier_score: str | None = None
    agent_score_delta: str | None = None
    resolved_at: str | None = None
    resolution_note: str | None = None
    cost_usd: str = "0"
    # Resolution-quality metadata. Legacy rows without these keys load with
    # the defaults below and count as "unaudited" until a quality audit runs.
    defer_reason: str | None = None
    label_quality: str | None = None
    quality_flags: list[str] = field(default_factory=list)
    resolution_window: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _as_utc(value: str | datetime.datetime | None = None) -> datetime.datetime:
    if value is None:
        return datetime.datetime.now(tz=UTC)
    if isinstance(value, datetime.datetime):
        dt = value
    else:
        clean = str(value).strip()
        if clean.endswith("Z"):
            clean = f"{clean[:-1]}+00:00"
        dt = datetime.datetime.fromisoformat(clean)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _stored_utc_or_none(value: str | datetime.datetime | None) -> datetime.datetime | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    try:
        return _as_utc(value)
    except (TypeError, ValueError, OverflowError):
        return None


def _add_trading_days(start: datetime.datetime, days: int) -> datetime.datetime:
    current = start
    added = 0
    while added < days:
        current += datetime.timedelta(days=1)
        if current.weekday() < 5:
            added += 1
    return current


def _forecast_id(*parts: Any) -> str:
    encoded = json.dumps([str(part) for part in parts], sort_keys=True).encode("utf-8")
    return f"af-{hashlib.sha256(encoded).hexdigest()[:24]}"


def _decimal(value: Any, default: str = "0") -> Decimal:
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal(default)


def _context_value(value: Any, default: str = "unknown") -> str:
    normalized = str(value or "").strip().lower().replace(" ", "_").replace("-", "_")
    return normalized or default


def _sector_from_mapping(*payloads: Mapping[str, Any] | None) -> str:
    for payload in payloads:
        if not isinstance(payload, Mapping):
            continue
        for key in ("sector", "gics_sector", "asset_sector", "industry_sector"):
            value = str(payload.get(key) or "").strip()
            if value:
                return _context_value(value)
        asset_context = payload.get("asset_context")
        if isinstance(asset_context, Mapping):
            nested = _sector_from_mapping(asset_context)
            if nested != "unknown":
                return nested
    return "unknown"


def _forecast_evidence_types(forecast: AgentForecast) -> set[str]:
    evidence_text = " ".join(
        [
            forecast.forecast_type,
            forecast.setup,
            *forecast.evidence_sources,
            *forecast.evidence_refs,
        ]
    ).lower()
    evidence_types: set[str] = set()
    for name in (
        "market",
        "news",
        "sentiment",
        "fundamentals",
        "macro",
        "options",
        "insider",
        "mirofish",
        "creator",
        "rating",
        "trader",
    ):
        if name in evidence_text:
            evidence_types.add(name)
    if "sec" in evidence_text or "edgar" in evidence_text:
        evidence_types.add("fundamentals")
    if "reddit" in evidence_text or "stocktwits" in evidence_text or "social" in evidence_text:
        evidence_types.add("sentiment")
    return evidence_types or {"unknown"}


def _rating_direction(rating: str) -> str:
    normalized = parse_rating(rating, default="Hold")
    if normalized in {"Buy", "Overweight"}:
        return "bullish"
    if normalized in {"Sell", "Underweight"}:
        return "bearish"
    return "neutral"


def _probability_for_rating(rating: str) -> Decimal:
    return _probability_for_rating_with_overrides(rating, None)


def _probability_for_rating_with_overrides(
    rating: str,
    overrides: Mapping[str, Decimal] | None,
) -> Decimal:
    normalized = parse_rating(rating, default="Hold")
    if overrides and normalized in overrides:
        return overrides[normalized]
    return RATING_PROBABILITY.get(normalized, Decimal("0.50"))


def _safe_calibrated_probability(
    row: Mapping[str, Any],
    *,
    min_samples: int = MIN_CALIBRATED_RATING_SAMPLES,
) -> Decimal | None:
    if str(row.get("state") or "") != "calibrated_with_shrinkage":
        return None
    if int(row.get("resolved_count") or 0) < max(1, min_samples):
        return None
    before = _decimal(row.get("average_brier_before"), "999")
    after = _decimal(row.get("average_brier_after"), "999")
    if after > before:
        return None
    calibrated = _decimal(row.get("calibrated_probability"), "0")
    if not (Decimal("0.01") <= calibrated <= Decimal("0.99")):
        return None
    return calibrated


def calibrated_rating_probabilities_from_packet(
    packet: Mapping[str, Any],
    *,
    min_samples: int = MIN_CALIBRATED_RATING_SAMPLES,
) -> dict[str, Decimal]:
    """Return safe rating probability overrides from a calibration packet.

    The packet can be either the standalone calibration object or a full
    decision-quality report containing ``quality_gates.rating_calibration``.
    Unsafe, sparse, or Brier-worse rows are ignored per rating.
    """

    calibration: Mapping[str, Any]
    if "rating_probabilities" in packet:
        calibration = packet
    else:
        quality_gates = packet.get("quality_gates") if isinstance(packet.get("quality_gates"), Mapping) else {}
        candidate = quality_gates.get("rating_calibration") if isinstance(quality_gates, Mapping) else None
        calibration = candidate if isinstance(candidate, Mapping) else {}
    if str(calibration.get("execution_authority") or "none") != "none":
        return {}
    overrides: dict[str, Decimal] = {}
    rows = calibration.get("rating_probabilities")
    if not isinstance(rows, Mapping):
        return overrides
    for rating in RATING_PROBABILITY:
        raw_row = rows.get(rating)
        if not isinstance(raw_row, Mapping):
            continue
        probability = _safe_calibrated_probability(raw_row, min_samples=min_samples)
        if probability is not None:
            overrides[rating] = probability
    return overrides


def load_calibrated_rating_probabilities(
    path: str | Path = DEFAULT_RATING_CALIBRATION_PATH,
    *,
    min_samples: int = MIN_CALIBRATED_RATING_SAMPLES,
) -> dict[str, Decimal]:
    calibration_path = Path(path)
    if not calibration_path.exists():
        return {}
    try:
        payload = json.loads(calibration_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, Mapping):
        return {}
    return calibrated_rating_probabilities_from_packet(payload, min_samples=min_samples)


def _stance_from_text(text: str) -> tuple[str, Decimal]:
    lower = str(text or "").lower()
    bullish = sum(1 for word in BULLISH_WORDS if word in lower)
    bearish = sum(1 for word in BEARISH_WORDS if word in lower)
    if bullish > bearish:
        return "bullish", min(Decimal("0.52") + Decimal("0.03") * bullish, Decimal("0.68"))
    if bearish > bullish:
        return "bearish", min(Decimal("0.52") + Decimal("0.03") * bearish, Decimal("0.68"))
    return "neutral", Decimal("0.50")


def _expected_outcome(direction: str, ticker: str, benchmark: str, threshold: Decimal) -> str:
    if direction == "bullish":
        return f"{ticker} outperforms {benchmark} by >{threshold}%"
    if direction == "bearish":
        return f"{ticker} underperforms {benchmark} by >{threshold}%"
    return f"{ticker} stays within +/-{threshold}% of {benchmark}"


def _claim(agent: str, direction: str, ticker: str, source: str) -> str:
    plain_agent = agent.replace("_", " ")
    if direction == "bullish":
        return f"{plain_agent} expects {ticker} to outperform based on {source}."
    if direction == "bearish":
        return f"{plain_agent} expects {ticker} to underperform based on {source}."
    return f"{plain_agent} expects no clear edge for {ticker} based on {source}."


def _sentences(text: str) -> list[str]:
    cleaned = " ".join(str(text or "").replace("\n", " ").split())
    parts = re.split(r"(?<=[.!?])\s+", cleaned)
    return [part.strip(" -") for part in parts if part.strip(" -")]


def _contains_any(text: str, words: Sequence[str]) -> bool:
    lower = text.lower()
    return any(word in lower for word in words)


def _public_equity_metadata(role: str, text: str, direction: str) -> dict[str, Any]:
    sentences = _sentences(text)
    first = sentences[0] if sentences else _claim(role, direction, "", "creator workflow")
    lower = text.lower()
    catalysts: list[str] = []
    thresholds: list[str] = []
    invalidators: list[str] = []

    if _contains_any(lower, ("guidance", "earnings", "8-k", "event", "catalyst")):
        catalysts.append("event_or_guidance_reaction")
    if _contains_any(lower, ("volume", "breadth", "confirmation")):
        catalysts.append("volume_or_breadth_confirmation")
    if _contains_any(lower, ("dip", "pullback", "support", "retest")):
        catalysts.append("pullback_support_retest")
        thresholds.append("wait_for_controlled_dip")
    if _contains_any(lower, ("confirmation", "confirm")):
        thresholds.append("require_confirmation")
    if _contains_any(lower, ("cash default", "hold cash", "cash")):
        thresholds.append("hold_cash_if_unconfirmed")

    for sentence in sentences:
        if _contains_any(
            sentence,
            (
                "risk",
                "warn",
                "warning",
                "downside",
                "valuation",
                "falling knife",
                "negative",
                "cash default",
            ),
        ):
            invalidators.append(sentence[:180])

    if _contains_any(lower, ("underreact", "underprice", "underpriced")):
        variant_wedge = "market_underreaction"
        priced_in_view = "not_fully_priced"
    elif _contains_any(lower, ("dip", "pullback", "support", "retest")):
        variant_wedge = "pullback_support"
        priced_in_view = "support_level_not_confirmed_until_price_action"
    elif _contains_any(lower, ("valuation", "downside")):
        variant_wedge = "valuation_risk"
        priced_in_view = "valuation_risk_not_fully_resolved"
    else:
        variant_wedge = "role_specific_research_edge"
        priced_in_view = "unknown"

    pm_action = {
        "bullish": "watch_for_buyable_dip",
        "bearish": "downrank_or_hold_cash",
        "neutral": "wait_for_confirmation",
    }.get(direction, "wait_for_confirmation")

    return {
        "thesis_pillars": [first[:180]],
        "variant_wedge": variant_wedge,
        "priced_in_view": priced_in_view,
        "catalyst_path": catalysts or ["no_specific_catalyst_identified"],
        "invalidators": invalidators,
        "action_thresholds": thresholds or ["require_fresh_validation"],
        "scenario_skew": direction,
        "pm_action": pm_action,
    }


def _build_forecast(
    *,
    agent: str,
    ticker: str,
    direction: str,
    probability: Decimal,
    claim: str,
    forecast_type: str,
    evidence_sources: Sequence[str],
    evidence_refs: Sequence[str] | None = None,
    methodology_metadata: Mapping[str, Any] | None = None,
    created_at: datetime.datetime,
    source_packet_id: str | None,
    benchmark: str,
    horizon_days: int,
    alpha_threshold_pct: Decimal,
    setup: str,
    regime: str,
    sector: str = "unknown",
) -> AgentForecast:
    resolve_after = _add_trading_days(created_at, horizon_days)
    confidence = abs(probability - Decimal("0.50")) * Decimal("2")
    metadata = dict(
        methodology_metadata
        or _public_equity_metadata(agent, claim, direction)
    )
    return AgentForecast(
        forecast_id=_forecast_id(
            source_packet_id,
            ticker,
            agent,
            forecast_type,
            created_at.isoformat(timespec="seconds"),
            horizon_days,
        ),
        agent=agent,
        ticker=ticker.upper(),
        claim=claim,
        forecast_type=forecast_type,
        horizon=f"{horizon_days} trading days",
        probability=str(probability.quantize(Decimal("0.01"))),
        expected_outcome=_expected_outcome(direction, ticker.upper(), benchmark, alpha_threshold_pct),
        direction=direction,
        benchmark=benchmark,
        sector=_context_value(sector),
        evidence_sources=list(evidence_sources),
        evidence_refs=list(evidence_refs or []),
        thesis_pillars=list(metadata.get("thesis_pillars") or []),
        variant_wedge=str(metadata.get("variant_wedge") or ""),
        priced_in_view=str(metadata.get("priced_in_view") or "unknown"),
        catalyst_path=list(metadata.get("catalyst_path") or []),
        invalidators=list(metadata.get("invalidators") or []),
        action_thresholds=list(metadata.get("action_thresholds") or []),
        scenario_skew=str(metadata.get("scenario_skew") or direction),
        pm_action=str(metadata.get("pm_action") or "wait_for_confirmation"),
        setup=_context_value(setup),
        regime=_context_value(regime),
        confidence=str(confidence.quantize(Decimal("0.01"))),
        created_at=created_at.isoformat(timespec="seconds"),
        resolve_after=resolve_after.isoformat(timespec="seconds"),
        source_packet_id=source_packet_id,
    )


def _creator_role_text(packet: Mapping[str, Any], artifact: Mapping[str, Any]) -> str:
    path_value = str(artifact.get("path") or "").strip()
    candidates: list[Path] = []
    if path_value:
        candidates.append(Path(path_value))
    packet_path = str(packet.get("packet_path") or "").strip()
    relative_path = str(artifact.get("relative_path") or "").strip()
    if packet_path and relative_path:
        candidates.append(Path(packet_path).parent / relative_path)
    for path in candidates:
        try:
            if path.exists() and path.is_file():
                return path.read_text(encoding="utf-8").strip()
        except OSError:
            continue
    return ""


def _creator_role_direction_and_probability(
    role: str,
    text: str,
    *,
    rating_probabilities: Mapping[str, Decimal] | None = None,
) -> tuple[str, Decimal]:
    rating = parse_rating(text, default="Hold")
    if rating != "Hold" or role in {"portfolio_manager", "research_manager", "trader"}:
        return _rating_direction(rating), _probability_for_rating_with_overrides(
            rating,
            rating_probabilities,
        )
    return _stance_from_text(text)


def forecasts_from_creator_workflow_packet(
    packet: Mapping[str, Any],
    *,
    benchmark: str = DEFAULT_BENCHMARK,
    horizon_days: int = 5,
    alpha_threshold_pct: Decimal | str = Decimal("1.5"),
    regime: str = "unknown",
    sector: str | None = None,
    rating_probabilities: Mapping[str, Decimal] | None = None,
) -> list[AgentForecast]:
    """Turn preserved creator workflow role artifacts into scoreable forecasts."""

    ticker = str(packet.get("symbol") or "").upper()
    if not ticker:
        return []
    created_at = _as_utc(packet.get("generated_at"))
    packet_id = str(packet.get("packet_id") or packet.get("packet_path") or "creator-workflow")
    threshold = _decimal(alpha_threshold_pct, "1.5")
    packet_path = str(packet.get("packet_path") or "").strip()
    forecast_sector = _context_value(sector or _sector_from_mapping(packet))
    forecasts: list[AgentForecast] = []
    for artifact in packet.get("role_artifacts") or []:
        if not isinstance(artifact, Mapping):
            continue
        role = str(artifact.get("role") or "").strip()
        if not role:
            continue
        text = _creator_role_text(packet, artifact)
        if not text:
            continue
        title = str(artifact.get("title") or role.replace("_", " "))
        direction, probability = _creator_role_direction_and_probability(
            role,
            text,
            rating_probabilities=rating_probabilities,
        )
        evidence_refs = [ref for ref in (packet_path, str(artifact.get("path") or "")) if ref]
        forecasts.append(
            _build_forecast(
                agent=role,
                ticker=ticker,
                direction=direction,
                probability=probability,
                claim=_claim(role, direction, ticker, f"{title} creator workflow artifact"),
                forecast_type=f"{role}_creator_workflow_direction",
                evidence_sources=[f"{role}_creator_workflow_artifact"],
                evidence_refs=evidence_refs,
                methodology_metadata=_public_equity_metadata(role, text, direction),
                created_at=created_at,
                source_packet_id=packet_id,
                benchmark=benchmark,
                horizon_days=horizon_days,
                alpha_threshold_pct=threshold,
                setup="creator_tradingagents_workflow",
                regime=regime,
                sector=forecast_sector,
            )
        )
    return forecasts


def forecasts_from_overnight_packet(
    packet: Mapping[str, Any],
    *,
    benchmark: str = DEFAULT_BENCHMARK,
    horizon_days: int = 5,
    alpha_threshold_pct: Decimal | str = Decimal("1.5"),
    setup: str = "overnight_tradingagents",
    regime: str = "unknown",
    rating_probabilities: Mapping[str, Decimal] | None = None,
) -> list[AgentForecast]:
    created_at = _as_utc(packet.get("generated_at"))
    packet_id = str(packet.get("packet_id") or packet.get("generated_at") or "overnight")
    threshold = _decimal(alpha_threshold_pct, "1.5")
    rating_probability_overrides = dict(
        rating_probabilities
        if rating_probabilities is not None
        else load_calibrated_rating_probabilities()
    )
    forecasts: list[AgentForecast] = []
    for result in packet.get("ticker_results") or []:
        if not isinstance(result, Mapping):
            continue
        ticker = str(result.get("symbol") or "").upper()
        if not ticker:
            continue
        sector = _sector_from_mapping(result, packet)
        creator_workflow = result.get("creator_workflow")
        if isinstance(creator_workflow, Mapping):
            creator_packet_path = str(creator_workflow.get("packet_path") or "").strip()
            if creator_packet_path:
                try:
                    creator_packet = json.loads(Path(creator_packet_path).read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    creator_packet = None
                if isinstance(creator_packet, Mapping):
                    forecasts.extend(
                        forecasts_from_creator_workflow_packet(
                            creator_packet,
                            benchmark=benchmark,
                            horizon_days=horizon_days,
                            alpha_threshold_pct=threshold,
                            regime=regime,
                            sector=sector,
                            rating_probabilities=rating_probability_overrides,
                        )
                    )
        reports = result.get("reports") or {}
        if isinstance(reports, Mapping):
            for agent, report_key in AGENT_REPORT_KEYS.items():
                report = str(reports.get(report_key) or "").strip()
                if not report:
                    continue
                direction, probability = _stance_from_text(report)
                forecasts.append(
                    _build_forecast(
                        agent=agent,
                        ticker=ticker,
                        direction=direction,
                        probability=probability,
                        claim=_claim(agent, direction, ticker, f"{report_key} report"),
                        forecast_type=f"{report_key}_report_direction",
                        evidence_sources=[f"{report_key}_report"],
                        created_at=created_at,
                        source_packet_id=packet_id,
                        benchmark=benchmark,
                        horizon_days=horizon_days,
                        alpha_threshold_pct=threshold,
                        setup=setup,
                        regime=regime,
                        sector=sector,
                    )
                )
        for agent, text_key, label in (
            ("research_manager", "investment_plan", "research debate"),
            ("trader", "trader_investment_plan", "trader proposal"),
            ("portfolio_manager", "final_trade_decision", "portfolio decision"),
        ):
            text = str(result.get(text_key) or "").strip()
            if not text and text_key == "final_trade_decision":
                text = str(result.get("rating") or "").strip()
            if not text:
                continue
            rating = parse_rating(text, default=str(result.get("rating") or "Hold"))
            direction = _rating_direction(rating)
            probability = _probability_for_rating_with_overrides(
                rating,
                rating_probability_overrides,
            )
            forecasts.append(
                _build_forecast(
                    agent=agent,
                    ticker=ticker,
                    direction=direction,
                    probability=probability,
                    claim=_claim(agent, direction, ticker, label),
                    forecast_type=f"{agent}_rating_direction",
                    evidence_sources=[text_key],
                    created_at=created_at,
                    source_packet_id=packet_id,
                    benchmark=benchmark,
                    horizon_days=horizon_days,
                    alpha_threshold_pct=threshold,
                    setup=setup,
                    regime=regime,
                    sector=sector,
                )
            )
    return forecasts


def _mirofish_advisory_from_packet(packet: Mapping[str, Any]) -> Mapping[str, Any]:
    payload = packet.get("payload")
    if isinstance(payload, Mapping):
        advisory = payload.get("final_advisory")
        if isinstance(advisory, Mapping):
            return advisory
    advisory = packet.get("final_advisory")
    if isinstance(advisory, Mapping):
        return advisory
    for signal in packet.get("signals") or []:
        if isinstance(signal, Mapping) and signal.get("type") == "mirofish_final_advisory":
            return signal
    return {}


def forecasts_from_mirofish_handoff_packet(
    packet: Mapping[str, Any],
    *,
    benchmark: str = DEFAULT_BENCHMARK,
    horizon_days: int = 5,
    alpha_threshold_pct: Decimal | str = Decimal("1.5"),
    regime: str = "pdt_reform_window",
) -> list[AgentForecast]:
    """Turn the final MiroFish advisory handoff into scoreable neutral forecasts.

    MiroFish has no execution authority and does not produce buy/sell signals.
    These forecasts score its central caution: PDT narrative heat should not be
    trusted as standalone flow without broker/account/options/macro validation.
    """

    advisory = _mirofish_advisory_from_packet(packet)
    if not advisory or str(advisory.get("execution_authority") or "none") != "none":
        return []
    machine_packet = advisory.get("machine_readable_packet")
    created_at = _as_utc(
        advisory.get("created_date")
        or (
            machine_packet.get("created_date")
            if isinstance(machine_packet, Mapping)
            else None
        )
        or packet.get("generated_at")
    )
    packet_id = str(
        advisory.get("simulation_id")
        or advisory.get("source_path")
        or packet.get("packet_id")
        or "mirofish"
    )
    threshold = _decimal(alpha_threshold_pct, "1.5")
    sector = _sector_from_mapping(advisory, packet)
    symbols = [
        str(symbol).upper()
        for symbol in advisory.get("forecast_symbols")
        or advisory.get("attention_symbols")
        or []
        if str(symbol).strip()
    ]
    symbols = [symbol for symbol in dict.fromkeys(symbols) if symbol != benchmark.upper()]
    if not symbols:
        return []
    primary_hypotheses = [str(item) for item in advisory.get("primary_hypotheses") or []]
    validation_tasks = [str(item) for item in advisory.get("validation_tasks") or []]
    false_signal_filters = [str(item) for item in advisory.get("false_signal_filters") or []]
    scenario_branches = [
        str(branch.get("description") or branch)
        for branch in advisory.get("scenario_branches") or []
        if isinstance(branch, Mapping) or str(branch).strip()
    ]
    claim = (
        "MiroFish expects PDT-reform narrative heat to require broker/account, "
        "options-flow, macro, and liquidity validation before it counts as real flow."
    )
    metadata = {
        "thesis_pillars": primary_hypotheses[:3]
        or ["PDT narrative attention is not standalone executable flow evidence."],
        "variant_wedge": "pdt_reform_market_mirror_control_branch",
        "priced_in_view": "narrative_not_confirmed_without_flow_validation",
        "catalyst_path": scenario_branches[:5] or ["scenario_branch_monitoring"],
        "invalidators": false_signal_filters[:8],
        "action_thresholds": validation_tasks[:8] or ["require_fresh_market_validation"],
        "scenario_skew": "neutral_control_branch",
        "pm_action": "validate_before_trade",
    }
    source_artifacts = advisory.get("source_artifacts")
    source_artifact_values = (
        source_artifacts.values() if isinstance(source_artifacts, Mapping) else []
    )
    source_refs = [
        str(ref)
        for ref in [advisory.get("source_path"), *source_artifact_values]
        if ref
    ]
    return [
        _build_forecast(
            agent="mirofish_market_mirror",
            ticker=symbol,
            direction="neutral",
            probability=Decimal("0.55"),
            claim=f"{claim} Attention symbol: {symbol}.",
            forecast_type="mirofish_pdt_narrative_requires_confirmation",
            evidence_sources=["mirofish_final_handoff", "mirofish_market_mirror_simulation"],
            evidence_refs=source_refs,
            methodology_metadata=metadata,
            created_at=created_at,
            source_packet_id=packet_id,
            benchmark=benchmark,
            horizon_days=horizon_days,
            alpha_threshold_pct=threshold,
            setup="mirofish_advisory_market_mirror",
            regime=regime,
            sector=sector,
        )
        for symbol in symbols
    ]


def load_ledger_with_stats(path: str | Path = DEFAULT_LEDGER_PATH) -> tuple[list[AgentForecast], int]:
    """Load the ledger and report how many non-empty lines failed to parse."""

    ledger_path = Path(path)
    if not ledger_path.exists():
        return [], 0
    records: list[AgentForecast] = []
    corrupt_line_count = 0
    for line in ledger_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            records.append(AgentForecast(**json.loads(line)))
        except (json.JSONDecodeError, TypeError, ValueError):
            # Skip malformed / schema-drifted lines rather than aborting the
            # entire ledger load on a single bad record.
            corrupt_line_count += 1
            continue
    return records, corrupt_line_count


def load_ledger(path: str | Path = DEFAULT_LEDGER_PATH) -> list[AgentForecast]:
    return load_ledger_with_stats(path)[0]


def append_forecasts(
    forecasts: Iterable[AgentForecast],
    *,
    path: str | Path = DEFAULT_LEDGER_PATH,
) -> int:
    ledger_path = Path(path)
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    existing_ids = {forecast.forecast_id for forecast in load_ledger(ledger_path)}
    appended = 0
    with ledger_path.open("a", encoding="utf-8") as handle:
        for forecast in forecasts:
            if forecast.forecast_id in existing_ids:
                continue
            handle.write(json.dumps(forecast.as_dict(), sort_keys=True) + "\n")
            existing_ids.add(forecast.forecast_id)
            appended += 1
    return appended


def _return_pct(start_price: Any, end_price: Any) -> Decimal | None:
    start = _decimal(start_price)
    end = _decimal(end_price)
    if not start.is_finite() or not end.is_finite() or start <= 0:
        return None
    return ((end - start) / start * Decimal("100")).quantize(Decimal("0.01"))


def _outcome_for_direction(direction: str, relative_return: Decimal, threshold: Decimal) -> bool:
    if direction == "bullish":
        return relative_return > threshold
    if direction == "bearish":
        return relative_return < -threshold
    return abs(relative_return) <= threshold


def _score_delta(outcome: bool, probability: Decimal) -> Decimal:
    return (probability - Decimal("0.50")) if outcome else -(probability - Decimal("0.50"))


PriceLookup = Callable[[str, str, str], tuple[Decimal | str | float, Decimal | str | float] | None]


def resolve_forecasts_with_quality(
    forecasts: Sequence[AgentForecast],
    *,
    window_lookup: WindowLookup,
    now: datetime.datetime | None = None,
    alpha_threshold_pct: Decimal | str = Decimal("1.5"),
) -> tuple[list[AgentForecast], list[ResolutionQualityReport]]:
    """Resolve due forecasts against mechanically audited price windows.

    Every pending forecast gets a :class:`ResolutionQualityReport`. Forecasts
    whose windows fail the audit are deferred with a reason instead of being
    scored against a partial, stale, or mismatched window.
    """

    current = _as_utc(now)
    threshold = _decimal(alpha_threshold_pct, "1.5")
    updated: list[AgentForecast] = []
    reports: list[ResolutionQualityReport] = []
    for forecast in forecasts:
        if forecast.resolved:
            updated.append(forecast)
            continue
        created = _stored_utc_or_none(forecast.created_at)
        resolve_after = _stored_utc_or_none(forecast.resolve_after)
        if created is None or resolve_after is None:
            reports.append(
                ResolutionQualityReport(
                    forecast_id=forecast.forecast_id,
                    ticker=forecast.ticker,
                    benchmark=forecast.benchmark,
                    status=STATUS_DEFERRED,
                    label_quality=None,
                    quality_flags=(DEFER_INVALID_FORECAST_TIMESTAMPS,),
                    defer_reason=DEFER_INVALID_FORECAST_TIMESTAMPS,
                    window=None,
                    note="created_at/resolve_after are missing or unparseable",
                )
            )
            updated.append(
                replace(
                    forecast,
                    defer_reason=DEFER_INVALID_FORECAST_TIMESTAMPS,
                    resolution_note="deferred: unparseable forecast timestamps",
                )
            )
            continue
        start_date = created.date().isoformat()
        end_date = resolve_after.date().isoformat()
        mature = resolve_after <= current
        if not mature:
            updated.append(forecast)
            reports.append(
                audit_resolution_window(
                    forecast_id=forecast.forecast_id,
                    ticker=forecast.ticker,
                    benchmark=forecast.benchmark,
                    intended_start=start_date,
                    intended_end=end_date,
                    horizon=forecast.horizon,
                    ticker_window=None,
                    benchmark_window=None,
                    now=current,
                    mature=False,
                )
            )
            continue
        ticker_window = window_lookup(forecast.ticker, start_date, end_date)
        benchmark_window = window_lookup(forecast.benchmark, start_date, end_date)
        report = audit_resolution_window(
            forecast_id=forecast.forecast_id,
            ticker=forecast.ticker,
            benchmark=forecast.benchmark,
            intended_start=start_date,
            intended_end=end_date,
            horizon=forecast.horizon,
            ticker_window=ticker_window,
            benchmark_window=benchmark_window,
            now=current,
        )
        if report.status != STATUS_RESOLVABLE:
            reports.append(report)
            updated.append(
                replace(
                    forecast,
                    defer_reason=report.defer_reason,
                    resolution_note=f"deferred: {report.note}",
                )
            )
            continue
        actual_return = _return_pct(ticker_window.entry_close, ticker_window.exit_close)
        benchmark_return = _return_pct(benchmark_window.entry_close, benchmark_window.exit_close)
        if actual_return is None or benchmark_return is None:
            report = replace(
                report,
                status="deferred",
                label_quality=None,
                defer_reason=DEFER_INVALID_WINDOW,
                window=None,
                note="non-positive entry price inside the resolution window",
            )
            reports.append(report)
            updated.append(
                replace(
                    forecast,
                    defer_reason=DEFER_INVALID_WINDOW,
                    resolution_note=f"deferred: {report.note}",
                )
            )
            continue
        reports.append(report)
        relative_return = (actual_return - benchmark_return).quantize(Decimal("0.01"))
        probability = _decimal(forecast.probability, "0.50")
        outcome = _outcome_for_direction(forecast.direction, relative_return, threshold)
        brier = ((probability - (Decimal("1") if outcome else Decimal("0"))) ** 2).quantize(
            Decimal("0.0001")
        )
        updated.append(
            replace(
                forecast,
                resolved=True,
                outcome=outcome,
                actual_return=str(actual_return),
                benchmark_return=str(benchmark_return),
                relative_return=str(relative_return),
                brier_score=str(brier),
                agent_score_delta=str(_score_delta(outcome, probability).quantize(Decimal("0.01"))),
                resolved_at=current.isoformat(timespec="seconds"),
                resolution_note="resolved against audited relative return window",
                defer_reason=None,
                label_quality=report.label_quality,
                quality_flags=list(report.quality_flags),
                resolution_window=report.window.as_dict() if report.window else None,
            )
        )
    return updated, reports


def audit_resolved_forecasts(
    forecasts: Sequence[AgentForecast],
    *,
    window_lookup: WindowLookup,
    now: datetime.datetime | None = None,
    alpha_threshold_pct: Decimal | str = Decimal("1.5"),
) -> tuple[list[AgentForecast], list[ResolutionQualityReport]]:
    """Retro-audit already-resolved labels without rewriting history.

    Each resolved forecast is re-measured against freshly fetched, dated
    windows. Outcomes and scores are never changed; instead a label whose
    recomputed outcome disagrees with the stored one (or whose window can no
    longer be verified) is downgraded to ``suspect`` so mining excludes it.
    """

    current = _as_utc(now)
    threshold = _decimal(alpha_threshold_pct, "1.5")
    updated: list[AgentForecast] = []
    reports: list[ResolutionQualityReport] = []
    for forecast in forecasts:
        if not forecast.resolved:
            updated.append(forecast)
            continue
        created = _stored_utc_or_none(forecast.created_at)
        resolve_after = _stored_utc_or_none(forecast.resolve_after)
        if created is None or resolve_after is None:
            report = ResolutionQualityReport(
                forecast_id=forecast.forecast_id,
                ticker=forecast.ticker,
                benchmark=forecast.benchmark,
                status=STATUS_RESOLVABLE,
                label_quality=LABEL_QUALITY_SUSPECT,
                quality_flags=("window_unverifiable",),
                defer_reason=None,
                window=None,
                note="stored label kept but unparseable timestamps prevent window verification",
            )
            reports.append(report)
            updated.append(
                replace(
                    forecast,
                    label_quality=LABEL_QUALITY_SUSPECT,
                    quality_flags=["window_unverifiable"],
                    resolution_window=None,
                )
            )
            continue
        start_date = created.date().isoformat()
        end_date = resolve_after.date().isoformat()
        ticker_window = window_lookup(forecast.ticker, start_date, end_date)
        benchmark_window = window_lookup(forecast.benchmark, start_date, end_date)
        report = audit_resolution_window(
            forecast_id=forecast.forecast_id,
            ticker=forecast.ticker,
            benchmark=forecast.benchmark,
            intended_start=start_date,
            intended_end=end_date,
            horizon=forecast.horizon,
            ticker_window=ticker_window,
            benchmark_window=benchmark_window,
            now=current,
        )
        if report.status != STATUS_RESOLVABLE:
            flags = tuple(dict.fromkeys([*report.quality_flags, "window_unverifiable"]))
            report = replace(
                report,
                status=STATUS_RESOLVABLE,
                label_quality=LABEL_QUALITY_SUSPECT,
                quality_flags=flags,
                note=f"stored label kept but window could not be verified: {report.note}",
            )
            reports.append(report)
            updated.append(
                replace(
                    forecast,
                    label_quality=LABEL_QUALITY_SUSPECT,
                    quality_flags=list(flags),
                    resolution_window=None,
                )
            )
            continue
        actual_return = _return_pct(ticker_window.entry_close, ticker_window.exit_close)
        benchmark_return = _return_pct(benchmark_window.entry_close, benchmark_window.exit_close)
        flags = list(report.quality_flags)
        label_quality = report.label_quality
        window_payload: dict[str, Any] | None = (
            report.window.as_dict() if report.window else None
        )
        if actual_return is None or benchmark_return is None:
            flags.append("window_unverifiable")
            label_quality = LABEL_QUALITY_SUSPECT
            window_payload = None
        else:
            relative_return = (actual_return - benchmark_return).quantize(Decimal("0.01"))
            recomputed_outcome = _outcome_for_direction(
                forecast.direction, relative_return, threshold
            )
            if forecast.outcome is not None and recomputed_outcome != forecast.outcome:
                flags.append("reaudit_outcome_mismatch")
                label_quality = LABEL_QUALITY_SUSPECT
            elif str(relative_return) != str(forecast.relative_return or ""):
                flags.append("reaudit_relative_return_drift")
                if label_quality == LABEL_QUALITY_HIGH:
                    label_quality = LABEL_QUALITY_DEGRADED
        report = replace(report, label_quality=label_quality, quality_flags=tuple(flags))
        reports.append(report)
        updated.append(
            replace(
                forecast,
                label_quality=label_quality,
                quality_flags=list(flags),
                resolution_window=window_payload,
            )
        )
    return updated, reports


def resolve_forecasts(
    forecasts: Sequence[AgentForecast],
    *,
    price_lookup: PriceLookup | None = None,
    window_lookup: WindowLookup | None = None,
    now: datetime.datetime | None = None,
    alpha_threshold_pct: Decimal | str = Decimal("1.5"),
) -> list[AgentForecast]:
    if window_lookup is not None:
        resolved, _reports = resolve_forecasts_with_quality(
            forecasts,
            window_lookup=window_lookup,
            now=now,
            alpha_threshold_pct=alpha_threshold_pct,
        )
        return resolved
    if price_lookup is None:
        raise ValueError("resolve_forecasts requires price_lookup or window_lookup")
    current = _as_utc(now)
    threshold = _decimal(alpha_threshold_pct, "1.5")
    resolved: list[AgentForecast] = []
    for forecast in forecasts:
        if forecast.resolved:
            resolved.append(forecast)
            continue
        created = _stored_utc_or_none(forecast.created_at)
        resolve_after = _stored_utc_or_none(forecast.resolve_after)
        if created is None or resolve_after is None:
            resolved.append(
                replace(
                    forecast,
                    resolution_note="unparseable forecast timestamps; forecast remains unresolved",
                )
            )
            continue
        if resolve_after > current:
            resolved.append(forecast)
            continue
        start_date = created.date().isoformat()
        end_date = resolve_after.date().isoformat()
        ticker_prices = price_lookup(forecast.ticker, start_date, end_date)
        benchmark_prices = price_lookup(forecast.benchmark, start_date, end_date)
        if ticker_prices is None or benchmark_prices is None:
            resolved.append(
                replace(
                    forecast,
                    resolution_note="price lookup unavailable; forecast remains unresolved",
                )
            )
            continue
        actual_return = _return_pct(ticker_prices[0], ticker_prices[1])
        benchmark_return = _return_pct(benchmark_prices[0], benchmark_prices[1])
        if actual_return is None or benchmark_return is None:
            resolved.append(
                replace(
                    forecast,
                    resolution_note="invalid price window; forecast remains unresolved",
                )
            )
            continue
        relative_return = (actual_return - benchmark_return).quantize(Decimal("0.01"))
        probability = _decimal(forecast.probability, "0.50")
        outcome = _outcome_for_direction(forecast.direction, relative_return, threshold)
        brier = ((probability - (Decimal("1") if outcome else Decimal("0"))) ** 2).quantize(
            Decimal("0.0001")
        )
        resolved.append(
            replace(
                forecast,
                resolved=True,
                outcome=outcome,
                actual_return=str(actual_return),
                benchmark_return=str(benchmark_return),
                relative_return=str(relative_return),
                brier_score=str(brier),
                agent_score_delta=str(_score_delta(outcome, probability).quantize(Decimal("0.01"))),
                resolved_at=current.isoformat(timespec="seconds"),
                resolution_note="resolved against relative return window",
            )
        )
    return resolved


def write_ledger(
    forecasts: Sequence[AgentForecast],
    *,
    path: str | Path = DEFAULT_LEDGER_PATH,
) -> None:
    ledger_path = Path(path)
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(json.dumps(forecast.as_dict(), sort_keys=True) for forecast in forecasts)
    ledger_path.write_text((text + "\n") if text else "", encoding="utf-8")


def summarize_agent_scores(forecasts: Sequence[AgentForecast]) -> dict[str, Any]:
    by_agent: dict[str, dict[str, Any]] = {}
    outcome_counts: dict[str, int] = {}
    label_quality_counts: dict[str, int] = {}
    for forecast in forecasts:
        if forecast.resolved:
            quality_label = forecast.label_quality or "unaudited"
            label_quality_counts[quality_label] = label_quality_counts.get(quality_label, 0) + 1
        bucket = by_agent.setdefault(
            forecast.agent,
            {
                "forecast_count": 0,
                "resolved_count": 0,
                "wins": 0,
                "useful_forecast_count": 0,
                "harmful_forecast_count": 0,
                "neutral_forecast_count": 0,
                "pending_forecast_count": 0,
                "brier_total": Decimal("0"),
                "score_delta_total": Decimal("0"),
                "probability_total": Decimal("0"),
                "cost_total": Decimal("0"),
                "time_to_resolution_days_total": Decimal("0"),
                "directional_wins": 0,
                "relative_wins": 0,
                "false_positive_count": 0,
                "false_negative_count": 0,
                "symbols": set(),
            },
        )
        bucket["forecast_count"] += 1
        bucket["symbols"].add(forecast.ticker)
        if not forecast.resolved:
            outcome_label = "pending"
            bucket["pending_forecast_count"] += 1
        elif forecast.outcome is True:
            outcome_label = "useful"
            bucket["useful_forecast_count"] += 1
        elif forecast.outcome is False:
            outcome_label = "harmful"
            bucket["harmful_forecast_count"] += 1
        else:
            outcome_label = "neutral"
            bucket["neutral_forecast_count"] += 1
        outcome_counts[outcome_label] = outcome_counts.get(outcome_label, 0) + 1
        if forecast.resolved:
            bucket["resolved_count"] += 1
            if forecast.outcome:
                bucket["wins"] += 1
                bucket["relative_wins"] += 1
            bucket["brier_total"] += _decimal(forecast.brier_score)
            bucket["score_delta_total"] += _decimal(forecast.agent_score_delta)
            probability = _decimal(forecast.probability, "0.50")
            bucket["probability_total"] += probability
            bucket["cost_total"] += _decimal(forecast.cost_usd)
            if forecast.resolved_at:
                created = _stored_utc_or_none(forecast.created_at)
                resolved = _stored_utc_or_none(forecast.resolved_at)
                if created is not None and resolved is not None:
                    elapsed = resolved - created
                    bucket["time_to_resolution_days_total"] += (
                        Decimal(str(elapsed.total_seconds())) / Decimal("86400")
                    )
            actual_return = _decimal(forecast.actual_return)
            threshold = _decimal("0")
            directional_outcome = (
                actual_return > threshold
                if forecast.direction == "bullish"
                else actual_return < -threshold
                if forecast.direction == "bearish"
                else abs(actual_return) <= threshold
            )
            if directional_outcome:
                bucket["directional_wins"] += 1
            predicted_positive = probability > Decimal("0.50")
            if predicted_positive and not forecast.outcome:
                bucket["false_positive_count"] += 1
            if not predicted_positive and forecast.outcome:
                bucket["false_negative_count"] += 1
    summary: dict[str, Any] = {
        "agents": {},
        "forecast_count": len(forecasts),
        "resolved_forecast_count": sum(1 for forecast in forecasts if forecast.resolved),
        "outcome_counts": outcome_counts,
        "label_quality_counts": label_quality_counts,
    }
    for agent, bucket in by_agent.items():
        resolved_count = bucket["resolved_count"]
        summary["agents"][agent] = {
            "forecast_count": bucket["forecast_count"],
            "resolved_count": resolved_count,
            "useful_forecast_count": bucket["useful_forecast_count"],
            "harmful_forecast_count": bucket["harmful_forecast_count"],
            "neutral_forecast_count": bucket["neutral_forecast_count"],
            "pending_forecast_count": bucket["pending_forecast_count"],
            "accuracy": (
                str((Decimal(bucket["wins"]) / Decimal(resolved_count)).quantize(Decimal("0.01")))
                if resolved_count
                else None
            ),
            "directional_accuracy": (
                str((Decimal(bucket["directional_wins"]) / Decimal(resolved_count)).quantize(Decimal("0.01")))
                if resolved_count
                else None
            ),
            "relative_accuracy": (
                str((Decimal(bucket["relative_wins"]) / Decimal(resolved_count)).quantize(Decimal("0.01")))
                if resolved_count
                else None
            ),
            "average_brier_score": (
                str((bucket["brier_total"] / Decimal(resolved_count)).quantize(Decimal("0.0001")))
                if resolved_count
                else None
            ),
            "confidence_calibration_error": (
                str(
                    abs(
                        (bucket["probability_total"] / Decimal(resolved_count))
                        - (Decimal(bucket["relative_wins"]) / Decimal(resolved_count))
                    ).quantize(Decimal("0.0001"))
                )
                if resolved_count
                else None
            ),
            "false_positive_count": bucket["false_positive_count"],
            "false_negative_count": bucket["false_negative_count"],
            "false_positive_rate": (
                str((Decimal(bucket["false_positive_count"]) / Decimal(resolved_count)).quantize(Decimal("0.0001")))
                if resolved_count
                else None
            ),
            "false_negative_rate": (
                str((Decimal(bucket["false_negative_count"]) / Decimal(resolved_count)).quantize(Decimal("0.0001")))
                if resolved_count
                else None
            ),
            "thesis_survival_rate": (
                str((Decimal(bucket["useful_forecast_count"]) / Decimal(resolved_count)).quantize(Decimal("0.0001")))
                if resolved_count
                else None
            ),
            "average_time_to_resolution_days": (
                str((bucket["time_to_resolution_days_total"] / Decimal(resolved_count)).quantize(Decimal("0.01")))
                if resolved_count
                else None
            ),
            "cost_total_usd": str(bucket["cost_total"].quantize(Decimal("0.0001"))),
            "cost_per_useful_insight_usd": (
                str((bucket["cost_total"] / Decimal(bucket["useful_forecast_count"])).quantize(Decimal("0.0001")))
                if bucket["useful_forecast_count"]
                else None
            ),
            "score_delta_total": str(bucket["score_delta_total"].quantize(Decimal("0.01"))),
            "symbols": sorted(bucket["symbols"]),
        }
    return summary


def _clamp_decimal(value: Decimal, floor: Decimal, ceiling: Decimal) -> Decimal:
    return max(floor, min(ceiling, value))


def _agent_weight_from_stats(
    stats: Mapping[str, Any],
    *,
    resolved_count: int,
    floor: Decimal,
    ceiling: Decimal,
) -> Decimal:
    accuracy = _decimal(stats.get("accuracy"), "0.50")
    average_brier = _decimal(stats.get("average_brier_score"), "0.25")
    score_delta_total = _decimal(stats.get("score_delta_total"), "0")
    average_delta = score_delta_total / Decimal(max(1, resolved_count))
    raw_weight = (
        Decimal("1.00")
        + ((accuracy - Decimal("0.50")) * Decimal("0.80"))
        + (average_delta * Decimal("1.00"))
        + ((Decimal("0.25") - average_brier) * Decimal("0.80"))
    )
    return _clamp_decimal(raw_weight, floor, ceiling).quantize(Decimal("0.01"))


def _context_filter_value(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = _context_value(value, default="")
    return normalized or None


def _forecast_matches_context(
    forecast: AgentForecast,
    *,
    ticker: str | None = None,
    setup: str | None = None,
    sector: str | None = None,
    regime: str | None = None,
    evidence_type: str | None = None,
) -> bool:
    if ticker and forecast.ticker.upper() != ticker.upper():
        return False
    if setup and _context_value(forecast.setup) != setup:
        return False
    if sector and _context_value(forecast.sector) != sector:
        return False
    if regime and _context_value(forecast.regime) != regime:
        return False
    return not (evidence_type and evidence_type not in _forecast_evidence_types(forecast))


def agent_influence_weights(
    forecasts: Sequence[AgentForecast],
    *,
    min_resolved: int = 3,
    floor: Decimal | str = DEFAULT_AGENT_WEIGHT_FLOOR,
    ceiling: Decimal | str = DEFAULT_AGENT_WEIGHT_CEILING,
    ticker: str | None = None,
    setup: str | None = None,
    sector: str | None = None,
    regime: str | None = None,
    evidence_type: str | None = None,
) -> dict[str, Any]:
    """Compute bounded earned influence weights for TradingAgents roles.

    The result is advisory. It is meant for prompt/context weighting and policy
    replays, not for bypassing execution safety.
    """

    summary = summarize_agent_scores(forecasts)
    floor_value = _decimal(floor, str(DEFAULT_AGENT_WEIGHT_FLOOR))
    ceiling_value = _decimal(ceiling, str(DEFAULT_AGENT_WEIGHT_CEILING))
    context_filters = {
        "ticker": ticker.upper() if ticker else None,
        "setup": _context_filter_value(setup),
        "sector": _context_filter_value(sector),
        "regime": _context_filter_value(regime),
        "evidence_type": _context_filter_value(evidence_type),
    }
    has_context = any(context_filters.values())
    context_forecasts = (
        [
            forecast
            for forecast in forecasts
            if _forecast_matches_context(forecast, **context_filters)
        ]
        if has_context
        else []
    )
    context_summary = summarize_agent_scores(context_forecasts) if has_context else {"agents": {}}
    context_resolved_count = sum(1 for forecast in context_forecasts if forecast.resolved)
    agents: dict[str, Any] = {}
    for agent, stats in summary["agents"].items():
        resolved_count = int(stats["resolved_count"] or 0)
        if resolved_count < max(1, int(min_resolved)):
            agents[agent] = {
                "weight": "1.00",
                "state": "insufficient_history",
                "resolved_count": resolved_count,
                "reason": "not enough resolved forecasts to change this agent's influence",
            }
            continue
        weight = _agent_weight_from_stats(
            stats,
            resolved_count=resolved_count,
            floor=floor_value,
            ceiling=ceiling_value,
        )
        item = {
            "weight": str(weight),
            "state": "earned_weight",
            "resolved_count": resolved_count,
            "accuracy": stats["accuracy"],
            "average_brier_score": stats["average_brier_score"],
            "score_delta_total": stats["score_delta_total"],
            "reason": (
                "agent influence adjusted by resolved accuracy, probability calibration, "
                "and score delta; bounded so it cannot override risk gates"
            ),
        }
        if has_context:
            context_stats = context_summary["agents"].get(agent)
            context_agent_resolved = int((context_stats or {}).get("resolved_count") or 0)
            item["context"] = {
                **context_filters,
                "resolved_count": context_agent_resolved,
                "state": "insufficient_context_history",
            }
            if context_stats and context_agent_resolved >= max(1, int(min_resolved)):
                context_weight = _agent_weight_from_stats(
                    context_stats,
                    resolved_count=context_agent_resolved,
                    floor=floor_value,
                    ceiling=ceiling_value,
                )
                blended = (
                    (context_weight * Decimal("0.70"))
                    + (weight * Decimal("0.30"))
                )
                item.update(
                    {
                        "weight": str(
                            _clamp_decimal(blended, floor_value, ceiling_value).quantize(Decimal("0.01"))
                        ),
                        "state": "contextual_earned_weight",
                        "context": {
                            **context_filters,
                            "resolved_count": context_agent_resolved,
                            "accuracy": context_stats["accuracy"],
                            "average_brier_score": context_stats["average_brier_score"],
                            "score_delta_total": context_stats["score_delta_total"],
                            "state": "earned_context",
                        },
                        "reason": (
                            "agent influence adjusted by matching setup, sector, regime, "
                            "evidence type, and global fallback; advisory only"
                        ),
                    }
                )
        agents[agent] = item
    return {
        "kind": "agent_influence_weights",
        "forecast_count": summary["forecast_count"],
        "min_resolved": max(1, int(min_resolved)),
        "floor": str(floor_value),
        "ceiling": str(ceiling_value),
        "context": {
            **context_filters,
            "matched_forecast_count": len(context_forecasts),
            "matched_resolved_count": context_resolved_count,
        } if has_context else None,
        "agents": agents,
        "execution_authority": "none",
        "forbidden_effects": list(LEDGER_FORBIDDEN_EFFECTS),
    }


def render_agent_influence_context(weights: Mapping[str, Any]) -> str:
    agents = weights.get("agents") or {}
    if not agents:
        return "Agent Intelligence Ledger: no resolved agent history is available yet."
    lines = [
        "Agent Intelligence Ledger influence weights are advisory only.",
        "They may adjust debate attention, but they cannot bypass live gates or risk limits.",
    ]
    context = weights.get("context")
    if isinstance(context, Mapping):
        supplied = [
            f"{key}={value}"
            for key, value in (
                ("ticker", context.get("ticker")),
                ("setup", context.get("setup")),
                ("sector", context.get("sector")),
                ("regime", context.get("regime")),
                ("evidence_type", context.get("evidence_type")),
            )
            if value
        ]
        if supplied:
            lines.append(
                "Using context "
                + " ".join(supplied)
                + f"; matched_resolved={context.get('matched_resolved_count', 0)}."
            )
    for agent in sorted(agents):
        item = agents[agent]
        lines.append(
            f"- {agent}: weight {item.get('weight', '1.00')} "
            f"({item.get('state', 'unknown')}, resolved={item.get('resolved_count', 0)})"
        )
    return "\n".join(lines)


def write_summary(
    forecasts: Sequence[AgentForecast],
    *,
    path: str | Path = DEFAULT_SUMMARY_PATH,
) -> Path:
    summary_path = Path(path)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary = summarize_agent_scores(forecasts)
    summary["influence_weights"] = agent_influence_weights(forecasts)
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return summary_path
