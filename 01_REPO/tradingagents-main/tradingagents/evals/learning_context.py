"""Point-in-time advisory learning assembled from immutable observations."""

from __future__ import annotations

import datetime as dt
import json
import re
import stat
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from tradingagents.evals.agent_intelligence_ledger import (
    AgentForecast,
    agent_influence_weights,
)
from tradingagents.evals.hypothesis_lifecycle import (
    EVENT_HYPOTHESIS_EVIDENCE_INSUFFICIENT,
    EVENT_HYPOTHESIS_REFUTED,
    EVENT_HYPOTHESIS_REGISTERED,
    EVENT_HYPOTHESIS_SUPPORTED,
    EVENT_PRIOR_EMITTED,
    EVENT_PRIOR_RETRACTED,
)
from tradingagents.evals.learning_availability import (
    AvailabilityCorruptionError,
    LearningAvailabilityError,
    LearningAvailabilityLedger,
    LearningObservation,
)
from tradingagents.evals.resolution_quality import (
    HORIZON_KIND_TRADING_DAYS,
    LABEL_QUALITY_DEGRADED,
    LABEL_QUALITY_HIGH,
    expected_entry_session,
    expected_exit_session,
)

LEARNING_CONTEXT_SCHEMA_VERSION = 1
MAX_INFLUENCE_ROWS = 4
MAX_HYPOTHESIS_ROWS = 4

_UTC = dt.timezone.utc
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_UTC_SECONDS = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+00:00$"
)
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:+@=-]{0,255}$")
_SAFE_CONTEXT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+/-]{0,63}$")
_SAFE_FILTER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+ /-]{0,127}$")
_CONTEXT_KEYS = frozenset({"agent", "direction", "setup", "regime", "sector"})
_MARKERS = (
    "BEGIN_POINT_IN_TIME_LEARNING_DATA",
    "END_POINT_IN_TIME_LEARNING_DATA",
)
_WINDOW_FIELDS = frozenset(
    {
        "intended_start",
        "intended_end",
        "expected_entry_session",
        "expected_exit_session",
        "expected_session_count",
        "ticker_entry_date",
        "ticker_exit_date",
        "benchmark_entry_date",
        "benchmark_exit_date",
        "ticker_session_count",
        "benchmark_session_count",
        "final_bar_available",
        "horizon",
        "horizon_kind",
    }
)
_STATUS_BY_EVENT = {
    EVENT_HYPOTHESIS_SUPPORTED: "supported",
    EVENT_HYPOTHESIS_REFUTED: "refuted",
    EVENT_HYPOTHESIS_EVIDENCE_INSUFFICIENT: "insufficient_out_of_sample",
}
_STATUSES = frozenset(
    {"preregistered", "supported", "refuted", "insufficient_out_of_sample"}
)
_PRIOR_EVENTS = frozenset({EVENT_PRIOR_EMITTED, EVENT_PRIOR_RETRACTED})
_QUALITY_FLAGS = frozenset(
    {
        "assumed_market_holiday_at_window_end",
        "assumed_market_holiday_at_window_start",
        "missing_weekday_sessions_inside_window",
        "ticker_benchmark_session_count_mismatch",
    }
)

_INERT_CLAIM = "Observed forecast; source prose intentionally omitted."
_INERT_EXPECTED_OUTCOME = (
    "Observed resolution only; source recommendation intentionally omitted."
)


@dataclass(frozen=True)
class LearningContext:
    schema_version: int
    as_of: str
    rendered: str
    source_observation_ids: tuple[str, ...]
    source_forecast_ids: tuple[str, ...]
    source_packet_ids: tuple[str, ...]
    source_hypothesis_ids: tuple[str, ...]
    analysis_only: bool = True
    execution_authority: str = "none"
    can_submit_orders: bool = False


