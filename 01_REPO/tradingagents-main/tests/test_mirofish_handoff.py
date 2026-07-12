import json
from pathlib import Path

from typer.testing import CliRunner

from cli.main import app
from tradingagents.research import mirofish_handoff
from tradingagents.research.mirofish_handoff import (
    build_compact_mirofish_handoff_status,
    build_mirofish_handoff_status,
    build_mirofish_source_context_packet,
    resolve_required_report_id,
)

runner = CliRunner()


def _write_scaffold(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "# MiroFish Pending Learning Scaffold",
                "",
                "Status: DRAFT ONLY - NOT FINAL, NOT SENDABLE, NOT A COMPLETED RUN HANDOFF.",
                "",
                "## Hard Boundary",
                "",
                "- Do not create, size, submit, promote, or cancel orders from this file.",
                "",
                "## Current MiroFish Prep Artifacts",
                "",
                "`C:\\Users\\Corbin\\Documents\\Coding projects\\mirofish-main`",
                "`C:\\Users\\Corbin\\Documents\\Coding projects\\mirofish-main\\docs\\mirror_fish\\MIRROR_FISH_PDT_REALITY_SEED.md`",
                "`C:\\Users\\Corbin\\Downloads\\deep-research-report (32).md`",
                "",
                "## Expected Final Handoff Contents After The Run",
                "",
                "- MiroFish project metadata and extracted seed.",
                "- Stage 04 ReportAgent report and section artifacts.",
                "- Codex extra-high synthesis converting MiroFish output into TradingAgents advisory evidence.",
                "",
                "Final handoff should include:",
                "",
                "- executive summary",
                "",
                "## Current Missing Pieces",
                "",
                "- The real MiroFish simulation has not started.",
                "- No final handoff exists yet.",
            ]
        ),
        encoding="utf-8",
    )


def _write_minimal_final_handoff(path: Path, *, report_id: str) -> None:
    path.write_text(
        "\n".join(
            [
                "# MiroFish Final TradingAgents Handoff",
                "",
                "Advisory only / no execution authority.",
                "",
                "## Machine-readable advisory packet",
                "",
                "```json",
                json.dumps(
                    {
                        "status": "final_advisory_no_execution_authority",
                        "execution_authority": "none",
                        "report_id": report_id,
                        "simulation_id": "simulated-regression",
                    }
                ),
                "```",
            ]
        ),
        encoding="utf-8",
    )


def test_mirofish_scaffold_builds_advisory_pending_packet(tmp_path: Path):
    scaffold = tmp_path / "MIROFISH_PENDING_LEARNING_SCAFFOLD.md"
    final_handoff = tmp_path / "MIROFISH_FINAL_TRADINGAGENTS_HANDOFF.md"
    _write_scaffold(scaffold)

    packet = build_mirofish_handoff_status(
        scaffold_path=scaffold,
        final_handoff_path=final_handoff,
    )

    status_signal = next(signal for signal in packet.signals if signal["type"] == "mirofish_handoff_status")
    boundary_signal = next(signal for signal in packet.signals if signal["type"] == "clean_room_boundary")

    assert packet.analysis_only is True
    assert packet.subject == "MiroFish external-run handoff status"
    assert status_signal["status"] == "pending_final_handoff"
    assert status_signal["final_handoff_available"] is False
    assert boundary_signal["execution_authority"] == "none"
    assert boundary_signal["agpl_code_import_allowed"] is False
    assert packet.freshness["forbidden_effects"] == [
        "create_trade_intent",
        "size_position",
        "submit_order",
        "promote_sleeve",
        "waive_live_gate",
    ]
    assert packet.freshness["clean_room"]["source_code_imported"] is False
    assert packet.freshness["can_submit_orders"] is False
    assert packet.freshness["prohibited_use"] == "direct_trade_trigger"
    assert packet.freshness["final_handoff_paths"] == []
    assert packet.freshness["available_artifact_count"] >= 1
    assert packet.freshness["morning_bot_instruction"].startswith("Use this packet")
    assert "No final MiroFish handoff is available yet" in packet.summary
    assert str(scaffold) in packet.source_refs
    assert len(packet.evidence_refs) == 3


