from __future__ import annotations

import ast
import dataclasses
import datetime as dt
import hashlib
import importlib
import json
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal, localcontext
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parents[1]
UTC = dt.timezone.utc


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


@pytest.fixture(autouse=True)
def _treat_loaded_repo_as_clean_for_registration(monkeypatch):
    import tradingagents.strategy.promotion_evidence as module

    original = module._git_text

    def controlled_git_text(repo: Path, *args: str) -> str:
        if (
            repo.resolve() == REPO_ROOT.resolve()
            and args == ("status", "--porcelain")
        ):
            return ""
        return original(repo, *args)

    monkeypatch.setattr(module, "_git_text", controlled_git_text)


def test_staged_intent_module_exists():
    module = importlib.import_module("tradingagents.strategy.staged_intent")

    assert module.__name__ == "tradingagents.strategy.staged_intent"


def _observation_payload(**overrides):
    payload = {
        "schema_version": 1,
        "symbol": "NFLX",
        "score": "0.8",
        "current_price": "100",
        "daily_change_fraction": "-0.01",
        "volume_ratio": "1",
        "time_sensitive": True,
        "source": "strategy.signal:v1",
        "reason": "Observed current strength with bounded paper inputs.",
    }
    payload.update(overrides)
    return payload


def test_observation_schema_canonical_bytes_round_trip_and_conversion():
    # Break caught: provenance or decimal bytes are omitted or normalized in identity.
    from tradingagents.strategy.staged_intent import (
        STRATEGY_OBSERVATION_REASON_MAX_UTF8_BYTES,
        STRATEGY_OBSERVATION_SOURCE_MAX_BYTES,
        StrategyObservationEvidence,
    )

    observation = StrategyObservationEvidence.from_dict(_observation_payload())

    assert STRATEGY_OBSERVATION_SOURCE_MAX_BYTES == 64
    assert STRATEGY_OBSERVATION_REASON_MAX_UTF8_BYTES == 512
    assert observation.to_dict() == _observation_payload()
    assert observation.canonical_json_bytes() == (
        b'{"current_price":"100","daily_change_fraction":"-0.01",'
        b'"reason":"Observed current strength with bounded paper inputs.",'
        b'"schema_version":1,"score":"0.8","source":"strategy.signal:v1",'
        b'"symbol":"NFLX","time_sensitive":true,"volume_ratio":"1"}'
    )
    assert (
        StrategyObservationEvidence.from_dict(observation.to_dict())
        == observation
    )
    compiler_observation = observation.to_strategy_observation()
    assert compiler_observation.symbol == "NFLX"
    assert compiler_observation.score == Decimal("0.8")
    assert compiler_observation.current_price == Decimal("100")
    assert compiler_observation.daily_change_fraction == Decimal("-0.01")
    assert compiler_observation.volume_ratio == Decimal("1")
    assert compiler_observation.time_sensitive is True
    with pytest.raises(dataclasses.FrozenInstanceError):
        observation.reason = "changed"  # type: ignore[misc]


@pytest.mark.parametrize(
    "source",
    (
        "",
        "A",
        "a" * 65,
        "white space",
        "é",
        "a\n",
        1,
    ),
)
def test_observation_source_rejects_invalid_or_oversized_material(source):
    # Break caught: source provenance is normalized or allowed beyond 64 ASCII bytes.
    from tradingagents.strategy.staged_intent import StrategyObservationEvidence

    with pytest.raises((TypeError, ValueError)):
        StrategyObservationEvidence.from_dict(
            _observation_payload(source=source)
        )


def test_observation_source_accepts_exact_64_ascii_bytes():
    # Break caught: the inclusive source byte boundary is implemented off by one.
    from tradingagents.strategy.staged_intent import StrategyObservationEvidence

    source = "a" + ("b" * 63)
    observation = StrategyObservationEvidence.from_dict(
        _observation_payload(source=source)
    )

    assert observation.source == source
    assert len(observation.source.encode("ascii")) == 64


@pytest.mark.parametrize(
    "reason",
    (
        "",
        " leading",
        "trailing ",
        "line\nbreak",
        "control\x00text",
        "e\u0301",
        1,
    ),
)
def test_observation_reason_rejects_noncanonical_or_nonprintable_material(reason):
    # Break caught: reason text is trimmed, normalized, or accepts controls.
    from tradingagents.strategy.staged_intent import StrategyObservationEvidence

    with pytest.raises((TypeError, ValueError)):
        StrategyObservationEvidence.from_dict(
            _observation_payload(reason=reason)
        )


def test_observation_reason_accepts_512_utf8_bytes_and_rejects_513():
    # Break caught: the reason limit counts characters instead of UTF-8 bytes.
    from tradingagents.strategy.staged_intent import StrategyObservationEvidence

    exact = ("a" * 510) + "é"
    oversized = ("a" * 511) + "é"

    accepted = StrategyObservationEvidence.from_dict(
        _observation_payload(reason=exact)
    )
    assert accepted.reason == exact
    assert len(accepted.reason.encode("utf-8")) == 512
    with pytest.raises(ValueError, match="512 UTF-8 bytes"):
        StrategyObservationEvidence.from_dict(
            _observation_payload(reason=oversized)
        )


@pytest.mark.parametrize(
    "field",
    (
        "score",
        "current_price",
        "daily_change_fraction",
        "volume_ratio",
    ),
)
def test_observation_decimal_fields_reject_floats_and_noncanonical_strings(
    field,
):
    # Break caught: identity accepts binary floats or normalizes caller decimal text.
    from tradingagents.strategy.staged_intent import StrategyObservationEvidence

    with pytest.raises((TypeError, ValueError)):
        StrategyObservationEvidence.from_dict(
            _observation_payload(**{field: 0.8})
        )
    with pytest.raises((TypeError, ValueError)):
        StrategyObservationEvidence.from_dict(
            _observation_payload(**{field: "0.80"})
        )


@pytest.mark.parametrize(
    "payload",
    (
        lambda: {**_observation_payload(), "extra": True},
        lambda: {
            key: value
            for key, value in _observation_payload().items()
            if key != "source"
        },
        lambda: {
            **_observation_payload(),
            "day_change_pct": "-1",
        },
        lambda: {
            **_observation_payload(),
            "daily_change_pct": "-1",
        },
    ),
)
def test_observation_strict_parser_rejects_unknown_missing_and_percentage_keys(
    payload,
):
    # Break caught: legacy percentage-point shapes enter the fractional compiler.
    from tradingagents.strategy.staged_intent import StrategyObservationEvidence

    with pytest.raises(ValueError, match="fields"):
        StrategyObservationEvidence.from_dict(payload())


def _candidate_state_payload(**overrides):
    payload = {
        "cash_usd": "100",
        "reserved_buy_notional_usd": "10",
        "held_symbols": ["AAPL"],
        "open_buy_symbols": ["MSFT"],
    }
    payload.update(overrides)
    return payload


def test_candidate_state_strict_projection_round_trip():
    # Break caught: state identity omits reservations or changes symbol ordering.
    from tradingagents.strategy import PaperCandidateState
    from tradingagents.strategy.staged_intent import (
        PAPER_CANDIDATE_STATE_KEYS,
        _paper_candidate_state_from_dict,
        _paper_candidate_state_to_dict,
    )

    state = PaperCandidateState(
        cash_usd=Decimal("100.00"),
        reserved_buy_notional_usd=Decimal("10.0"),
        held_symbols=("AAPL",),
        open_buy_symbols=("MSFT",),
    )
    projection = _paper_candidate_state_to_dict(state)

    assert {
        "cash_usd",
        "reserved_buy_notional_usd",
        "held_symbols",
        "open_buy_symbols",
    } == PAPER_CANDIDATE_STATE_KEYS
    assert projection == _candidate_state_payload()
    assert _paper_candidate_state_from_dict(projection) == state
    assert _paper_candidate_state_to_dict(
        _paper_candidate_state_from_dict(projection)
    ) == projection


@pytest.mark.parametrize(
    "payload",
    (
        lambda: {**_candidate_state_payload(), "extra": True},
        lambda: {
            key: value
            for key, value in _candidate_state_payload().items()
            if key != "cash_usd"
        },
        lambda: _candidate_state_payload(cash_usd=100.0),
        lambda: _candidate_state_payload(cash_usd="100.00"),
        lambda: _candidate_state_payload(held_symbols=("AAPL",)),
        lambda: _candidate_state_payload(open_buy_symbols=["msft"]),
        lambda: {
            **_candidate_state_payload(),
            "reserved_buy_notional_pct": "10",
        },
    ),
)
def test_candidate_state_strict_parser_rejects_noncanonical_shapes(payload):
    # Break caught: arbitrary mappings, floats, or percentage shapes reach compilation.
    from tradingagents.strategy.staged_intent import (
        _paper_candidate_state_from_dict,
    )

    with pytest.raises((TypeError, ValueError)):
        _paper_candidate_state_from_dict(payload())


def test_candidate_state_serializer_rejects_wrong_base_type():
    # Break caught: duck-typed state bypasses the compiler model invariants.
    from tradingagents.strategy.staged_intent import (
        _paper_candidate_state_to_dict,
    )

    with pytest.raises(TypeError, match="PaperCandidateState"):
        _paper_candidate_state_to_dict(_candidate_state_payload())  # type: ignore[arg-type]


def _decision_payload(**overrides):
    payload = {
        "schema_version": 1,
        "genome_id": f"genome-current-aggressive-{'a' * 64}",
        "family": "current-aggressive",
        "action": "buy",
        "symbol": "NFLX",
        "notional_usd": "90.00",
        "limit_price": "100.20",
        "market_session": "regular",
        "extended_hours": False,
        "reason_code": "eligible_current_aggressive",
        "rejected_observation_count": 0,
        "analysis_only": True,
        "paper_only": True,
        "execution_authority": "none",
        "can_submit_orders": False,
    }
    payload.update(overrides)
    return payload


