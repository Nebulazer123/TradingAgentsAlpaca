"""Source-derived point-in-time SEC and Alpaca observations."""

from __future__ import annotations

import datetime as dt
import json
import re
from collections.abc import Mapping, Sequence
from decimal import Decimal, DecimalException
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

from tradingagents.dataflows.pit.market_calendar import (
    MarketSessionCalendar,
    _resolve_source_session,
)
from tradingagents.dataflows.pit.raw_artifacts import (
    RawPointInTimeArtifact,
    RawPointInTimeArtifactArchive,
)
from tradingagents.dataflows.pit.records import (
    PointInTimeDataError,
    PointInTimeObservation,
    SecurityIdentity,
)

__all__ = ["build_alpaca_market_observation", "build_sec_fundamental_observation"]

_SEC_HOSTS = frozenset({"data.sec.gov", "www.sec.gov"})
_ALPACA_HOSTS = frozenset({"data.alpaca.markets"})
_ALPACA_ADJUSTMENT_STATUS = {
    "raw": "unadjusted",
    "split": "split_adjusted",
    "all": "total_return_adjusted",
}
_ALPACA_VALUE_FIELDS = frozenset({"o", "h", "l", "c", "v", "n", "vw"})
_ALPACA_DECIMAL_FIELDS = frozenset({"o", "h", "l", "c", "vw"})
_ALPACA_INTEGER_FIELDS = frozenset({"v", "n"})
_ALPACA_TIMEFRAME_SECONDS = {
    "1Min": 60,
    "5Min": 300,
    "15Min": 900,
    "30Min": 1_800,
    "1Hour": 3_600,
}
_SEC_DECIMAL_LIMITS = (1_024, 1_024, 2_048)
_ALPACA_DECIMAL_LIMITS = (128, 128, 256)
_MARKET_TZ = ZoneInfo("America/New_York")


def _bytes(
    archive: RawPointInTimeArtifactArchive,
    artifact: RawPointInTimeArtifact,
) -> bytes:
    if type(archive) is not RawPointInTimeArtifactArchive:
        raise PointInTimeDataError("archive must be an exact raw PIT artifact archive")
    if type(artifact) is not RawPointInTimeArtifact:
        raise PointInTimeDataError("raw_artifact must be an exact raw PIT artifact")
    return archive.read_bytes(artifact)


