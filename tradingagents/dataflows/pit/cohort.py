"""Pure deterministic cohort selection for point-in-time economic evaluation."""

from __future__ import annotations

import dataclasses
import datetime as dt
import hashlib
import json
import re
from decimal import Decimal, InvalidOperation

from tradingagents.dataflows.pit.records import (
    PointInTimeDataError,
    SecurityIdentity,
    validate_security_identity,
)

_AUTHORITY = {
    "analysis_only": True,
    "execution_authority": "none",
    "can_submit_orders": False,
}
_DECIMAL = re.compile(r"(?:0|[1-9][0-9]*)(?:\.[0-9]+)?")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{2,255}")
_TIMESTAMP = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\+00:00")
_COHORT_SCHEMA = "point_in_time_cohort/v1"
_CANDIDATE_SCHEMA = "point_in_time_cohort_candidate/v1"
_RANKING_SCHEMA = "point_in_time_cohort_ranking/v1"
_REJECTION_SCHEMA = "point_in_time_cohort_rejection/v1"
_US_LISTED_EXCHANGES = frozenset({"NASDAQ", "NYSE", "AMEX"})


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


def _decimal(value: object, *, label: str, positive: bool) -> Decimal:
    if type(value) is not str or _DECIMAL.fullmatch(value) is None:
        raise PointInTimeDataError(f"{label} must be a canonical decimal")
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise PointInTimeDataError(f"{label} must be a canonical decimal") from exc
    if (positive and parsed <= 0) or (not positive and parsed < 0):
        raise PointInTimeDataError(f"{label} has an invalid sign")
    return parsed


def _date(value: object, *, label: str) -> str:
    if type(value) is not str:
        raise PointInTimeDataError(f"{label} must be an ISO date")
    try:
        parsed = dt.date.fromisoformat(value)
    except ValueError as exc:
        raise PointInTimeDataError(f"{label} must be an ISO date") from exc
    if parsed.isoformat() != value:
        raise PointInTimeDataError(f"{label} must be an ISO date")
    return value


def _timestamp(value: object, *, label: str) -> str:
    if type(value) is not str or _TIMESTAMP.fullmatch(value) is None:
        raise PointInTimeDataError(f"{label} must be canonical UTC seconds")
    try:
        parsed = dt.datetime.fromisoformat(value)
    except ValueError as exc:
        raise PointInTimeDataError(f"{label} must be canonical UTC seconds") from exc
    if parsed.tzinfo != dt.UTC or parsed.isoformat(timespec="seconds") != value:
        raise PointInTimeDataError(f"{label} must be canonical UTC seconds")
    return value


def _identifier(value: object, *, label: str) -> str:
    if type(value) is not str or _IDENTIFIER.fullmatch(value) is None:
        raise PointInTimeDataError(f"{label} must be a canonical identifier")
    return value


def _digest(value: object, *, label: str) -> str:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        raise PointInTimeDataError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _authority(value: dict[str, object], *, label: str) -> None:
    if (
        value["analysis_only"] is not True
        or value["execution_authority"] != "none"
        or type(value["execution_authority"]) is not str
        or value["can_submit_orders"] is not False
    ):
        raise PointInTimeDataError(f"{label} authority fields are fixed")


def _exact(value: object, fields: frozenset[str], *, label: str) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != fields:
        raise PointInTimeDataError(f"{label} fields are invalid")
    return value


@dataclasses.dataclass(frozen=True, slots=True)
class PointInTimeCohortCandidate:
    """Source-bound input used to decide a security's cohort eligibility."""

    security: SecurityIdentity
    prior_complete_close: str
    session_dollar_volumes: tuple[str, ...]
    selection_artifact_id: str
    selection_artifact_sha256: str

    def __post_init__(self) -> None:
        if type(self.security) is not SecurityIdentity:
            raise PointInTimeDataError("candidate security must be a SecurityIdentity")
        _decimal(self.prior_complete_close, label="prior_complete_close", positive=True)
        if type(self.session_dollar_volumes) is not tuple or len(self.session_dollar_volumes) != 60:
            raise PointInTimeDataError("session_dollar_volumes must be an exact 60-session tuple")
        for index, volume in enumerate(self.session_dollar_volumes):
            _decimal(volume, label=f"session_dollar_volumes[{index}]", positive=False)
        _identifier(self.selection_artifact_id, label="selection_artifact_id")
        _digest(self.selection_artifact_sha256, label="selection_artifact_sha256")

    @property
    def median_dollar_volume(self) -> Decimal:
        values = sorted(Decimal(value) for value in self.session_dollar_volumes)
        return (values[29] + values[30]) / Decimal("2")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": _CANDIDATE_SCHEMA,
            "security": self.security.to_dict(),
            "prior_complete_close": self.prior_complete_close,
            "session_dollar_volumes": list(self.session_dollar_volumes),
            "selection_artifact_id": self.selection_artifact_id,
            "selection_artifact_sha256": self.selection_artifact_sha256,
            **_AUTHORITY,
        }