def test_decision_strict_parser_projection_and_digest_bytes():
    # Break caught: decision replay silently drops a field or changes canonical bytes.
    from tradingagents.strategy.staged_intent import (
        GENOME_PAPER_DECISION_KEYS,
        _genome_paper_decision_from_dict,
        _genome_paper_decision_to_dict,
    )

    decision = _genome_paper_decision_from_dict(_decision_payload())
    expected_bytes = (
        b'{"action":"buy","analysis_only":true,"can_submit_orders":false,'
        b'"execution_authority":"none","extended_hours":false,'
        b'"family":"current-aggressive","genome_id":"genome-current-aggressive-'
        + (b"a" * 64)
        + b'","limit_price":"100.20","market_session":"regular",'
        b'"notional_usd":"90.00","paper_only":true,'
        b'"reason_code":"eligible_current_aggressive",'
        b'"rejected_observation_count":0,"schema_version":1,'
        b'"symbol":"NFLX"}'
    )

    assert set(_decision_payload()) == GENOME_PAPER_DECISION_KEYS
    assert _genome_paper_decision_to_dict(decision) == _decision_payload()
    assert decision.canonical_json_bytes() == expected_bytes
    assert hashlib.sha256(decision.canonical_json_bytes()).digest() == (
        hashlib.sha256(expected_bytes).digest()
    )
    assert (
        _genome_paper_decision_from_dict(
            _genome_paper_decision_to_dict(decision)
        )
        == decision
    )


def test_decision_strict_parser_accepts_valid_hold():
    # Break caught: HOLD evidence is rejected even though no order is implied.
    from tradingagents.strategy.staged_intent import (
        _genome_paper_decision_from_dict,
    )

    hold = _genome_paper_decision_from_dict(
        _decision_payload(
            action="hold-cash",
            symbol=None,
            notional_usd="0.00",
            limit_price=None,
            reason_code="market_closed",
            market_session="closed",
        )
    )

    assert hold.action.value == "hold-cash"
    assert hold.symbol is None
    assert hold.notional_usd == "0.00"
    assert hold.limit_price is None


@pytest.mark.parametrize(
    "payload",
    (
        lambda: {**_decision_payload(), "extra": True},
        lambda: {
            key: value
            for key, value in _decision_payload().items()
            if key != "genome_id"
        },
        lambda: _decision_payload(family="unknown"),
        lambda: _decision_payload(action="submit"),
        lambda: _decision_payload(notional_usd=90.0),
        lambda: _decision_payload(analysis_only=False),
        lambda: _decision_payload(paper_only=False),
        lambda: _decision_payload(execution_authority="paper"),
        lambda: _decision_payload(can_submit_orders=True),
        lambda: {
            **_decision_payload(),
            "notional_pct": "10",
        },
    ),
)
def test_decision_strict_parser_rejects_noncanonical_shapes(payload):
    # Break caught: arbitrary, percentage, or authority-bearing decisions replay.
    from tradingagents.strategy.staged_intent import (
        _genome_paper_decision_from_dict,
    )

    with pytest.raises((TypeError, ValueError)):
        _genome_paper_decision_from_dict(payload())


def test_decision_serializer_rejects_wrong_base_type():
    # Break caught: a decision-shaped mapping bypasses compiler invariants.
    from tradingagents.strategy.staged_intent import (
        _genome_paper_decision_to_dict,
    )

    with pytest.raises(TypeError, match="GenomePaperDecision"):
        _genome_paper_decision_to_dict(_decision_payload())  # type: ignore[arg-type]


def _canonical_test_bytes(payload):
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _staged_model_payload():
    from tradingagents.strategy import (
        CurrentAggressiveParameters,
        GenomePaperDecision,
        PaperDecisionAction,
        StrategyFamily,
        StrategyGenome,
        load_strategy_evolution_policy,
    )
    from tradingagents.strategy.staged_intent import StrategyObservationEvidence

    genome = StrategyGenome.create(
        family=StrategyFamily.CURRENT_AGGRESSIVE,
        parameters=CurrentAggressiveParameters(min_score="0.8"),
        generation=1,
        parent_id="baseline-root",
    )
    policy = load_strategy_evolution_policy(
        REPO_ROOT / "config" / "strategy_evolution.json"
    )
    observation = StrategyObservationEvidence.from_dict(_observation_payload())
    decision = GenomePaperDecision(
        genome_id=genome.genome_id,
        family=genome.family,
        action=PaperDecisionAction.BUY,
        symbol="NFLX",
        notional_usd="90.00",
        limit_price="100.20",
        market_session="regular",
        extended_hours=False,
        reason_code="eligible_current_aggressive",
        rejected_observation_count=0,
    )
    observations = [observation.to_dict()]
    candidate_projection = _candidate_state_payload()
    payload = {
        "schema_version": 1,
        "staged_intent_id": "",
        "registration_id": f"evaluation-registration-{'1' * 64}",
        "promotion_evidence_id": f"promotion-evidence-{'2' * 64}",
        "promotion_evidence_sha256": "3" * 64,
        "genome": genome.to_dict(),
        "genome_canonical_sha256": hashlib.sha256(
            genome.canonical_json_bytes()
        ).hexdigest(),
        "evaluation_code_commit": "4" * 40,
        "evaluation_runtime_sha256": "5" * 64,
        "evolution_policy": policy.to_dict(),
        "evolution_policy_sha256": hashlib.sha256(
            policy.canonical_json_bytes()
        ).hexdigest(),
        "session_date": "2030-04-01",
        "observations": observations,
        "observations_sha256": hashlib.sha256(
            _canonical_test_bytes(observations)
        ).hexdigest(),
        "candidate_state": candidate_projection,
        "candidate_state_sha256": hashlib.sha256(
            _canonical_test_bytes(candidate_projection)
        ).hexdigest(),
        "market_session": "regular",
        "decision": decision.to_dict(),
        "decision_sha256": hashlib.sha256(
            decision.canonical_json_bytes()
        ).hexdigest(),
        "expires_at": "2030-04-01T14:15:00+00:00",
        "effective_at": "2030-04-01T14:00:00+00:00",
        "recorded_at": "2030-04-01T14:00:05+00:00",
        "analysis_only": True,
        "paper_only": True,
        "execution_authority": "none",
        "can_submit_orders": False,
    }
    _reidentify_staged_payload(payload)
    return payload


def _reidentify_staged_payload(payload):
    evidence_payload = {
        key: value
        for key, value in payload.items()
        if key not in {"staged_intent_id", "effective_at", "recorded_at"}
    }
    retry_material = {
        "kind": "staged-paper-intent",
        "effective_at": payload["effective_at"],
        "payload": evidence_payload,
    }
    payload["staged_intent_id"] = (
        "staged-paper-intent-"
        + hashlib.sha256(_canonical_test_bytes(retry_material)).hexdigest()
    )


def test_model_schema_canonical_round_trip_deep_immutability_and_authority():
    # Break caught: the staged model drops bound evidence or exposes mutable authority.
    from tradingagents.strategy import StagedPaperIntent

    payload = _staged_model_payload()
    intent = StagedPaperIntent.from_dict(payload)

    assert intent.to_dict() == payload
    assert intent.canonical_json_bytes() == _canonical_test_bytes(payload)
    assert StagedPaperIntent.from_dict(intent.to_dict()) == intent
    assert type(intent.observations) is tuple
    assert type(intent.candidate_state.held_symbols) is tuple
    assert intent.analysis_only is True
    assert intent.paper_only is True
    assert intent.execution_authority == "none"
    assert intent.can_submit_orders is False
    with pytest.raises(dataclasses.FrozenInstanceError):
        intent.expires_at = "changed"  # type: ignore[misc]


@pytest.mark.parametrize("invalid_version", (True, 1.0))
@pytest.mark.parametrize(
    "schema_name",
    ("observation", "evolution_policy", "staged_intent"),
)
def test_nested_and_top_level_schema_versions_require_exact_int(
    schema_name,
    invalid_version,
):
    # Break caught: bool or float 1 is normalized into canonical integer schema 1.
    from tradingagents.strategy import StagedPaperIntent
    from tradingagents.strategy.staged_intent import (
        StrategyObservationEvidence,
        _strategy_evolution_policy_from_dict,
    )

    if schema_name == "observation":
        with pytest.raises(ValueError, match="schema_version"):
            StrategyObservationEvidence.from_dict(
                _observation_payload(schema_version=invalid_version)
            )
        return

    payload = _staged_model_payload()
    if schema_name == "evolution_policy":
        policy_payload = dict(payload["evolution_policy"])
        policy_payload["schema_version"] = invalid_version
        with pytest.raises(ValueError, match="schema_version"):
            _strategy_evolution_policy_from_dict(policy_payload)
        return

    payload["schema_version"] = invalid_version
    with pytest.raises(ValueError, match="schema_version"):
        StagedPaperIntent.from_dict(payload)


def test_schema_versions_canonical_round_trip_as_exact_ints():
    # Break caught: a valid parser round trip changes schema type or canonical bytes.
    from tradingagents.strategy import StagedPaperIntent
    from tradingagents.strategy.staged_intent import (
        StrategyObservationEvidence,
        _strategy_evolution_policy_from_dict,
    )

    observation_payload = _observation_payload()
    observation = StrategyObservationEvidence.from_dict(observation_payload)
    assert observation.to_dict() == observation_payload
    assert type(observation.to_dict()["schema_version"]) is int

    staged_payload = _staged_model_payload()
    policy_payload = staged_payload["evolution_policy"]
    policy = _strategy_evolution_policy_from_dict(policy_payload)
    assert policy.to_dict() == policy_payload
    assert type(policy.to_dict()["schema_version"]) is int

    intent = StagedPaperIntent.from_dict(staged_payload)
    assert intent.to_dict() == staged_payload
    assert type(intent.to_dict()["schema_version"]) is int
    assert intent.canonical_json_bytes() == _canonical_test_bytes(
        staged_payload
    )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("genome_canonical_sha256", "0" * 64, "genome"),
        ("evaluation_code_commit", "A" * 40, "commit"),
        ("evaluation_runtime_sha256", "short", "runtime"),
        ("evolution_policy_sha256", "0" * 64, "policy"),
        ("observations_sha256", "0" * 64, "observation"),
        ("candidate_state_sha256", "0" * 64, "candidate"),
        ("decision_sha256", "0" * 64, "decision"),
        ("analysis_only", False, "analysis_only"),
        ("paper_only", False, "paper_only"),
        ("execution_authority", "paper", "execution_authority"),
        ("can_submit_orders", True, "can_submit_orders"),
    ),
)
def test_model_rejects_digest_commit_and_authority_drift(field, value, message):
    # Break caught: identity-bound material can change under a rehashed outer ID.
    from tradingagents.strategy import StagedPaperIntent

    payload = _staged_model_payload()
    payload[field] = value
    _reidentify_staged_payload(payload)

    with pytest.raises((TypeError, ValueError), match=message):
        StagedPaperIntent.from_dict(payload)


