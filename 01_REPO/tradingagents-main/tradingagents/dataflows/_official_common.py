"""Helpers for official/free research data adapters."""

from __future__ import annotations

import datetime
import email.utils
import hashlib
import json
import os
import random
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests

from tradingagents.schemas.research import SourceEvidencePacket
from tradingagents.schemas.trading import SourceProvenance

DEFAULT_TIMEOUT_SECONDS = 20
DEFAULT_CONNECT_TIMEOUT_SECONDS = 5
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_BACKOFF_BASE_SECONDS = 0.5
DEFAULT_BACKOFF_JITTER_SECONDS = 0.25
DEFAULT_RETRY_AFTER_CAP_SECONDS = 30.0
DEFAULT_CIRCUIT_FAILURE_THRESHOLD = 3
DEFAULT_CIRCUIT_COOLDOWN_SECONDS = 60.0
CONNECTOR_HEALTH_PATH = Path("results/_context/connector-health.json")
UTC = datetime.timezone.utc
SECRET_PARAM_NAMES = {
    "apca-api-key-id",
    "apca-api-secret-key",
    "api-secret",
    "api_secret",
    "api_key",
    "api_token",
    "apikey",
    "authorization",
    "registrationkey",
    "secret",
    "secret_key",
    "token",
    "user_id",
    "userid",
    "userkey",
    "x-api-key",
    "key",
}


class OfficialDataError(RuntimeError):
    """Raised when an official data source cannot produce an evidence packet."""


class RecoverableDataflowError(OfficialDataError):
    """A source failure for which the decision router may try another provider."""


class DataUnavailableError(RecoverableDataflowError):
    """A valid request produced no usable evidence from a configured source."""


class VendorNotConfiguredError(DataUnavailableError, ValueError):
    """An optional provider is unavailable because its configuration is absent."""


class DataTransportError(RecoverableDataflowError):
    """A source request exhausted its transport-level recovery policy."""


@dataclass(frozen=True)
class TextFetchResult:
    text: str
    status_code: int | None
    headers: dict[str, Any]


_CONNECTOR_HEALTH: dict[str, dict[str, Any]] = {}
_CONNECTOR_CIRCUITS: dict[str, dict[str, Any]] = {}


def now_iso() -> str:
    return datetime.datetime.now(tz=UTC).isoformat(timespec="seconds")


def _as_utc(value: datetime.datetime | None = None) -> datetime.datetime:
    current = value or datetime.datetime.now(tz=UTC)
    if current.tzinfo is None:
        return current.replace(tzinfo=UTC)
    return current.astimezone(UTC)


def _sanitize_reason(reason: str) -> str:
    clean = str(reason)
    for name in SECRET_PARAM_NAMES:
        clean = re.sub(
            rf"(?i)({re.escape(name)}=)[^&\s]+",
            r"\1[redacted]",
            clean,
        )
    return clean


def _timeout_value(timeout: int | float | tuple[float, float]) -> int | float | tuple[float, float]:
    if isinstance(timeout, tuple):
        return timeout
    return (min(float(DEFAULT_CONNECT_TIMEOUT_SECONDS), float(timeout)), float(timeout))


def _connector_key(url: str, connector_name: str | None) -> str:
    if connector_name:
        return connector_name
    host = urlsplit(url).netloc.lower()
    return host or "unknown"


def _health_row(connector: str) -> dict[str, Any]:
    row = _CONNECTOR_HEALTH.setdefault(
        connector,
        {
            "connector": connector,
            "calls": 0,
            "successes": 0,
            "errors": 0,
            "rate_limit_count": 0,
            "fallback_count": 0,
            "cache_hit_count": 0,
            "latencies_ms": [],
            "last_success": None,
            "last_error": None,
            "last_error_at": None,
            "circuit_state": "closed",
            "circuit_open_until": None,
        },
    )
    circuit = _CONNECTOR_CIRCUITS.get(connector) or {}
    open_until = circuit.get("opened_until")
    if open_until and float(open_until) > time.time():
        row["circuit_state"] = "open"
        row["circuit_open_until"] = datetime.datetime.fromtimestamp(
            float(open_until),
            tz=UTC,
        ).isoformat(timespec="seconds")
    elif circuit.get("consecutive_failures", 0):
        row["circuit_state"] = "half_open" if open_until else "closed"
        row["circuit_open_until"] = None
    else:
        row["circuit_state"] = "closed"
        row["circuit_open_until"] = None
    return row


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * percentile)))
    return round(ordered[index], 3)


