"""Archive-backed admission for source-verifiable economic cohorts."""

from __future__ import annotations

import datetime as dt
import json
import re
from collections.abc import Mapping, Sequence
from decimal import Decimal, DecimalException
from urllib.parse import parse_qsl, urlsplit
from zoneinfo import ZoneInfo

from tradingagents.dataflows.pit.cohort import (
    PointInTimeCohort,
    PointInTimeCohortCandidate,
    PointInTimeCohortIdentitySourceReference,
    PointInTimeCohortMarketDataSourceReference,
    build_point_in_time_cohort,
    validate_point_in_time_cohort,
)
from tradingagents.dataflows.pit.market_calendar import (
    MarketSessionCalendar,
    build_market_session_calendar,
    validate_market_session_calendar,
)
from tradingagents.dataflows.pit.raw_artifacts import (
    RawPointInTimeArtifact,
    RawPointInTimeArtifactArchive,
)
from tradingagents.dataflows.pit.records import (
    PointInTimeDataError,
    SecurityIdentity,
    validate_security_identity,
)

__all__ = [
    "build_source_verifiable_point_in_time_cohort",
    "verify_source_verifiable_point_in_time_cohort",
]


_UTC_TIMESTAMP = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\+00:00"
)
_SESSION_TIME = re.compile(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]")
_QUALIFICATION_FIELDS = frozenset(
    {
        "security_id",
        "symbol",
        "exchange",
        "security_type",
        "effective_from",
        "effective_to",
        "status",
        "asset_class",
        "tradable",
    }
)
_US_LISTED_EXCHANGES = frozenset(
    {"AMEX", "ARCA", "BATS", "NASDAQ", "NYSE", "NYSEARCA"}
)
_ALPACA_ASSET_HOSTS = frozenset(
    {"api.alpaca.markets", "paper-api.alpaca.markets"}
)
_MARKET_TZ = ZoneInfo("America/New_York")
_DECIMAL_LIMITS = (128, 128, 256)


def _exact(value: object, fields: frozenset[str], *, label: str) -> dict[str, object]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise PointInTimeDataError(f"{label} fields are invalid")
    return dict(value)


def _timestamp(value: object, *, label: str) -> dt.datetime:
    if type(value) is not str or _UTC_TIMESTAMP.fullmatch(value) is None:
        raise PointInTimeDataError(f"{label} must use canonical UTC seconds")
    try:
        parsed = dt.datetime.fromisoformat(value)
    except ValueError as exc:
        raise PointInTimeDataError(f"{label} must use canonical UTC seconds") from exc
    if parsed.tzinfo != dt.UTC or parsed.isoformat(timespec="seconds") != value:
        raise PointInTimeDataError(f"{label} must use canonical UTC seconds")
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


def _json_path(value: object, *, label: str) -> tuple[str | int, ...]:
    if type(value) not in (list, tuple) or not value:
        raise PointInTimeDataError(f"{label} must be a nonempty exact JSON path")
    result: list[str | int] = []
    for component in value:
        if type(component) is str and component:
            result.append(component)
        elif type(component) is int and component >= 0:
            result.append(component)
        else:
            raise PointInTimeDataError(f"{label} contains an invalid component")
    return tuple(result)


def _select_json(payload: object, path: Sequence[str | int], *, label: str) -> object:
    selected = payload
    for component in path:
        if type(component) is str and isinstance(selected, Mapping):
            if component not in selected:
                raise PointInTimeDataError(f"{label} is absent from retained source bytes")
            selected = selected[component]
        elif type(component) is int and type(selected) is list:
            if component >= len(selected):
                raise PointInTimeDataError(f"{label} is absent from retained source bytes")
            selected = selected[component]
        else:
            raise PointInTimeDataError(f"{label} does not resolve in retained source bytes")
    return selected


def _strict_json(raw_bytes: bytes, *, label: str) -> object:
    def reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise PointInTimeDataError(f"{label} contains a duplicate JSON key")
            result[key] = value
        return result

    def reject_nonfinite(_value: str) -> object:
        raise PointInTimeDataError(f"{label} contains a nonfinite JSON number")

    try:
        return json.loads(
            raw_bytes,
            object_pairs_hook=reject_duplicate_keys,
            parse_float=Decimal,
            parse_constant=reject_nonfinite,
        )
    except PointInTimeDataError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PointInTimeDataError(f"{label} is not strict JSON") from exc


