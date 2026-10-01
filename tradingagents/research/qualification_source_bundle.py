"""Authenticate and reconstruct multiple-original, analysis-only source bundles."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import stat
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlsplit

from tradingagents.dataflows.pit.official_observations import _json_mapping, _normalize_source_value
from tradingagents.research.qualification_media import canonical, media_source, validate_media_input
from tradingagents.research.qualification_semantics import BUNDLE_SCHEMA, timestamp

SCHEMA = "research_source_bundle_input/v1"
ARTIFACT_FIELDS = {"artifact_id", "artifact_path", "artifact_sha256", "byte_start", "byte_end"}
WORKFLOW_ORIGINALS = {
    "config/automation_schedule_contract.json", "config/automation_roles.json",
    "tradingagents/evals/automation_health_audit.py", "tests/test_automation_role_contracts.py",
}
_SHA = re.compile(r"[0-9a-f]{64}")
MAX_ARTIFACT_BYTES = 64 * 1024 * 1024
MAX_BUNDLE_BYTES = 128 * 1024 * 1024


class SourceBundleError(ValueError):
    pass


def engine_versions():
    """Bind the actual source-reader and interpreter code, independently of prose."""
    parent = Path(__file__).parent
    return {"qualification_source_bundle": hashlib.sha256((parent / "qualification_source_bundle.py").read_bytes()).hexdigest(),
            "qualification_semantics": hashlib.sha256((parent / "qualification_semantics.py").read_bytes()).hexdigest()}


def _fields(value, fields, label):
    if type(value) is not dict or set(value) != fields:
        raise SourceBundleError(f"{label} fields are not canonical")
    return value


def validate_artifact(value):
    row = _fields(value, ARTIFACT_FIELDS, "source artifact")
    if type(row["artifact_id"]) is not str or not row["artifact_id"].startswith("retained-artifact-") or len(row["artifact_id"]) > 128:
        raise SourceBundleError("source artifact ID is invalid")
    if type(row["artifact_path"]) is not str or not row["artifact_path"] or "\x00" in row["artifact_path"]:
        raise SourceBundleError("source artifact path is invalid")
    path = Path(row["artifact_path"])
    if path.is_absolute() or path.as_posix() != row["artifact_path"] or any(p in {"", ".", ".."} for p in path.parts):
        raise SourceBundleError("source artifact path is not contained")
    if type(row["artifact_sha256"]) is not str or _SHA.fullmatch(row["artifact_sha256"]) is None:
        raise SourceBundleError("source artifact digest is invalid")
    if type(row["byte_start"]) is not int or row["byte_start"] != 0 or type(row["byte_end"]) is not int or not 0 < row["byte_end"] <= MAX_ARTIFACT_BYTES:
        raise SourceBundleError("source artifacts require bounded complete originals")
    return dict(row)


def validate_source_bundle_input(value):
    row = _fields(value, {"schema_version", "sources", "engine_versions", "extraction_sha256"}, "source-bundle input")
    if row["schema_version"] != SCHEMA or type(row["sources"]) is not list or not 1 <= len(row["sources"]) <= 10:
        raise SourceBundleError("source-bundle schema/count is invalid")
    versions = _fields(row["engine_versions"], {"qualification_source_bundle", "qualification_semantics"}, "source-bundle engines")
    if any(type(v) is not str or _SHA.fullmatch(v) is None for v in versions.values()) or type(row["extraction_sha256"]) is not str or _SHA.fullmatch(row["extraction_sha256"]) is None:
        raise SourceBundleError("source-bundle engine/extraction identity is invalid")
    identifiers, artifact_ids, paths = set(), {}, {}
    for source in row["sources"]:
        if type(source) is not dict or type(source.get("source_id")) is not str or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", source["source_id"]) or source["source_id"] in identifiers:
            raise SourceBundleError("source IDs are invalid or duplicated")
        identifiers.add(source["source_id"])
        kind = source.get("kind")
        if kind == "media":
            _fields(source, {"source_id", "kind", "original", "media_input"}, "media source")
            validate_media_input(source["media_input"])
        elif kind == "financial_filing":
            _fields(source, {"source_id", "kind", "original", "media_input", "capture_receipt", "publication_metadata", "publication_capture_receipt", "accession"}, "financial source")
            media = validate_media_input(source["media_input"])
            if media["format"] != "html" or type(source["accession"]) is not str or not re.fullmatch(r"\d{10}-\d{2}-\d{6}", source["accession"]):
                raise SourceBundleError("financial source format/accession is invalid")
        elif kind == "workflow_fixture":
            _fields(source, {"source_id", "kind", "original", "source_originals", "fixture_transform"}, "workflow source")
            _fields(source["source_originals"], WORKFLOW_ORIGINALS, "workflow originals")
            if source["fixture_transform"] != "required_phrases_prompt/v1":
                raise SourceBundleError("workflow fixture transformation is unavailable")
        else:
            raise SourceBundleError("unsupported source-bundle kind")
        for artifact in source_artifacts(source):
            checked = validate_artifact(artifact)
            binding = (checked["artifact_path"], checked["artifact_sha256"], checked["byte_end"])
            previous = artifact_ids.setdefault(checked["artifact_id"], binding)
            previous_path = paths.setdefault(checked["artifact_path"], (checked["artifact_sha256"], checked["byte_end"]))
            if previous != binding or previous_path != (checked["artifact_sha256"], checked["byte_end"]):
                raise SourceBundleError("one artifact identity/path has inconsistent bindings")
    return copy.deepcopy(row)


def source_artifacts(source):
    """All component identities, including metadata and fixture source originals."""
    yield source["original"]
    if source["kind"] == "financial_filing":
        for field in ("capture_receipt", "publication_metadata", "publication_capture_receipt"):
            yield source[field]
    elif source["kind"] == "workflow_fixture":
        yield from source["source_originals"].values()


def _read(root, artifact, cache):
    root = root.resolve(strict=True)
    if not root.is_dir():
        raise SourceBundleError("artifact root is not a directory")
    target = root / artifact["artifact_path"]
    # Parent aliases are prohibited too; a contained final target is insufficient.
    for relative_parent in (Path(artifact["artifact_path"]), *Path(artifact["artifact_path"]).parents):
        if (root / relative_parent).is_symlink():
            raise SourceBundleError("source artifact uses a symlink")
    target.resolve(strict=True).relative_to(root)
    before = target.stat(follow_symlinks=False)
    identity = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
    if not stat.S_ISREG(before.st_mode) or before.st_size != artifact["byte_end"]:
        raise SourceBundleError("source artifact is not a complete regular original")
    key = (str(root), artifact["artifact_path"], artifact["artifact_sha256"])
    if key in cache:
        previous_identity, raw = cache[key]
        if previous_identity != identity:
            raise SourceBundleError("source artifact changed within the benchmark capture")
        return raw
    descriptor = os.open(target, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    with os.fdopen(descriptor, "rb") as stream:
        opened = os.fstat(stream.fileno())
        if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns) != identity:
            raise SourceBundleError("source artifact identity changed during open")
        raw = stream.read(MAX_ARTIFACT_BYTES + 1)
        after = os.fstat(stream.fileno())
    current = target.stat(follow_symlinks=False)
    target.resolve(strict=True).relative_to(root)
    if (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) != identity or (current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns) != identity or len(raw) != artifact["byte_end"] or hashlib.sha256(raw).hexdigest() != artifact["artifact_sha256"]:
        raise SourceBundleError("source artifact changed or has a different digest")
    cache[key] = (identity, raw)
    return raw


def _json(raw, label):
    def normalized(value):
        if isinstance(value, dict):
            return {k: normalized(v) for k, v in value.items()}
        if isinstance(value, list):
            return [normalized(v) for v in value]
        return _normalize_source_value(value) if type(value) is Decimal else value
    return normalized(dict(_json_mapping(raw, label=label)))


def _receipt(document, original, *, submissions=False):
    if document.get("schema") != "prospective-readonly-source-response/v1" or document.get("method") != "GET" or type(document.get("status_code")) is not int or document["status_code"] != 200:
        raise SourceBundleError("source capture receipt schema/method/status is invalid")
    if document.get("analysis_only") is not True or document.get("execution_authority") != "none" or document.get("can_submit_orders") is not False:
        raise SourceBundleError("source capture receipt has invalid authority")
    if document.get("body_sha256") != original["artifact_sha256"] or type(document.get("body_bytes")) is not int or document["body_bytes"] != original["byte_end"] or document.get("body_path") != Path(original["artifact_path"]).name:
        raise SourceBundleError("capture receipt is bound to a different original")
    if timestamp(document.get("request_started_at")) > timestamp(document.get("captured_at")):
        raise SourceBundleError("source capture chronology is invalid")
    uri = document.get("request_uri")
    if type(uri) is not str:
        raise SourceBundleError("source capture URI is missing")
    parsed = urlsplit(uri)
    allowed = {"data.sec.gov"} if submissions else {"www.sec.gov", "sec.gov"}
    pattern = r"/submissions/CIK\d{10}\.json" if submissions else r"/Archives/edgar/data/\d+/\d{18}/[^/]+"
    if parsed.scheme != "https" or parsed.hostname not in allowed or parsed.username or parsed.password or parsed.port or parsed.query or parsed.fragment or re.fullmatch(pattern, parsed.path) is None:
        raise SourceBundleError("source capture is not the declared official SEC route")
    return parsed


def _financial(root, source, cache):
    raw = _read(root, source["original"], cache)
    capture = _json(_read(root, source["capture_receipt"], cache), "filing capture")
    filing_uri = _receipt(capture, source["original"])
    if filing_uri.path.split("/")[-2] != source["accession"].replace("-", ""):
        raise SourceBundleError("filing capture belongs to a different accession")
    metadata = _json(_read(root, source["publication_metadata"], cache), "SEC publication metadata")
    publication_capture = _json(_read(root, source["publication_capture_receipt"], cache), "publication capture")
    metadata_uri = _receipt(publication_capture, source["publication_metadata"], submissions=True)
    cik = metadata.get("cik")
    if type(cik) not in {str, int} or not str(cik).isdigit() or int(cik) != int(filing_uri.path.split("/")[-3]) or int(metadata_uri.path.rsplit("/CIK", 1)[1].removesuffix(".json")) != int(cik):
        raise SourceBundleError("publication and filing issuer identities differ")
    recent = metadata.get("filings", {}).get("recent") if type(metadata.get("filings")) is dict else None
    if type(recent) is not dict or type(recent.get("accessionNumber")) is not list:
        raise SourceBundleError("SEC publication arrays are missing")
    accessions = recent["accessionNumber"]
    matches = [i for i, value in enumerate(accessions) if value == source["accession"]]
    if len(matches) != 1:
        raise SourceBundleError("SEC publication accession is missing or ambiguous")
    index = matches[0]
    fields = ("accessionNumber", "acceptanceDateTime", "filingDate", "reportDate", "form")
    if any(type(recent.get(f)) is not list or len(recent[f]) != len(accessions) or type(recent[f][index]) is not str for f in fields):
        raise SourceBundleError("SEC publication arrays disagree")
    publication = {f: recent[f][index] for f in fields}
    if timestamp(publication["acceptanceDateTime"]) > timestamp(capture["captured_at"]) or timestamp(publication["acceptanceDateTime"]) > timestamp(publication_capture["captured_at"]):
        raise SourceBundleError("publication occurs after its alleged observation")
    return {"source_id": source["source_id"], "accession": source["accession"],
            "extraction": json.loads(media_source(raw, source["media_input"])),
            "capture_record": capture, "publication_record": publication,
            "publication_capture_record": publication_capture}


def _workflow(root, source, cache):
    body = _json(_read(root, source["original"], cache), "workflow fixture")
    _fields(body, {"schema", "case_id", "fixture_not_deployed_configuration", "query", "schedule_contract", "role_contract", "automation_tomls", "source_bindings", "source_revision", "source_transformations"}, "workflow fixture")
    if body["schema"] != "counterfactual_workflow_configuration_input/v2" or body["fixture_not_deployed_configuration"] is not True or type(body["source_revision"]) is not str or not re.fullmatch(r"[0-9a-f]{40}", body["source_revision"]):
        raise SourceBundleError("workflow fixture schema/identity is invalid")
    references = _fields(body["source_bindings"], WORKFLOW_ORIGINALS, "workflow source bindings")
    originals = {}
    for relative, descriptor in source["source_originals"].items():
        original = _read(root, descriptor, cache)
        reference = references[relative]
        _fields(reference, {"original_relative_path", "source_revision", "retained_path", "sha256"}, "workflow source reference")
        if reference["original_relative_path"] != relative or reference["sha256"] != descriptor["artifact_sha256"] or reference["source_revision"] != body["source_revision"]:
            raise SourceBundleError("workflow fixture original binding differs")
        originals[relative] = original
    contract = _json(originals["config/automation_schedule_contract.json"], "workflow contract original")
    roles = _json(originals["config/automation_roles.json"], "workflow roles original")
    derived = copy.deepcopy(contract)
    if type(derived.get("automations")) is not dict or len(derived["automations"]) != 10:
        raise SourceBundleError("workflow contract does not declare ten roles")
    for record in derived["automations"].values():
        phrases = record.get("required_prompt_phrases") if type(record) is dict else None
        if type(phrases) is not list or any(type(p) is not str for p in phrases):
            raise SourceBundleError("workflow prompt derivation is invalid")
        record["prompt_sha256"] = hashlib.sha256("\n".join(("fixture TradingAgents automation", *phrases)).encode()).hexdigest()
    if body["schedule_contract"] != derived or body["role_contract"] != roles:
        raise SourceBundleError("workflow fixture altered its original contract/roles")
    tomls = body["automation_tomls"]
    if type(tomls) is not dict or not 1 <= len(tomls) <= 32 or any(type(k) is not str or not re.fullmatch(r"tradingagents-[a-z0-9-]{1,100}", k) or type(v) is not str or len(v.encode()) > 256 * 1024 for k, v in tomls.items()):
        raise SourceBundleError("workflow fixture records are invalid")
    # Paths, revision annotations, descriptive preparation questions and IDs are
    # custody metadata, not compared-lane evidence. Contract content is exact.
    material = {"schema": body["schema"], "fixture_not_deployed_configuration": True,
                "schedule_contract": derived, "role_contract": roles, "automation_tomls": tomls,
                "source_transformations": [{"operation": "required_phrases_prompt/v1", "changes": "fixture prompt_sha256 only"},
                                           {"operation": "exclude_local_custody_and_preparation_metadata", "fields": ["source_bindings", "source_revision", "query", "case_id", "source_transformations"]}]}
    return {"source_id": source["source_id"], "material": material}


def _assemble(root, descriptor, cache):
    unique = {(a["artifact_path"], a["artifact_sha256"]): a["byte_end"] for s in descriptor["sources"] for a in source_artifacts(s)}
    if sum(unique.values()) > MAX_BUNDLE_BYTES:
        raise SourceBundleError("source bundle exceeds bounded original size")
    sources = []
    for source in descriptor["sources"]:
        if source["kind"] == "media":
            raw = _read(root, source["original"], cache)
            sources.append({"source_id": source["source_id"], "media": json.loads(media_source(raw, source["media_input"]))})
        elif source["kind"] == "financial_filing":
            sources.append(_financial(root, source, cache))
        else:
            sources.append(_workflow(root, source, cache))
    return canonical({"schema_version": BUNDLE_SCHEMA, "sources": sources})


def build_source_bundle_input(artifact_root, sources, *, artifact_cache=None):
    """Build from complete originals; no expected answer is accepted here."""
    try:
        descriptor = validate_source_bundle_input({"schema_version": SCHEMA, "sources": list(sources), "engine_versions": engine_versions(), "extraction_sha256": "0" * 64})
        material = _assemble(Path(artifact_root), descriptor, {} if artifact_cache is None else artifact_cache)
        descriptor["extraction_sha256"] = hashlib.sha256(material).hexdigest()
        return descriptor, material
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise SourceBundleError(f"source-bundle build failed: {exc}") from exc


def source_bundle_source(artifact_root, descriptor, *, artifact_cache=None):
    try:
        checked = validate_source_bundle_input(descriptor)
        if checked["engine_versions"] != engine_versions():
            raise SourceBundleError("registered source-bundle reader/interpreter changed")
        material = _assemble(Path(artifact_root), checked, {} if artifact_cache is None else artifact_cache)
        if hashlib.sha256(material).hexdigest() != checked["extraction_sha256"]:
            raise SourceBundleError("registered source-bundle extraction changed")
        return material
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise SourceBundleError(f"source-bundle read failed: {exc}") from exc
