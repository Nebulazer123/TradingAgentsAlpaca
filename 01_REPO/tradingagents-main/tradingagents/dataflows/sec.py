"""SEC EDGAR evidence adapters."""

from __future__ import annotations

from ._official_common import (
    env_value,
    evidence_packet,
    extract_payload_timestamp,
    get_json,
    request_hash,
    safe_source_ref,
)

SEC_COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
SEC_COMPANY_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"


def normalize_cik(cik: str | int) -> str:
    digits = "".join(char for char in str(cik) if char.isdigit())
    if not digits:
        raise ValueError("CIK must contain digits")
    return digits.zfill(10)


def fetch_sec_companyfacts(
    cik: str | int,
    *,
    symbol: str | None = None,
    user_agent: str | None = None,
    session=None,
    as_of: str | None = None,
):
    normalized_cik = normalize_cik(cik)
    resolved_user_agent = env_value("SEC_USER_AGENT", user_agent, required=True)
    url = SEC_COMPANYFACTS_URL.format(cik=normalized_cik)
    data = get_json(url, headers={"User-Agent": resolved_user_agent or ""}, session=session)
    observed_as_of = as_of or extract_payload_timestamp(data, ("filed", "accepted", "end"))
    source_ref = safe_source_ref(url)
    return evidence_packet(
        source_name="sec_edgar",
        evidence_type="companyfacts",
        subject=f"SEC company facts for CIK {normalized_cik}",
        symbol=symbol,
        source_ref=source_ref,
        payload=data,
        as_of=observed_as_of,
        request_fingerprint=request_hash("GET", url, None, None),
    )


def fetch_sec_company_tickers(
    *,
    user_agent: str | None = None,
    session=None,
    as_of: str | None = None,
):
    resolved_user_agent = env_value("SEC_USER_AGENT", user_agent, required=True)
    data = get_json(
        SEC_COMPANY_TICKERS_URL,
        headers={"User-Agent": resolved_user_agent or ""},
        session=session,
    )
    observed_as_of = as_of or extract_payload_timestamp(data, ("last_updated", "filed", "accepted"))
    source_ref = safe_source_ref(SEC_COMPANY_TICKERS_URL)
    return evidence_packet(
        source_name="sec_edgar",
        evidence_type="company_tickers",
        subject="SEC company ticker to CIK mapping",
        source_ref=source_ref,
        payload=data,
        as_of=observed_as_of,
        request_fingerprint=request_hash("GET", SEC_COMPANY_TICKERS_URL, None, None),
    )


def fetch_sec_submissions(
    cik: str | int,
    *,
    symbol: str | None = None,
    user_agent: str | None = None,
    session=None,
    as_of: str | None = None,
):
    normalized_cik = normalize_cik(cik)
    resolved_user_agent = env_value("SEC_USER_AGENT", user_agent, required=True)
    url = SEC_SUBMISSIONS_URL.format(cik=normalized_cik)
    data = get_json(url, headers={"User-Agent": resolved_user_agent or ""}, session=session)
    observed_as_of = as_of or extract_payload_timestamp(data, ("filingDate", "acceptanceDateTime", "reportDate"))
    source_ref = safe_source_ref(url)
    return evidence_packet(
        source_name="sec_edgar",
        evidence_type="submissions",
        subject=f"SEC submissions for CIK {normalized_cik}",
        symbol=symbol,
        source_ref=source_ref,
        payload=data,
        as_of=observed_as_of,
        request_fingerprint=request_hash("GET", url, None, None),
    )