def test_mirofish_discovers_final_handoff_and_exports_source_context(tmp_path: Path):
    scaffold = tmp_path / "MIROFISH_PENDING_LEARNING_SCAFFOLD.md"
    final_handoff = tmp_path / "MIROFISH_FINAL_TRADINGAGENTS_HANDOFF.md"
    full_report = tmp_path / "full_report.md"
    _write_scaffold(scaffold)
    full_report.write_text(
        "\n".join(
            [
                "# Full MiroFish Report",
                "",
                "**AI-Bot Correlation and Institutional Liquidity Adaptation**",
                "",
                (
                    "AI-assisted traders and prompt-bot operators converge on obvious "
                    "signals, increasing false-positive crowding. Institutional market "
                    "makers fade or temporarily amplify novice clustering to manage "
                    "order-flow toxicity."
                ),
                "",
                "```json",
                json.dumps(
                    {
                        "scenario_branches": {
                            "bot_correlation_false_positive": {
                                "effect": "compressed_reaction_time_reflexive_spikes"
                            },
                            "institutional_liquidity_response": {
                                "stance": "fade_or_absorb",
                                "effect": "dampens_novice_clustering",
                            },
                        },
                        "key_state_variables_and_signals": {
                            "AI_bot_copycat_index": {
                                "description": "Measures convergence of automated traders on simplified narratives.",
                                "peak_periods": ["round_7", "round_8"],
                            },
                            "false_signal_risk_index": {
                                "correlation": "high_with_AI_bot_copycat_index_and_macro_waiting_periods"
                            },
                        },
                        "validation_tasks_for_real_market_data": [
                            "Confirm institutional fade/absorb behavior via order-flow toxicity metrics and market-maker spread adjustments.",
                            "Validate AI-bot correlation spikes against independent volume confirmation and institutional participation.",
                        ],
                        "risk_gates_and_false_positive_filters": {
                            "liquidity_trap": "Institutional desks fading novice clustering.",
                            "weekend_consolidation_risk": "Copycat bot templates and reflexive spikes.",
                        },
                        "confidence_and_uncertainty": {
                            "high_confidence": [
                                "Institutional liquidity providers fade or absorb novice clustering."
                            ],
                            "model_bias_warning": "Treat social volume as confusion proxy, not liquidity measure.",
                        },
                    }
                ),
                "```",
            ]
        ),
        encoding="utf-8",
    )
    final_handoff.write_text(
        "\n".join(
            [
                "# MiroFish Final TradingAgents Handoff",
                "",
                "Advisory only / no execution authority.",
                "",
                "## Scenario Branches To Track",
                "",
                "1. Narrative-only / limited flow effect.",
                "2. Bot-correlation branch around SPY, QQQ, TSLA, and AAPL.",
                "",
                "## Morning Validation Queue",
                "",
                "- Confirm broker/account evidence before using PDT chatter.",
                "- Check 0DTE volume/OI/spread support for SPY, QQQ, TSLA, and AAPL.",
                "",
                "## False-Signal Filters",
                "",
                "- Social heat without broker/account evidence is narrative, not flow.",
                "",
                "## Stage 05 Interview Targets",
                "",
                "- Webull 0874, BrokerPlatform, 11 actions",
                "",
                "## Machine-readable advisory packet",
                "",
                "```json",
                json.dumps(
                    {
                        "status": "final_advisory_no_execution_authority",
                        "execution_authority": "none",
                        "report_id": "report_1e3059f732b1",
                        "simulation_id": "sim_test",
                        "staleness": {
                            "valid_window": "2026-06-04 through 2026-06-13",
                            "expires_after": "2026-06-13 market close unless refreshed",
                            "requires_refresh": ["before tomorrow premarket brief", "at market open"],
                        },
                        "primary_hypotheses": [
                            "PDT-related narratives can raise retail attention but do not prove executable flow."
                        ],
                        "source_artifacts": {
                            "stage04_report": "C:\\stage04\\full_report.md",
                            "full_report": str(full_report),
                            "review_packet_zip": (
                                "C:\\Users\\Corbin\\Documents\\Coding projects\\mirofish-main"
                                "\\backend\\uploads\\reports\\report_1e3059f732b1"
                                "\\review_packet_report_1e3059f732b1.zip"
                            ),
                        },
                    }
                ),
                "```",
            ]
        ),
        encoding="utf-8",
    )

    packet = build_mirofish_handoff_status(
        scaffold_path=scaffold,
        final_handoff_path=final_handoff,
    )
    source_packet = build_mirofish_source_context_packet(
        scaffold_path=scaffold,
        final_handoff_path=final_handoff,
    )

    status_signal = next(signal for signal in packet.signals if signal["type"] == "mirofish_handoff_status")

    assert status_signal["status"] == "final_handoff_available"
    assert status_signal["final_handoff_available"] is True
    assert str(final_handoff) in status_signal["final_handoff_paths"]
    assert packet.freshness["execution_authority"] == "none"
    assert packet.freshness["final_advisory_available"] is True
    assert packet.freshness["advisory_valid_window"] == "2026-06-04 through 2026-06-13"
    assert packet.freshness["advisory_expires_after"] == "2026-06-13 market close unless refreshed"
    assert packet.freshness["advisory_requires_refresh"] == [
        "before tomorrow premarket brief",
        "at market open",
    ]
    assert packet.freshness["review_packet_zip"].endswith("review_packet_report_1e3059f732b1.zip")
    assert packet.freshness["acceptance_decision_path"].endswith(
        "MIRROR_FISH_FINAL_ACCEPTANCE_DECISION.md"
    )
    assert packet.freshness["full_report_highlight_available"] is True
    assert packet.freshness["full_report_source_path"] == str(full_report)
    assert "AI-bot copycat spikes" in packet.freshness["full_report_core_filter"]
    assert packet.freshness["full_report_ai_bot_liquidity_available"] is True
    assert "order-flow toxicity" in packet.freshness["full_report_ai_bot_liquidity_summary"]
    assert packet.freshness["scenario_branch_count"] == 2
    assert packet.freshness["validation_task_count"] == 2
    assert packet.freshness["false_signal_filter_count"] == 1
    assert packet.freshness["attention_symbols"] == ["SPY", "QQQ", "TSLA", "AAPL"]
    assert source_packet.source_name == "mirofish_handoff"
    assert source_packet.analysis_only is True
    assert source_packet.quality == "high"
    assert source_packet.payload["final_handoff_available"] is True
    assert str(final_handoff) in source_packet.payload["final_handoff_paths"]
    assert source_packet.payload["scenario_branches"][0]["scenario_id"] == "mirofish_branch_1"
    assert source_packet.payload["validation_tasks"]
    assert source_packet.payload["false_signal_filters"]
    assert source_packet.payload["advisory_valid_window"] == "2026-06-04 through 2026-06-13"
    assert source_packet.payload["advisory_requires_refresh"] == [
        "before tomorrow premarket brief",
        "at market open",
    ]
    assert source_packet.payload["review_packet_zip"].endswith("review_packet_report_1e3059f732b1.zip")
    assert source_packet.payload["acceptance_decision_path"].endswith(
        "MIRROR_FISH_FINAL_ACCEPTANCE_DECISION.md"
    )

    compact = build_compact_mirofish_handoff_status(
        packet,
        packet_path=tmp_path / "mirofish-status.json",
    )

    assert compact["schema"] == "compact_mirofish_handoff_status_v1"
    assert compact["analysis_only"] is True
    assert compact["raw_packet_path"].endswith("mirofish-status.json")
    assert compact["freshness"]["mirofish_status"] == "final_handoff_available"
    assert compact["freshness"]["final_handoff_available"] is True
    assert compact["freshness"]["execution_authority"] == "none"
    assert compact["freshness"]["can_submit_orders"] is False
    assert compact["freshness"]["scenario_branch_count"] == 2
    assert compact["freshness"]["attention_symbols"] == ["SPY", "QQQ", "TSLA", "AAPL"]
    assert "signals" not in compact
    highlights = source_packet.payload["full_report_highlights"]
    assert highlights["source_path"] == str(full_report)
    assert highlights["source_sha256"]
    assert any(
        report["path"] == str(full_report) and report["selected"]
        for report in highlights["candidate_reports"]
    )
    assert highlights["institutional_liquidity_response"]["stance"] == "fade_or_absorb"
    assert highlights["bot_correlation_false_positive"]["effect"] == "compressed_reaction_time_reflexive_spikes"
    assert highlights["ai_bot_copycat_index"]["peak_periods"] == ["round_7", "round_8"]
    assert highlights["advisory_gate_verdict"]["action"] == "flag"
    assert highlights["advisory_gate_verdict"]["triggered_gates"] == ["attribution_error"]
    assert "macro_attribution" in highlights["advisory_gate_verdict"]["required_validations"]
    assert packet.freshness["mirofish_advisory_gate_action"] == "flag"
    assert packet.freshness["mirofish_advisory_triggered_gates"] == ["attribution_error"]
    assert "liquidity_trap" in highlights["risk_gates"]
    assert highlights["ai_bot_liquidity_adaptation"]["section_available"] is True
    assert "false-positive crowding" in highlights["ai_bot_liquidity_adaptation"]["excerpt"]
    assert "market_maker_spread_or_depth_confirmation" in (
        highlights["ai_bot_liquidity_adaptation"]["validation_gates"]
    )
    assert highlights["execution_authority"] == "none"
    assert source_packet.payload["forecast_symbols"] == ["QQQ", "TSLA", "AAPL"]
    assert source_packet.payload["execution_authority"] == "none"
    assert source_packet.payload["can_submit_orders"] is False
    assert source_packet.payload["prohibited_use"] == "direct_trade_trigger"
    assert "submit_order" in source_packet.payload["forbidden_effects"]


