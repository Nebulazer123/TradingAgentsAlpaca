"""Agent Intelligence brain packet.

The learning loop's organs each persist their own artifacts (ledger, label
quality, hypothesis store, advisory priors, lifecycle events). This module
fuses them into one compact, durable state packet — the thing a future agent
or operator reads *first* to start at altitude instead of re-crawling raw
results:

- ledger truth (counts, outcomes, label-quality tiers, trusted labels),
- earned influence weights,
- hypothesis state plus the append-only lifecycle tail,
- a maturity radar: when the next out-of-sample evidence arrives,
- fixed-vocabulary attention flags and ordered recommended actions.

Every source is read with an explicit ``ok | missing | malformed`` status and
the builder never raises. The packet is analysis-only: it can steer research
attention but carries no order, sizing, or gate authority.
"""

from __future__ import annotations

import datetime
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from tradingagents.evals.agent_intelligence_ledger import (
    DEFAULT_LEDGER_PATH,
    DEFAULT_SUMMARY_PATH as DEFAULT_AGENT_SUMMARY_PATH,
    LEDGER_FORBIDDEN_EFFECTS,
    load_ledger_with_stats,
    summarize_agent_scores,
)
from tradingagents.evals.hypothesis_factory import (
    DEFAULT_PRIORS_PATH as DEFAULT_RESEARCH_PRIORS_PATH,
    DEFAULT_STORE_PATH as DEFAULT_HYPOTHESIS_STORE_PATH,
    DEFAULT_SUMMARY_PATH as DEFAULT_HYPOTHESIS_SUMMARY_PATH,
    STATUS_INSUFFICIENT,
    STATUS_PREREGISTERED,
    STATUS_SUPPORTED,
    load_hypotheses_with_stats,
)
from tradingagents.evals.hypothesis_lifecycle import (
    DEFAULT_LIFECYCLE_PATH,
    load_lifecycle_events_with_stats,
    summarize_lifecycle,
)
from tradingagents.evals.resolution_quality import (
    DEFAULT_RESOLUTION_QUALITY_PATH,
    MINABLE_LABEL_QUALITIES,
)
from tradingagents.policy.io import atomic_write_text

UTC = datetime.timezone.utc

DEFAULT_BRAIN_PATH = Path("results/agent_intelligence/brain.json")

FLAG_SOURCES_DEGRADED = "context_sources_missing_or_malformed"
FLAG_LEDGER_MISSING = "ledger_missing"
FLAG_ALL_RESOLVED_SUSPECT = "all_resolved_labels_suspect"
FLAG_NO_TRUSTED_LABELS = "no_trusted_labels_yet"
FLAG_FEED_LAG = "deferrals_waiting_on_final_bars"
FLAG_DUE_FORECASTS = "due_forecasts_awaiting_resolution"
FLAG_PRIORS_ACTIVE = "supported_priors_active"
FLAG_AWAITING_OOS = "hypotheses_awaiting_out_of_sample_evidence"
FLAG_CORRUPT_LINES = "corrupt_artifact_lines_present"

_ACTIVE_HYPOTHESIS_STATUSES = (STATUS_PREREGISTERED, STATUS_INSUFFICIENT)


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


def _load_json_object(path: Path) -> tuple[dict[str, Any] | None, str]:
    if not path.exists():
        return None, "missing"
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None, "malformed"
    if not isinstance(loaded, dict):
        return None, "malformed"
    return loaded, "ok"


def _maturity_radar(
    forecasts: Sequence[Any],
    *,
    now_dt: datetime.datetime,
    horizon_days: int,
) -> dict[str, Any]:
    as_of_date = now_dt.date()
    horizon_end = as_of_date + datetime.timedelta(days=max(0, int(horizon_days)))
    due_unresolved = 0
    buckets: dict[str, int] = {}
    beyond_horizon = 0
    unparseable = 0
    future_dates: list[datetime.date] = []
    for forecast in forecasts:
        if forecast.resolved:
            continue
        try:
            matures = _as_utc(forecast.resolve_after)
        except (TypeError, ValueError):
            unparseable += 1
            continue
        if matures <= now_dt:
            due_unresolved += 1
            continue
        mature_date = matures.date()
        future_dates.append(mature_date)
        if mature_date <= horizon_end:
            key = mature_date.isoformat()
            buckets[key] = buckets.get(key, 0) + 1
        else:
            beyond_horizon += 1
    return {
        "as_of": as_of_date.isoformat(),
        "horizon_days": max(0, int(horizon_days)),
        "due_unresolved_count": due_unresolved,
        "due_dates": dict(sorted(buckets.items())),
        "beyond_horizon_pending_count": beyond_horizon,
        "next_maturity_date": min(future_dates).isoformat() if future_dates else None,
        "unparseable_maturity_count": unparseable,
    }


