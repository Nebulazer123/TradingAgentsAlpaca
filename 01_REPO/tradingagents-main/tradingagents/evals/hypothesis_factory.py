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
import fcntl
import hashlib
import json
import os
import re
import stat
from collections.abc import Callable, Iterable, Mapping, Sequence
from contextlib import contextmanager, suppress
from dataclasses import asdict, dataclass, field, replace
from decimal import Decimal
from pathlib import Path
from typing import Any

from tradingagents.evals.agent_intelligence_ledger import (
    AgentForecast,
    load_ledger,
)
from tradingagents.evals.hypothesis_lifecycle import (
    HypothesisLifecycleEvent,
    append_lifecycle_events,
    hypothesis_lifecycle_events,
    load_lifecycle_events_with_stats,
)
from tradingagents.evals.learning_availability import observe_lifecycle_events
from tradingagents.evals.resolution_quality import (
    LABEL_QUALITY_SUSPECT,
    MINABLE_LABEL_QUALITIES,
)
from tradingagents.policy.io import atomic_write_text

UTC = datetime.timezone.utc

DEFAULT_STORE_PATH = Path("results/hypothesis_factory/hypotheses.jsonl")
DEFAULT_PRIORS_PATH = Path("results/hypothesis_factory/priors.json")
DEFAULT_SUMMARY_PATH = Path("results/hypothesis_factory/summary.json")
DEFAULT_LEARNING_AVAILABILITY_ROOT = Path("results/learning_availability")
PENDING_HYPOTHESIS_TRANSACTION_SCHEMA_VERSION = 1

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

_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_LOWER_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_PENDING_FIELDS = frozenset(
    {
        "schema_version",
        "transaction_id",
        "semantic_now",
        "store_path",
        "lifecycle_path",
        "availability_root",
        "priors_path",
        "summary_path",
        "base_store_sha256",
        "evaluated_store_sha256",
        "evaluated",
        "lifecycle_events",
        "metrics",
        "analysis_only",
        "execution_authority",
        "can_submit_orders",
    }
)
_PENDING_METRIC_FIELDS = frozenset(
    {
        "forecast_count",
        "resolved_forecast_count",
        "require_audited_labels",
        "minable_forecast_count",
        "excluded_suspect_count",
        "excluded_unaudited_count",
        "corrupt_store_line_count",
        "mined_count",
        "appended_count",
    }
)


class PendingHypothesisTransactionError(ValueError):
    """A durable hypothesis transaction cannot be validated or resumed."""

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


def _hypotheses_bytes(hypotheses: Sequence[ResearchHypothesis]) -> bytes:
    text = "\n".join(json.dumps(h.as_dict(), sort_keys=True) for h in hypotheses)
    return ((text + "\n") if text else "").encode("utf-8")


def write_hypotheses(
    hypotheses: Sequence[ResearchHypothesis],
    *,
    path: str | Path = DEFAULT_STORE_PATH,
) -> Path:
    return atomic_write_text(
        Path(path),
        _hypotheses_bytes(hypotheses).decode("utf-8"),
    )


def _canonical_pending_json(payload: Mapping[str, Any]) -> bytes:
    try:
        return json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise PendingHypothesisTransactionError(
            "pending transaction must contain canonical JSON values"
        ) from exc


def _normalized_output_path(path: str | Path) -> Path:
    return Path(os.path.abspath(os.fspath(Path(path).expanduser())))


def _safe_sidecar_path(store_path: str | Path, *, suffix: str) -> Path:
    store = _normalized_output_path(store_path)
    if store.name in {"", ".", ".."}:
        raise PendingHypothesisTransactionError(
            "hypothesis store path has no safe filename"
        )
    return store.with_name(f".{store.name}.{suffix}")


def _pending_transaction_path(store_path: str | Path) -> Path:
    return _safe_sidecar_path(
        store_path,
        suffix="learning.pending.json",
    )


def _factory_lock_path(store_path: str | Path) -> Path:
    return _safe_sidecar_path(
        store_path,
        suffix="learning.lock",
    )


