"""Current OpenFIGI and Nasdaq facts reopened from whole source originals.

These profiles prove returned fields, not a dated identity crosswalk. No ticker
join, issuer relationship, historical interval, or cohort is inferred here.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import re
from pathlib import PurePosixPath

from tradingagents.dataflows.pit.raw_artifacts import RawPointInTimeArtifactArchive
from tradingagents.dataflows.pit.records import PointInTimeDataError
from tradingagents.dataflows.pit.security_master import _canonical, _json, _plain

_AUTHORITY = {"analysis_only": True, "execution_authority": "none", "can_submit_orders": False}
_FIGI = re.compile(r"BBG[A-Z0-9]{9}")
_MAPPING_URI = "https://api.openfigi.com/v3/mapping"
_DIRECTORIES = {
    "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt": (
        "nasdaq_listed", "Symbol|Security Name|Market Category|Test Issue|Financial Status|Round Lot Size|ETF|NextShares"
    ),
    "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt": (
        "other_exchange_listed", "ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue|NASDAQ Symbol"
    ),
}


def _seal(material: dict) -> dict:
    digest = hashlib.sha256(_canonical(material)).hexdigest()
    return {**material, "profile_id": "security-source-profile-" + digest, "profile_sha256": digest}


def _original(archive, identifier: str, *, content_type: str):
    if type(archive) is not RawPointInTimeArtifactArchive:
        raise PointInTimeDataError("source profile requires an exact PIT archive")
    artifact = archive.read_artifact(identifier)
    raw = archive.read_bytes(artifact)
    if artifact.content_type != content_type or len(raw) > 2 * 1024 * 1024:
        raise PointInTimeDataError("source profile original type or byte bound differs")
    return artifact, raw


def _text(value: object, *, optional: bool = False) -> str | None:
    if value is None and optional:
        return None
    if type(value) is not str or not value or len(value) > 4096:
        raise PointInTimeDataError("source metadata string is missing or invalid")
    return value


def build_openfigi_mapping_source_profile(*, archive, request_artifact_id: str, response_artifact_id: str) -> dict:
    """Conservative five-job current US ticker mapping; never choose a first hit."""
    request, request_bytes = _original(archive, request_artifact_id, content_type="application/json")
    response, response_bytes = _original(archive, response_artifact_id, content_type="application/json")
    if request.source_uri != _MAPPING_URI or response.source_uri != _MAPPING_URI:
        raise PointInTimeDataError("OpenFIGI original route differs")
    if (dt.datetime.fromisoformat(request.retrieved_at) > dt.datetime.fromisoformat(response.retrieved_at)
            or dt.datetime.fromisoformat(request.archive_recorded_at) > dt.datetime.fromisoformat(response.archive_recorded_at)):
        raise PointInTimeDataError("OpenFIGI response precedes its outgoing request")
    jobs, replies = _json(request_bytes), _json(response_bytes)
    if type(jobs) is not list or not 1 <= len(jobs) <= 5 or type(replies) is not list or len(replies) != len(jobs):
        raise PointInTimeDataError("OpenFIGI request/response slots are incomplete")
    seen_jobs, results = set(), []
    for job_index, (job, reply) in enumerate(zip(jobs, replies, strict=True)):
        if (type(job) is not dict or set(job) != {"idType", "idValue", "exchCode", "marketSecDes"}
                or job["idType"] != "TICKER" or job["exchCode"] != "US" or job["marketSecDes"] != "Equity"
                or type(job["idValue"]) is not str or re.fullmatch(r"[A-Z][A-Z0-9.-]{0,19}", job["idValue"]) is None
                or job["idValue"] in seen_jobs):
            raise PointInTimeDataError("OpenFIGI original query scope is unsupported")
        seen_jobs.add(job["idValue"])
        if type(reply) is not dict or set(reply) not in ({"data"}, {"error"}, {"warning"}):
            raise PointInTimeDataError("OpenFIGI result envelope is unsupported")
        records = []
        if "data" in reply:
            if type(reply["data"]) is not list or not 1 <= len(reply["data"]) <= 1000:
                raise PointInTimeDataError("OpenFIGI returned records are unbounded or empty")
            seen_figis = set()
            for record_index, row in enumerate(reply["data"]):
                if type(row) is not dict or "metadata" in row:
                    raise PointInTimeDataError("OpenFIGI record metadata is unavailable")
                for name in ("figi", "ticker", "name", "exchCode", "marketSector", "securityType", "securityType2", "securityDescription"):
                    _text(row.get(name), optional=name in {"name", "securityType", "securityType2", "securityDescription"})
                if (row["ticker"] != job["idValue"] or row["exchCode"] != "US" or row["marketSector"] != "Equity"
                        or _FIGI.fullmatch(row["figi"]) is None or row["figi"] in seen_figis):
                    raise PointInTimeDataError("OpenFIGI record identity or query scope differs")
                seen_figis.add(row["figi"])
                for name in ("compositeFIGI", "shareClassFIGI"):
                    value = _text(row.get(name), optional=True)
                    if value is not None and _FIGI.fullmatch(value) is None:
                        raise PointInTimeDataError("OpenFIGI returned identifier is invalid")
                pair = row.get("securityType"), row.get("securityType2")
                # Only these actual, distinct publisher label pairs are qualified.
                # ETP/Mutual Fund is deliberately not translated into ETF or ETN.
                normalized = {("Common Stock", "Common Stock"): "common_stock",
                              ("ADR", "Depositary Receipt"): "adr"}.get(pair, "unknown")
                records.append({"record_index": record_index, "source_path": [job_index, "data", record_index],
                                "source_fields": _plain(row), "normalized_security_type": normalized,
                                "classification_status": "observed_label_pair" if normalized != "unknown" else "unsupported_label_pair",
                                "effective_from": None, "effective_to": None, "coverage_through": None,
                                "internal_security_id": None, "reviewed_crosswalk": False})
        else:
            _text(next(iter(reply.values())))
        results.append({"job_index": job_index, "request": _plain(job), "source_reply": _plain(reply),
                        "records": records, "result_status": "observed_unique_current_mapping" if len(records) == 1 else "ambiguous" if records else "unavailable"})
    return _seal({"schema_version": "openfigi_mapping_source_profile/v1", "parser_version": "openfigi_current_us_ticker/v1",
                  "original_request": request.to_dict(), "original_response": response.to_dict(), "results": results,
                  "dated_identity_coverage": "NOT_ESTABLISHED", "relationship_coverage": "NOT_ESTABLISHED",
                  "historical_custody_asserted": False, "cohort_qualified": False, **_AUTHORITY})


def build_nasdaq_directory_source_profile(*, archive, raw_artifact_id: str) -> dict:
    """Account for every source row and keep the footer clock's zone unknown."""
    artifact, raw = _original(archive, raw_artifact_id, content_type="text/plain")
    if artifact.source_uri not in _DIRECTORIES:
        raise PointInTimeDataError("Nasdaq directory original route differs")
    family, header = _DIRECTORIES[artifact.source_uri]
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise PointInTimeDataError("Nasdaq directory is not UTF-8 text") from exc
    lines = text.splitlines()
    if not 3 <= len(lines) <= 100_002 or lines[0] != header:
        raise PointInTimeDataError("Nasdaq directory header or row bound differs")
    fields, footer = header.split("|"), lines[-1].split("|")
    if not footer[0].startswith("File Creation Time: ") or not 7 <= len(footer) <= 8 or any(footer[1:]):
        raise PointInTimeDataError("Nasdaq directory lacks its complete terminal creation row")
    stamp = footer[0].removeprefix("File Creation Time: ")
    try:
        generated = dt.datetime.strptime(stamp, "%m%d%Y%H:%M")
    except ValueError as exc:
        raise PointInTimeDataError("Nasdaq directory generation clock is invalid") from exc
    if generated.strftime("%m%d%Y%H:%M") != stamp:
        raise PointInTimeDataError("Nasdaq directory generation clock is noncanonical")
    rows, seen = [], set()
    symbol_field = "Symbol" if family == "nasdaq_listed" else "ACT Symbol"
    for index, line in enumerate(lines[1:-1]):
        parts = line.split("|")
        if len(parts) != len(fields) or any(len(part) > 4096 for part in parts):
            raise PointInTimeDataError("Nasdaq directory row width or field bound differs")
        row = dict(zip(fields, parts, strict=True))
        symbol = _text(row[symbol_field])
        _text(row["Security Name"])
        if symbol in seen or row["ETF"] not in {"Y", "N"} or row["Test Issue"] not in {"Y", "N"}:
            raise PointInTimeDataError("Nasdaq directory symbols or explicit flags differ")
        seen.add(symbol)
        if (re.fullmatch(r"[0-9]{1,6}", row["Round Lot Size"]) is None
                or (family == "nasdaq_listed" and (row["Market Category"] not in {"Q", "G", "S"}
                                                   or row["Financial Status"] not in {"D", "E", "Q", "N", "G", "H", "J", "K"}
                                                   or row["NextShares"] not in {"Y", "N"}))):
            raise PointInTimeDataError("Nasdaq directory documented field values differ")
        gaps = (["undocumented_exchange_code"] if family == "other_exchange_listed" and row["Exchange"] not in {"A", "N", "P", "Z", "V"} else [])
        rows.append({"array_index": index, "source_line_number": index + 2, "source_fields": row,
                     "source_symbol": symbol, "source_symbol_namespace": symbol_field,
                     "observed_etf": row["ETF"] == "Y", "observed_test_issue": row["Test Issue"] == "Y",
                     "source_field_gaps": gaps, "internal_security_id": None, "reviewed_crosswalk": False})
    return _seal({"schema_version": "nasdaq_directory_source_profile/v1", "parser_version": "nasdaq_current_directory/v1",
                  "directory_family": family, "original": artifact.to_dict(), "original_filename": PurePosixPath(artifact.source_uri).name,
                  "source_generation_wall_time": generated.isoformat(), "source_generation_timezone": None,
                  "generation_clock_status": "publisher_timezone_not_documented", "rows": rows, "record_count": len(rows),
                  "dated_identity_coverage": "NOT_ESTABLISHED", "relationship_coverage": "NOT_ESTABLISHED",
                  "common_share_class_inferred_from_name": False, "historical_custody_asserted": False,
                  "cohort_qualified": False, **_AUTHORITY})


def verify_security_source_profile(value: object, *, archive) -> dict:
    if type(value) is not dict:
        raise PointInTimeDataError("security source profile must be an object")
    try:
        if value.get("schema_version") == "openfigi_mapping_source_profile/v1":
            rebuilt = build_openfigi_mapping_source_profile(archive=archive,
                request_artifact_id=value["original_request"]["raw_artifact_id"], response_artifact_id=value["original_response"]["raw_artifact_id"])
        elif value.get("schema_version") == "nasdaq_directory_source_profile/v1":
            rebuilt = build_nasdaq_directory_source_profile(archive=archive, raw_artifact_id=value["original"]["raw_artifact_id"])
        else:
            raise PointInTimeDataError("security source profile schema is unsupported")
        if _canonical(rebuilt) != _canonical(value):
            raise PointInTimeDataError("security source profile does not replay from originals")
    except (KeyError, TypeError) as exc:
        raise PointInTimeDataError("security source profile bindings are invalid") from exc
    return rebuilt
