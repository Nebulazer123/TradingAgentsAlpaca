"""ChatGPT Deep Research operating protocol as analysis-only evidence.

This packet tells the research planner when to use the external Deep Research
lane and how to capture it reliably. It is a methodology/control-plane note,
not a trading signal.
"""

from __future__ import annotations

from typing import Any

from tradingagents.dataflows._official_common import evidence_packet, request_hash

FORBIDDEN_EFFECTS = [
    "create_trade_intent",
    "size_position",
    "submit_order",
    "promote_sleeve",
    "waive_live_gate",
]


RELIABLE_BROWSER_ROUTE: dict[str, Any] = {
    "start_page": "https://chatgpt.com/deep-research",
    "visual_fingerprints": [
        "large composer with a Deep research chip",
        "model selector showing Pro or Pro - Extended before send",
        "completed report card showing research count/citation count metadata",
    ],
    "mode_selector_routes": [
        {
            "route": "dropdown",
            "steps": [
                "click the composer model selector",
                "choose Pro or Pro - Extended",
                "confirm the composer label changed before sending",
            ],
        },
        {
            "route": "slash_picker_backup",
            "steps": [
                "focus the composer textbox",
                "type /",
                "use the keyboard/menu picker to select the desired Pro or Thinking mode",
                "confirm the composer label changed before sending",
            ],
        },
    ],
    "capture_failover_order": [
        "report save/download button if the report viewer exposes it",
        "normal assistant copy button after removing the Deep research chip",
        "ask normal chat mode to restate/export the completed report",
        "extract rendered assistant/report DOM text",
        "screenshots as a temporary checkpoint when text capture fails",
    ],
    "operator_auth_boundary": (
        "Codex may open the page and click obvious navigation controls, but the "
        "operator handles login/authentication if the session is not already active."
    ),
}


USE_CASES: list[dict[str, Any]] = [
    {
        "use_case": "phase_gate_due_diligence",
        "trigger": (
            "Before a new sleeve can move from research notes into a paper "
            "policy or from paper evidence toward tiny-live eligibility."
        ),
        "required_output": "critical implementation report with sources and open risks",
        "consumer": "implementation_plan_and_review_queue",
    },
    {
        "use_case": "methodology_destructive_review",
        "trigger": (
            "When a strategy sounds attractive but has not yet been translated "
            "into deterministic features, invalidators, and replay tests."
        ),
        "required_output": "what would make this strategy fail and how to test it",
        "consumer": "strategy_methodology_cards",
    },
    {
        "use_case": "source_or_provider_audit",
        "trigger": (
            "When a new API, crawler, social source, or model lane is being "
            "considered for recurring overnight research."
        ),
        "required_output": "authority boundary, provenance needs, rate-limit risks, and fallback routes",
        "consumer": "provider_fallback_policy",
    },
    {
        "use_case": "post_incident_explanation",
        "trigger": (
            "After a repeated blocker, confusing email, failed overnight run, "
            "or live-control safety lock that needs plain-English explanation."
        ),
        "required_output": "operator-safe explanation and self-heal sequence",
        "consumer": "ops_alert_renderer",
    },
]


def build_deep_research_protocol_packet():
    source_ref = (
        "local://reports/research_merge/"
        "CHATGPT_DEEP_RESEARCH_TECHNICAL_DUE_DILIGENCE_2026-06-02.md"
        "#deep-research-protocol"
    )
    return evidence_packet(
        source_name="chatgpt_deep_research_protocol",
        evidence_type="external_deep_research_methodology",
        subject="ChatGPT Deep Research Pro operating protocol",
        source_ref=source_ref,
        payload={
            "analysis_only": True,
            "execution_authority": "none",
            "forbidden_effects": FORBIDDEN_EFFECTS,
            "primary_route": {
                "name": "chatgpt_deep_research_pro",
                "ui_url": "https://chatgpt.com/deep-research",
                "mode": "Deep Research plus Pro or Extended when available",
                "preferred_entry": "dedicated Deep Research page",
                "normal_followup_mode": (
                    "remove the Deep Research chip before asking normal follow-up "
                    "questions so another long report is not spawned"
                ),
            },
            "reliable_browser_route": RELIABLE_BROWSER_ROUTE,
            "backup_routes": [
                "slash_picker_mode_selection",
                "mode_dropdown_selection",
                "normal_chat_export_prompt",
                "dom_rendered_text_extraction",
                "download_or_save_button_when_viewer_exposes_it",
                "browser_screenshot_for_visual_checkpoint",
                "local_markdown_artifact_when_copy_button_is_unreliable",
            ],
            "capture_steps": [
                "open ChatGPT Deep Research",
                "let the operator log in if needed",
                "select Pro/Extended through the model dropdown or slash picker",
                "attach sanitized prompt packet with no secrets",
                "send a short instruction that asks for a critical sourced report",
                "after completion, remove Deep Research mode before follow-up",
                "try the normal copy route",
                "if copy grabs the wrong message, extract rendered report text from the DOM",
                "save the artifact under reports/research_merge",
            ],
            "methodology_insert": {
                "tradingagents_role": "advisory_hypothesis_engine_only",
                "what_it_is_good_at": [
                    "structured synthesis",
                    "adversarial critique",
                    "implementation sequencing",
                    "authority-boundary review",
                    "source-backed methodology comparison",
                ],
                "what_it_must_not_do": [
                    "create orders",
                    "pick live size",
                    "approve promotion",
                    "waive stale data",
                    "replace deterministic feature packets",
                    "replace broker reconciliation",
                ],
                "required_before_influence": [
                    "packetized recommendation",
                    "explicit source list or missing-source note",
                    "deterministic test or replay hook",
                    "Agent Intelligence Ledger forecast if it makes a market claim",
                    "paper evidence before promotion influence",
                ],
            },
            "when_tradingagents_should_use_deep_research": [
                "before promoting a new methodology from idea to paper policy",
                "before any advisory overlay can influence a promotion gate",
                "when a source/provider route needs a destructive audit",
                "when a confusing incident needs a clear operator-safe explanation",
                "when replay/ablation design needs an outside critical reviewer",
            ],
            "use_cases": USE_CASES,
            "plain_english": (
                "Deep Research is the outside expert reviewer. It can tell Codex "
                "what to build, what to doubt, and what evidence is missing. It "
                "cannot tell the bot to spend money."
            ),
        },
        quality="medium",
        request_fingerprint=request_hash(
            "LOCAL",
            source_ref,
            None,
            {"use_case_count": len(USE_CASES)},
        ),
        tool_route="local_chatgpt_deep_research_protocol",
        redaction_status="no_secrets_seen",
        freshness_extra={
            "read_only": True,
            "use_case_count": len(USE_CASES),
            "mode_route_count": len(RELIABLE_BROWSER_ROUTE["mode_selector_routes"]),
            "capture_failover_count": len(RELIABLE_BROWSER_ROUTE["capture_failover_order"]),
            "captured_report_date": "2026-06-02",
        },
    )