def _fsync_directory_path(path: Path) -> None:
    try:
        state = path.lstat()
    except OSError as exc:
        raise PendingHypothesisTransactionError(
            "hypothesis output directory could not be inspected"
        ) from exc
    if stat.S_ISLNK(state.st_mode) or not stat.S_ISDIR(state.st_mode):
        raise PendingHypothesisTransactionError(
            "hypothesis output directory must be a real directory"
        )
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | _NOFOLLOW,
        )
    except OSError as exc:
        raise PendingHypothesisTransactionError(
            "hypothesis output directory could not be opened safely"
        ) from exc
    try:
        try:
            if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
                raise OSError("directory descriptor is invalid")
            os.fsync(descriptor)
        except OSError as exc:
            raise PendingHypothesisTransactionError(
                "hypothesis output directory could not be made durable"
            ) from exc
    finally:
        os.close(descriptor)


@contextmanager
def _hypothesis_factory_lock(store_path: str | Path):
    lock_path = _factory_lock_path(store_path)
    try:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        parent_state = lock_path.parent.lstat()
    except OSError as exc:
        raise PendingHypothesisTransactionError(
            "hypothesis output directory could not be created safely"
        ) from exc
    if stat.S_ISLNK(parent_state.st_mode) or not stat.S_ISDIR(
        parent_state.st_mode
    ):
        raise PendingHypothesisTransactionError(
            "hypothesis output directory must be a real directory"
        )
    try:
        lock_state = lock_path.lstat()
    except FileNotFoundError:
        lock_state = None
    except OSError as exc:
        raise PendingHypothesisTransactionError(
            "hypothesis factory lock could not be inspected"
        ) from exc
    if lock_state is not None and (
        stat.S_ISLNK(lock_state.st_mode)
        or not stat.S_ISREG(lock_state.st_mode)
    ):
        raise PendingHypothesisTransactionError(
            "hypothesis factory lock must be a regular file"
        )
    try:
        descriptor = os.open(
            lock_path,
            os.O_CREAT | os.O_RDWR | _NOFOLLOW,
            0o600,
        )
    except OSError as exc:
        raise PendingHypothesisTransactionError(
            "hypothesis factory lock could not be opened safely"
        ) from exc
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise OSError("lock descriptor is invalid")
        if lock_state is None:
            _fsync_directory_path(lock_path.parent)
        fcntl.flock(descriptor, fcntl.LOCK_EX)
    except OSError as exc:
        os.close(descriptor)
        raise PendingHypothesisTransactionError(
            "hypothesis factory lock failed"
        ) from exc
    try:
        yield
    finally:
        with suppress(OSError):
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _store_bytes(path: str | Path) -> bytes:
    store = Path(path)
    try:
        state = store.lstat()
    except FileNotFoundError:
        return b""
    except OSError as exc:
        raise PendingHypothesisTransactionError(
            "hypothesis store could not be inspected safely"
        ) from exc
    if stat.S_ISLNK(state.st_mode) or not stat.S_ISREG(state.st_mode):
        raise PendingHypothesisTransactionError(
            "hypothesis store must be a regular file"
        )
    try:
        return store.read_bytes()
    except OSError as exc:
        raise PendingHypothesisTransactionError(
            "hypothesis store could not be read safely"
        ) from exc


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _strict_utc_seconds(value: Any, *, field_name: str) -> datetime.datetime:
    if not isinstance(value, str):
        raise PendingHypothesisTransactionError(
            f"{field_name} must be canonical UTC seconds"
        )
    try:
        parsed = datetime.datetime.fromisoformat(value)
    except ValueError as exc:
        raise PendingHypothesisTransactionError(
            f"{field_name} must be canonical UTC seconds"
        ) from exc
    if (
        parsed.tzinfo is None
        or parsed.utcoffset() != datetime.timedelta(0)
        or parsed.microsecond != 0
    ):
        raise PendingHypothesisTransactionError(
            f"{field_name} must be canonical UTC seconds"
        )
    normalized = parsed.astimezone(UTC)
    if normalized.isoformat(timespec="seconds") != value:
        raise PendingHypothesisTransactionError(
            f"{field_name} must be canonical UTC seconds"
        )
    return normalized


