"""Pure, nonqualifying canonical records for point-in-time cohorts.

This module performs no filesystem or network work. It proves only internal
receipt canonicality. Qualifying consumers must call the archive-backed
verifier in ``cohort_admission``.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from decimal import Decimal, DecimalException, InvalidOperation
from types import MappingProxyType
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from tradingagents.dataflows.pit.market_calendar import (
    MarketSessionCalendar,
    validate_market_session_calendar,
)
from tradingagents.dataflows.pit.records import (
    PointInTimeDataError,
    SecurityIdentity,
    validate_security_identity,
)

__all__ = [
    "PointInTimeCohort",
    "PointInTimeCohortCandidate",
    "PointInTimeCohortIdentitySourceReference",
    "PointInTimeCohortMarketDataSourceReference",
    "PointInTimeCohortRanking",
    "PointInTimeCohortRejection",
    "build_point_in_time_cohort",
    "validate_nonqualifying_point_in_time_cohort_record",
]


_AUTHORITY = {
    "analysis_only": True,
    "execution_authority": "none",
    "can_submit_orders": False,
}
_COHORT_SCHEMA = "point_in_time_cohort/v3"
_CANDIDATE_SCHEMA = "point_in_time_cohort_candidate/v3"
_IDENTITY_SOURCE_SCHEMA = "point_in_time_cohort_identity_source_reference/v2"
_MARKET_SOURCE_SCHEMA = "point_in_time_cohort_market_data_source_reference/v2"
_RANKING_SCHEMA = "point_in_time_cohort_ranking/v3"
_REJECTION_SCHEMA = "point_in_time_cohort_rejection/v3"
_UNIVERSE_SCHEMA = "canonical_ranked_universe/v1"
_DECIMAL = re.compile(r"(?:0|[1-9][0-9]*)(?:\.[0-9]+)?")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{2,255}")
_SYMBOL = re.compile(r"[A-Z][A-Z0-9.-]{0,14}")
_TIMESTAMP = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\+00:00"
)
_REASON = re.compile(r"[a-z0-9][a-z0-9_:.-]{2,255}")
_US_LISTED_EXCHANGES = frozenset(
    {"AMEX", "ARCA", "BATS", "NASDAQ", "NYSE", "NYSEARCA"}
)
_SOURCE_DECIMAL_LIMITS = (128, 128, 256)
_DERIVED_DECIMAL_LIMITS = (513, 640, 768)
_MAX_JSON_PATH_DEPTH = 4
_MAX_JSON_PATH_COMPONENT_CHARS = 64
_MAX_CANDIDATES = 512
_MARKET_TZ = ZoneInfo("America/New_York")
_IDENTITY_PROFILE_ORDER = ("alpaca_asset/v1", "security_master/v1")
_IDENTITY_PROFILE_SPECS: dict[str, tuple[str, Mapping[str, tuple[str, ...]]]] = {
    "alpaca_asset/v1": (
        "alpaca_asset",
        MappingProxyType(
            {
                "security_id": ("id",),
                "symbol": ("symbol",),
                "exchange": ("exchange",),
                "asset_class": ("class",),
                "status": ("status",),
                "tradable": ("tradable",),
            }
        ),
    ),
    "security_master/v1": (
        "security_master",
        MappingProxyType(
            {
                "security_id": ("security_id",),
                "symbol": ("symbol",),
                "security_type": ("security_type",),
                "effective_from": ("effective_from",),
                "effective_to": ("effective_to",),
            }
        ),
    ),
}
_MARKET_SOURCE_PROFILE = "alpaca_stock_daily_bars/v1"
_MARKET_BAR_SELECTORS = MappingProxyType(
    {
        "rows_path": ("bars",),
        "timestamp_field": "t",
        "close_field": "c",
        "volume_field": "v",
    }
)


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
        raise PointInTimeDataError(f"{label} must use canonical UTC seconds")
    try:
        parsed = dt.datetime.fromisoformat(value)
    except ValueError as exc:
        raise PointInTimeDataError(f"{label} must use canonical UTC seconds") from exc
    if parsed.tzinfo != dt.timezone.utc or parsed.isoformat(timespec="seconds") != value:
        raise PointInTimeDataError(f"{label} must use canonical UTC seconds")
    return value


def _timestamp_value(value: object, *, label: str) -> dt.datetime:
    return dt.datetime.fromisoformat(_timestamp(value, label=label))


def _identifier(value: object, *, label: str) -> str:
    if type(value) is not str or _IDENTIFIER.fullmatch(value) is None:
        raise PointInTimeDataError(f"{label} must be a canonical identifier")
    return value


def _digest(value: object, *, label: str) -> str:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        raise PointInTimeDataError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _symbol(value: object, *, label: str) -> str:
    if type(value) is not str or _SYMBOL.fullmatch(value) is None:
        raise PointInTimeDataError(f"{label} must be a normalized symbol")
    return value


def _source_uri(value: object, *, label: str) -> str:
    if type(value) is not str:
        raise PointInTimeDataError(f"{label} must be a canonical HTTPS URI")
    parsed = urlsplit(value)
    try:
        port = parsed.port
    except ValueError as exc:
        raise PointInTimeDataError(f"{label} must be a canonical HTTPS URI") from exc
    if (
        parsed.scheme != "https"
        or parsed.hostname is None
        or parsed.netloc != parsed.hostname
        or port is not None
        or parsed.username is not None
        or parsed.password is not None
        or not parsed.path
        or parsed.fragment
    ):
        raise PointInTimeDataError(f"{label} must be a canonical HTTPS URI")
    return value


def _decimal(
    value: object,
    *,
    label: str,
    positive: bool,
    limits: tuple[int, int, int],
) -> Decimal:
    if type(value) is not str or _DECIMAL.fullmatch(value) is None:
        raise PointInTimeDataError(f"{label} must be a canonical decimal")
    try:
        parsed = Decimal(value)
        sign, digits, exponent = parsed.as_tuple()
        adjusted = len(digits) + exponent - 1
    except (InvalidOperation, DecimalException, ValueError) as exc:
        raise PointInTimeDataError(f"{label} must be a canonical decimal") from exc
    max_digits, max_exponent, max_chars = limits
    if (
        not parsed.is_finite()
        or len(digits) > max_digits
        or abs(exponent) > max_exponent
        or abs(adjusted) > max_exponent
        or len(value) > max_chars
        or (positive and parsed <= 0)
        or (not positive and parsed < 0)
        or (sign and parsed == 0)
    ):
        raise PointInTimeDataError(f"{label} is outside the canonical decimal domain")
    return parsed


def _authority(payload: Mapping[str, object], *, label: str) -> None:
    if any(payload[key] != expected for key, expected in _AUTHORITY.items()):
        raise PointInTimeDataError(f"{label} authority fields are fixed")


def _exact(value: object, fields: frozenset[str], *, label: str) -> dict[str, object]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise PointInTimeDataError(f"{label} fields are invalid")
    return dict(value)


def _json_path(value: object, *, label: str) -> tuple[str | int, ...]:
    if (
        type(value) not in (list, tuple)
        or not value
        or len(value) > _MAX_JSON_PATH_DEPTH
    ):
        raise PointInTimeDataError(f"{label} must be a bounded nonempty JSON path")
    path: list[str | int] = []
    for component in value:
        if (
            type(component) is str
            and component
            and len(component) <= _MAX_JSON_PATH_COMPONENT_CHARS
        ) or (type(component) is int and 0 <= component <= _MAX_CANDIDATES):
            path.append(component)
        else:
            raise PointInTimeDataError(f"{label} contains an invalid component")
    return tuple(path)


def _selectors(value: object, *, label: str) -> MappingProxyType:
    if not isinstance(value, Mapping) or not value or len(value) > 16:
        raise PointInTimeDataError(f"{label} must be a bounded selector mapping")
    frozen: dict[str, tuple[str | int, ...]] = {}
    for name, path in value.items():
        _identifier(name, label=f"{label} name")
        frozen[name] = _json_path(path, label=f"{label}.{name}")
    return MappingProxyType(frozen)


def _thaw_selectors(value: Mapping[str, Sequence[str | int]]) -> dict[str, object]:
    return {name: list(path) for name, path in value.items()}


def _reasons(value: object) -> tuple[str, ...]:
    if type(value) not in (list, tuple) or len(value) > 32:
        raise PointInTimeDataError("candidate rejection_reasons must be bounded")
    reasons: list[str] = []
    for reason in value:
        if type(reason) is not str or _REASON.fullmatch(reason) is None:
            raise PointInTimeDataError("candidate rejection reason is invalid")
        if reason not in reasons:
            reasons.append(reason)
    return tuple(reasons)


@dataclasses.dataclass(frozen=True, slots=True)
class PointInTimeCohortIdentitySourceReference:
    """One registered, code-profiled identity source reference."""

    source_profile: str
    source_hash_name: str
    record_identity: str
    raw_artifact_id: str
    raw_artifact_sha256: str
    source_uri: str
    content_type: str
    retrieved_at: str
    archive_recorded_at: str
    qualification_field_selectors: Mapping[str, Sequence[str | int]]

    def __post_init__(self) -> None:
        if self.source_profile not in _IDENTITY_PROFILE_SPECS:
            raise PointInTimeDataError("identity source profile is not registered")
        expected_hash_name, expected_selectors = _IDENTITY_PROFILE_SPECS[
            self.source_profile
        ]
        if self.source_hash_name != expected_hash_name:
            raise PointInTimeDataError("identity source hash role does not match profile")
        if self.source_profile == "alpaca_asset/v1":
            try:
                _symbol(self.record_identity, label="identity source record_identity")
            except PointInTimeDataError:
                _identifier(self.record_identity, label="identity source record_identity")
        else:
            _identifier(self.record_identity, label="identity source record_identity")
        artifact_id = _identifier(self.raw_artifact_id, label="raw_artifact_id")
        if not artifact_id.startswith("pit-raw-artifact-"):
            raise PointInTimeDataError("identity source raw artifact identity is invalid")
        _digest(self.raw_artifact_sha256, label="raw_artifact_sha256")
        _source_uri(self.source_uri, label="identity source_uri")
        if self.content_type != "application/json":
            raise PointInTimeDataError("identity source must be JSON")
        _timestamp(self.retrieved_at, label="identity source retrieved_at")
        _timestamp(self.archive_recorded_at, label="identity source archive_recorded_at")
        selectors = _selectors(
            self.qualification_field_selectors,
            label="qualification_field_selectors",
        )
        if dict(selectors) != dict(expected_selectors):
            raise PointInTimeDataError(
                "identity source selectors are fixed by the registered profile"
            )
        object.__setattr__(self, "qualification_field_selectors", selectors)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": _IDENTITY_SOURCE_SCHEMA,
            "source_profile": self.source_profile,
            "source_hash_name": self.source_hash_name,
            "record_identity": self.record_identity,
            "raw_artifact_id": self.raw_artifact_id,
            "raw_artifact_sha256": self.raw_artifact_sha256,
            "source_uri": self.source_uri,
            "content_type": self.content_type,
            "retrieved_at": self.retrieved_at,
            "archive_recorded_at": self.archive_recorded_at,
            "qualification_field_selectors": _thaw_selectors(
                self.qualification_field_selectors
            ),
            **_AUTHORITY,
        }


@dataclasses.dataclass(frozen=True, slots=True)
class PointInTimeCohortMarketDataSourceReference:
    """Compact code-profiled reference to one retained 60-session response."""

    source_profile: str
    record_identity: str
    raw_artifact_id: str
    raw_artifact_sha256: str
    source_uri: str
    content_type: str
    retrieved_at: str
    archive_recorded_at: str
    feed: str
    adjustment: str
    timeframe: str
    rows_path: Sequence[str | int]
    timestamp_field: str
    close_field: str
    volume_field: str

    def __post_init__(self) -> None:
        if self.source_profile != _MARKET_SOURCE_PROFILE:
            raise PointInTimeDataError("market source profile is not registered")
        _symbol(self.record_identity, label="market source record_identity")
        artifact_id = _identifier(self.raw_artifact_id, label="raw_artifact_id")
        if not artifact_id.startswith("pit-raw-artifact-"):
            raise PointInTimeDataError("market source raw artifact identity is invalid")
        _digest(self.raw_artifact_sha256, label="raw_artifact_sha256")
        _source_uri(self.source_uri, label="market source_uri")
        if self.content_type != "application/json":
            raise PointInTimeDataError("market source must be JSON")
        _timestamp(self.retrieved_at, label="market source retrieved_at")
        _timestamp(self.archive_recorded_at, label="market source archive_recorded_at")
        if self.feed not in {"iex", "sip"}:
            raise PointInTimeDataError("market source feed is invalid")
        if self.adjustment != "raw" or self.timeframe != "1Day":
            raise PointInTimeDataError("market source must bind raw 1Day bars")
        rows_path = _json_path(self.rows_path, label="market source rows_path")
        if (
            rows_path != _MARKET_BAR_SELECTORS["rows_path"]
            or self.timestamp_field != _MARKET_BAR_SELECTORS["timestamp_field"]
            or self.close_field != _MARKET_BAR_SELECTORS["close_field"]
            or self.volume_field != _MARKET_BAR_SELECTORS["volume_field"]
        ):
            raise PointInTimeDataError(
                "market source selectors are fixed by the registered profile"
            )
        object.__setattr__(self, "rows_path", rows_path)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": _MARKET_SOURCE_SCHEMA,
            "source_profile": self.source_profile,
            "record_identity": self.record_identity,
            "raw_artifact_id": self.raw_artifact_id,
            "raw_artifact_sha256": self.raw_artifact_sha256,
            "source_uri": self.source_uri,
            "content_type": self.content_type,
            "retrieved_at": self.retrieved_at,
            "archive_recorded_at": self.archive_recorded_at,
            "feed": self.feed,
            "adjustment": self.adjustment,
            "timeframe": self.timeframe,
            "bar_selectors": {
                "rows_path": list(self.rows_path),
                "timestamp_field": self.timestamp_field,
                "close_field": self.close_field,
                "volume_field": self.volume_field,
            },
            **_AUTHORITY,
        }


@dataclasses.dataclass(frozen=True, slots=True)
class PointInTimeCohortCandidate:
    security: SecurityIdentity
    prior_complete_close: str
    median_daily_dollar_volume: str
    identity_sources: tuple[PointInTimeCohortIdentitySourceReference, ...]
    market_data_source: PointInTimeCohortMarketDataSourceReference
    rejection_reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if type(self.security) is not SecurityIdentity:
            raise PointInTimeDataError("candidate security must be a SecurityIdentity")
        _decimal(
            self.prior_complete_close,
            label="prior_complete_close",
            positive=True,
            limits=_SOURCE_DECIMAL_LIMITS,
        )
        _decimal(
            self.median_daily_dollar_volume,
            label="median_daily_dollar_volume",
            positive=False,
            limits=_DERIVED_DECIMAL_LIMITS,
        )
        if type(self.identity_sources) is not tuple:
            raise PointInTimeDataError("candidate identity_sources must be an exact tuple")
        profiles = tuple(source.source_profile for source in self.identity_sources)
        if profiles != _IDENTITY_PROFILE_ORDER:
            raise PointInTimeDataError(
                "candidate identity_sources must use canonical registered profile order"
            )
        if len({source.raw_artifact_id for source in self.identity_sources}) != len(
            self.identity_sources
        ):
            raise PointInTimeDataError("candidate identity source artifacts must be unique")
        asset_source, master_source = self.identity_sources
        if asset_source.record_identity not in {
            self.security.symbol,
            self.security.security_id,
        }:
            raise PointInTimeDataError("candidate Alpaca asset identity is inconsistent")
        if master_source.record_identity != self.security.security_id:
            raise PointInTimeDataError("candidate security-master identity is inconsistent")
        if type(self.market_data_source) is not PointInTimeCohortMarketDataSourceReference:
            raise PointInTimeDataError("candidate market_data_source is invalid")
        if self.market_data_source.record_identity != self.security.symbol:
            raise PointInTimeDataError("candidate market source identity is inconsistent")
        object.__setattr__(self, "rejection_reasons", _reasons(self.rejection_reasons))

    @property
    def median_dollar_volume(self) -> Decimal:
        return Decimal(self.median_daily_dollar_volume)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": _CANDIDATE_SCHEMA,
            "security": self.security.to_dict(),
            "prior_complete_close": self.prior_complete_close,
            "median_daily_dollar_volume": self.median_daily_dollar_volume,
            "identity_sources": [source.to_dict() for source in self.identity_sources],
            "market_data_source": self.market_data_source.to_dict(),
            "rejection_reasons": list(self.rejection_reasons),
            **_AUTHORITY,
        }


@dataclasses.dataclass(frozen=True, slots=True)
class PointInTimeCohortRanking:
    rank: int
    security_id: str
    symbol: str
    median_daily_dollar_volume: str
    market_data_raw_artifact_id: str
    market_data_raw_artifact_sha256: str

    def __post_init__(self) -> None:
        if type(self.rank) is not int or self.rank < 1:
            raise PointInTimeDataError("cohort ranking rank is invalid")
        _identifier(self.security_id, label="ranking security_id")
        _symbol(self.symbol, label="ranking symbol")
        _decimal(
            self.median_daily_dollar_volume,
            label="ranking median_daily_dollar_volume",
            positive=True,
            limits=_DERIVED_DECIMAL_LIMITS,
        )
        _identifier(
            self.market_data_raw_artifact_id,
            label="ranking market_data_raw_artifact_id",
        )
        _digest(
            self.market_data_raw_artifact_sha256,
            label="ranking market_data_raw_artifact_sha256",
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": _RANKING_SCHEMA,
            "rank": self.rank,
            "security_id": self.security_id,
            "symbol": self.symbol,
            "median_daily_dollar_volume": self.median_daily_dollar_volume,
            "market_data_raw_artifact_id": self.market_data_raw_artifact_id,
            "market_data_raw_artifact_sha256": self.market_data_raw_artifact_sha256,
            **_AUTHORITY,
        }


@dataclasses.dataclass(frozen=True, slots=True)
class PointInTimeCohortRejection:
    security_id: str
    symbol: str
    reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        _identifier(self.security_id, label="rejection security_id")
        _symbol(self.symbol, label="rejection symbol")
        normalized = _reasons(self.reasons)
        if not normalized:
            raise PointInTimeDataError("cohort rejection must contain a reason")
        object.__setattr__(self, "reasons", normalized)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": _REJECTION_SCHEMA,
            "security_id": self.security_id,
            "symbol": self.symbol,
            "reasons": list(self.reasons),
            **_AUTHORITY,
        }


@dataclasses.dataclass(frozen=True, slots=True, init=False)
class PointInTimeCohort:
    cohort_id: str
    cohort_sha256: str
    market_date: str
    selection_window_open_at: str
    selection_window_close_at: str
    market_session_open_at: str
    market_session_close_at: str
    selection_time: str
    as_of_cutoff: str
    market_calendar: MarketSessionCalendar
    calendar_retrieved_at: str
    calendar_archive_recorded_at: str
    session_dates: tuple[str, ...]
    market_data_feed: str
    candidates: tuple[PointInTimeCohortCandidate, ...]
    ranking: tuple[PointInTimeCohortRanking, ...]
    rejections: tuple[PointInTimeCohortRejection, ...]
    sensitivity_universe_100: tuple[str, ...]
    primary_universe_75: tuple[str, ...]
    sensitivity_universe_50: tuple[str, ...]
    sensitivity_universe_100_id: str
    sensitivity_universe_100_sha256: str
    primary_universe_75_id: str
    primary_universe_75_sha256: str
    sensitivity_universe_50_id: str
    sensitivity_universe_50_sha256: str

    def __init__(self, *args: object, **kwargs: object) -> None:
        raise TypeError("PointInTimeCohort instances must be created by its builder")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": _COHORT_SCHEMA,
            "cohort_id": self.cohort_id,
            "cohort_sha256": self.cohort_sha256,
            "market_date": self.market_date,
            "selection_window_open_at": self.selection_window_open_at,
            "selection_window_close_at": self.selection_window_close_at,
            "market_session_open_at": self.market_session_open_at,
            "market_session_close_at": self.market_session_close_at,
            "selection_time": self.selection_time,
            "as_of_cutoff": self.as_of_cutoff,
            "market_calendar": self.market_calendar.to_dict(),
            "calendar_retrieved_at": self.calendar_retrieved_at,
            "calendar_archive_recorded_at": self.calendar_archive_recorded_at,
            "session_dates": list(self.session_dates),
            "market_data_feed": self.market_data_feed,
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "ranking": [row.to_dict() for row in self.ranking],
            "rejections": [row.to_dict() for row in self.rejections],
            "sensitivity_universe_100": list(self.sensitivity_universe_100),
            "primary_universe_75": list(self.primary_universe_75),
            "sensitivity_universe_50": list(self.sensitivity_universe_50),
            "sensitivity_universe_100_id": self.sensitivity_universe_100_id,
            "sensitivity_universe_100_sha256": self.sensitivity_universe_100_sha256,
            "primary_universe_75_id": self.primary_universe_75_id,
            "primary_universe_75_sha256": self.primary_universe_75_sha256,
            "sensitivity_universe_50_id": self.sensitivity_universe_50_id,
            "sensitivity_universe_50_sha256": self.sensitivity_universe_50_sha256,
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


def _universe_identity(symbols: tuple[str, ...]) -> tuple[str, str]:
    material = {
        "schema_version": _UNIVERSE_SCHEMA,
        "symbols": list(symbols),
        **_AUTHORITY,
    }
    universe_id = "economic-universe-" + _sha256(material)
    return universe_id, _sha256({**material, "universe_id": universe_id})


def _merge_reason(reasons: list[str], reason: str) -> None:
    if reason not in reasons:
        reasons.append(reason)


def _canonical_candidate(
    candidate: PointInTimeCohortCandidate,
    *,
    session_dates: tuple[str, ...],
    market_date: str,
    as_of_cutoff: dt.datetime,
) -> PointInTimeCohortCandidate:
    reasons = list(candidate.rejection_reasons)
    identity = candidate.security
    if identity.exchange not in _US_LISTED_EXCHANGES:
        _merge_reason(
            reasons,
            "exchange_otc" if identity.exchange == "OTC" else "exchange_not_us_listed",
        )
    if identity.status != "active":
        _merge_reason(reasons, "identity_status_not_active")
    if (
        identity.effective_from > session_dates[0]
        or (identity.effective_to is not None and identity.effective_to < market_date)
    ):
        _merge_reason(reasons, "identity_not_effective_for_full_window")
    if Decimal(candidate.prior_complete_close) < Decimal("5"):
        _merge_reason(reasons, "prior_complete_close_below_5")
    if candidate.median_dollar_volume <= 0:
        _merge_reason(reasons, "median_daily_dollar_volume_not_positive")
    sources = (*candidate.identity_sources, candidate.market_data_source)
    for source in sources:
        if _timestamp_value(
            source.archive_recorded_at,
            label="source archive_recorded_at",
        ) > as_of_cutoff:
            raise PointInTimeDataError("candidate source was archived after as_of_cutoff")
        if _timestamp_value(
            source.retrieved_at,
            label="source retrieved_at",
        ) > as_of_cutoff:
            raise PointInTimeDataError("candidate source was retrieved after as_of_cutoff")
    if tuple(reasons) == candidate.rejection_reasons:
        return candidate
    return dataclasses.replace(candidate, rejection_reasons=tuple(reasons))


def _selection_bounds(
    *,
    market_date: str,
    selection_window_open_at: object,
    selection_window_close_at: object,
    market_session_open_at: object,
    market_session_close_at: object,
    selection_time: object,
    as_of_cutoff: object,
) -> tuple[str, str, str, str, str, str]:
    window_open_text = _timestamp(selection_window_open_at, label="selection_window_open_at")
    window_close_text = _timestamp(
        selection_window_close_at,
        label="selection_window_close_at",
    )
    session_open_text = _timestamp(market_session_open_at, label="market_session_open_at")
    session_close_text = _timestamp(
        market_session_close_at,
        label="market_session_close_at",
    )
    selection_text = _timestamp(selection_time, label="selection_time")
    cutoff_text = _timestamp(as_of_cutoff, label="as_of_cutoff")
    window_open = dt.datetime.fromisoformat(window_open_text)
    window_close = dt.datetime.fromisoformat(window_close_text)
    session_open = dt.datetime.fromisoformat(session_open_text)
    session_close = dt.datetime.fromisoformat(session_close_text)
    selected_at = dt.datetime.fromisoformat(selection_text)
    cutoff = dt.datetime.fromisoformat(cutoff_text)
    local_midnight = dt.datetime.combine(
        dt.date.fromisoformat(market_date),
        dt.time(0, 0),
        tzinfo=_MARKET_TZ,
    ).astimezone(dt.timezone.utc)
    if window_open != local_midnight or window_close != session_open:
        raise PointInTimeDataError(
            "cohort selection window must be local midnight through registered open"
        )
    if (
        session_open.astimezone(_MARKET_TZ).date().isoformat() != market_date
        or session_close.astimezone(_MARKET_TZ).date().isoformat() != market_date
        or session_open >= session_close
    ):
        raise PointInTimeDataError("market session bounds do not match market_date")
    if not window_open <= cutoff <= selected_at <= window_close:
        raise PointInTimeDataError(
            "as_of_cutoff and selection_time must be ordered within the pre-open window"
        )
    return (
        window_open_text,
        window_close_text,
        session_open_text,
        session_close_text,
        selection_text,
        cutoff_text,
    )


def build_point_in_time_cohort(
    *,
    market_date: str,
    selection_window_open_at: str,
    selection_window_close_at: str,
    market_session_open_at: str,
    market_session_close_at: str,
    selection_time: str,
    as_of_cutoff: str,
    market_calendar: MarketSessionCalendar,
    calendar_retrieved_at: str,
    calendar_archive_recorded_at: str,
    session_dates: tuple[str, ...],
    candidates: tuple[PointInTimeCohortCandidate, ...],
) -> PointInTimeCohort:
    """Freeze source-derived values; this record-only builder is nonqualifying."""

    normalized_market_date = _date(market_date, label="market_date")
    (
        window_open,
        window_close,
        session_open,
        session_close,
        selected_at,
        cutoff,
    ) = _selection_bounds(
        market_date=normalized_market_date,
        selection_window_open_at=selection_window_open_at,
        selection_window_close_at=selection_window_close_at,
        market_session_open_at=market_session_open_at,
        market_session_close_at=market_session_close_at,
        selection_time=selection_time,
        as_of_cutoff=as_of_cutoff,
    )
    cutoff_value = dt.datetime.fromisoformat(cutoff)
    calendar_retrieved = _timestamp(
        calendar_retrieved_at,
        label="calendar_retrieved_at",
    )
    calendar_recorded = _timestamp(
        calendar_archive_recorded_at,
        label="calendar_archive_recorded_at",
    )
    if dt.datetime.fromisoformat(calendar_recorded) > cutoff_value:
        raise PointInTimeDataError("calendar was archived after as_of_cutoff")
    if dt.datetime.fromisoformat(calendar_retrieved) > cutoff_value:
        raise PointInTimeDataError("calendar was retrieved after as_of_cutoff")
    if type(market_calendar) is not MarketSessionCalendar:
        raise PointInTimeDataError("market_calendar must be an exact calendar receipt")
    calendar = validate_market_session_calendar(market_calendar.to_dict())
    if normalized_market_date not in calendar.market_dates:
        raise PointInTimeDataError("market_date is not a registered calendar session")
    market_index = calendar.market_dates.index(normalized_market_date)
    expected_sessions = calendar.market_dates[max(0, market_index - 60) : market_index]
    if len(expected_sessions) != 60 or type(session_dates) is not tuple:
        raise PointInTimeDataError("cohort requires exactly 60 preceding calendar sessions")
    if session_dates != expected_sessions:
        raise PointInTimeDataError(
            "session_dates must be the exact 60 registered sessions before market_date"
        )
    if (
        type(candidates) is not tuple
        or not candidates
        or len(candidates) > _MAX_CANDIDATES
    ):
        raise PointInTimeDataError("candidates must be a bounded nonempty exact tuple")
    if any(type(candidate) is not PointInTimeCohortCandidate for candidate in candidates):
        raise PointInTimeDataError("candidates must contain exact candidate records")
    sorted_candidates = sorted(candidates, key=lambda row: row.security.security_id)
    if len({row.security.security_id for row in sorted_candidates}) != len(sorted_candidates):
        raise PointInTimeDataError("candidates must not duplicate security identities")
    if len({row.security.symbol for row in sorted_candidates}) != len(sorted_candidates):
        raise PointInTimeDataError("candidates must not duplicate symbols")
    canonical_candidates = tuple(
        _canonical_candidate(
            candidate,
            session_dates=session_dates,
            market_date=normalized_market_date,
            as_of_cutoff=cutoff_value,
        )
        for candidate in sorted_candidates
    )
    feeds = {candidate.market_data_source.feed for candidate in canonical_candidates}
    if len(feeds) != 1:
        raise PointInTimeDataError("cohort candidates must use one explicit market-data feed")
    market_data_feed = next(iter(feeds))
    eligible = [candidate for candidate in canonical_candidates if not candidate.rejection_reasons]
    if len(eligible) < 100:
        raise PointInTimeDataError("cohort requires at least 100 source-eligible securities")
    ranked_candidates = sorted(
        eligible,
        key=lambda candidate: (
            candidate.security.symbol,
            candidate.security.security_id,
        ),
    )
    ranked_candidates.sort(
        key=lambda candidate: candidate.median_dollar_volume,
        reverse=True,
    )
    ranking = tuple(
        PointInTimeCohortRanking(
            rank=index,
            security_id=candidate.security.security_id,
            symbol=candidate.security.symbol,
            median_daily_dollar_volume=candidate.median_daily_dollar_volume,
            market_data_raw_artifact_id=candidate.market_data_source.raw_artifact_id,
            market_data_raw_artifact_sha256=(
                candidate.market_data_source.raw_artifact_sha256
            ),
        )
        for index, candidate in enumerate(ranked_candidates, start=1)
    )
    rejections = tuple(
        PointInTimeCohortRejection(
            security_id=candidate.security.security_id,
            symbol=candidate.security.symbol,
            reasons=candidate.rejection_reasons,
        )
        for candidate in canonical_candidates
        if candidate.rejection_reasons
    )
    top_100 = tuple(row.symbol for row in ranking[:100])
    top_75 = top_100[:75]
    top_50 = top_100[:50]
    top_100_id, top_100_sha256 = _universe_identity(top_100)
    top_75_id, top_75_sha256 = _universe_identity(top_75)
    top_50_id, top_50_sha256 = _universe_identity(top_50)
    fields: dict[str, object] = {
        "market_date": normalized_market_date,
        "selection_window_open_at": window_open,
        "selection_window_close_at": window_close,
        "market_session_open_at": session_open,
        "market_session_close_at": session_close,
        "selection_time": selected_at,
        "as_of_cutoff": cutoff,
        "market_calendar": calendar,
        "calendar_retrieved_at": calendar_retrieved,
        "calendar_archive_recorded_at": calendar_recorded,
        "session_dates": session_dates,
        "market_data_feed": market_data_feed,
        "candidates": canonical_candidates,
        "ranking": ranking,
        "rejections": rejections,
        "sensitivity_universe_100": top_100,
        "primary_universe_75": top_75,
        "sensitivity_universe_50": top_50,
        "sensitivity_universe_100_id": top_100_id,
        "sensitivity_universe_100_sha256": top_100_sha256,
        "primary_universe_75_id": top_75_id,
        "primary_universe_75_sha256": top_75_sha256,
        "sensitivity_universe_50_id": top_50_id,
        "sensitivity_universe_50_sha256": top_50_sha256,
    }
    identity = {
        "schema_version": _COHORT_SCHEMA,
        **{
            key: (
                value.to_dict()
                if key == "market_calendar"
                else [item.to_dict() for item in value]
                if key in {"candidates", "ranking", "rejections"}
                else list(value)
                if key in {
                    "session_dates",
                    "sensitivity_universe_100",
                    "primary_universe_75",
                    "sensitivity_universe_50",
                }
                else value
            )
            for key, value in fields.items()
        },
        **_AUTHORITY,
    }
    cohort_id = "point-in-time-cohort-" + _sha256(identity)
    return _new_cohort(
        cohort_id=cohort_id,
        cohort_sha256=_sha256({**identity, "cohort_id": cohort_id}),
        **fields,
    )


def _identity_source_from_dict(value: object) -> PointInTimeCohortIdentitySourceReference:
    fields = frozenset(
        {
            "schema_version",
            "source_profile",
            "source_hash_name",
            "record_identity",
            "raw_artifact_id",
            "raw_artifact_sha256",
            "source_uri",
            "content_type",
            "retrieved_at",
            "archive_recorded_at",
            "qualification_field_selectors",
            *_AUTHORITY,
        }
    )
    payload = _exact(value, fields, label="cohort identity source reference")
    if payload["schema_version"] != _IDENTITY_SOURCE_SCHEMA:
        raise PointInTimeDataError("cohort identity source schema is invalid")
    _authority(payload, label="cohort identity source")
    return PointInTimeCohortIdentitySourceReference(
        source_profile=payload["source_profile"],  # type: ignore[arg-type]
        source_hash_name=payload["source_hash_name"],  # type: ignore[arg-type]
        record_identity=payload["record_identity"],  # type: ignore[arg-type]
        raw_artifact_id=payload["raw_artifact_id"],  # type: ignore[arg-type]
        raw_artifact_sha256=payload["raw_artifact_sha256"],  # type: ignore[arg-type]
        source_uri=payload["source_uri"],  # type: ignore[arg-type]
        content_type=payload["content_type"],  # type: ignore[arg-type]
        retrieved_at=payload["retrieved_at"],  # type: ignore[arg-type]
        archive_recorded_at=payload["archive_recorded_at"],  # type: ignore[arg-type]
        qualification_field_selectors=payload["qualification_field_selectors"],  # type: ignore[arg-type]
    )


def _market_source_from_dict(value: object) -> PointInTimeCohortMarketDataSourceReference:
    fields = frozenset(
        {
            "schema_version",
            "source_profile",
            "record_identity",
            "raw_artifact_id",
            "raw_artifact_sha256",
            "source_uri",
            "content_type",
            "retrieved_at",
            "archive_recorded_at",
            "feed",
            "adjustment",
            "timeframe",
            "bar_selectors",
            *_AUTHORITY,
        }
    )
    payload = _exact(value, fields, label="cohort market source reference")
    if payload["schema_version"] != _MARKET_SOURCE_SCHEMA:
        raise PointInTimeDataError("cohort market source schema is invalid")
    _authority(payload, label="cohort market source")
    selectors = _exact(
        payload["bar_selectors"],
        frozenset({"rows_path", "timestamp_field", "close_field", "volume_field"}),
        label="cohort market source bar selectors",
    )
    return PointInTimeCohortMarketDataSourceReference(
        source_profile=payload["source_profile"],  # type: ignore[arg-type]
        record_identity=payload["record_identity"],  # type: ignore[arg-type]
        raw_artifact_id=payload["raw_artifact_id"],  # type: ignore[arg-type]
        raw_artifact_sha256=payload["raw_artifact_sha256"],  # type: ignore[arg-type]
        source_uri=payload["source_uri"],  # type: ignore[arg-type]
        content_type=payload["content_type"],  # type: ignore[arg-type]
        retrieved_at=payload["retrieved_at"],  # type: ignore[arg-type]
        archive_recorded_at=payload["archive_recorded_at"],  # type: ignore[arg-type]
        feed=payload["feed"],  # type: ignore[arg-type]
        adjustment=payload["adjustment"],  # type: ignore[arg-type]
        timeframe=payload["timeframe"],  # type: ignore[arg-type]
        rows_path=selectors["rows_path"],  # type: ignore[arg-type]
        timestamp_field=selectors["timestamp_field"],  # type: ignore[arg-type]
        close_field=selectors["close_field"],  # type: ignore[arg-type]
        volume_field=selectors["volume_field"],  # type: ignore[arg-type]
    )


def _candidate_from_dict(value: object) -> PointInTimeCohortCandidate:
    fields = frozenset(
        {
            "schema_version",
            "security",
            "prior_complete_close",
            "median_daily_dollar_volume",
            "identity_sources",
            "market_data_source",
            "rejection_reasons",
            *_AUTHORITY,
        }
    )
    payload = _exact(value, fields, label="cohort candidate")
    if payload["schema_version"] != _CANDIDATE_SCHEMA:
        raise PointInTimeDataError("cohort candidate schema is invalid")
    _authority(payload, label="cohort candidate")
    if type(payload["identity_sources"]) is not list:
        raise PointInTimeDataError("cohort candidate identity_sources are invalid")
    return PointInTimeCohortCandidate(
        security=validate_security_identity(payload["security"]),
        prior_complete_close=payload["prior_complete_close"],  # type: ignore[arg-type]
        median_daily_dollar_volume=payload["median_daily_dollar_volume"],  # type: ignore[arg-type]
        identity_sources=tuple(
            _identity_source_from_dict(source)
            for source in payload["identity_sources"]
        ),
        market_data_source=_market_source_from_dict(payload["market_data_source"]),
        rejection_reasons=_reasons(payload["rejection_reasons"]),
    )


def validate_nonqualifying_point_in_time_cohort_record(value: object) -> PointInTimeCohort:
    """Validate canonical bytes only; this does not establish source qualification."""

    payload = _exact(value, _COHORT_SERIALIZED_FIELDS, label="point-in-time cohort")
    if payload["schema_version"] != _COHORT_SCHEMA:
        raise PointInTimeDataError("point-in-time cohort schema is invalid")
    _authority(payload, label="point-in-time cohort")
    if (
        type(payload["session_dates"]) is not list
        or type(payload["candidates"]) is not list
        or len(payload["candidates"]) > _MAX_CANDIDATES
    ):
        raise PointInTimeDataError("point-in-time cohort sequences are invalid")
    rebuilt = build_point_in_time_cohort(
        market_date=payload["market_date"],  # type: ignore[arg-type]
        selection_window_open_at=payload["selection_window_open_at"],  # type: ignore[arg-type]
        selection_window_close_at=payload["selection_window_close_at"],  # type: ignore[arg-type]
        market_session_open_at=payload["market_session_open_at"],  # type: ignore[arg-type]
        market_session_close_at=payload["market_session_close_at"],  # type: ignore[arg-type]
        selection_time=payload["selection_time"],  # type: ignore[arg-type]
        as_of_cutoff=payload["as_of_cutoff"],  # type: ignore[arg-type]
        market_calendar=validate_market_session_calendar(payload["market_calendar"]),
        calendar_retrieved_at=payload["calendar_retrieved_at"],  # type: ignore[arg-type]
        calendar_archive_recorded_at=payload["calendar_archive_recorded_at"],  # type: ignore[arg-type]
        session_dates=tuple(payload["session_dates"]),  # type: ignore[arg-type]
        candidates=tuple(_candidate_from_dict(item) for item in payload["candidates"]),
    )
    if rebuilt.canonical_json_bytes() != _canonical_json_bytes(payload):
        raise PointInTimeDataError("point-in-time cohort bytes do not match canonical rebuild")
    return rebuilt