def _canonical_decimal(value: object, *, label: str, positive: bool) -> str:
    if type(value) not in (int, Decimal):
        raise PointInTimeDataError(f"{label} must be an exact JSON number")
    try:
        parsed = value if type(value) is Decimal else Decimal(value)
        sign, digits, exponent = parsed.as_tuple()
        adjusted = len(digits) + exponent - 1
    except (DecimalException, TypeError, ValueError, OverflowError) as exc:
        raise PointInTimeDataError(f"{label} is not a bounded decimal") from exc
    max_digits, max_exponent, max_chars = _DECIMAL_LIMITS
    if (
        not parsed.is_finite()
        or len(digits) > max_digits
        or abs(exponent) > max_exponent
        or abs(adjusted) > max_exponent
        or (positive and parsed <= 0)
        or (not positive and parsed < 0)
        or (sign and parsed == 0)
    ):
        raise PointInTimeDataError(f"{label} is outside the bounded decimal domain")
    text = format(parsed, "f")
    if len(text) > max_chars:
        raise PointInTimeDataError(f"{label} exceeds decimal output limits")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text == "-0" else text


def _verified_artifact(
    *,
    archive: RawPointInTimeArtifactArchive,
    raw_artifact_id: object,
    raw_artifact_sha256: object,
    cutoff: dt.datetime,
    label: str,
) -> RawPointInTimeArtifact:
    if type(raw_artifact_id) is not str or type(raw_artifact_sha256) is not str:
        raise PointInTimeDataError(f"{label} raw artifact reference is invalid")
    artifact = archive.read_artifact(raw_artifact_id)
    if artifact.raw_artifact_sha256 != raw_artifact_sha256:
        raise PointInTimeDataError(f"{label} raw artifact digest does not match archive")
    if (
        _timestamp(artifact.retrieved_at, label=f"{label} retrieved_at") > cutoff
        or _timestamp(
            artifact.archive_recorded_at,
            label=f"{label} archive_recorded_at",
        )
        > cutoff
    ):
        raise PointInTimeDataError(f"{label} was retained after the selection cutoff")
    return artifact


def _calendar_context(
    *,
    archive: RawPointInTimeArtifactArchive,
    market_calendar: MarketSessionCalendar,
    market_date: str,
    cutoff: dt.datetime,
) -> tuple[
    MarketSessionCalendar,
    RawPointInTimeArtifact,
    tuple[str, ...],
    dict[str, dt.datetime],
]:
    if type(market_calendar) is not MarketSessionCalendar:
        raise PointInTimeDataError("market_calendar must be an exact canonical receipt")
    calendar = validate_market_session_calendar(market_calendar.to_dict())
    artifact = _verified_artifact(
        archive=archive,
        raw_artifact_id=calendar.raw_artifact_id,
        raw_artifact_sha256=calendar.raw_artifact_sha256,
        cutoff=cutoff,
        label="market calendar",
    )
    rebuilt = build_market_session_calendar(archive=archive, raw_artifact=artifact)
    if rebuilt.canonical_json_bytes() != calendar.canonical_json_bytes():
        raise PointInTimeDataError("market calendar receipt does not match retained bytes")
    if market_date not in calendar.market_dates:
        raise PointInTimeDataError("market_date is not a registered calendar session")
    market_index = calendar.market_dates.index(market_date)
    session_dates = calendar.market_dates[max(0, market_index - 60) : market_index]
    if len(session_dates) != 60:
        raise PointInTimeDataError("calendar lacks 60 complete sessions before market_date")
    source = _strict_json(archive.read_bytes(artifact), label="market calendar source")
    if type(source) is not list:
        raise PointInTimeDataError("market calendar source must be a JSON list")
    close_times: dict[str, dt.datetime] = {}
    selected = set(session_dates)
    for index, row in enumerate(source):
        if not isinstance(row, Mapping):
            raise PointInTimeDataError(f"market calendar row {index} is invalid")
        date_value = row.get("date")
        if date_value not in selected:
            continue
        if date_value in close_times:
            raise PointInTimeDataError("market calendar contains a duplicate selected session")
        raw_open = row.get("open")
        raw_close = row.get("close")
        if (
            type(raw_open) is not str
            or _SESSION_TIME.fullmatch(raw_open) is None
            or type(raw_close) is not str
            or _SESSION_TIME.fullmatch(raw_close) is None
        ):
            raise PointInTimeDataError("market calendar selected session is incomplete")
        open_time = dt.time.fromisoformat(raw_open)
        close_time = dt.time.fromisoformat(raw_close)
        if open_time >= close_time:
            raise PointInTimeDataError("market calendar selected session hours are invalid")
        local_close = dt.datetime.combine(
            dt.date.fromisoformat(date_value),
            close_time,
            tzinfo=_MARKET_TZ,
        )
        close_times[date_value] = local_close.astimezone(dt.UTC)
    if tuple(date for date in session_dates if date in close_times) != session_dates:
        raise PointInTimeDataError("market calendar selected sessions are incomplete")
    if any(completion > cutoff for completion in close_times.values()):
        raise PointInTimeDataError("selected market session completes after cutoff")
    return calendar, artifact, session_dates, close_times


