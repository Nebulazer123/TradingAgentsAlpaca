"""Bounded Alpaca intake diagnostics; never security-master/cohort admission.

Standard-library only. No network calls or application credential/configuration
reads on import; standard timezone data may be loaded. See
docs/data/ALPACA_SOURCE_PROBE.md.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import http.client
import json
import os
import re
import socket
import ssl
import stat
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, replace
from decimal import Decimal
from pathlib import Path
from typing import Protocol
from urllib.parse import urlencode, urlsplit
from uuid import UUID
from zoneinfo import ZoneInfo

UTC = dt.timezone.utc
NY = ZoneInfo("America/New_York")
SCHEMA = "alpaca_source_probe/v1"
SOURCE_REVISION = "b3484fe22270b9282adef2228a35477558730b4a"
MAX_SYMBOLS = 12
MAX_JSON_BYTES = 32 * 1024 * 1024
MAX_REQUESTS = 64
MAX_PAGES = 8
MAX_TOTAL_BYTES = 96 * 1024 * 1024
MAX_SECONDS = 180
MAX_EVENTS = 2000
AUTHORITY = {"analysis_only": True, "execution_authority": "none", "can_submit_orders": False}
_SYMBOL = re.compile(r"[A-Z][A-Z0-9.-]{0,14}")
_TOKEN = re.compile(r"[\x21-\x7e]{1,2048}")
_HOSTS = frozenset({"paper-api.alpaca.markets", "data.alpaca.markets", "stream.data.alpaca.markets"})
_EXCHANGES = frozenset({"AMEX", "ARCA", "BATS", "NASDAQ", "NYSE", "NYSEARCA"})
_TERMINAL_ERRORS = {"authentication_failed", "rate_limited", "credential_echo_withheld", "request_budget", "byte_budget", "time_budget"}


class ProbeError(ValueError):
    """A diagnostic input or retained bundle is invalid; never print raw inputs."""


def _json_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _date(value: object) -> dt.date:
    if type(value) is not str:
        raise ProbeError("date_requires_iso_string")
    try:
        result = dt.date.fromisoformat(value)
    except ValueError as exc:
        raise ProbeError("invalid_iso_date") from exc
    if result.isoformat() != value:
        raise ProbeError("noncanonical_iso_date")
    return result


def _stamp(value: dt.datetime) -> str:
    if type(value) is not dt.datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ProbeError("timezone_required")
    return value.astimezone(UTC).isoformat(timespec="microseconds")


def _time(value: object) -> dt.datetime:
    if type(value) is not str:
        raise ProbeError("timestamp_required")
    try:
        result = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ProbeError("invalid_timestamp") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise ProbeError("timezone_required")
    return result.astimezone(UTC)


def _load(raw: bytes) -> object:
    """Exact finite decimal parsing; duplicate JSON keys are never normalized away."""
    if type(raw) is not bytes or len(raw) > MAX_JSON_BYTES:
        raise ProbeError("json_byte_limit")

    def pairs(items: list[tuple[str, object]]) -> dict:
        output: dict = {}
        for key, value in items:
            if key in output:
                raise ProbeError("duplicate_json_key")
            output[key] = value
        return output

    def number(text: str) -> Decimal:
        if len(text) > 128:
            raise ProbeError("number_limit")
        value = Decimal(text)
        if not value.is_finite() or abs(value.as_tuple().exponent) > 100:
            raise ProbeError("number_limit")
        return value

    def integer(text: str) -> int:
        if len(text) > 128:
            raise ProbeError("number_limit")
        return int(text)

    def constant(_: str) -> object:
        raise ProbeError("nonfinite_json")

    try:
        value = json.loads(raw, object_pairs_hook=pairs, parse_float=number, parse_int=integer, parse_constant=constant)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ProbeError("malformed_json") from exc
    stack = [(value, 0)]
    count = 0
    while stack:
        item, depth = stack.pop()
        count += 1
        if depth > 32 or count > 1_000_000:
            raise ProbeError("json_shape_limit")
        if isinstance(item, dict):
            stack.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            stack.extend((child, depth + 1) for child in item)
    return value


def _plain(value: object) -> object:
    if isinstance(value, Decimal):
        return _decimal_text(value)
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_plain(item) for item in value]
    return value


def _decimal_text(value: Decimal) -> str:
    result = format(value, "f")
    return result.rstrip("0").rstrip(".") if "." in result else result


@dataclass(frozen=True)
class ProbePlan:
    """Explicit inclusive market-date window; not a historical study admission."""

    start: str
    end: str
    symbol_asof: str
    symbols: tuple[str, ...]
    replay_since: str | None = None
    replay_until: str | None = None

    def __post_init__(self) -> None:
        first, last, asof = _date(self.start), _date(self.end), _date(self.symbol_asof)
        if not dt.timedelta(0) <= last - first <= dt.timedelta(days=370):
            raise ProbeError("date_window_limit")
        if asof < dt.date(2010, 1, 1):
            raise ProbeError("symbol_asof_out_of_range")
        if type(self.symbols) is not tuple or not 1 <= len(self.symbols) <= MAX_SYMBOLS:
            raise ProbeError("symbol_count_limit")
        if any(type(item) is not str or not _SYMBOL.fullmatch(item) for item in self.symbols):
            raise ProbeError("invalid_symbol")
        if self.symbols != tuple(sorted(set(self.symbols))):
            raise ProbeError("symbols_must_be_unique_sorted")
        if (self.replay_since is None) != (self.replay_until is None):
            raise ProbeError("replay_requires_both_bounds")
        if self.replay_since is not None:
            span = _time(self.replay_until) - _time(self.replay_since)
            if not dt.timedelta(0) < span <= dt.timedelta(days=7):
                raise ProbeError("replay_window_limit")

    def to_dict(self) -> dict:
        return {"schema_version": SCHEMA, "start": self.start, "end": self.end,
                "symbol_asof": self.symbol_asof, "symbols": list(self.symbols),
                "replay_since": self.replay_since, "replay_until": self.replay_until}

    @classmethod
    def from_dict(cls, value: object) -> ProbePlan:
        fields = {"schema_version", "start", "end", "symbol_asof", "symbols", "replay_since", "replay_until"}
        if type(value) is not dict or set(value) != fields or value["schema_version"] != SCHEMA:
            raise ProbeError("invalid_probe_plan")
        if type(value["symbols"]) is not list:
            raise ProbeError("invalid_probe_symbols")
        return cls(value["start"], value["end"], value["symbol_asof"], tuple(value["symbols"]),
                   value["replay_since"], value["replay_until"])


@dataclass(frozen=True)
class ProbeRequest:
    query_id: str
    kind: str
    host: str
    path: str
    params: tuple[tuple[str, str], ...]
    symbol: str | None = None

    @property
    def url(self) -> str:
        return f"https://{self.host}{self.path}" + (f"?{urlencode(self.params)}" if self.params else "")

    def page(self, token: str) -> ProbeRequest:
        if self.kind not in {"bars", "actions"} or not _TOKEN.fullmatch(token):
            raise ProbeError("invalid_page_token")
        return replace(self, params=tuple((k, v) for k, v in self.params if k != "page_token") + (("page_token", token),))

    def to_dict(self) -> dict:
        return {"query_id": self.query_id, "kind": self.kind, "method": "GET", "url": self.url, "symbol": self.symbol}


def build_requests(plan: ProbePlan) -> tuple[ProbeRequest, ...]:
    """Routes are generated from validated data; no caller-supplied endpoint URLs."""
    plan = ProbePlan.from_dict(plan.to_dict())
    first = dt.datetime.combine(_date(plan.start), dt.time(), NY).astimezone(UTC)
    after = dt.datetime.combine(_date(plan.end) + dt.timedelta(days=1), dt.time(), NY).astimezone(UTC)
    def z(value: dt.datetime) -> str:
        return value.isoformat(timespec="seconds").replace("+00:00", "Z")

    requests = [
        ProbeRequest(f"assets_{state}", "assets", "paper-api.alpaca.markets", "/v2/assets",
                     (("status", state), ("asset_class", "us_equity")))
        for state in ("active", "inactive")
    ]
    requests.append(ProbeRequest("calendar", "calendar", "paper-api.alpaca.markets", "/v2/calendar",
                                 (("start", plan.start), ("end", plan.end), ("date_type", "TRADING"))))
    for symbol in plan.symbols:
        requests.append(ProbeRequest(f"asset_{symbol}", "asset", "paper-api.alpaca.markets", f"/v2/assets/{symbol}", (), symbol))
        requests.append(ProbeRequest(f"bars_{symbol}", "bars", "data.alpaca.markets", f"/v2/stocks/{symbol}/bars",
                                     (("timeframe", "1Day"), ("feed", "sip"), ("adjustment", "raw"),
                                      ("start", z(first)), ("end", z(after - dt.timedelta(seconds=1))),
                                      ("asof", plan.symbol_asof), ("limit", "1000"), ("sort", "asc")), symbol))
    requests.append(ProbeRequest("actions", "actions", "data.alpaca.markets", "/v1/corporate-actions",
                                 (("symbols", ",".join(plan.symbols)), ("start", plan.start), ("end", plan.end),
                                  ("region", "us"), ("data_quality", "all"), ("limit", "1000"), ("sort", "asc"))))
    if plan.replay_since:
        requests.append(ProbeRequest("action_replay", "sse", "stream.data.alpaca.markets", "/v1beta1/events/corporate-actions",
                                     (("region", "us"), ("since", plan.replay_since), ("until", plan.replay_until))))
    return tuple(requests)


@dataclass(frozen=True)
class FetchResult:
    status: int | None
    content_type: str
    body: bytes
    complete: bool = True
    stop_reason: str | None = None

    def __post_init__(self) -> None:
        if self.status is not None and (type(self.status) is not int or not 100 <= self.status <= 599):
            raise ProbeError("invalid_http_status")
        if type(self.complete) is not bool or type(self.body) is not bytes or type(self.content_type) is not str:
            raise ProbeError("invalid_response_types")
        if self.stop_reason is not None and (type(self.stop_reason) is not str or re.fullmatch(r"[a-z_]{1,80}", self.stop_reason) is None):
            raise ProbeError("invalid_stop_reason")
        if self.complete and self.stop_reason is not None:
            raise ProbeError("complete_response_has_stop_reason")


class Transport(Protocol):
    def get(self, request: ProbeRequest, *, timeout: float, max_bytes: int, deadline: float) -> FetchResult: ...


class AlpacaReadTransport:
    """One-shot fixed-route HTTPS GET; no redirects, proxies, retries or writes.

    Construct only after the caller has checked an explicit collection opt-in.
    DNS/OS calls retain OS timing behavior; the overall budget is cooperative.
    """

    def __init__(self, plan: ProbePlan, key: str, secret: str):
        self._base = {request.query_id: request for request in build_requests(plan)}
        if not key or not secret or any(ch.isspace() for ch in key + secret):
            raise ProbeError("paper_credentials_missing_or_invalid")
        self._headers = {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret, "Accept-Encoding": "identity"}
        self._secrets = (key.encode(), secret.encode())

    def get(self, request: ProbeRequest, *, timeout: float, max_bytes: int, deadline: float) -> FetchResult:
        base = self._base.get(request.query_id)
        if base is None:
            raise ProbeError("unplanned_request")
        token = dict(request.params).get("page_token")
        if request != (base.page(token) if token else base) or request.host not in _HOSTS:
            raise ProbeError("unplanned_request")
        if max_bytes <= 0 or timeout <= 0:
            return FetchResult(None, "", b"", False, "byte_or_time_budget")
        headers = {**self._headers, "Accept": "text/event-stream" if request.kind == "sse" else "application/json"}
        connection = http.client.HTTPSConnection(request.host, timeout=timeout, context=ssl.create_default_context())
        body = bytearray()
        status = None
        mime = ""
        complete = False
        reason = None
        try:
            parsed = urlsplit(request.url)
            connection.request("GET", parsed.path + ("?" + parsed.query if parsed.query else ""), headers=headers)
            response = connection.getresponse()
            status = response.status
            mime = response.getheader("Content-Type", "").split(";", 1)[0].strip().lower()
            if re.fullmatch(r"[a-z0-9.+-]{1,80}/[a-z0-9.+-]{1,80}", mime) is None:
                mime = "unrecognized"
            if any(secret.lower() in mime.encode() for secret in self._secrets):
                return FetchResult(status, "withheld", b"", False, "credential_echo_withheld")
            if response.getheader("Content-Encoding", "identity").lower() not in {"", "identity"}:
                return FetchResult(status, mime, b"", False, "unexpected_content_encoding")
            length_header = response.getheader("Content-Length")
            expected_length = None
            if length_header is not None:
                if not re.fullmatch(r"[0-9]{1,16}", length_header):
                    return FetchResult(status, mime, b"", False, "invalid_content_length")
                expected_length = int(length_header)
            while True:
                left = deadline - time.monotonic()
                if left <= 0:
                    reason = "time_budget"
                    break
                if connection.sock is not None:
                    connection.sock.settimeout(min(timeout, left))
                chunk = response.read1(min(65536, max_bytes - len(body) + 1))
                if not chunk:
                    complete = expected_length is None or len(body) == expected_length
                    reason = None if complete else "incomplete_http_body"
                    break
                body.extend(chunk)
                if len(body) > max_bytes:
                    del body[max_bytes:]
                    reason = "byte_budget"
                    break
        except (OSError, socket.timeout, http.client.HTTPException):
            # Never put exception text, credentials, or server error text in logs.
            reason = "transport_error"
        finally:
            connection.close()
        if any(secret in body for secret in self._secrets):
            return FetchResult(status, mime, b"", False, "credential_echo_withheld")
        return FetchResult(status, mime, bytes(body), complete, reason)


def _exclusive(path: Path, raw: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())


def _read(path: Path, limit: int = MAX_JSON_BYTES) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise ProbeError("bundle_file_unavailable") from exc
    with os.fdopen(fd, "rb") as handle:
        metadata = os.fstat(handle.fileno())
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > limit:
            raise ProbeError("bundle_file_type_or_size")
        raw = handle.read(limit + 1)
        if len(raw) > limit:
            raise ProbeError("bundle_file_size")
        return raw


def _response_problem(result: FetchResult) -> str | None:
    if not result.complete:
        return result.stop_reason or "incomplete_body"
    if result.status == 401:
        return "authentication_failed"
    if result.status == 403:
        return "forbidden_unverified_entitlement"
    if result.status == 404:
        return "not_found_not_delisting_proof"
    if result.status == 429:
        return "rate_limited"
    if result.status != 200:
        return "http_status_not_200"
    return None


def _next_token(kind: str, payload: object) -> str | None:
    if kind not in {"bars", "actions"}:
        return None
    if type(payload) is not dict or "next_page_token" not in payload:
        raise ProbeError("pagination_field_missing")
    token = payload["next_page_token"]
    if token is not None and (type(token) is not str or not _TOKEN.fullmatch(token)):
        raise ProbeError("invalid_page_token")
    return token


def collect_probe(
    plan: ProbePlan, destination: Path, transport: Transport, *, allow_network_read: bool = False,
    clock: Callable[[], dt.datetime] = lambda: dt.datetime.now(UTC),
    monotonic: Callable[[], float] = time.monotonic,
) -> dict:
    """Capture private diagnostics in a NEW bundle; do not admit trading evidence."""
    if allow_network_read is not True:
        raise ProbeError("collection_requires_explicit_read_authorization")
    plan = ProbePlan.from_dict(plan.to_dict())
    now = clock()
    local_today = _time(_stamp(now)).astimezone(NY).date()
    if _date(plan.end) >= local_today or _date(plan.symbol_asof) > local_today:
        raise ProbeError("capture_requires_completed_dates_and_nonfuture_asof")
    if plan.replay_until and _time(plan.replay_until) > now.astimezone(UTC):
        raise ProbeError("replay_until_in_future")
    # Only this private diagnostic directory is written. Existing destinations are refused.
    destination = Path(destination)
    if destination.is_symlink() or destination.exists():
        raise ProbeError("destination_must_be_new")
    if not destination.parent.is_dir():
        raise ProbeError("destination_parent_must_exist")
    destination.mkdir(mode=0o700)
    (destination / "responses").mkdir(mode=0o700)
    plan_bytes = _json_bytes(plan.to_dict())
    _exclusive(destination / "plan.json", plan_bytes)
    entries: list[dict] = []
    completed: list[str] = []
    failures: dict[str, str] = {}
    started = monotonic()
    stop_all = None
    total_bytes = 0
    previous_capture = now.astimezone(UTC)
    for base in build_requests(plan):
        if stop_all:
            failures[base.query_id] = "not_attempted_after_" + stop_all
            continue
        request = base
        seen: set[str] = set()
        for page in range(1, MAX_PAGES + 1):
            if len(entries) >= MAX_REQUESTS or total_bytes >= MAX_TOTAL_BYTES or monotonic() - started >= MAX_SECONDS:
                stop_all = "request_budget" if len(entries) >= MAX_REQUESTS else "byte_budget" if total_bytes >= MAX_TOTAL_BYTES else "time_budget"
                failures[base.query_id] = stop_all
                break
            began = _stamp(clock())
            if _time(began) < previous_capture:
                raise ProbeError("capture_clock_regressed")
            maximum = min(MAX_JSON_BYTES, MAX_TOTAL_BYTES - total_bytes)
            seconds = min(15.0, MAX_SECONDS - (monotonic() - started))
            try:
                result = transport.get(request, timeout=seconds, max_bytes=maximum, deadline=time.monotonic() + seconds)
            except Exception:
                # A provider/SDK exception may contain authentication headers.
                result = FetchResult(None, "", b"", False, "transport_error")
            ended = _stamp(clock())
            if _time(ended) < _time(began):
                raise ProbeError("capture_clock_regressed")
            previous_capture = _time(ended)
            if type(result) is not FetchResult or type(result.body) is not bytes:
                raise ProbeError("invalid_transport_result")
            if len(result.body) > maximum:
                result = replace(result, body=result.body[:maximum], complete=False, stop_reason="byte_budget")
            index = len(entries) + 1
            filename = f"responses/{index:04d}.body"
            _exclusive(destination / filename, result.body)
            entry = {"sequence": index, **request.to_dict(), "page": page,
                     "request_started_at": began, "capture_completed_at": ended,
                     "status": result.status, "content_type": result.content_type,
                     "body_complete": result.complete, "stop_reason": result.stop_reason,
                     "body_path": filename, "body_bytes": len(result.body), "body_sha256": _sha(result.body)}
            _exclusive(destination / f"responses/{index:04d}.json", _json_bytes(entry))
            entries.append(entry)
            total_bytes += len(result.body)
            problem = _response_problem(result)
            if problem:
                failures[base.query_id] = problem
                if problem in _TERMINAL_ERRORS:
                    stop_all = problem
                break
            if result.content_type != ("text/event-stream" if base.kind == "sse" else "application/json"):
                failures[base.query_id] = "unexpected_content_type"
                break
            try:
                payload = None if base.kind == "sse" else _load(result.body)
                token = _next_token(base.kind, payload)
            except ProbeError as exc:
                failures[base.query_id] = str(exc)
                break
            if token is None:
                completed.append(base.query_id)
                break
            if token in seen:
                failures[base.query_id] = "pagination_cycle"
                break
            if page == MAX_PAGES:
                failures[base.query_id] = "page_budget"
                break
            seen.add(token)
            request = base.page(token)
    finished_at = _stamp(clock())
    if _time(finished_at) < previous_capture:
        raise ProbeError("capture_clock_regressed")
    manifest = {"schema_version": SCHEMA, "plan_sha256": _sha(plan_bytes),
                "transport_mode": "https" if type(transport) is AlpacaReadTransport else "injected_fixture",
                "entries": entries, "completed_queries": completed, "failures": failures,
                "total_body_bytes": total_bytes, "capture_finished_at": finished_at, **AUTHORITY}
    _exclusive(destination / "manifest.json", _json_bytes(manifest))
    report = inspect_probe(destination)
    _exclusive(destination / "report.json", _json_bytes(report))
    return report


def _asset(row: object) -> dict:
    if type(row) is not dict or not {"id", "symbol", "class", "exchange", "status", "tradable"} <= set(row):
        raise ProbeError("asset_schema_missing_fields")
    try:
        UUID(row["id"])
    except (ValueError, TypeError, AttributeError) as exc:
        raise ProbeError("asset_id_not_uuid") from exc
    if any(type(row[key]) is not str or not row[key] for key in ("symbol", "class", "exchange", "status")) or type(row["tradable"]) is not bool:
        raise ProbeError("asset_field_type")
    return {key: row[key] for key in ("id", "symbol", "class", "exchange", "status", "tradable")}


def _calendar(payload: object, plan: ProbePlan) -> list[str]:
    if type(payload) is not list:
        raise ProbeError("calendar_not_list")
    dates = []
    for row in payload:
        if type(row) is not dict or not {"date", "open", "close"} <= set(row):
            raise ProbeError("calendar_schema")
        date = _date(row["date"])
        if not _date(plan.start) <= date <= _date(plan.end):
            raise ProbeError("calendar_outside_request")
        try:
            opening, closing = dt.time.fromisoformat(row["open"]), dt.time.fromisoformat(row["close"])
        except (ValueError, TypeError) as exc:
            raise ProbeError("calendar_hours") from exc
        if opening.tzinfo is not None or closing.tzinfo is not None or opening >= closing:
            raise ProbeError("calendar_hours")
        dates.append(date.isoformat())
    if dates != sorted(set(dates)):
        raise ProbeError("calendar_duplicate_or_unsorted")
    return dates


def _bars(payloads: list, symbol: str, sessions: list[str]) -> dict:
    values: list[tuple[str, Decimal, int]] = []
    for payload in payloads:
        if type(payload) is not dict or payload.get("symbol") != symbol or type(payload.get("bars")) is not list:
            raise ProbeError("bar_response_shape_or_symbol")
        for row in payload["bars"]:
            if type(row) is not dict or not {"t", "c", "v"} <= set(row):
                raise ProbeError("bar_schema")
            moment = _time(row["t"]).astimezone(NY)
            if moment.timetz().replace(tzinfo=None) != dt.time():
                raise ProbeError("not_daily_bar_timestamp")
            close, volume = row["c"], row["v"]
            if type(close) not in (int, Decimal) or type(volume) is not int or volume < 0:
                raise ProbeError("bar_number_type")
            close = Decimal(close)
            if not close.is_finite() or close <= 0 or len(close.as_tuple().digits) > 100 or len(str(volume)) > 100:
                raise ProbeError("bar_number_range")
            values.append((moment.date().isoformat(), close, volume))
    dates = [item[0] for item in values]
    if dates != sorted(set(dates)):
        raise ProbeError("bar_duplicate_or_unsorted")
    missing, extra = sorted(set(sessions) - set(dates)), sorted(set(dates) - set(sessions))
    result = {"row_count": len(values), "missing_sessions": missing, "unexpected_sessions": extra,
              "matches_60_session_grid": len(sessions) == 60 and dates == sessions,
              "feed": "sip", "adjustment": "raw", "session_basis": "alpaca_provider_daily_not_certified_regular_only",
              "prior_complete_close": None, "median_daily_dollar_volume": None, "price_floor_pass": None,
              "identity_continuity": "NOT_ESTABLISHED", "security_type": "UNKNOWN"}
    if result["matches_60_session_grid"]:
        # Same integer-coefficient method as cohort_admission: no ambient rounding.
        def decimal_from(coefficient: int, exponent: int) -> Decimal:
            return Decimal((0, tuple(int(ch) for ch in str(coefficient)), exponent))

        products = []
        for _, close, volume in values:
            _, digits, exponent = close.as_tuple()
            coefficient = int("".join(str(digit) for digit in digits))
            products.append(decimal_from(coefficient * volume, exponent))
        products.sort()
        parts = [item.as_tuple() for item in products[29:31]]
        exponent = min(item.exponent for item in parts)
        total = sum(int("".join(str(d) for d in item.digits)) * 10 ** (item.exponent - exponent) for item in parts)
        median = decimal_from(total // 2, exponent) if total % 2 == 0 else decimal_from(total * 5, exponent - 1)
        result.update(prior_complete_close=_decimal_text(values[-1][1]),
                      median_daily_dollar_volume=_decimal_text(median), price_floor_pass=values[-1][1] >= 5)
    return result


def parse_sse(raw: bytes) -> dict:
    """Retain/deduplicate emitted versions, without reconstructing action history.

    Only documented envelope identity fields are inspected. Unknown action types
    remain present; no inferred mutation order or invented effective time.
    """
    try:
        text = raw.decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
    except UnicodeError as exc:
        raise ProbeError("sse_not_utf8") from exc
    records: dict[str, bytes] = {}
    types: Counter = Counter()
    duplicate_count = 0
    data: list[str] = []
    wire_id: str | None = None
    frame_count = 0
    lines = text.split("\n")
    if text.endswith("\n"):
        lines.pop()  # An EOF after one line ending is not an SSE blank line.
    for line in lines:
        if line == "":
            if data:
                frame_count += 1
                if frame_count > MAX_EVENTS:
                    raise ProbeError("sse_event_limit")
                payload = _load("\n".join(data).encode())
                if type(payload) is not dict or type(payload.get("event_id")) is not str or type(payload.get("event_type")) is not str:
                    raise ProbeError("sse_envelope_unrecognized")
                event_id = payload["event_id"]
                if not event_id or (wire_id and wire_id != event_id):
                    raise ProbeError("sse_event_identity_mismatch")
                material = "\n".join(data).encode("utf-8")
                if event_id in records:
                    if records[event_id] != material:
                        raise ProbeError("sse_conflicting_event_identity")
                    duplicate_count += 1
                else:
                    records[event_id] = material
                    types[payload["event_type"]] += 1
            data, wire_id = [], None
        elif not line.startswith(":"):
            field, _, value = line.partition(":")
            value = value[1:] if value.startswith(" ") else value
            if field == "data":
                data.append(value)
            elif field == "id":
                wire_id = value
    if data:
        raise ProbeError("sse_unterminated_frame")
    return {"unique_events": len(records), "duplicate_deliveries": duplicate_count,
            "event_types": dict(sorted(types.items())), "event_ids": list(records),
            "revision_history_completeness": "UNKNOWN", "mutations_applied": False}


def inspect_probe(root: Path) -> dict:
    """Offline raw replay. Transport completion never becomes market completeness."""
    root = Path(root)
    if root.is_symlink() or (root / "responses").is_symlink():
        raise ProbeError("bundle_symlink")
    plan_bytes = _read(root / "plan.json", 65536)
    plan = ProbePlan.from_dict(_load(plan_bytes))
    manifest = _load(_read(root / "manifest.json", 2 * 1024 * 1024))
    manifest_fields = {"schema_version", "plan_sha256", "transport_mode", "entries", "completed_queries",
                       "failures", "total_body_bytes", "capture_finished_at", *AUTHORITY}
    if type(manifest) is not dict or set(manifest) != manifest_fields or manifest.get("schema_version") != SCHEMA or manifest.get("plan_sha256") != _sha(plan_bytes):
        raise ProbeError("manifest_plan_mismatch")
    if any(type(manifest.get(key)) is not type(value) or manifest[key] != value for key, value in AUTHORITY.items()):
        raise ProbeError("manifest_authority_mismatch")
    if manifest.get("transport_mode") not in {"https", "injected_fixture"}:
        raise ProbeError("unknown_transport_mode")
    finished_at = _time(manifest.get("capture_finished_at"))
    entries = manifest.get("entries")
    if type(entries) is not list or len(entries) > MAX_REQUESTS:
        raise ProbeError("manifest_entries_limit")
    requests = {item.query_id: item for item in build_requests(plan)}
    groups: dict[str, list[tuple[dict, bytes]]] = {key: [] for key in requests}
    expected_files = {"plan.json", "manifest.json", "report.json", "responses"}
    if {item.name for item in root.iterdir()} - expected_files:
        raise ProbeError("unexpected_bundle_file")
    total = 0
    previous_capture = None
    receipt_fields = {"sequence", "query_id", "kind", "method", "url", "symbol", "page",
                      "request_started_at", "capture_completed_at", "status", "content_type",
                      "body_complete", "stop_reason", "body_path", "body_bytes", "body_sha256"}
    for index, entry in enumerate(entries, 1):
        if type(entry) is not dict or set(entry) != receipt_fields or type(entry.get("sequence")) is not int or entry.get("sequence") != index or entry.get("body_path") != f"responses/{index:04d}.body":
            raise ProbeError("manifest_entry_identity")
        if entry.get("query_id") not in requests:
            raise ProbeError("unplanned_query")
        if _json_bytes(entry) != _read(root / f"responses/{index:04d}.json", 32768):
            raise ProbeError("receipt_manifest_mismatch")
        raw = _read(root / entry["body_path"])
        if len(raw) != entry.get("body_bytes") or _sha(raw) != entry.get("body_sha256"):
            raise ProbeError("raw_bytes_mismatch")
        began, ended = _time(entry["request_started_at"]), _time(entry["capture_completed_at"])
        if ended < began or ended > finished_at or (previous_capture is not None and began < previous_capture):
            raise ProbeError("receipt_clock_order")
        previous_capture = ended
        groups[entry["query_id"]].append((entry, raw))
        total += len(raw)
    actual_files = {item.name for item in (root / "responses").iterdir()}
    expected_responses = {f"{index:04d}.{suffix}" for index in range(1, len(entries) + 1) for suffix in ("body", "json")}
    if actual_files != expected_responses or total != manifest.get("total_body_bytes") or total > MAX_TOTAL_BYTES:
        raise ProbeError("response_inventory_mismatch")
    queries: dict[str, dict] = {}
    decoded: dict[str, list] = {}
    for query_id, base in requests.items():
        pages = groups[query_id]
        state: dict = {"status": "not_attempted", "page_count": len(pages), "body_bytes": sum(len(raw) for _, raw in pages)}
        queries[query_id] = state
        if not pages:
            continue
        expected, seen = base, set()
        decoded[query_id] = []
        token: str | None = None
        for index, (entry, raw) in enumerate(pages, 1):
            if entry["page"] != index or any(entry.get(key) != value for key, value in expected.to_dict().items()):
                raise ProbeError("request_or_pagination_chain_mismatch")
            if index > MAX_PAGES:
                raise ProbeError("page_count_limit")
            result = FetchResult(entry["status"], entry["content_type"], raw, entry["body_complete"], entry["stop_reason"])
            problem = _response_problem(result)
            if problem:
                state.update(status="unavailable", reason=problem)
                if index != len(pages):
                    raise ProbeError("pages_after_failed_request")
                break
            wanted = "text/event-stream" if base.kind == "sse" else "application/json"
            if result.content_type != wanted:
                state.update(status="invalid", reason="unexpected_content_type")
                break
            try:
                payload = parse_sse(raw) if base.kind == "sse" else _load(raw)
                decoded[query_id].append(payload)
                token = _next_token(base.kind, payload)
                if token in seen:
                    raise ProbeError("pagination_cycle")
                if token:
                    seen.add(token)
                    expected = base.page(token)
                elif index != len(pages):
                    raise ProbeError("pages_after_terminal_response")
            except ProbeError as exc:
                state.update(status="invalid", reason=str(exc))
                break
            state["status"] = "incomplete" if token else "response_complete"
        if state["status"] != "response_complete":
            decoded.pop(query_id, None)
    result = {"schema_version": SCHEMA, "plan_sha256": _sha(plan_bytes),
              "transport_mode": manifest["transport_mode"],
              "queries": queries, "sample_symbols": list(plan.symbols), "inventory": {}, "sample_assets": {},
              "sample_bars": {}, "corporate_actions": {}, "action_replay": {},
              "market_population_completeness": "NOT_ESTABLISHED", "security_master_qualified": False,
              "cohort_qualified": False, "historical_custody_qualified": False,
              "original_source_capture_times_preserved": True,
              "qualification_blockers": ["sample_is_not_ranked_market_universe", "dated_identity_and_type_history_unproven",
                                         "corporate_action_coverage_unproven", "provider_retention_and_use_rights_unverified"],
              **AUTHORITY}
    sessions: list[str] = []
    if "calendar" in decoded:
        try:
            sessions = _calendar(decoded["calendar"][0], plan)
            result["calendar"] = {"session_count": len(sessions), "sessions": sessions, "exactly_60": len(sessions) == 60}
        except ProbeError as exc:
            queries["calendar"].update(status="invalid", reason=str(exc))
    all_assets: dict[str, dict] = {}
    active_symbols: dict[str, list[str]] = {}
    for state_name in ("active", "inactive"):
        query_id = f"assets_{state_name}"
        if query_id not in decoded:
            continue
        try:
            payload = decoded[query_id][0]
            if type(payload) is not list:
                raise ProbeError("assets_not_list")
            assets = [_asset(item) for item in payload]
            if len({item["id"] for item in assets}) != len(assets):
                raise ProbeError("duplicate_asset_id")
            conflicts = []
            candidates = 0
            for item in assets:
                if item["status"] != state_name or item["class"] != "us_equity":
                    raise ProbeError("assets_request_filter_mismatch")
                if item["id"] in all_assets:
                    conflicts.append(item["id"])
                all_assets[item["id"]] = item
                if state_name == "active":
                    active_symbols.setdefault(item["symbol"], []).append(item["id"])
                    candidates += int(item["tradable"] and item["exchange"] in _EXCHANGES)
            result["inventory"][state_name] = {"records": len(assets), "potential_common_stock_candidates_not_type_verified": candidates,
                                                  "cross_snapshot_conflicting_ids": conflicts,
                                                  "historical_membership": "UNKNOWN", "common_stock_classification": "UNKNOWN"}
        except ProbeError as exc:
            queries[query_id].update(status="invalid", reason=str(exc))
    result["inventory"]["ambiguous_active_symbols"] = {key: ids for key, ids in sorted(active_symbols.items()) if len(ids) > 1}
    for symbol in plan.symbols:
        key = f"asset_{symbol}"
        if key in decoded:
            try:
                asset = _asset(decoded[key][0])
                if asset["symbol"] != symbol:
                    raise ProbeError("asset_symbol_mismatch")
                result["sample_assets"][symbol] = {**asset, "security_type": "UNKNOWN", "historical_effective_from": None,
                                                    "same_as_discovery_snapshot": all_assets.get(asset["id"]) == asset}
            except ProbeError as exc:
                queries[key].update(status="invalid", reason=str(exc))
        key = f"bars_{symbol}"
        if key in decoded:
            try:
                result["sample_bars"][symbol] = _bars(decoded[key], symbol, sessions)
            except ProbeError as exc:
                queries[key].update(status="invalid", reason=str(exc))
    if "actions" in decoded:
        try:
            counts: Counter = Counter()
            ids: dict[str, bytes] = {}
            for payload in decoded["actions"]:
                if type(payload) is not dict or type(payload.get("corporate_actions")) is not dict:
                    raise ProbeError("corporate_actions_shape")
                for action_type, items in payload["corporate_actions"].items():
                    if type(items) is not list:
                        raise ProbeError("corporate_action_group_shape")
                    for item in items:
                        if type(item) is not dict or type(item.get("id")) is not str:
                            raise ProbeError("corporate_action_id_missing")
                        if item["id"] in ids:
                            raise ProbeError("duplicate_or_revised_action_during_pagination")
                        ids[item["id"]] = _json_bytes(_plain(item))
                        counts[action_type] += 1
            result["corporate_actions"] = {"returned_records": len(ids), "types": dict(sorted(counts.items())),
                                             "query_date_basis": "process_date", "data_quality": "all",
                                             "event_absence_proven": False, "historical_coverage": "UNKNOWN"}
        except ProbeError as exc:
            queries["actions"].update(status="invalid", reason=str(exc))
    if "action_replay" in decoded:
        result["action_replay"] = decoded["action_replay"][0]
    result["all_planned_responses_valid"] = all(item["status"] == "response_complete" for item in queries.values())
    result["all_sample_grids_complete"] = len(result["sample_bars"]) == len(plan.symbols) and all(
        item["matches_60_session_grid"] for item in result["sample_bars"].values()
    )
    result["snapshot_identity_conflicts"] = bool(result["inventory"]["ambiguous_active_symbols"]) or any(
        item.get("cross_snapshot_conflicting_ids") for key, item in result["inventory"].items() if key in {"active", "inactive"}
    ) or any(not item["same_as_discovery_snapshot"] for item in result["sample_assets"].values())
    result["diagnostic_checks_passed"] = (result["all_planned_responses_valid"] and result["all_sample_grids_complete"]
                                          and not result["snapshot_identity_conflicts"])
    result["diagnostic_status"] = "responses_checked_not_qualified" if result["diagnostic_checks_passed"] else "gaps_detected"
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    planning = commands.add_parser("plan", help="Print a fixed GET plan; no credential or network access")
    planning.add_argument("--start", required=True)
    planning.add_argument("--end", required=True)
    planning.add_argument("--symbol-asof", required=True)
    planning.add_argument("--symbols", required=True, help="Comma-separated diagnostic sample; not a universe")
    planning.add_argument("--replay-since")
    planning.add_argument("--replay-until")
    capture = commands.add_parser("collect", help="Explicitly authorized read-only collection; NEVER places orders")
    capture.add_argument("--plan", required=True, type=Path)
    capture.add_argument("--out", required=True, type=Path)
    capture.add_argument("--allow-network-read", action="store_true")
    inspection = commands.add_parser("inspect", help="Offline raw replay; never reads credentials")
    inspection.add_argument("bundle", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "plan":
            symbols = tuple(sorted(set(args.symbols.split(","))))
            plan = ProbePlan(args.start, args.end, args.symbol_asof, symbols, args.replay_since, args.replay_until)
            print(_json_bytes(plan.to_dict()).decode())
            return 0
        if args.command == "collect":
            if not args.allow_network_read:
                raise ProbeError("collection_requires_explicit_read_authorization")
            plan = ProbePlan.from_dict(_load(_read(args.plan, 65536)))
            # Only these existing paper credential names are read, only here.
            # No dotenv, keychain, user config, model API, or broker-account reads.
            transport = AlpacaReadTransport(plan, os.environ.get("ALPACA_PAPER_API_KEY", ""),
                                           os.environ.get("ALPACA_PAPER_SECRET_KEY", ""))
            report = collect_probe(plan, args.out, transport, allow_network_read=True)
        else:
            report = inspect_probe(args.bundle)
        print(_json_bytes(report).decode())
        return 0 if report["diagnostic_checks_passed"] else 2
    except (ProbeError, OSError) as exc:
        message = str(exc) if isinstance(exc, ProbeError) else "local_file_operation_failed"
        print(_json_bytes({"status": "failed", "reason": message, "cohort_qualified": False, **AUTHORITY}).decode())
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