def connector_health_snapshot() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for connector in sorted(_CONNECTOR_HEALTH):
        row = dict(_health_row(connector))
        latencies = [float(value) for value in row.pop("latencies_ms", [])]
        row["p50_latency_ms"] = _percentile(latencies, 0.50)
        row["p95_latency_ms"] = _percentile(latencies, 0.95)
        rows.append(row)
    return rows


def write_connector_health(path: str | Path | None = None) -> Path:
    output_path = Path(path or CONNECTOR_HEALTH_PATH)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "1.0.0",
        "generated_at": now_iso(),
        "analysis_only": True,
        "can_submit_orders": False,
        "row_count": len(_CONNECTOR_HEALTH),
        "connectors": connector_health_snapshot(),
    }
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return output_path


def reset_connector_health() -> None:
    _CONNECTOR_HEALTH.clear()
    _CONNECTOR_CIRCUITS.clear()


def record_connector_health(
    connector: str,
    *,
    success: bool,
    latency_seconds: float = 0.0,
    error: str | None = None,
    rate_limited: bool = False,
    fallback: bool = False,
    cache_hit: bool = False,
    write: bool = True,
) -> None:
    row = _health_row(connector)
    row["calls"] += 1
    if success:
        row["successes"] += 1
        row["last_success"] = now_iso()
        row["last_error"] = None
        row["last_error_at"] = None
    else:
        row["errors"] += 1
        row["last_error"] = _sanitize_reason(error or "source request failed")
        row["last_error_at"] = now_iso()
    if rate_limited:
        row["rate_limit_count"] += 1
    if fallback:
        row["fallback_count"] += 1
    if cache_hit:
        row["cache_hit_count"] += 1
    latencies = row.setdefault("latencies_ms", [])
    if isinstance(latencies, list):
        latencies.append(round(max(latency_seconds, 0.0) * 1000, 3))
        del latencies[:-100]
    _health_row(connector)
    if write:
        write_connector_health()


def _circuit_open_error(connector: str) -> DataTransportError | None:
    state = _CONNECTOR_CIRCUITS.get(connector)
    if not state:
        return None
    open_until = float(state.get("opened_until") or 0.0)
    if open_until > time.time():
        return DataTransportError(f"{connector} connector circuit is open")
    return None


def _record_circuit_success(connector: str) -> None:
    _CONNECTOR_CIRCUITS[connector] = {"consecutive_failures": 0, "opened_until": None}
    _health_row(connector)


def _record_circuit_failure(
    connector: str,
    *,
    threshold: int,
    cooldown_seconds: float,
) -> None:
    state = _CONNECTOR_CIRCUITS.setdefault(
        connector,
        {"consecutive_failures": 0, "opened_until": None},
    )
    state["consecutive_failures"] = int(state.get("consecutive_failures") or 0) + 1
    if state["consecutive_failures"] >= threshold:
        state["opened_until"] = time.time() + cooldown_seconds
    _health_row(connector)
    write_connector_health()


def _retry_after_seconds(value: str | None, *, cap_seconds: float) -> float | None:
    if not value:
        return None
    clean = value.strip()
    try:
        return min(max(float(clean), 0.0), cap_seconds)
    except ValueError:
        pass
    try:
        parsed = email.utils.parsedate_to_datetime(clean)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return min(max((parsed.astimezone(UTC) - _as_utc()).total_seconds(), 0.0), cap_seconds)


def _backoff_seconds(
    attempt_index: int,
    *,
    base_seconds: float,
    jitter_seconds: float,
) -> float:
    return max(base_seconds * (2 ** max(attempt_index - 1, 0)), 0.0) + random.uniform(
        0.0,
        max(jitter_seconds, 0.0),
    )