def _identity_type_reason(value: object) -> str | None:
    if value == "common_stock":
        return None
    if value == "etf":
        return "security_type_etf"
    if value == "etn":
        return "security_type_etn"
    if value in {"preferred", "preferred_stock"}:
        return "security_type_preferred"
    if value == "warrant":
        return "security_type_warrant"
    return "security_type_not_common_stock"


def _identity_sources(
    *,
    archive: RawPointInTimeArtifactArchive,
    security: SecurityIdentity,
    raw_sources: object,
    cutoff: dt.datetime,
    first_session: str,
    market_date: str,
) -> tuple[tuple[PointInTimeCohortIdentitySourceReference, ...], tuple[str, ...]]:
    if type(raw_sources) is not list or not raw_sources:
        raise PointInTimeDataError("candidate identity_sources must be a nonempty list")
    expected_fields = frozenset(
        {
            "source_hash_name",
            "raw_artifact_id",
            "raw_artifact_sha256",
            "qualification_field_selectors",
        }
    )
    parsed_sources: list[PointInTimeCohortIdentitySourceReference] = []
    selected_values: dict[str, object] = {}
    seen_hash_names: set[str] = set()
    for index, raw_source in enumerate(raw_sources):
        values = _exact(raw_source, expected_fields, label=f"identity source {index}")
        source_hash_name = values["source_hash_name"]
        if type(source_hash_name) is not str or source_hash_name in seen_hash_names:
            raise PointInTimeDataError("candidate identity source hash names are invalid")
        seen_hash_names.add(source_hash_name)
        if source_hash_name not in security.source_hashes:
            raise PointInTimeDataError("identity source hash name is absent from SecurityIdentity")
        artifact = _verified_artifact(
            archive=archive,
            raw_artifact_id=values["raw_artifact_id"],
            raw_artifact_sha256=values["raw_artifact_sha256"],
            cutoff=cutoff,
            label=f"identity source {index}",
        )
        if artifact.raw_artifact_sha256 != security.source_hashes[source_hash_name]:
            raise PointInTimeDataError(
                "SecurityIdentity source hash has no matching retained raw artifact"
            )
        parsed_uri = urlsplit(artifact.source_uri)
        if (
            parsed_uri.hostname not in _ALPACA_ASSET_HOSTS
            or not parsed_uri.path.startswith("/v2/assets/")
            or parsed_uri.query
            or artifact.content_type != "application/json"
        ):
            raise PointInTimeDataError(
                "identity qualification source must be retained Alpaca asset JSON"
            )
        selectors_raw = values["qualification_field_selectors"]
        if not isinstance(selectors_raw, Mapping) or not selectors_raw:
            raise PointInTimeDataError("qualification_field_selectors must be nonempty")
        selectors: dict[str, tuple[str | int, ...]] = {}
        source_payload = _strict_json(
            archive.read_bytes(artifact),
            label=f"identity source {index}",
        )
        if not isinstance(source_payload, Mapping):
            raise PointInTimeDataError("identity source JSON must be an object")
        for field_name, raw_path in selectors_raw.items():
            if field_name not in _QUALIFICATION_FIELDS or field_name in selected_values:
                raise PointInTimeDataError("qualification field binding is mixed or ambiguous")
            path = _json_path(raw_path, label=f"qualification selector {field_name}")
            selectors[field_name] = path
            selected_values[field_name] = _select_json(
                source_payload,
                path,
                label=f"qualification field {field_name}",
            )
        parsed_sources.append(
            PointInTimeCohortIdentitySourceReference(
                source_hash_name=source_hash_name,
                raw_artifact_id=artifact.raw_artifact_id,
                raw_artifact_sha256=artifact.raw_artifact_sha256,
                source_uri=artifact.source_uri,
                content_type=artifact.content_type,
                retrieved_at=artifact.retrieved_at,
                archive_recorded_at=artifact.archive_recorded_at,
                qualification_field_selectors=selectors,
            )
        )
    if seen_hash_names != set(security.source_hashes):
        raise PointInTimeDataError(
            "every SecurityIdentity source hash must name a retained raw artifact"
        )
    missing_fields = _QUALIFICATION_FIELDS - set(selected_values)
    if missing_fields:
        raise PointInTimeDataError(
            f"unbound qualification fields: {sorted(missing_fields)}"
        )

    reasons: list[str] = []
    if selected_values["security_id"] != security.security_id:
        reasons.append("security_identity_id_mismatch")
    if selected_values["symbol"] != security.symbol:
        reasons.append("security_identity_symbol_mismatch")
    exchange = selected_values["exchange"]
    if type(exchange) is not str:
        raise PointInTimeDataError("source-derived exchange must be a string")
    if exchange == "OTC":
        reasons.append("exchange_otc")
    elif exchange not in _US_LISTED_EXCHANGES:
        reasons.append("exchange_not_us_listed")
    elif exchange != security.exchange:
        reasons.append("security_identity_exchange_mismatch")
    type_reason = _identity_type_reason(selected_values["security_type"])
    if type_reason is not None:
        reasons.append(type_reason)
    source_status = selected_values["status"]
    if source_status != "active":
        reasons.append("asset_status_not_active")
    if selected_values["asset_class"] != "us_equity":
        reasons.append("asset_class_not_us_equity")
    tradable = selected_values["tradable"]
    if type(tradable) is not bool:
        raise PointInTimeDataError("source-derived tradable must be an exact boolean")
    if not tradable:
        reasons.append("asset_not_tradable")
    effective_from = _date(
        selected_values["effective_from"],
        label="source-derived effective_from",
    )
    raw_effective_to = selected_values["effective_to"]
    effective_to = (
        None
        if raw_effective_to is None
        else _date(raw_effective_to, label="source-derived effective_to")
    )
    if effective_from > first_session or (
        effective_to is not None and effective_to < market_date
    ):
        reasons.append("identity_not_effective_for_full_window")
    return tuple(parsed_sources), tuple(reasons)


