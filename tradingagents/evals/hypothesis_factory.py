"""Hypothesis Factory.

The factory turns resolved Agent Intelligence Ledger evidence into
preregistered research hypotheses, then judges each hypothesis only on
forecasts created strictly after its preregistration. In-sample pattern
mining can propose ideas, but no hypothesis can be "supported" by the same
data that suggested it.

Lifecycle:

1. ``mine_hypotheses`` scans resolved forecasts for context cells (agent,
   direction, setup, regime, sector, evidence type) whose accuracy deviates
   from the global baseline by at least ``edge_threshold``.
2. Each finding is preregistered with its in-sample evidence frozen at
   mining time.
3. ``evaluate_hypotheses`` re-scores every hypothesis using only resolved
   forecasts created after ``preregistered_at`` (out-of-sample), moving it to
   ``supported``, ``refuted``, or ``insufficient_out_of_sample``.
4. ``research_priors`` converts supported hypotheses into bounded advisory
   prior multipliers for future debate/context weighting.

Everything here is analysis-only. Priors may adjust research attention but
can never bypass live gates, risk limits, or order safety.
"""

from __future__ import annotations

import datetime
import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field, replace
from decimal import Decimal
from pathlib import Path
from typing import Any

from tradingagents.evals.agent_intelligence_ledger import (
    AgentForecast,
    load_ledger,
)
from tradingagents.evals.hypothesis_lifecycle import (
    append_lifecycle_events,
    hypothesis_lifecycle_events,
    load_lifecycle_events_with_stats,
)
from tradingagents.evals.resolution_quality import (
    LABEL_QUALITY_SUSPECT,
    MINABLE_LABEL_QUALITIES,
)
from tradingagents.policy.io import atomic_write_text

UTC = datetime.timezone.utc

DEFAULT_STORE_PATH = Path("results/hypothesis_factory/hypotheses.jsonl")
DEFAULT_PRIORS_PATH = Path("results/hypothesis_factory/priors.json")
DEFAULT_SUMMARY_PATH = Path("results/hypothesis_factory/summary.json")

DEFAULT_MIN_SAMPLE = 12
DEFAULT_EDGE_THRESHOLD = Decimal("0.15")
DEFAULT_MIN_OUT_OF_SAMPLE = 8
PRIOR_MULTIPLIER_FLOOR = Decimal("0.70")
PRIOR_MULTIPLIER_CEILING = Decimal("1.30")

STATUS_PREREGISTERED = "preregistered"
STATUS_SUPPORTED = "supported"
STATUS_REFUTED = "refuted"
STATUS_INSUFFICIENT = "insufficient_out_of_sample"

HYPOTHESIS_FORBIDDEN_EFFECTS = (
    "submit_order",
    "size_position",
    "waive_live_gate",
    "promote_sleeve",
    "ignore_risk_envelope",
)

CONTEXT_KEYS = ("agent", "direction", "setup", "regime", "sector")

# Cells are deterministic so re-mining the same ledger yields the same
# hypothesis ids. Each spec names the forecast attributes that define a cell.
CELL_SPECS: tuple[tuple[str, ...], ...] = (
    ("agent",),
    ("agent", "direction"),
    ("agent", "setup"),
    ("agent", "regime"),
    ("agent", "sector"),
    ("direction",),
    ("setup",),
    ("sector",),
)


@dataclass(frozen=True)
class ResearchHypothesis:
    hypothesis_id: str
    claim: str
    context: dict[str, str]
    comparison: str  # "underperforms_baseline" | "outperforms_baseline"
    source: str
    preregistered_at: str
    in_sample_count: int
    in_sample_accuracy: str
    in_sample_baseline_accuracy: str
    in_sample_average_brier: str
    min_out_of_sample: int
    edge_threshold: str
    status: str = STATUS_PREREGISTERED
    out_of_sample_count: int = 0
    out_of_sample_accuracy: str | None = None
    out_of_sample_baseline_accuracy: str | None = None
    out_of_sample_delta: str | None = None
    evaluated_at: str | None = None
    evaluation_note: str | None = None
    tags: list[str] = field(default_factory=list)
    analysis_only: bool = True
    execution_authority: str = "none"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _now_utc(value: str | datetime.datetime | None = None) -> datetime.datetime:
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


def _decimal(value: Any, default: str = "0") -> Decimal:
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal(default)


def _normalize(value: Any) -> str:
    return str(value or "").strip().lower().replace(" ", "_").replace("-", "_")


