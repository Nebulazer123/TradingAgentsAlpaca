"""Contract tests for the analysis-only strategy mutation registry."""

import ast
import dataclasses
import datetime as dt
import hashlib
import json
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError, dataclass
from decimal import Decimal, Inexact, getcontext
from pathlib import Path

import pytest

from tradingagents.strategy.genome import (
    CatalystRelativeStrengthMutationBounds,
    CatalystRelativeStrengthParameters,
    CurrentAggressiveMutationBounds,
    CurrentAggressiveParameters,
    HoldCashParameters,
    PullbackSupportMutationBounds,
    PullbackSupportParameters,
    StrategyEvolutionPolicy,
    StrategyFamily,
    StrategyGenome,
    StrategyMutationBounds,
)

UTC = dt.timezone.utc
REPO_ROOT = Path(__file__).parents[1]


class _Clock:
    def __init__(self, *values: dt.datetime):
        self._values = list(values)
        self._lock = threading.Lock()

    def __call__(self) -> dt.datetime:
        with self._lock:
            if len(self._values) > 1:
                return self._values.pop(0)
            return self._values[0]


def _run_git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ("git", *args),
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


@dataclass(frozen=True)
class _DurableMutationEvidence:
    root: Path
    registry: object
    parent: StrategyGenome
    policy: StrategyEvolutionPolicy
    registration: object
    source_evidence: object
    cycle_effective_at: dt.datetime


@pytest.fixture
def durable_mutation_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> _DurableMutationEvidence:
    import tradingagents.strategy.promotion_evidence as promotion_module
    from tradingagents.strategy.compiler import StrategyObservation
    from tradingagents.strategy.evaluator import (
        EvaluationFrame,
        EvaluationMark,
        StrategyEvaluationPolicy,
        evaluate_genome_window,
    )
    from tradingagents.strategy.mutation_registry import StrategyMutationRegistry
    from tradingagents.strategy.promotion_evidence import (
        EvaluationWindowSpec,
        StrategyPromotionEvidenceLedger,
    )

    original_git_text = promotion_module._git_text

    def clean_calculation_checkout(repo: Path, *args: str) -> str:
        if repo.resolve() == REPO_ROOT.resolve() and args == (
            "status",
            "--porcelain",
        ):
            return ""
        return original_git_text(repo, *args)

    monkeypatch.setattr(
        promotion_module,
        "_git_text",
        clean_calculation_checkout,
    )
    commit = _run_git(REPO_ROOT, "rev-parse", "HEAD")

    parent = StrategyGenome.create(
        family=StrategyFamily.CURRENT_AGGRESSIVE,
        parameters=CurrentAggressiveParameters("0.75"),
        generation=0,
        parent_id="root",
    )
    policy = _policy()
    root = tmp_path / "evidence"
    baseline_registry = StrategyMutationRegistry(
        root,
        clock=_Clock(dt.datetime(2029, 12, 31, 14, 30, tzinfo=UTC)),
    )
    baseline_registry.register_baseline(
        parent,
        policy,
        effective_at=dt.datetime(2029, 12, 31, 14, 0, tzinfo=UTC),
    )

    evaluation_policy = StrategyEvaluationPolicy(
        benchmark_symbol="SPY",
        holding_sessions=1,
        commission_bps_per_side="1",
        half_spread_bps_per_side="1",
        slippage_bps_per_side="1",
        round_trip_sides=2,
    )
    window = EvaluationWindowSpec(
        ordinal=1,
        window_start="2030-01-02",
        window_end="2030-01-03",
        first_effective_at="2030-01-02T15:00:00Z",
        last_effective_at="2030-01-03T15:00:00Z",
        evaluation_as_of="2030-01-03T16:00:00Z",
        expected_tracked_sessions=2,
    )
    ledger = StrategyPromotionEvidenceLedger(
        root,
        repo_root=REPO_ROOT,
        clock=_Clock(
            dt.datetime(2029, 12, 31, 16, 0, tzinfo=UTC),
            dt.datetime(2030, 1, 3, 16, 1, tzinfo=UTC),
            dt.datetime(2030, 1, 3, 16, 2, tzinfo=UTC),
        ),
    )
    registration = ledger.register(
        genome=parent,
        evolution_policy=policy,
        evaluation_policy=evaluation_policy,
        windows=(window,),
        evaluation_code_commit=commit,
        effective_at=dt.datetime(2029, 12, 31, 15, 0, tzinfo=UTC),
    )
    frames = tuple(
        EvaluationFrame(
            session_date=effective.date(),
            effective_at=effective,
            recorded_at=effective + dt.timedelta(minutes=1),
            market_session="regular",
            observations=(
                StrategyObservation(
                    symbol="NFLX",
                    score=Decimal("0.8"),
                    current_price=price,
                    daily_change_fraction=Decimal("-0.01"),
                    volume_ratio=Decimal("1"),
                    time_sensitive=True,
                ),
            ),
            marks=(EvaluationMark("NFLX", price),),
            benchmark_price=Decimal("100"),
        )
        for effective, price in (
            (dt.datetime(2030, 1, 2, 15, 0, tzinfo=UTC), Decimal("100")),
            (dt.datetime(2030, 1, 3, 15, 0, tzinfo=UTC), Decimal("101")),
        )
    )
    result = evaluate_genome_window(
        parent,
        policy,
        evaluation_policy,
        frames,
        evaluation_as_of=dt.datetime(2030, 1, 3, 16, 0, tzinfo=UTC),
    )
    ledger.admit_window(registration.registration_id, 1, frames, result)
    source_evidence = ledger.assemble(registration.registration_id)
    cycle_effective_at = dt.datetime(2030, 1, 3, 16, 3, tzinfo=UTC)
    registry = StrategyMutationRegistry(
        root,
        clock=_Clock(dt.datetime(2030, 1, 3, 16, 4, tzinfo=UTC)),
    )
    return _DurableMutationEvidence(
        root=root,
        registry=registry,
        parent=parent,
        policy=policy,
        registration=registration,
        source_evidence=source_evidence,
        cycle_effective_at=cycle_effective_at,
    )


def test_durable_mutation_fixture_contains_source_and_referenced_registration(
    durable_mutation_evidence: _DurableMutationEvidence,
):
    # Break caught: constructing a source fixture without its durable registration.
    from tradingagents.strategy._immutable_evidence_store import (
        ImmutableStrategyEvidenceStore,
    )
    from tradingagents.strategy.promotion_evidence import (
        StrategyEvaluationRegistration,
        StrategyPromotionEvidence,
    )

    snapshot = ImmutableStrategyEvidenceStore(
        durable_mutation_evidence.root
    ).rebuild()
    source_envelope = next(
        item
        for item in snapshot
        if item.object_id == durable_mutation_evidence.source_evidence.evidence_id
    )
    source = StrategyPromotionEvidence.from_envelope(source_envelope)
    registration_envelope = next(
        item for item in snapshot if item.object_id == source.registration_id
    )
    registration = StrategyEvaluationRegistration.from_envelope(
        registration_envelope
    )

    assert source.canonical_json_bytes() == (
        durable_mutation_evidence.source_evidence.canonical_json_bytes()
    )
    assert registration.canonical_json_bytes() == (
        durable_mutation_evidence.registration.canonical_json_bytes()
    )


def _register_mutation(
    evidence: _DurableMutationEvidence,
    *,
    registry=None,
    source_evidence=None,
    parent: StrategyGenome | None = None,
    child: StrategyGenome | None = None,
    policy: StrategyEvolutionPolicy | None = None,
    effective_at: dt.datetime | None = None,
    cycle_id: str | None = None,
    ordinal: int = 1,
):
    from tradingagents.strategy.mutation_registry import (
        build_mutated_genome,
        build_mutation_cycle_id,
    )

    active_registry = registry or evidence.registry
    active_source = source_evidence or evidence.source_evidence
    active_parent = parent or evidence.parent
    active_policy = policy or evidence.policy
    active_child = child or build_mutated_genome(
        active_parent,
        "current-aggressive.min_score",
        "0.1",
        active_policy,
    )
    active_effective_at = effective_at or evidence.cycle_effective_at
    parent_digest = hashlib.sha256(
        active_parent.canonical_json_bytes()
    ).hexdigest()
    policy_digest = hashlib.sha256(
        active_policy.canonical_json_bytes()
    ).hexdigest()
    active_cycle_id = cycle_id or build_mutation_cycle_id(
        source_evidence_id=active_source.evidence_id,
        parent_genome_canonical_sha256=parent_digest,
        evolution_policy_sha256=policy_digest,
        cycle_effective_at=active_effective_at,
    )
    return active_registry.register_mutation(
        cycle_id=active_cycle_id,
        ordinal=ordinal,
        source_evidence=active_source,
        parent=active_parent,
        child=active_child,
        evolution_policy=active_policy,
        effective_at=active_effective_at,
    )


def _evidence_payload(model, *identity_fields: str) -> dict[str, object]:
    payload = model.to_dict()
    for field_name in identity_fields:
        del payload[field_name]
    return payload


def _admit_material(
    root: Path,
    *,
    clock: dt.datetime,
    kind: str,
    effective_at: str,
    payload: dict[str, object],
):
    from tradingagents.strategy._immutable_evidence_store import (
        EvidenceCandidate,
        ImmutableStrategyEvidenceStore,
    )

    return ImmutableStrategyEvidenceStore(
        root,
        clock=_Clock(clock),
    ).admit_checked(
        EvidenceCandidate(
            kind=kind,
            effective_at=effective_at,
            payload=payload,
        ),
        validate=lambda _snapshot, _envelope: None,
    ).envelope


