"""Immutable, analysis-only strategy eligibility proposals.

This module deliberately stops at a durable *eligibility* proposal.  It has no
broker, live-control, execution, or order dependency; a proposal cannot arm a
strategy or submit an order.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import re
import stat
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path

from tradingagents.orchestration.authority import ActionClass, authority_for
from tradingagents.policy.promotion import SleevePromotionEvidence, evaluate_sleeve_promotion
from tradingagents.policy.risk_envelope import load_risk_envelope
from tradingagents.strategy._immutable_evidence_store import (
    STRATEGY_PROMOTION_PROPOSAL_KIND,
    EvidenceCandidate,
    EvidenceEnvelope,
    ImmutableStrategyEvidenceStore,
    _thaw_json,
)
from tradingagents.strategy.promotion_evidence import (
    StrategyEvaluationRegistration,
    StrategyPromotionEvidence,
    require_active_evaluation_runtime,
)
from tradingagents.strategy.shadow_attestation import (
    StrategyShadowAttestation,
    _attestation_from_envelope,
)

STRATEGY_VALIDATION_ATTESTATION_SCHEMA_VERSION = 1
STRATEGY_RISK_ATTESTATION_SCHEMA_VERSION = 1
STRATEGY_PROMOTION_PROPOSAL_SCHEMA_VERSION = 1
STRATEGY_PROMOTION_SYNC_PREPARE_SCHEMA_VERSION = 1
STRATEGY_PROMOTION_SYNC_RECEIPT_SCHEMA_VERSION = 1
VALIDATION_ATTESTATION_MAX_AGE_SECONDS = 86_400
RISK_ATTESTATION_MAX_AGE_SECONDS = 900
SHADOW_ATTESTATION_MAX_AGE_SECONDS = 604_800
INTERNAL_EVIDENCE_MAX_AGE_SECONDS = 604_800
STRATEGY_PROMOTION_PROPOSAL_MAX_TTL_SECONDS = 900
REQUIRED_STRATEGY_PROMOTION_VALIDATION_COMMANDS = (
    "uv run pytest tests/test_strategy_evidence_store.py "
    "tests/test_strategy_promotion_evidence.py "
    "tests/test_strategy_mutation_registry.py "
    "tests/test_strategy_staged_intent.py "
    "tests/test_strategy_paper_execution_authorization.py "
    "tests/test_strategy_shadow_attestation.py "
    "tests/test_strategy_promotion_adapter.py "
    "tests/test_strategy_promotion_sync.py -q",
    "uv run pytest tests/test_promotion_policy.py tests/test_promotion_sync.py tests/test_live_gate.py tests/test_authority.py tests/test_authority_role_alignment.py tests/test_self_heal_recovery.py -q",
    "uv run pytest -q",
    "uv run ruff check tradingagents tests",
    "uv run python -m compileall -q tradingagents tests",
)
STRATEGY_PROMOTION_GATE_ORDER = (
    "ci_green",
    "shadow_sessions_sufficient",
    "reconciliation_confirmed",
    "capacity_gate_passed",
    "risk_budget_mode_capped",
    "risk_auto_promotion_allowed",
)
STRATEGY_PROMOTION_ADMISSION_INVARIANTS = (
    "internal_evidence_complete",
    "preregistered_schedule",
    "identity_chain_complete",
    "evaluation_code_commit_bound",
    "evaluation_runtime_bound",
    "benchmark_gate_already_passed",
    "cost_gate_already_passed",
    "recent_alpha_gate_already_passed",
    "validation_report_present",
    "risk_envelope_ref_present",
    "promotion_authority_confirmed",
    "internal_evidence_current",
    "validation_attestation_current",
    "shadow_attestation_current",
    "risk_attestation_current",
)
_UTC = datetime.timezone.utc
_SHA = re.compile(r"^[0-9a-f]{64}$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_MONEY = re.compile(r"^(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$")


def _canonical(value: Mapping[str, object]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _time(value: object, label: str) -> datetime.datetime:
    if type(value) is not str:
        raise ValueError(f"{label} must be canonical UTC")
    try:
        parsed = datetime.datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{label} must be canonical UTC") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{label} must be canonical UTC")
    parsed = parsed.astimezone(_UTC)
    if parsed.microsecond or parsed.isoformat(timespec="seconds") != value:
        raise ValueError(f"{label} must be canonical UTC")
    return parsed


def _time_text(value: datetime.datetime, label: str) -> str:
    if not isinstance(value, datetime.datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")
    return value.astimezone(_UTC).replace(microsecond=0).isoformat(timespec="seconds")


def _now(clock: Callable[[], datetime.datetime] | None) -> datetime.datetime:
    return datetime.datetime.now(_UTC) if clock is None else clock()


def _sha(value: object, label: str) -> str:
    if type(value) is not str or _SHA.fullmatch(value) is None:
        raise ValueError(f"{label} must be a full lowercase SHA-256")
    return value


def _commit(value: object, label: str) -> str:
    if type(value) is not str or _COMMIT.fullmatch(value) is None:
        raise ValueError(f"{label} must be lowercase 40-hex")
    return value


def _object_id(value: object, *, kind: str, label: str) -> str:
    if (
        type(value) is not str
        or not value.startswith(kind + "-")
        or _SHA.fullmatch(value.removeprefix(kind + "-")) is None
    ):
        raise ValueError(f"{label} must be a full {kind} object ID")
    return value


def _decimal_text(value: object, label: str, *, positive: bool = False) -> str:
    if type(value) is not str:
        raise TypeError(f"{label} must be a string")
    try:
        number = Decimal(value)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{label} must be a decimal") from exc
    if not number.is_finite() or (positive and number <= 0):
        raise ValueError(f"{label} is outside its allowed range")
    # Decimal's string form is the project-wide canonical representation.
    if str(number) != value or "E" in value or "e" in value:
        raise ValueError(f"{label} must be canonical decimal text")
    return value


def _exact_mapping(payload: Mapping[str, object], keys: set[str], label: str) -> dict[str, object]:
    if not isinstance(payload, Mapping) or set(payload) != keys or any(type(k) is not str for k in payload):
        raise ValueError(f"{label} fields do not match schema")
    return dict(payload)


def _safe_repo_file(repo_root: str | Path, reference: str | Path, label: str) -> tuple[Path, str]:
    root = Path(repo_root).resolve()
    raw = Path(reference)
    if raw.is_absolute() or not raw.parts or ".." in raw.parts:
        raise ValueError(f"{label} must be repo-relative")
    candidate = root / raw
    try:
        # Inspect the caller's spelling before resolving it.  Checking only
        # resolved path components would hide a symlink such as
        # `reports/current.json -> reports/approved.json` inside the repo.
        current = root
        for part in raw.parts:
            if part == ".":
                raise ValueError(f"{label} must be repo-relative")
            current /= part
            if stat.S_ISLNK(current.lstat().st_mode):
                raise ValueError(f"{label} cannot use symlinks")
        resolved = candidate.resolve(strict=True)
        relative = resolved.relative_to(root)
    except (FileNotFoundError, ValueError) as exc:
        if "cannot use symlinks" in str(exc):
            raise
        raise ValueError(f"{label} is not a safe repo-relative file") from exc
    current = root
    for part in relative.parts:
        current /= part
        if stat.S_ISLNK(current.lstat().st_mode):
            raise ValueError(f"{label} cannot use symlinks")
    if not stat.S_ISREG(resolved.stat().st_mode):
        raise ValueError(f"{label} must be a regular file")
    return resolved, relative.as_posix()


def _safe_relative_reference(value: str) -> bool:
    if type(value) is not str or not value or "\\" in value or "\x00" in value:
        return False
    path = Path(value)
    return (
        not path.is_absolute()
        and bool(path.parts)
        and all(part not in {".", ".."} for part in path.parts)
        and path.as_posix() == value
    )


def _git(repo_root: str | Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=repo_root, text=True, capture_output=True, check=False, timeout=10)
    if result.returncode:
        raise ValueError("local Git verification failed")
    return result.stdout.strip()


@dataclass(frozen=True, slots=True)
class StrategyValidationAttestation:
    tested_commit: str
    completed_at: str
    commands: tuple[str, ...]
    exit_code: int
    report_ref: str
    report_sha256: str
    verifier_role: str
    schema_version: int = field(init=False, default=1)
    analysis_only: bool = field(init=False, default=True)
    execution_authority: str = field(init=False, default="none")
    can_submit_orders: bool = field(init=False, default=False)

    def __post_init__(self) -> None:
        _commit(self.tested_commit, "tested_commit")
        _time(self.completed_at, "completed_at")
        _sha(self.report_sha256, "report_sha256")
        if type(self.commands) is not tuple or any(type(x) is not str for x in self.commands):
            raise TypeError("commands must be an exact string tuple")
        if type(self.exit_code) is not int:
            raise TypeError("exit_code must be an exact int")
        if not _safe_relative_reference(self.report_ref):
            raise ValueError("report_ref must be a safe canonical repo-relative file")
        if self.verifier_role != authority_for(ActionClass.VERIFY).owner_role:
            raise ValueError("verifier_role lacks verification authority")

    @property
    def ci_green(self) -> bool:
        return self.exit_code == 0 and self.commands == REQUIRED_STRATEGY_PROMOTION_VALIDATION_COMMANDS and _safe_relative_reference(self.report_ref) and _SHA.fullmatch(self.report_sha256) is not None and self.verifier_role == authority_for(ActionClass.VERIFY).owner_role

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> StrategyValidationAttestation:
        values = _exact_mapping(payload, {"schema_version", "tested_commit", "completed_at", "commands", "exit_code", "report_ref", "report_sha256", "verifier_role", "analysis_only", "execution_authority", "can_submit_orders"}, "validation attestation")
        if values["schema_version"] != 1 or values["analysis_only"] is not True or values["execution_authority"] != "none" or values["can_submit_orders"] is not False or type(values["commands"]) is not list:
            raise ValueError("validation attestation fixed fields are invalid")
        return cls(values["tested_commit"], values["completed_at"], tuple(values["commands"]), values["exit_code"], values["report_ref"], values["report_sha256"], values["verifier_role"])  # type: ignore[arg-type]

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "tested_commit": self.tested_commit,
            "completed_at": self.completed_at,
            "commands": list(self.commands),
            "exit_code": self.exit_code,
            "report_ref": self.report_ref,
            "report_sha256": self.report_sha256,
            "verifier_role": self.verifier_role,
            "analysis_only": True,
            "execution_authority": "none",
            "can_submit_orders": False,
        }

    def canonical_json_bytes(self) -> bytes:
        return _canonical(self.to_dict())


@dataclass(frozen=True, slots=True)
class StrategyRiskAttestation:
    risk_envelope_ref: str
    risk_envelope_sha256: str
    live_budget_mode: str
    account_max_capital_at_risk_usd: str
    per_name_cap_usd: str
    account_hard_ceiling_usd: str | None
    tiny_live_tranche_usd: str
    tiny_live_max_loss_usd: str
    max_drawdown_halt_fraction: str
    new_sleeve_auto_promote: bool
    reviewed_at: str
    reviewer_role: str
    schema_version: int = field(init=False, default=1)
    analysis_only: bool = field(init=False, default=True)
    execution_authority: str = field(init=False, default="none")
    can_submit_orders: bool = field(init=False, default=False)

    def __post_init__(self) -> None:
        _sha(self.risk_envelope_sha256, "risk_envelope_sha256")
        _time(self.reviewed_at, "reviewed_at")
        if not _safe_relative_reference(self.risk_envelope_ref):
            raise ValueError("risk_envelope_ref must be a safe canonical repo-relative file")
        if self.live_budget_mode not in {"fixed_tranche", "autonomous_with_caps", "autonomous_uncapped"}:
            raise ValueError("invalid live_budget_mode")
        for name in (
            "account_max_capital_at_risk_usd",
            "per_name_cap_usd",
            "tiny_live_tranche_usd",
            "tiny_live_max_loss_usd",
        ):
            _decimal_text(getattr(self, name), name, positive=True)
        drawdown = Decimal(
            _decimal_text(
                self.max_drawdown_halt_fraction,
                "max_drawdown_halt_fraction",
                positive=True,
            )
        )
        if drawdown > Decimal("1"):
            raise ValueError("max_drawdown_halt_fraction must be less than or equal to 1")
        if self.account_hard_ceiling_usd is not None:
            _decimal_text(self.account_hard_ceiling_usd, "account_hard_ceiling_usd", positive=True)
        if type(self.new_sleeve_auto_promote) is not bool:
            raise TypeError("new_sleeve_auto_promote must be bool")
        if self.reviewer_role != authority_for(ActionClass.RISK_CHANGE).owner_role:
            raise ValueError("reviewer_role lacks risk authority")

    @property
    def capped_mode(self) -> bool:
        return self.live_budget_mode in {"fixed_tranche", "autonomous_with_caps"}

    @property
    def capacity_usd(self) -> Decimal:
        values = [Decimal(self.account_max_capital_at_risk_usd), Decimal(self.per_name_cap_usd)]
        if self.account_hard_ceiling_usd is not None:
            values.append(Decimal(self.account_hard_ceiling_usd))
        return min(values)

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> StrategyRiskAttestation:
        keys = {
            "schema_version",
            "risk_envelope_ref",
            "risk_envelope_sha256",
            "live_budget_mode",
            "account_max_capital_at_risk_usd",
            "per_name_cap_usd",
            "account_hard_ceiling_usd",
            "tiny_live_tranche_usd",
            "tiny_live_max_loss_usd",
            "max_drawdown_halt_fraction",
            "new_sleeve_auto_promote",
            "reviewed_at",
            "reviewer_role",
            "analysis_only",
            "execution_authority",
            "can_submit_orders",
        }
        v = _exact_mapping(payload, keys, "risk attestation")
        if v["schema_version"] != 1 or v["analysis_only"] is not True or v["execution_authority"] != "none" or v["can_submit_orders"] is not False:
            raise ValueError("risk attestation fixed fields are invalid")
        return cls(**{k: v[k] for k in keys - {"schema_version", "analysis_only", "execution_authority", "can_submit_orders"}})  # type: ignore[arg-type]

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "risk_envelope_ref": self.risk_envelope_ref,
            "risk_envelope_sha256": self.risk_envelope_sha256,
            "live_budget_mode": self.live_budget_mode,
            "account_max_capital_at_risk_usd": self.account_max_capital_at_risk_usd,
            "per_name_cap_usd": self.per_name_cap_usd,
            "account_hard_ceiling_usd": self.account_hard_ceiling_usd,
            "tiny_live_tranche_usd": self.tiny_live_tranche_usd,
            "tiny_live_max_loss_usd": self.tiny_live_max_loss_usd,
            "max_drawdown_halt_fraction": self.max_drawdown_halt_fraction,
            "new_sleeve_auto_promote": self.new_sleeve_auto_promote,
            "reviewed_at": self.reviewed_at,
            "reviewer_role": self.reviewer_role,
            "analysis_only": True,
            "execution_authority": "none",
            "can_submit_orders": False,
        }

    def canonical_json_bytes(self) -> bytes:
        return _canonical(self.to_dict())


def build_validation_attestation(*, repo_root: str | Path, tested_commit: str, completed_at: datetime.datetime, commands: Sequence[str], exit_code: int, report_ref: str | Path, verifier_role: str, clock: Callable[[], datetime.datetime] | None = None) -> StrategyValidationAttestation:
    now = _now(clock)
    completed = _time_text(completed_at, "completed_at")
    if _time(completed, "completed_at") > now.astimezone(_UTC).replace(microsecond=0):
        raise ValueError("completed_at is in the future")
    path, ref = _safe_repo_file(repo_root, report_ref, "validation report")
    raw = path.read_bytes()
    if _git(repo_root, "rev-parse", "HEAD") != _commit(tested_commit, "tested_commit") or _git(repo_root, "status", "--porcelain") != "":
        raise ValueError("validation checkout must be current and clean")
    return StrategyValidationAttestation(tested_commit, completed, tuple(commands), exit_code, ref, _digest(raw), verifier_role)


def build_risk_attestation(*, repo_root: str | Path, risk_envelope_ref: str | Path, reviewed_at: datetime.datetime, reviewer_role: str, clock: Callable[[], datetime.datetime] | None = None) -> StrategyRiskAttestation:
    now = _now(clock)
    reviewed = _time_text(reviewed_at, "reviewed_at")
    if _time(reviewed, "reviewed_at") > now.astimezone(_UTC).replace(microsecond=0):
        raise ValueError("reviewed_at is in the future")
    path, ref = _safe_repo_file(repo_root, risk_envelope_ref, "risk envelope")
    first = path.read_bytes()
    envelope, issues = load_risk_envelope(path)
    if envelope is None or issues:
        raise ValueError("risk envelope is invalid")
    second = path.read_bytes()
    if first != second:
        raise ValueError("risk envelope changed during anchoring")
    ceiling = None if envelope.account_hard_ceiling_usd is None else str(envelope.account_hard_ceiling_usd)
    return StrategyRiskAttestation(
        ref, _digest(first), envelope.live_budget_mode, str(envelope.account_max_capital_at_risk_usd), str(envelope.per_name_cap_usd), ceiling, str(envelope.tiny_live_tranche_usd), str(envelope.tiny_live_max_loss_usd), str(envelope.max_drawdown_halt_pct), envelope.new_sleeve_auto_promote, reviewed, reviewer_role
    )


_PROPOSAL_FIELDS = (
    "proposal_id",
    "sleeve",
    "registration_id",
    "promotion_evidence_id",
    "promotion_evidence_sha256",
    "shadow_attestation_id",
    "shadow_attestation_sha256",
    "validation_attestation",
    "validation_attestation_sha256",
    "risk_attestation",
    "risk_attestation_sha256",
    "genome_id",
    "genome_canonical_sha256",
    "evaluation_code_commit",
    "evaluation_runtime_sha256",
    "promotion_runtime_commit",
    "benchmark_excess_return_fraction",
    "cost_adjusted_alpha_fraction",
    "recent_alpha_fraction",
    "capacity_usd",
    "requested_tiny_live_tranche_usd",
    "admission_invariants",
    "gates",
    "issues",
    "proposed_stage",
    "proposed_live_enabled",
    "promotion_owner_role",
    "expires_at",
    "effective_at",
    "recorded_at",
    "schema_version",
    "analysis_only",
    "execution_authority",
    "can_submit_orders",
)


@dataclass(frozen=True, slots=True)
class StrategyPromotionProposal:
    proposal_id: str
    sleeve: str
    registration_id: str
    promotion_evidence_id: str
    promotion_evidence_sha256: str
    shadow_attestation_id: str
    shadow_attestation_sha256: str
    validation_attestation: StrategyValidationAttestation
    validation_attestation_sha256: str
    risk_attestation: StrategyRiskAttestation
    risk_attestation_sha256: str
    genome_id: str
    genome_canonical_sha256: str
    evaluation_code_commit: str
    evaluation_runtime_sha256: str
    promotion_runtime_commit: str
    benchmark_excess_return_fraction: str
    cost_adjusted_alpha_fraction: str
    recent_alpha_fraction: str
    capacity_usd: str
    requested_tiny_live_tranche_usd: str
    admission_invariants: tuple[str, ...]
    gates: tuple[tuple[str, bool], ...]
    issues: tuple[str, ...]
    proposed_stage: str
    expires_at: str
    effective_at: str
    recorded_at: str
    proposed_live_enabled: bool = field(init=False, default=False)
    promotion_owner_role: str = field(init=False, default="strategy_learning")
    schema_version: int = field(init=False, default=1)
    analysis_only: bool = field(init=False, default=True)
    execution_authority: str = field(init=False, default="none")
    can_submit_orders: bool = field(init=False, default=False)

    def __post_init__(self) -> None:
        _object_id(
            self.proposal_id,
            kind=STRATEGY_PROMOTION_PROPOSAL_KIND,
            label="proposal_id",
        )
        _object_id(
            self.registration_id,
            kind="evaluation-registration",
            label="registration_id",
        )
        _object_id(
            self.promotion_evidence_id,
            kind="promotion-evidence",
            label="promotion_evidence_id",
        )
        _object_id(
            self.shadow_attestation_id,
            kind="paper-shadow-attestation",
            label="shadow_attestation_id",
        )
        for n in ("promotion_evidence_sha256", "shadow_attestation_sha256", "validation_attestation_sha256", "risk_attestation_sha256", "genome_canonical_sha256", "evaluation_runtime_sha256"):
            _sha(getattr(self, n), n)
        for n in ("evaluation_code_commit", "promotion_runtime_commit"):
            _commit(getattr(self, n), n)
        if type(self.sleeve) is not str or not self.sleeve:
            raise ValueError("sleeve is required")
        if self.validation_attestation_sha256 != _digest(self.validation_attestation.canonical_json_bytes()) or self.risk_attestation_sha256 != _digest(self.risk_attestation.canonical_json_bytes()):
            raise ValueError("attestation digest mismatch")
        for n in ("benchmark_excess_return_fraction", "cost_adjusted_alpha_fraction", "recent_alpha_fraction", "capacity_usd", "requested_tiny_live_tranche_usd"):
            _decimal_text(getattr(self, n), n, positive=n.endswith("usd"))
        if tuple(n for n, _ in self.gates) != STRATEGY_PROMOTION_GATE_ORDER or any(type(v) is not bool for _, v in self.gates):
            raise ValueError("proposal gates do not match fixed order")
        expected_issues = tuple(
            "risk_budget_mode_not_capped"
            if name == "risk_budget_mode_capped"
            else "risk_auto_promotion_disabled"
            if name == "risk_auto_promotion_allowed"
            else name
            for name, passed in self.gates
            if not passed
        )
        if self.issues != expected_issues:
            raise ValueError("proposal issues do not match failed gates in fixed order")
        if self.admission_invariants != STRATEGY_PROMOTION_ADMISSION_INVARIANTS:
            raise ValueError("admission_invariants do not match fixed order")
        if self.proposed_stage not in {"tiny_live_eligible", "paper_only"}:
            raise ValueError("proposal stage is invalid")
        if self.proposed_stage == "tiny_live_eligible" and not all(v for _, v in self.gates):
            raise ValueError("eligible proposal must pass operational gates")
        if self.proposed_stage == "paper_only" and all(v for _, v in self.gates):
            raise ValueError("paper-only proposal requires failed gate")
        effective = _time(self.effective_at, "effective_at")
        recorded = _time(self.recorded_at, "recorded_at")
        expires = _time(self.expires_at, "expires_at")
        if not effective <= recorded < expires:
            raise ValueError("proposal activity interval is invalid")

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> StrategyPromotionProposal:
        v = _exact_mapping(payload, set(_PROPOSAL_FIELDS), "strategy promotion proposal")
        if v["schema_version"] != 1 or v["analysis_only"] is not True or v["execution_authority"] != "none" or v["can_submit_orders"] is not False or v["proposed_live_enabled"] is not False or v["promotion_owner_role"] != "strategy_learning":
            raise ValueError("proposal fixed fields are invalid")
        if type(v["admission_invariants"]) is not list or type(v["gates"]) is not list or type(v["issues"]) is not list:
            raise TypeError("proposal sequences must be lists")
        gates = tuple((x[0], x[1]) for x in v["gates"] if type(x) is list and len(x) == 2)
        if len(gates) != len(v["gates"]):
            raise TypeError("proposal gates are invalid")
        args = {k: v[k] for k in _PROPOSAL_FIELDS if k not in {"proposed_live_enabled", "promotion_owner_role", "schema_version", "analysis_only", "execution_authority", "can_submit_orders", "validation_attestation", "risk_attestation", "admission_invariants", "gates", "issues"}}
        return cls(**args, validation_attestation=StrategyValidationAttestation.from_dict(v["validation_attestation"]), risk_attestation=StrategyRiskAttestation.from_dict(v["risk_attestation"]), admission_invariants=tuple(v["admission_invariants"]), gates=gates, issues=tuple(v["issues"]))  # type: ignore[arg-type]

    def to_dict(self) -> dict[str, object]:
        d = {n: getattr(self, n) for n in _PROPOSAL_FIELDS if n not in {"validation_attestation", "risk_attestation", "admission_invariants", "gates", "issues"}}
        d.update({"validation_attestation": self.validation_attestation.to_dict(), "risk_attestation": self.risk_attestation.to_dict(), "admission_invariants": list(self.admission_invariants), "gates": [[n, v] for n, v in self.gates], "issues": list(self.issues)})
        return d

    def canonical_json_bytes(self) -> bytes:
        return _canonical(self.to_dict())


def _durable(snapshot: Sequence[EvidenceEnvelope], kind: str, object_id: str, parser: Callable[[EvidenceEnvelope], object]) -> object:
    matches = [parser(x) for x in snapshot if x.kind == kind and x.object_id == object_id]
    if len(matches) != 1:
        raise ValueError("required durable evidence is absent")
    return matches[0]


def _current(source: str, at: datetime.datetime, seconds: int, label: str) -> bool:
    start = _time(source, label)
    return start <= at < start + datetime.timedelta(seconds=seconds)


class StrategyOperationalPromotionLedger:
    def __init__(self, root: str | Path, *, clock: Callable[[], datetime.datetime] | None = None):
        self._store = ImmutableStrategyEvidenceStore(root, clock=clock)
        self._clock = clock or (lambda: datetime.datetime.now(_UTC))
        self.root = Path(root)

    def _proposal(self, envelope: EvidenceEnvelope) -> StrategyPromotionProposal:
        if envelope.kind != STRATEGY_PROMOTION_PROPOSAL_KIND:
            raise ValueError("wrong proposal envelope kind")
        payload = _thaw_json(envelope.payload)
        if not isinstance(payload, dict):
            raise ValueError("proposal envelope payload is not an object")
        payload.update({"proposal_id": envelope.object_id, "effective_at": envelope.effective_at, "recorded_at": envelope.recorded_at})
        return StrategyPromotionProposal.from_dict(payload)

    def propose(self, *, promotion_evidence: StrategyPromotionEvidence, shadow_attestation: StrategyShadowAttestation, validation_attestation: StrategyValidationAttestation, risk_attestation: StrategyRiskAttestation, effective_at: datetime.datetime, expires_at: datetime.datetime) -> StrategyPromotionProposal:
        checked = _time_text(effective_at, "effective_at")
        expiry = _time_text(expires_at, "expires_at")
        moment = _time(checked, "effective_at")
        if (
            type(promotion_evidence) is not StrategyPromotionEvidence
            or type(shadow_attestation) is not StrategyShadowAttestation
            or type(validation_attestation) is not StrategyValidationAttestation
            or type(risk_attestation) is not StrategyRiskAttestation
        ):
            raise TypeError("proposal sources must be exact immutable strategy evidence")
        if not _safe_relative_reference(validation_attestation.report_ref):
            raise ValueError("validation report_ref must be a safe canonical repo-relative file")
        if not _safe_relative_reference(risk_attestation.risk_envelope_ref):
            raise ValueError("risk risk_envelope_ref must be a safe canonical repo-relative file")
        if _time(expiry, "expires_at") <= moment:
            raise ValueError("proposal expires_at must follow effective_at")
        snapshot = self._store.rebuild()
        promotion = _durable(snapshot, "promotion-evidence", promotion_evidence.evidence_id, StrategyPromotionEvidence.from_envelope)
        shadow = _durable(
            snapshot,
            "paper-shadow-attestation",
            shadow_attestation.shadow_attestation_id,
            _attestation_from_envelope,
        )
        registration = _durable(snapshot, "evaluation-registration", promotion.registration_id, StrategyEvaluationRegistration.from_envelope)
        if promotion.canonical_json_bytes() != promotion_evidence.canonical_json_bytes() or shadow.canonical_json_bytes() != shadow_attestation.canonical_json_bytes():
            raise ValueError("caller evidence is not byte-identical to durable evidence")
        if (promotion.registration_id, promotion.evaluation_runtime_sha256, promotion.genome_id, promotion.genome_canonical_sha256) != (registration.registration_id, registration.evaluation_runtime_sha256, registration.genome.genome_id, registration.genome_canonical_sha256):
            raise ValueError("promotion identity chain is invalid")
        if (shadow.registration_id, shadow.promotion_evidence_id, shadow.promotion_evidence_sha256, shadow.evaluation_runtime_sha256) != (registration.registration_id, promotion.evidence_id, _digest(promotion.canonical_json_bytes()), registration.evaluation_runtime_sha256):
            raise ValueError("shadow identity chain is invalid")
        require_active_evaluation_runtime(Path.cwd(), registration)
        invariants = (
            "internal_evidence_complete",
            "preregistered_schedule",
            "identity_chain_complete",
            "evaluation_code_commit_bound",
            "evaluation_runtime_bound",
            "benchmark_gate_already_passed",
            "cost_gate_already_passed",
            "recent_alpha_gate_already_passed",
            "validation_report_present",
            "risk_envelope_ref_present",
            "promotion_authority_confirmed",
            "internal_evidence_current",
            "validation_attestation_current",
            "shadow_attestation_current",
            "risk_attestation_current",
        )
        policy = authority_for(ActionClass.PROMOTION_CHANGE)
        source_gates = dict(promotion.gates)
        checks = (
            promotion.complete_internal_evidence,
            True,
            True,
            promotion.evaluation_code_commit == registration.evaluation_code_commit,
            True,
            source_gates.get("pooled_benchmark_excess_positive") is True,
            source_gates.get("pooled_benchmark_excess_positive") is True,
            source_gates.get("latest_window_benchmark_excess_positive") is True,
            bool(validation_attestation.report_ref),
            bool(risk_attestation.risk_envelope_ref),
            policy.allowed and not policy.human_required and policy.owner_role == "strategy_learning",
            _current(promotion.effective_at, moment, INTERNAL_EVIDENCE_MAX_AGE_SECONDS, "promotion evidence"),
            _current(validation_attestation.completed_at, moment, VALIDATION_ATTESTATION_MAX_AGE_SECONDS, "validation attestation"),
            _current(shadow.effective_at, moment, SHADOW_ATTESTATION_MAX_AGE_SECONDS, "shadow attestation"),
            _current(risk_attestation.reviewed_at, moment, RISK_ATTESTATION_MAX_AGE_SECONDS, "risk attestation"),
        )
        if not all(checks):
            raise ValueError("proposal admission invariants are not current and complete")
        sessions = shadow.tracked_sessions >= registration.evolution_policy.minimum_tracked_days
        reconciled = shadow.reconciliation_confirmed and shadow.buy_intents >= 1 and shadow.filled_buy_intents == shadow.buy_intents and not shadow.issues
        evidence = SleevePromotionEvidence(
            sleeve=registration.genome.family.value,
            preregistered=True,
            ci_green=validation_attestation.ci_green,
            shadow_confirmed=sessions and reconciled,
            benchmark_excess_return=Decimal(promotion.pooled_benchmark_excess_fraction),
            cost_adjusted_alpha=Decimal(promotion.pooled_benchmark_excess_fraction),
            recent_alpha=Decimal(promotion.latest_window_benchmark_excess_fraction),
            capacity_usd=risk_attestation.capacity_usd,
            requested_tiny_live_tranche_usd=Decimal(risk_attestation.tiny_live_tranche_usd),
            validation_report_ref=validation_attestation.report_ref,
            risk_envelope_ref=risk_attestation.risk_envelope_ref,
        )
        decision = evaluate_sleeve_promotion(evidence, arm_live=False, promoted_at=checked)
        if not all(decision.gates[n] for n in ("preregistered", "benchmark_gate_passed", "cost_gate_passed", "recent_alpha_gate_passed", "validation_report_present", "risk_envelope_ref_present")) or decision.live_enabled:
            raise ValueError("policy adapter admission failed")
        gates = (
            ("ci_green", validation_attestation.ci_green),
            ("shadow_sessions_sufficient", sessions),
            ("reconciliation_confirmed", reconciled),
            ("capacity_gate_passed", decision.gates["capacity_gate_passed"]),
            ("risk_budget_mode_capped", risk_attestation.capped_mode),
            ("risk_auto_promotion_allowed", risk_attestation.new_sleeve_auto_promote),
        )
        issues = tuple("risk_budget_mode_not_capped" if n == "risk_budget_mode_capped" else "risk_auto_promotion_disabled" if n == "risk_auto_promotion_allowed" else n for n, v in gates if not v)
        stage = "tiny_live_eligible" if all(v for _, v in gates) else "paper_only"
        deadlines = (
            moment + datetime.timedelta(seconds=STRATEGY_PROMOTION_PROPOSAL_MAX_TTL_SECONDS),
            _time(promotion.effective_at, "promotion effective_at") + datetime.timedelta(seconds=INTERNAL_EVIDENCE_MAX_AGE_SECONDS),
            _time(validation_attestation.completed_at, "validation completed_at") + datetime.timedelta(seconds=VALIDATION_ATTESTATION_MAX_AGE_SECONDS),
            _time(shadow.effective_at, "shadow effective_at") + datetime.timedelta(seconds=SHADOW_ATTESTATION_MAX_AGE_SECONDS),
            _time(risk_attestation.reviewed_at, "risk reviewed_at") + datetime.timedelta(seconds=RISK_ATTESTATION_MAX_AGE_SECONDS),
        )
        if _time(expiry, "expires_at") > min(deadlines):
            raise ValueError("proposal expiry exceeds earliest source deadline")
        payload = {
            "schema_version": 1,
            "sleeve": registration.genome.family.value,
            "registration_id": registration.registration_id,
            "promotion_evidence_id": promotion.evidence_id,
            "promotion_evidence_sha256": _digest(promotion.canonical_json_bytes()),
            "shadow_attestation_id": shadow.shadow_attestation_id,
            "shadow_attestation_sha256": _digest(shadow.canonical_json_bytes()),
            "validation_attestation": validation_attestation.to_dict(),
            "validation_attestation_sha256": _digest(validation_attestation.canonical_json_bytes()),
            "risk_attestation": risk_attestation.to_dict(),
            "risk_attestation_sha256": _digest(risk_attestation.canonical_json_bytes()),
            "genome_id": registration.genome.genome_id,
            "genome_canonical_sha256": registration.genome_canonical_sha256,
            "evaluation_code_commit": registration.evaluation_code_commit,
            "evaluation_runtime_sha256": registration.evaluation_runtime_sha256,
            "promotion_runtime_commit": validation_attestation.tested_commit,
            "benchmark_excess_return_fraction": promotion.pooled_benchmark_excess_fraction,
            "cost_adjusted_alpha_fraction": promotion.pooled_benchmark_excess_fraction,
            "recent_alpha_fraction": promotion.latest_window_benchmark_excess_fraction,
            "capacity_usd": str(risk_attestation.capacity_usd),
            "requested_tiny_live_tranche_usd": risk_attestation.tiny_live_tranche_usd,
            "admission_invariants": list(invariants),
            "gates": [[n, v] for n, v in gates],
            "issues": list(issues),
            "proposed_stage": stage,
            "proposed_live_enabled": False,
            "promotion_owner_role": "strategy_learning",
            "expires_at": expiry,
            "analysis_only": True,
            "execution_authority": "none",
            "can_submit_orders": False,
        }
        candidate = EvidenceCandidate(kind=STRATEGY_PROMOTION_PROPOSAL_KIND, effective_at=checked, payload=payload)
        def validate_proposal(
            _snapshot: tuple[EvidenceEnvelope, ...],
            envelope: EvidenceEnvelope,
        ) -> None:
            # The store, not the caller, assigns ``recorded_at``.  Refuse in
            # its pre-persistence validator when that stamp would leave no
            # half-open active interval, rather than admitting an immediately
            # unusable immutable event and discovering it on replay.
            if _time(envelope.recorded_at, "recorded_at") >= _time(
                expiry,
                "expires_at",
            ):
                raise ValueError("store clock left no active proposal interval")
            self._proposal(envelope)

        admitted = self._store.admit_checked(candidate, validate=validate_proposal)
        result = self._proposal(admitted.envelope)
        if _time(result.recorded_at, "recorded_at") >= _time(result.expires_at, "expires_at"):
            raise ValueError("store clock left no active proposal interval")
        return result

    def verify(self) -> tuple[StrategyPromotionProposal, ...]:
        return tuple(self._proposal(x) for x in self._store.verify() if x.kind == STRATEGY_PROMOTION_PROPOSAL_KIND)

    def rebuild(self) -> tuple[StrategyPromotionProposal, ...]:
        return tuple(self._proposal(x) for x in self._store.rebuild() if x.kind == STRATEGY_PROMOTION_PROPOSAL_KIND)