def test_mirofish_preserves_full_report_prose_liquidity_section_without_json(tmp_path: Path):
    scaffold = tmp_path / "MIROFISH_PENDING_LEARNING_SCAFFOLD.md"
    final_handoff = tmp_path / "MIROFISH_FINAL_TRADINGAGENTS_HANDOFF.md"
    full_report = tmp_path / "full_report.md"
    _write_scaffold(scaffold)
    full_report.write_text(
        "\n".join(
            [
                "# Full MiroFish Report",
                "",
                "**AI-Bot Correlation and Institutional Liquidity Adaptation**",
                "",
                (
                    "AI-assisted traders and prompt-bot operators frequently converge "
                    "on identical, obvious signals, compressing reaction times and "
                    "increasing false-positive crowding. Institutional desks may fade, "
                    "absorb, or temporarily amplify the flow to manage order-flow toxicity."
                ),
                "",
                "**Operational Guidance for TradingAgents**",
                "",
                "Advisory only.",
            ]
        ),
        encoding="utf-8",
    )
    final_handoff.write_text(
        "\n".join(
            [
                "# MiroFish Final TradingAgents Handoff",
                "",
                "Advisory only / no execution authority.",
                "",
                "## Machine-readable advisory packet",
                "",
                "```json",
                json.dumps(
                    {
                        "status": "final_advisory_no_execution_authority",
                        "execution_authority": "none",
                        "report_id": "report_1e3059f732b1",
                        "source_artifacts": {"full_report": str(full_report)},
                    }
                ),
                "```",
            ]
        ),
        encoding="utf-8",
    )

    packet = build_mirofish_source_context_packet(
        scaffold_path=scaffold,
        final_handoff_path=final_handoff,
    )

    highlights = packet.payload["full_report_highlights"]
    liquidity = highlights["ai_bot_liquidity_adaptation"]
    assert liquidity["section_available"] is True
    assert "order-flow toxicity" in liquidity["excerpt"]
    assert "obvious-signal convergence" in highlights["core_filter"]
    assert "temporarily_amplify" in liquidity["institutional_response_watch"]
    assert packet.freshness["full_report_ai_bot_liquidity_available"] is True