def _variant_durable_source(
    tmp_path: Path,
    evidence: _DurableMutationEvidence,
    *,
    include_baseline: bool = True,
    include_registration: bool = True,
    registration_payload: dict[str, object] | None = None,
    source_changes: dict[str, object] | None = None,
):
    from tradingagents.strategy._immutable_evidence_store import (
        ImmutableStrategyEvidenceStore,
    )
    from tradingagents.strategy.mutation_registry import StrategyMutationRegistry
    from tradingagents.strategy.promotion_evidence import (
        StrategyPromotionEvidence,
    )

    snapshot = ImmutableStrategyEvidenceStore(evidence.root).rebuild()
    baseline_envelope = next(item for item in snapshot if item.kind == "baseline-genome")
    registration_envelope = next(
        item
        for item in snapshot
        if item.object_id == evidence.registration.registration_id
    )
    source_envelope = next(
        item
        for item in snapshot
        if item.object_id == evidence.source_evidence.evidence_id
    )
    root = tmp_path / "variant-evidence"
    if include_baseline:
        _admit_material(
            root,
            clock=dt.datetime(2029, 12, 31, 14, 30, tzinfo=UTC),
            kind=baseline_envelope.kind,
            effective_at=baseline_envelope.effective_at,
            payload=dict(baseline_envelope.payload),
        )

    active_registration_envelope = None
    if include_registration:
        active_registration_envelope = _admit_material(
            root,
            clock=dt.datetime(2029, 12, 31, 16, 0, tzinfo=UTC),
            kind="evaluation-registration",
            effective_at=registration_envelope.effective_at,
            payload=(
                registration_payload
                if registration_payload is not None
                else dict(registration_envelope.payload)
            ),
        )

    source_payload = dict(source_envelope.payload)
    if active_registration_envelope is not None:
        source_payload["registration_id"] = (
            active_registration_envelope.object_id
        )
    if source_changes:
        source_payload.update(source_changes)
    active_source_envelope = _admit_material(
        root,
        clock=dt.datetime(2030, 1, 3, 16, 2, tzinfo=UTC),
        kind="promotion-evidence",
        effective_at=source_envelope.effective_at,
        payload=source_payload,
    )
    source = StrategyPromotionEvidence.from_envelope(active_source_envelope)
    registry = StrategyMutationRegistry(
        root,
        clock=_Clock(dt.datetime(2030, 1, 3, 16, 4, tzinfo=UTC)),
    )
    return registry, source, active_registration_envelope


def test_source_and_registration_traversal_admits_a_valid_durable_mutation(
    durable_mutation_evidence: _DurableMutationEvidence,
):
    # Break caught: accepting caller evidence without traversing its durable source chain.
    record = _register_mutation(durable_mutation_evidence)

    assert record.source_evidence_id == (
        durable_mutation_evidence.source_evidence.evidence_id
    )
    assert record.parent_genome == durable_mutation_evidence.parent
    assert record.child_genome.generation == 1
    assert record.analysis_only is True
    assert record.execution_authority == "none"
    assert record.can_submit_orders is False


def test_source_bytes_must_equal_the_durable_reader_facing_object(
    durable_mutation_evidence: _DurableMutationEvidence,
):
    # Break caught: trusting a caller object that only reuses the durable source ID.
    changed_caller = dataclasses.replace(
        durable_mutation_evidence.source_evidence,
        recorded_at="2030-01-03T16:03:00+00:00",
    )

    with pytest.raises(ValueError, match="source"):
        _register_mutation(
            durable_mutation_evidence,
            source_evidence=changed_caller,
        )


def test_missing_referenced_registration_is_rejected(
    tmp_path: Path,
    durable_mutation_evidence: _DurableMutationEvidence,
):
    # Break caught: admitting a mutation when the source registration is not durable.
    registry, source, _registration = _variant_durable_source(
        tmp_path,
        durable_mutation_evidence,
        include_registration=False,
    )

    with pytest.raises(ValueError, match="registration"):
        _register_mutation(
            durable_mutation_evidence,
            registry=registry,
            source_evidence=source,
        )


@pytest.mark.parametrize(
    ("field_name", "changed_value"),
    (
        ("evaluation_code_commit", "f" * 40),
        ("evaluation_runtime_sha256", "f" * 64),
    ),
)
def test_registration_commit_and_runtime_binding_is_revalidated(
    tmp_path: Path,
    durable_mutation_evidence: _DurableMutationEvidence,
    field_name: str,
    changed_value: str,
):
    # Break caught: accepting promotion provenance that disagrees with registration.
    registry, source, _registration = _variant_durable_source(
        tmp_path,
        durable_mutation_evidence,
        source_changes={field_name: changed_value},
    )

    with pytest.raises(ValueError, match="provenance"):
        _register_mutation(
            durable_mutation_evidence,
            registry=registry,
            source_evidence=source,
        )


def test_caller_policy_digest_must_match_the_embedded_registration_policy(
    durable_mutation_evidence: _DurableMutationEvidence,
):
    # Break caught: validating bounds from a caller policy not fixed by registration.
    changed_policy = _policy(current_aggressive_bound="0.2")

    with pytest.raises(ValueError, match="policy"):
        _register_mutation(
            durable_mutation_evidence,
            policy=changed_policy,
        )


def test_malformed_embedded_policy_digest_is_rejected(
    tmp_path: Path,
    durable_mutation_evidence: _DurableMutationEvidence,
):
    # Break caught: trusting the registration's digest without recomputing its policy.
    registration_payload = _evidence_payload(
        durable_mutation_evidence.registration,
        "registration_id",
        "effective_at",
        "recorded_at",
    )
    registration_payload["evolution_policy_sha256"] = "f" * 64
    registry, source, _registration = _variant_durable_source(
        tmp_path,
        durable_mutation_evidence,
        registration_payload=registration_payload,
    )

    with pytest.raises(ValueError, match="policy"):
        _register_mutation(
            durable_mutation_evidence,
            registry=registry,
            source_evidence=source,
        )


def test_wrong_registration_payload_kind_is_rejected(
    tmp_path: Path,
    durable_mutation_evidence: _DurableMutationEvidence,
):
    # Break caught: parsing promotion-evidence-shaped bytes as a registration.
    registration_payload = _evidence_payload(
        durable_mutation_evidence.source_evidence,
        "evidence_id",
        "effective_at",
        "recorded_at",
    )
    registry, source, _registration = _variant_durable_source(
        tmp_path,
        durable_mutation_evidence,
        registration_payload=registration_payload,
    )

    with pytest.raises(ValueError, match="registration"):
        _register_mutation(
            durable_mutation_evidence,
            registry=registry,
            source_evidence=source,
        )


def test_disabled_embedded_policy_is_rejected(
    tmp_path: Path,
    durable_mutation_evidence: _DurableMutationEvidence,
):
    # Break caught: admitting mutations from a durable policy with evolution disabled.
    disabled_policy = _policy(enabled=False)
    registration_payload = _evidence_payload(
        durable_mutation_evidence.registration,
        "registration_id",
        "effective_at",
        "recorded_at",
    )
    registration_payload["evolution_policy"] = disabled_policy.to_dict()
    registration_payload["evolution_policy_sha256"] = hashlib.sha256(
        disabled_policy.canonical_json_bytes()
    ).hexdigest()
    registry, source, _registration = _variant_durable_source(
        tmp_path,
        durable_mutation_evidence,
        registration_payload=registration_payload,
    )

    with pytest.raises(ValueError, match="disabled"):
        _register_mutation(
            durable_mutation_evidence,
            registry=registry,
            source_evidence=source,
            policy=disabled_policy,
        )


def test_embedded_policy_bound_is_authoritative(
    tmp_path: Path,
    durable_mutation_evidence: _DurableMutationEvidence,
):
    # Break caught: checking the mutation against a non-durable or stale bound.
    from tradingagents.strategy.mutation_registry import build_mutated_genome

    narrow_policy = _policy(current_aggressive_bound="0.01")
    registration_payload = _evidence_payload(
        durable_mutation_evidence.registration,
        "registration_id",
        "effective_at",
        "recorded_at",
    )
    registration_payload["evolution_policy"] = narrow_policy.to_dict()
    registration_payload["evolution_policy_sha256"] = hashlib.sha256(
        narrow_policy.canonical_json_bytes()
    ).hexdigest()
    registry, source, _registration = _variant_durable_source(
        tmp_path,
        durable_mutation_evidence,
        registration_payload=registration_payload,
    )
    excessive_child = build_mutated_genome(
        durable_mutation_evidence.parent,
        "current-aggressive.min_score",
        "0.1",
        durable_mutation_evidence.policy,
    )

    with pytest.raises(ValueError, match="bound"):
        _register_mutation(
            durable_mutation_evidence,
            registry=registry,
            source_evidence=source,
            policy=narrow_policy,
            child=excessive_child,
        )


def test_parent_must_be_durable_in_the_same_store(
    tmp_path: Path,
    durable_mutation_evidence: _DurableMutationEvidence,
):
    # Break caught: admitting lineage from a caller-only parent genome.
    registry, source, _registration = _variant_durable_source(
        tmp_path,
        durable_mutation_evidence,
        include_baseline=False,
    )

    with pytest.raises(ValueError, match="parent"):
        _register_mutation(
            durable_mutation_evidence,
            registry=registry,
            source_evidence=source,
        )