def _context_of(forecast: AgentForecast, keys: Sequence[str]) -> dict[str, str] | None:
    context: dict[str, str] = {}
    for key in keys:
        value = _normalize(getattr(forecast, key, ""))
        if not value or value == "unknown":
            return None
        context[key] = value
    return context


def _forecast_matches(forecast: AgentForecast, context: Mapping[str, str]) -> bool:
    return all(
        _normalize(getattr(forecast, key, "")) == _normalize(expected)
        for key, expected in context.items()
    )


def _hypothesis_id(context: Mapping[str, str], comparison: str) -> str:
    payload = json.dumps(
        {"context": dict(sorted(context.items())), "comparison": comparison},
        sort_keys=True,
    )
    return f"hyp-{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:16]}"


def _accuracy(forecasts: Sequence[AgentForecast]) -> Decimal | None:
    resolved = [f for f in forecasts if f.resolved and f.outcome is not None]
    if not resolved:
        return None
    wins = sum(1 for f in resolved if f.outcome)
    return (Decimal(wins) / Decimal(len(resolved))).quantize(Decimal("0.0001"))


def minable_forecasts(
    forecasts: Sequence[AgentForecast],
    *,
    require_audited_labels: bool = False,
) -> list[AgentForecast]:
    """Resolved forecasts whose labels the factory is allowed to learn from.

    ``suspect`` labels (window unverifiable, or the stored outcome disagrees
    with a recomputed audited window) are never evidence. With
    ``require_audited_labels`` the factory additionally refuses unaudited
    legacy labels, so it learns only from mechanically audited resolution
    windows.
    """

    minable: list[AgentForecast] = []
    for forecast in forecasts:
        if not forecast.resolved or forecast.outcome is None:
            continue
        quality = getattr(forecast, "label_quality", None)
        if quality == LABEL_QUALITY_SUSPECT:
            continue
        if require_audited_labels and quality not in MINABLE_LABEL_QUALITIES:
            continue
        minable.append(forecast)
    return minable


def _average_brier(forecasts: Sequence[AgentForecast]) -> Decimal | None:
    scores = [_decimal(f.brier_score) for f in forecasts if f.resolved and f.brier_score]
    if not scores:
        return None
    return (sum(scores) / Decimal(len(scores))).quantize(Decimal("0.0001"))


def _claim_text(context: Mapping[str, str], comparison: str, delta: Decimal) -> str:
    parts = ", ".join(f"{key}={value}" for key, value in sorted(context.items()))
    verb = "underperform" if comparison == "underperforms_baseline" else "outperform"
    return (
        f"Forecasts where {parts} {verb} the global resolved baseline "
        f"by {abs(delta)} accuracy points; treat as a calibration "
        f"{'downweight' if verb == 'underperform' else 'upweight'} candidate "
        "pending out-of-sample confirmation."
    )


def mine_hypotheses(
    forecasts: Sequence[AgentForecast],
    *,
    min_sample: int = DEFAULT_MIN_SAMPLE,
    edge_threshold: Decimal | str = DEFAULT_EDGE_THRESHOLD,
    now: datetime.datetime | str | None = None,
    source: str = "mined_from_resolution",
    require_audited_labels: bool = False,
) -> list[ResearchHypothesis]:
    """Propose preregistered hypotheses from resolved forecast evidence.

    Mining only looks at resolved forecasts whose labels pass the quality
    gate (suspect labels never count; with ``require_audited_labels`` only
    mechanically audited windows count). Findings are *suggestions*; every
    hypothesis starts ``preregistered`` and earns support strictly from
    forecasts created after this moment.
    """

    threshold = _decimal(edge_threshold, str(DEFAULT_EDGE_THRESHOLD))
    resolved = minable_forecasts(forecasts, require_audited_labels=require_audited_labels)
    baseline = _accuracy(resolved)
    if baseline is None:
        return []
    registered_at = _now_utc(now).isoformat(timespec="seconds")
    seen: set[str] = set()
    hypotheses: list[ResearchHypothesis] = []
    for spec in CELL_SPECS:
        cells: dict[tuple[tuple[str, str], ...], list[AgentForecast]] = {}
        for forecast in resolved:
            context = _context_of(forecast, spec)
            if context is None:
                continue
            cells.setdefault(tuple(sorted(context.items())), []).append(forecast)
        for cell_key in sorted(cells):
            members = cells[cell_key]
            if len(members) < max(1, int(min_sample)):
                continue
            cell_accuracy = _accuracy(members)
            if cell_accuracy is None:
                continue
            delta = (cell_accuracy - baseline).quantize(Decimal("0.0001"))
            if abs(delta) < threshold:
                continue
            comparison = (
                "underperforms_baseline" if delta < 0 else "outperforms_baseline"
            )
            context = dict(cell_key)
            hypothesis_id = _hypothesis_id(context, comparison)
            if hypothesis_id in seen:
                continue
            seen.add(hypothesis_id)
            brier = _average_brier(members)
            hypotheses.append(
                ResearchHypothesis(
                    hypothesis_id=hypothesis_id,
                    claim=_claim_text(context, comparison, delta),
                    context=context,
                    comparison=comparison,
                    source=source,
                    preregistered_at=registered_at,
                    in_sample_count=len(members),
                    in_sample_accuracy=str(cell_accuracy),
                    in_sample_baseline_accuracy=str(baseline),
                    in_sample_average_brier=str(brier) if brier is not None else "",
                    min_out_of_sample=DEFAULT_MIN_OUT_OF_SAMPLE,
                    edge_threshold=str(threshold),
                    tags=[f"cell:{'+'.join(spec)}"],
                )
            )
    return hypotheses


