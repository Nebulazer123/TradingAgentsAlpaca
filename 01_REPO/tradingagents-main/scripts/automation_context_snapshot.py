"""Build compact TradingAgents automation context for future Codex sessions.

The generated files are lossy indexes with pointers to full raw packets. They
are meant to reduce repeated token spend, not replace audit evidence.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import re
from contextlib import suppress
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import tomllib

from tradingagents.orchestration.incidents import IncidentStage, is_safe_incident_id
from tradingagents.storage.json_cache import JsonFileCache

ROOT = Path(__file__).resolve().parents[1]
AUTOMATION_ROOT = Path(r"C:\cm\automations")
CONTEXT_DIR = ROOT / "results" / "_context"
RESEARCH_EVIDENCE_DIR = ROOT / "results" / "research_evidence"
AUTOMATION_MEMORY_ROLLUP_LATEST = (
    ROOT / "results" / "token_efficiency" / "latest-automation-memory-rollup.json"
)
CENTRAL = ZoneInfo("America/Chicago")
PROVIDER_BUNDLE_SCAN_LIMIT = 50
JSON_FILE_CACHE = JsonFileCache.from_env(max_entries=2048)


AUTOMATION_IDS = [
    "hourly-market-supervisor",
    "paper-strategy-tournament-runner",
    "tradingagents-overnight-planning",
    "market-supervisor-15-min-before-open",
    "market-supervisor-30-min-after-open",
    "market-supervisor-30-min-before-close",
    "market-supervisor-15-min-after-close",
    "tradingagents-daily-market-report",
    "tradingagents-automation-sleep-controller",
    "tradingagents-automation-wake-controller",
    "tradingagents-night-shift-supervisor",
]

KNOWN_FOLLOW_UP_AUTOMATION_IDS = [
    "fetch-tradingagents-deep-research-report",
]

KNOWN_OBSERVER_AUTOMATION_IDS = [
    "tradingagents-self-heal-monitor",
    "tradingagents-wake-verification",
]

CONTROLLER_AUTOMATION_IDS = {
    "tradingagents-automation-sleep-controller",
    "tradingagents-automation-wake-controller",
    "tradingagents-night-shift-supervisor",
}


ADVISORY_LOCAL_MODEL_ROUTES = {
    "windows_local_ollama",
    "mac_ollama_research_mule",
}
LOCAL_MODEL_HELPER_ROUTES = ADVISORY_LOCAL_MODEL_ROUTES

COMPACT_SNAPSHOT_LABELS = {
    "automation_health_audit",
    "capability_audit",
    "execution_board_review",
    "hourly",
    "loss_review_evidence",
    "model_telemetry_report",
    "overnight",
    "overnight_calibration_guard",
    "overnight_verification",
    "paper_tournament",
    "preopen_validation",
    "research_batch",
    "n8n_evaluation_dataset",
    "source_quality_review",
    "mirofish_handoff_status",
    "premarket_brief",
}


LATEST_PACKETS = [
    ("hourly", ROOT / "results" / "hourly_supervisor"),
    ("paper_tournament", ROOT / "results" / "paper_strategy_tournament"),
    ("overnight", ROOT / "results" / "overnight_plans"),
    ("premarket_brief", ROOT / "results" / "premarket_briefs"),
    ("preopen_validation", ROOT / "results" / "preopen_validation"),
    ("overnight_verification", ROOT / "results" / "overnight_system_verification"),
    ("capability_audit", ROOT / "results" / "capability_audits"),
    ("research_batch", ROOT / "results" / "research_batches"),
    ("market_mirror", ROOT / "results" / "research_simulations"),
    ("crawler_run", ROOT / "results" / "crawler_runs"),
    ("model_telemetry_report", ROOT / "results" / "model_telemetry_reports"),
    ("source_quality_review", ROOT / "results" / "source_quality"),
    ("n8n_evaluation_dataset", ROOT / "results" / "n8n_evaluations"),
    ("overnight_calibration_guard", ROOT / "results" / "overnight_calibration"),
    ("automation_health_audit", ROOT / "results" / "automation_health"),
    ("self_heal_handoff", ROOT / "results" / "self_heal"),
    ("self_heal_plan", ROOT / "results" / "self_heal" / "plans"),
    ("execution_board_review", ROOT / "results" / "execution_board"),
    ("loss_review_evidence", ROOT / "results" / "loss_review_evidence"),
    ("mirofish_handoff_status", ROOT / "results" / "mirofish_handoff"),
    ("hook_event", ROOT / "results" / "_context" / "hook-events"),
]


LATEST_PACKET_FILES = [
    ("promotion_state", ROOT / "results" / "policy" / "promotion_state.json"),
    ("agent_intelligence_summary", ROOT / "results" / "agent_intelligence" / "summary.json"),
    ("connector_health", ROOT / "results" / "_context" / "connector-health.json"),
    ("source_routing", ROOT / "results" / "_context" / "source-routing-compact.json"),
]


GUIDANCE_FILES = [
    ROOT / "AGENTS.md",
    ROOT / "CONTEXT_ROUTER.md",
    ROOT / "TOKEN_EFFICIENCY_AUDIT.md",
    ROOT / "REPO_OVERVIEW.md",
    ROOT / "TRADING_METHODS_AND_AUTOMATIONS.md",
    ROOT / "CODEX_HANDOFF_PROMPT.md",
    ROOT / "CODEX_IMPLEMENTATION_SPEC.md",
]


DRILLDOWN_REASONS = {
    "blocker": "Open the full packet when blockers are present.",
    "issues": "Open the full packet when guardrail issues are present.",
    "submitted": "Open the full packet when any order/action was submitted.",
    "actions": "Open the full packet when actionable decisions are present.",
    "notify": "Open the full packet when notify is true.",
    "stale": "Open the full packet when stale warnings or failed freshness checks appear.",
    "graph_failure": "Open ticker summaries/full packet when graph failures are present.",
    "candidate_change": "Open tournament packet when live candidate changes or is promoted.",
    "schema": "Open raw packet when expected fields are missing.",
    "audit": "Open the audit packet when secrets were not redacted or expected tool config is missing.",
    "crawler": "Open crawler packet when the run is blocked/failed or the fetched page count is unexpected.",
    "model_telemetry": "Open model telemetry when model routes become harmful, costly, unresolved for too long, or budget is exhausted.",
    "connector_health": "Open connector health when a source circuit opens, rate limits occur, or connector errors/fallbacks rise.",
    "source_routing": "Open source routing when analyst vendor chains change or missing source categories become relevant.",
    "board_review": "Open BOARD review when it recommends pausing new buys, finds hard execution issues, or warns about loss/negative P/L.",
    "quality": "Open research batch packet when quality gates fail or fallback_required is true.",
    "automation_health": "Open automation health when managed jobs are missing, partial, late, duplicate, stale, warning, or self-heal follow-up is late.",
}


PACKET_METRIC_DERIVED_FIELDS = {
    "kb": ["raw_packet_file_size_bytes"],
    "lines": ["raw_packet_line_count"],
    "approx_tokens": ["raw_packet_byte_count"],
}

PACKET_SYSTEM_DERIVED_FIELDS = {
    "label": ["snapshot_packet_registry"],
    "path": ["raw_packet_file_path"],
    "directory": ["configured_packet_directory"],
    "missing": ["missing_raw_packet_file"],
    "error": ["raw_packet_json_decode"],
    "drilldown_required": ["drilldown_rules", "raw_packet_fields"],
    "drilldown_reasons": ["drilldown_rules", "raw_packet_fields"],
    "next_open": ["drilldown_rules", "raw_packet_fields"],
}

PROVIDER_BUNDLE_OVERLAY_KEYS = (
    "recent_provider_bundle_count",
    "recent_provider_bundle_scan_limit",
    "latest_provider_bundle_summary_path",
    "latest_provider_bundle_symbol",
    "latest_provider_bundle_generated_at",
    "recent_provider_bundle_gap_count",
    "recent_provider_gap_packet_count",
    "recent_provider_unsupported_route_count",
    "recent_provider_blocked_packet_attempt_count",
    "recent_provider_evidence_needs_with_gap_packets",
    "recent_provider_evidence_needs_without_non_gap_packets",
    "recent_provider_symbols_with_missing_non_gap",
    "recent_provider_bundle_symbols",
    "recent_provider_overnight_target_symbols",
    "recent_provider_target_symbols_with_bundle",
    "recent_provider_target_symbols_missing_bundle",
    "recent_provider_target_bundle_gap_count",
    "recent_provider_target_symbols_with_missing_non_gap",
    "recent_provider_target_evidence_needs_without_non_gap_packets",
    "recent_provider_bundle_gaps",
)

PACKET_FIELD_RAW_SOURCES = {
    "action_count": ["actions"],
    "actions": ["actions"],
    "issues": ["issues"],
    "submitted": ["submitted"],
    "notify": ["notify"],
    "generated_at": ["generated_at", "started_at"],
    "allowed_use": ["freshness.allowed_use"],
    "can_submit_orders": ["freshness.can_submit_orders"],
    "prohibited_use": ["freshness.prohibited_use"],
    "completion_status": ["overnight_quality.completion_status", "completion_status"],
    "completion_reasons": ["overnight_quality.completion_reasons", "completion_reasons"],
    "full_graph_count": ["overnight_quality.full_graph_count"],
    "full_graph_limit": ["overnight_quality.full_graph_limit"],
    "requested_full_graph_limit": ["overnight_quality.requested_full_graph_limit"],
    "full_graph_attempt_count": ["overnight_quality.full_graph_attempt_count"],
    "full_graph_success_count": ["overnight_quality.full_graph_success_count"],
    "fallback_count": ["overnight_quality.fallback_count"],
    "graph_failure_count": ["overnight_quality.graph_failure_count"],
    "original_graph_selected_tickers": [
        "original_tradingagents_graph.selected_tickers",
        "overnight_quality.original_graph_selected_tickers",
    ],
    "original_graph_successful_tickers": [
        "original_tradingagents_graph.successful_tickers",
        "overnight_quality.original_graph_successful_tickers",
    ],
    "original_graph_failed_tickers": [
        "original_tradingagents_graph.failed_tickers",
        "overnight_quality.original_graph_failed_tickers",
    ],
    "research_context_packet_count": ["overnight_quality.research_context_packet_count"],
    "research_context_blocked_count": ["overnight_quality.research_context_blocked_count"],
    "overnight_graph_profile": ["overnight_quality.graph_config.graph_profile"],
    "overnight_model_route": ["overnight_quality.graph_config.model_route"],
    "overnight_llm_provider": ["overnight_quality.graph_config.llm_provider"],
    "overnight_quick_model": ["overnight_quality.graph_config.quick_think_llm"],
    "overnight_deep_model": ["overnight_quality.graph_config.deep_think_llm"],
    "self_heal_signal_labels": ["signals[].label"],
    "self_heal_signal_reasons": ["signals[].reason"],
    "self_heal_signal_classifications": ["signals[].classification"],
    "self_heal_escalated_labels": ["signals[].label"],
    "self_heal_safe_recorded_labels": ["signals[].label"],
    "required_clean_packets": ["new_buy_policy.required_clean_packets"],
    "new_buy_policy_plain_english": ["new_buy_policy.plain_english"],
    "negative_live_pl_packets": ["metrics.negative_live_pl_packets"],
    "next_hour_buy_side": ["next_hour_policy.buy_side"],
    "next_hour_sell_side": ["next_hour_policy.sell_side"],
    "warning_types": ["warnings[].type"],
    "violation_types": ["violations[].type"],
    "symbol": ["payload.symbol", "symbol"],
    "hourly_decision": ["payload.hourly_decision"],
    "review_allowed": ["payload.review_allowed"],
    "source_packet_count": ["payload.source_packet_ids", "freshness.source_packet_count"],
    "evidence_needs": ["payload.evidence_needs"],
    "evidence_coverage_by_need": ["payload.evidence_coverage_by_need"],
    "remaining_blockers_before_refresh_count": ["payload.remaining_blockers_before_refresh"],
    "resolved_blocker_count": ["payload.resolved_blockers_by_refresh"],
    "resolved_blockers_by_refresh": ["payload.resolved_blockers_by_refresh"],
    "remaining_blocker_count": ["payload.remaining_blockers"],
    "next_action": ["payload.next_action"],
    "execution_authority": ["payload.execution_authority", "execution_authority"],
    **{field: [field] for field in PROVIDER_BUNDLE_OVERLAY_KEYS},
}


def approx_tokens(chars: int) -> int:
    return max(1, math.ceil(chars / 4))


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def read_json(path: Path) -> Any | None:
    return JSON_FILE_CACHE.read_json(path)


def resolve_repo_path(value: Any) -> Path | None:
    text = str(value or "").strip()
    if not text:
        return None
    path = Path(text)
    if not path.is_absolute():
        path = ROOT / path
    return path


def compact_string_list(value: Any) -> list[str]:
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def enrich_overnight_prior_feed(prior_feed: dict[str, Any]) -> dict[str, Any]:
    """Fill applied/dedupe proof for legacy prior-feed pointers."""

    if not isinstance(prior_feed, dict) or not prior_feed.get("path"):
        return prior_feed
    enriched = dict(prior_feed)
    prior_feed_packet: dict[str, Any] = {}
    needs_packet = any(
        enriched.get(name) is None
        for name in (
            "prior_applied",
            "dedupe_applied",
            "input_packet_ref_count",
            "unique_packet_ref_count",
            "duplicate_packet_ref_count",
            "carry_forward_scope",
        )
    )
    if needs_packet:
        feed_path = resolve_repo_path(enriched.get("path"))
        packet = read_json(feed_path) if feed_path else None
        if isinstance(packet, dict):
            prior_feed_packet = packet

    def feed_value(name: str) -> Any:
        value = enriched.get(name)
        if value is None:
            return prior_feed_packet.get(name)
        return value

    raw_refs = compact_string_list(feed_value("packet_refs"))
    unique_refs = list(dict.fromkeys(raw_refs))
    carry_forward_scope = compact_string_list(feed_value("carry_forward_scope"))
    if not carry_forward_scope and prior_feed_packet:
        scope_names = {
            "packet_refs": "source_packet_refs",
            "provider_needs": "provider_fallbacks",
            "watchlists": "watchlists",
            "mirofish": "mirofish",
            "methodology": "methodology",
        }
        for name, scope_name in scope_names.items():
            if prior_feed_packet.get(name):
                carry_forward_scope.append(scope_name)

    enriched["prior_applied"] = bool(
        feed_value("prior_applied")
        if feed_value("prior_applied") is not None
        else carry_forward_scope
    )
    enriched["dedupe_applied"] = bool(
        feed_value("dedupe_applied")
        if feed_value("dedupe_applied") is not None
        else (raw_refs or carry_forward_scope)
    )
    enriched["input_packet_ref_count"] = (
        feed_value("input_packet_ref_count")
        if feed_value("input_packet_ref_count") is not None
        else (len(raw_refs) if raw_refs else None)
    )
    enriched["unique_packet_ref_count"] = (
        feed_value("unique_packet_ref_count")
        if feed_value("unique_packet_ref_count") is not None
        else (len(unique_refs) if raw_refs else None)
    )
    enriched["duplicate_packet_ref_count"] = (
        feed_value("duplicate_packet_ref_count")
        if feed_value("duplicate_packet_ref_count") is not None
        else (len(raw_refs) - len(unique_refs) if raw_refs else None)
    )
    enriched["carry_forward_scope"] = carry_forward_scope
    return enriched


def int_or_zero(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def recent_provider_bundle_gap_overlay(
    directory: Path | None = None,
    *,
    limit: int = PROVIDER_BUNDLE_SCAN_LIMIT,
) -> dict[str, Any]:
    """Summarize recent ticker provider-bundle evidence gaps for compact routing."""

    evidence_dir = directory or RESEARCH_EVIDENCE_DIR
    if not evidence_dir.exists():
        target_symbols = latest_overnight_top_symbols()
        return {
            "recent_provider_bundle_count": 0,
            "recent_provider_bundle_gap_count": 0,
            "recent_provider_gap_packet_count": 0,
            "recent_provider_unsupported_route_count": 0,
            "recent_provider_blocked_packet_attempt_count": 0,
            "recent_provider_evidence_needs_with_gap_packets": [],
            "recent_provider_evidence_needs_without_non_gap_packets": [],
            "recent_provider_symbols_with_missing_non_gap": [],
            "recent_provider_bundle_symbols": [],
            "recent_provider_overnight_target_symbols": target_symbols,
            "recent_provider_target_symbols_with_bundle": [],
            "recent_provider_target_symbols_missing_bundle": target_symbols,
            "recent_provider_target_bundle_gap_count": 0,
            "recent_provider_target_symbols_with_missing_non_gap": [],
            "recent_provider_target_evidence_needs_without_non_gap_packets": [],
            "recent_provider_bundle_gaps": [],
        }

    bundle_records: list[dict[str, Any]] = []
    seen_bundle_keys: set[tuple[str, str, tuple[str, ...]]] = set()
    needs_with_gap: set[str] = set()
    needs_without_non_gap: set[str] = set()
    symbols_with_missing: set[str] = set()
    total_gap_packets = 0
    total_unsupported_routes = 0
    total_blocked_attempts = 0

    for path in recent_jsons(evidence_dir, limit=limit):
        packet = read_json(path)
        if not isinstance(packet, dict) or packet.get("source_name") != "ticker_provider_orchestrator":
            continue
        payload = packet.get("payload")
        if not isinstance(payload, dict):
            continue

        symbol = str(packet.get("symbol") or payload.get("symbol") or "").upper()
        packet_ids = tuple(compact_string_list(payload.get("source_packet_ids")))
        bundle_key = (symbol, str(packet.get("generated_at") or ""), packet_ids)
        if bundle_key in seen_bundle_keys:
            continue
        seen_bundle_keys.add(bundle_key)
        packet_needs_with_gap = compact_string_list(
            payload.get("evidence_needs_with_gap_packets")
        )
        packet_needs_without_non_gap = compact_string_list(
            payload.get("evidence_needs_without_non_gap_packets")
        )
        gap_packet_count = int_or_zero(payload.get("gap_packet_count"))
        unsupported_route_count = int_or_zero(payload.get("unsupported_route_count"))
        blocked_attempt_count = int_or_zero(payload.get("blocked_packet_attempt_count"))

        needs_with_gap.update(packet_needs_with_gap)
        needs_without_non_gap.update(packet_needs_without_non_gap)
        if symbol and packet_needs_without_non_gap:
            symbols_with_missing.add(symbol)
        total_gap_packets += gap_packet_count
        total_unsupported_routes += unsupported_route_count
        total_blocked_attempts += blocked_attempt_count

        record = {
            "symbol": symbol,
            "path": rel(path),
            "generated_at": packet.get("generated_at"),
            "gap_packet_count": gap_packet_count,
            "unsupported_route_count": unsupported_route_count,
            "blocked_packet_attempt_count": blocked_attempt_count,
            "evidence_needs_with_gap_packets": packet_needs_with_gap,
            "evidence_needs_without_non_gap_packets": packet_needs_without_non_gap,
        }
        bundle_records.append(record)

    target_symbols = latest_overnight_top_symbols()
    bundle_symbols = sorted({record["symbol"] for record in bundle_records if record["symbol"]})
    latest_record_by_symbol: dict[str, dict[str, Any]] = {}
    for record in bundle_records:
        symbol = str(record.get("symbol") or "")
        if symbol and symbol not in latest_record_by_symbol:
            latest_record_by_symbol[symbol] = record
    bundled_target_symbols = [
        symbol for symbol in target_symbols if symbol in set(bundle_symbols)
    ]
    missing_target_symbols = [
        symbol for symbol in target_symbols if symbol not in set(bundle_symbols)
    ]
    gap_records = [
        record
        for record in bundle_records
        if record["gap_packet_count"] > 0 or record["evidence_needs_without_non_gap_packets"]
    ]
    latest_target_records = [
        latest_record_by_symbol[symbol]
        for symbol in target_symbols
        if symbol in latest_record_by_symbol
    ]
    target_gap_records = [
        record
        for record in latest_target_records
        if record["gap_packet_count"] > 0 or record["evidence_needs_without_non_gap_packets"]
    ]
    target_needs_without_non_gap = sorted(
        {
            need
            for record in target_gap_records
            for need in record.get("evidence_needs_without_non_gap_packets", [])
        }
    )
    target_symbols_with_missing = sorted(
        {
            str(record.get("symbol"))
            for record in target_gap_records
            if record.get("evidence_needs_without_non_gap_packets") and record.get("symbol")
        }
    )
    latest_bundle = bundle_records[0] if bundle_records else {}
    return {
        "recent_provider_bundle_count": len(bundle_records),
        "recent_provider_bundle_scan_limit": limit,
        "latest_provider_bundle_summary_path": latest_bundle.get("path"),
        "latest_provider_bundle_symbol": latest_bundle.get("symbol"),
        "latest_provider_bundle_generated_at": latest_bundle.get("generated_at"),
        "recent_provider_bundle_gap_count": len(gap_records),
        "recent_provider_gap_packet_count": total_gap_packets,
        "recent_provider_unsupported_route_count": total_unsupported_routes,
        "recent_provider_blocked_packet_attempt_count": total_blocked_attempts,
        "recent_provider_evidence_needs_with_gap_packets": sorted(needs_with_gap),
        "recent_provider_evidence_needs_without_non_gap_packets": sorted(
            needs_without_non_gap
        ),
        "recent_provider_symbols_with_missing_non_gap": sorted(symbols_with_missing),
        "recent_provider_bundle_symbols": bundle_symbols,
        "recent_provider_overnight_target_symbols": target_symbols,
        "recent_provider_target_symbols_with_bundle": bundled_target_symbols,
        "recent_provider_target_symbols_missing_bundle": missing_target_symbols,
        "recent_provider_target_bundle_gap_count": len(target_gap_records),
        "recent_provider_target_symbols_with_missing_non_gap": target_symbols_with_missing,
        "recent_provider_target_evidence_needs_without_non_gap_packets": (
            target_needs_without_non_gap
        ),
        "recent_provider_bundle_gaps": gap_records[:5],
    }


def annotate_source_routing_compact(path: Path) -> None:
    data = read_json(path)
    if not isinstance(data, dict):
        return
    data = dict(data)
    data.update(recent_provider_bundle_gap_overlay())
    path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")


def latest_overnight_top_symbols(limit: int = 3) -> list[str]:
    path = latest_snapshot_json("overnight", ROOT / "results" / "overnight_plans")
    data = read_json(path) if path else None
    symbols: list[str] = []

    def add_symbol(value: Any) -> None:
        text = str(value or "").strip().upper()
        if text and text not in symbols:
            symbols.append(text)

    if isinstance(data, dict):
        top_candidate = data.get("top_candidate")
        if isinstance(top_candidate, dict):
            add_symbol(top_candidate.get("symbol"))
        for symbol in compact_string_list(data.get("top_symbols")):
            add_symbol(symbol)
        raw_path = resolve_repo_path(data.get("raw_packet_path"))
        raw_data = read_json(raw_path) if raw_path else None
        if isinstance(raw_data, dict):
            for symbol in top_ranked_symbols(raw_data.get("ranked_candidates"), limit):
                add_symbol(symbol)
    return symbols[:limit]


def expected_overnight_trade_date(now: dt.datetime | None = None) -> str:
    current = now or dt.datetime.now(tz=dt.timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=dt.timezone.utc)
    local_date = current.astimezone(CENTRAL).date()
    while local_date.weekday() >= 5:
        local_date += dt.timedelta(days=1)
    return local_date.isoformat()


def read_toml(path: Path) -> dict[str, Any]:
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def refresh_generated_context_files() -> None:
    try:
        from tradingagents.dataflows.interface import write_decision_source_routing

        source_routing_path = write_decision_source_routing(
            ROOT / "results" / "_context" / "source-routing.json"
        )
        annotate_source_routing_compact(
            source_routing_path.with_name("source-routing-compact.json")
        )
    except Exception:
        # Context generation must not block the morning bots; missing packets are
        # surfaced by the normal snapshot missing-file path.
        return


def file_metric(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"path": rel(path), "missing": True}
    metric = JSON_FILE_CACHE.text_metric(path)
    if metric is None:
        return {"path": rel(path), "missing": True}
    return {
        "path": rel(path),
        "bytes": metric.byte_count,
        "kb": round(metric.byte_count / 1024, 1),
        "lines": metric.line_count,
        "approx_tokens": approx_tokens(metric.char_count),
    }


def latest_json(directory: Path) -> Path | None:
    latest = directory / "latest.json"
    if latest.exists():
        return latest
    candidates = sorted(directory.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0] if candidates else None


def latest_snapshot_json(label: str, directory: Path) -> Path | None:
    if label in COMPACT_SNAPSHOT_LABELS:
        latest_compact = directory / "latest-compact.json"
        if latest_compact.exists():
            return latest_compact
    return latest_json(directory)


def latest_packet_path_for_label(label: str) -> Path | None:
    for packet_label, directory in LATEST_PACKETS:
        if packet_label == label:
            return latest_snapshot_json(label, directory)
    return None


def latest_raw_packet_ref_for_label(label: str) -> str | None:
    latest_path = latest_packet_path_for_label(label)
    if latest_path is None:
        return None
    try:
        data = json.loads(latest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return rel(latest_path)
    if isinstance(data, dict) and data.get("raw_packet_path"):
        return str(data.get("raw_packet_path"))
    return rel(latest_path)


def jsonl_record_count(path: Path) -> int | None:
    if not path.exists():
        return None
    try:
        return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
    except OSError:
        return None


def latest_loss_review_evidence_for_hourly(raw_hourly_ref: Any) -> tuple[Path, dict[str, Any], dict[str, Any]] | None:
    """Return latest matching loss-review evidence for a raw hourly packet.

    Compact hourly summaries can outlive the evidence refresh that resolves
    several original blocker categories. This helper lets the hourly context
    show the newer evidence state only when the evidence packet explicitly
    targets the same raw hourly packet.
    """

    if not raw_hourly_ref:
        return None
    evidence_path = latest_packet_path_for_label("loss_review_evidence")
    if evidence_path is None:
        return None
    evidence = read_json(evidence_path)
    if not isinstance(evidence, dict):
        return None
    payload = evidence.get("payload") if isinstance(evidence.get("payload"), dict) else {}
    evidence_hourly_ref = payload.get("hourly_packet_path")
    if normalized_packet_ref(evidence_hourly_ref) != normalized_packet_ref(raw_hourly_ref):
        return None
    return evidence_path, evidence, payload


def loss_review_refreshed_reason(
    *,
    evidence_payload: dict[str, Any],
    advisory: dict[str, Any],
    resolved_count: int,
    original_count: int,
    remaining_blockers: list[Any],
) -> str:
    symbol = str(evidence_payload.get("symbol") or "Position").strip() or "Position"
    parts = [
        f"{symbol} is in loss review.",
        "No live sell was submitted.",
    ]
    if original_count:
        parts.append(f"Refreshed evidence resolved {resolved_count} of {original_count} checks.")
    else:
        parts.append(f"Refreshed evidence resolved {resolved_count} check(s).")

    clean_remaining = [str(item).strip() for item in remaining_blockers if str(item).strip()]
    if clean_remaining:
        label = "Remaining blocker" if len(clean_remaining) == 1 else "Remaining blockers"
        shown = "; ".join(clean_remaining[:2])
        if len(clean_remaining) > 2:
            shown = f"{shown}; +{len(clean_remaining) - 2} more"
        parts.append(f"{label}: {shown}.")
    else:
        parts.append("No refreshed evidence blockers remain; normal live gates still apply.")

    candidate = advisory.get("loss_exit_candidate")
    if isinstance(candidate, dict):
        reason = str(candidate.get("allowed_exit_reason_candidate") or "").strip()
        confidence = str(candidate.get("confidence") or "").strip()
        if reason and confidence:
            parts.append(
                f"BOARD-only candidate: {reason} at confidence {confidence}; "
                "this is not approval to sell."
            )
        elif reason:
            parts.append(f"BOARD-only candidate: {reason}; this is not approval to sell.")

    return " ".join(parts)


def _summary_packet_path(path_value: Any) -> Path | None:
    raw = str(path_value or "").strip()
    if not raw:
        return None
    path = Path(raw)
    if path.is_absolute():
        return path
    return ROOT / path


def reconcile_hourly_loss_review_compact_sidecars(
    snapshot: dict[str, Any],
) -> list[Path]:
    """Persist refreshed loss-review wording into matching hourly sidecars.

    The snapshot summary can safely rewrite a loss-review reason after a later
    evidence refresh resolves stale blocker text. Dashboards and email paths may
    still read ``results/hourly_supervisor/latest-compact.json`` directly, so
    keep that compact sidecar aligned only when the evidence explicitly targets
    the same raw hourly packet.
    """

    written: list[Path] = []
    for packet in snapshot.get("latest_packets") or []:
        if not isinstance(packet, dict) or packet.get("label") != "hourly":
            continue
        if packet.get("loss_review_evidence_matches_latest") is not True:
            continue
        refreshed_reason = str(packet.get("reason") or "").strip()
        if not refreshed_reason:
            continue
        compact_path = _summary_packet_path(packet.get("path"))
        if compact_path is None:
            continue
        compact = read_json(compact_path)
        if not isinstance(compact, dict):
            continue
        compact = dict(compact)
        if compact.get("schema") != "compact_hourly_supervisor_v1":
            continue
        if compact.get("decision") != "loss-review":
            continue
        if normalized_packet_ref(compact.get("raw_packet_path")) != normalized_packet_ref(
            packet.get("raw_packet_path")
        ):
            continue
        if compact.get("reason") == refreshed_reason:
            continue

        compact["reason"] = refreshed_reason
        compact["loss_review_evidence_matches_latest"] = True
        for key in (
            "loss_review_evidence_path",
            "loss_review_remaining_blocker_count",
            "loss_review_resolved_blocker_count",
            "loss_review_next_action",
        ):
            if key in packet:
                compact[key] = packet[key]
        compact_path.write_text(
            json.dumps(compact, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        written.append(compact_path)
    return written


def normalized_packet_ref(path_value: Any) -> str:
    text = str(path_value or "").strip()
    if text.startswith("local://"):
        text = text.removeprefix("local://")
    text = text.replace("/", "\\")
    try:
        candidate = Path(text)
        if candidate.is_absolute():
            text = rel(candidate)
    except Exception:
        pass
    return text.lower()


def observed_less_than_expected_gap(status_reason: Any) -> int | None:
    match = re.search(r"observed_runs_less_than_expected:(\d+)/(\d+)", str(status_reason or ""))
    if not match:
        return None
    actual = int(match.group(1))
    expected = int(match.group(2))
    return max(expected - actual, 0)


def recent_jsons(directory: Path, limit: int = 2) -> list[Path]:
    candidates = sorted(
        [p for p in directory.glob("*.json") if p.name != "latest.json"],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    latest = directory / "latest.json"
    if latest.exists():
        return [latest, *candidates[: max(0, limit - 1)]]
    return candidates[:limit]


def recent_snapshot_jsons(label: str, directory: Path, limit: int = 2) -> list[Path]:
    if label not in COMPACT_SNAPSHOT_LABELS:
        return recent_jsons(directory, limit)
    latest_compact = directory / "latest-compact.json"
    compact_candidates = sorted(
        [p for p in directory.glob("*.compact.json")],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if latest_compact.exists():
        return [latest_compact, *compact_candidates[: max(0, limit - 1)]]
    if compact_candidates:
        return compact_candidates[:limit]
    return recent_jsons(directory, limit)


def compact_action(action: Any) -> str:
    if not isinstance(action, dict):
        return str(action)[:120]
    bits = [
        str(action.get("action") or action.get("type") or "?"),
        str(action.get("symbol") or action.get("ticker") or ""),
        str(action.get("account") or ""),
    ]
    return " ".join(bit for bit in bits if bit).strip()


def top_ranked_symbols(items: Any, limit: int = 5) -> list[str]:
    if not isinstance(items, list):
        return []
    symbols: list[str] = []
    for item in items[:limit]:
        if isinstance(item, dict):
            value = item.get("symbol") or item.get("ticker") or item.get("strategy_id")
            if value:
                symbols.append(str(value))
        elif isinstance(item, str):
            symbols.append(item)
    return symbols


def parse_packet_timestamp(value: Any) -> dt.datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def summarize_incidents(*, now: dt.datetime | None = None) -> dict[str, Any]:
    """Return only the five incident fields permitted in compact context."""

    incidents_root = ROOT / "results" / "control_plane" / "incidents"
    current = now or dt.datetime.now(dt.timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=dt.timezone.utc)
    else:
        current = current.astimezone(dt.timezone.utc)
    active: list[tuple[dict[str, Any], Path]] = []
    if incidents_root.exists():
        for snapshot_path in incidents_root.glob("*/latest.json"):
            payload = read_json(snapshot_path)
            if not isinstance(payload, dict):
                continue
            if not is_safe_incident_id(payload.get("incident_id")):
                continue
            try:
                stage = IncidentStage(payload.get("stage"))
            except ValueError:
                continue
            if parse_packet_timestamp(payload.get("created_at")) is None:
                continue
            if stage is not IncidentStage.CLOSED:
                active.append((payload, snapshot_path))

    oldest_minutes = 0
    if active:
        ages = [
            max(0, int((current - created).total_seconds() // 60))
            for payload, _path in active
            if (created := parse_packet_timestamp(payload.get("created_at"))) is not None
        ]
        oldest_minutes = max(ages, default=0)
    latest = max(
        active,
        key=lambda item: parse_packet_timestamp(item[0].get("updated_at"))
        or parse_packet_timestamp(item[0].get("created_at"))
        or dt.datetime.min.replace(tzinfo=dt.timezone.utc),
        default=None,
    )
    return {
        "active_incident_count": len(active),
        "oldest_active_incident_minutes": oldest_minutes,
        "unowned_incident_count": sum(
            not str(payload.get("owner_role") or "").strip() for payload, _path in active
        ),
        "external_blocked_count": sum(
            payload.get("stage") == "external_blocked" for payload, _path in active
        ),
        "latest_incident_ref": rel(latest[1]) if latest else None,
    }


def path_is_under(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def latest_packet_generated_at(relative_path: str) -> str | None:
    payload = read_json(ROOT / relative_path)
    if isinstance(payload, dict):
        value = payload.get("generated_at") or payload.get("started_at")
        return str(value) if value is not None else None
    return None


def summarize_packet(label: str, path: Path) -> dict[str, Any]:
    data = read_json(path)
    if not isinstance(data, dict):
        return {"label": label, "path": rel(path), "error": "unreadable-json"}

    summary: dict[str, Any] = {
        "label": label,
        "path": rel(path),
        "kb": round(path.stat().st_size / 1024, 1),
        "lines": file_metric(path).get("lines"),
        "approx_tokens": approx_tokens(path.stat().st_size),
        "generated_at": data.get("generated_at") or data.get("started_at"),
        "drilldown_required": False,
        "drilldown_reasons": [],
    }
    if data.get("raw_packet_path"):
        summary["raw_packet_path"] = str(data.get("raw_packet_path"))

    def flag(reason: str) -> None:
        summary["drilldown_required"] = True
        summary["drilldown_reasons"].append(reason)

    if label == "hourly":
        actions = data.get("actions") or []
        issues = data.get("issues") or []
        submitted = data.get("submitted") or []
        action_summary = data.get("action_summary") if isinstance(data.get("action_summary"), dict) else {}
        action_count = int(
            action_summary.get("action_count")
            if action_summary.get("action_count") is not None
            else len(actions)
        )
        issue_count = int(
            data.get("issue_count") if data.get("issue_count") is not None else len(issues)
        )
        submitted_count = int(
            data.get("submitted_count") if data.get("submitted_count") is not None else len(submitted)
        )
        summary.update(
            {
                "decision": data.get("decision"),
                "reason": data.get("reason"),
                "actions": [compact_action(a) for a in actions[:5]],
                "action_count": action_count,
                "issues": issue_count,
                "submitted": submitted_count,
                "notify": data.get("notify")
                if data.get("notify") is not None
                else (data.get("alert_summary") or {}).get("notify"),
                "raw_packet_path": data.get("raw_packet_path"),
                "can_submit_orders": data.get("can_submit_orders"),
                "execution_authority": data.get("execution_authority"),
                "next_open": "Open full hourly packet if action_count, issues, submitted, or notify is nonzero/true.",
            }
        )
        evidence_match = latest_loss_review_evidence_for_hourly(data.get("raw_packet_path"))
        if evidence_match is not None and data.get("decision") == "loss-review":
            evidence_path, _evidence, evidence_payload = evidence_match
            remaining_blockers = list(evidence_payload.get("remaining_blockers") or [])
            resolved_blockers = list(evidence_payload.get("resolved_blockers_by_refresh") or [])
            blockers_before_refresh = list(
                evidence_payload.get("remaining_blockers_before_refresh") or []
            )
            advisory = (
                evidence_payload.get("advisory_analysis")
                if isinstance(evidence_payload.get("advisory_analysis"), dict)
                else evidence_payload.get("advisory_summary")
                if isinstance(evidence_payload.get("advisory_summary"), dict)
                else {}
            )
            summary.update(
                {
                    "loss_review_evidence_path": rel(evidence_path),
                    "loss_review_evidence_matches_latest": True,
                    "loss_review_symbol": evidence_payload.get("symbol"),
                    "loss_review_review_allowed": evidence_payload.get("review_allowed"),
                    "loss_review_entry_context_found": bool(
                        evidence_payload.get("entry_context_found")
                    ),
                    "loss_review_remaining_blockers_before_refresh_count": len(
                        blockers_before_refresh
                    ),
                    "loss_review_resolved_blocker_count": len(resolved_blockers),
                    "loss_review_remaining_blocker_count": len(remaining_blockers),
                    "loss_review_remaining_blockers": remaining_blockers[:8],
                    "loss_review_resolved_blockers_by_refresh": resolved_blockers[:8],
                    "loss_review_next_action": evidence_payload.get("next_action"),
                    "loss_review_current_thesis_status_candidate": advisory.get(
                        "current_thesis_status_candidate"
                    ),
                    "loss_review_status_plain_english": (
                        "Latest evidence refresh resolved "
                        f"{len(resolved_blockers)} of "
                        f"{len(blockers_before_refresh)} original blocker(s); "
                        f"{len(remaining_blockers)} blocker(s) remain for BOARD/manual review."
                    ),
                    "reason": loss_review_refreshed_reason(
                        evidence_payload=evidence_payload,
                        advisory=advisory,
                        resolved_count=len(resolved_blockers),
                        original_count=len(blockers_before_refresh),
                        remaining_blockers=remaining_blockers,
                    ),
                }
            )
        if action_count:
            flag("actions")
        if issue_count:
            flag("issues")
        if submitted_count:
            flag("submitted")
        if summary.get("notify"):
            flag("notify")
        if data.get("decision") == "loss-review":
            flag("board_review")
        compact_schema = data.get("schema") == "compact_hourly_supervisor_v1"
        if not compact_schema and not {"generated_at", "decision", "actions", "issues", "submitted"}.issubset(data):
            flag("schema")
    elif label == "paper_tournament":
        report = data.get("latest_report") or data.get("report") or {}
        rankings = report.get("rankings") or []
        candidate = report.get("live_strategy_candidate") or data.get("live_strategy_selection") or {}
        submitted_count = int(data.get("submitted_count") or len(data.get("submitted") or []))
        candidate_selection_path = data.get("live_selection_path")
        generated_at = report.get("generated_at") or data.get("generated_at") or data.get("started_at")
        summary.update(
            {
                "generated_at": generated_at,
                "leader": rankings[0].get("strategy_id") if rankings and isinstance(rankings[0], dict) else None,
                "rankings": top_ranked_symbols(rankings, 3),
                "ranking_count": len(rankings),
                "candidate_status": candidate.get("status"),
                "candidate_strategy": candidate.get("strategy_id"),
                "submitted_count": submitted_count,
                "live_selection_path": candidate_selection_path,
                "next_open": "Open full tournament packet if a candidate was promoted, a live-selection file was written, or submitted_count is nonzero.",
            }
        )
        if candidate.get("status") in {"promoted", "live_enabled"} or candidate_selection_path or submitted_count:
            flag("candidate_change")
        if not (data.get("latest_report") or data.get("report")):
            flag("schema")
    elif label == "overnight":
        quality = data.get("overnight_quality") or {}
        if not isinstance(quality, dict):
            quality = {}
        graph_config = quality.get("graph_config") or {}
        if not isinstance(graph_config, dict):
            graph_config = {}
        ranked = data.get("ranked_candidates") or []
        top = ranked[0] if ranked and isinstance(ranked[0], dict) else {}
        counts = data.get("counts") if isinstance(data.get("counts"), dict) else {}
        if not top and isinstance(data.get("top_candidate"), dict):
            top = data.get("top_candidate") or {}
        graph_failures = int(quality.get("graph_failure_count") or 0)
        submitted = data.get("submitted") or []
        submitted_count = int(data.get("submitted_count") or len(submitted))
        trade_date = str(data.get("trade_date") or "").strip()
        expected_trade_date = expected_overnight_trade_date()
        stale_trade_date = bool(trade_date and trade_date != expected_trade_date)
        research_context_summary = data.get("research_context_summary")
        if not isinstance(research_context_summary, dict):
            research_context_summary = data.get("research_context")
        if not isinstance(research_context_summary, dict):
            research_context_summary = {}
        prior_feed = research_context_summary.get("prior_feed") or {}
        if not isinstance(prior_feed, dict):
            prior_feed = {}
        prior_feed = enrich_overnight_prior_feed(prior_feed)
        creator_workflow_summary = data.get("creator_workflow_summary")
        if isinstance(creator_workflow_summary, dict):
            creator_workflows = [
                {
                    "symbol": str(symbol),
                    "packet_path": str(packet_path),
                    "role_count": creator_workflow_summary.get("role_count_min"),
                }
                for symbol, packet_path in zip(
                    creator_workflow_summary.get("symbols") or [],
                    creator_workflow_summary.get("packet_paths") or [],
                    strict=False,
                )
            ]
            creator_workflow_count = int(creator_workflow_summary.get("workflow_count") or 0)
            creator_workflow_symbols = [str(item) for item in creator_workflow_summary.get("symbols") or []]
            creator_workflow_packet_paths = [
                str(item) for item in creator_workflow_summary.get("packet_paths") or []
            ]
            creator_role_count_min = creator_workflow_summary.get("role_count_min")
            creator_bad_authority_count = int(creator_workflow_summary.get("bad_authority_count") or 0)
        else:
            creator_workflows = []
            for item in data.get("ticker_results") or []:
                if not isinstance(item, dict):
                    continue
                workflow = item.get("creator_workflow")
                if not isinstance(workflow, dict):
                    continue
                packet_path = workflow.get("packet_path")
                if not packet_path:
                    continue
                creator_workflows.append(
                    {
                        "symbol": str(item.get("symbol") or ""),
                        "packet_path": str(packet_path),
                        "complete_report_path": str(workflow.get("complete_report_path") or ""),
                        "role_count": int(workflow.get("role_count") or 0),
                        "execution_authority": workflow.get("execution_authority"),
                    }
                )
            creator_workflow_count = len(creator_workflows)
            creator_workflow_symbols = [
                item["symbol"] for item in creator_workflows[:5] if item["symbol"]
            ]
            creator_workflow_packet_paths = [
                item["packet_path"] for item in creator_workflows[:5]
            ]
            creator_role_count_min = None
            creator_bad_authority_count = sum(
                1
                for item in creator_workflows
                if item.get("execution_authority") not in {None, "none"}
            )
        creator_role_counts = [
            item["role_count"] for item in creator_workflows if item.get("role_count") is not None
        ]
        if creator_role_count_min is None and creator_role_counts:
            creator_role_count_min = min(creator_role_counts)
        original_graph = data.get("original_tradingagents_graph") or {}
        if not isinstance(original_graph, dict):
            original_graph = {}
        selected_tickers = original_graph.get("selected_tickers")
        if selected_tickers is None:
            selected_tickers = quality.get("original_graph_selected_tickers")
        successful_tickers = original_graph.get("successful_tickers")
        if successful_tickers is None:
            successful_tickers = quality.get("original_graph_successful_tickers")
        failed_tickers = original_graph.get("failed_tickers")
        if failed_tickers is None:
            failed_tickers = quality.get("original_graph_failed_tickers")
        summary.update(
            {
                "analysis_only": data.get("analysis_only"),
                "raw_packet_path": data.get("raw_packet_path"),
                "trade_date": trade_date or None,
                "expected_trade_date": expected_trade_date,
                "stale_trade_date": stale_trade_date,
                "submitted": submitted_count,
                "ranked_count": len(ranked) or counts.get("ranked_candidates"),
                "top_symbol": top.get("symbol"),
                "top_symbols": top_ranked_symbols(ranked, 5) or [top.get("symbol")]
                if top.get("symbol")
                else [],
                "completion_status": quality.get("completion_status") or data.get("completion_status"),
                "completion_reasons": quality.get("completion_reasons") or data.get("completion_reasons") or [],
                "full_graph_count": quality.get("full_graph_count"),
                "full_graph_limit": quality.get("full_graph_limit"),
                "requested_full_graph_limit": quality.get("requested_full_graph_limit"),
                "full_graph_attempt_count": quality.get("full_graph_attempt_count"),
                "full_graph_success_count": quality.get("full_graph_success_count"),
                "fallback_count": quality.get("fallback_count"),
                "graph_failure_count": graph_failures,
                "original_graph_selected_tickers": selected_tickers,
                "original_graph_successful_tickers": successful_tickers,
                "original_graph_failed_tickers": failed_tickers,
                "graph_config": quality.get("graph_config"),
                "overnight_graph_profile": graph_config.get("graph_profile"),
                "overnight_model_route": graph_config.get("model_route"),
                "overnight_llm_provider": graph_config.get("llm_provider"),
                "overnight_quick_model": graph_config.get("quick_think_llm"),
                "overnight_deep_model": graph_config.get("deep_think_llm"),
                "research_context_packet_count": quality.get("research_context_packet_count"),
                "research_context_blocked_count": quality.get("research_context_blocked_count"),
                "overnight_prior_feed_path": prior_feed.get("path"),
                "overnight_prior_feed_latest_path": prior_feed.get("latest_path"),
                "overnight_prior_feed_packet_count": prior_feed.get("packet_count"),
                "overnight_prior_feed_blocked_count": prior_feed.get("blocked_count"),
                "overnight_prior_feed_applied": prior_feed.get("prior_applied"),
                "overnight_prior_feed_dedupe_applied": prior_feed.get("dedupe_applied"),
                "overnight_prior_feed_input_packet_ref_count": prior_feed.get(
                    "input_packet_ref_count"
                ),
                "overnight_prior_feed_unique_packet_ref_count": prior_feed.get(
                    "unique_packet_ref_count"
                ),
                "overnight_prior_feed_duplicate_packet_ref_count": prior_feed.get(
                    "duplicate_packet_ref_count"
                ),
                "overnight_prior_feed_carry_forward_scope": list(
                    prior_feed.get("carry_forward_scope") or []
                ),
                "ticker_result_count": counts.get("ticker_results")
                if counts
                else len(data.get("ticker_results") or []),
                "creator_workflow_count": creator_workflow_count,
                "creator_workflow_symbols": creator_workflow_symbols,
                "creator_workflow_role_count_min": creator_role_count_min,
                "creator_workflow_packet_paths": creator_workflow_packet_paths,
                "next_open": "Open full overnight packet only for graph failures, missing rankings, submissions, or stale latest mismatch.",
            }
        )
        if any(item["role_count"] < 4 for item in creator_workflows) or creator_bad_authority_count:
            flag("schema")
        if graph_failures:
            flag("graph_failure")
        if submitted_count:
            flag("submitted")
        if stale_trade_date or not trade_date:
            flag("stale")
        if not ranked and not counts.get("ranked_candidates"):
            flag("schema")
    elif label == "premarket_brief":
        instructions = data.get("premarket_instructions") or {}
        counts = data.get("counts") if isinstance(data.get("counts"), dict) else {}
        blockers = data.get("unresolved_blockers") or []
        stale = data.get("stale_warnings") or []
        blocker_count = int(counts.get("unresolved_blockers") or len(blockers))
        stale_count = int(counts.get("stale_warnings") or len(stale))
        summary.update(
            {
                "analysis_only": data.get("analysis_only"),
                "top_symbol": instructions.get("top_symbol"),
                "latest_hourly_decision": instructions.get("latest_hourly_decision"),
                "paper_tournament_leader": instructions.get("paper_tournament_leader"),
                "must_validate_fresh": list(instructions.get("must_validate_fresh") or [])[:8],
                "source_packet_count": int(
                    counts.get("source_packets") or len(data.get("source_packets") or [])
                ),
                "stale_warnings": stale_count,
                "blockers": blocker_count,
                "next_open": "Open full premarket packet only for blockers, stale warnings, top-symbol changes, or missing instructions.",
            }
        )
        if blocker_count:
            flag("blocker")
        if stale_count:
            flag("stale")
        if not instructions:
            flag("schema")
    elif label == "preopen_validation":
        status_counts = data.get("status_counts") if isinstance(data.get("status_counts"), dict) else {}
        account_summary = (
            data.get("account_summary")
            if isinstance(data.get("account_summary"), dict)
            else {}
        )
        live = (
            account_summary.get("live")
            if isinstance(account_summary.get("live"), dict)
            else {}
        )
        paper = (
            account_summary.get("paper")
            if isinstance(account_summary.get("paper"), dict)
            else {}
        )
        failed = [str(item) for item in data.get("failed_check_ids") or []]
        warned = [str(item) for item in data.get("warned_check_ids") or []]
        skipped = [str(item) for item in data.get("skipped_check_ids") or []]
        market_session = str(data.get("market_session") or "")
        non_tradeable_session = market_session not in {
            "pre_open",
            "open_window",
            "regular",
            "pre_close",
            "after_close",
        }
        closed_market_only_skip = (
            non_tradeable_session
            and set(skipped) <= {"premarket_quotes_and_spreads"}
        )
        fail_closed_only_warning = set(warned) <= {"live_sizing_room_and_buying_power"}
        deferred_for_closed_market = (
            not failed
            and bool(skipped)
            and closed_market_only_skip
            and fail_closed_only_warning
        )
        latest_overnight_generated_at = None
        latest_premarket_generated_at = None
        stale_after_latest_context = False
        if path_is_under(path, ROOT):
            preopen_generated_at = parse_packet_timestamp(data.get("generated_at"))
            latest_overnight_generated_at = latest_packet_generated_at(
                "results/overnight_plans/latest-compact.json"
            )
            latest_premarket_generated_at = latest_packet_generated_at(
                "results/premarket_briefs/latest-compact.json"
            )
            latest_context_times = [
                parsed
                for parsed in (
                    parse_packet_timestamp(latest_overnight_generated_at),
                    parse_packet_timestamp(latest_premarket_generated_at),
                )
                if parsed is not None
            ]
            stale_after_latest_context = (
                preopen_generated_at is not None
                and bool(latest_context_times)
                and preopen_generated_at < max(latest_context_times)
            )
        summary.update(
            {
                "analysis_only": data.get("analysis_only"),
                "can_submit_orders": data.get("can_submit_orders"),
                "execution_authority": data.get("execution_authority"),
                "overall_status": data.get("overall_status"),
                "market_session": market_session,
                "top_symbol": data.get("top_symbol"),
                "status_counts": dict(status_counts),
                "failed_check_ids": failed[:8],
                "warned_check_ids": warned[:8],
                "skipped_check_ids": skipped[:8],
                "deferred_for_closed_market": deferred_for_closed_market,
                "stale_after_latest_context": stale_after_latest_context,
                "latest_overnight_generated_at": latest_overnight_generated_at,
                "latest_premarket_generated_at": latest_premarket_generated_at,
                "fail_closed_live_control_warning_only": (
                    bool(warned) and fail_closed_only_warning
                ),
                "raw_packet_path": data.get("raw_packet_path"),
                "live_position_count": live.get("position_count"),
                "live_open_order_count": live.get("open_order_count"),
                "paper_position_count": paper.get("position_count"),
                "paper_open_order_count": paper.get("open_order_count"),
                "live_buying_power": live.get("buying_power"),
                "next_open": (
                    "Open full pre-open validation packet when any required check failed, "
                    "or when warnings/skips are not explained by a closed market plus "
                    "intentional fail-closed live control."
                ),
            }
        )
        if failed:
            flag("blocker")
        if stale_after_latest_context:
            flag("stale")
        if (warned or skipped) and not deferred_for_closed_market:
            flag("stale")
    elif label == "overnight_verification":
        is_compact_verification = (
            data.get("schema") == "compact_overnight_system_verification_v1"
        )
        checks = data.get("checks") or []
        failed = [
            c
            for c in checks
            if isinstance(c, dict) and c.get("status") not in {"pass", "ok"}
        ]
        failed_check_names = (
            [str(item) for item in data.get("failed_checks") or []]
            if is_compact_verification
            else [str(c.get("name")) for c in failed[:5] if c.get("name")]
        )
        warned_check_names = (
            [str(item) for item in data.get("warned_checks") or []]
            if is_compact_verification
            else [
                str(c.get("name"))
                for c in checks
                if isinstance(c, dict) and c.get("status") == "warn" and c.get("name")
            ][:5]
        )
        overnight = data.get("overnight") if isinstance(data.get("overnight"), dict) else {}
        freshness = data.get("freshness") if isinstance(data.get("freshness"), dict) else {}
        original_graph = (
            data.get("original_graph")
            if isinstance(data.get("original_graph"), dict)
            else {}
        )
        premarket_validation = (
            data.get("premarket_fresh_validation")
            if isinstance(data.get("premarket_fresh_validation"), dict)
            else {}
        )
        preopen = (
            data.get("simulated_preopen_validation")
            if isinstance(data.get("simulated_preopen_validation"), dict)
            else {}
        )
        summary.update(
            {
                "overall_status": data.get("overall_status"),
                "checks": int(
                    data.get("check_count")
                    if is_compact_verification
                    else len(checks)
                ),
                "failed_checks": failed_check_names[:8],
                "warned_checks": warned_check_names[:8],
                "raw_packet_path": data.get("raw_packet_path"),
                "top_symbol": overnight.get("top_symbol"),
                "ranked_count": overnight.get("ranked_count"),
                "graph_failure_count": overnight.get("graph_failure_count"),
                "completion_status": overnight.get("completion_status"),
                "stale": freshness.get("stale"),
                "freshness_deferred_for_calendar": freshness.get(
                    "freshness_deferred_for_calendar"
                ),
                "original_graph_status": original_graph.get("status"),
                "full_graph_success_count": original_graph.get(
                    "full_graph_success_count"
                ),
                "premarket_fresh_validation_status": premarket_validation.get(
                    "status"
                ),
                "premarket_compact_item_count": premarket_validation.get(
                    "compact_item_count"
                ),
                "simulated_preopen_status": preopen.get("status"),
                "simulated_preopen_skip_reason": preopen.get("skip_reason"),
                "next_open": "Open full verification packet when overall_status is not pass or failed_checks/warned_checks is non-empty.",
            }
        )
        if data.get("overall_status") != "pass" or failed_check_names or warned_check_names:
            flag("stale")
    elif label == "capability_audit":
        expected_present = data.get("env_present_count")
        missing_optional = data.get("missing_env_preview") or data.get("missing_optional_env_vars") or []
        if expected_present is None:
            env = data.get("env") or {}
            expected_present = 0
            missing_optional = []
            if isinstance(env, dict):
                for name, value in env.items():
                    if not isinstance(value, dict):
                        continue
                    scopes = value.get("scopes") if isinstance(value.get("scopes"), dict) else {}
                    process_present = bool((scopes.get("process") or {}).get("present"))
                    user_present = bool((scopes.get("user") or {}).get("present"))
                    machine_present = bool((scopes.get("machine") or {}).get("present"))
                    if bool(value.get("present")) or process_present or user_present or machine_present:
                        expected_present += 1
                    else:
                        missing_optional.append(name)
        if not isinstance(missing_optional, list):
            missing_optional = []
        composio = data.get("composio") or {}
        docker_mcp = data.get("docker_mcp") or {}
        summary.update(
            {
                "kind": data.get("kind"),
                "secrets_redacted": data.get("secrets_redacted"),
                "env_present_count": int(expected_present or 0),
                "missing_env_count": int(data.get("missing_env_count") or len(missing_optional)),
                "missing_env_preview": missing_optional[:8],
                "composio_configured": data.get("composio_configured", composio.get("configured")),
                "docker_mcp_configured": data.get(
                    "docker_mcp_configured", docker_mcp.get("configured")
                ),
                "raw_packet_path": data.get("raw_packet_path"),
                "integration_count": data.get("integration_count"),
                "can_submit_orders": data.get("can_submit_orders"),
                "execution_authority": data.get("execution_authority"),
                "next_open": "Open full capability audit if secrets_redacted is false, required keys are missing, or a connected-tool setup changed.",
            }
        )
        if data.get("secrets_redacted") is not True:
            flag("audit")
        composio_configured = data.get("composio_configured", composio.get("configured"))
        docker_configured = data.get("docker_mcp_configured", docker_mcp.get("configured"))
        if composio_configured is False or docker_configured is False:
            flag("audit")
    elif label == "research_batch":
        gates = data.get("quality_gates") or {}
        if "failed_quality_gates" in data or "advisory_missing_gates" in data:
            failed_gates = list(data.get("failed_quality_gates") or [])
            advisory_missing_gates = list(data.get("advisory_missing_gates") or [])
        else:
            raw_failed_gates = [
                key
                for key, value in gates.items()
                if isinstance(value, bool)
                and value is False
                and key != "fallback_required"
            ]
            if gates.get("fallback_required") is True:
                raw_failed_gates.append("fallback_required")
            advisory_missing_gates = []
            failed_gates = []
            for key in raw_failed_gates:
                if (
                    key == "at_least_one_local_worker_ready"
                    and gates.get("fallback_required") is False
                    and gates.get("research_quality_high_enough") is True
                ):
                    advisory_missing_gates.append(key)
                else:
                    failed_gates.append(key)
        summary.update(
            {
                "status": data.get("status"),
                "analysis_only": data.get("analysis_only"),
                "execution_authority": data.get("execution_authority"),
                "candidate_symbols": top_ranked_symbols(data.get("candidate_symbols") or [], 8),
                "lane_count": int(
                    data.get("lane_count")
                    if data.get("lane_count") is not None
                    else len(data.get("orchestration_lanes") or [])
                ),
                "source_packet_refs": int(
                    data.get("source_packet_ref_count")
                    if data.get("source_packet_ref_count") is not None
                    else len(data.get("source_packet_refs") or [])
                ),
                "model_telemetry_refs": int(
                    data.get("model_telemetry_ref_count")
                    if data.get("model_telemetry_ref_count") is not None
                    else len(data.get("model_telemetry_refs") or [])
                ),
                "crawler_packet_refs": int(
                    data.get("crawler_packet_ref_count")
                    if data.get("crawler_packet_ref_count") is not None
                    else len(data.get("crawler_packet_refs") or [])
                ),
                "fallback_actions": int(
                    data.get("fallback_action_count")
                    if data.get("fallback_action_count") is not None
                    else len(data.get("fallback_actions") or [])
                ),
                "raw_packet_path": data.get("raw_packet_path"),
                "can_submit_orders": data.get("can_submit_orders"),
                "failed_quality_gates": failed_gates[:8],
                "advisory_missing_gates": advisory_missing_gates[:8],
                "next_open": data.get(
                    "next_open",
                    "Open full research batch packet when status is not success, a quality gate failed, or fallback actions changed.",
                ),
            }
        )
        if data.get("status") != "success" or failed_gates:
            flag("quality")
    elif label == "market_mirror":
        summary.update(
            {
                "analysis_only": data.get("analysis_only"),
                "scenario_id": data.get("scenario_id"),
                "symbol": data.get("symbol"),
                "confidence": data.get("confidence"),
                "actor_profile_refs": len(data.get("actor_profile_refs") or []),
                "watch_items": len(data.get("watch_items") or []),
                "disagreements": len(data.get("disagreements") or []),
                "next_open": "Open full market-mirror packet when it involves an open position, top candidate, high disagreement, or low confidence.",
            }
        )
        if data.get("analysis_only") is not True:
            flag("schema")
        if data.get("confidence") == "low" or len(data.get("disagreements") or []) >= 3:
            flag("quality")
    elif label == "crawler_run":
        fetched = data.get("fetched_urls") or []
        blocked = data.get("blocked_urls") or []
        target = data.get("target") or {}
        target_url = target.get("url") if isinstance(target, dict) else str(target or "")
        summary.update(
            {
                "status": data.get("status"),
                "analysis_only": data.get("analysis_only"),
                "run_id": data.get("run_id"),
                "target_url": target_url,
                "crawler": data.get("crawler"),
                "fetched_count": len(fetched),
                "blocked_count": len(blocked),
                "max_pages": data.get("max_pages"),
                "robots_policy": data.get("robots_policy"),
                "next_open": "Open full crawler packet when status is not success, no page was fetched, or blocked URLs appear.",
            }
        )
        if data.get("status") != "success" or not fetched or blocked:
            flag("crawler")
    elif label == "model_telemetry_report":
        usefulness = data.get("usefulness_counts") or {}
        outcomes = data.get("outcome_counts") or {}
        harmful = int(usefulness.get("harmful") or 0) + int(outcomes.get("hurt") or 0)
        total_cost = data.get("estimated_cost_total_usd") or data.get("total_estimated_cost_usd")
        recent_errors = data.get("recent_errors") or []
        current_routes = [
            item
            for item in (data.get("current_route_statuses") or [])
            if isinstance(item, dict)
        ]
        selected_helper_routes = [
            {
                "route": item.get("route"),
                "model": item.get("model"),
                "status": item.get("status"),
            }
            for item in current_routes
            if item.get("status") in {"success", "fallback"}
            and str(item.get("route") or "") in {
                "mac_ollama_research_mule",
                "windows_local_ollama",
                "deterministic_packet_helpers",
                "codex_or_chatgpt_thread_judgment",
            }
        ]
        selected_local_helper_routes = [
            {
                "route": item.get("route"),
                "model": item.get("model"),
                "status": item.get("status"),
            }
            for item in current_routes
            if item.get("status") in {"success", "fallback", "selected"}
            and str(item.get("route") or "") in LOCAL_MODEL_HELPER_ROUTES
        ]
        blocked_route_summaries: list[dict[str, object]] = []
        for item in (data.get("blocked_route_summaries") or [])[:5]:
            if not isinstance(item, dict):
                continue
            blocked_summary = {
                key: item.get(key)
                for key in (
                    "route",
                    "provider",
                    "blocked_count",
                    "latest_error",
                    "error_kind",
                    "plain_english",
                )
                if item.get(key) is not None
            }
            actions = item.get("self_heal_actions")
            if isinstance(actions, list):
                blocked_summary["self_heal_actions"] = [
                    str(action) for action in actions[:5] if str(action).strip()
                ]
            blocked_route_summaries.append(blocked_summary)
        blocked_routes = [item.get("route") for item in blocked_route_summaries]
        blocked_local_helper_routes = sorted(
            {
                str(route)
                for route in [
                    *[
                        item.get("route")
                        for item in current_routes
                        if item.get("status") == "blocked"
                    ],
                    *blocked_routes,
                ]
                if str(route or "") in LOCAL_MODEL_HELPER_ROUTES
            }
        )
        advisory_route_names = [
            *[
                item.get("route")
                for item in recent_errors
                if isinstance(item, dict) and item.get("route")
            ],
            *blocked_routes,
        ]
        advisory_local_model_only = bool(advisory_route_names) and all(
            str(route) in ADVISORY_LOCAL_MODEL_ROUTES for route in advisory_route_names
        )
        hard_model_issue = bool(
            harmful
            or data.get("budget_remaining_usd") == 0
            or (recent_errors and not advisory_local_model_only)
        )
        local_helper_repair_signal = bool(blocked_local_helper_routes) and not selected_local_helper_routes
        summary.update(
            {
                "packet_count": data.get("packet_count"),
                "status_counts": data.get("status_counts"),
                "usefulness_counts": usefulness,
                "outcome_counts": outcomes,
                "resolved_model_run_count": data.get("resolved_model_run_count"),
                "estimated_cost_total_usd": total_cost,
                "budget_remaining_usd": data.get("budget_remaining_usd"),
                "average_quality_score": data.get("average_quality_score"),
                "recent_errors": len(recent_errors),
                "hard_model_issue": hard_model_issue,
                "advisory_local_model_only": advisory_local_model_only,
                "operator_summary": data.get("operator_summary"),
                "current_route_statuses": current_routes[:6],
                "selected_helper_routes": selected_helper_routes[:6],
                "selected_local_helper_routes": selected_local_helper_routes[:6],
                "blocked_local_helper_routes": blocked_local_helper_routes[:6],
                "local_helper_repair_signal": local_helper_repair_signal,
                "blocked_route_count": len(data.get("blocked_route_summaries") or []),
                "blocked_routes": blocked_routes,
                "blocked_route_summaries": blocked_route_summaries,
                "next_open": "Open full model telemetry when harmful/hurt counts, high spend, budget exhaustion, all local helper routes are down, or unresolved errors appear.",
            }
        )
        if hard_model_issue or local_helper_repair_signal:
            flag("model_telemetry")
    elif label == "source_quality_review":
        stale_count = int(data.get("stale_count") or 0)
        missing_count = int(data.get("missing_or_invalid_count") or 0)
        unreadable_count = int(data.get("unreadable_count") or 0)
        stale_downrank_count = data.get("stale_downrank_count")
        stale_low_or_unknown_count = data.get("stale_low_or_unknown_count")
        stale_safe_count = data.get("stale_safe_count")
        stale_needs_refresh_count = data.get("stale_needs_refresh_count")
        if (
            stale_downrank_count is None
            or stale_low_or_unknown_count is None
            or stale_safe_count is None
            or stale_needs_refresh_count is None
        ):
            decisions = data.get("decisions") or []
            stale_downrank_count = sum(
                1
                for decision in decisions
                if isinstance(decision, dict)
                and decision.get("freshness_status") == "stale"
                and "downrank" in (decision.get("allowed_effects") or [])
            )
            stale_low_or_unknown_count = sum(
                1
                for decision in decisions
                if isinstance(decision, dict)
                and decision.get("freshness_status") == "stale"
                and str(decision.get("quality") or "").lower() in {"low", "unknown"}
            )
            stale_safe_count = sum(
                1
                for decision in decisions
                if isinstance(decision, dict)
                and decision.get("freshness_status") == "stale"
                and (
                    "downrank" in (decision.get("allowed_effects") or [])
                    or str(decision.get("quality") or "").lower() in {"low", "unknown"}
                )
            )
            stale_needs_refresh_count = max(stale_count - stale_safe_count, 0)
        stale_downrank_count = int(stale_downrank_count or 0)
        stale_low_or_unknown_count = int(stale_low_or_unknown_count or 0)
        stale_safe_count = int(stale_safe_count or 0)
        stale_needs_refresh_count = int(stale_needs_refresh_count or 0)
        summary.update(
            {
                "analysis_only": data.get("analysis_only"),
                "can_submit_orders": data.get("can_submit_orders"),
                "execution_authority": data.get("execution_authority"),
                "source_count": data.get("source_count"),
                "stale_count": stale_count,
                "stale_downrank_count": stale_downrank_count,
                "stale_low_or_unknown_count": stale_low_or_unknown_count,
                "stale_safe_count": stale_safe_count,
                "stale_needs_refresh_count": stale_needs_refresh_count,
                "missing_or_invalid_count": missing_count,
                "unreadable_count": unreadable_count,
                "quality_counts": data.get("quality_counts") or {},
                "freshness_counts": data.get("freshness_counts") or {},
                "next_open": "Open full source-quality packet when stale sources are not downranked, missing/invalid, or unreadable sources appear.",
            }
        )
        if data.get("analysis_only") is not True or data.get("can_submit_orders") is not False:
            flag("schema")
        if stale_needs_refresh_count or missing_count or unreadable_count:
            flag("quality")
    elif label == "n8n_evaluation_dataset":
        required_actual_columns = {
            "actual_http_status",
            "actual_status",
            "actual_json",
            "actual_quality_score",
            "actual_checked_at",
            "actual_error",
        }
        column_names = {
            str(column.get("name"))
            for column in data.get("columns") or []
            if isinstance(column, dict)
        }
        if not column_names and isinstance(data.get("column_names"), list):
            column_names = {str(name) for name in data.get("column_names") or []}
        has_actual_output_columns = required_actual_columns <= column_names
        sync_path = path.parent / "latest-sync.json"
        sync_data = read_json(sync_path) if sync_path.exists() else None
        sync_status = sync_data.get("status") if isinstance(sync_data, dict) else None
        sync_row_count_matches = (
            sync_data.get("row_count_matches") if isinstance(sync_data, dict) else None
        )
        current_row_count = int(data.get("row_count") or 0)
        sync_final_row_count = (
            sync_data.get("final_row_count") if isinstance(sync_data, dict) else None
        )
        sync_expected_row_count = (
            sync_data.get("expected_row_count") if isinstance(sync_data, dict) else None
        )
        sync_dataset_generated_at = (
            sync_data.get("dataset_generated_at") if isinstance(sync_data, dict) else None
        )
        sync_current_row_count_matches = (
            sync_final_row_count == current_row_count
            and sync_expected_row_count == current_row_count
            if isinstance(sync_data, dict)
            else None
        )
        sync_current_dataset_generated_at_matches = (
            sync_dataset_generated_at == data.get("generated_at")
            if isinstance(sync_data, dict)
            else None
        )
        sync_api_key_redacted = (
            sync_data.get("api_key_redacted") if isinstance(sync_data, dict) else None
        )
        workflow_sync_path = path.parent / "latest-workflow-sync.json"
        workflow_sync_data = (
            read_json(workflow_sync_path) if workflow_sync_path.exists() else None
        )
        workflow_sync_status = (
            workflow_sync_data.get("status") if isinstance(workflow_sync_data, dict) else None
        )
        workflow_sync_api_key_redacted = (
            workflow_sync_data.get("api_key_redacted")
            if isinstance(workflow_sync_data, dict)
            else None
        )
        workflow_sync_created_workflow_names = (
            [
                str(item.get("name"))
                for item in workflow_sync_data.get("created_workflows") or []
                if isinstance(item, dict) and item.get("name")
            ]
            if isinstance(workflow_sync_data, dict)
            else []
        )
        workflow_sync_existing_workflow_names = (
            [
                str(item.get("name"))
                for item in workflow_sync_data.get("existing_workflows") or []
                if isinstance(item, dict) and item.get("name")
            ]
            if isinstance(workflow_sync_data, dict)
            else []
        )
        workflow_sync_would_create_workflow_names = (
            [
                str(item.get("name"))
                for item in workflow_sync_data.get("would_create_workflows") or []
                if isinstance(item, dict) and item.get("name")
            ]
            if isinstance(workflow_sync_data, dict)
            else []
        )
        workflow_sync_updated_workflow_names = (
            [
                str(item.get("name"))
                for item in workflow_sync_data.get("updated_workflows") or []
                if isinstance(item, dict) and item.get("name")
            ]
            if isinstance(workflow_sync_data, dict)
            else []
        )
        workflow_sync_would_update_workflow_names = (
            [
                str(item.get("name"))
                for item in workflow_sync_data.get("would_update_workflows") or []
                if isinstance(item, dict) and item.get("name")
            ]
            if isinstance(workflow_sync_data, dict)
            else []
        )
        workflow_sync_source_workflow_names = (
            list(workflow_sync_data.get("source_workflow_names") or [])
            if isinstance(workflow_sync_data, dict)
            else []
        )
        run_probe_path = path.parent / "latest-run-probe.json"
        run_probe_data = (
            read_json(run_probe_path) if run_probe_path.exists() else None
        )
        run_probe_status = (
            run_probe_data.get("status") if isinstance(run_probe_data, dict) else None
        )
        run_probe_api_key_redacted = (
            run_probe_data.get("api_key_redacted")
            if isinstance(run_probe_data, dict)
            else None
        )
        run_probe_acceptance = (
            run_probe_data.get("acceptance")
            if (
                isinstance(run_probe_data, dict)
                and isinstance(run_probe_data.get("acceptance"), dict)
            )
            else {}
        )
        run_probe_acceptance_accepted = run_probe_acceptance.get("accepted")
        summary.update(
            {
                "analysis_only": data.get("analysis_only"),
                "can_submit_orders": data.get("can_submit_orders"),
                "execution_authority": data.get("execution_authority"),
                "row_count": current_row_count,
                "column_count": int(data.get("column_count") or 0),
                "allowlisted_job_count": int(data.get("allowlisted_job_count") or 0),
                "edge_tag_count": int(data.get("edge_tag_count") or 0),
                "edge_tags": list(data.get("edge_tags") or [])[:20],
                "data_table_name": data.get("data_table_name"),
                "json_path": data.get("json_path"),
                "csv_path": data.get("csv_path"),
                "markdown_path": data.get("markdown_path"),
                "native_workflow_name": "TA · Built-in Automation Evaluation",
                "has_actual_output_columns": has_actual_output_columns,
                "actual_output_columns": sorted(required_actual_columns),
                "sync_path": rel(sync_path) if sync_path.exists() else None,
                "sync_status": sync_status,
                "sync_row_count_matches": sync_row_count_matches,
                "sync_current_row_count_matches": sync_current_row_count_matches,
                "sync_current_dataset_generated_at_matches": (
                    sync_current_dataset_generated_at_matches
                ),
                "sync_dataset_generated_at": sync_dataset_generated_at,
                "sync_final_row_count": sync_final_row_count,
                "sync_expected_row_count": sync_expected_row_count,
                "sync_column_count": (
                    sync_data.get("column_count") if isinstance(sync_data, dict) else None
                ),
                "sync_api_key_redacted": sync_api_key_redacted,
                "sync_missing_columns_added": (
                    list(sync_data.get("missing_columns_added") or [])
                    if isinstance(sync_data, dict)
                    else []
                ),
                "workflow_sync_path": (
                    rel(workflow_sync_path) if workflow_sync_path.exists() else None
                ),
                "workflow_sync_status": workflow_sync_status,
                "workflow_sync_source_workflow_count": (
                    workflow_sync_data.get("source_workflow_count")
                    if isinstance(workflow_sync_data, dict)
                    else None
                ),
                "workflow_sync_existing_count": (
                    workflow_sync_data.get("existing_count")
                    if isinstance(workflow_sync_data, dict)
                    else None
                ),
                "workflow_sync_created_count": (
                    workflow_sync_data.get("created_count")
                    if isinstance(workflow_sync_data, dict)
                    else None
                ),
                "workflow_sync_updated_count": (
                    workflow_sync_data.get("updated_count")
                    if isinstance(workflow_sync_data, dict)
                    else None
                ),
                "workflow_sync_would_create_count": (
                    workflow_sync_data.get("would_create_count")
                    if isinstance(workflow_sync_data, dict)
                    else None
                ),
                "workflow_sync_would_update_count": (
                    workflow_sync_data.get("would_update_count")
                    if isinstance(workflow_sync_data, dict)
                    else None
                ),
                "workflow_sync_duplicate_name_counts": (
                    dict(workflow_sync_data.get("duplicate_name_counts") or {})
                    if isinstance(workflow_sync_data, dict)
                    else {}
                ),
                "workflow_sync_archived_duplicate_name_counts": (
                    dict(workflow_sync_data.get("archived_duplicate_name_counts") or {})
                    if isinstance(workflow_sync_data, dict)
                    else {}
                ),
                "workflow_sync_api_key_redacted": workflow_sync_api_key_redacted,
                "workflow_sync_source_workflow_names": workflow_sync_source_workflow_names[:20],
                "workflow_sync_created_workflow_names": (
                    workflow_sync_created_workflow_names[:20]
                ),
                "workflow_sync_updated_workflow_names": (
                    workflow_sync_updated_workflow_names[:20]
                ),
                "workflow_sync_existing_workflow_names": (
                    workflow_sync_existing_workflow_names[:20]
                ),
                "workflow_sync_would_create_workflow_names": (
                    workflow_sync_would_create_workflow_names[:20]
                ),
                "workflow_sync_would_update_workflow_names": (
                    workflow_sync_would_update_workflow_names[:20]
                ),
                "run_probe_path": rel(run_probe_path) if run_probe_path.exists() else None,
                "run_probe_status": run_probe_status,
                "run_probe_workflow_found": (
                    run_probe_data.get("workflow_found")
                    if isinstance(run_probe_data, dict)
                    else None
                ),
                "run_probe_workflow_id": (
                    run_probe_data.get("workflow_id")
                    if isinstance(run_probe_data, dict)
                    else None
                ),
                "run_probe_editor_required": (
                    run_probe_data.get("editor_run_required")
                    if isinstance(run_probe_data, dict)
                    else None
                ),
                "run_probe_supported_endpoint_count": (
                    run_probe_data.get("supported_endpoint_count")
                    if isinstance(run_probe_data, dict)
                    else None
                ),
                "run_probe_probe_count": (
                    run_probe_data.get("probe_count")
                    if isinstance(run_probe_data, dict)
                    else None
                ),
                "run_probe_api_key_redacted": run_probe_api_key_redacted,
                "run_probe_accepted_as_current_gate": (
                    run_probe_data.get("accepted_as_current_gate")
                    if isinstance(run_probe_data, dict)
                    else None
                ),
                "run_probe_acceptance_accepted": run_probe_acceptance_accepted,
                "run_probe_sanctioned_run_surface": (
                    run_probe_data.get("sanctioned_run_surface")
                    if isinstance(run_probe_data, dict)
                    else None
                ),
                "run_probe_acceptance_reason": (
                    run_probe_data.get("acceptance_reason")
                    if isinstance(run_probe_data, dict)
                    else None
                ),
                "next_open": "Open n8n evaluation packets when actual-output columns are missing, Data Table/workflow sync proof is missing, stale, blocked, row counts or dataset identity mismatch, an API key is not redacted, or the native run probe reports a broken workflow.",
            }
        )
        if (
            data.get("analysis_only") is not True
            or data.get("can_submit_orders") is not False
            or data.get("execution_authority") != "none"
            or not has_actual_output_columns
        ):
            flag("schema")
        if not isinstance(sync_data, dict) or sync_status != "ok":
            flag("audit")
        if (
            sync_row_count_matches is False
            or sync_current_row_count_matches is not True
            or sync_current_dataset_generated_at_matches is not True
            or sync_api_key_redacted is not True
        ):
            flag("audit")
        if (
            not isinstance(workflow_sync_data, dict)
            or workflow_sync_status not in {"ok", "dry_run"}
            or workflow_sync_api_key_redacted is not True
            or workflow_sync_data.get("analysis_only") is not True
            or workflow_sync_data.get("can_submit_orders") is not False
            or workflow_sync_data.get("execution_authority") != "none"
            or bool(workflow_sync_data.get("duplicate_name_counts"))
        ):
            flag("audit")
        if isinstance(run_probe_data, dict) and (
            run_probe_status not in {"editor_required", "api_trigger_available"}
            or run_probe_api_key_redacted is not True
            or run_probe_data.get("analysis_only") is not True
            or run_probe_data.get("can_submit_orders") is not False
            or run_probe_data.get("execution_authority") != "none"
        ):
            flag("audit")
    elif label == "overnight_calibration_guard":
        is_compact_calibration = (
            data.get("schema") == "compact_overnight_calibration_guard_v1"
        )
        metric_summary = (
            data.get("metric_summary") if isinstance(data.get("metric_summary"), dict) else {}
        )
        baseline = (
            metric_summary.get("deterministic_sleeve_only")
            if isinstance(metric_summary.get("deterministic_sleeve_only"), dict)
            else {}
        )
        advisory = (
            metric_summary.get("tradingagents_advisory_overlay")
            if isinstance(metric_summary.get("tradingagents_advisory_overlay"), dict)
            else {}
        )
        red_flags = [str(item) for item in data.get("red_flags") or []]
        live_influence_policy = (
            data.get("live_influence_policy")
            if isinstance(data.get("live_influence_policy"), dict)
            else {}
        )
        entry_validation_requirements = [
            item
            for item in data.get("entry_validation_requirements") or []
            if isinstance(item, dict)
        ]
        if is_compact_calibration:
            entry_validation_requirement_ids = [
                str(item) for item in data.get("entry_validation_requirement_ids") or []
            ][:8]
            required_entry_validation_ids = [
                str(item) for item in data.get("required_entry_validation_ids") or []
            ][:8]
        else:
            entry_validation_requirement_ids = [
                str(item.get("id"))
                for item in entry_validation_requirements[:8]
                if item.get("id")
            ]
            required_entry_validation_ids = [
                str(item.get("id"))
                for item in entry_validation_requirements
                if item.get("id") and item.get("required") is True
            ][:8]
        summary.update(
            {
                "status": data.get("status"),
                "analysis_only": data.get("analysis_only"),
                "can_submit_orders": data.get("can_submit_orders"),
                "execution_authority": data.get("execution_authority"),
                "guard_decision": data.get("guard_decision"),
                "can_increase_live_influence": data.get("can_increase_live_influence"),
                "red_flags": red_flags[:12],
                "live_influence_policy": {
                    key: live_influence_policy.get(key)
                    for key in (
                        "mode",
                        "live_influence_action",
                        "new_buy_permission",
                        "replacement_buy_permission",
                        "sell_permission",
                    )
                    if live_influence_policy.get(key) is not None
                },
                "entry_validation_requirement_ids": entry_validation_requirement_ids,
                "required_entry_validation_ids": required_entry_validation_ids,
                "promotion_blockers": [
                    str(item) for item in data.get("promotion_blockers") or []
                ][:8],
                "paper_exploration_policy": data.get("paper_exploration_policy"),
                "sample_floor_met": data.get("sample_floor_met"),
                "selected_packet_count": data.get("selected_packet_count"),
                "returns_row_count": data.get("returns_row_count"),
                "fixture_row_count": data.get("fixture_row_count"),
                "cohort_summary_path": data.get("cohort_summary_path"),
                "replay_packet_path": data.get("replay_packet_path"),
                "baseline_action_relative_return": data.get(
                    "baseline_action_relative_return"
                )
                if is_compact_calibration
                else baseline.get("average_action_relative_return"),
                "baseline_false_positive_rate": data.get("baseline_false_positive_rate")
                if is_compact_calibration
                else baseline.get("false_positive_rate"),
                "tradingagents_action_relative_return": data.get(
                    "tradingagents_action_relative_return"
                )
                if is_compact_calibration
                else advisory.get(
                    "average_action_relative_return"
                ),
                "tradingagents_false_positive_rate": data.get(
                    "tradingagents_false_positive_rate"
                )
                if is_compact_calibration
                else advisory.get("false_positive_rate"),
                "recommended_guardrails": list(data.get("recommended_guardrails") or [])[:6],
                "next_action": data.get("next_action"),
                "next_open": "Open overnight calibration guard when status is blocked, schema is unsafe, or the guard decision changes before promotion.",
            }
        )
        if (
            data.get("analysis_only") is not True
            or data.get("can_submit_orders") is not False
            or data.get("execution_authority") != "none"
        ):
            flag("schema")
        if data.get("status") != "ok":
            flag("quality")
    elif label == "automation_health_audit":
        is_compact_health = data.get("schema") == "compact_automation_health_audit_v1"
        packet_summary = data.get("summary") if isinstance(data.get("summary"), dict) else {}
        automation_rows = [item for item in data.get("automations") or [] if isinstance(item, dict)]
        submitted_count = int(data.get("submitted_order_count") or 0)
        issue_count = int(data.get("issue_count") or 0)
        missing_count = int(
            (data.get("missing_count") if is_compact_health else packet_summary.get("missing_count")) or 0
        )
        partial_count = int(
            (data.get("partial_count") if is_compact_health else packet_summary.get("partial_count")) or 0
        )
        late_count = int(
            (data.get("late_count") if is_compact_health else packet_summary.get("late_count")) or 0
        )
        duplicate_count = int(
            (data.get("duplicate_count") if is_compact_health else packet_summary.get("duplicate_count")) or 0
        )
        stale_count = int(
            (data.get("stale_count") if is_compact_health else packet_summary.get("stale_count")) or 0
        )
        warning_count = int(
            (data.get("warning_count") if is_compact_health else packet_summary.get("warning_count")) or 0
        )
        row_timeliness_issue_count = sum(
            1
            for item in automation_rows
            if "self_heal_plan_late" in (item.get("issue_types") or [])
        )
        timeliness_issue_count = max(
            int(
                (
                    data.get("timeliness_issue_count")
                    if is_compact_health
                    else packet_summary.get("timeliness_issue_count")
                )
                or 0
            ),
            row_timeliness_issue_count,
        )
        if is_compact_health:
            benign_partial_ids = [str(item) for item in data.get("benign_partial_automation_ids") or []]
            actionable_partial_count = int(data.get("actionable_partial_count") or 0)
            problem_ids = [str(item) for item in data.get("problem_automation_ids") or []]
        else:
            benign_partial_ids = [
                str(item.get("automation_id"))
                for item in automation_rows
                if item.get("automation_id") == "tradingagents-night-shift-supervisor"
                and item.get("status") == "partial"
                and str(item.get("status_reason") or "").startswith(
                    "observed_runs_less_than_expected:"
                )
                and (observed_less_than_expected_gap(item.get("status_reason")) or 0) <= 1
                and int(item.get("actual_artifact_count") or 0) > 0
                and not {
                    "stale_memory",
                    "late_run",
                    "duplicate_run",
                    "night_shift_cadence_mismatch",
                    "self_heal_plan_late",
                }.intersection(set(item.get("issue_types") or []))
            ]
            actionable_partial_count = max(partial_count - len(benign_partial_ids), 0)
            problem_ids = [
                str(item.get("automation_id"))
                for item in automation_rows
                if str(item.get("automation_id")) not in benign_partial_ids
                and (
                    item.get("status") not in {"ok", None}
                or "self_heal_plan_late" in (item.get("issue_types") or [])
                )
            ]
        summary.update(
            {
                "analysis_only": data.get("analysis_only"),
                "can_submit_orders": data.get("can_submit_orders"),
                "raw_packet_path": data.get("raw_packet_path"),
                "automation_count": data.get("automation_count"),
                "submitted_order_count": submitted_count,
                "issue_count": issue_count,
                "missing_count": missing_count,
                "partial_count": partial_count,
                "actionable_partial_count": actionable_partial_count,
                "benign_partial_automation_ids": benign_partial_ids[:8],
                "late_count": late_count,
                "duplicate_count": duplicate_count,
                "stale_count": stale_count,
                "warning_count": warning_count,
                "timeliness_issue_count": timeliness_issue_count,
                "problem_automation_ids": problem_ids[:8],
                "next_open": "Open automation health when a managed automation has actionable partial/missing/late/duplicate/stale/warning status or self-heal follow-up missed its SLA.",
            }
        )
        if data.get("analysis_only") is not True or data.get("can_submit_orders") is not False:
            flag("schema")
        if submitted_count:
            flag("submitted")
        if (
            missing_count
            or actionable_partial_count
            or late_count
            or duplicate_count
            or stale_count
            or warning_count
            or timeliness_issue_count
            or issue_count
        ):
            flag("automation_health")
    elif label == "self_heal_handoff":
        should_start = bool(data.get("should_start_new_chat"))
        summary.update(
            {
                "analysis_only": data.get("analysis_only"),
                "can_submit_orders": data.get("can_submit_orders"),
                "execution_authority": data.get("execution_authority"),
                "should_start_new_chat": should_start,
                "trigger_count": data.get("trigger_count"),
                "max_severity": data.get("max_severity"),
                "start_condition": data.get("start_condition"),
                "prompt_path": data.get("prompt_path"),
                "next_open": "Open self-heal handoff when it says a new chat should start or trigger severity is medium/high.",
            }
        )
        if data.get("analysis_only") is not True or data.get("can_submit_orders") is not False:
            flag("schema")
        if should_start:
            flag("issues")
    elif label == "self_heal_plan":
        active_plan_count = int(data.get("active_plan_count") or 0)
        escalation_count = int(data.get("escalation_count") or 0)
        max_severity = str(data.get("max_severity") or "info").lower()
        high_severity_escalation = max_severity in {"medium", "high", "critical"}
        signals = [item for item in data.get("signals") or [] if isinstance(item, dict)]
        escalated_labels = [
            str(item.get("label"))
            for item in signals
            if item.get("status") == "escalated" and item.get("label")
        ]
        covered_escalated_labels = [
            str(item.get("label"))
            for item in signals
            if item.get("status") == "escalated"
            and item.get("classification") == "escalate_order_adjacent"
            and item.get("reason") == "board_review"
            and item.get("label") in {"hourly", "execution_board_review"}
        ]
        actionable_escalation_count = max(
            escalation_count - len(set(covered_escalated_labels)),
            0,
        )
        safe_recorded_labels = [
            str(item.get("label"))
            for item in signals
            if item.get("status") in {"already_recorded", "planned", "verified"}
            and item.get("label")
        ]
        summary.update(
            {
                "analysis_only": data.get("analysis_only"),
                "can_submit_orders": data.get("can_submit_orders"),
                "execution_authority": data.get("execution_authority"),
                "status": data.get("status"),
                "signal_count": data.get("signal_count"),
                "active_plan_count": active_plan_count,
                "escalation_count": escalation_count,
                "actionable_escalation_count": actionable_escalation_count,
                "deduped_prior_count": data.get("deduped_prior_count"),
                "max_severity": data.get("max_severity"),
                "executed_count": data.get("executed_count"),
                "verified_count": data.get("verified_count"),
                "verify_failed_count": data.get("verify_failed_count"),
                "self_heal_signal_labels": [
                    str(item.get("label")) for item in signals[:5] if item.get("label")
                ],
                "self_heal_signal_reasons": [
                    str(item.get("reason")) for item in signals[:5] if item.get("reason")
                ],
                "self_heal_signal_classifications": [
                    str(item.get("classification"))
                    for item in signals[:5]
                    if item.get("classification")
                ],
                "self_heal_escalated_labels": escalated_labels[:5],
                "self_heal_covered_escalated_labels": covered_escalated_labels[:5],
                "self_heal_safe_recorded_labels": safe_recorded_labels[:5],
                "next_open": "Open self-heal plan when safe plans are active, actionable escalations are present, verification fails, or the packet violates analysis-only boundaries.",
            }
        )
        if data.get("analysis_only") is not True or data.get("can_submit_orders") is not False:
            flag("schema")
        if active_plan_count or (actionable_escalation_count and high_severity_escalation):
            flag("issues")
    elif label == "execution_board_review":
        metrics = data.get("metrics") or {}
        violations = data.get("violations") or []
        warnings = data.get("warnings") or []
        recommendation = data.get("recommendation")
        new_buy_policy = data.get("new_buy_policy") or {}
        next_hour_policy = data.get("next_hour_policy") or {}
        violation_types = {
            item.get("type")
            for item in violations
            if isinstance(item, dict) and item.get("type")
        }
        warning_types = {
            item.get("type")
            for item in warnings
            if isinstance(item, dict) and item.get("type")
        }
        packet_reviews = data.get("packet_reviews") or []
        latest_packet_review = (
            packet_reviews[-1]
            if packet_reviews and isinstance(packet_reviews[-1], dict)
            else {}
        )
        latest_packet_decision = latest_packet_review.get("decision")
        latest_packet_needs_review = latest_packet_decision == "loss-review"
        board_latest_reviewed_packet_path = latest_packet_review.get("packet")
        latest_hourly_path = latest_packet_path_for_label("hourly")
        latest_hourly_packet_path = rel(latest_hourly_path) if latest_hourly_path else None
        latest_hourly_raw_packet_path = latest_raw_packet_ref_for_label("hourly")
        board_matches_latest_hourly = (
            normalized_packet_ref(board_latest_reviewed_packet_path)
            == normalized_packet_ref(latest_hourly_raw_packet_path)
            if board_latest_reviewed_packet_path and latest_hourly_raw_packet_path
            else None
        )
        new_buy_state = new_buy_policy.get("state")
        clean_packets = new_buy_policy.get("clean_packets_since_last_violation")
        required_clean_packets = new_buy_policy.get("required_clean_packets")
        try:
            clean_packets_int = int(clean_packets or 0)
            required_clean_packets_int = int(required_clean_packets or 0)
        except (TypeError, ValueError):
            clean_packets_int = 0
            required_clean_packets_int = 0
        historical_lessons_only = (
            recommendation == "continue_with_guardrails_after_clean_streak"
            and new_buy_state == "probation_allowed"
        )
        caution_guardrails_only = (
            recommendation == "review_underperformers_before_new_buys"
            and new_buy_state == "caution"
            and not violations
            and warning_types.issubset({"negative_live_unrealized_pl"})
            and not latest_packet_needs_review
            and clean_packets_int >= max(required_clean_packets_int, 1)
        )
        board_hard_issue = bool(
            new_buy_state == "paused"
            or recommendation
            in {
                "pause_new_buys_and_review",
            }
            or "unsafe_order_status" in violation_types
        )
        summary.update(
            {
                "recommendation": recommendation,
                "new_buy_state": new_buy_state,
                "clean_packets_since_last_violation": new_buy_policy.get(
                    "clean_packets_since_last_violation"
                ),
                "required_clean_packets": required_clean_packets,
                "new_buy_policy_plain_english": new_buy_policy.get("plain_english"),
                "historical_lessons_only": historical_lessons_only,
                "caution_guardrails_only": caution_guardrails_only,
                "board_hard_issue": board_hard_issue,
                "board_latest_reviewed_packet_path": board_latest_reviewed_packet_path,
                "latest_hourly_packet_path": latest_hourly_packet_path,
                "latest_hourly_raw_packet_path": latest_hourly_raw_packet_path,
                "board_matches_latest_hourly": board_matches_latest_hourly,
                "latest_packet_decision": latest_packet_decision,
                "latest_packet_needs_review": latest_packet_needs_review,
                "analysis_only": data.get("analysis_only"),
                "can_submit_orders": data.get("can_submit_orders"),
                "packet_count": metrics.get("packet_count"),
                "submitted_order_count": metrics.get("submitted_order_count"),
                "live_buy_count": metrics.get("live_buy_count"),
                "live_sell_count": metrics.get("live_sell_count"),
                "profit_sell_count": metrics.get("profit_sell_count"),
                "loss_exit_count": metrics.get("loss_exit_count"),
                "negative_live_pl_packets": metrics.get("negative_live_pl_packets"),
                "violation_count": len(violations),
                "violation_types": sorted(str(item) for item in violation_types),
                "warning_count": len(warnings),
                "warning_types": sorted(str(item) for item in warning_types),
                "next_hour_buy_side": next_hour_policy.get("buy_side"),
                "next_hour_sell_side": next_hour_policy.get("sell_side"),
                "next_open": "Open full BOARD review when new buys are actively paused, unsafe order statuses appear, or underperformers need fresh review.",
            }
        )
        if board_matches_latest_hourly is False:
            flag("stale")
        if latest_packet_needs_review or board_hard_issue or (
            (violations or warnings)
            and not historical_lessons_only
            and not caution_guardrails_only
            and recommendation not in {"continue_with_guardrails", "no_action_needed", None}
        ):
            flag("board_review")
    elif label == "loss_review_evidence":
        payload = data.get("payload") if isinstance(data.get("payload"), dict) else {}
        freshness = data.get("freshness") if isinstance(data.get("freshness"), dict) else {}
        source_ids = payload.get("source_packet_ids") or []
        blockers = payload.get("remaining_blockers") or []
        blockers_before_refresh = payload.get("remaining_blockers_before_refresh") or []
        resolved_blockers = payload.get("resolved_blockers_by_refresh") or []
        evidence_hourly_packet_path = payload.get("hourly_packet_path")
        latest_hourly_path = latest_packet_path_for_label("hourly")
        latest_hourly_packet_path = rel(latest_hourly_path) if latest_hourly_path else None
        latest_hourly_raw_packet_path = latest_raw_packet_ref_for_label("hourly")
        evidence_matches_latest_hourly = (
            normalized_packet_ref(evidence_hourly_packet_path)
            == normalized_packet_ref(latest_hourly_raw_packet_path)
            if evidence_hourly_packet_path and latest_hourly_raw_packet_path
            else None
        )
        summary.update(
            {
                "analysis_only": data.get("analysis_only"),
                "can_submit_orders": freshness.get("can_submit_orders"),
                "execution_authority": payload.get("execution_authority"),
                "symbol": payload.get("symbol") or data.get("symbol"),
                "hourly_packet_path": evidence_hourly_packet_path,
                "latest_hourly_packet_path": latest_hourly_packet_path,
                "latest_hourly_raw_packet_path": latest_hourly_raw_packet_path,
                "evidence_matches_latest_hourly": evidence_matches_latest_hourly,
                "hourly_decision": payload.get("hourly_decision"),
                "review_allowed": payload.get("review_allowed"),
                "source_packet_count": len(source_ids),
                "evidence_needs": payload.get("evidence_needs") or [],
                "evidence_coverage_by_need": payload.get("evidence_coverage_by_need") or {},
                "remaining_blockers_before_refresh_count": len(blockers_before_refresh),
                "resolved_blocker_count": len(resolved_blockers),
                "resolved_blockers_by_refresh": resolved_blockers,
                "remaining_blocker_count": len(blockers),
                "next_action": payload.get("next_action"),
                "next_open": "Open loss-review evidence when BOARD/manual review is deciding whether HOLD or a loss exit has better expected value.",
            }
        )
        if data.get("analysis_only") is not True or freshness.get("can_submit_orders") is not False:
            flag("schema")
        if evidence_matches_latest_hourly is False:
            flag("stale")
        next_action = str(payload.get("next_action") or "")
        if next_action.startswith("manual_board_review"):
            flag("board_review")
    elif label == "mirofish_handoff_status":
        freshness = data.get("freshness") or {}
        clean_room = freshness.get("clean_room") if isinstance(freshness.get("clean_room"), dict) else {}
        status = freshness.get("mirofish_status")
        execution_authority = freshness.get("execution_authority")
        summary.update(
            {
                "analysis_only": data.get("analysis_only"),
                "subject": data.get("subject"),
                "status": status,
                "final_handoff_available": freshness.get("final_handoff_available"),
                "required_report_id": freshness.get("required_report_id"),
                "execution_authority": execution_authority,
                "can_submit_orders": freshness.get("can_submit_orders"),
                "allowed_use": freshness.get("allowed_use"),
                "prohibited_use": freshness.get("prohibited_use"),
                "artifact_path_count": freshness.get("artifact_path_count"),
                "candidate_artifact_count": freshness.get("candidate_artifact_count"),
                "available_artifact_count": freshness.get("available_artifact_count"),
                "final_handoff_paths": freshness.get("final_handoff_paths") or [],
                "advisory_valid_window": freshness.get("advisory_valid_window"),
                "advisory_expires_after": freshness.get("advisory_expires_after"),
                "advisory_requires_refresh": freshness.get("advisory_requires_refresh") or [],
                "ignored_handoff_count": freshness.get("ignored_handoff_count"),
                "final_advisory_available": freshness.get("final_advisory_available"),
                "scenario_branch_count": freshness.get("scenario_branch_count", 0),
                "validation_task_count": freshness.get("validation_task_count", 0),
                "false_signal_filter_count": freshness.get("false_signal_filter_count", 0),
                "attention_symbols": freshness.get("attention_symbols", []),
                "forecast_symbols": freshness.get("forecast_symbols", []),
                "source_artifacts": freshness.get("source_artifacts") or {},
                "review_packet_zip": freshness.get("review_packet_zip"),
                "acceptance_decision_path": freshness.get("acceptance_decision_path"),
                "full_report_highlight_available": freshness.get("full_report_highlight_available"),
                "full_report_source_path": freshness.get("full_report_source_path"),
                "full_report_core_filter": freshness.get("full_report_core_filter"),
                "full_report_ai_bot_liquidity_available": freshness.get(
                    "full_report_ai_bot_liquidity_available"
                ),
                "full_report_ai_bot_liquidity_summary": freshness.get(
                    "full_report_ai_bot_liquidity_summary"
                ),
                "mirofish_advisory_gate_action": freshness.get("mirofish_advisory_gate_action"),
                "mirofish_advisory_triggered_gates": freshness.get(
                    "mirofish_advisory_triggered_gates"
                )
                or [],
                "deep_research_review_available": freshness.get(
                    "deep_research_review_available"
                ),
                "deep_research_review_report_id": freshness.get(
                    "deep_research_review_report_id"
                ),
                "deep_research_review_source_path": freshness.get(
                    "deep_research_review_source_path"
                ),
                "deep_research_review_core_filter": freshness.get(
                    "deep_research_review_core_filter"
                ),
                "deep_research_review_stock_selection_biases": freshness.get(
                    "deep_research_review_stock_selection_biases"
                )
                or {},
                "required_artifact_count": freshness.get("required_artifact_count"),
                "missing_piece_count": freshness.get("missing_piece_count"),
                "agpl_code_import_allowed": clean_room.get("agpl_code_import_allowed"),
                "source_code_imported": clean_room.get("source_code_imported"),
                "next_open": "Open full MiroFish handoff packet only when required advisory pieces are missing, the scaffold is missing, or clean-room/execution authority fields are wrong.",
            }
        )
        missing_piece_count = int(freshness.get("missing_piece_count") or 0)
        if data.get("analysis_only") is not True or execution_authority not in {"none", None}:
            flag("schema")
        if freshness.get("can_submit_orders") is not False:
            flag("schema")
        if (
            freshness.get("final_handoff_available") is True
            and (
                missing_piece_count > 0
                or freshness.get("final_advisory_available") is not True
            )
        ):
            flag("drilldown")
        if status == "blocked_missing_scaffold":
            flag("stale")
        if clean_room.get("agpl_code_import_allowed") is not False or clean_room.get("source_code_imported") is not False:
            flag("audit")
    elif label == "hook_event":
        raw_context = data.get("raw_context") if isinstance(data.get("raw_context"), dict) else {}
        hook_context = data.get("hook_context") if isinstance(data.get("hook_context"), dict) else {}
        summary.update(
            {
                "event": data.get("event"),
                "created_at": data.get("created_at"),
                "raw_context_required": raw_context.get("required"),
                "raw_context_reasons": raw_context.get("reasons") or [],
                "raw_context_paths": raw_context.get("paths") or [],
                "thread_id": hook_context.get("thread_id"),
                "goal_status": hook_context.get("goal_status"),
                "goal_objective_excerpt": hook_context.get("goal_objective_excerpt"),
                "goal_objective_truncated": hook_context.get("goal_objective_truncated"),
                "agent_id": hook_context.get("agent_id"),
                "agent_name": hook_context.get("agent_name"),
                "agent_role": hook_context.get("agent_role"),
                "run_id": hook_context.get("run_id"),
                "payload_keys": data.get("payload_keys") or [],
                "next_open": "Open hook event packets only when debugging hook routing or when raw_context_required is true and the corresponding compact flags explain why.",
            }
        )
    elif label == "promotion_state":
        sleeves = data.get("sleeves") or {}
        sleeve_items = sleeves.values() if isinstance(sleeves, dict) else []
        live_enabled = [
            name
            for name, state in (sleeves.items() if isinstance(sleeves, dict) else [])
            if isinstance(state, dict) and state.get("live_enabled") is True
        ]
        issue_count = sum(
            len(state.get("issues") or [])
            for state in sleeve_items
            if isinstance(state, dict)
        )
        summary.update(
            {
                "schema_version": data.get("schema_version"),
                "sleeve_count": len(sleeves) if isinstance(sleeves, dict) else 0,
                "live_enabled_sleeves": live_enabled,
                "issue_count": issue_count,
                "next_open": "Open promotion state when promotion issues appear or live-enabled sleeves unexpectedly change.",
            }
        )
        if issue_count:
            flag("candidate_change")
    elif label == "agent_intelligence_summary":
        agents = data.get("agents") or {}
        forecast_count = data.get("forecast_count")
        ledger_path = path.with_name("ledger.jsonl")
        ledger_count = jsonl_record_count(ledger_path)
        count_matches = (
            ledger_count is None
            or forecast_count is None
            or int(forecast_count or 0) == ledger_count
        )
        unresolved = [
            name
            for name, item in (agents.items() if isinstance(agents, dict) else [])
            if isinstance(item, dict) and int(item.get("resolved_count") or 0) == 0
        ]
        useful_agents = [
            name
            for name, item in (agents.items() if isinstance(agents, dict) else [])
            if isinstance(item, dict) and int(item.get("useful_forecast_count") or 0) > 0
        ]
        harmful_agents = [
            name
            for name, item in (agents.items() if isinstance(agents, dict) else [])
            if isinstance(item, dict) and int(item.get("harmful_forecast_count") or 0) > 0
        ]
        summary.update(
            {
                "forecast_count": forecast_count,
                "resolved_forecast_count": data.get("resolved_forecast_count"),
                "outcome_counts": data.get("outcome_counts") or {},
                "agent_count": len(agents) if isinstance(agents, dict) else 0,
                "unresolved_agent_count": len(unresolved),
                "useful_agent_count": len(useful_agents),
                "harmful_agent_count": len(harmful_agents),
                "influence_weight_count": len((data.get("influence_weights") or {}).get("agents") or {}),
                "ledger_path": rel(ledger_path) if ledger_count is not None else None,
                "ledger_record_count": ledger_count,
                "summary_ledger_count_matches": count_matches,
                "next_open": "Open agent intelligence summary when forecasts resolve, influence weights change, or an agent becomes harmful/useful by evidence.",
            }
        )
        if count_matches is False:
            flag("schema")
    elif label == "connector_health":
        connectors = data.get("connectors") or []
        connector_rows = [item for item in connectors if isinstance(item, dict)]
        open_circuits = [
            str(item.get("connector"))
            for item in connector_rows
            if item.get("circuit_state") == "open"
        ]
        rate_limited = [
            str(item.get("connector"))
            for item in connector_rows
            if int(item.get("rate_limit_count") or 0) > 0
        ]
        fallbacks = [
            str(item.get("connector"))
            for item in connector_rows
            if int(item.get("fallback_count") or 0) > 0
        ]
        error_rows = sorted(
            connector_rows,
            key=lambda item: int(item.get("errors") or 0),
            reverse=True,
        )
        total_errors = sum(int(item.get("errors") or 0) for item in connector_rows)
        total_rate_limits = sum(int(item.get("rate_limit_count") or 0) for item in connector_rows)
        total_fallbacks = sum(int(item.get("fallback_count") or 0) for item in connector_rows)
        missing_key_connectors = [
            str(item.get("connector"))
            for item in connector_rows
            if int(item.get("errors") or 0) > 0
            and "API_KEY is missing" in str(item.get("last_error") or "")
        ]
        def is_optional_endpoint_error(item: dict[str, Any]) -> bool:
            connector = str(item.get("connector") or "").lower()
            last_error = str(item.get("last_error") or "")
            if int(item.get("errors") or 0) <= 0:
                return False
            if item.get("circuit_state") == "open":
                return False
            if int(item.get("rate_limit_count") or 0) > 0:
                return False
            if int(item.get("fallback_count") or 0) > 0:
                return False
            if (
                connector == "alphainsider"
                and int(item.get("successes") or 0) > 0
                and "HTTP 400" in last_error
            ):
                return True
            if connector == "youtube_transcript" and "youtube_transcript MCP timed out" in last_error:
                return True
            return connector in {"reddit_public", "stocktwits_public"} and "HTTP 403" in last_error

        optional_endpoint_errors = [
            str(item.get("connector"))
            for item in connector_rows
            if is_optional_endpoint_error(item)
        ]
        non_missing_key_error_count = sum(
            int(item.get("errors") or 0)
            for item in connector_rows
            if int(item.get("errors") or 0) > 0
            and "API_KEY is missing" not in str(item.get("last_error") or "")
            and str(item.get("connector") or "") not in optional_endpoint_errors
        )
        summary.update(
            {
                "schema_version": data.get("schema_version"),
                "connector_count": len(connector_rows),
                "total_errors": total_errors,
                "non_missing_key_error_count": non_missing_key_error_count,
                "total_rate_limit_count": total_rate_limits,
                "total_fallback_count": total_fallbacks,
                "open_circuit_count": len(open_circuits),
                "open_circuits": open_circuits[:5],
                "rate_limited_connectors": rate_limited[:5],
                "fallback_connectors": fallbacks[:5],
                "optional_missing_key_connectors": missing_key_connectors[:8],
                "optional_endpoint_error_connectors": optional_endpoint_errors[:8],
                "worst_connectors": [
                    {
                        "connector": item.get("connector"),
                        "errors": item.get("errors"),
                        "last_error": item.get("last_error"),
                        "circuit_state": item.get("circuit_state"),
                    }
                    for item in error_rows[:5]
                    if int(item.get("errors") or 0) > 0
                ],
                "next_open": "Open connector health only when circuits open, rate limits occur, fallbacks are used, or non-key connector errors rise.",
            }
        )
        if open_circuits or total_rate_limits or total_fallbacks or non_missing_key_error_count:
            flag("connector_health")
    elif label == "source_routing":
        raw_categories = data.get("categories")
        raw_methods = data.get("methods")
        raw_gaps = data.get("source_category_gaps")
        raw_coverage = data.get("source_category_coverage")
        raw_gap_categories = data.get("gap_categories")
        raw_coverage_categories = data.get("coverage_categories")
        categories: dict[str, Any] = raw_categories if isinstance(raw_categories, dict) else {}
        methods: dict[str, Any] = raw_methods if isinstance(raw_methods, dict) else {}
        gaps: list[Any] = raw_gaps if isinstance(raw_gaps, list) else []
        coverage: list[Any] = raw_coverage if isinstance(raw_coverage, list) else []
        gap_categories: list[Any] = (
            raw_gap_categories if isinstance(raw_gap_categories, list) else []
        )
        coverage_categories: list[Any] = (
            raw_coverage_categories if isinstance(raw_coverage_categories, list) else []
        )
        empty_methods = [
            name
            for name, item in methods.items()
            if isinstance(item, dict) and not item.get("effective_fallback_chain")
        ]
        provider_overlay = {
            field: data.get(field)
            for field in PROVIDER_BUNDLE_OVERLAY_KEYS
            if field in data
        }
        fresh_provider_overlay = recent_provider_bundle_gap_overlay()
        if fresh_provider_overlay.get("recent_provider_bundle_count") or not provider_overlay:
            provider_overlay = fresh_provider_overlay
            data.update(provider_overlay)
            with suppress(OSError):
                path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
        summary.update(
            {
                "schema_version": data.get("schema_version") or data.get("schema"),
                "category_count": int(data.get("category_count") or len(categories)),
                "method_count": int(data.get("method_count") or len(methods)),
                "gap_count": int(data.get("gap_count") or len(gaps)),
                "gap_categories": (
                    [str(item) for item in gap_categories[:6]]
                    if gap_categories
                    else [
                        str(item.get("category"))
                        for item in gaps[:6]
                        if isinstance(item, dict) and item.get("category")
                    ]
                ),
                "coverage_count": int(data.get("coverage_count") or len(coverage)),
                "coverage_categories": (
                    [str(item) for item in coverage_categories[:6]]
                    if coverage_categories
                    else [
                        str(item.get("category"))
                        for item in coverage[:6]
                        if isinstance(item, dict) and item.get("category")
                    ]
                ),
                "empty_method_count": len(empty_methods),
                "empty_methods": empty_methods[:8],
                "next_open": "Open source routing when a method has no fallback chain, vendor chains change, or source categories become relevant to the day plan.",
                **provider_overlay,
            }
        )
        target_symbols = provider_overlay.get("recent_provider_overnight_target_symbols") or []
        target_provider_gap = (
            provider_overlay.get("recent_provider_target_symbols_missing_bundle")
            or provider_overlay.get("recent_provider_target_evidence_needs_without_non_gap_packets")
        )
        untargeted_provider_gap = not target_symbols and (
            int_or_zero(provider_overlay.get("recent_provider_gap_packet_count")) > 0
            or provider_overlay.get("recent_provider_evidence_needs_without_non_gap_packets")
        )
        if empty_methods or target_provider_gap or untargeted_provider_gap:
            flag("source_routing")

    return summary


def rrule_minutes(rrule: str | None) -> int | None:
    if not rrule:
        return None
    if "FREQ=HOURLY" in rrule:
        match = re.search(r"INTERVAL=(\d+)", rrule)
        return int(match.group(1)) * 60 if match else 60
    if "BYHOUR=" in rrule:
        return None
    return None


def automation_recommendation(automation_id: str, model: str | None, effort: str | None, rrule: str | None) -> dict[str, Any]:
    keep_quality_note = "Do not reduce evidence quality; reduce repeated prompt/input context first."
    if automation_id == "hourly-market-supervisor":
        return {
            "pricing_bet": "Keep medium reasoning for normal hourly ticks; require high only when summary flags actions/issues/submissions.",
            "model_level": model,
            "reasoning_effort": effort,
            "frequency": "Hourly is defensible while live supervision is active; consider market-hours-only plus explicit pre/post windows after observing no value from overnight weekend ticks.",
            "combine_with": "Can share the same compact supervisor prompt as market-window jobs; do not combine with paper tournament execution.",
            "quality_guard": keep_quality_note,
        }
    if automation_id == "paper-strategy-tournament-runner":
        return {
            "pricing_bet": "Paper-only quiet ticks can use compact prompt and medium effort; escalate only on submitted paper orders, blockers, or candidate changes.",
            "model_level": model,
            "reasoning_effort": effort,
            "frequency": "Hourly at minute 5 is likely more frequent than needed for strategic sleeve ranking; propose market-hours hourly or every 2 hours unless candidate promotion depends on every tick.",
            "combine_with": "Can be summarized by context index; keep execution separate from live supervisor.",
            "quality_guard": full_detail_guard(),
        }
    if automation_id == "tradingagents-overnight-planning":
        return {
            "pricing_bet": "Keep high reasoning because this is the expensive planning synthesis; save tokens by compacting prompt and using summaries, not by weakening analysis.",
            "model_level": model,
            "reasoning_effort": effort,
            "frequency": "Daily 3 AM run is reasonable; avoid extra reruns unless packet missing/stale/failed.",
            "combine_with": "Can produce premarket brief in same automation as now.",
            "quality_guard": keep_quality_note,
        }
    if "market-supervisor" in automation_id:
        return {
            "pricing_bet": "Use same shared supervisor prompt with time-window focus injected; keep high before/after open, medium near/after close unless flags require escalation.",
            "model_level": model,
            "reasoning_effort": effort,
            "frequency": "Keep four market-window runs; they are event checkpoints, not redundant hourly ticks.",
            "combine_with": "Combine prompt template with hourly supervisor, not schedules.",
            "quality_guard": keep_quality_note,
        }
    if automation_id == "tradingagents-daily-market-report":
        return {
            "pricing_bet": "Daily report can stay medium but should read generated context summary before full packets.",
            "model_level": model,
            "reasoning_effort": effort,
            "frequency": "Once per trading day is sufficient.",
            "combine_with": "Do not combine with after-close supervisor; report should wait for final packets.",
            "quality_guard": keep_quality_note,
        }
    if automation_id in {"tradingagents-automation-sleep-controller", "tradingagents-automation-wake-controller"}:
        return {
            "pricing_bet": "Low reasoning is appropriate because these controllers only inspect calendars/configs and update automation status.",
            "model_level": model,
            "reasoning_effort": effort,
            "frequency": "Twice-daily controller pattern is high leverage: it reduces token-heavy off-hours runs without weakening trading analysis.",
            "combine_with": "Do not combine the controllers; separate wake/sleep timing keeps status transitions auditable.",
            "quality_guard": "Keep controllers read-only with respect to repo/trading commands; status updates only.",
        }
    return {
        "pricing_bet": "Use compact prompt and escalate only on flags.",
        "model_level": model,
        "reasoning_effort": effort,
        "frequency": "No change proposed.",
        "combine_with": "No safe consolidation identified.",
        "quality_guard": keep_quality_note,
    }


def full_detail_guard() -> str:
    return "Keep full raw packets and drill down on candidate changes, blockers, submissions, or schema mismatch."


def discover_automation_ids() -> list[str]:
    if not AUTOMATION_ROOT.exists():
        return []
    ids: list[str] = []
    for path in sorted(AUTOMATION_ROOT.glob("*/automation.toml")):
        data = read_toml(path)
        automation_id = str(data.get("id") or path.parent.name)
        if automation_id:
            ids.append(automation_id)
    return ids


def classify_automation(automation_id: str, data: dict[str, Any] | None = None) -> str:
    data = data or {}
    prompt = str(data.get("prompt") or "").lower()
    cwd_text = " ".join(str(item) for item in data.get("cwds") or []).lower()
    is_tradingagents = (
        "tradingagents" in automation_id.lower()
        or "tradingagents" in prompt
        or "tradingagents-main" in cwd_text
    )
    if automation_id in CONTROLLER_AUTOMATION_IDS:
        return "controller"
    if automation_id in KNOWN_FOLLOW_UP_AUTOMATION_IDS:
        return "one_off_followup"
    if automation_id in KNOWN_OBSERVER_AUTOMATION_IDS:
        return "n8n_or_hook"
    if automation_id == "tradingagents-overnight-planning":
        return "overnight_research"
    if automation_id == "tradingagents-daily-market-report":
        return "daily_report"
    if automation_id in {"hourly-market-supervisor", "paper-strategy-tournament-runner"}:
        return "hourly_or_paper"
    if "market-supervisor" in automation_id:
        return "market_day"
    if "n8n" in automation_id.lower() or "hook" in automation_id.lower():
        return "n8n_or_hook"
    if is_tradingagents:
        return "unknown_tradingagents"
    return "other"


def summarize_automation(automation_id: str) -> dict[str, Any]:
    path = AUTOMATION_ROOT / automation_id / "automation.toml"
    memory = AUTOMATION_ROOT / automation_id / "memory.md"
    if not path.exists():
        return {
            "id": automation_id,
            "missing": True,
            "classification": classify_automation(automation_id),
            "managed_by_controllers": automation_id in AUTOMATION_IDS,
        }
    data = read_toml(path)
    prompt = str(data.get("prompt") or "")
    rrule = data.get("rrule")
    model = data.get("model")
    effort = data.get("reasoning_effort")
    prompt_tokens = approx_tokens(len(prompt))
    compact_prompt_tokens = 180
    recommendation = automation_recommendation(automation_id, model, effort, rrule)
    return {
        "id": automation_id,
        "path": str(path),
        "kind": data.get("kind"),
        "name": data.get("name"),
        "classification": classify_automation(automation_id, data),
        "managed_by_controllers": automation_id in AUTOMATION_IDS,
        "status": data.get("status"),
        "rrule": rrule,
        "estimated_interval_minutes": rrule_minutes(rrule),
        "model": model,
        "reasoning_effort": effort,
        "prompt_chars": len(prompt),
        "prompt_approx_tokens": prompt_tokens,
        "prompt_compaction_target_tokens": compact_prompt_tokens,
        "prompt_token_savings_estimate": max(0, prompt_tokens - compact_prompt_tokens),
        "memory_path": str(memory),
        "memory_kb": round(memory.stat().st_size / 1024, 1) if memory.exists() else 0,
        "memory_approx_tokens": approx_tokens(memory.stat().st_size) if memory.exists() else 0,
        "recommendation": recommendation,
    }


def collect_metrics(*, refresh: bool = True) -> dict[str, Any]:
    if refresh:
        refresh_generated_context_files()
    guidance = [file_metric(path) for path in GUIDANCE_FILES if path.exists()]
    automations = [summarize_automation(item) for item in AUTOMATION_IDS]
    latest_metrics = []
    for label, directory in LATEST_PACKETS:
        path = latest_snapshot_json(label, directory)
        if path:
            latest_metrics.append({"label": label, **file_metric(path)})
    for label, path in LATEST_PACKET_FILES:
        if path.exists():
            latest_metrics.append({"label": label, **file_metric(path)})
    top_sources = sorted(
        [
            *guidance,
            *latest_metrics,
            *[
                {
                    "path": item["path"],
                    "bytes": item["prompt_chars"],
                    "kb": round(item["prompt_chars"] / 1024, 1),
                    "lines": 1,
                    "approx_tokens": item["prompt_approx_tokens"],
                    "kind": "automation_prompt",
                }
                for item in automations
                if not item.get("missing")
            ],
            *[
                {
                    "path": item["memory_path"],
                    "bytes": int(item["memory_kb"] * 1024),
                    "kb": item["memory_kb"],
                    "lines": None,
                    "approx_tokens": item["memory_approx_tokens"],
                    "kind": "automation_memory",
                }
                for item in automations
                if not item.get("missing")
            ],
        ],
        key=lambda item: item.get("approx_tokens") or 0,
        reverse=True,
    )
    return {
        "method": "Approx tokens = ceil(character_or_byte_count / 4). Good for ranking, not billing.",
        "guidance_files": guidance,
        "latest_packets": latest_metrics,
        "automation_count": len([a for a in automations if not a.get("missing")]),
        "top_context_sources": top_sources[:20],
    }


def latest_automation_memory_rollup_summary() -> dict[str, Any] | None:
    path = AUTOMATION_MEMORY_ROLLUP_LATEST
    if not path.exists():
        return None
    try:
        packet = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"path": rel(path), "error": "invalid_json"}
    summary = packet.get("summary") or {}
    return {
        "path": rel(path),
        "generated_at": packet.get("generated_at"),
        "analysis_only": packet.get("analysis_only"),
        "can_submit_orders": packet.get("can_submit_orders"),
        "execution_authority": packet.get("execution_authority"),
        "mutation_mode": packet.get("mutation_mode"),
        "rollup_candidate_count": summary.get("rollup_candidate_count"),
        "candidate_approx_tokens": summary.get("candidate_approx_tokens"),
        "memory_count": summary.get("memory_count"),
    }


def collect_snapshot(*, refresh: bool = True) -> dict[str, Any]:
    if refresh:
        refresh_generated_context_files()
    packets = []
    for label, directory in LATEST_PACKETS:
        path = latest_snapshot_json(label, directory)
        if path:
            packets.append(summarize_packet(label, path))
        else:
            packets.append({"label": label, "missing": True, "directory": str(directory)})
    for label, path in LATEST_PACKET_FILES:
        if path.exists():
            packets.append(summarize_packet(label, path))
        else:
            packets.append({"label": label, "missing": True, "path": rel(path)})

    flags = []
    for packet in packets:
        if packet.get("drilldown_required"):
            for reason in packet.get("drilldown_reasons", []):
                flags.append(
                    {
                        "label": packet["label"],
                        "reason": reason,
                        "meaning": DRILLDOWN_REASONS.get(reason, reason),
                        "path": packet.get("path"),
                    }
                )

    next_open = list(dict.fromkeys(str(flag["path"]) for flag in flags if flag.get("path")))

    return {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "repo": str(ROOT),
        "router": "CONTEXT_ROUTER.md",
        "read_path": [
            "AGENTS.md",
            "CONTEXT_ROUTER.md",
            "results/_context/latest-summary.json",
            "results/_context/latest-flags.json",
            "Open raw packets only for listed flags or task-specific drilldown.",
        ],
        "latest_packets": packets,
        "incidents": summarize_incidents(),
        "flags": flags,
        "next_open": next_open,
    }


def _raw_fields_for_summary_field(field_name: str) -> list[str]:
    if field_name in PACKET_FIELD_RAW_SOURCES:
        return PACKET_FIELD_RAW_SOURCES[field_name]
    return [field_name]


def _field_provenance(
    *,
    field_name: str,
    packet_index: int,
    packet_path: str | None,
    missing_packet: bool,
) -> dict[str, Any]:
    base = {
        "summary_json_path": f"latest_packets[{packet_index}].{field_name}",
        "raw_packet_path": packet_path,
    }
    if missing_packet:
        return {
            **base,
            "source_kind": "missing_marker",
            "derived_from": PACKET_SYSTEM_DERIVED_FIELDS.get(field_name, ["missing_raw_packet_file"]),
        }
    if field_name in PACKET_METRIC_DERIVED_FIELDS:
        return {
            **base,
            "source_kind": "derived_field",
            "derived_from": PACKET_METRIC_DERIVED_FIELDS[field_name],
        }
    if field_name in PACKET_SYSTEM_DERIVED_FIELDS:
        return {
            **base,
            "source_kind": "derived_field",
            "derived_from": PACKET_SYSTEM_DERIVED_FIELDS[field_name],
        }
    return {
        **base,
        "source_kind": "raw_field",
        "raw_fields": _raw_fields_for_summary_field(field_name),
    }


def build_field_provenance(snapshot: dict[str, Any]) -> dict[str, Any]:
    packets = snapshot.get("latest_packets")
    packet_provenance = []
    if isinstance(packets, list):
        for index, packet in enumerate(packets):
            if not isinstance(packet, dict):
                continue
            packet_path = packet.get("path")
            packet_path_text = str(packet_path) if packet_path else None
            missing_packet = bool(packet.get("missing") or packet.get("error"))
            fields = {
                field_name: _field_provenance(
                    field_name=field_name,
                    packet_index=index,
                    packet_path=packet_path_text,
                    missing_packet=missing_packet,
                )
                for field_name in packet
            }
            packet_provenance.append(
                {
                    "label": packet.get("label"),
                    "raw_packet_path": packet_path_text,
                    "summary_json_path": f"latest_packets[{index}]",
                    "field_count": len(fields),
                    "fields": fields,
                }
            )
    return {
        "schema": "tradingagents.context.field_provenance.v1",
        "generated_at": snapshot.get("generated_at"),
        "summary_path": "results/_context/latest-summary.json",
        "rule": "Every compact latest_packets field must point to a raw packet field, file metric, or explicit missing marker.",
        "packets": packet_provenance,
    }


def collect_automation_index() -> dict[str, Any]:
    discovered_ids = discover_automation_ids()
    ordered_ids = list(
        dict.fromkeys(
            [*AUTOMATION_IDS, *KNOWN_FOLLOW_UP_AUTOMATION_IDS, *KNOWN_OBSERVER_AUTOMATION_IDS, *discovered_ids]
        )
    )
    automations = [summarize_automation(item) for item in ordered_ids]
    prompt_tokens = sum(item.get("prompt_approx_tokens", 0) for item in automations)
    target_tokens = sum(item.get("prompt_compaction_target_tokens", 0) for item in automations)
    by_classification: dict[str, int] = {}
    for item in automations:
        classification = str(item.get("classification") or "unknown")
        by_classification[classification] = by_classification.get(classification, 0) + 1
    known_ids = set(AUTOMATION_IDS) | set(KNOWN_FOLLOW_UP_AUTOMATION_IDS) | set(KNOWN_OBSERVER_AUTOMATION_IDS)
    unknown_tradingagents = [
        item["id"]
        for item in automations
        if item.get("classification") == "unknown_tradingagents"
    ]
    discovered_unmanaged = [
        item["id"]
        for item in automations
        if item["id"] not in known_ids and item.get("classification") != "other"
    ]
    return {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "source_root": str(AUTOMATION_ROOT),
        "automations": automations,
        "automation_count": len([item for item in automations if not item.get("missing")]),
        "known_managed_ids": AUTOMATION_IDS,
        "known_follow_up_ids": KNOWN_FOLLOW_UP_AUTOMATION_IDS,
        "known_observer_ids": KNOWN_OBSERVER_AUTOMATION_IDS,
        "classification_counts": by_classification,
        "unknown_tradingagents_ids": unknown_tradingagents,
        "discovered_unmanaged_tradingagents_ids": discovered_unmanaged,
        "prompt_totals": {
            "current_approx_tokens": prompt_tokens,
            "compact_target_approx_tokens": target_tokens,
            "estimated_savings_per_full_prompt_load": max(0, prompt_tokens - target_tokens),
        },
        "compaction_boundary": "No active automation TOML was changed by this script.",
    }


def packet_delta(label: str, directory: Path) -> str:
    paths = recent_snapshot_jsons(label, directory, 2)
    if not paths:
        return f"- {label}: no packets found"
    current = summarize_packet(label, paths[0])
    previous = summarize_packet(label, paths[1]) if len(paths) > 1 else None
    if not previous:
        return f"- {label}: only current packet available at `{current.get('path')}`"

    watched = [
        "decision",
        "reason",
        "top_symbol",
        "leader",
        "candidate_status",
        "candidate_strategy",
        "overall_status",
        "submitted",
        "issues",
        "blockers",
        "graph_failure_count",
        "secrets_redacted",
        "missing_env_count",
        "status",
        "failed_quality_gates",
        "fetched_count",
        "blocked_count",
        "usefulness_counts",
        "outcome_counts",
        "resolved_model_run_count",
        "sleeve_count",
        "live_enabled_sleeves",
        "issue_count",
        "forecast_count",
        "agent_count",
        "unresolved_agent_count",
    ]
    changes = []
    for key in watched:
        if current.get(key) != previous.get(key):
            changes.append(f"{key}: {previous.get(key)!r} -> {current.get(key)!r}")
    if not changes:
        changes.append("no watched-field changes")
    return f"- {label}: `{current.get('path')}` vs `{previous.get('path')}`; " + "; ".join(changes[:8])


def build_recent_deltas() -> str:
    lines = [
        "# Recent Context Deltas",
        "",
        f"Generated: {dt.datetime.now(dt.timezone.utc).isoformat()}",
        "",
        "Use this as a cheap change detector. Open raw packets only when a watched",
        "field changes or `latest-flags.json` says drilldown is required.",
        "",
    ]
    for label, directory in LATEST_PACKETS:
        lines.append(packet_delta(label, directory))
    for label, path in LATEST_PACKET_FILES:
        if path.exists():
            current = summarize_packet(label, path)
            lines.append(f"- {label}: current single-file state at `{current.get('path')}`")
        else:
            lines.append(f"- {label}: missing expected state file at `{rel(path)}`")
    lines.append("")
    lines.append("Raw packets remain the evidence source; this file is only an index.")
    return "\n".join(lines) + "\n"


def proposed_prompt_patterns() -> str:
    exe = r'C:\Users\Corbin\Documents\Coding projects\TradingAgents-main\.venv\Scripts\tradingagents.exe'
    return f"""# Automation Prompt Compaction Approval Plan