def test_mirofish_full_report_combines_split_ai_bot_and_liquidity_sections(tmp_path: Path):
    scaffold = tmp_path / "MIROFISH_PENDING_LEARNING_SCAFFOLD.md"
    final_handoff = tmp_path / "MIROFISH_FINAL_TRADINGAGENTS_HANDOFF.md"
    full_report = tmp_path / "full_report.md"
    _write_scaffold(scaffold)
    full_report.write_text(
        "\n".join(
            [
                "# Full MiroFish Report",
                "",
                "## AI-bot and prompt-bot failure modes",
                "",
                (
                    "AI-assisted traders and prompt-bot users converge on obvious "
                    "breakouts, creating false-positive crowding before execution "
                    "evidence confirms durable flow."
                ),
                "",
                "## Institutional investor, market-maker, and liquidity-provider reaction map",
                "",
                (
                    "Market makers and institutional liquidity providers may fade, "
                    "absorb, or briefly amplify novice clustering while managing "
                    "order-flow toxicity."
                ),
            ]
        ),
        encoding="utf-8",
    )
    final_handoff.write_text(
        "\n".join(
            [
                "# MiroFish Final TradingAgents Handoff",
                "",
                "Advisory only / no execution authority.",
                "",
                "## Machine-readable advisory packet",
                "",
                "```json",
                json.dumps(
                    {
                        "status": "final_advisory_no_execution_authority",
                        "execution_authority": "none",
                        "report_id": "report_1e3059f732b1",
                        "source_artifacts": {"full_report": str(full_report)},
                    }
                ),
                "```",
            ]
        ),
        encoding="utf-8",
    )

    packet = build_mirofish_source_context_packet(
        scaffold_path=scaffold,
        final_handoff_path=final_handoff,
    )

    liquidity = packet.payload["full_report_highlights"]["ai_bot_liquidity_adaptation"]
    assert liquidity["section_available"] is True
    assert "prompt-bot users converge" in liquidity["excerpt"]
    assert "order-flow toxicity" in liquidity["excerpt"]
    assert packet.freshness["full_report_ai_bot_liquidity_available"] is True