def load_hypotheses_with_stats(
    path: str | Path = DEFAULT_STORE_PATH,
) -> tuple[list[ResearchHypothesis], int]:
    """Load the hypothesis store and report corrupt-line counts."""

    store_path = Path(path)
    if not store_path.exists():
        return [], 0
    records: list[ResearchHypothesis] = []
    corrupt_line_count = 0
    for line in store_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            records.append(ResearchHypothesis(**json.loads(line)))
        except (json.JSONDecodeError, TypeError, ValueError):
            corrupt_line_count += 1
            continue
    return records, corrupt_line_count


def load_hypotheses(path: str | Path = DEFAULT_STORE_PATH) -> list[ResearchHypothesis]:
    return load_hypotheses_with_stats(path)[0]


def write_hypotheses(
    hypotheses: Sequence[ResearchHypothesis],
    *,
    path: str | Path = DEFAULT_STORE_PATH,
) -> Path:
    text = "\n".join(json.dumps(h.as_dict(), sort_keys=True) for h in hypotheses)
    return atomic_write_text(Path(path), (text + "\n") if text else "")


def merge_hypotheses(
    existing: Sequence[ResearchHypothesis],
    candidates: Iterable[ResearchHypothesis],
) -> tuple[list[ResearchHypothesis], int]:
    """Merge newly mined candidates into the store without re-registration.

    An existing hypothesis keeps its original ``preregistered_at`` and status;
    re-mining the same pattern must never reset its out-of-sample clock.
    """

    merged = list(existing)
    known = {h.hypothesis_id for h in existing}
    appended = 0
    for candidate in candidates:
        if candidate.hypothesis_id in known:
            continue
        merged.append(candidate)
        known.add(candidate.hypothesis_id)
        appended += 1
    return merged, appended


def evaluate_hypotheses(
    hypotheses: Sequence[ResearchHypothesis],
    forecasts: Sequence[AgentForecast],
    *,
    now: datetime.datetime | str | None = None,
    require_audited_labels: bool = False,
) -> list[ResearchHypothesis]:
    """Re-judge every hypothesis using only post-preregistration evidence.

    Statuses are recomputed on each run as more forecasts resolve; a
    hypothesis can move between supported/refuted as out-of-sample evidence
    accumulates, and the full trail stays in the store. Out-of-sample
    evidence passes the same label-quality gate as mining.
    """

    evaluated_at = _now_utc(now).isoformat(timespec="seconds")
    resolved = minable_forecasts(forecasts, require_audited_labels=require_audited_labels)
    results: list[ResearchHypothesis] = []
    for hypothesis in hypotheses:
        registered = _now_utc(hypothesis.preregistered_at)
        out_of_sample = [
            f for f in resolved if _now_utc(f.created_at) > registered
        ]
        matching = [
            f for f in out_of_sample if _forecast_matches(f, hypothesis.context)
        ]
        if len(matching) < max(1, int(hypothesis.min_out_of_sample)):
            results.append(
                replace(
                    hypothesis,
                    status=STATUS_INSUFFICIENT
                    if matching or hypothesis.status != STATUS_PREREGISTERED
                    else STATUS_PREREGISTERED,
                    out_of_sample_count=len(matching),
                    evaluated_at=evaluated_at,
                    evaluation_note=(
                        f"only {len(matching)} matching resolved forecasts created "
                        f"after preregistration; need {hypothesis.min_out_of_sample}"
                    ),
                )
            )
            continue
        oos_accuracy = _accuracy(matching)
        oos_baseline = _accuracy(out_of_sample)
        if oos_accuracy is None or oos_baseline is None:
            results.append(hypothesis)
            continue
        delta = (oos_accuracy - oos_baseline).quantize(Decimal("0.0001"))
        threshold = _decimal(hypothesis.edge_threshold, str(DEFAULT_EDGE_THRESHOLD))
        persistence_bar = threshold / Decimal("2")
        if hypothesis.comparison == "underperforms_baseline":
            persists = delta <= -persistence_bar
        else:
            persists = delta >= persistence_bar
        results.append(
            replace(
                hypothesis,
                status=STATUS_SUPPORTED if persists else STATUS_REFUTED,
                out_of_sample_count=len(matching),
                out_of_sample_accuracy=str(oos_accuracy),
                out_of_sample_baseline_accuracy=str(oos_baseline),
                out_of_sample_delta=str(delta),
                evaluated_at=evaluated_at,
                evaluation_note=(
                    "effect persisted out of sample at >= half the edge threshold"
                    if persists
                    else "effect did not persist out of sample"
                ),
            )
        )
    return results


