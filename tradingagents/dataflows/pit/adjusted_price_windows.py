"""Source-bound, total-return-adjusted Alpaca daily price windows."""

from __future__ import annotations

import dataclasses
import datetime as dt
import hashlib
import json
import re
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from types import MappingProxyType
from urllib.parse import parse_qs, urlsplit

from tradingagents.dataflows.pit.market_calendar import (
    MarketSessionCalendar,
    validate_market_session_calendar,
)
from tradingagents.dataflows.pit.raw_artifacts import (
    RawPointInTimeArtifact,
    RawPointInTimeArtifactArchive,
)
from tradingagents.dataflows.pit.records import PointInTimeDataError

__all__ = [
    "SourceBoundAdjustedPriceWindow",
    "build_source_bound_adjusted_price_window",
    "validate_five_session_adjusted_price_window",
    "validate_source_bound_adjusted_price_window",
    "verify_source_bound_adjusted_price_window",
]


_SCHEMA = "source_bound_adjusted_price_window/v1"
_AUTHORITY = {
    "analysis_only": True,
    "execution_authority": "none",
    "can_submit_orders": False,
}
_ALPACA_HOST = "data.alpaca.markets"
_SYMBOL = re.compile(r"[A-Z][A-Z0-9.-]{0,14}")
_SECURITY_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{2,255}")
_SHA256 = re.compile(r"[0-9a-f]{64}")


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


def _timestamp(value: object, *, label: str) -> str:
    if type(value) is not str:
        raise PointInTimeDataError(f"{label} must be canonical UTC seconds")
    try:
        parsed = dt.datetime.fromisoformat(value)
    except ValueError as exc:
        raise PointInTimeDataError(f"{label} must be canonical UTC seconds") from exc
    if (
        parsed.tzinfo != dt.timezone.utc
        or parsed.microsecond
        or parsed.isoformat(timespec="seconds") != value
    ):
        raise PointInTimeDataError(f"{label} must be canonical UTC seconds")
    return value


def _date(value: object, *, label: str) -> str:
    if type(value) is not str:
        raise PointInTimeDataError(f"{label} must be an ISO market date")
    try:
        parsed = dt.date.fromisoformat(value)
    except ValueError as exc:
        raise PointInTimeDataError(f"{label} must be an ISO market date") from exc
    if parsed.isoformat() != value:
        raise PointInTimeDataError(f"{label} must be an ISO market date")
    return value


def _symbol(value: object, *, label: str) -> str:
    if type(value) is not str or _SYMBOL.fullmatch(value) is None:
        raise PointInTimeDataError(f"{label} must be a normalized uppercase ticker")
    return value


def _security_id(value: object) -> str:
    if type(value) is not str or _SECURITY_ID.fullmatch(value) is None:
        raise PointInTimeDataError("security_id must be a canonical nonempty identifier")
    return value


def _requested_source_bounds(start: str, end: str) -> tuple[str, str]:
    """Return the canonical inclusive-date / exclusive-next-midnight request bounds."""

    try:
        end_date = dt.date.fromisoformat(end) + dt.timedelta(days=1)
    except OverflowError as exc:
        raise PointInTimeDataError(
            "requested_end cannot produce an exclusive next-day source bound"
        ) from exc
    return (
        f"{start}T00:00:00Z",
        f"{end_date.isoformat()}T00:00:00Z",
    )


def _positive_decimal(value: object, *, label: str) -> str:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise PointInTimeDataError(f"{label} must be a finite positive close") from exc
    if not parsed.is_finite() or parsed <= 0:
        raise PointInTimeDataError(f"{label} must be a finite positive close")
    return format(parsed.normalize(), "f")


