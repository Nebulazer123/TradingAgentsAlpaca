"""Model research telemetry packet helpers."""

from __future__ import annotations

import datetime
import json
from collections.abc import Iterable, Sequence
from decimal import Decimal, InvalidOperation
from pathlib import Path

from tradingagents.evals.agent_intelligence_ledger import AgentForecast
from tradingagents.llm_clients.model_catalog import get_model_context_window_tokens
from tradingagents.schemas.research import ModelRunTelemetryPacket

from .model_routing import ModelRoute

UTC = datetime.timezone.utc


def model_route_telemetry_packet(
    *,
    run_id: str,
    route: ModelRoute,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    latency_seconds: float | None = None,
    error_summary: str | None = None,
) -> ModelRunTelemetryPacket:
    status = (
        "success"
        if route.status == "selected"
        else "fallback"
        if route.status == "external"
        else "blocked"
    )
    return ModelRunTelemetryPacket(
        run_id=run_id,
        provider=route.provider,
        model=route.model,
        route=route.route,
        context_window_tokens=route.context_window_tokens,
        status=status,  # type: ignore[arg-type]
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        estimated_cost_usd=str(route.estimated_cost_usd),
        latency_seconds=latency_seconds,
        budget_ref=route.reason,
        error_summary=error_summary,
        tool_route="model_routing",
        redaction_status="redacted",
    )