def _clamp(value: Decimal, floor: Decimal, ceiling: Decimal) -> Decimal:
    return max(floor, min(ceiling, value))


def research_priors(hypotheses: Sequence[ResearchHypothesis]) -> dict[str, Any]:
    """Convert supported hypotheses into bounded advisory prior multipliers."""

    priors: list[dict[str, Any]] = []
    for hypothesis in hypotheses:
        if hypothesis.status != STATUS_SUPPORTED:
            continue
        delta = _decimal(hypothesis.out_of_sample_delta, "0")
        multiplier = _clamp(
            Decimal("1.00") + delta,
            PRIOR_MULTIPLIER_FLOOR,
            PRIOR_MULTIPLIER_CEILING,
        ).quantize(Decimal("0.01"))
        priors.append(
            {
                "hypothesis_id": hypothesis.hypothesis_id,
                "context": dict(hypothesis.context),
                "comparison": hypothesis.comparison,
                "multiplier": str(multiplier),
                "out_of_sample_count": hypothesis.out_of_sample_count,
                "out_of_sample_delta": hypothesis.out_of_sample_delta,
                "guidance": hypothesis.claim,
            }
        )
    return {
        "kind": "research_priors",
        "prior_count": len(priors),
        "priors": priors,
        "multiplier_floor": str(PRIOR_MULTIPLIER_FLOOR),
        "multiplier_ceiling": str(PRIOR_MULTIPLIER_CEILING),
        "analysis_only": True,
        "can_submit_orders": False,
        "execution_authority": "none",
        "forbidden_effects": list(HYPOTHESIS_FORBIDDEN_EFFECTS),
    }


def render_research_priors_context(packet: Mapping[str, Any]) -> str:
    priors = packet.get("priors") or []
    if not priors:
        return (
            "Hypothesis Factory: no out-of-sample supported research priors yet; "
            "use neutral weighting."
        )
    lines = [
        "Hypothesis Factory research priors are advisory only.",
        "They may adjust research attention, never live gates or order safety.",
    ]
    for prior in priors:
        context = prior.get("context") or {}
        parts = ", ".join(f"{key}={value}" for key, value in sorted(context.items()))
        lines.append(
            f"- [{prior.get('multiplier')}] {parts}: {prior.get('guidance')}"
        )
    return "\n".join(lines)


def summarize_hypotheses(hypotheses: Sequence[ResearchHypothesis]) -> dict[str, Any]:
    status_counts: dict[str, int] = {}
    for hypothesis in hypotheses:
        status_counts[hypothesis.status] = status_counts.get(hypothesis.status, 0) + 1
    return {
        "kind": "hypothesis_factory_summary",
        "hypothesis_count": len(hypotheses),
        "status_counts": status_counts,
        "supported": [
            h.as_dict() for h in hypotheses if h.status == STATUS_SUPPORTED
        ],
        "analysis_only": True,
        "can_submit_orders": False,
        "execution_authority": "none",
        "forbidden_effects": list(HYPOTHESIS_FORBIDDEN_EFFECTS),
    }


