"""Crash-safe evidence of when outcome-derived learning became available."""

from __future__ import annotations

import datetime as dt
import fcntl
import hashlib
import json
import os
import re
import stat
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

from tradingagents.evals.agent_intelligence_ledger import AgentForecast
from tradingagents.evals.hypothesis_lifecycle import HypothesisLifecycleEvent
from tradingagents.evals.source_bound_resolution import SourceBoundWindowLookup

LEARNING_AVAILABILITY_SCHEMA_VERSION = 1

_UTC = dt.timezone.utc
_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_LOWER_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SAFE_SOURCE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:+@=-]{0,255}$")
SOURCE_KIND_FORECAST_RESOLUTION_QUALITY = "forecast_resolution_quality"
SOURCE_KIND_SOURCE_BOUND_FORECAST_RESOLUTION = "forecast_resolution_quality_source_bound"
_SOURCE_KINDS = frozenset(
    {
        SOURCE_KIND_FORECAST_RESOLUTION_QUALITY,
        SOURCE_KIND_SOURCE_BOUND_FORECAST_RESOLUTION,
        "hypothesis_lifecycle",
    }
)
_AUTHORITY_FIELDS = {
    "analysis_only": True,
    "execution_authority": "none",
    "can_submit_orders": False,
}
_OBSERVATION_FIELDS = frozenset(
    {
        "schema_version",
        "observation_id",
        "source_kind",
        "source_id",
        "effective_at",
        "recorded_at",
        "payload_sha256",
        "payload",
        *_AUTHORITY_FIELDS,
    }
)
_EVENT_FIELDS = frozenset(
    {
        "schema_version",
        "sequence",
        "observation_id",
        "source_kind",
        "source_id",
        "payload_sha256",
        "effective_at",
        "recorded_at",
        *_AUTHORITY_FIELDS,
    }
)
_FORECAST_PAYLOAD_FIELDS = frozenset(
    {
        "forecast_id",
        "agent",
        "ticker",
        "forecast_type",
        "horizon",
        "probability",
        "direction",
        "benchmark",
        "sector",
        "evidence_sources",
        "evidence_refs",
        "setup",
        "regime",
        "created_at",
        "resolve_after",
        "source_packet_id",
        "resolved",
        "outcome",
        "actual_return",
        "benchmark_return",
        "relative_return",
        "brier_score",
        "agent_score_delta",
        "resolved_at",
        "label_quality",
        "quality_flags",
        "resolution_window",
    }
)
_SOURCE_BOUND_FORECAST_PAYLOAD_FIELDS = frozenset(
    {*_FORECAST_PAYLOAD_FIELDS, "resolution_evidence"}
)
_LIFECYCLE_PAYLOAD_FIELDS = frozenset(
    {
        "event_id",
        "event_type",
        "hypothesis_id",
        "occurred_at",
        "from_status",
        "to_status",
        "out_of_sample_count",
        "out_of_sample_delta",
        "prior_multiplier",
        "context",
        "analysis_only",
        "execution_authority",
    }
)
_RESOLUTION_WINDOW_FIELDS = frozenset(
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
_RESOLUTION_EVIDENCE_FIELDS = frozenset({"schema_version", "ticker", "benchmark"})
_SOURCE_BOUND_LEG_FIELDS = frozenset(
    {
        "schema_version",
        "window_id",
        "window_sha256",
        "security_id",
        "raw_artifact_id",
        "raw_artifact_sha256",
        "decision_cutoff",
        "retrieved_at",
        "feed",
        "adjustment_mode",
        "adjustment_status",
    }
)
_SOURCE_BOUND_RESOLUTION_EVIDENCE_SCHEMA = "source_bound_resolution_evidence/v1"
_SOURCE_BOUND_LEG_EVIDENCE_SCHEMA = "source_bound_price_window_evidence/v1"
_LIFECYCLE_CONTEXT_FIELDS = frozenset(
    {"agent", "direction", "setup", "regime", "sector"}
)


class LearningAvailabilityError(ValueError):
    """Base class for learning-availability contract failures."""


class ObservationCollisionError(LearningAvailabilityError):
    """An immutable observation identity names conflicting material."""


class AvailabilityCorruptionError(LearningAvailabilityError):
    """Stored availability evidence is malformed or inconsistent."""


def _canonical_json(payload: Mapping[str, Any]) -> bytes:
    try:
        return json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise LearningAvailabilityError(
            "payload must contain only finite canonical JSON values"
        ) from exc


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


def _required_canonical_text(value: Any, *, field: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value.strip() != value
        or any(ord(character) < 32 for character in value)
    ):
        raise LearningAvailabilityError(
            f"{field} must be a nonempty canonical string"
        )
    return value


def _source_id(value: Any, *, field: str) -> str:
    clean = _required_canonical_text(value, field=field)
    if _SAFE_SOURCE_ID.fullmatch(clean) is None:
        raise LearningAvailabilityError(f"{field} is not a safe source token")
    return clean


def _recorded_utc(value: dt.datetime) -> dt.datetime:
    if (
        not isinstance(value, dt.datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
        or value.utcoffset() != dt.timedelta(0)
    ):
        raise LearningAvailabilityError(
            "recorded_at must be an aware UTC datetime"
        )
    return value.astimezone(_UTC).replace(microsecond=0)


def _stored_utc(value: Any, *, field: str) -> dt.datetime:
    if not isinstance(value, str):
        raise LearningAvailabilityError(
            f"{field} must be canonical UTC ISO-8601 seconds"
        )
    try:
        parsed = dt.datetime.fromisoformat(value)
    except ValueError as exc:
        raise LearningAvailabilityError(
            f"{field} must be canonical UTC ISO-8601 seconds"
        ) from exc
    if (
        parsed.tzinfo is None
        or parsed.utcoffset() != dt.timedelta(0)
        or parsed.microsecond != 0
    ):
        raise LearningAvailabilityError(
            f"{field} must be canonical UTC ISO-8601 seconds"
        )
    normalized = parsed.astimezone(_UTC)
    if normalized.isoformat(timespec="seconds") != value:
        raise LearningAvailabilityError(
            f"{field} must be canonical UTC ISO-8601 seconds"
        )
    return normalized


def _payload_digest(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(_thaw(payload))).hexdigest()


def _observation_id(
    *,
    source_kind: str,
    source_id: str,
    effective_at: str,
    payload_sha256: str,
) -> str:
    identity = {
        "effective_at": effective_at,
        "payload_sha256": payload_sha256,
        "source_id": source_id,
        "source_kind": source_kind,
    }
    return f"lo-{hashlib.sha256(_canonical_json(identity)).hexdigest()}"


def _require_exact_fields(
    payload: Mapping[str, Any],
    expected: frozenset[str],
    *,
    label: str,
) -> None:
    keys = tuple(payload)
    if not all(isinstance(key, str) for key in keys):
        raise LearningAvailabilityError(f"{label} field names must be strings")
    missing = sorted(expected - set(keys))
    unknown = sorted(set(keys) - expected)
    if missing or unknown:
        details = []
        if missing:
            details.append(f"missing fields: {', '.join(missing)}")
        if unknown:
            details.append(f"unknown fields: {', '.join(unknown)}")
        raise LearningAvailabilityError(f"{label} " + "; ".join(details))


def _validate_string_sequence(value: Any, *, field: str) -> None:
    if isinstance(value, (str, bytes)) or not isinstance(value, (list, tuple)):
        raise LearningAvailabilityError(f"{field} must be a string collection")
    for item in value:
        _required_canonical_text(item, field=field)


def _validate_forecast_payload(payload: Mapping[str, Any]) -> None:
    _require_exact_fields(
        payload,
        _FORECAST_PAYLOAD_FIELDS,
        label="forecast payload",
    )
    if payload["resolved"] is not True or type(payload["outcome"]) is not bool:
        raise LearningAvailabilityError(
            "forecast observation requires a resolved boolean outcome"
        )
    _required_canonical_text(payload["label_quality"], field="label_quality")
    _validate_string_sequence(payload["evidence_sources"], field="evidence_sources")
    _validate_string_sequence(payload["evidence_refs"], field="evidence_refs")
    _validate_string_sequence(payload["quality_flags"], field="quality_flags")
    window = payload["resolution_window"]
    if not isinstance(window, Mapping):
        raise LearningAvailabilityError(
            "forecast observation requires a resolution_window"
        )
    _require_exact_fields(
        window,
        _RESOLUTION_WINDOW_FIELDS,
        label="resolution_window",
    )
    if type(window["final_bar_available"]) is not bool:
        raise LearningAvailabilityError(
            "resolution_window final_bar_available must be boolean"
        )
    for field in (
        "expected_session_count",
        "ticker_session_count",
        "benchmark_session_count",
    ):
        if type(window[field]) is not int or window[field] < 0:
            raise LearningAvailabilityError(
                f"resolution_window {field} must be a nonnegative integer"
            )


def _validate_source_bound_resolution_evidence(value: Any) -> None:
    if not isinstance(value, Mapping):
        raise LearningAvailabilityError("resolution_evidence must be an object")
    _require_exact_fields(
        value,
        _RESOLUTION_EVIDENCE_FIELDS,
        label="resolution_evidence",
    )
    if value["schema_version"] != _SOURCE_BOUND_RESOLUTION_EVIDENCE_SCHEMA:
        raise LearningAvailabilityError("resolution_evidence schema_version is invalid")
    for leg_name in ("ticker", "benchmark"):
        leg = value[leg_name]
        if not isinstance(leg, Mapping):
            raise LearningAvailabilityError(f"resolution_evidence {leg_name} must be an object")
        _require_exact_fields(
            leg,
            _SOURCE_BOUND_LEG_FIELDS,
            label=f"resolution_evidence {leg_name}",
        )
        if leg["schema_version"] != _SOURCE_BOUND_LEG_EVIDENCE_SCHEMA:
            raise LearningAvailabilityError(
                f"resolution_evidence {leg_name} schema_version is invalid"
            )
        for field in ("window_sha256", "raw_artifact_sha256"):
            if (
                not isinstance(leg[field], str)
                or _LOWER_SHA256.fullmatch(leg[field]) is None
            ):
                raise LearningAvailabilityError(
                    f"resolution_evidence {leg_name} {field} must be a SHA-256 digest"
                )
        for field in ("window_id", "security_id", "raw_artifact_id"):
            _source_id(leg[field], field=f"resolution_evidence {leg_name} {field}")
        retrieved_at = _stored_utc(
            leg["retrieved_at"],
            field=f"resolution_evidence {leg_name} retrieved_at",
        )
        decision_cutoff = _stored_utc(
            leg["decision_cutoff"],
            field=f"resolution_evidence {leg_name} decision_cutoff",
        )
        if retrieved_at > decision_cutoff:
            raise LearningAvailabilityError(
                f"resolution_evidence {leg_name} retrieval is after decision cutoff"
            )
        if leg["feed"] not in {"iex", "sip"}:
            raise LearningAvailabilityError(
                f"resolution_evidence {leg_name} feed is invalid"
            )
        if leg["adjustment_mode"] != "all" or leg["adjustment_status"] != "total_return_adjusted":
            raise LearningAvailabilityError(
                f"resolution_evidence {leg_name} adjustment contract is invalid"
            )


def _validate_source_bound_forecast_payload(payload: Mapping[str, Any]) -> None:
    _require_exact_fields(
        payload,
        _SOURCE_BOUND_FORECAST_PAYLOAD_FIELDS,
        label="source-bound forecast payload",
    )
    _validate_forecast_payload(
        {field: payload[field] for field in _FORECAST_PAYLOAD_FIELDS}
    )
    _validate_source_bound_resolution_evidence(payload["resolution_evidence"])


def _validate_lifecycle_payload(payload: Mapping[str, Any]) -> None:
    _require_exact_fields(
        payload,
        _LIFECYCLE_PAYLOAD_FIELDS,
        label="lifecycle payload",
    )
    if payload["analysis_only"] is not True:
        raise LearningAvailabilityError(
            "lifecycle payload analysis_only must be true"
        )
    if payload["execution_authority"] != "none":
        raise LearningAvailabilityError(
            "lifecycle payload execution_authority must be none"
        )
    context = payload["context"]
    if not isinstance(context, Mapping):
        raise LearningAvailabilityError("lifecycle context must be an object")
    unknown = sorted(set(context) - _LIFECYCLE_CONTEXT_FIELDS)
    if unknown:
        raise LearningAvailabilityError(
            "lifecycle context has unknown fields: " + ", ".join(unknown)
        )
    for key, value in context.items():
        _required_canonical_text(key, field="lifecycle context key")
        _required_canonical_text(value, field=f"lifecycle context {key}")


@dataclass(frozen=True)
class LearningObservation:
    schema_version: int
    observation_id: str
    source_kind: str
    source_id: str
    effective_at: str
    recorded_at: str
    payload_sha256: str
    payload: Mapping[str, Any]
    analysis_only: bool
    execution_authority: str
    can_submit_orders: bool

    @classmethod
    def from_forecast(
        cls,
        forecast: AgentForecast,
        *,
        recorded_at: dt.datetime,
    ) -> LearningObservation:
        """Reject creation of legacy learning observations.

        Existing ``forecast_resolution_quality`` objects remain readable for
        audit and migration, but only the receipt-verifying source-bound path
        may create a new learning admission.
        """

        del cls, forecast, recorded_at
        raise LearningAvailabilityError(
            "legacy forecast observations are historical read-only; use source-bound receipts"
        )

    @classmethod
    def from_historical_forecast(
        cls,
        forecast: AgentForecast,
        *,
        recorded_at: dt.datetime,
    ) -> LearningObservation:
        """Reconstruct a pre-existing legacy observation for audit-only tests/tools."""
        if (
            forecast.resolved is not True
            or type(forecast.outcome) is not bool
            or not isinstance(forecast.resolved_at, str)
            or not isinstance(forecast.label_quality, str)
            or not forecast.label_quality.strip()
            or not isinstance(forecast.resolution_window, Mapping)
            or not forecast.resolution_window
        ):
            raise LearningAvailabilityError(
                "forecast is not an audited resolved snapshot"
            )
        payload = {
            field: getattr(forecast, field)
            for field in sorted(_FORECAST_PAYLOAD_FIELDS)
        }
        return cls._create(
            source_kind=SOURCE_KIND_FORECAST_RESOLUTION_QUALITY,
            source_id=forecast.forecast_id,
            effective_at=forecast.resolved_at,
            recorded_at=recorded_at,
            payload=payload,
        )

    @classmethod
    def from_source_bound_forecast(
        cls,
        forecast: AgentForecast,
        *,
        recorded_at: dt.datetime,
        verifier: SourceBoundWindowLookup,
    ) -> LearningObservation:
        """Record a resolved outcome only when both price legs are bound to PIT bytes."""

        if (
            forecast.resolved is not True
            or type(forecast.outcome) is not bool
            or not isinstance(forecast.resolved_at, str)
            or not isinstance(forecast.label_quality, str)
            or not forecast.label_quality.strip()
            or not isinstance(forecast.resolution_window, Mapping)
            or not forecast.resolution_window
        ):
            raise LearningAvailabilityError(
                "forecast is not an audited resolved source-bound snapshot"
            )
        payload = {
            field: getattr(forecast, field)
            for field in sorted(_SOURCE_BOUND_FORECAST_PAYLOAD_FIELDS)
        }
        _validate_source_bound_forecast_payload(payload)
        if type(verifier) is not SourceBoundWindowLookup:
            raise LearningAvailabilityError(
                "source-bound admission requires an exact SourceBoundWindowLookup"
            )
        if verifier.verify_forecast(forecast) is not True:
            raise LearningAvailabilityError(
                "source-bound forecast evidence did not reverify against raw receipts"
            )
        return cls._create(
            source_kind=SOURCE_KIND_SOURCE_BOUND_FORECAST_RESOLUTION,
            source_id=forecast.forecast_id,
            effective_at=forecast.resolved_at,
            recorded_at=recorded_at,
            payload=payload,
        )

    @classmethod
    def from_lifecycle_event(
        cls,
        event: HypothesisLifecycleEvent,
        *,
        recorded_at: dt.datetime,
    ) -> LearningObservation:
        if event.analysis_only is not True or event.execution_authority != "none":
            raise LearningAvailabilityError(
                "lifecycle event has execution authority"
            )
        payload = {
            field: getattr(event, field)
            for field in sorted(_LIFECYCLE_PAYLOAD_FIELDS)
        }
        return cls._create(
            source_kind="hypothesis_lifecycle",
            source_id=event.event_id,
            effective_at=event.occurred_at,
            recorded_at=recorded_at,
            payload=payload,
        )

    @classmethod
    def _create(
        cls,
        *,
        source_kind: str,
        source_id: str,
        effective_at: str,
        recorded_at: dt.datetime,
        payload: Mapping[str, Any],
    ) -> LearningObservation:
        recorded = _recorded_utc(recorded_at)
        effective = _stored_utc(effective_at, field="effective_at")
        if effective > recorded:
            raise LearningAvailabilityError(
                "effective_at cannot be later than recorded_at"
            )
        clean_source_id = _source_id(source_id, field="source_id")
        frozen_payload = _freeze(payload)
        digest = _payload_digest(frozen_payload)
        observation = cls(
            schema_version=LEARNING_AVAILABILITY_SCHEMA_VERSION,
            observation_id=_observation_id(
                source_kind=source_kind,
                source_id=clean_source_id,
                effective_at=effective.isoformat(timespec="seconds"),
                payload_sha256=digest,
            ),
            source_kind=source_kind,
            source_id=clean_source_id,
            effective_at=effective.isoformat(timespec="seconds"),
            recorded_at=recorded.isoformat(timespec="seconds"),
            payload_sha256=digest,
            payload=frozen_payload,
            **_AUTHORITY_FIELDS,
        )
        _validate_observation(observation)
        return observation

    @classmethod
    def _from_mapping(cls, raw: Mapping[str, Any]) -> LearningObservation:
        _require_exact_fields(raw, _OBSERVATION_FIELDS, label="observation")
        observation = cls(
            schema_version=raw["schema_version"],
            observation_id=raw["observation_id"],
            source_kind=raw["source_kind"],
            source_id=raw["source_id"],
            effective_at=raw["effective_at"],
            recorded_at=raw["recorded_at"],
            payload_sha256=raw["payload_sha256"],
            payload=_freeze(raw["payload"]),
            analysis_only=raw["analysis_only"],
            execution_authority=raw["execution_authority"],
            can_submit_orders=raw["can_submit_orders"],
        )
        _validate_observation(observation)
        return observation

    def compact(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "observation_id": self.observation_id,
            "source_kind": self.source_kind,
            "source_id": self.source_id,
            "effective_at": self.effective_at,
            "recorded_at": self.recorded_at,
            "payload_sha256": self.payload_sha256,
            "payload": _thaw(self.payload),
            "analysis_only": self.analysis_only,
            "execution_authority": self.execution_authority,
            "can_submit_orders": self.can_submit_orders,
        }

    def canonical_json_bytes(self) -> bytes:
        return _canonical_json(self.compact())


def _validate_observation(observation: LearningObservation) -> None:
    if type(observation.schema_version) is not int or (
        observation.schema_version != LEARNING_AVAILABILITY_SCHEMA_VERSION
    ):
        raise LearningAvailabilityError("schema_version must equal 1")
    if observation.analysis_only is not True:
        raise ObservationCollisionError("analysis_only authority change")
    if observation.execution_authority != "none":
        raise ObservationCollisionError("execution_authority change")
    if observation.can_submit_orders is not False:
        raise ObservationCollisionError("can_submit_orders authority change")
    if observation.source_kind not in _SOURCE_KINDS:
        raise LearningAvailabilityError("unsupported source_kind")
    source_id = _source_id(observation.source_id, field="source_id")
    effective = _stored_utc(observation.effective_at, field="effective_at")
    recorded = _stored_utc(observation.recorded_at, field="recorded_at")
    if effective > recorded:
        raise LearningAvailabilityError(
            "effective_at cannot be later than recorded_at"
        )
    if (
        not isinstance(observation.payload_sha256, str)
        or _LOWER_SHA256.fullmatch(observation.payload_sha256) is None
    ):
        raise LearningAvailabilityError(
            "payload_sha256 must be a lowercase SHA-256 digest"
        )
    if not isinstance(observation.payload, Mapping):
        raise LearningAvailabilityError("payload must be an object")
    if observation.source_kind == SOURCE_KIND_FORECAST_RESOLUTION_QUALITY:
        _validate_forecast_payload(observation.payload)
        if observation.payload["forecast_id"] != source_id:
            raise ObservationCollisionError(
                "forecast source_id does not match payload forecast_id"
            )
        if observation.payload["resolved_at"] != observation.effective_at:
            raise ObservationCollisionError(
                "forecast effective_at does not match payload resolved_at"
            )
    elif observation.source_kind == SOURCE_KIND_SOURCE_BOUND_FORECAST_RESOLUTION:
        _validate_source_bound_forecast_payload(observation.payload)
        if observation.payload["forecast_id"] != source_id:
            raise ObservationCollisionError(
                "forecast source_id does not match payload forecast_id"
            )
        if observation.payload["resolved_at"] != observation.effective_at:
            raise ObservationCollisionError(
                "forecast effective_at does not match payload resolved_at"
            )
    else:
        _validate_lifecycle_payload(observation.payload)
        if observation.payload["event_id"] != source_id:
            raise ObservationCollisionError(
                "lifecycle source_id does not match payload event_id"
            )
        if observation.payload["occurred_at"] != observation.effective_at:
            raise ObservationCollisionError(
                "lifecycle effective_at does not match payload occurred_at"
            )
    digest = _payload_digest(observation.payload)
    if digest != observation.payload_sha256:
        raise ObservationCollisionError("payload digest mismatch")
    expected_id = _observation_id(
        source_kind=observation.source_kind,
        source_id=source_id,
        effective_at=observation.effective_at,
        payload_sha256=digest,
    )
    if observation.observation_id != expected_id:
        raise ObservationCollisionError("observation identity mismatch")


@dataclass(frozen=True)
class ObservationAdmission:
    observation: LearningObservation
    path: Path
    created: bool


@dataclass(frozen=True)
class _ObservationEvent:
    schema_version: int
    sequence: int
    observation_id: str
    source_kind: str
    source_id: str
    payload_sha256: str
    effective_at: str
    recorded_at: str

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> _ObservationEvent:
        try:
            _require_exact_fields(raw, _EVENT_FIELDS, label="event")
            if raw["analysis_only"] is not True:
                raise LearningAvailabilityError("event analysis_only must be true")
            if raw["execution_authority"] != "none":
                raise LearningAvailabilityError(
                    "event execution_authority must be none"
                )
            if raw["can_submit_orders"] is not False:
                raise LearningAvailabilityError(
                    "event can_submit_orders must be false"
                )
            if type(raw["schema_version"]) is not int or raw["schema_version"] != 1:
                raise LearningAvailabilityError("event schema_version must equal 1")
            if type(raw["sequence"]) is not int or raw["sequence"] < 1:
                raise LearningAvailabilityError(
                    "event sequence must be a positive integer"
                )
            _source_id(raw["source_id"], field="event source_id")
            if raw["source_kind"] not in _SOURCE_KINDS:
                raise LearningAvailabilityError("event source_kind is unsupported")
            _stored_utc(raw["effective_at"], field="event effective_at")
            _stored_utc(raw["recorded_at"], field="event recorded_at")
            if _LOWER_SHA256.fullmatch(str(raw["payload_sha256"])) is None:
                raise LearningAvailabilityError("event payload digest is invalid")
            if (
                not isinstance(raw["observation_id"], str)
                or re.fullmatch(r"lo-[0-9a-f]{64}", raw["observation_id"]) is None
            ):
                raise LearningAvailabilityError("event observation_id is invalid")
            return cls(
                schema_version=raw["schema_version"],
                sequence=raw["sequence"],
                observation_id=raw["observation_id"],
                source_kind=raw["source_kind"],
                source_id=raw["source_id"],
                payload_sha256=raw["payload_sha256"],
                effective_at=raw["effective_at"],
                recorded_at=raw["recorded_at"],
            )
        except LearningAvailabilityError as exc:
            raise AvailabilityCorruptionError(str(exc)) from exc

    @classmethod
    def from_observation(
        cls,
        observation: LearningObservation,
        *,
        sequence: int,
    ) -> _ObservationEvent:
        return cls(
            schema_version=LEARNING_AVAILABILITY_SCHEMA_VERSION,
            sequence=sequence,
            observation_id=observation.observation_id,
            source_kind=observation.source_kind,
            source_id=observation.source_id,
            payload_sha256=observation.payload_sha256,
            effective_at=observation.effective_at,
            recorded_at=observation.recorded_at,
        )

    def compact(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "sequence": self.sequence,
            "observation_id": self.observation_id,
            "source_kind": self.source_kind,
            "source_id": self.source_id,
            "payload_sha256": self.payload_sha256,
            "effective_at": self.effective_at,
            "recorded_at": self.recorded_at,
            **_AUTHORITY_FIELDS,
        }

    def canonical_json_bytes(self) -> bytes:
        return _canonical_json(self.compact())


class LearningAvailabilityLedger:
    """Persist immutable observations and replay their availability order."""

    def __init__(self, root: str | Path):
        lexical_root = Path(os.path.abspath(os.fspath(Path(root).expanduser())))
        try:
            state = lexical_root.lstat()
        except FileNotFoundError:
            state = None
        except OSError as exc:
            raise AvailabilityCorruptionError(
                "availability root could not be inspected"
            ) from exc
        if state is not None and stat.S_ISLNK(state.st_mode):
            raise AvailabilityCorruptionError(
                "availability root must not be a symlink"
            )
        self.root = lexical_root.resolve()
        self._lock_path = self.root / ".availability.lock"
        self._observations_dir = self.root / "observations"
        self._events_path = self.root / "events.jsonl"

    def record(self, observation: LearningObservation) -> ObservationAdmission:
        return self.record_many((observation,))[0]

    def record_many(
        self,
        observations: Sequence[LearningObservation],
    ) -> tuple[ObservationAdmission, ...]:
        snapshots = []
        for observation in observations:
            _validate_observation(observation)
            snapshots.append(
                LearningObservation._from_mapping(observation.compact())
            )
        ordered = sorted(
            snapshots,
            key=lambda item: (item.observation_id, item.recorded_at),
        )
        if not ordered:
            return ()
        with self._locked():
            self._ensure_observations_dir()
            events, stored = self._replay()
            self._redurable_journal_if_present()
            admissions: list[ObservationAdmission] = []
            mutable_events = list(events)
            stored_by_id = dict(stored)
            event_ids = {event.observation_id for event in mutable_events}
            for candidate in ordered:
                path = self._observation_path(candidate.observation_id)
                object_state = self._path_state(path, label="observation object")
                object_existed = object_state is not None
                if object_existed:
                    existing, _ = self._read_observation(path)
                    self._compare_retry(existing, candidate)
                    durable_observation = existing
                else:
                    self._write_immutable_observation(
                        path,
                        candidate.canonical_json_bytes(),
                    )
                    self._after_object_fsync(path)
                    durable_observation = candidate

                prior_stored = stored_by_id.get(candidate.observation_id)
                if prior_stored is not None:
                    self._compare_retry(prior_stored, candidate)
                    admissions.append(
                        ObservationAdmission(
                            observation=prior_stored,
                            path=path,
                            created=False,
                        )
                    )
                    continue

                if candidate.observation_id in event_ids:
                    raise AvailabilityCorruptionError(
                        "journal replay lost an admitted observation"
                    )
                if object_existed:
                    self._redurable_regular_file(path, label="observation object")
                    self._fsync_directory(self._observations_dir)
                event = _ObservationEvent.from_observation(
                    durable_observation,
                    sequence=len(mutable_events) + 1,
                )
                self._append_event(event)
                self._after_event_fsync(event)
                mutable_events.append(event)
                event_ids.add(event.observation_id)
                stored_by_id[event.observation_id] = durable_observation
                admissions.append(
                    ObservationAdmission(
                        observation=durable_observation,
                        path=path,
                        created=True,
                    )
                )
            return tuple(admissions)

    def verify(self) -> tuple[LearningObservation, ...]:
        with self._locked():
            self._ensure_observations_dir()
            _, stored = self._replay()
            return tuple(stored.values())

    def rebuild(self) -> tuple[LearningObservation, ...]:
        with self._locked():
            self._ensure_observations_dir()
            _, stored = self._replay()
            self._redurable_journal_if_present()
            return tuple(stored.values())

    def _after_object_fsync(self, path: Path) -> None:
        """Protected deterministic seam after an immutable object is durable."""

    def _after_event_fsync(self, event: _ObservationEvent) -> None:
        """Protected deterministic seam after a journal event is durable."""

    def _compare_retry(
        self,
        stored: LearningObservation,
        candidate: LearningObservation,
    ) -> None:
        stored_material = stored.compact()
        candidate_material = candidate.compact()
        stored_time = stored_material.pop("recorded_at")
        candidate_time = candidate_material.pop("recorded_at")
        if stored_material != candidate_material:
            raise ObservationCollisionError(
                f"observation ID collision: {candidate.observation_id}"
            )
        if _stored_utc(candidate_time, field="recorded_at") < _stored_utc(
            stored_time,
            field="recorded_at",
        ):
            raise ObservationCollisionError(
                f"observation retry attempts backdating: {candidate.observation_id}"
            )

    @contextmanager
    def _locked(self) -> Iterator[None]:
        self._ensure_root()
        state = self._path_state(self._lock_path, label="availability lock")
        if state is not None:
            self._require_regular_state(state, label="availability lock")
        try:
            descriptor = os.open(
                self._lock_path,
                os.O_CREAT | os.O_RDWR | _NOFOLLOW,
                0o600,
            )
        except OSError as exc:
            raise AvailabilityCorruptionError(
                "availability lock could not be opened safely"
            ) from exc
        try:
            self._require_regular_descriptor(
                descriptor,
                label="availability lock",
            )
            if state is None:
                self._fsync_directory(self.root)
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            yield
        finally:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)

    def _ensure_root(self) -> None:
        state = self._path_state(self.root, label="availability root")
        if state is None:
            try:
                self.root.mkdir(parents=True)
            except FileExistsError:
                pass
            except OSError as exc:
                raise AvailabilityCorruptionError(
                    "availability root could not be created"
                ) from exc
            state = self._path_state(self.root, label="availability root")
        if state is None or stat.S_ISLNK(state.st_mode) or not stat.S_ISDIR(
            state.st_mode
        ):
            raise AvailabilityCorruptionError(
                "availability root must be a real directory, not a symlink"
            )

    def _ensure_observations_dir(self) -> None:
        state = self._path_state(
            self._observations_dir,
            label="observations directory",
        )
        if state is None:
            try:
                self._observations_dir.mkdir()
            except FileExistsError:
                pass
            except OSError as exc:
                raise AvailabilityCorruptionError(
                    "observations directory could not be created"
                ) from exc
            state = self._path_state(
                self._observations_dir,
                label="observations directory",
            )
            self._fsync_directory(self.root)
        self._require_directory_state(state, label="observations directory")

    def _require_contained(self, path: Path) -> None:
        try:
            path.relative_to(self.root)
        except ValueError as exc:
            raise AvailabilityCorruptionError(
                "managed path escapes availability root"
            ) from exc

    def _path_state(
        self,
        path: Path,
        *,
        label: str,
    ) -> os.stat_result | None:
        self._require_contained(path)
        try:
            return path.lstat()
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise AvailabilityCorruptionError(
                f"{label} could not be inspected"
            ) from exc

    def _require_regular_state(
        self,
        state: os.stat_result,
        *,
        label: str,
    ) -> None:
        if stat.S_ISLNK(state.st_mode) or not stat.S_ISREG(state.st_mode):
            raise AvailabilityCorruptionError(
                f"{label} must be a regular file, not a symlink"
            )

    def _require_directory_state(
        self,
        state: os.stat_result | None,
        *,
        label: str,
    ) -> None:
        if (
            state is None
            or stat.S_ISLNK(state.st_mode)
            or not stat.S_ISDIR(state.st_mode)
        ):
            raise AvailabilityCorruptionError(
                f"{label} must be a real directory, not a symlink"
            )

    def _require_regular_descriptor(self, descriptor: int, *, label: str) -> None:
        try:
            state = os.fstat(descriptor)
        except OSError as exc:
            raise AvailabilityCorruptionError(
                f"{label} descriptor could not be inspected"
            ) from exc
        if not stat.S_ISREG(state.st_mode):
            raise AvailabilityCorruptionError(
                f"{label} descriptor must reference a regular file"
            )

    def _require_real_directory(self, path: Path, *, label: str) -> None:
        state = self._path_state(path, label=label)
        self._require_directory_state(state, label=label)

    def _fsync_directory(self, path: Path) -> None:
        self._require_real_directory(path, label=f"{path.name} directory")
        try:
            descriptor = os.open(
                path,
                os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | _NOFOLLOW,
            )
        except OSError as exc:
            raise AvailabilityCorruptionError(
                f"directory could not be opened: {path.name}"
            ) from exc
        try:
            try:
                state = os.fstat(descriptor)
                if not stat.S_ISDIR(state.st_mode):
                    raise OSError("not a directory")
                os.fsync(descriptor)
            except OSError as exc:
                raise AvailabilityCorruptionError(
                    f"directory could not be made durable: {path.name}"
                ) from exc
        finally:
            os.close(descriptor)

    def _redurable_regular_file(self, path: Path, *, label: str) -> None:
        state = self._path_state(path, label=label)
        if state is None:
            raise AvailabilityCorruptionError(f"{label} is missing")
        self._require_regular_state(state, label=label)
        try:
            descriptor = os.open(path, os.O_RDONLY | _NOFOLLOW)
        except OSError as exc:
            raise AvailabilityCorruptionError(
                f"{label} could not be reopened safely"
            ) from exc
        try:
            self._require_regular_descriptor(descriptor, label=label)
            try:
                os.fsync(descriptor)
            except OSError as exc:
                raise AvailabilityCorruptionError(
                    f"{label} could not be made durable"
                ) from exc
        finally:
            os.close(descriptor)

    def _redurable_journal_if_present(self) -> None:
        state = self._path_state(self._events_path, label="event journal")
        if state is None:
            return
        self._require_regular_state(state, label="event journal")
        self._redurable_regular_file(self._events_path, label="event journal")
        self._fsync_directory(self.root)

    def _read_regular(self, path: Path, *, label: str) -> bytes:
        state = self._path_state(path, label=label)
        if state is None:
            raise AvailabilityCorruptionError(f"{label} is missing")
        self._require_regular_state(state, label=label)
        try:
            descriptor = os.open(path, os.O_RDONLY | _NOFOLLOW)
        except OSError as exc:
            raise AvailabilityCorruptionError(
                f"{label} could not be opened safely"
            ) from exc
        try:
            self._require_regular_descriptor(descriptor, label=label)
            chunks = []
            while True:
                chunk = os.read(descriptor, 64 * 1024)
                if not chunk:
                    break
                chunks.append(chunk)
            return b"".join(chunks)
        except OSError as exc:
            raise AvailabilityCorruptionError(
                f"{label} could not be read"
            ) from exc
        finally:
            os.close(descriptor)

    def _observation_path(self, observation_id: str) -> Path:
        if re.fullmatch(r"lo-[0-9a-f]{64}", observation_id) is None:
            raise ObservationCollisionError("observation identity is invalid")
        path = self._observations_dir / f"{observation_id}.json"
        self._require_contained(path)
        return path

    def _write_immutable_observation(self, path: Path, payload: bytes) -> None:
        try:
            descriptor = os.open(
                path,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY | _NOFOLLOW,
                0o600,
            )
        except FileExistsError as exc:
            raise AvailabilityCorruptionError(
                "observation object appeared during locked creation"
            ) from exc
        except OSError as exc:
            raise AvailabilityCorruptionError(
                "observation object could not be created"
            ) from exc
        try:
            self._require_regular_descriptor(
                descriptor,
                label="observation object",
            )
            try:
                offset = 0
                while offset < len(payload):
                    written = os.write(descriptor, payload[offset:])
                    if written <= 0:
                        raise OSError("incomplete observation write")
                    offset += written
                os.fsync(descriptor)
            except OSError as exc:
                raise AvailabilityCorruptionError(
                    "observation object could not be made durable"
                ) from exc
        finally:
            os.close(descriptor)
        self._fsync_directory(self._observations_dir)

    def _read_observation(
        self,
        path: Path,
    ) -> tuple[LearningObservation, bytes]:
        raw = self._read_regular(path, label="observation object")
        try:
            decoded = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AvailabilityCorruptionError(
                "observation object is not valid JSON"
            ) from exc
        if not isinstance(decoded, Mapping):
            raise AvailabilityCorruptionError(
                "observation object must be a JSON object"
            )
        try:
            observation = LearningObservation._from_mapping(decoded)
        except LearningAvailabilityError as exc:
            raise AvailabilityCorruptionError(
                f"observation object schema is invalid: {exc}"
            ) from exc
        if observation.canonical_json_bytes() != raw:
            raise AvailabilityCorruptionError(
                "observation object bytes are noncanonical"
            )
        if path != self._observation_path(observation.observation_id):
            raise AvailabilityCorruptionError(
                "observation object path and identity mismatch"
            )
        return observation, raw

    def _replay(
        self,
    ) -> tuple[
        tuple[_ObservationEvent, ...],
        dict[str, LearningObservation],
    ]:
        state = self._path_state(self._events_path, label="event journal")
        if state is None:
            return (), {}
        raw = self._read_regular(self._events_path, label="event journal")
        if not raw:
            return (), {}
        if not raw.endswith(b"\n"):
            raise AvailabilityCorruptionError(
                "event journal has a torn final line"
            )
        lines = raw[:-1].split(b"\n")
        if any(not line for line in lines):
            raise AvailabilityCorruptionError(
                "event journal contains a blank line"
            )
        events: list[_ObservationEvent] = []
        observations: dict[str, LearningObservation] = {}
        for expected_sequence, line in enumerate(lines, start=1):
            try:
                decoded = json.loads(line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise AvailabilityCorruptionError(
                    f"event journal line {expected_sequence} is malformed"
                ) from exc
            if not isinstance(decoded, Mapping):
                raise AvailabilityCorruptionError(
                    f"event journal line {expected_sequence} is not an object"
                )
            event = _ObservationEvent.from_mapping(decoded)
            if event.canonical_json_bytes() != line:
                raise AvailabilityCorruptionError(
                    f"event journal line {expected_sequence} is noncanonical"
                )
            if event.sequence != expected_sequence:
                raise AvailabilityCorruptionError(
                    f"event sequence gap at {expected_sequence}"
                )
            if event.observation_id in observations:
                raise AvailabilityCorruptionError(
                    f"repeated observation event: {event.observation_id}"
                )
            observation, _ = self._read_observation(
                self._observation_path(event.observation_id)
            )
            if (
                hashlib.sha256(
                    _canonical_json(_thaw(observation.payload))
                ).hexdigest()
                != event.payload_sha256
                or observation.payload_sha256 != event.payload_sha256
            ):
                raise AvailabilityCorruptionError(
                    f"observation payload digest mismatch at sequence {event.sequence}"
                )
            if (
                event.source_kind != observation.source_kind
                or event.source_id != observation.source_id
                or event.effective_at != observation.effective_at
                or event.recorded_at != observation.recorded_at
            ):
                raise AvailabilityCorruptionError(
                    f"event and observation binding mismatch at sequence {event.sequence}"
                )
            events.append(event)
            observations[event.observation_id] = observation
        return tuple(events), observations

    def _append_event(self, event: _ObservationEvent) -> None:
        state = self._path_state(self._events_path, label="event journal")
        if state is not None:
            self._require_regular_state(state, label="event journal")
        line = event.canonical_json_bytes() + b"\n"
        try:
            descriptor = os.open(
                self._events_path,
                os.O_APPEND | os.O_CREAT | os.O_WRONLY | _NOFOLLOW,
                0o600,
            )
        except OSError as exc:
            raise AvailabilityCorruptionError(
                "event journal could not be opened safely"
            ) from exc
        try:
            self._require_regular_descriptor(descriptor, label="event journal")
            try:
                if os.write(descriptor, line) != len(line):
                    raise OSError("incomplete availability event append")
                os.fsync(descriptor)
            except OSError as exc:
                raise AvailabilityCorruptionError(
                    "event journal could not be made durable"
                ) from exc
        finally:
            os.close(descriptor)
        if state is None:
            self._fsync_directory(self.root)


def _forecast_is_observable(forecast: AgentForecast) -> bool:
    return (
        forecast.resolved is True
        and type(forecast.outcome) is bool
        and isinstance(forecast.resolved_at, str)
        and bool(forecast.resolved_at)
        and isinstance(forecast.label_quality, str)
        and bool(forecast.label_quality.strip())
        and isinstance(forecast.resolution_window, Mapping)
        and bool(forecast.resolution_window)
    )


def observe_forecasts(
    forecasts: Sequence[AgentForecast],
    *,
    availability_root: str | Path,
    recorded_at: dt.datetime,
    source_bound_verifier: SourceBoundWindowLookup | None = None,
) -> tuple[ObservationAdmission, ...]:
    if source_bound_verifier is None:
        return ()
    observable = []
    for forecast in forecasts:
        if not _forecast_is_observable(forecast):
            continue
        try:
            observable.append(
                LearningObservation.from_source_bound_forecast(
                    forecast,
                    recorded_at=recorded_at,
                    verifier=source_bound_verifier,
                )
            )
        except LearningAvailabilityError:
            # Legacy or malformed price evidence remains in the source ledger
            # for audit, but never becomes point-in-time learning evidence.
            continue
    if not observable:
        return ()
    return LearningAvailabilityLedger(availability_root).record_many(observable)


def observe_lifecycle_events(
    events: Sequence[HypothesisLifecycleEvent],
    *,
    availability_root: str | Path,
    recorded_at: dt.datetime,
) -> tuple[ObservationAdmission, ...]:
    observations = [
        LearningObservation.from_lifecycle_event(event, recorded_at=recorded_at)
        for event in events
    ]
    if not observations:
        return ()
    return LearningAvailabilityLedger(availability_root).record_many(observations)