def _source_material(
    artifact: RawPointInTimeArtifact,
    *,
    symbol: str,
    requested_start: str,
    requested_end: str,
) -> tuple[str, str]:
    parsed = urlsplit(artifact.source_uri)
    if parsed.hostname != _ALPACA_HOST or parsed.path != f"/v2/stocks/{symbol}/bars":
        raise PointInTimeDataError("raw artifact is not the requested Alpaca stock-bar route")
    if artifact.content_type != "application/json":
        raise PointInTimeDataError("Alpaca price source must be JSON")
    query = parse_qs(parsed.query, keep_blank_values=True)
    if "page_token" in query:
        raise PointInTimeDataError("Alpaca price source cannot start from a continuation page")
    source_start, source_end = _requested_source_bounds(requested_start, requested_end)
    if (
        query.get("timeframe") != ["1Day"]
        or query.get("feed") not in (["iex"], ["sip"])
        or query.get("adjustment") != ["all"]
        or query.get("start") != [source_start]
        or query.get("end") != [source_end]
    ):
        raise PointInTimeDataError(
            "Alpaca price source must pin its 1Day range, feed, and total-return adjustment"
        )
    return query["feed"][0], query["adjustment"][0]


def _bars(
    raw_bytes: bytes,
    *,
    symbol: str,
    requested_start: str,
    requested_end: str,
) -> tuple[tuple[str, str], ...]:
    try:
        payload = json.loads(raw_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PointInTimeDataError("Alpaca price source bytes are not JSON") from exc
    if not isinstance(payload, Mapping) or payload.get("symbol") != symbol:
        raise PointInTimeDataError("Alpaca price source symbol does not match the requested route")
    if "next_page_token" not in payload or payload["next_page_token"] is not None:
        raise PointInTimeDataError("Alpaca price source must be a complete, unpaginated response")
    # The single-symbol REST route returns a list. A symbol-indexed mapping
    # belongs to the multi-symbol REST route or an SDK conversion, not these bytes.
    symbol_bars = payload.get("bars")
    if type(symbol_bars) is not list or not symbol_bars:
        raise PointInTimeDataError("Alpaca price source has no bars for requested symbol")
    parsed: list[tuple[str, str]] = []
    for index, row in enumerate(symbol_bars):
        if not isinstance(row, Mapping):
            raise PointInTimeDataError(f"Alpaca bar {index} must be an object")
        raw_timestamp = row.get("t")
        if type(raw_timestamp) is not str:
            raise PointInTimeDataError(f"Alpaca bar {index} has no timestamp")
        normalized = raw_timestamp.removesuffix("Z") + (
            "+00:00" if raw_timestamp.endswith("Z") else ""
        )
        try:
            timestamp = dt.datetime.fromisoformat(normalized)
        except ValueError as exc:
            raise PointInTimeDataError(f"Alpaca bar {index} timestamp is invalid") from exc
        if timestamp.tzinfo != dt.timezone.utc or timestamp.microsecond:
            raise PointInTimeDataError(f"Alpaca bar {index} timestamp is invalid")
        market_date = timestamp.date().isoformat()
        if timestamp.weekday() >= 5:
            raise PointInTimeDataError(f"Alpaca bar {index} is not a weekday session")
        if requested_start <= market_date <= requested_end:
            parsed.append((market_date, _positive_decimal(row.get("c"), label=f"Alpaca bar {index} close")))
    if len(parsed) < 2:
        raise PointInTimeDataError("Alpaca price window requires two in-range daily bars")
    if parsed != sorted(parsed) or len({market_date for market_date, _ in parsed}) != len(parsed):
        raise PointInTimeDataError("Alpaca in-range daily bars must be chronological and unique")
    return tuple(parsed)


@dataclasses.dataclass(frozen=True, slots=True, init=False)
class SourceBoundAdjustedPriceWindow:
    """A return-measurement window derived only from one sealed Alpaca response."""

    window_id: str
    window_sha256: str
    security_id: str
    symbol: str
    requested_start: str
    requested_end: str
    decision_cutoff: str
    entry_date: str
    entry_close: str
    exit_date: str
    exit_close: str
    session_count: int
    daily_closes: tuple[tuple[str, str], ...]
    raw_artifact_id: str
    raw_artifact_sha256: str
    retrieved_at: str
    feed: str
    adjustment_mode: str
    adjustment_status: str
    source_span: Mapping[str, object]

    def __init__(self, *args: object, **kwargs: object) -> None:
        raise TypeError("SourceBoundAdjustedPriceWindow instances require its builder")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": _SCHEMA,
            "window_id": self.window_id,
            "window_sha256": self.window_sha256,
            "security_id": self.security_id,
            "symbol": self.symbol,
            "requested_start": self.requested_start,
            "requested_end": self.requested_end,
            "decision_cutoff": self.decision_cutoff,
            "entry_date": self.entry_date,
            "entry_close": self.entry_close,
            "exit_date": self.exit_date,
            "exit_close": self.exit_close,
            "session_count": self.session_count,
            "daily_closes": [
                {"market_date": market_date, "close": close}
                for market_date, close in self.daily_closes
            ],
            "raw_artifact_id": self.raw_artifact_id,
            "raw_artifact_sha256": self.raw_artifact_sha256,
            "retrieved_at": self.retrieved_at,
            "feed": self.feed,
            "adjustment_mode": self.adjustment_mode,
            "adjustment_status": self.adjustment_status,
            "source_span": dict(self.source_span),
            **_AUTHORITY,
        }

    def canonical_json_bytes(self) -> bytes:
        return _canonical_json_bytes(self.to_dict())