@dataclasses.dataclass(frozen=True, slots=True)
class PointInTimeCohortRanking:
    rank: int
    security_id: str
    symbol: str
    median_dollar_volume: str
    selection_artifact_id: str
    selection_artifact_sha256: str

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": _RANKING_SCHEMA,
            "rank": self.rank,
            "security_id": self.security_id,
            "symbol": self.symbol,
            "median_dollar_volume": self.median_dollar_volume,
            "selection_artifact_id": self.selection_artifact_id,
            "selection_artifact_sha256": self.selection_artifact_sha256,
            **_AUTHORITY,
        }


@dataclasses.dataclass(frozen=True, slots=True)
class PointInTimeCohortRejection:
    security_id: str
    symbol: str
    reason: str

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": _REJECTION_SCHEMA,
            "security_id": self.security_id,
            "symbol": self.symbol,
            "reason": self.reason,
            **_AUTHORITY,
        }


@dataclasses.dataclass(frozen=True, slots=True, init=False)
class PointInTimeCohort:
    cohort_id: str
    cohort_sha256: str
    market_date: str
    as_of_cutoff: str
    candidates: tuple[PointInTimeCohortCandidate, ...]
    ranking: tuple[PointInTimeCohortRanking, ...]
    rejections: tuple[PointInTimeCohortRejection, ...]
    sensitivity_universe_100: tuple[str, ...]
    primary_universe_75: tuple[str, ...]
    sensitivity_universe_50: tuple[str, ...]
    sensitivity_universe_100_id: str
    primary_universe_75_id: str
    sensitivity_universe_50_id: str

    def __init__(self, *args: object, **kwargs: object) -> None:
        raise TypeError("PointInTimeCohort instances must be created by its builder")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": _COHORT_SCHEMA,
            "cohort_id": self.cohort_id,
            "cohort_sha256": self.cohort_sha256,
            "market_date": self.market_date,
            "as_of_cutoff": self.as_of_cutoff,
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "ranking": [row.to_dict() for row in self.ranking],
            "rejections": [row.to_dict() for row in self.rejections],
            "sensitivity_universe_100": list(self.sensitivity_universe_100),
            "primary_universe_75": list(self.primary_universe_75),
            "sensitivity_universe_50": list(self.sensitivity_universe_50),
            "sensitivity_universe_100_id": self.sensitivity_universe_100_id,
            "primary_universe_75_id": self.primary_universe_75_id,
            "sensitivity_universe_50_id": self.sensitivity_universe_50_id,
            **_AUTHORITY,
        }

    def canonical_json_bytes(self) -> bytes:
        return _canonical_json_bytes(self.to_dict())


_COHORT_FIELDS = tuple(field.name for field in dataclasses.fields(PointInTimeCohort))
_COHORT_SERIALIZED_FIELDS = frozenset(
    _COHORT_FIELDS + ("schema_version",) + tuple(_AUTHORITY)
)


def _new_cohort(**fields: object) -> PointInTimeCohort:
    cohort = object.__new__(PointInTimeCohort)
    for field in _COHORT_FIELDS:
        object.__setattr__(cohort, field, fields[field])
    return cohort


def _decimal_text(value: Decimal) -> str:
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _universe_id(symbols: tuple[str, ...]) -> str:
    return "economic-universe-" + _sha256(list(symbols))


def _candidate_from_dict(value: object) -> PointInTimeCohortCandidate:
    fields = frozenset(
        {
            "schema_version",
            "security",
            "prior_complete_close",
            "session_dollar_volumes",
            "selection_artifact_id",
            "selection_artifact_sha256",
            *_AUTHORITY,
        }
    )
    payload = _exact(value, fields, label="cohort candidate")
    if payload["schema_version"] != _CANDIDATE_SCHEMA:
        raise PointInTimeDataError("cohort candidate schema is invalid")
    _authority(payload, label="cohort candidate")
    if type(payload["session_dollar_volumes"]) is not list:
        raise PointInTimeDataError("cohort candidate volumes are invalid")
    return PointInTimeCohortCandidate(
        security=validate_security_identity(payload["security"]),
        prior_complete_close=payload["prior_complete_close"],  # type: ignore[arg-type]
        session_dollar_volumes=tuple(payload["session_dollar_volumes"]),  # type: ignore[arg-type]
        selection_artifact_id=payload["selection_artifact_id"],  # type: ignore[arg-type]
        selection_artifact_sha256=payload["selection_artifact_sha256"],  # type: ignore[arg-type]
    )


