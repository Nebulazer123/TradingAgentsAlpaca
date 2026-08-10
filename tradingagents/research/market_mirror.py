"""Bounded MiroFish-inspired market-mirror packet builder."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass

from tradingagents.evals.agent_intelligence_ledger import AgentForecast
from tradingagents.schemas.research import MarketActorProfile, MarketMirrorScenarioPacket

from .memory import redact_research_text

DEFAULT_ACTORS = (
    ("long_only_pm", "long-only portfolio manager", "balanced"),
    ("risk_manager", "risk manager", "skeptical"),
    ("retail_momentum", "retail momentum trader", "risk_on"),
    ("ai_bot_day_trader", "AI-bot day trader", "risk_on"),
    ("pdt_reform_new_retail", "new retail intraday trader after PDT reform", "volatile"),
    ("skeptical_analyst", "skeptical analyst", "skeptical"),
    ("sector_specialist", "sector specialist", "balanced"),
    ("filing_event_watcher", "filing/event watcher", "event_driven"),
    ("macro_regime_watcher", "macro/regime watcher", "macro"),
    ("liquidity_critic", "liquidity/market-structure critic", "skeptical"),
    ("bear_case_adversary", "bear-case adversary", "bearish"),
)


@dataclass(frozen=True)
class MarketMirrorResult:
    scenario: MarketMirrorScenarioPacket
    actors: list[MarketActorProfile]

    @property
    def packets(self) -> list[MarketActorProfile | MarketMirrorScenarioPacket]:
        return [*self.actors, self.scenario]


def _scenario_id(symbol: str, evidence_refs: Iterable[str]) -> str:
    digest = hashlib.sha256(
        "|".join([symbol.upper(), *sorted(evidence_refs)]).encode("utf-8")
    ).hexdigest()[:16]
    return f"market-mirror-{symbol.upper()}-{digest}"


def build_market_mirror_panel(
    *,
    symbol: str,
    evidence_refs: list[str] | None = None,
    rounds: int = 2,
    max_actors: int = 9,
) -> MarketMirrorResult:
    safe_symbol, changed = redact_research_text(symbol)
    if changed or not safe_symbol.strip():
        raise ValueError("market mirror symbol must be a public ticker, not private text")
    normalized_symbol = safe_symbol.strip().upper()
    refs = [ref for ref in (evidence_refs or []) if ref]
    actor_specs = DEFAULT_ACTORS[: max(1, min(max_actors, len(DEFAULT_ACTORS)))]
    actors: list[MarketActorProfile] = []
    for actor_id, actor_type, stance in actor_specs:
        actor = MarketActorProfile(
            actor_id=f"{normalized_symbol}:{actor_id}",
            actor_type=actor_type,
            stance=stance,
            thesis=(
                f"{actor_type} reviews {normalized_symbol} as advisory context only; "
                "deterministic policy still decides hold, paper, shadow, or live eligibility."
            ),
            invalidators=[
                "stale source packet",
                "support break with rising volume",
                "macro or sector contradiction",
                "PDT-reform crowding turns strength into spike-chasing",
                "live gate or risk envelope block",
            ],
            evidence_refs=refs,
            tool_route="market_mirror_clean_room",
            redaction_status="redacted" if changed else "no_secrets_seen",
            freshness={
                "rounds": max(1, min(rounds, 3)),
                "clean_room": "MiroFish-inspired actor simulation; no copied external code or prompts",
                "execution_authority": "none",
                "forbidden_effects": [
                    "create_trade_intent",
                    "size_position",
                    "submit_order",
                    "promote_sleeve",
                    "waive_live_gate",
                ],
            },
        )
        actors.append(actor)
    scenario = MarketMirrorScenarioPacket(
        scenario_id=_scenario_id(normalized_symbol, refs),
        symbol=normalized_symbol,
        actor_profile_refs=[actor.packet_id for actor in actors],
        consensus=(
            f"{normalized_symbol} needs deterministic confirmation; mirror panel is advisory "
            "and cannot authorize orders."
        ),
        disagreements=[
            "momentum actor may like strength before risk manager accepts drawdown risk",
            "new intraday traders and AI-bot operators may overreact before fundamentals catch up",
            "sector specialist may require peer confirmation before portfolio manager adds risk",
        ],
        watch_items=[
            "open-position mention in social/crawler evidence",
            "overnight top-candidate status",
            "support/ATR depth changes",
            "PDT reform / intraday margin transition crowding",
            "retail euphoria, panic, or AI-bot herding after sudden moves",
            "fresh macro or filing invalidator",
        ],
        confidence="medium",
        source_refs=refs,
        tool_route="market_mirror_clean_room",
        redaction_status="redacted" if changed else "no_secrets_seen",
        freshness={
            "rounds": max(1, min(rounds, 3)),
            "actor_count": len(actors),
            "execution_authority": "none",
            "forbidden_effects": [
                "create_trade_intent",
                "size_position",
                "submit_order",
                "promote_sleeve",
                "waive_live_gate",
            ],
        },
    )
    return MarketMirrorResult(scenario=scenario, actors=actors)


def label_market_mirror_outcome(
    scenario: MarketMirrorScenarioPacket,
    forecasts: Iterable[AgentForecast],
) -> MarketMirrorScenarioPacket:
    """Label whether mirror caution helped after same-symbol forecasts resolve."""

    resolved = [
        forecast
        for forecast in forecasts
        if forecast.ticker.upper() == scenario.symbol.upper()
        and forecast.resolved
        and forecast.outcome is not None
    ]
    freshness = dict(scenario.freshness or {})
    freshness["execution_authority"] = "none"
    freshness.setdefault(
        "forbidden_effects",
        [
            "create_trade_intent",
            "size_position",
            "submit_order",
            "promote_sleeve",
            "waive_live_gate",
        ],
    )
    freshness["resolved_forecast_count"] = len(resolved)
    freshness["matched_forecast_ids"] = [forecast.forecast_id for forecast in resolved[:20]]
    if not resolved:
        return scenario.model_copy(
            update={
                "usefulness_label": "pending",
                "outcome_label": "unresolved",
                "quality_score": None,
                "outcome_notes": "No same-symbol resolved forecasts are available yet.",
                "freshness": freshness,
            }
        )
    wins = sum(1 for forecast in resolved if forecast.outcome is True)
    misses = sum(1 for forecast in resolved if forecast.outcome is False)
    total = max(len(resolved), 1)
    score = round((misses - wins) / total, 3)
    freshness["forecast_win_count"] = wins
    freshness["forecast_miss_count"] = misses
    if misses and not wins:
        usefulness_label = "useful"
        outcome_label = "helped"
        notes = "Mirror caution was useful because same-symbol forecasts missed."
    elif wins and not misses:
        usefulness_label = "harmful"
        outcome_label = "hurt"
        notes = "Mirror caution likely over-warned because same-symbol forecasts worked."
    else:
        usefulness_label = "mixed"
        outcome_label = "neutral"
        notes = "Mirror caution had mixed evidence after same-symbol forecasts resolved."
    latest_resolved_at = sorted(
        [forecast.resolved_at for forecast in resolved if forecast.resolved_at]
    )
    return scenario.model_copy(
        update={
            "usefulness_label": usefulness_label,
            "outcome_label": outcome_label,
            "quality_score": score,
            "outcome_notes": notes,
            "resolved_at": latest_resolved_at[-1] if latest_resolved_at else None,
            "freshness": freshness,
        }
    )
