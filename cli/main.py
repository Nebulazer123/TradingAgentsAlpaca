import datetime
import hashlib
import json
import multiprocessing
import os
import queue as queue_module
import re
import subprocess
import sys
import time
import urllib.request
from collections import deque
from collections.abc import Mapping, Sequence
from contextlib import suppress
from dataclasses import asdict, replace
from decimal import Decimal, InvalidOperation
from functools import lru_cache, wraps
from pathlib import Path
from typing import Any

import questionary
import typer
from rich import box
from rich.align import Align
from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.rule import Rule
from rich.spinner import Spinner
from rich.table import Table
from rich.text import Text

from cli.announcements import display_announcements, fetch_announcements
from cli.stats_handler import ModelBudgetExceededError, stats_callback_handler_from_env
from cli.utils import (
    ask_anthropic_effort,
    ask_gemini_thinking_config,
    ask_glm_region,
    ask_minimax_region,
    ask_openai_reasoning_effort,
    ask_output_language,
    ask_qwen_region,
    confirm_ollama_endpoint,
    detect_asset_type,
    ensure_api_key,
    select_analysts,
    select_deep_thinking_agent,
    select_llm_provider,
    select_research_depth,
    select_shallow_thinking_agent,
)
from tradingagents.agents.utils.rating import parse_rating
from tradingagents.brokers.alpaca import (
    AlpacaExecutionConfig,
    AlpacaRestClient,
    AlpacaSettings,
    OrderIssue,
    StrategyOrder,
    build_order_pairs,
    build_paper_orders,
    classify_alpaca_submit_error,
    compare_alpaca_order_to_intent,
    execute_paper_orders,
    find_order_by_client_order_id,
)
from tradingagents.brokers.alpaca_reconciliation import (
    reconcile_orcl_sell_state,
    reconcile_symbol_incident,
)
from tradingagents.brokers.alpaca_supervisor import (
    AGGRESSIVE_CANDIDATE_UNIVERSE,
    CENTRAL,
    CROWDED_AI_BETA_SYMBOLS,
    DEEP_RESEARCH_EVENT_SENSITIVE_SYMBOLS,
    DEEP_RESEARCH_POSITIVE_RELATIVE_SYMBOLS,
    CandidateSignal,
    HourlySupervisorConfig,
    build_candidate_signals,
    build_hourly_decision,
    build_hourly_evidence,
    build_overnight_candidate_universe,
    build_portfolio_snapshot,
    build_premarket_brief_packet,
    build_supervisor_order_payload,
    calculate_dynamic_live_cap,
    can_trade_session,
    compact_hourly_supervisor_payload,
    compact_overnight_plan_payload,
    compact_premarket_brief_payload,
    find_latest_hourly_packet,
    is_expected_hourly_safety_lock,
    is_order_action,
    load_latest_overnight_plan,
    load_latest_premarket_brief,
    market_session_label,
    resolve_live_sleeve,
    serialize_hourly_decision,
    should_notify_supervisor,
    supervisor_live_client_order_id,
    total_unrealized_pl,
    validate_hourly_supervisor_actions,
    validate_overnight_plan_against_candidates,
    validate_premarket_brief_against_candidates,
    validate_supervisor_live_submit_allowed,
    write_hourly_decision_packet,
    write_overnight_plan_packet,
    write_premarket_brief_packet,
)
from tradingagents.brokers.manual_action_attribution import (
    build_owner_manual_action_attribution,
    write_owner_manual_action_attribution,
)
from tradingagents.brokers.paper_tournament import (
    ALPHAINSIDER_PAPER_WATCH_ID,
    STRATEGY_IDS,
    adapt_candidate_signals_for_live_strategy,
    authenticated_market_date_window,
    build_alphainsider_paper_watch_plan,
    build_tournament_actions,
    build_tournament_order_payloads,
    build_tournament_report,
    initialize_tournament,
    load_live_strategy_selection,
    load_tournament_ledger,
    maybe_write_live_strategy_selection,
    reconcile_tournament_orders,
    record_equity_snapshot,
    # Submit-only helpers stay local to the command so authority inventory remains explicit.
    write_tournament_ledger,
    write_tournament_packet,
)
from tradingagents.brokers.supervisor.daily_report import (
    build_supervisor_daily_report_payload,
    compact_supervisor_daily_report_payload,
    write_supervisor_daily_report_packet,
)
from tradingagents.dataflows.alpaca_reference import (
    build_alpaca_reference_audit,
    load_alpaca_reference_catalog,
)
from tradingagents.dataflows.integration_registry import build_integration_registry_report
from tradingagents.dataflows.pit import (
    RawPointInTimeArtifactArchive,
    build_source_verifiable_point_in_time_cohort,
    validate_market_date_partitions,
    validate_market_session_calendar,
)
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.evals.agent_intelligence_brain import (
    DEFAULT_BRAIN_PATH,
    build_agent_intelligence_brain,
    render_agent_intelligence_brain,
    write_agent_intelligence_brain,
)
from tradingagents.evals.agent_intelligence_ledger import (
    DEFAULT_LEDGER_PATH,
    DEFAULT_RATING_CALIBRATION_PATH,
    DEFAULT_SUMMARY_PATH,
    agent_influence_weights,
    append_forecasts,
    audit_resolved_forecasts,
    downgrade_nonqualifying_resolution_labels,
    forecasts_from_mirofish_handoff_packet,
    forecasts_from_overnight_packet,
    has_source_bound_resolution_evidence,
    load_ledger,
    load_ledger_with_stats,
    render_agent_influence_context,
    resolve_forecasts_with_quality,
    summarize_agent_scores,
    write_ledger,
    write_summary,
)
from tradingagents.evals.agent_intelligence_reconciliation import (
    ReconciliationPathError,
    SummaryReadError,
    canonical_json_text,
    reconcile_ledger_file,
    write_reconciliation_receipt,
)
from tradingagents.evals.automation_health_audit import (
    build_automation_health_audit,
    build_compact_automation_health_audit,
    default_automation_root,
    write_automation_health_audit,
)
from tradingagents.evals.automation_memory_rollup import (
    apply_automation_memory_rollup_plan,
    build_automation_memory_rollup_plan,
    write_automation_memory_rollup_apply_result,
    write_automation_memory_rollup_plan,
)
from tradingagents.evals.economic_evaluation_admission import (
    EconomicEvaluationAdmissionAdapter,
    EconomicEvaluationAdmissionError,
)
from tradingagents.evals.economic_evaluation_partition_binding import (
    bind_validation_phase_eligibility,
)
from tradingagents.evals.economic_evaluation_protocol import (
    validate_frozen_evaluation_protocol,
)
from tradingagents.evals.economic_tournament import (
    EconomicTournamentCandidate,
    EconomicTournamentOutcome,
    evaluate_validation_ta_control,
)
from tradingagents.evals.economic_tournament_evidence import (
    SourceBoundTournamentInput,
    validate_source_bound_tournament_input,
)
from tradingagents.evals.economic_tournament_evidence_admission import (
    verify_source_bound_tournament_input,
)
from tradingagents.evals.email_clarity import evaluate_email_clarity, write_email_clarity_eval
from tradingagents.evals.execution_board import (
    build_execution_board_review,
    write_execution_board_review,
)
from tradingagents.evals.hypothesis_factory import run_hypothesis_factory
from tradingagents.evals.learning_availability import observe_forecasts
from tradingagents.evals.overnight_calibration import (
    build_overnight_calibration_guard,
    latest_walk_forward_cohort_path,
    write_overnight_calibration_guard,
)
from tradingagents.evals.process_review import build_process_review, write_process_review
from tradingagents.evals.real_simulation_audit import run_real_simulation_audit
from tradingagents.evals.replay_ablation import (
    FORBIDDEN_EFFECTS,
    build_decision_quality_report_packet,
    build_replay_ablation_plan_packet,
    build_walk_forward_fixture_from_overnight_packets,
    build_walk_forward_replay_packet,
    build_walk_forward_return_rows_from_overnight_packets,
)
from tradingagents.evals.resolution_quality import (
    DEFAULT_RESOLUTION_QUALITY_PATH,
    price_window_from_bars,
    summarize_resolution_quality,
)
from tradingagents.evals.source_bound_resolution import (
    load_source_bound_window_lookup,
)
from tradingagents.evals.source_quality import (
    build_compact_source_quality_review,
    build_source_quality_review,
    discover_source_packet_paths,
    write_source_quality_review,
)
from tradingagents.execution.lock import release_execution_lock
from tradingagents.execution.reconcile import reconcile_latest_packet_live_orders
from tradingagents.execution.tiny_live import acquire_tiny_live_operational_guard
from tradingagents.graph.analyst_execution import (
    AnalystWallTimeTracker,
    build_analyst_execution_plan,
    get_initial_analyst_node,
    sync_analyst_tracker_from_chunk,
)
from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.llm_clients.model_catalog import get_model_context_window_tokens
from tradingagents.orchestration.authority import ActionClass, authority_for
from tradingagents.orchestration.control_plane_patrol import write_control_plane_patrol_packet
from tradingagents.orchestration.n8n_api_sync import N8NApiSyncError, sync_n8n_evaluation_data_table
from tradingagents.orchestration.n8n_evaluation_run_probe import (
    probe_n8n_builtin_evaluation_run,
)
from tradingagents.orchestration.n8n_evaluations import (
    build_compact_n8n_evaluation_dataset,
    write_n8n_evaluation_dataset,
)
from tradingagents.orchestration.n8n_runner import list_jobs as list_n8n_runner_jobs
from tradingagents.orchestration.n8n_workflow_sync import sync_n8n_workflows
from tradingagents.orchestration.night_shift_patrol import write_night_shift_patrol_packet
from tradingagents.orchestration.recovery import (
    evaluate_rearm_readiness,
    load_recovery_evidence,
    rearm_after_verified_recovery,
)
from tradingagents.orchestration.self_heal import (
    build_self_heal_handoff,
    build_self_heal_plan,
    execute_self_heal_plan,
    write_self_heal_handoff,
    write_self_heal_plan,
)
from tradingagents.policy.io import (
    atomic_write_text as _atomic_write_text,
)
from tradingagents.policy.io import (
    unique_packet_path as _unique_packet_path,
)
from tradingagents.policy.live_control import (
    _write_live_control_state_locked,
    live_control_lock,
    load_live_control_state,
    parse_control_time,
    write_live_control_state,
)
from tradingagents.policy.packets import write_research_packet, write_shadow_run_packet
from tradingagents.policy.preregistration import (
    append_preregistration,
    build_sleeve_preregistration,
)
from tradingagents.policy.risk_envelope import load_risk_envelope
from tradingagents.policy.risk_posture import risk_posture_policy_from_config
from tradingagents.research.alphainsider import (
    alphainsider_env_status,
    compact_strategy_summaries,
    fetch_recommended_strategies,
    verify_alphainsider_token,
)
from tradingagents.research.automation_orchestrator import (
    build_research_automation_orchestration,
)
from tradingagents.research.crawler_policy import CrawlerPolicy
from tradingagents.research.crawler_runner import (
    crawler_runtime_status,
    run_crawlee_research_packet,
)
from tradingagents.research.deep_research_protocol import build_deep_research_protocol_packet
from tradingagents.research.knowledge_graph import graph_memory_store_from_env
from tradingagents.research.loss_review_evidence import (
    DEFAULT_LOSS_REVIEW_EVIDENCE_NEEDS,
    build_loss_review_evidence_packet,
    build_loss_review_provider_research,
    find_latest_loss_review_packet,
)
from tradingagents.research.market_mirror import build_market_mirror_panel, label_market_mirror_outcome
from tradingagents.research.market_mirror_prompts import (
    MARKET_MIRROR_PROMPT,
    MARKET_MIRROR_PROMPT_ID,
)
from tradingagents.research.methodology_cards import build_methodology_cards_packet
from tradingagents.research.mirofish_handoff import (
    build_compact_mirofish_handoff_status,
    build_mirofish_handoff_status,
    resolve_required_report_id,
)
from tradingagents.research.model_routing import (
    DEFAULT_MAC_OLLAMA_URL,
    DEFAULT_WINDOWS_OLLAMA_URL,
    MAC_OLLAMA_ENV_NAMES,
    WINDOWS_OLLAMA_ENV_NAMES,
    model_routing_policy_from_env,
    select_mac_ollama_model_route,
    select_windows_local_model_route,
)
from tradingagents.research.model_telemetry import (
    label_model_telemetry_from_agent_outcomes,
    load_model_telemetry_packets,
    summarize_model_telemetry,
    write_model_telemetry_report,
)
from tradingagents.research.original_workflow import (
    build_creator_workflow_status,
    write_creator_workflow_artifacts,
)
from tradingagents.research.overnight_context import write_overnight_research_context
from tradingagents.research.prompt_registry import register_prompt_metadata
from tradingagents.research.provider_fallbacks import build_provider_fallback_packet
from tradingagents.research.provider_orchestrator import (
    DEFAULT_SOURCE_QUALITY_REVIEW_PATH,
    DEFAULT_TICKER_EVIDENCE_NEEDS,
    build_ticker_provider_research_packets,
)
from tradingagents.research.reddit_watchlists import build_reddit_watchlist_packet
from tradingagents.research.release_calendar import build_release_calendar_packet
from tradingagents.schemas.research import MarketMirrorScenarioPacket
from tradingagents.sleeves.pullback_support import (
    PullbackFeatures,
    build_pullback_support_run_packet,
    evaluate_pullback_support,
)

console = Console()

CANONICAL_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
CANONICAL_BOARD_EVIDENCE_ROOT = CANONICAL_REPOSITORY_ROOT / "results"
CANONICAL_BOARD_LEDGER_ROOT = CANONICAL_REPOSITORY_ROOT / "state" / "decision_ledger"

OVERNIGHT_TOP_PROVIDER_EVIDENCE_NEEDS: tuple[str, ...] = (
    "earnings_transcripts",
    "short_interest",
    "options_iv_flow",
)

app = typer.Typer(
    name="TradingAgents",
    help="TradingAgents CLI: Multi-Agents LLM Financial Trading Framework",
    add_completion=True,  # Enable shell completion
    pretty_exceptions_show_locals=False,
)
alpaca_app = typer.Typer(
    name="alpaca",
    help="Alpaca paper trading and 10% live mirror commands",
    pretty_exceptions_show_locals=False,
)
paper_tournament_app = typer.Typer(
    name="paper-tournament",
    help="Alpaca paper-only strategy tournament commands",
    pretty_exceptions_show_locals=False,
)
policy_app = typer.Typer(
    name="policy",
    help="Deterministic policy shadow-run helpers",
    pretty_exceptions_show_locals=False,
)
integrations_app = typer.Typer(
    name="integrations",
    help="No-secret integration and capability diagnostics",
    pretty_exceptions_show_locals=False,
)
research_app = typer.Typer(
    name="research",
    help="Analysis-only research packet producers",
    pretty_exceptions_show_locals=False,
)
app.add_typer(alpaca_app, name="alpaca")
app.add_typer(policy_app, name="policy")
app.add_typer(integrations_app, name="integrations")
app.add_typer(research_app, name="research")
alpaca_app.add_typer(paper_tournament_app, name="paper-tournament")


CAPABILITY_ENV_VARS = [
    "COMPOSIO_API_KEY",
    "ALPHA_VANTAGE_API_KEY",
    "SEC_USER_AGENT",
    "ALPHAINSIDER_API_KEY",
    "FRED_API_KEY",
    "BLS_API_KEY",
    "BEA_API_KEY",
    "EIA_API_KEY",
    "EODHD_API_TOKEN",
    "EODHD_API_KEY",
    "FINNHUB_API_KEY",
    "FINNHUB_WEBHOOK_SECRET",
    "MASSIVE_API_KEY",
    "POLYGON_API_KEY",
    "FMP_API_KEY",
    "NEWSAPI_API_KEY",
    "TIINGO_API_KEY",
    "SCRAPINGBEE_API_KEY",
    "MARKETAUX_API_KEY",
    "MARKETAUX_API_TOKEN",
    "GOOGLE_API_KEY",
    "GEMINI_API_KEY",
    "GEMINI_PROJECT_NAME",
    "ZEP_API_KEY",
    "ALPACA_PAPER_API_KEY",
    "ALPACA_LIVE_API_KEY",
]

EXPECTED_DOCKER_PROFILE_SERVERS = [
    "context7",
    "desktop-commander",
    "duckduckgo",
    "fetch",
    "filesystem",
    "github-official",
    "mcp-api-gateway",
    "memory",
    "next-devtools-mcp",
    "playwright",
    "rust-mcp-filesystem",
    "sequentialthinking",
    "time",
    "twitter-research",
    "youtube_transcript",
]

EXPECTED_COMPOSIO_TOOLKITS = [
    "alpaca",
    "benzinga",
    "discord",
    "facebook",
    "firecrawl",
    "github",
    "gmail",
    "google_maps",
    "googlecalendar",
    "googledocs",
    "googledrive",
    "instagram",
    "linkedin",
    "notion",
    "openai",
    "reddit",
    "supabase",
    "youtube",
]


def _alpaca_execution_config() -> AlpacaExecutionConfig:
    env_config = AlpacaExecutionConfig.from_env()
    if env_config.paper_enabled or env_config.live_mirror_enabled:
        return env_config
    return AlpacaExecutionConfig(
        paper_enabled=bool(DEFAULT_CONFIG["alpaca_paper_enabled"]),
        live_mirror_enabled=bool(DEFAULT_CONFIG["alpaca_live_mirror_enabled"]),
        paper_exposure_limit=Decimal(str(DEFAULT_CONFIG["paper_exposure_limit"])),
        live_mirror_ratio=Decimal(str(DEFAULT_CONFIG["live_mirror_ratio"])),
        live_exposure_limit=Decimal(str(DEFAULT_CONFIG["live_exposure_limit"])),
    )


def _dynamic_live_cap_for_budget_mode(
    *,
    live_account: Mapping,
    live_positions: Sequence[Mapping],
    recent_packets: Sequence[Mapping],
    config: AlpacaExecutionConfig,
    risk_envelope_path: str | Path = "config/risk_envelope.yaml",
) -> tuple[Decimal, str, list[str], Any]:
    envelope, envelope_issues = load_risk_envelope(risk_envelope_path)
    if envelope is not None:
        budget_mode = envelope.live_budget_mode
    elif any(issue.startswith("live_budget_mode") for issue in envelope_issues):
        budget_mode = "invalid_or_retired"
    else:
        budget_mode = "blocked_until_risk_envelope_exists"
    max_cap = None
    base_cap = config.live_exposure_limit
    if envelope is not None and budget_mode == "autonomous_with_caps":
        max_cap = envelope.account_max_capital_at_risk_usd
    dynamic_cap = calculate_dynamic_live_cap(
        live_positions=live_positions,
        recent_packets=recent_packets,
        base_cap=base_cap,
        max_cap=max_cap or config.live_exposure_limit,
    )
    return dynamic_cap, budget_mode, envelope_issues, envelope


def _account_circuit_breaker_values(
    account: Mapping,
) -> tuple[Decimal | None, Decimal | None]:
    try:
        equity = Decimal(
            str(account.get("equity") or account.get("portfolio_value") or "0")
        )
        last_equity = Decimal(
            str(
                account.get("last_equity")
                or account.get("last_portfolio_value")
                or "0"
            )
        )
    except Exception:
        return None, None
    if last_equity <= 0:
        return None, None
    daily_loss = max(Decimal("0"), last_equity - equity).quantize(Decimal("0.01"))
    drawdown = (daily_loss / last_equity).quantize(Decimal("0.0001"))
    return daily_loss, drawdown


def _default_run_id() -> str:
    return datetime.datetime.now().strftime("%Y%m%d-%H%M%S")


def _compact_cli_error_reason(exc: Exception, *, max_chars: int = 320) -> str:
    text = re.sub(r"\s+", " ", str(exc)).strip() or f"{type(exc).__name__}: unavailable"
    text = re.sub(
        r"(?i)\b(api[_-]?key|api[_-]?token|authorization|secret|token)(\s*[=:]\s*)[^\s,;]+",
        r"\1\2[redacted]",
        text,
    )
    text = re.sub(
        r"\b[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b",
        "[redacted-jwt]",
        text,
    )
    return text[:max_chars]


def _windows_registry_env_value(name: str, scope: str) -> str | None:
    if os.name != "nt":
        return None
    try:
        import winreg
    except ImportError:
        return None
    if scope == "user":
        root = winreg.HKEY_CURRENT_USER
        key_path = "Environment"
    elif scope == "machine":
        root = winreg.HKEY_LOCAL_MACHINE
        key_path = r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"
    else:
        return None
    try:
        with winreg.OpenKey(root, key_path) as key:
            value, _ = winreg.QueryValueEx(key, name)
    except OSError:
        return None
    return str(value) if value is not None else None


def _env_scope_status(value: str | None) -> dict[str, object]:
    return {
        "present": bool(value),
        "length": len(value) if value else 0,
    }


def _env_presence_report(names: list[str]) -> dict[str, dict[str, object]]:
    report: dict[str, dict[str, object]] = {}
    for name in names:
        values = {
            "process": os.environ.get(name),
            "user": _windows_registry_env_value(name, "user"),
            "machine": _windows_registry_env_value(name, "machine"),
        }
        effective_source = next(
            (scope for scope in ("process", "user", "machine") if values[scope]),
            "missing",
        )
        effective_value = values.get(effective_source)
        report[name] = {
            "present": effective_source != "missing",
            "length": len(effective_value) if effective_value else 0,
            "source": effective_source,
            "scopes": {
                scope: _env_scope_status(value)
                for scope, value in values.items()
            },
        }
    return report


def _default_codex_config_path() -> Path:
    codex_home = os.environ.get("CODEX_HOME") or r"C:\cm"
    return Path(codex_home) / "config.toml"


def _configured_mcp_servers(config_text: str) -> list[str]:
    names = re.findall(r"^\[mcp_servers\.([^\]]+)\]", config_text, flags=re.MULTILINE)
    return sorted({name for name in names if "." not in name})


def _load_codex_config_text(config_path: Path) -> str:
    try:
        return config_path.read_text(encoding="utf-8")
    except OSError:
        return ""


def build_integration_capability_audit(
    *,
    config_path: Path | None = None,
    now: datetime.datetime | None = None,
) -> dict:
    generated_at = (now or datetime.datetime.now(tz=datetime.timezone.utc)).isoformat(
        timespec="seconds"
    )
    resolved_config_path = config_path or _default_codex_config_path()
    config_text = _load_codex_config_text(resolved_config_path)
    mcp_servers = _configured_mcp_servers(config_text)
    integration_registry = build_integration_registry_report()
    return {
        "kind": "integration_capability_audit",
        "generated_at": generated_at,
        "secrets_redacted": True,
        "env": _env_presence_report(CAPABILITY_ENV_VARS),
        "integration_registry": {
            "integration_count": integration_registry["integration_count"],
            "env_var_count": integration_registry["env_var_count"],
            "missing_optional_env_vars": integration_registry["missing_optional_env_vars"],
            "missing_required_env_vars": integration_registry["missing_required_env_vars"],
            "authority_counts": integration_registry["authority_counts"],
            "can_submit_orders": integration_registry["can_submit_orders"],
            "execution_authority": integration_registry["execution_authority"],
            "integrations": integration_registry["integrations"],
        },
        "codex_config": {
            "path": str(resolved_config_path),
            "exists": resolved_config_path.exists(),
            "mcp_servers_configured": mcp_servers,
        },
        "docker_mcp": {
            "configured": "MCP_DOCKER" in mcp_servers,
            "profile": "profile" if "MCP_DOCKER" in mcp_servers and "profile" in config_text else None,
            "expected_profile_servers": EXPECTED_DOCKER_PROFILE_SERVERS,
            "live_tool_check": "not_run",
        },
        "composio": {
            "configured": "composio" in mcp_servers,
            "api_key_env_present": bool(os.environ.get("COMPOSIO_API_KEY")),
            "expected_toolkits": EXPECTED_COMPOSIO_TOOLKITS,
            "active_account_check": "not_run",
        },
        "alpaca_mcp": {
            "configured_servers": [
                name for name in mcp_servers if name in {"alpaca_paper", "alpaca_live"}
            ],
        },
        "policy": {
            "read_only": True,
            "safe_for_autonomous_runtime": False,
            "notes": [
                "This audit reports names, presence, and lengths only.",
                "Autonomous trading code must consume normalized evidence packets, not MCP tool authority.",
            ],
        },
    }


def compact_integration_capability_audit_payload(
    payload: dict,
    *,
    raw_packet_path: str | Path | None = None,
) -> dict:
    env = payload.get("env") if isinstance(payload.get("env"), dict) else {}
    present: list[str] = []
    missing: list[str] = []
    if isinstance(env, dict):
        for name, value in env.items():
            if not isinstance(value, dict):
                continue
            scopes = value.get("scopes") if isinstance(value.get("scopes"), dict) else {}
            process_present = bool((scopes.get("process") or {}).get("present"))
            user_present = bool((scopes.get("user") or {}).get("present"))
            machine_present = bool((scopes.get("machine") or {}).get("present"))
            if bool(value.get("present")) or process_present or user_present or machine_present:
                present.append(str(name))
            else:
                missing.append(str(name))
    registry = (
        payload.get("integration_registry")
        if isinstance(payload.get("integration_registry"), dict)
        else {}
    )
    codex_config = payload.get("codex_config") if isinstance(payload.get("codex_config"), dict) else {}
    docker_mcp = payload.get("docker_mcp") if isinstance(payload.get("docker_mcp"), dict) else {}
    composio = payload.get("composio") if isinstance(payload.get("composio"), dict) else {}
    alpaca_mcp = payload.get("alpaca_mcp") if isinstance(payload.get("alpaca_mcp"), dict) else {}
    return {
        "schema": "compact_integration_capability_audit_v1",
        "kind": payload.get("kind"),
        "generated_at": payload.get("generated_at"),
        "secrets_redacted": payload.get("secrets_redacted"),
        "raw_packet_path": str(raw_packet_path) if raw_packet_path is not None else None,
        "env_present_count": len(present),
        "missing_env_count": len(missing),
        "missing_env_preview": missing[:12],
        "integration_count": registry.get("integration_count"),
        "env_var_count": registry.get("env_var_count"),
        "missing_optional_env_vars": registry.get("missing_optional_env_vars", [])[:12]
        if isinstance(registry.get("missing_optional_env_vars"), list)
        else [],
        "missing_required_env_vars": registry.get("missing_required_env_vars", [])[:12]
        if isinstance(registry.get("missing_required_env_vars"), list)
        else [],
        "authority_counts": registry.get("authority_counts"),
        "can_submit_orders": registry.get("can_submit_orders"),
        "execution_authority": registry.get("execution_authority"),
        "codex_config_exists": codex_config.get("exists"),
        "mcp_servers_configured": codex_config.get("mcp_servers_configured") or [],
        "docker_mcp_configured": docker_mcp.get("configured"),
        "docker_mcp_profile": docker_mcp.get("profile"),
        "composio_configured": composio.get("configured"),
        "composio_api_key_env_present": composio.get("api_key_env_present"),
        "alpaca_mcp_configured_servers": alpaca_mcp.get("configured_servers") or [],
        "next_open": (
            "Open full capability audit if secrets_redacted is false, required env vars are missing, "
            "MCP/Composio config changed, or a source/tool lane needs drilldown."
        ),
    }


def _write_capability_audit_packet(payload: dict, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.datetime.now(tz=datetime.timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    packet_path = output_dir / f"capability-audit-{timestamp}.json"
    text = json.dumps(payload, indent=2)
    packet_path.write_text(text, encoding="utf-8")
    (output_dir / "latest.json").write_text(text, encoding="utf-8")
    compact = compact_integration_capability_audit_payload(payload, raw_packet_path=packet_path)
    compact_text = json.dumps(compact, indent=2)
    compact_packet_path = packet_path.with_suffix(".compact.json")
    compact_packet_path.write_text(compact_text, encoding="utf-8")
    (output_dir / "latest-compact.json").write_text(compact_text, encoding="utf-8")
    return packet_path


def _write_manual_alpaca_submit_packet(payload: dict[str, Any], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.datetime.now(tz=datetime.timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    packet_path = output_dir / f"manual-alpaca-submit-{timestamp}.json"
    text = json.dumps(payload, indent=2, default=str)
    packet_path.write_text(text, encoding="utf-8")
    (output_dir / "latest.json").write_text(text, encoding="utf-8")
    return packet_path


@integrations_app.command("doctor")
def integrations_doctor(
    config_path: Path | None = typer.Option(
        None,
        "--config-path",
        help="Codex config path to inspect. Defaults to CODEX_HOME/config.toml or C:\\cm\\config.toml.",
    ),
    output_dir: Path = typer.Option(
        Path("results/capability_audits"),
        "--output-dir",
        help="Output directory when writing a redacted capability audit packet.",
    ),
    write_packet: bool = typer.Option(False, "--write-packet"),
    json_output: bool = typer.Option(False, "--json-output"),
):
    """Report integration env/MCP capability presence without printing secret values."""
    payload = build_integration_capability_audit(config_path=config_path)
    if write_packet:
        payload["packet_path"] = str(_write_capability_audit_packet(payload, output_dir))
    if json_output:
        print(json.dumps(payload, indent=2))
        return

    env_present = sum(1 for item in payload["env"].values() if item["present"])
    console.print("Integration capability audit (secrets redacted)")
    console.print(f"Env vars present: {env_present}/{len(payload['env'])}")
    console.print(
        "Configured MCP servers: "
        + ", ".join(payload["codex_config"]["mcp_servers_configured"])
        if payload["codex_config"]["mcp_servers_configured"]
        else "Configured MCP servers: none found"
    )
    if write_packet:
        console.print(f"Packet: {payload['packet_path']}")


def _parse_domain_csv(value: str) -> tuple[str, ...]:
    return tuple(
        item.strip().lower().strip(".")
        for item in str(value or "").split(",")
        if item.strip()
    )


@research_app.command("crawl-target")
def research_crawl_target(
    target: str = typer.Option(..., "--target", help="URL to crawl for analysis-only evidence."),
    run_id: str = typer.Option(_default_run_id(), "--run-id"),
    allowed_domains: str = typer.Option(
        "sec.gov,fred.stlouisfed.org,bls.gov,bea.gov,eia.gov,treasury.gov,alphavantage.co",
        "--allowed-domains",
        help="Comma-separated allowlist. Subdomains are allowed; lookalike domains are blocked.",
    ),
    max_pages: int = typer.Option(5, "--max-pages", min=1, max=50),
    max_bytes: int = typer.Option(5_000_000, "--max-bytes", min=1000),
    output_dir: Path = typer.Option(
        Path("results/crawler_runs"),
        "--output-dir",
        help="Directory for crawler packets.",
    ),
    json_output: bool = typer.Option(False, "--json-output"),
):
    """Write a read-only crawler packet for one allowlisted research target."""
    policy = CrawlerPolicy(
        allowed_domains=_parse_domain_csv(allowed_domains),
        max_pages=max_pages,
        max_bytes=max_bytes,
    )
    packet = run_crawlee_research_packet(
        run_id=run_id,
        target=target,
        policy=policy,
    )
    packet_path = write_research_packet(packet, output_dir)
    payload = packet.model_dump()
    payload["packet_path"] = str(packet_path)
    if json_output:
        typer.echo(json.dumps(payload, indent=2))
        return
    status_style = "green" if packet.status == "success" else ("yellow" if packet.status == "partial" else "red")
    console.print(f"[{status_style}]Crawler packet: {packet.status}[/{status_style}]")
    console.print(f"Packet: {packet_path}")


@research_app.command("crawler-runtime-doctor")
def research_crawler_runtime_doctor(
    json_output: bool = typer.Option(False, "--json-output"),
):
    """Report whether Crawlee + Playwright are importable and how Codex can self-heal."""
    payload = crawler_runtime_status().as_dict()
    if json_output:
        typer.echo(json.dumps(payload, indent=2))
        return
    status_style = "green" if payload["ready"] else "yellow"
    console.print(f"[{status_style}]Crawler runtime ready: {payload['ready']}[/{status_style}]")
    console.print(str(payload["operator_summary"]))
    if not payload["ready"]:
        commands = payload["install_commands"]
        console.print(f"Install Python package: {commands['python_dependencies']}")
        console.print(f"Install browser binary: {commands['browser_binaries']}")


@research_app.command("reddit-watchlist-packet")
def research_reddit_watchlist_packet(
    config_path: Path = typer.Option(
        Path("config/reddit_market_watchlists.json"),
        "--config-path",
        help="Repo-local Reddit market-sentiment watchlist config.",
    ),
    output_dir: Path = typer.Option(
        Path("results/research_evidence"),
        "--output-dir",
        help="Directory for the Reddit watchlist evidence packet.",
    ),
    json_output: bool = typer.Option(False, "--json-output"),
):
    """Write an analysis-only Reddit watchlist packet without fetching Reddit."""
    packet = build_reddit_watchlist_packet(path=config_path)
    packet_path = write_research_packet(packet, output_dir)
    payload = packet.model_dump()
    payload["packet_path"] = str(packet_path)
    if json_output:
        typer.echo(json.dumps(payload, indent=2))
        return
    console.print(f"Reddit watchlist targets: {packet.freshness['target_count']}")
    console.print(f"Packet: {packet_path}")


def _parse_source_csv(value: str) -> set[str]:
    return {
        item.strip().lower()
        for item in str(value or "").split(",")
        if item.strip()
    }


@lru_cache(maxsize=4096)
def _ledger_price_lookup(symbol: str, start_date: str, end_date: str):
    import yfinance as yf

    end_dt = datetime.datetime.strptime(end_date, "%Y-%m-%d").date()
    query_end = (end_dt + datetime.timedelta(days=1)).isoformat()
    history = yf.Ticker(symbol).history(start=start_date, end=query_end)
    if history is None or len(history) < 2:
        return None
    return history["Close"].iloc[0], history["Close"].iloc[-1]


@lru_cache(maxsize=4096)
def _ledger_window_lookup(symbol: str, start_date: str, end_date: str):
    """Dated price window for ledger resolution, so windows can be audited."""
    import yfinance as yf

    end_dt = datetime.datetime.strptime(end_date, "%Y-%m-%d").date()
    query_end = (end_dt + datetime.timedelta(days=1)).isoformat()
    history = yf.Ticker(symbol).history(start=start_date, end=query_end)
    if history is None or len(history) == 0:
        return None
    bars = [
        (timestamp.date().isoformat(), str(close))
        for timestamp, close in history["Close"].items()
    ]
    return price_window_from_bars(
        symbol=symbol,
        requested_start=start_date,
        requested_end=end_date,
        bars=bars,
    )


def _learning_producer_now() -> datetime.datetime:
    return datetime.datetime.now(tz=datetime.timezone.utc).replace(microsecond=0)


def _forecast_learning_availability_root(
    ledger_path: Path,
    override: Path | None,
) -> Path:
    if override is not None:
        return override
    if ledger_path == DEFAULT_LEDGER_PATH:
        return Path("results/learning_availability")
    return ledger_path.parent / "learning_availability"


def _static_price_lookup_from_rows(rows: list[Any]):
    by_key: dict[tuple[str, str, str], tuple[Any, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        symbol = str(row.get("symbol", "")).strip().upper()
        start_date = str(row.get("start_date", "")).strip()
        end_date = str(row.get("end_date", "")).strip()
        if not symbol or not start_date or not end_date:
            continue
        by_key[(symbol, start_date, end_date)] = (row.get("start_price"), row.get("end_price"))

    def price_lookup(symbol: str, start_date: str, end_date: str):
        return by_key.get((symbol.strip().upper(), start_date, end_date))

    return price_lookup


def _packet_as_of_date_for_cli(packet: Mapping[str, Any]) -> datetime.date | None:
    for key in ("as_of", "trade_date", "decision_date", "generated_at", "created_at", "timestamp"):
        value = packet.get(key)
        if value is None:
            continue
        try:
            return datetime.date.fromisoformat(str(value)[:10])
        except ValueError:
            continue
    return None


def _load_overnight_packet(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    payload.setdefault("packet_path", str(path))
    return payload


def _discover_mature_overnight_packets(
    overnight_log_dir: Path,
    *,
    horizon_days: int,
    through_date: datetime.date,
    max_packets: int,
) -> tuple[list[tuple[Path, dict[str, Any]]], list[dict[str, Any]]]:
    selected: list[tuple[Path, dict[str, Any]]] = []
    skipped: list[dict[str, Any]] = []
    for path in sorted(
        (
            path
            for path in overnight_log_dir.glob("overnight-plan-*.json")
            if _is_raw_json_packet_path(path)
        ),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    ):
        if len(selected) >= max(1, int(max_packets)):
            break
        packet = _load_overnight_packet(path)
        if packet is None:
            skipped.append({"path": str(path), "reason": "unreadable_packet"})
            continue
        as_of = _packet_as_of_date_for_cli(packet)
        if as_of is None:
            skipped.append({"path": str(path), "reason": "missing_as_of"})
            continue
        resolution_date = as_of + datetime.timedelta(days=max(1, int(horizon_days)))
        if resolution_date > through_date:
            skipped.append(
                {
                    "path": str(path),
                    "as_of": as_of.isoformat(),
                    "resolution_date": resolution_date.isoformat(),
                    "reason": "not_mature_yet",
                }
            )
            continue
        selected.append((path, packet))
    return selected, skipped


@research_app.command("provider-fallbacks")
def research_provider_fallbacks(
    evidence_need: str = typer.Option(
        ...,
        "--evidence-need",
        help="Evidence need such as market_news, quote_price_context, fundamentals_profile, macro_official, social_sentiment, or crawler_research.",
    ),
    depleted_sources: str = typer.Option(
        "",
        "--depleted-sources",
        help="Comma-separated source names that are out of calls or temporarily exhausted.",
    ),
    disabled_sources: str = typer.Option(
        "",
        "--disabled-sources",
        help="Comma-separated source names to skip for this run.",
    ),
    config_path: Path = typer.Option(
        Path("config/research_provider_fallbacks.json"),
        "--config-path",
        help="Repo-local provider fallback policy config.",
    ),
    output_dir: Path = typer.Option(
        Path("results/research_evidence"),
        "--output-dir",
        help="Directory for provider fallback evidence packets.",
    ),
    json_output: bool = typer.Option(False, "--json-output"),
):
    """Write the provider fallback plan for a research evidence need."""
    packet = build_provider_fallback_packet(
        evidence_need=evidence_need,
        path=config_path,
        depleted_sources=_parse_source_csv(depleted_sources),
        disabled_sources=_parse_source_csv(disabled_sources),
    )
    packet_path = write_research_packet(packet, output_dir)
    payload = packet.model_dump()
    payload["packet_path"] = str(packet_path)
    if json_output:
        typer.echo(json.dumps(payload, indent=2))
        return
    active = ", ".join(packet.payload["active_source_names"])
    console.print(f"Provider fallback packet for {evidence_need}")
    console.print(f"Active sources: {active}")
    console.print(f"Packet: {packet_path}")


@research_app.command("ticker-provider-bundle")
def research_ticker_provider_bundle(
    symbol: str = typer.Option(..., "--symbol", help="Ticker symbol to research."),
    evidence_needs: str = typer.Option(
        ",".join(DEFAULT_TICKER_EVIDENCE_NEEDS),
        "--evidence-needs",
        help="Comma-separated evidence needs such as market_news, quote_price_context, fundamentals_profile.",
    ),
    provider_config_path: Path = typer.Option(
        Path("config/research_provider_fallbacks.json"),
        "--provider-config-path",
        help="Provider fallback configuration.",
    ),
    output_dir: Path = typer.Option(
        Path("results/research_evidence"),
        "--output-dir",
        help="Directory for source evidence packets.",
    ),
    cache_dir: Path = typer.Option(
        Path("results/research_provider_cache"),
        "--cache-dir",
        help="Directory for per-source cache packets.",
    ),
    broker_snapshot_dir: Path = typer.Option(
        Path("results/hourly_supervisor"),
        "--broker-snapshot-dir",
        help="Hourly supervisor packet directory or JSON file for sanitized broker_snapshot evidence.",
    ),
    max_packets_per_need: int = typer.Option(
        3,
        "--max-packets-per-need",
        min=1,
        help="Maximum supported provider packets to write for each evidence need.",
    ),
    depleted_sources: str = typer.Option(
        "",
        "--depleted-sources",
        help="Comma-separated sources out of calls for this run.",
    ),
    disabled_sources: str = typer.Option(
        "",
        "--disabled-sources",
        help="Comma-separated sources to skip for this run.",
    ),
    source_quality_review_path: Path = typer.Option(
        DEFAULT_SOURCE_QUALITY_REVIEW_PATH,
        "--source-quality-review-path",
        help="Latest source-quality review used for dynamic provider ordering.",
    ),
    source_quality_ordering: bool = typer.Option(
        True,
        "--source-quality-ordering/--no-source-quality-ordering",
        help="Use source-quality strength scores to order provider attempts when the review exists.",
    ),
    json_output: bool = typer.Option(False, "--json-output"),
):
    """Write a broad, analysis-only ticker provider evidence bundle."""
    needs = tuple(
        need.strip()
        for need in evidence_needs.split(",")
        if need and need.strip()
    )
    result = build_ticker_provider_research_packets(
        symbol,
        evidence_needs=needs or DEFAULT_TICKER_EVIDENCE_NEEDS,
        provider_config_path=provider_config_path,
        depleted_sources=_parse_source_csv(depleted_sources),
        disabled_sources=_parse_source_csv(disabled_sources),
        max_packets_per_need=max_packets_per_need,
        cache_dir=cache_dir,
        broker_snapshot_dir=broker_snapshot_dir,
        source_quality_review_path=(
            source_quality_review_path
            if source_quality_ordering and source_quality_review_path.exists()
            else None
        ),
    )
    packet_paths = {
        packet.packet_id: write_research_packet(packet, output_dir)
        for packet in result.packets
    }
    summary_path = (
        write_research_packet(result.summary_packet, output_dir)
        if result.summary_packet is not None
        else None
    )
    payload = {
        "symbol": result.symbol,
        "analysis_only": True,
        "packet_count": len(result.packets),
        "source_packet_paths": {
            packet_id: str(path)
            for packet_id, path in packet_paths.items()
        },
        "summary_packet_path": str(summary_path) if summary_path else None,
        "summary_packet": result.summary_packet.model_dump() if result.summary_packet else None,
        "route_attempts": result.route_attempts,
    }
    if json_output:
        typer.echo(json.dumps(payload, indent=2))
        return
    console.print(f"Ticker provider bundle: {result.symbol}")
    console.print(f"Source packets: {len(result.packets)}")
    console.print(f"Summary packet: {summary_path}")


@research_app.command("loss-review-evidence")
def research_loss_review_evidence(
    hourly_dir: Path = typer.Option(
        Path("results/hourly_supervisor"),
        "--hourly-dir",
        help="Hourly supervisor directory or packet to inspect for the latest loss-review.",
    ),
    evidence_needs: str = typer.Option(
        ",".join(DEFAULT_LOSS_REVIEW_EVIDENCE_NEEDS),
        "--evidence-needs",
        help="Comma-separated provider evidence needs to refresh for autonomous portfolio BOARD loss-review.",
    ),
    provider_config_path: Path = typer.Option(
        Path("config/research_provider_fallbacks.json"),
        "--provider-config-path",
        help="Provider fallback configuration.",
    ),
    output_dir: Path = typer.Option(
        Path("results/loss_review_evidence"),
        "--output-dir",
        help="Directory for the loss-review evidence wrapper packet.",
    ),
    source_output_dir: Path = typer.Option(
        Path("results/research_evidence"),
        "--source-output-dir",
        help="Directory for source evidence packets gathered during the refresh.",
    ),
    cache_dir: Path = typer.Option(
        Path("results/research_provider_cache"),
        "--cache-dir",
        help="Directory for per-source cache packets.",
    ),
    broker_snapshot_dir: Path = typer.Option(
        Path("results/hourly_supervisor"),
        "--broker-snapshot-dir",
        help="Hourly supervisor packet directory or JSON file for sanitized broker_snapshot evidence.",
    ),
    max_packets_per_need: int = typer.Option(
        2,
        "--max-packets-per-need",
        min=1,
        help="Maximum supported provider packets to write for each evidence need.",
    ),
    depleted_sources: str = typer.Option(
        "",
        "--depleted-sources",
        help="Comma-separated sources out of calls for this run.",
    ),
    disabled_sources: str = typer.Option(
        "",
        "--disabled-sources",
        help="Comma-separated sources to skip for this run.",
    ),
    source_quality_review_path: Path = typer.Option(
        DEFAULT_SOURCE_QUALITY_REVIEW_PATH,
        "--source-quality-review-path",
        help="Latest source-quality review used for dynamic provider ordering.",
    ),
    source_quality_ordering: bool = typer.Option(
        True,
        "--source-quality-ordering/--no-source-quality-ordering",
        help="Use source-quality strength scores to order provider attempts when the review exists.",
    ),
    json_output: bool = typer.Option(False, "--json-output"),
):
    """Refresh analysis-only evidence for the latest hourly loss-review hold."""
    hourly_packet_path, hourly_packet, loss_review = find_latest_loss_review_packet(hourly_dir)
    symbol = str(loss_review.get("symbol") or "").strip().upper()
    if not symbol:
        raise typer.BadParameter("latest loss-review packet is missing symbol")
    needs = tuple(
        need.strip()
        for need in evidence_needs.split(",")
        if need and need.strip()
    )
    # This drives request windows/cache routing only.  Decision authority is
    # evaluated once all provider calls have returned, below.
    refresh_started_at = datetime.datetime.now(tz=datetime.timezone.utc).replace(microsecond=0)
    # One read-only broker clock is captured for the entire refresh.  The
    # immutable evidence packet binds the exact response; no historical
    # supervisor session label can silently become current decision authority.
    try:
        raw_response = _alpaca_live_client().get_clock()
        if isinstance(raw_response, Mapping):
            raw_clock = dict(raw_response)
        elif hasattr(raw_response, "model_dump"):
            raw_clock = dict(raw_response.model_dump())
        elif hasattr(raw_response, "dict"):
            raw_clock = dict(raw_response.dict())
        else:
            raw_clock = {"invalid_clock_response": type(raw_response).__name__}
    except Exception as exc:  # noqa: BLE001 - a clock read failure must HOLD, never abort research.
        raw_clock = {"clock_error": type(exc).__name__}
    captured_at = datetime.datetime.now(tz=datetime.timezone.utc).replace(microsecond=0).isoformat(timespec="seconds")
    raw_timestamp = raw_clock.get("timestamp") if isinstance(raw_clock, Mapping) else None
    try:
        parsed_timestamp = datetime.datetime.fromisoformat(str(raw_timestamp).replace("Z", "+00:00"))
        if parsed_timestamp.tzinfo is None:
            raise ValueError("raw clock timestamp is timezone-naive")
        clock_as_of = parsed_timestamp.astimezone(datetime.timezone.utc).replace(microsecond=0).isoformat(timespec="seconds")
    except (TypeError, ValueError):
        # An invalid clock is preserved as raw evidence and causes a HOLD in
        # the strict downstream verifier.  Never synthesize as_of from local
        # time, because that would make a broken broker response look current.
        clock_as_of = None
    market_clock = {
        "source_name": "alpaca_clock",
        "source_ref": "alpaca:/v2/clock",
        "as_of": clock_as_of,
        "captured_at": captured_at,
        "is_open": raw_clock.get("is_open") if isinstance(raw_clock, Mapping) else None,
        "raw_clock": dict(raw_clock) if isinstance(raw_clock, Mapping) else {"invalid_clock_response": True},
    }
    def post_fetch_authority_now() -> datetime.datetime:
        return datetime.datetime.now(tz=datetime.timezone.utc).replace(microsecond=0)

    result = build_loss_review_provider_research(
        symbol,
        evidence_needs=needs or DEFAULT_LOSS_REVIEW_EVIDENCE_NEEDS,
        provider_config_path=provider_config_path,
        depleted_sources=_parse_source_csv(depleted_sources),
        disabled_sources=_parse_source_csv(disabled_sources),
        max_packets_per_need=max_packets_per_need,
        cache_dir=cache_dir,
        broker_snapshot_dir=broker_snapshot_dir,
        source_quality_review_path=(
            source_quality_review_path
            if source_quality_ordering and source_quality_review_path.exists()
            else None
        ),
        now=refresh_started_at,
        authority_now=post_fetch_authority_now,
    )
    source_packet_paths = {
        packet.packet_id: write_research_packet(packet, source_output_dir)
        for packet in result.packets
    }
    summary_packet_path = (
        write_research_packet(result.summary_packet, source_output_dir)
        if result.summary_packet is not None
        else None
    )
    # One post-fetch authority instant evaluates every diagnostic packet.  It
    # is deliberately not the routing-start time and is not a source packet's
    # own timestamp, so stale/future evidence cannot self-qualify.
    authority_now = post_fetch_authority_now()
    packet = build_loss_review_evidence_packet(
        hourly_packet_path=hourly_packet_path,
        hourly_packet=hourly_packet,
        provider_result=result,
        evidence_needs=needs or DEFAULT_LOSS_REVIEW_EVIDENCE_NEEDS,
        source_packet_paths=source_packet_paths,
        decision_evidence_root=CANONICAL_BOARD_EVIDENCE_ROOT,
        market_clock=market_clock,
        now=authority_now,
    )
    packet_path = write_research_packet(packet, output_dir)
    payload = packet.model_dump()
    packet_payload = packet.payload
    payload["packet_path"] = str(packet_path)
    payload["symbol"] = symbol
    payload["can_submit_orders"] = packet.freshness.get("can_submit_orders") is True
    payload["execution_authority"] = packet_payload["execution_authority"]
    payload["hourly_packet_path"] = packet_payload.get("hourly_packet_path")
    payload["hourly_decision"] = packet_payload.get("hourly_decision")
    payload["review_allowed"] = packet_payload.get("review_allowed")
    payload["entry_context_found"] = packet_payload.get("entry_context_found") is True
    payload["entry_context"] = packet_payload.get("entry_context") or {}
    payload["evidence_needs"] = packet_payload.get("evidence_needs") or []
    payload["evidence_coverage_by_need"] = (
        packet_payload.get("evidence_coverage_by_need") or {}
    )
    payload["remaining_blockers_before_refresh_count"] = len(
        packet_payload.get("remaining_blockers_before_refresh") or []
    )
    payload["resolved_blockers_by_refresh"] = (
        packet_payload.get("resolved_blockers_by_refresh") or []
    )
    payload["remaining_blocker_count"] = len(packet_payload.get("remaining_blockers") or [])
    payload["resolved_blocker_count"] = len(
        packet_payload.get("resolved_blockers_by_refresh") or []
    )
    payload["next_action"] = packet_payload.get("next_action")
    payload["source_packet_count"] = len(result.packets)
    payload["source_packet_paths"] = {
        packet_id: str(path)
        for packet_id, path in source_packet_paths.items()
    }
    payload["summary_packet_path"] = str(summary_packet_path) if summary_packet_path else None
    if json_output:
        typer.echo(json.dumps(payload, indent=2))
        return
    console.print(f"Loss-review evidence: {symbol}")
    console.print(f"Source packets: {len(result.packets)}")
    console.print(f"Packet: {packet_path}")


@research_app.command("source-quality-review")
def research_source_quality_review(
    source_root: list[Path] | None = typer.Option(
        None,
        "--source-root",
        help="Directory containing source/evidence JSON packets. Can be repeated.",
    ),
    output_dir: Path = typer.Option(
        Path("results/source_quality"),
        "--output-dir",
        help="Directory for source-quality review packets.",
    ),
    limit: int = typer.Option(250, "--limit", min=1, max=2000),
    json_output: bool = typer.Option(False, "--json-output"),
    compact_json_output: bool = typer.Option(
        False,
        "--compact-json-output",
        help="When used with --json-output, print compact counts and drilldown paths instead of full per-source decisions.",
    ),
):
    """Review research source quality without touching broker/order paths."""
    packet_paths = (
        discover_source_packet_paths(source_root, limit=limit)
        if source_root
        else discover_source_packet_paths(limit=limit)
    )
    review = build_source_quality_review(packet_paths)
    payload = write_source_quality_review(review, output_dir=output_dir)
    if json_output:
        if compact_json_output:
            typer.echo(json.dumps(build_compact_source_quality_review(payload), indent=2))
            return
        typer.echo(json.dumps(payload, indent=2))
        return
    console.print(f"Source packets reviewed: {payload['source_count']}")
    console.print(f"Stale sources: {payload['stale_count']}")
    console.print(f"Missing/invalid timestamps: {payload['missing_or_invalid_count']}")
    console.print(f"Review: {payload['json_path']}")


@research_app.command("creator-workflow-status")
def research_creator_workflow_status(
    overnight_packet: Path = typer.Option(
        Path("results/overnight_plans/latest.json"),
        "--overnight-packet",
        help="Overnight packet containing creator_workflow refs.",
    ),
    json_output: bool = typer.Option(False, "--json-output"),
):
    """Summarize preserved original TradingAgents workflow artifacts."""
    packet = _read_json_packet(overnight_packet) or {}
    payload = build_creator_workflow_status(packet)
    payload["overnight_packet"] = str(overnight_packet)
    if json_output:
        typer.echo(json.dumps(payload, indent=2))
        return
    console.print(f"Creator workflow packets: {payload['workflow_count']}")
    console.print(f"Symbols: {', '.join(payload['symbols']) if payload['symbols'] else 'none'}")
    console.print("Execution authority: none")


@research_app.command("agent-ledger-from-overnight")
def research_agent_ledger_from_overnight(
    overnight_packet: Path = typer.Option(
        Path("results/overnight_plans/latest.json"),
        "--overnight-packet",
        help="Overnight plan packet to convert into scoreable agent forecasts.",
    ),
    ledger_path: Path = typer.Option(
        DEFAULT_LEDGER_PATH,
        "--ledger-path",
        help="Append-only Agent Intelligence Ledger JSONL path.",
    ),
    benchmark: str = typer.Option("SPY", "--benchmark"),
    horizon_days: int = typer.Option(5, "--horizon-days", min=1, max=60),
    alpha_threshold_pct: str = typer.Option("1.5", "--alpha-threshold-pct"),
    setup: str = typer.Option("overnight_tradingagents", "--setup"),
    regime: str = typer.Option("unknown", "--regime"),
    json_output: bool = typer.Option(False, "--json-output"),
):
    """Turn TradingAgents overnight outputs into scoreable agent forecasts."""
    packet = _read_json_packet(overnight_packet)
    if not packet:
        raise typer.BadParameter(f"Could not read overnight packet: {overnight_packet}")
    forecasts = forecasts_from_overnight_packet(
        packet,
        benchmark=benchmark.upper(),
        horizon_days=horizon_days,
        alpha_threshold_pct=Decimal(alpha_threshold_pct),
        setup=setup,
        regime=regime,
    )
    appended = append_forecasts(forecasts, path=ledger_path)
    payload = {
        "ledger_path": str(ledger_path),
        "forecast_count": len(forecasts),
        "appended_count": appended,
        "benchmark": benchmark.upper(),
        "horizon_days": horizon_days,
        "alpha_threshold_pct": alpha_threshold_pct,
        "agents": sorted({forecast.agent for forecast in forecasts}),
    }
    if json_output:
        typer.echo(json.dumps(payload, indent=2))
        return
    console.print(f"Agent forecasts found: {len(forecasts)}")
    console.print(f"New forecasts appended: {appended}")
    console.print(f"Ledger: {ledger_path}")


@research_app.command("agent-ledger-from-mirofish")
def research_agent_ledger_from_mirofish(
    handoff_packet: Path = typer.Option(
        Path("results/mirofish_handoff/latest.json"),
        "--handoff-packet",
        help="MiroFish handoff status packet to convert into scoreable advisory forecasts.",
    ),
    ledger_path: Path = typer.Option(
        DEFAULT_LEDGER_PATH,
        "--ledger-path",
        help="Append-only Agent Intelligence Ledger JSONL path.",
    ),
    benchmark: str = typer.Option("SPY", "--benchmark"),
    horizon_days: int = typer.Option(5, "--horizon-days", min=1, max=60),
    alpha_threshold_pct: str = typer.Option("1.5", "--alpha-threshold-pct"),
    regime: str = typer.Option("pdt_reform_window", "--regime"),
    json_output: bool = typer.Option(False, "--json-output"),
):
    """Turn final MiroFish advisory output into scoreable neutral forecasts."""
    packet = _read_json_packet(handoff_packet)
    if not packet:
        raise typer.BadParameter(f"Could not read MiroFish handoff packet: {handoff_packet}")
    forecasts = forecasts_from_mirofish_handoff_packet(
        packet,
        benchmark=benchmark.upper(),
        horizon_days=horizon_days,
        alpha_threshold_pct=Decimal(alpha_threshold_pct),
        regime=regime,
    )
    appended = append_forecasts(forecasts, path=ledger_path)
    payload = {
        "analysis_only": True,
        "can_submit_orders": False,
        "execution_authority": "none",
        "handoff_packet": str(handoff_packet),
        "ledger_path": str(ledger_path),
        "forecast_count": len(forecasts),
        "appended_count": appended,
        "benchmark": benchmark.upper(),
        "horizon_days": horizon_days,
        "alpha_threshold_pct": alpha_threshold_pct,
        "regime": regime,
        "agents": sorted({forecast.agent for forecast in forecasts}),
        "symbols": sorted({forecast.ticker for forecast in forecasts}),
    }
    if json_output:
        typer.echo(json.dumps(payload, indent=2))
        return
    console.print(f"MiroFish forecasts found: {len(forecasts)}")
    console.print(f"New forecasts appended: {appended}")
    console.print(f"Ledger: {ledger_path}")


@research_app.command("agent-ledger-resolve")
def research_agent_ledger_resolve(
    ledger_path: Path = typer.Option(
        DEFAULT_LEDGER_PATH,
        "--ledger-path",
        help="Agent Intelligence Ledger JSONL path.",
    ),
    summary_path: Path = typer.Option(
        DEFAULT_SUMMARY_PATH,
        "--summary-path",
        help="Agent score summary output path.",
    ),
    resolution_quality_path: Path = typer.Option(
        DEFAULT_RESOLUTION_QUALITY_PATH,
        "--resolution-quality-path",
        help="Machine-readable resolution-window quality summary output path.",
    ),
    learning_availability_root: Path | None = typer.Option(
        None,
        "--learning-availability-root",
        help="Immutable point-in-time learning availability ledger root.",
    ),
    pit_raw_artifact_archive: Path | None = typer.Option(
        None,
        "--pit-raw-artifact-archive",
        help="Immutable PIT raw-artifact archive root for source-bound resolution.",
    ),
    pit_raw_artifact_receipts: list[Path] = typer.Option(
        [],
        "--pit-raw-artifact-receipt",
        exists=True,
        readable=True,
        help="Canonical raw-artifact receipt JSON. Repeat for every ticker/benchmark source.",
    ),
    pit_price_window_receipts: list[Path] = typer.Option(
        [],
        "--pit-price-window-receipt",
        exists=True,
        readable=True,
        help="Canonical source-bound adjusted-price receipt JSON. Repeat for every window.",
    ),
    alpha_threshold_pct: str = typer.Option("1.5", "--alpha-threshold-pct"),
    context_ticker: str = typer.Option("", "--context-ticker"),
    context_setup: str = typer.Option("", "--context-setup"),
    context_sector: str = typer.Option("", "--context-sector"),
    context_regime: str = typer.Option("", "--context-regime"),
    context_evidence_type: str = typer.Option("", "--context-evidence-type"),
    json_output: bool = typer.Option(False, "--json-output"),
):
    """Resolve due forecasts against audited price windows and update agent scores.

    Forecasts whose windows fail the mechanical audit (missing final bar,
    mismatched ticker/benchmark sessions, stale data) are deferred with a
    machine-readable reason instead of being scored against bad windows.  The
    default legacy yfinance route is explicitly nonqualifying; immutable PIT
    receipts are required before a result can enter learning availability.
    """
    producer_recorded_at = _learning_producer_now()
    availability_root = _forecast_learning_availability_root(
        ledger_path,
        learning_availability_root,
    )
    pit_inputs_supplied = (
        pit_raw_artifact_archive is not None
        or bool(pit_raw_artifact_receipts)
        or bool(pit_price_window_receipts)
    )
    if pit_inputs_supplied and (
        pit_raw_artifact_archive is None
        or not pit_raw_artifact_receipts
        or not pit_price_window_receipts
    ):
        raise typer.BadParameter(
            "source-bound resolution requires --pit-raw-artifact-archive plus at least "
            "one --pit-raw-artifact-receipt and --pit-price-window-receipt"
        )
    if pit_inputs_supplied:
        try:
            window_lookup = load_source_bound_window_lookup(
                raw_artifact_archive=pit_raw_artifact_archive,
                raw_artifact_receipts=tuple(pit_raw_artifact_receipts),
                price_window_receipts=tuple(pit_price_window_receipts),
            )
        except ValueError as exc:
            raise typer.BadParameter(
                f"source-bound PIT resolution inputs are invalid: {exc}"
            ) from exc
        price_window_route = "source_bound_adjusted_pit_receipts"
    else:
        window_lookup = _ledger_window_lookup
        price_window_route = "legacy_yfinance_nonqualifying"
    forecasts = load_ledger(ledger_path)
    unaudited_before = sum(
        1 for forecast in forecasts if forecast.resolved and not forecast.label_quality
    )
    resolved, quality_reports = resolve_forecasts_with_quality(
        forecasts,
        window_lookup=window_lookup,
        now=producer_recorded_at,
        alpha_threshold_pct=Decimal(alpha_threshold_pct),
    )
    if not pit_inputs_supplied:
        resolved, quality_reports = downgrade_nonqualifying_resolution_labels(
            resolved,
            quality_reports,
        )
    quality_summary = summarize_resolution_quality(
        quality_reports,
        unaudited_resolved_count=unaudited_before,
    )
    write_ledger(resolved, path=ledger_path)
    availability_admissions = observe_forecasts(
        resolved,
        availability_root=availability_root,
        recorded_at=producer_recorded_at,
        source_bound_verifier=window_lookup if pit_inputs_supplied else None,
    )
    write_summary(
        resolved,
        path=summary_path,
        source_bound_verifier=window_lookup if pit_inputs_supplied else None,
    )
    resolution_quality_path.parent.mkdir(parents=True, exist_ok=True)
    resolution_quality_path.write_text(
        json.dumps(quality_summary, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    before = sum(1 for forecast in forecasts if forecast.resolved)
    after = sum(1 for forecast in resolved if forecast.resolved)
    influence = agent_influence_weights(
        resolved,
        source_bound_verifier=window_lookup if pit_inputs_supplied else None,
        ticker=context_ticker or None,
        setup=context_setup or None,
        sector=context_sector or None,
        regime=context_regime or None,
        evidence_type=context_evidence_type or None,
    )
    payload = {
        "analysis_only": True,
        "can_submit_orders": False,
        "execution_authority": "none",
        "ledger_path": str(ledger_path),
        "summary_path": str(summary_path),
        "resolution_quality_path": str(resolution_quality_path),
        "price_window_route": price_window_route,
        "economic_qualification": (
            "source_bound_ledger_resolution_only"
            if pit_inputs_supplied
            else "legacy_nonqualifying"
        ),
        "learning_availability_root": str(availability_root),
        "learning_observed_count": len(availability_admissions),
        "learning_newly_recorded_count": sum(
            admission.created for admission in availability_admissions
        ),
        "forecast_count": len(resolved),
        "newly_resolved_count": after - before,
        "resolved_count": after,
        "resolved_forecast_count": after,
        "resolution_quality": quality_summary,
        "summary": summarize_agent_scores(resolved),
        "influence_weights": influence,
        "influence_context": render_agent_influence_context(influence),
    }
    if json_output:
        typer.echo(json.dumps(payload, indent=2))
        return
    console.print(f"Forecasts in ledger: {len(resolved)}")
    console.print(f"Newly resolved: {after - before}")
    console.print(
        f"Deferred (window quality): {quality_summary['deferred_count']} "
        f"not mature: {quality_summary['not_mature_count']}"
    )
    console.print(f"Summary: {summary_path}")
    console.print(f"Resolution quality: {resolution_quality_path}")


@research_app.command("ledger-quality-audit")
def research_ledger_quality_audit(
    ledger_path: Path = typer.Option(
        DEFAULT_LEDGER_PATH,
        "--ledger-path",
        help="Agent Intelligence Ledger JSONL path.",
    ),
    summary_path: Path = typer.Option(
        DEFAULT_SUMMARY_PATH,
        "--summary-path",
        help="Agent score summary output path (refreshed with quality counts).",
    ),
    quality_path: Path = typer.Option(
        DEFAULT_RESOLUTION_QUALITY_PATH,
        "--quality-path",
        help="Machine-readable resolution-window quality summary output path.",
    ),
    learning_availability_root: Path | None = typer.Option(
        None,
        "--learning-availability-root",
        help="Immutable point-in-time learning availability ledger root.",
    ),
    pit_raw_artifact_archive: Path | None = typer.Option(
        None,
        "--pit-raw-artifact-archive",
        help="Immutable PIT raw-artifact archive root for source-bound audit.",
    ),
    pit_raw_artifact_receipts: list[Path] = typer.Option(
        [],
        "--pit-raw-artifact-receipt",
        exists=True,
        readable=True,
        help="Canonical raw-artifact receipt JSON. Repeat for every ticker/benchmark source.",
    ),
    pit_price_window_receipts: list[Path] = typer.Option(
        [],
        "--pit-price-window-receipt",
        exists=True,
        readable=True,
        help="Canonical source-bound adjusted-price receipt JSON. Repeat for every window.",
    ),
    alpha_threshold_pct: str = typer.Option("1.5", "--alpha-threshold-pct"),
    backup: bool = typer.Option(
        True,
        "--backup/--no-backup",
        help="Write a timestamped ledger backup before annotating rows.",
    ),
    json_output: bool = typer.Option(False, "--json-output"),
):
    """Retro-audit resolved ledger labels against verified price windows.

    Annotates each resolved forecast with its measured resolution window and a
    label-quality tier. Outcomes and scores are never rewritten: a label whose
    recomputed outcome disagrees with the stored one, or whose window can no
    longer be verified, is downgraded to suspect so mining excludes it.
    Analysis-only; no execution authority.
    """
    producer_recorded_at = _learning_producer_now()
    availability_root = _forecast_learning_availability_root(
        ledger_path,
        learning_availability_root,
    )
    pit_inputs_supplied = (
        pit_raw_artifact_archive is not None
        or bool(pit_raw_artifact_receipts)
        or bool(pit_price_window_receipts)
    )
    if pit_inputs_supplied and (
        pit_raw_artifact_archive is None
        or not pit_raw_artifact_receipts
        or not pit_price_window_receipts
    ):
        raise typer.BadParameter(
            "source-bound audit requires --pit-raw-artifact-archive plus at least "
            "one --pit-raw-artifact-receipt and --pit-price-window-receipt"
        )
    if pit_inputs_supplied:
        try:
            window_lookup = load_source_bound_window_lookup(
                raw_artifact_archive=pit_raw_artifact_archive,
                raw_artifact_receipts=tuple(pit_raw_artifact_receipts),
                price_window_receipts=tuple(pit_price_window_receipts),
            )
        except ValueError as exc:
            raise typer.BadParameter(
                f"source-bound PIT audit inputs are invalid: {exc}"
            ) from exc
        price_window_route = "source_bound_adjusted_pit_receipts"
    else:
        window_lookup = _ledger_window_lookup
        price_window_route = "legacy_yfinance_nonqualifying"
    forecasts, corrupt_line_count = load_ledger_with_stats(ledger_path)
    resolved_count = sum(1 for forecast in forecasts if forecast.resolved)
    backup_path: Path | None = None
    if backup and forecasts and ledger_path.exists():
        stamp = datetime.datetime.now(tz=datetime.timezone.utc).strftime("%Y%m%d-%H%M%S")
        backup_path = ledger_path.with_name(
            f"{ledger_path.stem}.backup-quality-audit-{stamp}.jsonl"
        )
        backup_path.write_text(ledger_path.read_text(encoding="utf-8"), encoding="utf-8")
    audit_targets = (
        forecasts
        if pit_inputs_supplied
        else [
            forecast
            for forecast in forecasts
            if not has_source_bound_resolution_evidence(forecast)
        ]
    )
    audited_targets, quality_reports = audit_resolved_forecasts(
        audit_targets,
        window_lookup=window_lookup,
        now=producer_recorded_at,
        alpha_threshold_pct=Decimal(alpha_threshold_pct),
    )
    if pit_inputs_supplied:
        audited = audited_targets
    else:
        audited_by_id = {forecast.forecast_id: forecast for forecast in audited_targets}
        audited = [audited_by_id.get(forecast.forecast_id, forecast) for forecast in forecasts]
    if not pit_inputs_supplied:
        audited, quality_reports = downgrade_nonqualifying_resolution_labels(
            audited,
            quality_reports,
        )
    write_ledger(audited, path=ledger_path)
    availability_admissions = observe_forecasts(
        audited,
        availability_root=availability_root,
        recorded_at=producer_recorded_at,
        source_bound_verifier=window_lookup if pit_inputs_supplied else None,
    )
    write_summary(
        audited,
        path=summary_path,
        source_bound_verifier=window_lookup if pit_inputs_supplied else None,
    )
    quality_summary = summarize_resolution_quality(quality_reports)
    quality_path.parent.mkdir(parents=True, exist_ok=True)
    quality_path.write_text(
        json.dumps(quality_summary, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    suspect_ids = [
        report.forecast_id
        for report in quality_reports
        if report.label_quality == "suspect"
    ]
    payload = {
        "analysis_only": True,
        "can_submit_orders": False,
        "execution_authority": "none",
        "ledger_path": str(ledger_path),
        "summary_path": str(summary_path),
        "quality_path": str(quality_path),
        "price_window_route": price_window_route,
        "economic_qualification": (
            "source_bound_ledger_resolution_only"
            if pit_inputs_supplied
            else "legacy_nonqualifying"
        ),
        "learning_availability_root": str(availability_root),
        "learning_observed_count": len(availability_admissions),
        "learning_newly_recorded_count": sum(
            admission.created for admission in availability_admissions
        ),
        "backup_path": str(backup_path) if backup_path else None,
        "forecast_count": len(audited),
        "resolved_forecast_count": resolved_count,
        "audited_label_count": len(quality_reports),
        "corrupt_ledger_line_count": corrupt_line_count,
        "resolution_quality": quality_summary,
        "suspect_forecast_ids": suspect_ids[:50],
        "suspect_forecast_count": len(suspect_ids),
    }
    if json_output:
        typer.echo(json.dumps(payload, indent=2))
        return
    console.print(f"Resolved labels audited: {len(quality_reports)}")
    console.print(f"Label quality: {quality_summary['label_quality_counts']}")
    console.print(f"Suspect labels: {len(suspect_ids)}")
    console.print(f"Quality summary: {quality_path}")


@research_app.command("agent-ledger-update")
def research_agent_ledger_update(
    overnight_packet: Path = typer.Option(
        Path("results/overnight_plans/latest.json"),
        "--overnight-packet",
        help="Latest overnight plan packet to append as scoreable forecasts.",
    ),
    mirofish_packet: Path = typer.Option(
        Path("results/mirofish_handoff/latest.json"),
        "--mirofish-packet",
        help="Latest MiroFish handoff packet to append as scoreable advisory forecasts.",
    ),
    ledger_path: Path = typer.Option(
        DEFAULT_LEDGER_PATH,
        "--ledger-path",
        help="Append-only Agent Intelligence Ledger JSONL path.",
    ),
    summary_path: Path = typer.Option(
        DEFAULT_SUMMARY_PATH,
        "--summary-path",
        help="Agent score summary output path.",
    ),
    learning_availability_root: Path | None = typer.Option(
        None,
        "--learning-availability-root",
        help="Immutable point-in-time learning availability ledger root.",
    ),
    benchmark: str = typer.Option("SPY", "--benchmark"),
    horizon_days: int = typer.Option(5, "--horizon-days", min=1, max=60),
    alpha_threshold_pct: str = typer.Option("1.5", "--alpha-threshold-pct"),
    setup: str = typer.Option("overnight_tradingagents", "--setup"),
    regime: str = typer.Option("unknown", "--regime"),
    context_ticker: str = typer.Option("", "--context-ticker"),
    context_setup: str = typer.Option("", "--context-setup"),
    context_sector: str = typer.Option("", "--context-sector"),
    context_regime: str = typer.Option("", "--context-regime"),
    context_evidence_type: str = typer.Option("", "--context-evidence-type"),
    include_mirofish: bool = typer.Option(
        True,
        "--include-mirofish/--no-include-mirofish",
        help="Also append advisory MiroFish forecasts when the handoff packet is present.",
    ),
    json_output: bool = typer.Option(False, "--json-output"),
):
    """Append latest advisory forecasts and write a nonqualifying summary.

    Source-bound price receipts are required by ``agent-ledger-resolve`` before
    any due forecast is resolved.  This automation-safe ingestion path never
    uses a legacy downloader to manufacture learning-quality labels.
    """

    producer_recorded_at = _learning_producer_now()
    availability_root = _forecast_learning_availability_root(
        ledger_path,
        learning_availability_root,
    )
    threshold = Decimal(alpha_threshold_pct)
    overnight_forecasts = []
    overnight_payload = _read_json_packet(overnight_packet)
    if overnight_payload:
        overnight_forecasts = forecasts_from_overnight_packet(
            overnight_payload,
            benchmark=benchmark.upper(),
            horizon_days=horizon_days,
            alpha_threshold_pct=threshold,
            setup=setup,
            regime=regime,
        )

    mirofish_forecasts = []
    if include_mirofish:
        mirofish_payload = _read_json_packet(mirofish_packet)
        if mirofish_payload:
            mirofish_forecasts = forecasts_from_mirofish_handoff_packet(
                mirofish_payload,
                benchmark=benchmark.upper(),
                horizon_days=horizon_days,
                alpha_threshold_pct=threshold,
                regime=regime if regime != "unknown" else "pdt_reform_window",
            )

    discovered_forecasts = [*overnight_forecasts, *mirofish_forecasts]
    before_records = load_ledger(ledger_path)
    before_resolved = sum(1 for forecast in before_records if forecast.resolved)
    appended = append_forecasts(discovered_forecasts, path=ledger_path)

    forecasts = load_ledger(ledger_path)
    resolved = forecasts
    quality_summary = summarize_resolution_quality((), unaudited_resolved_count=0)
    availability_admissions = observe_forecasts(
        resolved,
        availability_root=availability_root,
        recorded_at=producer_recorded_at,
    )
    write_summary(resolved, path=summary_path)
    after_resolved = sum(1 for forecast in resolved if forecast.resolved)
    summary = summarize_agent_scores(resolved)
    influence = agent_influence_weights(
        resolved,
        ticker=context_ticker or None,
        setup=context_setup or None,
        sector=context_sector or None,
        regime=context_regime or None,
        evidence_type=context_evidence_type or None,
    )
    payload = {
        "analysis_only": True,
        "can_submit_orders": False,
        "execution_authority": "none",
        "forbidden_effects": [
            "create_trade_intent",
            "size_position",
            "submit_order",
            "promote_sleeve",
            "waive_live_gate",
        ],
        "overnight_packet": str(overnight_packet),
        "mirofish_packet": str(mirofish_packet),
        "include_mirofish": include_mirofish,
        "ledger_path": str(ledger_path),
        "summary_path": str(summary_path),
        "learning_availability_root": str(availability_root),
        "price_window_route": "not_resolved_by_agent_ledger_update",
        "economic_qualification": "requires_source_bound_ledger_resolution",
        "learning_observed_count": len(availability_admissions),
        "learning_newly_recorded_count": sum(
            admission.created for admission in availability_admissions
        ),
        "forecast_count": len(resolved),
        "discovered_forecast_count": len(discovered_forecasts),
        "overnight_forecast_count": len(overnight_forecasts),
        "mirofish_forecast_count": len(mirofish_forecasts),
        "appended_count": appended,
        "newly_resolved_count": after_resolved - before_resolved,
        "resolved_forecast_count": after_resolved,
        "agent_count": len(summary.get("agents") or {}),
        "outcome_counts": summary.get("outcome_counts") or {},
        "resolution_quality": quality_summary,
        "influence_weights": influence,
        "influence_context": render_agent_influence_context(influence),
    }
    if json_output:
        typer.echo(json.dumps(payload, indent=2))
        return
    console.print(f"Forecasts discovered: {len(discovered_forecasts)}")
    console.print(f"New forecasts appended: {appended}")
    console.print(f"Newly resolved: {after_resolved - before_resolved}")
    console.print(f"Summary: {summary_path}")


@research_app.command("agent-ledger-summary")
def research_agent_ledger_summary(
    ledger_path: Path = typer.Option(
        DEFAULT_LEDGER_PATH,
        "--ledger-path",
        help="Agent Intelligence Ledger JSONL path.",
    ),
    summary_path: Path = typer.Option(
        DEFAULT_SUMMARY_PATH,
        "--summary-path",
    ),
    context_ticker: str = typer.Option("", "--context-ticker"),
    context_setup: str = typer.Option("", "--context-setup"),
    context_sector: str = typer.Option("", "--context-sector"),
    context_regime: str = typer.Option("", "--context-regime"),
    context_evidence_type: str = typer.Option("", "--context-evidence-type"),
    json_output: bool = typer.Option(False, "--json-output"),
):
    """Summarize which TradingAgents roles have earned trust so far."""
    forecasts = load_ledger(ledger_path)
    summary = summarize_agent_scores(forecasts)
    influence = agent_influence_weights(
        forecasts,
        ticker=context_ticker or None,
        setup=context_setup or None,
        sector=context_sector or None,
        regime=context_regime or None,
        evidence_type=context_evidence_type or None,
    )
    write_summary(forecasts, path=summary_path)
    payload = {
        "ledger_path": str(ledger_path),
        "summary_path": str(summary_path),
        "summary": summary,
        "influence_weights": influence,
        "influence_context": render_agent_influence_context(influence),
    }
    if json_output:
        typer.echo(json.dumps(payload, indent=2))
        return
    console.print(f"Forecasts in ledger: {summary['forecast_count']}")
    for agent, stats in summary["agents"].items():
        accuracy = stats["accuracy"] if stats["accuracy"] is not None else "unresolved"
        console.print(
            f"{agent}: forecasts={stats['forecast_count']} "
            f"resolved={stats['resolved_count']} accuracy={accuracy}"
        )
    console.print("Influence weights are advisory only and cannot bypass risk gates.")


@research_app.command("agent-ledger-reconcile")
def research_agent_ledger_reconcile(
    ledger_path: Path = typer.Option(
        DEFAULT_LEDGER_PATH,
        "--ledger-path",
        help="Agent Intelligence Ledger JSONL path (read-only).",
    ),
    summary_path: Path = typer.Option(
        DEFAULT_SUMMARY_PATH,
        "--summary-path",
        help=(
            "Agent score summary evaluated for freshness; "
            "it is never replaced by this command."
        ),
    ),
    receipt_path: Path | None = typer.Option(
        None,
        "--receipt-path",
        help="Optional path for an atomic write of the reconciliation receipt only.",
    ),
):
    """Emit a read-only reconciliation receipt for one ledger byte snapshot.

    Prints canonical JSON to stdout. Counts valid, corrupt, duplicate,
    conflicting, resolved, and clustered rows without rewriting anything.
    The conservative market-event cluster count is labeled provisional until
    a preregistered estimator exists.
    """
    try:
        receipt = reconcile_ledger_file(ledger_path, summary_path=summary_path)
    except SummaryReadError as exc:
        raise typer.BadParameter(str(exc)) from exc
    except OSError as exc:
        raise typer.BadParameter(f"could not read ledger: {exc}") from exc
    if receipt_path is not None:
        try:
            write_reconciliation_receipt(
                receipt,
                receipt_path,
                protected_paths=(ledger_path, summary_path),
            )
        except ReconciliationPathError as exc:
            raise typer.BadParameter(f"rejected receipt path: {exc}") from exc
        except OSError as exc:
            raise typer.BadParameter(f"could not write receipt: {exc}") from exc
    typer.echo(canonical_json_text(receipt))


@research_app.command("hypothesis-factory")
def research_hypothesis_factory(
    ledger_path: Path = typer.Option(
        DEFAULT_LEDGER_PATH,
        "--ledger-path",
        help="Agent Intelligence Ledger JSONL path used as resolution evidence.",
    ),
    store_path: Path = typer.Option(
        Path("results/hypothesis_factory/hypotheses.jsonl"),
        "--store-path",
        help="Preregistered hypothesis store (append-merge, never re-registers).",
    ),
    priors_path: Path = typer.Option(
        Path("results/hypothesis_factory/priors.json"),
        "--priors-path",
        help="Advisory research priors packet for future agent context.",
    ),
    summary_path: Path = typer.Option(
        Path("results/hypothesis_factory/summary.json"),
        "--summary-path",
    ),
    lifecycle_path: Path = typer.Option(
        Path("results/hypothesis_factory/lifecycle.jsonl"),
        "--lifecycle-path",
        help="Append-only hypothesis lifecycle event ledger (never rewritten).",
    ),
    learning_availability_root: Path | None = typer.Option(
        None,
        "--learning-availability-root",
        help="Immutable point-in-time learning availability ledger root.",
    ),
    min_sample: int = typer.Option(
        12,
        "--min-sample",
        min=1,
        help="Minimum resolved forecasts a context cell needs before mining.",
    ),
    edge_threshold: str = typer.Option(
        "0.15",
        "--edge-threshold",
        help="Accuracy deviation from baseline needed to preregister a hypothesis.",
    ),
    require_audited_labels: bool = typer.Option(
        True,
        "--require-audited-labels/--allow-unaudited-labels",
        help=(
            "Learn only from labels with mechanically audited resolution windows. "
            "Suspect labels are always excluded."
        ),
    ),
    json_output: bool = typer.Option(False, "--json-output"),
):
    """Mine resolved-forecast evidence into preregistered research hypotheses.

    Analysis-only. Mined hypotheses are judged strictly out of sample: only
    forecasts created after preregistration can support or refute them, and
    supported hypotheses become bounded advisory priors, never order authority.
    """
    payload = run_hypothesis_factory(
        ledger_path=ledger_path,
        store_path=store_path,
        priors_path=priors_path,
        summary_path=summary_path,
        lifecycle_path=lifecycle_path,
        availability_root=learning_availability_root,
        min_sample=min_sample,
        edge_threshold=Decimal(edge_threshold),
        require_audited_labels=require_audited_labels,
    )
    if json_output:
        typer.echo(json.dumps(payload, indent=2))
        return
    console.print(
        f"Resolved evidence: {payload['resolved_forecast_count']} forecasts "
        f"({payload['minable_forecast_count']} minable, "
        f"{payload['excluded_suspect_count']} suspect excluded, "
        f"{payload['excluded_unaudited_count']} unaudited excluded)"
    )
    console.print(
        f"Hypotheses: {payload['hypothesis_count']} total, "
        f"{payload['appended_count']} newly preregistered"
    )
    console.print(f"Status counts: {payload['status_counts']}")
    console.print(f"Supported priors: {payload['prior_count']}")
    console.print(
        f"Lifecycle events: +{payload['lifecycle_appended_event_count']} "
        f"({payload['lifecycle_total_event_count']} total) -> {payload['lifecycle_path']}"
    )
    console.print(f"Store: {payload['store_path']}")
    console.print(f"Priors: {payload['priors_path']}")
    console.print("Hypothesis priors are advisory only and cannot bypass risk gates.")


@research_app.command("agent-intelligence-brief")
def research_agent_intelligence_brief(
    ledger_path: Path = typer.Option(
        DEFAULT_LEDGER_PATH,
        "--ledger-path",
        help="Agent Intelligence Ledger JSONL path.",
    ),
    summary_path: Path = typer.Option(
        DEFAULT_SUMMARY_PATH,
        "--summary-path",
        help="Agent score summary (source of earned influence weights).",
    ),
    quality_path: Path = typer.Option(
        DEFAULT_RESOLUTION_QUALITY_PATH,
        "--quality-path",
        help="Latest resolution-window quality summary.",
    ),
    hypothesis_store_path: Path = typer.Option(
        Path("results/hypothesis_factory/hypotheses.jsonl"),
        "--hypothesis-store-path",
        help="Hypothesis store (current statuses).",
    ),
    hypothesis_summary_path: Path = typer.Option(
        Path("results/hypothesis_factory/summary.json"),
        "--hypothesis-summary-path",
        help="Hypothesis Factory summary packet.",
    ),
    priors_path: Path = typer.Option(
        Path("results/hypothesis_factory/priors.json"),
        "--priors-path",
        help="Advisory research priors packet.",
    ),
    lifecycle_path: Path = typer.Option(
        Path("results/hypothesis_factory/lifecycle.jsonl"),
        "--lifecycle-path",
        help="Append-only hypothesis lifecycle event ledger.",
    ),
    brain_path: Path = typer.Option(
        DEFAULT_BRAIN_PATH,
        "--brain-path",
        help="Compact brain packet output path.",
    ),
    radar_horizon_days: int = typer.Option(
        7,
        "--radar-horizon-days",
        min=0,
        help="How many days of upcoming forecast maturities to bucket by date.",
    ),
    json_output: bool = typer.Option(False, "--json-output"),
):
    """Fuse the learning loop's artifacts into one compact brain packet.

    The brain is the durable state packet a future agent or operator reads
    first: ledger truth, label quality, hypothesis + lifecycle state, a
    maturity radar for incoming evidence, and recommended next actions.
    Analysis-only; missing or malformed sources degrade to explicit statuses.
    """
    brain = build_agent_intelligence_brain(
        ledger_path=ledger_path,
        agent_summary_path=summary_path,
        resolution_quality_path=quality_path,
        hypothesis_store_path=hypothesis_store_path,
        hypothesis_summary_path=hypothesis_summary_path,
        research_priors_path=priors_path,
        lifecycle_path=lifecycle_path,
        radar_horizon_days=radar_horizon_days,
    )
    written_path = write_agent_intelligence_brain(brain, path=brain_path)
    payload = {**brain, "brain_path": str(written_path)}
    if json_output:
        typer.echo(json.dumps(payload, indent=2))
        return
    console.print(render_agent_intelligence_brain(brain))
    console.print(f"Brain packet: {written_path}")


@research_app.command("release-calendar-packet")
def research_release_calendar_packet(
    config_path: Path = typer.Option(
        Path("config/release_calendar_watchlist.json"),
        "--config-path",
        help="Repo-local official release-calendar watchlist config.",
    ),
    output_dir: Path = typer.Option(
        Path("results/research_evidence"),
        "--output-dir",
        help="Directory for release-calendar evidence packets.",
    ),
    lookahead_days: int = typer.Option(
        14,
        "--lookahead-days",
        help="Number of days ahead to include upcoming official releases.",
    ),
    json_output: bool = typer.Option(False, "--json-output"),
):
    """Write analysis-only official macro release-calendar context."""
    packet = build_release_calendar_packet(
        path=config_path,
        lookahead_days=lookahead_days,
    )
    packet_path = write_research_packet(packet, output_dir)
    payload = packet.model_dump()
    payload["packet_path"] = str(packet_path)
    if json_output:
        typer.echo(json.dumps(payload, indent=2))
        return
    console.print(f"Release-calendar risk state: {packet.payload['event_risk_state']}")
    console.print(f"Upcoming official releases: {len(packet.payload['upcoming_events'])}")
    console.print(f"Packet: {packet_path}")


@research_app.command("methodology-cards")
def research_methodology_cards(
    output_dir: Path = typer.Option(
        Path("results/research_evidence"),
        "--output-dir",
        help="Directory for strategy methodology cards packet.",
    ),
    json_output: bool = typer.Option(False, "--json-output"),
):
    """Write analysis-only strategy methodology cards from current research."""
    packet = build_methodology_cards_packet()
    packet_path = write_research_packet(packet, output_dir)
    payload = packet.model_dump()
    payload["packet_path"] = str(packet_path)
    if json_output:
        typer.echo(json.dumps(payload, indent=2))
        return
    console.print(f"Methodology cards: {packet.freshness['card_count']}")
    console.print(f"Packet: {packet_path}")


@research_app.command("deep-research-protocol")
def research_deep_research_protocol(
    output_dir: Path = typer.Option(
        Path("results/research_evidence"),
        "--output-dir",
        help="Directory for ChatGPT Deep Research protocol packet.",
    ),
    json_output: bool = typer.Option(False, "--json-output"),
):
    """Write the analysis-only ChatGPT Deep Research operating protocol packet."""
    packet = build_deep_research_protocol_packet()
    packet_path = write_research_packet(packet, output_dir)
    payload = packet.model_dump()
    payload["packet_path"] = str(packet_path)
    if json_output:
        typer.echo(json.dumps(payload, indent=2))
        return
    console.print(f"Deep Research use cases: {packet.freshness['use_case_count']}")
    console.print(f"Packet: {packet_path}")


@research_app.command("prompt-registry-defaults")
def research_prompt_registry_defaults(
    output_dir: Path = typer.Option(
        Path("results/prompt_registry"),
        "--output-dir",
        help="Directory for prompt-registry packets.",
    ),
    json_output: bool = typer.Option(False, "--json-output"),
):
    """Write clean-room prompt metadata for advisory research prompts."""
    packet, packet_path = register_prompt_metadata(
        prompt_id=MARKET_MIRROR_PROMPT_ID,
        prompt_text=MARKET_MIRROR_PROMPT,
        prompt_role="market_mirror_actor_panel",
        allowed_outputs=["stance", "evidence_refs", "invalidators", "watch_items"],
        methodology_refs=["mirofish_inspired_clean_room"],
        model_route="local_or_capped_judgment",
        output_dir=output_dir,
    )
    payload = packet.model_dump()
    payload["packet_path"] = str(packet_path)
    if json_output:
        typer.echo(json.dumps(payload, indent=2))
        return
    console.print(f"Prompt registered: {packet.prompt_id}")
    console.print("Raw prompt stored: false")
    console.print(f"Packet: {packet_path}")


@research_app.command("graph-memory-note")
def research_graph_memory_note(
    symbol: str = typer.Option(..., "--symbol"),
    theme: str = typer.Option(..., "--theme"),
    note: str = typer.Option(..., "--note"),
    memory_path: Path = typer.Option(
        Path("results/research_memory/graph_memory.jsonl"),
        "--memory-path",
        help="Local graph memory JSONL path.",
    ),
    output_dir: Path = typer.Option(
        Path("results/research_memory"),
        "--output-dir",
        help="Directory for graph memory packets.",
    ),
    json_output: bool = typer.Option(False, "--json-output"),
):
    """Store a redacted public-market graph note and write advisory packets."""
    store, backend = graph_memory_store_from_env(dict(os.environ), path=memory_path)
    symbol_node = store.upsert_node(
        node_type="symbol",
        label=symbol,
        properties={"theme": theme, "note": note},
    )
    theme_node = store.upsert_node(
        node_type="theme",
        label=theme,
        properties={"note": note},
    )
    edge = store.upsert_edge(
        source_node_id=symbol_node.node_id,
        target_node_id=theme_node.node_id,
        relation="has_research_theme",
        properties={"note": note},
    )
    query = store.query_symbol_context(symbol)
    paths = [
        write_research_packet(symbol_node, output_dir),
        write_research_packet(theme_node, output_dir),
        write_research_packet(edge, output_dir),
        write_research_packet(query, output_dir),
    ]
    payload = {
        "backend": backend,
        "memory_path": str(memory_path),
        "packet_paths": [str(path) for path in paths],
        "symbol_node": symbol_node.model_dump(),
        "theme_node": theme_node.model_dump(),
        "edge": edge.model_dump(),
        "query": query.model_dump(),
        "analysis_only": True,
        "can_submit_orders": False,
    }
    if json_output:
        typer.echo(json.dumps(payload, indent=2))
        return
    console.print(f"Graph memory note stored for {symbol_node.label}")
    console.print(f"Packets: {len(paths)}")


@research_app.command("market-mirror")
def research_market_mirror(
    symbol: str = typer.Option(..., "--symbol"),
    evidence_refs: str = typer.Option(
        "",
        "--evidence-refs",
        help="Comma-separated evidence packet refs.",
    ),
    rounds: int = typer.Option(2, "--rounds", min=1, max=3),
    max_actors: int = typer.Option(9, "--max-actors", min=1, max=9),
    output_dir: Path = typer.Option(
        Path("results/research_simulations"),
        "--output-dir",
        help="Directory for market-mirror packets.",
    ),
    json_output: bool = typer.Option(False, "--json-output"),
):
    """Write advisory market-mirror actor and scenario packets."""
    refs = [item.strip() for item in evidence_refs.split(",") if item.strip()]
    result = build_market_mirror_panel(
        symbol=symbol,
        evidence_refs=refs,
        rounds=rounds,
        max_actors=max_actors,
    )
    actor_paths = [write_research_packet(actor, output_dir) for actor in result.actors]
    scenario_path = write_research_packet(result.scenario, output_dir)
    payload = result.scenario.model_dump()
    payload["scenario_packet_path"] = str(scenario_path)
    payload["actor_packet_paths"] = [str(path) for path in actor_paths]
    payload["actor_count"] = len(result.actors)
    payload["execution_authority"] = "none"
    payload["forbidden_effects"] = result.scenario.freshness.get("forbidden_effects", [])
    if json_output:
        typer.echo(json.dumps(payload, indent=2))
        return
    console.print(f"Market mirror scenario: {result.scenario.scenario_id}")
    console.print(f"Actors: {len(result.actors)}")
    console.print(f"Scenario packet: {scenario_path}")


@research_app.command("replay-ablation-plan")
def research_replay_ablation_plan(
    candidate_symbols: str = typer.Option(
        "",
        "--candidate-symbols",
        help="Comma-separated symbols to include in the replay/ablation plan.",
    ),
    sleeve: str = typer.Option(
        "pullback-support",
        "--sleeve",
        help="Strategy sleeve being evaluated.",
    ),
    benchmark: str = typer.Option("SPY", "--benchmark"),
    minimum_decisions_per_arm: int = typer.Option(
        30,
        "--minimum-decisions-per-arm",
        min=1,
        help="Minimum replay decisions before comparing overlay quality.",
    ),
    output_dir: Path = typer.Option(
        Path("results/research_batches"),
        "--output-dir",
        help="Directory for replay/ablation plan packets.",
    ),
    json_output: bool = typer.Option(False, "--json-output"),
):
    """Write an analysis-only replay/ablation plan packet."""
    packet = build_replay_ablation_plan_packet(
        candidate_symbols=candidate_symbols,
        sleeve=sleeve,
        benchmark=benchmark,
        minimum_decisions_per_arm=minimum_decisions_per_arm,
    )
    packet_path = write_research_packet(packet, output_dir)
    payload = packet.model_dump()
    payload["packet_path"] = str(packet_path)
    if json_output:
        typer.echo(json.dumps(payload, indent=2))
        return
    console.print(f"Replay/ablation sleeve: {packet.quality_gates['sleeve']}")
    console.print(f"Replay arms: {len(packet.orchestration_lanes)}")
    console.print(f"Packet: {packet_path}")


@research_app.command("decision-quality-report")
def research_decision_quality_report(
    candidate_symbols: str = typer.Option(
        "",
        "--candidate-symbols",
        help="Comma-separated symbols to include in the decision-quality report.",
    ),
    sleeve: str = typer.Option(
        "pullback-support",
        "--sleeve",
        help="Strategy sleeve being evaluated.",
    ),
    benchmark: str = typer.Option("SPY", "--benchmark"),
    ledger_path: Path = typer.Option(
        DEFAULT_LEDGER_PATH,
        "--ledger-path",
        help="Agent Intelligence Ledger JSONL path to calibrate from.",
    ),
    prior_weight: int = typer.Option(
        10,
        "--prior-weight",
        min=0,
        max=500,
        help="Shrinkage prior weight applied to hardcoded rating probabilities.",
    ),
    min_resolved: int = typer.Option(
        1,
        "--min-resolved",
        min=1,
        max=1000,
        help="Minimum resolved rating forecasts before a rating can move from its prior.",
    ),
    output_dir: Path = typer.Option(
        Path("results/research_batches"),
        "--output-dir",
        help="Directory for decision-quality report packets.",
    ),
    rating_calibration_path: Path = typer.Option(
        DEFAULT_RATING_CALIBRATION_PATH,
        "--rating-calibration-path",
        help="Standalone calibration file consumed by future Agent Intelligence forecast builders.",
    ),
    json_output: bool = typer.Option(False, "--json-output"),
):
    """Write an analysis-only decision-quality report with as-of audit and rating calibration."""
    forecasts = load_ledger(ledger_path)
    packet = build_decision_quality_report_packet(
        forecasts,
        candidate_symbols=candidate_symbols,
        sleeve=sleeve,
        benchmark=benchmark,
        prior_weight=prior_weight,
        min_resolved=min_resolved,
    )
    packet_path = write_research_packet(packet, output_dir)
    payload = packet.model_dump()
    payload["packet_path"] = str(packet_path)
    payload["ledger_path"] = str(ledger_path)
    calibration = packet.quality_gates["rating_calibration"]
    calibration_payload = dict(calibration)
    calibration_payload["source_packet_path"] = str(packet_path)
    calibration_payload["ledger_path"] = str(ledger_path)
    calibration_payload["analysis_only"] = True
    calibration_payload["can_submit_orders"] = False
    _atomic_write_text(
        rating_calibration_path,
        json.dumps(calibration_payload, indent=2, sort_keys=True),
    )
    payload["rating_calibration_path"] = str(rating_calibration_path)
    if json_output:
        typer.echo(json.dumps(payload, indent=2))
        return
    console.print(f"Decision-quality sleeve: {packet.quality_gates['sleeve']}")
    console.print(f"Resolved rating forecasts: {calibration['resolved_rating_forecast_count']}")
    console.print(f"Point-in-time gaps: {packet.quality_gates['point_in_time_gap_count']}")
    console.print(f"Packet: {packet_path}")
    console.print(f"Rating calibration: {rating_calibration_path}")


def _economic_json_object(
    path: Path,
    *,
    label: str,
    max_bytes: int = 16_000_000,
    require_canonical: bool = False,
) -> dict[str, object]:
    """Load one bounded strict JSON receipt without ambiguous decoder behavior."""

    max_depth = 32
    max_nodes = 1_000_000
    max_objects = 200_000
    max_lists = 200_000
    max_strings = 1_000_000
    max_container_items = 10_000
    max_string_chars = 4_096

    def reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise typer.BadParameter(f"{label} contains a duplicate JSON key")
            result[key] = value
        return result

    def reject_nonfinite(_value: str) -> object:
        raise typer.BadParameter(f"{label} contains a nonfinite JSON number")

    def bounded_integer(text: str) -> int:
        if len(text.removeprefix("-")) > 128:
            raise typer.BadParameter(f"{label} contains an over-limit JSON number")
        return int(text)

    def bounded_float(text: str) -> float:
        parts = text.lower().split("e", 1)
        coefficient = parts[0].replace("-", "").replace(".", "")
        exponent = parts[1] if len(parts) == 2 else "0"
        if (
            len(coefficient.lstrip("0") or "0") > 128
            or len(exponent.removeprefix("-").removeprefix("+")) > 4
            or abs(int(exponent)) > 128
        ):
            raise typer.BadParameter(f"{label} contains an over-limit JSON number")
        return float(text)

    try:
        if path.stat().st_size > max_bytes:
            raise typer.BadParameter(f"{label} exceeds the {max_bytes}-byte limit")
        raw_bytes = path.read_bytes()
        if len(raw_bytes) > max_bytes:
            raise typer.BadParameter(f"{label} exceeds the {max_bytes}-byte limit")
        payload = json.loads(
            raw_bytes,
            object_pairs_hook=reject_duplicate_keys,
            parse_int=bounded_integer,
            parse_float=bounded_float,
            parse_constant=reject_nonfinite,
        )
    except typer.BadParameter:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise typer.BadParameter(f"{label} must be bounded strict JSON") from exc
    if not isinstance(payload, dict):
        raise typer.BadParameter(f"{label} must contain a JSON object")
    objects = 0
    lists = 0
    strings = 0
    nodes = 0
    stack: list[tuple[object, int]] = [(payload, 0)]
    while stack:
        value, depth = stack.pop()
        nodes += 1
        if nodes > max_nodes or depth > max_depth:
            raise typer.BadParameter(f"{label} exceeds JSON depth/node limits")
        if isinstance(value, dict):
            objects += 1
            if objects > max_objects or len(value) > max_container_items:
                raise typer.BadParameter(f"{label} exceeds JSON object limits")
            for key, item in value.items():
                strings += 1
                if strings > max_strings or len(key) > max_string_chars:
                    raise typer.BadParameter(f"{label} exceeds JSON string limits")
                stack.append((item, depth + 1))
        elif isinstance(value, list):
            lists += 1
            if lists > max_lists or len(value) > max_container_items:
                raise typer.BadParameter(f"{label} exceeds JSON list limits")
            stack.extend((item, depth + 1) for item in value)
        elif isinstance(value, str):
            strings += 1
            if strings > max_strings or len(value) > max_string_chars:
                raise typer.BadParameter(f"{label} exceeds JSON string limits")
    if require_canonical:
        canonical = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        if raw_bytes != canonical:
            raise typer.BadParameter(f"{label} must use canonical JSON bytes")
    return payload


def _economic_exact_object(
    value: object,
    *,
    label: str,
    fields: frozenset[str],
) -> dict[str, object]:
    """Require one explicitly versioned JSON object shape at the CLI boundary."""

    if not isinstance(value, dict) or set(value) != fields:
        raise typer.BadParameter(f"{label} fields are invalid")
    return value


def _economic_cohort_from_input(
    payload: dict[str, object],
    *,
    archive: object,
    market_calendar: object,
):
    """Open exact source references and derive one source-verifiable cohort."""

    values = _economic_exact_object(
        payload,
        label="cohort candidate input",
        fields=frozenset(
            {"market_date", "as_of_cutoff", "selection_time", "candidates"}
        ),
    )
    raw_candidates = values["candidates"]
    if type(raw_candidates) is not list:
        raise typer.BadParameter("cohort candidate input candidates must be a JSON list")
    try:
        return build_source_verifiable_point_in_time_cohort(
            archive=archive,
            market_calendar=validate_market_session_calendar(market_calendar),
            market_date=values["market_date"],
            as_of_cutoff=values["as_of_cutoff"],
            selection_time=values["selection_time"],
            candidates=tuple(raw_candidates),
        )
    except (TypeError, ValueError) as exc:
        raise typer.BadParameter(f"cohort candidate input is invalid: {exc}") from exc


def _write_economic_receipt(path: Path, payload: dict[str, object], *, label: str) -> Path:
    """Write a local canonical receipt once, or prove the existing bytes match."""

    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    expected = text.encode("utf-8")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        try:
            existing = path.read_bytes()
        except OSError as exc:
            raise typer.BadParameter(f"{label} cannot be read") from exc
        if existing != expected:
            raise typer.BadParameter(f"{label} already exists with different bytes") from None
        return path
    except OSError as exc:
        raise typer.BadParameter(f"{label} cannot be created") from exc
    try:
        offset = 0
        while offset < len(expected):
            written = os.write(descriptor, expected[offset:])
            if written <= 0:
                raise OSError("incomplete receipt write")
            offset += written
        os.fsync(descriptor)
    except OSError as exc:
        with suppress(OSError):
            path.unlink()
        raise typer.BadParameter(f"{label} cannot be written") from exc
    finally:
        os.close(descriptor)
    try:
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except OSError as exc:
        raise typer.BadParameter(f"{label} directory cannot be synchronized") from exc
    return path


def _economic_decimal(value: object, *, label: str) -> Decimal:
    """Parse one finite decimal required by the frozen pullback rule."""

    if type(value) is not str:
        raise typer.BadParameter(f"{label} must be a decimal string")
    try:
        parsed = Decimal(value)
    except (InvalidOperation, ValueError) as exc:
        raise typer.BadParameter(f"{label} must be a decimal string") from exc
    if not parsed.is_finite():
        raise typer.BadParameter(f"{label} must be finite")
    return parsed


def _economic_pullback_features(value: object, *, label: str) -> PullbackFeatures | None:
    """Parse complete pullback inputs without allowing an implicit live route."""

    if value is None:
        return None
    fields = frozenset(
        {
            "symbol",
            "current_price",
            "support_level",
            "atr",
            "pullback_atr",
            "above_rising_50d",
            "above_rising_200d",
            "sell_volume_state",
            "gap_state",
            "sector_relative_strength",
            "regime_state",
            "earnings_blackout",
            "fresh_negative_event",
            "green_spike_atr",
            "evidence_trend",
            "reward_risk_ratio",
            "notional_usd",
        }
    )
    payload = _economic_exact_object(value, label=label, fields=fields)
    string_fields = (
        "symbol",
        "sell_volume_state",
        "gap_state",
        "regime_state",
        "evidence_trend",
    )
    if any(type(payload[field]) is not str or not payload[field] for field in string_fields):
        raise typer.BadParameter(f"{label} string fields are invalid")
    bool_fields = (
        "above_rising_50d",
        "above_rising_200d",
        "earnings_blackout",
        "fresh_negative_event",
    )
    if any(type(payload[field]) is not bool for field in bool_fields):
        raise typer.BadParameter(f"{label} boolean fields are invalid")
    return PullbackFeatures(
        symbol=payload["symbol"],
        current_price=_economic_decimal(payload["current_price"], label=f"{label}.current_price"),
        support_level=_economic_decimal(payload["support_level"], label=f"{label}.support_level"),
        atr=_economic_decimal(payload["atr"], label=f"{label}.atr"),
        pullback_atr=_economic_decimal(payload["pullback_atr"], label=f"{label}.pullback_atr"),
        above_rising_50d=payload["above_rising_50d"],
        above_rising_200d=payload["above_rising_200d"],
        sell_volume_state=payload["sell_volume_state"],
        gap_state=payload["gap_state"],
        sector_relative_strength=_economic_decimal(
            payload["sector_relative_strength"],
            label=f"{label}.sector_relative_strength",
        ),
        regime_state=payload["regime_state"],
        earnings_blackout=payload["earnings_blackout"],
        fresh_negative_event=payload["fresh_negative_event"],
        green_spike_atr=_economic_decimal(
            payload["green_spike_atr"], label=f"{label}.green_spike_atr"
        ),
        evidence_trend=payload["evidence_trend"],
        reward_risk_ratio=_economic_decimal(
            payload["reward_risk_ratio"], label=f"{label}.reward_risk_ratio"
        ),
        notional_usd=_economic_decimal(payload["notional_usd"], label=f"{label}.notional_usd"),
    )


def _economic_tournament_candidate(value: object, *, label: str) -> EconomicTournamentCandidate:
    """Rebuild one explicit, cutoff-limited candidate for a frozen arm."""

    payload = _economic_exact_object(
        value,
        label=label,
        fields=frozenset(
            {
                "symbol",
                "available_at",
                "close_t_21",
                "close_t_252",
                "trailing_operating_income",
                "average_total_assets",
                "pullback_features",
            }
        ),
    )
    for field in (
        "close_t_21",
        "close_t_252",
        "trailing_operating_income",
        "average_total_assets",
    ):
        if payload[field] is not None and type(payload[field]) is not str:
            raise typer.BadParameter(f"{label}.{field} must be a decimal string or null")
    if type(payload["available_at"]) is not str:
        raise typer.BadParameter(f"{label}.available_at must be canonical UTC")
    _economic_effective_at(payload["available_at"])
    try:
        return EconomicTournamentCandidate(
            symbol=payload["symbol"],
            available_at=payload["available_at"],
            close_t_21=payload["close_t_21"],
            close_t_252=payload["close_t_252"],
            trailing_operating_income=payload["trailing_operating_income"],
            average_total_assets=payload["average_total_assets"],
            pullback_features=_economic_pullback_features(
                payload["pullback_features"],
                label=f"{label}.pullback_features",
            ),
        )
    except (TypeError, ValueError) as exc:
        raise typer.BadParameter(f"{label} is invalid: {exc}") from exc


def _economic_tournament_inputs(
    payload: dict[str, object],
    *,
    expected_event_ids: tuple[str, ...],
) -> tuple[dict[str, tuple[EconomicTournamentCandidate, ...]], tuple[EconomicTournamentOutcome, ...]]:
    """Require one complete, canonically ordered validation tournament input."""

    values = _economic_exact_object(
        payload,
        label="economic tournament input",
        fields=frozenset({"candidates_by_event", "outcomes"}),
    )
    raw_candidates = values["candidates_by_event"]
    raw_outcomes = values["outcomes"]
    if type(raw_candidates) is not list or type(raw_outcomes) is not list:
        raise typer.BadParameter("economic tournament inputs must contain JSON lists")
    candidate_rows: list[tuple[str, tuple[EconomicTournamentCandidate, ...]]] = []
    for index, raw_row in enumerate(raw_candidates):
        row = _economic_exact_object(
            raw_row,
            label=f"economic tournament candidates_by_event[{index}]",
            fields=frozenset({"decision_event_id", "candidates"}),
        )
        if type(row["decision_event_id"]) is not str or type(row["candidates"]) is not list:
            raise typer.BadParameter(
                f"economic tournament candidates_by_event[{index}] is invalid"
            )
        candidate_rows.append(
            (
                row["decision_event_id"],
                tuple(
                    _economic_tournament_candidate(
                        candidate,
                        label=f"economic tournament candidates_by_event[{index}].candidates[{offset}]",
                    )
                    for offset, candidate in enumerate(row["candidates"])
                ),
            )
        )
    if tuple(item[0] for item in candidate_rows) != expected_event_ids:
        raise typer.BadParameter(
            "economic tournament candidate rows must exactly match canonical validation IDs"
        )
    outcome_rows: list[EconomicTournamentOutcome] = []
    for index, raw_row in enumerate(raw_outcomes):
        row = _economic_exact_object(
            raw_row,
            label=f"economic tournament outcomes[{index}]",
            fields=frozenset({"decision_event_id", "realized_returns"}),
        )
        returns = row["realized_returns"]
        if type(row["decision_event_id"]) is not str or type(returns) is not list:
            raise typer.BadParameter(f"economic tournament outcomes[{index}] is invalid")
        return_rows: list[tuple[str, str]] = []
        for offset, raw_return in enumerate(returns):
            realized = _economic_exact_object(
                raw_return,
                label=f"economic tournament outcomes[{index}].realized_returns[{offset}]",
                fields=frozenset({"symbol", "return"}),
            )
            if type(realized["symbol"]) is not str or type(realized["return"]) is not str:
                raise typer.BadParameter(
                    f"economic tournament outcomes[{index}].realized_returns[{offset}] is invalid"
                )
            return_rows.append((realized["symbol"], realized["return"]))
        try:
            outcome_rows.append(
                EconomicTournamentOutcome(
                    decision_event_id=row["decision_event_id"],
                    realized_returns=tuple(return_rows),
                )
            )
        except (TypeError, ValueError) as exc:
            raise typer.BadParameter(
                f"economic tournament outcomes[{index}] are invalid: {exc}"
            ) from exc
    if tuple(item.decision_event_id for item in outcome_rows) != expected_event_ids:
        raise typer.BadParameter(
            "economic tournament outcome rows must exactly match canonical validation IDs"
        )
    return dict(candidate_rows), tuple(outcome_rows)


def _economic_validation_report(
    *,
    protocol_id: str,
    partitions: object,
    validation_event_ids: tuple[str, ...],
    result: object,
    tournament_input: SourceBoundTournamentInput,
) -> dict[str, object]:
    """Wrap one canonical validation result in the immutable admission schema."""

    result_payload = result.to_dict()
    return {
        "schema_version": "economic_validation_report/v3",
        "protocol_id": protocol_id,
        "market_date_partitions": partitions.to_dict(),
        "validation_event_ids": list(validation_event_ids),
        "result": result_payload,
        "result_id": result_payload["result_id"],
        "result_sha256": result_payload["result_sha256"],
        "tournament_input": {
            "input_id": tournament_input.input_id,
            "input_sha256": tournament_input.input_sha256,
        },
        "analysis_only": True,
        "execution_authority": "none",
        "can_submit_orders": False,
    }


def _economic_effective_at(value: str) -> datetime.datetime:
    """Parse a canonical, second-aligned UTC receipt timestamp."""

    try:
        parsed = datetime.datetime.fromisoformat(value)
    except ValueError as exc:
        raise typer.BadParameter("effective-at must be canonical UTC ISO-8601 seconds") from exc
    if (
        parsed.tzinfo is None
        or parsed.utcoffset() != datetime.timedelta(0)
        or parsed.microsecond
        or parsed.isoformat(timespec="seconds") != value
    ):
        raise typer.BadParameter("effective-at must be canonical UTC ISO-8601 seconds")
    return parsed


@research_app.command("economic-cohort-build")
def research_economic_cohort_build(
    candidate_input_path: Path = typer.Option(
        ...,
        "--candidate-input-path",
        exists=True,
        readable=True,
        help="Security identities plus registered retained-source profiles; caller-authored qualification facts and paths are rejected.",
    ),
    pit_artifact_root: Path = typer.Option(
        ...,
        "--pit-artifact-root",
        exists=True,
        file_okay=False,
        readable=True,
        help="Immutable PIT raw-artifact archive reopened for every cohort candidate.",
    ),
    market_calendar_path: Path = typer.Option(
        ...,
        "--market-calendar-path",
        exists=True,
        readable=True,
        help="Canonical source-bound market-session calendar receipt.",
    ),
    output_path: Path = typer.Option(
        ...,
        "--output-path",
        help="New local canonical cohort receipt path; a differing existing receipt is rejected.",
    ),
    json_output: bool = typer.Option(False, "--json-output"),
):
    """Build one analysis-only cohort by reopening retained local source bytes."""

    from tradingagents.dataflows.pit.raw_artifacts import (
        RawPointInTimeArtifactArchive as CohortArtifactArchive,
    )

    cohort = _economic_cohort_from_input(
        _economic_json_object(
            candidate_input_path,
            label="candidate-input-path",
            max_bytes=4_000_000,
        ),
        archive=CohortArtifactArchive(pit_artifact_root),
        market_calendar=_economic_json_object(
            market_calendar_path,
            label="market-calendar-path",
            max_bytes=2_000_000,
            require_canonical=True,
        ),
    )
    written = _write_economic_receipt(
        output_path,
        cohort.to_dict(),
        label="economic cohort receipt",
    )
    payload = {
        "analysis_only": True,
        "execution_authority": "none",
        "can_submit_orders": False,
        "cohort_id": cohort.cohort_id,
        "cohort_sha256": cohort.cohort_sha256,
        "sensitivity_universe_100_id": cohort.sensitivity_universe_100_id,
        "sensitivity_universe_100_sha256": cohort.sensitivity_universe_100_sha256,
        "primary_universe_75_id": cohort.primary_universe_75_id,
        "primary_universe_75_sha256": cohort.primary_universe_75_sha256,
        "sensitivity_universe_50_id": cohort.sensitivity_universe_50_id,
        "sensitivity_universe_50_sha256": cohort.sensitivity_universe_50_sha256,
        "receipt_path": str(written),
    }
    if json_output:
        typer.echo(json.dumps(payload, indent=2, sort_keys=True))
        return
    console.print(f"Economic cohort: {cohort.cohort_id}")
    console.print(f"Canonical local receipt: {written}")
    console.print("Analysis-only; this receipt grants no execution or promotion authority.")


@research_app.command("economic-tournament-run")
def research_economic_tournament_run(
    protocol_path: Path = typer.Option(
        ...,
        "--protocol-path",
        exists=True,
        readable=True,
        help="Canonical frozen protocol JSON receipt already admitted to the evidence store.",
    ),
    partitions_path: Path = typer.Option(
        ...,
        "--partitions-path",
        exists=True,
        readable=True,
        help="Canonical PIT market-date partition receipt for this protocol.",
    ),
    tournament_input_path: Path = typer.Option(
        ...,
        "--tournament-input-path",
        exists=True,
        readable=True,
        help="Complete source-bound candidate and realized-outcome evidence JSON for validation only.",
    ),
    pit_artifact_root: Path = typer.Option(
        ...,
        "--pit-artifact-root",
        exists=True,
        file_okay=False,
        readable=True,
        help="Immutable PIT raw-artifact archive that must verify every tournament input.",
    ),
    evidence_root: Path = typer.Option(
        Path("results/economic_evaluation/evidence"),
        "--evidence-root",
        help="Immutable local economic-evidence store root.",
    ),
    repo_root: Path = typer.Option(
        CANONICAL_REPOSITORY_ROOT,
        "--repo-root",
        exists=True,
        file_okay=False,
        readable=True,
        help="Repository root retained for the immutable admission adapter identity.",
    ),
    effective_at: str = typer.Option(
        ...,
        "--effective-at",
        help="Canonical UTC timestamp for the immutable validation-only receipt.",
    ),
    json_output: bool = typer.Option(False, "--json-output"),
):
    """Admit one sealed validation TA-Control result as analysis-only evidence."""

    protocol_payload = _economic_json_object(protocol_path, label="protocol-path")
    partitions_payload = _economic_json_object(partitions_path, label="partitions-path")
    tournament_payload = _economic_json_object(
        tournament_input_path,
        label="tournament-input-path",
        max_bytes=32_000_000,
        require_canonical=True,
    )
    effective = _economic_effective_at(effective_at)
    try:
        protocol = validate_frozen_evaluation_protocol(protocol_payload)
        eligibility = bind_validation_phase_eligibility(
            protocol=protocol,
            partitions=validate_market_date_partitions(partitions_payload),
        )
        tournament_input = validate_source_bound_tournament_input(
            tournament_payload,
            protocol=protocol,
            eligibility=eligibility,
        )
        tournament_input = verify_source_bound_tournament_input(
            archive=RawPointInTimeArtifactArchive(pit_artifact_root),
            value=tournament_input.to_dict(),
            protocol=protocol,
            eligibility=eligibility,
        )
        result = evaluate_validation_ta_control(
            protocol=protocol,
            eligibility=eligibility,
            candidates_by_event=dict(tournament_input.candidates_by_event),
            outcomes=tournament_input.outcomes,
        )
        admission = EconomicEvaluationAdmissionAdapter(
            evidence_root,
            repo_root=repo_root,
        ).admit_evaluation_run(
            protocol.protocol_id,
            phase="validation",
            effective_at=effective,
            pit_artifact_root=pit_artifact_root,
            tournament_input=tournament_input,
            frozen_validation_report=_economic_validation_report(
                protocol_id=protocol.protocol_id,
                partitions=eligibility.partitions,
                validation_event_ids=eligibility.event_ids,
                result=result,
                tournament_input=tournament_input,
            ),
        )
    except (EconomicEvaluationAdmissionError, TypeError, ValueError) as exc:
        raise typer.BadParameter(f"economic tournament admission rejected: {exc}") from exc
    payload = {
        "analysis_only": True,
        "execution_authority": "none",
        "can_submit_orders": False,
        "protocol_id": result.protocol_id,
        "validation_result_id": result.result_id,
        "validation_partition_id": result.validation_partition_id,
        "tournament_input_id": tournament_input.input_id,
        "tournament_input_sha256": tournament_input.input_sha256,
        "evaluation_run_object_id": admission.envelope.object_id,
        "created": admission.created,
        "evidence_root": str(evidence_root),
    }
    if json_output:
        typer.echo(json.dumps(payload, indent=2, sort_keys=True))
        return
    console.print(f"Economic validation result: {result.result_id}")
    console.print(f"Immutable validation admission: {admission.envelope.object_id}")
    console.print("Analysis-only; this receipt grants no execution or promotion authority.")


@research_app.command("economic-holdout-release")
def research_economic_holdout_release(
    protocol_id: str = typer.Option(
        ...,
        "--protocol-id",
        help="Exact protocol ID whose immutable validation report is eligible for release.",
    ),
    released_by: str = typer.Option(
        ...,
        "--released-by",
        help="Explicit owner identifier recorded in the immutable release evidence.",
    ),
    released_at: str = typer.Option(
        ...,
        "--released-at",
        help="Canonical UTC timestamp for the immutable holdout-release receipt.",
    ),
    evidence_root: Path = typer.Option(
        Path("results/economic_evaluation/evidence"),
        "--evidence-root",
        help="Immutable local economic-evidence store root.",
    ),
    repo_root: Path = typer.Option(
        CANONICAL_REPOSITORY_ROOT,
        "--repo-root",
        exists=True,
        file_okay=False,
        readable=True,
        help="Repository root retained for the immutable admission adapter identity.",
    ),
    json_output: bool = typer.Option(False, "--json-output"),
):
    """Release a sealed holdout only from its existing immutable validation report."""

    released = _economic_effective_at(released_at)
    try:
        adapter = EconomicEvaluationAdmissionAdapter(evidence_root, repo_root=repo_root)
        release = adapter.release_holdout(
            protocol_id,
            released_by=released_by,
            released_at=released,
            frozen_validation_report=adapter.frozen_validation_report(protocol_id),
        )
    except (EconomicEvaluationAdmissionError, TypeError, ValueError) as exc:
        raise typer.BadParameter(f"economic holdout release rejected: {exc}") from exc
    payload = {
        "analysis_only": True,
        "execution_authority": "none",
        "can_submit_orders": False,
        "protocol_id": release.protocol_id,
        "holdout_release_object_id": release.envelope.object_id,
        "validation_run_object_id": release.validation_run_object_id,
        "created": release.created,
        "evidence_root": str(evidence_root),
    }
    if json_output:
        typer.echo(json.dumps(payload, indent=2, sort_keys=True))
        return
    console.print(f"Economic holdout release: {release.envelope.object_id}")
    console.print("Analysis-only; this release grants no execution or promotion authority.")


@research_app.command("economic-readiness-status")
def research_economic_readiness_status(
    protocol_id: str = typer.Option(
        ...,
        "--protocol-id",
        help="Exact economic protocol ID to inspect without opening holdout rows.",
    ),
    evidence_root: Path = typer.Option(
        Path("results/economic_evaluation/evidence"),
        "--evidence-root",
        help="Immutable local economic-evidence store root.",
    ),
    repo_root: Path = typer.Option(
        CANONICAL_REPOSITORY_ROOT,
        "--repo-root",
        exists=True,
        file_okay=False,
        readable=True,
        help="Repository root retained for the immutable admission adapter identity.",
    ),
    json_output: bool = typer.Option(False, "--json-output"),
):
    """Read non-authorizing economic evidence state without accessing holdout rows."""

    try:
        readiness = EconomicEvaluationAdmissionAdapter(
            evidence_root,
            repo_root=repo_root,
        ).readiness_status(protocol_id)
    except (EconomicEvaluationAdmissionError, TypeError, ValueError) as exc:
        raise typer.BadParameter(f"economic readiness status rejected: {exc}") from exc
    payload = {
        "analysis_only": True,
        "execution_authority": "none",
        "can_submit_orders": False,
        "protocol_id": readiness.protocol_id,
        "state": readiness.state,
        "protocol_admission_object_id": readiness.protocol_admission_object_id,
        "validation_run_object_id": readiness.validation_run_object_id,
        "holdout_release_object_id": readiness.holdout_release_object_id,
        "evidence_sequence": readiness.evidence_sequence,
        "evidence_head_event_sha256": readiness.evidence_head_event_sha256,
        "evidence_root": str(evidence_root),
    }
    if json_output:
        typer.echo(json.dumps(payload, indent=2, sort_keys=True))
        return
    console.print(f"Economic evidence state: {readiness.state}")
    console.print("Read-only and analysis-only; this status grants no execution or promotion authority.")


@research_app.command("economic-protocol-admit")
def research_economic_protocol_admit(
    protocol_path: Path = typer.Option(
        ...,
        "--protocol-path",
        exists=True,
        readable=True,
        help="Canonical frozen economic protocol JSON receipt.",
    ),
    evidence_root: Path = typer.Option(
        Path("results/economic_evaluation/evidence"),
        "--evidence-root",
        help="Immutable local economic-evidence store root.",
    ),
    repo_root: Path = typer.Option(
        CANONICAL_REPOSITORY_ROOT,
        "--repo-root",
        exists=True,
        file_okay=False,
        readable=True,
        help="Repository root that owns the declared source paths.",
    ),
    source_revision: str = typer.Option(
        ...,
        "--source-revision",
        help="Exact 40-character Git revision that produced the protocol source.",
    ),
    source_paths: list[str] = typer.Option(
        [],
        "--source-path",
        help="Repository-relative source path to bind; repeat for every source file.",
    ),
    effective_at: str = typer.Option(
        ...,
        "--effective-at",
        help="Canonical UTC timestamp for this immutable analysis-only receipt.",
    ),
    json_output: bool = typer.Option(False, "--json-output"),
):
    """Admit one complete frozen protocol as analysis-only local evidence.

    This command has no provider, broker, scheduling, promotion, or submit
    option. It binds only supplied protocol bytes, repository source bytes,
    and the immutable evidence-store predecessor.
    """

    if not source_paths:
        raise typer.BadParameter("at least one --source-path is required")
    protocol_payload = _economic_json_object(protocol_path, label="protocol-path")
    effective = _economic_effective_at(effective_at)
    try:
        protocol = validate_frozen_evaluation_protocol(protocol_payload)
        admission = EconomicEvaluationAdmissionAdapter(
            evidence_root,
            repo_root=repo_root,
        ).admit_protocol(
            protocol,
            source_revision=source_revision,
            effective_at=effective,
            source_paths=tuple(source_paths),
        )
    except (EconomicEvaluationAdmissionError, TypeError, ValueError) as exc:
        raise typer.BadParameter(f"economic protocol admission rejected: {exc}") from exc
    payload = {
        "analysis_only": True,
        "execution_authority": "none",
        "can_submit_orders": False,
        "protocol_id": admission.protocol_id,
        "input_manifest_sha256": admission.input_manifest_sha256,
        "admission_object_id": admission.envelope.object_id,
        "created": admission.created,
        "evidence_root": str(evidence_root),
        "source_revision": source_revision,
    }
    if json_output:
        typer.echo(json.dumps(payload, indent=2, sort_keys=True))
        return
    console.print(f"Economic protocol: {payload['protocol_id']}")
    console.print(f"Immutable admission: {payload['admission_object_id']}")
    console.print("Analysis-only; this receipt grants no execution or promotion authority.")


@research_app.command("walk-forward-replay")
def research_walk_forward_replay(
    fixture_path: Path = typer.Option(
        ...,
        "--fixture-path",
        exists=True,
        readable=True,
        help="JSON fixture file with fixed-as-of rows or {'rows': [...]} payload.",
    ),
    candidate_symbols: str = typer.Option(
        "",
        "--candidate-symbols",
        help="Optional comma-separated symbols to filter and include in the walk-forward replay.",
    ),
    sleeve: str = typer.Option(
        "pullback-support",
        "--sleeve",
        help="Strategy sleeve being evaluated.",
    ),
    benchmark: str = typer.Option("SPY", "--benchmark"),
    minimum_decisions_per_arm: int = typer.Option(
        10,
        "--minimum-decisions-per-arm",
        min=1,
        help="Minimum baseline fixture rows before the replay can be treated as sample-floor clean.",
    ),
    hold_band: str = typer.Option(
        "0.0025",
        "--hold-band",
        help="Relative-return band where a hold decision counts directionally correct.",
    ),
    commission_bps: str = typer.Option("0", "--commission-bps"),
    half_spread_bps: str = typer.Option("0", "--half-spread-bps"),
    slippage_bps: str = typer.Option("0", "--slippage-bps"),
    latency_bps_per_second: str = typer.Option("0", "--latency-bps-per-second"),
    round_trip_sides: int = typer.Option(2, "--round-trip-sides", min=1, max=4),
    output_dir: Path = typer.Option(
        Path("results/research_batches"),
        "--output-dir",
        help="Directory for walk-forward replay packets.",
    ),
    json_output: bool = typer.Option(False, "--json-output"),
):
    """Write an analysis-only fixed-as-of walk-forward replay packet."""
    fixture_payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    fixture_rows = fixture_payload.get("rows") if isinstance(fixture_payload, dict) else fixture_payload
    if not isinstance(fixture_rows, list):
        raise typer.BadParameter("fixture file must be a JSON list or an object with a rows list")
    packet = build_walk_forward_replay_packet(
        fixture_rows,
        candidate_symbols=candidate_symbols,
        sleeve=sleeve,
        benchmark=benchmark,
        minimum_decisions_per_arm=minimum_decisions_per_arm,
        hold_band=hold_band,
        commission_bps=commission_bps,
        half_spread_bps=half_spread_bps,
        slippage_bps=slippage_bps,
        latency_bps_per_second=latency_bps_per_second,
        round_trip_sides=round_trip_sides,
    )
    packet_path = write_research_packet(packet, output_dir)
    payload = packet.model_dump()
    payload["packet_path"] = str(packet_path)
    payload["fixture_path"] = str(fixture_path)
    if json_output:
        typer.echo(json.dumps(payload, indent=2))
        return
    console.print(f"Walk-forward sleeve: {packet.quality_gates['sleeve']}")
    console.print(f"Fixture rows: {packet.quality_gates['walk_forward_row_count']}")
    console.print(f"Sample floor met: {packet.quality_gates['sample_floor_met']}")
    console.print(f"Packet: {packet_path}")


@research_app.command("walk-forward-fixture-from-overnight")
def research_walk_forward_fixture_from_overnight(
    overnight_packet_paths: list[Path] = typer.Option(
        [],
        "--overnight-packet",
        exists=True,
        readable=True,
        help="Captured overnight plan packet JSON. Repeat for multiple packets.",
    ),
    returns_path: Path = typer.Option(
        ...,
        "--returns-path",
        exists=True,
        readable=True,
        help="JSON return rows keyed by symbol/as_of, or {'rows': [...]} payload.",
    ),
    output_path: Path = typer.Option(
        Path("results/research_batches/walk_forward_fixture_from_overnight.json"),
        "--output-path",
        help="Where to write the generated walk-forward fixture JSON.",
    ),
    benchmark: str = typer.Option("SPY", "--benchmark"),
    json_output: bool = typer.Option(False, "--json-output"),
):
    """Build fixed-as-of replay fixture rows from captured overnight packets."""
    if not overnight_packet_paths:
        raise typer.BadParameter("at least one --overnight-packet is required")
    overnight_packets: list[dict[str, Any]] = []
    for packet_path in overnight_packet_paths:
        payload = json.loads(packet_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise typer.BadParameter(f"{packet_path} must contain a JSON object")
        payload.setdefault("packet_path", str(packet_path))
        overnight_packets.append(payload)
    returns_payload = json.loads(returns_path.read_text(encoding="utf-8"))
    return_rows = returns_payload.get("rows") if isinstance(returns_payload, dict) else returns_payload
    if not isinstance(return_rows, list):
        raise typer.BadParameter("returns file must be a JSON list or an object with a rows list")
    fixture = build_walk_forward_fixture_from_overnight_packets(
        overnight_packets,
        return_rows,
        benchmark=benchmark,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(fixture, indent=2), encoding="utf-8")
    payload = dict(fixture)
    payload["output_path"] = str(output_path)
    payload["returns_path"] = str(returns_path)
    payload["overnight_packet_paths"] = [str(path) for path in overnight_packet_paths]
    if json_output:
        typer.echo(json.dumps(payload, indent=2))
        return
    console.print(f"Fixture rows: {fixture['row_count']}")
    console.print(f"Skipped results: {fixture['skipped_count']}")
    console.print(f"Output: {output_path}")


@research_app.command("walk-forward-returns-from-overnight")
def research_walk_forward_returns_from_overnight(
    overnight_packet_paths: list[Path] = typer.Option(
        [],
        "--overnight-packet",
        exists=True,
        readable=True,
        help="Captured overnight plan packet JSON. Repeat for multiple packets.",
    ),
    output_path: Path = typer.Option(
        Path("results/research_batches/walk_forward_returns_from_overnight.json"),
        "--output-path",
        help="Where to write collected return rows.",
    ),
    benchmark: str = typer.Option("SPY", "--benchmark"),
    horizon_days: int = typer.Option(
        5,
        "--horizon-days",
        min=1,
        help="Calendar-day window from captured as-of date to return resolution date.",
    ),
    price_rows_path: Path | None = typer.Option(
        None,
        "--price-rows-path",
        exists=True,
        readable=True,
        help="Optional deterministic price rows for tests, or {'rows': [...]} payload.",
    ),
    json_output: bool = typer.Option(False, "--json-output"),
):
    """Collect later return rows for captured overnight decisions."""
    if not overnight_packet_paths:
        raise typer.BadParameter("at least one --overnight-packet is required")
    overnight_packets: list[dict[str, Any]] = []
    for packet_path in overnight_packet_paths:
        payload = json.loads(packet_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise typer.BadParameter(f"{packet_path} must contain a JSON object")
        payload.setdefault("packet_path", str(packet_path))
        overnight_packets.append(payload)
    if price_rows_path is not None:
        price_payload = json.loads(price_rows_path.read_text(encoding="utf-8"))
        price_rows = price_payload.get("rows") if isinstance(price_payload, dict) else price_payload
        if not isinstance(price_rows, list):
            raise typer.BadParameter("price rows file must be a JSON list or an object with a rows list")
        price_lookup = _static_price_lookup_from_rows(price_rows)
        price_route = "static_price_rows"
    else:
        price_lookup = _ledger_price_lookup
        price_route = "yfinance"
    payload = build_walk_forward_return_rows_from_overnight_packets(
        overnight_packets,
        price_lookup=price_lookup,
        horizon_days=horizon_days,
        benchmark=benchmark,
    )
    payload["price_route"] = price_route
    if price_rows_path is not None:
        payload["price_rows_path"] = str(price_rows_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    payload["output_path"] = str(output_path)
    payload["overnight_packet_paths"] = [str(path) for path in overnight_packet_paths]
    if json_output:
        typer.echo(json.dumps(payload, indent=2))
        return
    console.print(f"Return rows: {payload['row_count']}")
    console.print(f"Skipped results: {payload['skipped_count']}")
    console.print(f"Output: {output_path}")


@research_app.command("walk-forward-refresh-overnight-cohort")
def research_walk_forward_refresh_overnight_cohort(
    overnight_log_dir: Path = typer.Option(
        Path("results/overnight_plans"),
        "--overnight-log-dir",
        exists=True,
        file_okay=False,
        readable=True,
        help="Directory containing captured overnight-plan-*.json packets.",
    ),
    output_dir: Path = typer.Option(
        Path("results/research_batches"),
        "--output-dir",
        help="Directory for collected return rows, generated fixture, replay packet, and cohort summary.",
    ),
    benchmark: str = typer.Option("SPY", "--benchmark"),
    horizon_days: int = typer.Option(
        3,
        "--horizon-days",
        min=1,
        help="Calendar-day return window used to decide whether an overnight packet is mature.",
    ),
    through_date: str | None = typer.Option(
        None,
        "--through-date",
        help="Date that return collection may use through. Defaults to today's UTC date.",
    ),
    max_packets: int = typer.Option(
        12,
        "--max-packets",
        min=1,
        help="Maximum mature overnight packets to include in the cohort.",
    ),
    price_rows_path: Path | None = typer.Option(
        None,
        "--price-rows-path",
        exists=True,
        readable=True,
        help="Optional deterministic price rows for tests/proofs, or {'rows': [...]} payload.",
    ),
    sleeve: str = typer.Option("pullback-support", "--sleeve"),
    minimum_decisions_per_arm: int = typer.Option(
        10,
        "--minimum-decisions-per-arm",
        min=1,
    ),
    hold_band: str = typer.Option("0.0025", "--hold-band"),
    commission_bps: str = typer.Option("0", "--commission-bps"),
    half_spread_bps: str = typer.Option("0", "--half-spread-bps"),
    slippage_bps: str = typer.Option("0", "--slippage-bps"),
    latency_bps_per_second: str = typer.Option("0", "--latency-bps-per-second"),
    round_trip_sides: int = typer.Option(2, "--round-trip-sides", min=1, max=4),
    json_output: bool = typer.Option(False, "--json-output"),
):
    """Refresh the mature overnight walk-forward cohort end-to-end."""
    if through_date:
        try:
            resolved_through_date = datetime.date.fromisoformat(through_date[:10])
        except ValueError as exc:
            raise typer.BadParameter("--through-date must be YYYY-MM-DD") from exc
    else:
        resolved_through_date = datetime.datetime.now(tz=datetime.timezone.utc).date()
    selected, skipped_packets = _discover_mature_overnight_packets(
        overnight_log_dir,
        horizon_days=horizon_days,
        through_date=resolved_through_date,
        max_packets=max_packets,
    )
    overnight_packets = [packet for _path, packet in selected]
    if price_rows_path is not None:
        price_payload = json.loads(price_rows_path.read_text(encoding="utf-8"))
        price_rows = price_payload.get("rows") if isinstance(price_payload, dict) else price_payload
        if not isinstance(price_rows, list):
            raise typer.BadParameter("price rows file must be a JSON list or an object with a rows list")
        price_lookup = _static_price_lookup_from_rows(price_rows)
        price_route = "static_price_rows"
    else:
        price_lookup = _ledger_price_lookup
        price_route = "yfinance"

    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now(tz=datetime.timezone.utc).strftime("%Y%m%d-%H%M%S")
    returns_payload = build_walk_forward_return_rows_from_overnight_packets(
        overnight_packets,
        price_lookup=price_lookup,
        horizon_days=horizon_days,
        benchmark=benchmark,
    )
    returns_payload["price_route"] = price_route
    returns_payload["through_date"] = resolved_through_date.isoformat()
    returns_payload["selected_packet_paths"] = [str(path) for path, _packet in selected]
    returns_payload["skipped_packet_count"] = len(skipped_packets)
    returns_payload["skipped_packets"] = skipped_packets
    if price_rows_path is not None:
        returns_payload["price_rows_path"] = str(price_rows_path)
    returns_path = output_dir / f"walk_forward_returns_cohort_{stamp}_h{horizon_days}.json"
    returns_path.write_text(json.dumps(returns_payload, indent=2), encoding="utf-8")

    fixture = build_walk_forward_fixture_from_overnight_packets(
        overnight_packets,
        returns_payload["rows"],
        benchmark=benchmark,
    )
    fixture["returns_path"] = str(returns_path)
    fixture["through_date"] = resolved_through_date.isoformat()
    fixture_path = output_dir / f"walk_forward_fixture_cohort_{stamp}_h{horizon_days}.json"
    fixture_path.write_text(json.dumps(fixture, indent=2), encoding="utf-8")

    replay_packet = build_walk_forward_replay_packet(
        fixture["rows"],
        candidate_symbols="",
        sleeve=sleeve,
        benchmark=benchmark,
        minimum_decisions_per_arm=minimum_decisions_per_arm,
        hold_band=hold_band,
        commission_bps=commission_bps,
        half_spread_bps=half_spread_bps,
        slippage_bps=slippage_bps,
        latency_bps_per_second=latency_bps_per_second,
        round_trip_sides=round_trip_sides,
    )
    replay_packet_path = write_research_packet(replay_packet, output_dir)
    summary = {
        "kind": "walk_forward_overnight_cohort_refresh",
        "schema_version": "1.0.0",
        "generated_at": datetime.datetime.now(tz=datetime.timezone.utc).isoformat(timespec="seconds"),
        "analysis_only": True,
        "can_submit_orders": False,
        "execution_authority": "none",
        "forbidden_effects": FORBIDDEN_EFFECTS,
        "overnight_log_dir": str(overnight_log_dir),
        "through_date": resolved_through_date.isoformat(),
        "horizon_days": horizon_days,
        "benchmark": benchmark.strip().upper() or "SPY",
        "price_route": price_route,
        "selected_packet_count": len(selected),
        "selected_packet_paths": [str(path) for path, _packet in selected],
        "skipped_packet_count": len(skipped_packets),
        "skipped_packets": skipped_packets,
        "returns_path": str(returns_path),
        "returns_row_count": returns_payload["row_count"],
        "returns_skipped_count": returns_payload["skipped_count"],
        "fixture_path": str(fixture_path),
        "fixture_row_count": fixture["row_count"],
        "fixture_skipped_count": fixture["skipped_count"],
        "replay_packet_path": str(replay_packet_path),
        "sample_floor_met": replay_packet.quality_gates["sample_floor_met"],
        "walk_forward_metrics": replay_packet.quality_gates["walk_forward_metrics"],
        "next_action": (
            "Use this cohort for calibration only after sample floors are met; "
            "otherwise keep collecting mature overnight packets."
        ),
    }
    summary_path = output_dir / f"walk_forward_cohort_refresh_{stamp}_h{horizon_days}.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    summary["summary_path"] = str(summary_path)
    if json_output:
        typer.echo(json.dumps(summary, indent=2))
        return
    console.print(f"Selected overnight packets: {summary['selected_packet_count']}")
    console.print(f"Return rows: {summary['returns_row_count']}")
    console.print(f"Fixture rows: {summary['fixture_row_count']}")
    console.print(f"Sample floor met: {summary['sample_floor_met']}")
    console.print(f"Summary: {summary_path}")


@research_app.command("overnight-calibration-guard")
def research_overnight_calibration_guard(
    cohort_summary_path: Path | None = typer.Option(
        None,
        "--cohort-summary-path",
        exists=True,
        readable=True,
        help="Specific walk_forward_cohort_refresh_*.json summary to evaluate.",
    ),
    input_dir: Path = typer.Option(
        Path("results/research_batches"),
        "--input-dir",
        exists=True,
        file_okay=False,
        readable=True,
        help="Directory containing walk_forward_cohort_refresh_*.json summaries.",
    ),
    output_dir: Path = typer.Option(
        Path("results/overnight_calibration"),
        "--output-dir",
        help="Directory for the latest overnight calibration guard packet.",
    ),
    json_output: bool = typer.Option(False, "--json-output"),
):
    """Build the analysis-only overnight influence calibration guard."""

    selected_path = cohort_summary_path or latest_walk_forward_cohort_path(input_dir)
    cohort_summary: dict[str, Any] | None = None
    if selected_path is not None:
        cohort_summary = json.loads(selected_path.read_text(encoding="utf-8"))
    packet = build_overnight_calibration_guard(
        cohort_summary,
        cohort_summary_path=selected_path,
    )
    packet_path = write_overnight_calibration_guard(packet, output_dir)
    packet["packet_path"] = str(packet_path)
    (output_dir / "latest.json").write_text(json.dumps(packet, indent=2), encoding="utf-8")
    if json_output:
        typer.echo(json.dumps(packet, indent=2))
        return
    console.print(f"Decision: {packet['guard_decision']}")
    console.print(f"Can increase live influence: {packet['can_increase_live_influence']}")
    console.print(f"Packet: {packet_path}")


@research_app.command("process-review")
def research_process_review(
    output_dir: Path = typer.Option(
        Path("results/process_reviews"),
        "--output-dir",
        help="Directory for Plugin Eval-style process review artifacts.",
    ),
    json_output: bool = typer.Option(False, "--json-output"),
):
    """Write a Plugin Eval-inspired structural/process review for this repo."""
    review = build_process_review(Path.cwd())
    json_path, md_path = write_process_review(review, output_dir)
    payload = dict(review)
    payload["json_path"] = str(json_path)
    payload["markdown_path"] = str(md_path)
    if json_output:
        typer.echo(json.dumps(payload, indent=2))
        return
    console.print(f"Process review findings: {len(review['findings'])}")
    console.print(f"Unchecked long-plan items: {review['unchecked_step_count']}")
    console.print(f"Report: {md_path}")


@research_app.command("automation-memory-rollup")
def research_automation_memory_rollup(
    automation_root: Path = typer.Option(
        default_automation_root(),
        "--automation-root",
        help="Codex automation root to inspect.",
    ),
    output_dir: Path = typer.Option(
        Path("results/token_efficiency"),
        "--output-dir",
        help="Directory for automation memory rollup plan artifacts.",
    ),
    max_tail_lines: int = typer.Option(
        80,
        "--max-tail-lines",
        min=0,
        max=500,
        help="Tail lines to retain if a future approved compaction is applied.",
    ),
    candidate_kb: int = typer.Option(
        64,
        "--candidate-kb",
        min=1,
        max=10240,
        help="Memory size threshold for rollup candidacy.",
    ),
    json_output: bool = typer.Option(False, "--json-output"),
    apply: bool = typer.Option(
        False,
        "--apply",
        help="Archive and compact rollup candidates. Requires --confirm-apply.",
    ),
    confirm_apply: bool = typer.Option(
        False,
        "--confirm-apply",
        help="Required with --apply to mutate automation memory files.",
    ),
):
    """Write an analysis-only rollup plan for large automation memory files."""
    packet = build_automation_memory_rollup_plan(
        automation_root=automation_root,
        archive_root=output_dir / "automation_memory_archives",
        max_tail_lines=max_tail_lines,
        candidate_kb=candidate_kb,
    )
    json_path, md_path = write_automation_memory_rollup_plan(packet, output_dir)
    payload = dict(packet)
    payload["json_path"] = str(json_path)
    payload["markdown_path"] = str(md_path)
    if apply:
        if not confirm_apply:
            raise typer.BadParameter("--apply requires --confirm-apply")
        apply_result = apply_automation_memory_rollup_plan(
            packet,
            confirm_apply=confirm_apply,
        )
        apply_path = write_automation_memory_rollup_apply_result(apply_result, output_dir)
        payload["apply_result"] = apply_result
        payload["apply_json_path"] = str(apply_path)
    if json_output:
        typer.echo(json.dumps(payload, indent=2))
        return
    console.print(f"Automation memories inspected: {packet['summary']['memory_count']}")
    console.print(f"Rollup candidates: {packet['summary']['rollup_candidate_count']}")
    if apply:
        console.print(f"Compacted memories: {payload['apply_result']['compacted_count']}")
    console.print(f"Report: {md_path}")


def _build_compact_automation_health_audit(packet: Mapping[str, Any]) -> dict[str, Any]:
    return build_compact_automation_health_audit(packet)


@research_app.command("automation-health-audit")
def research_automation_health_audit(
    automation_root: Path = typer.Option(
        default_automation_root(),
        "--automation-root",
        help="Codex automation root to inspect.",
    ),
    output_dir: Path = typer.Option(
        Path("results/automation_health"),
        "--output-dir",
        help="Directory for automation health audit artifacts.",
    ),
    window_hours: int = typer.Option(24, "--window-hours", min=1, max=168),
    self_heal_plan_sla_minutes: int = typer.Option(
        30,
        "--self-heal-plan-sla-minutes",
        min=1,
        max=240,
        help="Minutes an actionable self-heal handoff may wait before a follow-up plan/execution is flagged late.",
    ),
    json_output: bool = typer.Option(False, "--json-output"),
    compact_json_output: bool = typer.Option(
        False,
        "--compact-json-output",
        help="When used with --json-output, print compact health counts and artifact paths instead of the full audit.",
    ),
):
    """Write an analysis-only automation run-ledger health audit."""
    audit = build_automation_health_audit(
        repo_root=Path.cwd(),
        automation_root=automation_root,
        window_hours=window_hours,
        self_heal_plan_sla_minutes=self_heal_plan_sla_minutes,
    )
    json_path, md_path = write_automation_health_audit(audit, output_dir)
    payload = dict(audit)
    payload["json_path"] = str(json_path)
    payload["markdown_path"] = str(md_path)
    if json_output:
        if compact_json_output:
            typer.echo(json.dumps(_build_compact_automation_health_audit(payload), indent=2))
            return
        typer.echo(json.dumps(payload, indent=2))
        return
    console.print(f"Automation health status: {audit['summary']}")
    console.print(f"Submitted order count: {audit['submitted_order_count']}")
    console.print(f"Report: {md_path}")


@research_app.command("night-shift-patrol")
def research_night_shift_patrol(
    output_dir: Path = typer.Option(
        Path("results/night_shift_patrol"),
        "--output-dir",
        help="Directory for analysis-only night-shift patrol evidence packets.",
    ),
    json_output: bool = typer.Option(False, "--json-output"),
):
    """Write an analysis-only evidence packet for the night-shift supervisor."""
    packet = write_night_shift_patrol_packet(repo_root=Path.cwd(), output_dir=output_dir)
    if json_output:
        typer.echo(json.dumps(packet, indent=2))
        return
    console.print("Night-shift patrol packet written.")
    console.print(f"Packet: {packet['json_path']}")


@research_app.command("controller-patrol")
def research_controller_patrol(
    automation_id: str = typer.Option(
        ...,
        "--automation-id",
        help="Controller automation id to record evidence for.",
    ),
    automation_root: Path = typer.Option(
        default_automation_root(),
        "--automation-root",
        help="Codex automation root to summarize.",
    ),
    output_dir: Path = typer.Option(
        Path("results/control_plane_patrol"),
        "--output-dir",
        help="Directory for analysis-only controller patrol evidence packets.",
    ),
    json_output: bool = typer.Option(False, "--json-output"),
):
    """Write an analysis-only evidence packet for a wake/sleep controller pass."""
    try:
        packet = write_control_plane_patrol_packet(
            repo_root=Path.cwd(),
            automation_root=automation_root,
            automation_id=automation_id,
            output_dir=output_dir,
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc), param_hint="--automation-id") from exc
    if json_output:
        typer.echo(json.dumps(packet, indent=2))
        return
    console.print("Controller patrol packet written.")
    console.print(f"Packet: {packet['json_path']}")


@research_app.command("n8n-evaluation-dataset")
def research_n8n_evaluation_dataset(
    output_dir: Path = typer.Option(
        Path("results/n8n_evaluations"),
        "--output-dir",
        help="Directory for n8n built-in evaluation dataset artifacts.",
    ),
    json_output: bool = typer.Option(False, "--json-output"),
    compact_json_output: bool = typer.Option(
        False,
        "--compact-json-output",
        help="When used with --json-output, print compact dataset metadata and artifact paths instead of all rows.",
    ),
):
    """Write Data Table-ready cases for n8n built-in workflow evaluations."""
    packet = write_n8n_evaluation_dataset(output_dir=output_dir)
    if json_output:
        if compact_json_output:
            typer.echo(json.dumps(build_compact_n8n_evaluation_dataset(packet), indent=2))
            return
        typer.echo(json.dumps(packet, indent=2))
        return
    console.print(f"n8n eval rows: {packet['row_count']}")
    console.print(f"CSV: {packet['csv_path']}")
    console.print(f"JSON: {packet['json_path']}")


@research_app.command("n8n-list-jobs")
def research_n8n_list_jobs(
    allowlist_path: Path | None = typer.Option(
        None,
        "--allowlist-path",
        help="Optional n8n job allowlist path. Defaults to the repo allowlist.",
    ),
    json_output: bool = typer.Option(False, "--json-output"),
):
    """List allowlisted n8n wrapper jobs without running them."""
    packet = list_n8n_runner_jobs(allowlist_path=allowlist_path)
    if json_output:
        typer.echo(json.dumps(packet, indent=2))
        return
    console.print(f"n8n allowlisted jobs: {packet['job_count']}")
    console.print(f"Submit-capable jobs: {packet['submit_capable_count']}")


@research_app.command("n8n-sync-evaluation-table")
def research_n8n_sync_evaluation_table(
    api_base_url: str = typer.Option(
        "http://localhost:5678/api/v1",
        "--api-base-url",
        help="n8n public API base URL.",
    ),
    api_key_env: str = typer.Option(
        "N8N_API_KEY",
        "--api-key-env",
        help="Environment variable holding the n8n API key.",
    ),
    api_key_sqlite_db: Path | None = typer.Option(
        None,
        "--api-key-sqlite-db",
        help="Optional copied n8n SQLite database path used only to read an existing API key; the key is never printed.",
    ),
    table_name: str = typer.Option(
        "TradingAgents_Automation_Evaluations",
        "--table-name",
        help="n8n Data Table name to create/update.",
    ),
    replace: bool = typer.Option(
        True,
        "--replace/--append",
        help="Replace existing rows before inserting the current dataset.",
    ),
    dry_run: bool = typer.Option(False, "--dry-run"),
    output_dir: Path = typer.Option(
        Path("results/n8n_evaluations"),
        "--output-dir",
        help="Directory for redacted n8n sync proof artifacts.",
    ),
    json_output: bool = typer.Option(False, "--json-output"),
):
    """Sync the n8n evaluation dataset into n8n's Data Table through the public API."""
    try:
        result = sync_n8n_evaluation_data_table(
            api_base_url=api_base_url,
            api_key_env=api_key_env,
            api_key_sqlite_db=api_key_sqlite_db,
            table_name=table_name,
            replace=replace,
            dry_run=dry_run,
            output_dir=output_dir,
        )
    except N8NApiSyncError as exc:
        dataset = write_n8n_evaluation_dataset(output_dir=output_dir)
        message = str(exc)
        status = "blocked_missing_api_key" if "missing n8n API key" in message else "error"
        result = {
            "schema_version": 1,
            "status": status,
            "analysis_only": True,
            "can_submit_orders": False,
            "execution_authority": "none",
            "api_base_url": api_base_url,
            "api_key_env": api_key_env,
            "api_key_redacted": True,
            "data_table_name": table_name,
            "expected_row_count": dataset["row_count"],
            "json_path": dataset["json_path"],
            "csv_path": dataset["csv_path"],
            "markdown_path": dataset["markdown_path"],
            "error": message,
            "remediation": f"Set {api_key_env} or pass --api-key-sqlite-db with a copied n8n database, then rerun.",
        }
        if json_output:
            typer.echo(json.dumps(result, indent=2))
        else:
            console.print(f"n8n sync status: {result['status']}")
            console.print(f"Blocked: {message}")
            console.print(f"Dataset ready: {result['json_path']}")
        raise typer.Exit(code=1) from None
    if json_output:
        typer.echo(json.dumps(result, indent=2))
        return
    console.print(f"n8n sync status: {result['status']}")
    console.print(f"Rows: {result['final_row_count']} / {result['expected_row_count']}")
    console.print(f"Proof: {result['json_path']}")


@research_app.command("n8n-sync-workflows")
def research_n8n_sync_workflows(
    api_base_url: str = typer.Option(
        "http://localhost:5678/api/v1",
        "--api-base-url",
        help="n8n public API base URL.",
    ),
    api_key_env: str = typer.Option(
        "N8N_API_KEY",
        "--api-key-env",
        help="Environment variable holding the n8n API key.",
    ),
    api_key_sqlite_db: Path | None = typer.Option(
        None,
        "--api-key-sqlite-db",
        help="Optional copied n8n SQLite database path used only to read an existing API key; the key is never printed.",
    ),
    workflow_dir: Path = typer.Option(
        Path("n8n/workflows"),
        "--workflow-dir",
        help="Directory containing source-controlled n8n workflow JSON files.",
    ),
    dry_run: bool = typer.Option(False, "--dry-run"),
    output_dir: Path = typer.Option(
        Path("results/n8n_evaluations"),
        "--output-dir",
        help="Directory for redacted n8n workflow sync proof artifacts.",
    ),
    json_output: bool = typer.Option(False, "--json-output"),
):
    """Create missing source-controlled n8n observer workflows through the public API."""
    try:
        result = sync_n8n_workflows(
            api_base_url=api_base_url,
            api_key_env=api_key_env,
            api_key_sqlite_db=api_key_sqlite_db,
            workflow_dir=workflow_dir,
            dry_run=dry_run,
            output_dir=output_dir,
        )
    except N8NApiSyncError as exc:
        status = "blocked_missing_api_key" if "missing n8n API key" in str(exc) else "error"
        result = {
            "schema_version": 1,
            "status": status,
            "analysis_only": True,
            "can_submit_orders": False,
            "execution_authority": "none",
            "api_base_url": api_base_url,
            "api_key_env": api_key_env,
            "api_key_redacted": True,
            "workflow_dir": str(workflow_dir),
            "error": str(exc),
            "remediation": f"Set {api_key_env} or pass --api-key-sqlite-db with a copied n8n database, then rerun.",
        }
        if json_output:
            typer.echo(json.dumps(result, indent=2))
        else:
            console.print(f"n8n workflow sync status: {result['status']}")
            console.print(f"Blocked: {result['error']}")
        raise typer.Exit(code=1) from None
    if json_output:
        typer.echo(json.dumps(result, indent=2))
        return
    console.print(f"n8n workflow sync status: {result['status']}")
    console.print(f"Created: {result['created_count']} / {result['source_workflow_count']}")
    console.print(f"Proof: {result['json_path']}")


@research_app.command("n8n-evaluation-run-probe")
def research_n8n_evaluation_run_probe(
    api_base_url: str = typer.Option(
        "http://localhost:5678/api/v1",
        "--api-base-url",
        help="n8n public API base URL.",
    ),
    api_key_env: str = typer.Option(
        "N8N_API_KEY",
        "--api-key-env",
        help="Environment variable holding the n8n API key.",
    ),
    api_key_sqlite_db: Path | None = typer.Option(
        None,
        "--api-key-sqlite-db",
        help="Optional copied n8n SQLite database path used only to read an existing API key; the key is never printed.",
    ),
    workflow_name: str = typer.Option(
        "TA · Built-in Automation Evaluation",
        "--workflow-name",
        help="Name of the native n8n Evaluation Trigger workflow to probe.",
    ),
    output_dir: Path = typer.Option(
        Path("results/n8n_evaluations"),
        "--output-dir",
        help="Directory for redacted n8n evaluation run-probe artifacts.",
    ),
    json_output: bool = typer.Option(False, "--json-output"),
):
    """Probe whether local n8n exposes a native API trigger for built-in evaluations."""
    try:
        result = probe_n8n_builtin_evaluation_run(
            api_base_url=api_base_url,
            api_key_env=api_key_env,
            api_key_sqlite_db=api_key_sqlite_db,
            workflow_name=workflow_name,
            output_dir=output_dir,
        )
    except N8NApiSyncError as exc:
        status = "blocked_missing_api_key" if "missing n8n API key" in str(exc) else "error"
        result = {
            "schema_version": 1,
            "status": status,
            "analysis_only": True,
            "can_submit_orders": False,
            "execution_authority": "none",
            "api_base_url": api_base_url,
            "api_key_env": api_key_env,
            "api_key_redacted": True,
            "workflow_name": workflow_name,
            "error": str(exc),
            "remediation": f"Set {api_key_env} or pass --api-key-sqlite-db with a copied n8n database, then rerun.",
        }
        if json_output:
            typer.echo(json.dumps(result, indent=2))
        else:
            console.print(f"n8n evaluation run probe status: {result['status']}")
            console.print(f"Blocked: {result['error']}")
        raise typer.Exit(code=1) from None
    if json_output:
        typer.echo(json.dumps(result, indent=2))
        return
    console.print(f"n8n evaluation run probe status: {result['status']}")
    console.print(f"Editor required: {result['editor_run_required']}")
    console.print(f"Proof: {result['json_path']}")


@research_app.command("self-heal-handoff")
def research_self_heal_handoff(
    output_dir: Path = typer.Option(
        Path("results/self_heal"),
        "--output-dir",
        help="Directory for self-heal handoff artifacts.",
    ),
    max_triggers: int = typer.Option(
        12,
        "--max-triggers",
        min=1,
        max=50,
        help="Maximum compact triggers to include in the handoff.",
    ),
    refresh_context: bool = typer.Option(
        True,
        "--refresh-context/--no-refresh-context",
        help="Refresh results/_context before building the handoff.",
    ),
    json_output: bool = typer.Option(False, "--json-output"),
):
    """Write a safe handoff prompt for supervisor/control-plane error repair."""
    if refresh_context:
        subprocess.run(
            [sys.executable, "scripts/automation_context_snapshot.py", "--write"],
            text=True,
            capture_output=True,
            timeout=60,
            check=False,
        )
    packet = build_self_heal_handoff(Path.cwd(), max_triggers=max_triggers)
    json_path, markdown_path, prompt_path = write_self_heal_handoff(packet, output_dir)
    payload = dict(packet)
    payload["json_path"] = str(json_path)
    payload["markdown_path"] = str(markdown_path)
    payload["prompt_path"] = str(prompt_path)
    if json_output:
        typer.echo(json.dumps(payload, indent=2))
        return
    console.print(f"Self-heal triggers: {payload['trigger_count']}")
    console.print(f"Start new chat: {payload['should_start_new_chat']}")
    console.print(f"Prompt: {prompt_path}")


@research_app.command("self-heal-plan")
def research_self_heal_plan(
    output_dir: Path = typer.Option(
        Path("results/self_heal/plans"),
        "--output-dir",
        help="Directory for PA self-heal plan artifacts.",
    ),
    max_signals: int = typer.Option(
        20,
        "--max-signals",
        min=1,
        max=100,
        help="Maximum compact failure signals to classify in the plan.",
    ),
    refresh_context: bool = typer.Option(
        True,
        "--refresh-context/--no-refresh-context",
        help="Refresh results/_context before building the self-heal plan.",
    ),
    execute_safe: bool = typer.Option(
        False,
        "--execute-safe/--no-execute-safe",
        help="Run allowlisted safe-plane verification/refresh actions before writing the plan.",
    ),
    safe_reverify_minutes: int = typer.Option(
        15,
        "--safe-reverify-minutes",
        min=0,
        max=1440,
        help="Minutes before a persistent safe-plane signal is verified again.",
    ),
    promotion_owner_approval_path: Path | None = typer.Option(
        None,
        "--promotion-owner-approval-path",
        help=(
            "Signed account_owner JSON artifact for an already prepared, "
            "exact verified-recovery promotion. Used only with --execute-safe."
        ),
    ),
    json_output: bool = typer.Option(False, "--json-output"),
):
    """Write an audited safe-plane self-heal plan without executing fixes."""
    if refresh_context:
        subprocess.run(
            [sys.executable, "scripts/automation_context_snapshot.py", "--write"],
            text=True,
            capture_output=True,
            timeout=60,
            check=False,
        )
    packet = build_self_heal_plan(
        Path.cwd(),
        max_signals=max_signals,
        output_dir=output_dir,
        safe_reverify_minutes=safe_reverify_minutes,
    )
    # This command is analysis-only unless the caller explicitly requests the
    # already allowlisted safe-plane action.  In particular, an
    # ``owned_recovery_ready`` classification is evidence for a later
    # independently controlled recovery operation; it is not authority to
    # coordinate recovery, rearm live control, or run an executor here.
    promotion_owner_approval = None
    if promotion_owner_approval_path is not None:
        if not execute_safe:
            raise typer.BadParameter(
                "--promotion-owner-approval-path requires --execute-safe"
            )
        if (
            not promotion_owner_approval_path.is_file()
            or promotion_owner_approval_path.is_symlink()
        ):
            raise typer.BadParameter(
                "promotion owner approval must be a regular non-symlink JSON file"
            )
        try:
            promotion_owner_approval = json.loads(
                promotion_owner_approval_path.read_text(encoding="utf-8")
            )
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise typer.BadParameter(
                "promotion owner approval artifact is unreadable JSON"
            ) from exc
        if not isinstance(promotion_owner_approval, dict):
            raise typer.BadParameter(
                "promotion owner approval artifact must be a JSON object"
            )
    if execute_safe:
        execute_kwargs = (
            {"promotion_owner_approval": promotion_owner_approval}
            if promotion_owner_approval is not None
            else {}
        )
        packet = execute_self_heal_plan(
            packet,
            repo_root=Path.cwd(),
            **execute_kwargs,
        )
    json_path, markdown_path = write_self_heal_plan(packet, output_dir)
    payload = dict(packet)
    payload["json_path"] = str(json_path)
    payload["markdown_path"] = str(markdown_path)
    if json_output:
        typer.echo(json.dumps(payload, indent=2))
        return
    console.print(f"Self-heal signals: {payload['signal_count']}")
    console.print(f"Active safe plans: {payload['active_plan_count']}")
    console.print(f"Escalations: {payload['escalation_count']}")
    console.print(f"Plan: {markdown_path}")


@research_app.command("email-clarity-eval")
def research_email_clarity_eval(
    body_file: Path = typer.Option(
        ...,
        "--body-file",
        help="Text file containing the rendered email body to evaluate.",
    ),
    subject: str = typer.Option(
        "",
        "--subject",
        help="Optional rendered email subject.",
    ),
    report_type: str = typer.Option(
        "daily",
        "--report-type",
        help="Email type: daily or urgent.",
    ),
    output_dir: Path = typer.Option(
        Path("results/email_clarity"),
        "--output-dir",
        help="Directory for email clarity eval artifacts.",
    ),
    json_output: bool = typer.Option(False, "--json-output"),
):
    """Evaluate whether an operator email is concise, plain, and actionable."""
    body = body_file.read_text(encoding="utf-8")
    evaluation = evaluate_email_clarity(body, subject=subject, report_type=report_type)
    json_path, md_path = write_email_clarity_eval(evaluation, output_dir)
    payload = dict(evaluation)
    payload["json_path"] = str(json_path)
    payload["markdown_path"] = str(md_path)
    if json_output:
        typer.echo(json.dumps(payload, indent=2))
        return
    console.print(f"Email clarity: {evaluation['status']} score={evaluation['score']}")
    console.print(f"Issues: {len(evaluation['issues'])}")
    console.print(f"Report: {md_path}")


@research_app.command("execution-board-review")
def research_execution_board_review(
    hourly_dir: Path = typer.Option(
        Path("results/hourly_supervisor"),
        "--hourly-dir",
        help="Directory containing hourly supervisor packets to review.",
    ),
    max_packets: int = typer.Option(
        24,
        "--max-packets",
        min=1,
        max=200,
        help="Maximum recent hourly packets to review.",
    ),
    loss_review_evidence_dir: Path = typer.Option(
        Path("results/loss_review_evidence"),
        "--loss-review-evidence-dir",
        help="Directory containing refreshed loss-review evidence packets.",
    ),
    output_dir: Path = typer.Option(
        Path("results/execution_board"),
        "--output-dir",
        help="Directory for BOARD execution review artifacts.",
    ),
    json_output: bool = typer.Option(False, "--json-output"),
):
    """Write an analysis-only BOARD review of recent intraday execution quality."""
    review = build_execution_board_review(
        hourly_dir=hourly_dir,
        max_packets=max_packets,
        loss_review_evidence_dir=loss_review_evidence_dir,
        decision_ledger_root=CANONICAL_BOARD_LEDGER_ROOT,
        decision_evidence_root=CANONICAL_BOARD_EVIDENCE_ROOT,
    )
    json_path, md_path = write_execution_board_review(review, output_dir)
    payload = dict(review)
    payload["json_path"] = str(json_path)
    payload["markdown_path"] = str(md_path)
    if json_output:
        typer.echo(json.dumps(payload, indent=2))
        return
    console.print(f"BOARD recommendation: {review['recommendation']}")
    console.print(f"Hard issues: {len(review['violations'])}")
    console.print(f"Warnings: {len(review['warnings'])}")
    console.print(f"Report: {md_path}")


@research_app.command("model-telemetry-report")
def research_model_telemetry_report(
    input_dir: Path = typer.Option(
        Path("results/model_telemetry"),
        "--input-dir",
        help="Directory containing model telemetry packets.",
    ),
    output_dir: Path = typer.Option(
        Path("results/model_telemetry_reports"),
        "--output-dir",
        help="Directory for model telemetry reports.",
    ),
    budget_limit_usd: str | None = typer.Option(
        None,
        "--budget-limit-usd",
        help="Optional budget cap to show remaining model spend.",
    ),
    json_output: bool = typer.Option(False, "--json-output"),
):
    """Summarize model route cost, latency, and reliability from local packets."""
    packets = load_model_telemetry_packets(input_dir)
    report = summarize_model_telemetry(
        packets,
        budget_limit_usd=budget_limit_usd,
    )
    report_path = write_model_telemetry_report(report, output_dir)
    report["packet_path"] = str(report_path)
    if json_output:
        typer.echo(json.dumps(report, indent=2))
        return
    console.print(f"Model telemetry packets: {report['packet_count']}")
    console.print(f"Estimated model spend: ${report['estimated_cost_total_usd']}")
    console.print(f"Packet: {report_path}")


@research_app.command("outcome-labeling")
def research_outcome_labeling(
    ledger_path: Path = typer.Option(
        DEFAULT_LEDGER_PATH,
        "--ledger-path",
        help="Agent Intelligence Ledger JSONL path with resolved forecasts.",
    ),
    summary_path: Path = typer.Option(
        DEFAULT_SUMMARY_PATH,
        "--summary-path",
        help="Agent score summary output path.",
    ),
    model_telemetry_dir: Path = typer.Option(
        Path("results/model_telemetry"),
        "--model-telemetry-dir",
        help="Directory containing model telemetry packets to label from ledger refs.",
    ),
    model_telemetry_report_dir: Path = typer.Option(
        Path("results/model_telemetry_reports"),
        "--model-telemetry-report-dir",
        help="Directory for the labeled model telemetry report.",
    ),
    market_mirror_dir: Path = typer.Option(
        Path("results/research_simulations"),
        "--market-mirror-dir",
        help="Directory containing latest market-mirror scenario packet.",
    ),
    json_output: bool = typer.Option(False, "--json-output"),
):
    """Apply resolved outcome labels to advisory model and mirror packets."""
    forecasts = load_ledger(ledger_path)
    summary_path_written = write_summary(forecasts, path=summary_path)
    telemetry_packets = load_model_telemetry_packets(model_telemetry_dir)
    labeled_telemetry = label_model_telemetry_from_agent_outcomes(
        telemetry_packets,
        forecasts,
    )
    telemetry_report = summarize_model_telemetry(labeled_telemetry)
    telemetry_report_path = write_model_telemetry_report(
        telemetry_report,
        model_telemetry_report_dir,
    )
    telemetry_report["packet_path"] = str(telemetry_report_path)

    mirror_summary: dict[str, Any] | None = None
    mirror_latest = market_mirror_dir / "latest.json"
    if mirror_latest.exists():
        mirror_packet = MarketMirrorScenarioPacket.model_validate(
            json.loads(mirror_latest.read_text(encoding="utf-8"))
        )
        labeled_mirror = label_market_mirror_outcome(mirror_packet, forecasts)
        mirror_path = write_research_packet(labeled_mirror, market_mirror_dir)
        mirror_summary = {
            "symbol": labeled_mirror.symbol,
            "scenario_id": labeled_mirror.scenario_id,
            "usefulness_label": labeled_mirror.usefulness_label,
            "outcome_label": labeled_mirror.outcome_label,
            "quality_score": labeled_mirror.quality_score,
            "resolved_forecast_count": labeled_mirror.freshness.get("resolved_forecast_count"),
            "execution_authority": labeled_mirror.freshness.get("execution_authority", "none"),
            "packet_path": str(mirror_path),
        }

    payload = {
        "analysis_only": True,
        "can_submit_orders": False,
        "ledger_path": str(ledger_path),
        "summary_path": str(summary_path_written),
        "forecast_count": len(forecasts),
        "resolved_forecast_count": sum(1 for forecast in forecasts if forecast.resolved),
        "model_telemetry_packet_count": len(telemetry_packets),
        "model_telemetry_report": telemetry_report,
        "market_mirror": mirror_summary,
    }
    if json_output:
        typer.echo(json.dumps(payload, indent=2))
        return
    console.print(f"Forecasts in ledger: {len(forecasts)}")
    console.print(f"Resolved forecasts: {payload['resolved_forecast_count']}")
    console.print(f"Model telemetry report: {telemetry_report_path}")
    if mirror_summary:
        console.print(f"Market mirror label: {mirror_summary['outcome_label']}")


@research_app.command("mirofish-handoff-status")
def research_mirofish_handoff_status(
    scaffold_path: Path = typer.Option(
        Path("reports/mirofish/MIROFISH_PENDING_LEARNING_SCAFFOLD.md"),
        "--scaffold-path",
        help="Repo-local MiroFish pending scaffold path.",
    ),
    final_handoff_path: Path = typer.Option(
        Path("reports/mirofish/MIROFISH_FINAL_TRADINGAGENTS_HANDOFF.md"),
        "--final-handoff-path",
        help="Expected final MiroFish-to-TradingAgents handoff path.",
    ),
    output_dir: Path = typer.Option(
        Path("results/mirofish_handoff"),
        "--output-dir",
        help="Directory for the advisory handoff-status packet.",
    ),
    required_report_id: str | None = typer.Option(
        None,
        "--required-report-id",
        help=(
            "Only treat final-looking handoff files as current if they contain this report id. "
            "Defaults to TRADINGAGENTS_MIROFISH_REQUIRED_REPORT_ID, then the current accepted report id."
        ),
    ),
    json_output: bool = typer.Option(False, "--json-output"),
):
    """Write the current advisory MiroFish external-run handoff status."""
    required_report_id = resolve_required_report_id(required_report_id)
    packet = build_mirofish_handoff_status(
        scaffold_path=scaffold_path,
        final_handoff_path=final_handoff_path,
        required_report_id=required_report_id,
    )
    packet_path = write_research_packet(packet, output_dir)
    compact_payload = build_compact_mirofish_handoff_status(packet, packet_path=packet_path)
    compact_text = json.dumps(compact_payload, indent=2)
    compact_path = packet_path.with_suffix(".compact.json")
    compact_path.write_text(compact_text, encoding="utf-8")
    (output_dir / "latest-compact.json").write_text(compact_text, encoding="utf-8")
    status_signal = next(
        signal for signal in packet.signals if signal.get("type") == "mirofish_handoff_status"
    )
    clean_room = packet.freshness.get("clean_room", {})
    payload = {
        "analysis_only": True,
        "can_submit_orders": False,
        "status": status_signal.get("status"),
        "final_handoff_available": status_signal.get("final_handoff_available"),
        "required_report_id": status_signal.get("required_report_id"),
        "final_handoff_paths": status_signal.get("final_handoff_paths", []),
        "ignored_handoff_paths": status_signal.get("ignored_handoff_paths", []),
        "final_advisory_available": packet.freshness.get("final_advisory_available", False),
        "advisory_valid_window": packet.freshness.get("advisory_valid_window"),
        "advisory_expires_after": packet.freshness.get("advisory_expires_after"),
        "advisory_requires_refresh": packet.freshness.get("advisory_requires_refresh", []),
        "scenario_branch_count": packet.freshness.get("scenario_branch_count", 0),
        "validation_task_count": packet.freshness.get("validation_task_count", 0),
        "false_signal_filter_count": packet.freshness.get("false_signal_filter_count", 0),
        "attention_symbols": packet.freshness.get("attention_symbols", []),
        "forecast_symbols": packet.freshness.get("forecast_symbols", []),
        "execution_authority": packet.freshness.get("execution_authority", "none"),
        "artifact_path_count": packet.freshness.get("artifact_path_count", 0),
        "candidate_artifact_count": packet.freshness.get("candidate_artifact_count", 0),
        "available_artifact_count": packet.freshness.get("available_artifact_count", 0),
        "required_artifact_count": packet.freshness.get("required_artifact_count", 0),
        "missing_piece_count": packet.freshness.get("missing_piece_count", 0),
        "source_artifacts": packet.freshness.get("source_artifacts", {}),
        "review_packet_zip": packet.freshness.get("review_packet_zip"),
        "acceptance_decision_path": packet.freshness.get("acceptance_decision_path"),
        "full_report_highlight_available": packet.freshness.get("full_report_highlight_available", False),
        "full_report_source_path": packet.freshness.get("full_report_source_path"),
        "full_report_core_filter": packet.freshness.get("full_report_core_filter"),
        "full_report_ai_bot_liquidity_available": packet.freshness.get(
            "full_report_ai_bot_liquidity_available",
            False,
        ),
        "full_report_ai_bot_liquidity_summary": packet.freshness.get(
            "full_report_ai_bot_liquidity_summary"
        ),
        "mirofish_advisory_gate_action": packet.freshness.get("mirofish_advisory_gate_action"),
        "mirofish_advisory_triggered_gates": packet.freshness.get(
            "mirofish_advisory_triggered_gates",
            [],
        ),
        "deep_research_review_available": packet.freshness.get(
            "deep_research_review_available",
            False,
        ),
        "deep_research_review_report_id": packet.freshness.get("deep_research_review_report_id"),
        "deep_research_review_source_path": packet.freshness.get(
            "deep_research_review_source_path"
        ),
        "deep_research_review_core_filter": packet.freshness.get(
            "deep_research_review_core_filter"
        ),
        "deep_research_review_market_regime": packet.freshness.get(
            "deep_research_review_market_regime",
            {},
        ),
        "deep_research_review_stock_selection_biases": packet.freshness.get(
            "deep_research_review_stock_selection_biases",
            {},
        ),
        "deep_research_review_selection_rules": packet.freshness.get(
            "deep_research_review_selection_rules",
            [],
        ),
        "deep_research_review_risk_controls": packet.freshness.get(
            "deep_research_review_risk_controls",
            [],
        ),
        "morning_bot_instruction": packet.freshness.get("morning_bot_instruction"),
        "clean_room": clean_room,
        "packet_path": str(packet_path),
    }
    if json_output:
        typer.echo(json.dumps(payload, indent=2))
        return
    console.print(f"MiroFish handoff status: {payload['status']}")
    console.print(f"Execution authority: {payload['execution_authority']}")
    console.print(f"Packet: {packet_path}")


@research_app.command("automation-orchestration-plan")
def research_automation_orchestration_plan(
    candidate_symbols: str = typer.Option(
        "",
        "--candidate-symbols",
        help="Comma-separated symbols the automation is researching.",
    ),
    output_dir: Path = typer.Option(
        Path("results/research_batches"),
        "--output-dir",
        help="Directory for the orchestration batch packet.",
    ),
    model_telemetry_dir: Path = typer.Option(
        Path("results/model_telemetry"),
        "--model-telemetry-dir",
        help="Directory for model route telemetry packets.",
    ),
    research_context_dir: Path = typer.Option(
        Path("results/research_evidence/orchestration_context"),
        "--research-context-dir",
        help="Directory for source/reddit/social/release context packets.",
    ),
    include_research_context: bool = typer.Option(
        True,
        "--include-research-context/--no-research-context",
        help="Write source/social/release context packets for the orchestration plan.",
    ),
    depleted_sources: str = typer.Option(
        "",
        "--depleted-sources",
        help="Comma-separated research sources out of calls for this run.",
    ),
    disabled_sources: str = typer.Option(
        "",
        "--disabled-sources",
        help="Comma-separated research sources to skip for this run.",
    ),
    estimated_judgment_cost_usd: str = typer.Option(
        "0",
        "--estimated-judgment-cost-usd",
        help="Estimated cost for the optional high-judgment model lane.",
    ),
    json_output: bool = typer.Option(False, "--json-output"),
):
    """Write a read-only multi-agent research orchestration plan packet."""
    route_env = _active_model_route_env()
    policy = model_routing_policy_from_env(route_env)
    windows_endpoint = (
        _env_or_none("TRADINGAGENTS_WINDOWS_OLLAMA_URL")
        or _env_or_none("TRADINGAGENTS_LOCAL_OLLAMA_URL")
        or _env_or_none("TRADINGAGENTS_LOCAL_MODEL_URL")
        or _env_or_none("OLLAMA_BASE_URL")
        or _env_or_none("OLLAMA_HOST")
        or (
            DEFAULT_WINDOWS_OLLAMA_URL
            if route_env.get("TRADINGAGENTS_WINDOWS_OLLAMA_URL")
            else None
        )
    )
    mac_endpoint = _env_or_none("TRADINGAGENTS_MAC_OLLAMA_URL") or DEFAULT_MAC_OLLAMA_URL
    route_health: dict[str, dict[str, object]] = {
        "mac_ollama": _ollama_endpoint_health(
            mac_endpoint,
            expected_model=policy.mac_local_model,
        )
    }
    if windows_endpoint:
        route_health["windows_local"] = _ollama_endpoint_health(
            windows_endpoint,
            expected_model=policy.windows_local_model,
        )
    result = build_research_automation_orchestration(
        candidate_symbols=candidate_symbols,
        env=route_env,
        route_health=route_health,
        estimated_judgment_cost_usd=estimated_judgment_cost_usd,
        include_research_context=include_research_context,
        research_context_dir=research_context_dir,
        model_telemetry_dir=model_telemetry_dir,
        batch_output_dir=output_dir,
        depleted_sources=_parse_source_csv(depleted_sources),
        disabled_sources=_parse_source_csv(disabled_sources),
    )
    payload = result.batch_packet.model_dump()
    payload["packet_path"] = str(result.batch_packet_path)
    payload["model_telemetry_paths"] = {
        run_id: str(path)
        for run_id, path in result.model_telemetry_paths.items()
    }
    payload["replay_plan_packet_path"] = (
        str(result.replay_plan_path) if result.replay_plan_path else None
    )
    if json_output:
        typer.echo(json.dumps(payload, indent=2))
        return
    gates = result.batch_packet.quality_gates
    console.print(f"Research orchestration status: {result.batch_packet.status}")
    console.print(
        "Research quality high enough: "
        f"{gates.get('research_quality_high_enough', False)}"
    )
    console.print(f"Model/source lanes: {len(result.batch_packet.orchestration_lanes)}")
    console.print(f"Packet: {result.batch_packet_path}")


@research_app.command("real-simulation-audit")
def research_real_simulation_audit(
    top_symbols: str = typer.Option(
        "",
        "--top-symbols",
        help="Comma-separated symbols for ticker-provider bundle checks. Defaults to NOW,IBM,CRM.",
    ),
    output_dir: Path = typer.Option(
        Path("results/real_simulation_audits"),
        "--output-dir",
        help="Directory for real simulation audit packets.",
    ),
    mac_ollama_url: str = typer.Option(
        "http://macbook-pro.tail37edd7.ts.net:11434/v1",
        "--mac-ollama-url",
        help="Mac Ollama OpenAI-compatible endpoint for helper-lane health and routing.",
    ),
    json_output: bool = typer.Option(False, "--json-output"),
):
    """Run a live-data dry-run simulation across TradingAgents departments."""
    audit = run_real_simulation_audit(
        repo_root=Path("."),
        output_dir=output_dir,
        top_symbols=top_symbols,
        mac_ollama_url=mac_ollama_url,
    )
    if json_output:
        typer.echo(json.dumps(audit, indent=2))
        return
    console.print(f"Real simulation audit: {audit['failed_command_count']} failed commands")
    console.print(f"Submitted order count: {audit['total_submitted_order_count']}")
    console.print(f"Packet: {audit['json_path']}")


@policy_app.command("freeze-live")
def policy_freeze_live(
    reason: str = typer.Option(..., "--reason"),
    control_path: Path = typer.Option(
        Path("results/policy/live_control.json"),
        "--control-path",
        help="Live control state path.",
    ),
    json_output: bool = typer.Option(False, "--json-output"),
):
    """Freeze live trading through the policy control state."""
    written = write_live_control_state(
        control_path,
        frozen=True,
        reason=reason,
        dead_man_expires_at=datetime.datetime.now(tz=datetime.timezone.utc)
        + datetime.timedelta(days=3650),
    )
    payload = {
        "frozen": True,
        "reason": reason,
        "control_path": str(written),
    }
    if json_output:
        print(json.dumps(payload, indent=2))
    else:
        console.print(f"Live trading frozen: {written}")


@policy_app.command("refresh-live-control")
def policy_refresh_live_control(
    reason: str = typer.Option(..., "--reason"),
    ttl_hours: float = typer.Option(6.0, "--ttl-hours"),
    control_path: Path = typer.Option(
        Path("results/policy/live_control.json"),
        "--control-path",
        help="Live control state path.",
    ),
    json_output: bool = typer.Option(False, "--json-output"),
):
    """Refresh the tiny-live dead-man control state without submitting orders."""
    with live_control_lock(control_path):
        existing, existing_issues = load_live_control_state(control_path)
        if (
            existing is None
            or existing_issues
            or existing.get("frozen") is True
            or existing.get("recovery_mode") == "verified_recovery"
        ):
            payload = {
                "refreshed": False,
                "frozen": (
                    existing.get("frozen")
                    if isinstance(existing, dict)
                    else True
                ),
                "reason": (
                    "live control refresh blocked; verified recovery is "
                    "required to unfreeze"
                ),
                "control_path": str(control_path),
            }
            if json_output:
                print(json.dumps(payload, indent=2))
            else:
                console.print(payload["reason"])
            raise typer.Exit(1)
        accepted_preimage_sha256 = hashlib.sha256(
            control_path.read_bytes()
        ).hexdigest()
        expires_at = datetime.datetime.now(
            tz=datetime.timezone.utc
        ) + datetime.timedelta(hours=ttl_hours)
        written = _write_live_control_state_locked(
            control_path,
            frozen=False,
            reason=reason,
            dead_man_expires_at=expires_at,
            expected_preimage_sha256=accepted_preimage_sha256,
        )
    payload = {
        "refreshed": True,
        "frozen": False,
        "reason": reason,
        "dead_man_expires_at": expires_at.isoformat(timespec="seconds"),
        "control_path": str(written),
    }
    if json_output:
        print(json.dumps(payload, indent=2))
    else:
        console.print(f"Live control refreshed until {payload['dead_man_expires_at']}")


@policy_app.command("recover-incident")
def policy_recover_incident(
    incident_path: Path = typer.Option(..., "--incident-path"),
    reconciliation_path: Path = typer.Option(..., "--reconciliation-path"),
    promotion_sync_path: Path = typer.Option(..., "--promotion-sync-path"),
    focused_proof_path: Path = typer.Option(..., "--focused-proof-path"),
    recovery_manifest_path: Path | None = typer.Option(None, "--recovery-manifest-path"),
    repairer_run_id: str = typer.Option(..., "--repairer-run-id"),
    verifier_run_id: str = typer.Option(..., "--verifier-run-id"),
    ttl_minutes: int = typer.Option(90, "--ttl-minutes"),
    control_path: Path = typer.Option(Path("results/policy/live_control.json"), "--control-path"),
    receipt_dir: Path = typer.Option(Path("results/control_plane/rearm"), "--receipt-dir"),
    json_output: bool = typer.Option(False, "--json-output"),
):
    """Re-arm a frozen live-control lease from integrity-verified packets."""
    control_absolute = control_path.resolve()
    accepted_control_preimage_sha256: str | None = None
    control_acceptance_issues: list[str] = []
    with live_control_lock(control_absolute):
        try:
            control_preimage = control_absolute.read_bytes()
        except OSError:
            control_acceptance_issues.append(
                "existing live control is not valid"
            )
        else:
            control_state, control_issues = load_live_control_state(
                control_absolute
            )
            unsafe_control_issues = [
                issue
                for issue in control_issues
                if not issue.startswith("live control state is frozen:")
                and not issue.startswith("dead-man expired at ")
            ]
            if (
                control_state is None
                or control_state.get("frozen") is not True
                or not isinstance(control_state.get("reason"), str)
                or not control_state["reason"].strip()
                or parse_control_time(
                    str(control_state.get("dead_man_expires_at", ""))
                )
                is None
                or unsafe_control_issues
            ):
                control_acceptance_issues.append(
                    "existing live control must be a valid frozen state"
                )
            else:
                accepted_control_preimage_sha256 = hashlib.sha256(
                    control_preimage
                ).hexdigest()

    if accepted_control_preimage_sha256 is None:
        payload: dict[str, Any] = {
            "ready": False,
            "issues": control_acceptance_issues,
            "can_submit_orders": False,
        }
    else:
        evidence, parse_issues = load_recovery_evidence(
            incident_path=incident_path,
            reconciliation_path=reconciliation_path,
            promotion_sync_path=promotion_sync_path,
            focused_proof_path=focused_proof_path,
            recovery_manifest_path=recovery_manifest_path,
            repairer_run_id=repairer_run_id,
            verifier_run_id=verifier_run_id,
        )
        if evidence is None:
            payload = {
                "ready": False,
                "issues": list(parse_issues),
                "can_submit_orders": False,
            }
        else:
            verdict = evaluate_rearm_readiness(evidence)
            if not verdict.ready:
                payload = {
                    "ready": False,
                    "issues": list(verdict.issues),
                    "can_submit_orders": False,
                }
            else:
                try:
                    request_authority = authority_for(
                        ActionClass.REARM_REQUEST
                    )
                    issue_authority = authority_for(ActionClass.REARM_ISSUE)
                    if (
                        request_authority.allowed is not True
                        or request_authority.human_required is not False
                        or request_authority.owner_role
                        != "reliability_controller"
                        or issue_authority.allowed is not True
                        or issue_authority.human_required is not False
                        or issue_authority.owner_role
                        != "integrity_verifier"
                    ):
                        raise ValueError(
                            "rearm authority contract is unavailable"
                        )
                    receipt = rearm_after_verified_recovery(
                        evidence=evidence,
                        control_path=control_path,
                        receipt_dir=receipt_dir,
                        ttl_minutes=ttl_minutes,
                        expected_control_preimage_sha256=(
                            accepted_control_preimage_sha256
                        ),
                    )
                except (OSError, ValueError) as exc:
                    payload = {
                        "ready": False,
                        "issues": [str(exc)],
                        "can_submit_orders": False,
                    }
                else:
                    payload = {
                        "ready": True,
                        "receipt": receipt,
                        "can_submit_orders": False,
                    }
    if json_output:
        print(json.dumps(payload, indent=2, sort_keys=True))
    elif payload["ready"]:
        console.print(f"Verified recovery receipt: {payload['receipt']['receipt_path']}")
    else:
        console.print("Recovery re-arm blocked: " + "; ".join(payload["issues"]))
    if not payload["ready"]:
        raise typer.Exit(1)


@policy_app.command("sync-promotion")
def policy_sync_promotion(
    report_path: Path = typer.Option(
        Path("results/paper_strategy_tournament/latest.json"),
        "--report-path",
        help="Paper tournament report (or packet wrapping latest_report).",
    ),
    state_path: Path = typer.Option(
        Path("results/policy/promotion_state.json"),
        "--state-path",
        help="Promotion state consumed by the unified live gate.",
    ),
    output_state_path: Path | None = typer.Option(
        None,
        "--output-state-path",
        help="Optional staged output; reads --state-path without replacing it.",
    ),
    envelope_path: Path = typer.Option(
        Path("config/risk_envelope.yaml"),
        "--envelope-path",
        help="Risk envelope providing the tiny-live tranche size.",
    ),
    arm_live: bool = typer.Option(
        False,
        "--arm-live/--no-arm-live",
        help="Mark the promoted sleeve live-enabled when every gate passes.",
    ),
    ci_green: bool = typer.Option(
        False,
        "--ci-green/--no-ci-green",
        help="Attest that the focused test suite passed for this working tree.",
    ),
    generated_at: str | None = typer.Option(
        None,
        "--generated-at",
        help=(
            "Optional timezone-aware deterministic tournament-evaluation "
            "time; never controls owner-approval authority time."
        ),
    ),
    json_output: bool = typer.Option(False, "--json-output"),
    owner_approval_path: Path | None = typer.Option(
        None,
        "--owner-approval-path",
        help=(
            "Signed account_owner approval artifact (JSON) bound to this "
            "exact promotion. Required when --arm-live would promote; "
            "verified against the canonical trust root."
        ),
    ),
):
    """Sync live promotion state from paper-tournament evidence.

    Promotes the tournament's live candidate through the deterministic gate
    set and demotes any live-enabled sleeve whose own tournament evidence
    turned negative. Never submits orders; live submission still requires
    the unified go-live guard at submit time.
    """
    from tradingagents.policy.promotion_sync import sync_promotion_state_file

    owner_approval_artifact = None
    if owner_approval_path is not None:
        try:
            parsed = json.loads(owner_approval_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise typer.BadParameter(
                f"owner approval artifact unreadable at {owner_approval_path}: {exc}"
            ) from exc
        if not isinstance(parsed, dict):
            raise typer.BadParameter(
                "owner approval artifact must be a JSON object"
            )
        owner_approval_artifact = parsed

    # Bind exactly the validated regular file: read bytes once, validate,
    # then confirm the bytes did not change during validation so the signed
    # envelope binding cannot differ from what was checked.
    if not envelope_path.is_file():
        raise typer.BadParameter(
            f"risk envelope must be an existing regular file: {envelope_path}"
        )
    try:
        envelope_bytes = envelope_path.read_bytes()
    except OSError as exc:
        raise typer.BadParameter(
            f"risk envelope unreadable at {envelope_path}: {exc}"
        ) from exc
    envelope, envelope_issues = load_risk_envelope(envelope_path)
    if envelope is None:
        raise typer.BadParameter(
            f"risk envelope unusable at {envelope_path}: {'; '.join(envelope_issues)}"
        )
    try:
        confirmed_bytes = envelope_path.read_bytes()
    except OSError as exc:
        raise typer.BadParameter(
            f"risk envelope unreadable at {envelope_path}: {exc}"
        ) from exc
    if confirmed_bytes != envelope_bytes:
        raise typer.BadParameter(
            f"risk envelope changed while being validated: {envelope_path}"
        )
    owner_approval_envelope_ref = str(envelope_path.resolve())
    owner_approval_envelope_sha256 = hashlib.sha256(confirmed_bytes).hexdigest()
    promotion_now = None
    if generated_at is not None:
        try:
            promotion_now = datetime.datetime.fromisoformat(
                generated_at.replace("Z", "+00:00")
            )
        except ValueError:
            raise typer.BadParameter(
                "--generated-at must be a timezone-aware ISO timestamp"
            ) from None
        if promotion_now.tzinfo is None:
            raise typer.BadParameter(
                "--generated-at must be a timezone-aware ISO timestamp"
            )
        promotion_now = promotion_now.astimezone(datetime.timezone.utc)
    tranche = envelope.tiny_live_tranche_usd
    result = sync_promotion_state_file(
        report_path,
        state_path,
        output_state_path=output_state_path,
        tiny_live_tranche_usd=tranche,
        arm_live=arm_live,
        ci_green=ci_green,
        now=promotion_now,
        owner_approval=owner_approval_artifact,
        owner_approval_envelope_ref=owner_approval_envelope_ref,
        owner_approval_envelope_sha256=owner_approval_envelope_sha256,
        risk_envelope_ref=owner_approval_envelope_ref,
    )
    written_state_path = output_state_path or state_path
    payload = {
        "summary": result.summary,
        "promoted": result.promoted,
        "demoted": result.demoted,
        "issues_by_sleeve": result.issues_by_sleeve,
        "state_path": str(written_state_path),
        "canonical_state_path": str(state_path),
        "report_path": str(report_path),
        "arm_live": arm_live,
        "ci_green": ci_green,
        "can_submit_orders": False,
        "execution_authority": "none",
        "state": result.state,
    }
    if json_output:
        print(json.dumps(payload, indent=2))
    else:
        console.print(result.summary)
        for sleeve, sleeve_issues in result.issues_by_sleeve.items():
            for issue in sleeve_issues:
                console.print(f"  {sleeve}: {issue}")


@policy_app.command("readiness-status")
def policy_readiness_status(
    supersession_receipt_path: Path = typer.Option(
        ..., "--supersession-receipt-path", exists=True, readable=True
    ),
    promotion_state_path: Path = typer.Option(
        ..., "--promotion-state-path", exists=True, readable=True
    ),
    live_control_path: Path = typer.Option(
        ..., "--live-control-path", exists=True, readable=True
    ),
    schedule_contract_path: Path = typer.Option(
        ..., "--schedule-contract-path", exists=True, readable=True
    ),
    automation_root: Path = typer.Option(
        ..., "--automation-root", exists=True, file_okay=False, readable=True
    ),
    role_contract_path: Path = typer.Option(
        ..., "--role-contract-path", exists=True, readable=True
    ),
    generated_at: str | None = typer.Option(None, "--generated-at"),
    json_output: bool = typer.Option(False, "--json-output"),
):
    """Read current non-authorizing readiness from verified local evidence."""

    from tradingagents.policy.promotion_sync import build_current_readiness_packet

    try:
        moment = (
            datetime.datetime.now(tz=datetime.timezone.utc)
            if generated_at is None
            else datetime.datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
        )
        packet = build_current_readiness_packet(
            supersession_receipt_path=supersession_receipt_path,
            promotion_state_path=promotion_state_path,
            live_control_path=live_control_path,
            schedule_contract_path=schedule_contract_path,
            automation_root=automation_root,
            role_contract_path=role_contract_path,
            now=moment,
        )
    except (OSError, UnicodeError, ValueError) as exc:
        raise typer.BadParameter(f"readiness evidence rejected: {exc}") from exc
    if json_output:
        typer.echo(json.dumps(packet, indent=2, sort_keys=True))
        return
    console.print(f"Readiness: {packet['readiness_status']}")
    console.print(
        "Analysis-only; this status grants no execution or promotion authority."
    )


@policy_app.command("preregister-sleeve")
def policy_preregister_sleeve(
    sleeve: str = typer.Option(..., "--sleeve"),
    hypothesis: str = typer.Option(..., "--hypothesis"),
    rules_summary: str = typer.Option(..., "--rules-summary"),
    benchmark: str = typer.Option("SPY", "--benchmark"),
    min_sample_size: int = typer.Option(30, "--min-sample-size", min=1),
    capacity_assumption_usd: str = typer.Option("0", "--capacity-assumption-usd"),
    output_path: Path = typer.Option(
        Path("results/policy/preregistrations.jsonl"),
        "--output-path",
        help="Append-only preregistration log path.",
    ),
    json_output: bool = typer.Option(False, "--json-output"),
):
    """Freeze a sleeve hypothesis before promotion evidence is evaluated."""
    record = build_sleeve_preregistration(
        sleeve=sleeve,
        hypothesis=hypothesis,
        rules_summary=rules_summary,
        benchmark=benchmark,
        min_sample_size=min_sample_size,
        capacity_assumption_usd=capacity_assumption_usd,
    )
    append_preregistration(record, output_path)
    payload = {
        **record.__dict__,
        "output_path": str(output_path),
        "can_submit_orders": False,
    }
    if json_output:
        print(json.dumps(payload, indent=2))
    else:
        console.print(f"Preregistered sleeve: {record.sleeve}")
        console.print(f"Registration: {record.registration_id}")


@policy_app.command("pullback-support")
def policy_pullback_support(
    symbol: str = typer.Option(..., "--symbol"),
    current_price: str = typer.Option(..., "--current-price"),
    support_level: str = typer.Option(..., "--support-level"),
    atr: str = typer.Option(..., "--atr"),
    pullback_atr: str = typer.Option(..., "--pullback-atr"),
    above_rising_50d: bool = typer.Option(
        False,
        "--above-rising-50d/--below-rising-50d",
    ),
    above_rising_200d: bool = typer.Option(
        False,
        "--above-rising-200d/--below-rising-200d",
    ),
    sell_volume_state: str = typer.Option(..., "--sell-volume-state"),
    gap_state: str = typer.Option(..., "--gap-state"),
    sector_relative_strength: str = typer.Option(..., "--sector-relative-strength"),
    regime_state: str = typer.Option(..., "--regime-state"),
    earnings_blackout: bool = typer.Option(False, "--earnings-blackout/--no-earnings-blackout"),
    fresh_negative_event: bool = typer.Option(False, "--fresh-negative-event/--no-fresh-negative-event"),
    notional_usd: str = typer.Option("100.00", "--notional-usd"),
    output_dir: Path = typer.Option(
        Path("results/shadow_policy_packets"),
        "--output-dir",
        help="Directory for shadow policy packets.",
    ),
    json_output: bool = typer.Option(False, "--json-output"),
):
    """Evaluate the deterministic pullback-support sleeve and write a paper-only packet."""
    now = datetime.datetime.now(tz=datetime.timezone.utc).isoformat(timespec="seconds")
    current_price_dec = Decimal(current_price)
    support_level_dec = Decimal(support_level)
    atr_dec = Decimal(atr)
    pullback_atr_dec = Decimal(pullback_atr)
    sector_relative_strength_dec = Decimal(sector_relative_strength)
    notional_usd_dec = Decimal(notional_usd)
    features = PullbackFeatures(
        symbol=symbol,
        current_price=current_price_dec,
        support_level=support_level_dec,
        atr=atr_dec,
        pullback_atr=pullback_atr_dec,
        above_rising_50d=above_rising_50d,
        above_rising_200d=above_rising_200d,
        sell_volume_state=sell_volume_state,
        gap_state=gap_state,
        sector_relative_strength=sector_relative_strength_dec,
        regime_state=regime_state,
        earnings_blackout=earnings_blackout,
        fresh_negative_event=fresh_negative_event,
        notional_usd=notional_usd_dec,
    )
    decision = evaluate_pullback_support(features)
    normalized_symbol = symbol.strip().upper()
    packet = build_pullback_support_run_packet(
        features,
        decision=decision,
        run_id=f"pullback-support-{normalized_symbol}-{_default_run_id()}",
        as_of=now,
        source_name="cli:policy pullback-support",
        universe_bucket="manual_cli",
    )
    packet_path = write_shadow_run_packet(packet, output_dir)
    payload = {
        "decision": decision.decision,
        "score": str(decision.score),
        "reasons": decision.reasons,
        "intent": decision.intent.model_dump() if decision.intent else None,
        "packet_path": str(packet_path),
    }
    if json_output:
        print(json.dumps(payload, indent=2))
    else:
        console.print(f"Pullback-support decision: {decision.decision}")
        console.print(f"Packet: {packet_path}")


def _rank_third_candidate() -> tuple[str, Decimal]:
    candidates = ["MSFT", "AMZN", "META", "AAPL", "AVGO", "TSM", "AMD", "ORCL"]
    try:
        import yfinance as yf

        for symbol in candidates:
            history = yf.Ticker(symbol).history(period="5d", interval="1d")
            if history.empty:
                continue
            close = Decimal(str(float(history["Close"].dropna().iloc[-1])))
            return symbol, close.quantize(Decimal("0.01"))
    except Exception as exc:
        raise typer.BadParameter(f"could not rank third candidate from yfinance: {exc}") from exc
    raise typer.BadParameter("could not rank a third candidate from mega-cap tech universe")


def _ticket_orders(
    *,
    premarket: bool,
    third_symbol: str | None,
    third_limit_price: float | None,
) -> list[StrategyOrder]:
    orders = [
        StrategyOrder(
            ticket_id="googl-starter",
            symbol="GOOGL",
            side="buy",
            notional=Decimal("450"),
            limit_price=Decimal("383.50"),
            extended_hours=premarket,
        ),
        StrategyOrder(
            ticket_id="nvda-pullback",
            symbol="NVDA",
            side="buy",
            notional=Decimal("250"),
            limit_price=Decimal("212.25"),
            extended_hours=False,
        ),
    ]
    if third_symbol is None and third_limit_price is None:
        third_symbol, ranked_limit = _rank_third_candidate()
        third_limit_price = float(ranked_limit)
    if third_symbol and third_limit_price is not None:
        orders.append(
            StrategyOrder(
                ticket_id=f"{third_symbol.lower()}-third",
                symbol=third_symbol,
                side="buy",
                notional=Decimal("300"),
                limit_price=Decimal(str(third_limit_price)),
                extended_hours=premarket,
            )
        )
    return orders


def _serialize_pair_result(result) -> dict:
    return {
        "accepted": [
            {
                "ticket_id": pair.paper.ticket_id,
                "paper": pair.paper.order,
                "live": pair.live.order,
                "live_parent_client_order_id": pair.live.parent_client_order_id,
            }
            for pair in result.accepted
        ],
        "rejected": [
            {"ticket_id": issue.ticket_id, "reason": issue.reason}
            for issue in result.rejected
        ],
        "skipped": [
            {"ticket_id": issue.ticket_id, "reason": issue.reason}
            for issue in result.skipped
        ],
    }


def _print_pair_result(result) -> None:
    table = Table(title="Alpaca Paper + Live Mirror Preview")
    table.add_column("Ticket")
    table.add_column("Symbol")
    table.add_column("Paper")
    table.add_column("Live")
    table.add_column("Limit")
    table.add_column("Ext")
    for pair in result.accepted:
        table.add_row(
            pair.paper.ticket_id,
            pair.paper.order["symbol"],
            f"${pair.paper.order['notional']}",
            f"${pair.live.order['notional']}",
            pair.paper.order["limit_price"],
            "yes" if pair.paper.order["extended_hours"] else "no",
        )
    console.print(table)
    for issue in result.rejected:
        console.print(f"[red]Rejected {issue.ticket_id}: {issue.reason}[/red]")
    for issue in result.skipped:
        console.print(f"[yellow]Skipped {issue.ticket_id}: {issue.reason}[/yellow]")


def _alpaca_clients() -> tuple[AlpacaRestClient, AlpacaRestClient]:
    paper_client = AlpacaRestClient(AlpacaSettings.from_env(paper=True))
    live_client = AlpacaRestClient(AlpacaSettings.from_env(paper=False))
    paper_client.assert_expected_mode(paper=True)
    live_client.assert_expected_mode(paper=False)
    return paper_client, live_client


def _alpaca_paper_client() -> AlpacaRestClient:
    paper_client = AlpacaRestClient(AlpacaSettings.from_env(paper=True))
    paper_client.assert_expected_mode(paper=True)
    return paper_client


def _alpaca_live_client() -> AlpacaRestClient:
    live_client = AlpacaRestClient(AlpacaSettings.from_env(paper=False))
    live_client.assert_expected_mode(paper=False)
    return live_client


def _alpaca_policy_now() -> datetime.datetime:
    return datetime.datetime.now(tz=datetime.timezone.utc)


def _skip_simulated_preopen_validation_for_calendar(now: datetime.datetime) -> str | None:
    if now.tzinfo is None:
        now = now.replace(tzinfo=datetime.timezone.utc)
    local = now.astimezone(CENTRAL)
    if local.weekday() == 5:
        return "saturday_no_regular_market_morning"
    return None


def _serialize_paper_result(result) -> dict:
    return {
        "accepted": [
            {
                "ticket_id": planned.ticket_id,
                "paper": planned.order,
            }
            for planned in result.accepted
        ],
        "rejected": [
            {"ticket_id": issue.ticket_id, "reason": issue.reason}
            for issue in result.rejected
        ],
        "skipped": [
            {"ticket_id": issue.ticket_id, "reason": issue.reason}
            for issue in result.skipped
        ],
    }


def _issue_dicts(issues) -> list[dict[str, str]]:
    return [
        {
            "ticket_id": str(issue.ticket_id),
            "reason": str(issue.reason),
        }
        for issue in issues
    ]


def _money_total(values) -> str:
    total = sum((Decimal(str(value)) for value in values), Decimal("0"))
    return str(total.quantize(Decimal("0.01")))


def _paper_submit_spend_summary(planned_orders, failed_issues) -> dict[str, str]:
    failed_tickets = {str(issue.ticket_id) for issue in failed_issues}
    return {
        "paper": _money_total(
            planned.order.get("notional", "0")
            for planned in planned_orders
            if str(planned.ticket_id) not in failed_tickets
        ),
        "live": "0.00",
    }


def _pair_submit_spend_summary(order_pairs, failed_issues) -> dict[str, str]:
    failed_tickets = {str(issue.ticket_id) for issue in failed_issues}
    successful_pairs = [
        pair
        for pair in order_pairs
        if str(pair.paper.ticket_id) not in failed_tickets
        and str(pair.live.ticket_id) not in failed_tickets
    ]
    return {
        "paper": _money_total(pair.paper.order.get("notional", "0") for pair in successful_pairs),
        "live": _money_total(pair.live.order.get("notional", "0") for pair in successful_pairs),
    }


def _manual_submit_packet_base(
    *,
    run_id: str,
    account_mode: str,
    status: str,
    reason: str,
    planned_orders: dict[str, Any],
    account_scope: list[str],
    submitted: list[dict[str, Any]] | None = None,
    failed: list[dict[str, str]] | None = None,
    issues: list[dict[str, str]] | None = None,
    estimated_spent_this_run_by_account: dict[str, str] | None = None,
) -> dict[str, Any]:
    submitted_items = list(submitted or [])
    failed_items = list(failed or [])
    issue_items = list(issues or [])
    spent = estimated_spent_this_run_by_account or {"paper": "0.00", "live": "0.00"}
    if status == "submitted":
        summary = (
            f"The legacy Alpaca submit command sent {len(submitted_items)} order(s). "
            f"Estimated spend this run: paper ${spent.get('paper', '0.00')}, "
            f"live ${spent.get('live', '0.00')}."
        )
    elif status == "blocked":
        summary = (
            "The legacy Alpaca submit command did not submit orders because a safety gate blocked it. "
            "The bot kept money still."
        )
    elif status == "refused":
        summary = (
            "The legacy Alpaca submit command refused to run because required execution settings were not armed. "
            "The bot kept money still."
        )
    elif status == "partial_failure":
        summary = (
            f"The legacy Alpaca submit command sent {len(submitted_items)} order(s), "
            "then stopped after a broker problem. Check failed items before trying again."
        )
    else:
        summary = "The legacy Alpaca submit command ended without a submitted order."
    return {
        "kind": "manual_alpaca_submit",
        "schema_version": "1.0.0",
        "generated_at": datetime.datetime.now(tz=datetime.timezone.utc).isoformat(timespec="seconds"),
        "run_id": run_id,
        "account_mode": account_mode,
        "account_scope": account_scope,
        "status": status,
        "reason": reason,
        "plain_english_summary": summary,
        "planned_orders": planned_orders,
        "submitted": submitted_items,
        "submitted_count": len(submitted_items),
        "failed": failed_items,
        "failed_count": len(failed_items),
        "issues": issue_items,
        "estimated_spent_this_run_by_account": spent,
        "legacy_path": True,
        "packet_policy": {
            "purpose": "receipt_for_manual_legacy_submit_path",
            "live_orders_require_unified_live_gate": True,
        },
    }


def _print_paper_result(result) -> None:
    table = Table(title="Alpaca Paper-Only Preview")
    table.add_column("Ticket")
    table.add_column("Symbol")
    table.add_column("Paper")
    table.add_column("Limit")
    table.add_column("Ext")
    for planned in result.accepted:
        table.add_row(
            planned.ticket_id,
            planned.order["symbol"],
            f"${planned.order['notional']}",
            planned.order["limit_price"],
            "yes" if planned.order["extended_hours"] else "no",
        )
    console.print(table)
    for issue in result.rejected:
        console.print(f"[red]Rejected {issue.ticket_id}: {issue.reason}[/red]")
    for issue in result.skipped:
        console.print(f"[yellow]Skipped {issue.ticket_id}: {issue.reason}[/yellow]")


def _print_hourly_supervisor(decision, packet_path: Path | None = None) -> None:
    table = Table(title="Alpaca Hourly Supervisor")
    table.add_column("Field")
    table.add_column("Value")
    table.add_row("Decision", decision.decision)
    table.add_row("Material", "yes" if decision.material else "no")
    table.add_row("Live Exposure", f"${decision.live_exposure:.2f}")
    live = decision.portfolio.get("live", {}) if decision.portfolio else {}
    if live:
        table.add_row("Live Equity", f"${live.get('equity', '0.00')}")
        table.add_row("Live Buying Power", f"${live.get('buying_power', '0.00')}")
        table.add_row("Live Unrealized P/L", f"${live.get('unrealized_pl', '0.00')}")
    table.add_row("Reason", decision.reason)
    if packet_path:
        table.add_row("Packet", str(packet_path))
    console.print(table)
    for action in decision.actions:
        console.print(
            f"[yellow]{action.action.upper()} {action.symbol}: "
            f"${action.notional:.2f} limit {action.limit_price:.2f} "
            f"because {action.reason}[/yellow]"
        )


def _load_supervisor_packets(log_dir: Path, report_date: datetime.date | None = None) -> list[dict]:
    report_date = report_date or datetime.datetime.now(tz=datetime.timezone.utc).date()
    packets: list[dict] = []
    if not log_dir.exists():
        return packets
    for packet_path in sorted(
        path
        for path in log_dir.glob("hourly-supervisor-*.json")
        if _is_raw_json_packet_path(path)
    ):
        try:
            packet = json.loads(packet_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        generated_at = packet.get("generated_at", "")
        try:
            packet_date = datetime.datetime.fromisoformat(generated_at).date()
        except ValueError:
            continue
        if packet_date == report_date:
            packet["packet_path"] = str(packet_path)
            packets.append(packet)
    return packets


def _latest_supervisor_packets(log_dir: Path, limit: int = 12) -> list[dict]:
    if not log_dir.exists():
        return []
    packets: list[dict] = []
    for packet_path in sorted(
        (
            path
            for path in log_dir.glob("hourly-supervisor-*.json")
            if _is_raw_json_packet_path(path)
        ),
        reverse=True,
    ):
        try:
            packets.append(json.loads(packet_path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
        if len(packets) >= limit:
            break
    return packets


FRESH_INTRADAY_QUOTE_MAX_AGE = datetime.timedelta(minutes=30)


def _yf_symbol_frame(data: Any, symbol: str) -> Any:
    if hasattr(data, "columns"):
        with suppress(Exception):
            if symbol in data.columns.get_level_values(0):
                return data[symbol]
    return data


def _coerce_quote_timestamp(value: Any) -> datetime.datetime | None:
    raw = value.to_pydatetime() if hasattr(value, "to_pydatetime") else value
    if isinstance(raw, datetime.date) and not isinstance(raw, datetime.datetime):
        raw = datetime.datetime.combine(raw, datetime.time.min)
    if not isinstance(raw, datetime.datetime):
        with suppress(ValueError):
            raw = datetime.datetime.fromisoformat(str(value))
    if not isinstance(raw, datetime.datetime):
        return None
    if raw.tzinfo is None:
        raw = raw.replace(tzinfo=datetime.timezone.utc)
    return raw.astimezone(datetime.timezone.utc)


def _latest_nonempty_close(frame: Any) -> tuple[Decimal, datetime.datetime | None] | None:
    if "Close" not in frame:
        return None
    close = frame["Close"].dropna()
    if close.empty:
        return None
    timestamp = _coerce_quote_timestamp(close.index[-1])
    return Decimal(str(float(close.iloc[-1]))), timestamp


def _volume_ratio_from_frame(frame: Any, *, window: int = 20) -> Decimal:
    if "Volume" not in frame:
        return Decimal("1")
    volume = frame["Volume"].dropna()
    if len(volume) <= 1:
        return Decimal("1")
    latest_volume = Decimal(str(float(volume.iloc[-1])))
    avg_volume = Decimal(str(float(volume.iloc[:-1].tail(window).mean())))
    return latest_volume / avg_volume if avg_volume > 0 else Decimal("1")


def _quote_freshness(
    timestamp: datetime.datetime | None,
    now_utc: datetime.datetime,
    *,
    source_name: str,
) -> tuple[bool, bool, str | None]:
    if timestamp is None:
        return False, True, f"latest {source_name} quote has no parseable timestamp"
    quote_age = now_utc - timestamp
    fresh = datetime.timedelta(0) <= quote_age <= FRESH_INTRADAY_QUOTE_MAX_AGE
    return (
        fresh,
        not fresh,
        None if fresh else f"latest {source_name} quote is stale: age {quote_age}",
    )


def _fetch_alpaca_latest_trade_rows(
    symbols: Sequence[str],
    *,
    now_utc: datetime.datetime,
) -> dict[str, dict[str, Any]]:
    with suppress(Exception):
        from tradingagents.dataflows.alpaca_market_data import fetch_alpaca_latest_trades

        packet = fetch_alpaca_latest_trades(symbols)
        payload = getattr(packet, "payload", None)
        if not isinstance(payload, Mapping):
            return {}
        trades = payload.get("trades") if isinstance(payload.get("trades"), Mapping) else payload
        if not isinstance(trades, Mapping):
            return {}
        rows: dict[str, dict[str, Any]] = {}
        for symbol, trade in trades.items():
            if not isinstance(trade, Mapping):
                continue
            price = trade.get("p") or trade.get("price")
            if price in (None, ""):
                continue
            timestamp = _coerce_quote_timestamp(trade.get("t") or trade.get("timestamp"))
            quote_fresh, stale_quote, stale_reason = _quote_freshness(
                timestamp,
                now_utc,
                source_name="Alpaca latest trade",
            )
            rows[str(symbol).upper()] = {
                "current_price": Decimal(str(price)),
                "quote_timestamp": timestamp,
                "quote_fresh": quote_fresh,
                "stale_quote": stale_quote,
                "quote_stale_reason": stale_reason,
                "source": "alpaca_market_data:latest_trade",
                "bar_interval": "latest_trade",
            }
        return rows
    return {}


class AggressiveCandidateMarketDataError(RuntimeError):
    """The shared candidate feed failed before it could return a valid snapshot."""


def _fetch_aggressive_candidate_market_data() -> dict[str, dict]:
    try:
        import yfinance as yf

        tickers = list(AGGRESSIVE_CANDIDATE_UNIVERSE)
        session_label = market_session_label()
        tradeable_session = can_trade_session(session_label)
        now_utc = datetime.datetime.now(tz=datetime.timezone.utc)
        daily_bar_is_trade_fresh = not tradeable_session
        stale_reason = (
            None
            if daily_bar_is_trade_fresh
            else "yfinance 1d close is not a fresh intraday quote during tradeable sessions"
        )
        daily_data = yf.download(
            tickers,
            period="5d",
            interval="1d",
            progress=False,
            group_by="ticker",
            threads=True,
            auto_adjust=False,
        )
        intraday_data = None
        if tradeable_session:
            with suppress(Exception):
                intraday_data = yf.download(
                    tickers,
                    period="1d",
                    interval="5m",
                    progress=False,
                    group_by="ticker",
                    threads=True,
                    auto_adjust=False,
                    prepost=True,
                )
        alpaca_trade_rows = (
            _fetch_alpaca_latest_trade_rows(tickers, now_utc=now_utc)
            if tradeable_session
            else {}
        )
        market_data: dict[str, dict] = {}
        for symbol in tickers:
            try:
                frame = _yf_symbol_frame(daily_data, symbol)
                close = frame["Close"].dropna()
                if close.empty:
                    continue
                current = Decimal(str(float(close.iloc[-1])))
                previous = Decimal(str(float(close.iloc[-2]))) if len(close) > 1 else current
                volume_ratio = _volume_ratio_from_frame(frame, window=4)
                quote_fresh = daily_bar_is_trade_fresh
                quote_stale = not daily_bar_is_trade_fresh
                quote_stale_reason = stale_reason
                quote_timestamp = _coerce_quote_timestamp(close.index[-1])
                bar_interval = "1d"
                source = "yfinance:5d-1d"
                alpaca_row = alpaca_trade_rows.get(symbol.upper())
                if alpaca_row and bool(alpaca_row["quote_fresh"]):
                    current = alpaca_row["current_price"]
                    quote_timestamp = alpaca_row["quote_timestamp"]
                    quote_fresh = bool(alpaca_row["quote_fresh"])
                    quote_stale = bool(alpaca_row["stale_quote"])
                    quote_stale_reason = alpaca_row["quote_stale_reason"]
                    bar_interval = str(alpaca_row["bar_interval"])
                    source = str(alpaca_row["source"])
                elif intraday_data is not None:
                    intraday_frame = _yf_symbol_frame(intraday_data, symbol)
                    latest_intraday = _latest_nonempty_close(intraday_frame)
                    if latest_intraday is not None:
                        intraday_current, intraday_timestamp = latest_intraday
                        current = intraday_current
                        volume_ratio = _volume_ratio_from_frame(intraday_frame, window=20)
                        quote_timestamp = intraday_timestamp
                        bar_interval = "5m"
                        source = "yfinance:1d-5m-prepost"
                        quote_fresh, quote_stale, quote_stale_reason = _quote_freshness(
                            intraday_timestamp,
                            now_utc,
                            source_name="yfinance intraday bar",
                        )
                elif alpaca_row:
                    current = alpaca_row["current_price"]
                    quote_timestamp = alpaca_row["quote_timestamp"]
                    quote_fresh = bool(alpaca_row["quote_fresh"])
                    quote_stale = bool(alpaca_row["stale_quote"])
                    quote_stale_reason = alpaca_row["quote_stale_reason"]
                    bar_interval = str(alpaca_row["bar_interval"])
                    source = str(alpaca_row["source"])
                market_data[symbol] = {
                    "current_price": current,
                    "previous_close": previous,
                    "volume_ratio": volume_ratio,
                    "tradable": True,
                    "quote_fresh": quote_fresh,
                    "stale_quote": quote_stale,
                    "quote_session_label": session_label,
                    "quote_timestamp": quote_timestamp.isoformat() if quote_timestamp else None,
                    "quote_stale_reason": quote_stale_reason,
                    "bar_interval": bar_interval,
                    "source": source,
                }
            except Exception:
                continue
        return market_data
    except Exception as exc:
        raise AggressiveCandidateMarketDataError(
            f"aggressive candidate market data provider failed: {exc}"
        ) from exc


def _fetch_aggressive_candidate_market_data_result(
) -> tuple[dict[str, dict], dict[str, str]]:
    """Preserve valid empty snapshots while making transport failure explicit."""

    try:
        return _fetch_aggressive_candidate_market_data(), {}
    except Exception as exc:  # noqa: BLE001 - callers must persist the failure channel.
        return {}, {
            "market_data": (
                "aggressive candidate market data refresh failed: "
                f"{_compact_cli_error_reason(exc)}"
            )
        }


def _apply_mirofish_market_priors_to_market_data(
    market_data: Mapping[str, Mapping],
    research_context: Mapping | None,
) -> dict[str, dict]:
    """Attach advisory MiroFish/report-33 flags to market rows for scoring.

    This does not create trade authority. It only marks rows so the deterministic
    candidate scorer can downrank unconfirmed bot-copycat and crowded-AI-beta
    setups during macro-dominant windows.
    """

    enriched: dict[str, dict] = {
        str(symbol).upper(): dict(data)
        for symbol, data in market_data.items()
        if isinstance(data, Mapping)
    }
    if not isinstance(research_context, Mapping):
        return enriched

    mirofish = research_context.get("mirofish_handoff") or research_context.get("mirofish") or {}
    if not isinstance(mirofish, Mapping):
        mirofish = {}
    watchlists = research_context.get("watchlists") or {}
    release_calendar = watchlists.get("release_calendar") if isinstance(watchlists, Mapping) else {}
    planner_flags = (
        release_calendar.get("planner_flags")
        if isinstance(release_calendar, Mapping)
        else {}
    ) or {}

    market_regime = mirofish.get("deep_research_review_market_regime") or {}
    stock_biases = mirofish.get("deep_research_review_stock_selection_biases") or {}
    negative_biases = [
        str(item).lower()
        for item in stock_biases.get("negative_bias", [])
        if item is not None
    ] if isinstance(stock_biases, Mapping) else []
    macro_event_risk = bool(planner_flags.get("macro_event_risk")) or (
        "macro" in str(market_regime.get("primary_driver", "")).lower()
        if isinstance(market_regime, Mapping)
        else False
    )
    crowded_ai_bias_active = any(
        token in bias
        for bias in negative_biases
        for token in ("semiconductor", "soxx", "smh", "nasdaq", "qqq", "crowded_ai")
    )
    positive_biases = [
        str(item).lower()
        for item in stock_biases.get("positive_bias", [])
        if item is not None
    ] if isinstance(stock_biases, Mapping) else []
    positive_relative_bias_active = any(
        token in bias
        for bias in positive_biases
        for token in ("dow", "dia", "quality", "energy", "defensive")
    )
    event_watch_biases = [
        str(item).lower()
        for item in stock_biases.get("event_sensitive_watch", [])
        if item is not None
    ] if isinstance(stock_biases, Mapping) else []
    event_sensitive_watch_active = bool(event_watch_biases)
    gate_action = str(mirofish.get("mirofish_advisory_gate_action") or "").lower()
    triggered_gates = {
        str(item).lower()
        for item in (mirofish.get("mirofish_advisory_triggered_gates") or [])
        if item is not None
    }
    false_signal_suppression_active = gate_action in {"flag", "suppress"} and bool(
        triggered_gates
        & {"broker_friction", "macro_override", "bot_convergence", "attribution_error"}
    )

    attention_map = mirofish.get("ticker_attention_map") or {}
    attention_symbols: set[str] = set()
    if isinstance(attention_map, Mapping):
        for symbol, details in attention_map.items():
            category = ""
            if isinstance(details, Mapping):
                category = str(details.get("category") or details.get("hypothesis") or "").lower()
            if any(token in category for token in ("bot", "copycat", "retail")):
                attention_symbols.add(str(symbol).upper())
    for hypothesis in mirofish.get("retail_flow_hypotheses", []) if isinstance(mirofish, Mapping) else []:
        if not isinstance(hypothesis, Mapping):
            continue
        for symbol in hypothesis.get("symbols") or []:
            attention_symbols.add(str(symbol).upper())

    for symbol, row in enriched.items():
        tags = list(row.get("mirofish_prior_tags") or [])
        if macro_event_risk:
            row["macro_event_risk"] = True
            if "macro_event_risk" not in tags:
                tags.append("macro_event_risk")
        if symbol in attention_symbols:
            row["bot_copycat_attention"] = True
            if "mirofish_bot_correlation" not in tags:
                tags.append("mirofish_bot_correlation")
        if crowded_ai_bias_active and symbol in CROWDED_AI_BETA_SYMBOLS:
            row["ai_beta_crowding_risk"] = True
            if "deep_research_crowded_ai_beta" not in tags:
                tags.append("deep_research_crowded_ai_beta")
        if positive_relative_bias_active and symbol in DEEP_RESEARCH_POSITIVE_RELATIVE_SYMBOLS:
            row["deep_research_positive_relative_bias"] = True
            if "deep_research_positive_relative_bias" not in tags:
                tags.append("deep_research_positive_relative_bias")
        if event_sensitive_watch_active and symbol in DEEP_RESEARCH_EVENT_SENSITIVE_SYMBOLS:
            row["deep_research_event_sensitive_watch"] = True
            if "deep_research_event_sensitive_watch" not in tags:
                tags.append("deep_research_event_sensitive_watch")
        if false_signal_suppression_active and (
            symbol in attention_symbols
            or bool(row.get("ai_beta_crowding_risk"))
            or bool(row.get("deep_research_event_sensitive_watch"))
        ):
            row["mirofish_false_signal_suppression"] = True
            row["mirofish_advisory_gate_action"] = gate_action
            row["mirofish_triggered_advisory_gates"] = sorted(triggered_gates)
            if "mirofish_false_signal_suppression" not in tags:
                tags.append("mirofish_false_signal_suppression")
        if tags:
            row["mirofish_prior_tags"] = tags
    return enriched


def _default_watchlist_paths() -> list[Path]:
    return [
        Path("watchlist.txt"),
        Path("config") / "watchlist.txt",
        Path("results") / "watchlist.txt",
    ]


def _load_recent_market_packet_paths(
    roots: list[Path] | None = None,
    *,
    limit: int = 20,
) -> list[Path]:
    roots = roots or [
        Path("results") / "market_verification",
        Path("results") / "hourly_supervisor",
        Path("results") / "strategy",
    ]
    packets: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        packets.extend(
            path
            for path in root.glob("*")
            if path.is_file() and path.suffix.lower() in {".md", ".json", ".txt"}
        )
    return sorted(packets, key=lambda path: path.stat().st_mtime, reverse=True)[:limit]


def _is_tradable_stock(client, symbol: str) -> tuple[bool, str]:
    try:
        asset = client.get_asset(symbol)
    except Exception as exc:
        return False, str(exc)
    asset_class = str(asset.get("class") or asset.get("asset_class") or "").lower()
    status = str(asset.get("status") or "").lower()
    tradable = bool(asset.get("tradable"))
    if tradable and asset_class in {"us_equity", "stock"} and status in {"active", ""}:
        return True, "tradable stock"
    return False, f"not tradable stock: class={asset_class or 'unknown'} status={status or 'unknown'} tradable={tradable}"


def _score_overnight_rating(rating: str) -> Decimal:
    score_map = {
        "Buy": Decimal("0.90"),
        "Overweight": Decimal("0.75"),
        "Hold": Decimal("0.50"),
        "Underweight": Decimal("0.30"),
        "Sell": Decimal("0.10"),
    }
    return score_map.get(rating, Decimal("0.50"))


class OvernightGraphIncompleteAnalysis(RuntimeError):
    """Raised when a graph returns without its required final analysis."""


def _require_complete_overnight_graph_state(
    final_state: Mapping,
    *,
    selected_analysts: list[str],
) -> None:
    if not isinstance(final_state, Mapping):
        raise OvernightGraphIncompleteAnalysis(
            "overnight_graph_incomplete_analysis missing=graph_state"
        )
    report_fields = {
        "market": "market_report",
        "social": "sentiment_report",
        "news": "news_report",
        "fundamentals": "fundamentals_report",
    }
    incomplete_markers = {
        "INCOMPLETE_TOOL_CALL_LOOP",
        "EMPTY_ANALYST_RESPONSE",
    }
    incomplete = []
    for analyst in selected_analysts:
        field = report_fields.get(analyst)
        if field is None:
            continue
        report = final_state.get(field)
        if not isinstance(report, str) or not report.strip() or any(
            marker in report for marker in incomplete_markers
        ):
            incomplete.append(analyst)
    final_decision = final_state.get("final_trade_decision")
    if not isinstance(final_decision, str) or not final_decision.strip():
        incomplete.append("portfolio_decision")
    if incomplete:
        raise OvernightGraphIncompleteAnalysis(
            "overnight_graph_incomplete_analysis missing="
            + ",".join(sorted(set(incomplete)))
        )


def _run_overnight_ticker_analysis(
    symbol: str,
    trade_date: str,
    output_dir: Path,
    graph_config_overrides: dict | None = None,
) -> dict:
    config = DEFAULT_CONFIG.copy()
    config["results_dir"] = str(output_dir / "agent_runs")
    overrides = dict(graph_config_overrides or {})
    selected_analysts = overrides.pop(
        "_selected_analysts",
        ["market", "social", "news", "fundamentals"],
    )
    if overrides:
        config.update(overrides)
    graph = TradingAgentsGraph(
        selected_analysts,
        config=config,
        debug=False,
    )
    final_state, signal = graph.propagate(symbol, trade_date, asset_type="stock")
    _require_complete_overnight_graph_state(
        final_state,
        selected_analysts=list(selected_analysts),
    )
    final_decision = str(final_state.get("final_trade_decision", ""))
    rating = parse_rating(final_decision or str(signal), default="Hold")
    creator_packet = write_creator_workflow_artifacts(
        final_state,
        symbol=symbol,
        trade_date=trade_date,
        output_root=Path(config["results_dir"]),
        rating=rating,
        signal=str(signal),
    )
    return {
        "symbol": symbol.upper(),
        "status": "ok",
        "method": "original_tradingagents_graph",
        "rating": rating,
        "score": str(_score_overnight_rating(rating)),
        "signal": str(signal),
        "final_trade_decision": final_decision,
        "investment_plan": final_state.get("investment_plan", ""),
        "trader_investment_plan": final_state.get("trader_investment_plan", ""),
        "reports": {
            "market": final_state.get("market_report", ""),
            "sentiment": final_state.get("sentiment_report", ""),
            "news": final_state.get("news_report", ""),
            "fundamentals": final_state.get("fundamentals_report", ""),
        },
        "creator_workflow": {
            "packet_path": creator_packet["packet_path"],
            "complete_report_path": creator_packet["complete_report_path"],
            "role_count": creator_packet["role_count"],
            "execution_authority": "none",
        },
    }


def _overnight_ticker_process_main(
    queue,
    symbol: str,
    trade_date: str,
    output_dir: str,
    graph_config_overrides: dict | None,
) -> None:
    try:
        queue.put(
            {
                "ok": True,
                "result": _run_overnight_ticker_analysis(
                    symbol,
                    trade_date,
                    Path(output_dir),
                    graph_config_overrides=graph_config_overrides,
                ),
            }
        )
    except BaseException as exc:
        queue.put(
            {
                "ok": False,
                "error": str(exc),
                "error_type": type(exc).__name__,
                "stage": "ticker_graph",
            }
        )
    finally:
        with suppress(Exception):
            queue.close()


def _overnight_worker_message_result(symbol: str, message: dict) -> dict:
    if message.get("ok"):
        return message["result"]
    return {
        "symbol": symbol.upper(),
        "status": "failed",
        "error": message.get("error", "unknown ticker worker failure"),
        "error_type": message.get("error_type", "UnknownTickerWorkerFailure"),
        "error_stage": message.get("stage", "ticker_graph"),
        "score": "0.00",
        "rating": "Hold",
    }


def _close_overnight_worker_queue(queue) -> None:
    with suppress(Exception):
        queue.close()
    with suppress(Exception):
        queue.join_thread()


def _terminate_overnight_process_tree(process, *, wait_seconds: float = 5) -> None:
    pid = getattr(process, "pid", None)
    if os.name == "nt" and pid:
        with suppress(Exception):
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=wait_seconds,
            )
    try:
        if process.is_alive():
            process.terminate()
    except Exception:
        pass
    with suppress(Exception):
        process.join(wait_seconds)
    try:
        if process.is_alive() and hasattr(process, "kill"):
            process.kill()
            process.join(wait_seconds)
    except Exception:
        pass


def _wait_for_overnight_worker_result(
    *,
    symbol: str,
    process,
    queue,
    timeout_seconds: float,
) -> dict:
    deadline = time.monotonic() + timeout_seconds
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            _terminate_overnight_process_tree(process)
            _close_overnight_worker_queue(queue)
            return {
                "symbol": symbol.upper(),
                "status": "failed",
                "error": f"Timed out after {timeout_seconds:.0f} seconds",
                "error_type": "TickerWorkerTimeout",
                "error_stage": "ticker_graph",
                "score": "0.00",
                "rating": "Hold",
            }
        try:
            message = queue.get(timeout=min(0.25, max(0.01, remaining)))
        except queue_module.Empty:
            if process.is_alive():
                continue
            process.join(5)
            try:
                message = queue.get_nowait()
            except queue_module.Empty:
                _terminate_overnight_process_tree(process)
                _close_overnight_worker_queue(queue)
                return {
                    "symbol": symbol.upper(),
                    "status": "failed",
                    "error": f"Ticker worker exited without a result; exitcode={process.exitcode}",
                    "error_type": "TickerWorkerExited",
                    "error_stage": "ticker_graph",
                    "score": "0.00",
                    "rating": "Hold",
                }
        process.join(5)
        if process.is_alive():
            _terminate_overnight_process_tree(process)
        _close_overnight_worker_queue(queue)
        return _overnight_worker_message_result(symbol, message)


def _run_overnight_ticker_analysis_guarded(
    *,
    symbol: str,
    trade_date: str,
    output_dir: Path,
    timeout_seconds: float,
    graph_config_overrides: dict | None = None,
) -> dict:
    if timeout_seconds <= 0:
        try:
            return _run_overnight_ticker_analysis(
                symbol,
                trade_date,
                output_dir,
                graph_config_overrides=graph_config_overrides,
            )
        except Exception as exc:
            return {
                "symbol": symbol.upper(),
                "status": "failed",
                "error": str(exc),
                "error_type": type(exc).__name__,
                "error_stage": "ticker_graph",
                "score": "0.00",
                "rating": "Hold",
            }

    ctx = multiprocessing.get_context("spawn")
    queue = ctx.Queue()
    process = ctx.Process(
        target=_overnight_ticker_process_main,
        args=(queue, symbol, trade_date, str(output_dir), graph_config_overrides),
    )
    process.start()
    return _wait_for_overnight_worker_result(
        symbol=symbol,
        process=process,
        queue=queue,
        timeout_seconds=timeout_seconds,
    )


def _is_bounded_prefetch_retry_candidate(
    graph_result: Mapping,
    graph_config_overrides: Mapping,
) -> bool:
    return (
        graph_result.get("error_type") == "AnalystToolRoundLimitExceeded"
        and not graph_config_overrides.get("tool_free_analysts")
    )


def _env_or_none(name: str) -> str | None:
    value = os.environ.get(name)
    if value:
        return value
    if os.name == "nt":
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
                value, _ = winreg.QueryValueEx(key, name)
                return value or None
        except OSError:
            return None
    return None


def _active_model_route_env() -> dict[str, str]:
    env = dict(os.environ)
    for name in (
        *WINDOWS_OLLAMA_ENV_NAMES,
        *MAC_OLLAMA_ENV_NAMES,
        "TRADINGAGENTS_WINDOWS_RESEARCH_MODEL",
        "TRADINGAGENTS_LOCAL_RESEARCH_MODEL",
        "TRADINGAGENTS_MAC_RESEARCH_MODEL",
    ):
        value = _env_or_none(name)
        if value:
            env[name] = value
    if not any(str(env.get(name, "")).strip() for name in WINDOWS_OLLAMA_ENV_NAMES):
        env.update(_autodetected_windows_ollama_env(env))
    return env


def _autodetected_windows_ollama_env(env: Mapping[str, str]) -> dict[str, str]:
    """Return local Windows Ollama route overrides when the default endpoint is healthy."""
    policy = model_routing_policy_from_env(env)
    health = _ollama_endpoint_health(
        DEFAULT_WINDOWS_OLLAMA_URL,
        expected_model=policy.windows_local_model,
    )
    if not bool(health.get("reachable")):
        return {}
    models = [
        str(model).strip()
        for model in health.get("models", [])
        if str(model).strip()
    ]
    overrides = {"TRADINGAGENTS_WINDOWS_OLLAMA_URL": DEFAULT_WINDOWS_OLLAMA_URL}
    has_explicit_model = bool(
        str(env.get("TRADINGAGENTS_WINDOWS_RESEARCH_MODEL", "")).strip()
        or str(env.get("TRADINGAGENTS_LOCAL_RESEARCH_MODEL", "")).strip()
    )
    if not has_explicit_model and models and policy.windows_local_model not in models:
        overrides["TRADINGAGENTS_WINDOWS_RESEARCH_MODEL"] = models[0]
    return overrides


def _normalize_ollama_openai_base_url(endpoint: str) -> str:
    base = str(endpoint or "").strip().rstrip("/")
    if base.endswith("/api/tags"):
        base = base[: -len("/api/tags")]
    elif base.endswith("/api"):
        base = base[: -len("/api")]
    if base and not base.endswith("/v1"):
        base = f"{base}/v1"
    return base


def _ollama_tags_url(endpoint: str) -> str:
    base = str(endpoint or "").strip().rstrip("/")
    if base.endswith("/api/tags"):
        return base
    if base.endswith("/v1"):
        base = base[: -len("/v1")]
    if base.endswith("/api"):
        return f"{base}/tags"
    return f"{base}/api/tags"


def _overnight_ollama_probe_timeout_seconds() -> float:
    raw = _env_or_none("TRADINGAGENTS_OVERNIGHT_OLLAMA_PROBE_TIMEOUT_SECONDS")
    if not raw:
        return 3.0
    try:
        return max(0.25, min(float(raw), 15.0))
    except ValueError:
        return 3.0


def _ollama_endpoint_healthy(endpoint: str) -> bool:
    try:
        with urllib.request.urlopen(
            _ollama_tags_url(endpoint),
            timeout=_overnight_ollama_probe_timeout_seconds(),
        ) as response:
            return 200 <= int(getattr(response, "status", 200)) < 400
    except Exception:
        return False


def _ollama_endpoint_health(endpoint: str, *, expected_model: str | None = None) -> dict[str, object]:
    tags_url = _ollama_tags_url(endpoint)
    try:
        with urllib.request.urlopen(
            tags_url,
            timeout=_overnight_ollama_probe_timeout_seconds(),
        ) as response:
            status = int(getattr(response, "status", 200))
            raw = response.read().decode("utf-8", errors="replace")
    except Exception as exc:  # noqa: BLE001 - health probe must fail closed with evidence.
        return {
            "endpoint_url": endpoint,
            "tags_url": tags_url,
            "reachable": False,
            "expected_model": expected_model,
            "models": [],
            "error": _compact_cli_error_reason(exc),
        }
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        payload = {}
    models = [
        str(item.get("name") or item.get("model") or "").strip()
        for item in (payload.get("models") if isinstance(payload, dict) else []) or []
        if isinstance(item, dict) and str(item.get("name") or item.get("model") or "").strip()
    ]
    return {
        "endpoint_url": endpoint,
        "tags_url": tags_url,
        "reachable": 200 <= status < 400,
        "http_status": status,
        "expected_model": expected_model,
        "model_present": expected_model in models if expected_model else None,
        "models": models[:25],
    }


def _looks_like_ollama_backend(provider: str | None, endpoint: str | None) -> bool:
    normalized_provider = str(provider or "").strip().lower()
    if normalized_provider == "ollama":
        return True
    lowered = str(endpoint or "").strip().lower()
    return bool(lowered) and (
        ":11434" in lowered
        or "ollama" in lowered
        or "localhost" in lowered
        or "127.0.0.1" in lowered
        or "tail37edd7.ts.net" in lowered
    )


def _is_explicit_non_ollama_overnight_provider(provider: str | None) -> bool:
    normalized_provider = str(provider or "").strip().lower()
    return bool(normalized_provider) and normalized_provider != "ollama"


def _auto_overnight_local_model_overrides() -> dict[str, str]:
    env = _active_model_route_env()
    policy = model_routing_policy_from_env(env)
    def _probed_endpoint_health(endpoint: str | None) -> dict[str, object] | None:
        # Route selectors fail closed ("blocked") when no tags health probe is
        # supplied, so probe the candidate endpoint first and pass the evidence in.
        if not endpoint:
            return None
        return {"reachable": _ollama_endpoint_healthy(endpoint), "models": []}

    windows_route = select_windows_local_model_route(env=env, policy=policy)
    windows_route = select_windows_local_model_route(
        env=env,
        policy=policy,
        endpoint_health=_probed_endpoint_health(windows_route.endpoint_url),
    )
    if windows_route.status == "selected" and windows_route.endpoint_url:
        endpoint = _normalize_ollama_openai_base_url(windows_route.endpoint_url)
        return {
            "llm_provider": "ollama",
            "quick_think_llm": windows_route.model,
            "deep_think_llm": windows_route.model,
            "backend_url": endpoint,
            "overnight_model_route": windows_route.route,
        }
    mac_route = select_mac_ollama_model_route(env=env, policy=policy)
    mac_route = select_mac_ollama_model_route(
        env=env,
        policy=policy,
        endpoint_health=_probed_endpoint_health(mac_route.endpoint_url),
    )
    if mac_route.status == "selected" and mac_route.endpoint_url:
        return {
            "overnight_model_route": "deterministic_fallback_with_mac_helper",
            "overnight_helper_route": mac_route.route,
            "overnight_helper_model": mac_route.model,
            "overnight_helper_backend_url": _normalize_ollama_openai_base_url(
                mac_route.endpoint_url
            ),
            "overnight_graph_disabled_reason": (
                "Windows Ollama graph backend is unavailable; Mac DeepSeek is reachable "
                "but reserved for source triage, stale-source summaries, contradiction "
                "hunting, draft cleanup, and compression. Full graph is skipped so the "
                "overnight run does not burn time on a helper lane."
            ),
        }
    return {
        "overnight_model_route": "deterministic_fallback_no_healthy_local_graph_backend",
        "overnight_graph_disabled_reason": (
            "No healthy local graph-capable Ollama backend was reachable; overnight "
            "planning used deterministic market-snapshot fallbacks."
        ),
    }


def _build_overnight_graph_config_overrides(
    *,
    graph_profile: str,
    llm_provider: str | None,
    quick_think_llm: str | None,
    deep_think_llm: str | None,
    backend_url: str | None,
    max_completion_tokens: int | None,
    llm_timeout_seconds: float | None = None,
    llm_max_retries: int | None = None,
) -> dict:
    overrides: dict = _overnight_graph_profile_overrides(graph_profile)
    env_values = {
        "llm_provider": _env_or_none("TRADINGAGENTS_OVERNIGHT_LLM_PROVIDER"),
        "quick_think_llm": _env_or_none("TRADINGAGENTS_OVERNIGHT_QUICK_THINK_LLM"),
        "deep_think_llm": _env_or_none("TRADINGAGENTS_OVERNIGHT_DEEP_THINK_LLM"),
        "backend_url": _env_or_none("TRADINGAGENTS_OVERNIGHT_LLM_BACKEND_URL"),
    }
    values = {
        "llm_provider": llm_provider or env_values["llm_provider"],
        "quick_think_llm": quick_think_llm or env_values["quick_think_llm"],
        "deep_think_llm": deep_think_llm or env_values["deep_think_llm"],
        "backend_url": backend_url or env_values["backend_url"],
    }
    explicit_non_ollama_provider = _is_explicit_non_ollama_overnight_provider(
        values.get("llm_provider")
    )
    explicit_backend = bool(backend_url)
    backend_from_env = bool(env_values["backend_url"]) and not explicit_backend
    if (
        not explicit_backend
        and not explicit_non_ollama_provider
        and backend_from_env
        and _looks_like_ollama_backend(values.get("llm_provider"), values.get("backend_url"))
        and not _ollama_endpoint_healthy(str(values["backend_url"]))
    ):
        values = {}
    if (
        not explicit_backend
        and not explicit_non_ollama_provider
        and not values.get("backend_url")
    ):
        values.update(_auto_overnight_local_model_overrides())
    if explicit_non_ollama_provider and not values.get("overnight_model_route"):
        values["overnight_model_route"] = (
            f"explicit_{str(values['llm_provider']).strip().lower()}_overnight_graph"
        )
    filtered_values = {key: value for key, value in values.items() if value}
    if explicit_non_ollama_provider and not values.get("backend_url"):
        filtered_values["backend_url"] = None
    overrides.update(filtered_values)
    token_value = max_completion_tokens
    if token_value is None:
        env_tokens = _env_or_none("TRADINGAGENTS_OVERNIGHT_MAX_COMPLETION_TOKENS")
        token_value = int(env_tokens) if env_tokens else None
    if token_value is not None:
        overrides["llm_max_output_tokens"] = token_value
        overrides["ollama_max_completion_tokens"] = token_value
    timeout_value = llm_timeout_seconds
    if timeout_value is None:
        env_timeout = _env_or_none("TRADINGAGENTS_OVERNIGHT_LLM_TIMEOUT_SECONDS")
        timeout_value = float(env_timeout) if env_timeout else None
    if timeout_value is not None:
        overrides["llm_timeout_seconds"] = timeout_value
    retry_value = llm_max_retries
    if retry_value is None:
        env_retries = _env_or_none("TRADINGAGENTS_OVERNIGHT_LLM_MAX_RETRIES")
        retry_value = int(env_retries) if env_retries else None
    if retry_value is not None:
        overrides["llm_max_retries"] = retry_value
    return overrides


def _overnight_graph_profile_overrides(graph_profile: str) -> dict:
    normalized = (graph_profile or "full").strip().lower()
    if normalized == "full":
        return {
            "overnight_graph_profile": "full",
            "_selected_analysts": ["market", "social", "news", "fundamentals"],
            "max_analyst_tool_rounds": 8,
        }
    if normalized == "compact":
        return {
            "overnight_graph_profile": "compact",
            "_selected_analysts": ["market", "social", "news", "fundamentals"],
            "tool_free_analysts": ["market", "social", "news", "fundamentals"],
            "analyst_concurrency_limit": 2,
            "max_debate_rounds": 0,
            "max_risk_discuss_rounds": 0,
            "max_recur_limit": 100,
            "news_article_limit": 5,
            "global_news_article_limit": 3,
            "global_news_lookback_days": 3,
            "global_news_queries": [
                "Federal Reserve interest rates inflation",
                "S&P 500 Nasdaq earnings AI stocks",
                "geopolitical risk oil commodities",
            ],
        }
    if normalized == "market-news":
        return {
            "overnight_graph_profile": "market-news",
            "_selected_analysts": ["market", "social", "news"],
            "tool_free_analysts": ["market", "social", "news"],
            "analyst_concurrency_limit": 2,
            "max_debate_rounds": 0,
            "max_risk_discuss_rounds": 0,
            "max_recur_limit": 100,
            "news_article_limit": 5,
            "global_news_article_limit": 3,
            "global_news_lookback_days": 3,
            "global_news_queries": [
                "Federal Reserve interest rates inflation",
                "S&P 500 Nasdaq earnings AI stocks",
                "geopolitical risk oil commodities",
            ],
        }
    if normalized == "market-only":
        return {
            "overnight_graph_profile": "market-only",
            "_selected_analysts": ["market"],
            "tool_free_analysts": ["market"],
            "max_debate_rounds": 0,
            "max_risk_discuss_rounds": 0,
            "max_recur_limit": 100,
        }
    raise typer.BadParameter(
        "overnight graph profile must be one of: full, compact, market-news, market-only"
    )


def _sanitize_overnight_graph_config(overrides: dict) -> dict:
    graph_disabled = bool(overrides.get("overnight_graph_disabled_reason"))
    provider = "none" if graph_disabled else overrides.get("llm_provider", DEFAULT_CONFIG.get("llm_provider"))
    quick_model = "none" if graph_disabled else overrides.get("quick_think_llm", DEFAULT_CONFIG.get("quick_think_llm"))
    deep_model = "none" if graph_disabled else overrides.get("deep_think_llm", DEFAULT_CONFIG.get("deep_think_llm"))
    helper_model = overrides.get("overnight_helper_model")
    helper_provider = "ollama" if helper_model else "none"
    return {
        "graph_profile": overrides.get("overnight_graph_profile", "full"),
        "selected_analysts": overrides.get(
            "_selected_analysts",
            ["market", "social", "news", "fundamentals"],
        ),
        "tool_free_analysts": overrides.get("tool_free_analysts", []),
        "llm_provider": provider,
        "quick_think_llm": quick_model,
        "deep_think_llm": deep_model,
        "quick_context_window_tokens": get_model_context_window_tokens(provider, quick_model),
        "deep_context_window_tokens": get_model_context_window_tokens(provider, deep_model),
        "backend_url": None if graph_disabled else overrides.get("backend_url", DEFAULT_CONFIG.get("backend_url")),
        "model_route": overrides.get("overnight_model_route"),
        "helper_route": overrides.get("overnight_helper_route"),
        "helper_model": helper_model,
        "helper_context_window_tokens": get_model_context_window_tokens(helper_provider, helper_model)
        if helper_model
        else None,
        "helper_backend_url": overrides.get("overnight_helper_backend_url"),
        "llm_timeout_seconds": overrides.get(
            "llm_timeout_seconds",
            DEFAULT_CONFIG.get("llm_timeout_seconds"),
        ),
        "llm_max_retries": overrides.get(
            "llm_max_retries",
            DEFAULT_CONFIG.get("llm_max_retries"),
        ),
        "max_output_tokens": overrides.get(
            "llm_max_output_tokens",
            DEFAULT_CONFIG.get("llm_max_output_tokens"),
        ),
        "max_completion_tokens": overrides.get(
            "ollama_max_completion_tokens",
            overrides.get(
                "llm_max_output_tokens",
                DEFAULT_CONFIG.get("ollama_max_completion_tokens"),
            ),
        ),
        "max_debate_rounds": overrides.get("max_debate_rounds", DEFAULT_CONFIG.get("max_debate_rounds")),
        "max_risk_discuss_rounds": overrides.get(
            "max_risk_discuss_rounds",
            DEFAULT_CONFIG.get("max_risk_discuss_rounds"),
        ),
        "max_recur_limit": overrides.get("max_recur_limit", DEFAULT_CONFIG.get("max_recur_limit")),
        "max_analyst_tool_rounds": overrides.get(
            "max_analyst_tool_rounds",
            DEFAULT_CONFIG.get("max_analyst_tool_rounds"),
        ),
        "analyst_concurrency_limit": overrides.get(
            "analyst_concurrency_limit",
            DEFAULT_CONFIG.get("analyst_concurrency_limit"),
        ),
        "news_article_limit": overrides.get("news_article_limit", DEFAULT_CONFIG.get("news_article_limit")),
        "global_news_article_limit": overrides.get(
            "global_news_article_limit",
            DEFAULT_CONFIG.get("global_news_article_limit"),
        ),
    }


def _default_overnight_trade_date(
    now: datetime.datetime | None = None,
    *,
    timezone=CENTRAL,
) -> str:
    current = now or datetime.datetime.now(tz=datetime.timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=datetime.timezone.utc)
    local_date = current.astimezone(timezone).date()
    while local_date.weekday() >= 5:
        local_date += datetime.timedelta(days=1)
    return local_date.isoformat()


def _overnight_graph_completion_status(
    *,
    requested_full_graph_tickers: int,
    effective_full_graph_tickers: int,
    tradable_count: int,
    full_graph_count: int,
    full_graph_success_count: int,
    graph_failure_count: int,
    graph_disabled_reason: str | None,
) -> tuple[str, list[str]]:
    if requested_full_graph_tickers <= 0:
        return "not_requested", ["full graph ticker limit was set to 0"]
    if graph_disabled_reason:
        return "disabled", [str(graph_disabled_reason)]
    if tradable_count <= 0:
        return "no_tradable_symbols", ["no tradable symbols were available for graph analysis"]
    if effective_full_graph_tickers <= 0:
        return "disabled", ["effective full graph limit was 0"]
    if full_graph_success_count > 0:
        reasons = [f"{full_graph_success_count} full graph run(s) completed"]
        if full_graph_count < min(effective_full_graph_tickers, tradable_count):
            reasons.append("remaining requested graph slots were not attempted before fallback scoring")
        if graph_failure_count > 0:
            reasons.append(f"{graph_failure_count} graph run(s) failed and used fallback scoring")
        return "complete", reasons
    if full_graph_count > 0:
        return "failed", [f"{graph_failure_count or full_graph_count} graph run(s) attempted but none completed"]
    return "incomplete", ["full graph was requested but no graph run was attempted"]


def _latest_json_packet_path(log_dir: Path, pattern: str) -> Path | None:
    candidates: list[Path] = []
    latest = log_dir / "latest.json"
    if latest.exists():
        candidates.append(latest)
    candidates.extend(path for path in log_dir.glob(pattern) if _is_raw_json_packet_path(path))

    readable: list[tuple[tuple[int, float], Path]] = []
    for candidate in candidates:
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, Mapping):
            continue
        if candidate.name != "latest.json" and payload.get("latest_alias_written") is False:
            continue
        generated_at = _parse_packet_timestamp(payload.get("generated_at"))
        if generated_at is not None:
            sort_key = (1, generated_at.timestamp())
        else:
            try:
                sort_key = (0, candidate.stat().st_mtime)
            except OSError:
                continue
        readable.append((sort_key, candidate))
    if not readable:
        return None
    readable.sort(key=lambda item: item[0], reverse=True)
    return readable[0][1]


def _read_json_packet(path: Path | None) -> dict | None:
    if not path or not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


PREOPEN_VALIDATION_MAX_AGE = datetime.timedelta(minutes=45)


def _latest_preopen_validation_packet(log_dir: Path) -> dict | None:
    return _read_json_packet(log_dir / "latest-compact.json") or _read_json_packet(
        log_dir / "latest.json"
    )


def _preopen_validation_submit_check(
    packet: Mapping[str, Any] | None,
    *,
    log_dir: Path,
    now: datetime.datetime,
    max_age: datetime.timedelta = PREOPEN_VALIDATION_MAX_AGE,
) -> tuple[dict[str, Any], list[OrderIssue]]:
    if packet is None:
        summary = {
            "status": "missing",
            "path": str(log_dir / "latest-compact.json"),
            "summary": "missing latest pre-open validation packet",
        }
        return summary, [
            OrderIssue("preopen-validation", summary["summary"]),
        ]

    generated_at_raw = packet.get("generated_at")
    generated_at = _parse_packet_timestamp(generated_at_raw)
    issues: list[str] = []
    if generated_at is None:
        issues.append("pre-open validation generated_at is missing or invalid")
        age_seconds = None
    else:
        age = now.astimezone(datetime.timezone.utc) - generated_at
        age_seconds = int(age.total_seconds())
        if age > max_age:
            issues.append(
                "pre-open validation is stale: "
                f"age {age} exceeds max age {max_age}"
            )
    failed_check_ids = [str(item) for item in packet.get("failed_check_ids") or []]
    warned_check_ids = [str(item) for item in packet.get("warned_check_ids") or []]
    skipped_check_ids = [str(item) for item in packet.get("skipped_check_ids") or []]
    overall_status = str(packet.get("overall_status") or "").strip()
    market_session = str(packet.get("market_session") or "").strip()
    if market_session != "pre_open":
        issues.append(
            "pre-open validation market_session must be pre_open before submit; "
            f"got {market_session or 'missing'}"
        )
    if overall_status != "pass":
        issues.append(
            "pre-open validation overall_status must be pass before submit; "
            f"got {overall_status or 'missing'}"
        )
    if failed_check_ids:
        issues.append(
            "pre-open validation has failed checks: " + ", ".join(failed_check_ids)
        )
    if warned_check_ids:
        issues.append(
            "pre-open validation has warnings: " + ", ".join(warned_check_ids)
        )
    if skipped_check_ids:
        issues.append(
            "pre-open validation has skipped checks: " + ", ".join(skipped_check_ids)
        )

    summary = {
        "status": "pass" if not issues else "blocked",
        "path": str(log_dir / "latest-compact.json"),
        "raw_packet_path": packet.get("raw_packet_path"),
        "generated_at": generated_at_raw,
        "age_seconds": age_seconds,
        "overall_status": overall_status,
        "market_session": market_session,
        "failed_check_ids": failed_check_ids,
        "warned_check_ids": warned_check_ids,
        "skipped_check_ids": skipped_check_ids,
        "can_submit_orders": False,
        "execution_authority": "none",
    }
    return summary, [
        OrderIssue("preopen-validation", issue)
        for issue in issues
    ]


def _parse_packet_timestamp(value: object) -> datetime.datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=datetime.timezone.utc)
    return parsed


def _is_raw_json_packet_path(path: Path) -> bool:
    if not path.is_file() or path.suffix.lower() != ".json":
        return False
    name = path.name.lower()
    return not (name.endswith(".compact.json") or name == "latest-compact.json")


def _resolved_path_or_none(path: Path) -> Path | None:
    try:
        return path.resolve()
    except OSError:
        return None


def _is_path_within(child: Path, parent: Path) -> bool:
    child_resolved = _resolved_path_or_none(child)
    parent_resolved = _resolved_path_or_none(parent)
    if child_resolved is None or parent_resolved is None:
        return False
    try:
        child_resolved.relative_to(parent_resolved)
    except ValueError:
        return False
    return True


def _audit_overnight_prior_feed(checks: list[dict], overnight_packet: Mapping | None) -> None:
    """Verify the compact overnight prior-feed artifact when a new packet exposes it."""
    if not isinstance(overnight_packet, Mapping):
        return
    research_context = overnight_packet.get("research_context") or {}
    if not isinstance(research_context, Mapping):
        research_context = {}
    prior_feed_ref = research_context.get("prior_feed") or {}
    if not isinstance(prior_feed_ref, Mapping) or not prior_feed_ref.get("path"):
        _verification_check(
            checks,
            "overnight_prior_feed",
            "warn",
            "Latest overnight packet predates or is missing the compact prior-feed artifact pointer.",
            packet_count=research_context.get("packet_count"),
            execution_authority=prior_feed_ref.get("execution_authority") if isinstance(prior_feed_ref, Mapping) else None,
        )
        return

    prior_feed_path = Path(str(prior_feed_ref.get("path")))
    expected_parent: Path | None = None
    packet_path_value = overnight_packet.get("packet_path") or overnight_packet.get("path")
    if packet_path_value:
        expected_parent = Path(str(packet_path_value)).parent / "research_context"
    path_scope_ok = True
    path_scope_issue: str | None = None
    if expected_parent is not None:
        path_scope_ok = _is_path_within(prior_feed_path, expected_parent)
        if not path_scope_ok:
            path_scope_issue = "prior feed path is outside the overnight packet research_context directory"

    prior_feed_packet = _read_json_packet(prior_feed_path)
    if not isinstance(prior_feed_packet, dict):
        _verification_check(
            checks,
            "overnight_prior_feed",
            "fail",
            "Latest overnight packet points to a compact prior-feed artifact that cannot be read.",
            path=str(prior_feed_path),
            schema=prior_feed_ref.get("schema"),
            packet_count=prior_feed_ref.get("packet_count"),
            blocked_count=prior_feed_ref.get("blocked_count"),
            execution_authority=prior_feed_ref.get("execution_authority"),
            expected_parent=str(expected_parent) if expected_parent is not None else None,
            path_scope_ok=path_scope_ok,
            path_scope_issue=path_scope_issue,
        )
        return

    forbidden_effects = prior_feed_packet.get("forbidden_effects") or []
    mismatches: list[str] = []
    for field in (
        "schema",
        "packet_count",
        "blocked_count",
        "analysis_only",
        "execution_authority",
    ):
        if field in prior_feed_ref and prior_feed_ref.get(field) != prior_feed_packet.get(field):
            mismatches.append(field)
    if "forbidden_effects" in prior_feed_ref and list(prior_feed_ref.get("forbidden_effects") or []) != list(forbidden_effects):
        mismatches.append("forbidden_effects")
    packet_self_path = prior_feed_packet.get("path")
    if packet_self_path:
        ref_resolved = _resolved_path_or_none(prior_feed_path)
        packet_resolved = _resolved_path_or_none(Path(str(packet_self_path)))
        if ref_resolved is None or packet_resolved is None or ref_resolved != packet_resolved:
            mismatches.append("path")

    valid = (
        prior_feed_packet.get("schema") == "overnight_prior_feed_v1"
        and prior_feed_packet.get("analysis_only") is True
        and prior_feed_packet.get("execution_authority") == "none"
        and "submit_order" in forbidden_effects
        and path_scope_ok
        and not mismatches
    )
    _verification_check(
        checks,
        "overnight_prior_feed",
        "pass" if valid else "fail",
        (
            "Compact overnight prior-feed artifact is readable, analysis-only, and has no execution authority."
            if valid
            else "Compact overnight prior-feed artifact exists but failed safety, scope, or reference-integrity checks."
        ),
        path=str(prior_feed_path),
        expected_parent=str(expected_parent) if expected_parent is not None else None,
        path_scope_ok=path_scope_ok,
        path_scope_issue=path_scope_issue,
        mismatches=mismatches,
        schema=prior_feed_packet.get("schema"),
        packet_count=prior_feed_packet.get("packet_count"),
        blocked_count=prior_feed_packet.get("blocked_count"),
        analysis_only=prior_feed_packet.get("analysis_only"),
        execution_authority=prior_feed_packet.get("execution_authority"),
        forbidden_effects=forbidden_effects,
    )


def _safe_int(value: object, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _top_ranked_symbols(packet: Mapping | None, *, limit: int = 3) -> list[str]:
    if not isinstance(packet, Mapping):
        return []
    symbols: list[str] = []
    for candidate in packet.get("ranked_candidates") or []:
        if not isinstance(candidate, Mapping):
            continue
        symbol = str(candidate.get("symbol") or "").strip().upper()
        if not symbol:
            continue
        symbols.append(symbol)
        if len(symbols) >= limit:
            break
    return symbols


def _audit_overnight_source_quality(
    checks: list[dict],
    overnight_packet: Mapping | None,
) -> None:
    """Verify overnight planning carried source-quality downranking evidence."""
    if not isinstance(overnight_packet, Mapping):
        return
    research_context = overnight_packet.get("research_context") or {}
    watchlists = (
        research_context.get("watchlists")
        if isinstance(research_context, Mapping)
        else {}
    )
    source_quality = (
        watchlists.get("source_quality")
        if isinstance(watchlists, Mapping)
        else {}
    )
    if not isinstance(source_quality, Mapping) or not source_quality:
        _verification_check(
            checks,
            "overnight_source_quality_context",
            "fail",
            "Latest overnight packet is missing source-quality context for stale/weak-source downranking.",
            research_context_packet_count=research_context.get("packet_count")
            if isinstance(research_context, Mapping)
            else None,
        )
        return

    status = str(source_quality.get("status") or "").strip().lower()
    ordering_enabled = source_quality.get("source_quality_ordering_enabled") is True
    stale_needs_refresh_count = _safe_int(
        source_quality.get("stale_needs_refresh_count")
    )
    missing_or_invalid_count = _safe_int(
        source_quality.get("missing_or_invalid_count")
    )
    unreadable_count = _safe_int(source_quality.get("unreadable_count"))
    blocked = source_quality.get("blocked") is True
    ok = (
        status == "available"
        and ordering_enabled
        and stale_needs_refresh_count == 0
        and missing_or_invalid_count == 0
        and unreadable_count == 0
        and not blocked
    )
    _verification_check(
        checks,
        "overnight_source_quality_context",
        "pass" if ok else "fail",
        (
            "Latest overnight packet carried source-quality ordering/downrank evidence with no refresh-blocking gaps."
            if ok
            else "Latest overnight packet carried incomplete or blocked source-quality evidence."
        ),
        source_quality_status=status or None,
        review_path=source_quality.get("review_path"),
        source_quality_ordering_enabled=ordering_enabled,
        scored_source_count=source_quality.get("scored_source_count"),
        source_count=source_quality.get("source_count"),
        stale_count=source_quality.get("stale_count"),
        stale_downrank_count=source_quality.get("stale_downrank_count"),
        stale_needs_refresh_count=stale_needs_refresh_count,
        blocked_count=source_quality.get("blocked_count"),
        missing_or_invalid_count=missing_or_invalid_count,
        unreadable_count=unreadable_count,
        next_action=source_quality.get("next_action"),
        blocked=blocked,
    )


def _audit_overnight_top_provider_bundles(
    checks: list[dict],
    overnight_packet: Mapping | None,
    *,
    source_routing_compact_path: Path = Path("results/_context/source-routing-compact.json"),
    top_n: int = 3,
) -> None:
    """Verify top overnight candidates have broad provider-bundle coverage."""
    if not isinstance(overnight_packet, Mapping):
        return
    top_symbols = _top_ranked_symbols(overnight_packet, limit=top_n)
    if not top_symbols:
        _verification_check(
            checks,
            "overnight_top_provider_bundles",
            "fail",
            "Latest overnight packet has no ranked symbols to verify provider-bundle coverage.",
        )
        return

    embedded = overnight_packet.get("top_provider_bundles")
    if isinstance(embedded, Mapping) and embedded.get("enabled") is not False:
        bundle_symbols = {
            str(symbol).strip().upper()
            for symbol in embedded.get("symbols") or []
            if str(symbol).strip()
        }
        missing_symbols = [symbol for symbol in top_symbols if symbol not in bundle_symbols]
        error_count = _safe_int(embedded.get("error_count"))
        analysis_only = embedded.get("analysis_only") is True
        no_execution = embedded.get("execution_authority") == "none"
        bundle_count = _safe_int(embedded.get("bundle_count"))
        ok = (
            bundle_count > 0
            and not missing_symbols
            and error_count == 0
            and analysis_only
            and no_execution
        )
        _verification_check(
            checks,
            "overnight_top_provider_bundles",
            "pass" if ok else "fail",
            (
                "Latest overnight packet embeds analysis-only provider bundles for the top candidates."
                if ok
                else "Latest overnight packet has incomplete embedded provider-bundle coverage for top candidates."
            ),
            coverage_source="overnight_packet",
            top_symbols=top_symbols,
            bundle_symbols=sorted(bundle_symbols),
            missing_symbols=missing_symbols,
            bundle_count=bundle_count,
            source_packet_count=embedded.get("source_packet_count"),
            gap_packet_count=embedded.get("gap_packet_count"),
            error_count=error_count,
            evidence_needs_without_non_gap_packets=embedded.get(
                "evidence_needs_without_non_gap_packets"
            )
            or [],
            symbols_with_missing_non_gap=embedded.get("symbols_with_missing_non_gap")
            or [],
            analysis_only=analysis_only,
            execution_authority=embedded.get("execution_authority"),
            summary_packet_paths=embedded.get("summary_packet_paths") or {},
        )
        return

    overlay = _read_json_packet(source_routing_compact_path)
    bundled_targets = {
        str(symbol).strip().upper()
        for symbol in (overlay or {}).get("recent_provider_target_symbols_with_bundle", [])
        if str(symbol).strip()
    }
    overlay_missing = {
        str(symbol).strip().upper()
        for symbol in (overlay or {}).get("recent_provider_target_symbols_missing_bundle", [])
        if str(symbol).strip()
    }
    missing_symbols = [
        symbol
        for symbol in top_symbols
        if symbol not in bundled_targets or symbol in overlay_missing
    ]
    ok = bool(overlay) and not missing_symbols
    _verification_check(
        checks,
        "overnight_top_provider_bundles",
        "pass" if ok else "fail",
        (
            "Top overnight candidates have recent provider-bundle coverage in compact source-routing context."
            if ok
            else "Top overnight candidates are missing provider-bundle coverage in both packet and compact context."
        ),
        coverage_source="source_routing_overlay",
        source_routing_compact_path=str(source_routing_compact_path),
        top_symbols=top_symbols,
        recent_provider_bundle_count=(overlay or {}).get("recent_provider_bundle_count"),
        latest_provider_bundle_summary_path=(overlay or {}).get(
            "latest_provider_bundle_summary_path"
        ),
        latest_provider_bundle_generated_at=(overlay or {}).get(
            "latest_provider_bundle_generated_at"
        ),
        bundled_target_symbols=sorted(bundled_targets),
        missing_symbols=missing_symbols,
        recent_provider_bundle_gap_count=(overlay or {}).get(
            "recent_provider_bundle_gap_count"
        ),
        recent_provider_target_bundle_gap_count=(overlay or {}).get(
            "recent_provider_target_bundle_gap_count"
        ),
    )


def _packet_has_symbol_sell_evidence(packet: Mapping | None, symbol: str) -> bool:
    if not isinstance(packet, Mapping):
        return False
    target_symbol = str(symbol or "").upper().strip()
    if not target_symbol:
        return False
    for collection_key in ("submitted", "reconciled_orders"):
        entries = packet.get(collection_key) or []
        if not isinstance(entries, Sequence) or isinstance(entries, (str, bytes)):
            continue
        for entry in entries:
            if not isinstance(entry, Mapping):
                continue
            candidates = [entry]
            for nested_key in ("live_response", "live_order", "live", "order", "intent"):
                nested = entry.get(nested_key)
                if isinstance(nested, Mapping):
                    candidates.append(nested)
            for candidate in candidates:
                candidate_symbol = str(candidate.get("symbol") or "").upper().strip()
                candidate_side = str(candidate.get("side") or "").lower().strip()
                if candidate_symbol == target_symbol and candidate_side == "sell":
                    return True
    return False


def _discover_reconciliation_packet_paths(
    log_dir: Path,
    pattern: str,
    *,
    symbol: str,
    max_candidates: int = 50,
    max_matches: int = 10,
) -> tuple[list[Path], list[dict[str, str]]]:
    candidates: list[Path] = []
    latest = log_dir / "latest.json"
    if latest.exists():
        candidates.append(latest)
    candidates.extend(
        sorted(
            (path for path in log_dir.glob(pattern) if _is_raw_json_packet_path(path)),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
    )
    seen: set[Path] = set()
    matches: list[Path] = []
    valid_fallbacks: list[Path] = []
    issues: list[dict[str, str]] = []
    for candidate in candidates[:max_candidates]:
        resolved = candidate.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        payload = _read_json_packet(candidate)
        if payload is None:
            issues.append({"path": str(candidate), "issue": "invalid_or_unreadable_json"})
            continue
        valid_fallbacks.append(candidate)
        if _packet_has_symbol_sell_evidence(payload, symbol):
            matches.append(candidate)
            if len(matches) >= max_matches:
                break
    if matches:
        return matches, issues
    if valid_fallbacks:
        issues.append(
            {
                "path": str(log_dir),
                "issue": f"no_recent_{symbol.upper()}_sell_evidence_found;using_latest_valid_packet",
            }
        )
        return valid_fallbacks[:1], issues
    issues.append({"path": str(log_dir), "issue": "no_valid_hourly_packets_found"})
    return [], issues


def _verification_check(
    checks: list[dict],
    name: str,
    status: str,
    summary: str,
    **evidence,
) -> None:
    checks.append(
        {
            "name": name,
            "status": status,
            "summary": summary,
            "evidence": {key: value for key, value in evidence.items() if value is not None},
        }
    )


REQUIRED_PREMARKET_FRESH_VALIDATIONS = (
    "premarket quotes and spreads",
    "overnight and morning news/social deltas",
    "open live and paper orders",
    "current positions and P/L",
    "live sizing room and buying power",
)


def _premarket_fresh_validation_items(packet: Mapping | None) -> list[str]:
    if not isinstance(packet, Mapping):
        return []
    instructions = packet.get("premarket_instructions")
    if not isinstance(instructions, Mapping):
        return []
    return [str(item) for item in instructions.get("must_validate_fresh") or [] if str(item).strip()]


def _audit_premarket_fresh_validation_checklist(
    checks: list[dict],
    *,
    premarket_packet: Mapping | None,
    premarket_path: Path | None,
    premarket_brief_log_dir: Path,
) -> None:
    raw_items = _premarket_fresh_validation_items(premarket_packet)
    raw_missing = [item for item in REQUIRED_PREMARKET_FRESH_VALIDATIONS if item not in raw_items]

    compact_path = premarket_brief_log_dir / "latest-compact.json"
    compact_packet = _read_json_packet(compact_path)
    compact_items = _premarket_fresh_validation_items(compact_packet)
    compact_missing = [item for item in REQUIRED_PREMARKET_FRESH_VALIDATIONS if item not in compact_items]
    compact_schema_ok = (
        isinstance(compact_packet, Mapping)
        and compact_packet.get("schema") == "compact_premarket_brief_v1"
    )
    compact_raw_path = (
        str(compact_packet.get("raw_packet_path") or "")
        if isinstance(compact_packet, Mapping)
        else ""
    )
    compact_points_to_latest_raw = False
    if compact_raw_path and premarket_path:
        compact_raw_name = Path(compact_raw_path).name
        compact_points_to_latest_raw = (
            compact_raw_name == premarket_path.name
            or (
                premarket_path.name == "latest.json"
                and compact_raw_name.startswith("premarket-brief-")
                and (premarket_brief_log_dir / compact_raw_name).exists()
            )
        )

    checklist_ok = (
        bool(premarket_packet)
        and not raw_missing
        and compact_schema_ok
        and bool(compact_raw_path)
        and compact_points_to_latest_raw
        and not compact_missing
    )
    _verification_check(
        checks,
        "premarket_fresh_validation_checklist",
        "pass" if checklist_ok else "fail",
        (
            "Raw and compact premarket packets preserve the required fresh-validation checklist for morning agents."
            if checklist_ok
            else "Premarket first-read context is missing the required fresh-validation checklist or raw-packet pointer."
        ),
        raw_path=str(premarket_path) if premarket_path else None,
        compact_path=str(compact_path),
        expected_items=list(REQUIRED_PREMARKET_FRESH_VALIDATIONS),
        raw_item_count=len(raw_items),
        raw_missing=raw_missing,
        compact_item_count=len(compact_items),
        compact_missing=compact_missing,
        compact_schema=compact_packet.get("schema") if isinstance(compact_packet, Mapping) else None,
        compact_raw_packet_path=compact_raw_path or None,
        compact_points_to_latest_raw=compact_points_to_latest_raw,
    )


def _preopen_check(
    check_id: str,
    status: str,
    summary: str,
    **evidence: Any,
) -> dict[str, Any]:
    return {
        "id": check_id,
        "required": True,
        "status": status,
        "summary": summary,
        "evidence": {key: value for key, value in evidence.items() if value is not None},
    }


def _preopen_overall_status(checks: Sequence[Mapping[str, Any]]) -> str:
    statuses = {str(check.get("status") or "").lower() for check in checks}
    if "fail" in statuses:
        return "fail"
    if "warn" in statuses:
        return "pass_with_warnings"
    return "pass"


def _preopen_validation_status_counts(checks: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for check in checks:
        status = str(check.get("status") or "unknown").lower()
        counts[status] = counts.get(status, 0) + 1
    return counts


def _broker_read(label: str, fn, default):
    try:
        return fn(), None
    except Exception as exc:  # noqa: BLE001 - packet must preserve broker-read failures.
        return default, f"{label} failed: {exc}"


def _decimal_present(value: object) -> bool:
    try:
        Decimal(str(value))
    except Exception:  # noqa: BLE001 - validation only.
        return False
    return True


def _top_symbol_from_premarket(packet: Mapping | None) -> str | None:
    if not isinstance(packet, Mapping):
        return None
    instructions = packet.get("premarket_instructions")
    if not isinstance(instructions, Mapping):
        return None
    raw = str(instructions.get("top_symbol") or "").strip().upper()
    return raw or None


def _build_preopen_validation_packet(
    *,
    generated_at: datetime.datetime,
    market_session: str,
    live_account: Mapping[str, Any],
    paper_account: Mapping[str, Any],
    live_positions: Sequence[Mapping[str, Any]],
    paper_positions: Sequence[Mapping[str, Any]],
    live_open_orders: Sequence[Mapping[str, Any]],
    paper_open_orders: Sequence[Mapping[str, Any]],
    broker_errors: Mapping[str, str],
    market_data: Mapping[str, Mapping[str, Any]],
    candidate_signals: Sequence[CandidateSignal],
    premarket_packet: Mapping | None,
    premarket_path: Path | None,
    premarket_validation: Mapping | None,
    overnight_validation: Mapping | None,
    live_control_state: Mapping[str, Any] | None,
    live_control_issues: Sequence[str],
    risk_envelope_issues: Sequence[str],
    risk_envelope_mode: str | None,
) -> dict[str, Any]:
    top_symbol = _top_symbol_from_premarket(premarket_packet)
    signal_by_symbol = {signal.symbol.upper(): signal for signal in candidate_signals}
    top_signal = signal_by_symbol.get(top_symbol or "")
    top_market_row = market_data.get(top_symbol or "") if top_symbol else None
    tradeable_session = can_trade_session(market_session)

    checks: list[dict[str, Any]] = []
    if not top_symbol:
        checks.append(
            _preopen_check(
                "premarket_quotes_and_spreads",
                "fail",
                "No premarket top symbol is available, so fresh quote validation cannot be targeted.",
                market_session=market_session,
            )
        )
    elif not tradeable_session:
        checks.append(
            _preopen_check(
                "premarket_quotes_and_spreads",
                "skip",
                "Market session is not tradeable; rerun this validation during pre-open/open before any live action.",
                market_session=market_session,
                top_symbol=top_symbol,
            )
        )
    elif top_signal is not None:
        checks.append(
            _preopen_check(
                "premarket_quotes_and_spreads",
                "pass",
                f"{top_symbol} has a fresh candidate quote in the supervisor market-data feed.",
                top_symbol=top_symbol,
                source=top_signal.source,
                current_price=str(top_signal.current_price),
                previous_close=str(top_signal.previous_close) if top_signal.previous_close is not None else None,
                day_change_pct=str(top_signal.day_change_pct),
                volume_ratio=str(top_signal.volume_ratio),
            )
        )
    else:
        stale_reason = (
            top_market_row.get("quote_stale_reason")
            if isinstance(top_market_row, Mapping)
            else None
        )
        checks.append(
            _preopen_check(
                "premarket_quotes_and_spreads",
                "fail",
                f"{top_symbol} did not survive fresh quote validation in the supervisor market-data feed.",
                top_symbol=top_symbol,
                market_row_present=isinstance(top_market_row, Mapping),
                stale_quote=(top_market_row or {}).get("stale_quote") if isinstance(top_market_row, Mapping) else None,
                quote_fresh=(top_market_row or {}).get("quote_fresh") if isinstance(top_market_row, Mapping) else None,
                stale_reason=stale_reason,
            )
        )

    source_packets = (
        premarket_packet.get("source_packets")
        if isinstance(premarket_packet, Mapping)
        else []
    ) or []
    instructions = (
        premarket_packet.get("premarket_instructions")
        if isinstance(premarket_packet, Mapping)
        else {}
    )
    research_context = (
        instructions.get("latest_research_context")
        if isinstance(instructions, Mapping)
        else {}
    )
    stale_warnings = (
        premarket_packet.get("stale_warnings")
        if isinstance(premarket_packet, Mapping)
        else []
    ) or []
    generated = (
        _parse_packet_timestamp(premarket_packet.get("generated_at"))
        if isinstance(premarket_packet, Mapping)
        else None
    )
    age_hours = None
    if generated is not None:
        age_hours = round(
            max(
                (generated_at.astimezone(datetime.timezone.utc) - generated.astimezone(datetime.timezone.utc)).total_seconds()
                / 3600,
                0,
            ),
            2,
        )
    research_packet_count = int((research_context or {}).get("packet_count") or 0) if isinstance(research_context, Mapping) else 0
    if not isinstance(premarket_packet, Mapping):
        checks.append(
            _preopen_check(
                "overnight_and_morning_news_social_deltas",
                "fail",
                "No premarket brief is available, so news/social delta validation is missing.",
            )
        )
    elif stale_warnings:
        checks.append(
            _preopen_check(
                "overnight_and_morning_news_social_deltas",
                "warn",
                "Premarket brief exists but carries stale warnings; refresh research/news/social context before relying on it.",
                source_packet_count=len(source_packets),
                stale_warnings=stale_warnings[:5],
                age_hours=age_hours,
            )
        )
    elif research_packet_count > 0 and len(source_packets) > 0:
        checks.append(
            _preopen_check(
                "overnight_and_morning_news_social_deltas",
                "pass",
                "Premarket brief links overnight research context and has no stale warnings.",
                source_packet_count=len(source_packets),
                research_context_packet_count=research_packet_count,
                age_hours=age_hours,
                provider_fallback_needs=(research_context or {}).get("provider_fallback_needs") if isinstance(research_context, Mapping) else None,
            )
        )
    else:
        checks.append(
            _preopen_check(
                "overnight_and_morning_news_social_deltas",
                "warn",
                "Premarket brief is readable, but research/news/social context is too thin to prove fresh deltas.",
                source_packet_count=len(source_packets),
                research_context_packet_count=research_packet_count,
                age_hours=age_hours,
            )
        )

    order_errors = [broker_errors.get("live_open_orders"), broker_errors.get("paper_open_orders")]
    order_errors = [error for error in order_errors if error]
    checks.append(
        _preopen_check(
            "open_live_and_paper_orders",
            "fail" if order_errors else "pass",
            (
                "Open live and paper orders were read from Alpaca."
                if not order_errors
                else "One or more open-order reads failed; do not use stale order assumptions."
            ),
            live_open_order_count=len(live_open_orders),
            paper_open_order_count=len(paper_open_orders),
            errors=order_errors,
        )
    )

    position_errors = [broker_errors.get("live_positions"), broker_errors.get("paper_positions")]
    position_errors = [error for error in position_errors if error]
    checks.append(
        _preopen_check(
            "current_positions_and_pl",
            "fail" if position_errors else "pass",
            (
                "Current live and paper positions were read from Alpaca."
                if not position_errors
                else "One or more position reads failed; do not use stale P/L assumptions."
            ),
            live_position_count=len(live_positions),
            paper_position_count=len(paper_positions),
            live_unrealized_pl=str(total_unrealized_pl(live_positions)),
            paper_unrealized_pl=str(total_unrealized_pl(paper_positions)),
            errors=position_errors,
        )
    )

    buying_power_errors = [broker_errors.get("live_account"), broker_errors.get("paper_account")]
    buying_power_errors = [error for error in buying_power_errors if error]
    live_buying_power = live_account.get("buying_power") if isinstance(live_account, Mapping) else None
    live_control_open = not live_control_issues and live_control_state is not None
    sizing_status = "pass"
    sizing_summary = "Live buying power, risk envelope, and live-control state were readable."
    if buying_power_errors or not _decimal_present(live_buying_power):
        sizing_status = "fail"
        sizing_summary = "Live buying power could not be proven from fresh broker account data."
    elif risk_envelope_issues:
        sizing_status = "fail"
        sizing_summary = "Risk-envelope parsing issues block reliable live sizing."
    elif not live_control_open:
        sizing_status = "warn"
        sizing_summary = "Broker buying power is readable, but live-control is closed or expired."
    checks.append(
        _preopen_check(
            "live_sizing_room_and_buying_power",
            sizing_status,
            sizing_summary,
            live_buying_power=str(live_buying_power) if live_buying_power not in (None, "") else None,
            live_equity=live_account.get("equity") if isinstance(live_account, Mapping) else None,
            risk_envelope_mode=risk_envelope_mode,
            risk_envelope_issues=list(risk_envelope_issues),
            live_control_loaded=live_control_state is not None,
            live_control_issues=list(live_control_issues),
            errors=buying_power_errors,
        )
    )

    status_counts = _preopen_validation_status_counts(checks)
    return {
        "kind": "tradingagents_preopen_validation",
        "schema": "preopen_validation_v1",
        "generated_at": generated_at.astimezone(datetime.timezone.utc).isoformat(timespec="seconds"),
        "analysis_only": True,
        "can_submit_orders": False,
        "execution_authority": "none",
        "submitted_count": 0,
        "market_session": market_session,
        "top_symbol": top_symbol,
        "overall_status": _preopen_overall_status(checks),
        "errors": dict(broker_errors),
        "status_counts": status_counts,
        "checks": checks,
        "failed_check_ids": [check["id"] for check in checks if check["status"] == "fail"],
        "warned_check_ids": [check["id"] for check in checks if check["status"] == "warn"],
        "skipped_check_ids": [check["id"] for check in checks if check["status"] == "skip"],
        "premarket_brief": {
            "path": str(premarket_path) if premarket_path else None,
            "generated_at": premarket_packet.get("generated_at") if isinstance(premarket_packet, Mapping) else None,
            "validation": dict(premarket_validation or {}),
        },
        "overnight_plan": {
            "validation": dict(overnight_validation or {}),
        },
        "account_summary": {
            "live": {
                "status": live_account.get("status") if isinstance(live_account, Mapping) else None,
                "buying_power": live_buying_power,
                "equity": live_account.get("equity") if isinstance(live_account, Mapping) else None,
                "position_count": len(live_positions),
                "open_order_count": len(live_open_orders),
            },
            "paper": {
                "status": paper_account.get("status") if isinstance(paper_account, Mapping) else None,
                "buying_power": paper_account.get("buying_power") if isinstance(paper_account, Mapping) else None,
                "equity": paper_account.get("equity") if isinstance(paper_account, Mapping) else None,
                "position_count": len(paper_positions),
                "open_order_count": len(paper_open_orders),
            },
        },
        "candidate_summary": {
            "candidate_count": len(candidate_signals),
            "top_candidates": [
                {
                    "symbol": signal.symbol,
                    "score": str(signal.score),
                    "day_change_pct": str(signal.day_change_pct),
                    "source": signal.source,
                }
                for signal in candidate_signals[:5]
            ],
        },
    }


def compact_preopen_validation_payload(packet: Mapping[str, Any], packet_path: Path | str) -> dict[str, Any]:
    account = packet.get("account_summary") if isinstance(packet.get("account_summary"), Mapping) else {}
    live = account.get("live") if isinstance(account.get("live"), Mapping) else {}
    paper = account.get("paper") if isinstance(account.get("paper"), Mapping) else {}
    return {
        "schema": "compact_preopen_validation_v1",
        "analysis_only": True,
        "can_submit_orders": False,
        "execution_authority": "none",
        "raw_packet_path": str(packet_path),
        "generated_at": packet.get("generated_at"),
        "overall_status": packet.get("overall_status"),
        "market_session": packet.get("market_session"),
        "top_symbol": packet.get("top_symbol"),
        "status_counts": dict(packet.get("status_counts") or {}),
        "failed_check_ids": list(packet.get("failed_check_ids") or [])[:8],
        "warned_check_ids": list(packet.get("warned_check_ids") or [])[:8],
        "skipped_check_ids": list(packet.get("skipped_check_ids") or [])[:8],
        "check_summaries": [
            {
                "id": check.get("id"),
                "status": check.get("status"),
                "summary": check.get("summary"),
            }
            for check in list(packet.get("checks") or [])[:8]
            if isinstance(check, Mapping)
        ],
        "account_summary": {
            "live": {
                "status": live.get("status"),
                "buying_power": live.get("buying_power"),
                "equity": live.get("equity"),
                "position_count": live.get("position_count"),
                "open_order_count": live.get("open_order_count"),
            },
            "paper": {
                "status": paper.get("status"),
                "buying_power": paper.get("buying_power"),
                "equity": paper.get("equity"),
                "position_count": paper.get("position_count"),
                "open_order_count": paper.get("open_order_count"),
            },
        },
        "premarket_brief": packet.get("premarket_brief") or {},
        "candidate_summary": packet.get("candidate_summary") or {},
    }


def write_preopen_validation_packet(
    packet: Mapping[str, Any],
    *,
    output_dir: str | Path = "results/preopen_validation",
    write_latest: bool = True,
) -> Path:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    generated_at = _parse_packet_timestamp(packet.get("generated_at")) or datetime.datetime.now(tz=datetime.timezone.utc)
    packet_path = _unique_packet_path(
        output_path,
        f"preopen-validation-{generated_at:%Y%m%d-%H%M%S}",
    )
    payload = {**dict(packet), "packet_path": str(packet_path)}
    packet_text = json.dumps(payload, indent=2)
    _atomic_write_text(packet_path, packet_text)
    compact = compact_preopen_validation_payload(payload, packet_path)
    compact_text = json.dumps(compact, indent=2)
    _atomic_write_text(packet_path.with_name(f"{packet_path.stem}.compact.json"), compact_text)
    if write_latest:
        _atomic_write_text(output_path / "latest.json", packet_text)
        _atomic_write_text(output_path / "latest-compact.json", compact_text)
    return packet_path


def _audit_overnight_packet_freshness(
    checks: list[dict],
    *,
    overnight_packet: Mapping | None,
    now: datetime.datetime,
    max_age_hours: float,
    calendar_skip_reason: str | None = None,
) -> None:
    if not isinstance(overnight_packet, Mapping):
        return
    if max_age_hours <= 0:
        _verification_check(
            checks,
            "overnight_packet_freshness",
            "pass",
            "Overnight packet freshness age check was disabled for this verification run.",
            max_age_hours=max_age_hours,
        )
        return
    current = now if now.tzinfo else now.replace(tzinfo=datetime.timezone.utc)
    current = current.astimezone(datetime.timezone.utc)
    generated_at = _parse_packet_timestamp(overnight_packet.get("generated_at"))
    if generated_at is None:
        _verification_check(
            checks,
            "overnight_packet_freshness",
            "fail",
            "Latest overnight packet has no parseable generated_at timestamp, so freshness cannot be proven.",
            generated_at=overnight_packet.get("generated_at"),
            current_time=current.isoformat(timespec="seconds"),
            max_age_hours=max_age_hours,
        )
        return
    generated_at = generated_at.astimezone(datetime.timezone.utc)
    if generated_at - current > datetime.timedelta(minutes=5):
        _verification_check(
            checks,
            "overnight_packet_freshness",
            "fail",
            "Latest overnight packet timestamp is in the future; do not trust it for market workflow routing.",
            generated_at=generated_at.isoformat(timespec="seconds"),
            current_time=current.isoformat(timespec="seconds"),
            max_age_hours=max_age_hours,
        )
        return
    age_hours = max((current - generated_at).total_seconds() / 3600, 0.0)
    stale = age_hours > max_age_hours
    deferred_for_calendar = stale and bool(calendar_skip_reason)
    _verification_check(
        checks,
        "overnight_packet_freshness",
        "pass" if deferred_for_calendar or not stale else "warn",
        (
            "Latest overnight packet is older than the configured window, but this calendar slot has no useful regular-market morning."
            if deferred_for_calendar
            else (
            "Latest overnight packet is stale for the configured verification window; rerun overnight research before relying on it."
            if stale
            else "Latest overnight packet is fresh enough for the configured verification window."
            )
        ),
        generated_at=generated_at.isoformat(timespec="seconds"),
        current_time=current.isoformat(timespec="seconds"),
        age_hours=round(age_hours, 2),
        max_age_hours=max_age_hours,
        stale=stale,
        freshness_deferred_for_calendar=deferred_for_calendar,
        calendar_skip_reason=calendar_skip_reason if deferred_for_calendar else None,
    )


def _audit_overnight_packet_trade_date(
    checks: list[dict],
    *,
    overnight_packet: Mapping | None,
    now: datetime.datetime,
) -> None:
    if not isinstance(overnight_packet, Mapping):
        return
    expected_trade_date = _default_overnight_trade_date(now)
    actual_trade_date = str(overnight_packet.get("trade_date") or "").strip()
    if not actual_trade_date:
        _verification_check(
            checks,
            "overnight_packet_trade_date",
            "fail",
            "Latest overnight packet is missing trade_date; rerun overnight research before relying on it.",
            expected_trade_date=expected_trade_date,
            actual_trade_date=None,
        )
        return
    status = "pass" if actual_trade_date == expected_trade_date else "fail"
    _verification_check(
        checks,
        "overnight_packet_trade_date",
        status,
        (
            "Latest overnight packet targets the expected next useful market date."
            if status == "pass"
            else (
                "Latest overnight packet targets a stale or wrong market date; rerun overnight "
                "research before using it for the morning workflow."
            )
        ),
        expected_trade_date=expected_trade_date,
        actual_trade_date=actual_trade_date,
    )


def _automation_text(automation_dir: Path, automation_id: str) -> str | None:
    path = automation_dir / automation_id / "automation.toml"
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def _automation_status_from_text(text: str | None) -> str | None:
    if not text:
        return None
    match = re.search(r'(?m)^\s*status\s*=\s*["\']?([^"\'\r\n#]+)', text)
    if not match:
        return None
    return match.group(1).strip()


def _automation_rrule_from_text(text: str | None) -> str | None:
    if not text:
        return None
    match = re.search(r'(?m)^\s*rrule\s*=\s*["\']?([^"\'\r\n#]+)', text)
    if not match:
        return None
    return match.group(1).strip()


def _rrule_part(rrule: str | None, key: str) -> str | None:
    if not rrule:
        return None
    for part in str(rrule).split(";"):
        if "=" not in part:
            continue
        name, value = part.split("=", 1)
        if name.strip().upper().removeprefix("RRULE:") == key.upper():
            return value.strip()
    return None


def _rrule_int_values(rrule: str | None, key: str, default: Sequence[int]) -> list[int]:
    value = _rrule_part(rrule, key)
    if not value:
        return list(default)
    parsed: list[int] = []
    for piece in value.split(","):
        try:
            parsed.append(int(piece))
        except ValueError:
            continue
    return parsed or list(default)


def _rrule_weekdays(rrule: str | None) -> set[int]:
    mapping = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}
    value = _rrule_part(rrule, "BYDAY")
    if not value:
        return set(range(7))
    return {mapping[piece] for piece in value.split(",") if piece in mapping}


def _next_useful_overnight_due(
    *,
    now: datetime.datetime,
    automation_text: str | None,
) -> datetime.datetime | None:
    """Return the next useful overnight automation due time in UTC."""

    if now.tzinfo is None:
        now = now.replace(tzinfo=datetime.timezone.utc)
    current_local = now.astimezone(CENTRAL).replace(second=0, microsecond=0)
    rrule = _automation_rrule_from_text(automation_text)
    hours = _rrule_int_values(rrule, "BYHOUR", [2])
    minutes = _rrule_int_values(rrule, "BYMINUTE", [30])
    weekdays = _rrule_weekdays(rrule)
    candidates: list[datetime.datetime] = []
    for offset in range(0, 8):
        day = current_local.date() + datetime.timedelta(days=offset)
        if day.weekday() not in weekdays:
            continue
        if day.weekday() == 5:
            continue
        for hour in hours:
            for minute in minutes:
                candidate = datetime.datetime.combine(
                    day,
                    datetime.time(hour=hour, minute=minute),
                    tzinfo=CENTRAL,
                )
                if candidate > current_local:
                    candidates.append(candidate.astimezone(datetime.timezone.utc))
    return min(candidates) if candidates else None


def _verify_automation_status(
    checks: list[dict],
    *,
    automation_dir: Path,
    automation_id: str,
    expected_status: str,
    summary: str,
) -> None:
    path = automation_dir / automation_id / "automation.toml"
    text = _automation_text(automation_dir, automation_id)
    if text is None:
        _verification_check(
            checks,
            f"automation_status:{automation_id}",
            "fail",
            "Automation file was not found, so schedule status could not be proven.",
            path=str(path),
            expected_status=expected_status,
            actual_status=None,
        )
        return
    actual_status = _automation_status_from_text(text)
    if actual_status is None:
        _verification_check(
            checks,
            f"automation_status:{automation_id}",
            "fail",
            "Automation status is missing; the schedule may not be enabled.",
            path=str(path),
            expected_status=expected_status,
            actual_status=None,
        )
        return
    status_ok = actual_status.upper() == expected_status.upper()
    _verification_check(
        checks,
        f"automation_status:{automation_id}",
        "pass" if status_ok else "fail",
        summary if status_ok else f"Automation status is {actual_status}; expected {expected_status}.",
        path=str(path),
        expected_status=expected_status,
        actual_status=actual_status,
    )


def _verify_overnight_planning_status(
    checks: list[dict],
    *,
    automation_dir: Path,
    overnight_packet: dict[str, Any] | None,
    now: datetime.datetime | None = None,
) -> None:
    automation_id = "tradingagents-overnight-planning"
    path = automation_dir / automation_id / "automation.toml"
    text = _automation_text(automation_dir, automation_id)
    expected_status = "ACTIVE_OR_PAUSED_AFTER_COMPLETE_PACKET"
    if text is None:
        _verification_check(
            checks,
            f"automation_status:{automation_id}",
            "fail",
            "Automation file was not found, so schedule status could not be proven.",
            path=str(path),
            expected_status=expected_status,
            actual_status=None,
        )
        return
    actual_status = _automation_status_from_text(text)
    if actual_status is None:
        _verification_check(
            checks,
            f"automation_status:{automation_id}",
            "fail",
            "Automation status is missing; the schedule may not be enabled.",
            path=str(path),
            expected_status=expected_status,
            actual_status=None,
        )
        return

    upper_status = actual_status.upper()
    verification_now = now or _alpaca_policy_now()
    if verification_now.tzinfo is None:
        verification_now = verification_now.replace(tzinfo=datetime.timezone.utc)
    verification_now = verification_now.astimezone(datetime.timezone.utc)
    next_due = _next_useful_overnight_due(now=verification_now, automation_text=text)
    reactivation_lead_hours = 12.0
    hours_until_next_due = (
        (next_due - verification_now).total_seconds() / 3600 if next_due else None
    )
    reactivation_required = (
        upper_status == "PAUSED"
        and hours_until_next_due is not None
        and 0 <= hours_until_next_due <= reactivation_lead_hours
    )
    quality = overnight_packet.get("overnight_quality") if isinstance(overnight_packet, dict) else {}
    quality = quality if isinstance(quality, dict) else {}
    ranked = overnight_packet.get("ranked_candidates") if isinstance(overnight_packet, dict) else []
    submitted = overnight_packet.get("submitted") if isinstance(overnight_packet, dict) else []
    ready_complete_packet = (
        isinstance(overnight_packet, dict)
        and overnight_packet.get("analysis_only") is True
        and isinstance(ranked, list)
        and len(ranked) > 0
        and isinstance(submitted, list)
        and len(submitted) == 0
        and str(quality.get("completion_status") or "").lower() == "complete"
    )
    status_ok = upper_status == "ACTIVE" or (
        upper_status == "PAUSED" and ready_complete_packet and not reactivation_required
    )
    if upper_status == "ACTIVE":
        summary = "Overnight automation is ACTIVE for the next scheduled research window."
    elif reactivation_required:
        summary = (
            "Overnight automation is PAUSED inside the next useful run lead window; "
            "reactivate it before the 2:30 AM research pass."
        )
    elif status_ok:
        summary = "Overnight automation is PAUSED after a current complete analysis-only packet was produced."
    else:
        summary = (
            f"Automation status is {actual_status}; expected ACTIVE, or PAUSED only after "
            "a complete analysis-only overnight packet exists."
        )
    _verification_check(
        checks,
        f"automation_status:{automation_id}",
        "pass" if status_ok else "fail",
        summary,
        path=str(path),
        expected_status=expected_status,
        actual_status=actual_status,
        complete_packet_ready=ready_complete_packet,
        next_useful_due_at=next_due.isoformat(timespec="seconds") if next_due else None,
        hours_until_next_useful_due=round(hours_until_next_due, 2)
        if hours_until_next_due is not None
        else None,
        reactivation_lead_hours=reactivation_lead_hours,
        reactivation_required=reactivation_required,
    )


def _verify_automation_text(
    checks: list[dict],
    *,
    automation_dir: Path,
    automation_id: str,
    required_fragments: list[str],
    summary: str,
) -> None:
    text = _automation_text(automation_dir, automation_id)
    if text is None:
        _verification_check(
            checks,
            f"automation:{automation_id}",
            "warn",
            "Automation file was not found; repo commands may still work, but app schedule wiring was not proven.",
            path=str(automation_dir / automation_id / "automation.toml"),
        )
        return
    normalized_text = text.replace("\\\\", "\\")
    missing = [
        fragment
        for fragment in required_fragments
        if fragment not in text and fragment not in normalized_text
    ]
    _verification_check(
        checks,
        f"automation:{automation_id}",
        "pass" if not missing else "fail",
        summary if not missing else f"Automation exists but is missing required fragments: {', '.join(missing)}",
        path=str(automation_dir / automation_id / "automation.toml"),
        missing=missing,
    )


def _extract_cli_option_value(command_text: str, option: str) -> str | None:
    def _clean_value(value: str) -> str:
        return value.strip().strip("'\"`.,;)")

    match = re.search(rf"{re.escape(option)}(?:=|\s+)([^\s]+)", command_text)
    if match:
        return _clean_value(match.group(1))
    tokens = command_text.replace("\\\n", " ").split()
    for index, token in enumerate(tokens):
        if token == option and index + 1 < len(tokens):
            return _clean_value(tokens[index + 1])
        if token.startswith(f"{option}="):
            return _clean_value(token.split("=", 1)[1])
    return None


def _parse_overnight_automation_contract(automation_dir: Path) -> dict:
    text = _automation_text(automation_dir, "tradingagents-overnight-planning") or ""
    normalized_text = text.replace("\\\\", "\\").replace("\\n", " ")

    def _int_option(option: str) -> int | None:
        value = _extract_cli_option_value(normalized_text, option)
        if value is None:
            return None
        try:
            return int(value)
        except ValueError:
            return None

    def _float_option(option: str) -> float | None:
        value = _extract_cli_option_value(normalized_text, option)
        if value is None:
            return None
        try:
            return float(value)
        except ValueError:
            return None

    def _str_option(option: str) -> str | None:
        return _extract_cli_option_value(normalized_text, option)

    return {
        "graph_profile": _str_option("--overnight-graph-profile"),
        "llm_provider": _str_option("--overnight-llm-provider"),
        "quick_think_llm": _str_option("--overnight-quick-think-llm"),
        "deep_think_llm": _str_option("--overnight-deep-think-llm"),
        "full_graph_limit": _int_option("--full-graph-tickers"),
        "per_ticker_timeout_minutes": _float_option("--per-ticker-timeout-minutes"),
        "time_budget_minutes": _float_option("--time-budget-minutes"),
        "max_completion_tokens": _int_option("--overnight-max-completion-tokens"),
    }


def _overnight_packet_contract_actual(packet: dict | None) -> dict:
    quality = (packet or {}).get("overnight_quality") or {}
    graph_config = quality.get("graph_config") or {}
    return {
        "graph_profile": graph_config.get("graph_profile"),
        "full_graph_limit": quality.get("full_graph_limit"),
        "requested_full_graph_limit": quality.get("requested_full_graph_limit"),
        "graph_disabled_reason": quality.get("graph_disabled_reason"),
        "full_graph_count": quality.get("full_graph_count"),
        "full_graph_attempt_count": quality.get("full_graph_attempt_count"),
        "full_graph_success_count": quality.get("full_graph_success_count"),
        "graph_failure_count": quality.get("graph_failure_count"),
        "fallback_count": quality.get("fallback_count"),
        "completion_status": quality.get("completion_status"),
        "completion_reasons": quality.get("completion_reasons"),
        "tradable_count": quality.get("tradable_count"),
        "ranked_count": quality.get("ranked_count"),
        "per_ticker_timeout_minutes": quality.get("per_ticker_timeout_minutes"),
        "time_budget_minutes": quality.get("time_budget_minutes"),
        "llm_provider": graph_config.get("llm_provider"),
        "quick_think_llm": graph_config.get("quick_think_llm"),
        "deep_think_llm": graph_config.get("deep_think_llm"),
        "max_completion_tokens": graph_config.get("max_completion_tokens"),
    }


def _matches_overnight_automation_contract(actual: dict, expected: dict) -> bool:
    for key, expected_value in expected.items():
        if expected_value is None:
            continue
        actual_value = actual.get(key)
        if (
            key == "full_graph_limit"
            and actual.get("graph_disabled_reason")
            and actual.get("requested_full_graph_limit") == expected_value
            and actual_value == 0
        ):
            continue
        if actual_value is None:
            return False
        if isinstance(expected_value, float):
            try:
                if abs(float(actual_value) - expected_value) > 0.0001:
                    return False
            except (TypeError, ValueError):
                return False
        elif actual_value != expected_value:
            return False
    return True


def _render_overnight_verification_markdown(packet: dict) -> str:
    lines = [
        "# TradingAgents Overnight System Verification",
        "",
        f"- Generated at: {packet.get('generated_at', 'unknown')}",
        f"- Overall status: {packet.get('overall_status', 'unknown')}",
        f"- Checks: {len(packet.get('checks') or [])}",
        "",
        "## Checks",
    ]
    for check in packet.get("checks") or []:
        lines.append(f"- {check.get('status', 'unknown').upper()} - {check.get('name')}: {check.get('summary')}")
    lines.extend(["", "## Commands Exercised"])
    for command in packet.get("commands_exercised") or []:
        lines.append(f"- `{command}`")
    return "\n".join(lines)


def _compact_overnight_verification_payload(
    packet: dict,
    packet_path: str | Path | None = None,
) -> dict:
    checks = [check for check in packet.get("checks") or [] if isinstance(check, dict)]
    status_counts: dict[str, int] = {}
    failed_checks: list[str] = []
    warned_checks: list[str] = []
    by_name: dict[str, dict] = {}
    for check in checks:
        name = str(check.get("name") or "")
        status = str(check.get("status") or "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
        if name:
            by_name[name] = check
        if status == "fail" and name:
            failed_checks.append(name)
        elif status == "warn" and name:
            warned_checks.append(name)

    def evidence_for(name: str) -> dict:
        evidence = by_name.get(name, {}).get("evidence")
        return evidence if isinstance(evidence, dict) else {}

    latest_overnight = evidence_for("latest_overnight_packet")
    freshness = evidence_for("overnight_packet_freshness")
    contract = evidence_for("overnight_matches_automation_contract")
    original_graph = evidence_for("overnight_original_graph_execution")
    source_quality = evidence_for("overnight_source_quality_context")
    top_provider_bundles = evidence_for("overnight_top_provider_bundles")
    premarket = evidence_for("latest_premarket_brief")
    premarket_checklist = evidence_for("premarket_fresh_validation_checklist")
    hourly = evidence_for("latest_hourly_supervisor_packet")
    tournament = evidence_for("latest_paper_tournament_packet")
    preopen = evidence_for("simulated_preopen_validation")
    return {
        "schema": "compact_overnight_system_verification_v1",
        "generated_at": packet.get("generated_at"),
        "analysis_only": True,
        "can_submit_orders": False,
        "execution_authority": "none",
        "overall_status": packet.get("overall_status"),
        "check_count": len(checks),
        "status_counts": status_counts,
        "failed_checks": failed_checks[:10],
        "warned_checks": warned_checks[:10],
        "raw_packet_path": str(packet_path) if packet_path is not None else None,
        "overnight": {
            "path": latest_overnight.get("path"),
            "top_symbol": latest_overnight.get("top_symbol"),
            "ranked_count": latest_overnight.get("ranked_count"),
            "ticker_count": latest_overnight.get("ticker_count"),
            "graph_failure_count": latest_overnight.get("graph_failure_count"),
            "completion_status": latest_overnight.get("completion_status"),
        },
        "freshness": {
            "age_hours": freshness.get("age_hours"),
            "max_age_hours": freshness.get("max_age_hours"),
            "stale": freshness.get("stale"),
            "freshness_deferred_for_calendar": freshness.get(
                "freshness_deferred_for_calendar"
            ),
            "calendar_skip_reason": freshness.get("calendar_skip_reason"),
        },
        "automation_contract": {
            "status": by_name.get("overnight_matches_automation_contract", {}).get(
                "status"
            ),
            "expected": contract.get("expected"),
            "actual": contract.get("actual"),
        },
        "original_graph": {
            "status": by_name.get("overnight_original_graph_execution", {}).get(
                "status"
            ),
            "expected_full_graph_limit": original_graph.get(
                "expected_full_graph_limit"
            ),
            "full_graph_success_count": original_graph.get("full_graph_success_count"),
            "graph_failure_count": original_graph.get("graph_failure_count"),
            "fallback_count": original_graph.get("fallback_count"),
            "completion_status": original_graph.get("completion_status"),
        },
        "source_quality": {
            "status": by_name.get("overnight_source_quality_context", {}).get(
                "status"
            ),
            "review_path": source_quality.get("review_path"),
            "source_quality_ordering_enabled": source_quality.get(
                "source_quality_ordering_enabled"
            ),
            "source_count": source_quality.get("source_count"),
            "stale_count": source_quality.get("stale_count"),
            "stale_downrank_count": source_quality.get("stale_downrank_count"),
            "stale_needs_refresh_count": source_quality.get(
                "stale_needs_refresh_count"
            ),
            "missing_or_invalid_count": source_quality.get(
                "missing_or_invalid_count"
            ),
            "unreadable_count": source_quality.get("unreadable_count"),
            "blocked": source_quality.get("blocked"),
        },
        "top_provider_bundles": {
            "status": by_name.get("overnight_top_provider_bundles", {}).get(
                "status"
            ),
            "coverage_source": top_provider_bundles.get("coverage_source"),
            "top_symbols": top_provider_bundles.get("top_symbols"),
            "missing_symbols": top_provider_bundles.get("missing_symbols"),
            "bundle_count": top_provider_bundles.get("bundle_count"),
            "source_packet_count": top_provider_bundles.get("source_packet_count"),
            "error_count": top_provider_bundles.get("error_count"),
            "recent_provider_bundle_count": top_provider_bundles.get(
                "recent_provider_bundle_count"
            ),
            "latest_provider_bundle_summary_path": top_provider_bundles.get(
                "latest_provider_bundle_summary_path"
            ),
            "latest_provider_bundle_generated_at": top_provider_bundles.get(
                "latest_provider_bundle_generated_at"
            ),
            "recent_provider_target_bundle_gap_count": top_provider_bundles.get(
                "recent_provider_target_bundle_gap_count"
            ),
        },
        "premarket": {
            "path": premarket.get("path"),
            "top_symbol": premarket.get("top_symbol"),
            "source_packet_count": premarket.get("source_packet_count"),
            "stale_warning_count": len(premarket.get("stale_warnings") or []),
            "unresolved_blocker_count": len(premarket.get("unresolved_blockers") or []),
        },
        "premarket_fresh_validation": {
            "status": by_name.get("premarket_fresh_validation_checklist", {}).get(
                "status"
            ),
            "raw_item_count": premarket_checklist.get("raw_item_count"),
            "compact_item_count": premarket_checklist.get("compact_item_count"),
            "raw_missing": list(premarket_checklist.get("raw_missing") or [])[:8],
            "compact_missing": list(premarket_checklist.get("compact_missing") or [])[
                :8
            ],
            "compact_schema": premarket_checklist.get("compact_schema"),
            "compact_points_to_latest_raw": premarket_checklist.get(
                "compact_points_to_latest_raw"
            ),
        },
        "hourly": {
            "path": hourly.get("path"),
            "decision": hourly.get("decision"),
            "submitted_count": hourly.get("submitted_count"),
            "issue_count": hourly.get("issue_count"),
            "expected_safety_lock": hourly.get("expected_safety_lock"),
        },
        "paper_tournament": {
            "path": tournament.get("path"),
            "ranking_count": tournament.get("ranking_count"),
            "submitted_count": tournament.get("submitted_count"),
            "live_strategy_candidate": tournament.get("live_strategy_candidate"),
        },
        "simulated_preopen_validation": {
            "status": by_name.get("simulated_preopen_validation", {}).get("status"),
            "validation_skipped": preopen.get("validation_skipped"),
            "skip_reason": preopen.get("skip_reason"),
            "overnight_status": preopen.get("overnight_status"),
            "premarket_status": preopen.get("premarket_status"),
            "overnight_top": preopen.get("overnight_top"),
            "current_top": preopen.get("current_top"),
            "premarket_top": preopen.get("premarket_top"),
        },
        "next_open": (
            "Open full verification packet when overall_status is not pass, "
            "failed_checks or warned_checks are non-empty, or check evidence is needed."
        ),
    }


def _rating_from_score(score: Decimal) -> str:
    if score >= Decimal("0.75"):
        return "Buy"
    if score >= Decimal("0.60"):
        return "Overweight"
    if score >= Decimal("0.40"):
        return "Hold"
    if score >= Decimal("0.25"):
        return "Underweight"
    return "Sell"


def _fallback_overnight_ticker_result(
    *,
    symbol: str,
    candidate: dict,
    candidate_signal: CandidateSignal | None,
    reason: str,
    graph_result: dict | None = None,
) -> dict:
    score = candidate_signal.score if candidate_signal else Decimal("0.50")
    rating = _rating_from_score(score)
    result = {
        "symbol": symbol.upper(),
        "status": "fallback",
        "method": "market_snapshot_fallback",
        "rating": rating,
        "score": str(score.quantize(Decimal("0.01"))),
        "signal": rating.upper(),
        "final_trade_decision": f"Fallback rating: {rating}. {reason}",
        "fallback_reason": reason,
        "candidate_sources": candidate.get("sources", []),
        "reports": {
            "market": candidate_signal.reason if candidate_signal else "No current market signal was available.",
        },
    }
    if graph_result and graph_result.get("status") == "failed":
        result["graph_status"] = "failed"
        result["graph_error"] = graph_result.get("error", "unknown graph failure")
        result["graph_error_type"] = graph_result.get(
            "error_type",
            "UnknownTickerWorkerFailure",
        )
        result["graph_error_stage"] = graph_result.get(
            "error_stage",
            "ticker_graph",
        )
    return result


def _write_overnight_ticker_report(output_dir: Path, result: dict) -> None:
    symbol = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in result["symbol"])
    report_dir = output_dir / "ticker_reports" / symbol
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "summary.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    reports = result.get("reports") or {}
    for name, content in reports.items():
        (report_dir / f"{name}.md").write_text(str(content), encoding="utf-8")


def _rank_overnight_results(results: list[dict]) -> list[dict]:
    ranked = [
        {
            "symbol": result["symbol"],
            "score": result.get("score", "0.00"),
            "rating": result.get("rating", "Hold"),
            "signal": result.get("signal", ""),
            "status": result.get("status", "unknown"),
            "method": result.get("method", "full_graph"),
            "reason": (
                (result.get("reports") or {}).get("market")
                or result.get("fallback_reason")
                or result.get("final_trade_decision")
                or ""
            ),
            "fallback_reason": result.get("fallback_reason", ""),
        }
        for result in results
        if result.get("status") in {"ok", "fallback"}
    ]
    return sorted(
        ranked,
        key=lambda item: (Decimal(str(item["score"])), item["symbol"]),
        reverse=True,
    )


def _build_original_tradingagents_graph_packet(
    *,
    ticker_results: list[dict],
    full_graph_tickers: int,
    per_ticker_timeout_minutes: float,
    time_budget_minutes: float,
    graph_config: dict,
) -> dict:
    full_graph_methods = {
        "original_tradingagents_graph",
        "original_tradingagents_graph_bounded_prefetch_retry",
    }
    selected: list[str] = []
    successful: list[str] = []
    failed: list[str] = []
    fallback: list[str] = []

    for result in ticker_results:
        symbol = str(result.get("symbol") or "").upper()
        if not symbol:
            continue
        method = result.get("method")
        graph_status = result.get("graph_status")
        if method in full_graph_methods or graph_status == "failed":
            selected.append(symbol)
        if method in full_graph_methods and result.get("status") == "ok":
            successful.append(symbol)
        if graph_status == "failed":
            failed.append(symbol)
        if result.get("status") == "fallback":
            fallback.append(symbol)

    return {
        "schema_version": 1,
        "analysis_only": True,
        "execution_authority": "none",
        "enabled": full_graph_tickers > 0,
        "selection_rule": (
            "Run the original TradingAgents graph for the highest-ranked tradable "
            "candidates until full_graph_limit or the soft time budget is exhausted; "
            "score all remaining symbols with the deterministic market snapshot fallback."
        ),
        "selected_tickers": selected,
        "successful_tickers": successful,
        "failed_tickers": failed,
        "fallback_tickers": fallback,
        "bounds": {
            "full_graph_limit": full_graph_tickers,
            "per_ticker_timeout_minutes": per_ticker_timeout_minutes,
            "time_budget_minutes": time_budget_minutes,
            "graph_profile": graph_config.get("graph_profile"),
            "max_completion_tokens": graph_config.get("max_completion_tokens"),
            "max_output_tokens": graph_config.get("max_output_tokens"),
            "llm_timeout_seconds": graph_config.get("llm_timeout_seconds"),
            "llm_max_retries": graph_config.get("llm_max_retries"),
            "max_recur_limit": graph_config.get("max_recur_limit"),
            "max_debate_rounds": graph_config.get("max_debate_rounds"),
            "max_risk_discuss_rounds": graph_config.get("max_risk_discuss_rounds"),
        },
        "graph_config": graph_config,
    }


def _summary_payload(summary_packet: Any) -> dict[str, Any]:
    payload = getattr(summary_packet, "payload", None)
    if isinstance(payload, dict):
        return payload
    if hasattr(summary_packet, "model_dump"):
        dumped = summary_packet.model_dump()
        if isinstance(dumped, dict) and isinstance(dumped.get("payload"), dict):
            return dumped["payload"]
    return {}


def _write_overnight_top_provider_bundles(
    ranked: Sequence[Mapping[str, Any]],
    *,
    top_n: int,
    output_dir: Path,
    cache_dir: Path,
    provider_config_path: Path = Path("config/research_provider_fallbacks.json"),
    broker_snapshot_dir: Path = Path("results/hourly_supervisor"),
    source_quality_review_path: Path | None = None,
    depleted_sources: set[str] | None = None,
    disabled_sources: set[str] | None = None,
    max_packets_per_need: int = 3,
) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "analysis_only": True,
        "execution_authority": "none",
        "enabled": top_n > 0,
        "top_n": max(0, int(top_n)),
        "evidence_needs": list(OVERNIGHT_TOP_PROVIDER_EVIDENCE_NEEDS),
        "symbols": [],
        "bundle_count": 0,
        "source_packet_count": 0,
        "summary_packet_paths": {},
        "gap_packet_count": 0,
        "unsupported_route_count": 0,
        "blocked_packet_attempt_count": 0,
        "evidence_needs_without_non_gap_packets": [],
        "symbols_with_missing_non_gap": [],
        "bundle_summaries": [],
        "errors": [],
        "error_count": 0,
    }
    if top_n <= 0:
        return summary

    symbols: list[str] = []
    seen: set[str] = set()
    for item in ranked:
        if not isinstance(item, Mapping):
            continue
        symbol = str(item.get("symbol") or "").strip().upper()
        if not symbol or symbol in seen:
            continue
        symbols.append(symbol)
        seen.add(symbol)
        if len(symbols) >= top_n:
            break
    summary["symbols"] = symbols
    if not symbols:
        return summary

    missing_needs: set[str] = set()
    symbols_with_missing: set[str] = set()
    output_dir.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)

    for symbol in symbols:
        try:
            result = build_ticker_provider_research_packets(
                symbol,
                evidence_needs=OVERNIGHT_TOP_PROVIDER_EVIDENCE_NEEDS,
                provider_config_path=provider_config_path,
                depleted_sources=depleted_sources or set(),
                disabled_sources=disabled_sources or set(),
                max_packets_per_need=max_packets_per_need,
                cache_dir=cache_dir,
                broker_snapshot_dir=broker_snapshot_dir,
                source_quality_review_path=source_quality_review_path,
            )
        except Exception as exc:
            summary["errors"].append(
                {
                    "symbol": symbol,
                    "error_type": type(exc).__name__,
                    "error": _compact_cli_error_reason(exc),
                }
            )
            continue

        source_packet_paths = {
            packet.packet_id: str(write_research_packet(packet, output_dir))
            for packet in result.packets
        }
        summary_packet_path = (
            write_research_packet(result.summary_packet, output_dir)
            if result.summary_packet is not None
            else None
        )
        payload = _summary_payload(result.summary_packet)
        needs_without_non_gap = [
            str(need)
            for need in payload.get("evidence_needs_without_non_gap_packets") or []
            if str(need).strip()
        ]
        if needs_without_non_gap:
            missing_needs.update(needs_without_non_gap)
            symbols_with_missing.add(symbol)
        bundle_summary = {
            "symbol": symbol,
            "source_packet_count": len(result.packets),
            "source_packet_paths": source_packet_paths,
            "summary_packet_path": str(summary_packet_path) if summary_packet_path else None,
            "gap_packet_count": int(payload.get("gap_packet_count") or 0),
            "unsupported_route_count": int(payload.get("unsupported_route_count") or 0),
            "blocked_packet_attempt_count": int(payload.get("blocked_packet_attempt_count") or 0),
            "evidence_needs_without_non_gap_packets": sorted(set(needs_without_non_gap)),
        }
        summary["bundle_summaries"].append(bundle_summary)
        summary["source_packet_count"] += len(result.packets)
        summary["gap_packet_count"] += bundle_summary["gap_packet_count"]
        summary["unsupported_route_count"] += bundle_summary["unsupported_route_count"]
        summary["blocked_packet_attempt_count"] += bundle_summary["blocked_packet_attempt_count"]
        if summary_packet_path:
            summary["summary_packet_paths"][symbol] = str(summary_packet_path)

    summary["bundle_count"] = len(summary["bundle_summaries"])
    summary["evidence_needs_without_non_gap_packets"] = sorted(missing_needs)
    summary["symbols_with_missing_non_gap"] = sorted(symbols_with_missing)
    summary["error_count"] = len(summary["errors"])
    return summary


def _compact_overnight_plan_payload(packet: Mapping[str, Any], packet_path: Path | str) -> dict[str, Any]:
    return compact_overnight_plan_payload(packet, packet_path)


def _compact_premarket_brief_payload(packet: Mapping[str, Any], packet_path: Path | str) -> dict[str, Any]:
    return compact_premarket_brief_payload(packet, packet_path)


def _compact_hourly_supervisor_payload(packet: Mapping[str, Any], packet_path: Path | str) -> dict[str, Any]:
    return compact_hourly_supervisor_payload(packet, packet_path)


def _write_supervisor_daily_report_packet(packet: dict[str, Any], output_dir: Path | str) -> Path:
    return write_supervisor_daily_report_packet(packet, output_dir)


def _compact_supervisor_daily_report_payload(packet: Mapping[str, Any], packet_path: Path | str) -> dict[str, Any]:
    return compact_supervisor_daily_report_payload(packet, packet_path)


def _latest_packet_path(
    output_dir: Path,
    pattern: str,
    latest_name: str = "latest.json",
    *,
    recursive: bool = False,
) -> Path | None:
    latest = output_dir / latest_name
    if latest.exists():
        return latest
    if not output_dir.exists():
        return None
    iterator = output_dir.rglob(pattern) if recursive else output_dir.glob(pattern)
    paths = [path for path in iterator if _is_raw_json_packet_path(path)]
    if not paths:
        return None
    return max(paths, key=lambda path: path.stat().st_mtime)


def _compact_output_audit_row(
    label: str,
    raw_path: Path | None,
    compact_payload: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if raw_path is None or compact_payload is None:
        return {
            "label": label,
            "status": "missing",
            "raw_packet_path": str(raw_path) if raw_path else None,
            "raw_bytes": 0,
            "compact_bytes": 0,
            "byte_reduction": 0,
            "reduction_pct": None,
            "lossless_by_reference": False,
        }
    raw_bytes = raw_path.stat().st_size
    compact_text = json.dumps(compact_payload, indent=2)
    compact_bytes = len(compact_text.encode("utf-8"))
    byte_reduction = max(0, raw_bytes - compact_bytes)
    reduction_pct = round((byte_reduction / raw_bytes) * 100, 2) if raw_bytes else None
    return {
        "label": label,
        "status": "measured",
        "raw_packet_path": str(raw_path),
        "schema": compact_payload.get("schema"),
        "raw_bytes": raw_bytes,
        "compact_bytes": compact_bytes,
        "byte_reduction": byte_reduction,
        "reduction_pct": reduction_pct,
        "lossless_by_reference": bool(
            compact_payload.get("raw_packet_path")
            and compact_payload.get("raw_field_groups")
        ),
    }


def _render_compact_output_audit_markdown(packet: Mapping[str, Any]) -> str:
    lines = [
        "# Compact Output Byte-Reduction Audit",
        "",
        f"Generated: {packet.get('generated_at')}",
        "",
        "| Family | Raw bytes | Compact bytes | Reduction | Lossless ref | Raw packet |",
        "| --- | ---: | ---: | ---: | --- | --- |",
    ]
    for row in packet.get("rows") or []:
        reduction = (
            f"{row.get('reduction_pct')}%"
            if row.get("reduction_pct") is not None
            else "missing"
        )
        lines.append(
            "| "
            f"{row.get('label')} | "
            f"{row.get('raw_bytes')} | "
            f"{row.get('compact_bytes')} | "
            f"{reduction} | "
            f"{row.get('lossless_by_reference')} | "
            f"{row.get('raw_packet_path') or ''} |"
        )
    lines.extend(
        [
            "",
            "Compact payloads are intentionally lossy in stdout but lossless by reference: "
            "`raw_packet_path` plus `raw_field_groups` points readers back to the full packet.",
        ]
    )
    return "\n".join(lines) + "\n"


def _build_compact_output_audit_packet(
    *,
    hourly_log_dir: Path,
    overnight_log_dir: Path,
    premarket_brief_log_dir: Path,
    daily_report_log_dir: Path,
    automation_health_dir: Path,
) -> dict[str, Any]:
    hourly_path = _latest_packet_path(hourly_log_dir, "hourly-supervisor-*.json")
    overnight_path = _latest_packet_path(overnight_log_dir, "overnight-plan-*.json")
    premarket_path = _latest_packet_path(premarket_brief_log_dir, "premarket-brief-*.json")
    daily_path = _latest_packet_path(
        daily_report_log_dir,
        "supervisor-daily-report-*.json",
        recursive=True,
    )
    automation_health_path = _latest_packet_path(
        automation_health_dir,
        "automation-health-audit-*.json",
    )

    hourly_packet = _read_json_packet(hourly_path)
    overnight_packet = _read_json_packet(overnight_path)
    premarket_packet = _read_json_packet(premarket_path)
    daily_packet = _read_json_packet(daily_path)
    automation_health_packet = _read_json_packet(automation_health_path)

    rows = [
        _compact_output_audit_row(
            "hourly_supervisor",
            hourly_path,
            _compact_hourly_supervisor_payload(hourly_packet, hourly_path)
            if hourly_packet and hourly_path
            else None,
        ),
        _compact_output_audit_row(
            "overnight_plan",
            overnight_path,
            _compact_overnight_plan_payload(overnight_packet, overnight_path)
            if overnight_packet and overnight_path
            else None,
        ),
        _compact_output_audit_row(
            "premarket_brief",
            premarket_path,
            _compact_premarket_brief_payload(premarket_packet, premarket_path)
            if premarket_packet and premarket_path
            else None,
        ),
        _compact_output_audit_row(
            "supervisor_daily_report",
            daily_path,
            _compact_supervisor_daily_report_payload(daily_packet, daily_path)
            if daily_packet and daily_path
            else None,
        ),
        _compact_output_audit_row(
            "automation_health_audit",
            automation_health_path,
            _build_compact_automation_health_audit(
                {
                    **automation_health_packet,
                    "json_path": str(automation_health_path),
                    "markdown_path": str(automation_health_path.with_suffix(".md")),
                }
            )
            if automation_health_packet and automation_health_path
            else None,
        ),
    ]
    measured = [row for row in rows if row.get("status") == "measured"]
    return {
        "generated_at": datetime.datetime.now(tz=datetime.timezone.utc).isoformat(timespec="seconds"),
        "analysis_only": True,
        "can_submit_orders": False,
        "execution_authority": "none",
        "status": "success" if measured else "missing_packets",
        "row_count": len(rows),
        "measured_count": len(measured),
        "total_raw_bytes": sum(int(row.get("raw_bytes") or 0) for row in measured),
        "total_compact_bytes": sum(int(row.get("compact_bytes") or 0) for row in measured),
        "total_byte_reduction": sum(int(row.get("byte_reduction") or 0) for row in measured),
        "rows": rows,
    }


# Create a deque to store recent messages with a maximum length
class MessageBuffer:
    # Fixed teams that always run (not user-selectable)
    FIXED_AGENTS = {
        "Research Team": ["Bull Researcher", "Bear Researcher", "Research Manager"],
        "Trading Team": ["Trader"],
        "Risk Management": ["Aggressive Analyst", "Neutral Analyst", "Conservative Analyst"],
        "Portfolio Management": ["Portfolio Manager"],
    }

    # Analyst name mapping
    ANALYST_MAPPING = {
        "market": "Market Analyst",
        "social": "Sentiment Analyst",
        "news": "News Analyst",
        "fundamentals": "Fundamentals Analyst",
    }

    # Report section mapping: section -> (analyst_key for filtering, finalizing_agent)
    # analyst_key: which analyst selection controls this section (None = always included)
    # finalizing_agent: which agent must be "completed" for this report to count as done
    REPORT_SECTIONS = {
        "market_report": ("market", "Market Analyst"),
        "sentiment_report": ("social", "Sentiment Analyst"),
        "news_report": ("news", "News Analyst"),
        "fundamentals_report": ("fundamentals", "Fundamentals Analyst"),
        "investment_plan": (None, "Research Manager"),
        "trader_investment_plan": (None, "Trader"),
        "final_trade_decision": (None, "Portfolio Manager"),
    }

    def __init__(self, max_length=100):
        self.messages = deque(maxlen=max_length)
        self.tool_calls = deque(maxlen=max_length)
        self.current_report = None
        self.final_report = None  # Store the complete final report
        self.agent_status = {}
        self.current_agent = None
        self.report_sections = {}
        self.selected_analysts = []
        self._processed_message_ids = set()

    def init_for_analysis(self, selected_analysts):
        """Initialize agent status and report sections based on selected analysts.

        Args:
            selected_analysts: List of analyst type strings (e.g., ["market", "news"])
        """
        self.selected_analysts = [a.lower() for a in selected_analysts]

        # Build agent_status dynamically
        self.agent_status = {}

        # Add selected analysts
        for analyst_key in self.selected_analysts:
            if analyst_key in self.ANALYST_MAPPING:
                self.agent_status[self.ANALYST_MAPPING[analyst_key]] = "pending"

        # Add fixed teams
        for team_agents in self.FIXED_AGENTS.values():
            for agent in team_agents:
                self.agent_status[agent] = "pending"

        # Build report_sections dynamically
        self.report_sections = {}
        for section, (analyst_key, _) in self.REPORT_SECTIONS.items():
            if analyst_key is None or analyst_key in self.selected_analysts:
                self.report_sections[section] = None

        # Reset other state
        self.current_report = None
        self.final_report = None
        self.current_agent = None
        self.messages.clear()
        self.tool_calls.clear()
        self._processed_message_ids.clear()

    def get_completed_reports_count(self):
        """Count reports that are finalized (their finalizing agent is completed).

        A report is considered complete when:
        1. The report section has content (not None), AND
        2. The agent responsible for finalizing that report has status "completed"

        This prevents interim updates (like debate rounds) from counting as completed.
        """
        count = 0
        for section in self.report_sections:
            if section not in self.REPORT_SECTIONS:
                continue
            _, finalizing_agent = self.REPORT_SECTIONS[section]
            # Report is complete if it has content AND its finalizing agent is done
            has_content = self.report_sections.get(section) is not None
            agent_done = self.agent_status.get(finalizing_agent) == "completed"
            if has_content and agent_done:
                count += 1
        return count

    def add_message(self, message_type, content):
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        self.messages.append((timestamp, message_type, content))

    def add_tool_call(self, tool_name, args):
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        self.tool_calls.append((timestamp, tool_name, args))

    def update_agent_status(self, agent, status):
        if agent in self.agent_status:
            self.agent_status[agent] = status
            self.current_agent = agent

    def update_report_section(self, section_name, content):
        if section_name in self.report_sections:
            self.report_sections[section_name] = content
            self._update_current_report()

    def _update_current_report(self):
        # For the panel display, only show the most recently updated section
        latest_section = None
        latest_content = None

        # Find the most recently updated section
        for section, content in self.report_sections.items():
            if content is not None:
                latest_section = section
                latest_content = content
               
        if latest_section and latest_content:
            # Format the current section for display
            section_titles = {
                "market_report": "Market Analysis",
                "sentiment_report": "Social Sentiment",
                "news_report": "News Analysis",
                "fundamentals_report": "Fundamentals Analysis",
                "investment_plan": "Research Team Decision",
                "trader_investment_plan": "Trading Team Plan",
                "final_trade_decision": "Portfolio Management Decision",
            }
            self.current_report = (
                f"### {section_titles[latest_section]}\n{latest_content}"
            )

        # Update the final complete report
        self._update_final_report()

    def _update_final_report(self):
        report_parts = []

        # Analyst Team Reports - use .get() to handle missing sections
        analyst_sections = ["market_report", "sentiment_report", "news_report", "fundamentals_report"]
        if any(self.report_sections.get(section) for section in analyst_sections):
            report_parts.append("## Analyst Team Reports")
            if self.report_sections.get("market_report"):
                report_parts.append(
                    f"### Market Analysis\n{self.report_sections['market_report']}"
                )
            if self.report_sections.get("sentiment_report"):
                report_parts.append(
                    f"### Social Sentiment\n{self.report_sections['sentiment_report']}"
                )
            if self.report_sections.get("news_report"):
                report_parts.append(
                    f"### News Analysis\n{self.report_sections['news_report']}"
                )
            if self.report_sections.get("fundamentals_report"):
                report_parts.append(
                    f"### Fundamentals Analysis\n{self.report_sections['fundamentals_report']}"
                )

        # Research Team Reports
        if self.report_sections.get("investment_plan"):
            report_parts.append("## Research Team Decision")
            report_parts.append(f"{self.report_sections['investment_plan']}")

        # Trading Team Reports
        if self.report_sections.get("trader_investment_plan"):
            report_parts.append("## Trading Team Plan")
            report_parts.append(f"{self.report_sections['trader_investment_plan']}")

        # Portfolio Management Decision
        if self.report_sections.get("final_trade_decision"):
            report_parts.append("## Portfolio Management Decision")
            report_parts.append(f"{self.report_sections['final_trade_decision']}")

        self.final_report = "\n\n".join(report_parts) if report_parts else None


message_buffer = MessageBuffer()


def create_layout():
    layout = Layout()
    layout.split_column(
        Layout(name="header", size=3),
        Layout(name="main"),
        Layout(name="footer", size=3),
    )
    layout["main"].split_column(
        Layout(name="upper", ratio=3), Layout(name="analysis", ratio=5)
    )
    layout["upper"].split_row(
        Layout(name="progress", ratio=2), Layout(name="messages", ratio=3)
    )
    return layout


def format_tokens(n):
    """Format token count for display."""
    if n >= 1000:
        return f"{n/1000:.1f}k"
    return str(n)


def update_display(layout, spinner_text=None, stats_handler=None, start_time=None):
    # Header with welcome message
    layout["header"].update(
        Panel(
            "[bold green]Welcome to TradingAgents CLI[/bold green]\n"
            "[dim]© [Tauric Research](https://github.com/TauricResearch)[/dim]",
            title="Welcome to TradingAgents",
            border_style="green",
            padding=(1, 2),
            expand=True,
        )
    )

    # Progress panel showing agent status
    progress_table = Table(
        show_header=True,
        header_style="bold magenta",
        show_footer=False,
        box=box.SIMPLE_HEAD,  # Use simple header with horizontal lines
        title=None,  # Remove the redundant Progress title
        padding=(0, 2),  # Add horizontal padding
        expand=True,  # Make table expand to fill available space
    )
    progress_table.add_column("Team", style="cyan", justify="center", width=20)
    progress_table.add_column("Agent", style="green", justify="center", width=20)
    progress_table.add_column("Status", style="yellow", justify="center", width=20)

    # Group agents by team - filter to only include agents in agent_status
    all_teams = {
        "Analyst Team": [
            "Market Analyst",
            "Sentiment Analyst",
            "News Analyst",
            "Fundamentals Analyst",
        ],
        "Research Team": ["Bull Researcher", "Bear Researcher", "Research Manager"],
        "Trading Team": ["Trader"],
        "Risk Management": ["Aggressive Analyst", "Neutral Analyst", "Conservative Analyst"],
        "Portfolio Management": ["Portfolio Manager"],
    }

    # Filter teams to only include agents that are in agent_status
    teams = {}
    for team, agents in all_teams.items():
        active_agents = [a for a in agents if a in message_buffer.agent_status]
        if active_agents:
            teams[team] = active_agents

    for team, agents in teams.items():
        # Add first agent with team name
        first_agent = agents[0]
        status = message_buffer.agent_status.get(first_agent, "pending")
        if status == "in_progress":
            spinner = Spinner(
                "dots", text="[blue]in_progress[/blue]", style="bold cyan"
            )
            status_cell = spinner
        else:
            status_color = {
                "pending": "yellow",
                "completed": "green",
                "error": "red",
            }.get(status, "white")
            status_cell = f"[{status_color}]{status}[/{status_color}]"
        progress_table.add_row(team, first_agent, status_cell)

        # Add remaining agents in team
        for agent in agents[1:]:
            status = message_buffer.agent_status.get(agent, "pending")
            if status == "in_progress":
                spinner = Spinner(
                    "dots", text="[blue]in_progress[/blue]", style="bold cyan"
                )
                status_cell = spinner
            else:
                status_color = {
                    "pending": "yellow",
                    "completed": "green",
                    "error": "red",
                }.get(status, "white")
                status_cell = f"[{status_color}]{status}[/{status_color}]"
            progress_table.add_row("", agent, status_cell)

        # Add horizontal line after each team
        progress_table.add_row("─" * 20, "─" * 20, "─" * 20, style="dim")

    layout["progress"].update(
        Panel(progress_table, title="Progress", border_style="cyan", padding=(1, 2))
    )

    # Messages panel showing recent messages and tool calls
    messages_table = Table(
        show_header=True,
        header_style="bold magenta",
        show_footer=False,
        expand=True,  # Make table expand to fill available space
        box=box.MINIMAL,  # Use minimal box style for a lighter look
        show_lines=True,  # Keep horizontal lines
        padding=(0, 1),  # Add some padding between columns
    )
    messages_table.add_column("Time", style="cyan", width=8, justify="center")
    messages_table.add_column("Type", style="green", width=10, justify="center")
    messages_table.add_column(
        "Content", style="white", no_wrap=False, ratio=1
    )  # Make content column expand

    # Combine tool calls and messages
    all_messages = []

    # Add tool calls
    for timestamp, tool_name, args in message_buffer.tool_calls:
        formatted_args = format_tool_args(args)
        all_messages.append((timestamp, "Tool", f"{tool_name}: {formatted_args}"))

    # Add regular messages
    for timestamp, msg_type, content in message_buffer.messages:
        content_str = str(content) if content else ""
        if len(content_str) > 200:
            content_str = content_str[:197] + "..."
        all_messages.append((timestamp, msg_type, content_str))

    # Sort by timestamp descending (newest first)
    all_messages.sort(key=lambda x: x[0], reverse=True)

    # Calculate how many messages we can show based on available space
    max_messages = 12

    # Get the first N messages (newest ones)
    recent_messages = all_messages[:max_messages]

    # Add messages to table (already in newest-first order)
    for timestamp, msg_type, content in recent_messages:
        # Format content with word wrapping
        wrapped_content = Text(content, overflow="fold")
        messages_table.add_row(timestamp, msg_type, wrapped_content)

    layout["messages"].update(
        Panel(
            messages_table,
            title="Messages & Tools",
            border_style="blue",
            padding=(1, 2),
        )
    )

    # Analysis panel showing current report
    if message_buffer.current_report:
        layout["analysis"].update(
            Panel(
                Markdown(message_buffer.current_report),
                title="Current Report",
                border_style="green",
                padding=(1, 2),
            )
        )
    else:
        layout["analysis"].update(
            Panel(
                "[italic]Waiting for analysis report...[/italic]",
                title="Current Report",
                border_style="green",
                padding=(1, 2),
            )
        )

    # Footer with statistics
    # Agent progress - derived from agent_status dict
    agents_completed = sum(
        1 for status in message_buffer.agent_status.values() if status == "completed"
    )
    agents_total = len(message_buffer.agent_status)

    # Report progress - based on agent completion (not just content existence)
    reports_completed = message_buffer.get_completed_reports_count()
    reports_total = len(message_buffer.report_sections)

    # Build stats parts
    stats_parts = [f"Agents: {agents_completed}/{agents_total}"]

    # LLM and tool stats from callback handler
    if stats_handler:
        stats = stats_handler.get_stats()
        stats_parts.append(f"LLM: {stats['llm_calls']}")
        stats_parts.append(f"Tools: {stats['tool_calls']}")

        # Token display with graceful fallback
        if stats["tokens_in"] > 0 or stats["tokens_out"] > 0:
            tokens_str = f"Tokens: {format_tokens(stats['tokens_in'])}\u2191 {format_tokens(stats['tokens_out'])}\u2193"
        else:
            tokens_str = "Tokens: --"
        stats_parts.append(tokens_str)

    stats_parts.append(f"Reports: {reports_completed}/{reports_total}")

    # Elapsed time
    if start_time:
        elapsed = time.time() - start_time
        elapsed_str = f"\u23f1 {int(elapsed // 60):02d}:{int(elapsed % 60):02d}"
        stats_parts.append(elapsed_str)

    stats_table = Table(show_header=False, box=None, padding=(0, 2), expand=True)
    stats_table.add_column("Stats", justify="center")
    stats_table.add_row(" | ".join(stats_parts))

    layout["footer"].update(Panel(stats_table, border_style="grey50"))


def get_user_selections():
    """Get all user selections before starting the analysis display."""
    # Display ASCII art welcome message
    with open(Path(__file__).parent / "static" / "welcome.txt", encoding="utf-8") as f:
        welcome_ascii = f.read()

    # Create welcome box content
    welcome_content = f"{welcome_ascii}\n"
    welcome_content += "[bold green]TradingAgents: Multi-Agents LLM Financial Trading Framework - CLI[/bold green]\n\n"
    welcome_content += "[bold]Workflow Steps:[/bold]\n"
    welcome_content += "I. Analyst Team → II. Research Team → III. Trader → IV. Risk Management → V. Portfolio Management\n\n"
    welcome_content += (
        "[dim]Built by [Tauric Research](https://github.com/TauricResearch)[/dim]"
    )

    # Create and center the welcome box
    welcome_box = Panel(
        welcome_content,
        border_style="green",
        padding=(1, 2),
        title="Welcome to TradingAgents",
        subtitle="Multi-Agents LLM Financial Trading Framework",
    )
    console.print(Align.center(welcome_box))
    console.print()
    console.print()  # Add vertical space before announcements

    # Fetch and display announcements (silent on failure)
    announcements = fetch_announcements()
    display_announcements(console, announcements)

    # Create a boxed questionnaire for each step
    def create_question_box(title, prompt, default=None):
        box_content = f"[bold]{title}[/bold]\n"
        box_content += f"[dim]{prompt}[/dim]"
        if default:
            box_content += f"\n[dim]Default: {default}[/dim]"
        return Panel(box_content, border_style="blue", padding=(1, 2))

    # Step 1: Ticker symbol
    console.print(
        create_question_box(
            "Step 1: Ticker Symbol",
            "Enter the exact ticker symbol to analyze, including exchange suffix when needed (examples: SPY, CNC.TO, 7203.T, 0700.HK)",
            "SPY",
        )
    )
    selected_ticker = get_ticker()
    asset_type = detect_asset_type(selected_ticker)
    console.print(
        f"[green]Detected asset type:[/green] {asset_type.value}"
    )

    # Step 2: Analysis date
    default_date = datetime.datetime.now().strftime("%Y-%m-%d")
    console.print(
        create_question_box(
            "Step 2: Analysis Date",
            "Enter the analysis date (YYYY-MM-DD)",
            default_date,
        )
    )
    analysis_date = get_analysis_date()

    # Step 3: Output language
    console.print(
        create_question_box(
            "Step 3: Output Language",
            "Select the language for analyst reports and final decision"
        )
    )
    output_language = ask_output_language()

    # Step 4: Select analysts
    console.print(
        create_question_box(
            "Step 4: Analysts Team", "Select your LLM analyst agents for the analysis"
        )
    )
    selected_analysts = select_analysts(asset_type)
    console.print(
        f"[green]Selected analysts:[/green] {', '.join(analyst.value for analyst in selected_analysts)}"
    )

    # Step 5: Research depth
    console.print(
        create_question_box(
            "Step 5: Research Depth", "Select your research depth level"
        )
    )
    selected_research_depth = select_research_depth()

    # Step 6: LLM Provider
    console.print(
        create_question_box(
            "Step 6: LLM Provider", "Select your LLM provider"
        )
    )
    selected_llm_provider, backend_url = select_llm_provider()

    # Providers with regional endpoints prompt for the region as a secondary
    # step so the main dropdown stays clean (mainland China and international
    # accounts cannot share API keys).
    if selected_llm_provider == "qwen":
        selected_llm_provider, backend_url = ask_qwen_region()
    elif selected_llm_provider == "minimax":
        selected_llm_provider, backend_url = ask_minimax_region()
    elif selected_llm_provider == "glm":
        selected_llm_provider, backend_url = ask_glm_region()

    # For Ollama, surface the resolved endpoint (OLLAMA_BASE_URL vs default)
    # before model selection so it's obvious where we're connecting.
    if selected_llm_provider == "ollama":
        confirm_ollama_endpoint(backend_url)

    # Confirm the provider's API key is present; prompt the user to paste
    # one and persist it to .env if it's missing, so the analysis run
    # doesn't fail later at the first API call.
    ensure_api_key(selected_llm_provider)

    # Step 7: Thinking agents
    console.print(
        create_question_box(
            "Step 7: Thinking Agents", "Select your thinking agents for analysis"
        )
    )
    selected_shallow_thinker = select_shallow_thinking_agent(selected_llm_provider)
    selected_deep_thinker = select_deep_thinking_agent(selected_llm_provider)

    # Step 8: Provider-specific thinking configuration
    thinking_level = None
    reasoning_effort = None
    anthropic_effort = None

    provider_lower = selected_llm_provider.lower()
    if provider_lower == "google":
        console.print(
            create_question_box(
                "Step 8: Thinking Mode",
                "Configure Gemini thinking mode"
            )
        )
        thinking_level = ask_gemini_thinking_config()
    elif provider_lower == "openai":
        console.print(
            create_question_box(
                "Step 8: Reasoning Effort",
                "Configure OpenAI reasoning effort level"
            )
        )
        reasoning_effort = ask_openai_reasoning_effort()
    elif provider_lower == "anthropic":
        console.print(
            create_question_box(
                "Step 8: Effort Level",
                "Configure Claude effort level"
            )
        )
        anthropic_effort = ask_anthropic_effort()

    return {
        "ticker": selected_ticker,
        "asset_type": asset_type.value,
        "analysis_date": analysis_date,
        "analysts": selected_analysts,
        "research_depth": selected_research_depth,
        "llm_provider": selected_llm_provider.lower(),
        "backend_url": backend_url,
        "shallow_thinker": selected_shallow_thinker,
        "deep_thinker": selected_deep_thinker,
        "google_thinking_level": thinking_level,
        "openai_reasoning_effort": reasoning_effort,
        "anthropic_effort": anthropic_effort,
        "output_language": output_language,
    }


def get_ticker():
    """Get ticker symbol from user input, preserving exchange suffixes."""
    # typer.prompt strips trailing dot-suffixes on some shells (e.g. 000404.SH
    # collapses to 000404). questionary.text reads the raw line.
    ticker = questionary.text(
        "",
        validate=lambda value: (
            not value.strip()
            or (
                all(ch.isalnum() or ch in "._-^" for ch in value.strip())
                and len(value.strip()) <= 32
            )
        )
        or "Please enter a valid ticker symbol, e.g. AAPL, 000404.SZ, 0700.HK.",
    ).ask()

    if ticker is None:
        console.print("\n[red]No ticker symbol provided. Exiting...[/red]")
        raise typer.Exit(1)

    return (ticker.strip() or "SPY").upper()


def get_analysis_date():
    """Get the analysis date from user input."""
    while True:
        date_str = typer.prompt(
            "", default=datetime.datetime.now().strftime("%Y-%m-%d")
        )
        try:
            # Validate date format and ensure it's not in the future
            analysis_date = datetime.datetime.strptime(date_str, "%Y-%m-%d")
            if analysis_date.date() > datetime.datetime.now().date():
                console.print("[red]Error: Analysis date cannot be in the future[/red]")
                continue
            return date_str
        except ValueError:
            console.print(
                "[red]Error: Invalid date format. Please use YYYY-MM-DD[/red]"
            )


def save_report_to_disk(final_state, ticker: str, save_path: Path):
    """Save complete analysis report to disk with organized subfolders."""
    save_path.mkdir(parents=True, exist_ok=True)
    sections = []

    # 1. Analysts
    analysts_dir = save_path / "1_analysts"
    analyst_parts = []
    if final_state.get("market_report"):
        analysts_dir.mkdir(exist_ok=True)
        (analysts_dir / "market.md").write_text(final_state["market_report"], encoding="utf-8")
        analyst_parts.append(("Market Analyst", final_state["market_report"]))
    if final_state.get("sentiment_report"):
        analysts_dir.mkdir(exist_ok=True)
        (analysts_dir / "sentiment.md").write_text(final_state["sentiment_report"], encoding="utf-8")
        analyst_parts.append(("Sentiment Analyst", final_state["sentiment_report"]))
    if final_state.get("news_report"):
        analysts_dir.mkdir(exist_ok=True)
        (analysts_dir / "news.md").write_text(final_state["news_report"], encoding="utf-8")
        analyst_parts.append(("News Analyst", final_state["news_report"]))
    if final_state.get("fundamentals_report"):
        analysts_dir.mkdir(exist_ok=True)
        (analysts_dir / "fundamentals.md").write_text(final_state["fundamentals_report"], encoding="utf-8")
        analyst_parts.append(("Fundamentals Analyst", final_state["fundamentals_report"]))
    if analyst_parts:
        content = "\n\n".join(f"### {name}\n{text}" for name, text in analyst_parts)
        sections.append(f"## I. Analyst Team Reports\n\n{content}")

    # 2. Research
    if final_state.get("investment_debate_state"):
        research_dir = save_path / "2_research"
        debate = final_state["investment_debate_state"]
        research_parts = []
        if debate.get("bull_history"):
            research_dir.mkdir(exist_ok=True)
            (research_dir / "bull.md").write_text(debate["bull_history"], encoding="utf-8")
            research_parts.append(("Bull Researcher", debate["bull_history"]))
        if debate.get("bear_history"):
            research_dir.mkdir(exist_ok=True)
            (research_dir / "bear.md").write_text(debate["bear_history"], encoding="utf-8")
            research_parts.append(("Bear Researcher", debate["bear_history"]))
        if debate.get("judge_decision"):
            research_dir.mkdir(exist_ok=True)
            (research_dir / "manager.md").write_text(debate["judge_decision"], encoding="utf-8")
            research_parts.append(("Research Manager", debate["judge_decision"]))
        if research_parts:
            content = "\n\n".join(f"### {name}\n{text}" for name, text in research_parts)
            sections.append(f"## II. Research Team Decision\n\n{content}")

    # 3. Trading
    if final_state.get("trader_investment_plan"):
        trading_dir = save_path / "3_trading"
        trading_dir.mkdir(exist_ok=True)
        (trading_dir / "trader.md").write_text(final_state["trader_investment_plan"], encoding="utf-8")
        sections.append(f"## III. Trading Team Plan\n\n### Trader\n{final_state['trader_investment_plan']}")

    # 4. Risk Management
    if final_state.get("risk_debate_state"):
        risk_dir = save_path / "4_risk"
        risk = final_state["risk_debate_state"]
        risk_parts = []
        if risk.get("aggressive_history"):
            risk_dir.mkdir(exist_ok=True)
            (risk_dir / "aggressive.md").write_text(risk["aggressive_history"], encoding="utf-8")
            risk_parts.append(("Aggressive Analyst", risk["aggressive_history"]))
        if risk.get("conservative_history"):
            risk_dir.mkdir(exist_ok=True)
            (risk_dir / "conservative.md").write_text(risk["conservative_history"], encoding="utf-8")
            risk_parts.append(("Conservative Analyst", risk["conservative_history"]))
        if risk.get("neutral_history"):
            risk_dir.mkdir(exist_ok=True)
            (risk_dir / "neutral.md").write_text(risk["neutral_history"], encoding="utf-8")
            risk_parts.append(("Neutral Analyst", risk["neutral_history"]))
        if risk_parts:
            content = "\n\n".join(f"### {name}\n{text}" for name, text in risk_parts)
            sections.append(f"## IV. Risk Management Team Decision\n\n{content}")

        # 5. Portfolio Manager
        if risk.get("judge_decision"):
            portfolio_dir = save_path / "5_portfolio"
            portfolio_dir.mkdir(exist_ok=True)
            (portfolio_dir / "decision.md").write_text(risk["judge_decision"], encoding="utf-8")
            sections.append(f"## V. Portfolio Manager Decision\n\n### Portfolio Manager\n{risk['judge_decision']}")

    # Write consolidated report
    header = f"# Trading Analysis Report: {ticker}\n\nGenerated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
    (save_path / "complete_report.md").write_text(header + "\n\n".join(sections), encoding="utf-8")
    return save_path / "complete_report.md"


def display_complete_report(final_state):
    """Display the complete analysis report sequentially (avoids truncation)."""
    console.print()
    console.print(Rule("Complete Analysis Report", style="bold green"))

    # I. Analyst Team Reports
    analysts = []
    if final_state.get("market_report"):
        analysts.append(("Market Analyst", final_state["market_report"]))
    if final_state.get("sentiment_report"):
        analysts.append(("Sentiment Analyst", final_state["sentiment_report"]))
    if final_state.get("news_report"):
        analysts.append(("News Analyst", final_state["news_report"]))
    if final_state.get("fundamentals_report"):
        analysts.append(("Fundamentals Analyst", final_state["fundamentals_report"]))
    if analysts:
        console.print(Panel("[bold]I. Analyst Team Reports[/bold]", border_style="cyan"))
        for title, content in analysts:
            console.print(Panel(Markdown(content), title=title, border_style="blue", padding=(1, 2)))

    # II. Research Team Reports
    if final_state.get("investment_debate_state"):
        debate = final_state["investment_debate_state"]
        research = []
        if debate.get("bull_history"):
            research.append(("Bull Researcher", debate["bull_history"]))
        if debate.get("bear_history"):
            research.append(("Bear Researcher", debate["bear_history"]))
        if debate.get("judge_decision"):
            research.append(("Research Manager", debate["judge_decision"]))
        if research:
            console.print(Panel("[bold]II. Research Team Decision[/bold]", border_style="magenta"))
            for title, content in research:
                console.print(Panel(Markdown(content), title=title, border_style="blue", padding=(1, 2)))

    # III. Trading Team
    if final_state.get("trader_investment_plan"):
        console.print(Panel("[bold]III. Trading Team Plan[/bold]", border_style="yellow"))
        console.print(Panel(Markdown(final_state["trader_investment_plan"]), title="Trader", border_style="blue", padding=(1, 2)))

    # IV. Risk Management Team
    if final_state.get("risk_debate_state"):
        risk = final_state["risk_debate_state"]
        risk_reports = []
        if risk.get("aggressive_history"):
            risk_reports.append(("Aggressive Analyst", risk["aggressive_history"]))
        if risk.get("conservative_history"):
            risk_reports.append(("Conservative Analyst", risk["conservative_history"]))
        if risk.get("neutral_history"):
            risk_reports.append(("Neutral Analyst", risk["neutral_history"]))
        if risk_reports:
            console.print(Panel("[bold]IV. Risk Management Team Decision[/bold]", border_style="red"))
            for title, content in risk_reports:
                console.print(Panel(Markdown(content), title=title, border_style="blue", padding=(1, 2)))

        # V. Portfolio Manager Decision
        if risk.get("judge_decision"):
            console.print(Panel("[bold]V. Portfolio Manager Decision[/bold]", border_style="green"))
            console.print(Panel(Markdown(risk["judge_decision"]), title="Portfolio Manager", border_style="blue", padding=(1, 2)))


def update_research_team_status(status):
    """Update status for research team members (not Trader)."""
    research_team = ["Bull Researcher", "Bear Researcher", "Research Manager"]
    for agent in research_team:
        message_buffer.update_agent_status(agent, status)


# Ordered list of analysts for status transitions
ANALYST_ORDER = ["market", "social", "news", "fundamentals"]
ANALYST_AGENT_NAMES = {
    "market": "Market Analyst",
    "social": "Sentiment Analyst",
    "news": "News Analyst",
    "fundamentals": "Fundamentals Analyst",
}
ANALYST_REPORT_MAP = {
    "market": "market_report",
    "social": "sentiment_report",
    "news": "news_report",
    "fundamentals": "fundamentals_report",
}


def update_analyst_statuses(message_buffer, chunk, wall_time_tracker=None):
    """Update analyst statuses based on accumulated report state.

    Logic:
    - Store new report content from the current chunk if present
    - Check accumulated report_sections (not just current chunk) for status
    - Analysts with reports = completed
    - First analyst without report = in_progress
    - Remaining analysts without reports = pending
    - When all analysts done, set Bull Researcher to in_progress
    """
    selected = message_buffer.selected_analysts
    found_active = False

    if wall_time_tracker is not None:
        sync_analyst_tracker_from_chunk(wall_time_tracker, chunk)

    for analyst_key in ANALYST_ORDER:
        if analyst_key not in selected:
            continue

        agent_name = ANALYST_AGENT_NAMES[analyst_key]
        report_key = ANALYST_REPORT_MAP[analyst_key]

        # Capture new report content from current chunk
        if chunk.get(report_key):
            message_buffer.update_report_section(report_key, chunk[report_key])

        # Determine status from accumulated sections, not just current chunk
        has_report = bool(message_buffer.report_sections.get(report_key))

        if has_report:
            message_buffer.update_agent_status(agent_name, "completed")
        elif not found_active:
            message_buffer.update_agent_status(agent_name, "in_progress")
            found_active = True
        else:
            message_buffer.update_agent_status(agent_name, "pending")

    # When all analysts complete, transition research team to in_progress
    if not found_active and selected and message_buffer.agent_status.get("Bull Researcher") == "pending":
        message_buffer.update_agent_status("Bull Researcher", "in_progress")

def extract_content_string(content):
    """Extract string content from various message formats.
    Returns None if no meaningful text content is found.
    """
    import ast

    def is_empty(val):
        """Check if value is empty using Python's truthiness."""
        if val is None or val == '':
            return True
        if isinstance(val, str):
            s = val.strip()
            if not s:
                return True
            try:
                return not bool(ast.literal_eval(s))
            except (ValueError, SyntaxError):
                return False  # Can't parse = real text
        return not bool(val)

    if is_empty(content):
        return None

    if isinstance(content, str):
        return content.strip()

    if isinstance(content, dict):
        text = content.get('text', '')
        return text.strip() if not is_empty(text) else None

    if isinstance(content, list):
        text_parts = [
            item.get('text', '').strip() if isinstance(item, dict) and item.get('type') == 'text'
            else (item.strip() if isinstance(item, str) else '')
            for item in content
        ]
        result = ' '.join(t for t in text_parts if t and not is_empty(t))
        return result if result else None

    return str(content).strip() if not is_empty(content) else None


def classify_message_type(message) -> tuple[str, str | None]:
    """Classify LangChain message into display type and extract content.

    Returns:
        (type, content) - type is one of: User, Agent, Data, Control
                        - content is extracted string or None
    """
    from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

    content = extract_content_string(getattr(message, 'content', None))

    if isinstance(message, HumanMessage):
        if content and content.strip() == "Continue":
            return ("Control", content)
        return ("User", content)

    if isinstance(message, ToolMessage):
        return ("Data", content)

    if isinstance(message, AIMessage):
        return ("Agent", content)

    # Fallback for unknown types
    return ("System", content)


def format_tool_args(args, max_length=80) -> str:
    """Format tool arguments for terminal display."""
    result = str(args)
    if len(result) > max_length:
        return result[:max_length - 3] + "..."
    return result

def run_analysis(checkpoint: bool = False):
    # First get all user selections
    selections = get_user_selections()

    # Create config with selected research depth
    config = DEFAULT_CONFIG.copy()
    config["max_debate_rounds"] = selections["research_depth"]
    config["max_risk_discuss_rounds"] = selections["research_depth"]
    config["quick_think_llm"] = selections["shallow_thinker"]
    config["deep_think_llm"] = selections["deep_thinker"]
    config["backend_url"] = selections["backend_url"]
    config["llm_provider"] = selections["llm_provider"].lower()
    # Provider-specific thinking configuration
    config["google_thinking_level"] = selections.get("google_thinking_level")
    config["openai_reasoning_effort"] = selections.get("openai_reasoning_effort")
    config["anthropic_effort"] = selections.get("anthropic_effort")
    config["output_language"] = selections.get("output_language", "English")
    config["checkpoint_enabled"] = checkpoint

    # Create stats callback handler for tracking LLM/tool calls and explicit env caps.
    stats_handler = stats_callback_handler_from_env(os.environ)

    # Normalize analyst selection to predefined order (selection is a 'set', order is fixed)
    selected_set = {analyst.value for analyst in selections["analysts"]}
    selected_analyst_keys = [a for a in ANALYST_ORDER if a in selected_set]
    analyst_execution_plan = build_analyst_execution_plan(
        selected_analyst_keys,
        concurrency_limit=config["analyst_concurrency_limit"],
    )
    analyst_wall_time_tracker = AnalystWallTimeTracker(analyst_execution_plan)

    # Initialize the graph with callbacks bound to LLMs
    graph = TradingAgentsGraph(
        selected_analyst_keys,
        config=config,
        debug=True,
        callbacks=[stats_handler],
    )

    # Initialize message buffer with selected analysts
    message_buffer.init_for_analysis(selected_analyst_keys)

    # Track start time for elapsed display
    start_time = time.time()

    # Create result directory
    results_dir = Path(config["results_dir"]) / selections["ticker"] / selections["analysis_date"]
    results_dir.mkdir(parents=True, exist_ok=True)
    report_dir = results_dir / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    log_file = results_dir / "message_tool.log"
    log_file.touch(exist_ok=True)

    def save_message_decorator(obj, func_name):
        func = getattr(obj, func_name)
        @wraps(func)
        def wrapper(*args, **kwargs):
            func(*args, **kwargs)
            timestamp, message_type, content = obj.messages[-1]
            content = content.replace("\n", " ")  # Replace newlines with spaces
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(f"{timestamp} [{message_type}] {content}\n")
        return wrapper
    
    def save_tool_call_decorator(obj, func_name):
        func = getattr(obj, func_name)
        @wraps(func)
        def wrapper(*args, **kwargs):
            func(*args, **kwargs)
            timestamp, tool_name, args = obj.tool_calls[-1]
            args_str = ", ".join(f"{k}={v}" for k, v in args.items())
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(f"{timestamp} [Tool Call] {tool_name}({args_str})\n")
        return wrapper

    def save_report_section_decorator(obj, func_name):
        func = getattr(obj, func_name)
        @wraps(func)
        def wrapper(section_name, content):
            func(section_name, content)
            if section_name in obj.report_sections and obj.report_sections[section_name] is not None:
                content = obj.report_sections[section_name]
                if content:
                    file_name = f"{section_name}.md"
                    text = "\n".join(str(item) for item in content) if isinstance(content, list) else content
                    with open(report_dir / file_name, "w", encoding="utf-8") as f:
                        f.write(text)
        return wrapper

    message_buffer.add_message = save_message_decorator(message_buffer, "add_message")
    message_buffer.add_tool_call = save_tool_call_decorator(message_buffer, "add_tool_call")
    message_buffer.update_report_section = save_report_section_decorator(message_buffer, "update_report_section")

    # Now start the display layout
    layout = create_layout()

    with Live(layout, refresh_per_second=4):
        # Initial display
        update_display(layout, stats_handler=stats_handler, start_time=start_time)

        # Add initial messages
        message_buffer.add_message("System", f"Selected ticker: {selections['ticker']}")
        message_buffer.add_message("System", f"Detected asset type: {selections['asset_type']}")
        message_buffer.add_message(
            "System", f"Analysis date: {selections['analysis_date']}"
        )
        message_buffer.add_message(
            "System",
            f"Selected analysts: {', '.join(analyst.value for analyst in selections['analysts'])}",
        )
        update_display(layout, stats_handler=stats_handler, start_time=start_time)

        # Update agent status to in_progress for the first analyst
        first_analyst = get_initial_analyst_node(analyst_execution_plan)
        message_buffer.update_agent_status(first_analyst, "in_progress")
        analyst_wall_time_tracker.mark_started(selected_analyst_keys[0])
        update_display(layout, stats_handler=stats_handler, start_time=start_time)

        # Create spinner text
        spinner_text = (
            f"Analyzing {selections['ticker']} on {selections['analysis_date']}..."
        )
        update_display(layout, spinner_text, stats_handler=stats_handler, start_time=start_time)

        # Initialize state and get graph args with callbacks
        init_agent_state = graph.propagator.create_initial_state(
            selections["ticker"],
            selections["analysis_date"],
            asset_type=selections["asset_type"],
            past_context="",
        )
        # Pass callbacks to graph config for tool execution tracking
        # (LLM tracking is handled separately via LLM constructor)
        args = graph.propagator.get_graph_args(callbacks=[stats_handler])

        # Stream the analysis
        trace = []
        try:
            graph_stream = graph.graph.stream(init_agent_state, **args)
            for chunk in graph_stream:
                # Process all messages in chunk, deduplicating by message ID
                for message in chunk.get("messages", []):
                    msg_id = getattr(message, "id", None)
                    if msg_id is not None:
                        if msg_id in message_buffer._processed_message_ids:
                            continue
                        message_buffer._processed_message_ids.add(msg_id)

                    msg_type, content = classify_message_type(message)
                    if content and content.strip():
                        message_buffer.add_message(msg_type, content)

                    if hasattr(message, "tool_calls") and message.tool_calls:
                        for tool_call in message.tool_calls:
                            if isinstance(tool_call, dict):
                                message_buffer.add_tool_call(tool_call["name"], tool_call["args"])
                            else:
                                message_buffer.add_tool_call(tool_call.name, tool_call.args)

                # Update analyst statuses based on report state (runs on every chunk)
                update_analyst_statuses(
                    message_buffer,
                    chunk,
                    wall_time_tracker=analyst_wall_time_tracker,
                )

                # Research Team - Handle Investment Debate State
                if chunk.get("investment_debate_state"):
                    debate_state = chunk["investment_debate_state"]
                    bull_hist = debate_state.get("bull_history", "").strip()
                    bear_hist = debate_state.get("bear_history", "").strip()
                    judge = debate_state.get("judge_decision", "").strip()

                    # Only update status when there's actual content
                    if bull_hist or bear_hist:
                        update_research_team_status("in_progress")
                    if bull_hist:
                        message_buffer.update_report_section(
                            "investment_plan", f"### Bull Researcher Analysis\n{bull_hist}"
                        )
                    if bear_hist:
                        message_buffer.update_report_section(
                            "investment_plan", f"### Bear Researcher Analysis\n{bear_hist}"
                        )
                    if judge:
                        message_buffer.update_report_section(
                            "investment_plan", f"### Research Manager Decision\n{judge}"
                        )
                        update_research_team_status("completed")
                        message_buffer.update_agent_status("Trader", "in_progress")

                # Trading Team
                if chunk.get("trader_investment_plan"):
                    message_buffer.update_report_section(
                        "trader_investment_plan", chunk["trader_investment_plan"]
                    )
                    if message_buffer.agent_status.get("Trader") != "completed":
                        message_buffer.update_agent_status("Trader", "completed")
                        message_buffer.update_agent_status("Aggressive Analyst", "in_progress")

                # Risk Management Team - Handle Risk Debate State
                if chunk.get("risk_debate_state"):
                    risk_state = chunk["risk_debate_state"]
                    agg_hist = risk_state.get("aggressive_history", "").strip()
                    con_hist = risk_state.get("conservative_history", "").strip()
                    neu_hist = risk_state.get("neutral_history", "").strip()
                    judge = risk_state.get("judge_decision", "").strip()

                    if agg_hist:
                        if message_buffer.agent_status.get("Aggressive Analyst") != "completed":
                            message_buffer.update_agent_status("Aggressive Analyst", "in_progress")
                        message_buffer.update_report_section(
                            "final_trade_decision", f"### Aggressive Analyst Analysis\n{agg_hist}"
                        )
                    if con_hist:
                        if message_buffer.agent_status.get("Conservative Analyst") != "completed":
                            message_buffer.update_agent_status("Conservative Analyst", "in_progress")
                        message_buffer.update_report_section(
                            "final_trade_decision", f"### Conservative Analyst Analysis\n{con_hist}"
                        )
                    if neu_hist:
                        if message_buffer.agent_status.get("Neutral Analyst") != "completed":
                            message_buffer.update_agent_status("Neutral Analyst", "in_progress")
                        message_buffer.update_report_section(
                            "final_trade_decision", f"### Neutral Analyst Analysis\n{neu_hist}"
                        )
                    if judge and message_buffer.agent_status.get("Portfolio Manager") != "completed":
                        message_buffer.update_agent_status("Portfolio Manager", "in_progress")
                        message_buffer.update_report_section(
                            "final_trade_decision", f"### Portfolio Manager Decision\n{judge}"
                        )
                        message_buffer.update_agent_status("Aggressive Analyst", "completed")
                        message_buffer.update_agent_status("Conservative Analyst", "completed")
                        message_buffer.update_agent_status("Neutral Analyst", "completed")
                        message_buffer.update_agent_status("Portfolio Manager", "completed")

                # Update the display
                update_display(layout, stats_handler=stats_handler, start_time=start_time)

                trace.append(chunk)
        except ModelBudgetExceededError as exc:
            message_buffer.add_message("System", f"Model budget cap exceeded: {exc}")
            update_display(layout, stats_handler=stats_handler, start_time=start_time)
            raise typer.Exit(code=2) from exc

        # Streamed chunks are per-node deltas, not full state. Merge them
        # so every report field populated across the run is present.
        final_state = {}
        for chunk in trace:
            final_state.update(chunk)
        graph.process_signal(final_state["final_trade_decision"])

        # Update all agent statuses to completed
        for agent in message_buffer.agent_status:
            message_buffer.update_agent_status(agent, "completed")

        message_buffer.add_message(
            "System", f"Completed analysis for {selections['analysis_date']}"
        )
        message_buffer.add_message("System", analyst_wall_time_tracker.format_summary())

        # Update final report sections
        for section in message_buffer.report_sections:
            if section in final_state:
                message_buffer.update_report_section(section, final_state[section])

        update_display(layout, stats_handler=stats_handler, start_time=start_time)

    # Post-analysis prompts (outside Live context for clean interaction)
    console.print("\n[bold cyan]Analysis Complete![/bold cyan]\n")
    console.print(f"[dim]{analyst_wall_time_tracker.format_summary()}[/dim]")

    # Prompt to save report
    save_choice = typer.prompt("Save report?", default="Y").strip().upper()
    if save_choice in ("Y", "YES", ""):
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        default_path = Path.cwd() / "reports" / f"{selections['ticker']}_{timestamp}"
        save_path_str = typer.prompt(
            "Save path (press Enter for default)",
            default=str(default_path)
        ).strip()
        save_path = Path(save_path_str)
        try:
            report_file = save_report_to_disk(final_state, selections["ticker"], save_path)
            console.print(f"\n[green]✓ Report saved to:[/green] {save_path.resolve()}")
            console.print(f"  [dim]Complete report:[/dim] {report_file.name}")
        except Exception as e:
            console.print(f"[red]Error saving report: {e}[/red]")

    # Prompt to display full report
    display_choice = typer.prompt("\nDisplay full report on screen?", default="Y").strip().upper()
    if display_choice in ("Y", "YES", ""):
        display_complete_report(final_state)


@app.command()
def analyze(
    checkpoint: bool = typer.Option(
        False,
        "--checkpoint",
        help="Enable checkpoint/resume: save state after each node so a crashed run can resume.",
    ),
    clear_checkpoints: bool = typer.Option(
        False,
        "--clear-checkpoints",
        help="Delete all saved checkpoints before running (force fresh start).",
    ),
):
    if clear_checkpoints:
        from tradingagents.graph.checkpointer import clear_all_checkpoints
        n = clear_all_checkpoints(DEFAULT_CONFIG["data_cache_dir"])
        console.print(f"[yellow]Cleared {n} checkpoint(s).[/yellow]")
    run_analysis(checkpoint=checkpoint)


@alpaca_app.command("check")
def alpaca_check():
    """Verify Alpaca paper and live account connectivity without placing orders."""
    paper_client, live_client = _alpaca_clients()
    paper_account = paper_client.get_account()
    live_account = live_client.get_account()

    table = Table(title="Alpaca Account Check")
    table.add_column("Mode")
    table.add_column("Status")
    table.add_column("Buying Power")
    table.add_column("Equity")
    table.add_row(
        "paper",
        str(paper_account.get("status", "")),
        str(paper_account.get("buying_power", "")),
        str(paper_account.get("equity", "")),
    )
    table.add_row(
        "live",
        str(live_account.get("status", "")),
        str(live_account.get("buying_power", "")),
        str(live_account.get("equity", "")),
    )
    console.print(table)


# Documented Get All Orders maximum limit; a bound reconciliation reads with
# this limit so only a response strictly below the limit proves completeness,
# while an at-limit response fails closed because completeness could not be
# proven beyond it.
_BOUND_RECONCILIATION_ORDER_LIMIT = 500


@alpaca_app.command("reconcile-observer")
def alpaca_reconcile_observer(
    output_dir: Path = typer.Option(
        Path("results/observer_reconciliation"),
        "--output-dir",
        help="Directory for immutable read-only live and paper reconciliation packets.",
    ),
    shadow_start_object_id: str | None = typer.Option(
        None,
        "--shadow-start-object-id",
        help="Bind this reconciliation to one authenticated manual shadow-day start.",
    ),
    json_output: bool = typer.Option(False, "--json-output"),
):
    """Capture broker state through observer reads only; never submit or cancel."""

    from tradingagents.evals.safety_sentinel import capture_read_only_broker_snapshot

    if not isinstance(shadow_start_object_id, str):
        shadow_start_object_id = None
    shadow_start = None
    if shadow_start_object_id is not None:
        from tradingagents.evals.shadow_trial import load_shadow_record

        try:
            shadow_start = load_shadow_record(
                shadow_start_object_id,
                expected_kind="manual-shadow-day-start",
            )
        except ValueError as exc:
            raise typer.BadParameter(str(exc), param_hint="--shadow-start-object-id") from exc
    generated_at = _alpaca_policy_now()
    try:
        live = capture_read_only_broker_snapshot(_alpaca_live_client(), captured_at=generated_at)
    except Exception as exc:  # noqa: BLE001 - preserve an unavailable observer as evidence.
        live = {"errors": {"client": f"live client initialization failed: {exc}"}}
    try:
        paper_client = _alpaca_paper_client()
        paper = capture_read_only_broker_snapshot(paper_client, captured_at=generated_at)
    except Exception as exc:  # noqa: BLE001 - preserve an unavailable observer as evidence.
        paper_client = None
        paper = {"errors": {"client": f"paper client initialization failed: {exc}"}}
    if shadow_start is not None and paper_client is not None:
        # A bound reconciliation must observe the complete same-market-day
        # paper order book so adjudication can prove one-to-one identity with
        # the day's tournament packet.  This stays a read-only GET using only
        # documented query parameters; the wrapper fails closed when the
        # collection reaches the limit, because completeness could not be
        # proven beyond that ceiling.
        try:
            market_date = str(shadow_start.payload["market_date"])
            day_open_utc = (
                datetime.datetime.combine(
                    datetime.date.fromisoformat(market_date), datetime.time.min
                )
                .replace(tzinfo=CENTRAL)
                .astimezone(datetime.timezone.utc)
            )
            paper["all_orders"] = paper_client.list_orders(
                status="all",
                after=day_open_utc.isoformat(),
                limit=_BOUND_RECONCILIATION_ORDER_LIMIT,
            )
        except Exception as exc:  # noqa: BLE001 - a failed read must fail the day closed.
            paper.setdefault("errors", {})["all_orders"] = f"list_orders(all) failed: {exc}"
    packet: dict[str, object] = {
        "kind": "broker_reconciliation_observer",
        "generated_at": generated_at.isoformat(timespec="seconds"),
        "status": "HOLD" if live.get("errors") or paper.get("errors") else "COMPLETE",
        "analysis_only": True,
        "execution_authority": "none",
        "can_submit_orders": False,
        "submitted_count": 0,
        "cancelled_count": 0,
        "read_only": True,
        "live": live,
        "paper": paper,
    }
    if shadow_start is not None:
        start_payload = shadow_start.payload
        packet["shadow_start_object_id"] = shadow_start.object_id
        packet["run_id"] = start_payload["run_id"]
        packet["market_date"] = start_payload["market_date"]
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = f"observer-reconciliation-{generated_at.strftime('%Y%m%d-%H%M%S-%f')}"
    packet_path = _write_reconciliation_packet(output_dir, stem=stem, packet=packet)[0]
    packet["packet_path"] = str(packet_path)
    if json_output:
        typer.echo(json.dumps(packet, indent=2, sort_keys=True))
        return
    console.print(f"Observer reconciliation: {packet['status']}")
    console.print(f"Packet: {packet_path}")


def _resolve_safety_sentinel_automation_root(
    automation_root: Path | None,
    *,
    require_canonical_root: bool,
) -> Path:
    """Keep qualification preflight bound to the one canonical automation tree."""

    if not require_canonical_root:
        return automation_root if automation_root is not None else default_automation_root()

    from tradingagents.evals.shadow_trial import _canonical_automation_root

    canonical_root = _canonical_automation_root()
    if automation_root is not None and (
        automation_root.expanduser().resolve(strict=False)
        != canonical_root.expanduser().resolve(strict=False)
    ):
        raise typer.BadParameter(
            "--automation-root conflicts with the canonical qualification root",
            param_hint="--automation-root",
        )
    return canonical_root


@research_app.command("safety-sentinel-audit")
def research_safety_sentinel_audit(
    output_dir: Path = typer.Option(
        Path("results/safety_sentinel"),
        "--output-dir",
        help="Directory for immutable read-only safety-sentinel packets.",
    ),
    live_control_path: Path = typer.Option(
        Path("results/policy/live_control.json"),
        "--live-control-path",
        help="Live-control state to inspect without refreshing it.",
    ),
    preopen_validation_path: Path = typer.Option(
        Path("results/preopen_validation/latest.json"),
        "--preopen-validation-path",
        help="Exact pre-open validation packet to capture and verify.",
    ),
    schedule_contract_path: Path = typer.Option(
        Path("config/automation_schedule_contract.json"),
        "--schedule-contract-path",
        help="Versioned schedule contract to evaluate read-only.",
    ),
    automation_root: Path | None = typer.Option(
        None,
        "--automation-root",
        help="Codex automation root to inspect for an unbound observer audit.",
    ),
    role_contract_path: Path = typer.Option(
        Path("config/automation_roles.json"),
        "--role-contract-path",
        help="Versioned role contract to capture and verify.",
    ),
    max_evidence_age_minutes: float = typer.Option(
        90.0,
        "--max-evidence-age-minutes",
        min=0.1,
        help="Maximum accepted age for the exact pre-open validation packet.",
    ),
    shadow_start_object_id: str | None = typer.Option(
        None,
        "--shadow-start-object-id",
        help="Bind this observer packet to one authenticated manual shadow-day start.",
    ),
    require_paused: bool = typer.Option(
        False,
        "--require-paused",
        help="Exit nonzero after writing when the exact ten-record paused contract is not proven.",
    ),
    json_output: bool = typer.Option(False, "--json-output"),
):
    """Capture a deterministic observer-only safety packet with read-only Alpaca state."""
    from tradingagents.evals.safety_sentinel import (
        build_safety_sentinel_packet,
        capture_read_only_broker_snapshot,
        write_safety_sentinel_packet,
    )

    if not isinstance(shadow_start_object_id, str):
        shadow_start_object_id = None
    shadow_start = None
    if shadow_start_object_id is not None:
        from tradingagents.evals.shadow_trial import load_shadow_record

        try:
            shadow_start = load_shadow_record(
                shadow_start_object_id,
                expected_kind="manual-shadow-day-start",
            )
        except ValueError as exc:
            raise typer.BadParameter(str(exc), param_hint="--shadow-start-object-id") from exc
    automation_root = _resolve_safety_sentinel_automation_root(
        automation_root,
        require_canonical_root=require_paused or shadow_start is not None,
    )
    generated_at = _alpaca_policy_now()
    try:
        broker_snapshot = capture_read_only_broker_snapshot(
            _alpaca_live_client(),
            captured_at=generated_at,
        )
    except Exception as exc:  # noqa: BLE001 - preserve client setup failures in a HOLD packet.
        broker_snapshot = {
            "account": {},
            "positions": [],
            "open_orders": [],
            "clock": {},
            "errors": {"client": f"live client initialization failed: {exc}"},
            "read_methods": ["get_account", "list_positions", "list_orders", "get_clock"],
            "captured_at": generated_at.isoformat(timespec="seconds"),
        }
    packet = build_safety_sentinel_packet(
        live_control_path=live_control_path,
        preopen_validation_path=preopen_validation_path,
        schedule_contract_path=schedule_contract_path,
        automation_root=automation_root,
        role_contract_path=role_contract_path,
        broker_snapshot=broker_snapshot,
        now=generated_at,
        max_evidence_age_minutes=max_evidence_age_minutes,
    )
    if shadow_start is not None:
        start_payload = shadow_start.payload
        packet["shadow_start_object_id"] = shadow_start.object_id
        packet["run_id"] = start_payload["run_id"]
        packet["market_date"] = start_payload["market_date"]
    packet_path = write_safety_sentinel_packet(packet, output_dir=output_dir)
    payload = {**packet, "packet_path": str(packet_path)}
    if json_output:
        typer.echo(json.dumps(payload, indent=2, sort_keys=True))
        if require_paused and packet.get("schedule_check", {}).get("safe_predeployment") is not True:
            raise typer.Exit(code=1)
        return
    console.print(f"Safety sentinel: {packet['status']}")
    console.print(f"Packet: {packet_path}")
    if require_paused and packet.get("schedule_check", {}).get("safe_predeployment") is not True:
        raise typer.Exit(code=1)


@research_app.command("shadow-day-start")
def research_shadow_day_start(
    run_id: str = typer.Option(..., "--run-id", help="Opaque manual observer run identifier."),
    market_date: str = typer.Option(..., "--market-date", help="Current Central regular-market date."),
    predecessor_object_id: str | None = typer.Option(
        None,
        "--predecessor-object-id",
        help="Authenticated prior shadow day object identity, when the ledger requires one.",
    ),
    json_output: bool = typer.Option(False, "--json-output"),
):
    """Capture start-state evidence only; this command has no authority effects."""

    from tradingagents.evals.shadow_trial import (
        admitted_shadow_record_view,
        create_shadow_day_start_manifest,
    )

    try:
        admission = create_shadow_day_start_manifest(
            run_id=run_id,
            market_date=market_date,
            predecessor_object_id=predecessor_object_id,
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    payload = admitted_shadow_record_view(admission)
    if json_output:
        typer.echo(json.dumps(payload, indent=2, sort_keys=True))
        return
    console.print(f"Shadow-day start record: {admission.path}")


@research_app.command("shadow-day-adjudicate")
def research_shadow_day_adjudicate(
    start_object_id: str = typer.Option(..., "--start-object-id", help="Authenticated pending shadow start object identity."),
    safety_sentinel: Path = typer.Option(..., "--safety-sentinel", help="Same-run sentinel artifact."),
    paper_tournament: Path = typer.Option(..., "--paper-tournament", help="Same-run paper artifact."),
    daily_chain_manifest: Path = typer.Option(..., "--daily-chain-manifest", help="Complete authenticated observer-chain manifest."),
    json_output: bool = typer.Option(False, "--json-output"),
):
    """Adjudicate supplied local evidence only; missing evidence is never a pass."""

    from tradingagents.evals.shadow_trial import (
        adjudicate_shadow_day,
        admitted_shadow_record_view,
        load_shadow_record,
    )

    try:
        load_shadow_record(start_object_id, expected_kind="manual-shadow-day-start")
        admission = adjudicate_shadow_day(
            start_object_id=start_object_id,
            artifacts={
                "safety_sentinel": safety_sentinel,
                "paper_tournament": paper_tournament,
                "daily_chain_manifest": daily_chain_manifest,
            },
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    payload = admitted_shadow_record_view(admission)
    if json_output:
        typer.echo(json.dumps(payload, indent=2, sort_keys=True))
        return
    console.print(f"Shadow-day adjudication: {admission.envelope.payload['status']}")
    console.print(f"Decision: {admission.path}")


@research_app.command("shadow-day-abort")
def research_shadow_day_abort(
    start_object_id: str = typer.Option(..., "--start-object-id", help="Authenticated pending shadow start object identity."),
    stopped_at_stage: str = typer.Option(
        ...,
        "--stopped-at-stage",
        help="Interruption stage key: day_start, one of the fixed daily-chain stage keys, or manifest_written (after the sealed manifest, before adjudication).",
    ),
    notes: str = typer.Option(
        ...,
        "--notes",
        help="Short operator explanation recorded inside the immutable closure result.",
    ),
    safety_sentinel: Path | None = typer.Option(None, "--safety-sentinel", help="Present sentinel artifact, when one exists."),
    paper_tournament: Path | None = typer.Option(None, "--paper-tournament", help="Present paper artifact, when one exists."),
    daily_chain_manifest: Path | None = typer.Option(None, "--daily-chain-manifest", help="Present observer-chain manifest, when one exists."),
    json_output: bool = typer.Option(False, "--json-output"),
):
    """Crash-safe closure of today's stranded pending shadow day; terminal and non-authorizing."""

    from tradingagents.evals.shadow_trial import (
        abort_shadow_day,
        admitted_shadow_record_view,
        load_shadow_record,
    )

    supplied: dict[str, Path] = {
        key: value
        for key, value in (
            ("safety_sentinel", safety_sentinel),
            ("paper_tournament", paper_tournament),
            ("daily_chain_manifest", daily_chain_manifest),
        )
        if value is not None
    }
    try:
        load_shadow_record(start_object_id, expected_kind="manual-shadow-day-start")
        admission = abort_shadow_day(
            start_object_id=start_object_id,
            stopped_at_stage=stopped_at_stage,
            notes=notes,
            artifacts=supplied,
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    payload = admitted_shadow_record_view(admission)
    if json_output:
        typer.echo(json.dumps(payload, indent=2, sort_keys=True))
        return
    console.print(f"Shadow-day abort recorded: {payload['status']}")
    console.print(f"Decision: {admission.path}")


@research_app.command("shadow-day-expire-pending")
def research_shadow_day_expire_pending(
    json_output: bool = typer.Option(False, "--json-output"),
):
    """Close a pending shadow day whose Central market date has already passed."""

    from tradingagents.evals.shadow_trial import (
        admitted_shadow_record_view,
        expire_pending_shadow_day,
    )

    try:
        admission = expire_pending_shadow_day()
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    envelope = {
        "analysis_only": True,
        "execution_authority": "none",
        "can_submit_orders": False,
    }
    if admission is None:
        result = {**envelope, "expired": False, "record": None}
        if json_output:
            typer.echo(json.dumps(result, indent=2, sort_keys=True))
            return
        console.print("No expired pending shadow day.")
        return
    record = admitted_shadow_record_view(admission)
    result = {**envelope, "expired": True, "record": record}
    if json_output:
        typer.echo(json.dumps(result, indent=2, sort_keys=True))
        return
    console.print(f"Expired pending shadow day closed: {record['status']}")
    console.print(f"Decision: {admission.path}")


@research_app.command("shadow-day-manifest")
def research_shadow_day_manifest(
    start_object_id: str = typer.Option(..., "--start-object-id", help="Authenticated pending shadow start object identity."),
    stage: list[str] = typer.Option(
        ..., "--stage", help="One exact KEY=PATH stage artifact; repeat for all required stages."
    ),
    output_dir: Path = typer.Option(
        Path("results/manual_shadow/manifests"),
        "--output-dir",
        help="Local directory for daily-chain observer manifests.",
    ),
    json_output: bool = typer.Option(False, "--json-output"),
):
    """Bind the exact complete local observer chain to an admitted start record."""

    from tradingagents.evals.shadow_trial import create_shadow_day_manifest

    stages: dict[str, Path] = {}
    for item in stage:
        key, separator, value = item.partition("=")
        if not separator or not key or not value or key in stages:
            raise typer.BadParameter("each --stage must be a unique nonblank KEY=PATH value")
        stages[key] = Path(value)
    try:
        payload, packet_path = create_shadow_day_manifest(
            start_object_id=start_object_id,
            stages=stages,
            output_dir=output_dir,
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    result = {**payload, "packet_path": str(packet_path)}
    if json_output:
        typer.echo(json.dumps(result, indent=2, sort_keys=True))
        return
    console.print(f"Shadow daily-chain manifest: {packet_path}")


@research_app.command("shadow-streak-status")
def research_shadow_streak_status(
    json_output: bool = typer.Option(False, "--json-output"),
):
    """Read-only shadow-trial progress inspection; never writes the pinned ledger."""

    from tradingagents.evals.shadow_trial import shadow_streak_status

    try:
        payload = shadow_streak_status()
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    if json_output:
        typer.echo(json.dumps(payload, indent=2, sort_keys=True))
        return
    console.print(f"Shadow-trial phase: {payload['phase']}")
    console.print(f"Clean trial streak: {payload['clean_trial_streak']}")
    console.print(f"Next start admissible: {payload['can_start_next_day']}")


@research_app.command("shadow-streak-report")
def research_shadow_streak_report(
    json_output: bool = typer.Option(False, "--json-output"),
    final_no_go: bool = typer.Option(
        False,
        "--final-no-go/--no-final-no-go",
        help="Explicitly terminate the whole program as a final NO-GO before a clean trial_complete.",
    ),
):
    """Admit exactly one terminal non-authorizing readiness report."""

    from tradingagents.evals.shadow_trial import build_shadow_streak_report

    try:
        report = build_shadow_streak_report(final_no_go=final_no_go)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    if json_output:
        typer.echo(json.dumps(report, indent=2, sort_keys=True))
        return
    console.print(f"Shadow-trial readiness: {report['status']}")
    console.print(f"Report: {report.get('record_path', 'already admitted ledger report')}")


def _write_reconciliation_packet(
    output_dir: Path,
    *,
    stem: str,
    packet: dict,
) -> tuple[Path, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = _reserve_reconciliation_packet_path(output_dir, stem)
    packet["json_path"] = str(output_path)
    json_text = json.dumps(packet, indent=2, sort_keys=True) + "\n"
    try:
        _atomic_write_text(output_path, json_text)
    except Exception:
        output_path.unlink(missing_ok=True)
        raise
    _atomic_write_text(output_dir / "latest.json", json_text)
    return output_path, json_text


def _reserve_reconciliation_packet_path(output_dir: Path, stem: str) -> Path:
    candidate = _unique_packet_path(output_dir, stem)
    for index in range(1000):
        try:
            descriptor = os.open(candidate, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            candidate = output_dir / f"{stem}-{index + 1:03d}.json"
            continue
        os.close(descriptor)
        return candidate
    raise RuntimeError(f"could not reserve immutable reconciliation packet for {stem}")


@alpaca_app.command("reconcile-orcl-incident")
def alpaca_reconcile_orcl_incident(
    order_packet_paths: list[Path] = typer.Argument(None),
    symbol: str = typer.Option("ORCL", "--symbol"),
    max_recent_fills: int = typer.Option(25, "--max-recent-fills"),
    hourly_log_dir: Path = typer.Option(
        Path("results/hourly_supervisor"),
        "--hourly-log-dir",
        help="Hourly supervisor packet directory used when packet paths are omitted.",
    ),
    output_dir: Path = typer.Option(
        Path("results/orcl_reconciliation"),
        "--output-dir",
        help="Directory for the read-only ORCL reconciliation packet.",
    ),
    json_output: bool = typer.Option(False, "--json-output"),
):
    """Build ORCL incident reconciliation evidence from packets and live read-only broker state."""
    live_client = _alpaca_live_client()
    resolved_paths = list(order_packet_paths or [])
    discovery_issues: list[dict[str, str]] = []
    if not resolved_paths:
        resolved_paths, discovery_issues = _discover_reconciliation_packet_paths(
            hourly_log_dir,
            "hourly-supervisor-*.json",
            symbol=symbol,
        )
    payload = reconcile_orcl_sell_state(
        resolved_paths,
        live_client=live_client,
        symbol=symbol,
        max_recent_fills=max_recent_fills,
    )
    generated_at = datetime.datetime.now(tz=datetime.timezone.utc)
    packet = {
        "schema_version": 1,
        "kind": "orcl_sell_reconciliation",
        "generated_at": generated_at.isoformat(timespec="seconds"),
        "read_only": True,
        "analysis_only": True,
        "can_submit_orders": False,
        "execution_authority": "none",
        "broker_write_calls": 0,
        "packet_discovery_issues": discovery_issues,
        **payload,
    }
    output_path, json_text = _write_reconciliation_packet(
        output_dir,
        stem=f"orcl-reconciliation-{generated_at:%Y%m%d-%H%M%S}",
        packet=packet,
    )
    if json_output:
        typer.echo(json_text)
        return
    console.print(
        f"final_old_sell_state={packet['final_old_sell_state']} "
        f"current_position={packet['current_orcl_position'].get('qty', '0')}"
    )
    console.print(f"open_orders={len(packet['open_orcl_orders'])}")
    console.print(f"recent_fills={len(packet['recent_orcl_fills'])}")
    console.print(f"packet={output_path}")


@alpaca_app.command("reconcile-symbol-incident")
def alpaca_reconcile_symbol_incident(
    symbol: str = typer.Option(..., "--symbol"),
    packet_paths: list[Path] = typer.Option(
        [],
        "--packet-path",
        help="Captured packet JSON to reconcile. Repeat for multiple packets.",
    ),
    expected_qty: str | None = typer.Option(None, "--expected-qty"),
    owner_action_attestation_paths: list[Path] = typer.Option(
        [],
        "--owner-action-attestation",
        help="Immutable owner-manual action attribution. Repeat for multiple exact actions.",
    ),
    output_dir: Path = typer.Option(
        Path("results/control_plane/reconciliation"),
        "--output-dir",
        help="Directory for the read-only symbol reconciliation packet.",
    ),
    json_output: bool = typer.Option(False, "--json-output"),
):
    """Build read-only broker reconciliation evidence for one symbol."""

    reconciliation = reconcile_symbol_incident(
        symbol=symbol,
        packet_paths=packet_paths,
        live_client=_alpaca_live_client(),
        expected_qty=expected_qty,
        owner_action_attestation_paths=owner_action_attestation_paths,
    )
    generated_at = datetime.datetime.now(tz=datetime.timezone.utc)
    packet = {
        "schema_version": 1,
        "kind": "symbol_broker_reconciliation",
        "generated_at": generated_at.isoformat(timespec="seconds"),
        "read_only": True,
        "analysis_only": True,
        "can_submit_orders": False,
        "execution_authority": "none",
        **asdict(reconciliation),
    }
    output_path, json_text = _write_reconciliation_packet(
        output_dir,
        stem=f"symbol-reconciliation-{generated_at:%Y%m%d-%H%M%S}",
        packet=packet,
    )
    if json_output:
        typer.echo(json_text)
        return
    console.print(f"symbol={packet['symbol']} matched={packet['matched']}")
    console.print(f"packet={output_path}")


@alpaca_app.command("record-owner-manual-action")
def alpaca_record_owner_manual_action(
    source_packet: Path = typer.Option(..., "--source-packet"),
    reconciliation_packet: Path = typer.Option(..., "--reconciliation-packet"),
    originating_client_order_id: str = typer.Option(
        ..., "--originating-client-order-id"
    ),
    manual_fill_client_order_id: str = typer.Option(
        ..., "--manual-fill-client-order-id"
    ),
    attested_at: str = typer.Option(..., "--attested-at"),
    output: Path = typer.Option(..., "--output"),
    json_output: bool = typer.Option(False, "--json-output"),
):
    """Record a local owner attestation from captured evidence without broker I/O."""

    try:
        reconciliation = json.loads(
            reconciliation_packet.read_text(encoding="utf-8")
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise typer.BadParameter(
            "reconciliation packet must be readable JSON"
        ) from error
    if not isinstance(reconciliation, dict):
        raise typer.BadParameter("reconciliation packet must be a JSON object")
    payload = build_owner_manual_action_attribution(
        source_packet_path=source_packet,
        reconciliation_packet=reconciliation,
        originating_client_order_id=originating_client_order_id,
        manual_fill_client_order_id=manual_fill_client_order_id,
        attested_at=attested_at,
    )
    written = write_owner_manual_action_attribution(output, payload)
    text = written.read_text(encoding="utf-8")
    if json_output:
        typer.echo(text, nl=False)
        return
    console.print(f"owner_manual_action={written}")


@alpaca_app.command("preview")
def alpaca_preview(
    run_id: str = typer.Option(_default_run_id(), "--run-id"),
    premarket: bool = typer.Option(True, "--premarket/--regular-hours"),
    third_symbol: str | None = typer.Option(None, "--third-symbol"),
    third_limit_price: float | None = typer.Option(None, "--third-limit-price"),
    paper_only: bool = typer.Option(False, "--paper-only"),
    json_output: bool = typer.Option(False, "--json-output"),
):
    """Preview paired Alpaca paper/live mirror orders without submitting."""
    config = _alpaca_execution_config()
    orders = _ticket_orders(
        premarket=premarket,
        third_symbol=third_symbol,
        third_limit_price=third_limit_price,
    )
    if paper_only:
        paper_result = build_paper_orders(
            orders,
            config=config,
            run_id=run_id,
        )
        if json_output:
            typer.echo(json.dumps(_serialize_paper_result(paper_result), indent=2))
            return
        _print_paper_result(paper_result)
        return

    result = build_order_pairs(
        orders,
        config=config,
        run_id=run_id,
    )
    if json_output:
        typer.echo(json.dumps(_serialize_pair_result(result), indent=2))
        return
    _print_pair_result(result)


@alpaca_app.command("submit")
def alpaca_submit(
    run_id: str = typer.Option(_default_run_id(), "--run-id"),
    premarket: bool = typer.Option(True, "--premarket/--regular-hours"),
    third_symbol: str | None = typer.Option(None, "--third-symbol"),
    third_limit_price: float | None = typer.Option(None, "--third-limit-price"),
    paper_only: bool = typer.Option(False, "--paper-only"),
    log_dir: Path = typer.Option(
        Path("results/manual_alpaca_submit"),
        "--log-dir",
        help="Directory for manual legacy submit receipt packets.",
    ),
):
    """Submit paired Alpaca paper orders and 10% live mirror orders."""
    config = _alpaca_execution_config()
    orders = _ticket_orders(
        premarket=premarket,
        third_symbol=third_symbol,
        third_limit_price=third_limit_price,
    )

    if paper_only:
        if not config.paper_enabled:
            packet = _manual_submit_packet_base(
                run_id=run_id,
                account_mode="paper_only",
                account_scope=["paper"],
                status="refused",
                reason="TRADINGAGENTS_ALPACA_PAPER_ENABLED is not true",
                planned_orders={"requested": [order.__dict__ for order in orders]},
            )
            packet_path = _write_manual_alpaca_submit_packet(packet, log_dir)
            console.print(
                "[red]Refusing to submit. Set "
                "TRADINGAGENTS_ALPACA_PAPER_ENABLED=true first.[/red]"
            )
            console.print(f"Packet: {packet_path}")
            raise typer.Exit(1)
        paper_client = _alpaca_paper_client()
        result = build_paper_orders(
            orders,
            config=config,
            run_id=run_id,
            existing_open_client_order_ids=paper_client.list_open_client_order_ids(),
        )
        if not result.accepted:
            _print_paper_result(result)
            packet = _manual_submit_packet_base(
                run_id=run_id,
                account_mode="paper_only",
                account_scope=["paper"],
                status="blocked",
                reason="paper-only planning produced no accepted orders",
                planned_orders=_serialize_paper_result(result),
                issues=[*_issue_dicts(result.rejected), *_issue_dicts(result.skipped)],
            )
            packet_path = _write_manual_alpaca_submit_packet(packet, log_dir)
            console.print(f"Packet: {packet_path}")
            raise typer.Exit(1)
        report = execute_paper_orders(result.accepted, paper_client=paper_client)
        _print_paper_result(result)
        for response in report.submitted:
            console.print(
                "[green]Submitted paper order "
                f"{response.get('client_order_id', response.get('id', ''))}[/green]"
            )
        for issue in report.failed:
            console.print(f"[red]Failed {issue.ticket_id}: {issue.reason}[/red]")
        status = "partial_failure" if report.failed else "submitted"
        packet = _manual_submit_packet_base(
            run_id=run_id,
            account_mode="paper_only",
            account_scope=["paper"],
            status=status,
            reason=(
                "paper submit had broker failures"
                if report.failed
                else "paper orders submitted"
            ),
            planned_orders=_serialize_paper_result(result),
            submitted=list(report.submitted),
            failed=_issue_dicts(report.failed),
            estimated_spent_this_run_by_account=_paper_submit_spend_summary(
                result.accepted,
                report.failed,
            ),
        )
        packet_path = _write_manual_alpaca_submit_packet(packet, log_dir)
        console.print(f"Packet: {packet_path}")
        if report.failed:
            raise typer.Exit(1)
        return

    packet = _manual_submit_packet_base(
        run_id=run_id,
        account_mode="live_submit_disabled",
        account_scope=["live"],
        status="refused",
        reason=(
            "manual live submission is disabled: an authorized normal live intent "
            "and its activation receipt must be issued outside this CLI path"
        ),
        planned_orders={"requested": [order.__dict__ for order in orders]},
    )
    packet_path = _write_manual_alpaca_submit_packet(packet, log_dir)
    console.print(
        "[red]Refusing to submit: an authorized normal live intent and activation "
        "receipt must be independently issued outside this CLI path.[/red]"
    )
    console.print(f"Packet: {packet_path}")
    raise typer.Exit(1)


@alpaca_app.command("pullback-support-paper")
def alpaca_pullback_support_paper(
    symbol: str = typer.Option(..., "--symbol"),
    current_price: str = typer.Option(..., "--current-price"),
    support_level: str = typer.Option(..., "--support-level"),
    atr: str = typer.Option(..., "--atr"),
    pullback_atr: str = typer.Option(..., "--pullback-atr"),
    above_rising_50d: bool = typer.Option(
        False,
        "--above-rising-50d/--below-rising-50d",
    ),
    above_rising_200d: bool = typer.Option(
        False,
        "--above-rising-200d/--below-rising-200d",
    ),
    sell_volume_state: str = typer.Option(..., "--sell-volume-state"),
    gap_state: str = typer.Option(..., "--gap-state"),
    sector_relative_strength: str = typer.Option(..., "--sector-relative-strength"),
    regime_state: str = typer.Option(..., "--regime-state"),
    earnings_blackout: bool = typer.Option(False, "--earnings-blackout/--no-earnings-blackout"),
    fresh_negative_event: bool = typer.Option(False, "--fresh-negative-event/--no-fresh-negative-event"),
    notional_usd: str = typer.Option("100.00", "--notional-usd"),
    run_id: str = typer.Option(_default_run_id(), "--run-id"),
    dry_run: bool = typer.Option(True, "--dry-run/--submit-actions"),
    output_dir: Path = typer.Option(
        Path("results/shadow_policy_packets"),
        "--output-dir",
        help="Directory for pullback-support paper decision packets.",
    ),
    json_output: bool = typer.Option(False, "--json-output"),
):
    """Run the pullback-support sleeve through paper-only dry-run or submit."""

    now_dt = _alpaca_policy_now()
    now = now_dt.isoformat(timespec="seconds")
    features = PullbackFeatures(
        symbol=symbol,
        current_price=Decimal(current_price),
        support_level=Decimal(support_level),
        atr=Decimal(atr),
        pullback_atr=Decimal(pullback_atr),
        above_rising_50d=above_rising_50d,
        above_rising_200d=above_rising_200d,
        sell_volume_state=sell_volume_state,
        gap_state=gap_state,
        sector_relative_strength=Decimal(sector_relative_strength),
        regime_state=regime_state,
        earnings_blackout=earnings_blackout,
        fresh_negative_event=fresh_negative_event,
        notional_usd=Decimal(notional_usd),
    )
    decision = evaluate_pullback_support(features)
    normalized_symbol = symbol.strip().upper()
    packet_run_id = f"pullback-support-paper-{normalized_symbol}-{run_id}"
    packet = build_pullback_support_run_packet(
        features,
        decision=decision,
        run_id=packet_run_id,
        as_of=now,
        source_name="cli:alpaca pullback-support-paper",
        universe_bucket="manual_cli",
    )

    payload = {
        "decision": decision.decision,
        "dry_run": dry_run,
        "score": str(decision.score),
        "reasons": decision.reasons,
        "intent": decision.intent.model_dump() if decision.intent else None,
        "paper_account_check": {"status": "not_needed_no_order_intent"},
        "planned_orders": {"accepted": [], "rejected": [], "skipped": []},
        "submitted": [],
        "failed": [],
        "packet_path": None,
    }

    audit_extra = {
        "dry_run": dry_run,
        "paper_account_check": payload["paper_account_check"],
        "planned_orders": payload["planned_orders"],
        "submitted_count": 0,
        "failed": [],
    }
    exit_code = 0

    if decision.intent:
        try:
            paper_client = _alpaca_paper_client()
            paper_account = paper_client.get_account()
            open_client_order_ids = paper_client.list_open_client_order_ids()
            payload["paper_account_check"] = {
                "status": "ok",
                "account_status": paper_account.get("status", "unknown"),
                "buying_power": paper_account.get("buying_power", "unknown"),
                "equity": paper_account.get("equity", "unknown"),
            }
        except Exception as exc:
            payload["paper_account_check"] = {
                "status": "blocked",
                "reason": f"{type(exc).__name__}: paper account check failed",
            }
            payload["failed"].append(
                {"ticket_id": decision.intent.intent_id, "reason": "paper account check failed"}
            )
            exit_code = 1
            open_client_order_ids = set()
            paper_client = None
        audit_extra["paper_account_check"] = payload["paper_account_check"]

        if paper_client is not None:
            config = _alpaca_execution_config()
            order = StrategyOrder(
                ticket_id=decision.intent.intent_id or decision.intent.idempotency_key[:16],
                symbol=decision.intent.symbol,
                side=decision.intent.side,
                notional=Decimal(decision.intent.size_usd),
                limit_price=Decimal(decision.intent.limit_price),
                time_in_force=decision.intent.tif,
            )
            paper_result = build_paper_orders(
                [order],
                config=config,
                run_id=packet_run_id,
                existing_open_client_order_ids=open_client_order_ids,
            )
            payload["planned_orders"] = _serialize_paper_result(paper_result)
            audit_extra["planned_orders"] = payload["planned_orders"]
            clean_dry_run = (
                len(paper_result.accepted) == 1
                and not paper_result.rejected
                and not paper_result.skipped
            )

            if not clean_dry_run:
                exit_code = 1 if not dry_run else 0
            elif not dry_run:
                if not config.paper_enabled:
                    payload["failed"].append(
                        {
                            "ticket_id": order.ticket_id,
                            "reason": "paper submit blocked; TRADINGAGENTS_ALPACA_PAPER_ENABLED is not true",
                        }
                    )
                    exit_code = 1
                else:
                    report = execute_paper_orders(
                        paper_result.accepted,
                        paper_client=paper_client,
                    )
                    payload["submitted"] = report.submitted
                    payload["failed"] = [
                        {"ticket_id": issue.ticket_id, "reason": issue.reason}
                        for issue in report.failed
                    ]
                    audit_extra["submitted_count"] = len(report.submitted)
                    if report.failed:
                        exit_code = 1

    audit_extra["failed"] = payload["failed"]
    packet = packet.model_copy(update={"audit": {**packet.audit, **audit_extra}})
    packet_path = write_shadow_run_packet(packet, output_dir)
    payload["packet_path"] = str(packet_path)

    if json_output:
        typer.echo(json.dumps(payload, indent=2))
    else:
        console.print(f"Pullback-support paper decision: {decision.decision}")
        console.print(f"Paper account check: {payload['paper_account_check']['status']}")
        console.print(f"Packet: {packet_path}")
        if payload["submitted"]:
            console.print(f"[green]Submitted paper orders: {len(payload['submitted'])}[/green]")
        for issue in payload["failed"]:
            console.print(f"[red]Blocked {issue['ticket_id']}: {issue['reason']}[/red]")
    if exit_code:
        raise typer.Exit(exit_code)


@paper_tournament_app.command("init")
def alpaca_paper_tournament_init(
    capital_per_strategy: float = typer.Option(10000.0, "--capital-per-strategy"),
    duration_days: int = typer.Option(31, "--duration-days", min=1, max=31),
    max_submission_market_days: int = typer.Option(
        31,
        "--max-submission-market-days",
        min=1,
        max=31,
    ),
    json_output: bool = typer.Option(False, "--json-output"),
    log_dir: Path = typer.Option(
        Path("results/paper_strategy_tournament"),
        "--log-dir",
        help="Directory for paper strategy tournament ledger and packets.",
    ),
):
    """Initialize the paper-only three-strategy tournament ledger."""
    paper_client = _alpaca_paper_client()
    paper_account = paper_client.get_account()
    paper_positions = paper_client.list_positions()
    now = _alpaca_policy_now()
    first_market_date, last_market_date = authenticated_market_date_window(
        now,
        duration_days=duration_days,
        market_day_limit=max_submission_market_days,
    )
    market_calendar = paper_client.list_calendar(start=first_market_date, end=last_market_date)
    ledger = initialize_tournament(
        paper_account=paper_account,
        paper_positions=paper_positions,
        capital_per_strategy=Decimal(str(capital_per_strategy)),
        now=now,
        duration_days=duration_days,
        max_submission_market_days=max_submission_market_days,
        market_calendar=market_calendar,
    )
    market_data = {}
    record_equity_snapshot(ledger, market_data=market_data, now=now)
    report = build_tournament_report(ledger, market_data=market_data, now=now)
    ledger["latest_report"] = report
    from tradingagents.brokers.paper_tournament import tournament_submission_lock

    # The durable initialization serializes with every other writer so an
    # abort cannot land between the retired-root guard's disk read and this
    # atomic write.  Broker/calendar reads deliberately stay outside the lock.
    with tournament_submission_lock(log_dir):
        ledger_path = write_tournament_ledger(ledger, log_dir)
    packet = {
        "kind": "paper_tournament_init",
        "ledger_path": str(ledger_path),
        "report": report,
        "strategies": ledger["strategies"],
    }
    packet_path = write_tournament_packet(packet, log_dir, prefix="paper-tournament-init")
    packet["packet_path"] = str(packet_path)
    if json_output:
        typer.echo(json.dumps(packet, indent=2))
        return
    console.print(f"[green]Paper tournament initialized at {ledger_path}[/green]")
    console.print(f"Current leader: {report['rankings'][0]['strategy_id']}")


@paper_tournament_app.command("alphainsider-watch")
def alpaca_paper_tournament_alphainsider_watch(
    fetch_recommended: bool = typer.Option(
        True,
        "--fetch-recommended/--no-fetch-recommended",
        help="Fetch AlphaInsider recommended strategies when ALPHAINSIDER_API_KEY is available.",
    ),
    strategy_type: str = typer.Option("stock", "--strategy-type"),
    max_strategies: int = typer.Option(5, "--max-strategies", min=0, max=25),
    reserved_budget_usd: str = typer.Option("30000", "--reserved-budget-usd"),
    max_allocation_per_strategy_usd: str = typer.Option("2000", "--max-allocation-per-strategy-usd"),
    json_output: bool = typer.Option(False, "--json-output"),
    log_dir: Path = typer.Option(
        Path("results/paper_strategy_tournament"),
        "--log-dir",
        help="Directory for paper strategy tournament ledger and packets.",
    ),
):
    """Plan AlphaInsider popular-strategy tracking with leftover paper budget only."""
    paper_client = _alpaca_paper_client()
    paper_account = paper_client.get_account()
    env_status = alphainsider_env_status()
    ledger = None
    try:
        ledger = load_tournament_ledger(log_dir)
    except FileNotFoundError:
        ledger = None
    recommended = []
    fetch_status = "not_requested"
    fetch_reason = "recommended strategy fetch disabled"
    if fetch_recommended:
        token_verified = False
        try:
            if env_status.get("api_key_present"):
                verify_alphainsider_token()
                token_verified = True
            recommended = compact_strategy_summaries(
                fetch_recommended_strategies(
                    strategy_type=strategy_type,
                    limit=max_strategies,
                )
            )
            fetch_status = "success"
            prefix = "token verified; " if token_verified else ""
            fetch_reason = f"{prefix}fetched {len(recommended)} recommended AlphaInsider strategies"
        except Exception as exc:
            fetch_status = "blocked"
            prefix = "token verified; " if token_verified else ""
            fetch_reason = f"{type(exc).__name__}: {prefix}{_compact_cli_error_reason(exc)}"
    plan = build_alphainsider_paper_watch_plan(
        paper_account=paper_account,
        recommended_strategies=recommended,
        ledger=ledger,
        reserved_budget=Decimal(reserved_budget_usd),
        max_strategies=max_strategies,
        max_allocation_per_strategy=Decimal(max_allocation_per_strategy_usd),
        fetch_status=fetch_status,
        fetch_reason=fetch_reason,
        env_status=env_status,
        now=_alpaca_policy_now(),
    )
    if ledger is not None:
        from tradingagents.brokers.paper_tournament import tournament_submission_lock

        # The persisted update serializes under the per-root lock and operates
        # on a fresh reload, so an interleaved abort is respected instead of
        # overwritten by the stale pre-command snapshot.  Planning above kept
        # its original early-snapshot inputs; only the durable write reloads.
        with tournament_submission_lock(log_dir):
            try:
                fresh_ledger = load_tournament_ledger(log_dir)
            except FileNotFoundError:
                fresh_ledger = None
            if fresh_ledger is not None:
                fresh_ledger["alphainsider_paper_watch_plan"] = plan
                write_tournament_ledger(fresh_ledger, log_dir)
    packet_path = write_tournament_packet(plan, log_dir, prefix="alphainsider-paper-watch")
    payload = {**plan, "packet_path": str(packet_path)}
    if json_output:
        typer.echo(json.dumps(payload, indent=2))
        return
    console.print(f"AlphaInsider paper watch: {ALPHAINSIDER_PAPER_WATCH_ID}")
    console.print(f"Available shadow budget: ${plan['available_shadow_budget_usd']}")
    console.print(f"Strategies watched: {plan['strategy_count']}")
    console.print(f"Packet: {packet_path}")


@paper_tournament_app.command("run")
def alpaca_paper_tournament_run(
    all_strategies: bool = typer.Option(False, "--all", help="Run all tournament strategies."),
    strategy: str | None = typer.Option(None, "--strategy", help="Run one strategy id."),
    dry_run: bool = typer.Option(True, "--dry-run/--submit-actions"),
    json_output: bool = typer.Option(False, "--json-output"),
    log_dir: Path = typer.Option(
        Path("results/paper_strategy_tournament"),
        "--log-dir",
        help="Directory for paper strategy tournament ledger and packets.",
    ),
    min_promotion_days: int = typer.Option(5, "--min-promotion-days"),
    shadow_start_object_id: str | None = typer.Option(
        None,
        "--shadow-start-object-id",
        help="Bind this paper-only run packet to one authenticated manual shadow-day start.",
    ),
):
    """Run one paper-only tournament tick and optionally submit paper orders."""
    from tradingagents.brokers.paper_tournament import (
        begin_submission_transaction,
        complete_submission_transaction,
        mark_submission_recovery_required,
        record_submission_response,
        remove_trial_live_strategy_selection,
        tournament_submission_lock,
        validate_submission_lease,
        validate_submission_runtime_boundary,
    )

    if not all_strategies and not strategy:
        raise typer.BadParameter("use --all or --strategy STRATEGY_ID")
    strategy_ids = list(STRATEGY_IDS) if all_strategies else [str(strategy)]
    invalid = [item for item in strategy_ids if item not in STRATEGY_IDS]
    if invalid:
        raise typer.BadParameter(f"unknown strategy id(s): {', '.join(invalid)}")

    if not isinstance(shadow_start_object_id, str):
        shadow_start_object_id = None
    shadow_start = None
    if shadow_start_object_id is not None:
        from tradingagents.evals.shadow_trial import load_shadow_record

        try:
            shadow_start = load_shadow_record(
                shadow_start_object_id,
                expected_kind="manual-shadow-day-start",
            )
        except ValueError as exc:
            raise typer.BadParameter(str(exc), param_hint="--shadow-start-object-id") from exc

    paper_client = _alpaca_paper_client()
    with tournament_submission_lock(log_dir):
        ledger = load_tournament_ledger(log_dir)
        remove_trial_live_strategy_selection(ledger, log_dir)
        now = _alpaca_policy_now()
        submission_market_date = None
        if not dry_run:
            try:
                submission_market_date = validate_submission_lease(
                    ledger,
                    paper_client=paper_client,
                    now=now,
                    post_clock_now=_alpaca_policy_now,
                )
            except ValueError as exc:
                raise typer.BadParameter(str(exc)) from exc
        try:
            paper_orders = paper_client.list_orders(status="all")
        except Exception:
            paper_orders = paper_client.list_orders(status="open")
        reconcile_tournament_orders(ledger, paper_orders, now=now)
        market_data, market_data_errors = (
            _fetch_aggressive_candidate_market_data_result()
        )
        candidate_signals = build_candidate_signals(market_data)
        actions = build_tournament_actions(
            ledger,
            candidate_signals=candidate_signals,
            market_session=market_session_label(),
            strategy_ids=strategy_ids,
        )
        payloads = build_tournament_order_payloads(actions, now=now)
        submitted = []
        if not dry_run and payloads:
            try:
                transaction_now = _alpaca_policy_now()
                transaction_market_date = validate_submission_lease(
                    ledger,
                    paper_client=paper_client,
                    now=transaction_now,
                    post_clock_now=_alpaca_policy_now,
                )
                if transaction_market_date != submission_market_date:
                    raise ValueError("paper submission lease Central market date changed")
            except ValueError as exc:
                raise typer.BadParameter(str(exc)) from exc
            try:
                begin_submission_transaction(
                    ledger,
                    market_date=str(submission_market_date),
                    payloads=payloads,
                    now=transaction_now,
                )
                write_tournament_ledger(ledger, log_dir)
                for payload in payloads:
                    post_now = _alpaca_policy_now()
                    validate_submission_runtime_boundary(
                        ledger,
                        paper_client=paper_client,
                        now=post_now,
                        expected_market_date=str(submission_market_date),
                        post_clock_now=_alpaca_policy_now,
                    )
                    order_payload = {
                        key: value
                        for key, value in payload.items()
                        if key not in {"strategy_id", "reason"}
                    }
                    response = paper_client.submit_order(order_payload)
                    response_now = _alpaca_policy_now()
                    submitted.append(
                        record_submission_response(
                            ledger,
                            payload=payload,
                            response=response,
                            market_date=str(submission_market_date),
                            now=response_now,
                        )
                    )
                    write_tournament_ledger(ledger, log_dir)
                complete_submission_transaction(ledger, now=_alpaca_policy_now())
                write_tournament_ledger(ledger, log_dir)
            except Exception as exc:
                mark_submission_recovery_required(
                    ledger,
                    reason=str(exc),
                    now=_alpaca_policy_now(),
                )
                write_tournament_ledger(ledger, log_dir)
                raise typer.BadParameter("paper submission recovery is required") from exc
        record_equity_snapshot(ledger, market_data=market_data, now=now)
        report = build_tournament_report(
            ledger,
            market_data=market_data,
            now=now,
            min_promotion_days=min_promotion_days,
        )
        selection_path = None
        if not dry_run or report.get("ledger_type") == "qualification_paper_trial":
            selection = maybe_write_live_strategy_selection(report, log_dir, now=now)
            selection_path = str(selection) if selection else None
            if selection_path:
                ledger["live_strategy_selection"] = report["live_strategy_candidate"]
        ledger["latest_report"] = report
        ledger_path = write_tournament_ledger(ledger, log_dir)
    packet = {
        "kind": "paper_tournament_run",
        "generated_at": now.isoformat(timespec="seconds"),
        "dry_run": dry_run,
        "strategy_ids": strategy_ids,
        "actions": [
            {
                "strategy_id": action.strategy_id,
                "action": action.action,
                "symbol": action.symbol,
                "notional": str(action.notional),
                "limit_price": str(action.limit_price),
                "reason": action.reason,
            }
            for action in actions
        ],
        "payloads": payloads,
        "submitted": submitted,
        "submitted_count": len(submitted),
        "ledger_path": str(ledger_path),
        "live_selection_path": selection_path,
        "report": report,
        "status": (
            "COMPLETE"
            if submitted
            else ("NO_PAPER_SIGNAL" if not payloads else "HOLD")
        ),
        "analysis_only": True,
        "execution_authority": "none",
        "can_submit_orders": False,
        "errors": market_data_errors,
    }
    if shadow_start is not None:
        start_payload = shadow_start.payload
        packet["shadow_start_object_id"] = shadow_start.object_id
        packet["run_id"] = start_payload["run_id"]
        packet["market_date"] = start_payload["market_date"]
    packet_path = write_tournament_packet(packet, log_dir, prefix="paper-tournament-run")
    packet["packet_path"] = str(packet_path)
    if json_output:
        typer.echo(json.dumps(packet, indent=2))
        return
    console.print(f"[green]Paper tournament tick written to {packet_path}[/green]")
    console.print(f"Submitted paper orders: {len(submitted)}")
    if report["rankings"]:
        console.print(f"Leader: {report['rankings'][0]['strategy_id']}")


@paper_tournament_app.command("finalize")
def alpaca_paper_tournament_finalize(
    json_output: bool = typer.Option(False, "--json-output"),
    log_dir: Path = typer.Option(
        Path("results/paper_strategy_tournament"),
        "--log-dir",
        help="Directory for paper strategy tournament ledger and packets.",
    ),
):
    """Reconcile tournament paper orders and permanently close its submit lease."""
    from tradingagents.brokers.paper_tournament import (
        _validate_exact_paper_client,
        finalize_submission_lease,
        tournament_submission_lock,
        validate_submission_transaction_state,
    )

    paper_client = _alpaca_paper_client()
    with tournament_submission_lock(log_dir):
        ledger = load_tournament_ledger(log_dir)
        try:
            _validate_exact_paper_client(paper_client)
            validate_submission_transaction_state(ledger)
        except ValueError as exc:
            raise typer.BadParameter(str(exc)) from exc
        now = _alpaca_policy_now()
        try:
            paper_orders = paper_client.list_orders(status="all")
        except Exception as exc:
            raise typer.BadParameter("paper finalization requires complete paper-order reconciliation") from exc
        try:
            finalization = finalize_submission_lease(
                ledger,
                paper_client=paper_client,
                paper_orders=paper_orders,
                now=now,
            )
        except ValueError as exc:
            raise typer.BadParameter(str(exc)) from exc
        ledger_path = write_tournament_ledger(ledger, log_dir)
    packet = {
        "kind": "paper_tournament_finalize",
        "generated_at": now.isoformat(timespec="seconds"),
        "ledger_path": str(ledger_path),
        "submission_window_status": ledger.get("submission_window_status"),
        "finalization": finalization,
    }
    packet_path = write_tournament_packet(packet, log_dir, prefix="paper-tournament-finalize")
    packet["packet_path"] = str(packet_path)
    if json_output:
        typer.echo(json.dumps(packet, indent=2))
        return
    console.print(f"[green]Paper tournament submission lease finalized at {ledger_path}[/green]")


@paper_tournament_app.command("abort-submission-lease")
def alpaca_paper_tournament_abort_submission_lease(
    reason: str = typer.Option(..., "--reason", help="Operator reason for retiring this root."),
    json_output: bool = typer.Option(False, "--json-output"),
    log_dir: Path = typer.Option(
        Path("results/paper_strategy_tournament"),
        "--log-dir",
        help="Directory containing the paper strategy tournament ledger.",
    ),
):
    """Permanently retire a recovery-required paper root without any broker call."""

    from tradingagents.brokers.paper_tournament import (
        abort_submission_lease,
        load_tournament_ledger,
        tournament_submission_lock,
        write_tournament_ledger,
    )

    with tournament_submission_lock(log_dir):
        ledger = load_tournament_ledger(log_dir)
        now = _alpaca_policy_now()
        try:
            abortion = abort_submission_lease(ledger, reason=reason, now=now)
        except ValueError as exc:
            raise typer.BadParameter(str(exc)) from exc
        ledger_path = write_tournament_ledger(ledger, log_dir)
    packet = {
        "kind": "paper_tournament_abort",
        "generated_at": now.isoformat(timespec="seconds"),
        "ledger_path": str(ledger_path),
        "submission_window_status": ledger.get("submission_window_status"),
        "abortion": abortion,
        "analysis_only": True,
        "execution_authority": "none",
        "can_submit_orders": False,
    }
    packet_path = write_tournament_packet(packet, log_dir, prefix="paper-tournament-abort")
    packet["packet_path"] = str(packet_path)
    if json_output:
        typer.echo(json.dumps(packet, indent=2))
        return
    console.print(f"[red]Paper submission lease aborted at {ledger_path}[/red]")
    console.print("This root is permanently retired; initialize a fresh root for a replacement trial.")


@paper_tournament_app.command("report")
def alpaca_paper_tournament_report(
    json_output: bool = typer.Option(False, "--json-output"),
    log_dir: Path = typer.Option(
        Path("results/paper_strategy_tournament"),
        "--log-dir",
        help="Directory for paper strategy tournament ledger and packets.",
    ),
    min_promotion_days: int = typer.Option(5, "--min-promotion-days"),
):
    """Render the paper-only strategy tournament report."""
    from tradingagents.brokers.paper_tournament import (
        remove_trial_live_strategy_selection,
        tournament_submission_lock,
    )

    paper_client = _alpaca_paper_client()
    with tournament_submission_lock(log_dir):
        ledger = load_tournament_ledger(log_dir)
        remove_trial_live_strategy_selection(ledger, log_dir)
        now = _alpaca_policy_now()
        try:
            paper_orders = paper_client.list_orders(status="all")
        except Exception:
            paper_orders = paper_client.list_orders(status="open")
        reconcile_tournament_orders(ledger, paper_orders, now=now)
        market_data, market_data_errors = (
            _fetch_aggressive_candidate_market_data_result()
        )
        record_equity_snapshot(ledger, market_data=market_data, now=now)
        report = build_tournament_report(
            ledger,
            market_data=market_data,
            now=now,
            min_promotion_days=min_promotion_days,
        )
        selection = maybe_write_live_strategy_selection(report, log_dir, now=now)
        ledger["latest_report"] = report
        write_tournament_ledger(ledger, log_dir)
    packet = {
        "kind": "paper_tournament_report",
        "generated_at": now.isoformat(timespec="seconds"),
        "report": report,
        "live_selection_path": str(selection) if selection else None,
        "errors": market_data_errors,
    }
    packet_path = write_tournament_packet(packet, log_dir, prefix="paper-tournament-report")
    packet["packet_path"] = str(packet_path)
    if json_output:
        typer.echo(json.dumps(packet, indent=2))
        return
    console.print(f"[green]Paper tournament report written to {packet_path}[/green]")
    for item in report["rankings"]:
        console.print(
            f"{item['strategy_id']}: equity ${item['equity']} "
            f"return ${item['total_return']} ({item['total_return_pct']}%)"
        )


@alpaca_app.command("plan-overnight")
def alpaca_plan_overnight(
    json_output: bool = typer.Option(False, "--json-output"),
    compact_json_output: bool = typer.Option(
        False,
        "--compact-json-output",
        help="When used with --json-output, print a compact lossless-by-reference summary instead of the full raw packet.",
    ),
    log_dir: Path = typer.Option(
        Path("results/overnight_plans"),
        "--log-dir",
        help="Directory for overnight planning packets.",
    ),
    trade_date: str | None = typer.Option(
        None,
        "--trade-date",
        help=(
            "Analysis date for the TradingAgents graph. Defaults to the local "
            "Central date, rolling weekend runs forward to the next weekday."
        ),
    ),
    full_graph_tickers: int = typer.Option(
        3,
        "--full-graph-tickers",
        min=0,
        help="Maximum number of ranked tradable tickers to run through the full TradingAgents graph.",
    ),
    per_ticker_timeout_minutes: float = typer.Option(
        5.0,
        "--per-ticker-timeout-minutes",
        min=0,
        help="Timeout for each full-graph ticker. Use 0 to run in-process without timeout.",
    ),
    time_budget_minutes: float = typer.Option(
        25.0,
        "--time-budget-minutes",
        min=0,
        help="Soft total time budget for full-graph ticker work. Remaining tickers use fallback scoring.",
    ),
    overnight_graph_profile: str = typer.Option(
        "full",
        "--overnight-graph-profile",
        help="TradingAgents graph profile for full-graph tickers: full, compact, market-news, or market-only.",
    ),
    overnight_llm_provider: str | None = typer.Option(
        None,
        "--overnight-llm-provider",
        help="Optional LLM provider override for overnight full-graph work only.",
    ),
    overnight_quick_think_llm: str | None = typer.Option(
        None,
        "--overnight-quick-think-llm",
        help="Optional quick-thinking model override for overnight full-graph work only.",
    ),
    overnight_deep_think_llm: str | None = typer.Option(
        None,
        "--overnight-deep-think-llm",
        help="Optional deep-thinking model override for overnight full-graph work only.",
    ),
    overnight_backend_url: str | None = typer.Option(
        None,
        "--overnight-backend-url",
        help="Optional backend URL override for overnight full-graph work only.",
    ),
    overnight_max_completion_tokens: int | None = typer.Option(
        None,
        "--overnight-max-completion-tokens",
        min=1,
        help="Optional output-token cap for overnight full-graph work; useful for slow local models.",
    ),
    overnight_llm_timeout_seconds: float | None = typer.Option(
        None,
        "--overnight-llm-timeout-seconds",
        min=1,
        help="Optional per-LLM-call timeout for overnight full-graph work.",
    ),
    overnight_llm_max_retries: int | None = typer.Option(
        None,
        "--overnight-llm-max-retries",
        min=0,
        help="Optional LLM retry count for overnight full-graph work.",
    ),
    write_latest: bool = typer.Option(
        True,
        "--write-latest/--no-write-latest",
        help="Update latest.json/latest.md. Use --no-write-latest for manual probes that should not feed automations.",
    ),
    include_research_context: bool = typer.Option(
        True,
        "--include-research-context/--no-research-context",
        help="Attach analysis-only provider fallback, Reddit, and social watchlist context to the overnight packet.",
    ),
    research_context_dir: Path | None = typer.Option(
        None,
        "--research-context-dir",
        help="Directory for overnight research context packets. Defaults to LOG_DIR/research_context.",
    ),
    release_calendar_config_path: Path = typer.Option(
        Path("config/release_calendar_watchlist.json"),
        "--release-calendar-config-path",
        help="Repo-local official release-calendar context config.",
    ),
    source_quality_review_path: Path = typer.Option(
        Path("results/source_quality/latest.json"),
        "--source-quality-review-path",
        help="Latest source-quality review used to downrank stale/weak overnight research sources.",
    ),
    source_quality_ordering: bool = typer.Option(
        True,
        "--source-quality-ordering/--no-source-quality-ordering",
        help="Use source-quality strengths to order overnight provider fallbacks when the review exists.",
    ),
    include_agent_intelligence: bool = typer.Option(
        True,
        "--include-agent-intelligence/--no-agent-intelligence",
        help=(
            "Attach earned agent influence weights and supported hypothesis priors "
            "as advisory research context."
        ),
    ),
    top_provider_bundle_count: int = typer.Option(
        3,
        "--top-provider-bundle-count",
        min=0,
        help=(
            "Number of top-ranked overnight candidates to refresh with analysis-only "
            "ticker provider bundles. Use 0 to disable for probes."
        ),
    ),
    top_provider_bundle_output_dir: Path = typer.Option(
        Path("results/research_evidence"),
        "--top-provider-bundle-output-dir",
        help="Directory for top-candidate provider evidence packets.",
    ),
    top_provider_bundle_cache_dir: Path = typer.Option(
        Path("results/research_provider_cache"),
        "--top-provider-bundle-cache-dir",
        help="Cache directory for top-candidate provider evidence fetches.",
    ),
    depleted_research_sources: str = typer.Option(
        "",
        "--depleted-research-sources",
        help="Comma-separated research sources that are out of calls or temporarily exhausted.",
    ),
    disabled_research_sources: str = typer.Option(
        "",
        "--disabled-research-sources",
        help="Comma-separated research sources to skip for this overnight run.",
    ),
    write_agent_ledger: bool = typer.Option(
        True,
        "--write-agent-ledger/--no-agent-ledger",
        help="Append scoreable TradingAgents role forecasts to the Agent Intelligence Ledger.",
    ),
    agent_ledger_path: Path = typer.Option(
        DEFAULT_LEDGER_PATH,
        "--agent-ledger-path",
        help="Agent Intelligence Ledger JSONL path.",
    ),
):
    """Run the analysis-only overnight TradingAgents planning pass."""
    expected_trade_date = _default_overnight_trade_date()
    run_date = trade_date or expected_trade_date
    if trade_date and write_latest and run_date != expected_trade_date:
        raise typer.BadParameter(
            (
                f"{run_date} does not match the current expected overnight "
                f"trade date {expected_trade_date}; rerun with --no-write-latest "
                "for historical probes so automation latest.json stays current."
            ),
            param_hint="--trade-date",
        )
    paper_client, live_client = _alpaca_clients()
    live_account = live_client.get_account()
    paper_account = paper_client.get_account()
    live_positions = live_client.list_positions()
    paper_positions = paper_client.list_positions()
    live_open_orders = live_client.list_orders(status="open")
    paper_open_orders = paper_client.list_orders(status="open")
    recent_packets = _latest_supervisor_packets(Path("results/hourly_supervisor"), limit=12)
    current_market_data, market_data_errors = (
        _fetch_aggressive_candidate_market_data_result()
    )
    research_context = {
        "analysis_only": True,
        "status": "disabled",
        "reason": "overnight research context was disabled by command option",
        "execution_authority": "none",
        "forbidden_effects": [
            "create_trade_intent",
            "size_position",
            "submit_order",
            "promote_sleeve",
            "waive_live_gate",
        ],
    }
    if include_research_context:
        context_result = write_overnight_research_context(
            output_dir=research_context_dir or (log_dir / "research_context"),
            release_calendar_config_path=release_calendar_config_path,
            source_quality_review_path=source_quality_review_path,
            source_quality_ordering=source_quality_ordering,
            depleted_sources=_parse_source_csv(depleted_research_sources),
            disabled_sources=_parse_source_csv(disabled_research_sources),
            include_agent_intelligence=include_agent_intelligence,
        )
        research_context = context_result.summary
    current_market_data = _apply_mirofish_market_priors_to_market_data(
        current_market_data,
        research_context,
    )
    current_candidate_signals = build_candidate_signals(current_market_data)
    if current_candidate_signals:
        recent_packets = [
            {
                "generated_at": datetime.datetime.now(tz=datetime.timezone.utc).isoformat(timespec="seconds"),
                "source": "current_ranked_candidates",
                "ranked_candidates": [
                    {"symbol": signal.symbol, "score": str(signal.score)}
                    for signal in current_candidate_signals
                ],
            }
        ] + recent_packets
    candidate_universe = build_overnight_candidate_universe(
        live_positions=live_positions,
        paper_positions=paper_positions,
        live_open_orders=live_open_orders,
        paper_open_orders=paper_open_orders,
        recent_supervisor_packets=recent_packets,
        market_packet_paths=_load_recent_market_packet_paths(),
        watchlist_paths=_default_watchlist_paths(),
        base_universe=AGGRESSIVE_CANDIDATE_UNIVERSE,
    )
    tradable_universe: list[dict] = []
    rejected_symbols: list[dict] = []
    for candidate in candidate_universe:
        tradable, reason = _is_tradable_stock(live_client, candidate["symbol"])
        if tradable:
            tradable_universe.append(candidate)
        else:
            rejected_symbols.append({"symbol": candidate["symbol"], "reason": reason})
    if include_research_context:
        research_context["consumer"] = {
            "overnight_candidate_symbols": [candidate["symbol"] for candidate in candidate_universe],
            "tradable_symbols": [candidate["symbol"] for candidate in tradable_universe],
            "live_position_symbols": [
                str(position.get("symbol", "")).strip().upper()
                for position in live_positions
                if isinstance(position, dict) and str(position.get("symbol", "")).strip()
            ],
            "paper_position_symbols": [
                str(position.get("symbol", "")).strip().upper()
                for position in paper_positions
                if isinstance(position, dict) and str(position.get("symbol", "")).strip()
            ],
        }
    graph_config_overrides = _build_overnight_graph_config_overrides(
        graph_profile=overnight_graph_profile,
        llm_provider=overnight_llm_provider,
        quick_think_llm=overnight_quick_think_llm,
        deep_think_llm=overnight_deep_think_llm,
        backend_url=overnight_backend_url,
        max_completion_tokens=overnight_max_completion_tokens,
        llm_timeout_seconds=overnight_llm_timeout_seconds,
        llm_max_retries=overnight_llm_max_retries,
    )
    requested_full_graph_tickers = full_graph_tickers
    graph_disabled_reason = graph_config_overrides.get("overnight_graph_disabled_reason")
    effective_full_graph_tickers = 0 if graph_disabled_reason else full_graph_tickers
    ticker_results: list[dict] = []
    signal_by_symbol = {signal.symbol: signal for signal in current_candidate_signals}
    started_at = datetime.datetime.now(tz=datetime.timezone.utc)
    deadline = (
        started_at + datetime.timedelta(minutes=time_budget_minutes)
        if time_budget_minutes > 0
        else None
    )
    full_graph_count = 0
    full_graph_attempt_count = 0
    full_graph_success_count = 0
    bounded_prefetch_retry_count = 0
    bounded_prefetch_retry_success_count = 0
    fallback_count = 0
    graph_failure_count = 0
    graph_attempt_failure_count = 0
    sorted_tradable_universe = sorted(
        tradable_universe,
        key=lambda item: (
            signal_by_symbol.get(item["symbol"], CandidateSignal(
                symbol=item["symbol"],
                score=Decimal("0.50"),
                current_price=Decimal("0"),
            )).score,
            item["symbol"],
        ),
        reverse=True,
    )
    for candidate in sorted_tradable_universe:
        symbol = candidate["symbol"]
        signal = signal_by_symbol.get(symbol)
        budget_exhausted = deadline is not None and datetime.datetime.now(tz=datetime.timezone.utc) >= deadline
        should_run_full_graph = full_graph_count < effective_full_graph_tickers and not budget_exhausted
        if should_run_full_graph:
            graph_result = _run_overnight_ticker_analysis_guarded(
                symbol=symbol,
                trade_date=run_date,
                output_dir=log_dir,
                timeout_seconds=per_ticker_timeout_minutes * 60,
                graph_config_overrides=graph_config_overrides,
            )
            full_graph_attempt_count += 1
            if graph_result.get("status") == "ok":
                result = dict(graph_result)
                result.setdefault("method", "original_tradingagents_graph")
                full_graph_count += 1
                full_graph_success_count += 1
            else:
                graph_attempt_failure_count += 1
                can_retry_with_prefetch = (
                    _is_bounded_prefetch_retry_candidate(
                        graph_result,
                        graph_config_overrides,
                    )
                    and (
                        deadline is None
                        or datetime.datetime.now(tz=datetime.timezone.utc) < deadline
                    )
                )
                retry_result = None
                retry_timeout_seconds = per_ticker_timeout_minutes * 60
                if can_retry_with_prefetch and deadline is not None:
                    remaining_budget_seconds = max(
                        0.0,
                        (
                            deadline
                            - datetime.datetime.now(tz=datetime.timezone.utc)
                        ).total_seconds(),
                    )
                    if remaining_budget_seconds <= 0:
                        can_retry_with_prefetch = False
                    elif retry_timeout_seconds <= 0:
                        retry_timeout_seconds = remaining_budget_seconds
                    else:
                        retry_timeout_seconds = min(
                            retry_timeout_seconds,
                            remaining_budget_seconds,
                        )
                if can_retry_with_prefetch:
                    retry_overrides = dict(graph_config_overrides)
                    retry_overrides["overnight_graph_profile"] = (
                        "full-bounded-prefetch-retry"
                    )
                    retry_overrides["tool_free_analysts"] = list(
                        retry_overrides.get(
                            "_selected_analysts",
                            ["market", "social", "news", "fundamentals"],
                        )
                    )
                    bounded_prefetch_retry_count += 1
                    full_graph_attempt_count += 1
                    retry_result = _run_overnight_ticker_analysis_guarded(
                        symbol=symbol,
                        trade_date=run_date,
                        output_dir=log_dir,
                        timeout_seconds=retry_timeout_seconds,
                        graph_config_overrides=retry_overrides,
                    )
                if retry_result and retry_result.get("status") == "ok":
                    result = dict(retry_result)
                    result["method"] = (
                        "original_tradingagents_graph_bounded_prefetch_retry"
                    )
                    result["bounded_prefetch_retry"] = True
                    result["initial_graph_error"] = graph_result.get("error")
                    result["initial_graph_error_type"] = graph_result.get(
                        "error_type"
                    )
                    result["initial_graph_error_stage"] = graph_result.get(
                        "error_stage"
                    )
                    full_graph_count += 1
                    full_graph_success_count += 1
                    bounded_prefetch_retry_success_count += 1
                else:
                    if retry_result:
                        graph_attempt_failure_count += 1
                    graph_failure_count += 1
                    fallback_count += 1
                    full_graph_count += 1
                    result = _fallback_overnight_ticker_result(
                        symbol=symbol,
                        candidate=candidate,
                        candidate_signal=signal,
                        reason="Full TradingAgents graph failed or timed out; ranked with market snapshot fallback so the overnight packet can still complete.",
                        graph_result=retry_result or graph_result,
                    )
                    if retry_result:
                        result["initial_graph_error"] = graph_result.get("error")
                        result["initial_graph_error_type"] = graph_result.get(
                            "error_type"
                        )
                        result["initial_graph_error_stage"] = graph_result.get(
                            "error_stage"
                        )
        else:
            fallback_count += 1
            result = _fallback_overnight_ticker_result(
                symbol=symbol,
                candidate=candidate,
                candidate_signal=signal,
                reason=(
                    "Skipped full TradingAgents graph due to overnight runtime bounds; "
                    "ranked with the shared market snapshot fallback."
                ),
            )
        ticker_results.append(result)
        _write_overnight_ticker_report(log_dir, result)

    generated_at = datetime.datetime.now(tz=datetime.timezone.utc).isoformat(timespec="seconds")
    ranked = _rank_overnight_results(ticker_results)
    top_provider_bundles = _write_overnight_top_provider_bundles(
        ranked,
        top_n=top_provider_bundle_count,
        output_dir=top_provider_bundle_output_dir,
        cache_dir=top_provider_bundle_cache_dir,
        source_quality_review_path=(
            source_quality_review_path
            if source_quality_ordering and source_quality_review_path.exists()
            else None
        ),
        depleted_sources=_parse_source_csv(depleted_research_sources),
        disabled_sources=_parse_source_csv(disabled_research_sources),
    )
    completion_status, completion_reasons = _overnight_graph_completion_status(
        requested_full_graph_tickers=requested_full_graph_tickers,
        effective_full_graph_tickers=effective_full_graph_tickers,
        tradable_count=len(tradable_universe),
        full_graph_count=full_graph_count,
        full_graph_success_count=full_graph_success_count,
        graph_failure_count=graph_failure_count,
        graph_disabled_reason=graph_disabled_reason,
    )
    graph_config = _sanitize_overnight_graph_config(graph_config_overrides)
    original_graph = _build_original_tradingagents_graph_packet(
        ticker_results=ticker_results,
        full_graph_tickers=effective_full_graph_tickers,
        per_ticker_timeout_minutes=per_ticker_timeout_minutes,
        time_budget_minutes=time_budget_minutes,
        graph_config=graph_config,
    )
    packet = {
        "generated_at": generated_at,
        "analysis_only": True,
        "trade_date": run_date,
        "methodology": "Bounded overnight TradingAgents pass: every tradable ticker receives the same market snapshot fallback rubric; top-ranked tickers run the full graph when runtime bounds allow.",
        "equal_weighting": "Every candidate receives the same research priority and scoring rubric; current holdings are portfolio context only.",
        "overnight_quality": {
            "started_at": started_at.isoformat(timespec="seconds"),
            "full_graph_limit": effective_full_graph_tickers,
            "requested_full_graph_limit": requested_full_graph_tickers,
            "graph_disabled_reason": graph_disabled_reason,
            "full_graph_count": full_graph_count,
            "full_graph_attempt_count": full_graph_attempt_count,
            "full_graph_success_count": full_graph_success_count,
            "bounded_prefetch_retry_count": bounded_prefetch_retry_count,
            "bounded_prefetch_retry_success_count": (
                bounded_prefetch_retry_success_count
            ),
            "fallback_count": fallback_count,
            "graph_failure_count": graph_failure_count,
            "graph_attempt_failure_count": graph_attempt_failure_count,
            "completion_status": completion_status,
            "completion_reasons": completion_reasons,
            "tradable_count": len(tradable_universe),
            "ranked_count": len(ranked),
            "per_ticker_timeout_minutes": per_ticker_timeout_minutes,
            "time_budget_minutes": time_budget_minutes,
            "original_graph_selected_tickers": original_graph["selected_tickers"],
            "original_graph_successful_tickers": original_graph["successful_tickers"],
            "original_graph_failed_tickers": original_graph["failed_tickers"],
            "graph_config": graph_config,
            "research_context_packet_count": research_context.get("packet_count", 0),
            "research_context_blocked_count": len(research_context.get("blocked_packets", [])),
            "research_context_enabled": include_research_context,
            "agent_intelligence_enabled": (
                include_research_context and include_agent_intelligence
            ),
            "agent_ledger_append_enabled": write_agent_ledger,
            "top_provider_bundle_requested_count": top_provider_bundle_count,
            "top_provider_bundle_count": top_provider_bundles.get("bundle_count", 0),
            "top_provider_bundle_symbols": top_provider_bundles.get("symbols", []),
            "top_provider_bundle_gap_count": top_provider_bundles.get("gap_packet_count", 0),
            "top_provider_bundle_error_count": top_provider_bundles.get("error_count", 0),
            "top_provider_bundle_missing_non_gap_needs": top_provider_bundles.get(
                "evidence_needs_without_non_gap_packets",
                [],
            ),
            "completed_at": generated_at,
        },
        "original_tradingagents_graph": original_graph,
        "accounts": {
            "live": {
                "status": live_account.get("status"),
                "equity": live_account.get("equity"),
                "buying_power": live_account.get("buying_power"),
            },
            "paper": {
                "status": paper_account.get("status"),
                "equity": paper_account.get("equity"),
                "buying_power": paper_account.get("buying_power"),
            },
        },
        "candidate_universe": candidate_universe,
        "tradable_universe": tradable_universe,
        "rejected_symbols": rejected_symbols,
        "ranked_candidates": ranked,
        "ticker_results": ticker_results,
        "research_context": research_context,
        "top_provider_bundles": top_provider_bundles,
        "submitted": [],
        "errors": market_data_errors,
    }
    if write_agent_ledger:
        ledger_forecasts = forecasts_from_overnight_packet(packet)
        appended_forecasts = append_forecasts(ledger_forecasts, path=agent_ledger_path)
        packet["agent_intelligence_ledger"] = {
            "ledger_path": str(agent_ledger_path),
            "forecast_count": len(ledger_forecasts),
            "appended_count": appended_forecasts,
            "analysis_only": True,
            "execution_authority": "none",
        }
    packet_path = write_overnight_plan_packet(packet, output_dir=log_dir, write_latest=write_latest)
    payload = dict(packet)
    payload["packet_path"] = str(packet_path)
    if json_output:
        if compact_json_output:
            typer.echo(json.dumps(_compact_overnight_plan_payload(packet, packet_path), indent=2))
            return
        typer.echo(json.dumps(payload, indent=2))
        return
    console.print(f"[green]Overnight plan written to {packet_path}[/green]")
    if ranked:
        console.print(f"Top candidate: {ranked[0]['symbol']} ({ranked[0]['rating']})")


@alpaca_app.command("premarket-brief")
def alpaca_premarket_brief(
    json_output: bool = typer.Option(False, "--json-output"),
    compact_json_output: bool = typer.Option(
        False,
        "--compact-json-output",
        help="When used with --json-output, print a compact lossless-by-reference summary instead of the full raw packet.",
    ),
    log_dir: Path = typer.Option(
        Path("results/premarket_briefs"),
        "--log-dir",
        help="Directory for rolling premarket brief packets.",
    ),
    hourly_log_dir: Path = typer.Option(
        Path("results/hourly_supervisor"),
        "--hourly-log-dir",
        help="Directory containing hourly supervisor packets.",
    ),
    overnight_log_dir: Path = typer.Option(
        Path("results/overnight_plans"),
        "--overnight-log-dir",
        help="Directory containing overnight planning packets.",
    ),
    paper_tournament_log_dir: Path = typer.Option(
        Path("results/paper_strategy_tournament"),
        "--paper-tournament-log-dir",
        help="Directory containing paper tournament packets.",
    ),
    write_latest: bool = typer.Option(
        True,
        "--write-latest/--no-write-latest",
        help="Update latest.json/latest.md. Use --no-write-latest for manual probes.",
    ),
):
    """Build a read-only rolling premarket brief from local TradingAgents packets."""
    previous_brief = load_latest_premarket_brief(log_dir)
    packet = build_premarket_brief_packet(
        hourly_log_dir=hourly_log_dir,
        overnight_log_dir=overnight_log_dir,
        paper_tournament_log_dir=paper_tournament_log_dir,
        previous_brief=previous_brief,
    )
    packet_path = write_premarket_brief_packet(packet, output_dir=log_dir, write_latest=write_latest)
    payload = dict(packet)
    payload["packet_path"] = str(packet_path)
    if json_output:
        if compact_json_output:
            typer.echo(json.dumps(_compact_premarket_brief_payload(packet, packet_path), indent=2))
            return
        typer.echo(json.dumps(payload, indent=2))
        return
    console.print(f"[green]Premarket brief written to {packet_path}[/green]")
    top_symbol = (packet.get("premarket_instructions") or {}).get("top_symbol") or "none"
    console.print(f"Top symbol to validate: {top_symbol}")


@alpaca_app.command("preopen-validation")
def alpaca_preopen_validation(
    json_output: bool = typer.Option(False, "--json-output"),
    compact_json_output: bool = typer.Option(
        False,
        "--compact-json-output",
        help="When used with --json-output, print compact context instead of the full packet.",
    ),
    log_dir: Path = typer.Option(
        Path("results/preopen_validation"),
        "--log-dir",
        help="Directory for analysis-only pre-open validation packets.",
    ),
    premarket_brief_log_dir: Path = typer.Option(
        Path("results/premarket_briefs"),
        "--premarket-brief-log-dir",
        help="Directory containing rolling premarket brief packets.",
    ),
    overnight_log_dir: Path = typer.Option(
        Path("results/overnight_plans"),
        "--overnight-log-dir",
        help="Directory containing overnight planning packets.",
    ),
    live_control_path: Path = typer.Option(
        Path("results/policy/live_control.json"),
        "--live-control-path",
        help="Live-control state to read without refreshing it.",
    ),
    risk_envelope_path: Path = typer.Option(
        Path("config/risk_envelope.yaml"),
        "--risk-envelope-path",
        help="Risk envelope to parse for sizing-readiness evidence only.",
    ),
    write_latest: bool = typer.Option(
        True,
        "--write-latest/--no-write-latest",
        help="Update latest.json/latest-compact.json. Use --no-write-latest for n8n/manual probes.",
    ),
):
    """Write an analysis-only pre-open validation packet from fresh broker/context reads."""
    generated_at = _alpaca_policy_now()
    market_session = market_session_label(generated_at)
    broker_errors: dict[str, str] = {}
    paper_account: dict[str, Any] = {}
    live_account: dict[str, Any] = {}
    paper_positions: list[dict[str, Any]] = []
    live_positions: list[dict[str, Any]] = []
    paper_open_orders: list[dict[str, Any]] = []
    live_open_orders: list[dict[str, Any]] = []

    try:
        paper_client, live_client = _alpaca_clients()
    except Exception as exc:  # noqa: BLE001 - preserve setup failure in packet.
        broker_errors["clients"] = f"Alpaca clients could not be initialized: {exc}"
    else:
        paper_account, error = _broker_read("paper account", paper_client.get_account, {})
        if error:
            broker_errors["paper_account"] = error
        live_account, error = _broker_read("live account", live_client.get_account, {})
        if error:
            broker_errors["live_account"] = error
        paper_positions, error = _broker_read("paper positions", paper_client.list_positions, [])
        if error:
            broker_errors["paper_positions"] = error
        live_positions, error = _broker_read("live positions", live_client.list_positions, [])
        if error:
            broker_errors["live_positions"] = error
        paper_open_orders, error = _broker_read(
            "paper open orders",
            lambda: paper_client.list_orders(status="open"),
            [],
        )
        if error:
            broker_errors["paper_open_orders"] = error
        live_open_orders, error = _broker_read(
            "live open orders",
            lambda: live_client.list_orders(status="open"),
            [],
        )
        if error:
            broker_errors["live_open_orders"] = error

    market_data, market_data_errors = (
        _fetch_aggressive_candidate_market_data_result()
    )
    broker_errors.update(market_data_errors)
    held_symbols = [str(position.get("symbol", "")) for position in live_positions]
    candidate_signals = build_candidate_signals(market_data, held_symbols=held_symbols)

    premarket_path = _latest_json_packet_path(
        premarket_brief_log_dir,
        "premarket-brief-*.json",
    )
    premarket_packet = _read_json_packet(premarket_path)
    premarket_validation = validate_premarket_brief_against_candidates(
        premarket_packet,
        candidate_signals,
        now=generated_at,
    )
    overnight_packet = load_latest_overnight_plan(overnight_log_dir)
    overnight_validation = validate_overnight_plan_against_candidates(
        overnight_packet,
        candidate_signals,
        now=generated_at,
    )
    live_control_state, live_control_issues = load_live_control_state(
        live_control_path,
        now=generated_at,
    )
    risk_envelope, risk_envelope_issues = load_risk_envelope(risk_envelope_path)
    packet = _build_preopen_validation_packet(
        generated_at=generated_at,
        market_session=market_session,
        live_account=live_account,
        paper_account=paper_account,
        live_positions=live_positions,
        paper_positions=paper_positions,
        live_open_orders=live_open_orders,
        paper_open_orders=paper_open_orders,
        broker_errors=broker_errors,
        market_data=market_data,
        candidate_signals=candidate_signals,
        premarket_packet=premarket_packet,
        premarket_path=premarket_path,
        premarket_validation=premarket_validation,
        overnight_validation=overnight_validation,
        live_control_state=live_control_state,
        live_control_issues=live_control_issues,
        risk_envelope_issues=risk_envelope_issues,
        risk_envelope_mode=(
            risk_envelope.live_budget_mode if risk_envelope is not None else None
        ),
    )
    packet_path = write_preopen_validation_packet(
        packet,
        output_dir=log_dir,
        write_latest=write_latest,
    )
    if json_output:
        if compact_json_output:
            typer.echo(json.dumps(compact_preopen_validation_payload(packet, packet_path), indent=2))
        else:
            payload = {**packet, "packet_path": str(packet_path)}
            typer.echo(json.dumps(payload, indent=2))
        return
    status_style = "green" if packet["overall_status"] == "pass" else (
        "yellow" if packet["overall_status"] == "pass_with_warnings" else "red"
    )
    console.print(f"[{status_style}]Pre-open validation: {packet['overall_status']}[/{status_style}]")
    console.print(f"Packet: {packet_path}")


@alpaca_app.command("verify-overnight-system")
def alpaca_verify_overnight_system(
    json_output: bool = typer.Option(False, "--json-output"),
    max_overnight_age_hours: float = typer.Option(
        30.0,
        "--max-overnight-age-hours",
        help=(
            "Warn when the latest raw overnight plan is older than this many hours. "
            "Use 0 to disable the age check for historical tests."
        ),
    ),
    log_dir: Path = typer.Option(
        Path("results/overnight_system_verification"),
        "--log-dir",
        help="Directory for overnight-system verification packets.",
    ),
    overnight_log_dir: Path = typer.Option(
        Path("results/overnight_plans"),
        "--overnight-log-dir",
        help="Directory containing overnight planning packets.",
    ),
    premarket_brief_log_dir: Path = typer.Option(
        Path("results/premarket_briefs"),
        "--premarket-brief-log-dir",
        help="Directory containing rolling premarket brief packets.",
    ),
    hourly_log_dir: Path = typer.Option(
        Path("results/hourly_supervisor"),
        "--hourly-log-dir",
        help="Directory containing hourly supervisor packets.",
    ),
    paper_tournament_log_dir: Path = typer.Option(
        Path("results/paper_strategy_tournament"),
        "--paper-tournament-log-dir",
        help="Directory containing paper tournament packets.",
    ),
    automation_dir: Path = typer.Option(
        Path("C:/cm/automations"),
        "--automation-dir",
        help="Codex automation directory to audit for schedule/command wiring.",
    ),
    context_dir: Path = typer.Option(
        Path("results/_context"),
        "--context-dir",
        help="Compact context directory containing source-routing provider-bundle overlays.",
    ),
):
    """Audit the read-only overnight planning chain and write a proof packet."""
    checks: list[dict] = []
    verification_now = _alpaca_policy_now()
    commands_exercised = [
        "tradingagents alpaca check",
        "tradingagents alpaca plan-overnight",
        "tradingagents alpaca premarket-brief",
        "tradingagents alpaca supervise-hourly --dry-run",
        "tradingagents alpaca paper-tournament run --all",
        "tradingagents alpaca supervisor-daily-report",
    ]

    overnight_path = _latest_json_packet_path(overnight_log_dir, "overnight-plan-*.json")
    overnight_packet = _read_json_packet(overnight_path)
    if not overnight_packet:
        _verification_check(
            checks,
            "latest_overnight_packet",
            "fail",
            "No readable overnight plan packet was found.",
            path=str(overnight_path) if overnight_path else None,
        )
    else:
        ranked = overnight_packet.get("ranked_candidates") or []
        ticker_results = overnight_packet.get("ticker_results") or []
        quality = overnight_packet.get("overnight_quality") or {}
        submitted = overnight_packet.get("submitted") or []
        has_core_fields = (
            overnight_packet.get("analysis_only") is True
            and len(submitted) == 0
            and bool(ranked)
            and bool(ticker_results)
            and bool(quality.get("graph_config"))
            and bool(overnight_packet.get("packet_path"))
        )
        graph_failures = int(quality.get("graph_failure_count") or 0)
        completion_status = str(quality.get("completion_status") or "").strip().lower()
        completion_blocking = completion_status in {"incomplete"}
        packet_status = "pass" if has_core_fields and graph_failures == 0 and not completion_blocking else (
            "warn" if has_core_fields else "fail"
        )
        _verification_check(
            checks,
            "latest_overnight_packet",
            packet_status,
            (
                "Latest overnight packet is analysis-only, ranked, has graph config, and submitted no orders."
                if has_core_fields and graph_failures == 0 and not completion_blocking
                else "Latest overnight packet exists but has graph failures or missing proof fields."
            ),
            path=str(overnight_path),
            top_symbol=ranked[0].get("symbol") if ranked and isinstance(ranked[0], dict) else None,
            ranked_count=len(ranked),
            ticker_count=len(ticker_results),
            graph_failure_count=graph_failures,
            completion_status=completion_status or None,
            completion_reasons=quality.get("completion_reasons") or [],
            graph_config=quality.get("graph_config"),
        )
        _audit_overnight_packet_freshness(
            checks,
            overnight_packet=overnight_packet,
            now=verification_now,
            max_age_hours=max_overnight_age_hours,
            calendar_skip_reason=_skip_simulated_preopen_validation_for_calendar(verification_now),
        )
        _audit_overnight_packet_trade_date(
            checks,
            overnight_packet=overnight_packet,
            now=verification_now,
        )
        expected_contract = _parse_overnight_automation_contract(automation_dir)
        actual_contract = _overnight_packet_contract_actual(overnight_packet)
        contract_known = any(value is not None for value in expected_contract.values())
        contract_matches = (
            _matches_overnight_automation_contract(actual_contract, expected_contract)
            if contract_known
            else False
        )
        _verification_check(
            checks,
            "overnight_matches_automation_contract",
            "pass" if contract_matches else "fail",
            (
                "Latest overnight packet matches the active automation's full-graph timeout and model-token contract."
                if contract_matches
                else "Latest overnight packet does not match the active overnight automation profile; it may be a manual probe."
            ),
            expected=expected_contract,
            actual=actual_contract,
        )
        expected_full_graph_limit = expected_contract.get("full_graph_limit")
        actual_full_graph_count = int(actual_contract.get("full_graph_count") or 0)
        actual_graph_failures = int(actual_contract.get("graph_failure_count") or 0)
        actual_full_graph_success_count = actual_contract.get("full_graph_success_count")
        if actual_full_graph_success_count is None:
            actual_full_graph_success_count = max(actual_full_graph_count - actual_graph_failures, 0)
        actual_full_graph_success_count = int(actual_full_graph_success_count or 0)
        if expected_full_graph_limit is not None:
            graph_disabled_reason = str(actual_contract.get("graph_disabled_reason") or "").strip()
            completion_status = str(actual_contract.get("completion_status") or "").strip().lower()
            if int(expected_full_graph_limit or 0) <= 0:
                graph_execution_status = "pass"
                graph_execution_summary = "The active overnight automation does not request original graph runs."
            elif actual_full_graph_success_count > 0:
                graph_execution_status = "pass"
                graph_execution_summary = "Latest overnight packet completed at least one original TradingAgents graph run."
            elif completion_status == "incomplete":
                graph_execution_status = "fail"
                graph_execution_summary = (
                    "The active overnight automation requested original TradingAgents graph runs, "
                    "but none were attempted; this is an incomplete production overnight packet."
                )
            elif actual_full_graph_count > 0:
                graph_execution_status = "warn"
                graph_execution_summary = (
                    "The active overnight automation attempted original TradingAgents graph runs, "
                    "but none completed successfully."
                )
            else:
                graph_execution_status = "warn"
                graph_execution_summary = (
                    "The active overnight automation requested original TradingAgents graph runs, "
                    "but the latest packet is fallback-only."
                )
            _verification_check(
                checks,
                "overnight_original_graph_execution",
                graph_execution_status,
                graph_execution_summary,
                expected_full_graph_limit=expected_full_graph_limit,
                requested_full_graph_limit=actual_contract.get("requested_full_graph_limit"),
                actual_full_graph_limit=actual_contract.get("full_graph_limit"),
                full_graph_count=actual_full_graph_count,
                full_graph_attempt_count=actual_contract.get("full_graph_attempt_count") or actual_full_graph_count,
                full_graph_success_count=actual_full_graph_success_count,
                graph_failure_count=actual_graph_failures,
                fallback_count=actual_contract.get("fallback_count"),
                graph_disabled_reason=graph_disabled_reason or None,
                completion_status=completion_status or None,
                completion_reasons=actual_contract.get("completion_reasons") or [],
        )
        _audit_overnight_prior_feed(checks, overnight_packet)
        _audit_overnight_source_quality(checks, overnight_packet)
        _audit_overnight_top_provider_bundles(
            checks,
            overnight_packet,
            source_routing_compact_path=context_dir / "source-routing-compact.json",
        )

    premarket_path = _latest_json_packet_path(premarket_brief_log_dir, "premarket-brief-*.json")
    premarket_packet = _read_json_packet(premarket_path)
    if not premarket_packet:
        _verification_check(
            checks,
            "latest_premarket_brief",
            "fail",
            "No readable premarket brief packet was found.",
            path=str(premarket_path) if premarket_path else None,
        )
    else:
        source_packets = premarket_packet.get("source_packets") or []
        source_paths = {str(item.get("path")) for item in source_packets if isinstance(item, dict)}
        overnight_source_match = False
        if overnight_packet:
            overnight_packet_path = str(overnight_packet.get("packet_path") or overnight_path or "")
            overnight_source_match = (
                overnight_packet_path in source_paths
                or str(overnight_path) in source_paths
                or any(Path(path).name == Path(overnight_packet_path).name for path in source_paths if path)
            )
        stale_warnings = premarket_packet.get("stale_warnings") or []
        blockers = premarket_packet.get("unresolved_blockers") or []
        instructions = premarket_packet.get("premarket_instructions") or {}
        premarket_ok = (
            premarket_packet.get("analysis_only") is True
            and overnight_source_match
            and bool(instructions.get("top_symbol"))
            and not stale_warnings
            and not blockers
        )
        _verification_check(
            checks,
            "latest_premarket_brief",
            "pass" if premarket_ok else "fail",
            (
                "Premarket brief includes the latest overnight plan, has no blockers/stale warnings, and remains analysis-only."
                if premarket_ok
                else "Premarket brief is missing latest overnight linkage, top symbol, or clean status."
            ),
            path=str(premarket_path),
            source_packet_count=len(source_packets),
            top_symbol=instructions.get("top_symbol"),
            stale_warnings=stale_warnings,
            unresolved_blockers=blockers,
        )
    _audit_premarket_fresh_validation_checklist(
        checks,
        premarket_packet=premarket_packet,
        premarket_path=premarket_path,
        premarket_brief_log_dir=premarket_brief_log_dir,
    )

    hourly_path = _latest_json_packet_path(hourly_log_dir, "hourly-supervisor-*.json")
    hourly_packet = _read_json_packet(hourly_path)
    if not hourly_packet:
        _verification_check(
            checks,
            "latest_hourly_supervisor_packet",
            "warn",
            "No readable hourly supervisor packet was found; dry-run handoff evidence was not proven.",
            path=str(hourly_path) if hourly_path else None,
        )
    else:
        evidence = hourly_packet.get("evidence") or {}
        submitted = hourly_packet.get("submitted") or []
        issues = hourly_packet.get("issues") or []
        portfolio = hourly_packet.get("portfolio") or {}
        live = portfolio.get("live") or {}
        expected_safety_lock = is_expected_hourly_safety_lock(
            {
                "kind": "hourly_supervisor",
                "decision": hourly_packet.get("decision"),
                "reason": hourly_packet.get("reason"),
                "submitted_count": len(submitted),
                "open_order_count": len(live.get("open_orders") or []),
                "issue_reasons": [
                    str(issue.get("reason"))
                    for issue in issues
                    if isinstance(issue, dict) and issue.get("reason")
                ],
            }
        )
        hourly_ok = (
            "overnight_plan" in evidence
            and len(submitted) == 0
            and (not issues or expected_safety_lock)
        )
        _verification_check(
            checks,
            "latest_hourly_supervisor_packet",
            "pass" if hourly_ok else "fail",
            (
                "Hourly supervisor consumed overnight evidence and submitted no orders; any issue is an expected live-control safety lock."
                if hourly_ok
                else "Hourly supervisor packet is missing overnight evidence or has issues/submissions."
            ),
            path=str(hourly_path),
            decision=hourly_packet.get("decision"),
            overnight_status=(evidence.get("overnight_plan") or {}).get("status"),
            submitted_count=len(submitted),
            issue_count=len(issues),
            expected_safety_lock=expected_safety_lock,
        )

    tournament_path = _latest_json_packet_path(paper_tournament_log_dir, "paper-tournament-*.json")
    tournament_packet = _read_json_packet(tournament_path)
    if not tournament_packet:
        _verification_check(
            checks,
            "latest_paper_tournament_packet",
            "warn",
            "No readable paper tournament packet was found.",
            path=str(tournament_path) if tournament_path else None,
        )
    else:
        report = tournament_packet.get("report") or tournament_packet.get("latest_report") or {}
        rankings = report.get("rankings") or []
        submitted_count = tournament_packet.get("submitted_count", len(tournament_packet.get("submitted") or []))
        _verification_check(
            checks,
            "latest_paper_tournament_packet",
            "pass" if len(rankings) >= 3 and submitted_count == 0 else "warn",
            "Paper tournament packet has strategy rankings and did not submit routine quiet orders.",
            path=str(tournament_path),
            ranking_count=len(rankings),
            submitted_count=submitted_count,
            live_strategy_candidate=report.get("live_strategy_candidate"),
        )

    if overnight_packet:
        validation_now = verification_now
        validation_skip_reason = _skip_simulated_preopen_validation_for_calendar(validation_now)
        if validation_skip_reason:
            _verification_check(
                checks,
                "simulated_preopen_validation",
                "pass",
                "Skipped simulated pre-open candidate validation because this calendar slot has no useful regular-market morning.",
                validation_skipped=True,
                skip_reason=validation_skip_reason,
            )
        else:
            market_data, market_data_errors = (
                _fetch_aggressive_candidate_market_data_result()
            )
            if market_data_errors:
                _verification_check(
                    checks,
                    "simulated_preopen_validation",
                    "fail",
                    "Fresh aggressive-candidate market data could not be loaded.",
                    errors=market_data_errors,
                )
            else:
                candidate_signals = build_candidate_signals(market_data)
                overnight_validation = validate_overnight_plan_against_candidates(
                    overnight_packet,
                    candidate_signals,
                    now=validation_now,
                )
                premarket_validation = validate_premarket_brief_against_candidates(
                    premarket_packet,
                    candidate_signals,
                    now=validation_now,
                )
                _verification_check(
                    checks,
                    "simulated_preopen_validation",
                    "pass" if overnight_validation.get("status") in {"confirmed", "amended"} and premarket_validation.get("status") in {"confirmed", "amended"} else "warn",
                    "Loaded latest overnight and premarket packets against fresh candidate rankings without waiting for the pre-open automation window.",
                    overnight_status=overnight_validation.get("status"),
                    premarket_status=premarket_validation.get("status"),
                    overnight_top=overnight_validation.get("overnight_top_symbol"),
                    current_top=overnight_validation.get("current_top_symbol"),
                    premarket_top=premarket_validation.get("brief_top_symbol"),
                )

    _verify_automation_text(
        checks,
        automation_dir=automation_dir,
        automation_id="tradingagents-overnight-planning",
        required_fragments=[
            ".venv\\Scripts\\tradingagents.exe",
            "alpaca check",
            "alpaca plan-overnight",
            "--overnight-graph-profile compact",
            "--per-ticker-timeout-minutes 25",
            "--overnight-max-completion-tokens 220",
            "alpaca premarket-brief",
            "must never place live or paper orders",
        ],
        summary="Overnight automation is PATH-proof, read-only, uses the longer local-model graph window, and refreshes the premarket brief.",
    )
    _verify_overnight_planning_status(
        checks,
        automation_dir=automation_dir,
        overnight_packet=overnight_packet,
        now=verification_now,
    )
    _verify_automation_text(
        checks,
        automation_dir=automation_dir,
        automation_id="hourly-market-supervisor",
        required_fragments=[
            ".venv\\Scripts\\tradingagents.exe",
            "alpaca check",
            "alpaca supervise-hourly --dry-run",
            "--overnight-log-dir results/overnight_plans",
            "--paper-tournament-log-dir results/paper_strategy_tournament",
            "--premarket-brief-log-dir results/premarket_briefs",
        ],
        summary="Hourly supervisor automation consumes overnight, tournament, and premarket brief context before submit-capable runs.",
    )
    _verify_automation_text(
        checks,
        automation_dir=automation_dir,
        automation_id="paper-strategy-tournament-runner",
        required_fragments=[
            "paper-tournament run --all",
            "This automation is paper-only",
            "must never place live orders",
        ],
        summary="Paper tournament automation is isolated to paper and feeds strategy context for live supervisor selection.",
    )
    _verify_automation_text(
        checks,
        automation_dir=automation_dir,
        automation_id="tradingagents-daily-market-report",
        required_fragments=[
            "supervisor-daily-report",
            "--paper-tournament-log-dir results/paper_strategy_tournament",
            "--premarket-brief-log-dir results/premarket_briefs",
            "must never place trades",
        ],
        summary="Daily report automation is read-only and summarizes tournament plus premarket context.",
    )

    failed = [check for check in checks if check["status"] == "fail"]
    warned = [check for check in checks if check["status"] == "warn"]
    overall_status = "fail" if failed else ("pass_with_warnings" if warned else "pass")
    generated_at = datetime.datetime.now(tz=datetime.timezone.utc).astimezone(CENTRAL)
    log_dir.mkdir(parents=True, exist_ok=True)
    packet_path = log_dir / f"overnight-system-verification-{generated_at:%Y%m%d-%H%M%S}.json"
    packet = {
        "generated_at": generated_at.isoformat(timespec="seconds"),
        "analysis_only": True,
        "can_submit_orders": False,
        "execution_authority": "none",
        "overall_status": overall_status,
        "checks": checks,
        "commands_exercised": commands_exercised,
        "packet_path": str(packet_path),
    }
    packet_text = json.dumps(packet, indent=2)
    packet_path.write_text(packet_text, encoding="utf-8")
    (log_dir / "latest.json").write_text(packet_text, encoding="utf-8")
    compact = _compact_overnight_verification_payload(packet, packet_path)
    compact_text = json.dumps(compact, indent=2)
    compact_path = packet_path.with_suffix(".compact.json")
    compact_path.write_text(compact_text, encoding="utf-8")
    (log_dir / "latest-compact.json").write_text(compact_text, encoding="utf-8")
    markdown = _render_overnight_verification_markdown(packet)
    markdown_path = log_dir / f"overnight-system-verification-{generated_at:%Y%m%d-%H%M%S}.md"
    markdown_path.write_text(markdown, encoding="utf-8")
    (log_dir / "latest.md").write_text(markdown, encoding="utf-8")

    if json_output:
        typer.echo(json.dumps(packet, indent=2))
        return
    status_style = "green" if overall_status == "pass" else ("yellow" if overall_status == "pass_with_warnings" else "red")
    console.print(f"[{status_style}]Overnight system verification: {overall_status}[/{status_style}]")
    console.print(f"Packet: {packet_path}")


@alpaca_app.command("supervise-hourly")
def alpaca_supervise_hourly(
    dry_run: bool = typer.Option(True, "--dry-run/--submit-actions"),
    json_output: bool = typer.Option(False, "--json-output"),
    compact_json_output: bool = typer.Option(
        False,
        "--compact-json-output",
        help="When used with --json-output, print compact context instead of the full packet.",
    ),
    log_dir: Path = typer.Option(
        Path("results/hourly_supervisor"),
        "--log-dir",
        help="Directory for hourly supervisor JSON packets.",
    ),
    notification_policy: str = typer.Option(
        "material-only",
        "--notification-policy",
        help="material-only, every-check, daily-digest, or urgent-exceptions.",
    ),
    write_outbox: bool = typer.Option(
        True,
        "--write-outbox/--no-write-outbox",
        help=(
            "Allow local notification outbox writes for non-dry-run ticks. "
            "Dry-run ticks always suppress the outbox."
        ),
    ),
    overnight_log_dir: Path = typer.Option(
        Path("results/overnight_plans"),
        "--overnight-log-dir",
        help="Directory containing overnight planning packets.",
    ),
    paper_tournament_log_dir: Path = typer.Option(
        Path("results/paper_strategy_tournament"),
        "--paper-tournament-log-dir",
        help="Directory containing paper tournament live-strategy selection.",
    ),
    premarket_brief_log_dir: Path = typer.Option(
        Path("results/premarket_briefs"),
        "--premarket-brief-log-dir",
        help="Directory containing rolling premarket brief packets.",
    ),
    preopen_validation_dir: Path = typer.Option(
        Path("results/preopen_validation"),
        "--preopen-validation-dir",
        help="Directory containing latest analysis-only pre-open validation packets.",
    ),
    execution_board_dir: Path = typer.Option(
        Path("results/execution_board"),
        "--execution-board-dir",
        help="Directory containing latest BOARD execution review packets.",
    ),
):
    """Run one hourly Alpaca portfolio supervision tick."""
    config = _alpaca_execution_config()
    posture_policy = risk_posture_policy_from_config(
        DEFAULT_CONFIG,
        environment="paper",
    )
    paper_client, live_client = _alpaca_clients()
    live_account = live_client.get_account()
    paper_account = paper_client.get_account()
    live_positions = live_client.list_positions()
    paper_positions = paper_client.list_positions()
    live_open_orders = live_client.list_orders(status="open")
    paper_open_orders = paper_client.list_orders(status="open")
    previous_packet = find_latest_hourly_packet(log_dir)
    recent_packets = _latest_supervisor_packets(log_dir)
    market_session = market_session_label()
    (
        dynamic_live_cap,
        live_budget_mode,
        live_budget_envelope_issues,
        live_budget_envelope,
    ) = _dynamic_live_cap_for_budget_mode(
        live_account=live_account,
        live_positions=live_positions,
        recent_packets=recent_packets,
        config=config,
    )
    market_data, market_data_errors = (
        _fetch_aggressive_candidate_market_data_result()
    )
    held_symbols = [str(position.get("symbol", "")) for position in live_positions]
    candidate_signals = build_candidate_signals(
        market_data,
        held_symbols=held_symbols,
    )
    live_strategy_selection = load_live_strategy_selection(paper_tournament_log_dir)
    promotion_state_for_sleeve = _read_json_packet(
        Path(
            os.environ.get(
                "TRADINGAGENTS_PROMOTION_STATE_PATH",
                "results/policy/promotion_state.json",
            )
        )
    )
    resolved_live_sleeve, live_sleeve_resolution = resolve_live_sleeve(
        live_strategy_selection, promotion_state_for_sleeve
    )
    live_signals_adapted = False
    if (
        live_strategy_selection
        and resolved_live_sleeve == live_strategy_selection.get("strategy_id")
    ):
        # The tournament selection is backed by a live-enabled promotion
        # record, so reshape candidate signals to the winning sleeve's
        # profile before the hourly decision.
        candidate_signals = adapt_candidate_signals_for_live_strategy(
            resolved_live_sleeve,
            candidate_signals,
        )
        live_signals_adapted = True
    overnight_plan = load_latest_overnight_plan(overnight_log_dir)
    overnight_validation = validate_overnight_plan_against_candidates(
        overnight_plan,
        candidate_signals,
        now=_alpaca_policy_now(),
    )
    premarket_brief_validation = None
    if market_session == "pre_open":
        premarket_brief = load_latest_premarket_brief(premarket_brief_log_dir)
        premarket_brief_validation = validate_premarket_brief_against_candidates(
            premarket_brief,
            candidate_signals,
            now=_alpaca_policy_now(),
        )
    preopen_validation_summary = None
    preopen_validation_issues: list[OrderIssue] = []
    if market_session == "pre_open":
        preopen_validation_packet = _latest_preopen_validation_packet(
            preopen_validation_dir
        )
        (
            preopen_validation_summary,
            preopen_validation_issues,
        ) = _preopen_validation_submit_check(
            preopen_validation_packet,
            log_dir=preopen_validation_dir,
            now=_alpaca_policy_now(),
        )
    execution_board_review = _read_json_packet(execution_board_dir / "latest.json")
    new_buys_suspended_reason = None
    board_recommendation = (
        execution_board_review.get("recommendation")
        if isinstance(execution_board_review, Mapping)
        else None
    )
    if board_recommendation in {
        "pause_new_buys_and_review",
        "review_underperformers_before_new_buys",
    }:
        metrics = execution_board_review.get("metrics") or {}
        new_buys_suspended_reason = (
            f"BOARD recommended {board_recommendation}: "
            f"{len(execution_board_review.get('violations') or [])} hard issue(s), "
            f"{len(execution_board_review.get('warnings') or [])} warning(s), "
            f"and reviewed {metrics.get('packet_count', 'unknown')} hourly packet(s)."
        )

    decision = build_hourly_decision(
        live_positions=live_positions,
        live_open_orders=live_open_orders,
        config=HourlySupervisorConfig(
            notification_policy=notification_policy,
            paper_first_threshold=posture_policy.paper_first_threshold,
        ),
        candidate_signals=candidate_signals,
        market_session=market_session,
        dynamic_live_cap=dynamic_live_cap,
        new_buys_suspended_reason=new_buys_suspended_reason,
        live_sleeve=resolved_live_sleeve,
    )
    issues = validate_hourly_supervisor_actions(
        decision.actions,
        current_live_exposure=decision.live_exposure,
        config=replace(config, live_exposure_limit=dynamic_live_cap),
        open_orders=live_open_orders + paper_open_orders,
    )
    if issues:
        decision = replace(
            decision,
            decision="blocked",
            material=True,
            reason="hourly supervisor action failed guardrail validation",
            issues=issues,
        )

    submitted = []
    latest_packet_reconciliation = None
    if decision.actions and not dry_run and not decision.issues:
        if market_session == "pre_open" and preopen_validation_issues:
            decision = replace(
                decision,
                decision="blocked",
                material=True,
                reason="hourly supervisor pre-open validation blocked submit",
                issues=[*decision.issues, *preopen_validation_issues],
            )
        if not decision.issues:
            current_daily_loss_usd, current_drawdown_pct = _account_circuit_breaker_values(
                live_account
            )
            live_submit_issues = validate_supervisor_live_submit_allowed(
                actions=decision.actions,
                current_live_exposure=decision.live_exposure,
                current_daily_loss_usd=current_daily_loss_usd,
                current_drawdown_pct=current_drawdown_pct,
                live_account=live_account,
                live_positions=live_positions,
                decision_evidence=decision.evidence,
                now=decision.generated_at,
            )
            if live_submit_issues:
                decision = replace(
                    decision,
                    decision="blocked",
                    material=True,
                    reason="hourly supervisor live submit failed guard validation",
                    issues=[*decision.issues, *live_submit_issues],
                )
        if not decision.issues:
            live_actions = [
                action
                for action in decision.actions
                if is_order_action(action) and action.account.lower() == "live"
            ]
            if live_actions and previous_packet:
                try:
                    previous_packet_payload = json.loads(
                        previous_packet.read_text(encoding="utf-8")
                    )
                except (OSError, json.JSONDecodeError) as exc:
                    latest_packet_reconciliation = {
                        "source": str(previous_packet),
                        "matched": False,
                        "checked_client_order_ids": [],
                        "issues": [f"latest hourly packet could not be parsed: {exc}"],
                    }
                    decision = replace(
                        decision,
                        decision="blocked",
                        material=True,
                        reason="hourly supervisor latest-packet reconciliation blocked submit",
                        issues=[
                            *decision.issues,
                            OrderIssue(
                                "latest-packet-reconciliation",
                                latest_packet_reconciliation["issues"][0],
                            ),
                        ],
                    )
                else:
                    latest_reconciliation = reconcile_latest_packet_live_orders(
                        previous_packet_payload,
                        order_lookup=lambda client_order_id: find_order_by_client_order_id(
                            live_client,
                            client_order_id,
                        ),
                    )
                    latest_packet_reconciliation = {
                        "source": str(previous_packet),
                        "matched": latest_reconciliation.matched,
                        "checked_client_order_ids": (
                            latest_reconciliation.checked_client_order_ids
                        ),
                        "issues": latest_reconciliation.issues,
                    }
                    if not latest_reconciliation.matched:
                        decision = replace(
                            decision,
                            decision="blocked",
                            material=True,
                            reason=(
                                "hourly supervisor latest-packet reconciliation "
                                "blocked submit"
                            ),
                            issues=[
                                *decision.issues,
                                *[
                                    OrderIssue(
                                        "latest-packet-reconciliation",
                                        (
                                            "latest hourly packet reconciliation "
                                            f"blocked submit: {issue}"
                                        ),
                                    )
                                    for issue in latest_reconciliation.issues
                                ],
                            ],
                        )
            if decision.issues:
                live_actions = []
            if live_actions:
                decision = replace(
                    decision,
                    decision="blocked",
                    material=True,
                    reason=(
                        "hourly supervisor live submission requires an independently "
                        "issued authorized normal live intent and activation receipt"
                    ),
                    issues=[
                        *decision.issues,
                        OrderIssue(
                            "normal-live-intent",
                            (
                                "live actions are no-submit until the exact authorized "
                                "normal live intent and activation receipt are supplied "
                                "outside this CLI path"
                            ),
                        ),
                    ],
                )
                live_actions = []
            tiny_live_guard = acquire_tiny_live_operational_guard(
                live_actions=live_actions,
                live_client=live_client,
                expected_live_positions=live_positions,
                expected_live_open_orders=live_open_orders,
                owner=f"hourly-supervisor-{decision.generated_at:%Y%m%d-%H%M%S}",
                control_state_path="results/policy/live_control.json",
            )
            if not tiny_live_guard.allowed:
                decision = replace(
                    decision,
                    decision="blocked",
                    material=True,
                    reason="hourly supervisor tiny-live operational guard blocked submit",
                    issues=[*decision.issues, *tiny_live_guard.issues],
                )
            lock_path = (
                tiny_live_guard.lock.path
                if tiny_live_guard.lock and tiny_live_guard.lock.acquired
                else None
            )
            submit_issues = []
            reconciled_orders = []
            try:
                if not decision.issues:
                    for index, action in enumerate(decision.actions, start=1):
                        if not is_order_action(action):
                            continue
                        if (
                            action.account.lower() == "live"
                            and action.execution_mode.lower() == "tiny_live"
                        ):
                            client_order_id = supervisor_live_client_order_id(
                                action,
                                generated_at=decision.generated_at,
                            )
                        else:
                            client_order_id = (
                                f"ta-hourly-{decision.generated_at:%Y%m%d-%H%M%S}-"
                                f"{index}-{action.symbol.lower()}-{action.action}"
                            )[:48]
                        payload = build_supervisor_order_payload(
                            action,
                            client_order_id=client_order_id,
                        )
                        try:
                            if action.account.lower() == "paper":
                                submitted.append(paper_client.submit_order(payload))
                            else:
                                raise RuntimeError(
                                    "hourly CLI live submission is hard-disabled without "
                                    "an independently issued normal live intent"
                                )
                        except Exception as exc:  # noqa: BLE001 - preserve packet evidence for broker failures.
                            classification = classify_alpaca_submit_error(
                                exc,
                                account=action.account,
                                client_order_id=client_order_id,
                            )
                            issue_reason = classification.message
                            if classification.idempotency_conflict:
                                lookup_client = (
                                    paper_client
                                    if action.account.lower() == "paper"
                                    else live_client
                                )
                                try:
                                    existing_order = find_order_by_client_order_id(
                                        lookup_client,
                                        client_order_id,
                                    )
                                except Exception as lookup_exc:  # noqa: BLE001 - keep packet evidence.
                                    issue_reason = (
                                        f"{issue_reason} Existing order lookup failed: "
                                        f"{lookup_exc}"
                                    )
                                else:
                                    if existing_order:
                                        comparison_issues = compare_alpaca_order_to_intent(
                                            existing_order,
                                            payload,
                                        )
                                        reconciled_orders.append(
                                            {
                                                "account": action.account.lower(),
                                                "client_order_id": client_order_id,
                                                "lookup": "found",
                                                "intent_match": not comparison_issues,
                                                "comparison_issues": comparison_issues,
                                                "order": existing_order,
                                            }
                                        )
                                        if comparison_issues:
                                            issue_reason = (
                                                f"{issue_reason} Existing broker order found "
                                                f"with status={existing_order.get('status', 'unknown')} "
                                                f"id={existing_order.get('id', 'unknown')}, "
                                                "but it does not match the intended action: "
                                                f"{'; '.join(comparison_issues)}."
                                            )
                                        else:
                                            issue_reason = (
                                                f"{issue_reason} Existing broker order found "
                                                f"with status={existing_order.get('status', 'unknown')} "
                                                f"id={existing_order.get('id', 'unknown')} and it "
                                                "matches the intended action. The run stays blocked "
                                                "until reconciliation is reviewed."
                                            )
                                    else:
                                        issue_reason = (
                                            f"{issue_reason} Existing order lookup did not "
                                            "find a broker order yet."
                                        )
                            submit_issues.append(
                                OrderIssue(
                                    action.symbol,
                                    issue_reason,
                                )
                            )
                            break
            finally:
                if lock_path is not None:
                    release_execution_lock(lock_path)
            if submit_issues:
                decision = replace(
                    decision,
                    decision="blocked",
                    material=True,
                    reason="hourly supervisor submit failed; see issues for broker response",
                    issues=[*decision.issues, *submit_issues],
                    submitted=submitted,
                    reconciled_orders=reconciled_orders,
                )
            elif not decision.issues:
                decision = replace(
                    decision,
                    material=True,
                    submitted=submitted,
                )

    evidence = {
        **decision.evidence,
        **build_hourly_evidence(
            live_account=live_account,
            paper_account=paper_account,
            live_positions=live_positions,
            live_open_orders=live_open_orders,
            previous_packet=previous_packet,
            overnight_validation=overnight_validation,
            premarket_brief_validation=premarket_brief_validation,
        ),
    }
    if live_strategy_selection:
        selection_is_binding = live_signals_adapted
        evidence["live_strategy_selection"] = {
            **live_strategy_selection,
            "advisory_only": not selection_is_binding,
            "reason": (
                f"{live_strategy_selection.get('reason', '')} "
                + (
                    "Selection is binding: backed by a live-enabled promotion record."
                    if selection_is_binding
                    else "Selection is advisory until a live-enabled promotion record exists."
                )
            ).strip(),
        }
    evidence["live_sleeve_resolution"] = {
        "live_sleeve": resolved_live_sleeve,
        "reason": live_sleeve_resolution,
        "signals_adapted": live_signals_adapted,
    }
    if latest_packet_reconciliation is not None:
        evidence["latest_packet_reconciliation"] = latest_packet_reconciliation
    if preopen_validation_summary is not None:
        evidence["preopen_validation"] = preopen_validation_summary
    if execution_board_review:
        execution_board_evidence = {
            "recommendation": execution_board_review.get("recommendation"),
            "generated_at": execution_board_review.get("generated_at"),
            "analysis_only": execution_board_review.get("analysis_only"),
            "can_submit_orders": execution_board_review.get("can_submit_orders"),
            "new_buys_suspended": bool(new_buys_suspended_reason),
            "summary": new_buys_suspended_reason,
            "json_path": str(execution_board_dir / "latest.json"),
        }
        loss_review_evidence = execution_board_review.get("loss_review_evidence")
        if isinstance(loss_review_evidence, Mapping):
            execution_board_evidence["loss_review_evidence"] = dict(loss_review_evidence)
        evidence["execution_board_review"] = execution_board_evidence
    evidence["risk_posture"] = posture_policy.as_dict()
    repo_dollar_cap_active = live_budget_mode == "autonomous_with_caps"
    evidence["live_budget"] = {
        "mode": live_budget_mode,
        "repo_dollar_cap_active": repo_dollar_cap_active,
        "dynamic_live_cap_usd": str(dynamic_live_cap) if repo_dollar_cap_active else None,
        "base_cap_usd": str(config.live_exposure_limit) if repo_dollar_cap_active else None,
        "hard_account_cap_usd": (
            str(live_budget_envelope.account_max_capital_at_risk_usd)
            if repo_dollar_cap_active and live_budget_envelope is not None
            else None
        ),
        "per_name_cap_usd": (
            str(live_budget_envelope.per_name_cap_usd)
            if repo_dollar_cap_active and live_budget_envelope is not None
            else None
        ),
        "risk_envelope_issues": live_budget_envelope_issues,
        "plain_english": (
            "The bot may choose live order size inside the risk envelope caps."
            if live_budget_mode == "autonomous_with_caps"
            else (
                "Live budget is blocked because the configured mode is invalid or retired."
                if live_budget_mode == "invalid_or_retired"
                else "Live budget is not autonomous until config/risk_envelope.yaml opts in."
            )
        ),
    }

    decision = replace(
        decision,
        evidence=evidence,
        portfolio=build_portfolio_snapshot(
            live_account=live_account,
            paper_account=paper_account,
            live_positions=live_positions,
            live_open_orders=live_open_orders,
            paper_positions=paper_positions,
            paper_open_orders=paper_open_orders,
            dynamic_live_cap=dynamic_live_cap,
            market_session=market_session,
            candidates=candidate_signals,
        ),
    )

    outbox_write_allowed = bool(write_outbox and not dry_run)
    packet_metadata = {
        "outbox_suppressed": not outbox_write_allowed,
        "outbox_write_allowed": outbox_write_allowed,
        "errors": market_data_errors,
    }
    if dry_run:
        packet_metadata.update(
            {
                "shadow_dry_run": True,
                "analysis_only": True,
                "execution_authority": "none",
                "can_submit_orders": False,
            }
        )
    packet_path = write_hourly_decision_packet(
        decision,
        output_dir=log_dir,
        recent_packets=recent_packets,
        packet_metadata=packet_metadata,
    )
    payload = serialize_hourly_decision(decision, recent_packets=recent_packets)
    payload.update(
        {
            "outbox_suppressed": not outbox_write_allowed,
            "outbox_write_allowed": outbox_write_allowed,
            "errors": market_data_errors,
        }
    )
    if dry_run:
        payload.update(
            {
                "shadow_dry_run": True,
                "analysis_only": True,
                "execution_authority": "none",
                "can_submit_orders": False,
            }
        )
    payload["packet_path"] = str(packet_path)
    policy_notify = should_notify_supervisor(
        decision,
        notification_policy=notification_policy,
    )
    payload["notification_policy_notify"] = policy_notify
    payload["notify"] = bool(payload.get("alert", {}).get("notify", policy_notify))
    if payload["notify"] and outbox_write_allowed:
        alert_email = payload.get("alert_email")
        if isinstance(alert_email, Mapping) and alert_email.get("body"):
            from tradingagents.notifications.outbox import write_outbox_message

            outbox_path = write_outbox_message(
                {**alert_email, "email_to": ""},
                report_type="urgent",
                severity=str(payload.get("alert", {}).get("severity") or "NOTABLE"),
            )
            payload["outbox_path"] = str(outbox_path)
    payload["account"] = {
        "live": {
            "status": live_account.get("status"),
            "buying_power": live_account.get("buying_power"),
            "equity": live_account.get("equity"),
        },
        "paper": {
            "status": paper_account.get("status"),
            "buying_power": paper_account.get("buying_power"),
            "equity": paper_account.get("equity"),
        },
    }
    if json_output:
        if compact_json_output:
            typer.echo(json.dumps(_compact_hourly_supervisor_payload(payload, packet_path), indent=2))
        else:
            typer.echo(json.dumps(payload, indent=2))
        return
    _print_hourly_supervisor(decision, packet_path)


@alpaca_app.command("supervisor-daily-report")
def alpaca_supervisor_daily_report(
    json_output: bool = typer.Option(False, "--json-output"),
    compact_json_output: bool = typer.Option(
        False,
        "--compact-json-output",
        help="When used with --json-output, print compact context and write the full report packet.",
    ),
    write_outbox: bool = typer.Option(
        True,
        "--write-outbox/--no-write-outbox",
        help="Write the rendered report to the local notification outbox.",
    ),
    log_dir: Path = typer.Option(
        Path("results/hourly_supervisor"),
        "--log-dir",
        help="Directory containing hourly supervisor JSON packets.",
    ),
    daily_report_log_dir: Path = typer.Option(
        Path("results/daily_reports"),
        "--daily-report-log-dir",
        help="Directory for full daily report packets written by compact JSON mode.",
    ),
    paper_tournament_log_dir: Path = typer.Option(
        Path("results/paper_strategy_tournament"),
        "--paper-tournament-log-dir",
        help="Directory containing paper tournament ledger and report.",
    ),
    premarket_brief_log_dir: Path = typer.Option(
        Path("results/premarket_briefs"),
        "--premarket-brief-log-dir",
        help="Directory containing rolling premarket brief packets.",
    ),
    model_telemetry_report_dir: Path = typer.Option(
        Path("results/model_telemetry_reports"),
        "--model-telemetry-report-dir",
        help="Directory containing model telemetry report latest.json.",
    ),
    execution_board_dir: Path = typer.Option(
        Path("results/execution_board"),
        "--execution-board-dir",
        help="Directory containing latest BOARD execution review packets.",
    ),
    alpaca_reference_dir: Path = typer.Option(
        Path("results/alpaca_reference"),
        "--alpaca-reference-dir",
        help="Directory containing the latest read-only Alpaca reference audit.",
    ),
    email_to: str = typer.Option(
        "nebulazer2003@gmail.com",
        "--email-to",
        help="Email recipient rendered in the report body.",
    ),
):
    """Render the daily TradingAgents supervisor report."""
    paper_client, live_client = _alpaca_clients()
    live_account = live_client.get_account()
    paper_account = paper_client.get_account()
    live_positions = live_client.list_positions()
    paper_positions = paper_client.list_positions()
    live_open_orders = live_client.list_orders(status="open")
    paper_open_orders = paper_client.list_orders(status="open")
    recent_packets = _latest_supervisor_packets(log_dir)
    config = _alpaca_execution_config()
    dynamic_live_cap, _, _, _ = _dynamic_live_cap_for_budget_mode(
        live_account=live_account,
        live_positions=live_positions,
        recent_packets=recent_packets,
        config=config,
    )
    market_data, market_data_errors = (
        _fetch_aggressive_candidate_market_data_result()
    )
    candidate_signals = build_candidate_signals(
        market_data,
        held_symbols=[str(position.get("symbol", "")) for position in live_positions],
    )
    portfolio = build_portfolio_snapshot(
        live_account=live_account,
        paper_account=paper_account,
        live_positions=live_positions,
        live_open_orders=live_open_orders,
        paper_positions=paper_positions,
        paper_open_orders=paper_open_orders,
        dynamic_live_cap=dynamic_live_cap,
        market_session=market_session_label(),
        candidates=candidate_signals,
    )
    packets = _load_supervisor_packets(log_dir)
    paper_tournament_report = None
    try:
        paper_tournament_report = load_tournament_ledger(paper_tournament_log_dir).get("latest_report")
    except (FileNotFoundError, json.JSONDecodeError):
        paper_tournament_report = None
    premarket_brief = load_latest_premarket_brief(premarket_brief_log_dir)
    if premarket_brief:
        premarket_brief_path = (
            premarket_brief_log_dir / "latest.json"
            if (premarket_brief_log_dir / "latest.json").exists()
            else None
        )
        premarket_brief_validation = validate_premarket_brief_against_candidates(
            premarket_brief,
            candidate_signals,
            now=_alpaca_policy_now(),
        )
    else:
        premarket_brief_path = None
        premarket_brief_validation = None
    model_telemetry_report_path = model_telemetry_report_dir / "latest.json"
    model_telemetry_report = _read_json_packet(model_telemetry_report_path)
    execution_board_review_path = execution_board_dir / "latest.json"
    execution_board_review = _read_json_packet(execution_board_review_path)
    alpaca_reference_summary = _read_json_packet(
        alpaca_reference_dir / "latest-summary.json"
    )
    payload = build_supervisor_daily_report_payload(
        portfolio=portfolio,
        packets=packets,
        email_to=email_to,
        paper_tournament_report=paper_tournament_report,
        premarket_brief=premarket_brief,
        premarket_brief_validation=premarket_brief_validation,
        premarket_brief_path=premarket_brief_path,
        model_telemetry_report=model_telemetry_report,
        execution_board_review=execution_board_review,
        alpaca_reference_summary=alpaca_reference_summary,
    )
    payload["errors"] = market_data_errors
    if write_outbox:
        from tradingagents.notifications.outbox import write_outbox_message

        payload["outbox_path"] = str(
            write_outbox_message(payload, report_type="daily", severity="ROUTINE")
        )
    if json_output:
        if compact_json_output:
            packet_path = _write_supervisor_daily_report_packet(payload, daily_report_log_dir)
            typer.echo(json.dumps(_compact_supervisor_daily_report_payload(payload, packet_path), indent=2))
        else:
            typer.echo(json.dumps(payload, indent=2))
        return
    typer.echo(str(payload.get("body") or ""))


@alpaca_app.command("reference-snapshot")
def alpaca_reference_snapshot(
    catalog_path: Path = typer.Option(
        Path("config/alpaca_api_reference_catalog.json"),
        "--catalog-path",
        help="Versioned Alpaca API reference catalog.",
    ),
    output_dir: Path = typer.Option(
        Path("results/alpaca_reference"),
        "--output-dir",
        help="Directory for local read-only reference audit packets.",
    ),
    json_output: bool = typer.Option(False, "--json-output"),
):
    """Write a complete local Alpaca reference audit without API mutations."""

    audit = build_alpaca_reference_audit(load_alpaca_reference_catalog(catalog_path))
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = str(audit["generated_at"]).replace(":", "").replace("+", "-")
    packet_path = output_dir / f"alpaca-reference-audit-{stamp}.json"
    audit["packet_path"] = str(packet_path)
    text = json.dumps(audit, indent=2)
    _atomic_write_text(packet_path, text)
    _atomic_write_text(output_dir / "latest.json", text)
    _atomic_write_text(output_dir / "latest-summary.json", text)
    if json_output:
        typer.echo(text)
        return
    typer.echo(str(packet_path))


@alpaca_app.command("compact-output-audit")
def alpaca_compact_output_audit(
    json_output: bool = typer.Option(False, "--json-output"),
    output_dir: Path = typer.Option(
        Path("results/token_efficiency"),
        "--output-dir",
        help="Directory for compact-output byte-reduction audit packets.",
    ),
    hourly_log_dir: Path = typer.Option(
        Path("results/hourly_supervisor"),
        "--hourly-log-dir",
        help="Directory containing hourly supervisor packets.",
    ),
    overnight_log_dir: Path = typer.Option(
        Path("results/overnight_plans"),
        "--overnight-log-dir",
        help="Directory containing overnight plan packets.",
    ),
    premarket_brief_log_dir: Path = typer.Option(
        Path("results/premarket_briefs"),
        "--premarket-brief-log-dir",
        help="Directory containing premarket brief packets.",
    ),
    daily_report_log_dir: Path = typer.Option(
        Path("results/daily_reports"),
        "--daily-report-log-dir",
        help="Directory containing supervisor daily report packets.",
    ),
    automation_health_dir: Path = typer.Option(
        Path("results/automation_health"),
        "--automation-health-dir",
        help="Directory containing automation health audit packets.",
    ),
):
    """Measure compact JSON stdout byte reduction against raw result packets."""
    packet = _build_compact_output_audit_packet(
        hourly_log_dir=hourly_log_dir,
        overnight_log_dir=overnight_log_dir,
        premarket_brief_log_dir=premarket_brief_log_dir,
        daily_report_log_dir=daily_report_log_dir,
        automation_health_dir=automation_health_dir,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.datetime.now(tz=datetime.timezone.utc).astimezone(CENTRAL)
    stem = f"compact-output-audit-{generated_at:%Y%m%d-%H%M%S-%f}"
    packet_path = _unique_packet_path(output_dir, stem)
    markdown_path = _unique_packet_path(output_dir, stem, ".md")
    packet["packet_path"] = str(packet_path)
    packet["markdown_path"] = str(markdown_path)
    packet_text = json.dumps(packet, indent=2)
    _atomic_write_text(packet_path, packet_text)
    _atomic_write_text(output_dir / "latest.json", packet_text)
    markdown = _render_compact_output_audit_markdown(packet)
    _atomic_write_text(markdown_path, markdown)
    _atomic_write_text(output_dir / "latest.md", markdown)
    if json_output:
        typer.echo(json.dumps(packet, indent=2))
        return
    typer.echo(markdown)


if __name__ == "__main__":
    app()
