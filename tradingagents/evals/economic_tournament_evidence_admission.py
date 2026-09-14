"""Archive custody and exact raw replay for tournament input receipts."""

from __future__ import annotations

import json
import os
import re
import secrets
import stat
from collections.abc import Mapping
from contextlib import suppress
from pathlib import Path

from tradingagents.dataflows.pit import (
    RawPointInTimeArtifactArchive,
    build_market_session_calendar,
    resolve_market_session_open,
    validate_market_session_calendar,
    validate_point_in_time_observation,
    validate_security_identity,
    validate_source_bound_adjusted_price_window,
    validate_source_bound_execution_outcome,
    verify_source_bound_adjusted_price_window,
)
from tradingagents.evals.economic_evaluation_partition_binding import (
    EconomicPhaseEligibility,
    ValidationPhaseEligibility,
)
from tradingagents.evals.economic_evaluation_protocol import FrozenEvaluationProtocol
from tradingagents.evals.economic_tournament_evidence import (
    EconomicTournamentInputEvidenceError,
    SourceBoundTournamentInput,
    build_source_bound_tournament_input,
    validate_source_bound_tournament_features,
    validate_source_bound_tournament_input,
    validate_source_bound_tournament_outcomes,
)

__all__ = [
    "EconomicTournamentReceiptArchive",
    "verify_source_bound_tournament_input",
]


_AUTHORITY = {
    "analysis_only": True,
    "execution_authority": "none",
    "can_submit_orders": False,
}
_SHA256 = re.compile(r"[0-9a-f]{64}")
_FEATURE_ID = re.compile(r"economic-tournament-feature-[0-9a-f]{64}")
_INPUT_ID = re.compile(r"economic-tournament-input-[0-9a-f]{64}")
_MAX_RECEIPT_BYTES = 32_000_000
_MAX_RAW_JSON_BYTES = 16_000_000
_MAX_JSON_DEPTH = 64
_MAX_JSON_NODES = 1_000_000
_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_CUSTODY_SCHEMA = "economic_tournament_receipt_custody/v1"
_Eligibility = EconomicPhaseEligibility | ValidationPhaseEligibility


