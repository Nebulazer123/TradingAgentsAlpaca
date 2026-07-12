"""Runtime helpers for scheduled-event launch context.

These helpers are intentionally pure and dependency-light so docs checks can
verify launch behavior without importing OASIS or starting a simulation.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


BRANCH_CAUSE_PROMPT = (
    "Compare PDT/retail flow against macro/rates, Treasury auctions, jobs/CPI/PPI, "
    "oil/geopolitics, AI/semiconductor catalysts, options-expiration mechanics, "
    "broker/platform rollout differences, broker friction, and institutional "
    "liquidity response."
)

BROKER_SEGMENTATION_PROMPT = (
    "Account cues: cash vs margin, equity bucket, options approval, API/bot "
    "access, broker/platform rollout differences, buying-power and margin confusion."
)

OPTIONS_MICROSTRUCTURE_PROMPT = (
    "Options/microstructure cues: options-expiration mechanics, weekly expiry, "
    "0DTE, SPY/QQQ/TSLA/AAPL, physical vs cash-settled confusion, "
    "assignment/exercise, IV/gamma/OI/volume/spread/liquidity, market-maker, "
    "dealer, and ETF desk response."
)

LIVE_CONTEXT_PROMPT = (
    "Live context patch: June 4-13 event window, fragmented broker/platform "
    "rollout differences, macro/rates gates, Treasury auctions, Apple/AI/"
    "semiconductor catalysts, oil/geopolitics, and advisory TradingAgents "
    "purpose only."
)

FORECAST_BALLOT_PROMPT = (
    "Forecast ballot required this round: estimate branch probabilities for "
    "mostly narrative, medium retail-flow, large speculative-flow, adverse "
    "macro override, valid-support, broker-friction, bot-correlation, "
    "institutional-liquidity, policy/media clarification, "
    "developer-infrastructure, and no meaningful retail-flow control. Include "
    "confidence 0-100, evidence used, what would change your mind, affected "
    "tickers/categories, and causal attribution."
)


def _as_positive_int(value: Any) -> Optional[int]:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _as_list(value: Any) -> List[Any]:
    return value if isinstance(value, list) else []


def config_total_rounds(config: Dict[str, Any]) -> int:
    """Return the configured round count from time_config."""
    time_config = config.get("time_config") if isinstance(config.get("time_config"), dict) else {}
    total_hours = _as_positive_int(time_config.get("total_simulation_hours")) or 72
    minutes_per_round = _as_positive_int(time_config.get("minutes_per_round")) or 30
    return int((total_hours * 60) // minutes_per_round)


def scheduled_events(config: Dict[str, Any]) -> List[Dict[str, Any]]:
    event_config = config.get("event_config") if isinstance(config.get("event_config"), dict) else {}
    return [event for event in _as_list(event_config.get("scheduled_events")) if isinstance(event, dict)]


def resolve_effective_max_rounds(
    config: Dict[str, Any],
    requested_max_rounds: Optional[int] = None,
) -> Optional[int]:
    """Resolve the max-round cap that should reach the runner.

    An explicit positive request wins. If no request is supplied and the config
    has scheduled events, use the scheduled-event count as the launch cap. This
    prevents prepared 30-beat runs from drifting into uncovered generic rounds.
    Return None only when there is no explicit cap and no scheduled-event cap.
    """
    configured_rounds = config_total_rounds(config)
    requested = _as_positive_int(requested_max_rounds)
    if requested:
        return min(configured_rounds, requested)

    event_count = len(scheduled_events(config))
    if event_count:
        return min(configured_rounds, event_count)

    return None


def max_rounds_source(config: Dict[str, Any], requested_max_rounds: Optional[int] = None) -> str:
    if _as_positive_int(requested_max_rounds):
        return "request"
    if scheduled_events(config):
        return "scheduled_events_default"
    return "time_config"


def get_round_event_context(
    config: Dict[str, Any],
    round_num: int,
    platform: Optional[str] = None,
) -> Dict[str, Any]:
    """Return normalized scheduled-event metadata for a 1-based round."""
    round_int = _as_positive_int(round_num)
    if not round_int:
        return {}

    match: Optional[Dict[str, Any]] = None
    for event in scheduled_events(config):
        if _as_positive_int(event.get("round")) == round_int:
            match = event
            break
    if not match:
        return {}

    predictive = config.get("predictive_quality_upgrade")
    if not isinstance(predictive, dict):
        predictive = {}

    date = str(match.get("date") or "")
    event_beat_id = str(match.get("event_beat_id") or f"{date or 'round'}-r{round_int:02d}")
    metadata = {
        "round": round_int,
        "event_beat_id": event_beat_id,
        "date": date,
        "window": str(match.get("window") or date),
        "beat": str(match.get("beat") or ""),
        "primary_catalysts": [str(item) for item in _as_list(match.get("primary_catalysts"))],
        "interpretation_note": str(match.get("interpretation_note") or match.get("note") or ""),
        "state_variable_focus": [str(item) for item in _as_list(match.get("state_variable_focus"))],
        "scenario_pressure": str(match.get("scenario_pressure") or BRANCH_CAUSE_PROMPT),
        "forecast_ballot_required": bool(match.get("forecast_ballot_required")),
        "control_branch_check": bool(match.get("control_branch_check")),
        "platform_lane": platform or "",
        "runtime_context_items": [
            "event beat map",
            "state variables",
            "forecast ballot markers",
            "causal attribution hints",
            "options/microstructure brief",
            "live context patch",
            "broker/account segmentation cues",
            "control/counterfactual branch",
            "TradingAgents advisory purpose",
        ],
        "forecast_branches": [str(item) for item in _as_list(predictive.get("forecast_branches"))],
        "state_variables_all": [str(item) for item in _as_list(predictive.get("state_variables"))],
        "control_branch": str(predictive.get("control_branch") or ""),
    }
    return metadata


def format_round_event_context_post(
    config: Dict[str, Any],
    round_num: int,
    platform: str,
) -> str:
    """Build the compact context post injected before active agents act."""
    event = get_round_event_context(config, round_num, platform)
    if not event:
        return ""

    lane = "Twitter/common lane" if platform == "twitter" else "Reddit/boost lane"
    catalysts = "; ".join(event["primary_catalysts"]) or "none listed"
    state_focus = "; ".join(event["state_variable_focus"]) or "branch_confidence_distribution"
    control_branch = event.get("control_branch") or (
        "No meaningful retail-flow effect: chatter rises but macro, broker controls, "
        "and unconfirmed realized flow dominate."
    )

    lines = [
        f"[Stage03 runtime event beat] beat_id={event['event_beat_id']}",
        (
            f"Lane: {lane}. Round {event['round']} | Date/window: {event['window']} | "
            f"Beat: {event['beat']}"
        ),
        f"Catalysts to react to: {catalysts}.",
        f"State-variable focus: {state_focus}.",
        f"Causal attribution: {event['scenario_pressure'] or BRANCH_CAUSE_PROMPT}",
        BROKER_SEGMENTATION_PROMPT,
        OPTIONS_MICROSTRUCTURE_PROMPT,
        LIVE_CONTEXT_PROMPT,
        f"Control branch check: {control_branch}",
    ]

    if event.get("forecast_ballot_required"):
        lines.append(FORECAST_BALLOT_PROMPT)
    else:
        lines.append(
            "No formal forecast ballot is required this round, but preserve branch "
            "probability reasoning and false-attribution skepticism in your actions."
        )

    return "\n".join(lines)


def select_context_poster_agent_id(config: Dict[str, Any], platform: str) -> int:
    """Select a deterministic existing agent to publish runtime context posts."""
    preferred_by_platform = {
        "twitter": [
            "MediaOutlet",
            "BrokerPlatform",
            "RegulatorAgency",
            "Organization",
            "InstitutionalInvestor",
            "MarketStructureActor",
            "DeveloperCommunity",
        ],
        "reddit": [
            "MediaOutlet",
            "DeveloperCommunity",
            "BrokerPlatform",
            "RegulatorAgency",
            "Organization",
            "InstitutionalInvestor",
            "MarketStructureActor",
        ],
    }
    preferred = preferred_by_platform.get(platform, preferred_by_platform["twitter"])
    agent_configs = [cfg for cfg in _as_list(config.get("agent_configs")) if isinstance(cfg, dict)]

    for entity_type in preferred:
        candidates = [
            cfg for cfg in agent_configs
            if str(cfg.get("entity_type")) == entity_type and _as_positive_int(cfg.get("agent_id")) is not None
        ]
        if candidates:
            candidates.sort(key=lambda cfg: (-float(cfg.get("influence_weight", 1.0) or 1.0), int(cfg.get("agent_id", 0))))
            return int(candidates[0].get("agent_id"))

    for cfg in agent_configs:
        agent_id = _as_positive_int(cfg.get("agent_id"))
        if agent_id is not None:
            return agent_id
    return 0