Generated: {dt.datetime.now(dt.timezone.utc).isoformat()}

This is an approval plan, not an applied automation change. It preserves report
quality by keeping full raw packets and using generated summaries as the first
read path.

## Shared Compact Header

Use this repo's compact read path before opening large packets:
`AGENTS.md -> CONTEXT_ROUTER.md -> results/_context/latest-summary.json -> results/_context/latest-flags.json`.
Open full raw packets only when flags show blockers, issues, submitted actions,
stale data, graph failures, candidate changes, schema mismatch, or unexplained
P/L/action changes. Raw packets remain authoritative.

Use the repo executable directly:
`& "{exe}" ...`

## Proposed Automation Changes

| Automation | Current | Proposed |
| --- | --- | --- |
| hourly-market-supervisor | Hourly all days, model gpt-5.5, medium effort, long prompt | Keep schedule for now, replace repeated context with shared header, escalate reasoning only when flags/actions/issues appear. |
| paper-strategy-tournament-runner | Hourly all days, gpt-5.5 medium | Consider every 2 hours or market-hours-only after approval; keep separate from live supervisor; compact prompt now is safe. |
| tradingagents-overnight-planning | Daily 3 AM, gpt-5.5 high | Keep high reasoning and daily frequency; compact prompt only. |
| market-supervisor-15-min-before-open | Weekdays 8:15, gpt-5.5 high | Keep high; compact with shared header plus pre-open focus. |
| market-supervisor-30-min-after-open | Weekdays 9:00, gpt-5.5 high | Keep high; compact with shared header plus open-window focus. |
| market-supervisor-30-min-before-close | Weekdays 14:30, gpt-5.5 medium | Keep medium; compact with shared header plus close-prep focus. |
| market-supervisor-15-min-after-close | Weekdays 15:15, gpt-5.5 medium | Keep medium; compact with shared header plus after-close focus. |
| tradingagents-daily-market-report | Weekdays 15:30, gpt-5.5 medium | Keep once daily; read summaries first and drill down for report detail only as needed. |
| tradingagents-automation-sleep-controller | Daily 16:45, gpt-5.5 low | Keep low; high leverage because it pauses token-heavy automations after market work. |
| tradingagents-automation-wake-controller | Daily 06:45, gpt-5.5 low | Keep low; high leverage because it wakes market-day automations only when useful. |
| tradingagents-night-shift-supervisor | Overnight patrol, low effort | Keep low and controller-only; it checks status drift and compact flags without running trading commands. |
| fetch-tradingagents-deep-research-report | One-off Browser/report heartbeat | Treat as follow-up, not a TradingAgents scheduler; do not pause/resume unless explicitly requested. |