def test_mutation_effective_time_cannot_predate_durable_source(
    durable_mutation_evidence: _DurableMutationEvidence,
):
    # Break caught: deriving causality from caller times instead of durable first-seen time.
    with pytest.raises(ValueError, match="predates"):
        _register_mutation(
            durable_mutation_evidence,
            effective_at=dt.datetime(2030, 1, 3, 16, 1, tzinfo=UTC),
        )


def test_mutation_effective_time_cannot_predate_durable_parent(
    tmp_path: Path,
    durable_mutation_evidence: _DurableMutationEvidence,
):
    # Break caught: checking source chronology but ignoring later parent first-seen time.
    from tradingagents.strategy._immutable_evidence_store import (
        ImmutableStrategyEvidenceStore,
    )
    from tradingagents.strategy.mutation_registry import StrategyMutationRegistry
    from tradingagents.strategy.promotion_evidence import (
        StrategyPromotionEvidence,
    )

    snapshot = ImmutableStrategyEvidenceStore(
        durable_mutation_evidence.root
    ).rebuild()
    baseline = next(item for item in snapshot if item.kind == "baseline-genome")
    registration = next(
        item
        for item in snapshot
        if item.object_id == durable_mutation_evidence.registration.registration_id
    )
    source = next(
        item
        for item in snapshot
        if item.object_id == durable_mutation_evidence.source_evidence.evidence_id
    )
    root = tmp_path / "late-parent"
    _admit_material(
        root,
        clock=dt.datetime(2029, 12, 31, 16, 0, tzinfo=UTC),
        kind=registration.kind,
        effective_at=registration.effective_at,
        payload=dict(registration.payload),
    )
    durable_source = _admit_material(
        root,
        clock=dt.datetime(2030, 1, 3, 16, 2, tzinfo=UTC),
        kind=source.kind,
        effective_at=source.effective_at,
        payload=dict(source.payload),
    )
    _admit_material(
        root,
        clock=dt.datetime(2030, 1, 3, 16, 3, tzinfo=UTC),
        kind=baseline.kind,
        effective_at=baseline.effective_at,
        payload=dict(baseline.payload),
    )
    registry = StrategyMutationRegistry(
        root,
        clock=_Clock(dt.datetime(2030, 1, 3, 16, 4, tzinfo=UTC)),
    )

    with pytest.raises(ValueError, match="predates"):
        _register_mutation(
            durable_mutation_evidence,
            registry=registry,
            source_evidence=StrategyPromotionEvidence.from_envelope(
                durable_source
            ),
            effective_at=dt.datetime(2030, 1, 3, 16, 2, tzinfo=UTC),
        )


def test_source_and_policy_validation_is_io_free(
    durable_mutation_evidence: _DurableMutationEvidence,
    monkeypatch: pytest.MonkeyPatch,
):
    # Break caught: replaying promotion workflows or calculation I/O in validation.
    import tradingagents.strategy.evaluator as evaluator_module
    import tradingagents.strategy.promotion_evidence as promotion_module

    def unexpected_io(*_args, **_kwargs):
        raise AssertionError("snapshot validation performed forbidden I/O")

    monkeypatch.setattr(promotion_module, "_git_text", unexpected_io)
    monkeypatch.setattr(promotion_module, "_read_regular_source", unexpected_io)
    monkeypatch.setattr(
        promotion_module.StrategyPromotionEvidenceLedger,
        "__init__",
        unexpected_io,
    )
    monkeypatch.setattr(
        evaluator_module,
        "evaluate_genome_window",
        unexpected_io,
    )

    record = _register_mutation(durable_mutation_evidence)
    assert durable_mutation_evidence.registry.verify() == (record,)
    assert durable_mutation_evidence.registry.rebuild() == (record,)


def test_cycle_ordinals_must_start_at_one_and_be_contiguous(
    durable_mutation_evidence: _DurableMutationEvidence,
):
    # Break caught: allowing a cycle to skip its first or next ordinal.
    from tradingagents.strategy.mutation_registry import build_mutated_genome

    with pytest.raises(ValueError, match="ordinal"):
        _register_mutation(durable_mutation_evidence, ordinal=2)

    _register_mutation(durable_mutation_evidence)
    negative_child = build_mutated_genome(
        durable_mutation_evidence.parent,
        "current-aggressive.min_score",
        "-0.1",
        durable_mutation_evidence.policy,
    )
    with pytest.raises(ValueError, match="ordinal"):
        _register_mutation(
            durable_mutation_evidence,
            child=negative_child,
            ordinal=3,
        )


def test_two_distinct_contiguous_ordinals_share_exact_cycle_material(
    durable_mutation_evidence: _DurableMutationEvidence,
):
    # Break caught: letting one cycle change source, parent, policy, or effective time.
    from tradingagents.strategy.mutation_registry import build_mutated_genome

    first = _register_mutation(durable_mutation_evidence)
    second = _register_mutation(
        durable_mutation_evidence,
        ordinal=2,
        child=build_mutated_genome(
            durable_mutation_evidence.parent,
            "current-aggressive.min_score",
            "-0.1",
            durable_mutation_evidence.policy,
        ),
    )

    assert first.cycle_id == second.cycle_id
    assert first.source_evidence_id == second.source_evidence_id
    assert (
        first.parent_genome_canonical_sha256
        == second.parent_genome_canonical_sha256
    )
    assert first.evolution_policy_sha256 == second.evolution_policy_sha256
    assert first.effective_at == second.effective_at
    assert (first.ordinal, second.ordinal) == (1, 2)


def test_verify_and_rebuild_accept_a_complete_contiguous_cycle(
    durable_mutation_evidence: _DurableMutationEvidence,
):
    # Break caught: replay treating later durable ordinals as if they preceded ordinal one.
    from tradingagents.strategy.mutation_registry import build_mutated_genome

    first = _register_mutation(durable_mutation_evidence)
    second = _register_mutation(
        durable_mutation_evidence,
        ordinal=2,
        child=build_mutated_genome(
            durable_mutation_evidence.parent,
            "current-aggressive.min_score",
            "-0.1",
            durable_mutation_evidence.policy,
        ),
    )

    assert durable_mutation_evidence.registry.verify() == (first, second)
    assert durable_mutation_evidence.registry.rebuild() == (first, second)


def test_duplicate_cycle_slot_with_different_child_is_rejected(
    durable_mutation_evidence: _DurableMutationEvidence,
):
    # Break caught: mapping one cycle ordinal to two immutable mutations.
    from tradingagents.strategy.mutation_registry import build_mutated_genome

    _register_mutation(durable_mutation_evidence)
    changed_child = build_mutated_genome(
        durable_mutation_evidence.parent,
        "current-aggressive.min_score",
        "-0.1",
        durable_mutation_evidence.policy,
    )

    with pytest.raises(ValueError, match="slot|ordinal"):
        _register_mutation(
            durable_mutation_evidence,
            child=changed_child,
        )


def test_embedded_mutations_per_cycle_caps_ordinals(
    durable_mutation_evidence: _DurableMutationEvidence,
):
    # Break caught: accepting more records than the durable cycle policy allows.
    from tradingagents.strategy.mutation_registry import build_mutated_genome

    _register_mutation(durable_mutation_evidence)
    _register_mutation(
        durable_mutation_evidence,
        ordinal=2,
        child=build_mutated_genome(
            durable_mutation_evidence.parent,
            "current-aggressive.min_score",
            "-0.1",
            durable_mutation_evidence.policy,
        ),
    )
    third_child = build_mutated_genome(
        durable_mutation_evidence.parent,
        "current-aggressive.min_score",
        "0.05",
        durable_mutation_evidence.policy,
    )

    with pytest.raises(ValueError, match="cycle|ordinal"):
        _register_mutation(
            durable_mutation_evidence,
            ordinal=3,
            child=third_child,
        )


def test_duplicate_child_full_digest_is_rejected_across_cycles(
    durable_mutation_evidence: _DurableMutationEvidence,
):
    # Break caught: admitting a second lineage edge for the same full child bytes.
    first = _register_mutation(durable_mutation_evidence)

    with pytest.raises(ValueError, match="child"):
        _register_mutation(
            durable_mutation_evidence,
            child=first.child_genome,
            effective_at=dt.datetime(2030, 1, 3, 16, 4, tzinfo=UTC),
        )


def test_duplicate_semantic_child_is_rejected_against_a_baseline(
    durable_mutation_evidence: _DurableMutationEvidence,
):
    # Break caught: admitting an existing semantic genome under new lineage bytes.
    from tradingagents.strategy.mutation_registry import StrategyMutationRegistry

    duplicate_semantic_root = StrategyGenome.create(
        family=StrategyFamily.CURRENT_AGGRESSIVE,
        parameters=CurrentAggressiveParameters("0.85"),
        generation=0,
        parent_id="root",
    )
    StrategyMutationRegistry(
        durable_mutation_evidence.root,
        clock=_Clock(dt.datetime(2030, 1, 3, 16, 2, tzinfo=UTC)),
    ).register_baseline(
        duplicate_semantic_root,
        durable_mutation_evidence.policy,
        effective_at=dt.datetime(2029, 12, 31, 14, 0, tzinfo=UTC),
    )

    with pytest.raises(ValueError, match="semantic child"):
        _register_mutation(durable_mutation_evidence)