_FIELD_NAMES = tuple(field.name for field in dataclasses.fields(SourceBoundAdjustedPriceWindow))
_SERIALIZED_FIELDS = frozenset(_FIELD_NAMES + ("schema_version",) + tuple(_AUTHORITY))


def _new_window(**fields: object) -> SourceBoundAdjustedPriceWindow:
    value = object.__new__(SourceBoundAdjustedPriceWindow)
    for name in _FIELD_NAMES:
        object.__setattr__(value, name, fields[name])
    return value


def _from_material(
    *,
    security_id: object,
    symbol: object,
    requested_start: object,
    requested_end: object,
    decision_cutoff: object,
    bars: tuple[tuple[str, str], ...],
    raw_artifact_id: object,
    raw_artifact_sha256: object,
    retrieved_at: object,
    feed: object,
    adjustment_mode: object,
    source_span: object,
) -> SourceBoundAdjustedPriceWindow:
    normalized_security_id = _security_id(security_id)
    normalized_symbol = _symbol(symbol, label="symbol")
    start = _date(requested_start, label="requested_start")
    end = _date(requested_end, label="requested_end")
    if start > end:
        raise PointInTimeDataError("requested price window dates are reversed")
    cutoff = _timestamp(decision_cutoff, label="decision_cutoff")
    retrieved = _timestamp(retrieved_at, label="retrieved_at")
    if retrieved > cutoff:
        raise PointInTimeDataError("price source was retrieved after the decision cutoff")
    if (
        type(raw_artifact_id) is not str
        or not raw_artifact_id.startswith("pit-raw-artifact-")
        or type(raw_artifact_sha256) is not str
        or _SHA256.fullmatch(raw_artifact_sha256) is None
    ):
        raise PointInTimeDataError("price window raw artifact identity is invalid")
    if feed not in {"iex", "sip"} or adjustment_mode != "all":
        raise PointInTimeDataError("price window feed or adjustment mode is invalid")
    if not isinstance(source_span, Mapping) or set(source_span) != {
        "span_type",
        "start_byte",
        "end_byte",
        "source_sha256",
    }:
        raise PointInTimeDataError("price window source span is invalid")
    if (
        source_span["span_type"] != "byte_range"
        or type(source_span["start_byte"]) is not int
        or type(source_span["end_byte"]) is not int
        or source_span["start_byte"] != 0
        or source_span["end_byte"] <= 0
        or source_span["source_sha256"] != raw_artifact_sha256
    ):
        raise PointInTimeDataError("price window source span is invalid")
    if len(bars) < 2 or bars != tuple(sorted(bars)):
        raise PointInTimeDataError("price window bars are invalid")
    if (
        len({market_date for market_date, _ in bars}) != len(bars)
        or any(
            market_date < start
            or market_date > end
            or dt.date.fromisoformat(market_date).weekday() >= 5
            for market_date, _ in bars
        )
    ):
        raise PointInTimeDataError("price window bars fall outside valid weekday sessions")
    count = len(bars)
    material = {
        "schema_version": _SCHEMA,
        "security_id": normalized_security_id,
        "symbol": normalized_symbol,
        "requested_start": start,
        "requested_end": end,
        "decision_cutoff": cutoff,
        "entry_date": bars[0][0],
        "entry_close": bars[0][1],
        "exit_date": bars[-1][0],
        "exit_close": bars[-1][1],
        "session_count": count,
        "daily_closes": [
            {"market_date": market_date, "close": close}
            for market_date, close in bars
        ],
        "raw_artifact_id": raw_artifact_id,
        "raw_artifact_sha256": raw_artifact_sha256,
        "retrieved_at": retrieved,
        "feed": feed,
        "adjustment_mode": adjustment_mode,
        "adjustment_status": "total_return_adjusted",
        "source_span": dict(source_span),
        **_AUTHORITY,
    }
    window_id = "source-bound-adjusted-price-window-" + _sha256(material)
    digest = _sha256({**material, "window_id": window_id})
    fields: dict[str, object] = {
        "window_id": window_id,
        "window_sha256": digest,
        **material,
    }
    fields["source_span"] = MappingProxyType(dict(source_span))
    fields["daily_closes"] = bars
    return _new_window(**fields)