def _pending_bindings(
    *,
    store_path: str | Path,
    lifecycle_path: str | Path,
    availability_root: str | Path,
    priors_path: str | Path,
    summary_path: str | Path,
) -> dict[str, str]:
    return {
        "store_path": str(_normalized_output_path(store_path)),
        "lifecycle_path": str(_normalized_output_path(lifecycle_path)),
        "availability_root": str(
            _normalized_output_path(availability_root)
        ),
        "priors_path": str(_normalized_output_path(priors_path)),
        "summary_path": str(_normalized_output_path(summary_path)),
    }


def _build_pending_transaction(
    *,
    semantic_now: datetime.datetime,
    store_path: str | Path,
    lifecycle_path: str | Path,
    availability_root: str | Path,
    priors_path: str | Path,
    summary_path: str | Path,
    evaluated: Sequence[ResearchHypothesis],
    lifecycle_events: Sequence[HypothesisLifecycleEvent],
    metrics: Mapping[str, Any],
) -> dict[str, Any]:
    if set(metrics) != _PENDING_METRIC_FIELDS:
        raise PendingHypothesisTransactionError(
            "pending transaction metrics do not match the schema"
        )
    core = {
        "schema_version": PENDING_HYPOTHESIS_TRANSACTION_SCHEMA_VERSION,
        "semantic_now": semantic_now.isoformat(timespec="seconds"),
        **_pending_bindings(
            store_path=store_path,
            lifecycle_path=lifecycle_path,
            availability_root=availability_root,
            priors_path=priors_path,
            summary_path=summary_path,
        ),
        "base_store_sha256": _sha256(_store_bytes(store_path)),
        "evaluated_store_sha256": _sha256(_hypotheses_bytes(evaluated)),
        "evaluated": [item.as_dict() for item in evaluated],
        "lifecycle_events": [event.as_dict() for event in lifecycle_events],
        "metrics": dict(metrics),
        "analysis_only": True,
        "execution_authority": "none",
        "can_submit_orders": False,
    }
    return {
        **core,
        "transaction_id": f"hpt-{_sha256(_canonical_pending_json(core))}",
    }


def _write_pending_transaction(
    store_path: str | Path,
    transaction: Mapping[str, Any],
) -> Path:
    path = _pending_transaction_path(store_path)
    try:
        state = path.lstat()
    except FileNotFoundError:
        state = None
    except OSError as exc:
        raise PendingHypothesisTransactionError(
            "pending transaction could not be inspected"
        ) from exc
    if state is not None and (
        stat.S_ISLNK(state.st_mode) or not stat.S_ISREG(state.st_mode)
    ):
        raise PendingHypothesisTransactionError(
            "pending transaction must be a regular file"
        )
    payload = _canonical_pending_json(transaction)
    atomic_write_text(path, payload.decode("utf-8"))
    try:
        written_state = path.lstat()
        written = path.read_bytes()
    except OSError as exc:
        raise PendingHypothesisTransactionError(
            "pending transaction could not be verified"
        ) from exc
    if (
        stat.S_ISLNK(written_state.st_mode)
        or not stat.S_ISREG(written_state.st_mode)
        or written != payload
    ):
        raise PendingHypothesisTransactionError(
            "pending transaction durability verification failed"
        )
    return path