def test_baseline_cannot_reintroduce_an_admitted_semantic_child(
    durable_mutation_evidence: _DurableMutationEvidence,
):
    # Break caught: bypassing semantic deduplication by registering a child as a root.
    from tradingagents.strategy.mutation_registry import StrategyMutationRegistry

    child = _register_mutation(durable_mutation_evidence).child_genome
    same_semantic_root = StrategyGenome.create(
        family=child.family,
        parameters=child.parameters,
        generation=0,
        parent_id="root",
    )
    registry = StrategyMutationRegistry(
        durable_mutation_evidence.root,
        clock=_Clock(dt.datetime(2030, 1, 3, 16, 4, tzinfo=UTC)),
    )

    with pytest.raises(ValueError, match="semantic"):
        registry.register_baseline(
            same_semantic_root,
            durable_mutation_evidence.policy,
            effective_at=dt.datetime(2030, 1, 3, 16, 4, tzinfo=UTC),
        )


def test_changed_cycle_material_gets_a_distinct_cycle_and_fresh_ordinal_one(
    durable_mutation_evidence: _DurableMutationEvidence,
):
    # Break caught: consuming an old cycle's ordinal after identity material changes.
    from tradingagents.strategy.mutation_registry import build_mutated_genome

    first = _register_mutation(durable_mutation_evidence)
    second = _register_mutation(
        durable_mutation_evidence,
        effective_at=dt.datetime(2030, 1, 3, 16, 4, tzinfo=UTC),
        child=build_mutated_genome(
            durable_mutation_evidence.parent,
            "current-aggressive.min_score",
            "-0.1",
            durable_mutation_evidence.policy,
        ),
    )

    assert first.cycle_id != second.cycle_id
    assert first.ordinal == second.ordinal == 1


def test_arbitrary_or_stale_cycle_id_is_rejected(
    durable_mutation_evidence: _DurableMutationEvidence,
):
    # Break caught: accepting caller-selected cycle identities.
    with pytest.raises(ValueError, match="cycle_id"):
        _register_mutation(
            durable_mutation_evidence,
            cycle_id="cycle-" + ("f" * 64),
        )


def test_exact_mutation_retry_is_event_silent_and_keeps_first_seen_bytes(
    durable_mutation_evidence: _DurableMutationEvidence,
):
    # Break caught: treating a byte-identical retry as a duplicate cycle slot.
    first = _register_mutation(durable_mutation_evidence)
    retried = _register_mutation(durable_mutation_evidence)
    events = [
        json.loads(line)
        for line in (
            durable_mutation_evidence.root / "events.jsonl"
        ).read_text(encoding="utf-8").splitlines()
    ]

    assert retried.canonical_json_bytes() == first.canonical_json_bytes()
    assert sum(item["kind"] == "mutation-record" for item in events) == 1


def test_exact_retry_of_non_tail_ordinal_succeeds_after_later_ordinal(
    durable_mutation_evidence: _DurableMutationEvidence,
):
    # Break caught: applying new-admission ordinal ordering to an exact old retry.
    from tradingagents.strategy.mutation_registry import build_mutated_genome

    first = _register_mutation(durable_mutation_evidence)
    _register_mutation(
        durable_mutation_evidence,
        ordinal=2,
        child=build_mutated_genome(
            durable_mutation_evidence.parent,
            "current-aggressive.min_score",
            "-0.1",
            durable_mutation_evidence.policy,
        ),
    )

    retried = _register_mutation(durable_mutation_evidence)

    assert retried.canonical_json_bytes() == first.canonical_json_bytes()


@pytest.mark.parametrize("reuse_later_child", (False, True))
def test_conflicting_non_tail_cycle_slot_or_child_still_rejects(
    durable_mutation_evidence: _DurableMutationEvidence,
    reuse_later_child: bool,
):
    # Break caught: treating any old slot or child as an exact retry.
    from tradingagents.strategy.mutation_registry import build_mutated_genome

    _register_mutation(durable_mutation_evidence)
    later_child = build_mutated_genome(
        durable_mutation_evidence.parent,
        "current-aggressive.min_score",
        "-0.1",
        durable_mutation_evidence.policy,
    )
    _register_mutation(
        durable_mutation_evidence,
        ordinal=2,
        child=later_child,
    )
    conflicting_child = (
        later_child
        if reuse_later_child
        else build_mutated_genome(
            durable_mutation_evidence.parent,
            "current-aggressive.min_score",
            "0.05",
            durable_mutation_evidence.policy,
        )
    )

    with pytest.raises(ValueError, match="slot|child"):
        _register_mutation(
            durable_mutation_evidence,
            ordinal=1,
            child=conflicting_child,
        )


def test_exact_retry_still_revalidates_durable_source_bytes(
    durable_mutation_evidence: _DurableMutationEvidence,
):
    # Break caught: returning an existing mutation before dependency revalidation.
    _register_mutation(durable_mutation_evidence)
    changed_caller = dataclasses.replace(
        durable_mutation_evidence.source_evidence,
        recorded_at="2030-01-03T16:03:00+00:00",
    )

    with pytest.raises(ValueError, match="source"):
        _register_mutation(
            durable_mutation_evidence,
            source_evidence=changed_caller,
        )


def test_exact_baseline_retry_self_excludes_but_changed_bytes_conflict(
    durable_mutation_evidence: _DurableMutationEvidence,
):
    # Break caught: rejecting exact roots or accepting same-genome changed candidates.
    from tradingagents.strategy.mutation_registry import StrategyMutationRegistry

    registry = StrategyMutationRegistry(
        durable_mutation_evidence.root,
        clock=_Clock(dt.datetime(2030, 1, 3, 16, 2, tzinfo=UTC)),
    )
    exact = registry.register_baseline(
        durable_mutation_evidence.parent,
        durable_mutation_evidence.policy,
        effective_at=dt.datetime(2029, 12, 31, 14, 0, tzinfo=UTC),
    )
    assert exact.genome == durable_mutation_evidence.parent

    with pytest.raises(ValueError, match="duplicate baseline"):
        registry.register_baseline(
            durable_mutation_evidence.parent,
            durable_mutation_evidence.policy,
            effective_at=dt.datetime(2029, 12, 31, 14, 1, tzinfo=UTC),
        )


def test_backdated_retry_is_rejected_before_candidate_self_exclusion(
    durable_mutation_evidence: _DurableMutationEvidence,
):
    # Break caught: letting retry identity bypass the store chronology watermark.
    from tradingagents.strategy._immutable_evidence_store import (
        EvidenceBackdatingError,
    )
    from tradingagents.strategy.mutation_registry import StrategyMutationRegistry

    _register_mutation(durable_mutation_evidence)
    backdated = StrategyMutationRegistry(
        durable_mutation_evidence.root,
        clock=_Clock(dt.datetime(2030, 1, 3, 16, 3, 59, tzinfo=UTC)),
    )
    with pytest.raises(EvidenceBackdatingError):
        _register_mutation(
            durable_mutation_evidence,
            registry=backdated,
        )