def _market_source(
    *,
    archive: RawPointInTimeArtifactArchive,
    security: SecurityIdentity,
    raw_source: object,
    cutoff: dt.datetime,
    market_date: str,
    session_dates: tuple[str, ...],
    close_times: Mapping[str, dt.datetime],
) -> tuple[PointInTimeCohortMarketDataSourceReference, str, str]:
    values = _exact(
        raw_source,
        frozenset({"raw_artifact_id", "raw_artifact_sha256", "bar_selectors"}),
        label="candidate market_data_source",
    )
    artifact = _verified_artifact(
        archive=archive,
        raw_artifact_id=values["raw_artifact_id"],
        raw_artifact_sha256=values["raw_artifact_sha256"],
        cutoff=cutoff,
        label="candidate market-data source",
    )
    parsed_uri = urlsplit(artifact.source_uri)
    if (
        parsed_uri.hostname != "data.alpaca.markets"
        or parsed_uri.path != f"/v2/stocks/{security.symbol}/bars"
        or artifact.content_type != "application/json"
    ):
        raise PointInTimeDataError("market source is not the exact Alpaca stock-bars route")
    query_pairs = parse_qsl(parsed_uri.query, keep_blank_values=True)
    if len({key for key, _value in query_pairs}) != len(query_pairs):
        raise PointInTimeDataError("Alpaca bar route contains duplicate query selectors")
    query = dict(query_pairs)
    expected_start = f"{session_dates[0]}T00:00:00Z"
    expected_end = f"{market_date}T00:00:00Z"
    if set(query) != {"timeframe", "feed", "adjustment", "start", "end"}:
        raise PointInTimeDataError("Alpaca bar route selectors are mixed or ambiguous")
    if (
        query["timeframe"] != "1Day"
        or query["feed"] not in {"iex", "sip"}
        or query["adjustment"] != "raw"
        or query["start"] != expected_start
        or query["end"] != expected_end
    ):
        raise PointInTimeDataError(
            "Alpaca bars must pin the exact 60-session range, feed, and raw adjustment"
        )
    selector_values = _exact(
        values["bar_selectors"],
        frozenset({"rows_path", "timestamp_field", "close_field", "volume_field"}),
        label="candidate bar_selectors",
    )
    rows_path = _json_path(selector_values["rows_path"], label="bar rows_path")
    if rows_path != ("bars", security.symbol):
        raise PointInTimeDataError("bar rows_path must bind the exact security symbol")
    if (
        selector_values["timestamp_field"] != "t"
        or selector_values["close_field"] != "c"
        or selector_values["volume_field"] != "v"
    ):
        raise PointInTimeDataError("bar field selectors must bind Alpaca t/c/v")
    source_payload = _strict_json(
        archive.read_bytes(artifact),
        label="Alpaca bar source",
    )
    if not isinstance(source_payload, Mapping):
        raise PointInTimeDataError("Alpaca bar source must be a JSON object")
    if source_payload.get("next_page_token") is not None:
        raise PointInTimeDataError("Alpaca bar source is incomplete or paginated")
    raw_rows = _select_json(source_payload, rows_path, label="Alpaca bar rows")
    if type(raw_rows) is not list or len(raw_rows) != 60:
        raise PointInTimeDataError("Alpaca bar source must contain exactly 60 session rows")
    closes: list[Decimal] = []
    daily_dollar_volumes: list[Decimal] = []
    actual_dates: list[str] = []
    artifact_retrieved = _timestamp(artifact.retrieved_at, label="bars retrieved_at")
    for index, row in enumerate(raw_rows):
        if not isinstance(row, Mapping):
            raise PointInTimeDataError(f"Alpaca bar row {index} must be an object")
        raw_timestamp = row.get("t")
        if type(raw_timestamp) is not str:
            raise PointInTimeDataError(f"Alpaca bar row {index} has no timestamp")
        normalized = raw_timestamp.removesuffix("Z") + (
            "+00:00" if raw_timestamp.endswith("Z") else ""
        )
        try:
            bar_time = dt.datetime.fromisoformat(normalized)
        except ValueError as exc:
            raise PointInTimeDataError(f"Alpaca bar row {index} timestamp is invalid") from exc
        local_time = bar_time.astimezone(_MARKET_TZ) if bar_time.tzinfo is not None else None
        if (
            bar_time.tzinfo != dt.UTC
            or bar_time.microsecond
            or local_time is None
            or local_time.timetz().replace(tzinfo=None) != dt.time(0, 0)
        ):
            raise PointInTimeDataError(f"Alpaca bar row {index} is not a daily session bar")
        session_date = local_time.date().isoformat()
        actual_dates.append(session_date)
        close_text = _canonical_decimal(
            row.get("c"),
            label=f"Alpaca bar row {index} close",
            positive=True,
        )
        raw_volume = row.get("v")
        if type(raw_volume) is not int or raw_volume < 0:
            raise PointInTimeDataError(
                f"Alpaca bar row {index} volume must be a nonnegative exact integer"
            )
        close = Decimal(close_text)
        closes.append(close)
        daily_dollar_volumes.append(close * Decimal(raw_volume))
        completion = close_times.get(session_date)
        if completion is None:
            raise PointInTimeDataError("Alpaca bar row is not a registered calendar session")
        if completion > cutoff or artifact_retrieved < completion:
            raise PointInTimeDataError("Alpaca bar row is incomplete or after cutoff")
    if tuple(actual_dates) != session_dates:
        raise PointInTimeDataError(
            "Alpaca bars must be unique, chronological, and exactly match 60 sessions"
        )
    ordered_volumes = sorted(daily_dollar_volumes)
    median = (ordered_volumes[29] + ordered_volumes[30]) / Decimal("2")
    reference = PointInTimeCohortMarketDataSourceReference(
        raw_artifact_id=artifact.raw_artifact_id,
        raw_artifact_sha256=artifact.raw_artifact_sha256,
        source_uri=artifact.source_uri,
        content_type=artifact.content_type,
        retrieved_at=artifact.retrieved_at,
        archive_recorded_at=artifact.archive_recorded_at,
        feed=query["feed"],
        adjustment=query["adjustment"],
        timeframe=query["timeframe"],
        rows_path=rows_path,
        timestamp_field="t",
        close_field="c",
        volume_field="v",
    )
    return (
        reference,
        _canonical_decimal(closes[-1], label="prior complete close", positive=True),
        _canonical_decimal(median, label="median daily dollar volume", positive=False),
    )