def _plain_json(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _plain_json(item) for key, item in value.items()}
    if type(value) is tuple:
        return [_plain_json(item) for item in value]
    return value


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        _plain_json(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _strict_json(raw_bytes: bytes, *, max_bytes: int, label: str) -> object:
    if type(raw_bytes) is not bytes or not raw_bytes or len(raw_bytes) > max_bytes:
        raise EconomicTournamentInputEvidenceError(f"{label} bytes are invalid")

    def pairs(values: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in values:
            if key in result:
                raise EconomicTournamentInputEvidenceError(
                    f"{label} contains a duplicate JSON key"
                )
            result[key] = value
        return result

    def constant(_value: str) -> object:
        raise EconomicTournamentInputEvidenceError(
            f"{label} contains a nonfinite JSON number"
        )

    def integer(value: str) -> int:
        if len(value) > 128:
            raise EconomicTournamentInputEvidenceError(
                f"{label} contains an oversized JSON integer"
            )
        return int(value)

    def decimal(_value: str) -> object:
        raise EconomicTournamentInputEvidenceError(
            f"{label} contains a JSON float"
        )

    try:
        value = json.loads(
            raw_bytes,
            object_pairs_hook=pairs,
            parse_constant=constant,
            parse_int=integer,
            parse_float=decimal,
        )
    except EconomicTournamentInputEvidenceError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise EconomicTournamentInputEvidenceError(
            f"{label} is not bounded canonical JSON"
        ) from exc
    stack: list[tuple[object, int]] = [(value, 1)]
    nodes = 0
    while stack:
        current, depth = stack.pop()
        nodes += 1
        if nodes > _MAX_JSON_NODES or depth > _MAX_JSON_DEPTH:
            raise EconomicTournamentInputEvidenceError(
                f"{label} JSON structure is too large"
            )
        if isinstance(current, Mapping):
            stack.extend((item, depth + 1) for item in current.values())
        elif type(current) is list:
            stack.extend((item, depth + 1) for item in current)
    return value


def _select_json(value: object, path: object, *, label: str) -> object:
    if type(path) not in (list, tuple) or not path:
        raise EconomicTournamentInputEvidenceError(f"{label} path is invalid")
    current = value
    for component in path:
        if type(component) is str and isinstance(current, Mapping) and component in current:
            current = current[component]
            continue
        if type(component) is int and type(current) is list and 0 <= component < len(current):
            current = current[component]
            continue
        raise EconomicTournamentInputEvidenceError(f"{label} path cannot be resolved")
    return current


def _verify_observation(
    archive: RawPointInTimeArtifactArchive,
    value: object,
    *,
    source_values: dict[tuple[str, bytes], bytes],
) -> None:
    try:
        observation = validate_point_in_time_observation(_plain_json(value))
        artifact = archive.read_artifact(observation.raw_artifact_id)
        raw_bytes = archive.read_bytes(artifact)
    except (OSError, TypeError, ValueError) as exc:
        raise EconomicTournamentInputEvidenceError(
            "tournament observation raw artifact cannot be verified"
        ) from exc
    if (
        artifact.raw_artifact_sha256 != observation.raw_artifact_sha256
        or artifact.retrieved_at != observation.availability_time
        or artifact.archive_recorded_at != observation.retrieval_time
        or artifact.content_type not in {"application/json", "application/x-ndjson"}
    ):
        raise EconomicTournamentInputEvidenceError(
            "tournament observation raw receipt does not match"
        )
    span = observation.source_span
    if span.get("source_sha256") != artifact.raw_artifact_sha256:
        raise EconomicTournamentInputEvidenceError(
            "tournament observation source span digest does not match"
        )
    span_type = span.get("span_type")
    if span_type == "json_paths":
        payload = _strict_json(
            raw_bytes,
            max_bytes=_MAX_RAW_JSON_BYTES,
            label="tournament raw source",
        )
        paths = span.get("paths")
        if not isinstance(paths, Mapping) or "observed_value" not in paths:
            raise EconomicTournamentInputEvidenceError(
                "tournament observation lacks an observed-value path"
            )
        rebuilt = _select_json(
            payload,
            paths["observed_value"],
            label="tournament observed value",
        )
    elif span_type == "byte_range":
        start = span.get("start_byte")
        end = span.get("end_byte")
        if (
            type(start) is not int
            or type(end) is not int
            or start < 0
            or end <= start
            or end > len(raw_bytes)
        ):
            raise EconomicTournamentInputEvidenceError(
                "tournament observation byte range is invalid"
            )
        rebuilt = _strict_json(
            raw_bytes[start:end],
            max_bytes=_MAX_RAW_JSON_BYTES,
            label="tournament raw source span",
        )
    else:
        raise EconomicTournamentInputEvidenceError(
            "tournament observation source span is unsupported"
        )
    if _canonical_json_bytes(rebuilt) != _canonical_json_bytes(observation.observed_value):
        raise EconomicTournamentInputEvidenceError(
            "tournament observation value does not replay from raw bytes"
        )
    key = (artifact.raw_artifact_id, _canonical_json_bytes(span))
    rebuilt_bytes = _canonical_json_bytes(rebuilt)
    prior = source_values.setdefault(key, rebuilt_bytes)
    if prior != rebuilt_bytes:
        raise EconomicTournamentInputEvidenceError(
            "tournament source span has conflicting values"
        )


def verify_source_bound_tournament_input(
    *,
    archive: RawPointInTimeArtifactArchive,
    value: object,
    protocol: FrozenEvaluationProtocol,
    eligibility: _Eligibility,
) -> SourceBoundTournamentInput:
    """Reopen raw bytes and rebuild every declared value and price window."""

    if type(archive) is not RawPointInTimeArtifactArchive:
        raise EconomicTournamentInputEvidenceError("archive must be an exact PIT archive")
    receipt = validate_source_bound_tournament_input(
        value,
        protocol=protocol,
        eligibility=eligibility,
    )
    source_values: dict[tuple[str, bytes], bytes] = {}
    for date_evidence in receipt.features.date_evidence:
        candidates = date_evidence.get("candidates")
        benchmark = date_evidence.get("benchmark")
        if type(candidates) is not tuple or not isinstance(benchmark, Mapping):
            raise EconomicTournamentInputEvidenceError(
                "canonical tournament feature evidence is invalid"
            )
        for candidate in candidates:
            if not isinstance(candidate, Mapping):
                raise EconomicTournamentInputEvidenceError(
                    "canonical tournament candidate evidence is invalid"
                )
            _verify_observation(
                archive,
                candidate.get("security_observation"),
                source_values=source_values,
            )
            _verify_observation(
                archive,
                candidate.get("candidate_observation"),
                source_values=source_values,
            )
            sources = candidate.get("field_sources")
            if type(sources) is not tuple:
                raise EconomicTournamentInputEvidenceError(
                    "canonical tournament field sources are invalid"
                )
            for source in sources:
                if not isinstance(source, Mapping):
                    raise EconomicTournamentInputEvidenceError(
                        "canonical tournament field source is invalid"
                    )
                _verify_observation(
                    archive,
                    source.get("observation"),
                    source_values=source_values,
                )
        _verify_observation(
            archive,
            benchmark.get("security_observation"),
            source_values=source_values,
        )
        _verify_observation(
            archive,
            benchmark.get("benchmark_observation"),
            source_values=source_values,
        )
    for feature_date, date_evidence in zip(
        receipt.features.date_evidence,
        receipt.outcome_receipt.date_evidence,
        strict=True,
    ):
        outcomes = date_evidence.get("outcomes")
        if type(outcomes) is not tuple:
            raise EconomicTournamentInputEvidenceError(
                "canonical tournament outcomes are invalid"
            )
        try:
            calendar = validate_market_session_calendar(
                _plain_json(date_evidence.get("market_calendar"))
            )
            calendar_artifact = archive.read_artifact(calendar.raw_artifact_id)
            verified_calendar = build_market_session_calendar(
                archive=archive,
                raw_artifact=calendar_artifact,
            )
        except (OSError, TypeError, ValueError) as exc:
            raise EconomicTournamentInputEvidenceError(
                "tournament market calendar raw artifact cannot be verified"
            ) from exc
        if verified_calendar.canonical_json_bytes() != calendar.canonical_json_bytes():
            raise EconomicTournamentInputEvidenceError(
                "tournament market calendar bytes are not exact"
            )
        identities: dict[str, object] = {}
        for candidate in feature_date["candidates"]:
            security = validate_security_identity(_plain_json(candidate["security"]))
            identities[security.symbol] = security
        benchmark = feature_date["benchmark"]
        benchmark_security = validate_security_identity(
            _plain_json(benchmark["security"])
        )
        identities[benchmark_security.symbol] = benchmark_security
        for outcome in outcomes:
            if not isinstance(outcome, Mapping):
                raise EconomicTournamentInputEvidenceError(
                    "canonical tournament outcome is invalid"
                )
            try:
                window = validate_source_bound_adjusted_price_window(
                    _plain_json(outcome.get("price_window"))
                )
                artifact = archive.read_artifact(window.raw_artifact_id)
                verified = verify_source_bound_adjusted_price_window(
                    archive=archive,
                    raw_artifact=artifact,
                    value=window.to_dict(),
                )
                raw_execution = _plain_json(outcome.get("execution_outcome"))
                symbol = raw_execution.get("symbol")
                security = identities[symbol]
                execution = validate_source_bound_execution_outcome(
                    raw_execution,
                    security=security,
                    market_calendar=calendar,
                    adjusted_price_window=verified,
                )
                official_open = resolve_market_session_open(
                    archive=archive,
                    market_calendar=calendar,
                    session_date=execution.entry_session_date,
                )
            except (OSError, TypeError, ValueError) as exc:
                raise EconomicTournamentInputEvidenceError(
                    "tournament outcome raw artifact cannot be verified"
                ) from exc
            if verified.canonical_json_bytes() != window.canonical_json_bytes():
                raise EconomicTournamentInputEvidenceError(
                    "tournament outcome price window bytes are not exact"
                )
            if execution.entry_session_open_at != official_open:
                raise EconomicTournamentInputEvidenceError(
                    "tournament execution open does not replay from raw calendar bytes"
                )
    return receipt


def _canonical_existing_directory(value: str | Path) -> Path:
    path = Path(value).expanduser().absolute()
    try:
        state = os.lstat(path)
    except OSError as exc:
        raise EconomicTournamentInputEvidenceError(
            "PIT artifact root does not exist"
        ) from exc
    if not stat.S_ISDIR(state.st_mode) or stat.S_ISLNK(state.st_mode):
        raise EconomicTournamentInputEvidenceError("PIT artifact root is unsafe")
    return path


class EconomicTournamentReceiptArchive:
    """Content-addressed, write-once custody for complete feature/outcome receipts."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().absolute()

    @property
    def _features(self) -> Path:
        return self.root / "features"

    @property
    def _outcomes(self) -> Path:
        return self.root / "outcomes"

    @property
    def _custody(self) -> Path:
        return self.root / "custody"

    @property
    def _staging(self) -> Path:
        return self.root / ".staging"

    def admit(
        self,
        receipt: SourceBoundTournamentInput,
        *,
        pit_artifact_root: str | Path,
    ) -> None:
        """Persist both complete receipts and their local raw-archive custody."""

        if type(receipt) is not SourceBoundTournamentInput:
            raise EconomicTournamentInputEvidenceError(
                "receipt must be an exact source-bound tournament input"
            )
        pit_root = _canonical_existing_directory(pit_artifact_root)
        self._ensure_directories()
        self._publish(
            self._features / f"{receipt.features.feature_id}.json",
            receipt.features.canonical_json_bytes(),
        )
        self._publish(
            self._outcomes / f"{receipt.input_id}.json",
            receipt.outcome_receipt.canonical_json_bytes(),
        )
        custody = {
            "schema_version": _CUSTODY_SCHEMA,
            "input_id": receipt.input_id,
            "input_sha256": receipt.input_sha256,
            "feature_id": receipt.features.feature_id,
            "feature_sha256": receipt.features.feature_sha256,
            "pit_artifact_root": str(pit_root),
            **_AUTHORITY,
        }
        self._publish(
            self._custody / f"{receipt.input_id}.json",
            _canonical_json_bytes(custody),
        )

    def reopen(
        self,
        *,
        input_id: str,
        input_sha256: str,
        protocol: FrozenEvaluationProtocol,
        eligibility: _Eligibility,
    ) -> SourceBoundTournamentInput:
        """Reopen both complete receipts and all retained PIT source bytes."""

        if _INPUT_ID.fullmatch(input_id) is None or _SHA256.fullmatch(input_sha256) is None:
            raise EconomicTournamentInputEvidenceError(
                "tournament receipt reference is invalid"
            )
        self._verify_directories()
        outcome_bytes = self._read_regular(self._outcomes / f"{input_id}.json")
        outcome_value = _strict_json(
            outcome_bytes,
            max_bytes=_MAX_RECEIPT_BYTES,
            label="tournament outcome receipt",
        )
        if not isinstance(outcome_value, Mapping):
            raise EconomicTournamentInputEvidenceError(
                "tournament outcome receipt is not an object"
            )
        if outcome_value.get("input_id") != input_id or outcome_value.get("input_sha256") != input_sha256:
            raise EconomicTournamentInputEvidenceError(
                "tournament outcome receipt identity does not match"
            )
        feature_id = outcome_value.get("feature_id")
        feature_sha256 = outcome_value.get("feature_sha256")
        if type(feature_id) is not str or _FEATURE_ID.fullmatch(feature_id) is None:
            raise EconomicTournamentInputEvidenceError(
                "tournament feature reference is invalid"
            )
        feature_bytes = self._read_regular(self._features / f"{feature_id}.json")
        feature_value = _strict_json(
            feature_bytes,
            max_bytes=_MAX_RECEIPT_BYTES,
            label="tournament feature receipt",
        )
        features = validate_source_bound_tournament_features(
            feature_value,
            protocol=protocol,
            eligibility=eligibility,
        )
        if features.feature_sha256 != feature_sha256:
            raise EconomicTournamentInputEvidenceError(
                "tournament feature receipt digest does not match"
            )
        outcomes = validate_source_bound_tournament_outcomes(
            outcome_value,
            protocol=protocol,
            eligibility=eligibility,
            features=features,
        )
        receipt = build_source_bound_tournament_input(
            protocol=protocol,
            eligibility=eligibility,
            features=features,
            outcomes=outcomes,
        )
        custody_bytes = self._read_regular(self._custody / f"{input_id}.json")
        custody = _strict_json(
            custody_bytes,
            max_bytes=8_192,
            label="tournament receipt custody",
        )
        if not isinstance(custody, Mapping) or custody != {
            "schema_version": _CUSTODY_SCHEMA,
            "input_id": input_id,
            "input_sha256": input_sha256,
            "feature_id": feature_id,
            "feature_sha256": feature_sha256,
            "pit_artifact_root": custody.get("pit_artifact_root"),
            **_AUTHORITY,
        }:
            raise EconomicTournamentInputEvidenceError(
                "tournament receipt custody is invalid"
            )
        pit_root = _canonical_existing_directory(custody["pit_artifact_root"])
        return verify_source_bound_tournament_input(
            archive=RawPointInTimeArtifactArchive(pit_root),
            value=receipt.to_dict(),
            protocol=protocol,
            eligibility=eligibility,
        )

    def _ensure_directories(self) -> None:
        parent = self.root.parent
        root_existed = self.root.exists()
        if parent.exists():
            state = os.lstat(parent)
            if not stat.S_ISDIR(state.st_mode) or stat.S_ISLNK(state.st_mode):
                raise EconomicTournamentInputEvidenceError(
                    "tournament receipt archive parent is unsafe"
                )
        for path in (self.root, self._features, self._outcomes, self._custody, self._staging):
            try:
                path.mkdir(mode=0o700, parents=path == self.root, exist_ok=True)
                state = os.lstat(path)
            except OSError as exc:
                raise EconomicTournamentInputEvidenceError(
                    "tournament receipt archive cannot create directories"
                ) from exc
            if (
                not stat.S_ISDIR(state.st_mode)
                or stat.S_ISLNK(state.st_mode)
                or stat.S_IMODE(state.st_mode) != 0o700
            ):
                raise EconomicTournamentInputEvidenceError(
                    "tournament receipt archive directory is unsafe"
                )
        if not root_existed:
            self._fsync_directory(parent)
        self._fsync_directory(self.root)

    def _verify_directories(self) -> None:
        for path in (self.root, self._features, self._outcomes, self._custody, self._staging):
            try:
                state = os.lstat(path)
            except OSError as exc:
                raise EconomicTournamentInputEvidenceError(
                    "tournament receipt archive directory is missing"
                ) from exc
            if (
                not stat.S_ISDIR(state.st_mode)
                or stat.S_ISLNK(state.st_mode)
                or stat.S_IMODE(state.st_mode) != 0o700
            ):
                raise EconomicTournamentInputEvidenceError(
                    "tournament receipt archive directory is unsafe"
                )

    def _publish(self, path: Path, data: bytes) -> None:
        value = _strict_json(
            data,
            max_bytes=_MAX_RECEIPT_BYTES,
            label="tournament archived receipt",
        )
        if _canonical_json_bytes(value) != data:
            raise EconomicTournamentInputEvidenceError(
                "tournament archived receipt is not canonical JSON"
            )
        if path.parent not in {self._features, self._outcomes, self._custody}:
            raise EconomicTournamentInputEvidenceError(
                "tournament archived receipt path is unsafe"
            )
        if path.exists():
            if self._read_regular(path) != data:
                raise EconomicTournamentInputEvidenceError(
                    "tournament receipt content-address collision"
                )
            return
        staged = self._staging / f"{path.stem}.{secrets.token_hex(8)}.tmp"
        try:
            descriptor = os.open(staged, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.link(staged, path, follow_symlinks=False)
            except FileExistsError as exc:
                if self._read_regular(path) != data:
                    raise EconomicTournamentInputEvidenceError(
                        "tournament receipt content-address collision"
                    ) from exc
            self._fsync_directory(path.parent)
        except EconomicTournamentInputEvidenceError:
            raise
        except OSError as exc:
            raise EconomicTournamentInputEvidenceError(
                "tournament receipt archive publish failed"
            ) from exc
        finally:
            with suppress(OSError):
                staged.unlink(missing_ok=True)
            self._fsync_directory(self._staging)
        if self._read_regular(path) != data:
            raise EconomicTournamentInputEvidenceError(
                "tournament receipt archive reread differs"
            )

    @staticmethod
    def _read_regular(path: Path) -> bytes:
        try:
            state = os.lstat(path)
            if (
                not stat.S_ISREG(state.st_mode)
                or stat.S_ISLNK(state.st_mode)
                or stat.S_IMODE(state.st_mode) != 0o600
            ):
                raise EconomicTournamentInputEvidenceError(
                    "tournament receipt path is unsafe"
                )
            descriptor = os.open(path, os.O_RDONLY | _NOFOLLOW)
            with os.fdopen(descriptor, "rb") as handle:
                return handle.read(_MAX_RECEIPT_BYTES + 1)
        except EconomicTournamentInputEvidenceError:
            raise
        except OSError as exc:
            raise EconomicTournamentInputEvidenceError(
                "tournament receipt cannot be read"
            ) from exc

    @staticmethod
    def _fsync_directory(path: Path) -> None:
        try:
            descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        except OSError as exc:
            raise EconomicTournamentInputEvidenceError(
                "tournament receipt archive cannot sync directory"
            ) from exc