def normalize_learning_as_of(value: str | dt.datetime) -> dt.datetime:
    """Normalize an explicit as-of value without consulting the wall clock."""
    if isinstance(value, bool):
        raise TypeError("as_of must be a canonical string or aware datetime")
    if isinstance(value, dt.datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("as_of datetime must be timezone-aware")
        return value.astimezone(_UTC).replace(microsecond=0)
    if not isinstance(value, str):
        raise TypeError("as_of must be a canonical string or aware datetime")
    if _DATE.fullmatch(value):
        try:
            parsed_date = dt.date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("as_of must be a canonical calendar date") from exc
        return dt.datetime.combine(parsed_date, dt.time(), tzinfo=_UTC)
    if _UTC_SECONDS.fullmatch(value):
        try:
            parsed = dt.datetime.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("as_of must be canonical UTC seconds") from exc
        if parsed.isoformat(timespec="seconds") == value:
            return parsed
    raise ValueError("as_of must be YYYY-MM-DD or canonical UTC seconds")


def _canonical_utc(value: Any, *, field: str) -> dt.datetime:
    if not isinstance(value, str) or _UTC_SECONDS.fullmatch(value) is None:
        raise ValueError(f"{field} must be canonical UTC seconds")
    try:
        parsed = dt.datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field} must be canonical UTC seconds") from exc
    if parsed.isoformat(timespec="seconds") != value:
        raise ValueError(f"{field} must be canonical UTC seconds")
    return parsed


def _canonical_date(value: Any, *, field: str) -> dt.date:
    if not isinstance(value, str) or _DATE.fullmatch(value) is None:
        raise ValueError(f"{field} must be a canonical date")
    try:
        parsed = dt.date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field} must be a canonical date") from exc
    if parsed.isoformat() != value:
        raise ValueError(f"{field} must be a canonical date")
    return parsed