def run_hypothesis_factory(
    *,
    ledger_path: str | Path,
    store_path: str | Path = DEFAULT_STORE_PATH,
    priors_path: str | Path = DEFAULT_PRIORS_PATH,
    summary_path: str | Path = DEFAULT_SUMMARY_PATH,
    lifecycle_path: str | Path | None = None,
    min_sample: int = DEFAULT_MIN_SAMPLE,
    edge_threshold: Decimal | str = DEFAULT_EDGE_THRESHOLD,
    now: datetime.datetime | str | None = None,
    require_audited_labels: bool = True,
) -> dict[str, Any]:
    """One-shot mine -> merge -> evaluate -> persist cycle for automations.

    The production default learns only from labels with mechanically audited
    resolution windows; suspect labels are always excluded. Every status
    transition (and prior emission/retraction) is appended to the append-only
    lifecycle ledger, which lives next to the hypothesis store unless
    ``lifecycle_path`` overrides it.
    """

    lifecycle_store = (
        Path(lifecycle_path)
        if lifecycle_path is not None
        else Path(store_path).with_name("lifecycle.jsonl")
    )
    forecasts = load_ledger(ledger_path)
    existing, corrupt_store_line_count = load_hypotheses_with_stats(store_path)
    resolved = [f for f in forecasts if f.resolved and f.outcome is not None]
    minable = minable_forecasts(forecasts, require_audited_labels=require_audited_labels)
    excluded_suspect_count = sum(
        1 for f in resolved if getattr(f, "label_quality", None) == LABEL_QUALITY_SUSPECT
    )
    excluded_unaudited_count = len(resolved) - excluded_suspect_count - len(minable)
    mined = mine_hypotheses(
        forecasts,
        min_sample=min_sample,
        edge_threshold=edge_threshold,
        now=now,
        require_audited_labels=require_audited_labels,
    )
    merged, appended = merge_hypotheses(existing, mined)
    evaluated = evaluate_hypotheses(
        merged,
        forecasts,
        now=now,
        require_audited_labels=require_audited_labels,
    )
    write_hypotheses(evaluated, path=store_path)
    priors = research_priors(evaluated)
    known_events, corrupt_lifecycle_line_count = load_lifecycle_events_with_stats(lifecycle_store)
    lifecycle_events = hypothesis_lifecycle_events(
        existing,
        evaluated,
        evaluated_at=_now_utc(now).isoformat(timespec="seconds"),
        known_events=known_events,
        prior_multipliers={
            str(row["hypothesis_id"]): str(row["multiplier"]) for row in priors["priors"]
        },
    )
    lifecycle_appended_count = append_lifecycle_events(lifecycle_events, path=lifecycle_store)
    lifecycle_event_type_counts: dict[str, int] = {}
    for event in lifecycle_events:
        lifecycle_event_type_counts[event.event_type] = (
            lifecycle_event_type_counts.get(event.event_type, 0) + 1
        )
    atomic_write_text(Path(priors_path), json.dumps(priors, indent=2, sort_keys=True))
    summary = summarize_hypotheses(evaluated)
    atomic_write_text(Path(summary_path), json.dumps(summary, indent=2, sort_keys=True))
    return {
        "analysis_only": True,
        "can_submit_orders": False,
        "execution_authority": "none",
        "forbidden_effects": list(HYPOTHESIS_FORBIDDEN_EFFECTS),
        "ledger_path": str(ledger_path),
        "store_path": str(store_path),
        "priors_path": str(priors_path),
        "summary_path": str(summary_path),
        "lifecycle_path": str(lifecycle_store),
        "lifecycle_appended_event_count": lifecycle_appended_count,
        "lifecycle_total_event_count": len(known_events) + lifecycle_appended_count,
        "lifecycle_event_type_counts": lifecycle_event_type_counts,
        "corrupt_lifecycle_line_count": corrupt_lifecycle_line_count,
        "forecast_count": len(forecasts),
        "resolved_forecast_count": len(resolved),
        "require_audited_labels": require_audited_labels,
        "minable_forecast_count": len(minable),
        "excluded_suspect_count": excluded_suspect_count,
        "excluded_unaudited_count": excluded_unaudited_count,
        "corrupt_store_line_count": corrupt_store_line_count,
        "mined_count": len(mined),
        "appended_count": appended,
        "hypothesis_count": len(evaluated),
        "status_counts": summary["status_counts"],
        "prior_count": priors["prior_count"],
        "priors_context": render_research_priors_context(priors),
    }