def _json_mapping(raw_bytes: bytes, *, label: str) -> Mapping[str, object]:
    def reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise PointInTimeDataError(
                    f"{label} source JSON contains a duplicate key"
                )
            result[key] = value
        return result

    def reject_nonfinite_constant(_value: str) -> object:
        raise PointInTimeDataError(
            f"{label} source JSON contains a nonfinite number"
        )

    try:
        parsed = json.loads(
            raw_bytes,
            object_pairs_hook=reject_duplicate_keys,
            parse_constant=reject_nonfinite_constant,
            parse_float=Decimal,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PointInTimeDataError(f"{label} source bytes are not JSON") from exc
    if not isinstance(parsed, Mapping):
        raise PointInTimeDataError(f"{label} source JSON must be an object")
    return parsed


def _timestamp(value: object, *, label: str) -> str:
    if type(value) is not str:
        raise PointInTimeDataError(f"{label} is absent from the raw source")
    normalized = value.removesuffix("Z") + ("+00:00" if value.endswith("Z") else "")
    try:
        parsed = dt.datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise PointInTimeDataError(f"{label} is not a source UTC timestamp") from exc
    if parsed.tzinfo != dt.UTC or parsed.microsecond:
        raise PointInTimeDataError(f"{label} is not a source UTC timestamp")
    return parsed.isoformat(timespec="seconds")


def _json_path(value: object, *, label: str) -> tuple[str | int, ...]:
    if type(value) not in (list, tuple) or not value:
        raise PointInTimeDataError(f"{label} must be a nonempty exact JSON path")
    result: list[str | int] = []
    for component in value:
        if type(component) is str and component:
            result.append(component)
            continue
        if type(component) is int and component >= 0:
            result.append(component)
            continue
        raise PointInTimeDataError(f"{label} contains an invalid JSON path component")
    return tuple(result)


def _select_json(
    payload: object,
    path: Sequence[str | int],
    *,
    label: str,
) -> object:
    selected = payload
    for component in path:
        if type(component) is str and isinstance(selected, Mapping):
            if component not in selected:
                raise PointInTimeDataError(f"{label} is absent from the raw source")
            selected = selected[component]
            continue
        if type(component) is int and type(selected) is list:
            if component >= len(selected):
                raise PointInTimeDataError(f"{label} is absent from the raw source")
            selected = selected[component]
            continue
        raise PointInTimeDataError(f"{label} does not resolve in the raw source")
    return selected


def _security_identity(value: object) -> SecurityIdentity:
    if type(value) is not SecurityIdentity:
        raise PointInTimeDataError(
            "security_identity must be an exact PIT SecurityIdentity"
        )
    return value


def _canonical_decimal(
    value: Decimal | int,
    *,
    label: str,
    limits: tuple[int, int, int],
) -> str:
    max_digits, max_exponent, max_output_chars = limits
    try:
        decimal_value = value if type(value) is Decimal else Decimal(value)
        if not decimal_value.is_finite():
            raise PointInTimeDataError(f"{label} must be finite")
        if decimal_value.is_zero():
            return "0"
        sign, digits, exponent = decimal_value.as_tuple()
    except PointInTimeDataError:
        raise
    except (DecimalException, TypeError, ValueError, OverflowError) as exc:
        raise PointInTimeDataError(f"{label} is not a bounded decimal") from exc

    digit_count = len(digits)
    adjusted_exponent = digit_count + exponent - 1
    if (
        digit_count > max_digits
        or abs(exponent) > max_exponent
        or abs(adjusted_exponent) > max_exponent
    ):
        raise PointInTimeDataError(f"{label} exceeds decimal resource limits")
    if exponent >= 0:
        predicted_length = digit_count + exponent
    else:
        decimal_position = digit_count + exponent
        predicted_length = (
            digit_count + 1
            if decimal_position > 0
            else 2 - decimal_position + digit_count
        )
    predicted_length += sign
    if predicted_length > max_output_chars:
        raise PointInTimeDataError(f"{label} exceeds decimal output limits")

    try:
        text = format(decimal_value, "f")
    except (DecimalException, ValueError, OverflowError) as exc:
        raise PointInTimeDataError(f"{label} cannot be canonicalized") from exc
    if len(text) > max_output_chars:
        raise PointInTimeDataError(f"{label} exceeds decimal output limits")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def _normalize_source_value(value: object) -> object:
    if type(value) is Decimal:
        return _canonical_decimal(
            value,
            label="SEC selected decimal",
            limits=_SEC_DECIMAL_LIMITS,
        )
    if isinstance(value, Mapping):
        return {
            key: _normalize_source_value(item)
            for key, item in value.items()
        }
    if type(value) is list:
        return [_normalize_source_value(item) for item in value]
    return value


def _alpaca_value(value: object, *, field: str) -> object:
    if field in _ALPACA_DECIMAL_FIELDS:
        if type(value) not in (int, Decimal):
            raise PointInTimeDataError(
                f"Alpaca {field} must be a JSON number"
            )
        decimal_value = value if type(value) is Decimal else Decimal(value)
        if not decimal_value.is_finite() or decimal_value <= 0:
            raise PointInTimeDataError(
                f"Alpaca {field} must be a finite positive number"
            )
        return _canonical_decimal(
            decimal_value,
            label=f"Alpaca {field}",
            limits=_ALPACA_DECIMAL_LIMITS,
        )
    if field in _ALPACA_INTEGER_FIELDS:
        if type(value) is not int or value < 0:
            raise PointInTimeDataError(
                f"Alpaca {field} must be a nonnegative exact integer"
            )
        return value
    raise PointInTimeDataError("Alpaca value_field is not recognized")


def _source_cik(value: object) -> str:
    if type(value) is int and 0 <= value <= 9_999_999_999:
        return f"{value:010d}"
    if type(value) is str and re.fullmatch(r"[0-9]{10}", value) is not None:
        return value
    raise PointInTimeDataError("SEC source identity is not a canonical CIK")


def _single_query_value(
    query: Mapping[str, list[str]],
    field: str,
) -> str:
    values = query.get(field)
    if values is None or len(values) != 1 or not values[0]:
        raise PointInTimeDataError(f"Alpaca URL must bind exactly one {field}")
    return values[0]


def _alpaca_bar_path(
    parsed_url,
    *,
    query: Mapping[str, list[str]],
    payload: Mapping[str, object],
    expected_symbol: str,
    bar_path: Sequence[str | int],
) -> tuple[str | int, ...]:
    """Bind the exact selector to the endpoint's single- or multi-symbol shape."""

    selected = _json_path(bar_path, label="Alpaca bar_path")
    if parsed_url.path == f"/v2/stocks/{expected_symbol}/bars":
        if payload.get("symbol") != expected_symbol:
            raise PointInTimeDataError("Alpaca response symbol does not match the security")
        prefix = ("bars",)
    elif parsed_url.path == "/v2/stocks/bars":
        symbols = _single_query_value(query, "symbols").split(",")
        if not all(symbols) or len(set(symbols)) != len(symbols) or expected_symbol not in symbols:
            raise PointInTimeDataError("Alpaca URL does not unambiguously request the security symbol")
        prefix = ("bars", expected_symbol)
    else:
        raise PointInTimeDataError(
            "Alpaca URL is not a supported bars endpoint for the security symbol"
        )
    if len(selected) != len(prefix) + 1 or selected[:-1] != prefix or type(selected[-1]) is not int:
        raise PointInTimeDataError("Alpaca bar_path must bind one bar for the security symbol")
    return selected


def _bar_completion(
    event_time: str,
    *,
    timeframe: str,
    archive: RawPointInTimeArtifactArchive,
    market_calendar: MarketSessionCalendar,
) -> tuple[str, str, dict[str, object], MarketSessionCalendar]:
    parsed = dt.datetime.fromisoformat(event_time)
    local_event = parsed.astimezone(_MARKET_TZ)
    local_date = local_event.date()
    session_date = local_date.isoformat()
    calendar, session_material = _resolve_source_session(
        archive=archive,
        market_calendar=market_calendar,
        session_date=session_date,
    )
    regular_open = dt.time.fromisoformat(
        str(session_material["regular_session_open"])
    )
    regular_close = dt.time.fromisoformat(
        str(session_material["regular_session_close"])
    )
    local_time = local_event.timetz().replace(tzinfo=None)
    if timeframe == "1Day":
        if local_time != dt.time(0, 0):
            raise PointInTimeDataError(
                "Alpaca daily bar does not identify the calendar session midnight"
            )
        completion = dt.datetime.combine(
            local_date,
            regular_close,
            tzinfo=_MARKET_TZ,
        ).astimezone(dt.UTC)
        method = "registered_regular_session_close"
        duration: int | None = None
    else:
        duration = _ALPACA_TIMEFRAME_SECONDS.get(timeframe)
        if duration is None:
            raise PointInTimeDataError("Alpaca timeframe is not explicitly supported")
        if not (regular_open <= local_time < regular_close):
            raise PointInTimeDataError(
                "Alpaca intraday bar is outside the regular market session"
            )
        session_open = dt.datetime.combine(
            local_date,
            regular_open,
            tzinfo=_MARKET_TZ,
        )
        elapsed = int((local_event - session_open).total_seconds())
        if local_event.microsecond or elapsed < 0 or elapsed % duration:
            raise PointInTimeDataError(
                "Alpaca intraday bar start is not aligned to its timeframe"
            )
        completion = parsed + dt.timedelta(seconds=duration)
        local_completion = completion.astimezone(_MARKET_TZ)
        if (
            local_completion.date() != local_date
            or local_completion.timetz().replace(tzinfo=None) > regular_close
        ):
            raise PointInTimeDataError(
                "Alpaca intraday bar overruns the regular market session"
            )
        method = "bar_start_plus_timeframe"
    completion_time = completion.isoformat(timespec="seconds")
    return (
        session_date,
        completion_time,
        {
            **session_material,
            "method": method,
            "completion_time": completion_time,
            "market_timezone": "America/New_York",
            "bar_duration_seconds": duration,
        },
        calendar,
    )


def build_sec_fundamental_observation(
    *,
    security_identity: SecurityIdentity,
    archive: RawPointInTimeArtifactArchive,
    raw_artifact: RawPointInTimeArtifact,
    source_identity_path: Sequence[str | int],
    value_path: Sequence[str | int],
    event_time_path: Sequence[str | int],
    publication_time_path: Sequence[str | int],
) -> PointInTimeObservation:
    """Derive one SEC fact and its times from explicit archived JSON paths."""

    identity = _security_identity(security_identity)
    raw_bytes = _bytes(archive, raw_artifact)
    if (
        urlsplit(raw_artifact.source_uri).hostname not in _SEC_HOSTS
        or raw_artifact.content_type != "application/json"
    ):
        raise PointInTimeDataError("raw artifact is not an SEC JSON source")
    payload = _json_mapping(raw_bytes, label="SEC")
    cik_path = _json_path(source_identity_path, label="SEC source_identity_path")
    selected_value_path = _json_path(value_path, label="SEC value_path")
    selected_event_path = _json_path(event_time_path, label="SEC event_time_path")
    selected_publication_path = _json_path(
        publication_time_path,
        label="SEC publication_time_path",
    )
    if identity.cik is None or _source_cik(
        _select_json(payload, cik_path, label="SEC source identity")
    ) != identity.cik:
        raise PointInTimeDataError(
            "SEC source identity does not match the bound security identity"
        )
    observed_value = _normalize_source_value(
        _select_json(
            payload,
            selected_value_path,
            label="SEC observed value",
        )
    )
    event_time = _timestamp(
        _select_json(payload, selected_event_path, label="SEC event_time"),
        label="SEC event_time",
    )
    publication_time = _timestamp(
        _select_json(
            payload,
            selected_publication_path,
            label="SEC publication_time",
        ),
        label="SEC publication_time",
    )
    return PointInTimeObservation(
        security_id=identity.security_id,
        identity_effective_from=identity.effective_from,
        identity_effective_to=identity.effective_to,
        event_time=event_time,
        publication_time=publication_time,
        availability_time=raw_artifact.retrieved_at,
        retrieval_time=raw_artifact.archive_recorded_at,
        raw_artifact_id=raw_artifact.raw_artifact_id,
        raw_artifact_sha256=raw_artifact.raw_artifact_sha256,
        observed_value=observed_value,
        market_data_feed=None,
        adjustment_mode=None,
        market_session=None,
        session_date=None,
        adjustment_status="unadjusted",
        source_span={
            "source_kind": "sec_json_xbrl",
            "span_type": "json_paths",
            "source_sha256": raw_artifact.raw_artifact_sha256,
            "paths": {
                "source_identity": cik_path,
                "observed_value": selected_value_path,
                "event_time": selected_event_path,
                "publication_time": selected_publication_path,
            },
        },
    )


def build_alpaca_market_observation(
    *,
    security_identity: SecurityIdentity,
    archive: RawPointInTimeArtifactArchive,
    raw_artifact: RawPointInTimeArtifact,
    market_calendar: MarketSessionCalendar,
    bar_path: Sequence[str | int],
    value_field: str,
) -> PointInTimeObservation:
    """Derive bar time and feed/adjustment facts from archived response evidence."""

    identity = _security_identity(security_identity)
    raw_bytes = _bytes(archive, raw_artifact)
    parsed_url = urlsplit(raw_artifact.source_uri)
    if (
        parsed_url.hostname not in _ALPACA_HOSTS
        or raw_artifact.content_type != "application/json"
    ):
        raise PointInTimeDataError("raw artifact is not Alpaca market-data JSON")
    query = parse_qs(parsed_url.query, keep_blank_values=True)
    feed = _single_query_value(query, "feed")
    adjustment = _single_query_value(query, "adjustment")
    timeframe = _single_query_value(query, "timeframe")
    if feed not in {"iex", "sip"} or adjustment not in _ALPACA_ADJUSTMENT_STATUS:
        raise PointInTimeDataError("Alpaca URL has unsupported feed or adjustment")
    payload = _json_mapping(raw_bytes, label="Alpaca")
    selected_bar_path = _alpaca_bar_path(
        parsed_url, query=query, payload=payload,
        expected_symbol=identity.symbol, bar_path=bar_path,
    )
    selected_bar = _select_json(
        payload,
        selected_bar_path,
        label="Alpaca selected bar",
    )
    if not isinstance(selected_bar, Mapping):
        raise PointInTimeDataError("Alpaca selected bar is not an object")
    if type(value_field) is not str or value_field not in _ALPACA_VALUE_FIELDS:
        raise PointInTimeDataError("Alpaca value_field is not recognized")
    value_path = (*selected_bar_path, value_field)
    event_path = (*selected_bar_path, "t")
    observed_value = _alpaca_value(
        _select_json(
            payload,
            value_path,
            label="Alpaca observed value",
        ),
        field=value_field,
    )
    event_time = _timestamp(
        _select_json(payload, event_path, label="Alpaca bar timestamp"),
        label="Alpaca bar timestamp",
    )
    session_date, publication_time, publication_derivation, calendar = _bar_completion(
        event_time,
        timeframe=timeframe,
        archive=archive,
        market_calendar=market_calendar,
    )
    if dt.datetime.fromisoformat(raw_artifact.retrieved_at) < dt.datetime.fromisoformat(
        publication_time
    ):
        raise PointInTimeDataError(
            "Alpaca source retrieval precedes proven bar completion"
        )
    return PointInTimeObservation(
        security_id=identity.security_id,
        identity_effective_from=identity.effective_from,
        identity_effective_to=identity.effective_to,
        event_time=event_time,
        publication_time=publication_time,
        availability_time=raw_artifact.retrieved_at,
        retrieval_time=raw_artifact.archive_recorded_at,
        raw_artifact_id=raw_artifact.raw_artifact_id,
        raw_artifact_sha256=raw_artifact.raw_artifact_sha256,
        observed_value=observed_value,
        market_data_feed=feed,
        adjustment_mode=adjustment,
        market_session="regular",
        session_date=session_date,
        adjustment_status=_ALPACA_ADJUSTMENT_STATUS[adjustment],
        source_span={
            "source_kind": "alpaca_market_data",
            "span_type": "json_paths",
            "source_sha256": raw_artifact.raw_artifact_sha256,
            "market_calendar_id": calendar.calendar_id,
            "market_calendar_sha256": calendar.calendar_sha256,
            "timeframe": timeframe,
            "publication_derivation": publication_derivation,
            "paths": {
                "observed_value": value_path,
                "event_time": event_path,
            },
        },
    )