def _compact_error_detail(value: Any, *, max_chars: int = 300) -> str:
    redacted = redact_payload(value)
    if isinstance(redacted, str):
        text = redacted
    else:
        try:
            text = json.dumps(redacted, sort_keys=True, default=str)
        except (TypeError, ValueError):
            text = str(redacted)
    clean = re.sub(r"\s+", " ", _sanitize_reason(text)).strip()
    clean = re.sub(
        r"\b[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b",
        "[redacted-jwt]",
        clean,
    )
    return clean[:max_chars]


def _response_error_detail(response: Any) -> str | None:
    if response is None:
        return None
    try:
        data = response.json()
    except ValueError:
        text = _response_text(response)
        return _compact_error_detail(text) if text.strip() else None
    if isinstance(data, dict):
        for key in ("response", "message", "error", "detail"):
            value = data.get(key)
            if value not in (None, "", [], {}):
                return _compact_error_detail(value)
        if data.get("success") is False:
            return _compact_error_detail(data)
    elif data not in (None, "", [], {}):
        return _compact_error_detail(data)
    return None


def _request_json(
    method: str,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    body: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    session: Any | None = None,
    timeout: int | float | tuple[float, float] = DEFAULT_TIMEOUT_SECONDS,
    connector_name: str | None = None,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    backoff_base_seconds: float = DEFAULT_BACKOFF_BASE_SECONDS,
    backoff_jitter_seconds: float = DEFAULT_BACKOFF_JITTER_SECONDS,
    retry_after_cap_seconds: float = DEFAULT_RETRY_AFTER_CAP_SECONDS,
    circuit_failure_threshold: int = DEFAULT_CIRCUIT_FAILURE_THRESHOLD,
    circuit_cooldown_seconds: float = DEFAULT_CIRCUIT_COOLDOWN_SECONDS,
    sleep_func: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    normalized_method = method.upper()
    if normalized_method not in {"GET", "POST"}:
        raise OfficialDataError("JSON response helper supports GET and POST only")

    connector = _connector_key(url, connector_name)
    open_error = _circuit_open_error(connector)
    if open_error is not None:
        record_connector_health(connector, success=False, error=str(open_error), write=True)
        raise open_error

    client = session or requests.Session()
    attempts = max(max_attempts, 1)
    last_error = "official source request failed"
    for attempt in range(1, attempts + 1):
        started = time.perf_counter()
        rate_limited = False
        try:
            if normalized_method == "POST":
                response = client.post(
                    url,
                    json=body,
                    headers=headers,
                    timeout=_timeout_value(timeout),
                )
            else:
                response = client.get(
                    url,
                    params=params,
                    headers=headers,
                    timeout=_timeout_value(timeout),
                )
            status_code = int(getattr(response, "status_code", 0) or 0)
            rate_limited = status_code == 429
            if status_code in {429, 500, 502, 503, 504} and attempt < attempts:
                retry_after = _retry_after_seconds(
                    getattr(response, "headers", {}).get("Retry-After"),
                    cap_seconds=retry_after_cap_seconds,
                )
                delay = retry_after if retry_after is not None else _backoff_seconds(
                    attempt,
                    base_seconds=backoff_base_seconds,
                    jitter_seconds=backoff_jitter_seconds,
                )
                record_connector_health(
                    connector,
                    success=False,
                    latency_seconds=time.perf_counter() - started,
                    error=f"transient HTTP {status_code}",
                    rate_limited=rate_limited,
                    write=True,
                )
                sleep_func(delay)
                continue
            response.raise_for_status()
            data = response.json()
        except requests.RequestException as exc:
            status_code = _request_exception_status_code(exc)
            status_prefix = f"HTTP {status_code}: " if status_code is not None else ""
            detail = _response_error_detail(getattr(exc, "response", None))
            if detail:
                last_error = f"{status_prefix}{type(exc).__name__}: {detail}"
            else:
                last_error = f"{status_prefix}{type(exc).__name__}: official source request failed"
            record_connector_health(
                connector,
                success=False,
                latency_seconds=time.perf_counter() - started,
                error=last_error,
                rate_limited=rate_limited,
                write=True,
            )
            if attempt < attempts:
                sleep_func(
                    _backoff_seconds(
                        attempt,
                        base_seconds=backoff_base_seconds,
                        jitter_seconds=backoff_jitter_seconds,
                    )
                )
                continue
            _record_circuit_failure(
                connector,
                threshold=circuit_failure_threshold,
                cooldown_seconds=circuit_cooldown_seconds,
            )
            raise DataTransportError(last_error) from exc
        except ValueError as exc:
            last_error = "official source returned non-JSON data"
            record_connector_health(
                connector,
                success=False,
                latency_seconds=time.perf_counter() - started,
                error=last_error,
                write=True,
            )
            _record_circuit_failure(
                connector,
                threshold=circuit_failure_threshold,
                cooldown_seconds=circuit_cooldown_seconds,
            )
            raise DataTransportError(last_error) from exc
        _record_circuit_success(connector)
        record_connector_health(
            connector,
            success=True,
            latency_seconds=time.perf_counter() - started,
            rate_limited=rate_limited,
            write=True,
        )
        if not isinstance(data, dict):
            return {"data": data}
        return data

    _record_circuit_failure(
        connector,
        threshold=circuit_failure_threshold,
        cooldown_seconds=circuit_cooldown_seconds,
    )
    raise DataTransportError(last_error)


def _response_text(response: Any) -> str:
    text = getattr(response, "text", None)
    if isinstance(text, str):
        return text
    content = getattr(response, "content", b"")
    if isinstance(content, bytes):
        return content.decode("utf-8", errors="replace")
    return str(content)


def _response_headers(response: Any) -> dict[str, Any]:
    headers = getattr(response, "headers", {}) or {}
    return dict(headers) if isinstance(headers, dict) else {}


def _request_exception_status_code(exc: BaseException) -> int | None:
    response = getattr(exc, "response", None)
    status_code = getattr(response, "status_code", None)
    if status_code is None:
        text = str(exc)
        match = re.search(r"\b([45]\d\d)\b", text)
        if match:
            status_code = match.group(1)
    try:
        return int(status_code) if status_code is not None else None
    except (TypeError, ValueError):
        return None


def _request_text_response(
    method: str,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    session: Any | None = None,
    timeout: int | float | tuple[float, float] = DEFAULT_TIMEOUT_SECONDS,
    connector_name: str | None = None,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    backoff_base_seconds: float = DEFAULT_BACKOFF_BASE_SECONDS,
    backoff_jitter_seconds: float = DEFAULT_BACKOFF_JITTER_SECONDS,
    circuit_failure_threshold: int = DEFAULT_CIRCUIT_FAILURE_THRESHOLD,
    circuit_cooldown_seconds: float = DEFAULT_CIRCUIT_COOLDOWN_SECONDS,
    sleep_func: Callable[[float], None] = time.sleep,
) -> TextFetchResult:
    connector = _connector_key(url, connector_name)
    open_error = _circuit_open_error(connector)
    if open_error is not None:
        record_connector_health(connector, success=False, error=str(open_error), write=True)
        raise open_error

    client = session or requests.Session()
    attempts = max(max_attempts, 1)
    last_error = "official source request failed"
    for attempt in range(1, attempts + 1):
        started = time.perf_counter()
        rate_limited = False
        try:
            if method.upper() != "GET":
                raise OfficialDataError("text response helper supports GET only")
            response = client.get(
                url,
                params=params,
                headers=headers,
                timeout=_timeout_value(timeout),
            )
            status_code = int(getattr(response, "status_code", 0) or 0)
            rate_limited = status_code == 429
            if status_code in {429, 500, 502, 503, 504} and attempt < attempts:
                retry_after = _retry_after_seconds(
                    _response_headers(response).get("Retry-After"),
                    cap_seconds=DEFAULT_RETRY_AFTER_CAP_SECONDS,
                )
                delay = retry_after if retry_after is not None else _backoff_seconds(
                    attempt,
                    base_seconds=backoff_base_seconds,
                    jitter_seconds=backoff_jitter_seconds,
                )
                record_connector_health(
                    connector,
                    success=False,
                    latency_seconds=time.perf_counter() - started,
                    error=f"transient HTTP {status_code}",
                    rate_limited=rate_limited,
                    write=True,
                )
                sleep_func(delay)
                continue
            response.raise_for_status()
            text = _response_text(response)
        except OfficialDataError:
            raise
        except requests.RequestException as exc:
            status_code = _request_exception_status_code(exc)
            status_prefix = f"HTTP {status_code}: " if status_code is not None else ""
            last_error = f"{status_prefix}{type(exc).__name__}: official source request failed"
            record_connector_health(
                connector,
                success=False,
                latency_seconds=time.perf_counter() - started,
                error=last_error,
                rate_limited=rate_limited,
                write=True,
            )
            if attempt < attempts:
                sleep_func(
                    _backoff_seconds(
                        attempt,
                        base_seconds=backoff_base_seconds,
                        jitter_seconds=backoff_jitter_seconds,
                    )
                )
                continue
            _record_circuit_failure(
                connector,
                threshold=circuit_failure_threshold,
                cooldown_seconds=circuit_cooldown_seconds,
            )
            raise DataTransportError(last_error) from exc

        _record_circuit_success(connector)
        record_connector_health(
            connector,
            success=True,
            latency_seconds=time.perf_counter() - started,
            rate_limited=rate_limited,
            write=True,
        )
        return TextFetchResult(
            text=text,
            status_code=getattr(response, "status_code", None),
            headers=_response_headers(response),
        )

    _record_circuit_failure(
        connector,
        threshold=circuit_failure_threshold,
        cooldown_seconds=circuit_cooldown_seconds,
    )
    raise DataTransportError(last_error)


def get_text_response(
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    session: Any | None = None,
    timeout: int | float | tuple[float, float] = DEFAULT_TIMEOUT_SECONDS,
    connector_name: str | None = None,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    backoff_base_seconds: float = DEFAULT_BACKOFF_BASE_SECONDS,
    backoff_jitter_seconds: float = DEFAULT_BACKOFF_JITTER_SECONDS,
    circuit_failure_threshold: int = DEFAULT_CIRCUIT_FAILURE_THRESHOLD,
    circuit_cooldown_seconds: float = DEFAULT_CIRCUIT_COOLDOWN_SECONDS,
    sleep_func: Callable[[float], None] = time.sleep,
) -> TextFetchResult:
    return _request_text_response(
        "GET",
        url,
        params=params,
        headers=headers,
        session=session,
        timeout=timeout,
        connector_name=connector_name,
        max_attempts=max_attempts,
        backoff_base_seconds=backoff_base_seconds,
        backoff_jitter_seconds=backoff_jitter_seconds,
        circuit_failure_threshold=circuit_failure_threshold,
        circuit_cooldown_seconds=circuit_cooldown_seconds,
        sleep_func=sleep_func,
    )


def get_text(
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    session: Any | None = None,
    timeout: int | float | tuple[float, float] = DEFAULT_TIMEOUT_SECONDS,
    connector_name: str | None = None,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    backoff_base_seconds: float = DEFAULT_BACKOFF_BASE_SECONDS,
    backoff_jitter_seconds: float = DEFAULT_BACKOFF_JITTER_SECONDS,
    circuit_failure_threshold: int = DEFAULT_CIRCUIT_FAILURE_THRESHOLD,
    circuit_cooldown_seconds: float = DEFAULT_CIRCUIT_COOLDOWN_SECONDS,
    sleep_func: Callable[[float], None] = time.sleep,
) -> str:
    return get_text_response(
        url,
        params=params,
        headers=headers,
        session=session,
        timeout=timeout,
        connector_name=connector_name,
        max_attempts=max_attempts,
        backoff_base_seconds=backoff_base_seconds,
        backoff_jitter_seconds=backoff_jitter_seconds,
        circuit_failure_threshold=circuit_failure_threshold,
        circuit_cooldown_seconds=circuit_cooldown_seconds,
        sleep_func=sleep_func,
    ).text


def env_value(name: str, explicit: str | None = None, *, required: bool = False) -> str | None:
    raw = explicit if explicit is not None else os.getenv(name)
    value = raw.strip() if raw is not None else ""
    if value:
        return value
    if required:
        raise VendorNotConfiguredError(f"{name} is missing")
    return None


def safe_source_ref(url: str, params: dict[str, Any] | None = None) -> str:
    """Build a source reference without any credential-bearing parameters."""

    parts = urlsplit(url)
    safe_params: dict[str, Any] = {}
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        if key.lower() not in SECRET_PARAM_NAMES and value not in (None, ""):
            safe_params[key] = value
    for key, value in (params or {}).items():
        if key.lower() in SECRET_PARAM_NAMES or value in (None, ""):
            continue
        safe_params[key] = value
    query = urlencode(safe_params, doseq=True)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, ""))