def _load_pending_transaction(
    *,
    store_path: str | Path,
    lifecycle_path: str | Path,
    availability_root: str | Path,
    priors_path: str | Path,
    summary_path: str | Path,
) -> dict[str, Any] | None:
    path = _pending_transaction_path(store_path)
    try:
        state = path.lstat()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise PendingHypothesisTransactionError(
            "pending transaction could not be inspected"
        ) from exc
    if stat.S_ISLNK(state.st_mode) or not stat.S_ISREG(state.st_mode):
        raise PendingHypothesisTransactionError(
            "pending transaction must be a regular file"
        )
    try:
        raw = path.read_bytes()
        decoded = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PendingHypothesisTransactionError(
            "pending transaction is malformed"
        ) from exc
    if not isinstance(decoded, Mapping) or set(decoded) != _PENDING_FIELDS:
        raise PendingHypothesisTransactionError(
            "pending transaction fields do not match the schema"
        )
    if _canonical_pending_json(decoded) != raw:
        raise PendingHypothesisTransactionError(
            "pending transaction bytes are noncanonical"
        )
    if (
        type(decoded["schema_version"]) is not int
        or decoded["schema_version"]
        != PENDING_HYPOTHESIS_TRANSACTION_SCHEMA_VERSION
        or decoded["analysis_only"] is not True
        or decoded["execution_authority"] != "none"
        or decoded["can_submit_orders"] is not False
    ):
        raise PendingHypothesisTransactionError(
            "pending transaction authority or schema is invalid"
        )
    core = dict(decoded)
    transaction_id = core.pop("transaction_id")
    expected_id = f"hpt-{_sha256(_canonical_pending_json(core))}"
    if transaction_id != expected_id:
        raise PendingHypothesisTransactionError(
            "pending transaction digest mismatch"
        )
    expected_bindings = _pending_bindings(
        store_path=store_path,
        lifecycle_path=lifecycle_path,
        availability_root=availability_root,
        priors_path=priors_path,
        summary_path=summary_path,
    )
    if any(decoded[key] != value for key, value in expected_bindings.items()):
        raise PendingHypothesisTransactionError(
            "pending transaction output bindings changed"
        )
    for field_name in ("base_store_sha256", "evaluated_store_sha256"):
        if (
            not isinstance(decoded[field_name], str)
            or _LOWER_SHA256.fullmatch(decoded[field_name]) is None
        ):
            raise PendingHypothesisTransactionError(
                f"pending transaction {field_name} is invalid"
            )
    current_store_digest = _sha256(_store_bytes(store_path))
    if current_store_digest not in {
        decoded["base_store_sha256"],
        decoded["evaluated_store_sha256"],
    }:
        raise PendingHypothesisTransactionError(
            "hypothesis store diverged from its pending transaction"
        )
    semantic_now = _strict_utc_seconds(
        decoded["semantic_now"],
        field_name="pending semantic_now",
    )
    raw_evaluated = decoded["evaluated"]
    if not isinstance(raw_evaluated, list):
        raise PendingHypothesisTransactionError(
            "pending evaluated state must be a list"
        )
    hypothesis_fields = set(ResearchHypothesis.__dataclass_fields__)
    evaluated = []
    for item in raw_evaluated:
        if not isinstance(item, Mapping) or set(item) != hypothesis_fields:
            raise PendingHypothesisTransactionError(
                "pending hypothesis fields do not match the schema"
            )
        try:
            hypothesis = ResearchHypothesis(**item)
        except (TypeError, ValueError) as exc:
            raise PendingHypothesisTransactionError(
                "pending hypothesis is malformed"
            ) from exc
        if (
            hypothesis.analysis_only is not True
            or hypothesis.execution_authority != "none"
        ):
            raise PendingHypothesisTransactionError(
                "pending hypothesis has execution authority"
            )
        evaluated.append(hypothesis)
    if _sha256(_hypotheses_bytes(evaluated)) != decoded[
        "evaluated_store_sha256"
    ]:
        raise PendingHypothesisTransactionError(
            "pending evaluated-state digest mismatch"
        )
    raw_events = decoded["lifecycle_events"]
    if not isinstance(raw_events, list):
        raise PendingHypothesisTransactionError(
            "pending lifecycle events must be a list"
        )
    event_fields = set(HypothesisLifecycleEvent.__dataclass_fields__)
    lifecycle_events = []
    event_ids = set()
    for item in raw_events:
        if not isinstance(item, Mapping) or set(item) != event_fields:
            raise PendingHypothesisTransactionError(
                "pending lifecycle event fields do not match the schema"
            )
        try:
            event = HypothesisLifecycleEvent(**item)
        except (TypeError, ValueError) as exc:
            raise PendingHypothesisTransactionError(
                "pending lifecycle event is malformed"
            ) from exc
        if (
            event.analysis_only is not True
            or event.execution_authority != "none"
            or not isinstance(event.event_id, str)
            or not event.event_id
            or event.event_id in event_ids
        ):
            raise PendingHypothesisTransactionError(
                "pending lifecycle event authority or identity is invalid"
            )
        _strict_utc_seconds(
            event.occurred_at,
            field_name="pending lifecycle occurred_at",
        )
        event_ids.add(event.event_id)
        lifecycle_events.append(event)
    metrics = decoded["metrics"]
    if not isinstance(metrics, Mapping) or set(metrics) != _PENDING_METRIC_FIELDS:
        raise PendingHypothesisTransactionError(
            "pending transaction metrics do not match the schema"
        )
    for key, value in metrics.items():
        if key == "require_audited_labels":
            if type(value) is not bool:
                raise PendingHypothesisTransactionError(
                    "pending audited-label flag must be boolean"
                )
        elif type(value) is not int or value < 0:
            raise PendingHypothesisTransactionError(
                f"pending metric {key} must be a nonnegative integer"
            )
    return {
        "semantic_now": semantic_now,
        "evaluated": evaluated,
        "lifecycle_events": lifecycle_events,
        "metrics": dict(metrics),
        "transaction_id": transaction_id,
    }