def build_point_in_time_cohort(
    *,
    market_date: str,
    as_of_cutoff: str,
    candidates: tuple[PointInTimeCohortCandidate, ...],
) -> PointInTimeCohort:
    """Freeze a ranked top-100 U.S. common-stock cohort from source-bound inputs."""

    _date(market_date, label="market_date")
    _timestamp(as_of_cutoff, label="as_of_cutoff")
    if type(candidates) is not tuple or not candidates:
        raise PointInTimeDataError("candidates must be a nonempty exact tuple")
    validated: list[PointInTimeCohortCandidate] = []
    seen_security_ids: set[str] = set()
    seen_symbols: set[str] = set()
    for candidate in candidates:
        if type(candidate) is not PointInTimeCohortCandidate:
            raise PointInTimeDataError("candidates must contain exact candidate records")
        if candidate.security.security_id in seen_security_ids or candidate.security.symbol in seen_symbols:
            raise PointInTimeDataError("candidates must not duplicate securities or symbols")
        seen_security_ids.add(candidate.security.security_id)
        seen_symbols.add(candidate.security.symbol)
        validated.append(candidate)

    eligible: list[PointInTimeCohortCandidate] = []
    rejections: list[PointInTimeCohortRejection] = []
    for candidate in validated:
        if candidate.security.exchange not in _US_LISTED_EXCHANGES:
            rejections.append(
                PointInTimeCohortRejection(
                    candidate.security.security_id,
                    candidate.security.symbol,
                    "exchange_not_us_listed",
                )
            )
        elif Decimal(candidate.prior_complete_close) < Decimal("5"):
            rejections.append(
                PointInTimeCohortRejection(
                    candidate.security.security_id,
                    candidate.security.symbol,
                    "prior_complete_close_below_5",
                )
            )
        elif candidate.median_dollar_volume <= 0:
            rejections.append(
                PointInTimeCohortRejection(
                    candidate.security.security_id,
                    candidate.security.symbol,
                    "median_dollar_volume_not_positive",
                )
            )
        else:
            eligible.append(candidate)
    if len(eligible) < 100:
        raise PointInTimeDataError("cohort requires at least 100 eligible securities")
    ranked_candidates = sorted(
        sorted(eligible, key=lambda candidate: candidate.security.symbol),
        key=lambda candidate: candidate.median_dollar_volume,
        reverse=True,
    )
    ranking = tuple(
        PointInTimeCohortRanking(
            rank=index,
            security_id=candidate.security.security_id,
            symbol=candidate.security.symbol,
            median_dollar_volume=_decimal_text(candidate.median_dollar_volume),
            selection_artifact_id=candidate.selection_artifact_id,
            selection_artifact_sha256=candidate.selection_artifact_sha256,
        )
        for index, candidate in enumerate(ranked_candidates, start=1)
    )
    top_100 = tuple(sorted(row.symbol for row in ranking[:100]))
    top_75 = tuple(sorted(row.symbol for row in ranking[:75]))
    top_50 = tuple(sorted(row.symbol for row in ranking[:50]))
    fields: dict[str, object] = {
        "market_date": market_date,
        "as_of_cutoff": as_of_cutoff,
        "candidates": tuple(validated),
        "ranking": ranking,
        "rejections": tuple(rejections),
        "sensitivity_universe_100": top_100,
        "primary_universe_75": top_75,
        "sensitivity_universe_50": top_50,
        "sensitivity_universe_100_id": _universe_id(top_100),
        "primary_universe_75_id": _universe_id(top_75),
        "sensitivity_universe_50_id": _universe_id(top_50),
    }
    identity = {
        "schema_version": _COHORT_SCHEMA,
        "market_date": market_date,
        "as_of_cutoff": as_of_cutoff,
        "candidates": [candidate.to_dict() for candidate in validated],
        "ranking": [row.to_dict() for row in ranking],
        "rejections": [row.to_dict() for row in rejections],
        "sensitivity_universe_100": list(top_100),
        "primary_universe_75": list(top_75),
        "sensitivity_universe_50": list(top_50),
        "sensitivity_universe_100_id": fields["sensitivity_universe_100_id"],
        "primary_universe_75_id": fields["primary_universe_75_id"],
        "sensitivity_universe_50_id": fields["sensitivity_universe_50_id"],
        **_AUTHORITY,
    }
    cohort_id = "point-in-time-cohort-" + _sha256(identity)
    digest_material = {**identity, "cohort_id": cohort_id}
    return _new_cohort(
        cohort_id=cohort_id,
        cohort_sha256=_sha256(digest_material),
        **fields,
    )


def validate_point_in_time_cohort(value: object) -> PointInTimeCohort:
    """Rebuild a full source-bound cohort and reject any altered bytes."""

    payload = _exact(value, _COHORT_SERIALIZED_FIELDS, label="point-in-time cohort")
    if payload["schema_version"] != _COHORT_SCHEMA:
        raise PointInTimeDataError("point-in-time cohort schema is invalid")
    _authority(payload, label="point-in-time cohort")
    if type(payload["candidates"]) is not list:
        raise PointInTimeDataError("point-in-time cohort candidates are invalid")
    rebuilt = build_point_in_time_cohort(
        market_date=payload["market_date"],  # type: ignore[arg-type]
        as_of_cutoff=payload["as_of_cutoff"],  # type: ignore[arg-type]
        candidates=tuple(_candidate_from_dict(item) for item in payload["candidates"]),
    )
    if rebuilt.canonical_json_bytes() != _canonical_json_bytes(payload):
        raise PointInTimeDataError("point-in-time cohort bytes do not match canonical rebuild")
    return rebuilt