def request_hash(method: str, url: str, params: dict[str, Any] | None, body: dict[str, Any] | None) -> str:
    safe_request = {
        "method": method.upper(),
        "url": safe_source_ref(url, params),
        "params": {
            key: value
            for key, value in (params or {}).items()
            if key.lower() not in SECRET_PARAM_NAMES
        },
        "json": {
            key: value
            for key, value in (body or {}).items()
            if key.lower() not in SECRET_PARAM_NAMES
        },
    }
    encoded = json.dumps(safe_request, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def redact_payload(value: Any) -> Any:
    """Remove obvious credential echoes from API responses before packet writing."""

    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            if key.lower() in SECRET_PARAM_NAMES:
                redacted[key] = "[redacted]"
            else:
                redacted[key] = redact_payload(item)
        return redacted
    if isinstance(value, list):
        return [redact_payload(item) for item in value]
    return value


def validate_official_path(value: str, *, allowed_prefixes: tuple[str, ...]) -> str:
    clean = value.strip().strip("/")
    if (
        not clean
        or ".." in clean
        or "\\" in clean
        or "://" in clean
        or "?" in clean
        or "#" in clean
        or not re.fullmatch(r"[A-Za-z0-9_./-]+", clean)
    ):
        raise OfficialDataError("official source path is not a safe relative API path")
    normalized_prefixes = tuple(prefix.strip("/").lower() for prefix in allowed_prefixes)
    if normalized_prefixes and not any(
        clean.lower() == prefix or clean.lower().startswith(f"{prefix}/")
        for prefix in normalized_prefixes
    ):
        raise OfficialDataError("official source path is not in the allowed endpoint families")
    return clean


def extract_payload_timestamp(payload: dict[str, Any], candidate_keys: tuple[str, ...]) -> str | None:
    lowered_keys = {key.lower() for key in candidate_keys}
    stack: list[Any] = [payload]
    while stack:
        current = stack.pop()
        if isinstance(current, dict):
            for key, value in current.items():
                if key.lower() in lowered_keys and isinstance(value, str) and value.strip():
                    return value.strip()
                if isinstance(value, (dict, list)):
                    stack.append(value)
        elif isinstance(current, list):
            stack.extend(current[:50])
    return None


def get_json(
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    session: Any | None = None,
    timeout: int | float | tuple[float, float] = DEFAULT_TIMEOUT_SECONDS,
    connector_name: str | None = None,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    backoff_base_seconds: float = DEFAULT_BACKOFF_BASE_SECONDS,
    backoff_jitter_seconds: float = DEFAULT_BACKOFF_JITTER_SECONDS,
    circuit_failure_threshold: int = DEFAULT_CIRCUIT_FAILURE_THRESHOLD,
    circuit_cooldown_seconds: float = DEFAULT_CIRCUIT_COOLDOWN_SECONDS,
    sleep_func: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    return _request_json(
        "GET",
        url,
        params=params,
        headers=headers,
        session=session,
        timeout=timeout,
        connector_name=connector_name,
        max_attempts=max_attempts,
        backoff_base_seconds=backoff_base_seconds,
        backoff_jitter_seconds=backoff_jitter_seconds,
        circuit_failure_threshold=circuit_failure_threshold,
        circuit_cooldown_seconds=circuit_cooldown_seconds,
        sleep_func=sleep_func,
    )


def post_json(
    url: str,
    *,
    body: dict[str, Any],
    headers: dict[str, str] | None = None,
    session: Any | None = None,
    timeout: int | float | tuple[float, float] = DEFAULT_TIMEOUT_SECONDS,
    connector_name: str | None = None,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    backoff_base_seconds: float = DEFAULT_BACKOFF_BASE_SECONDS,
    backoff_jitter_seconds: float = DEFAULT_BACKOFF_JITTER_SECONDS,
    circuit_failure_threshold: int = DEFAULT_CIRCUIT_FAILURE_THRESHOLD,
    circuit_cooldown_seconds: float = DEFAULT_CIRCUIT_COOLDOWN_SECONDS,
    sleep_func: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    return _request_json(
        "POST",
        url,
        body=body,
        headers=headers,
        session=session,
        timeout=timeout,
        connector_name=connector_name,
        max_attempts=max_attempts,
        backoff_base_seconds=backoff_base_seconds,
        backoff_jitter_seconds=backoff_jitter_seconds,
        circuit_failure_threshold=circuit_failure_threshold,
        circuit_cooldown_seconds=circuit_cooldown_seconds,
        sleep_func=sleep_func,
    )


def evidence_packet(
    *,
    source_name: str,
    evidence_type: str,
    subject: str,
    source_ref: str,
    payload: dict[str, Any],
    quality: str = "high",
    tool_route: str = "official_data",
    symbol: str | None = None,
    as_of: str | None = None,
    request_fingerprint: str | None = None,
    stale: bool = False,
    redaction_status: str = "redacted",
    freshness_extra: dict[str, Any] | None = None,
) -> SourceEvidencePacket:
    timestamp = as_of or now_iso()
    freshness = {"as_of": timestamp, "stale": stale}
    freshness.update(freshness_extra or {})
    return SourceEvidencePacket(
        source_name=source_name,
        evidence_type=evidence_type,
        subject=subject,
        symbol=symbol,
        as_of=timestamp,
        sources=[
            SourceProvenance(
                source=source_name,
                as_of=timestamp,
                path=source_ref,
                quality=quality,  # type: ignore[arg-type]
            )
        ],
        source_refs=[source_ref],
        input_hashes={"request": request_fingerprint} if request_fingerprint else {},
        freshness=freshness,
        payload=redact_payload(payload),
        quality=quality,  # type: ignore[arg-type]
        tool_route=tool_route,
        redaction_status=redaction_status,  # type: ignore[arg-type]
    )


def blocked_evidence_packet(
    *,
    source_name: str,
    evidence_type: str,
    subject: str,
    reason: str,
    symbol: str | None = None,
    source_ref: str | None = None,
) -> SourceEvidencePacket:
    ref = source_ref or f"blocked://{source_name}/{evidence_type}"
    return evidence_packet(
        source_name=source_name,
        evidence_type=evidence_type,
        subject=subject,
        symbol=symbol,
        source_ref=ref,
        payload={"status": "blocked", "reason": _sanitize_reason(reason)},
        quality="unknown",
        stale=True,
        redaction_status="blocked",
        freshness_extra={"blocked": True, "reason": _sanitize_reason(reason)},
    )


def safe_fetch_evidence(
    fetcher,
    *,
    source_name: str,
    evidence_type: str,
    subject: str,
    symbol: str | None = None,
    source_ref: str | None = None,
) -> SourceEvidencePacket:
    try:
        return fetcher()
    except RecoverableDataflowError as exc:
        reason = _sanitize_reason(str(exc))
    return blocked_evidence_packet(
        source_name=source_name,
        evidence_type=evidence_type,
        subject=subject,
        symbol=symbol,
        source_ref=source_ref,
        reason=reason,
    )


def official_cache_key(*parts: Any) -> str:
    encoded = json.dumps([str(part) for part in parts], sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _cache_path(cache_dir: str | Path, cache_key: str) -> Path:
    safe_key = re.sub(r"[^a-fA-F0-9]", "", cache_key)[:64]
    if not safe_key:
        safe_key = official_cache_key(cache_key)
    return Path(cache_dir) / f"{safe_key}.json"


def _cache_age_seconds(path: Path, *, now: datetime.datetime | None = None) -> float:
    return max(_as_utc(now).timestamp() - path.stat().st_mtime, 0.0)


def _load_cached_packet(path: Path) -> SourceEvidencePacket | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return SourceEvidencePacket.model_validate(payload)
    except (OSError, json.JSONDecodeError, ValueError):
        return None


def _with_cache_state(
    packet: SourceEvidencePacket,
    *,
    state: str,
    age_seconds: float | None,
    ttl_seconds: int,
    reason: str | None = None,
) -> SourceEvidencePacket:
    payload = packet.model_dump()
    freshness = dict(payload.get("freshness") or {})
    cache_state = {
        "state": state,
        "ttl_seconds": ttl_seconds,
        "age_seconds": round(age_seconds, 3) if age_seconds is not None else None,
    }
    if reason:
        cache_state["reason"] = _sanitize_reason(reason)
    freshness["cache"] = cache_state
    if state == "stale_fallback":
        freshness["stale"] = True
    payload["freshness"] = freshness
    return SourceEvidencePacket.model_validate(payload)


def write_official_evidence_cache(
    packet: SourceEvidencePacket,
    *,
    cache_key: str,
    cache_dir: str | Path = "results/official_data_cache",
) -> Path:
    path = _cache_path(cache_dir, cache_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(packet.model_dump_json(indent=2), encoding="utf-8")
    return path


def cached_safe_fetch_evidence(
    fetcher,
    *,
    cache_key: str,
    ttl_seconds: int,
    source_name: str,
    evidence_type: str,
    subject: str,
    symbol: str | None = None,
    source_ref: str | None = None,
    cache_dir: str | Path = "results/official_data_cache",
    now: datetime.datetime | None = None,
    allow_stale_on_error: bool = True,
    cached_packet_validator: Callable[[SourceEvidencePacket], bool] | None = None,
) -> SourceEvidencePacket:
    path = _cache_path(cache_dir, cache_key)
    cached = _load_cached_packet(path)
    cached_is_usable = cached is not None and (
        cached_packet_validator is None or cached_packet_validator(cached)
    )
    if cached is not None and path.exists():
        age_seconds = _cache_age_seconds(path, now=now)
        if age_seconds <= ttl_seconds and cached_is_usable:
            record_connector_health(
                source_name,
                success=True,
                latency_seconds=0.0,
                cache_hit=True,
                write=True,
            )
            return _with_cache_state(
                cached,
                state="hit",
                age_seconds=age_seconds,
                ttl_seconds=ttl_seconds,
            )

    try:
        packet = fetcher()
    except RecoverableDataflowError as exc:
        reason = _sanitize_reason(str(exc))
    else:
        write_official_evidence_cache(packet, cache_key=cache_key, cache_dir=cache_dir)
        record_connector_health(
            source_name,
            success=True,
            latency_seconds=0.0,
            write=True,
        )
        return _with_cache_state(
            packet,
            state="refreshed",
            age_seconds=0.0,
            ttl_seconds=ttl_seconds,
        )

    if allow_stale_on_error and cached_is_usable and cached is not None and path.exists():
        record_connector_health(
            source_name,
            success=False,
            latency_seconds=0.0,
            error=reason,
            fallback=True,
            write=True,
        )
        return _with_cache_state(
            cached,
            state="stale_fallback",
            age_seconds=_cache_age_seconds(path, now=now),
            ttl_seconds=ttl_seconds,
            reason=reason,
        )

    record_connector_health(
        source_name,
        success=False,
        latency_seconds=0.0,
        error=reason,
        write=True,
    )
    return blocked_evidence_packet(
        source_name=source_name,
        evidence_type=evidence_type,
        subject=subject,
        symbol=symbol,
        source_ref=source_ref,
        reason=reason,
    )