def _safe_id(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or _SAFE_ID.fullmatch(value) is None:
        raise ValueError(f"{field} must be a safe ASCII identifier")
    if any(marker in value for marker in _MARKERS):
        raise ValueError(f"{field} contains a reserved marker")
    return value


def _safe_context(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or _SAFE_CONTEXT.fullmatch(value) is None:
        raise ValueError(f"{field} must be a safe ASCII context token")
    if any(marker in value for marker in _MARKERS):
        raise ValueError(f"{field} contains a reserved marker")
    return value


def _safe_filter(value: str | None, *, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or _SAFE_FILTER.fullmatch(value) is None:
        raise ValueError(f"{field} must be a safe canonical filter")
    if any(marker in value for marker in _MARKERS):
        raise ValueError(f"{field} contains a reserved marker")
    return value


def _finite_decimal(
    value: Any,
    *,
    field: str,
    minimum: Decimal | None = None,
    maximum: Decimal | None = None,
) -> str:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be a finite decimal string")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{field} must be a finite decimal string") from exc
    if not parsed.is_finite():
        raise ValueError(f"{field} must be finite")
    if minimum is not None and parsed < minimum:
        raise ValueError(f"{field} is below its allowed minimum")
    if maximum is not None and parsed > maximum:
        raise ValueError(f"{field} is above its allowed maximum")
    return str(value)


def _validate_options(
    *,
    ticker: str,
    setup: str | None,
    sector: str | None,
    regime: str | None,
    evidence_type: str | None,
    horizon: str | None,
    max_chars: int,
    min_resolved: int,
) -> dict[str, str | None]:
    clean_ticker = _safe_id(ticker, field="ticker")
    if type(max_chars) is not int or not 256 <= max_chars <= 4_000:
        raise ValueError("max_chars must be an integer from 256 through 4000")
    if type(min_resolved) is not int or not 1 <= min_resolved <= 10_000:
        raise ValueError(
            "min_resolved must be an integer from 1 through 10000"
        )
    return {
        "ticker": clean_ticker,
        "setup": _safe_filter(setup, field="setup"),
        "sector": _safe_filter(sector, field="sector"),
        "regime": _safe_filter(regime, field="regime"),
        "evidence_type": _safe_filter(
            evidence_type,
            field="evidence_type",
        ),
        "horizon": _safe_filter(horizon, field="horizon"),
    }


def _neutral_payload(as_of: dt.datetime) -> dict[str, Any]:
    return {
        "schema_version": LEARNING_CONTEXT_SCHEMA_VERSION,
        "as_of": as_of.isoformat(timespec="seconds"),
        "analysis_only": True,
        "execution_authority": "none",
        "can_submit_orders": False,
        "influence": [],
        "hypotheses": [],
    }


def _render(payload: Mapping[str, Any]) -> str:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def _context_result(payload: Mapping[str, Any]) -> LearningContext:
    influence = payload["influence"]
    hypotheses = payload["hypotheses"]
    observation_ids: list[str] = []
    forecast_ids: list[str] = []
    packet_ids: list[str] = []
    hypothesis_ids: list[str] = []

    def extend_unique(target: list[str], values: Sequence[str]) -> None:
        present = set(target)
        for value in values:
            if value not in present:
                target.append(value)
                present.add(value)

    for row in influence:
        extend_unique(observation_ids, row["observation_ids"])
        extend_unique(forecast_ids, row["forecast_ids"])
        extend_unique(packet_ids, row["source_packet_ids"])
    for row in hypotheses:
        extend_unique(observation_ids, row["observation_ids"])
        extend_unique(hypothesis_ids, [row["hypothesis_id"]])
    return LearningContext(
        schema_version=LEARNING_CONTEXT_SCHEMA_VERSION,
        as_of=payload["as_of"],
        rendered=_render(payload),
        source_observation_ids=tuple(observation_ids),
        source_forecast_ids=tuple(forecast_ids),
        source_packet_ids=tuple(packet_ids),
        source_hypothesis_ids=tuple(hypothesis_ids),
    )


def _top_level_observations(
    observations: Sequence[LearningObservation],
    *,
    as_of: dt.datetime,
) -> list[LearningObservation]:
    eligible = []
    for observation in observations:
        if not isinstance(observation, LearningObservation):
            continue
        try:
            verified = LearningObservation._from_mapping(
                observation.compact()
            )
            effective = _canonical_utc(
                verified.effective_at,
                field="effective_at",
            )
            recorded = _canonical_utc(
                verified.recorded_at,
                field="recorded_at",
            )
        except (LearningAvailabilityError, TypeError, ValueError):
            continue
        if effective <= as_of and recorded <= as_of:
            eligible.append(verified)
    return eligible


def _window_is_valid(
    window: Any,
    *,
    horizon: str,
    quality_flags: frozenset[str],
    created_at: dt.datetime,
    resolve_after: dt.datetime,
    as_of: dt.datetime,
) -> bool:
    if not isinstance(window, Mapping) or set(window) != _WINDOW_FIELDS:
        return False
    try:
        intended_start = _canonical_date(
            window["intended_start"],
            field="intended_start",
        )
        intended_end = _canonical_date(
            window["intended_end"],
            field="intended_end",
        )
        expected_entry = _canonical_date(
            window["expected_entry_session"],
            field="expected_entry_session",
        )
        expected_exit = _canonical_date(
            window["expected_exit_session"],
            field="expected_exit_session",
        )
        ticker_entry = _canonical_date(
            window["ticker_entry_date"],
            field="ticker_entry_date",
        )
        ticker_exit = _canonical_date(
            window["ticker_exit_date"],
            field="ticker_exit_date",
        )
        benchmark_entry = _canonical_date(
            window["benchmark_entry_date"],
            field="benchmark_entry_date",
        )
        benchmark_exit = _canonical_date(
            window["benchmark_exit_date"],
            field="benchmark_exit_date",
        )
    except ValueError:
        return False
    counts = (
        window["expected_session_count"],
        window["ticker_session_count"],
        window["benchmark_session_count"],
    )
    if any(type(count) is not int or count <= 0 for count in counts):
        return False
    if (
        window["final_bar_available"] is not True
        or window["horizon"] != horizon
        or window["horizon_kind"] != HORIZON_KIND_TRADING_DAYS
        or intended_start != created_at.date()
        or intended_end != resolve_after.date()
        or intended_end > as_of.date()
        or expected_entry != expected_entry_session(intended_start)
        or expected_exit != expected_exit_session(intended_end)
        or ticker_entry != benchmark_entry
        or ticker_exit != benchmark_exit
        or not quality_flags <= _QUALITY_FLAGS
    ):
        return False

    def weekday_count(start: dt.date, end: dt.date) -> int:
        count = 0
        current = start
        while current <= end:
            if current.weekday() < 5:
                count += 1
            current += dt.timedelta(days=1)
        return count

    expected_count = weekday_count(expected_entry, expected_exit)
    start_gap = weekday_count(
        expected_entry,
        ticker_entry - dt.timedelta(days=1),
    )
    end_gap = weekday_count(
        ticker_exit + dt.timedelta(days=1),
        expected_exit,
    )
    start_holiday = "assumed_market_holiday_at_window_start" in quality_flags
    end_holiday = "assumed_market_holiday_at_window_end" in quality_flags
    missing_inside = "missing_weekday_sessions_inside_window" in quality_flags
    count_mismatch = (
        "ticker_benchmark_session_count_mismatch" in quality_flags
    )
    allowed_count = expected_count - int(start_holiday) - int(end_holiday)
    return (
        window["expected_session_count"] == expected_count
        and start_gap == int(start_holiday)
        and end_gap == int(end_holiday)
        and (
            (window["benchmark_session_count"] < allowed_count)
            == missing_inside
        )
        and (
            (
                window["ticker_session_count"]
                != window["benchmark_session_count"]
            )
            == count_mismatch
        )
        and window["ticker_session_count"] <= allowed_count
        and window["benchmark_session_count"] <= allowed_count
    )


def _forecast_from_observation(
    observation: LearningObservation,
    *,
    as_of: dt.datetime,
    filters: Mapping[str, str | None],
) -> AgentForecast | None:
    payload = observation.payload
    try:
        forecast_id = _safe_id(payload["forecast_id"], field="forecast_id")
        if forecast_id != observation.source_id:
            return None
        agent = _safe_id(payload["agent"], field="agent")
        ticker = _safe_id(payload["ticker"], field="forecast ticker")
        forecast_type = _safe_id(
            payload["forecast_type"],
            field="forecast_type",
        )
        benchmark = _safe_id(payload["benchmark"], field="benchmark")
        source_packet_id = _safe_id(
            payload["source_packet_id"],
            field="source_packet_id",
        )
        evidence_sources = [
            _safe_id(item, field="evidence_source")
            for item in payload["evidence_sources"]
        ]
        evidence_refs = [
            _safe_id(item, field="evidence_ref")
            for item in payload["evidence_refs"]
        ]
        setup = _safe_context(payload["setup"], field="forecast setup")
        sector = _safe_context(payload["sector"], field="forecast sector")
        regime = _safe_context(payload["regime"], field="forecast regime")
        direction = _safe_context(
            payload["direction"],
            field="forecast direction",
        )
        horizon = _safe_filter(payload["horizon"], field="forecast horizon")
        created = _canonical_utc(payload["created_at"], field="created_at")
        resolve_after = _canonical_utc(
            payload["resolve_after"],
            field="resolve_after",
        )
        resolved_at = _canonical_utc(
            payload["resolved_at"],
            field="resolved_at",
        )
        effective = _canonical_utc(
            observation.effective_at,
            field="effective_at",
        )
        recorded = _canonical_utc(
            observation.recorded_at,
            field="recorded_at",
        )
        probability = _finite_decimal(
            payload["probability"],
            field="probability",
            minimum=Decimal("0"),
            maximum=Decimal("1"),
        )
        for field in (
            "actual_return",
            "benchmark_return",
            "relative_return",
            "brier_score",
            "agent_score_delta",
        ):
            _finite_decimal(payload[field], field=field)
        quality = payload["label_quality"]
        if quality not in (LABEL_QUALITY_HIGH, LABEL_QUALITY_DEGRADED):
            return None
        flags = [
            _safe_context(item, field="quality_flag")
            for item in payload["quality_flags"]
        ]
    except (KeyError, TypeError, ValueError):
        return None
    if (
        payload["resolved"] is not True
        or type(payload["outcome"]) is not bool
        or ticker.upper() != str(filters["ticker"]).upper()
        or created > as_of
        or created > resolve_after
        or resolve_after > as_of
        or resolve_after > resolved_at
        or resolved_at > as_of
        or effective > as_of
        or recorded > as_of
        or resolved_at != effective
        or (quality == LABEL_QUALITY_HIGH and flags)
        or (quality == LABEL_QUALITY_DEGRADED and not flags)
        or not _window_is_valid(
            payload["resolution_window"],
            horizon=horizon,
            quality_flags=frozenset(flags),
            created_at=created,
            resolve_after=resolve_after,
            as_of=as_of,
        )
    ):
        return None
    if filters["setup"] is not None and setup != filters["setup"]:
        return None
    if filters["sector"] is not None and sector != filters["sector"]:
        return None
    if filters["regime"] is not None and regime != filters["regime"]:
        return None
    if filters["evidence_type"] is not None:
        evidence_text = " ".join(
            [forecast_type, setup, *evidence_sources, *evidence_refs]
        ).lower()
        evidence_types = {
            name
            for name in (
                "market",
                "news",
                "sentiment",
                "fundamentals",
                "macro",
                "options",
                "insider",
                "mirofish",
                "creator",
                "rating",
                "trader",
            )
            if name in evidence_text
        }
        if "sec" in evidence_text or "edgar" in evidence_text:
            evidence_types.add("fundamentals")
        if any(
            name in evidence_text
            for name in ("reddit", "stocktwits", "social")
        ):
            evidence_types.add("sentiment")
        if filters["evidence_type"] not in (evidence_types or {"unknown"}):
            return None
    if filters["horizon"] is not None and horizon != filters["horizon"]:
        return None
    return AgentForecast(
        forecast_id=forecast_id,
        agent=agent,
        ticker=ticker,
        claim=_INERT_CLAIM,
        forecast_type=forecast_type,
        horizon=horizon,
        probability=probability,
        expected_outcome=_INERT_EXPECTED_OUTCOME,
        direction=direction,
        benchmark=benchmark,
        sector=sector,
        evidence_sources=evidence_sources,
        evidence_refs=evidence_refs,
        setup=setup,
        regime=regime,
        created_at=payload["created_at"],
        resolve_after=payload["resolve_after"],
        source_packet_id=source_packet_id,
        resolved=True,
        outcome=payload["outcome"],
        actual_return=payload["actual_return"],
        benchmark_return=payload["benchmark_return"],
        relative_return=payload["relative_return"],
        brier_score=payload["brier_score"],
        agent_score_delta=payload["agent_score_delta"],
        resolved_at=payload["resolved_at"],
        label_quality=quality,
        quality_flags=flags,
        resolution_window=dict(payload["resolution_window"]),
    )


def _forecast_rows(
    observations: Sequence[LearningObservation],
    *,
    as_of: dt.datetime,
    filters: Mapping[str, str | None],
    min_resolved: int,
) -> list[dict[str, Any]]:
    forecast_observations = [
        item
        for item in observations
        if item.source_kind == "forecast_resolution_quality"
    ]
    duplicate_ids = {
        item
        for item, count in Counter(
            observation.observation_id
            for observation in forecast_observations
        ).items()
        if count > 1
    }
    grouped: dict[str, list[LearningObservation]] = defaultdict(list)
    for observation in forecast_observations:
        grouped[observation.source_id].append(observation)
    accepted: list[tuple[LearningObservation, AgentForecast]] = []
    for forecast_id, history in grouped.items():
        if any(item.observation_id in duplicate_ids for item in history):
            continue
        latest_recorded = max(item.recorded_at for item in history)
        latest = [
            item for item in history if item.recorded_at == latest_recorded
        ]
        if len(latest) != 1:
            continue
        forecast = _forecast_from_observation(
            latest[0],
            as_of=as_of,
            filters=filters,
        )
        if forecast is not None and forecast.forecast_id == forecast_id:
            accepted.append((latest[0], forecast))
    forecasts = [forecast for _, forecast in accepted]
    if not forecasts:
        return []
    weights = agent_influence_weights(
        forecasts,
        min_resolved=min_resolved,
        ticker=filters["ticker"],
        setup=filters["setup"],
        sector=filters["sector"],
        regime=filters["regime"],
        evidence_type=filters["evidence_type"],
    )
    by_agent: dict[str, list[tuple[LearningObservation, AgentForecast]]] = (
        defaultdict(list)
    )
    for item in accepted:
        by_agent[item[1].agent].append(item)
    rows = []
    for agent, details in weights["agents"].items():
        context = details.get("context") or {}
        if details.get("state") != "contextual_earned_weight":
            continue
        ordered = sorted(
            by_agent[agent],
            key=lambda item: item[1].forecast_id,
        )
        rows.append(
            {
                "agent": agent,
                "weight": details["weight"],
                "state": details["state"],
                "resolved_count": int(context["resolved_count"]),
                "observation_ids": [
                    item[0].observation_id for item in ordered
                ],
                "forecast_ids": [
                    item[1].forecast_id for item in ordered
                ],
                "source_packet_ids": sorted(
                    {
                        str(entry[1].source_packet_id)
                        for entry in ordered
                    }
                ),
            }
        )
    rows.sort(
        key=lambda row: (
            -row["resolved_count"],
            -abs(Decimal(row["weight"]) - Decimal("1")),
            row["agent"],
        )
    )
    return rows[:MAX_INFLUENCE_ROWS]


def _safe_lifecycle_context(value: Any) -> dict[str, str] | None:
    if not isinstance(value, Mapping) or not set(value) <= _CONTEXT_KEYS:
        return None
    try:
        return {
            _safe_context(key, field="hypothesis context key"): _safe_context(
                item,
                field=f"hypothesis context {key}",
            )
            for key, item in value.items()
        }
    except ValueError:
        return None


def _hypothesis_row(
    history: Sequence[LearningObservation],
    *,
    filters: Mapping[str, str | None],
) -> dict[str, Any] | None:
    observation_ids = [item.observation_id for item in history]
    if len(observation_ids) != len(set(observation_ids)):
        return None
    payloads = [item.payload for item in history]
    try:
        hypothesis_ids = {
            _safe_id(payload["hypothesis_id"], field="hypothesis_id")
            for payload in payloads
        }
        event_ids = [
            _safe_id(payload["event_id"], field="event_id")
            for payload in payloads
        ]
    except (KeyError, ValueError):
        return None
    if len(hypothesis_ids) != 1 or len(event_ids) != len(set(event_ids)):
        return None
    registration_indexes = [
        index
        for index, payload in enumerate(payloads)
        if payload.get("event_type") == EVENT_HYPOTHESIS_REGISTERED
    ]
    if len(registration_indexes) != 1:
        return None
    registration = payloads[registration_indexes[0]]
    if (
        registration.get("from_status") is not None
        or registration.get("to_status") != "preregistered"
    ):
        return None
    registration_context = _safe_lifecycle_context(
        registration.get("context")
    )
    if registration_context is None:
        return None
    ordered = sorted(
        history,
        key=lambda item: (
            item.effective_at,
            item.recorded_at,
            str(item.payload["event_id"]),
        ),
    )
    state: str | None = None
    status_times: set[str] = set()
    for observation in ordered:
        payload = observation.payload
        if (
            payload.get("analysis_only") is not True
            or payload.get("execution_authority") != "none"
            or _safe_lifecycle_context(payload.get("context"))
            != registration_context
        ):
            return None
        from_status = payload.get("from_status")
        to_status = payload.get("to_status")
        if from_status is not None and from_status not in _STATUSES:
            return None
        if to_status is not None and to_status not in _STATUSES:
            return None
        event_type = payload.get("event_type")
        if event_type == EVENT_HYPOTHESIS_REGISTERED:
            if state is not None or from_status is not None or (
                to_status != "preregistered"
            ):
                return None
            state = "preregistered"
            continue
        if event_type in _STATUS_BY_EVENT:
            if observation.effective_at in status_times:
                return None
            status_times.add(observation.effective_at)
            expected = _STATUS_BY_EVENT[event_type]
            if from_status != state or to_status != expected:
                return None
            state = expected
            continue
        if event_type in _PRIOR_EVENTS:
            if state is None:
                return None
            continue
        return None
    if state != "preregistered":
        return None
    for key in ("setup", "sector", "regime"):
        supplied = filters[key]
        if supplied is not None and registration_context.get(key) != supplied:
            return None
    hypothesis_id = next(iter(hypothesis_ids))
    registration_observation = history[registration_indexes[0]]
    return {
        "hypothesis_id": hypothesis_id,
        "status": "preregistered",
        "registration_effective_at": registration_observation.effective_at,
        "context": dict(sorted(registration_context.items())),
        "observation_ids": [
            item.observation_id
            for item in sorted(
                history,
                key=lambda item: (
                    item.effective_at,
                    item.recorded_at,
                    str(item.payload["event_id"]),
                ),
            )
        ],
    }


def _hypothesis_rows(
    observations: Sequence[LearningObservation],
    *,
    filters: Mapping[str, str | None],
) -> list[dict[str, Any]]:
    grouped: dict[str, list[LearningObservation]] = defaultdict(list)
    for observation in observations:
        if observation.source_kind != "hypothesis_lifecycle":
            continue
        hypothesis_id = observation.payload.get("hypothesis_id")
        if isinstance(hypothesis_id, str):
            grouped[hypothesis_id].append(observation)
    rows = []
    for history in grouped.values():
        row = _hypothesis_row(history, filters=filters)
        if row is not None:
            rows.append(row)
    rows.sort(
        key=lambda row: (
            row["registration_effective_at"],
            row["hypothesis_id"],
        )
    )
    return rows[:MAX_HYPOTHESIS_ROWS]


def _bounded_payload(
    *,
    as_of: dt.datetime,
    influence_rows: Sequence[Mapping[str, Any]],
    hypothesis_rows: Sequence[Mapping[str, Any]],
    max_chars: int,
) -> dict[str, Any]:
    payload = _neutral_payload(as_of)
    if len(_render(payload)) > max_chars:
        raise ValueError("max_chars cannot hold the neutral learning envelope")
    for key, rows in (
        ("influence", influence_rows),
        ("hypotheses", hypothesis_rows),
    ):
        for row in rows:
            candidate = {
                **payload,
                key: [*payload[key], dict(row)],
            }
            if len(_render(candidate)) <= max_chars:
                payload = candidate
    return payload


def build_learning_context(
    *,
    observations: Sequence[LearningObservation],
    as_of: str | dt.datetime,
    ticker: str,
    setup: str | None = None,
    sector: str | None = None,
    regime: str | None = None,
    evidence_type: str | None = None,
    horizon: str | None = None,
    max_chars: int = 4_000,
    min_resolved: int = 3,
) -> LearningContext:
    current = normalize_learning_as_of(as_of)
    filters = _validate_options(
        ticker=ticker,
        setup=setup,
        sector=sector,
        regime=regime,
        evidence_type=evidence_type,
        horizon=horizon,
        max_chars=max_chars,
        min_resolved=min_resolved,
    )
    verified = _top_level_observations(observations, as_of=current)
    influence_rows = _forecast_rows(
        verified,
        as_of=current,
        filters=filters,
        min_resolved=min_resolved,
    )
    hypothesis_rows = _hypothesis_rows(verified, filters=filters)
    payload = _bounded_payload(
        as_of=current,
        influence_rows=influence_rows,
        hypothesis_rows=hypothesis_rows,
        max_chars=max_chars,
    )
    return _context_result(payload)


def learning_context_from_store(
    *,
    availability_root: str | Path,
    as_of: str | dt.datetime,
    ticker: str,
    setup: str | None = None,
    sector: str | None = None,
    regime: str | None = None,
    evidence_type: str | None = None,
    horizon: str | None = None,
    max_chars: int = 4_000,
    min_resolved: int = 3,
) -> LearningContext:
    current = normalize_learning_as_of(as_of)
    filters = _validate_options(
        ticker=ticker,
        setup=setup,
        sector=sector,
        regime=regime,
        evidence_type=evidence_type,
        horizon=horizon,
        max_chars=max_chars,
        min_resolved=min_resolved,
    )
    root = Path(availability_root)
    try:
        root_state = root.lstat()
    except FileNotFoundError:
        return _context_result(_neutral_payload(current))
    except OSError as exc:
        raise AvailabilityCorruptionError(
            "availability root could not be inspected"
        ) from exc
    if stat.S_ISLNK(root_state.st_mode) or not stat.S_ISDIR(
        root_state.st_mode
    ):
        raise AvailabilityCorruptionError(
            "availability root must be a real directory"
        )
    try:
        entries = tuple(root.iterdir())
    except OSError as exc:
        raise AvailabilityCorruptionError(
            "availability root could not be listed"
        ) from exc
    if not entries:
        return _context_result(_neutral_payload(current))

    lock_path = root / ".availability.lock"
    observations_path = root / "observations"
    events_path = root / "events.jsonl"
    try:
        lock_state = lock_path.lstat()
        observations_state = observations_path.lstat()
    except (FileNotFoundError, OSError) as exc:
        raise AvailabilityCorruptionError(
            "availability store is partially initialized"
        ) from exc
    if stat.S_ISLNK(lock_state.st_mode) or not stat.S_ISREG(
        lock_state.st_mode
    ):
        raise AvailabilityCorruptionError(
            "availability lock must be a regular file"
        )
    if stat.S_ISLNK(observations_state.st_mode) or not stat.S_ISDIR(
        observations_state.st_mode
    ):
        raise AvailabilityCorruptionError(
            "observations must be a real directory"
        )
    try:
        events_state = events_path.lstat()
    except FileNotFoundError:
        events_state = None
    except OSError as exc:
        raise AvailabilityCorruptionError(
            "availability journal could not be inspected"
        ) from exc
    if events_state is not None and (
        stat.S_ISLNK(events_state.st_mode)
        or not stat.S_ISREG(events_state.st_mode)
    ):
        raise AvailabilityCorruptionError(
            "availability journal must be a regular file"
        )
    observations = LearningAvailabilityLedger(root).verify()
    return build_learning_context(
        observations=observations,
        as_of=current,
        ticker=str(filters["ticker"]),
        setup=filters["setup"],
        sector=filters["sector"],
        regime=filters["regime"],
        evidence_type=filters["evidence_type"],
        horizon=filters["horizon"],
        max_chars=max_chars,
        min_resolved=min_resolved,
    )