def build_source_bound_adjusted_price_window(
    *,
    archive: RawPointInTimeArtifactArchive,
    raw_artifact: RawPointInTimeArtifact,
    security_id: str,
    symbol: str,
    requested_start: str,
    requested_end: str,
    decision_cutoff: str,
) -> SourceBoundAdjustedPriceWindow:
    """Derive a total-return price window from exact eligible Alpaca bytes."""

    if type(archive) is not RawPointInTimeArtifactArchive:
        raise PointInTimeDataError("archive must be an exact raw PIT artifact archive")
    if type(raw_artifact) is not RawPointInTimeArtifact:
        raise PointInTimeDataError("raw_artifact must be an exact raw PIT artifact")
    normalized_symbol = _symbol(symbol, label="symbol")
    persisted = archive.read_receipt(raw_artifact)
    start = _date(requested_start, label="requested_start")
    end = _date(requested_end, label="requested_end")
    feed, adjustment = _source_material(
        persisted,
        symbol=normalized_symbol,
        requested_start=start,
        requested_end=end,
    )
    raw_bytes = archive.read_bytes(persisted)
    bars = _bars(
        raw_bytes,
        symbol=normalized_symbol,
        requested_start=start,
        requested_end=end,
    )
    return _from_material(
        security_id=security_id,
        symbol=normalized_symbol,
        requested_start=start,
        requested_end=end,
        decision_cutoff=decision_cutoff,
        bars=bars,
        raw_artifact_id=persisted.raw_artifact_id,
        raw_artifact_sha256=persisted.raw_artifact_sha256,
        retrieved_at=persisted.retrieved_at,
        feed=feed,
        adjustment_mode=adjustment,
        source_span={
            "span_type": "byte_range",
            "start_byte": 0,
            "end_byte": len(raw_bytes),
            "source_sha256": persisted.raw_artifact_sha256,
        },
    )


