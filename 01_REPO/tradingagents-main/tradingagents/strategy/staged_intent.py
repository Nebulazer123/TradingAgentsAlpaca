"""Immutable, analysis-only strategy intent evidence."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import unicodedata
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from tradingagents.strategy._immutable_evidence_store import (
    STAGED_PAPER_INTENT_KIND,
    EvidenceCandidate,
    EvidenceEnvelope,
    ImmutableStrategyEvidenceStore,
)
from tradingagents.strategy.compiler import (
    GenomePaperDecision,
    PaperCandidateState,
    PaperDecisionAction,
    StrategyObservation,
    compile_genome_paper_decision,
)
from tradingagents.strategy.genome import (
    CatalystRelativeStrengthMutationBounds,
    CurrentAggressiveMutationBounds,
    PullbackSupportMutationBounds,
    StrategyEvolutionPolicy,
    StrategyFamily,
    StrategyGenome,
    StrategyMutationBounds,
)
from tradingagents.strategy.promotion_evidence import (
    StrategyEvaluationRegistration,
    StrategyPromotionEvidence,
    require_active_evaluation_runtime,
)

STAGED_PAPER_INTENT_SCHEMA_VERSION = 1
STAGED_PAPER_INTENT_MAX_TTL_SECONDS = 900
STRATEGY_OBSERVATION_SOURCE_MAX_BYTES = 64
STRATEGY_OBSERVATION_REASON_MAX_UTF8_BYTES = 512

_OBSERVATION_SCHEMA_VERSION = 1
_DECIMAL_PATTERN = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?")
_DIGEST_PATTERN = re.compile(r"[0-9a-f]{64}")
_COMMIT_PATTERN = re.compile(r"[0-9a-f]{40}")
_DATE_PATTERN = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_SOURCE_PATTERN = re.compile(r"[a-z0-9][a-z0-9._:/-]{0,63}")
PAPER_CANDIDATE_STATE_KEYS = {
    "cash_usd",
    "reserved_buy_notional_usd",
    "held_symbols",
    "open_buy_symbols",
}
GENOME_PAPER_DECISION_KEYS = {
    "schema_version",
    "genome_id",
    "family",
    "action",
    "symbol",
    "notional_usd",
    "limit_price",
    "market_session",
    "extended_hours",
    "reason_code",
    "rejected_observation_count",
    "analysis_only",
    "paper_only",
    "execution_authority",
    "can_submit_orders",
}
_OBSERVATION_KEYS = frozenset(
    {
        "schema_version",
        "symbol",
        "score",
        "current_price",
        "daily_change_fraction",
        "volume_ratio",
        "time_sensitive",
        "source",
        "reason",
    }
)
_STAGED_INTENT_KEYS = frozenset(
    {
        "schema_version",
        "staged_intent_id",
        "registration_id",
        "promotion_evidence_id",
        "promotion_evidence_sha256",
        "genome",
        "genome_canonical_sha256",
        "evaluation_code_commit",
        "evaluation_runtime_sha256",
        "evolution_policy",
        "evolution_policy_sha256",
        "session_date",
        "observations",
        "observations_sha256",
        "candidate_state",
        "candidate_state_sha256",
        "market_session",
        "decision",
        "decision_sha256",
        "expires_at",
        "effective_at",
        "recorded_at",
        "analysis_only",
        "paper_only",
        "execution_authority",
        "can_submit_orders",
    }
)


def _canonical_json_bytes(payload: object) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _require_exact_fields(
    payload: object,
    expected: frozenset[str],
    *,
    label: str,
) -> Mapping[str, object]:
    if not isinstance(payload, Mapping):
        raise TypeError(f"{label} must be an object")
    actual = set(payload)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise ValueError(
            f"{label} fields do not match; missing={missing}, extra={extra}"
        )
    return payload


def _require_canonical_decimal_text(value: object, *, label: str) -> Decimal:
    if type(value) is not str:
        raise TypeError(f"{label} must be a decimal string")
    if _DECIMAL_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{label} must use canonical fixed-point syntax")
    parsed = Decimal(value)
    if not parsed.is_finite():
        raise ValueError(f"{label} must be finite")
    if parsed == 0 and value.startswith("-"):
        raise ValueError(f"{label} cannot use negative zero")
    canonical = format(parsed, "f")
    if "." in canonical:
        canonical = canonical.rstrip("0").rstrip(".")
    if value != canonical:
        raise ValueError(f"{label} must use canonical fixed-point syntax")
    return parsed


def _require_digest(value: object, *, label: str) -> str:
    if type(value) is not str or _DIGEST_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{label} must be lowercase 64-hex")
    return value


def _require_object_id(value: object, *, kind: str, label: str) -> str:
    if (
        type(value) is not str
        or not value.startswith(f"{kind}-")
        or _DIGEST_PATTERN.fullmatch(value.removeprefix(f"{kind}-")) is None
    ):
        raise ValueError(f"{label} must be a {kind} object ID")
    return value


def _require_canonical_utc(value: object, *, label: str) -> dt.datetime:
    if type(value) is not str:
        raise TypeError(f"{label} must be a timestamp string")
    try:
        parsed = dt.datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{label} must be canonical UTC") from exc
    if (
        parsed.tzinfo is None
        or parsed.utcoffset() != dt.timedelta(0)
        or parsed.microsecond != 0
        or parsed.isoformat(timespec="seconds") != value
    ):
        raise ValueError(f"{label} must be canonical whole-second UTC")
    return parsed


def _require_session_date(value: object) -> str:
    if type(value) is not str or _DATE_PATTERN.fullmatch(value) is None:
        raise ValueError("session_date must use YYYY-MM-DD")
    try:
        parsed = dt.date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("session_date must use YYYY-MM-DD") from exc
    if parsed.isoformat() != value:
        raise ValueError("session_date must use YYYY-MM-DD")
    return value


def _datetime_text(value: object, *, label: str) -> str:
    if type(value) is not dt.datetime:
        raise TypeError(f"{label} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")
    if value.microsecond != 0:
        raise ValueError(f"{label} must use whole seconds")
    return value.astimezone(dt.timezone.utc).isoformat(timespec="seconds")


def _thaw_json(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _thaw_json(item) for key, item in value.items()}
    if type(value) is tuple:
        return [_thaw_json(item) for item in value]
    return value


def _strategy_evolution_policy_from_dict(
    payload: object,
) -> StrategyEvolutionPolicy:
    values = _require_exact_fields(
        payload,
        frozenset(
            {
                "schema_version",
                "enabled",
                "experiment_starting_cash_usd",
                "candidate_min_order_usd",
                "max_active_candidates",
                "mutations_per_cycle",
                "minimum_tracked_days",
                "minimum_closed_trades",
                "minimum_walk_forward_windows",
                "maximum_paper_drawdown_pct",
                "mutation_bounds",
                "analysis_only",
                "execution_authority",
                "can_submit_orders",
            }
        ),
        label="strategy evolution policy",
    )
    if values["schema_version"] != 1:
        raise ValueError("strategy evolution policy schema_version does not match")
    if values["analysis_only"] is not True:
        raise ValueError("strategy evolution policy analysis_only must be true")
    if values["execution_authority"] != "none":
        raise ValueError(
            "strategy evolution policy execution_authority must be none"
        )
    if values["can_submit_orders"] is not False:
        raise ValueError(
            "strategy evolution policy can_submit_orders must be false"
        )
    bounds = _require_exact_fields(
        values["mutation_bounds"],
        frozenset(
            {
                "current-aggressive",
                "pullback-support",
                "catalyst-relative-strength",
            }
        ),
        label="mutation bounds",
    )
    aggressive = _require_exact_fields(
        bounds["current-aggressive"],
        frozenset({"min_score"}),
        label="current aggressive bounds",
    )
    pullback = _require_exact_fields(
        bounds["pullback-support"],
        frozenset(
            {
                "min_daily_change_fraction",
                "max_daily_change_fraction",
                "max_volume_ratio",
            }
        ),
        label="pullback support bounds",
    )
    catalyst = _require_exact_fields(
        bounds["catalyst-relative-strength"],
        frozenset({"min_score"}),
        label="catalyst relative strength bounds",
    )
    policy = StrategyEvolutionPolicy(
        enabled=values["enabled"],  # type: ignore[arg-type]
        experiment_starting_cash_usd=values["experiment_starting_cash_usd"],  # type: ignore[arg-type]
        candidate_min_order_usd=values["candidate_min_order_usd"],  # type: ignore[arg-type]
        max_active_candidates=values["max_active_candidates"],  # type: ignore[arg-type]
        mutations_per_cycle=values["mutations_per_cycle"],  # type: ignore[arg-type]
        minimum_tracked_days=values["minimum_tracked_days"],  # type: ignore[arg-type]
        minimum_closed_trades=values["minimum_closed_trades"],  # type: ignore[arg-type]
        minimum_walk_forward_windows=values["minimum_walk_forward_windows"],  # type: ignore[arg-type]
        maximum_paper_drawdown_pct=values["maximum_paper_drawdown_pct"],  # type: ignore[arg-type]
        mutation_bounds=StrategyMutationBounds(
            current_aggressive=CurrentAggressiveMutationBounds(
                min_score=aggressive["min_score"],  # type: ignore[arg-type]
            ),
            pullback_support=PullbackSupportMutationBounds(
                min_daily_change_fraction=pullback[
                    "min_daily_change_fraction"
                ],  # type: ignore[arg-type]
                max_daily_change_fraction=pullback[
                    "max_daily_change_fraction"
                ],  # type: ignore[arg-type]
                max_volume_ratio=pullback["max_volume_ratio"],  # type: ignore[arg-type]
            ),
            catalyst_relative_strength=CatalystRelativeStrengthMutationBounds(
                min_score=catalyst["min_score"],  # type: ignore[arg-type]
            ),
        ),
    )
    if policy.to_dict() != dict(values):
        raise ValueError("strategy evolution policy round trip is not exact")
    return policy


def _canonical_decimal_from_decimal(value: object, *, label: str) -> str:
    if type(value) is not Decimal:
        raise TypeError(f"{label} must be a Decimal")
    if not value.is_finite():
        raise ValueError(f"{label} must be finite")
    canonical = format(value, "f")
    if "." in canonical:
        canonical = canonical.rstrip("0").rstrip(".")
    if canonical == "-0":
        canonical = "0"
    return canonical


def _paper_candidate_state_to_dict(
    state: PaperCandidateState,
) -> dict[str, object]:
    if type(state) is not PaperCandidateState:
        raise TypeError("candidate_state must be a PaperCandidateState")
    return {
        "cash_usd": _canonical_decimal_from_decimal(
            state.cash_usd,
            label="cash_usd",
        ),
        "reserved_buy_notional_usd": _canonical_decimal_from_decimal(
            state.reserved_buy_notional_usd,
            label="reserved_buy_notional_usd",
        ),
        "held_symbols": list(state.held_symbols),
        "open_buy_symbols": list(state.open_buy_symbols),
    }


def _paper_candidate_state_from_dict(
    payload: Mapping[str, object],
) -> PaperCandidateState:
    values = _require_exact_fields(
        payload,
        frozenset(PAPER_CANDIDATE_STATE_KEYS),
        label="paper candidate state",
    )
    held_symbols = values["held_symbols"]
    open_buy_symbols = values["open_buy_symbols"]
    if type(held_symbols) is not list:
        raise TypeError("held_symbols must be a list")
    if type(open_buy_symbols) is not list:
        raise TypeError("open_buy_symbols must be a list")
    return PaperCandidateState(
        cash_usd=_require_canonical_decimal_text(
            values["cash_usd"],
            label="cash_usd",
        ),
        reserved_buy_notional_usd=_require_canonical_decimal_text(
            values["reserved_buy_notional_usd"],
            label="reserved_buy_notional_usd",
        ),
        held_symbols=tuple(held_symbols),  # type: ignore[arg-type]
        open_buy_symbols=tuple(open_buy_symbols),  # type: ignore[arg-type]
    )


def _genome_paper_decision_to_dict(
    decision: GenomePaperDecision,
) -> dict[str, object]:
    if type(decision) is not GenomePaperDecision:
        raise TypeError("decision must be a GenomePaperDecision")
    return decision.to_dict()


def _genome_paper_decision_from_dict(
    payload: Mapping[str, object],
) -> GenomePaperDecision:
    values = _require_exact_fields(
        payload,
        frozenset(GENOME_PAPER_DECISION_KEYS),
        label="genome paper decision",
    )
    if (
        type(values["schema_version"]) is not int
        or values["schema_version"] != 1
    ):
        raise ValueError("decision schema_version does not match")
    if values["analysis_only"] is not True:
        raise ValueError("decision analysis_only must be true")
    if values["paper_only"] is not True:
        raise ValueError("decision paper_only must be true")
    if values["execution_authority"] != "none":
        raise ValueError("decision execution_authority must be none")
    if values["can_submit_orders"] is not False:
        raise ValueError("decision can_submit_orders must be false")
    if type(values["family"]) is not str:
        raise TypeError("decision family must be a string")
    if type(values["action"]) is not str:
        raise TypeError("decision action must be a string")
    try:
        family = StrategyFamily(values["family"])
    except ValueError as exc:
        raise ValueError("decision family is not allowed") from exc
    try:
        action = PaperDecisionAction(values["action"])
    except ValueError as exc:
        raise ValueError("decision action is not allowed") from exc
    decision = GenomePaperDecision(
        genome_id=values["genome_id"],  # type: ignore[arg-type]
        family=family,
        action=action,
        symbol=values["symbol"],  # type: ignore[arg-type]
        notional_usd=values["notional_usd"],  # type: ignore[arg-type]
        limit_price=values["limit_price"],  # type: ignore[arg-type]
        market_session=values["market_session"],  # type: ignore[arg-type]
        extended_hours=values["extended_hours"],  # type: ignore[arg-type]
        reason_code=values["reason_code"],  # type: ignore[arg-type]
        rejected_observation_count=values["rejected_observation_count"],  # type: ignore[arg-type]
    )
    if decision.to_dict() != dict(values):
        raise ValueError("decision canonical round trip is not exact")
    return decision


@dataclass(frozen=True, slots=True)
class StrategyObservationEvidence:
    symbol: str
    score: str
    current_price: str
    daily_change_fraction: str
    volume_ratio: str
    time_sensitive: bool
    source: str
    reason: str
    schema_version: int = field(
        init=False,
        default=_OBSERVATION_SCHEMA_VERSION,
    )

    def __post_init__(self) -> None:
        score = _require_canonical_decimal_text(self.score, label="score")
        current_price = _require_canonical_decimal_text(
            self.current_price,
            label="current_price",
        )
        daily_change = _require_canonical_decimal_text(
            self.daily_change_fraction,
            label="daily_change_fraction",
        )
        volume_ratio = _require_canonical_decimal_text(
            self.volume_ratio,
            label="volume_ratio",
        )
        StrategyObservation(
            symbol=self.symbol,
            score=score,
            current_price=current_price,
            daily_change_fraction=daily_change,
            volume_ratio=volume_ratio,
            time_sensitive=self.time_sensitive,
        )
        if type(self.source) is not str:
            raise TypeError("source must be a string")
        try:
            source_bytes = self.source.encode("ascii")
        except UnicodeEncodeError as exc:
            raise ValueError("source must contain only ASCII bytes") from exc
        if (
            not 1 <= len(source_bytes) <= STRATEGY_OBSERVATION_SOURCE_MAX_BYTES
            or _SOURCE_PATTERN.fullmatch(self.source) is None
        ):
            raise ValueError(
                "source must be 1-64 lowercase provenance ASCII bytes"
            )
        if type(self.reason) is not str:
            raise TypeError("reason must be a string")
        reason_bytes = self.reason.encode("utf-8")
        if not reason_bytes:
            raise ValueError("reason must not be empty")
        if len(reason_bytes) > STRATEGY_OBSERVATION_REASON_MAX_UTF8_BYTES:
            raise ValueError("reason must be at most 512 UTF-8 bytes")
        if self.reason.strip() != self.reason:
            raise ValueError("reason must not have surrounding whitespace")
        if not all(character.isprintable() for character in self.reason):
            raise ValueError("reason must contain only printable characters")
        if unicodedata.normalize("NFC", self.reason) != self.reason:
            raise ValueError("reason must already be NFC-normalized")
        if self.schema_version != _OBSERVATION_SCHEMA_VERSION:
            raise ValueError("observation schema_version is fixed")

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, object],
    ) -> StrategyObservationEvidence:
        values = _require_exact_fields(
            payload,
            _OBSERVATION_KEYS,
            label="strategy observation evidence",
        )
        if values["schema_version"] != _OBSERVATION_SCHEMA_VERSION:
            raise ValueError("observation schema_version does not match")
        return cls(
            symbol=values["symbol"],  # type: ignore[arg-type]
            score=values["score"],  # type: ignore[arg-type]
            current_price=values["current_price"],  # type: ignore[arg-type]
            daily_change_fraction=values["daily_change_fraction"],  # type: ignore[arg-type]
            volume_ratio=values["volume_ratio"],  # type: ignore[arg-type]
            time_sensitive=values["time_sensitive"],  # type: ignore[arg-type]
            source=values["source"],  # type: ignore[arg-type]
            reason=values["reason"],  # type: ignore[arg-type]
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "symbol": self.symbol,
            "score": self.score,
            "current_price": self.current_price,
            "daily_change_fraction": self.daily_change_fraction,
            "volume_ratio": self.volume_ratio,
            "time_sensitive": self.time_sensitive,
            "source": self.source,
            "reason": self.reason,
        }

    def canonical_json_bytes(self) -> bytes:
        return _canonical_json_bytes(self.to_dict())

    def to_strategy_observation(self) -> StrategyObservation:
        return StrategyObservation(
            symbol=self.symbol,
            score=Decimal(self.score),
            current_price=Decimal(self.current_price),
            daily_change_fraction=Decimal(self.daily_change_fraction),
            volume_ratio=Decimal(self.volume_ratio),
            time_sensitive=self.time_sensitive,
        )


@dataclass(frozen=True, slots=True)
class StagedPaperIntent:
    staged_intent_id: str
    registration_id: str
    promotion_evidence_id: str
    promotion_evidence_sha256: str
    genome: StrategyGenome
    genome_canonical_sha256: str
    evaluation_code_commit: str
    evaluation_runtime_sha256: str
    evolution_policy: StrategyEvolutionPolicy
    evolution_policy_sha256: str
    session_date: str
    observations: tuple[StrategyObservationEvidence, ...]
    observations_sha256: str
    candidate_state: PaperCandidateState
    candidate_state_sha256: str
    market_session: str
    decision: GenomePaperDecision
    decision_sha256: str
    expires_at: str
    effective_at: str
    recorded_at: str
    schema_version: int = field(
        init=False,
        default=STAGED_PAPER_INTENT_SCHEMA_VERSION,
    )
    analysis_only: bool = field(init=False, default=True)
    paper_only: bool = field(init=False, default=True)
    execution_authority: str = field(init=False, default="none")
    can_submit_orders: bool = field(init=False, default=False)

    def __post_init__(self) -> None:
        _require_object_id(
            self.staged_intent_id,
            kind="staged-paper-intent",
            label="staged_intent_id",
        )
        _require_object_id(
            self.registration_id,
            kind="evaluation-registration",
            label="registration_id",
        )
        _require_object_id(
            self.promotion_evidence_id,
            kind="promotion-evidence",
            label="promotion_evidence_id",
        )
        _require_digest(
            self.promotion_evidence_sha256,
            label="promotion_evidence_sha256",
        )
        if type(self.genome) is not StrategyGenome:
            raise TypeError("genome must be a StrategyGenome")
        if self.genome_canonical_sha256 != hashlib.sha256(
            self.genome.canonical_json_bytes()
        ).hexdigest():
            raise ValueError("genome_canonical_sha256 does not match genome")
        if (
            type(self.evaluation_code_commit) is not str
            or _COMMIT_PATTERN.fullmatch(self.evaluation_code_commit) is None
        ):
            raise ValueError(
                "evaluation_code_commit must be lowercase 40-hex commit"
            )
        _require_digest(
            self.evaluation_runtime_sha256,
            label="evaluation_runtime_sha256",
        )
        if type(self.evolution_policy) is not StrategyEvolutionPolicy:
            raise TypeError("evolution_policy type does not match")
        if self.evolution_policy_sha256 != hashlib.sha256(
            self.evolution_policy.canonical_json_bytes()
        ).hexdigest():
            raise ValueError(
                "evolution_policy_sha256 does not match evolution policy"
            )
        _require_session_date(self.session_date)
        if type(self.observations) is not tuple:
            raise TypeError("observations must be an exact tuple")
        if any(
            type(observation) is not StrategyObservationEvidence
            for observation in self.observations
        ):
            raise TypeError(
                "observations must contain StrategyObservationEvidence"
            )
        symbols = tuple(observation.symbol for observation in self.observations)
        if len(set(symbols)) != len(symbols):
            raise ValueError("duplicate observation symbol")
        observations_bytes = _canonical_json_bytes(
            [observation.to_dict() for observation in self.observations]
        )
        if self.observations_sha256 != hashlib.sha256(
            observations_bytes
        ).hexdigest():
            raise ValueError(
                "observations_sha256 does not match ordered observations"
            )
        if type(self.candidate_state) is not PaperCandidateState:
            raise TypeError("candidate_state must be a PaperCandidateState")
        candidate_projection = _paper_candidate_state_to_dict(
            self.candidate_state
        )
        if self.candidate_state_sha256 != hashlib.sha256(
            _canonical_json_bytes(candidate_projection)
        ).hexdigest():
            raise ValueError(
                "candidate_state_sha256 does not match candidate state"
            )
        if type(self.decision) is not GenomePaperDecision:
            raise TypeError("decision must be a GenomePaperDecision")
        if self.market_session != self.decision.market_session:
            raise ValueError("market_session does not match decision")
        if self.decision.genome_id != self.genome.genome_id:
            raise ValueError("decision genome does not match staged genome")
        if self.decision.family is not self.genome.family:
            raise ValueError("decision family does not match staged genome")
        if self.decision_sha256 != hashlib.sha256(
            self.decision.canonical_json_bytes()
        ).hexdigest():
            raise ValueError("decision_sha256 does not match decision")
        expires_at = _require_canonical_utc(
            self.expires_at,
            label="expires_at",
        )
        effective_at = _require_canonical_utc(
            self.effective_at,
            label="effective_at",
        )
        recorded_at = _require_canonical_utc(
            self.recorded_at,
            label="recorded_at",
        )
        if effective_at > recorded_at:
            raise ValueError("future-effective staged intent is not allowed")
        if recorded_at >= expires_at:
            raise ValueError("staged intent is expired on first admission")
        ttl = expires_at - effective_at
        if (
            ttl <= dt.timedelta(0)
            or ttl
            > dt.timedelta(seconds=STAGED_PAPER_INTENT_MAX_TTL_SECONDS)
        ):
            raise ValueError("staged intent TTL must be at most 900 seconds")
        if self.schema_version != STAGED_PAPER_INTENT_SCHEMA_VERSION:
            raise ValueError("staged intent schema_version is fixed")
        if self.analysis_only is not True:
            raise ValueError("staged intent analysis_only is fixed")
        if self.paper_only is not True:
            raise ValueError("staged intent paper_only is fixed")
        if self.execution_authority != "none":
            raise ValueError("staged intent execution_authority is fixed")
        if self.can_submit_orders is not False:
            raise ValueError("staged intent can_submit_orders is fixed")
        expected_id = (
            "staged-paper-intent-"
            + hashlib.sha256(
                _canonical_json_bytes(
                    {
                        "kind": "staged-paper-intent",
                        "effective_at": self.effective_at,
                        "payload": self._evidence_payload(),
                    }
                )
            ).hexdigest()
        )
        if self.staged_intent_id != expected_id:
            raise ValueError("staged_intent_id does not match evidence identity")

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, object],
    ) -> StagedPaperIntent:
        values = _require_exact_fields(
            payload,
            _STAGED_INTENT_KEYS,
            label="staged paper intent",
        )
        if values["schema_version"] != STAGED_PAPER_INTENT_SCHEMA_VERSION:
            raise ValueError("staged intent schema_version does not match")
        if values["analysis_only"] is not True:
            raise ValueError("staged intent analysis_only must be true")
        if values["paper_only"] is not True:
            raise ValueError("staged intent paper_only must be true")
        if values["execution_authority"] != "none":
            raise ValueError("staged intent execution_authority must be none")
        if values["can_submit_orders"] is not False:
            raise ValueError("staged intent can_submit_orders must be false")
        raw_observations = values["observations"]
        if type(raw_observations) is not list:
            raise TypeError("observations must be a list")
        intent = cls(
            staged_intent_id=values["staged_intent_id"],  # type: ignore[arg-type]
            registration_id=values["registration_id"],  # type: ignore[arg-type]
            promotion_evidence_id=values["promotion_evidence_id"],  # type: ignore[arg-type]
            promotion_evidence_sha256=values["promotion_evidence_sha256"],  # type: ignore[arg-type]
            genome=StrategyGenome.from_dict(values["genome"]),  # type: ignore[arg-type]
            genome_canonical_sha256=values["genome_canonical_sha256"],  # type: ignore[arg-type]
            evaluation_code_commit=values["evaluation_code_commit"],  # type: ignore[arg-type]
            evaluation_runtime_sha256=values["evaluation_runtime_sha256"],  # type: ignore[arg-type]
            evolution_policy=_strategy_evolution_policy_from_dict(
                values["evolution_policy"]
            ),
            evolution_policy_sha256=values["evolution_policy_sha256"],  # type: ignore[arg-type]
            session_date=values["session_date"],  # type: ignore[arg-type]
            observations=tuple(
                StrategyObservationEvidence.from_dict(observation)  # type: ignore[arg-type]
                for observation in raw_observations
            ),
            observations_sha256=values["observations_sha256"],  # type: ignore[arg-type]
            candidate_state=_paper_candidate_state_from_dict(
                values["candidate_state"]  # type: ignore[arg-type]
            ),
            candidate_state_sha256=values["candidate_state_sha256"],  # type: ignore[arg-type]
            market_session=values["market_session"],  # type: ignore[arg-type]
            decision=_genome_paper_decision_from_dict(
                values["decision"]  # type: ignore[arg-type]
            ),
            decision_sha256=values["decision_sha256"],  # type: ignore[arg-type]
            expires_at=values["expires_at"],  # type: ignore[arg-type]
            effective_at=values["effective_at"],  # type: ignore[arg-type]
            recorded_at=values["recorded_at"],  # type: ignore[arg-type]
        )
        if intent.to_dict() != dict(values):
            raise ValueError("staged intent canonical round trip is not exact")
        return intent

    def _evidence_payload(self) -> dict[str, object]:
        payload = self.to_dict()
        for field_name in (
            "staged_intent_id",
            "effective_at",
            "recorded_at",
        ):
            del payload[field_name]
        return payload

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "staged_intent_id": self.staged_intent_id,
            "registration_id": self.registration_id,
            "promotion_evidence_id": self.promotion_evidence_id,
            "promotion_evidence_sha256": self.promotion_evidence_sha256,
            "genome": self.genome.to_dict(),
            "genome_canonical_sha256": self.genome_canonical_sha256,
            "evaluation_code_commit": self.evaluation_code_commit,
            "evaluation_runtime_sha256": self.evaluation_runtime_sha256,
            "evolution_policy": self.evolution_policy.to_dict(),
            "evolution_policy_sha256": self.evolution_policy_sha256,
            "session_date": self.session_date,
            "observations": [
                observation.to_dict() for observation in self.observations
            ],
            "observations_sha256": self.observations_sha256,
            "candidate_state": _paper_candidate_state_to_dict(
                self.candidate_state
            ),
            "candidate_state_sha256": self.candidate_state_sha256,
            "market_session": self.market_session,
            "decision": _genome_paper_decision_to_dict(self.decision),
            "decision_sha256": self.decision_sha256,
            "expires_at": self.expires_at,
            "effective_at": self.effective_at,
            "recorded_at": self.recorded_at,
            "analysis_only": self.analysis_only,
            "paper_only": self.paper_only,
            "execution_authority": self.execution_authority,
            "can_submit_orders": self.can_submit_orders,
        }

    def canonical_json_bytes(self) -> bytes:
        return _canonical_json_bytes(self.to_dict())

    def is_active(self, *, at: dt.datetime) -> bool:
        active_at = _require_canonical_utc(
            _datetime_text(at, label="at"),
            label="at",
        )
        recorded_at = _require_canonical_utc(
            self.recorded_at,
            label="recorded_at",
        )
        expires_at = _require_canonical_utc(
            self.expires_at,
            label="expires_at",
        )
        return recorded_at <= active_at < expires_at


def _registration_from_snapshot(
    snapshot: Sequence[EvidenceEnvelope],
    registration_id: str,
) -> StrategyEvaluationRegistration:
    matches = tuple(
        StrategyEvaluationRegistration.from_envelope(envelope)
        for envelope in snapshot
        if envelope.kind == "evaluation-registration"
        and envelope.object_id == registration_id
    )
    if len(matches) != 1:
        raise ValueError("registration must already be durable in this store")
    return matches[0]


def _promotion_from_snapshot(
    snapshot: Sequence[EvidenceEnvelope],
    promotion_evidence_id: str,
) -> StrategyPromotionEvidence:
    matches = tuple(
        StrategyPromotionEvidence.from_envelope(envelope)
        for envelope in snapshot
        if envelope.kind == "promotion-evidence"
        and envelope.object_id == promotion_evidence_id
    )
    if len(matches) != 1:
        raise ValueError(
            "promotion evidence must already be durable in this store"
        )
    return matches[0]


def _require_durable_lineage(
    registration: StrategyEvaluationRegistration,
    promotion_evidence: StrategyPromotionEvidence,
) -> None:
    if not promotion_evidence.complete_internal_evidence:
        raise ValueError(
            "complete internal promotion evidence is required for staging"
        )
    expected = {
        "registration_id": registration.registration_id,
        "genome_id": registration.genome.genome_id,
        "genome_canonical_sha256": registration.genome_canonical_sha256,
        "evaluation_code_commit": registration.evaluation_code_commit,
        "evaluation_runtime_sha256": registration.evaluation_runtime_sha256,
    }
    for field_name, value in expected.items():
        if getattr(promotion_evidence, field_name) != value:
            raise ValueError(
                f"promotion evidence {field_name} does not match registration"
            )
    if registration.evaluator_version == "":
        raise ValueError("registration evaluator lineage is missing")


def _staged_intent_from_envelope(
    envelope: EvidenceEnvelope,
) -> StagedPaperIntent:
    if type(envelope) is not EvidenceEnvelope:
        raise TypeError("staged intent envelope type does not match")
    if envelope.kind != STAGED_PAPER_INTENT_KIND:
        raise ValueError("envelope kind is not staged-paper-intent")
    raw_payload = _thaw_json(envelope.payload)
    if type(raw_payload) is not dict:
        raise ValueError("staged intent payload is not an object")
    full = {
        **raw_payload,
        "staged_intent_id": envelope.object_id,
        "effective_at": envelope.effective_at,
        "recorded_at": envelope.recorded_at,
    }
    intent = StagedPaperIntent.from_dict(full)
    if intent._evidence_payload() != raw_payload:
        raise ValueError("staged intent payload round trip is not exact")
    return intent


def _logical_slot(
    intent: StagedPaperIntent,
) -> tuple[str, str, str]:
    return (
        intent.promotion_evidence_id,
        intent.session_date,
        intent.market_session,
    )


def _require_logical_slot_available(
    admitted: Sequence[EvidenceEnvelope],
    candidate: StagedPaperIntent,
) -> None:
    candidate_slot = _logical_slot(candidate)
    for envelope in admitted:
        if (
            envelope.kind != STAGED_PAPER_INTENT_KIND
            or envelope.object_id == candidate.staged_intent_id
        ):
            continue
        if _logical_slot(_staged_intent_from_envelope(envelope)) == (
            candidate_slot
        ):
            raise ValueError(
                "staged intent logical slot already has different material"
            )


def _require_intent_bindings(
    intent: StagedPaperIntent,
    *,
    registration: StrategyEvaluationRegistration,
    promotion_evidence: StrategyPromotionEvidence,
    observations: tuple[StrategyObservationEvidence, ...],
    candidate_state: PaperCandidateState,
    decision: GenomePaperDecision,
) -> None:
    _require_durable_lineage(registration, promotion_evidence)
    if intent.registration_id != registration.registration_id:
        raise ValueError("staged registration dependency does not match")
    if intent.promotion_evidence_id != promotion_evidence.evidence_id:
        raise ValueError("staged promotion dependency does not match")
    if intent.promotion_evidence_sha256 != hashlib.sha256(
        promotion_evidence.canonical_json_bytes()
    ).hexdigest():
        raise ValueError("staged promotion evidence digest does not match")
    if intent.genome.canonical_json_bytes() != (
        registration.genome.canonical_json_bytes()
    ):
        raise ValueError("staged genome does not match registration")
    if intent.genome_canonical_sha256 != (
        registration.genome_canonical_sha256
    ):
        raise ValueError("staged genome digest does not match registration")
    if intent.evaluation_code_commit != registration.evaluation_code_commit:
        raise ValueError("staged evaluation commit does not match registration")
    if (
        intent.evaluation_runtime_sha256
        != registration.evaluation_runtime_sha256
    ):
        raise ValueError(
            "staged evaluation runtime does not match registration"
        )
    if intent.evolution_policy.canonical_json_bytes() != (
        registration.evolution_policy.canonical_json_bytes()
    ):
        raise ValueError("staged evolution policy does not match registration")
    if intent.evolution_policy_sha256 != (
        registration.evolution_policy_sha256
    ):
        raise ValueError(
            "staged evolution policy digest does not match registration"
        )
    if intent.observations != observations:
        raise ValueError("staged observations do not match admission snapshot")
    if intent.candidate_state != candidate_state:
        raise ValueError("staged candidate state does not match snapshot")
    if intent.decision.canonical_json_bytes() != decision.canonical_json_bytes():
        raise ValueError("staged decision does not match compiler replay")
    if _require_canonical_utc(
        promotion_evidence.effective_at,
        label="promotion evidence effective_at",
    ) > _require_canonical_utc(intent.effective_at, label="effective_at"):
        raise ValueError("staged intent predates promotion evidence")


def _intent_evidence_payload(
    *,
    registration: StrategyEvaluationRegistration,
    promotion_evidence: StrategyPromotionEvidence,
    observations: tuple[StrategyObservationEvidence, ...],
    candidate_state: PaperCandidateState,
    session_date: str,
    market_session: str,
    decision: GenomePaperDecision,
    expires_at: str,
) -> dict[str, object]:
    observation_payload = [
        observation.to_dict() for observation in observations
    ]
    candidate_projection = _paper_candidate_state_to_dict(candidate_state)
    return {
        "schema_version": STAGED_PAPER_INTENT_SCHEMA_VERSION,
        "registration_id": registration.registration_id,
        "promotion_evidence_id": promotion_evidence.evidence_id,
        "promotion_evidence_sha256": hashlib.sha256(
            promotion_evidence.canonical_json_bytes()
        ).hexdigest(),
        "genome": registration.genome.to_dict(),
        "genome_canonical_sha256": registration.genome_canonical_sha256,
        "evaluation_code_commit": registration.evaluation_code_commit,
        "evaluation_runtime_sha256": registration.evaluation_runtime_sha256,
        "evolution_policy": registration.evolution_policy.to_dict(),
        "evolution_policy_sha256": registration.evolution_policy_sha256,
        "session_date": session_date,
        "observations": observation_payload,
        "observations_sha256": hashlib.sha256(
            _canonical_json_bytes(observation_payload)
        ).hexdigest(),
        "candidate_state": candidate_projection,
        "candidate_state_sha256": hashlib.sha256(
            _canonical_json_bytes(candidate_projection)
        ).hexdigest(),
        "market_session": market_session,
        "decision": decision.to_dict(),
        "decision_sha256": hashlib.sha256(
            decision.canonical_json_bytes()
        ).hexdigest(),
        "expires_at": expires_at,
        "analysis_only": True,
        "paper_only": True,
        "execution_authority": "none",
        "can_submit_orders": False,
    }


class StrategyStagedIntentLedger:
    def __init__(
        self,
        root: str | Path,
        *,
        repo_root: str | Path,
        clock: Callable[[], dt.datetime] | None = None,
    ):
        self._repo_root = Path(repo_root)
        self._store = ImmutableStrategyEvidenceStore(root, clock=clock)

    def stage(
        self,
        *,
        registration: StrategyEvaluationRegistration,
        promotion_evidence: StrategyPromotionEvidence,
        observations: Sequence[StrategyObservationEvidence],
        candidate_state: PaperCandidateState,
        session_date: str,
        market_session: str,
        effective_at: dt.datetime,
        expires_at: dt.datetime,
    ) -> StagedPaperIntent:
        if type(registration) is not StrategyEvaluationRegistration:
            raise TypeError(
                "registration must be a StrategyEvaluationRegistration"
            )
        if type(promotion_evidence) is not StrategyPromotionEvidence:
            raise TypeError(
                "promotion_evidence must be a StrategyPromotionEvidence"
            )
        if isinstance(observations, (str, bytes)) or not isinstance(
            observations,
            Sequence,
        ):
            raise TypeError("observations must be a sequence")
        observations_snapshot = tuple(observations)
        if any(
            type(observation) is not StrategyObservationEvidence
            for observation in observations_snapshot
        ):
            raise TypeError(
                "observations must contain StrategyObservationEvidence"
            )
        candidate_snapshot = _paper_candidate_state_from_dict(
            _paper_candidate_state_to_dict(candidate_state)
        )
        session_date_snapshot = _require_session_date(session_date)
        if type(market_session) is not str:
            raise TypeError("market_session must be a string")
        effective_text = _datetime_text(effective_at, label="effective_at")
        expires_text = _datetime_text(expires_at, label="expires_at")

        snapshot = self._store.rebuild()
        durable_registration = _registration_from_snapshot(
            snapshot,
            registration.registration_id,
        )
        durable_promotion = _promotion_from_snapshot(
            snapshot,
            promotion_evidence.evidence_id,
        )
        if registration.canonical_json_bytes() != (
            durable_registration.canonical_json_bytes()
        ):
            raise ValueError("caller registration does not match durable bytes")
        if promotion_evidence.canonical_json_bytes() != (
            durable_promotion.canonical_json_bytes()
        ):
            raise ValueError(
                "caller promotion evidence does not match durable bytes"
            )
        _require_durable_lineage(durable_registration, durable_promotion)

        manifest_before = require_active_evaluation_runtime(
            self._repo_root,
            durable_registration,
        )
        decision = compile_genome_paper_decision(
            durable_registration.genome,
            durable_registration.evolution_policy,
            tuple(
                observation.to_strategy_observation()
                for observation in observations_snapshot
            ),
            candidate_snapshot,
            market_session=market_session,
        )
        manifest_after = require_active_evaluation_runtime(
            self._repo_root,
            durable_registration,
        )
        if manifest_before.canonical_json_bytes() != (
            manifest_after.canonical_json_bytes()
        ):
            raise ValueError("active evaluation runtime changed during compile")

        candidate = EvidenceCandidate(
            kind=STAGED_PAPER_INTENT_KIND,
            effective_at=effective_text,
            payload=_intent_evidence_payload(
                registration=durable_registration,
                promotion_evidence=durable_promotion,
                observations=observations_snapshot,
                candidate_state=candidate_snapshot,
                session_date=session_date_snapshot,
                market_session=market_session,
                decision=decision,
                expires_at=expires_text,
            ),
        )

        def validate(
            admitted: tuple[EvidenceEnvelope, ...],
            envelope: EvidenceEnvelope,
        ) -> None:
            locked_registration = _registration_from_snapshot(
                admitted,
                durable_registration.registration_id,
            )
            locked_promotion = _promotion_from_snapshot(
                admitted,
                durable_promotion.evidence_id,
            )
            if locked_registration.canonical_json_bytes() != (
                durable_registration.canonical_json_bytes()
            ):
                raise ValueError(
                    "durable registration changed during staged admission"
                )
            if locked_promotion.canonical_json_bytes() != (
                durable_promotion.canonical_json_bytes()
            ):
                raise ValueError(
                    "durable promotion evidence changed during staged admission"
                )
            intent = _staged_intent_from_envelope(envelope)
            _require_intent_bindings(
                intent,
                registration=locked_registration,
                promotion_evidence=locked_promotion,
                observations=observations_snapshot,
                candidate_state=candidate_snapshot,
                decision=decision,
            )
            _require_logical_slot_available(admitted, intent)

        def validate_orphans(
            orphans: tuple[EvidenceEnvelope, ...],
            envelope: EvidenceEnvelope,
        ) -> None:
            _require_logical_slot_available(
                orphans,
                _staged_intent_from_envelope(envelope),
            )

        admission = self._store.admit_checked(
            candidate,
            validate=validate,
            validate_orphans=validate_orphans,
        )
        return _staged_intent_from_envelope(admission.envelope)

    def verify(self) -> tuple[StagedPaperIntent, ...]:
        return self._replay(self._store.verify())

    def rebuild(self) -> tuple[StagedPaperIntent, ...]:
        return self._replay(self._store.rebuild())

    def _replay(
        self,
        snapshot: tuple[EvidenceEnvelope, ...],
    ) -> tuple[StagedPaperIntent, ...]:
        intents: list[StagedPaperIntent] = []
        for envelope in snapshot:
            if envelope.kind != STAGED_PAPER_INTENT_KIND:
                continue
            intent = _staged_intent_from_envelope(envelope)
            registration = _registration_from_snapshot(
                snapshot,
                intent.registration_id,
            )
            promotion_evidence = _promotion_from_snapshot(
                snapshot,
                intent.promotion_evidence_id,
            )
            manifest_before = require_active_evaluation_runtime(
                self._repo_root,
                registration,
            )
            decision = compile_genome_paper_decision(
                registration.genome,
                registration.evolution_policy,
                tuple(
                    observation.to_strategy_observation()
                    for observation in intent.observations
                ),
                intent.candidate_state,
                market_session=intent.market_session,
            )
            manifest_after = require_active_evaluation_runtime(
                self._repo_root,
                registration,
            )
            if manifest_before.canonical_json_bytes() != (
                manifest_after.canonical_json_bytes()
            ):
                raise ValueError(
                    "active evaluation runtime changed during replay"
                )
            _require_intent_bindings(
                intent,
                registration=registration,
                promotion_evidence=promotion_evidence,
                observations=intent.observations,
                candidate_state=intent.candidate_state,
                decision=decision,
            )
            intents.append(intent)
        return tuple(intents)
