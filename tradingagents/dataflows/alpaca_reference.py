"""Allowlisted read-only access to Alpaca's documented API surface.

The catalog records mutation endpoints for operator reference, but this module
can issue only GET requests. It cannot accept arbitrary URLs or HTTP methods.
"""

from __future__ import annotations

import datetime
import json
import os
import re
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote

import requests

from tradingagents.dataflows._official_common import (
    OfficialDataError,
    evidence_packet,
    extract_payload_timestamp,
    get_json,
    redact_payload,
    request_hash,
    safe_source_ref,
)
from tradingagents.schemas.research import SourceEvidencePacket

UTC = datetime.timezone.utc
ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CATALOG_PATH = ROOT / "config" / "alpaca_api_reference_catalog.json"
DEFAULT_TIMEOUT_SECONDS = 15
DEFAULT_STREAM_MAX_EVENTS = 25
PATH_PARAMETER = re.compile(r"\{([^{}]+)\}")
ALLOWED_HOSTS = {
    "authentication": "https://api.alpaca.markets",
    "market_data": "https://data.alpaca.markets",
    "trading": "https://paper-api.alpaca.markets",
}
DOCUMENTED_METHODS = {"GET", "POST", "PATCH", "PUT", "DELETE"}


class AlpacaReferenceError(OfficialDataError):
    """Raised before any unsafe or non-cataloged reference request is sent."""


def load_alpaca_reference_catalog(
    path: Path | str = DEFAULT_CATALOG_PATH,
) -> dict[str, Any]:
    catalog = json.loads(Path(path).read_text(encoding="utf-8"))
    endpoints = catalog.get("endpoints")
    if catalog.get("schema_version") != "alpaca_api_reference_catalog_v1":
        raise AlpacaReferenceError("Unsupported Alpaca reference catalog schema")
    if not isinstance(endpoints, list):
        raise AlpacaReferenceError("Alpaca reference catalog endpoints are missing")
    route_ids = [str(endpoint.get("id") or "") for endpoint in endpoints]
    if not all(route_ids) or len(route_ids) != len(set(route_ids)):
        raise AlpacaReferenceError("Alpaca reference catalog route IDs are invalid")
    for endpoint in endpoints:
        api = str(endpoint.get("api") or "")
        host = str(endpoint.get("host") or "").rstrip("/")
        method = str(endpoint.get("method") or "").upper()
        route_path = str(endpoint.get("path") or "")
        if host != ALLOWED_HOSTS.get(api):
            raise AlpacaReferenceError(
                f"Alpaca reference catalog host is not allowlisted for {api or 'unknown API'}"
            )
        if method not in DOCUMENTED_METHODS:
            raise AlpacaReferenceError("Alpaca reference catalog method is unsupported")
        if (
            not route_path.startswith("/")
            or "://" in route_path
            or "?" in route_path
            or "#" in route_path
            or "\\" in route_path
            or ".." in route_path
        ):
            raise AlpacaReferenceError("Alpaca reference catalog path is unsafe")
    return catalog


def summarize_alpaca_reference_catalog(catalog: Mapping[str, Any] | None = None) -> dict[str, Any]:
    source = dict(catalog or load_alpaca_reference_catalog())
    endpoints = list(source.get("endpoints") or [])
    method_counts: dict[str, int] = {}
    api_counts: dict[str, int] = {}
    runtime_counts: dict[str, int] = {}
    paths: set[tuple[str, str]] = set()
    for endpoint in endpoints:
        method = str(endpoint.get("method") or "UNKNOWN")
        api = str(endpoint.get("api") or "unknown")
        runtime_class = str(endpoint.get("runtime_class") or "unknown")
        method_counts[method] = method_counts.get(method, 0) + 1
        api_counts[api] = api_counts.get(api, 0) + 1
        runtime_counts[runtime_class] = runtime_counts.get(runtime_class, 0) + 1
        paths.add((api, str(endpoint.get("path") or "")))
    return {
        "schema_version": source.get("schema_version"),
        "upstream": source.get("upstream"),
        "path_count": len(paths),
        "operation_count": len(endpoints),
        "method_counts": dict(sorted(method_counts.items())),
        "api_counts": dict(sorted(api_counts.items())),
        "runtime_counts": dict(sorted(runtime_counts.items())),
        "callable_operation_count": method_counts.get("GET", 0),
        "documented_non_get_count": len(endpoints) - method_counts.get("GET", 0),
        "analysis_only": True,
        "execution_authority": "none",
    }