def test_mirofish_full_report_candidates_include_downloaded_copy(monkeypatch, tmp_path: Path):
    scaffold = tmp_path / "MIROFISH_PENDING_LEARNING_SCAFFOLD.md"
    final_handoff = tmp_path / "MIROFISH_FINAL_TRADINGAGENTS_HANDOFF.md"
    backend_report = tmp_path / "backend" / "full_report.md"
    downloaded_report = tmp_path / "Downloads" / "full_report.md"
    backend_report.parent.mkdir(parents=True)
    downloaded_report.parent.mkdir(parents=True)
    _write_scaffold(scaffold)
    report_body = "\n".join(
        [
            "# Full MiroFish Report",
            "",
            "**AI-Bot Correlation and Institutional Liquidity Adaptation**",
            "",
            "AI-assisted traders converge on obvious signals while institutions fade order-flow toxicity.",
            "",
        ]
    )
    backend_report.write_text(report_body, encoding="utf-8")
    downloaded_report.write_text(report_body + "\n", encoding="utf-8")
    monkeypatch.setattr(
        mirofish_handoff,
        "DEFAULT_FULL_REPORT_PATHS",
        (str(backend_report), str(downloaded_report)),
    )
    final_handoff.write_text(
        "\n".join(
            [
                "# MiroFish Final TradingAgents Handoff",
                "",
                "Advisory only / no execution authority.",
                "",
                "## Machine-readable advisory packet",
                "",
                "```json",
                json.dumps(
                    {
                        "status": "final_advisory_no_execution_authority",
                        "execution_authority": "none",
                        "report_id": "report_1e3059f732b1",
                        "source_artifacts": {"stage04_report": str(backend_report)},
                    }
                ),
                "```",
            ]
        ),
        encoding="utf-8",
    )

    packet = build_mirofish_source_context_packet(
        scaffold_path=scaffold,
        final_handoff_path=final_handoff,
    )

    source_artifacts = packet.payload["source_artifacts"]
    highlights = packet.payload["full_report_highlights"]
    assert source_artifacts["downloaded_full_report"] == str(downloaded_report)
    assert highlights["source_path"] == str(backend_report)
    assert {report["path"] for report in highlights["candidate_reports"]} == {
        str(backend_report),
        str(downloaded_report),
    }
    assert all(report["sha256"] for report in highlights["candidate_reports"])