def _clear_pending_transaction(store_path: str | Path) -> None:
    path = _pending_transaction_path(store_path)
    try:
        state = path.lstat()
    except FileNotFoundError:
        return
    except OSError as exc:
        raise PendingHypothesisTransactionError(
            "pending transaction could not be inspected for removal"
        ) from exc
    if stat.S_ISLNK(state.st_mode) or not stat.S_ISREG(state.st_mode):
        raise PendingHypothesisTransactionError(
            "pending transaction must be a regular file"
        )
    try:
        path.unlink()
    except OSError as exc:
        raise PendingHypothesisTransactionError(
            "pending transaction could not be removed"
        ) from exc
    _fsync_directory_path(path.parent)


def _lifecycle_event_bytes(event: HypothesisLifecycleEvent) -> bytes:
    return json.dumps(event.as_dict(), sort_keys=True).encode("utf-8")


def _valid_lifecycle_event_bytes(
    payload: bytes,
) -> HypothesisLifecycleEvent | None:
    try:
        decoded = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    event_fields = set(HypothesisLifecycleEvent.__dataclass_fields__)
    if not isinstance(decoded, Mapping) or set(decoded) != event_fields:
        return None
    try:
        event = HypothesisLifecycleEvent(**decoded)
        _strict_utc_seconds(
            event.occurred_at,
            field_name="lifecycle occurred_at",
        )
    except (TypeError, ValueError, PendingHypothesisTransactionError):
        return None
    if (
        event.analysis_only is not True
        or event.execution_authority != "none"
        or not isinstance(event.event_id, str)
        or not event.event_id
    ):
        return None
    return event


