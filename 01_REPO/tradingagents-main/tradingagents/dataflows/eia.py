"""EIA Open Data evidence adapter."""

from __future__ import annotations

from ._official_common import (
    env_value,
    evidence_packet,
    extract_payload_timestamp,
    get_json,
    request_hash,
    safe_source_ref,
    validate_official_path,
)

EIA_BASE_URL = "https://api.eia.gov/v2"
EIA_ALLOWED_ROUTE_PREFIXES = (
    "electricity",
    "petroleum",
    "natural-gas",
    "coal",
    "steo",
    "aeo",
    "international",
    "finance",
    "seds",
)


def fetch_eia_route(
    route: str,
    *,
    api_key: str | None = None,
    session=None,
    as_of: str | None = None,
    **params,
):
    resolved_key = env_value("EIA_API_KEY", api_key, required=True)
    clean_route = validate_official_path(route, allowed_prefixes=EIA_ALLOWED_ROUTE_PREFIXES)
    url = f"{EIA_BASE_URL}/{clean_route}"
    request_params = {**params, "api_key": resolved_key}
    data = get_json(url, params=request_params, session=session)
    observed_as_of = as_of or extract_payload_timestamp(data, ("period", "last_updated", "updated"))
    source_ref = safe_source_ref(url, request_params)
    return evidence_packet(
        source_name="eia",
        evidence_type="route",
        subject=f"EIA route {clean_route}",
        source_ref=source_ref,
        payload=data,
        as_of=observed_as_of,
        request_fingerprint=request_hash("GET", url, request_params, None),
    )