## Safe Consolidation

- Combine prompt templates for hourly and four market-window supervisors.
- Keep execution schedules separate because each window has different market risk.
- Keep paper tournament separate from live supervisor because it is paper-only.
- Keep daily report separate because it must wait for after-close packets.

## Changes Requiring Approval

- Any schedule/frequency reduction.
- Any model downgrade.
- Any active `C:\\cm\\automations\\...\\automation.toml` prompt rewrite.
- Any packet schema compaction.
"""


def write_context_files() -> list[Path]:
    CONTEXT_DIR.mkdir(parents=True, exist_ok=True)
    refresh_generated_context_files()
    snapshot = collect_snapshot(refresh=False)
    automation_index = collect_automation_index()
    metrics = collect_metrics(refresh=False)
    flags = {
        "generated_at": snapshot["generated_at"],
        "flags": snapshot["flags"],
        "drilldown_reasons": DRILLDOWN_REASONS,
        "next_open": snapshot["next_open"],
    }
    manifest = {
        "generated_at": snapshot["generated_at"],
        "files": {
            "latest_summary": "results/_context/latest-summary.json",
            "latest_flags": "results/_context/latest-flags.json",
            "automation_index": "results/_context/automation-index.json",
            "field_provenance": "results/_context/field-provenance.json",
            "recent_deltas": "results/_context/recent-deltas.md",
            "context_manifest": "results/_context/context-manifest.json",
            "automation_approval_plan": "results/_context/automation-compaction-approval-plan.md",
            "automation_memory_rollup": "results/token_efficiency/latest-automation-memory-rollup.json",
        },
        "read_path": snapshot["read_path"],
        "metrics": metrics,
        "automation_memory_rollup": latest_automation_memory_rollup_summary(),
    }
    outputs = {
        CONTEXT_DIR / "latest-summary.json": snapshot,
        CONTEXT_DIR / "latest-flags.json": flags,
        CONTEXT_DIR / "automation-index.json": automation_index,
        CONTEXT_DIR / "field-provenance.json": build_field_provenance(snapshot),
        CONTEXT_DIR / "context-manifest.json": manifest,
    }
    written: list[Path] = []
    for path, payload in outputs.items():
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        written.append(path)
    deltas = CONTEXT_DIR / "recent-deltas.md"
    deltas.write_text(build_recent_deltas(), encoding="utf-8")
    written.append(deltas)
    approval = CONTEXT_DIR / "automation-compaction-approval-plan.md"
    approval.write_text(proposed_prompt_patterns(), encoding="utf-8")
    written.append(approval)
    written.extend(reconcile_hourly_loss_review_compact_sidecars(snapshot))
    return written


def print_text(snapshot: dict[str, Any]) -> None:
    print(f"Repo: {snapshot['repo']}")
    print(f"Router: {snapshot['router']}")
    print()
    print("Read path:")
    for item in snapshot["read_path"]:
        print(f"- {item}")
    print()
    print("Latest packets:")
    for packet in snapshot["latest_packets"]:
        if packet.get("missing") or packet.get("error"):
            print(f"- {packet.get('label')}: {packet.get('error') or 'missing'}")
            continue
        rest = {k: v for k, v in packet.items() if k not in {"label", "path", "graph_config"}}
        print(f"- {packet['label']}: {packet['path']}")
        for key, value in rest.items():
            print(f"  {key}: {value}")
    print()
    print("Flags:")
    if not snapshot["flags"]:
        print("- none")
    for flag in snapshot["flags"]:
        print(f"- {flag['label']} {flag['reason']}: {flag['path']}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="emit compact JSON")
    parser.add_argument("--write", action="store_true", help="write compact context artifacts under results/_context")
    args = parser.parse_args()

    snapshot = collect_snapshot()
    if args.write:
        written = write_context_files()
        print("Wrote context artifacts:")
        for path in written:
            print(f"- {rel(path)}")
        return 0
    if args.json:
        print(json.dumps(snapshot, indent=2, sort_keys=True))
    else:
        print_text(snapshot)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
