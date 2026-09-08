"""Immutable, analysis-only admission for frozen economic protocols.

The economic-evaluation protocol module remains pure.  This adapter is the
boundary that pins an already-validated protocol to exact local source bytes
and the predecessor of the immutable strategy-evidence journal.  Admission is
not execution authority and cannot submit orders.
"""

from __future__ import annotations

import base64
import binascii
import datetime as dt
import hashlib
import json
import lzma
import os
import re
import stat
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from tradingagents.dataflows.pit import RawPointInTimeArtifactArchive
from tradingagents.dataflows.pit.partitions import validate_market_date_partitions
from tradingagents.evals.economic_evaluation_partition_binding import (
    bind_phase_eligibility,
    bind_validation_phase_eligibility,
)
from tradingagents.evals.economic_evaluation_protocol import (
    FrozenEvaluationProtocol,
    validate_frozen_evaluation_protocol,
)
from tradingagents.evals.economic_evaluation_result import (
    EconomicValidationResult,
    LegacyEconomicValidationResult,
    validate_economic_phase_result,
    validate_economic_validation_result,
)
from tradingagents.evals.economic_tournament_evidence import (
    SourceBoundTournamentInput,
)
from tradingagents.evals.economic_tournament_evidence_admission import (
    EconomicTournamentReceiptArchive,
    verify_source_bound_tournament_input,
)
from tradingagents.strategy._immutable_evidence_store import (
    EvidenceCandidate,
    EvidenceEnvelope,
    EvidenceEvent,
    ImmutableStrategyEvidenceStore,
)

__all__ = [
    "EconomicEvaluationAdmissionError",
    "EconomicEvaluationProtocolAdmission",
    "EconomicEvaluationRun",
    "EconomicHoldoutRelease",
    "EconomicEvaluationReadiness",
    "EconomicEvaluationAdmissionAdapter",
]


ECONOMIC_EVALUATION_PROTOCOL_KIND = "economic-evaluation-protocol"
ECONOMIC_EVALUATION_RUN_KIND = "economic-evaluation-run"
ECONOMIC_HOLDOUT_RELEASE_KIND = "economic-holdout-release"
ECONOMIC_EVALUATION_PROTOCOL_ADMISSION_SCHEMA = (
    "economic_evaluation_protocol_admission/v2"
)
ECONOMIC_HOLDOUT_RELEASE_SCHEMA = "economic_holdout_release/v1"
ECONOMIC_EVALUATION_RUN_SCHEMA = "economic_evaluation_run/v1"
ECONOMIC_VALIDATION_REPORT_SCHEMA = "economic_validation_report/v3"
ECONOMIC_PHASE_REPORT_SCHEMA = "economic_evaluation_report/v4"
_LEGACY_ECONOMIC_VALIDATION_REPORT_SCHEMA = "economic_validation_report/v1"
_PRE_SOURCE_BOUND_VALIDATION_REPORT_SCHEMA = "economic_validation_report/v2"
_AUTHORITY_FIELDS: dict[str, object] = {
    "analysis_only": True,
    "execution_authority": "none",
    "can_submit_orders": False,
}
_ZERO_HASH = "0" * 64
_GIT_REVISION = re.compile(r"[0-9a-f]{40}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{2,255}")
_CANONICAL_UTC = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\+00:00")
_PROTOCOL_RECEIPT_CHUNK_CHARS = 60_000
_MAX_PROTOCOL_RECEIPT_BYTES = 16_000_000
_MAX_RECEIPT_COMPRESSED_BYTES = 750_000
_MAX_RECEIPT_ENCODED_CHARS = 1_000_000
_MAX_RECEIPT_CHUNKS = 17
_RECEIPT_LZMA_MEMLIMIT_BYTES = 32 * 1024 * 1024
_RECEIPT_LZMA_FILTERS = (
    {
        "id": lzma.FILTER_LZMA2,
        "dict_size": 8 * 1024 * 1024,
        "lc": 3,
        "lp": 0,
        "pb": 2,
        "mode": lzma.MODE_NORMAL,
        "nice_len": 64,
        "mf": lzma.MF_BT4,
        "depth": 0,
    },
)
_VALIDATION_REPORT_FIELDS = frozenset(
    {
        "schema_version",
        "protocol_id",
        "market_date_partitions",
        "validation_event_ids",
        "result",
        "result_id",
        "result_sha256",
        "tournament_input",
        *_AUTHORITY_FIELDS,
    }
)
_UNAVAILABLE_VALIDATION_REPORT_FIELDS = frozenset(
    _VALIDATION_REPORT_FIELDS | {"availability_status", "qualification_status"}
)
_PHASE_REPORT_FIELDS = frozenset(
    {
        "schema_version",
        "protocol_id",
        "phase",
        "market_date_partitions",
        "event_ids",
        "result",
        "result_id",
        "result_sha256",
        "tournament_input",
        *_AUTHORITY_FIELDS,
    }
)
_UNAVAILABLE_PHASE_REPORT_FIELDS = frozenset(
    _PHASE_REPORT_FIELDS | {"availability_status", "qualification_status"}
)
_TOURNAMENT_INPUT_REFERENCE_FIELDS = frozenset({"input_id", "input_sha256"})
_LEGACY_VALIDATION_REPORT_FIELDS = frozenset(
    {
        "schema_version",
        "protocol_id",
        "validation_event_ids",
        "result",
        "result_id",
        "result_sha256",
        *_AUTHORITY_FIELDS,
    }
)
_SOURCE_MANIFEST_ROW_FIELDS = frozenset({"path", "sha256"})
_PROTOCOL_ADMISSION_FIELDS = frozenset(
    {
        "schema_version",
        "protocol",
        "protocol_id",
        "cohort_id",
        "cohort_sha256",
        "partition_id",
        "partition_sha256",
        "input_manifest_id",
        "input_manifest_sha256",
        "evaluation_policy_sha256",
        "primary_universe_sha256",
        "sensitivity_universe_50_sha256",
        "sensitivity_universe_100_sha256",
        "source_revision",
        "source_manifest",
        "source_manifest_sha256",
        "store_predecessor",
        *_AUTHORITY_FIELDS,
    }
)


class EconomicEvaluationAdmissionError(ValueError):
    """A frozen protocol cannot be safely admitted as economic evidence."""


@dataclass(frozen=True, slots=True)
class EconomicEvaluationProtocolAdmission:
    """A local receipt for one immutable admitted protocol record."""

    envelope: EvidenceEnvelope
    created: bool
    protocol_id: str
    input_manifest_sha256: str
    predecessor_sequence: int
    predecessor_event_sha256: str

    def __post_init__(self) -> None:
        if self.envelope.kind != ECONOMIC_EVALUATION_PROTOCOL_KIND:
            raise EconomicEvaluationAdmissionError("admission envelope kind is invalid")
        if type(self.created) is not bool:
            raise EconomicEvaluationAdmissionError("admission created flag is invalid")
        if type(self.predecessor_sequence) is not int or self.predecessor_sequence < 0:
            raise EconomicEvaluationAdmissionError("admission predecessor sequence is invalid")
        if _SHA256.fullmatch(self.predecessor_event_sha256) is None:
            raise EconomicEvaluationAdmissionError("admission predecessor digest is invalid")


@dataclass(frozen=True, slots=True)
class EconomicHoldoutRelease:
    """Immutable receipt that makes one protocol's holdout eligible to read."""

    envelope: EvidenceEnvelope
    created: bool
    protocol_id: str
    protocol_admission_object_id: str
    validation_run_object_id: str
    predecessor_sequence: int
    predecessor_event_sha256: str

    def __post_init__(self) -> None:
        if self.envelope.kind != ECONOMIC_HOLDOUT_RELEASE_KIND:
            raise EconomicEvaluationAdmissionError("holdout envelope kind is invalid")
        if type(self.created) is not bool:
            raise EconomicEvaluationAdmissionError("holdout created flag is invalid")
        if not isinstance(self.protocol_id, str) or not self.protocol_id.startswith(
            "economic-evaluation-protocol-"
        ):
            raise EconomicEvaluationAdmissionError("holdout protocol identity is invalid")
        if not isinstance(self.protocol_admission_object_id, str):
            raise EconomicEvaluationAdmissionError("holdout protocol record is invalid")
        if not isinstance(self.validation_run_object_id, str):
            raise EconomicEvaluationAdmissionError("holdout validation run is invalid")
        if type(self.predecessor_sequence) is not int or self.predecessor_sequence < 1:
            raise EconomicEvaluationAdmissionError("holdout predecessor sequence is invalid")
        if _SHA256.fullmatch(self.predecessor_event_sha256) is None:
            raise EconomicEvaluationAdmissionError("holdout predecessor digest is invalid")


@dataclass(frozen=True, slots=True)
class EconomicEvaluationRun:
    """Immutable receipt for one completed analysis-only protocol phase."""

    envelope: EvidenceEnvelope
    created: bool
    protocol_id: str
    phase: str
    protocol_admission_object_id: str
    predecessor_sequence: int
    predecessor_event_sha256: str

    def __post_init__(self) -> None:
        if self.envelope.kind != ECONOMIC_EVALUATION_RUN_KIND:
            raise EconomicEvaluationAdmissionError("evaluation-run envelope kind is invalid")
        if type(self.created) is not bool:
            raise EconomicEvaluationAdmissionError("evaluation-run created flag is invalid")
        if not isinstance(self.protocol_id, str) or not self.protocol_id.startswith(
            "economic-evaluation-protocol-"
        ):
            raise EconomicEvaluationAdmissionError("evaluation-run protocol identity is invalid")
        if self.phase not in {"development", "validation", "holdout"}:
            raise EconomicEvaluationAdmissionError("evaluation-run phase is invalid")
        if not isinstance(self.protocol_admission_object_id, str):
            raise EconomicEvaluationAdmissionError("evaluation-run protocol record is invalid")
        if type(self.predecessor_sequence) is not int or self.predecessor_sequence < 1:
            raise EconomicEvaluationAdmissionError("evaluation-run predecessor sequence is invalid")
        if _SHA256.fullmatch(self.predecessor_event_sha256) is None:
            raise EconomicEvaluationAdmissionError("evaluation-run predecessor digest is invalid")