def _repair_pending_lifecycle_tail(
    path: str | Path,
    pending_events: Sequence[HypothesisLifecycleEvent],
) -> None:
    lifecycle_path = Path(path)
    try:
        descriptor = os.open(
            lifecycle_path,
            os.O_RDWR | _NOFOLLOW,
        )
    except FileNotFoundError:
        return
    except OSError as exc:
        raise PendingHypothesisTransactionError(
            "lifecycle ledger could not be opened safely"
        ) from exc
    repaired = False
    try:
        try:
            state = os.fstat(descriptor)
            if not stat.S_ISREG(state.st_mode):
                raise OSError("lifecycle descriptor is invalid")
            chunks = []
            while True:
                chunk = os.read(descriptor, 1024 * 1024)
                if not chunk:
                    break
                chunks.append(chunk)
            ledger_bytes = b"".join(chunks)
        except OSError as exc:
            raise PendingHypothesisTransactionError(
                "lifecycle ledger could not be inspected safely"
            ) from exc
        if not ledger_bytes or ledger_bytes.endswith(b"\n"):
            return
        tail_start = ledger_bytes.rfind(b"\n") + 1
        tail = ledger_bytes[tail_start:]
        complete_event = _valid_lifecycle_event_bytes(tail)
        if (
            complete_event is not None
            and _lifecycle_event_bytes(complete_event) == tail
        ):
            try:
                os.lseek(descriptor, 0, os.SEEK_END)
                if os.write(descriptor, b"\n") != 1:
                    raise OSError("incomplete lifecycle newline repair")
                os.fsync(descriptor)
            except OSError as exc:
                raise PendingHypothesisTransactionError(
                    "complete lifecycle tail could not be repaired"
                ) from exc
            repaired = True
        else:
            pending_payloads = [
                _lifecycle_event_bytes(event) for event in pending_events
            ]
            if not tail or not any(
                len(tail) < len(payload) and payload.startswith(tail)
                for payload in pending_payloads
            ):
                raise PendingHypothesisTransactionError(
                    "unrelated incomplete lifecycle tail cannot be repaired"
                )
            try:
                os.ftruncate(descriptor, tail_start)
                os.fsync(descriptor)
            except OSError as exc:
                raise PendingHypothesisTransactionError(
                    "pending lifecycle tail could not be repaired"
                ) from exc
            repaired = True
    finally:
        os.close(descriptor)
    if repaired:
        _fsync_directory_path(lifecycle_path.parent)


def _fsync_lifecycle_ledger(path: str | Path) -> None:
    lifecycle_path = Path(path)
    try:
        state = lifecycle_path.lstat()
    except OSError as exc:
        raise PendingHypothesisTransactionError(
            "lifecycle ledger could not be inspected for durability"
        ) from exc
    if stat.S_ISLNK(state.st_mode) or not stat.S_ISREG(state.st_mode):
        raise PendingHypothesisTransactionError(
            "lifecycle ledger must be a regular file"
        )
    try:
        descriptor = os.open(
            lifecycle_path,
            os.O_RDONLY | _NOFOLLOW,
        )
    except OSError as exc:
        raise PendingHypothesisTransactionError(
            "lifecycle ledger could not be opened for durability"
        ) from exc
    try:
        try:
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise OSError("lifecycle descriptor is invalid")
            os.fsync(descriptor)
        except OSError as exc:
            raise PendingHypothesisTransactionError(
                "lifecycle ledger could not be made durable"
            ) from exc
    finally:
        os.close(descriptor)
    _fsync_directory_path(lifecycle_path.parent)


def _require_pending_lifecycle_events(
    path: str | Path,
    pending_events: Sequence[HypothesisLifecycleEvent],
    valid_events: Sequence[HypothesisLifecycleEvent],
) -> None:
    expected_by_id = {
        event.event_id: event
        for event in pending_events
    }
    valid_by_id: dict[str, list[HypothesisLifecycleEvent]] = {}
    for event in valid_events:
        if event.event_id in expected_by_id:
            valid_by_id.setdefault(event.event_id, []).append(event)
    try:
        raw = Path(path).read_bytes()
    except OSError as exc:
        raise PendingHypothesisTransactionError(
            "lifecycle ledger could not be verified"
        ) from exc
    raw_lines = raw.splitlines()
    for event_id, expected in expected_by_id.items():
        valid_matches = valid_by_id.get(event_id, [])
        canonical_payload = _lifecycle_event_bytes(expected)
        if (
            valid_matches != [expected]
            or raw_lines.count(canonical_payload) != 1
        ):
            raise PendingHypothesisTransactionError(
                "pending lifecycle event is missing or mismatched"
            )


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


def _before_hypothesis_store_publish() -> None:
    """Protected deterministic seam after append-only evidence is durable."""