def build_source_verifiable_point_in_time_cohort(
    *,
    archive: RawPointInTimeArtifactArchive,
    market_calendar: MarketSessionCalendar,
    market_date: str,
    as_of_cutoff: str,
    selection_time: str,
    candidates: tuple[Mapping[str, object], ...],
) -> PointInTimeCohort:
    """Strictly reopen every named source and derive all qualification facts."""

    if type(archive) is not RawPointInTimeArtifactArchive:
        raise PointInTimeDataError("archive must be an exact raw PIT artifact archive")
    normalized_market_date = _date(market_date, label="market_date")
    cutoff = _timestamp(as_of_cutoff, label="as_of_cutoff")
    _timestamp(selection_time, label="selection_time")
    calendar, calendar_artifact, session_dates, close_times = _calendar_context(
        archive=archive,
        market_calendar=market_calendar,
        market_date=normalized_market_date,
        cutoff=cutoff,
    )
    if type(candidates) is not tuple or not candidates:
        raise PointInTimeDataError("candidate input must be a nonempty exact tuple")
    derived: list[PointInTimeCohortCandidate] = []
    for index, raw_candidate in enumerate(candidates):
        values = _exact(
            raw_candidate,
            frozenset({"security", "identity_sources", "market_data_source"}),
            label=f"candidate input fields at index {index}",
        )
        security = validate_security_identity(values["security"])
        identity_sources, reasons = _identity_sources(
            archive=archive,
            security=security,
            raw_sources=values["identity_sources"],
            cutoff=cutoff,
            first_session=session_dates[0],
            market_date=normalized_market_date,
        )
        market_source, prior_close, median = _market_source(
            archive=archive,
            security=security,
            raw_source=values["market_data_source"],
            cutoff=cutoff,
            market_date=normalized_market_date,
            session_dates=session_dates,
            close_times=close_times,
        )
        derived.append(
            PointInTimeCohortCandidate(
                security=security,
                prior_complete_close=prior_close,
                median_daily_dollar_volume=median,
                identity_sources=identity_sources,
                market_data_source=market_source,
                rejection_reasons=reasons,
            )
        )
    return build_point_in_time_cohort(
        market_date=normalized_market_date,
        as_of_cutoff=as_of_cutoff,
        selection_time=selection_time,
        market_calendar=calendar,
        calendar_retrieved_at=calendar_artifact.retrieved_at,
        calendar_archive_recorded_at=calendar_artifact.archive_recorded_at,
        session_dates=session_dates,
        candidates=tuple(derived),
    )