def _decimal(value: str | None) -> Decimal:
    try:
        return Decimal(str(value or "0"))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _money(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.0001")))


def _counter_add(counter: dict[str, int], key: str) -> None:
    counter[key] = counter.get(key, 0) + 1


def _route_error_kind(route: str, error_summary: str) -> str:
    text = f"{route} {error_summary}".lower()
    if "mac_ollama" in text or "mac worker" in text:
        network_markers = (
            "timed out",
            "timeout",
            "connection timed out",
            "host unreachable",
            "network is unreachable",
            "no route to host",
            "temporary failure in name resolution",
            "getaddrinfo failed",
            "name or service not known",
            "could not resolve",
        )
        if any(marker in text for marker in network_markers):
            return "mac_host_unreachable"
        if "not in tags" in text or "required helper model" in text:
            return "mac_model_missing"
        if "not configured" in text:
            return "mac_endpoint_not_configured"
        return "mac_endpoint_unreachable"
    if "windows_local_ollama" in text or "windows local ollama" in text:
        if "not in tags" in text or "required helper model" in text:
            return "windows_model_missing"
        if "not configured" in text:
            return "windows_endpoint_not_configured"
        return "windows_endpoint_unreachable"
    if "paid" in text or "budget" in text:
        return "paid_route_disabled_or_budgeted"
    return "route_blocked"


def _plain_english_for_blocked_route(route: str, error_summary: str) -> str:
    kind = _route_error_kind(route, error_summary)
    if kind == "mac_host_unreachable":
        return (
            "Mac helper host is unreachable from Windows/Tailscale; overnight research "
            "will skip the Mac DeepSeek lane and use Windows local, deterministic, or "
            "Codex fallback until the Mac is online and Ollama responds."
        )
    if kind == "mac_model_missing":
        return (
            "Mac Ollama is reachable, but the configured helper model is missing; pull "
            "the Mac helper model before using that lane."
        )
    if kind == "mac_endpoint_not_configured":
        return (
            "Mac helper endpoint is not configured for this process; keep using Windows "
            "local or deterministic fallback until the Mac Ollama URL is set."
        )
    if kind == "mac_endpoint_unreachable":
        return (
            "Mac helper endpoint is not responding; verify the Mac host, Ollama service, "
            "and tags endpoint before routing helper work there."
        )
    if kind == "windows_endpoint_not_configured":
        return (
            "Windows local Ollama endpoint is not configured; use deterministic helpers "
            "until the local endpoint is available."
        )
    if kind == "windows_model_missing":
        return (
            "Windows local Ollama is reachable, but the configured helper model is "
            "missing; pull the model before using that lane."
        )
    if kind == "windows_endpoint_unreachable":
        return (
            "Windows local Ollama is not responding; start or repair the local Ollama "
            "service before routing helper work there."
        )
    return f"{route} is not ready: {error_summary}"


def _self_heal_actions_for_route(route: str, error_summary: str) -> list[str]:
    kind = _route_error_kind(route, error_summary)
    if kind == "mac_host_unreachable":
        return [
            "verify_mac_tailscale_or_host_is_online",
            "verify_mac_ssh_macbook_codex",
            "restart_or_expose_mac_ollama_after_host_reachable",
            "verify_mac_ollama_tags_endpoint",
            "use_windows_or_deterministic_fallback_until_ready",
        ]
    if kind.startswith("windows_"):
        return [
            "install_or_start_windows_ollama",
            "set_TRADINGAGENTS_WINDOWS_OLLAMA_URL_after_endpoint_exists",
            "use_deterministic_helpers_until_ready",
        ]
    if kind.startswith("mac_"):
        return [
            "verify_mac_ollama_tags_endpoint",
            "set_TRADINGAGENTS_MAC_OLLAMA_URL_after_endpoint_exists",
            "use_windows_or_deterministic_fallback_until_ready",
        ]
    if kind == "paid_route_disabled_or_budgeted":
        return [
            "keep_paid_models_disabled",
            "use_free_or_local_routes",
            "only_arm_paid_route_with_explicit_budget",
        ]
    return ["use_deterministic_helpers_until_ready"]


def _blocked_route_summaries(errors: list[dict[str, str]]) -> list[dict[str, object]]:
    grouped: dict[tuple[str, str], dict[str, object]] = {}
    for error in errors:
        route = error.get("route") or "unknown"
        provider = error.get("provider") or "unknown"
        key = (route, provider)
        summary = grouped.setdefault(
            key,
            {
                "route": route,
                "provider": provider,
                "blocked_count": 0,
                "latest_error": "",
                "error_kind": "route_blocked",
                "plain_english": "",
                "self_heal_actions": [],
            },
        )
        summary["blocked_count"] = int(summary["blocked_count"]) + 1
        latest_error = error.get("error_summary") or "route blocked"
        summary["latest_error"] = latest_error
        summary["error_kind"] = _route_error_kind(route, latest_error)
        summary["plain_english"] = _plain_english_for_blocked_route(route, latest_error)
        summary["self_heal_actions"] = _self_heal_actions_for_route(route, latest_error)
    return sorted(
        grouped.values(),
        key=lambda item: (-int(item["blocked_count"]), str(item["route"])),
    )


def _latest_route_packets(
    packets: Iterable[ModelRunTelemetryPacket],
) -> dict[str, ModelRunTelemetryPacket]:
    latest: dict[str, ModelRunTelemetryPacket] = {}
    for packet in packets:
        route = packet.route or "unknown"
        previous = latest.get(route)
        if previous is None:
            latest[route] = packet
            continue
        if (packet.generated_at, packet.run_id) >= (previous.generated_at, previous.run_id):
            latest[route] = packet
    return latest


def _current_route_statuses(
    latest_by_route: dict[str, ModelRunTelemetryPacket],
) -> list[dict[str, object]]:
    statuses: list[dict[str, object]] = []
    for route, packet in sorted(latest_by_route.items()):
        context_window_tokens = packet.context_window_tokens
        if context_window_tokens is None:
            context_window_tokens = get_model_context_window_tokens(
                packet.provider,
                packet.model,
            )
        statuses.append(
            {
                "route": route,
                "provider": packet.provider,
                "model": packet.model,
                "context_window_tokens": context_window_tokens,
                "status": packet.status,
                "generated_at": packet.generated_at,
                "error_summary": (packet.error_summary or "")[:300],
            }
        )
    return statuses


def _errors_from_packets(packets: Iterable[ModelRunTelemetryPacket]) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    for packet in packets:
        if packet.status not in {"blocked", "failed"} and not packet.error_summary:
            continue
        errors.append(
            {
                "run_id": packet.run_id,
                "provider": packet.provider,
                "route": packet.route,
                "status": packet.status,
                "error_summary": (packet.error_summary or "route blocked")[:300],
            }
        )
    return errors


def _operator_summary(report: dict, blocked_routes: list[dict[str, object]]) -> str:
    packet_count = int(report.get("packet_count") or 0)
    resolved = int(report.get("resolved_model_run_count") or 0)
    spend = str(report.get("estimated_cost_total_usd") or "0.0000")
    historical_blocked_count = int(report.get("historical_blocked_route_count") or 0)
    if blocked_routes:
        route_names = ", ".join(str(item["route"]) for item in blocked_routes[:3])
        first_detail = str(blocked_routes[0].get("plain_english") or "").strip()
        detail = f" {first_detail}" if first_detail else ""
        return (
            f"Model routes are safe but not fully ready: {len(blocked_routes)} route(s) "
            f"blocked ({route_names}).{detail} Resolved runs: {resolved}/{packet_count}. "
            f"Estimated spend: ${spend}. Keep using deterministic/free fallback until a route is ready."
        )
    if historical_blocked_count:
        return (
            f"Current model routes have no blocked helper lanes; historical telemetry still has "
            f"{historical_blocked_count} route(s) with old blocked packets. Resolved runs: "
            f"{resolved}/{packet_count}. Estimated spend: ${spend}."
        )
    if resolved == 0 and packet_count:
        return (
            f"Model routes have {packet_count} packet(s), but none are resolved yet. "
            f"Estimated spend: ${spend}. Keep collecting outcomes before upgrading."
        )
    return (
        f"Model telemetry has {packet_count} packet(s), {resolved} resolved, "
        f"and estimated spend ${spend}."
    )


def _forecast_refs_for_packet(packet: ModelRunTelemetryPacket) -> list[str]:
    refs = list(packet.source_refs or [])
    freshness_refs = packet.freshness.get("agent_forecast_refs") if isinstance(packet.freshness, dict) else None
    if isinstance(freshness_refs, list):
        refs.extend(str(ref) for ref in freshness_refs if str(ref).strip())
    return refs


def _latest_resolved_at(forecasts: Sequence[AgentForecast]) -> str | None:
    resolved_at = [forecast.resolved_at for forecast in forecasts if forecast.resolved_at]
    return sorted(resolved_at)[-1] if resolved_at else None


def label_model_telemetry_from_agent_outcomes(
    packets: Sequence[ModelRunTelemetryPacket],
    forecasts: Sequence[AgentForecast],
) -> list[ModelRunTelemetryPacket]:
    """Label model runs using already-resolved Agent Intelligence forecasts.

    The function is deliberately conservative: a model packet is updated only
    when it explicitly references resolved forecast ids. Unreferenced packets
    stay pending/unresolved so optional model lanes do not become false blockers.
    """

    resolved_by_id = {
        forecast.forecast_id: forecast
        for forecast in forecasts
        if forecast.resolved and forecast.outcome is not None
    }
    labeled: list[ModelRunTelemetryPacket] = []
    for packet in packets:
        refs = _forecast_refs_for_packet(packet)
        matched = [resolved_by_id[ref] for ref in refs if ref in resolved_by_id]
        if not matched:
            labeled.append(packet)
            continue
        wins = sum(1 for forecast in matched if forecast.outcome is True)
        misses = sum(1 for forecast in matched if forecast.outcome is False)
        total = max(len(matched), 1)
        score = round((wins - misses) / total, 3)
        if wins and not misses:
            usefulness_label = "useful"
            outcome_label = "helped"
        elif misses and not wins:
            usefulness_label = "harmful"
            outcome_label = "hurt"
        else:
            usefulness_label = "mixed"
            outcome_label = "neutral"
        freshness = dict(packet.freshness or {})
        freshness["agent_forecast_refs"] = refs
        freshness["resolved_forecast_count"] = len(matched)
        freshness["forecast_win_count"] = wins
        freshness["forecast_miss_count"] = misses
        labeled.append(
            packet.model_copy(
                update={
                    "usefulness_label": usefulness_label,
                    "outcome_label": outcome_label,
                    "quality_score": score,
                    "outcome_notes": (
                        f"Resolved from {len(matched)} referenced Agent Intelligence "
                        f"forecast(s): {wins} useful, {misses} harmful."
                    ),
                    "resolved_at": _latest_resolved_at(matched),
                    "freshness": freshness,
                }
            )
        )
    return labeled


def model_upgrade_recommendation(
    report: dict,
    *,
    min_comparable_runs: int = 20,
    min_useful_rate: float = 0.6,
    max_harmful_rate: float = 0.1,
) -> dict:
    """Recommend model-route posture from telemetry; never auto-arms paid routes."""
    packet_count = int(report.get("packet_count") or 0)
    usefulness = report.get("usefulness_counts") or {}
    outcomes = report.get("outcome_counts") or {}
    useful = int(usefulness.get("useful") or 0)
    harmful = int(usefulness.get("harmful") or 0) + int(outcomes.get("hurt") or 0)
    resolved = int(report.get("resolved_model_run_count") or 0)
    if packet_count < min_comparable_runs or resolved < min_comparable_runs:
        return {
            "state": "insufficient_history",
            "action": "keep_free_or_disabled_default",
            "reason": (
                f"needs at least {min_comparable_runs} comparable resolved runs before "
                "paid route changes are considered"
            ),
            "auto_upgrade_allowed": False,
        }
    useful_rate = useful / max(resolved, 1)
    harmful_rate = harmful / max(resolved, 1)
    if harmful_rate > max_harmful_rate:
        return {
            "state": "downgrade_or_disable",
            "action": "disable_or_downrank_route_until_reviewed",
            "reason": f"harmful/hurt rate {harmful_rate:.2f} exceeds cap {max_harmful_rate:.2f}",
            "useful_rate": round(useful_rate, 4),
            "harmful_rate": round(harmful_rate, 4),
            "auto_upgrade_allowed": False,
        }
    if useful_rate >= min_useful_rate:
        return {
            "state": "manual_experiment_candidate",
            "action": "eligible_for_human-approved_capped_experiment_only",
            "reason": f"useful rate {useful_rate:.2f} meets threshold {min_useful_rate:.2f}",
            "useful_rate": round(useful_rate, 4),
            "harmful_rate": round(harmful_rate, 4),
            "auto_upgrade_allowed": False,
        }
    return {
        "state": "keep_default",
        "action": "keep_free_or_disabled_default",
        "reason": f"useful rate {useful_rate:.2f} is below threshold {min_useful_rate:.2f}",
        "useful_rate": round(useful_rate, 4),
        "harmful_rate": round(harmful_rate, 4),
        "auto_upgrade_allowed": False,
    }


def summarize_model_telemetry(
    packets: Iterable[ModelRunTelemetryPacket],
    *,
    budget_limit_usd: Decimal | str | None = None,
) -> dict:
    seen: set[str] = set()
    unique_packets: list[ModelRunTelemetryPacket] = []
    for packet in packets:
        if packet.packet_id in seen:
            continue
        seen.add(packet.packet_id)
        unique_packets.append(packet)

    by_status: dict[str, int] = {}
    by_provider: dict[str, int] = {}
    by_route: dict[str, int] = {}
    by_usefulness: dict[str, int] = {}
    by_outcome: dict[str, int] = {}
    cost_by_usefulness: dict[str, Decimal] = {}
    error_count = 0
    resolved_model_run_count = 0
    total_input_tokens = 0
    total_output_tokens = 0
    total_cost = Decimal("0")
    latencies: list[float] = []
    quality_scores: list[float] = []
    errors: list[dict[str, str]] = []
    recent_outcomes: list[dict[str, str]] = []

    for packet in unique_packets:
        _counter_add(by_status, packet.status)
        _counter_add(by_provider, packet.provider or "unknown")
        _counter_add(by_route, packet.route or "unknown")
        usefulness = packet.usefulness_label or "unknown"
        outcome = packet.outcome_label or "unresolved"
        _counter_add(by_usefulness, usefulness)
        _counter_add(by_outcome, outcome)
        packet_cost = _decimal(packet.estimated_cost_usd)
        cost_by_usefulness[usefulness] = cost_by_usefulness.get(usefulness, Decimal("0")) + packet_cost
        total_input_tokens += int(packet.input_tokens or 0)
        total_output_tokens += int(packet.output_tokens or 0)
        total_cost += packet_cost
        if packet.latency_seconds is not None:
            latencies.append(float(packet.latency_seconds))
        if packet.quality_score is not None:
            quality_scores.append(float(packet.quality_score))
        if outcome not in {"unresolved", "not_evaluable"}:
            resolved_model_run_count += 1
            recent_outcomes.append(
                {
                    "run_id": packet.run_id,
                    "provider": packet.provider,
                    "route": packet.route,
                    "usefulness_label": usefulness,
                    "outcome_label": outcome,
                    "quality_score": str(packet.quality_score) if packet.quality_score is not None else "",
                    "outcome_notes": (packet.outcome_notes or "")[:300],
                }
            )
        if packet.error_summary:
            error_count += 1
            errors.append(
                {
                    "run_id": packet.run_id,
                    "provider": packet.provider,
                    "route": packet.route,
                    "status": packet.status,
                    "error_summary": packet.error_summary[:300],
                }
            )

    budget = _decimal(str(budget_limit_usd)) if budget_limit_usd is not None else None
    historical_blocked_routes = _blocked_route_summaries(errors)
    latest_by_route = _latest_route_packets(unique_packets)
    current_route_statuses = _current_route_statuses(latest_by_route)
    current_errors = _errors_from_packets(latest_by_route.values())
    blocked_routes = _blocked_route_summaries(current_errors)
    report = {
        "kind": "model_telemetry_report",
        "schema_version": "1.0.0",
        "generated_at": datetime.datetime.now(tz=UTC).isoformat(timespec="seconds"),
        "analysis_only": True,
        "packet_count": len(unique_packets),
        "status_counts": by_status,
        "provider_counts": by_provider,
        "route_counts": by_route,
        "usefulness_counts": by_usefulness,
        "outcome_counts": by_outcome,
        "resolved_model_run_count": resolved_model_run_count,
        "total_input_tokens": total_input_tokens,
        "total_output_tokens": total_output_tokens,
        "estimated_cost_total_usd": _money(total_cost),
        "cost_by_usefulness_usd": {
            label: _money(cost)
            for label, cost in sorted(cost_by_usefulness.items())
        },
        "budget_limit_usd": _money(budget) if budget is not None else None,
        "budget_remaining_usd": _money(max(budget - total_cost, Decimal("0"))) if budget is not None else None,
        "average_latency_seconds": round(sum(latencies) / len(latencies), 3) if latencies else None,
        "max_latency_seconds": max(latencies) if latencies else None,
        "average_quality_score": round(sum(quality_scores) / len(quality_scores), 3) if quality_scores else None,
        "error_count": error_count,
        "recent_errors": errors[-10:],
        "current_route_statuses": current_route_statuses,
        "blocked_route_summaries": blocked_routes,
        "historical_blocked_route_summaries": historical_blocked_routes,
        "historical_blocked_route_count": len(historical_blocked_routes),
        "recent_outcomes": recent_outcomes[-10:],
        "policy": {
            "can_trade": False,
            "purpose": "track model route quality, usefulness, outcomes, and cost before increasing paid usage",
        },
    }
    report["operator_summary"] = _operator_summary(report, blocked_routes)
    report["upgrade_recommendation"] = model_upgrade_recommendation(report)
    return report


def load_model_telemetry_packets(input_dir: str | Path) -> list[ModelRunTelemetryPacket]:
    path = Path(input_dir)
    if not path.exists():
        return []
    packets: list[ModelRunTelemetryPacket] = []
    for packet_path in sorted(path.glob("*.json")):
        try:
            payload = json.loads(packet_path.read_text(encoding="utf-8"))
            packets.append(ModelRunTelemetryPacket.model_validate(payload))
        except (OSError, json.JSONDecodeError, ValueError):
            continue
    return packets


def write_model_telemetry_report(report: dict, output_dir: str | Path) -> Path:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.datetime.now(tz=UTC).strftime("%Y%m%d-%H%M%S-%f")
    report_path = output_path / f"model-telemetry-report-{timestamp}.json"
    text = json.dumps(report, indent=2)
    report_path.write_text(text, encoding="utf-8")
    (output_path / "latest.json").write_text(text, encoding="utf-8")
    compact = compact_model_telemetry_report(report, raw_packet_path=report_path)
    compact_text = json.dumps(compact, indent=2, sort_keys=True)
    report_path.with_name(f"{report_path.stem}.compact.json").write_text(
        compact_text,
        encoding="utf-8",
    )
    (output_path / "latest-compact.json").write_text(compact_text, encoding="utf-8")
    return report_path


def compact_model_telemetry_report(
    report: dict,
    *,
    raw_packet_path: str | Path | None = None,
) -> dict[str, object]:
    recent_errors = [
        {
            key: item.get(key)
            for key in ("run_id", "provider", "route", "status", "error_summary")
            if isinstance(item, dict) and item.get(key) is not None
        }
        for item in (report.get("recent_errors") or [])[:10]
        if isinstance(item, dict)
    ]
    current_route_statuses = [
        {
            key: item.get(key)
            for key in (
                "route",
                "provider",
                "model",
                "context_window_tokens",
                "status",
                "generated_at",
                "error_summary",
            )
            if isinstance(item, dict)
            and (key == "context_window_tokens" or item.get(key) is not None)
        }
        for item in (report.get("current_route_statuses") or [])[:8]
        if isinstance(item, dict)
    ]
    blocked_route_summaries = [
        {
            key: item.get(key)
            for key in (
                "route",
                "provider",
                "blocked_count",
                "latest_error",
                "error_kind",
                "plain_english",
                "self_heal_actions",
            )
            if isinstance(item, dict) and item.get(key) is not None
        }
        for item in (report.get("blocked_route_summaries") or [])[:8]
        if isinstance(item, dict)
    ]
    return {
        "schema": "compact_model_telemetry_report_v1",
        "kind": report.get("kind", "model_telemetry_report"),
        "generated_at": report.get("generated_at"),
        "analysis_only": report.get("analysis_only") is True,
        "can_submit_orders": False,
        "packet_count": report.get("packet_count"),
        "status_counts": report.get("status_counts") or {},
        "provider_counts": report.get("provider_counts") or {},
        "route_counts": report.get("route_counts") or {},
        "usefulness_counts": report.get("usefulness_counts") or {},
        "outcome_counts": report.get("outcome_counts") or {},
        "resolved_model_run_count": report.get("resolved_model_run_count"),
        "total_input_tokens": report.get("total_input_tokens"),
        "total_output_tokens": report.get("total_output_tokens"),
        "estimated_cost_total_usd": report.get("estimated_cost_total_usd"),
        "budget_limit_usd": report.get("budget_limit_usd"),
        "budget_remaining_usd": report.get("budget_remaining_usd"),
        "average_latency_seconds": report.get("average_latency_seconds"),
        "max_latency_seconds": report.get("max_latency_seconds"),
        "average_quality_score": report.get("average_quality_score"),
        "error_count": report.get("error_count"),
        "recent_errors": recent_errors,
        "current_route_statuses": current_route_statuses,
        "blocked_route_summaries": blocked_route_summaries,
        "historical_blocked_route_count": report.get("historical_blocked_route_count"),
        "operator_summary": report.get("operator_summary"),
        "upgrade_recommendation": report.get("upgrade_recommendation") or {},
        "policy": {
            "can_trade": False,
            "purpose": "track model route quality, usefulness, outcomes, and cost before increasing paid usage",
        },
        "raw_packet_path": str(raw_packet_path) if raw_packet_path is not None else None,
        "next_open": "Open the raw model telemetry report for full recent outcomes or route details.",
    }