def build_agent_intelligence_brain(
    *,
    ledger_path: str | Path = DEFAULT_LEDGER_PATH,
    agent_summary_path: str | Path = DEFAULT_AGENT_SUMMARY_PATH,
    resolution_quality_path: str | Path = DEFAULT_RESOLUTION_QUALITY_PATH,
    hypothesis_store_path: str | Path = DEFAULT_HYPOTHESIS_STORE_PATH,
    hypothesis_summary_path: str | Path = DEFAULT_HYPOTHESIS_SUMMARY_PATH,
    research_priors_path: str | Path = DEFAULT_RESEARCH_PRIORS_PATH,
    lifecycle_path: str | Path = DEFAULT_LIFECYCLE_PATH,
    now: str | datetime.datetime | None = None,
    radar_horizon_days: int = 7,
    lifecycle_tail: int = 10,
) -> dict[str, Any]:
    """Fuse the learning loop's artifacts into one compact state packet.

    Never raises: every source degrades to an explicit status and the packet
    is always fully shaped, so downstream readers can rely on its keys.
    """

    now_dt = _as_utc(now)
    paths = {
        "ledger": Path(ledger_path),
        "agent_summary": Path(agent_summary_path),
        "resolution_quality": Path(resolution_quality_path),
        "hypothesis_store": Path(hypothesis_store_path),
        "hypothesis_summary": Path(hypothesis_summary_path),
        "research_priors": Path(research_priors_path),
        "lifecycle": Path(lifecycle_path),
    }
    statuses: dict[str, str] = {}

    forecasts, corrupt_ledger_lines = load_ledger_with_stats(paths["ledger"])
    statuses["ledger"] = "ok" if paths["ledger"].exists() else "missing"
    ledger_scores = summarize_agent_scores(forecasts)
    resolved_count = int(ledger_scores["resolved_forecast_count"])
    trusted_from_ledger = sum(
        1
        for forecast in forecasts
        if forecast.resolved and forecast.label_quality in MINABLE_LABEL_QUALITIES
    )
    suspect_from_ledger = int(ledger_scores["label_quality_counts"].get("suspect", 0))

    agent_summary, statuses["agent_summary"] = _load_json_object(paths["agent_summary"])
    influence_raw = (agent_summary or {}).get("influence_weights")
    agents_raw = (
        influence_raw.get("agents")
        if isinstance(influence_raw, Mapping) and isinstance(influence_raw.get("agents"), Mapping)
        else {}
    )
    influence_weights = {
        agent: str(item.get("weight", "1.00"))
        for agent, item in agents_raw.items()
        if isinstance(item, Mapping)
    }
    influence_states = {
        agent: str(item.get("state", "unknown"))
        for agent, item in agents_raw.items()
        if isinstance(item, Mapping)
    }

    quality_summary, statuses["resolution_quality"] = _load_json_object(
        paths["resolution_quality"]
    )
    quality = quality_summary or {}
    defer_reason_counts = (
        dict(quality.get("defer_reason_counts") or {})
        if isinstance(quality.get("defer_reason_counts"), Mapping)
        else {}
    )

    hypotheses, corrupt_store_lines = load_hypotheses_with_stats(paths["hypothesis_store"])
    statuses["hypothesis_store"] = "ok" if paths["hypothesis_store"].exists() else "missing"
    _, statuses["hypothesis_summary"] = _load_json_object(paths["hypothesis_summary"])
    hypothesis_status_counts: dict[str, int] = {}
    for hypothesis in hypotheses:
        hypothesis_status_counts[hypothesis.status] = (
            hypothesis_status_counts.get(hypothesis.status, 0) + 1
        )
    active_hypotheses = [
        {
            "hypothesis_id": hypothesis.hypothesis_id,
            "status": hypothesis.status,
            "context": dict(hypothesis.context),
            "preregistered_at": hypothesis.preregistered_at,
            "out_of_sample_count": hypothesis.out_of_sample_count,
            "min_out_of_sample": hypothesis.min_out_of_sample,
        }
        for hypothesis in hypotheses
        if hypothesis.status in _ACTIVE_HYPOTHESIS_STATUSES
    ]

    priors_packet, statuses["research_priors"] = _load_json_object(paths["research_priors"])
    prior_rows_raw = (priors_packet or {}).get("priors")
    prior_rows = [
        dict(row)
        for row in (prior_rows_raw if isinstance(prior_rows_raw, list) else [])
        if isinstance(row, Mapping)
    ]

    lifecycle_events, corrupt_lifecycle_lines = load_lifecycle_events_with_stats(
        paths["lifecycle"]
    )
    statuses["lifecycle"] = "ok" if paths["lifecycle"].exists() else "missing"
    lifecycle_summary = summarize_lifecycle(lifecycle_events)
    tail_count = max(0, int(lifecycle_tail))
    last_events = [
        {
            "event_id": event.event_id,
            "event_type": event.event_type,
            "hypothesis_id": event.hypothesis_id,
            "occurred_at": event.occurred_at,
            "to_status": event.to_status,
        }
        for event in (lifecycle_events[-tail_count:] if tail_count else [])
    ]

    radar = _maturity_radar(forecasts, now_dt=now_dt, horizon_days=radar_horizon_days)

    flags: list[str] = []
    if any(status != "ok" for status in statuses.values()):
        flags.append(FLAG_SOURCES_DEGRADED)
    if statuses["ledger"] == "missing":
        flags.append(FLAG_LEDGER_MISSING)
    if resolved_count and suspect_from_ledger == resolved_count:
        flags.append(FLAG_ALL_RESOLVED_SUSPECT)
    if resolved_count and trusted_from_ledger == 0:
        flags.append(FLAG_NO_TRUSTED_LABELS)
    if int(defer_reason_counts.get("final_bar_missing") or 0) > 0:
        flags.append(FLAG_FEED_LAG)
    if radar["due_unresolved_count"] > 0:
        flags.append(FLAG_DUE_FORECASTS)
    if prior_rows:
        flags.append(FLAG_PRIORS_ACTIVE)
    if active_hypotheses and not hypothesis_status_counts.get(STATUS_SUPPORTED):
        flags.append(FLAG_AWAITING_OOS)
    if corrupt_ledger_lines or corrupt_store_lines or corrupt_lifecycle_lines:
        flags.append(FLAG_CORRUPT_LINES)

    actions: list[str] = []
    if statuses["ledger"] == "missing":
        actions.append(
            "no forecast ledger found: run `python -m cli.main research agent-ledger-update "
            "--json-output` to convert the latest packets into scoreable forecasts"
        )
    if suspect_from_ledger:
        actions.append(
            f"run `python -m cli.main research ledger-quality-audit --json-output` — "
            f"{suspect_from_ledger} suspect label(s) re-measure and can heal once final bars land"
        )
    if radar["due_unresolved_count"]:
        actions.append(
            f"run `python -m cli.main research agent-ledger-resolve --json-output` — "
            f"{radar['due_unresolved_count']} mature forecast(s) await audited resolution"
        )
    actions.append(
        "run `python -m cli.main research hypothesis-factory --json-output` after resolving "
        "so verdicts, advisory priors, and lifecycle events stay current"
    )
    if prior_rows:
        actions.append(
            "verify the next overnight research context carries the supported prior(s) "
            "via its agent_intelligence_advisory packet"
        )

    return {
        "kind": "agent_intelligence_brain",
        "schema": "agent_intelligence_brain_v1",
        "generated_at": now_dt.isoformat(timespec="seconds"),
        "analysis_only": True,
        "can_submit_orders": False,
        "execution_authority": "none",
        "forbidden_effects": list(LEDGER_FORBIDDEN_EFFECTS),
        "source_paths": {name: str(path) for name, path in paths.items()},
        "source_statuses": statuses,
        "ledger": {
            "forecast_count": int(ledger_scores["forecast_count"]),
            "resolved_forecast_count": resolved_count,
            "pending_forecast_count": int(ledger_scores["forecast_count"]) - resolved_count,
            "corrupt_line_count": corrupt_ledger_lines,
            "outcome_counts": dict(ledger_scores["outcome_counts"]),
            "label_quality_counts": dict(ledger_scores["label_quality_counts"]),
            "trusted_label_count": trusted_from_ledger,
        },
        "influence": {
            "weights": influence_weights,
            "states": influence_states,
        },
        "resolution_quality": {
            "trusted_label_count": quality.get("trusted_label_count"),
            "report_count": quality.get("report_count"),
            "deferred_count": quality.get("deferred_count"),
            "not_mature_count": quality.get("not_mature_count"),
            "resolvable_count": quality.get("resolvable_count"),
            "defer_reason_counts": defer_reason_counts,
            "label_quality_counts": (
                dict(quality.get("label_quality_counts") or {})
                if isinstance(quality.get("label_quality_counts"), Mapping)
                else {}
            ),
        },
        "hypotheses": {
            "hypothesis_count": len(hypotheses),
            "status_counts": hypothesis_status_counts,
            "supported_count": hypothesis_status_counts.get(STATUS_SUPPORTED, 0),
            "prior_count": len(prior_rows),
            "corrupt_store_line_count": corrupt_store_lines,
            "active": active_hypotheses,
        },
        "research_priors": prior_rows,
        "lifecycle": {
            "event_count": lifecycle_summary["event_count"],
            "corrupt_line_count": corrupt_lifecycle_lines,
            "event_type_counts": lifecycle_summary["event_type_counts"],
            "last_events": last_events,
        },
        "maturity_radar": radar,
        "attention_flags": flags,
        "recommended_actions": actions,
        "advisory_note": (
            "Advisory only: this packet summarizes earned agent intelligence so future "
            "research starts at altitude. It cannot change live gates, position sizing, "
            "or order authority."
        ),
    }