def test_model_rejects_unknown_missing_fields_and_duplicate_symbols():
    # Break caught: schema expansion or duplicate observations changes compiler meaning.
    from tradingagents.strategy import StagedPaperIntent

    extra = {**_staged_model_payload(), "live_enabled": True}
    with pytest.raises(ValueError, match="fields"):
        StagedPaperIntent.from_dict(extra)

    missing = _staged_model_payload()
    del missing["promotion_evidence_sha256"]
    with pytest.raises(ValueError, match="fields"):
        StagedPaperIntent.from_dict(missing)

    duplicated = _staged_model_payload()
    duplicated["observations"] = [
        duplicated["observations"][0],
        duplicated["observations"][0],
    ]
    duplicated["observations_sha256"] = hashlib.sha256(
        _canonical_test_bytes(duplicated["observations"])
    ).hexdigest()
    _reidentify_staged_payload(duplicated)
    with pytest.raises(ValueError, match="duplicate observation symbol"):
        StagedPaperIntent.from_dict(duplicated)


def _evaluation_windows():
    from tradingagents.strategy import EvaluationWindowSpec

    return (
        EvaluationWindowSpec(
            ordinal=1,
            window_start="2030-01-02",
            window_end="2030-01-22",
            first_effective_at="2030-01-02T15:00:00Z",
            last_effective_at="2030-01-22T15:00:00Z",
            evaluation_as_of="2030-01-22T16:00:00Z",
            expected_tracked_sessions=21,
        ),
        EvaluationWindowSpec(
            ordinal=2,
            window_start="2030-02-02",
            window_end="2030-02-22",
            first_effective_at="2030-02-02T15:00:00Z",
            last_effective_at="2030-02-22T15:00:00Z",
            evaluation_as_of="2030-02-22T16:00:00Z",
            expected_tracked_sessions=21,
        ),
        EvaluationWindowSpec(
            ordinal=3,
            window_start="2030-03-02",
            window_end="2030-03-22",
            first_effective_at="2030-03-02T15:00:00Z",
            last_effective_at="2030-03-22T15:00:00Z",
            evaluation_as_of="2030-03-22T16:00:00Z",
            expected_tracked_sessions=21,
        ),
    )


def _evaluation_frames(window, *, score=Decimal("0.8")):
    from tradingagents.strategy import StrategyObservation
    from tradingagents.strategy.evaluator import EvaluationFrame, EvaluationMark

    start = dt.datetime.fromisoformat(window.first_effective_at)
    frames = []
    for index in range(window.expected_tracked_sessions):
        block = index // 5
        price = Decimal("100") * (Decimal("1.1") ** block)
        effective = start + dt.timedelta(days=index)
        frames.append(
            EvaluationFrame(
                session_date=effective.date(),
                effective_at=effective,
                recorded_at=effective + dt.timedelta(minutes=1),
                market_session="regular",
                observations=(
                    StrategyObservation(
                        symbol="NFLX",
                        score=score,
                        current_price=price,
                        daily_change_fraction=Decimal("-0.01"),
                        volume_ratio=Decimal("1"),
                        time_sensitive=True,
                    ),
                ),
                marks=(EvaluationMark("NFLX", price),),
                benchmark_price=Decimal("100"),
            )
        )
    return tuple(frames)


def _durable_internal_evidence(
    tmp_path,
    *,
    observation_score=Decimal("0.8"),
    genome_parent_id="baseline-root",
    require_complete=True,
):
    from tradingagents.strategy import (
        CurrentAggressiveParameters,
        StrategyFamily,
        StrategyGenome,
        StrategyPromotionEvidenceLedger,
        evaluate_genome_window,
        load_strategy_evaluation_policy,
        load_strategy_evolution_policy,
    )

    root = tmp_path / "evidence"
    windows = _evaluation_windows()
    evolution_policy = load_strategy_evolution_policy(
        REPO_ROOT / "config" / "strategy_evolution.json"
    )
    evaluation_policy = load_strategy_evaluation_policy(
        REPO_ROOT / "config" / "strategy_evaluation.json"
    )
    genome = StrategyGenome.create(
        family=StrategyFamily.CURRENT_AGGRESSIVE,
        parameters=CurrentAggressiveParameters(min_score="0.8"),
        generation=1,
        parent_id=genome_parent_id,
    )
    ledger = StrategyPromotionEvidenceLedger(
        root,
        repo_root=REPO_ROOT,
        clock=_Clock(
            dt.datetime(2029, 12, 31, 16, 0, tzinfo=UTC),
            dt.datetime(2030, 1, 22, 16, 1, tzinfo=UTC),
            dt.datetime(2030, 2, 22, 16, 1, tzinfo=UTC),
            dt.datetime(2030, 3, 22, 16, 1, tzinfo=UTC),
            dt.datetime(2030, 3, 22, 16, 2, tzinfo=UTC),
        ),
    )
    registration = ledger.register(
        genome=genome,
        evolution_policy=evolution_policy,
        evaluation_policy=evaluation_policy,
        windows=windows,
        evaluation_code_commit=_run_git(REPO_ROOT, "rev-parse", "HEAD"),
        effective_at=dt.datetime(2029, 12, 31, 15, 0, tzinfo=UTC),
    )
    for ordinal, window in enumerate(windows, start=1):
        frames = _evaluation_frames(window, score=observation_score)
        result = evaluate_genome_window(
            registration.genome,
            registration.evolution_policy,
            registration.evaluation_policy,
            frames,
            evaluation_as_of=dt.datetime.fromisoformat(window.evaluation_as_of),
        )
        ledger.admit_window(
            registration.registration_id,
            ordinal,
            frames,
            result,
        )
    evidence = ledger.assemble(registration.registration_id)
    assert evidence.complete_internal_evidence is require_complete
    return root, registration, evidence


def _stage_observations():
    from tradingagents.strategy import StrategyObservationEvidence

    return [
        StrategyObservationEvidence.from_dict(
            _observation_payload(
                score="0.9",
                source="strategy.signal:v1",
                reason="Current strength cleared the frozen paper threshold.",
            )
        )
    ]


def _stage_candidate_state():
    from tradingagents.strategy import PaperCandidateState

    return PaperCandidateState(
        cash_usd=Decimal("100"),
        reserved_buy_notional_usd=Decimal("10"),
        held_symbols=("AAPL",),
        open_buy_symbols=("MSFT",),
    )


def _stage_once(
    root,
    registration,
    evidence,
    *,
    clock=None,
    market_session="regular",
):
    from tradingagents.strategy import StrategyStagedIntentLedger

    ledger = StrategyStagedIntentLedger(
        root,
        repo_root=REPO_ROOT,
        clock=clock
        or _Clock(dt.datetime(2030, 4, 1, 14, 0, 5, tzinfo=UTC)),
    )
    intent = ledger.stage(
        registration=registration,
        promotion_evidence=evidence,
        observations=_stage_observations(),
        candidate_state=_stage_candidate_state(),
        session_date="2030-04-01",
        market_session=market_session,
        effective_at=dt.datetime(2030, 4, 1, 14, 0, tzinfo=UTC),
        expires_at=dt.datetime(2030, 4, 1, 14, 15, tzinfo=UTC),
    )
    return ledger, intent


@pytest.mark.parametrize("invalid_version", (True, 1.0))
def test_invalid_observation_schema_rejects_before_staged_event(
    tmp_path,
    invalid_version,
):
    # Break caught: invalid observation schema normalizes and gains durability.
    from tradingagents.strategy import StrategyObservationEvidence

    root, registration, evidence = _durable_internal_evidence(tmp_path)
    before = (root / "events.jsonl").read_bytes()

    with pytest.raises(ValueError, match="schema_version"):
        observation = StrategyObservationEvidence.from_dict(
            _observation_payload(schema_version=invalid_version)
        )
        _stage_with_times(
            root,
            registration,
            evidence,
            clock_time=dt.datetime(2030, 4, 1, 14, 0, 5, tzinfo=UTC),
            effective_at=dt.datetime(2030, 4, 1, 14, 0, tzinfo=UTC),
            expires_at=dt.datetime(2030, 4, 1, 14, 15, tzinfo=UTC),
            observations=[observation],
        )

    assert (root / "events.jsonl").read_bytes() == before


def _stage_with_times(
    root,
    registration,
    evidence,
    *,
    clock_time,
    effective_at,
    expires_at,
    observations=None,
    candidate_state=None,
    session_date="2030-04-01",
    market_session="regular",
):
    from tradingagents.strategy import StrategyStagedIntentLedger

    ledger = StrategyStagedIntentLedger(
        root,
        repo_root=REPO_ROOT,
        clock=_Clock(clock_time),
    )
    intent = ledger.stage(
        registration=registration,
        promotion_evidence=evidence,
        observations=observations or _stage_observations(),
        candidate_state=candidate_state or _stage_candidate_state(),
        session_date=session_date,
        market_session=market_session,
        effective_at=effective_at,
        expires_at=expires_at,
    )
    return ledger, intent


def test_buy_stage_replays_compiler_once_with_runtime_bracket(
    tmp_path,
    monkeypatch,
):
    # Break caught: admission trusts a caller decision or compiles inside the lock.
    import tradingagents.strategy.staged_intent as module
    from tradingagents.strategy import StrategyStagedIntentLedger

    root, registration, evidence = _durable_internal_evidence(tmp_path)
    observations = _stage_observations()
    state = _stage_candidate_state()
    expected = module.compile_genome_paper_decision(
        registration.genome,
        registration.evolution_policy,
        tuple(item.to_strategy_observation() for item in observations),
        state,
        market_session="regular",
    )
    original_compile = module.compile_genome_paper_decision
    original_runtime = module.require_active_evaluation_runtime
    compile_calls = 0
    runtime_manifests = []

    def counted_compile(*args, **kwargs):
        nonlocal compile_calls
        compile_calls += 1
        return original_compile(*args, **kwargs)

    def counted_runtime(*args, **kwargs):
        manifest = original_runtime(*args, **kwargs)
        runtime_manifests.append(manifest.canonical_json_bytes())
        return manifest

    monkeypatch.setattr(module, "compile_genome_paper_decision", counted_compile)
    monkeypatch.setattr(module, "require_active_evaluation_runtime", counted_runtime)
    ledger = StrategyStagedIntentLedger(
        root,
        repo_root=REPO_ROOT,
        clock=_Clock(dt.datetime(2030, 4, 1, 14, 0, 5, tzinfo=UTC)),
    )

    intent = ledger.stage(
        registration=registration,
        promotion_evidence=evidence,
        observations=observations,
        candidate_state=state,
        session_date="2030-04-01",
        market_session="regular",
        effective_at=dt.datetime(2030, 4, 1, 14, 0, tzinfo=UTC),
        expires_at=dt.datetime(2030, 4, 1, 14, 15, tzinfo=UTC),
    )

    assert compile_calls == 1
    assert len(runtime_manifests) == 2
    assert runtime_manifests[0] == runtime_manifests[1]
    assert intent.decision == expected
    assert intent.decision.action.value == "buy"
    assert intent.decision.notional_usd == "90.00"
    assert intent.promotion_evidence_sha256 == hashlib.sha256(
        evidence.canonical_json_bytes()
    ).hexdigest()
    assert intent.recorded_at == "2030-04-01T14:00:05+00:00"
    assert (root / "events.jsonl").read_bytes().count(b"\n") == 6


