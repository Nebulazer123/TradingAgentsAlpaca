"""Archive-backed qualification for source-verifiable economic cohorts."""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import stat
from collections.abc import Mapping, Sequence
from decimal import Decimal, DecimalException
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from tradingagents.dataflows.pit.cohort import (
    PointInTimeCohort,
    PointInTimeCohortCandidate,
    PointInTimeCohortIdentitySourceReference,
    PointInTimeCohortMarketDataSourceReference,
    build_point_in_time_cohort,
    validate_nonqualifying_point_in_time_cohort_record,
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
_US_LISTED_EXCHANGES = frozenset(
    {"AMEX", "ARCA", "BATS", "NASDAQ", "NYSE", "NYSEARCA"}
)
_ALPACA_ASSET_HOSTS = frozenset(
    {"api.alpaca.markets", "paper-api.alpaca.markets"}
)
_SECURITY_MASTER_HOST = "security-master.tradingagents.local"
_MARKET_TZ = ZoneInfo("America/New_York")
_SOURCE_DECIMAL_LIMITS = (128, 128, 256)
_DERIVED_DECIMAL_LIMITS = (513, 640, 768)
_MAX_CANDIDATES = 512
_MAX_CALENDAR_ARTIFACT_BYTES = 2_000_000
_MAX_IDENTITY_ARTIFACT_BYTES = 64_000
_MAX_BAR_ARTIFACT_BYTES = 1_000_000
_MAX_JSON_DEPTH = 12
_MAX_JSON_OBJECTS = 512
_MAX_JSON_LISTS = 64
_MAX_JSON_STRINGS = 4_096
_MAX_JSON_NODES = 8_192
_MAX_CONTAINER_ITEMS = 1_024
_MAX_STRING_CHARS = 512
_MAX_NUMERIC_DIGITS = 128
_MAX_ARTIFACT_RECEIPT_BYTES = 16_384
_RAW_ARTIFACT_ID = re.compile(r"pit-raw-artifact-[0-9a-f]{64}")
_IDENTITY_PROFILE_ORDER = ("alpaca_asset/v1", "security_master/v1")
_IDENTITY_PROFILES: dict[str, dict[str, object]] = {
    "alpaca_asset/v1": {
        "source_hash_name": "alpaca_asset",
        "selectors": {
            "security_id": ("id",),
            "symbol": ("symbol",),
            "exchange": ("exchange",),
            "asset_class": ("class",),
            "status": ("status",),
            "tradable": ("tradable",),
        },
    },
    "security_master/v1": {
        "source_hash_name": "security_master",
        "selectors": {
            "security_id": ("security_id",),
            "symbol": ("symbol",),
            "security_type": ("security_type",),
            "effective_from": ("effective_from",),
            "effective_to": ("effective_to",),
        },
    },
}
_MARKET_SOURCE_PROFILE = "alpaca_stock_daily_bars/v1"
_MARKET_SELECTORS = {
    "rows_path": ("bars",),
    "timestamp_field": "t",
    "close_field": "c",
    "volume_field": "v",
}
_CANDIDATE_FIELDS = frozenset(
    {"security", "identity_sources", "market_data_source"}
)
_IDENTITY_INPUT_FIELDS = frozenset(
    {"source_profile", "record_identity", "raw_artifact_id", "raw_artifact_sha256"}
)
_MARKET_INPUT_FIELDS = frozenset(
    {"source_profile", "record_identity", "raw_artifact_id", "raw_artifact_sha256"}
)


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
    if parsed.tzinfo != dt.timezone.utc or parsed.isoformat(timespec="seconds") != value:
        raise PointInTimeDataError(f"{label} must use canonical UTC seconds")
    return parsed


def _timestamp_text(value: dt.datetime) -> str:
    return value.astimezone(dt.timezone.utc).isoformat(timespec="seconds")


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


def _bounded_json_shape(payload: object, *, label: str) -> None:
    objects = 0
    lists = 0
    strings = 0
    nodes = 0
    stack: list[tuple[object, int]] = [(payload, 0)]
    while stack:
        value, depth = stack.pop()
        nodes += 1
        if nodes > _MAX_JSON_NODES or depth > _MAX_JSON_DEPTH:
            raise PointInTimeDataError(f"{label} exceeds JSON depth/node limits")
        if isinstance(value, Mapping):
            objects += 1
            if objects > _MAX_JSON_OBJECTS or len(value) > _MAX_CONTAINER_ITEMS:
                raise PointInTimeDataError(f"{label} exceeds JSON object limits")
            for key, item in value.items():
                strings += 1
                if (
                    strings > _MAX_JSON_STRINGS
                    or type(key) is not str
                    or len(key) > _MAX_STRING_CHARS
                ):
                    raise PointInTimeDataError(f"{label} exceeds JSON string limits")
                stack.append((item, depth + 1))
        elif type(value) is list:
            lists += 1
            if lists > _MAX_JSON_LISTS or len(value) > _MAX_CONTAINER_ITEMS:
                raise PointInTimeDataError(f"{label} exceeds JSON list limits")
            stack.extend((item, depth + 1) for item in value)
        elif type(value) is str:
            strings += 1
            if strings > _MAX_JSON_STRINGS or len(value) > _MAX_STRING_CHARS:
                raise PointInTimeDataError(f"{label} exceeds JSON string limits")


def _strict_json(raw_bytes: bytes, *, label: str) -> object:
    def reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise PointInTimeDataError(f"{label} contains a duplicate JSON key")
            result[key] = value
        return result

    def bounded_integer(text: str) -> int:
        digits = text.removeprefix("-")
        if len(digits) > _MAX_NUMERIC_DIGITS:
            raise PointInTimeDataError(f"{label} numeric coefficient is too large")
        return int(text)

    def bounded_decimal(text: str) -> Decimal:
        coefficient = text.lower().split("e", 1)[0].replace("-", "").replace(".", "")
        exponent = text.lower().split("e", 1)[1] if "e" in text.lower() else "0"
        exponent_digits = exponent.removeprefix("-").removeprefix("+")
        if (
            len(coefficient.lstrip("0") or "0") > _MAX_NUMERIC_DIGITS
            or len(exponent_digits) > 4
            or abs(int(exponent)) > _MAX_NUMERIC_DIGITS
        ):
            raise PointInTimeDataError(f"{label} numeric coefficient is too large")
        return Decimal(text)

    def reject_nonfinite(_value: str) -> object:
        raise PointInTimeDataError(f"{label} contains a nonfinite JSON number")

    try:
        payload = json.loads(
            raw_bytes,
            object_pairs_hook=reject_duplicate_keys,
            parse_int=bounded_integer,
            parse_float=bounded_decimal,
            parse_constant=reject_nonfinite,
        )
    except PointInTimeDataError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, DecimalException, RecursionError) as exc:
        raise PointInTimeDataError(f"{label} is not bounded strict JSON") from exc
    _bounded_json_shape(payload, label=label)
    return payload


