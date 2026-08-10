"""BLS Public Data API evidence adapter."""

from __future__ import annotations

from ._official_common import (
    env_value,
    evidence_packet,
    extract_payload_timestamp,
    post_json,
    request_hash,
    safe_source_ref,
)

BLS_TIMESERIES_URL = "https://api.bls.gov/publicAPI/v2/timeseries/data/"


def fetch_bls_timeseries(
    series_ids: list[str],
    start_year: str | int,
    end_year: str | int,
    *,
    api_key: str | None = None,
    session=None,
    as_of: str | None = None,
):
    resolved_key = env_value("BLS_API_KEY", api_key, required=False)
    body = {
        "seriesid": series_ids,
        "startyear": str(start_year),
        "endyear": str(end_year),
    }
    if resolved_key:
        body["registrationkey"] = resolved_key
    data = post_json(BLS_TIMESERIES_URL, body=body, session=session)
    observed_as_of = as_of or extract_payload_timestamp(data, ("latest", "year", "period"))
    source_ref = safe_source_ref(
        BLS_TIMESERIES_URL,
        {
            "seriesid": ",".join(series_ids),
            "startyear": str(start_year),
            "endyear": str(end_year),
        },
    )
    return evidence_packet(
        source_name="bls",
        evidence_type="timeseries",
        subject=f"BLS time series for {', '.join(series_ids)}",
        source_ref=source_ref,
        payload=data,
        as_of=observed_as_of,
        request_fingerprint=request_hash("POST", BLS_TIMESERIES_URL, None, body),
    )