@dataclass(frozen=True, slots=True)
class EconomicEvaluationReadiness:
    """Read-only evidence state for one protocol; never execution authority."""

    protocol_id: str
    protocol_admission_object_id: str | None
    development_run_object_id: str | None
    validation_run_object_id: str | None
    holdout_release_object_id: str | None
    holdout_run_object_id: str | None
    evidence_sequence: int
    evidence_head_event_sha256: str

    def __post_init__(self) -> None:
        _require_protocol_id(self.protocol_id)
        for value in (
            self.protocol_admission_object_id,
            self.development_run_object_id,
            self.validation_run_object_id,
            self.holdout_release_object_id,
            self.holdout_run_object_id,
        ):
            if value is not None and type(value) is not str:
                raise EconomicEvaluationAdmissionError("readiness object identity is invalid")
        if type(self.evidence_sequence) is not int or self.evidence_sequence < 0:
            raise EconomicEvaluationAdmissionError("readiness evidence sequence is invalid")
        if _SHA256.fullmatch(self.evidence_head_event_sha256) is None:
            raise EconomicEvaluationAdmissionError("readiness evidence digest is invalid")
        if any(
            value is not None
            for value in (
                self.development_run_object_id,
                self.validation_run_object_id,
                self.holdout_run_object_id,
            )
        ) and self.protocol_admission_object_id is None:
            raise EconomicEvaluationAdmissionError("evaluation run lacks an admitted protocol")
        if self.holdout_release_object_id is not None and self.validation_run_object_id is None:
            raise EconomicEvaluationAdmissionError("holdout release lacks a validation run")

    @property
    def state(self) -> str:
        if self.protocol_admission_object_id is None:
            return "protocol_not_admitted"
        if self.validation_run_object_id is None:
            return "validation_not_admitted"
        if self.holdout_release_object_id is None:
            return "holdout_sealed"
        if self.holdout_run_object_id is None:
            return "holdout_released_analysis_only"
        return "holdout_completed_analysis_only"


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        _thaw_json(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _thaw_json(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    if isinstance(value, list):
        return [_thaw_json(item) for item in value]
    return value


def _reject_json_constant(constant: str) -> object:
    raise ValueError(f"invalid JSON constant: {constant}")


def _receipt_chunks(value: object) -> list[str]:
    try:
        receipt_bytes = _canonical_json_bytes(value)
    except (RecursionError, TypeError, ValueError, UnicodeError) as exc:
        raise EconomicEvaluationAdmissionError(
            "receipt value is not canonical JSON"
        ) from exc
    if len(receipt_bytes) > _MAX_PROTOCOL_RECEIPT_BYTES:
        raise EconomicEvaluationAdmissionError("receipt value is too large")
    compressed = lzma.compress(
        receipt_bytes,
        format=lzma.FORMAT_XZ,
        check=lzma.CHECK_CRC64,
        filters=_RECEIPT_LZMA_FILTERS,
    )
    if len(compressed) > _MAX_RECEIPT_COMPRESSED_BYTES:
        raise EconomicEvaluationAdmissionError("compressed receipt is too large")
    encoded = base64.b64encode(compressed).decode("ascii")
    if len(encoded) > _MAX_RECEIPT_ENCODED_CHARS:
        raise EconomicEvaluationAdmissionError("encoded receipt is too large")
    return [
        encoded[offset : offset + _PROTOCOL_RECEIPT_CHUNK_CHARS]
        for offset in range(0, len(encoded), _PROTOCOL_RECEIPT_CHUNK_CHARS)
    ]


def _protocol_receipt_chunks(protocol: FrozenEvaluationProtocol) -> list[str]:
    return _receipt_chunks(protocol.to_dict())


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


def _canonical_effective_at(value: object) -> str:
    if type(value) is not dt.datetime:
        raise EconomicEvaluationAdmissionError("effective_at must be an exact datetime")
    if value.tzinfo is None or value.utcoffset() != dt.timedelta(0):
        raise EconomicEvaluationAdmissionError("effective_at must be UTC")
    if value.microsecond:
        raise EconomicEvaluationAdmissionError("effective_at must be second-aligned")
    return value.isoformat(timespec="seconds")


def _canonical_repo_root(value: str | Path) -> Path:
    root = Path(value)
    try:
        resolved = root.resolve(strict=True)
    except OSError as exc:
        raise EconomicEvaluationAdmissionError("repo_root must exist") from exc
    if not resolved.is_dir():
        raise EconomicEvaluationAdmissionError("repo_root must be a directory")
    return resolved


def _source_path(root: Path, value: object) -> tuple[str, Path]:
    if type(value) is not str or not value:
        raise EconomicEvaluationAdmissionError("source paths must be nonempty strings")
    if "\\" in value:
        raise EconomicEvaluationAdmissionError("source paths must use POSIX separators")
    relative = Path(value)
    if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
        raise EconomicEvaluationAdmissionError("source path must be contained and normalized")
    normalized = relative.as_posix()
    if normalized != value:
        raise EconomicEvaluationAdmissionError("source path must be canonically normalized")
    candidate = root / relative
    current = root
    for part in relative.parts:
        current = current / part
        try:
            state = os.lstat(current)
        except OSError as exc:
            raise EconomicEvaluationAdmissionError("source path does not exist") from exc
        if stat.S_ISLNK(state.st_mode):
            raise EconomicEvaluationAdmissionError("source paths must not traverse symlinks")
    if not stat.S_ISREG(os.lstat(candidate).st_mode):
        raise EconomicEvaluationAdmissionError("source path must name a regular file")
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise EconomicEvaluationAdmissionError("source path cannot be resolved") from exc
    if not resolved.is_relative_to(root):
        raise EconomicEvaluationAdmissionError("source path escapes repo_root")
    return normalized, candidate


def _source_manifest(root: Path, paths: object) -> tuple[list[dict[str, str]], str]:
    if type(paths) is not tuple or not paths:
        raise EconomicEvaluationAdmissionError("source_paths must be a nonempty exact tuple")
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    for value in paths:
        normalized, source = _source_path(root, value)
        if normalized in seen:
            raise EconomicEvaluationAdmissionError("source_paths must not contain duplicates")
        seen.add(normalized)
        try:
            contents = source.read_bytes()
        except OSError as exc:
            raise EconomicEvaluationAdmissionError("source path cannot be read") from exc
        rows.append(
            {
                "path": normalized,
                "sha256": hashlib.sha256(contents).hexdigest(),
            }
        )
    rows.sort(key=lambda row: row["path"])
    return rows, _sha256(rows)


def _require_source_revision(value: object) -> str:
    if type(value) is not str or _GIT_REVISION.fullmatch(value) is None:
        raise EconomicEvaluationAdmissionError(
            "source_revision must be a lowercase 40-hex Git revision"
        )
    return value


def _bind_source_revision_to_manifest(
    root: Path,
    *,
    revision: str,
    source_rows: list[dict[str, str]],
) -> None:
    """Require every admitted working-tree byte to match one local Git commit."""

    try:
        resolved = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--verify", f"{revision}^{{commit}}"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise EconomicEvaluationAdmissionError(
            "repo_root must support local Git revision verification"
        ) from exc
    if resolved.returncode != 0 or resolved.stdout.strip() != revision:
        raise EconomicEvaluationAdmissionError(
            "source_revision is not an exact commit in repo_root"
        )
    for row in source_rows:
        path = row["path"]
        try:
            blob = subprocess.run(
                ["git", "-C", str(root), "show", f"{revision}:{path}"],
                check=False,
                capture_output=True,
                timeout=10,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise EconomicEvaluationAdmissionError(
                "source_revision blob verification failed"
            ) from exc
        if blob.returncode != 0 or hashlib.sha256(blob.stdout).hexdigest() != row["sha256"]:
            raise EconomicEvaluationAdmissionError(
                "source bytes do not match source_revision"
            )


def _require_protocol_id(value: object) -> str:
    if (
        type(value) is not str
        or not value.startswith("economic-evaluation-protocol-")
        or _SHA256.fullmatch(value.removeprefix("economic-evaluation-protocol-"))
        is None
    ):
        raise EconomicEvaluationAdmissionError("protocol_id is not canonical")
    return value


def _require_owner(value: object) -> str:
    if type(value) is not str or _IDENTIFIER.fullmatch(value) is None:
        raise EconomicEvaluationAdmissionError("released_by must be a canonical owner identity")
    return value


def _canonical_timestamp_text(value: object, *, label: str) -> str:
    if type(value) is not str or _CANONICAL_UTC.fullmatch(value) is None:
        raise EconomicEvaluationAdmissionError(f"{label} must be canonical UTC seconds")
    try:
        parsed = dt.datetime.fromisoformat(value)
    except ValueError as exc:
        raise EconomicEvaluationAdmissionError(
            f"{label} must be a real canonical UTC timestamp"
        ) from exc
    if parsed.tzinfo != dt.UTC or parsed.isoformat(timespec="seconds") != value:
        raise EconomicEvaluationAdmissionError(f"{label} must be canonical UTC seconds")
    return value


def _require_authority(value: Mapping[str, object], *, label: str) -> None:
    if value.get("analysis_only") is not True:
        raise EconomicEvaluationAdmissionError(f"{label}.analysis_only must be true")
    if value.get("execution_authority") != "none" or type(
        value.get("execution_authority")
    ) is not str:
        raise EconomicEvaluationAdmissionError(
            f"{label}.execution_authority must be none"
        )
    if value.get("can_submit_orders") is not False:
        raise EconomicEvaluationAdmissionError(
            f"{label}.can_submit_orders must be false"
        )


def _payload_mapping(value: object, *, label: str) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise EconomicEvaluationAdmissionError(f"{label} must be a mapping")
    return dict(value)


def _tournament_input_reference(value: object) -> dict[str, str]:
    reference = _payload_mapping(value, label="tournament_input")
    if set(reference) != _TOURNAMENT_INPUT_REFERENCE_FIELDS:
        raise EconomicEvaluationAdmissionError("tournament input reference fields are invalid")
    input_id = reference["input_id"]
    input_sha256 = reference["input_sha256"]
    if (
        type(input_id) is not str
        or not input_id.startswith("economic-tournament-input-")
        or _SHA256.fullmatch(input_id.removeprefix("economic-tournament-input-")) is None
        or type(input_sha256) is not str
        or _SHA256.fullmatch(input_sha256) is None
    ):
        raise EconomicEvaluationAdmissionError("tournament input reference is invalid")
    return {"input_id": input_id, "input_sha256": input_sha256}


def _frozen_validation_report(
    value: object,
    *,
    protocol: FrozenEvaluationProtocol,
    allow_legacy: bool = False,
) -> dict[str, object]:
    report = _payload_mapping(_thaw_json(value), label="frozen_validation_report")
    if report.get("schema_version") in {
        _LEGACY_ECONOMIC_VALIDATION_REPORT_SCHEMA,
        _PRE_SOURCE_BOUND_VALIDATION_REPORT_SCHEMA,
    }:
        return _legacy_frozen_validation_report(
            report,
            protocol=protocol,
            allow_legacy=allow_legacy,
        )
    unavailable = "availability_status" in report
    expected_fields = (
        _UNAVAILABLE_VALIDATION_REPORT_FIELDS
        if unavailable
        else _VALIDATION_REPORT_FIELDS
    )
    if set(report) != expected_fields:
        raise EconomicEvaluationAdmissionError("frozen_validation_report fields are invalid")
    if report["schema_version"] != ECONOMIC_VALIDATION_REPORT_SCHEMA:
        raise EconomicEvaluationAdmissionError("validation report schema is invalid")
    if _require_protocol_id(report["protocol_id"]) != protocol.protocol_id:
        raise EconomicEvaluationAdmissionError("validation report protocol does not match")
    try:
        partitions = validate_market_date_partitions(report["market_date_partitions"])
        if (
            partitions.partition_id != protocol.partition_id
            or partitions.partition_sha256 != protocol.partition_sha256
            or partitions.canonical_json_bytes()
            != protocol.market_date_partitions.canonical_json_bytes()
        ):
            raise EconomicEvaluationAdmissionError(
                "validation report does not contain the protocol's complete partition receipt"
            )
        eligibility = bind_validation_phase_eligibility(
            protocol=protocol,
            partitions=partitions,
        )
    except (TypeError, ValueError) as exc:
        raise EconomicEvaluationAdmissionError(
            "validation report PIT partition binding is invalid"
        ) from exc
    if report["validation_event_ids"] != list(eligibility.event_ids):
        raise EconomicEvaluationAdmissionError(
            "validation report event partition does not match PIT eligibility"
        )
    _tournament_input_reference(report["tournament_input"])
    try:
        result = validate_economic_validation_result(report["result"])
    except (TypeError, ValueError) as exc:
        raise EconomicEvaluationAdmissionError("validation report result is invalid") from exc
    if type(result) is not EconomicValidationResult:
        raise EconomicEvaluationAdmissionError(
            "legacy validation results are readable but nonqualifying"
        )
    if unavailable:
        if (
            report["availability_status"] != "unavailable"
            or report["qualification_status"]
            != "nonqualifying_unavailable_execution_evidence"
            or result.availability_status != report["availability_status"]
            or result.qualification_status != report["qualification_status"]
        ):
            raise EconomicEvaluationAdmissionError(
                "unavailable validation report status is invalid"
            )
    elif result.availability_status != "available":
        raise EconomicEvaluationAdmissionError(
            "available validation report omits unavailable result status"
        )
    if (
        result.protocol_id != protocol.protocol_id
        or result.validation_partition_id != eligibility.partition_id
        or result.validation_partition_sha256 != eligibility.partition_sha256
        or result.validation_event_ids != eligibility.event_ids
        or report["result_id"] != result.result_id
        or report["result_sha256"] != result.result_sha256
        or _canonical_json_bytes(report["result"])
        != result.canonical_json_bytes()
    ):
        raise EconomicEvaluationAdmissionError(
            "validation report result does not exactly bind the protocol validation output"
        )
    _require_authority(report, label="frozen_validation_report")
    try:
        _canonical_json_bytes(report)
    except (TypeError, ValueError) as exc:
        raise EconomicEvaluationAdmissionError(
            "frozen_validation_report is not canonical JSON"
        ) from exc
    return report


def _frozen_phase_report(
    value: object,
    *,
    protocol: FrozenEvaluationProtocol,
) -> dict[str, object]:
    """Validate one development or holdout result without validation aliases."""

    report = _payload_mapping(_thaw_json(value), label="frozen_phase_report")
    unavailable = "availability_status" in report
    expected_fields = (
        _UNAVAILABLE_PHASE_REPORT_FIELDS if unavailable else _PHASE_REPORT_FIELDS
    )
    if set(report) != expected_fields:
        raise EconomicEvaluationAdmissionError("frozen phase report fields are invalid")
    if report["schema_version"] != ECONOMIC_PHASE_REPORT_SCHEMA:
        raise EconomicEvaluationAdmissionError("phase report schema is invalid")
    if _require_protocol_id(report["protocol_id"]) != protocol.protocol_id:
        raise EconomicEvaluationAdmissionError("phase report protocol does not match")
    phase = report["phase"]
    if phase not in {"development", "holdout"}:
        raise EconomicEvaluationAdmissionError("phase report phase is invalid")
    try:
        partitions = validate_market_date_partitions(report["market_date_partitions"])
        eligibility = bind_phase_eligibility(
            protocol=protocol,
            partitions=partitions,
            phase=phase,
        )
    except (TypeError, ValueError) as exc:
        raise EconomicEvaluationAdmissionError("phase report PIT partition binding is invalid") from exc
    if report["event_ids"] != list(eligibility.event_ids):
        raise EconomicEvaluationAdmissionError("phase report event IDs do not match eligibility")
    _tournament_input_reference(report["tournament_input"])
    try:
        result = validate_economic_phase_result(report["result"])
    except (TypeError, ValueError) as exc:
        raise EconomicEvaluationAdmissionError("phase report result is invalid") from exc
    if unavailable:
        if (
            report["availability_status"] != "unavailable"
            or report["qualification_status"]
            != "nonqualifying_unavailable_execution_evidence"
            or result.availability_status != report["availability_status"]
            or result.qualification_status != report["qualification_status"]
        ):
            raise EconomicEvaluationAdmissionError("unavailable phase report status is invalid")
    elif result.availability_status != "available":
        raise EconomicEvaluationAdmissionError("available phase report omits unavailable status")
    if (
        result.protocol_id != protocol.protocol_id
        or result.phase != phase
        or result.validation_partition_id != eligibility.partition_id
        or result.validation_partition_sha256 != eligibility.partition_sha256
        or result.validation_event_ids != eligibility.event_ids
        or report["result_id"] != result.result_id
        or report["result_sha256"] != result.result_sha256
        or _canonical_json_bytes(report["result"]) != result.canonical_json_bytes()
    ):
        raise EconomicEvaluationAdmissionError("phase report result does not exactly bind phase output")
    _require_authority(report, label="frozen_phase_report")
    return report


def _frozen_report_for_phase(
    value: object,
    *,
    protocol: FrozenEvaluationProtocol,
    phase: str,
    allow_legacy: bool = False,
) -> dict[str, object]:
    if phase == "validation":
        return _frozen_validation_report(
            value,
            protocol=protocol,
            allow_legacy=allow_legacy,
        )
    if phase in {"development", "holdout"}:
        return _frozen_phase_report(value, protocol=protocol)
    raise EconomicEvaluationAdmissionError("evaluation-run phase is invalid")


def _legacy_frozen_validation_report(
    report: Mapping[str, object],
    *,
    protocol: FrozenEvaluationProtocol,
    allow_legacy: bool,
) -> dict[str, object]:
    """Validate historical report bytes without granting qualifying status."""

    values = _payload_mapping(report, label="legacy_validation_report")
    if values["schema_version"] == _LEGACY_ECONOMIC_VALIDATION_REPORT_SCHEMA:
        expected_fields = _LEGACY_VALIDATION_REPORT_FIELDS
        require_legacy_result = True
    elif values["schema_version"] == _PRE_SOURCE_BOUND_VALIDATION_REPORT_SCHEMA:
        expected_fields = _VALIDATION_REPORT_FIELDS - {"tournament_input"}
        require_legacy_result = False
    else:
        raise EconomicEvaluationAdmissionError("legacy validation report schema is invalid")
    if set(values) != expected_fields:
        raise EconomicEvaluationAdmissionError("legacy validation report fields are invalid")
    if _require_protocol_id(values["protocol_id"]) != protocol.protocol_id:
        raise EconomicEvaluationAdmissionError("legacy validation report protocol does not match")
    if values["validation_event_ids"] != list(protocol.validation_event_ids):
        raise EconomicEvaluationAdmissionError(
            "legacy validation report event partition does not match protocol"
        )
    try:
        result = validate_economic_validation_result(values["result"])
    except (TypeError, ValueError) as exc:
        raise EconomicEvaluationAdmissionError("legacy validation report result is invalid") from exc
    if require_legacy_result and type(result) is not LegacyEconomicValidationResult:
        raise EconomicEvaluationAdmissionError("legacy validation report result schema is invalid")
    if not require_legacy_result and type(result) is not EconomicValidationResult:
        raise EconomicEvaluationAdmissionError("legacy validation report result schema is invalid")
    if (
        result.protocol_id != protocol.protocol_id
        or result.validation_event_ids != protocol.validation_event_ids
        or values["result_id"] != result.result_id
        or values["result_sha256"] != result.result_sha256
        or _canonical_json_bytes(values["result"]) != result.canonical_json_bytes()
    ):
        raise EconomicEvaluationAdmissionError(
            "legacy validation report result does not bind protocol output"
        )
    _require_authority(values, label="legacy_validation_report")
    if not allow_legacy:
        raise EconomicEvaluationAdmissionError(
            "legacy validation reports are readable but nonqualifying"
        )
    return values


def _admission_from_envelope(
    envelope: EvidenceEnvelope,
    *,
    created: bool,
) -> EconomicEvaluationProtocolAdmission:
    payload = _payload_mapping(envelope.payload, label="admission payload")
    predecessor = _payload_mapping(
        payload.get("store_predecessor"), label="store_predecessor"
    )
    return EconomicEvaluationProtocolAdmission(
        envelope=envelope,
        created=created,
        protocol_id=payload["protocol_id"],  # type: ignore[arg-type]
        input_manifest_sha256=payload["input_manifest_sha256"],  # type: ignore[arg-type]
        predecessor_sequence=predecessor["sequence"],  # type: ignore[arg-type]
        predecessor_event_sha256=predecessor["event_sha256"],  # type: ignore[arg-type]
    )


def _holdout_release_from_envelope(
    envelope: EvidenceEnvelope,
    *,
    created: bool,
) -> EconomicHoldoutRelease:
    payload = _payload_mapping(envelope.payload, label="holdout release payload")
    predecessor = _payload_mapping(
        payload.get("store_predecessor"),
        label="holdout release predecessor",
    )
    return EconomicHoldoutRelease(
        envelope=envelope,
        created=created,
        protocol_id=payload["protocol_id"],  # type: ignore[arg-type]
        protocol_admission_object_id=payload[
            "protocol_admission_object_id"
        ],  # type: ignore[arg-type]
        validation_run_object_id=payload["validation_run_object_id"],  # type: ignore[arg-type]
        predecessor_sequence=predecessor["sequence"],  # type: ignore[arg-type]
        predecessor_event_sha256=predecessor["event_sha256"],  # type: ignore[arg-type]
    )


def _event_sha256(event: EvidenceEvent) -> str:
    return hashlib.sha256(event.canonical_json_bytes()).hexdigest()


def _current_predecessor(events: tuple[EvidenceEvent, ...]) -> dict[str, object]:
    if not events:
        return {
            "sequence": 0,
            "object_id": None,
            "event_sha256": _ZERO_HASH,
        }
    event = events[-1]
    return {
        "sequence": event.sequence,
        "object_id": event.object_id,
        "event_sha256": _event_sha256(event),
    }


def _reject_orphaned_economic_evidence(
    orphans: tuple[EvidenceEnvelope, ...],
    _envelope: EvidenceEnvelope,
) -> None:
    economic_kinds = {
        ECONOMIC_EVALUATION_PROTOCOL_KIND,
        ECONOMIC_EVALUATION_RUN_KIND,
        ECONOMIC_HOLDOUT_RELEASE_KIND,
    }
    if any(orphan.kind in economic_kinds for orphan in orphans):
        raise EconomicEvaluationAdmissionError(
            "orphaned economic evidence must not be adopted"
        )


def _validate_historical_predecessor(
    payload: Mapping[str, object],
    *,
    envelope: EvidenceEnvelope,
    events: tuple[EvidenceEvent, ...],
) -> None:
    predecessor = _payload_mapping(
        payload.get("store_predecessor"),
        label="store_predecessor",
    )
    if set(predecessor) != {"sequence", "object_id", "event_sha256"}:
        raise EconomicEvaluationAdmissionError("store_predecessor fields are invalid")
    sequence = predecessor["sequence"]
    if type(sequence) is not int or sequence < 0:
        raise EconomicEvaluationAdmissionError("store_predecessor sequence is invalid")
    by_object_id = {event.object_id: event for event in events}
    current = by_object_id.get(envelope.object_id)
    if current is None:
        raise EconomicEvaluationAdmissionError("admission envelope is missing from journal")
    if current.sequence != sequence + 1:
        raise EconomicEvaluationAdmissionError("admission journal sequence is inconsistent")
    if sequence == 0:
        if predecessor["object_id"] is not None or predecessor["event_sha256"] != _ZERO_HASH:
            raise EconomicEvaluationAdmissionError("empty predecessor binding is invalid")
        if current.previous_event_sha256 != _ZERO_HASH:
            raise EconomicEvaluationAdmissionError("first journal event predecessor is invalid")
        return
    if sequence > len(events):
        raise EconomicEvaluationAdmissionError("store_predecessor sequence is not in journal")
    previous = events[sequence - 1]
    if (
        predecessor["object_id"] != previous.object_id
        or predecessor["event_sha256"] != _event_sha256(previous)
        or current.previous_event_sha256 != _event_sha256(previous)
    ):
        raise EconomicEvaluationAdmissionError("store_predecessor does not bind journal history")


def _receipt_value(receipt: object, *, label: str) -> object:
    if type(receipt) is not list or not receipt or len(receipt) > _MAX_RECEIPT_CHUNKS:
        raise EconomicEvaluationAdmissionError(
            f"{label} receipt chunks are invalid"
        )
    if any(type(chunk) is not str for chunk in receipt):
        raise EconomicEvaluationAdmissionError(f"{label} receipt chunks are invalid")
    if any(
        len(chunk) != _PROTOCOL_RECEIPT_CHUNK_CHARS
        for chunk in receipt[:-1]
    ) or not 1 <= len(receipt[-1]) <= _PROTOCOL_RECEIPT_CHUNK_CHARS:
        raise EconomicEvaluationAdmissionError(f"{label} receipt chunks are invalid")
    encoded_chars = sum(len(chunk) for chunk in receipt)
    if encoded_chars > _MAX_RECEIPT_ENCODED_CHARS:
        raise EconomicEvaluationAdmissionError(f"{label} receipt is too large")
    encoded = "".join(receipt)
    try:
        compressed = base64.b64decode(encoded, validate=True)
        if len(compressed) > _MAX_RECEIPT_COMPRESSED_BYTES:
            raise EconomicEvaluationAdmissionError(f"{label} receipt is too large")
        if base64.b64encode(compressed).decode("ascii") != encoded:
            raise EconomicEvaluationAdmissionError(
                f"{label} receipt base64 is not canonical"
            )
        decompressor = lzma.LZMADecompressor(
            format=lzma.FORMAT_XZ,
            memlimit=_RECEIPT_LZMA_MEMLIMIT_BYTES,
        )
        receipt_bytes = decompressor.decompress(
            compressed,
            max_length=_MAX_PROTOCOL_RECEIPT_BYTES + 1,
        )
        if (
            len(receipt_bytes) > _MAX_PROTOCOL_RECEIPT_BYTES
            or not decompressor.eof
            or decompressor.unused_data
        ):
            raise EconomicEvaluationAdmissionError(
                f"{label} receipt compression is invalid"
            )
        value = json.loads(
            receipt_bytes.decode("utf-8"),
            parse_constant=_reject_json_constant,
        )
    except (
        binascii.Error,
        lzma.LZMAError,
        UnicodeError,
        json.JSONDecodeError,
        RecursionError,
        TypeError,
        ValueError,
    ) as exc:
        raise EconomicEvaluationAdmissionError(f"{label} receipt is invalid") from exc
    try:
        canonical_bytes = _canonical_json_bytes(value)
    except (RecursionError, TypeError, ValueError, UnicodeError) as exc:
        raise EconomicEvaluationAdmissionError(f"{label} receipt is invalid") from exc
    if receipt_bytes != canonical_bytes:
        raise EconomicEvaluationAdmissionError(
            f"{label} receipt is not canonical JSON"
        )
    if receipt != _receipt_chunks(value):
        raise EconomicEvaluationAdmissionError(
            f"{label} receipt encoding is not canonical"
        )
    return value


def _validation_report_receipt_value(value: object, *, label: str) -> object:
    if isinstance(value, Mapping):
        legacy = _thaw_json(value)
        if (
            isinstance(legacy, Mapping)
            and legacy.get("schema_version") == ECONOMIC_VALIDATION_REPORT_SCHEMA
        ):
            raise EconomicEvaluationAdmissionError(
                f"{label} current report must use a receipt"
            )
        return legacy
    return _receipt_value(value, label=label)


def _protocol_from_receipt(protocol_receipt: object) -> FrozenEvaluationProtocol:
    protocol = validate_frozen_evaluation_protocol(
        _receipt_value(protocol_receipt, label="admitted protocol")
    )
    return protocol


def _admitted_protocol_from_envelope(
    envelope: EvidenceEnvelope,
    *,
    events: tuple[EvidenceEvent, ...],
) -> FrozenEvaluationProtocol:
    if envelope.kind != ECONOMIC_EVALUATION_PROTOCOL_KIND:
        raise EconomicEvaluationAdmissionError("admitted protocol envelope kind is invalid")
    payload = _payload_mapping(
        _thaw_json(envelope.payload),
        label="admitted protocol payload",
    )
    if set(payload) != _PROTOCOL_ADMISSION_FIELDS:
        raise EconomicEvaluationAdmissionError("admitted protocol fields are invalid")
    if payload.get("schema_version") != ECONOMIC_EVALUATION_PROTOCOL_ADMISSION_SCHEMA:
        raise EconomicEvaluationAdmissionError("admitted protocol schema is invalid")
    _require_authority(payload, label="admitted protocol")
    protocol = _protocol_from_receipt(payload.get("protocol"))
    if payload.get("protocol_id") != protocol.protocol_id:
        raise EconomicEvaluationAdmissionError("admitted protocol identity is inconsistent")
    for field_name in (
        "cohort_id",
        "cohort_sha256",
        "partition_id",
        "partition_sha256",
        "input_manifest_id",
        "input_manifest_sha256",
        "evaluation_policy_sha256",
        "primary_universe_sha256",
        "sensitivity_universe_50_sha256",
        "sensitivity_universe_100_sha256",
    ):
        if payload.get(field_name) != getattr(protocol, field_name):
            raise EconomicEvaluationAdmissionError(
                "admitted protocol redundant binding is inconsistent"
            )
    source_manifest = _thaw_json(payload.get("source_manifest"))
    if not isinstance(source_manifest, list) or not source_manifest:
        raise EconomicEvaluationAdmissionError("admitted source manifest is invalid")
    source_paths: list[str] = []
    for row in source_manifest:
        row_mapping = _payload_mapping(row, label="admitted source manifest row")
        if set(row_mapping) != _SOURCE_MANIFEST_ROW_FIELDS:
            raise EconomicEvaluationAdmissionError("admitted source manifest row is invalid")
        source_path = row_mapping["path"]
        if (
            type(source_path) is not str
            or not source_path
            or source_path.startswith("/")
            or "\\" in source_path
            or Path(source_path).as_posix() != source_path
        ):
            raise EconomicEvaluationAdmissionError("admitted source manifest path is invalid")
        if any(part in {"", ".", ".."} for part in Path(source_path).parts):
            raise EconomicEvaluationAdmissionError("admitted source manifest path is invalid")
        if _SHA256.fullmatch(row_mapping["sha256"]) is None:
            raise EconomicEvaluationAdmissionError("admitted source manifest digest is invalid")
        source_paths.append(source_path)
    if source_paths != sorted(source_paths) or len(source_paths) != len(set(source_paths)):
        raise EconomicEvaluationAdmissionError("admitted source manifest order is invalid")
    if _sha256(source_manifest) != payload.get("source_manifest_sha256"):
        raise EconomicEvaluationAdmissionError("admitted source manifest digest is invalid")
    _require_source_revision(payload.get("source_revision"))
    _validate_historical_predecessor(payload, envelope=envelope, events=events)
    return protocol


def _evaluation_run_from_envelope(
    envelope: EvidenceEnvelope,
    *,
    protocol: FrozenEvaluationProtocol,
    protocol_admission_object_id: str,
    events: tuple[EvidenceEvent, ...],
) -> EconomicEvaluationRun:
    if envelope.kind != ECONOMIC_EVALUATION_RUN_KIND:
        raise EconomicEvaluationAdmissionError("evaluation-run envelope kind is invalid")
    payload = _payload_mapping(
        _thaw_json(envelope.payload),
        label="evaluation-run payload",
    )
    expected_fields = {
        "schema_version",
        "protocol_id",
        "protocol_admission_object_id",
        "phase",
        "frozen_validation_report",
        "validation_report_sha256",
        "store_predecessor",
        *_AUTHORITY_FIELDS,
    }
    if set(payload) != expected_fields:
        raise EconomicEvaluationAdmissionError("evaluation-run fields are invalid")
    if payload["schema_version"] != ECONOMIC_EVALUATION_RUN_SCHEMA:
        raise EconomicEvaluationAdmissionError("evaluation-run schema is invalid")
    if _require_protocol_id(payload["protocol_id"]) != protocol.protocol_id:
        raise EconomicEvaluationAdmissionError("evaluation-run protocol does not match")
    if payload["protocol_admission_object_id"] != protocol_admission_object_id:
        raise EconomicEvaluationAdmissionError(
            "evaluation-run admitted protocol identity does not match"
        )
    if payload["phase"] not in {"development", "validation", "holdout"}:
        raise EconomicEvaluationAdmissionError("evaluation-run phase is invalid")
    report = _frozen_report_for_phase(
        _validation_report_receipt_value(
            payload["frozen_validation_report"],
            label="evaluation-run validation report",
        ),
        protocol=protocol,
        phase=payload["phase"],
        allow_legacy=True,
    )
    if payload["validation_report_sha256"] != _sha256(report):
        raise EconomicEvaluationAdmissionError("evaluation-run report digest is invalid")
    _require_authority(payload, label="evaluation-run")
    _validate_historical_predecessor(payload, envelope=envelope, events=events)
    return EconomicEvaluationRun(
        envelope=envelope,
        created=False,
        protocol_id=payload["protocol_id"],  # type: ignore[arg-type]
        phase=payload["phase"],  # type: ignore[arg-type]
        protocol_admission_object_id=payload[
            "protocol_admission_object_id"
        ],  # type: ignore[arg-type]
        predecessor_sequence=_payload_mapping(
            payload["store_predecessor"],
            label="evaluation-run predecessor",
        )["sequence"],  # type: ignore[arg-type]
        predecessor_event_sha256=_payload_mapping(
            payload["store_predecessor"],
            label="evaluation-run predecessor",
        )["event_sha256"],  # type: ignore[arg-type]
    )


def _validate_holdout_release_payload(
    payload: Mapping[str, object],
    *,
    protocol: FrozenEvaluationProtocol,
    protocol_admission_object_id: str,
    validation_run_object_id: str,
    allow_legacy: bool = False,
) -> None:
    expected_fields = {
        "schema_version",
        "protocol_id",
        "protocol_admission_object_id",
        "validation_run_object_id",
        "released_by",
        "released_at",
        "frozen_validation_report",
        "validation_report_sha256",
        "store_predecessor",
        *_AUTHORITY_FIELDS,
    }
    if set(payload) != expected_fields:
        raise EconomicEvaluationAdmissionError("holdout release fields are invalid")
    if payload["schema_version"] != ECONOMIC_HOLDOUT_RELEASE_SCHEMA:
        raise EconomicEvaluationAdmissionError("holdout release schema is invalid")
    if _require_protocol_id(payload["protocol_id"]) != protocol.protocol_id:
        raise EconomicEvaluationAdmissionError("holdout release protocol does not match")
    if payload["protocol_admission_object_id"] != protocol_admission_object_id:
        raise EconomicEvaluationAdmissionError(
            "holdout release admitted protocol identity does not match"
        )
    if payload["validation_run_object_id"] != validation_run_object_id:
        raise EconomicEvaluationAdmissionError(
            "holdout release validation-run identity does not match"
        )
    _require_owner(payload["released_by"])
    _canonical_timestamp_text(payload["released_at"], label="released_at")
    report = _frozen_validation_report(
        _validation_report_receipt_value(
            payload["frozen_validation_report"],
            label="holdout validation report",
        ),
        protocol=protocol,
        allow_legacy=allow_legacy,
    )
    if payload["validation_report_sha256"] != _sha256(report):
        raise EconomicEvaluationAdmissionError("holdout validation report digest is invalid")
    predecessor = _payload_mapping(
        payload["store_predecessor"],
        label="holdout release predecessor",
    )
    if set(predecessor) != {"sequence", "object_id", "event_sha256"}:
        raise EconomicEvaluationAdmissionError("holdout predecessor fields are invalid")
    if type(predecessor["sequence"]) is not int or predecessor["sequence"] < 1:
        raise EconomicEvaluationAdmissionError("holdout predecessor sequence is invalid")
    if type(predecessor["object_id"]) is not str:
        raise EconomicEvaluationAdmissionError("holdout predecessor object is invalid")
    if _SHA256.fullmatch(predecessor["event_sha256"]) is None:
        raise EconomicEvaluationAdmissionError("holdout predecessor digest is invalid")
    _require_authority(payload, label="holdout release")


class EconomicEvaluationAdmissionAdapter:
    """Admit a frozen protocol only with source and journal provenance pinned."""

    def __init__(
        self,
        evidence_root: str | Path,
        *,
        repo_root: str | Path,
        clock: Callable[[], dt.datetime] | None = None,
    ) -> None:
        self._repo_root = _canonical_repo_root(repo_root)
        self._store = ImmutableStrategyEvidenceStore(evidence_root, clock=clock)
        self._tournament_archive = EconomicTournamentReceiptArchive(
            Path(evidence_root).expanduser().absolute() / "_tournament_receipts"
        )

    def _reopen_tournament_input(
        self,
        *,
        protocol: FrozenEvaluationProtocol,
        report: Mapping[str, object],
    ) -> SourceBoundTournamentInput | None:
        """Reopen complete current receipts; legacy reports remain nonqualifying."""

        if report.get("schema_version") != ECONOMIC_VALIDATION_REPORT_SCHEMA:
            return None
        if report.get("qualification_status") is not None:
            return None
        eligibility = bind_validation_phase_eligibility(
            protocol=protocol,
            partitions=validate_market_date_partitions(report["market_date_partitions"]),
        )
        reference = _tournament_input_reference(report["tournament_input"])
        try:
            return self._tournament_archive.reopen(
                input_id=reference["input_id"],
                input_sha256=reference["input_sha256"],
                protocol=protocol,
                eligibility=eligibility,
            )
        except (OSError, TypeError, ValueError) as exc:
            raise EconomicEvaluationAdmissionError(
                "complete tournament receipt custody is not qualifying"
            ) from exc

    def _reopen_phase_tournament_input(
        self,
        *,
        protocol: FrozenEvaluationProtocol,
        report: Mapping[str, object],
    ) -> SourceBoundTournamentInput | None:
        """Reopen a qualifying development or holdout receipt from custody."""

        if report.get("schema_version") != ECONOMIC_PHASE_REPORT_SCHEMA:
            return None
        if report.get("qualification_status") is not None:
            return None
        phase = report.get("phase")
        if phase not in {"development", "holdout"}:
            raise EconomicEvaluationAdmissionError("phase receipt phase is invalid")
        try:
            eligibility = bind_phase_eligibility(
                protocol=protocol,
                partitions=validate_market_date_partitions(report["market_date_partitions"]),
                phase=phase,
            )
            reference = _tournament_input_reference(report["tournament_input"])
            return self._tournament_archive.reopen(
                input_id=reference["input_id"],
                input_sha256=reference["input_sha256"],
                protocol=protocol,
                eligibility=eligibility,
            )
        except (OSError, TypeError, ValueError) as exc:
            raise EconomicEvaluationAdmissionError(
                "complete phase tournament receipt custody is not qualifying"
            ) from exc

    def admit_protocol(
        self,
        protocol: FrozenEvaluationProtocol,
        *,
        source_revision: str,
        effective_at: dt.datetime,
        source_paths: tuple[str, ...],
    ) -> EconomicEvaluationProtocolAdmission:
        """Persist one canonical protocol record or return the exact prior one.

        The predecessor is captured before candidate creation and checked again
        inside the store transaction.  A second source preflight rejects bytes
        changed during admission preparation.
        """

        if type(protocol) is not FrozenEvaluationProtocol:
            raise EconomicEvaluationAdmissionError(
                "protocol must be an exact FrozenEvaluationProtocol"
            )
        try:
            rebuilt = validate_frozen_evaluation_protocol(protocol.to_dict())
        except (TypeError, ValueError) as exc:
            raise EconomicEvaluationAdmissionError("protocol canonical validation failed") from exc
        if rebuilt.canonical_json_bytes() != protocol.canonical_json_bytes():
            raise EconomicEvaluationAdmissionError("protocol bytes do not round trip exactly")
        revision = _require_source_revision(source_revision)
        effective_text = _canonical_effective_at(effective_at)
        source_rows, source_manifest_sha256 = _source_manifest(
            self._repo_root,
            source_paths,
        )
        _bind_source_revision_to_manifest(
            self._repo_root,
            revision=revision,
            source_rows=source_rows,
        )

        snapshot, events = self._store.verify_with_events()
        predecessor = _current_predecessor(events)
        for existing in snapshot:
            if existing.kind != ECONOMIC_EVALUATION_PROTOCOL_KIND:
                continue
            existing_payload = _payload_mapping(
                existing.payload,
                label="existing admission payload",
            )
            existing_protocol = _admitted_protocol_from_envelope(
                existing,
                events=events,
            )
            if existing_payload.get("protocol_id") != protocol.protocol_id:
                receipt_identity = (
                    existing_protocol.cohort_id,
                    existing_protocol.cohort_sha256,
                    existing_protocol.partition_id,
                    existing_protocol.partition_sha256,
                )
                submitted_identity = (
                    protocol.cohort_id,
                    protocol.cohort_sha256,
                    protocol.partition_id,
                    protocol.partition_sha256,
                )
                if (
                    existing_protocol.input_manifest_id == protocol.input_manifest_id
                    and receipt_identity != submitted_identity
                ):
                    raise EconomicEvaluationAdmissionError(
                        "input manifest is already bound to a different cohort "
                        "or partition receipt"
                    )
                continue
            if (
                existing_protocol.canonical_json_bytes()
                != protocol.canonical_json_bytes()
            ):
                raise EconomicEvaluationAdmissionError(
                    "protocol identity is already bound to different bytes"
                )
            expected_existing = {
                "protocol": _protocol_receipt_chunks(protocol),
                "protocol_id": protocol.protocol_id,
                "cohort_id": protocol.cohort_id,
                "cohort_sha256": protocol.cohort_sha256,
                "partition_id": protocol.partition_id,
                "partition_sha256": protocol.partition_sha256,
                "input_manifest_id": protocol.input_manifest_id,
                "input_manifest_sha256": protocol.input_manifest_sha256,
                "source_revision": revision,
                "source_manifest": source_rows,
                "source_manifest_sha256": source_manifest_sha256,
            }
            actual_existing = {
                key: existing_payload.get(key) for key in expected_existing
            }
            if _canonical_json_bytes(actual_existing) != _canonical_json_bytes(
                expected_existing
            ):
                raise EconomicEvaluationAdmissionError(
                    "protocol identity is already bound to different provenance"
                )
            return _admission_from_envelope(existing, created=False)

        material: dict[str, object] = {
            "schema_version": ECONOMIC_EVALUATION_PROTOCOL_ADMISSION_SCHEMA,
            "protocol": _protocol_receipt_chunks(protocol),
            "protocol_id": protocol.protocol_id,
            "cohort_id": protocol.cohort_id,
            "cohort_sha256": protocol.cohort_sha256,
            "partition_id": protocol.partition_id,
            "partition_sha256": protocol.partition_sha256,
            "input_manifest_id": protocol.input_manifest_id,
            "input_manifest_sha256": protocol.input_manifest_sha256,
            "evaluation_policy_sha256": protocol.evaluation_policy_sha256,
            "primary_universe_sha256": protocol.primary_universe_sha256,
            "sensitivity_universe_50_sha256": protocol.sensitivity_universe_50_sha256,
            "sensitivity_universe_100_sha256": protocol.sensitivity_universe_100_sha256,
            "source_revision": revision,
            "source_manifest": source_rows,
            "source_manifest_sha256": source_manifest_sha256,
            "store_predecessor": {
                **predecessor,
            },
            **_AUTHORITY_FIELDS,
        }
        second_rows, second_manifest_sha256 = _source_manifest(
            self._repo_root,
            source_paths,
        )
        if (
            second_manifest_sha256 != source_manifest_sha256
            or _canonical_json_bytes(second_rows) != _canonical_json_bytes(source_rows)
        ):
            raise EconomicEvaluationAdmissionError(
                "source bytes changed during admission preflight"
            )
        candidate = EvidenceCandidate(
            kind=ECONOMIC_EVALUATION_PROTOCOL_KIND,
            effective_at=effective_text,
            payload=material,
        )

        def validate(
            current_snapshot: tuple[EvidenceEnvelope, ...],
            envelope: EvidenceEnvelope,
        ) -> None:
            if len(current_snapshot) != predecessor["sequence"]:
                raise EconomicEvaluationAdmissionError(
                    "immutable evidence-store head changed during admission"
                )
            if predecessor["sequence"] == 0:
                if current_snapshot or predecessor["object_id"] is not None:
                    raise EconomicEvaluationAdmissionError("invalid empty evidence-store head")
                if predecessor["event_sha256"] != _ZERO_HASH:
                    raise EconomicEvaluationAdmissionError("invalid empty predecessor digest")
            elif (
                not current_snapshot
                or current_snapshot[-1].object_id != predecessor["object_id"]
            ):
                raise EconomicEvaluationAdmissionError(
                    "immutable evidence-store predecessor does not match"
                )
            submitted = _payload_mapping(
                _thaw_json(envelope.payload),
                label="admission payload",
            )
            if _canonical_json_bytes(submitted) != _canonical_json_bytes(material):
                raise EconomicEvaluationAdmissionError("admission payload is not exact")
            try:
                persisted = _protocol_from_receipt(submitted["protocol"])
            except (KeyError, TypeError, ValueError) as exc:
                raise EconomicEvaluationAdmissionError(
                    "persisted protocol validation failed"
                ) from exc
            if persisted.canonical_json_bytes() != protocol.canonical_json_bytes():
                raise EconomicEvaluationAdmissionError("persisted protocol bytes are not exact")
            for prior in current_snapshot:
                if prior.kind != ECONOMIC_EVALUATION_PROTOCOL_KIND:
                    continue
                prior_payload = _payload_mapping(
                    prior.payload,
                    label="prior admission payload",
                )
                if prior_payload.get("protocol_id") == protocol.protocol_id:
                    raise EconomicEvaluationAdmissionError(
                        "protocol identity is already admitted"
                    )

        try:
            admission = self._store.admit_checked(
                candidate,
                validate=validate,
                validate_orphans=_reject_orphaned_economic_evidence,
            )
        except EconomicEvaluationAdmissionError:
            raise
        except (TypeError, ValueError) as exc:
            raise EconomicEvaluationAdmissionError("protocol admission failed") from exc
        return _admission_from_envelope(admission.envelope, created=admission.created)

    def admit_evaluation_run(
        self,
        protocol_id: str,
        *,
        phase: str,
        effective_at: dt.datetime,
        frozen_validation_report: Mapping[str, object],
        pit_artifact_root: str | Path,
        tournament_input: SourceBoundTournamentInput | None = None,
    ) -> EconomicEvaluationRun:
        """Admit a completed validation result before any holdout release."""

        identity = _require_protocol_id(protocol_id)
        if phase not in {"development", "validation", "holdout"}:
            raise EconomicEvaluationAdmissionError(
                "phase must be development, validation, or holdout"
            )
        effective_text = _canonical_effective_at(effective_at)
        snapshot, events = self._store.verify_with_events()
        predecessor = _current_predecessor(events)
        admitted_pairs = [
            (
                envelope,
                _admitted_protocol_from_envelope(envelope, events=events),
            )
            for envelope in snapshot
            if envelope.kind == ECONOMIC_EVALUATION_PROTOCOL_KIND
        ]
        matches = [
            (envelope, protocol)
            for envelope, protocol in admitted_pairs
            if protocol.protocol_id == identity
        ]
        if len(matches) != 1:
            raise EconomicEvaluationAdmissionError(
                "evaluation-run requires exactly one admitted protocol"
            )
        protocol_envelope, protocol = matches[0]
        if phase == "holdout" and not self.is_holdout_released(identity):
            raise EconomicEvaluationAdmissionError(
                "holdout evaluation requires an immutable qualifying release"
            )
        report = _frozen_report_for_phase(
            frozen_validation_report,
            protocol=protocol,
            phase=phase,
        )
        if type(tournament_input) is not SourceBoundTournamentInput:
            raise EconomicEvaluationAdmissionError(
                "evaluation-run requires one verified source-bound tournament input"
            )
        try:
            partitions = validate_market_date_partitions(report["market_date_partitions"])
            eligibility = (
                bind_validation_phase_eligibility(protocol=protocol, partitions=partitions)
                if phase == "validation"
                else bind_phase_eligibility(
                    protocol=protocol, partitions=partitions, phase=phase
                )
            )
            verified_input = verify_source_bound_tournament_input(
                archive=RawPointInTimeArtifactArchive(pit_artifact_root),
                value=tournament_input.to_dict(),
                protocol=protocol,
                eligibility=eligibility,
            )
            self._tournament_archive.admit(
                verified_input,
                pit_artifact_root=pit_artifact_root,
            )
            verified_input = self._tournament_archive.reopen(
                input_id=verified_input.input_id,
                input_sha256=verified_input.input_sha256,
                protocol=protocol,
                eligibility=eligibility,
            )
        except (OSError, TypeError, ValueError) as exc:
            raise EconomicEvaluationAdmissionError(
                "evaluation-run tournament input archive verification failed"
            ) from exc
        if (
            report["tournament_input"]
            != {
                "input_id": verified_input.input_id,
                "input_sha256": verified_input.input_sha256,
            }
        ):
            raise EconomicEvaluationAdmissionError(
                "evaluation-run tournament input does not match report identity"
            )
        report_sha256 = _sha256(report)
        for existing in snapshot:
            if existing.kind != ECONOMIC_EVALUATION_RUN_KIND:
                continue
            existing_payload = _payload_mapping(
                existing.payload,
                label="existing evaluation-run payload",
            )
            if (
                existing_payload.get("protocol_id") != identity
                or existing_payload.get("phase") != phase
            ):
                continue
            existing_run = _evaluation_run_from_envelope(
                existing,
                protocol=protocol,
                protocol_admission_object_id=protocol_envelope.object_id,
                events=events,
            )
            expected_existing = {
                "protocol_id": identity,
                "protocol_admission_object_id": protocol_envelope.object_id,
                "phase": phase,
                "frozen_validation_report": _receipt_chunks(report),
                "validation_report_sha256": report_sha256,
            }
            actual_existing = {
                key: existing_payload.get(key) for key in expected_existing
            }
            if _canonical_json_bytes(actual_existing) != _canonical_json_bytes(
                expected_existing
            ):
                raise EconomicEvaluationAdmissionError(
                    "validation phase is already bound to different results"
                )
            return EconomicEvaluationRun(
                envelope=existing_run.envelope,
                created=False,
                protocol_id=existing_run.protocol_id,
                phase=existing_run.phase,
                protocol_admission_object_id=existing_run.protocol_admission_object_id,
                predecessor_sequence=existing_run.predecessor_sequence,
                predecessor_event_sha256=existing_run.predecessor_event_sha256,
            )

        material: dict[str, object] = {
            "schema_version": ECONOMIC_EVALUATION_RUN_SCHEMA,
            "protocol_id": identity,
            "protocol_admission_object_id": protocol_envelope.object_id,
            "phase": phase,
            "frozen_validation_report": _receipt_chunks(report),
            "validation_report_sha256": report_sha256,
            "store_predecessor": {**predecessor},
            **_AUTHORITY_FIELDS,
        }
        candidate = EvidenceCandidate(
            kind=ECONOMIC_EVALUATION_RUN_KIND,
            effective_at=effective_text,
            payload=material,
        )

        def validate(
            current_snapshot: tuple[EvidenceEnvelope, ...],
            envelope: EvidenceEnvelope,
        ) -> None:
            if (
                len(current_snapshot) != predecessor["sequence"]
                or (
                    predecessor["sequence"] == 0
                    and (current_snapshot or predecessor["object_id"] is not None)
                )
                or (
                    predecessor["sequence"] != 0
                    and (
                        not current_snapshot
                        or current_snapshot[-1].object_id
                        != predecessor["object_id"]
                    )
                )
            ):
                raise EconomicEvaluationAdmissionError(
                    "immutable evidence-store head changed during evaluation-run admission"
                )
            prior_protocols = [
                item
                for item in current_snapshot
                if item.object_id == protocol_envelope.object_id
            ]
            if len(prior_protocols) != 1 or (
                prior_protocols[0].canonical_json_bytes()
                != protocol_envelope.canonical_json_bytes()
            ):
                raise EconomicEvaluationAdmissionError(
                    "admitted protocol changed before evaluation-run admission"
                )
            submitted = _payload_mapping(
                _thaw_json(envelope.payload),
                label="evaluation-run payload",
            )
            if _canonical_json_bytes(submitted) != _canonical_json_bytes(material):
                raise EconomicEvaluationAdmissionError("evaluation-run payload is not exact")
            submitted_report = _frozen_report_for_phase(
                _validation_report_receipt_value(
                    submitted["frozen_validation_report"],
                    label="evaluation-run validation report",
                ),
                protocol=protocol,
                phase=phase,
            )
            reopened = (
                self._reopen_tournament_input(
                    protocol=protocol,
                    report=submitted_report,
                )
                if phase == "validation"
                else self._reopen_phase_tournament_input(
                    protocol=protocol,
                    report=submitted_report,
                )
            )
            if reopened is None and submitted_report.get("qualification_status") is None:
                raise EconomicEvaluationAdmissionError(
                    "current evaluation-run receipt is not qualifying"
                )
            if any(
                item.kind == ECONOMIC_EVALUATION_RUN_KIND
                and _payload_mapping(item.payload, label="prior evaluation-run payload").get(
                    "protocol_id"
                )
                == identity
                and _payload_mapping(item.payload, label="prior evaluation-run payload").get(
                    "phase"
                )
                == phase
                for item in current_snapshot
            ):
                raise EconomicEvaluationAdmissionError(
                    "validation phase is already admitted"
                )

        try:
            admission = self._store.admit_checked(
                candidate,
                validate=validate,
                validate_orphans=_reject_orphaned_economic_evidence,
            )
        except EconomicEvaluationAdmissionError:
            raise
        except (TypeError, ValueError) as exc:
            raise EconomicEvaluationAdmissionError("evaluation-run admission failed") from exc
        verified_snapshot, verified_events = self._store.verify_with_events()
        persisted = next(
            (
                item
                for item in verified_snapshot
                if item.object_id == admission.envelope.object_id
            ),
            None,
        )
        if persisted is None:
            raise EconomicEvaluationAdmissionError(
                "admitted evaluation-run cannot be read back"
            )
        validated = _evaluation_run_from_envelope(
            persisted,
            protocol=protocol,
            protocol_admission_object_id=protocol_envelope.object_id,
            events=verified_events,
        )
        persisted_payload = _payload_mapping(
            _thaw_json(persisted.payload),
            label="persisted evaluation-run payload",
        )
        persisted_report = _frozen_report_for_phase(
            _validation_report_receipt_value(
                persisted_payload["frozen_validation_report"],
                label="persisted evaluation-run validation report",
            ),
            protocol=protocol,
            phase=phase,
        )
        reopened_persisted = (
            self._reopen_tournament_input(
                protocol=protocol,
                report=persisted_report,
            )
            if phase == "validation"
            else self._reopen_phase_tournament_input(
                protocol=protocol,
                report=persisted_report,
            )
        )
        if reopened_persisted is None and persisted_report.get("qualification_status") is None:
            raise EconomicEvaluationAdmissionError(
                "persisted evaluation-run receipt is not qualifying"
            )
        return EconomicEvaluationRun(
            envelope=validated.envelope,
            created=admission.created,
            protocol_id=validated.protocol_id,
            phase=validated.phase,
            protocol_admission_object_id=validated.protocol_admission_object_id,
            predecessor_sequence=validated.predecessor_sequence,
            predecessor_event_sha256=validated.predecessor_event_sha256,
        )

    def readiness_status(self, protocol_id: str) -> EconomicEvaluationReadiness:
        """Read one protocol's immutable admission state without opening holdout rows."""

        identity = _require_protocol_id(protocol_id)
        snapshot, events = self._store.verify_with_events()
        predecessor = _current_predecessor(events)
        admitted_pairs = [
            (
                envelope,
                _admitted_protocol_from_envelope(envelope, events=events),
            )
            for envelope in snapshot
            if envelope.kind == ECONOMIC_EVALUATION_PROTOCOL_KIND
        ]
        matches = [
            (envelope, protocol)
            for envelope, protocol in admitted_pairs
            if protocol.protocol_id == identity
        ]
        if len(matches) > 1:
            raise EconomicEvaluationAdmissionError(
                "protocol identity has more than one immutable admission"
            )
        if not matches:
            return EconomicEvaluationReadiness(
                protocol_id=identity,
                protocol_admission_object_id=None,
                development_run_object_id=None,
                validation_run_object_id=None,
                holdout_release_object_id=None,
                holdout_run_object_id=None,
                evidence_sequence=predecessor["sequence"],  # type: ignore[arg-type]
                evidence_head_event_sha256=predecessor["event_sha256"],  # type: ignore[arg-type]
            )
        protocol_envelope, protocol = matches[0]
        development_runs = [
            _evaluation_run_from_envelope(
                envelope,
                protocol=protocol,
                protocol_admission_object_id=protocol_envelope.object_id,
                events=events,
            )
            for envelope in snapshot
            if envelope.kind == ECONOMIC_EVALUATION_RUN_KIND
            and _payload_mapping(envelope.payload, label="evaluation-run payload").get(
                "protocol_id"
            )
            == identity
            and _payload_mapping(envelope.payload, label="evaluation-run payload").get(
                "phase"
            )
            == "development"
        ]
        if len(development_runs) > 1:
            raise EconomicEvaluationAdmissionError(
                "protocol identity has more than one immutable development run"
            )
        validation_runs = [
            _evaluation_run_from_envelope(
                envelope,
                protocol=protocol,
                protocol_admission_object_id=protocol_envelope.object_id,
                events=events,
            )
            for envelope in snapshot
            if envelope.kind == ECONOMIC_EVALUATION_RUN_KIND
            and _payload_mapping(
                envelope.payload,
                label="evaluation-run payload",
            ).get("protocol_id")
            == identity
            and _payload_mapping(
                envelope.payload,
                label="evaluation-run payload",
            ).get("phase")
            == "validation"
        ]
        if len(validation_runs) > 1:
            raise EconomicEvaluationAdmissionError(
                "protocol identity has more than one immutable validation run"
            )
        validation_run = validation_runs[0] if validation_runs else None
        if validation_run is not None:
            run_payload = _payload_mapping(
                _thaw_json(validation_run.envelope.payload),
                label="readiness evaluation-run payload",
            )
            run_report = _frozen_validation_report(
                _validation_report_receipt_value(
                    run_payload["frozen_validation_report"],
                    label="readiness validation report",
                ),
                protocol=protocol,
                allow_legacy=True,
            )
            if self._reopen_tournament_input(
                protocol=protocol,
                report=run_report,
            ) is None:
                validation_run = None
        releases = [
            envelope
            for envelope in snapshot
            if envelope.kind == ECONOMIC_HOLDOUT_RELEASE_KIND
            and _payload_mapping(
                envelope.payload,
                label="holdout release payload",
            ).get("protocol_id")
            == identity
        ]
        if len(releases) > 1:
            raise EconomicEvaluationAdmissionError(
                "protocol identity has more than one immutable holdout release"
            )
        if releases and not validation_runs:
            raise EconomicEvaluationAdmissionError(
                "holdout release exists without an immutable validation run"
            )
        if releases and validation_run is None:
            releases = []
        if releases and not self.is_holdout_released(identity):
            raise EconomicEvaluationAdmissionError("holdout release is not fully validated")
        holdout_runs = [
            _evaluation_run_from_envelope(
                envelope,
                protocol=protocol,
                protocol_admission_object_id=protocol_envelope.object_id,
                events=events,
            )
            for envelope in snapshot
            if envelope.kind == ECONOMIC_EVALUATION_RUN_KIND
            and _payload_mapping(envelope.payload, label="evaluation-run payload").get(
                "protocol_id"
            )
            == identity
            and _payload_mapping(envelope.payload, label="evaluation-run payload").get(
                "phase"
            )
            == "holdout"
        ]
        if len(holdout_runs) > 1:
            raise EconomicEvaluationAdmissionError(
                "protocol identity has more than one immutable holdout run"
            )
        if holdout_runs and not releases:
            raise EconomicEvaluationAdmissionError(
                "holdout run exists without an immutable holdout release"
            )
        holdout_run = holdout_runs[0] if holdout_runs else None
        if holdout_run is not None:
            run_payload = _payload_mapping(
                _thaw_json(holdout_run.envelope.payload),
                label="readiness holdout-run payload",
            )
            report = _frozen_phase_report(
                _validation_report_receipt_value(
                    run_payload["frozen_validation_report"],
                    label="readiness holdout report",
                ),
                protocol=protocol,
            )
            if self._reopen_phase_tournament_input(
                protocol=protocol,
                report=report,
            ) is None:
                holdout_run = None
        return EconomicEvaluationReadiness(
            protocol_id=identity,
            protocol_admission_object_id=protocol_envelope.object_id,
            development_run_object_id=(
                development_runs[0].envelope.object_id if development_runs else None
            ),
            validation_run_object_id=(
                validation_run.envelope.object_id if validation_run is not None else None
            ),
            holdout_release_object_id=releases[0].object_id if releases else None,
            holdout_run_object_id=(
                holdout_run.envelope.object_id if holdout_run is not None else None
            ),
            evidence_sequence=predecessor["sequence"],  # type: ignore[arg-type]
            evidence_head_event_sha256=predecessor["event_sha256"],  # type: ignore[arg-type]
        )

    def frozen_validation_report(self, protocol_id: str) -> dict[str, object]:
        """Return the one validated immutable validation report for release binding."""

        identity = _require_protocol_id(protocol_id)
        readiness = self.readiness_status(identity)
        if readiness.protocol_admission_object_id is None:
            raise EconomicEvaluationAdmissionError(
                "validation report requires exactly one admitted protocol"
            )
        if readiness.validation_run_object_id is None:
            raise EconomicEvaluationAdmissionError(
                "validation report requires exactly one immutable validation run"
            )
        snapshot, events = self._store.verify_with_events()
        protocol_envelope = next(
            (
                envelope
                for envelope in snapshot
                if envelope.object_id == readiness.protocol_admission_object_id
            ),
            None,
        )
        validation_envelope = next(
            (
                envelope
                for envelope in snapshot
                if envelope.object_id == readiness.validation_run_object_id
            ),
            None,
        )
        if protocol_envelope is None or validation_envelope is None:
            raise EconomicEvaluationAdmissionError(
                "immutable validation evidence changed during read"
            )
        protocol = _admitted_protocol_from_envelope(protocol_envelope, events=events)
        run = _evaluation_run_from_envelope(
            validation_envelope,
            protocol=protocol,
            protocol_admission_object_id=protocol_envelope.object_id,
            events=events,
        )
        if run.protocol_id != identity:
            raise EconomicEvaluationAdmissionError("validation report binds a different protocol")
        payload = _payload_mapping(
            _thaw_json(validation_envelope.payload),
            label="evaluation-run payload",
        )
        report = _frozen_validation_report(
            _validation_report_receipt_value(
                payload["frozen_validation_report"],
                label="evaluation-run validation report",
            ),
            protocol=protocol,
        )
        if self._reopen_tournament_input(protocol=protocol, report=report) is None:
            raise EconomicEvaluationAdmissionError(
                "validation report does not reference qualifying tournament custody"
            )
        return report

    def release_holdout(
        self,
        protocol_id: str,
        *,
        released_by: str,
        released_at: dt.datetime,
        frozen_validation_report: Mapping[str, object],
    ) -> EconomicHoldoutRelease:
        """Release a sealed holdout only after a bound validation receipt.

        This method adds evidence only.  It provides neither execution nor
        promotion authority, and it never reads market data or submits orders.
        """

        identity = _require_protocol_id(protocol_id)
        owner = _require_owner(released_by)
        released_text = _canonical_effective_at(released_at)
        snapshot, events = self._store.verify_with_events()
        predecessor = _current_predecessor(events)
        admitted_pairs = [
            (
                envelope,
                _admitted_protocol_from_envelope(envelope, events=events),
            )
            for envelope in snapshot
            if envelope.kind == ECONOMIC_EVALUATION_PROTOCOL_KIND
        ]
        matches = [
            (envelope, protocol)
            for envelope, protocol in admitted_pairs
            if protocol.protocol_id == identity
        ]
        if len(matches) != 1:
            raise EconomicEvaluationAdmissionError(
                "holdout release requires exactly one admitted protocol"
            )
        protocol_envelope, protocol = matches[0]
        report = _frozen_validation_report(
            frozen_validation_report,
            protocol=protocol,
        )
        if self._reopen_tournament_input(protocol=protocol, report=report) is None:
            raise EconomicEvaluationAdmissionError(
                "holdout release requires qualifying tournament custody"
            )
        report_sha256 = _sha256(report)
        validation_runs = [
            _evaluation_run_from_envelope(
                envelope,
                protocol=protocol,
                protocol_admission_object_id=protocol_envelope.object_id,
                events=events,
            )
            for envelope in snapshot
            if envelope.kind == ECONOMIC_EVALUATION_RUN_KIND
            and _payload_mapping(
                envelope.payload,
                label="evaluation-run payload",
            ).get("protocol_id")
            == identity
        ]
        if len(validation_runs) != 1:
            raise EconomicEvaluationAdmissionError(
                "holdout release requires exactly one immutable validation run"
            )
        validation_run = validation_runs[0]
        run_report_receipt = _payload_mapping(
            _thaw_json(validation_run.envelope.payload),
            label="validation-run payload",
        )["frozen_validation_report"]
        run_report = _validation_report_receipt_value(
            run_report_receipt,
            label="evaluation-run validation report",
        )
        if _canonical_json_bytes(run_report) != _canonical_json_bytes(report):
            raise EconomicEvaluationAdmissionError(
                "holdout release report does not match immutable validation run"
            )
        for existing in snapshot:
            if existing.kind != ECONOMIC_HOLDOUT_RELEASE_KIND:
                continue
            existing_payload = _payload_mapping(
                existing.payload,
                label="existing holdout release payload",
            )
            if existing_payload.get("protocol_id") != identity:
                continue
            expected_existing = {
                "protocol_id": identity,
                "protocol_admission_object_id": protocol_envelope.object_id,
                "validation_run_object_id": validation_run.envelope.object_id,
                "released_by": owner,
                "released_at": released_text,
                "frozen_validation_report": _receipt_chunks(report),
                "validation_report_sha256": report_sha256,
            }
            actual_existing = {
                key: existing_payload.get(key) for key in expected_existing
            }
            if _canonical_json_bytes(actual_existing) != _canonical_json_bytes(
                expected_existing
            ):
                raise EconomicEvaluationAdmissionError(
                    "holdout is already released with different provenance"
                )
            _validate_holdout_release_payload(
                _payload_mapping(
                    _thaw_json(existing_payload),
                    label="existing holdout release payload",
                ),
                protocol=protocol,
                protocol_admission_object_id=protocol_envelope.object_id,
                validation_run_object_id=validation_run.envelope.object_id,
                allow_legacy=True,
            )
            _validate_historical_predecessor(
                _payload_mapping(
                    _thaw_json(existing_payload),
                    label="existing holdout release payload",
                ),
                envelope=existing,
                events=events,
            )
            return _holdout_release_from_envelope(existing, created=False)

        material: dict[str, object] = {
            "schema_version": ECONOMIC_HOLDOUT_RELEASE_SCHEMA,
            "protocol_id": identity,
            "protocol_admission_object_id": protocol_envelope.object_id,
            "validation_run_object_id": validation_run.envelope.object_id,
            "released_by": owner,
            "released_at": released_text,
            "frozen_validation_report": _receipt_chunks(report),
            "validation_report_sha256": report_sha256,
            "store_predecessor": {
                **predecessor,
            },
            **_AUTHORITY_FIELDS,
        }
        candidate = EvidenceCandidate(
            kind=ECONOMIC_HOLDOUT_RELEASE_KIND,
            effective_at=released_text,
            payload=material,
        )

        def validate(
            current_snapshot: tuple[EvidenceEnvelope, ...],
            envelope: EvidenceEnvelope,
        ) -> None:
            if (
                predecessor["sequence"] < 1
                or len(current_snapshot) != predecessor["sequence"]
                or not current_snapshot
                or current_snapshot[-1].object_id != predecessor["object_id"]
            ):
                raise EconomicEvaluationAdmissionError(
                    "immutable evidence-store head changed during holdout release"
                )
            current_protocols = [
                item
                for item in current_snapshot
                if item.object_id == protocol_envelope.object_id
            ]
            if len(current_protocols) != 1:
                raise EconomicEvaluationAdmissionError(
                    "admitted protocol changed before holdout release"
                )
            if (
                current_protocols[0].canonical_json_bytes()
                != protocol_envelope.canonical_json_bytes()
            ):
                raise EconomicEvaluationAdmissionError(
                    "admitted protocol bytes changed before holdout release"
                )
            current_runs = [
                item
                for item in current_snapshot
                if item.object_id == validation_run.envelope.object_id
            ]
            if len(current_runs) != 1 or (
                current_runs[0].canonical_json_bytes()
                != validation_run.envelope.canonical_json_bytes()
            ):
                raise EconomicEvaluationAdmissionError(
                    "immutable validation run changed before holdout release"
                )
            submitted = _payload_mapping(_thaw_json(envelope.payload), label="holdout payload")
            if _canonical_json_bytes(submitted) != _canonical_json_bytes(material):
                raise EconomicEvaluationAdmissionError("holdout release payload is not exact")
            if self._reopen_tournament_input(
                protocol=protocol,
                report=report,
            ) is None:
                raise EconomicEvaluationAdmissionError(
                    "holdout release tournament custody is not qualifying"
                )
            _validate_holdout_release_payload(
                submitted,
                protocol=protocol,
                protocol_admission_object_id=protocol_envelope.object_id,
                validation_run_object_id=validation_run.envelope.object_id,
            )
            if any(
                item.kind == ECONOMIC_HOLDOUT_RELEASE_KIND
                and _payload_mapping(item.payload, label="prior holdout payload").get(
                    "protocol_id"
                )
                == identity
                for item in current_snapshot
            ):
                raise EconomicEvaluationAdmissionError("holdout is already released")

        try:
            admission = self._store.admit_checked(
                candidate,
                validate=validate,
                validate_orphans=_reject_orphaned_economic_evidence,
            )
        except EconomicEvaluationAdmissionError:
            raise
        except (TypeError, ValueError) as exc:
            raise EconomicEvaluationAdmissionError("holdout release failed") from exc
        return _holdout_release_from_envelope(admission.envelope, created=admission.created)

    def is_holdout_released(self, protocol_id: str) -> bool:
        """Return whether a fully validated immutable release record exists."""

        identity = _require_protocol_id(protocol_id)
        snapshot, events = self._store.verify_with_events()
        protocols = {
            envelope.object_id: _admitted_protocol_from_envelope(
                envelope,
                events=events,
            )
            for envelope in snapshot
            if envelope.kind == ECONOMIC_EVALUATION_PROTOCOL_KIND
        }
        validation_runs: dict[str, EconomicEvaluationRun] = {}
        for envelope in snapshot:
            if envelope.kind != ECONOMIC_EVALUATION_RUN_KIND:
                continue
            run_payload = _payload_mapping(
                _thaw_json(envelope.payload),
                label="evaluation-run payload",
            )
            admission_object_id = run_payload.get("protocol_admission_object_id")
            if admission_object_id not in protocols:
                raise EconomicEvaluationAdmissionError(
                    "evaluation-run references a missing admitted protocol"
                )
            validation_runs[envelope.object_id] = _evaluation_run_from_envelope(
                envelope,
                protocol=protocols[admission_object_id],
                protocol_admission_object_id=admission_object_id,
                events=events,
            )
        for envelope in snapshot:
            if envelope.kind != ECONOMIC_HOLDOUT_RELEASE_KIND:
                continue
            payload = _payload_mapping(
                _thaw_json(envelope.payload),
                label="holdout release payload",
            )
            admitted_object_id = payload.get("protocol_admission_object_id")
            if admitted_object_id not in protocols:
                raise EconomicEvaluationAdmissionError(
                    "holdout release references a missing admitted protocol"
                )
            validation_run_object_id = payload.get("validation_run_object_id")
            if validation_run_object_id not in validation_runs:
                raise EconomicEvaluationAdmissionError(
                    "holdout release references a missing validation run"
                )
            validation_run = validation_runs[validation_run_object_id]
            if validation_run.protocol_admission_object_id != admitted_object_id:
                raise EconomicEvaluationAdmissionError(
                    "holdout release validation run binds a different protocol"
                )
            _validate_holdout_release_payload(
                payload,
                protocol=protocols[admitted_object_id],
                protocol_admission_object_id=admitted_object_id,
                validation_run_object_id=validation_run_object_id,
                allow_legacy=True,
            )
            run_report = _payload_mapping(
                _thaw_json(validation_run.envelope.payload),
                label="evaluation-run payload",
            )["frozen_validation_report"]
            release_report_value = _validation_report_receipt_value(
                payload["frozen_validation_report"],
                label="holdout validation report",
            )
            run_report_value = _validation_report_receipt_value(
                run_report,
                label="evaluation-run validation report",
            )
            if _canonical_json_bytes(release_report_value) != _canonical_json_bytes(
                run_report_value
            ):
                raise EconomicEvaluationAdmissionError(
                    "holdout release report does not match validation run"
                )
            _validate_historical_predecessor(
                payload,
                envelope=envelope,
                events=events,
            )
            current_report = _payload_mapping(
                run_report_value,
                label="validation-run report",
            )
            if current_report.get("schema_version") != ECONOMIC_VALIDATION_REPORT_SCHEMA:
                continue
            if self._reopen_tournament_input(
                protocol=protocols[admitted_object_id],
                report=current_report,
            ) is None:
                continue
            if payload["protocol_id"] == identity:
                return True
        return False