def _run_hypothesis_factory_locked(
    *,
    ledger_path: str | Path,
    store_path: str | Path = DEFAULT_STORE_PATH,
    priors_path: str | Path = DEFAULT_PRIORS_PATH,
    summary_path: str | Path = DEFAULT_SUMMARY_PATH,
    lifecycle_path: str | Path | None = None,
    availability_root: str | Path | None = None,
    producer_recorded_at: datetime.datetime | None = None,
    availability_clock: Callable[[], datetime.datetime] | None = None,
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

    semantic_now = _now_utc(now)
    lifecycle_store = (
        Path(lifecycle_path)
        if lifecycle_path is not None
        else Path(store_path).with_name("lifecycle.jsonl")
    )
    availability_store = (
        Path(availability_root)
        if availability_root is not None
        else (
            DEFAULT_LEARNING_AVAILABILITY_ROOT
            if Path(store_path) == DEFAULT_STORE_PATH
            else Path(store_path).parent / "learning_availability"
        )
    )
    pending = _load_pending_transaction(
        store_path=store_path,
        lifecycle_path=lifecycle_store,
        availability_root=availability_store,
        priors_path=priors_path,
        summary_path=summary_path,
    )
    known_events, corrupt_lifecycle_line_count = (
        load_lifecycle_events_with_stats(lifecycle_store)
    )
    if pending is not None:
        semantic_now = pending["semantic_now"]
        evaluated = pending["evaluated"]
        lifecycle_events = pending["lifecycle_events"]
        metrics = pending["metrics"]
    else:
        forecasts = load_ledger(ledger_path)
        existing, corrupt_store_line_count = load_hypotheses_with_stats(
            store_path
        )
        resolved = [
            forecast
            for forecast in forecasts
            if forecast.resolved and forecast.outcome is not None
        ]
        minable = minable_forecasts(
            forecasts,
            require_audited_labels=require_audited_labels,
        )
        excluded_suspect_count = sum(
            1
            for forecast in resolved
            if getattr(forecast, "label_quality", None)
            == LABEL_QUALITY_SUSPECT
        )
        excluded_unaudited_count = (
            len(resolved) - excluded_suspect_count - len(minable)
        )
        mined = mine_hypotheses(
            forecasts,
            min_sample=min_sample,
            edge_threshold=edge_threshold,
            now=semantic_now,
            require_audited_labels=require_audited_labels,
        )
        merged, appended = merge_hypotheses(existing, mined)
        evaluated = evaluate_hypotheses(
            merged,
            forecasts,
            now=semantic_now,
            require_audited_labels=require_audited_labels,
        )
        fresh_priors = research_priors(evaluated)
        lifecycle_events = hypothesis_lifecycle_events(
            existing,
            evaluated,
            evaluated_at=semantic_now.isoformat(timespec="seconds"),
            known_events=known_events,
            prior_multipliers={
                str(row["hypothesis_id"]): str(row["multiplier"])
                for row in fresh_priors["priors"]
            },
        )
        metrics = {
            "forecast_count": len(forecasts),
            "resolved_forecast_count": len(resolved),
            "require_audited_labels": require_audited_labels,
            "minable_forecast_count": len(minable),
            "excluded_suspect_count": excluded_suspect_count,
            "excluded_unaudited_count": excluded_unaudited_count,
            "corrupt_store_line_count": corrupt_store_line_count,
            "mined_count": len(mined),
            "appended_count": appended,
        }
        pending_transaction = _build_pending_transaction(
            semantic_now=semantic_now,
            store_path=store_path,
            lifecycle_path=lifecycle_store,
            availability_root=availability_store,
            priors_path=priors_path,
            summary_path=summary_path,
            evaluated=evaluated,
            lifecycle_events=lifecycle_events,
            metrics=metrics,
        )
        _write_pending_transaction(store_path, pending_transaction)

    priors = research_priors(evaluated)
    _repair_pending_lifecycle_tail(lifecycle_store, lifecycle_events)
    lifecycle_appended_count = append_lifecycle_events(lifecycle_events, path=lifecycle_store)
    _fsync_lifecycle_ledger(lifecycle_store)
    all_lifecycle_events, corrupt_lifecycle_after = load_lifecycle_events_with_stats(
        lifecycle_store
    )
    _require_pending_lifecycle_events(
        lifecycle_store,
        lifecycle_events,
        all_lifecycle_events,
    )
    producer_time = (
        producer_recorded_at
        if producer_recorded_at is not None
        else (
            availability_clock()
            if availability_clock is not None
            else datetime.datetime.now(tz=UTC)
        )
    )
    if not isinstance(producer_time, datetime.datetime):
        raise ValueError("availability clock must return a datetime")
    producer_time = producer_time.replace(microsecond=0)
    availability_admissions = observe_lifecycle_events(
        all_lifecycle_events,
        availability_root=availability_store,
        recorded_at=producer_time,
    )
    _before_hypothesis_store_publish()
    write_hypotheses(evaluated, path=store_path)
    lifecycle_event_type_counts: dict[str, int] = {}
    for event in lifecycle_events:
        lifecycle_event_type_counts[event.event_type] = (
            lifecycle_event_type_counts.get(event.event_type, 0) + 1
        )
    atomic_write_text(Path(priors_path), json.dumps(priors, indent=2, sort_keys=True))
    summary = summarize_hypotheses(evaluated)
    atomic_write_text(Path(summary_path), json.dumps(summary, indent=2, sort_keys=True))
    _clear_pending_transaction(store_path)
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
        "lifecycle_total_event_count": len(all_lifecycle_events),
        "lifecycle_event_type_counts": lifecycle_event_type_counts,
        "corrupt_lifecycle_line_count": max(
            corrupt_lifecycle_line_count,
            corrupt_lifecycle_after,
        ),
        "learning_availability_root": str(availability_store),
        "learning_observed_count": len(availability_admissions),
        "learning_newly_recorded_count": sum(
            admission.created for admission in availability_admissions
        ),
        "forecast_count": metrics["forecast_count"],
        "resolved_forecast_count": metrics["resolved_forecast_count"],
        "require_audited_labels": metrics["require_audited_labels"],
        "minable_forecast_count": metrics["minable_forecast_count"],
        "excluded_suspect_count": metrics["excluded_suspect_count"],
        "excluded_unaudited_count": metrics["excluded_unaudited_count"],
        "corrupt_store_line_count": metrics["corrupt_store_line_count"],
        "mined_count": metrics["mined_count"],
        "appended_count": metrics["appended_count"],
        "hypothesis_count": len(evaluated),
        "status_counts": summary["status_counts"],
        "prior_count": priors["prior_count"],
        "priors_context": render_research_priors_context(priors),
    }