def test_mirofish_source_context_includes_deep_research_report_33_overlay(monkeypatch, tmp_path: Path):
    scaffold = tmp_path / "MIROFISH_PENDING_LEARNING_SCAFFOLD.md"
    final_handoff = tmp_path / "MIROFISH_FINAL_TRADINGAGENTS_HANDOFF.md"
    deep_review = tmp_path / "deep-research-report (33).md"
    _write_scaffold(scaffold)
    deep_review.write_text(
        "\n".join(
            [
                "# Mirror Fish market prediction review",
                "",
                "## Independent outlook for the next 7-10 days",
                "",
                "### Directional outlook",
                "",
                "| Market / sector | My base case for the next 7-10 days | Probability | Why |",
                "|---|---|---:|---|",
                "| Energy | Outperform broad market | 60% | Oil remains a live inflation driver |",
                "| Semiconductors | Underperform broad market | 60% | AI expectations are crowded |",
                "",
                "## Actionable implications and risk management",
                "",
                "### Practical decision table",
                "",
                "| Situation | Better response | Worse response |",
                "|---|---|---|",
                "| You are long semis/AI into June 5-11 | Reduce size or hedge | Assume AI overrides rates |",
                "",
                "## Timeline and limitations",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(mirofish_handoff, "DEFAULT_DEEP_RESEARCH_REVIEW_PATHS", (str(deep_review),))
    final_handoff.write_text(
        "\n".join(
            [
                "# MiroFish Final TradingAgents Handoff",
                "",
                "Advisory only / no execution authority.",
                "",
                "## Machine-readable advisory packet",
                "",
                "```json",
                json.dumps(
                    {
                        "status": "final_advisory_no_execution_authority",
                        "execution_authority": "none",
                        "report_id": "report_1e3059f732b1",
                    }
                ),
                "```",
            ]
        ),
        encoding="utf-8",
    )

    packet = build_mirofish_source_context_packet(
        scaffold_path=scaffold,
        final_handoff_path=final_handoff,
    )

    review = packet.payload["deep_research_review"]
    assert review["report_id"] == "deep_research_report_33"
    assert review["source_path"] == str(deep_review)
    assert review["source_sha256"]
    assert "macro-first" in review["core_filter"]
    assert review["market_regime"]["primary_driver"] == "macro_dominant_dispersion_heavy"
    assert "energy" in review["stock_selection_biases"]["positive_bias"]
    assert "QQQ_or_Nasdaq" in review["stock_selection_biases"]["negative_bias"]
    assert review["directional_outlook"][0]["market_or_sector"] == "Energy"
    assert review["directional_outlook"][0]["probability"] == 0.6
    assert review["practical_decision_rules"][0]["better_response"] == "Reduce size or hedge"
    assert packet.freshness["deep_research_review_available"] is True
    assert packet.freshness["deep_research_review_report_id"] == "deep_research_report_33"
    assert packet.freshness["deep_research_review_source_path"] == str(deep_review)
    assert packet.freshness["execution_authority"] == "none"
    assert packet.freshness["can_submit_orders"] is False


def test_mirofish_final_handoff_normalizes_attention_maps_and_retail_flow_hypotheses(tmp_path: Path):
    scaffold = tmp_path / "MIROFISH_PENDING_LEARNING_SCAFFOLD.md"
    final_handoff = tmp_path / "MIROFISH_FINAL_TRADINGAGENTS_HANDOFF.md"
    _write_scaffold(scaffold)
    final_handoff.write_text(
        "\n".join(
            [
                "# MiroFish Final TradingAgents Handoff",
                "",
                "Advisory only / no execution authority.",
                "",
                "## Machine-readable advisory packet",
                "",
                "```json",
                json.dumps(
                    {
                        "status": "final_advisory_no_execution_authority",
                        "execution_authority": "none",
                        "report_id": "report_1e3059f732b1",
                        "simulation_id": "sim_attention",
                        "scenario_branches": [
                            {
                                "scenario_id": "copycat_attention",
                                "description": "Copycat bots cluster around retail-friendly names.",
                                "probability": 0.35,
                            }
                        ],
                        "ticker_attention_map": {
                            "tsla": {
                                "category": "bot_correlation",
                                "hypothesis": "Retail scripts may chase TSLA headlines before confirmation.",
                                "probability": 0.42,
                                "validation_tasks": ["Check opening-volume quality."],
                                "false_signal_filters": ["Ignore social-only heat."],
                            },
                            "QQQ": {
                                "category": "index_proxy",
                                "hypothesis": "Broad AI-bot attention may express through QQQ.",
                            },
                        },
                        "category_attention_map": {
                            "zero_dte_options": {
                                "symbols": ["spy", "qqq"],
                                "hypothesis": "0DTE chatter can magnify perceived attention.",
                                "probability": 0.28,
                            }
                        },
                        "retail_flow_hypotheses": [
                            {
                                "hypothesis_id": "retail_copycat_flow",
                                "description": "Small-account bot users watch TSLA and QQQ together.",
                                "symbols": ["tsla", "qqq"],
                                "probability": 0.31,
                                "confirmations": ["Broker/account evidence appears."],
                                "invalidators": ["Attention fails to appear in volume."],
                            }
                        ],
                    }
                ),
                "```",
                "",
                "## How TradingAgents Should Use This",
                "",
                "Use as advisory validation context only.",
            ]
        ),
        encoding="utf-8",
    )

    source_packet = build_mirofish_source_context_packet(
        scaffold_path=scaffold,
        final_handoff_path=final_handoff,
    )

    assert source_packet.payload["scenario_branches"][0]["probability"] == 0.35
    assert source_packet.payload["ticker_attention_map"]["TSLA"]["category"] == "bot_correlation"
    assert source_packet.payload["ticker_attention_map"]["TSLA"]["probability"] == 0.42
    assert source_packet.payload["category_attention_map"]["zero_dte_options"]["symbols"] == ["SPY", "QQQ"]
    assert source_packet.payload["retail_flow_hypotheses"][0]["symbols"] == ["TSLA", "QQQ"]
    assert source_packet.payload["attention_symbols"] == ["SPY", "QQQ", "TSLA"]
    assert source_packet.payload["forecast_symbols"] == ["QQQ", "TSLA"]
    assert source_packet.freshness["ticker_attention_count"] == 2
    assert source_packet.freshness["category_attention_count"] == 1
    assert source_packet.freshness["retail_flow_hypothesis_count"] == 1
    assert source_packet.payload["execution_authority"] == "none"


def test_mirofish_handoff_file_requires_positive_final_marker(tmp_path: Path):
    scaffold = tmp_path / "MIROFISH_PENDING_LEARNING_SCAFFOLD.md"
    final_handoff = tmp_path / "MIROFISH_FINAL_TRADINGAGENTS_HANDOFF.md"
    _write_scaffold(scaffold)
    final_handoff.write_text(
        "\n".join(
            [
                "# MiroFish Notes",
                "",
                "This file looks like a handoff by name but has no final advisory packet marker.",
            ]
        ),
        encoding="utf-8",
    )

    packet = build_mirofish_handoff_status(
        scaffold_path=scaffold,
        final_handoff_path=final_handoff,
    )

    status_signal = next(signal for signal in packet.signals if signal["type"] == "mirofish_handoff_status")

    assert status_signal["status"] == "pending_final_handoff"
    assert status_signal["final_handoff_available"] is False
    assert status_signal["final_handoff_paths"] == []


def test_mirofish_handoff_file_must_match_current_report_id(tmp_path: Path):
    scaffold = tmp_path / "MIROFISH_PENDING_LEARNING_SCAFFOLD.md"
    final_handoff = tmp_path / "MIROFISH_FINAL_TRADINGAGENTS_HANDOFF.md"
    _write_scaffold(scaffold)
    final_handoff.write_text(
        "\n".join(
            [
                "# MiroFish Final TradingAgents Handoff",
                "",
                "Advisory only / no execution authority.",
                "",
                "## Machine-readable advisory packet",
                "",
                "```json",
                json.dumps(
                    {
                        "status": "final_advisory_no_execution_authority",
                        "execution_authority": "none",
                        "report_id": "old_report",
                        "simulation_id": "stale_sim",
                    }
                ),
                "```",
            ]
        ),
        encoding="utf-8",
    )

    packet = build_mirofish_handoff_status(
        scaffold_path=scaffold,
        final_handoff_path=final_handoff,
    )

    status_signal = next(signal for signal in packet.signals if signal["type"] == "mirofish_handoff_status")

    assert status_signal["status"] == "pending_final_handoff"
    assert status_signal["final_handoff_available"] is False
    assert status_signal["required_report_id"] == "report_1e3059f732b1"
    assert status_signal["final_handoff_paths"] == []
    assert status_signal["ignored_handoff_paths"] == [str(final_handoff)]
    assert packet.freshness["ignored_handoff_count"] == 1
    assert "report_1e3059f732b1" in packet.summary


def test_mirofish_required_report_id_uses_current_default(monkeypatch):
    monkeypatch.delenv("TRADINGAGENTS_MIROFISH_REQUIRED_REPORT_ID", raising=False)

    assert resolve_required_report_id() == "report_1e3059f732b1"


def test_mirofish_handoff_can_accept_next_report_id_from_env(monkeypatch, tmp_path: Path):
    scaffold = tmp_path / "MIROFISH_PENDING_LEARNING_SCAFFOLD.md"
    final_handoff = tmp_path / "MIROFISH_FINAL_TRADINGAGENTS_HANDOFF.md"
    _write_scaffold(scaffold)
    _write_minimal_final_handoff(final_handoff, report_id="report_future_123")
    monkeypatch.setenv("TRADINGAGENTS_MIROFISH_REQUIRED_REPORT_ID", "report_future_123")

    packet = build_mirofish_handoff_status(
        scaffold_path=scaffold,
        final_handoff_path=final_handoff,
    )

    status_signal = next(signal for signal in packet.signals if signal["type"] == "mirofish_handoff_status")

    assert status_signal["status"] == "final_handoff_available"
    assert status_signal["required_report_id"] == "report_future_123"
    assert status_signal["final_handoff_available"] is True
    assert status_signal["final_handoff_paths"] == [str(final_handoff)]


def test_mirofish_cli_writes_compact_status_packet(tmp_path: Path):
    scaffold = tmp_path / "MIROFISH_PENDING_LEARNING_SCAFFOLD.md"
    final_handoff = tmp_path / "MIROFISH_FINAL_TRADINGAGENTS_HANDOFF.md"
    output_dir = tmp_path / "research_evidence"
    _write_scaffold(scaffold)

    result = runner.invoke(
        app,
        [
            "research",
            "mirofish-handoff-status",
            "--scaffold-path",
            str(scaffold),
            "--final-handoff-path",
            str(final_handoff),
            "--output-dir",
            str(output_dir),
            "--json-output",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    latest = json.loads((output_dir / "latest.json").read_text(encoding="utf-8"))

    assert payload["analysis_only"] is True
    assert payload["can_submit_orders"] is False
    assert payload["status"] == "pending_final_handoff"
    assert payload["execution_authority"] == "none"
    assert payload["required_report_id"] == "report_1e3059f732b1"
    assert payload["final_handoff_paths"] == []
    assert payload["available_artifact_count"] >= 1
    assert payload["morning_bot_instruction"].startswith("Use this packet")
    assert payload["clean_room"]["agpl_code_import_allowed"] is False
    assert payload["missing_piece_count"] == 2
    assert latest["packet_id"].startswith("research-intel-")
    assert latest["freshness"]["mirofish_status"] == "pending_final_handoff"


def test_mirofish_cli_uses_required_report_id_from_env(monkeypatch, tmp_path: Path):
    scaffold = tmp_path / "MIROFISH_PENDING_LEARNING_SCAFFOLD.md"
    final_handoff = tmp_path / "MIROFISH_FINAL_TRADINGAGENTS_HANDOFF.md"
    output_dir = tmp_path / "research_evidence"
    _write_scaffold(scaffold)
    _write_minimal_final_handoff(final_handoff, report_id="report_future_cli")
    monkeypatch.setenv("TRADINGAGENTS_MIROFISH_REQUIRED_REPORT_ID", "report_future_cli")

    result = runner.invoke(
        app,
        [
            "research",
            "mirofish-handoff-status",
            "--scaffold-path",
            str(scaffold),
            "--final-handoff-path",
            str(final_handoff),
            "--output-dir",
            str(output_dir),
            "--json-output",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)

    assert payload["status"] == "final_handoff_available"
    assert payload["required_report_id"] == "report_future_cli"
    assert payload["final_handoff_available"] is True
    assert payload["final_handoff_paths"] == [str(final_handoff)]