def render_agent_intelligence_brain(brain: Mapping[str, Any]) -> str:
    """Render the brain packet as a compact human briefing."""

    ledger = brain.get("ledger") or {}
    quality = brain.get("resolution_quality") or {}
    hypotheses = brain.get("hypotheses") or {}
    radar = brain.get("maturity_radar") or {}
    influence = brain.get("influence") or {}
    weights = influence.get("weights") or {}
    states = influence.get("states") or {}
    lines = [
        f"Agent Intelligence Brain — generated {brain.get('generated_at')} "
        "(advisory only; execution authority: none)",
        f"Forecasts: {ledger.get('forecast_count', 0)} total | "
        f"resolved {ledger.get('resolved_forecast_count', 0)} | "
        f"pending {ledger.get('pending_forecast_count', 0)}",
        f"Trusted labels: {ledger.get('trusted_label_count', 0)} "
        f"(label quality {ledger.get('label_quality_counts') or {}}; "
        f"deferred {quality.get('deferred_count') or 0} awaiting data)",
    ]
    if weights:
        rendered_weights = ", ".join(
            f"{agent}={weights[agent]} ({states.get(agent, 'unknown')})"
            for agent in sorted(weights)
        )
        lines.append(f"Influence weights: {rendered_weights}")
    lines.append(
        f"Hypotheses: {hypotheses.get('hypothesis_count', 0)} "
        f"({hypotheses.get('status_counts') or {}}) | "
        f"supported priors: {hypotheses.get('prior_count', 0)}"
    )
    lines.append(
        f"Maturity radar: {radar.get('due_unresolved_count', 0)} due now; "
        f"next maturity {radar.get('next_maturity_date') or 'none scheduled'}; "
        f"{radar.get('beyond_horizon_pending_count', 0)} beyond the "
        f"{radar.get('horizon_days', 0)}-day horizon"
    )
    flags = brain.get("attention_flags") or []
    if flags:
        lines.append(f"Attention: {', '.join(flags)}")
    for index, action in enumerate(brain.get("recommended_actions") or [], start=1):
        lines.append(f"Next {index}: {action}")
    return "\n".join(lines)


def write_agent_intelligence_brain(
    brain: Mapping[str, Any],
    *,
    path: str | Path = DEFAULT_BRAIN_PATH,
) -> Path:
    return atomic_write_text(Path(path), json.dumps(dict(brain), indent=2, sort_keys=True))
