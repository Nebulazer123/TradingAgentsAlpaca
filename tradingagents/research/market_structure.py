"""Market-structure policy packets for overnight planning."""

from __future__ import annotations

import datetime
from typing import Any

from tradingagents.dataflows._official_common import evidence_packet, request_hash

UTC = datetime.timezone.utc
PDT_REFORM_APPROVED_AT = datetime.datetime(2026, 4, 14, tzinfo=UTC)
REGULATORY_STATUS = "approved_pending_finra_notice_or_broker_adoption"
ALPACA_INTRADAY_MARGIN_DOC = (
    "https://docs.alpaca.markets/us/docs/"
    "understanding-finras-new-intraday-margin-rule-and-the-end-of-pdt"
)
SEC_INTRADAY_MARGIN_ORDER = "https://www.sec.gov/files/rules/sro/finra/2026/34-105226.pdf"
FINRA_INTRADAY_MARGIN_FILING = (
    "https://www.finra.org/rules-guidance/rule-filings/sr-finra-2025-017"
)
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
    reform_active_for_account: bool | None = None,
    adoption_evidence_source: str | None = None,
    adoption_evidence_as_of: str | None = None,
) -> Any:
    """Return advisory context for the approved, not universally effective, reform."""

    reference_time = _as_utc(now)
    if reform_active_for_account is not None and not adoption_evidence_source:
        raise ValueError("account-specific reform status requires adoption_evidence_source")
    adoption_state: bool | str = (
        reform_active_for_account if reform_active_for_account is not None else "unknown"
    )
    reform_active = reform_active_for_account is True
    payload = {
        "policy": {
            "execution_authority": "none",
            "forbidden_effects": list(FORBIDDEN_MARKET_STRUCTURE_EFFECTS),
            "source_role": "market-structure context only",
        },
        "regulatory_status": REGULATORY_STATUS,
        "approval_date": PDT_REFORM_APPROVED_AT.date().isoformat(),
        "effective_date": None,
        "reference_time": reference_time.isoformat(timespec="seconds"),
        "reform_active_for_account": adoption_state,
        "adoption_evidence_source": adoption_evidence_source,
        "adoption_evidence_as_of": adoption_evidence_as_of,
        "rule_interpretation": {
            "old_pdt_designation_removed": reform_active,
            "old_three_day_trades_in_five_business_days_counter_removed": reform_active,
            "old_25000_pdt_minimum_removed": reform_active,
            "old_day_trading_buying_power_logic_removed": reform_active,
            "new_framework": "approved intraday margin and risk monitoring transition",
            "phase_in_may_vary_by_broker": True,
        },
        "planner_flags": {
            "ignore_old_pdt_trade_count_gate": reform_active,
            "ignore_old_25000_pdt_minimum_gate": reform_active,
            "requires_fresh_broker_buying_power_check": True,
            "requires_intraday_margin_context": True,
            "market_structure_transition": True,
            "crowd_ai_bot_unpredictability": reform_active,
            "prefer_buy_the_dip_over_chasing_green_spikes": True,
            "requires_fresh_post_spike_validation": True,
            "mirrorfish_society_reaction_required": True,
        },
        "mirrorfish_prompt_seed": {
            "scenario": (
                "FINRA's intraday-margin reform is approved but awaits an announced effective "
                "date or account-specific broker adoption; model phased-transition behavior only."
            ),
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
            SEC_INTRADAY_MARGIN_ORDER,
            FINRA_INTRADAY_MARGIN_FILING,
        ],
    }
    source_ref = "local://market_structure/intraday_margin_rule_pending_adoption"
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
            "regulatory_status": REGULATORY_STATUS,
            "effective_date": None,
            "reform_active_for_account": adoption_state,
            "adoption_evidence_as_of": adoption_evidence_as_of,
        },
    )