def test_hold_stage_is_valid_durable_analysis_without_order_meaning(tmp_path):
    # Break caught: HOLD is discarded or incorrectly grants submission authority.
    from tradingagents.strategy import StrategyStagedIntentLedger

    root, registration, evidence = _durable_internal_evidence(tmp_path)
    ledger = StrategyStagedIntentLedger(
        root,
        repo_root=REPO_ROOT,
        clock=_Clock(dt.datetime(2030, 4, 1, 14, 0, 5, tzinfo=UTC)),
    )

    intent = ledger.stage(
        registration=registration,
        promotion_evidence=evidence,
        observations=_stage_observations(),
        candidate_state=_stage_candidate_state(),
        session_date="2030-04-01",
        market_session="closed",
        effective_at=dt.datetime(2030, 4, 1, 14, 0, tzinfo=UTC),
        expires_at=dt.datetime(2030, 4, 1, 14, 15, tzinfo=UTC),
    )

    assert intent.decision.action.value == "hold-cash"
    assert intent.decision.symbol is None
    assert intent.decision.notional_usd == "0.00"
    assert intent.decision.limit_price is None
    assert intent.can_submit_orders is False
    assert intent.execution_authority == "none"


def test_admission_callbacks_do_not_reenter_runtime_or_compiler(
    tmp_path,
    monkeypatch,
):
    # Break caught: lock-held validation performs source I/O or compiler work.
    import tradingagents.strategy.staged_intent as module
    from tradingagents.strategy import StrategyStagedIntentLedger

    root, registration, evidence = _durable_internal_evidence(tmp_path)
    ledger = StrategyStagedIntentLedger(
        root,
        repo_root=REPO_ROOT,
        clock=_Clock(dt.datetime(2030, 4, 1, 14, 0, 5, tzinfo=UTC)),
    )
    original_admit = ledger._store.admit_checked
    original_compile = module.compile_genome_paper_decision
    original_runtime = module.require_active_evaluation_runtime
    inside_callback = False

    def guarded_compile(*args, **kwargs):
        assert inside_callback is False
        return original_compile(*args, **kwargs)

    def guarded_runtime(*args, **kwargs):
        assert inside_callback is False
        return original_runtime(*args, **kwargs)

    def wrapped_admit(
        candidate,
        *,
        validate,
        validate_orphans=None,
        validate_combined=None,
    ):
        assert validate_combined is not None

        def wrap(callback):
            def guarded(*args):
                nonlocal inside_callback
                inside_callback = True
                try:
                    return callback(*args)
                finally:
                    inside_callback = False

            return guarded

        return original_admit(
            candidate,
            validate=wrap(validate),
            validate_orphans=(
                wrap(validate_orphans)
                if validate_orphans is not None
                else None
            ),
            validate_combined=(
                wrap(validate_combined)
                if validate_combined is not None
                else None
            ),
        )

    monkeypatch.setattr(module, "compile_genome_paper_decision", guarded_compile)
    monkeypatch.setattr(
        module,
        "require_active_evaluation_runtime",
        guarded_runtime,
    )
    monkeypatch.setattr(ledger._store, "admit_checked", wrapped_admit)

    intent = ledger.stage(
        registration=registration,
        promotion_evidence=evidence,
        observations=_stage_observations(),
        candidate_state=_stage_candidate_state(),
        session_date="2030-04-01",
        market_session="regular",
        effective_at=dt.datetime(2030, 4, 1, 14, 0, tzinfo=UTC),
        expires_at=dt.datetime(2030, 4, 1, 14, 15, tzinfo=UTC),
    )

    assert intent.decision.action.value == "buy"


@pytest.mark.parametrize("operation", ("verify", "rebuild"))
def test_replay_requires_byte_identical_compiler_decision(
    tmp_path,
    monkeypatch,
    operation,
):
    # Break caught: historical replay accepts a changed compiler decision.
    import tradingagents.strategy.staged_intent as module

    root, registration, evidence = _durable_internal_evidence(tmp_path)
    ledger, _intent = _stage_once(root, registration, evidence)
    original_compile = module.compile_genome_paper_decision

    def changed_compile(*args, **kwargs):
        decision = original_compile(*args, **kwargs)
        return dataclasses.replace(
            decision,
            notional_usd="89.99",
        )

    monkeypatch.setattr(
        module,
        "compile_genome_paper_decision",
        changed_compile,
    )

    with pytest.raises(ValueError, match="decision"):
        getattr(ledger, operation)()


def test_head_advance_allows_stage_verify_and_rebuild(tmp_path, monkeypatch):
    # Break caught: unrelated descendant HEAD incorrectly invalidates frozen bytes.
    import tradingagents.strategy.promotion_evidence as promotion_module

    root, registration, evidence = _durable_internal_evidence(tmp_path)
    original_git_text = promotion_module._git_text

    def descendant_git_text(repo_root: Path, *args: str) -> str:
        if args == ("rev-parse", "HEAD"):
            return "f" * 40
        return original_git_text(repo_root, *args)

    monkeypatch.setattr(
        promotion_module,
        "_git_text",
        descendant_git_text,
    )
    ledger, intent = _stage_once(root, registration, evidence)

    assert ledger.verify() == (intent,)
    assert ledger.rebuild() == (intent,)


def _drift_calculation_source(monkeypatch, relative):
    import tradingagents.strategy.promotion_evidence as promotion_module

    original = promotion_module._read_regular_source

    def drifted(repo_root: Path, candidate: str) -> bytes:
        active = original(repo_root, candidate)
        if candidate == relative:
            return active + b"drift\n"
        return active

    monkeypatch.setattr(
        promotion_module,
        "_read_regular_source",
        drifted,
    )


@pytest.mark.parametrize("operation", ("stage", "verify", "rebuild"))
@pytest.mark.parametrize("source_index", range(5))
def test_source_drift_rejects_before_compiler_replay(
    tmp_path,
    monkeypatch,
    operation,
    source_index,
):
    # Break caught: drifted calculation bytes reach compiler replay.
    import tradingagents.strategy.promotion_evidence as promotion_module
    import tradingagents.strategy.staged_intent as module
    from tradingagents.strategy import StrategyStagedIntentLedger

    root, registration, evidence = _durable_internal_evidence(tmp_path)
    ledger = StrategyStagedIntentLedger(
        root,
        repo_root=REPO_ROOT,
        clock=_Clock(dt.datetime(2030, 4, 1, 14, 0, 5, tzinfo=UTC)),
    )
    if operation != "stage":
        ledger.stage(
            registration=registration,
            promotion_evidence=evidence,
            observations=_stage_observations(),
            candidate_state=_stage_candidate_state(),
            session_date="2030-04-01",
            market_session="regular",
            effective_at=dt.datetime(2030, 4, 1, 14, 0, tzinfo=UTC),
            expires_at=dt.datetime(2030, 4, 1, 14, 15, tzinfo=UTC),
        )
    before = (root / "events.jsonl").read_bytes()
    _drift_calculation_source(
        monkeypatch,
        promotion_module.EVALUATION_SOURCE_PATHS[source_index],
    )
    compiler_called = False

    def forbidden_compiler(*_args, **_kwargs):
        nonlocal compiler_called
        compiler_called = True
        raise AssertionError("compiler ran after active source drift")

    monkeypatch.setattr(
        module,
        "compile_genome_paper_decision",
        forbidden_compiler,
    )

    with pytest.raises(
        ValueError,
        match="loaded calculation source|active calculation manifest",
    ):
        if operation == "stage":
            ledger.stage(
                registration=registration,
                promotion_evidence=evidence,
                observations=_stage_observations(),
                candidate_state=_stage_candidate_state(),
                session_date="2030-04-01",
                market_session="regular",
                effective_at=dt.datetime(
                    2030, 4, 1, 14, 0, tzinfo=UTC
                ),
                expires_at=dt.datetime(
                    2030, 4, 1, 14, 15, tzinfo=UTC
                ),
            )
        else:
            getattr(ledger, operation)()

    assert compiler_called is False
    assert (root / "events.jsonl").read_bytes() == before


@pytest.mark.parametrize("operation", ("stage", "verify", "rebuild"))
def test_evaluation_runtime_change_during_replay_rejects(
    tmp_path,
    monkeypatch,
    operation,
):
    # Break caught: compiler replay spans two different active manifests.
    import tradingagents.strategy.staged_intent as module
    from tradingagents.strategy import StrategyStagedIntentLedger

    root, registration, evidence = _durable_internal_evidence(tmp_path)
    ledger = StrategyStagedIntentLedger(
        root,
        repo_root=REPO_ROOT,
        clock=_Clock(dt.datetime(2030, 4, 1, 14, 0, 5, tzinfo=UTC)),
    )
    if operation != "stage":
        ledger.stage(
            registration=registration,
            promotion_evidence=evidence,
            observations=_stage_observations(),
            candidate_state=_stage_candidate_state(),
            session_date="2030-04-01",
            market_session="regular",
            effective_at=dt.datetime(2030, 4, 1, 14, 0, tzinfo=UTC),
            expires_at=dt.datetime(2030, 4, 1, 14, 15, tzinfo=UTC),
        )
    before = (root / "events.jsonl").read_bytes()
    original_runtime = module.require_active_evaluation_runtime
    calls = 0

    def changed_runtime(*args, **kwargs):
        nonlocal calls
        calls += 1
        manifest = original_runtime(*args, **kwargs)
        if calls == 2:
            first = dataclasses.replace(
                manifest.files[0],
                sha256="f" * 64,
            )
            return dataclasses.replace(
                manifest,
                files=(first, *manifest.files[1:]),
            )
        return manifest

    monkeypatch.setattr(
        module,
        "require_active_evaluation_runtime",
        changed_runtime,
    )

    with pytest.raises(ValueError, match="runtime changed"):
        if operation == "stage":
            ledger.stage(
                registration=registration,
                promotion_evidence=evidence,
                observations=_stage_observations(),
                candidate_state=_stage_candidate_state(),
                session_date="2030-04-01",
                market_session="regular",
                effective_at=dt.datetime(
                    2030, 4, 1, 14, 0, tzinfo=UTC
                ),
                expires_at=dt.datetime(
                    2030, 4, 1, 14, 15, tzinfo=UTC
                ),
            )
        else:
            getattr(ledger, operation)()

    assert calls == 2
    assert (root / "events.jsonl").read_bytes() == before


