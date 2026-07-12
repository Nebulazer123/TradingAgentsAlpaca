"""Market-structure policy packets for overnight planning."""

from __future__ import annotations

import datetime
from typing import Any

from tradingagents.dataflows._official_common import evidence_packet, request_hash

UTC = datetime.timezone.utc
PDT_REFORM_EFFECTIVE_AT = datetime.datetime(2026, 6, 4, tzinfo=UTC)
ALPACA_INTRADAY_MARGIN_DOC = "https://docs.alpaca.markets/docs/the-intraday-margin-rule"
FINRA_INTRADAY_MARGIN_NOTICE = "https://www.finra.org/rules-guidance/notices/25-14"
FORBIDDEN_MARKET_STRUCTURE_EFFECTS = (
    "create_trade_intent",
    "size_position",
    "submit_order",
    "promote_sleeve",
    "waive_live_gate",
)


def _as_utc(value: datetime.datetime | None = None) -> datetime.datetime:
    current = value or datetime.datetime.now(tz=UTC)
    if current.tzinfo is None:
        return current.replace(tzinfo=UTC)
    return current.astimezone(UTC)


def build_intraday_margin_market_structure_packet(
    *,
    now: datetime.datetime | None = None,
) -> Any:
    """Return an advisory packet for the June 2026 PDT-to-intraday-margin regime."""

    reference_time = _as_utc(now)
    reform_active = reference_time.date() >= PDT_REFORM_EFFECTIVE_AT.date()
    transition_window = reference_time.date() <= datetime.date(2026, 7, 3)
    payload = {
        "policy": {
            "execution_authority": "none",
            "forbidden_effects": list(FORBIDDEN_MARKET_STRUCTURE_EFFECTS),
            "source_role": "market-structure context only",
        },
        "effective_date": PDT_REFORM_EFFECTIVE_AT.date().isoformat(),
        "reference_time": reference_time.isoformat(timespec="seconds"),
        "reform_active": reform_active,
        "rule_interpretation": {
            "old_pdt_designation_removed": True,
            "old_three_day_trades_in_five_business_days_counter_removed": True,
            "old_25000_pdt_minimum_removed": True,
            "old_day_trading_buying_power_logic_removed": True,
            "new_framework": "intraday margin and risk monitoring",
        },
        "planner_flags": {
            "ignore_old_pdt_trade_count_gate": True,
            "ignore_old_25000_pdt_minimum_gate": True,
            "requires_fresh_broker_buying_power_check": True,
            "requires_intraday_margin_context": True,
            "market_structure_transition": transition_window,
            "crowd_ai_bot_unpredictability": transition_window,
            "prefer_buy_the_dip_over_chasing_green_spikes": True,
            "requires_fresh_post_spike_validation": True,
            "mirrorfish_society_reaction_required": True,
        },
        "mirrorfish_prompt_seed": {
            "scenario": "Retail traders and AI trading bots get broader access to intraday trading after old PDT constraints are removed.",
            "actors_to_include": [
                "new retail day trader",
                "AI-bot operator",
                "risk manager",
                "liquidity provider",
                "momentum chaser",
                "dip buyer",
                "news/social amplifier",
            ],
            "questions": [
                "Which setups become crowded quickly?",
                "Where does buying strength turn into chasing?",
                "Where do panic dips become real falling knives?",
                "Which tickers are most likely to see retail euphoria or forced exits?",
            ],
        },
        "source_urls": [
            ALPACA_INTRADAY_MARGIN_DOC,
            FINRA_INTRADAY_MARGIN_NOTICE,
        ],
    }
    source_ref = "local://market_structure/intraday_margin_rule_2026-06-04"
    return evidence_packet(
        source_name="market_structure_policy",
        evidence_type="intraday_margin_regime",
        subject="pdt_reform_intraday_margin_transition",
        source_ref=source_ref,
        payload=payload,
        quality="high",
        request_fingerprint=request_hash("READ", source_ref, None, payload),
        tool_route="local_market_structure_policy",
        redaction_status="no_secrets_seen",
        freshness_extra={
            "read_only": True,
            "effective_date": PDT_REFORM_EFFECTIVE_AT.date().isoformat(),
            "reform_active": reform_active,
            "transition_window": transition_window,
        },
    )