def _canonical_decimal(
    value: object,
    *,
    label: str,
    positive: bool,
    limits: tuple[int, int, int],
) -> str:
    if type(value) not in (int, Decimal):
        raise PointInTimeDataError(f"{label} must be an exact JSON number")
    try:
        parsed = value if type(value) is Decimal else Decimal(value)
        sign, digits, exponent = parsed.as_tuple()
        adjusted = len(digits) + exponent - 1
    except (DecimalException, TypeError, ValueError, OverflowError) as exc:
        raise PointInTimeDataError(f"{label} is not a bounded decimal") from exc
    max_digits, max_exponent, max_chars = limits
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


def _coefficient(value: Decimal) -> tuple[int, int]:
    sign, digits, exponent = value.as_tuple()
    coefficient = int("".join(str(digit) for digit in digits))
    return (-coefficient if sign else coefficient), exponent


def _decimal_from_coefficient(coefficient: int, exponent: int) -> Decimal:
    sign = 1 if coefficient < 0 else 0
    digits = tuple(int(char) for char in str(abs(coefficient))) if coefficient else (0,)
    return Decimal((sign, digits, exponent))


def _exact_product(close: Decimal, volume: int) -> Decimal:
    coefficient, exponent = _coefficient(close)
    return _decimal_from_coefficient(coefficient * volume, exponent)


