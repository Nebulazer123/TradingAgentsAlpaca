"""BEA Data API evidence adapter."""

from __future__ import annotations

from ._official_common import (
    env_value,
    evidence_packet,
    extract_payload_timestamp,
    get_json,
    request_hash,
    safe_source_ref,
)

BEA_DATA_URL = "https://apps.bea.gov/api/data/"


def fetch_bea_data(
    dataset_name: str,
    *,
    api_key: str | None = None,
    session=None,
    as_of: str | None = None,
    **params,
):
    resolved_key = env_value("BEA_API_KEY", api_key, required=True)
    request_params = {
        "UserID": resolved_key,
        "method": "GetData",
        "datasetname": dataset_name,
        "ResultFormat": "JSON",
        **params,
    }
    data = get_json(BEA_DATA_URL, params=request_params, session=session)
    observed_as_of = as_of or extract_payload_timestamp(data, ("TimePeriod", "Year", "LastUpdated"))
    source_ref = safe_source_ref(BEA_DATA_URL, request_params)
    return evidence_packet(
        source_name="bea",
        evidence_type="get_data",
        subject=f"BEA {dataset_name} data",
        source_ref=source_ref,
        payload=data,
        as_of=observed_as_of,
        request_fingerprint=request_hash("GET", BEA_DATA_URL, request_params, None),
    )