def validate_source_bound_adjusted_price_window(
    value: object,
) -> SourceBoundAdjustedPriceWindow:
    """Rebuild the canonical receipt fields of a derived price window."""

    if not isinstance(value, Mapping) or set(value) != _SERIALIZED_FIELDS:
        raise PointInTimeDataError("source-bound price window fields are invalid")
    payload = dict(value)
    if payload["schema_version"] != _SCHEMA or any(
        payload[key] != expected for key, expected in _AUTHORITY.items()
    ):
        raise PointInTimeDataError("source-bound price window schema or authority is invalid")
    raw_id = payload["raw_artifact_id"]
    raw_digest = payload["raw_artifact_sha256"]
    if (
        type(raw_id) is not str
        or not raw_id.startswith("pit-raw-artifact-")
        or type(raw_digest) is not str
        or _SHA256.fullmatch(raw_digest) is None
    ):
        raise PointInTimeDataError("source-bound price window raw evidence is invalid")
    serialized_bars = payload["daily_closes"]
    if type(serialized_bars) is not list:
        raise PointInTimeDataError("source-bound price window daily_closes is invalid")
    bars: list[tuple[str, str]] = []
    for index, row in enumerate(serialized_bars):
        if not isinstance(row, Mapping) or set(row) != {"market_date", "close"}:
            raise PointInTimeDataError(
                f"source-bound price window daily close {index} is invalid"
            )
        bars.append(
            (
                _date(row["market_date"], label=f"daily close {index} market_date"),
                _positive_decimal(row["close"], label=f"daily close {index} close"),
            )
        )
    rebuilt = _from_material(
        security_id=payload["security_id"],
        symbol=payload["symbol"],
        requested_start=payload["requested_start"],
        requested_end=payload["requested_end"],
        decision_cutoff=payload["decision_cutoff"],
        bars=tuple(bars),
        raw_artifact_id=raw_id,
        raw_artifact_sha256=raw_digest,
        retrieved_at=payload["retrieved_at"],
        feed=payload["feed"],
        adjustment_mode=payload["adjustment_mode"],
        source_span=payload["source_span"],
    )
    if rebuilt.canonical_json_bytes() != _canonical_json_bytes(payload):
        raise PointInTimeDataError("source-bound price window bytes do not match canonical rebuild")
    return rebuilt


def verify_source_bound_adjusted_price_window(
    *,
    archive: RawPointInTimeArtifactArchive,
    raw_artifact: RawPointInTimeArtifact,
    value: object,
) -> SourceBoundAdjustedPriceWindow:
    """Re-derive a serialized window from its exact immutable source bytes."""

    if type(archive) is not RawPointInTimeArtifactArchive:
        raise PointInTimeDataError("archive must be an exact raw PIT artifact archive")
    if type(raw_artifact) is not RawPointInTimeArtifact:
        raise PointInTimeDataError("raw_artifact must be an exact raw PIT artifact")
    window = validate_source_bound_adjusted_price_window(value)
    if (
        raw_artifact.raw_artifact_id != window.raw_artifact_id
        or raw_artifact.raw_artifact_sha256 != window.raw_artifact_sha256
    ):
        raise PointInTimeDataError("price window does not name the supplied raw artifact")
    rebuilt = build_source_bound_adjusted_price_window(
        archive=archive,
        raw_artifact=raw_artifact,
        security_id=window.security_id,
        symbol=window.symbol,
        requested_start=window.requested_start,
        requested_end=window.requested_end,
        decision_cutoff=window.decision_cutoff,
    )
    if rebuilt.canonical_json_bytes() != window.canonical_json_bytes():
        raise PointInTimeDataError("price window does not match its immutable source bytes")
    return rebuilt


def validate_five_session_adjusted_price_window(
    *,
    value: object,
    market_calendar: MarketSessionCalendar,
    decision_market_date: str,
) -> SourceBoundAdjustedPriceWindow:
    """Bind one adjusted outcome window to the next five admitted sessions.

    The first row is the next regular session after the registered decision
    date and the fifth row is the exit session.  The calendar receipt remains
    the authority for session membership; this helper performs no retrieval.
    """

    window = validate_source_bound_adjusted_price_window(value)
    if type(market_calendar) is not MarketSessionCalendar:
        raise PointInTimeDataError(
            "market_calendar must be an exact MarketSessionCalendar"
        )
    calendar = validate_market_session_calendar(market_calendar.to_dict())
    decision_date = _date(decision_market_date, label="decision_market_date")
    later_sessions = tuple(
        market_date for market_date in calendar.market_dates if market_date > decision_date
    )
    if len(later_sessions) < 5:
        raise PointInTimeDataError(
            "market calendar does not prove five post-decision sessions"
        )
    expected = later_sessions[:5]
    observed = tuple(market_date for market_date, _close in window.daily_closes)
    if observed != expected:
        raise PointInTimeDataError(
            "adjusted price window must contain the exact next five calendar sessions"
        )
    return window