def build_alpaca_reference_audit(
    catalog: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a complete local catalog audit without contacting trading endpoints."""

    source = dict(catalog or load_alpaca_reference_catalog())
    summary = summarize_alpaca_reference_catalog(source)
    endpoint_statuses = {
        str(endpoint["id"]): {
            "api": endpoint["api"],
            "method": endpoint["method"],
            "path": endpoint["path"],
            "runtime_class": endpoint["runtime_class"],
            "report_visibility": endpoint["report_visibility"],
            "callable": endpoint["method"] == "GET"
            and endpoint["runtime_class"] not in {"documented_mutation", "auth_only"},
        }
        for endpoint in source["endpoints"]
    }
    return {
        "schema": "alpaca_reference_audit_v1",
        "generated_at": datetime.datetime.now(tz=UTC).isoformat(timespec="seconds"),
        "analysis_only": True,
        "can_submit_orders": False,
        "execution_authority": "none",
        "status": "catalog_current",
        "material": False,
        "material_summary": None,
        **summary,
        "documentation_tools": source.get("documentation_tools", []),
        "route_statuses": endpoint_statuses,
        "forbidden_effects": source["policy"]["forbidden_effects"],
    }


def _route(catalog: Mapping[str, Any], route_id: str) -> dict[str, Any]:
    for endpoint in catalog.get("endpoints") or []:
        if endpoint.get("id") == route_id:
            return dict(endpoint)
    raise AlpacaReferenceError(f"Unknown Alpaca reference route: {route_id}")


def _headers(
    *,
    api_key: str | None,
    secret_key: str | None,
    environ: Mapping[str, str] | None,
) -> dict[str, str]:
    env = os.environ if environ is None else environ
    key = (api_key or env.get("ALPACA_PAPER_API_KEY") or "").strip()
    secret = (secret_key or env.get("ALPACA_PAPER_SECRET_KEY") or "").strip()
    if not key or not secret:
        raise AlpacaReferenceError("Alpaca paper credentials are missing")
    return {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}


def _request_parts(
    route: Mapping[str, Any], params: Mapping[str, Any] | None
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    supplied = dict(params or {})
    path_params: dict[str, Any] = {}
    path = str(route["path"])
    for name in PATH_PARAMETER.findall(path):
        value = supplied.pop(name, None)
        if value is None or str(value).strip() == "":
            raise AlpacaReferenceError(f"Missing path parameter {name!r} for {route['id']}")
        clean = str(value).strip()
        if "/" in clean or ".." in clean:
            raise AlpacaReferenceError(f"Unsafe path parameter {name!r}")
        path_params[name] = clean
        path = path.replace("{" + name + "}", quote(clean, safe=""))
    query = {key: value for key, value in supplied.items() if value is not None}
    return f"{str(route['host']).rstrip('/')}{path}", query, path_params


def _semantic_caveats(route: Mapping[str, Any]) -> list[str]:
    caveats: list[str] = []
    if str(route.get("path")).endswith("/trades/latest"):
        caveats.append(
            "Latest-trade results exclude trade conditions that do not update bar price and are not a complete tape."
        )
    if route.get("id") in {"trading.get.v2_calendar", "trading.get.v3_calendar_market"}:
        caveats.append(
            "Calendar responses may include session and settlement fields; preserve the selected date_type and as-of time."
        )
    return caveats


def fetch_alpaca_reference(
    route_id: str,
    params: Mapping[str, Any] | None = None,
    *,
    mode: Literal["on_demand", "scheduled"] = "on_demand",
    include_account_admin: bool = False,
    catalog_path: Path | str = DEFAULT_CATALOG_PATH,
    api_key: str | None = None,
    secret_key: str | None = None,
    environ: Mapping[str, str] | None = None,
    session: Any | None = None,
    timeout: int | float = DEFAULT_TIMEOUT_SECONDS,
) -> SourceEvidencePacket:
    """Fetch one cataloged GET route and return an analysis-only evidence packet."""

    catalog = load_alpaca_reference_catalog(catalog_path)
    route = _route(catalog, route_id)
    if route.get("method") != "GET" or route.get("runtime_class") in {
        "documented_mutation",
        "auth_only",
    }:
        raise AlpacaReferenceError(f"Alpaca reference route {route_id} is not callable")
    if route.get("runtime_class") == "bounded_stream":
        raise AlpacaReferenceError(f"Alpaca stream route {route_id} requires collect_alpaca_reference_stream")
    if mode == "scheduled" and route.get("runtime_class") != "scheduled_core":
        raise AlpacaReferenceError(f"Alpaca reference route {route_id} is not approved for scheduled collection")
    if route.get("access_scope") == "account_admin" and not include_account_admin:
        raise AlpacaReferenceError(f"Alpaca reference route {route_id} requires include_account_admin=True")

    url, query, path_params = _request_parts(route, params)
    headers = _headers(api_key=api_key, secret_key=secret_key, environ=environ)
    payload = get_json(
        url,
        params=query,
        headers=headers,
        session=session,
        timeout=timeout,
        connector_name="alpaca_reference",
    )
    as_of = extract_payload_timestamp(payload, ("timestamp", "t", "as_of", "date"))
    request_context = {
        "route_id": route_id,
        "api": route["api"],
        "method": "GET",
        "path_parameters": path_params,
        "query_parameters": query,
        "feed": query.get("feed"),
        "date_type": query.get("date_type"),
        "runtime_class": route["runtime_class"],
    }
    return evidence_packet(
        source_name="alpaca_api_reference",
        evidence_type="alpaca_reference_read",
        subject=route_id,
        source_ref=safe_source_ref(url, query),
        payload={
            "request_context": request_context,
            "semantic_caveats": _semantic_caveats(route),
            "data": payload,
        },
        quality="high",
        as_of=as_of,
        request_fingerprint=request_hash("GET", url, query, None),
        tool_route="alpaca_reference_read_only",
        redaction_status="redacted",
        freshness_extra={
            "read_only": True,
            "execution_authority": "none",
            "route_id": route_id,
            "feed": query.get("feed"),
            "forbidden_effects": list(catalog["policy"]["forbidden_effects"]),
        },
    )


def collect_alpaca_reference_stream(
    route_id: str,
    params: Mapping[str, Any] | None = None,
    *,
    enabled: bool = False,
    max_events: int = DEFAULT_STREAM_MAX_EVENTS,
    timeout_seconds: int | float = DEFAULT_TIMEOUT_SECONDS,
    catalog_path: Path | str = DEFAULT_CATALOG_PATH,
    api_key: str | None = None,
    secret_key: str | None = None,
    environ: Mapping[str, str] | None = None,
    session: Any | None = None,
) -> SourceEvidencePacket:
    """Collect a bounded number of events from one of two allowlisted SSE GET routes."""

    if not enabled:
        raise AlpacaReferenceError("Alpaca reference streams are disabled by default")
    if max_events < 1 or max_events > 100:
        raise AlpacaReferenceError("max_events must be between 1 and 100")
    if timeout_seconds <= 0 or timeout_seconds > 60:
        raise AlpacaReferenceError("timeout_seconds must be between 0 and 60")
    catalog = load_alpaca_reference_catalog(catalog_path)
    route = _route(catalog, route_id)
    if route.get("method") != "GET" or route.get("runtime_class") != "bounded_stream":
        raise AlpacaReferenceError(f"Alpaca reference route {route_id} is not an allowlisted stream")
    url, query, _ = _request_parts(route, params)
    headers = _headers(api_key=api_key, secret_key=secret_key, environ=environ)
    client = session or requests
    started = time.monotonic()
    response = client.get(url, params=query, headers=headers, timeout=timeout_seconds, stream=True)
    response.raise_for_status()
    events: list[Any] = []
    try:
        for raw_line in response.iter_lines(decode_unicode=True):
            if time.monotonic() - started >= timeout_seconds or len(events) >= max_events:
                break
            if not raw_line:
                continue
            line = raw_line.decode("utf-8", errors="replace") if isinstance(raw_line, bytes) else str(raw_line)
            if line.startswith("data:"):
                line = line[5:].strip()
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                events.append({"event": line})
    finally:
        response.close()
    elapsed = time.monotonic() - started
    now = datetime.datetime.now(tz=UTC).isoformat(timespec="seconds")
    return evidence_packet(
        source_name="alpaca_api_reference",
        evidence_type="alpaca_reference_stream",
        subject=route_id,
        source_ref=safe_source_ref(url, query),
        payload={"events": redact_payload(events), "event_count": len(events)},
        quality="high",
        as_of=now,
        request_fingerprint=request_hash("GET", url, query, None),
        tool_route="alpaca_reference_bounded_stream",
        redaction_status="redacted",
        freshness_extra={
            "read_only": True,
            "execution_authority": "none",
            "bounded_stream": True,
            "max_events": max_events,
            "elapsed_seconds": round(elapsed, 3),
            "forbidden_effects": list(catalog["policy"]["forbidden_effects"]),
        },
    )


def collect_alpaca_reference_bundle(
    *,
    families: Sequence[str],
    route_params: Mapping[str, Mapping[str, Any]],
    symbols: Sequence[str] = (),
    start: str | None = None,
    end: str | None = None,
    include_account_admin: bool = False,
    include_streams: bool = False,
    catalog_path: Path | str = DEFAULT_CATALOG_PATH,
    api_key: str | None = None,
    secret_key: str | None = None,
    environ: Mapping[str, str] | None = None,
    session: Any | None = None,
) -> list[SourceEvidencePacket]:
    """Collect only explicitly supplied scheduled routes, plus opt-in bounded streams."""

    del symbols, start, end  # Reserved for higher-level route planners; never infer broad polling.
    catalog = load_alpaca_reference_catalog(catalog_path)
    allowed_families = {str(family) for family in families}
    packets: list[SourceEvidencePacket] = []
    for route_id in sorted(route_params):
        route = _route(catalog, route_id)
        if route.get("api") not in allowed_families:
            continue
        if route.get("access_scope") == "account_admin" and not include_account_admin:
            continue
        if route.get("runtime_class") == "bounded_stream":
            if include_streams:
                packets.append(
                    collect_alpaca_reference_stream(
                        route_id,
                        route_params[route_id],
                        enabled=True,
                        catalog_path=catalog_path,
                        api_key=api_key,
                        secret_key=secret_key,
                        environ=environ,
                        session=session,
                    )
                )
            continue
        if route.get("runtime_class") != "scheduled_core":
            continue
        packets.append(
            fetch_alpaca_reference(
                route_id,
                route_params[route_id],
                mode="scheduled",
                include_account_admin=include_account_admin,
                catalog_path=catalog_path,
                api_key=api_key,
                secret_key=secret_key,
                environ=environ,
                session=session,
            )
        )
    return packets