def test_concurrent_identical_mutation_retries_create_one_commit(
    durable_mutation_evidence: _DurableMutationEvidence,
):
    # Break caught: racing identical retries into duplicate events or one rejection.
    from tradingagents.strategy.mutation_registry import StrategyMutationRegistry

    def worker(_index: int):
        registry = StrategyMutationRegistry(
            durable_mutation_evidence.root,
            clock=_Clock(dt.datetime(2030, 1, 3, 16, 4, tzinfo=UTC)),
        )
        return _register_mutation(
            durable_mutation_evidence,
            registry=registry,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        records = tuple(pool.map(worker, range(2)))
    events = [
        json.loads(line)
        for line in (
            durable_mutation_evidence.root / "events.jsonl"
        ).read_text(encoding="utf-8").splitlines()
    ]

    assert records[0].canonical_json_bytes() == records[1].canonical_json_bytes()
    assert sum(item["kind"] == "mutation-record" for item in events) == 1


def test_concurrent_conflicting_cycle_slots_allow_exactly_one_commit(
    durable_mutation_evidence: _DurableMutationEvidence,
):
    # Break caught: validating two conflicting slots outside the shared store lock.
    from tradingagents.strategy.mutation_registry import (
        StrategyMutationRegistry,
        build_mutated_genome,
    )

    children = (
        build_mutated_genome(
            durable_mutation_evidence.parent,
            "current-aggressive.min_score",
            "0.1",
            durable_mutation_evidence.policy,
        ),
        build_mutated_genome(
            durable_mutation_evidence.parent,
            "current-aggressive.min_score",
            "-0.1",
            durable_mutation_evidence.policy,
        ),
    )

    def worker(child: StrategyGenome):
        registry = StrategyMutationRegistry(
            durable_mutation_evidence.root,
            clock=_Clock(dt.datetime(2030, 1, 3, 16, 4, tzinfo=UTC)),
        )
        try:
            return _register_mutation(
                durable_mutation_evidence,
                registry=registry,
                child=child,
            )
        except ValueError as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = tuple(pool.map(worker, children))

    assert sum(not isinstance(item, Exception) for item in outcomes) == 1
    assert sum(isinstance(item, ValueError) for item in outcomes) == 1
    assert len(durable_mutation_evidence.registry.verify()) == 1


def test_concurrent_duplicate_child_across_cycles_allows_one_commit(
    durable_mutation_evidence: _DurableMutationEvidence,
):
    # Break caught: racing one full child digest into two distinct cycle identities.
    from tradingagents.strategy.mutation_registry import (
        StrategyMutationRegistry,
        build_mutated_genome,
    )

    child = build_mutated_genome(
        durable_mutation_evidence.parent,
        "current-aggressive.min_score",
        "0.1",
        durable_mutation_evidence.policy,
    )
    effective_times = (
        dt.datetime(2030, 1, 3, 16, 3, tzinfo=UTC),
        dt.datetime(2030, 1, 3, 16, 4, tzinfo=UTC),
    )

    def worker(effective_at: dt.datetime):
        registry = StrategyMutationRegistry(
            durable_mutation_evidence.root,
            clock=_Clock(dt.datetime(2030, 1, 3, 16, 4, tzinfo=UTC)),
        )
        try:
            return _register_mutation(
                durable_mutation_evidence,
                registry=registry,
                child=child,
                effective_at=effective_at,
            )
        except ValueError as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = tuple(pool.map(worker, effective_times))

    assert sum(not isinstance(item, Exception) for item in outcomes) == 1
    assert sum(isinstance(item, ValueError) for item in outcomes) == 1
    assert len(durable_mutation_evidence.registry.verify()) == 1


class _CrashAfterMutationObject:
    @staticmethod
    def build(root: Path, clock: _Clock):
        from tradingagents.strategy._immutable_evidence_store import (
            ImmutableStrategyEvidenceStore,
        )

        class CrashingStore(ImmutableStrategyEvidenceStore):
            def _after_object_fsync(self, _path: Path) -> None:
                raise RuntimeError("crash after mutation object fsync")

        return CrashingStore(root, clock=clock)


class _CrashAfterMutationEvent:
    @staticmethod
    def build(root: Path, clock: _Clock):
        from tradingagents.strategy._immutable_evidence_store import (
            EvidenceEvent,
            ImmutableStrategyEvidenceStore,
        )

        class CrashingStore(ImmutableStrategyEvidenceStore):
            def _after_event_fsync(self, _event: EvidenceEvent) -> None:
                raise RuntimeError("crash after mutation event fsync")

        return CrashingStore(root, clock=clock)


@pytest.mark.parametrize(
    "crash_factory",
    (_CrashAfterMutationObject, _CrashAfterMutationEvent),
)
def test_crashed_mutation_admission_recovers_as_one_durable_record(
    durable_mutation_evidence: _DurableMutationEvidence,
    crash_factory,
):
    # Break caught: losing or duplicating a validated mutation across fsync crashes.
    from tradingagents.strategy.mutation_registry import StrategyMutationRegistry

    crashing = StrategyMutationRegistry(
        durable_mutation_evidence.root,
        clock=_Clock(dt.datetime(2030, 1, 3, 16, 4, tzinfo=UTC)),
    )
    crashing._store = crash_factory.build(  # type: ignore[attr-defined]
        durable_mutation_evidence.root,
        _Clock(dt.datetime(2030, 1, 3, 16, 4, tzinfo=UTC)),
    )
    with pytest.raises(RuntimeError, match="crash after mutation"):
        _register_mutation(
            durable_mutation_evidence,
            registry=crashing,
        )

    repaired = StrategyMutationRegistry(
        durable_mutation_evidence.root,
        clock=_Clock(dt.datetime(2030, 1, 3, 16, 5, tzinfo=UTC)),
    )
    record = _register_mutation(
        durable_mutation_evidence,
        registry=repaired,
    )
    assert repaired.verify() == (record,)


def test_concurrent_conflicting_baseline_semantic_ids_allow_one_commit(
    tmp_path: Path,
):
    # Break caught: racing duplicate semantic baseline roots past locked validation.
    from tradingagents.strategy.mutation_registry import StrategyMutationRegistry

    root = tmp_path / "baseline-race"
    genomes = (
        StrategyGenome.create(
            family=StrategyFamily.CURRENT_AGGRESSIVE,
            parameters=CurrentAggressiveParameters("0.75"),
            generation=0,
            parent_id="root-a",
        ),
        StrategyGenome.create(
            family=StrategyFamily.CURRENT_AGGRESSIVE,
            parameters=CurrentAggressiveParameters("0.75"),
            generation=0,
            parent_id="root-b",
        ),
    )

    def worker(genome: StrategyGenome):
        registry = StrategyMutationRegistry(
            root,
            clock=_Clock(dt.datetime(2030, 1, 1, 12, 0, tzinfo=UTC)),
        )
        try:
            return registry.register_baseline(
                genome,
                _policy(),
                effective_at=dt.datetime(2030, 1, 1, 11, 0, tzinfo=UTC),
            )
        except ValueError as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = tuple(pool.map(worker, genomes))

    assert sum(not isinstance(item, Exception) for item in outcomes) == 1
    assert sum(isinstance(item, ValueError) for item in outcomes) == 1


@pytest.mark.parametrize(
    ("family", "parameters", "path", "delta", "expected"),
    (
        (
            StrategyFamily.CURRENT_AGGRESSIVE,
            CurrentAggressiveParameters("0.75"),
            "current-aggressive.min_score",
            "0.1",
            "0.85",
        ),
        (
            StrategyFamily.CURRENT_AGGRESSIVE,
            CurrentAggressiveParameters("0.75"),
            "current-aggressive.min_score",
            "-0.1",
            "0.65",
        ),
        (
            StrategyFamily.PULLBACK_SUPPORT,
            PullbackSupportParameters("-0.1", "0", "1"),
            "pullback-support.min_daily_change_fraction",
            "0.05",
            "-0.05",
        ),
        (
            StrategyFamily.PULLBACK_SUPPORT,
            PullbackSupportParameters("-0.1", "0", "1"),
            "pullback-support.min_daily_change_fraction",
            "-0.05",
            "-0.15",
        ),
        (
            StrategyFamily.PULLBACK_SUPPORT,
            PullbackSupportParameters("-0.1", "0", "1"),
            "pullback-support.max_daily_change_fraction",
            "0.05",
            "0.05",
        ),
        (
            StrategyFamily.PULLBACK_SUPPORT,
            PullbackSupportParameters("-0.1", "0", "1"),
            "pullback-support.max_daily_change_fraction",
            "-0.05",
            "-0.05",
        ),
        (
            StrategyFamily.PULLBACK_SUPPORT,
            PullbackSupportParameters("-0.1", "0", "1"),
            "pullback-support.max_volume_ratio",
            "0.1",
            "1.1",
        ),
        (
            StrategyFamily.PULLBACK_SUPPORT,
            PullbackSupportParameters("-0.1", "0", "1"),
            "pullback-support.max_volume_ratio",
            "-0.1",
            "0.9",
        ),
        (
            StrategyFamily.CATALYST_RELATIVE_STRENGTH,
            CatalystRelativeStrengthParameters("0.75"),
            "catalyst-relative-strength.min_score",
            "0.1",
            "0.85",
        ),
        (
            StrategyFamily.CATALYST_RELATIVE_STRENGTH,
            CatalystRelativeStrengthParameters("0.75"),
            "catalyst-relative-strength.min_score",
            "-0.1",
            "0.65",
        ),
    ),
)
def test_positive_and_negative_mutation_for_every_mutable_field(
    family,
    parameters,
    path: str,
    delta: str,
    expected: str,
):
    # Break caught: wiring one frozen parameter path to the wrong family field.
    from tradingagents.strategy.mutation_registry import build_mutated_genome

    parent = StrategyGenome.create(
        family=family,
        parameters=parameters,
        generation=4,
        parent_id="prior",
    )
    before = parent.to_dict()
    policy_before = _policy().to_dict()
    child = build_mutated_genome(parent, path, delta, _policy())

    assert child.parameters.to_dict()[path.split(".", 1)[1]] == expected
    assert child.generation == 5
    assert child.parent_id == parent.genome_id
    assert parent.to_dict() == before
    assert _policy().to_dict() == policy_before


@pytest.mark.parametrize(
    "delta",
    (
        "0",
        "-0",
        "+0.1",
        "1e-1",
        "00.1",
        "0.10",
        ".1",
        "0.",
    ),
)
def test_delta_grammar_rejects_noncanonical_or_noop_values(delta: str):
    # Break caught: accepting a delta spelling that has multiple byte forms.
    from tradingagents.strategy.mutation_registry import build_mutated_genome

    parent = StrategyGenome.create(
        family=StrategyFamily.CURRENT_AGGRESSIVE,
        parameters=CurrentAggressiveParameters("0.75"),
        generation=0,
        parent_id="root",
    )
    with pytest.raises(ValueError):
        build_mutated_genome(
            parent,
            "current-aggressive.min_score",
            delta,
            _policy(),
        )
    with pytest.raises(TypeError):
        build_mutated_genome(
            parent,
            "current-aggressive.min_score",
            Decimal("0.1"),  # type: ignore[arg-type]
            _policy(),
        )


def test_exact_bound_and_32_place_decimal_envelope():
    # Break caught: rounding or rejecting the smallest permitted fixed-point scale.
    from tradingagents.strategy.mutation_registry import build_mutated_genome

    quantum = "0." + ("0" * 31) + "1"
    policy = _policy(current_aggressive_bound=quantum)
    parent = StrategyGenome.create(
        family=StrategyFamily.CURRENT_AGGRESSIVE,
        parameters=CurrentAggressiveParameters("0.75"),
        generation=0,
        parent_id="root",
    )
    child = build_mutated_genome(
        parent,
        "current-aggressive.min_score",
        quantum,
        policy,
    )

    assert child.parameters.min_score == "0.75000000000000000000000000000001"
    one_above_tenth = "0.10000000000000000000000000000001"
    assert len(one_above_tenth.split(".", 1)[1]) == 32
    with pytest.raises(ValueError, match="bound"):
        build_mutated_genome(
            parent,
            "current-aggressive.min_score",
            one_above_tenth,
            _policy(),
        )
    too_fine_bound = "0." + ("0" * 32) + "1"
    with pytest.raises(ValueError, match="bound"):
        build_mutated_genome(
            parent,
            "current-aggressive.min_score",
            quantum,
            _policy(current_aggressive_bound=too_fine_bound),
        )


def test_mutation_decimal_context_and_flags_are_caller_independent():
    # Break caught: mutating the process Decimal precision, traps, or sticky flags.
    from tradingagents.strategy.mutation_registry import build_mutated_genome

    parent = StrategyGenome.create(
        family=StrategyFamily.CURRENT_AGGRESSIVE,
        parameters=CurrentAggressiveParameters("0.75"),
        generation=0,
        parent_id="root",
    )
    context = getcontext()
    original_precision = context.prec
    original_rounding = context.rounding
    original_traps = context.traps.copy()
    original_flags = context.flags.copy()
    context.prec = 7
    context.flags[Inexact] = True
    try:
        child = build_mutated_genome(
            parent,
            "current-aggressive.min_score",
            "0.1",
            _policy(),
        )
        assert child.parameters.min_score == "0.85"
        assert context.prec == 7
        assert context.rounding == original_rounding
        assert context.traps == original_traps
        assert context.flags[Inexact] is True
    finally:
        context.prec = original_precision
        context.rounding = original_rounding
        for signal, enabled in original_traps.items():
            context.traps[signal] = enabled
        for signal, raised in original_flags.items():
            context.flags[signal] = raised


def test_cycle_id_normalizes_aware_time_and_rejects_ambiguous_time():
    # Break caught: accepting naive/subsecond cycle time or emitting a non-UTC hash.
    from tradingagents.strategy.mutation_registry import build_mutation_cycle_id

    inputs = {
        "source_evidence_id": "promotion-evidence-" + ("1" * 64),
        "parent_genome_canonical_sha256": "2" * 64,
        "evolution_policy_sha256": "3" * 64,
    }
    utc_id = build_mutation_cycle_id(
        **inputs,
        cycle_effective_at=dt.datetime(
            2026,
            1,
            2,
            15,
            4,
            5,
            tzinfo=UTC,
        ),
    )
    offset_id = build_mutation_cycle_id(
        **inputs,
        cycle_effective_at=dt.datetime(
            2026,
            1,
            2,
            10,
            4,
            5,
            tzinfo=dt.timezone(dt.timedelta(hours=-5)),
        ),
    )
    assert offset_id == utc_id
    with pytest.raises(ValueError):
        build_mutation_cycle_id(
            **inputs,
            cycle_effective_at=dt.datetime(2026, 1, 2, 15, 4, 5),
        )
    with pytest.raises(ValueError):
        build_mutation_cycle_id(
            **inputs,
            cycle_effective_at=dt.datetime(
                2026,
                1,
                2,
                15,
                4,
                5,
                1,
                tzinfo=UTC,
            ),
        )


def test_mutation_record_schema_bytes_parser_identity_and_authority(
    durable_mutation_evidence: _DurableMutationEvidence,
):
    # Break caught: dropping identity-bearing record fields or weakening authority.
    from tradingagents.strategy._immutable_evidence_store import (
        ImmutableStrategyEvidenceStore,
    )
    from tradingagents.strategy.mutation_registry import StrategyMutationRecord

    record = _register_mutation(durable_mutation_evidence)
    expected_fields = {
        "schema_version",
        "mutation_id",
        "cycle_id",
        "ordinal",
        "source_evidence_id",
        "parent_genome",
        "parent_genome_canonical_sha256",
        "child_genome",
        "child_genome_canonical_sha256",
        "family",
        "parameter_path",
        "before_value",
        "after_value",
        "signed_delta",
        "evolution_policy_sha256",
        "effective_at",
        "recorded_at",
        "analysis_only",
        "execution_authority",
        "can_submit_orders",
    }
    assert set(record.to_dict()) == expected_fields
    assert StrategyMutationRecord.from_dict(
        record.to_dict()
    ).canonical_json_bytes() == record.canonical_json_bytes()
    envelope = next(
        item
        for item in ImmutableStrategyEvidenceStore(
            durable_mutation_evidence.root
        ).rebuild()
        if item.object_id == record.mutation_id
    )
    assert StrategyMutationRecord.from_envelope(envelope) == record
    assert record.mutation_id.startswith("mutation-record-")
    assert record.analysis_only is True
    assert record.execution_authority == "none"
    assert record.can_submit_orders is False

    z_timestamp = record.to_dict()
    z_timestamp["effective_at"] = "2030-01-03T16:03:00Z"
    with pytest.raises(ValueError, match=r"\+00:00"):
        StrategyMutationRecord.from_dict(z_timestamp)
    wrong_authority = record.to_dict()
    wrong_authority["can_submit_orders"] = True
    with pytest.raises(ValueError, match="authority"):
        StrategyMutationRecord.from_dict(wrong_authority)


def test_baseline_schema_bytes_parser_identity_and_authority(
    durable_mutation_evidence: _DurableMutationEvidence,
):
    # Break caught: weakening the root registration's exact persisted contract.
    from tradingagents.strategy._immutable_evidence_store import (
        ImmutableStrategyEvidenceStore,
    )
    from tradingagents.strategy.mutation_registry import (
        BaselineGenomeRegistration,
    )

    envelope = next(
        item
        for item in ImmutableStrategyEvidenceStore(
            durable_mutation_evidence.root
        ).rebuild()
        if item.kind == "baseline-genome"
    )
    baseline = BaselineGenomeRegistration.from_envelope(envelope)
    assert set(baseline.to_dict()) == {
        "schema_version",
        "baseline_id",
        "genome",
        "genome_canonical_sha256",
        "evolution_policy_sha256",
        "effective_at",
        "recorded_at",
        "analysis_only",
        "execution_authority",
        "can_submit_orders",
    }
    assert baseline.baseline_id == envelope.object_id
    assert baseline.canonical_json_bytes() == json.dumps(
        baseline.to_dict(),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    assert baseline.analysis_only is True
    assert baseline.execution_authority == "none"
    assert baseline.can_submit_orders is False


def test_baseline_direct_model_recomputes_content_identity(
    durable_mutation_evidence: _DurableMutationEvidence,
):
    # Break caught: accepting an arbitrary regex-valid ID on the public model.
    from tradingagents.strategy._immutable_evidence_store import (
        ImmutableStrategyEvidenceStore,
    )
    from tradingagents.strategy.mutation_registry import (
        BaselineGenomeRegistration,
    )

    envelope = next(
        item
        for item in ImmutableStrategyEvidenceStore(
            durable_mutation_evidence.root
        ).rebuild()
        if item.kind == "baseline-genome"
    )
    baseline = BaselineGenomeRegistration.from_envelope(envelope)

    assert dataclasses.replace(baseline) == baseline
    assert (
        BaselineGenomeRegistration.from_envelope(envelope).canonical_json_bytes()
        == baseline.canonical_json_bytes()
    )
    forged_id = "baseline-genome-" + (
        "0" * 64
        if not baseline.baseline_id.endswith("0" * 64)
        else "1" * 64
    )
    with pytest.raises(ValueError, match="identity"):
        dataclasses.replace(baseline, baseline_id=forged_id)


def test_verify_and_rebuild_reject_forged_standalone_baseline_authority(
    tmp_path: Path,
):
    # Break caught: skipping baseline parsing when no mutation references it.
    from tradingagents.strategy.mutation_registry import StrategyMutationRegistry

    genome = StrategyGenome.create(
        family=StrategyFamily.CURRENT_AGGRESSIVE,
        parameters=CurrentAggressiveParameters("0.75"),
        generation=0,
        parent_id="root",
    )
    policy = _policy()
    payload = {
        "schema_version": 1,
        "genome": genome.to_dict(),
        "genome_canonical_sha256": hashlib.sha256(
            genome.canonical_json_bytes()
        ).hexdigest(),
        "evolution_policy_sha256": hashlib.sha256(
            policy.canonical_json_bytes()
        ).hexdigest(),
        "analysis_only": False,
        "execution_authority": "orders",
        "can_submit_orders": True,
    }
    root = tmp_path / "forged-standalone-baseline"
    _admit_material(
        root,
        clock=dt.datetime(2030, 1, 1, 15, 1, tzinfo=UTC),
        kind="baseline-genome",
        effective_at="2030-01-01T15:00:00+00:00",
        payload=payload,
    )
    registry = StrategyMutationRegistry(root)

    with pytest.raises(ValueError, match="authority"):
        registry.verify()
    with pytest.raises(ValueError, match="authority"):
        registry.rebuild()


def test_verify_and_rebuild_reject_duplicate_baseline_replay(
    durable_mutation_evidence: _DurableMutationEvidence,
):
    # Break caught: replaying duplicate semantic/full baseline identities.
    from tradingagents.strategy._immutable_evidence_store import (
        ImmutableStrategyEvidenceStore,
    )
    from tradingagents.strategy.mutation_registry import StrategyMutationRegistry

    baseline = next(
        item
        for item in ImmutableStrategyEvidenceStore(
            durable_mutation_evidence.root
        ).rebuild()
        if item.kind == "baseline-genome"
    )
    _admit_material(
        durable_mutation_evidence.root,
        clock=dt.datetime(2030, 1, 3, 16, 5, tzinfo=UTC),
        kind="baseline-genome",
        effective_at="2029-12-31T14:01:00+00:00",
        payload=dict(baseline.payload),
    )
    registry = StrategyMutationRegistry(durable_mutation_evidence.root)

    with pytest.raises(ValueError, match="duplicate baseline"):
        registry.verify()
    with pytest.raises(ValueError, match="duplicate baseline"):
        registry.rebuild()


def test_verify_and_rebuild_reject_baseline_semantic_collision_with_child(
    durable_mutation_evidence: _DurableMutationEvidence,
):
    # Break caught: replay accepting a root that reintroduces a mutation child.
    from tradingagents.strategy.mutation_registry import StrategyMutationRegistry

    child = _register_mutation(durable_mutation_evidence).child_genome
    colliding_root = StrategyGenome.create(
        family=child.family,
        parameters=child.parameters,
        generation=0,
        parent_id="root",
    )
    _admit_material(
        durable_mutation_evidence.root,
        clock=dt.datetime(2030, 1, 3, 16, 5, tzinfo=UTC),
        kind="baseline-genome",
        effective_at="2030-01-03T16:04:00+00:00",
        payload={
            "schema_version": 1,
            "genome": colliding_root.to_dict(),
            "genome_canonical_sha256": hashlib.sha256(
                colliding_root.canonical_json_bytes()
            ).hexdigest(),
            "evolution_policy_sha256": hashlib.sha256(
                durable_mutation_evidence.policy.canonical_json_bytes()
            ).hexdigest(),
            "analysis_only": True,
            "execution_authority": "none",
            "can_submit_orders": False,
        },
    )
    registry = StrategyMutationRegistry(durable_mutation_evidence.root)

    with pytest.raises(ValueError, match="semantic"):
        registry.verify()
    with pytest.raises(ValueError, match="semantic"):
        registry.rebuild()


@pytest.mark.parametrize("defect", ("noop", "family", "generation", "parent_id"))
def test_registry_rejects_invalid_child_shape(
    durable_mutation_evidence: _DurableMutationEvidence,
    defect: str,
):
    # Break caught: accepting a child outside exact one-edge lineage shape.
    if defect == "family":
        child = StrategyGenome.create(
            family=StrategyFamily.CATALYST_RELATIVE_STRENGTH,
            parameters=CatalystRelativeStrengthParameters("0.85"),
            generation=1,
            parent_id=durable_mutation_evidence.parent.genome_id,
        )
    else:
        child = StrategyGenome.create(
            family=StrategyFamily.CURRENT_AGGRESSIVE,
            parameters=CurrentAggressiveParameters(
                "0.75" if defect == "noop" else "0.85"
            ),
            generation=2 if defect == "generation" else 1,
            parent_id=(
                "wrong-parent"
                if defect == "parent_id"
                else durable_mutation_evidence.parent.genome_id
            ),
        )

    with pytest.raises(ValueError):
        _register_mutation(
            durable_mutation_evidence,
            child=child,
        )


def test_failed_promotion_gates_remain_a_valid_learning_source(
    tmp_path: Path,
    durable_mutation_evidence: _DurableMutationEvidence,
):
    # Break caught: requiring promotion gates to pass before analysis-only mutation.
    gates = [
        [name, False if index == 0 else passed]
        for index, (name, passed) in enumerate(
            durable_mutation_evidence.source_evidence.gates
        )
    ]
    registry, failed_source, _registration = _variant_durable_source(
        tmp_path,
        durable_mutation_evidence,
        source_changes={
            "gates": gates,
            "issues": [gates[0][0]],
            "complete_internal_evidence": False,
        },
    )
    record = _register_mutation(
        durable_mutation_evidence,
        registry=registry,
        source_evidence=failed_source,
    )

    assert failed_source.complete_internal_evidence is False
    assert record.source_evidence_id == failed_source.evidence_id


def test_provenance_only_change_changes_source_cycle_and_mutation_identity(
    tmp_path: Path,
    durable_mutation_evidence: _DurableMutationEvidence,
):
    # Break caught: omitting calculation provenance from transitive mutation identity.
    original_record = _register_mutation(durable_mutation_evidence)
    registry, changed_source, _registration = _variant_durable_source(
        tmp_path,
        durable_mutation_evidence,
        source_changes={"evaluation_code_commit": "f" * 40},
    )
    with pytest.raises(ValueError, match="provenance"):
        _register_mutation(
            durable_mutation_evidence,
            registry=registry,
            source_evidence=changed_source,
        )

    registration_payload = _evidence_payload(
        durable_mutation_evidence.registration,
        "registration_id",
        "effective_at",
        "recorded_at",
    )
    registration_payload["evaluation_code_commit"] = "f" * 40
    (tmp_path / "bound-change").mkdir()
    registry, changed_source, _registration = _variant_durable_source(
        tmp_path / "bound-change",
        durable_mutation_evidence,
        registration_payload=registration_payload,
        source_changes={"evaluation_code_commit": "f" * 40},
    )
    changed_record = _register_mutation(
        durable_mutation_evidence,
        registry=registry,
        source_evidence=changed_source,
    )

    assert changed_source.evidence_id != (
        durable_mutation_evidence.source_evidence.evidence_id
    )
    assert changed_record.cycle_id != original_record.cycle_id
    assert changed_record.mutation_id != original_record.mutation_id

    forged = object.__new__(type(changed_source))
    for model_field in dataclasses.fields(changed_source):
        object.__setattr__(
            forged,
            model_field.name,
            getattr(changed_source, model_field.name),
        )
    object.__setattr__(
        forged,
        "evidence_id",
        durable_mutation_evidence.source_evidence.evidence_id,
    )
    with pytest.raises(ValueError, match="source"):
        _register_mutation(
            durable_mutation_evidence,
            source_evidence=forged,
            effective_at=dt.datetime(2030, 1, 3, 16, 4, tzinfo=UTC),
        )


def test_wrong_source_parent_and_own_recorded_time_are_rejected(
    tmp_path: Path,
    durable_mutation_evidence: _DurableMutationEvidence,
):
    # Break caught: admitting caller lineage absent from source or after first-seen time.
    registry, wrong_source, _registration = _variant_durable_source(
        tmp_path,
        durable_mutation_evidence,
        source_changes={
            "genome_id": "genome-current-aggressive-" + ("f" * 64),
            "genome_canonical_sha256": "f" * 64,
        },
    )
    with pytest.raises(ValueError, match="parent"):
        _register_mutation(
            durable_mutation_evidence,
            registry=registry,
            source_evidence=wrong_source,
        )

    from tradingagents.strategy.mutation_registry import StrategyMutationRegistry

    early_clock = StrategyMutationRegistry(
        durable_mutation_evidence.root,
        clock=_Clock(dt.datetime(2030, 1, 3, 16, 2, tzinfo=UTC)),
    )
    with pytest.raises(ValueError, match="effective_at"):
        _register_mutation(
            durable_mutation_evidence,
            registry=early_clock,
        )


def test_cross_family_multifield_and_hold_cash_reject():
    # Break caught: allowing non-numeric, multi-field, or cross-family mutations.
    from tradingagents.strategy.mutation_registry import (
        StrategyMutationRecord,
        build_mutated_genome,
    )

    hold = StrategyGenome.create(
        family=StrategyFamily.HOLD_CASH,
        parameters=HoldCashParameters(),
        generation=0,
        parent_id="root",
    )
    with pytest.raises(ValueError):
        build_mutated_genome(
            hold,
            "current-aggressive.min_score",
            "0.1",
            _policy(),
        )
    aggressive = StrategyGenome.create(
        family=StrategyFamily.CURRENT_AGGRESSIVE,
        parameters=CurrentAggressiveParameters("0.75"),
        generation=0,
        parent_id="root",
    )
    with pytest.raises(ValueError, match="family"):
        build_mutated_genome(
            aggressive,
            "catalyst-relative-strength.min_score",
            "0.1",
            _policy(),
        )
    pullback = StrategyGenome.create(
        family=StrategyFamily.PULLBACK_SUPPORT,
        parameters=PullbackSupportParameters("-0.1", "0", "1"),
        generation=0,
        parent_id="root",
    )
    multifield = StrategyGenome.create(
        family=StrategyFamily.PULLBACK_SUPPORT,
        parameters=PullbackSupportParameters("-0.15", "0.05", "1"),
        generation=1,
        parent_id=pullback.genome_id,
    )
    with pytest.raises(ValueError, match="one numeric"):
        StrategyMutationRecord(
            mutation_id="mutation-record-" + ("1" * 64),
            cycle_id="cycle-" + ("2" * 64),
            ordinal=1,
            source_evidence_id="promotion-evidence-" + ("3" * 64),
            parent_genome=pullback,
            parent_genome_canonical_sha256=hashlib.sha256(
                pullback.canonical_json_bytes()
            ).hexdigest(),
            child_genome=multifield,
            child_genome_canonical_sha256=hashlib.sha256(
                multifield.canonical_json_bytes()
            ).hexdigest(),
            family=StrategyFamily.PULLBACK_SUPPORT,
            parameter_path="pullback-support.min_daily_change_fraction",
            before_value="-0.1",
            after_value="-0.15",
            signed_delta="-0.05",
            evolution_policy_sha256="4" * 64,
            effective_at="2030-01-03T16:03:00+00:00",
            recorded_at="2030-01-03T16:04:00+00:00",
        )
def test_attempted_lineage_cycle_rejects_through_registry(
    durable_mutation_evidence: _DurableMutationEvidence,
):
    # Break caught: accepting a child whose parent edge points to itself.
    from tradingagents.strategy.mutation_registry import build_mutated_genome

    normal_child = build_mutated_genome(
        durable_mutation_evidence.parent,
        "current-aggressive.min_score",
        "0.1",
        durable_mutation_evidence.policy,
    )
    cyclic_child = StrategyGenome.create(
        family=normal_child.family,
        parameters=normal_child.parameters,
        generation=normal_child.generation,
        parent_id=normal_child.genome_id,
    )
    assert cyclic_child.genome_id == normal_child.genome_id

    with pytest.raises(ValueError, match="parent_id"):
        _register_mutation(
            durable_mutation_evidence,
            child=cyclic_child,
        )


def test_lineage_changes_full_digest_even_when_semantic_identity_is_stable():
    # Break caught: deduplicating full lineage objects by semantic identity alone.
    first = StrategyGenome.create(
        family=StrategyFamily.CURRENT_AGGRESSIVE,
        parameters=CurrentAggressiveParameters("0.75"),
        generation=1,
        parent_id="parent-a",
    )
    second = StrategyGenome.create(
        family=StrategyFamily.CURRENT_AGGRESSIVE,
        parameters=CurrentAggressiveParameters("0.75"),
        generation=2,
        parent_id="parent-b",
    )

    assert first.genome_id == second.genome_id
    assert hashlib.sha256(first.canonical_json_bytes()).hexdigest() != (
        hashlib.sha256(second.canonical_json_bytes()).hexdigest()
    )


def test_import_and_authority_isolation_from_execution_surfaces():
    # Break caught: granting mutation code execution, runtime, or external authority.
    import tradingagents.strategy.mutation_registry as module

    source_path = Path(module.__file__).resolve()
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    imported = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    } | {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    allowed_roots = {
        "__future__",
        "collections.abc",
        "dataclasses",
        "datetime",
        "decimal",
        "hashlib",
        "json",
        "pathlib",
        "re",
        "tradingagents.strategy._immutable_evidence_store",
        "tradingagents.strategy.genome",
        "tradingagents.strategy.promotion_evidence",
    }
    assert imported <= allowed_roots
    forbidden = {
        "broker",
        "live_control",
        "promotion_sync",
        "random",
        "requests",
        "socket",
        "subprocess",
    }
    assert not any(
        fragment in source_path.read_text(encoding="utf-8").lower()
        for fragment in forbidden
    )


def test_mutation_registry_module_is_publicly_importable():
    # Break caught: removing the dedicated bounded-mutation registry module.
    from tradingagents.strategy.mutation_registry import StrategyMutationRegistry

    assert StrategyMutationRegistry is not None


def _policy(
    *,
    enabled: bool = True,
    current_aggressive_bound: str = "0.1",
    mutations_per_cycle: int = 2,
) -> StrategyEvolutionPolicy:
    return StrategyEvolutionPolicy(
        enabled=enabled,
        experiment_starting_cash_usd="100",
        candidate_min_order_usd="1",
        max_active_candidates=2,
        mutations_per_cycle=mutations_per_cycle,
        minimum_tracked_days=1,
        minimum_closed_trades=1,
        minimum_walk_forward_windows=1,
        maximum_paper_drawdown_pct="-1",
        mutation_bounds=StrategyMutationBounds(
            current_aggressive=CurrentAggressiveMutationBounds(
                current_aggressive_bound
            ),
            pullback_support=PullbackSupportMutationBounds("0.1", "0.1", "0.1"),
            catalyst_relative_strength=CatalystRelativeStrengthMutationBounds("0.1"),
        ),
    )


def test_cycle_id_uses_the_frozen_hash_fixture():
    # Break caught: changing an identity-bearing cycle-material field or JSON form.
    from tradingagents.strategy.mutation_registry import build_mutation_cycle_id

    actual = build_mutation_cycle_id(
        source_evidence_id="promotion-evidence-" + "1" * 64,
        parent_genome_canonical_sha256="2" * 64,
        evolution_policy_sha256="3" * 64,
        cycle_effective_at=dt.datetime(2026, 1, 2, 15, 4, 5, tzinfo=dt.timezone.utc),
    )
    assert actual == "cycle-5c1e22f7bfead4b6b94915a51d52859e66a1a76f40abc6f9133ecc08715ebda3"


def test_mutated_genome_accepts_one_canonical_bounded_field_delta():
    # Break caught: allowing an unbounded or multi-field mutation primitive.
    from tradingagents.strategy.mutation_registry import build_mutated_genome

    parent = StrategyGenome.create(
        family=StrategyFamily.CURRENT_AGGRESSIVE,
        parameters=CurrentAggressiveParameters("0.75"),
        generation=0,
        parent_id="root",
    )
    child = build_mutated_genome(parent, "current-aggressive.min_score", "-0.1", _policy())
    assert child.parameters.min_score == "0.65"
    assert child.generation == 1
    assert child.parent_id == parent.genome_id
    with pytest.raises(ValueError):
        build_mutated_genome(parent, "current-aggressive.min_score", "0.10", _policy())
    with pytest.raises(ValueError):
        build_mutated_genome(parent, "hold-cash.anything", "0.1", _policy())


@pytest.mark.parametrize(
    ("parameter_path", "signed_delta"),
    (
        ("pullback-support.min_daily_change_fraction", "0.03"),
        ("pullback-support.max_daily_change_fraction", "-0.03"),
    ),
)
def test_pullback_mutation_rejects_crossed_min_max_invariants(
    parameter_path: str,
    signed_delta: str,
):
    # Break caught: bypassing the existing pullback cross-field domain invariant.
    from tradingagents.strategy.mutation_registry import build_mutated_genome

    parent = StrategyGenome.create(
        family=StrategyFamily.PULLBACK_SUPPORT,
        parameters=PullbackSupportParameters("-0.01", "0.01", "1.5"),
        generation=0,
        parent_id="root",
    )

    with pytest.raises(ValueError):
        build_mutated_genome(
            parent,
            parameter_path,
            signed_delta,
            _policy(),
        )


def test_mutated_genome_rejects_thirty_three_fractional_digit_delta():
    # Break caught: accepting a delta beyond the frozen 32-place envelope.
    from tradingagents.strategy.mutation_registry import build_mutated_genome

    parent = StrategyGenome.create(
        family=StrategyFamily.CURRENT_AGGRESSIVE,
        parameters=CurrentAggressiveParameters("0.75"),
        generation=0,
        parent_id="root",
    )

    with pytest.raises(ValueError, match="fixed-point"):
        build_mutated_genome(
            parent,
            "current-aggressive.min_score",
            "0." + ("0" * 32) + "1",
            _policy(),
        )


def test_baseline_registration_is_root_only_canonical_and_analysis_only(tmp_path):
    # Break caught: admitting a non-root or mutable baseline outside the store.
    from tradingagents.strategy.mutation_registry import StrategyMutationRegistry

    root = StrategyGenome.create(
        family=StrategyFamily.CURRENT_AGGRESSIVE,
        parameters=CurrentAggressiveParameters("0.75"),
        generation=0,
        parent_id="root",
    )
    registry = StrategyMutationRegistry(
        tmp_path,
        clock=lambda: dt.datetime(2026, 1, 2, 15, 4, 6, tzinfo=dt.timezone.utc),
    )
    baseline = registry.register_baseline(
        root,
        _policy(),
        effective_at=dt.datetime(2026, 1, 2, 15, 4, 5, tzinfo=dt.timezone.utc),
    )

    assert baseline.baseline_id.startswith("baseline-genome-")
    assert baseline.effective_at == "2026-01-02T15:04:05+00:00"
    assert baseline.recorded_at == "2026-01-02T15:04:06+00:00"
    assert baseline.analysis_only is True
    assert baseline.execution_authority == "none"
    assert baseline.can_submit_orders is False
    with pytest.raises(FrozenInstanceError):
        baseline.recorded_at = "changed"  # type: ignore[misc]
    with pytest.raises(ValueError):
        registry.register_baseline(
            StrategyGenome.create(
                family=StrategyFamily.CURRENT_AGGRESSIVE,
                parameters=CurrentAggressiveParameters("0.75"),
                generation=1,
                parent_id=root.genome_id,
            ),
            _policy(),
            effective_at=dt.datetime(2026, 1, 2, 15, 4, 5, tzinfo=dt.timezone.utc),
        )


def test_mutation_primitives_and_baseline_are_public_exports():
    # Break caught: silently omitting the analysis-only mutation API from package users.
    from tradingagents.strategy import (
        BaselineGenomeRegistration,
        StrategyMutationRecord,
        StrategyMutationRegistry,
        StrategyMutationRegistryError,
        build_mutated_genome,
        build_mutation_cycle_id,
    )

    assert BaselineGenomeRegistration is not None
    assert StrategyMutationRecord is not None
    assert StrategyMutationRegistry is not None
    assert StrategyMutationRegistryError is not None
    assert build_mutated_genome is not None
    assert build_mutation_cycle_id is not None


def test_mutation_record_parser_rejects_an_incomplete_schema():
    # Break caught: accepting a persisted mutation record with missing identity material.
    from tradingagents.strategy.mutation_registry import StrategyMutationRecord

    with pytest.raises(ValueError, match="schema"):
        StrategyMutationRecord.from_dict({"schema_version": 1})