def _exact_even_median(lower: Decimal, upper: Decimal) -> Decimal:
    lower_coefficient, lower_exponent = _coefficient(lower)
    upper_coefficient, upper_exponent = _coefficient(upper)
    common_exponent = min(lower_exponent, upper_exponent)
    numerator = (
        lower_coefficient * (10 ** (lower_exponent - common_exponent))
        + upper_coefficient * (10 ** (upper_exponent - common_exponent))
    )
    if numerator % 2 == 0:
        return _decimal_from_coefficient(numerator // 2, common_exponent)
    return _decimal_from_coefficient(numerator * 5, common_exponent - 1)


def _exact_https_uri(value: str, *, host: str, path: str, query: str = "") -> bool:
    expected = f"https://{host}{path}" + (f"?{query}" if query else "")
    if value != expected:
        return False
    parsed = urlsplit(value)
    return (
        parsed.scheme == "https"
        and parsed.netloc == host
        and parsed.hostname == host
        and parsed.port is None
        and parsed.username is None
        and parsed.password is None
        and parsed.path == path
        and parsed.query == query
        and not parsed.fragment
    )


def _verified_artifact(
    *,
    archive: RawPointInTimeArtifactArchive,
    raw_artifact_id: object,
    raw_artifact_sha256: object,
    as_of_cutoff: dt.datetime,
    max_byte_count: int,
    label: str,
) -> RawPointInTimeArtifact:
    if type(raw_artifact_id) is not str or type(raw_artifact_sha256) is not str:
        raise PointInTimeDataError(f"{label} raw artifact reference is invalid")
    if _RAW_ARTIFACT_ID.fullmatch(raw_artifact_id) is None:
        raise PointInTimeDataError(f"{label} raw artifact identity is invalid")
    object_root = archive.root / "objects"
    for path, byte_limit in (
        (object_root / f"{raw_artifact_id}.json", _MAX_ARTIFACT_RECEIPT_BYTES),
        (object_root / f"{raw_artifact_id}.raw", max_byte_count),
    ):
        try:
            metadata = os.lstat(path)
        except OSError as exc:
            raise PointInTimeDataError(f"{label} raw artifact path is unavailable") from exc
        if (
            not stat.S_ISREG(metadata.st_mode)
            or stat.S_ISLNK(metadata.st_mode)
            or metadata.st_size > byte_limit
        ):
            raise PointInTimeDataError(f"{label} raw artifact exceeds safe path/byte limits")
    artifact = archive.read_artifact(raw_artifact_id)
    if artifact.raw_artifact_sha256 != raw_artifact_sha256:
        raise PointInTimeDataError(f"{label} raw artifact digest does not match archive")
    if artifact.byte_count > max_byte_count:
        raise PointInTimeDataError(f"{label} raw artifact exceeds byte limit")
    if _timestamp(
        artifact.archive_recorded_at,
        label=f"{label} archive_recorded_at",
    ) > as_of_cutoff:
        raise PointInTimeDataError(f"{label} was archived after as_of_cutoff")
    if _timestamp(artifact.retrieved_at, label=f"{label} retrieved_at") > as_of_cutoff:
        raise PointInTimeDataError(f"{label} was retrieved after as_of_cutoff")
    return artifact


def _preflight_candidates(
    candidates: object,
) -> tuple[dict[str, object], ...]:
    if (
        type(candidates) is not tuple
        or not candidates
        or len(candidates) > _MAX_CANDIDATES
    ):
        raise PointInTimeDataError("candidate input exceeds the bounded candidate count")
    preflight: list[dict[str, object]] = []
    for index, candidate in enumerate(candidates):
        values = _exact(candidate, _CANDIDATE_FIELDS, label=f"candidate input {index}")
        sources = values["identity_sources"]
        if type(sources) is not list or len(sources) != len(_IDENTITY_PROFILE_ORDER):
            raise PointInTimeDataError(
                "candidate identity_sources must contain exactly two registered profiles"
            )
        for source_index, source in enumerate(sources):
            _exact(
                source,
                _IDENTITY_INPUT_FIELDS,
                label=f"candidate identity source {index}:{source_index}",
            )
        _exact(
            values["market_data_source"],
            _MARKET_INPUT_FIELDS,
            label=f"candidate market source {index}",
        )
        preflight.append(values)
    return tuple(preflight)


def _calendar_context(
    *,
    archive: RawPointInTimeArtifactArchive,
    market_calendar: MarketSessionCalendar,
    market_date: str,
    selection_time: dt.datetime,
    as_of_cutoff: dt.datetime,
) -> tuple[
    MarketSessionCalendar,
    RawPointInTimeArtifact,
    tuple[str, ...],
    dict[str, dt.datetime],
    dt.datetime,
    dt.datetime,
    dt.datetime,
]:
    if type(market_calendar) is not MarketSessionCalendar:
        raise PointInTimeDataError("market_calendar must be an exact canonical receipt")
    calendar = validate_market_session_calendar(market_calendar.to_dict())
    artifact = _verified_artifact(
        archive=archive,
        raw_artifact_id=calendar.raw_artifact_id,
        raw_artifact_sha256=calendar.raw_artifact_sha256,
        as_of_cutoff=as_of_cutoff,
        max_byte_count=_MAX_CALENDAR_ARTIFACT_BYTES,
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
    calendar_query = f"start={session_dates[0]}&end={market_date}"
    if not any(
        _exact_https_uri(
            artifact.source_uri,
            host=host,
            path="/v2/calendar",
            query=calendar_query,
        )
        for host in _ALPACA_ASSET_HOSTS
    ):
        raise PointInTimeDataError("market calendar URI is not canonical Alpaca provenance")
    source = _strict_json(archive.read_bytes(artifact), label="market calendar source")
    if type(source) is not list:
        raise PointInTimeDataError("market calendar source must be a JSON list")
    expected_dates = (*session_dates, market_date)
    if len(source) != len(expected_dates):
        raise PointInTimeDataError(
            "market calendar source must contain exactly the requested 61 sessions"
        )
    hours: dict[str, tuple[dt.datetime, dt.datetime]] = {}
    for index, (row, expected_date) in enumerate(zip(source, expected_dates, strict=True)):
        if not isinstance(row, Mapping):
            raise PointInTimeDataError(f"market calendar row {index} is invalid")
        date_value = row.get("date")
        if date_value != expected_date:
            raise PointInTimeDataError(
                "market calendar source rows must exactly match the requested sessions"
            )
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
        session_date = dt.date.fromisoformat(date_value)
        local_open = dt.datetime.combine(session_date, open_time, tzinfo=_MARKET_TZ)
        local_close = dt.datetime.combine(session_date, close_time, tzinfo=_MARKET_TZ)
        hours[date_value] = (local_open.astimezone(dt.timezone.utc), local_close.astimezone(dt.timezone.utc))
    if tuple(hours) != expected_dates:
        raise PointInTimeDataError("market calendar requested sessions are incomplete")
    close_times = {date: hours[date][1] for date in session_dates}
    if any(completion > as_of_cutoff for completion in close_times.values()):
        raise PointInTimeDataError("preceding session completes after as_of_cutoff")
    market_open, market_close = hours[market_date]
    selection_window_open = dt.datetime.combine(
        dt.date.fromisoformat(market_date),
        dt.time(0, 0),
        tzinfo=_MARKET_TZ,
    ).astimezone(dt.timezone.utc)
    if not selection_window_open <= as_of_cutoff <= selection_time <= market_open:
        raise PointInTimeDataError(
            "as_of_cutoff and selection_time must be ordered within the pre-open window"
        )
    return (
        calendar,
        artifact,
        session_dates,
        close_times,
        selection_window_open,
        market_open,
        market_close,
    )


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


def _identity_profile_uri(
    *,
    profile: str,
    record_identity: str,
    security: SecurityIdentity,
    source_uri: str,
) -> bool:
    if profile == "alpaca_asset/v1":
        if record_identity not in {security.symbol, security.security_id}:
            return False
        return any(
            _exact_https_uri(
                source_uri,
                host=host,
                path=f"/v2/assets/{record_identity}",
            )
            for host in _ALPACA_ASSET_HOSTS
        )
    return (
        record_identity == security.security_id
        and _exact_https_uri(
            source_uri,
            host=_SECURITY_MASTER_HOST,
            path=f"/v1/securities/{security.security_id}",
        )
    )


def _identity_sources(
    *,
    archive: RawPointInTimeArtifactArchive,
    security: SecurityIdentity,
    raw_sources: object,
    as_of_cutoff: dt.datetime,
    first_session: str,
    market_date: str,
) -> tuple[tuple[PointInTimeCohortIdentitySourceReference, ...], tuple[str, ...]]:
    if set(security.source_hashes) != {"alpaca_asset", "security_master"}:
        raise PointInTimeDataError(
            "SecurityIdentity must bind exact alpaca_asset and security_master hashes"
        )
    if type(raw_sources) is not list or len(raw_sources) != 2:
        raise PointInTimeDataError("candidate identity_sources must contain two profiles")
    by_profile: dict[str, dict[str, object]] = {}
    for index, raw_source in enumerate(raw_sources):
        values = _exact(raw_source, _IDENTITY_INPUT_FIELDS, label=f"identity source {index}")
        profile = values["source_profile"]
        if type(profile) is not str or profile not in _IDENTITY_PROFILES or profile in by_profile:
            raise PointInTimeDataError("candidate identity source profiles are invalid")
        by_profile[profile] = values
    if set(by_profile) != set(_IDENTITY_PROFILE_ORDER):
        raise PointInTimeDataError("candidate identity source profiles are incomplete")
    selected_by_profile: dict[str, dict[str, object]] = {}
    references: list[PointInTimeCohortIdentitySourceReference] = []
    artifact_ids: set[str] = set()
    for profile in _IDENTITY_PROFILE_ORDER:
        values = by_profile[profile]
        specification = _IDENTITY_PROFILES[profile]
        source_hash_name = specification["source_hash_name"]
        selectors = specification["selectors"]
        if type(source_hash_name) is not str or not isinstance(selectors, Mapping):
            raise AssertionError("registered identity profile is malformed")
        record_identity = values["record_identity"]
        if type(record_identity) is not str:
            raise PointInTimeDataError("identity source record_identity is invalid")
        artifact = _verified_artifact(
            archive=archive,
            raw_artifact_id=values["raw_artifact_id"],
            raw_artifact_sha256=values["raw_artifact_sha256"],
            as_of_cutoff=as_of_cutoff,
            max_byte_count=_MAX_IDENTITY_ARTIFACT_BYTES,
            label=f"identity source {profile}",
        )
        if artifact.raw_artifact_id in artifact_ids:
            raise PointInTimeDataError("identity source artifacts must be unique")
        artifact_ids.add(artifact.raw_artifact_id)
        if artifact.raw_artifact_sha256 != security.source_hashes[source_hash_name]:
            raise PointInTimeDataError(
                "SecurityIdentity source hash has no matching retained raw artifact"
            )
        if (
            artifact.content_type != "application/json"
            or not _identity_profile_uri(
                profile=profile,
                record_identity=record_identity,
                security=security,
                source_uri=artifact.source_uri,
            )
        ):
            raise PointInTimeDataError(
                f"identity source {profile} URI/content profile is invalid"
            )
        source_payload = _strict_json(
            archive.read_bytes(artifact),
            label=f"identity source {profile}",
        )
        if not isinstance(source_payload, Mapping):
            raise PointInTimeDataError("identity source JSON must be an object")
        selected_values: dict[str, object] = {}
        for role, path in selectors.items():
            selected_values[role] = _select_json(
                source_payload,
                path,
                label=f"qualification field {role}",
            )
        selected_by_profile[profile] = selected_values
        references.append(
            PointInTimeCohortIdentitySourceReference(
                source_profile=profile,
                source_hash_name=source_hash_name,
                record_identity=record_identity,
                raw_artifact_id=artifact.raw_artifact_id,
                raw_artifact_sha256=artifact.raw_artifact_sha256,
                source_uri=artifact.source_uri,
                content_type=artifact.content_type,
                retrieved_at=artifact.retrieved_at,
                archive_recorded_at=artifact.archive_recorded_at,
                qualification_field_selectors=selectors,
            )
        )
    asset_values = selected_by_profile["alpaca_asset/v1"]
    master_values = selected_by_profile["security_master/v1"]
    reasons: list[str] = []
    if (
        asset_values["security_id"] != security.security_id
        or master_values["security_id"] != security.security_id
    ):
        reasons.append("security_identity_id_mismatch")
    if (
        asset_values["symbol"] != security.symbol
        or master_values["symbol"] != security.symbol
    ):
        reasons.append("security_identity_symbol_mismatch")
    exchange = asset_values["exchange"]
    if type(exchange) is not str:
        raise PointInTimeDataError("source-derived exchange must be a string")
    if exchange == "OTC":
        reasons.append("exchange_otc")
    elif exchange not in _US_LISTED_EXCHANGES:
        reasons.append("exchange_not_us_listed")
    elif exchange != security.exchange:
        reasons.append("security_identity_exchange_mismatch")
    type_reason = _identity_type_reason(master_values["security_type"])
    if type_reason is not None:
        reasons.append(type_reason)
    if master_values["security_type"] != security.security_type:
        reasons.append("security_identity_type_mismatch")
    source_status = asset_values["status"]
    if source_status != "active":
        reasons.append("asset_status_not_active")
    if source_status != security.status:
        reasons.append("security_identity_status_mismatch")
    if asset_values["asset_class"] != "us_equity":
        reasons.append("asset_class_not_us_equity")
    tradable = asset_values["tradable"]
    if type(tradable) is not bool:
        raise PointInTimeDataError("source-derived tradable must be an exact boolean")
    if not tradable:
        reasons.append("asset_not_tradable")
    effective_from = _date(
        master_values["effective_from"],
        label="source-derived effective_from",
    )
    raw_effective_to = master_values["effective_to"]
    effective_to = (
        None
        if raw_effective_to is None
        else _date(raw_effective_to, label="source-derived effective_to")
    )
    if effective_from != security.effective_from:
        reasons.append("security_identity_effective_from_mismatch")
    if effective_to != security.effective_to:
        reasons.append("security_identity_effective_to_mismatch")
    if effective_from > first_session or (
        effective_to is not None and effective_to < market_date
    ):
        reasons.append("identity_not_effective_for_full_window")
    return tuple(references), tuple(dict.fromkeys(reasons))


def _market_source(
    *,
    archive: RawPointInTimeArtifactArchive,
    security: SecurityIdentity,
    raw_source: object,
    as_of_cutoff: dt.datetime,
    market_date: str,
    session_dates: tuple[str, ...],
    close_times: Mapping[str, dt.datetime],
) -> tuple[PointInTimeCohortMarketDataSourceReference, str, str]:
    values = _exact(raw_source, _MARKET_INPUT_FIELDS, label="candidate market_data_source")
    if values["source_profile"] != _MARKET_SOURCE_PROFILE:
        raise PointInTimeDataError("market source profile is not registered")
    if values["record_identity"] != security.symbol:
        raise PointInTimeDataError("market source record_identity must be the exact symbol")
    artifact = _verified_artifact(
        archive=archive,
        raw_artifact_id=values["raw_artifact_id"],
        raw_artifact_sha256=values["raw_artifact_sha256"],
        as_of_cutoff=as_of_cutoff,
        max_byte_count=_MAX_BAR_ARTIFACT_BYTES,
        label="candidate market-data source",
    )
    expected_start = f"{session_dates[0]}T00:00:00Z"
    expected_end = f"{market_date}T00:00:00Z"
    matched_feed: str | None = None
    for feed in ("iex", "sip"):
        query = (
            f"timeframe=1Day&feed={feed}&adjustment=raw"
            f"&start={expected_start}&end={expected_end}"
        )
        if _exact_https_uri(
            artifact.source_uri,
            host="data.alpaca.markets",
            path=f"/v2/stocks/{security.symbol}/bars",
            query=query,
        ):
            matched_feed = feed
            break
    if artifact.content_type != "application/json" or matched_feed is None:
        raise PointInTimeDataError(
            "market source URI must be the exact canonical Alpaca daily-bars route"
        )
    source_payload = _strict_json(
        archive.read_bytes(artifact),
        label="Alpaca bar source",
    )
    if not isinstance(source_payload, Mapping) or set(source_payload) != {
        "bars",
        "symbol",
        "next_page_token",
    }:
        raise PointInTimeDataError("Alpaca bar source response fields are invalid")
    if source_payload["symbol"] != security.symbol:
        raise PointInTimeDataError("Alpaca bar source symbol is invalid")
    if source_payload["next_page_token"] is not None:
        raise PointInTimeDataError("Alpaca bar source is incomplete or paginated")
    raw_rows = source_payload["bars"]
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
        if type(raw_timestamp) is not str or not raw_timestamp.endswith("Z"):
            raise PointInTimeDataError(f"Alpaca bar row {index} has no canonical timestamp")
        try:
            bar_time = dt.datetime.fromisoformat(raw_timestamp[:-1] + "+00:00")
        except ValueError as exc:
            raise PointInTimeDataError(f"Alpaca bar row {index} timestamp is invalid") from exc
        local_time = bar_time.astimezone(_MARKET_TZ)
        if (
            bar_time.tzinfo != dt.timezone.utc
            or bar_time.microsecond
            or local_time.timetz().replace(tzinfo=None) != dt.time(0, 0)
        ):
            raise PointInTimeDataError(f"Alpaca bar row {index} is not a daily session bar")
        session_date = local_time.date().isoformat()
        actual_dates.append(session_date)
        close_text = _canonical_decimal(
            row.get("c"),
            label=f"Alpaca bar row {index} close",
            positive=True,
            limits=_SOURCE_DECIMAL_LIMITS,
        )
        raw_volume = row.get("v")
        if (
            type(raw_volume) is not int
            or raw_volume < 0
            or len(str(raw_volume)) > _MAX_NUMERIC_DIGITS
        ):
            raise PointInTimeDataError(
                f"Alpaca bar row {index} volume must be a bounded nonnegative integer"
            )
        close = Decimal(close_text)
        closes.append(close)
        product = _exact_product(close, raw_volume)
        _canonical_decimal(
            product,
            label=f"Alpaca bar row {index} daily dollar volume",
            positive=False,
            limits=_DERIVED_DECIMAL_LIMITS,
        )
        daily_dollar_volumes.append(product)
        completion = close_times.get(session_date)
        if completion is None:
            raise PointInTimeDataError("Alpaca bar row is not a registered calendar session")
        if completion > as_of_cutoff or artifact_retrieved < completion:
            raise PointInTimeDataError("Alpaca bar row is incomplete or after cutoff")
    if tuple(actual_dates) != session_dates:
        raise PointInTimeDataError(
            "Alpaca bars must be unique, chronological, and exactly match 60 sessions"
        )
    ordered_volumes = sorted(daily_dollar_volumes)
    median = _exact_even_median(ordered_volumes[29], ordered_volumes[30])
    prior_close = _canonical_decimal(
        closes[-1],
        label="prior complete close",
        positive=True,
        limits=_SOURCE_DECIMAL_LIMITS,
    )
    median_text = _canonical_decimal(
        median,
        label="median daily dollar volume",
        positive=False,
        limits=_DERIVED_DECIMAL_LIMITS,
    )
    reference = PointInTimeCohortMarketDataSourceReference(
        source_profile=_MARKET_SOURCE_PROFILE,
        record_identity=security.symbol,
        raw_artifact_id=artifact.raw_artifact_id,
        raw_artifact_sha256=artifact.raw_artifact_sha256,
        source_uri=artifact.source_uri,
        content_type=artifact.content_type,
        retrieved_at=artifact.retrieved_at,
        archive_recorded_at=artifact.archive_recorded_at,
        feed=matched_feed,
        adjustment="raw",
        timeframe="1Day",
        rows_path=_MARKET_SELECTORS["rows_path"],
        timestamp_field="t",
        close_field="c",
        volume_field="v",
    )
    return reference, prior_close, median_text


def build_source_verifiable_point_in_time_cohort(
    *,
    archive: RawPointInTimeArtifactArchive,
    market_calendar: MarketSessionCalendar,
    market_date: str,
    as_of_cutoff: str,
    selection_time: str,
    candidates: tuple[Mapping[str, object], ...],
) -> PointInTimeCohort:
    """Reopen every registered source and derive all qualification facts."""

    if type(archive) is not RawPointInTimeArtifactArchive:
        raise PointInTimeDataError("archive must be an exact raw PIT artifact archive")
    preflight = _preflight_candidates(candidates)
    normalized_market_date = _date(market_date, label="market_date")
    selected_at = _timestamp(selection_time, label="selection_time")
    cutoff = _timestamp(as_of_cutoff, label="as_of_cutoff")
    (
        calendar,
        calendar_artifact,
        session_dates,
        close_times,
        selection_window_open,
        market_open,
        market_close,
    ) = _calendar_context(
        archive=archive,
        market_calendar=market_calendar,
        market_date=normalized_market_date,
        selection_time=selected_at,
        as_of_cutoff=cutoff,
    )
    derived: list[PointInTimeCohortCandidate] = []
    for values in preflight:
        security = validate_security_identity(values["security"])
        identity_sources, reasons = _identity_sources(
            archive=archive,
            security=security,
            raw_sources=values["identity_sources"],
            as_of_cutoff=cutoff,
            first_session=session_dates[0],
            market_date=normalized_market_date,
        )
        market_source, prior_close, median = _market_source(
            archive=archive,
            security=security,
            raw_source=values["market_data_source"],
            as_of_cutoff=cutoff,
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
        selection_window_open_at=_timestamp_text(selection_window_open),
        selection_window_close_at=_timestamp_text(market_open),
        market_session_open_at=_timestamp_text(market_open),
        market_session_close_at=_timestamp_text(market_close),
        selection_time=selection_time,
        as_of_cutoff=as_of_cutoff,
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
    """Mandatory qualifying verification: reopen and rederive every source byte."""

    cohort = validate_nonqualifying_point_in_time_cohort_record(value)
    candidate_inputs = tuple(
        {
            "security": candidate.security.to_dict(),
            "identity_sources": [
                {
                    "source_profile": source.source_profile,
                    "record_identity": source.record_identity,
                    "raw_artifact_id": source.raw_artifact_id,
                    "raw_artifact_sha256": source.raw_artifact_sha256,
                }
                for source in candidate.identity_sources
            ],
            "market_data_source": {
                "source_profile": candidate.market_data_source.source_profile,
                "record_identity": candidate.market_data_source.record_identity,
                "raw_artifact_id": candidate.market_data_source.raw_artifact_id,
                "raw_artifact_sha256": (
                    candidate.market_data_source.raw_artifact_sha256
                ),
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