def verify_source_verifiable_point_in_time_cohort(
    *,
    archive: RawPointInTimeArtifactArchive,
    value: object,
) -> PointInTimeCohort:
    """Reopen every source named by a serialized cohort and rederive its bytes."""

    cohort = validate_point_in_time_cohort(value)
    candidate_inputs = tuple(
        {
            "security": candidate.security.to_dict(),
            "identity_sources": [
                {
                    "source_hash_name": source.source_hash_name,
                    "raw_artifact_id": source.raw_artifact_id,
                    "raw_artifact_sha256": source.raw_artifact_sha256,
                    "qualification_field_selectors": {
                        name: list(path)
                        for name, path in source.qualification_field_selectors.items()
                    },
                }
                for source in candidate.identity_sources
            ],
            "market_data_source": {
                "raw_artifact_id": candidate.market_data_source.raw_artifact_id,
                "raw_artifact_sha256": (
                    candidate.market_data_source.raw_artifact_sha256
                ),
                "bar_selectors": {
                    "rows_path": list(candidate.market_data_source.rows_path),
                    "timestamp_field": candidate.market_data_source.timestamp_field,
                    "close_field": candidate.market_data_source.close_field,
                    "volume_field": candidate.market_data_source.volume_field,
                },
            },
        }
        for candidate in cohort.candidates
    )
    rebuilt = build_source_verifiable_point_in_time_cohort(
        archive=archive,
        market_calendar=cohort.market_calendar,
        market_date=cohort.market_date,
        as_of_cutoff=cohort.as_of_cutoff,
        selection_time=cohort.selection_time,
        candidates=candidate_inputs,
    )
    if rebuilt.canonical_json_bytes() != cohort.canonical_json_bytes():
        raise PointInTimeDataError("cohort does not match its retained source bytes")
    return rebuilt
