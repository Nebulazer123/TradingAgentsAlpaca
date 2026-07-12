"""Treasury FiscalData evidence adapter."""

from __future__ import annotations

from ._official_common import (
    evidence_packet,
    extract_payload_timestamp,
    get_json,
    request_hash,
    safe_source_ref,
    validate_official_path,
)

TREASURY_FISCAL_BASE_URL = "https://api.fiscaldata.treasury.gov/services/api/fiscal_service"
TREASURY_FISCAL_ALLOWED_PATH_PREFIXES = (
    "v1/accounting",
    "v2/accounting",
    "v1/debt",
    "v2/debt",
    "v1/revenue",
    "v2/revenue",
    "v1/treasury",
    "v2/treasury",
)


def fetch_treasury_fiscal(
    path: str,
    *,
    session=None,
    as_of: str | None = None,
    **params,
):
    clean_path = validate_official_path(
        path,
        allowed_prefixes=TREASURY_FISCAL_ALLOWED_PATH_PREFIXES,
    )
    url = f"{TREASURY_FISCAL_BASE_URL}/{clean_path}"
    data = get_json(url, params=params, session=session)
    observed_as_of = as_of or extract_payload_timestamp(data, ("record_date", "last_updated"))
    source_ref = safe_source_ref(url, params)
    return evidence_packet(
        source_name="treasury_fiscal",
        evidence_type="fiscal_service",
        subject=f"Treasury FiscalData {clean_path}",
        source_ref=source_ref,
        payload=data,
        as_of=observed_as_of,
        request_fingerprint=request_hash("GET", url, params, None),
    )