def test_ttl_exact_900_seconds_and_half_open_active_interval(tmp_path):
    # Break caught: inclusive expiry or an off-by-one TTL changes paper eligibility.
    root, registration, evidence = _durable_internal_evidence(tmp_path)
    ledger, intent = _stage_with_times(
        root,
        registration,
        evidence,
        clock_time=dt.datetime(2030, 4, 1, 14, 0, 5, tzinfo=UTC),
        effective_at=dt.datetime(2030, 4, 1, 14, 0, tzinfo=UTC),
        expires_at=dt.datetime(2030, 4, 1, 14, 15, tzinfo=UTC),
    )

    recorded = dt.datetime.fromisoformat(intent.recorded_at)
    expires = dt.datetime.fromisoformat(intent.expires_at)
    assert intent.is_active(at=recorded) is True
    assert intent.is_active(at=expires - dt.timedelta(seconds=1)) is True
    assert intent.is_active(at=expires) is False
    assert intent.is_active(at=recorded - dt.timedelta(seconds=1)) is False
    assert ledger.verify() == (intent,)


def test_ttl_one_second_over_limit_rejects_without_event(tmp_path):
    # Break caught: a 901-second intent bypasses the frozen 15-minute maximum.
    root, registration, evidence = _durable_internal_evidence(tmp_path)
    before = (root / "events.jsonl").read_bytes()

    with pytest.raises(ValueError, match="900 seconds"):
        _stage_with_times(
            root,
            registration,
            evidence,
            clock_time=dt.datetime(2030, 4, 1, 14, 0, 5, tzinfo=UTC),
            effective_at=dt.datetime(2030, 4, 1, 14, 0, tzinfo=UTC),
            expires_at=dt.datetime(2030, 4, 1, 14, 15, 1, tzinfo=UTC),
        )

    assert (root / "events.jsonl").read_bytes() == before


@pytest.mark.parametrize(
    ("effective_at", "expires_at", "message"),
    (
        (
            dt.datetime(2030, 4, 1, 14, 0, 6, tzinfo=UTC),
            dt.datetime(2030, 4, 1, 14, 15, tzinfo=UTC),
            "future-effective",
        ),
        (
            dt.datetime(2030, 4, 1, 14, 0, tzinfo=UTC),
            dt.datetime(2030, 4, 1, 14, 0, 5, tzinfo=UTC),
            "expired",
        ),
    ),
)
def test_ttl_future_effective_or_expired_first_admission_rejects_without_event(
    tmp_path,
    effective_at,
    expires_at,
    message,
):
    # Break caught: the store first-sees an intent outside its active interval.
    root, registration, evidence = _durable_internal_evidence(tmp_path)
    before = (root / "events.jsonl").read_bytes()

    with pytest.raises(ValueError, match=message):
        _stage_with_times(
            root,
            registration,
            evidence,
            clock_time=dt.datetime(2030, 4, 1, 14, 0, 5, tzinfo=UTC),
            effective_at=effective_at,
            expires_at=expires_at,
        )

    assert (root / "events.jsonl").read_bytes() == before


def test_active_inputs_normalize_aware_offsets_and_reject_naive_at(tmp_path):
    # Break caught: equivalent aware timestamps produce noncanonical identities.
    root, registration, evidence = _durable_internal_evidence(tmp_path)
    eastern = dt.timezone(dt.timedelta(hours=-4))
    _ledger, intent = _stage_with_times(
        root,
        registration,
        evidence,
        clock_time=dt.datetime(2030, 4, 1, 14, 0, 5, tzinfo=UTC),
        effective_at=dt.datetime(2030, 4, 1, 10, 0, tzinfo=eastern),
        expires_at=dt.datetime(2030, 4, 1, 10, 15, tzinfo=eastern),
    )

    assert intent.effective_at == "2030-04-01T14:00:00+00:00"
    assert intent.expires_at == "2030-04-01T14:15:00+00:00"
    with pytest.raises(ValueError, match="timezone-aware"):
        intent.is_active(at=dt.datetime(2030, 4, 1, 14, 1))


def test_backdated_exact_retry_rejects_without_event(tmp_path):
    # Break caught: a retry clock before first-seen time rewrites chronology.
    from tradingagents.strategy import StrategyStagedIntentLedger
    from tradingagents.strategy._immutable_evidence_store import (
        EvidenceBackdatingError,
    )

    root, registration, evidence = _durable_internal_evidence(tmp_path)
    _ledger, intent = _stage_once(root, registration, evidence)
    before = (root / "events.jsonl").read_bytes()
    earlier = StrategyStagedIntentLedger(
        root,
        repo_root=REPO_ROOT,
        clock=_Clock(dt.datetime(2030, 4, 1, 14, 0, 4, tzinfo=UTC)),
    )

    with pytest.raises(EvidenceBackdatingError):
        earlier.stage(
            registration=registration,
            promotion_evidence=evidence,
            observations=_stage_observations(),
            candidate_state=_stage_candidate_state(),
            session_date=intent.session_date,
            market_session=intent.market_session,
            effective_at=dt.datetime.fromisoformat(intent.effective_at),
            expires_at=dt.datetime.fromisoformat(intent.expires_at),
        )

    assert (root / "events.jsonl").read_bytes() == before


@pytest.mark.parametrize("changed_material", ("observations", "state", "expiry"))
def test_slot_changed_material_conflicts_atomically(
    tmp_path,
    changed_material,
):
    # Break caught: one operational slot acquires two immutable meanings.
    root, registration, evidence = _durable_internal_evidence(tmp_path)
    _ledger, _intent = _stage_once(root, registration, evidence)
    before = (root / "events.jsonl").read_bytes()
    observations = _stage_observations()
    state = _stage_candidate_state()
    expires = dt.datetime(2030, 4, 1, 14, 15, tzinfo=UTC)
    if changed_material == "observations":
        observations = [
            dataclasses.replace(observations[0], reason="Changed reason.")
        ]
    elif changed_material == "state":
        state = dataclasses.replace(state, cash_usd=Decimal("99"))
    else:
        expires -= dt.timedelta(seconds=1)

    with pytest.raises(ValueError, match="logical slot"):
        _stage_with_times(
            root,
            registration,
            evidence,
            clock_time=dt.datetime(2030, 4, 1, 14, 0, 6, tzinfo=UTC),
            effective_at=dt.datetime(2030, 4, 1, 14, 0, tzinfo=UTC),
            expires_at=expires,
            observations=observations,
            candidate_state=state,
        )

    assert (root / "events.jsonl").read_bytes() == before


def test_exact_retry_preserves_first_seen_bytes_and_revalidates_replay(
    tmp_path,
    monkeypatch,
):
    # Break caught: an exact retry bypasses runtime/compiler validation or rewrites time.
    import tradingagents.strategy.staged_intent as module

    root, registration, evidence = _durable_internal_evidence(tmp_path)
    _ledger, original = _stage_once(root, registration, evidence)
    before = (root / "events.jsonl").read_bytes()
    original_compile = module.compile_genome_paper_decision
    original_runtime = module.require_active_evaluation_runtime
    compile_calls = 0
    runtime_calls = 0

    def counted_compile(*args, **kwargs):
        nonlocal compile_calls
        compile_calls += 1
        return original_compile(*args, **kwargs)

    def counted_runtime(*args, **kwargs):
        nonlocal runtime_calls
        runtime_calls += 1
        return original_runtime(*args, **kwargs)

    monkeypatch.setattr(module, "compile_genome_paper_decision", counted_compile)
    monkeypatch.setattr(
        module,
        "require_active_evaluation_runtime",
        counted_runtime,
    )
    retry_ledger, retried = _stage_with_times(
        root,
        registration,
        evidence,
        clock_time=dt.datetime(2030, 4, 1, 14, 0, 10, tzinfo=UTC),
        effective_at=dt.datetime(2030, 4, 1, 14, 0, tzinfo=UTC),
        expires_at=dt.datetime(2030, 4, 1, 14, 15, tzinfo=UTC),
    )

    assert retry_ledger.rebuild() == (original,)
    assert retried == original
    assert retried.recorded_at == "2030-04-01T14:00:05+00:00"
    assert compile_calls == 2
    assert runtime_calls == 4
    assert (root / "events.jsonl").read_bytes() == before