def run_hypothesis_factory(
    *,
    ledger_path: str | Path,
    store_path: str | Path = DEFAULT_STORE_PATH,
    priors_path: str | Path = DEFAULT_PRIORS_PATH,
    summary_path: str | Path = DEFAULT_SUMMARY_PATH,
    lifecycle_path: str | Path | None = None,
    availability_root: str | Path | None = None,
    producer_recorded_at: datetime.datetime | None = None,
    availability_clock: Callable[[], datetime.datetime] | None = None,
    min_sample: int = DEFAULT_MIN_SAMPLE,
    edge_threshold: Decimal | str = DEFAULT_EDGE_THRESHOLD,
    now: datetime.datetime | str | None = None,
    require_audited_labels: bool = True,
) -> dict[str, Any]:
    """Run one durable hypothesis-factory transaction at a time."""

    with _hypothesis_factory_lock(store_path):
        return _run_hypothesis_factory_locked(
            ledger_path=ledger_path,
            store_path=store_path,
            priors_path=priors_path,
            summary_path=summary_path,
            lifecycle_path=lifecycle_path,
            availability_root=availability_root,
            producer_recorded_at=producer_recorded_at,
            availability_clock=availability_clock,
            min_sample=min_sample,
            edge_threshold=edge_threshold,
            now=now,
            require_audited_labels=require_audited_labels,
        )
