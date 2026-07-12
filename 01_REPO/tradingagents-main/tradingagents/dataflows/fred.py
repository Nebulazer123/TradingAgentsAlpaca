"""FRED evidence adapter."""

from __future__ import annotations

from ._official_common import (
    env_value,
    evidence_packet,
    extract_payload_timestamp,
    get_json,
    request_hash,
    safe_source_ref,
)

FRED_SERIES_OBSERVATIONS_URL = "https://api.stlouisfed.org/fred/series/observations"


def fetch_fred_series_observations(
    series_id: str,
    *,
    api_key: str | None = None,
    session=None,
    as_of: str | None = None,
    **params,
):
    resolved_key = env_value("FRED_API_KEY", api_key, required=True)
    request_params = {
        "series_id": series_id,
        "file_type": "json",
        **params,
        "api_key": resolved_key,
    }
    data = get_json(FRED_SERIES_OBSERVATIONS_URL, params=request_params, session=session)
    observed_as_of = as_of or extract_payload_timestamp(data, ("realtime_end", "date"))
    source_ref = safe_source_ref(FRED_SERIES_OBSERVATIONS_URL, request_params)
    return evidence_packet(
        source_name="fred",
        evidence_type="series_observations",
        subject=f"FRED observations for {series_id}",
        source_ref=source_ref,
        payload=data,
        as_of=observed_as_of,
        request_fingerprint=request_hash(
            "GET",
            FRED_SERIES_OBSERVATIONS_URL,
            request_params,
            None,
        ),
    )