def test_concurrent_changed_material_same_slot_admits_exactly_one(tmp_path):
    # Break caught: two callers race past a pre-lock logical-slot check.
    from tradingagents.strategy import StrategyStagedIntentLedger

    root, registration, evidence = _durable_internal_evidence(tmp_path)
    barrier = threading.Barrier(2)

    def stage(reason: str):
        ledger = StrategyStagedIntentLedger(
            root,
            repo_root=REPO_ROOT,
            clock=_Clock(dt.datetime(2030, 4, 1, 14, 0, 5, tzinfo=UTC)),
        )
        observations = [
            dataclasses.replace(_stage_observations()[0], reason=reason)
        ]
        barrier.wait()
        return ledger.stage(
            registration=registration,
            promotion_evidence=evidence,
            observations=observations,
            candidate_state=_stage_candidate_state(),
            session_date="2030-04-01",
            market_session="regular",
            effective_at=dt.datetime(2030, 4, 1, 14, 0, tzinfo=UTC),
            expires_at=dt.datetime(2030, 4, 1, 14, 15, tzinfo=UTC),
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = (
            executor.submit(stage, "First competing paper meaning."),
            executor.submit(stage, "Second competing paper meaning."),
        )
        outcomes = []
        for future in futures:
            try:
                outcomes.append(future.result())
            except ValueError as exc:
                outcomes.append(exc)

    assert sum(not isinstance(outcome, Exception) for outcome in outcomes) == 1
    errors = [outcome for outcome in outcomes if isinstance(outcome, Exception)]
    assert len(errors) == 1
    assert "logical slot" in str(errors[0])
    assert (root / "events.jsonl").read_bytes().count(b"\n") == 6


def _crash_staged_intent_after_object_fsync(
    root,
    registration,
    evidence,
    *,
    observations=None,
    session_date="2030-04-01",
):
    from tradingagents.strategy import StrategyStagedIntentLedger

    ledger = StrategyStagedIntentLedger(
        root,
        repo_root=REPO_ROOT,
        clock=_Clock(dt.datetime(2030, 4, 1, 14, 0, 5, tzinfo=UTC)),
    )
    original = ledger._store._after_object_fsync

    def crash(_path):
        raise RuntimeError("simulated staged object fsync crash")

    ledger._store._after_object_fsync = crash
    with pytest.raises(RuntimeError, match="object fsync crash"):
        ledger.stage(
            registration=registration,
            promotion_evidence=evidence,
            observations=observations or _stage_observations(),
            candidate_state=_stage_candidate_state(),
            session_date=session_date,
            market_session="regular",
            effective_at=dt.datetime(2030, 4, 1, 14, 0, tzinfo=UTC),
            expires_at=dt.datetime(2030, 4, 1, 14, 15, tzinfo=UTC),
        )
    ledger._store._after_object_fsync = original


def test_exact_object_fsync_orphan_retry_adopts_original_first_seen(tmp_path):
    # Break caught: a byte-exact staged orphan cannot be adopted after a crash.
    root, registration, evidence = _durable_internal_evidence(tmp_path)
    _crash_staged_intent_after_object_fsync(root, registration, evidence)
    before = (root / "events.jsonl").read_bytes()
    orphan_paths = tuple(
        (root / "objects" / "staged-paper-intent").glob("*.json")
    )

    _ledger, repaired = _stage_with_times(
        root,
        registration,
        evidence,
        clock_time=dt.datetime(2030, 4, 1, 14, 0, 10, tzinfo=UTC),
        effective_at=dt.datetime(2030, 4, 1, 14, 0, tzinfo=UTC),
        expires_at=dt.datetime(2030, 4, 1, 14, 15, tzinfo=UTC),
    )

    assert len(orphan_paths) == 1
    assert repaired.recorded_at == "2030-04-01T14:00:05+00:00"
    assert (root / "events.jsonl").read_bytes().count(b"\n") == (
        before.count(b"\n") + 1
    )


def test_changed_material_same_slot_orphan_blocks_before_any_new_bytes(tmp_path):
    # Break caught: a crash orphan and a changed retry create two slot meanings.
    root, registration, evidence = _durable_internal_evidence(tmp_path)
    _crash_staged_intent_after_object_fsync(root, registration, evidence)
    before_events = (root / "events.jsonl").read_bytes()
    before_objects = {
        path.relative_to(root): path.read_bytes()
        for path in (root / "objects").rglob("*.json")
    }
    changed = [
        dataclasses.replace(
            _stage_observations()[0],
            reason="Changed meaning after the object crash.",
        )
    ]

    with pytest.raises(ValueError, match="logical slot"):
        _stage_with_times(
            root,
            registration,
            evidence,
            clock_time=dt.datetime(2030, 4, 1, 14, 0, 10, tzinfo=UTC),
            effective_at=dt.datetime(2030, 4, 1, 14, 0, tzinfo=UTC),
            expires_at=dt.datetime(2030, 4, 1, 14, 15, tzinfo=UTC),
            observations=changed,
        )

    assert (root / "events.jsonl").read_bytes() == before_events
    assert {
        path.relative_to(root): path.read_bytes()
        for path in (root / "objects").rglob("*.json")
    } == before_objects


def _durable_file_bytes(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def test_prerequisite_cross_set_slot_conflict_blocks_unrelated_candidate(
    tmp_path,
):
    # Break caught: admitted A and strict-valid orphan B build separate slot
    # indexes, so later unrelated candidate C can write over their conflict.
    from tradingagents.strategy import StagedPaperIntent
    from tradingagents.strategy._immutable_evidence_store import (
        STAGED_PAPER_INTENT_KIND,
        EvidenceCandidate,
        ImmutableStrategyEvidenceStore,
    )

    root, registration, evidence = _durable_internal_evidence(tmp_path)
    _ledger, admitted = _stage_once(root, registration, evidence)
    orphan_payload = admitted.to_dict()
    orphan_payload["expires_at"] = "2030-04-01T14:14:59+00:00"
    _reidentify_staged_payload(orphan_payload)
    orphan = StagedPaperIntent.from_dict(orphan_payload)
    orphan_store = ImmutableStrategyEvidenceStore(
        root,
        clock=_Clock(dt.datetime(2030, 4, 1, 14, 0, 6, tzinfo=UTC)),
    )

    def crash(_path):
        raise RuntimeError("simulated cross-set staged orphan")

    orphan_store._after_object_fsync = crash
    with pytest.raises(RuntimeError, match="cross-set staged orphan"):
        orphan_store.admit_checked(
            EvidenceCandidate(
                kind=STAGED_PAPER_INTENT_KIND,
                effective_at=orphan.effective_at,
                payload=orphan._evidence_payload(),
            ),
            validate=lambda _snapshot, _envelope: None,
        )

    ImmutableStrategyEvidenceStore(
        root,
        clock=_Clock(dt.datetime(2030, 4, 1, 14, 0, 7, tzinfo=UTC)),
    ).admit_checked(
        EvidenceCandidate(
            kind="baseline-genome",
            effective_at="2030-04-01T14:00:07+00:00",
            payload={"later_unrelated": True},
        ),
        validate=lambda _snapshot, _envelope: None,
    )
    before = _durable_file_bytes(root)

    with pytest.raises(ValueError, match="logical slot"):
        _stage_with_times(
            root,
            registration,
            evidence,
            clock_time=dt.datetime(
                2030,
                4,
                1,
                14,
                0,
                8,
                tzinfo=UTC,
            ),
            effective_at=dt.datetime(
                2030,
                4,
                1,
                14,
                0,
                tzinfo=UTC,
            ),
            expires_at=dt.datetime(
                2030,
                4,
                1,
                14,
                15,
                tzinfo=UTC,
            ),
            session_date="2030-04-02",
        )

    assert admitted.staged_intent_id != orphan.staged_intent_id
    assert _durable_file_bytes(root) == before


def test_prerequisite_malformed_staged_orphan_is_neutral(tmp_path):
    # Break caught: a domain-invalid staged orphan is parsed as durable intent
    # material and blocks an otherwise valid candidate.
    from tradingagents.strategy._immutable_evidence_store import (
        STAGED_PAPER_INTENT_KIND,
        EvidenceCandidate,
        ImmutableStrategyEvidenceStore,
    )

    root, registration, evidence = _durable_internal_evidence(tmp_path)
    malformed_payload = _staged_model_payload()
    malformed_payload["session_date"] = "not-a-session-date"
    malformed_store = ImmutableStrategyEvidenceStore(
        root,
        clock=_Clock(dt.datetime(2030, 4, 1, 14, 0, 4, tzinfo=UTC)),
    )

    def crash(_path):
        raise RuntimeError("simulated malformed staged orphan")

    malformed_store._after_object_fsync = crash
    with pytest.raises(RuntimeError, match="malformed staged orphan"):
        malformed_store.admit_checked(
            EvidenceCandidate(
                kind=STAGED_PAPER_INTENT_KIND,
                effective_at=malformed_payload["effective_at"],
                payload={
                    key: value
                    for key, value in malformed_payload.items()
                    if key
                    not in {
                        "staged_intent_id",
                        "effective_at",
                        "recorded_at",
                    }
                },
            ),
            validate=lambda _snapshot, _envelope: None,
        )

    _ledger, intent = _stage_once(
        root,
        registration,
        evidence,
        clock=_Clock(dt.datetime(2030, 4, 1, 14, 0, 5, tzinfo=UTC)),
    )

    assert intent.session_date == "2030-04-01"


def test_unrelated_slot_and_kind_orphans_are_neutral(tmp_path):
    # Break caught: orphan filtering blocks unrelated strategy evidence globally.
    from tradingagents.strategy import StrategyStagedIntentLedger
    from tradingagents.strategy._immutable_evidence_store import (
        EvidenceCandidate,
    )

    root, registration, evidence = _durable_internal_evidence(tmp_path)
    _crash_staged_intent_after_object_fsync(
        root,
        registration,
        evidence,
        session_date="2030-04-02",
    )
    ledger = StrategyStagedIntentLedger(
        root,
        repo_root=REPO_ROOT,
        clock=_Clock(dt.datetime(2030, 4, 1, 14, 0, 6, tzinfo=UTC)),
    )
    original = ledger._store._after_object_fsync

    def crash(_path):
        raise RuntimeError("simulated unrelated object crash")

    ledger._store._after_object_fsync = crash
    with pytest.raises(RuntimeError, match="unrelated object crash"):
        ledger._store.admit_checked(
            EvidenceCandidate(
                kind="baseline-genome",
                effective_at="2030-04-01T14:00:00+00:00",
                payload={"unrelated": True},
            ),
            validate=lambda _snapshot, _envelope: None,
        )
    ledger._store._after_object_fsync = original

    intent = ledger.stage(
        registration=registration,
        promotion_evidence=evidence,
        observations=_stage_observations(),
        candidate_state=_stage_candidate_state(),
        session_date="2030-04-01",
        market_session="regular",
        effective_at=dt.datetime(2030, 4, 1, 14, 0, tzinfo=UTC),
        expires_at=dt.datetime(2030, 4, 1, 14, 15, tzinfo=UTC),
    )

    assert intent.session_date == "2030-04-01"
    assert (root / "events.jsonl").read_bytes().count(b"\n") == 6


def test_event_fsync_crash_retry_repairs_without_duplicate_event(tmp_path):
    # Break caught: a visible staged event is duplicated during pointer recovery.
    from tradingagents.strategy import StrategyStagedIntentLedger

    root, registration, evidence = _durable_internal_evidence(tmp_path)
    ledger = StrategyStagedIntentLedger(
        root,
        repo_root=REPO_ROOT,
        clock=_Clock(dt.datetime(2030, 4, 1, 14, 0, 5, tzinfo=UTC)),
    )
    original = ledger._store._after_event_fsync

    def crash(_event):
        raise RuntimeError("simulated staged event fsync crash")

    ledger._store._after_event_fsync = crash
    with pytest.raises(RuntimeError, match="event fsync crash"):
        ledger.stage(
            registration=registration,
            promotion_evidence=evidence,
            observations=_stage_observations(),
            candidate_state=_stage_candidate_state(),
            session_date="2030-04-01",
            market_session="regular",
            effective_at=dt.datetime(2030, 4, 1, 14, 0, tzinfo=UTC),
            expires_at=dt.datetime(2030, 4, 1, 14, 15, tzinfo=UTC),
        )
    ledger._store._after_event_fsync = original
    before = (root / "events.jsonl").read_bytes()

    _repair_ledger, repaired = _stage_with_times(
        root,
        registration,
        evidence,
        clock_time=dt.datetime(2030, 4, 1, 14, 0, 10, tzinfo=UTC),
        effective_at=dt.datetime(2030, 4, 1, 14, 0, tzinfo=UTC),
        expires_at=dt.datetime(2030, 4, 1, 14, 15, tzinfo=UTC),
    )

    assert repaired.recorded_at == "2030-04-01T14:00:05+00:00"
    assert (root / "events.jsonl").read_bytes() == before


def test_staged_object_tamper_is_rejected_by_verify(tmp_path):
    # Break caught: changed staged payload bytes survive immutable-store replay.
    root, registration, evidence = _durable_internal_evidence(tmp_path)
    ledger, _intent = _stage_once(root, registration, evidence)
    object_path = next(
        (root / "objects" / "staged-paper-intent").glob("*.json")
    )
    payload = json.loads(object_path.read_bytes())
    payload["payload"]["observations"][0]["reason"] = "Tampered."
    object_path.write_bytes(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    )

    with pytest.raises(ValueError):
        ledger.verify()


def test_incomplete_internal_evidence_rejects_without_staged_event(tmp_path):
    # Break caught: durable failed learning evidence is promoted into paper meaning.
    root, registration, evidence = _durable_internal_evidence(
        tmp_path,
        observation_score=Decimal("0.1"),
        require_complete=False,
    )
    before = (root / "events.jsonl").read_bytes()

    with pytest.raises(ValueError, match="complete internal"):
        _stage_once(root, registration, evidence)

    assert (root / "events.jsonl").read_bytes() == before


@pytest.mark.parametrize("dependency", ("missing", "foreign"))
def test_missing_or_foreign_store_dependencies_reject_without_event(
    tmp_path,
    dependency,
):
    # Break caught: caller-owned evidence substitutes for event-admitted dependencies.
    (tmp_path / "source").mkdir()
    source_root, source_registration, source_evidence = (
        _durable_internal_evidence(tmp_path / "source")
    )
    if dependency == "missing":
        (tmp_path / "missing").mkdir()
        target_root = tmp_path / "missing" / "evidence"
    else:
        (tmp_path / "target").mkdir()
        target_root, _target_registration, _target_evidence = (
            _durable_internal_evidence(
                tmp_path / "target",
                genome_parent_id="foreign-baseline-root",
            )
        )
    before = (
        (target_root / "events.jsonl").read_bytes()
        if (target_root / "events.jsonl").exists()
        else None
    )

    with pytest.raises(ValueError, match="registration"):
        _stage_once(
            target_root,
            source_registration,
            source_evidence,
        )

    after = (
        (target_root / "events.jsonl").read_bytes()
        if (target_root / "events.jsonl").exists()
        else None
    )
    assert after == before
    assert source_root != target_root


def test_orphan_registration_never_satisfies_durable_dependency(tmp_path):
    # Break caught: a valid post-object-fsync orphan is treated as admitted lineage.
    from tradingagents.strategy import StrategyStagedIntentLedger
    from tradingagents.strategy._immutable_evidence_store import (
        EvidenceCandidate,
    )

    (tmp_path / "source").mkdir()
    _source_root, registration, evidence = _durable_internal_evidence(
        tmp_path / "source"
    )
    (tmp_path / "target").mkdir()
    target_root = tmp_path / "target" / "evidence"
    ledger = StrategyStagedIntentLedger(
        target_root,
        repo_root=REPO_ROOT,
        clock=_Clock(dt.datetime(2030, 4, 1, 14, 0, 5, tzinfo=UTC)),
    )
    original = ledger._store._after_object_fsync

    def crash(_path):
        raise RuntimeError("simulated registration object crash")

    ledger._store._after_object_fsync = crash
    with pytest.raises(RuntimeError, match="registration object crash"):
        ledger._store.admit_checked(
            EvidenceCandidate(
                kind="evaluation-registration",
                effective_at=registration.effective_at,
                payload=registration._evidence_payload(),
            ),
            validate=lambda _snapshot, _envelope: None,
        )
    ledger._store._after_object_fsync = original
    assert not (target_root / "events.jsonl").exists()

    with pytest.raises(ValueError, match="registration"):
        ledger.stage(
            registration=registration,
            promotion_evidence=evidence,
            observations=_stage_observations(),
            candidate_state=_stage_candidate_state(),
            session_date="2030-04-01",
            market_session="regular",
            effective_at=dt.datetime(2030, 4, 1, 14, 0, tzinfo=UTC),
            expires_at=dt.datetime(2030, 4, 1, 14, 15, tzinfo=UTC),
        )

    assert not (target_root / "events.jsonl").exists()


def test_prerequisite_orphan_promotion_never_satisfies_staged_dependency(
    tmp_path,
):
    # Break caught: strict-valid promotion object bytes without a journal event
    # satisfy the staged intent's durable promotion dependency.
    from tradingagents.strategy import StrategyStagedIntentLedger
    from tradingagents.strategy._immutable_evidence_store import (
        EvidenceCandidate,
        ImmutableStrategyEvidenceStore,
    )

    (tmp_path / "source").mkdir()
    source_root, registration, evidence = _durable_internal_evidence(
        tmp_path / "source"
    )
    source_snapshot = ImmutableStrategyEvidenceStore(source_root).verify()
    (tmp_path / "target").mkdir()
    target_root = tmp_path / "target" / "evidence"
    for envelope in source_snapshot:
        if envelope.object_id == evidence.evidence_id:
            continue
        ImmutableStrategyEvidenceStore(
            target_root,
            clock=lambda envelope=envelope: dt.datetime.fromisoformat(
                envelope.recorded_at
            ),
        ).admit_checked(
            EvidenceCandidate(
                kind=envelope.kind,
                effective_at=envelope.effective_at,
                payload=json.loads(envelope.canonical_json_bytes())["payload"],
            ),
            validate=lambda _snapshot, _envelope: None,
        )

    promotion_envelope = next(
        envelope
        for envelope in source_snapshot
        if envelope.object_id == evidence.evidence_id
    )
    promotion_store = ImmutableStrategyEvidenceStore(
        target_root,
        clock=_Clock(
            dt.datetime.fromisoformat(promotion_envelope.recorded_at)
        ),
    )

    def crash(_path):
        raise RuntimeError("simulated orphan promotion dependency")

    promotion_store._after_object_fsync = crash
    with pytest.raises(RuntimeError, match="orphan promotion dependency"):
        promotion_store.admit_checked(
            EvidenceCandidate(
                kind=promotion_envelope.kind,
                effective_at=promotion_envelope.effective_at,
                payload=json.loads(
                    promotion_envelope.canonical_json_bytes()
                )["payload"],
            ),
            validate=lambda _snapshot, _envelope: None,
        )
    before = _durable_file_bytes(target_root)
    ledger = StrategyStagedIntentLedger(
        target_root,
        repo_root=REPO_ROOT,
        clock=_Clock(dt.datetime(2030, 4, 1, 14, 0, 5, tzinfo=UTC)),
    )

    with pytest.raises(ValueError, match="promotion evidence"):
        ledger.stage(
            registration=registration,
            promotion_evidence=evidence,
            observations=_stage_observations(),
            candidate_state=_stage_candidate_state(),
            session_date="2030-04-01",
            market_session="regular",
            effective_at=dt.datetime(2030, 4, 1, 14, 0, tzinfo=UTC),
            expires_at=dt.datetime(2030, 4, 1, 14, 15, tzinfo=UTC),
        )

    assert _durable_file_bytes(target_root) == before
    assert not tuple(
        (target_root / "objects" / "staged-paper-intent").glob("*.json")
    )


def test_stage_preserves_caller_sequences_state_and_decimal_context(tmp_path):
    # Break caught: compiler replay mutates caller containers or Decimal flags.
    from tradingagents.strategy import compile_genome_paper_decision

    root, registration, evidence = _durable_internal_evidence(tmp_path)
    observations = _stage_observations()
    original_observations = tuple(observations)
    candidate_state = _stage_candidate_state()
    expected_decision = compile_genome_paper_decision(
        registration.genome,
        registration.evolution_policy,
        tuple(item.to_strategy_observation() for item in observations),
        candidate_state,
        market_session="regular",
    )

    with localcontext() as context:
        context.prec = 2
        flags_before = context.flags.copy()
        _ledger, intent = _stage_with_times(
            root,
            registration,
            evidence,
            clock_time=dt.datetime(2030, 4, 1, 14, 0, 5, tzinfo=UTC),
            effective_at=dt.datetime(2030, 4, 1, 14, 0, tzinfo=UTC),
            expires_at=dt.datetime(2030, 4, 1, 14, 15, tzinfo=UTC),
            observations=observations,
            candidate_state=candidate_state,
        )
        assert context.prec == 2
        assert context.flags == flags_before

    assert observations == list(original_observations)
    assert all(
        actual is original
        for actual, original in zip(
            observations,
            original_observations,
            strict=True,
        )
    )
    assert candidate_state == _stage_candidate_state()
    assert intent.observations == original_observations
    assert intent.decision.canonical_json_bytes() == (
        expected_decision.canonical_json_bytes()
    )


def test_nonstaged_tail_preserves_projection_slot_and_exact_retry(tmp_path):
    # Break caught: staged replay assumes the intent is the journal tail.
    from tradingagents.strategy._immutable_evidence_store import (
        EvidenceCandidate,
    )

    root, registration, evidence = _durable_internal_evidence(tmp_path)
    ledger, intent = _stage_once(root, registration, evidence)
    staged_event = (root / "events.jsonl").read_bytes().splitlines()[-1]
    ledger._store.admit_checked(
        EvidenceCandidate(
            kind="baseline-genome",
            effective_at="2030-04-01T14:00:06+00:00",
            payload={"tail": "unrelated"},
        ),
        validate=lambda _snapshot, _envelope: None,
    )
    with_tail = (root / "events.jsonl").read_bytes()

    assert ledger.verify() == (intent,)
    assert ledger.rebuild() == (intent,)
    assert with_tail.splitlines()[-2] == staged_event
    _retry_ledger, retried = _stage_with_times(
        root,
        registration,
        evidence,
        clock_time=dt.datetime(2030, 4, 1, 14, 0, 10, tzinfo=UTC),
        effective_at=dt.datetime(2030, 4, 1, 14, 0, tzinfo=UTC),
        expires_at=dt.datetime(2030, 4, 1, 14, 15, tzinfo=UTC),
    )
    assert retried == intent
    assert retried.recorded_at == intent.recorded_at
    assert (root / "events.jsonl").read_bytes() == with_tail
    with pytest.raises(ValueError, match="logical slot"):
        _stage_with_times(
            root,
            registration,
            evidence,
            clock_time=dt.datetime(2030, 4, 1, 14, 0, 11, tzinfo=UTC),
            effective_at=dt.datetime(2030, 4, 1, 14, 0, tzinfo=UTC),
            expires_at=dt.datetime(2030, 4, 1, 14, 14, 59, tzinfo=UTC),
        )


def _direct_store_replay_fixture(
    tmp_path,
    *,
    promotion_after_staged,
    duplicate_slot,
):
    from tradingagents.strategy import (
        StagedPaperIntent,
        StrategyPromotionEvidence,
        StrategyStagedIntentLedger,
    )
    from tradingagents.strategy._immutable_evidence_store import (
        EvidenceCandidate,
    )

    source_root, registration, evidence = _durable_internal_evidence(
        tmp_path / "source"
    )
    source_ledger, original_intent = _stage_once(
        source_root,
        registration,
        evidence,
    )
    source_snapshot = source_ledger._store.verify()
    registration_envelope = next(
        envelope
        for envelope in source_snapshot
        if envelope.object_id == registration.registration_id
    )
    window_envelopes = tuple(
        envelope
        for envelope in source_snapshot
        if envelope.kind == "genome-window"
    )
    promotion_envelope = next(
        envelope
        for envelope in source_snapshot
        if envelope.object_id == evidence.evidence_id
    )
    staged_envelope = next(
        envelope
        for envelope in source_snapshot
        if envelope.object_id == original_intent.staged_intent_id
    )
    prefix_clock_values = (
        dt.datetime(2029, 12, 31, 16, 0, tzinfo=UTC),
        dt.datetime(2030, 1, 22, 16, 1, tzinfo=UTC),
        dt.datetime(2030, 2, 22, 16, 1, tzinfo=UTC),
        dt.datetime(2030, 3, 22, 16, 1, tzinfo=UTC),
    )
    if promotion_after_staged:
        clock_values = (
            *prefix_clock_values,
            dt.datetime(2030, 4, 1, 14, 0, 5, tzinfo=UTC),
            dt.datetime(2030, 4, 1, 14, 0, 6, tzinfo=UTC),
        )
    else:
        clock_values = (
            *prefix_clock_values,
            dt.datetime(2030, 3, 22, 16, 2, tzinfo=UTC),
            dt.datetime(2030, 4, 1, 14, 0, 5, tzinfo=UTC),
            dt.datetime(2030, 4, 1, 14, 0, 6, tzinfo=UTC),
        )
    ledger = StrategyStagedIntentLedger(
        tmp_path / "target-evidence",
        repo_root=REPO_ROOT,
        clock=_Clock(*clock_values),
    )

    def admit_envelope(envelope):
        envelope_dict = json.loads(envelope.canonical_json_bytes())
        ledger._store.admit_checked(
            EvidenceCandidate(
                kind=envelope.kind,
                effective_at=envelope.effective_at,
                payload=envelope_dict["payload"],
            ),
            validate=lambda _snapshot, _candidate: None,
        )

    admit_envelope(registration_envelope)
    for envelope in window_envelopes:
        admit_envelope(envelope)
    if not promotion_after_staged:
        admit_envelope(promotion_envelope)
        admit_envelope(staged_envelope)
    else:
        future_promotion_payload = evidence.to_dict()
        future_promotion_payload["recorded_at"] = (
            "2030-04-01T14:00:06+00:00"
        )
        future_promotion = StrategyPromotionEvidence.from_dict(
            future_promotion_payload
        )
        future_bound_payload = original_intent.to_dict()
        future_bound_payload["promotion_evidence_sha256"] = hashlib.sha256(
            future_promotion.canonical_json_bytes()
        ).hexdigest()
        _reidentify_staged_payload(future_bound_payload)
        future_bound_intent = StagedPaperIntent.from_dict(
            future_bound_payload
        )
        ledger._store.admit_checked(
            EvidenceCandidate(
                kind="staged-paper-intent",
                effective_at=future_bound_intent.effective_at,
                payload=future_bound_intent._evidence_payload(),
            ),
            validate=lambda _snapshot, _candidate: None,
        )
    if promotion_after_staged:
        admit_envelope(promotion_envelope)

    changed_intent = None
    if duplicate_slot:
        changed_payload = original_intent.to_dict()
        changed_payload["expires_at"] = "2030-04-01T14:14:59+00:00"
        _reidentify_staged_payload(changed_payload)
        changed_intent = StagedPaperIntent.from_dict(changed_payload)
        ledger._store.admit_checked(
            EvidenceCandidate(
                kind="staged-paper-intent",
                effective_at=changed_intent.effective_at,
                payload=changed_intent._evidence_payload(),
            ),
            validate=lambda _snapshot, _candidate: None,
        )
    return ledger, original_intent, changed_intent


@pytest.mark.parametrize("operation", ("verify", "rebuild"))
def test_replay_rejects_promotion_dependency_appended_after_intent(
    tmp_path,
    operation,
):
    # Break caught: replay resolves staged dependencies from future journal events.
    (tmp_path / "source").mkdir()
    ledger, _intent, _changed = _direct_store_replay_fixture(
        tmp_path,
        promotion_after_staged=True,
        duplicate_slot=False,
    )

    with pytest.raises(ValueError, match="promotion evidence"):
        getattr(ledger, operation)()


@pytest.mark.parametrize("operation", ("verify", "rebuild"))
def test_replay_rejects_two_distinct_intents_for_one_logical_slot(
    tmp_path,
    operation,
):
    # Break caught: direct-store history preserves two meanings for one slot.
    (tmp_path / "source").mkdir()
    ledger, original, changed = _direct_store_replay_fixture(
        tmp_path,
        promotion_after_staged=False,
        duplicate_slot=True,
    )
    assert changed is not None
    assert changed.staged_intent_id != original.staged_intent_id

    with pytest.raises(ValueError, match="logical slot"):
        getattr(ledger, operation)()


@pytest.mark.parametrize(
    "session_date",
    ("2030-4-01", "2030-04-31", "2030-04-01T00:00:00"),
)
def test_session_date_rejects_noncanonical_or_impossible_syntax(session_date):
    # Break caught: the authoritative session label is normalized or loosely parsed.
    from tradingagents.strategy import StagedPaperIntent

    payload = _staged_model_payload()
    payload["session_date"] = session_date
    _reidentify_staged_payload(payload)

    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        StagedPaperIntent.from_dict(payload)


def _imported_modules(source):
    tree = ast.parse(source)
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imported.add(node.module)
    return imported


def _forbidden_import_violations(source):
    forbidden_prefixes = {
        "brokers",
        "execution",
        "live_control",
        "live_gate",
        "promotion_sync",
        "cli",
        "requests",
        "httpx",
        "openai",
        "anthropic",
        "tradingagents.brokers",
        "tradingagents.cli",
        "tradingagents.execution",
        "tradingagents.llm_clients",
        "tradingagents.policy.live_control",
        "tradingagents.policy.live_gate",
        "tradingagents.policy.promotion_sync",
    }
    imported = _imported_modules(source)
    return {
        imported_module
        for imported_module in imported
        for forbidden_prefix in forbidden_prefixes
        if imported_module == forbidden_prefix
        or imported_module.startswith(f"{forbidden_prefix}.")
    }


def test_import_guard_detects_fully_qualified_forbidden_paths():
    # Break caught: splitting only the first component hides TradingAgents imports.
    source = """
import tradingagents.brokers.adapter
from tradingagents.execution.orders import submit
from tradingagents.policy.live_gate import require_gate
from tradingagents.policy.promotion_sync import sync_promotion_state
"""

    assert _forbidden_import_violations(source) == {
        "tradingagents.brokers.adapter",
        "tradingagents.execution.orders",
        "tradingagents.policy.live_gate",
        "tradingagents.policy.promotion_sync",
    }


def test_staged_intent_import_and_call_isolation():
    # Break caught: evidence staging acquires execution, network, or model authority.
    source_path = REPO_ROOT / "tradingagents" / "strategy" / "staged_intent.py"
    source = source_path.read_text()
    tree = ast.parse(source)
    called_names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                called_names.add(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                called_names.add(node.func.attr)

    assert _forbidden_import_violations(source) == set()
    assert called_names.isdisjoint(
        {"submit_order", "cancel_order", "replace_order"}
    )


def test_staged_intent_forbidden_authority_literals_are_absent():
    # Break caught: dormant submission hooks enter the analysis-only module.
    tree = ast.parse(
        (
        REPO_ROOT / "tradingagents" / "strategy" / "staged_intent.py"
        ).read_text()
    )
    exact_tokens = {
        node.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Name)
    }
    exact_tokens.update(
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
    )
    exact_tokens.update(
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and type(node.value) is str
    )

    for forbidden in (
        "submit_order",
        "cancel_order",
        "replace_order",
        "TA_LIVE_SUBMIT",
        "authorized_normal_trade_intent",
    ):
        assert forbidden not in exact_tokens
