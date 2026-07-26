from __future__ import annotations

import ast
import dataclasses
import datetime as dt
import hashlib
import importlib
import inspect
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path

import pytest

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


def _calculation_repo(tmp_path: Path) -> tuple[Path, str]:
    from tradingagents.strategy.promotion_evidence import EVALUATION_SOURCE_PATHS

    repo = tmp_path / "calculation-repo"
    repo.mkdir()
    _run_git(repo, "init", "-q")
    _run_git(repo, "config", "user.email", "strategy-tests@example.invalid")
    _run_git(repo, "config", "user.name", "Strategy Tests")
    for path in EVALUATION_SOURCE_PATHS:
        target = repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(f"frozen calculation bytes: {path}\n".encode())
    _run_git(repo, "add", "--", *EVALUATION_SOURCE_PATHS)
    _run_git(repo, "commit", "-qm", "frozen calculation sources")
    return repo, _run_git(repo, "rev-parse", "HEAD")


def _policies():
    from tradingagents.strategy import (
        load_strategy_evaluation_policy,
        load_strategy_evolution_policy,
    )

    return (
        load_strategy_evolution_policy(REPO_ROOT / "config" / "strategy_evolution.json"),
        load_strategy_evaluation_policy(REPO_ROOT / "config" / "strategy_evaluation.json"),
    )


def _genome(*, generation: int = 1, parent_id: str = "baseline-root"):
    from tradingagents.strategy import (
        CurrentAggressiveParameters,
        StrategyFamily,
        StrategyGenome,
    )

    return StrategyGenome.create(
        family=StrategyFamily.CURRENT_AGGRESSIVE,
        parameters=CurrentAggressiveParameters(min_score="0.8"),
        generation=generation,
        parent_id=parent_id,
    )


def _frames_for_window(
    window,
    *,
    benchmark_step: Decimal = Decimal("0"),
    block_multiplier: Decimal = Decimal("1.1"),
    eligible: bool = True,
):
    from tradingagents.strategy.compiler import StrategyObservation
    from tradingagents.strategy.evaluator import EvaluationFrame, EvaluationMark

    start = dt.datetime.fromisoformat(window.first_effective_at)
    result = []
    for index in range(window.expected_tracked_sessions):
        block = index // 5
        price = Decimal("100") * (block_multiplier**block)
        benchmark = Decimal("100") + benchmark_step * index
        effective = start + dt.timedelta(days=index)
        observation = StrategyObservation(
            symbol="NFLX",
            score=Decimal("0.8") if eligible else Decimal("0.6"),
            current_price=price,
            daily_change_fraction=Decimal("-0.01"),
            volume_ratio=Decimal("1"),
            time_sensitive=True,
        )
        result.append(
            EvaluationFrame(
                session_date=effective.date(),
                effective_at=effective,
                recorded_at=effective + dt.timedelta(minutes=1),
                market_session="regular",
                observations=(observation,),
                marks=(EvaluationMark("NFLX", price),),
                benchmark_price=benchmark,
            )
        )
    return tuple(result)


def _evaluate_registered_window(registration, ordinal: int):
    from tradingagents.strategy.evaluator import evaluate_genome_window

    window = registration.windows[ordinal - 1]
    frames = _frames_for_window(window)
    result = evaluate_genome_window(
        registration.genome,
        registration.evolution_policy,
        registration.evaluation_policy,
        frames,
        evaluation_as_of=dt.datetime.fromisoformat(window.evaluation_as_of),
    )
    return frames, result


def _admit_all(
    ledger,
    registration,
    *,
    block_multiplier: Decimal = Decimal("1.1"),
    eligible: bool = True,
):
    from tradingagents.strategy.evaluator import evaluate_genome_window

    admitted = []
    for ordinal, window in enumerate(registration.windows, start=1):
        frames = _frames_for_window(
            window,
            block_multiplier=block_multiplier,
            eligible=eligible,
        )
        result = evaluate_genome_window(
            registration.genome,
            registration.evolution_policy,
            registration.evaluation_policy,
            frames,
            evaluation_as_of=dt.datetime.fromisoformat(window.evaluation_as_of),
        )
        admitted.append(
            ledger.admit_window(
                registration.registration_id,
                ordinal,
                frames,
                result,
            )
        )
    return tuple(admitted)


def _windows():
    from tradingagents.strategy.promotion_evidence import EvaluationWindowSpec

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


def _register(
    tmp_path: Path,
    *,
    clock: _Clock | None = None,
):
    from tradingagents.strategy.promotion_evidence import (
        StrategyPromotionEvidenceLedger,
    )

    repo, commit = _calculation_repo(tmp_path)
    evolution_policy, evaluation_policy = _policies()
    ledger = StrategyPromotionEvidenceLedger(
        tmp_path / "evidence",
        repo_root=repo,
        clock=clock or _Clock(dt.datetime(2029, 12, 31, 16, 0, tzinfo=UTC)),
    )
    registration = ledger.register(
        genome=_genome(),
        evolution_policy=evolution_policy,
        evaluation_policy=evaluation_policy,
        windows=_windows(),
        evaluation_code_commit=commit,
        effective_at=dt.datetime(2029, 12, 31, 15, 0, tzinfo=UTC),
    )
    return ledger, registration, repo, commit


def test_promotion_evidence_module_exists():
    module = importlib.import_module("tradingagents.strategy.promotion_evidence")

    assert module.__name__ == "tradingagents.strategy.promotion_evidence"


def test_evaluator_contract_preserves_task_6b_signature_and_schema():
    from tradingagents.strategy.evaluator import (
        GenomeWindowResult,
        evaluate_genome_window,
    )

    parameters = inspect.signature(evaluate_genome_window).parameters

    assert tuple(parameters) == (
        "genome",
        "evolution_policy",
        "evaluation_policy",
        "frames",
        "evaluation_as_of",
    )
    assert parameters["evaluation_as_of"].kind is inspect.Parameter.KEYWORD_ONLY
    assert "evaluation_code_commit" not in GenomeWindowResult.__dataclass_fields__
    assert "evaluation_runtime_sha256" not in (GenomeWindowResult.__dataclass_fields__)


def test_manifest_schema_paths_order_canonical_bytes_and_runtime_digest():
    from tradingagents.strategy.promotion_evidence import (
        EVALUATION_SOURCE_MANIFEST_SCHEMA_VERSION,
        EVALUATION_SOURCE_PATHS,
        EvaluationSourceFile,
        EvaluationSourceManifest,
    )

    digests = tuple(f"{index:064x}" for index in range(1, 6))
    manifest = EvaluationSourceManifest(files=tuple(EvaluationSourceFile(path=path, sha256=digest) for path, digest in zip(EVALUATION_SOURCE_PATHS, digests, strict=True)))

    assert EVALUATION_SOURCE_MANIFEST_SCHEMA_VERSION == 1
    assert EVALUATION_SOURCE_PATHS == (
        "tradingagents/strategy/compiler.py",
        "tradingagents/strategy/evaluator.py",
        "tradingagents/strategy/genome.py",
        "config/strategy_evolution.json",
        "config/strategy_evaluation.json",
    )
    assert manifest.to_dict() == {
        "schema_version": 1,
        "files": [
            {"path": path, "sha256": digest}
            for path, digest in zip(
                EVALUATION_SOURCE_PATHS,
                digests,
                strict=True,
            )
        ],
    }
    assert manifest.canonical_json_bytes() == (
        b'{"files":[{"path":"tradingagents/strategy/compiler.py",'
        b'"sha256":"' + digests[0].encode() + b'"},'
        b'{"path":"tradingagents/strategy/evaluator.py","sha256":"' + digests[1].encode() + b'"},'
        b'{"path":"tradingagents/strategy/genome.py","sha256":"' + digests[2].encode() + b'"},'
        b'{"path":"config/strategy_evolution.json","sha256":"' + digests[3].encode() + b'"},'
        b'{"path":"config/strategy_evaluation.json","sha256":"' + digests[4].encode() + b'"}],"schema_version":1}'
    )
    assert EvaluationSourceManifest.from_dict(manifest.to_dict()) == manifest


@pytest.mark.parametrize(
    "mutator",
    [
        lambda payload: {**payload, "extra": True},
        lambda payload: {**payload, "schema_version": 2},
        lambda payload: {**payload, "files": payload["files"][:-1]},
        lambda payload: {
            **payload,
            "files": list(reversed(payload["files"])),
        },
        lambda payload: {
            **payload,
            "files": [
                *payload["files"][:-1],
                {
                    "path": payload["files"][-1]["path"],
                    "sha256": "A" * 64,
                },
            ],
        },
    ],
)
def test_manifest_rejects_extra_missing_reordered_and_forged_material(mutator):
    from tradingagents.strategy.promotion_evidence import (
        EVALUATION_SOURCE_PATHS,
        EvaluationSourceFile,
        EvaluationSourceManifest,
    )

    manifest = EvaluationSourceManifest(files=tuple(EvaluationSourceFile(path=path, sha256=f"{index:064x}") for index, path in enumerate(EVALUATION_SOURCE_PATHS, start=1)))

    with pytest.raises((TypeError, ValueError)):
        EvaluationSourceManifest.from_dict(mutator(manifest.to_dict()))


def test_registration_binds_clean_commit_git_objects_manifest_and_identity(
    tmp_path,
):
    from tradingagents.strategy.promotion_evidence import (
        StrategyEvaluationRegistration,
    )

    _ledger, registration, repo, commit = _register(tmp_path)

    assert registration.evaluation_code_commit == commit
    assert registration.recorded_at == "2029-12-31T16:00:00+00:00"
    assert registration.effective_at == "2029-12-31T15:00:00+00:00"
    assert registration.evaluation_runtime_sha256 == hashlib.sha256(registration.evaluation_source_manifest.canonical_json_bytes()).hexdigest()
    assert registration.genome_canonical_sha256 == hashlib.sha256(registration.genome.canonical_json_bytes()).hexdigest()
    assert registration.evolution_policy_sha256 == hashlib.sha256(registration.evolution_policy.canonical_json_bytes()).hexdigest()
    assert registration.evaluation_policy_sha256 == hashlib.sha256(registration.evaluation_policy.canonical_json_bytes()).hexdigest()
    for source in registration.evaluation_source_manifest.files:
        assert source.sha256 == hashlib.sha256((repo / source.path).read_bytes()).hexdigest()
        git_bytes = subprocess.run(
            ("git", "show", f"{commit}:{source.path}"),
            cwd=repo,
            check=True,
            capture_output=True,
        ).stdout
        assert git_bytes == (repo / source.path).read_bytes()
    assert StrategyEvaluationRegistration.from_dict(registration.to_dict()) == registration
    assert StrategyEvaluationRegistration.from_dict(registration.to_dict()).canonical_json_bytes() == registration.canonical_json_bytes()

    durable = tmp_path / "evidence" / "objects" / "evaluation-registration" / f"{registration.registration_id}.json"
    envelope = __import__("json").loads(durable.read_bytes())
    assert envelope["object_id"] == registration.registration_id
    assert "registration_id" not in envelope["payload"]
    assert "effective_at" not in envelope["payload"]
    assert "recorded_at" not in envelope["payload"]


def test_registration_exact_retry_preserves_first_seen_time(tmp_path):
    from tradingagents.strategy.promotion_evidence import (
        StrategyPromotionEvidenceLedger,
    )

    clock = _Clock(
        dt.datetime(2029, 12, 31, 16, 0, tzinfo=UTC),
        dt.datetime(2030, 1, 1, 16, 0, tzinfo=UTC),
    )
    ledger, first, repo, commit = _register(tmp_path, clock=clock)
    evolution_policy, evaluation_policy = _policies()
    retry_ledger = StrategyPromotionEvidenceLedger(
        tmp_path / "evidence",
        repo_root=repo,
        clock=clock,
    )

    retried = retry_ledger.register(
        genome=_genome(),
        evolution_policy=evolution_policy,
        evaluation_policy=evaluation_policy,
        windows=_windows(),
        evaluation_code_commit=commit,
        effective_at=dt.datetime(2029, 12, 31, 15, 0, tzinfo=UTC),
    )

    assert retried == first
    assert ledger.verify() == ()
    assert (tmp_path / "evidence" / "events.jsonl").read_bytes().count(b"\n") == 1


@pytest.mark.parametrize(
    "commit_transform",
    [
        str.upper,
        lambda value: value[:-1],
        lambda _value: "z" * 40,
    ],
)
def test_registration_rejects_malformed_code_commit_without_event(
    tmp_path,
    commit_transform,
):
    from tradingagents.strategy.promotion_evidence import (
        StrategyPromotionEvidenceLedger,
    )

    repo, commit = _calculation_repo(tmp_path)
    evolution_policy, evaluation_policy = _policies()
    ledger = StrategyPromotionEvidenceLedger(
        tmp_path / "evidence",
        repo_root=repo,
        clock=_Clock(dt.datetime(2029, 12, 31, 16, 0, tzinfo=UTC)),
    )

    with pytest.raises((TypeError, ValueError)):
        ledger.register(
            genome=_genome(),
            evolution_policy=evolution_policy,
            evaluation_policy=evaluation_policy,
            windows=_windows(),
            evaluation_code_commit=commit_transform(commit),
            effective_at=dt.datetime(2029, 12, 31, 15, 0, tzinfo=UTC),
        )

    assert not (tmp_path / "evidence").exists()


def test_registration_rejects_dirty_head_and_git_object_byte_drift(tmp_path):
    from tradingagents.strategy.promotion_evidence import (
        EVALUATION_SOURCE_PATHS,
        StrategyPromotionEvidenceLedger,
    )

    repo, commit = _calculation_repo(tmp_path)
    evolution_policy, evaluation_policy = _policies()
    ledger = StrategyPromotionEvidenceLedger(
        tmp_path / "evidence",
        repo_root=repo,
        clock=_Clock(dt.datetime(2029, 12, 31, 16, 0, tzinfo=UTC)),
    )
    dirty_path = repo / EVALUATION_SOURCE_PATHS[0]
    dirty_path.write_bytes(b"dirty active bytes\n")

    with pytest.raises(ValueError, match="clean"):
        ledger.register(
            genome=_genome(),
            evolution_policy=evolution_policy,
            evaluation_policy=evaluation_policy,
            windows=_windows(),
            evaluation_code_commit=commit,
            effective_at=dt.datetime(2029, 12, 31, 15, 0, tzinfo=UTC),
        )
    assert not (tmp_path / "evidence").exists()

    _run_git(repo, "checkout", "--", EVALUATION_SOURCE_PATHS[0])
    _run_git(repo, "update-index", "--assume-unchanged", EVALUATION_SOURCE_PATHS[0])
    dirty_path.write_bytes(b"hidden active byte drift\n")
    assert _run_git(repo, "status", "--porcelain") == ""

    with pytest.raises(ValueError, match="Git object"):
        ledger.register(
            genome=_genome(),
            evolution_policy=evolution_policy,
            evaluation_policy=evaluation_policy,
            windows=_windows(),
            evaluation_code_commit=commit,
            effective_at=dt.datetime(2029, 12, 31, 15, 0, tzinfo=UTC),
        )
    assert not (tmp_path / "evidence").exists()


def test_registration_rejects_late_first_seen_and_invalid_schedule(tmp_path):
    from tradingagents.strategy.promotion_evidence import (
        EvaluationWindowSpec,
        StrategyPromotionEvidenceLedger,
    )

    repo, commit = _calculation_repo(tmp_path)
    evolution_policy, evaluation_policy = _policies()

    late = StrategyPromotionEvidenceLedger(
        tmp_path / "late-evidence",
        repo_root=repo,
        clock=_Clock(dt.datetime(2030, 1, 2, 15, 0, 1, tzinfo=UTC)),
    )
    with pytest.raises(ValueError, match="first window"):
        late.register(
            genome=_genome(),
            evolution_policy=evolution_policy,
            evaluation_policy=evaluation_policy,
            windows=_windows(),
            evaluation_code_commit=commit,
            effective_at=dt.datetime(2029, 12, 31, 15, 0, tzinfo=UTC),
        )
    assert not (tmp_path / "late-evidence" / "events.jsonl").exists()
    assert not list((tmp_path / "late-evidence").rglob("*.json"))

    low_capacity = tuple(dataclasses.replace(window, expected_tracked_sessions=6) for window in _windows())
    insufficient = StrategyPromotionEvidenceLedger(
        tmp_path / "insufficient-evidence",
        repo_root=repo,
        clock=_Clock(dt.datetime(2029, 12, 31, 16, 0, tzinfo=UTC)),
    )
    with pytest.raises(ValueError, match="closed trades"):
        insufficient.register(
            genome=_genome(),
            evolution_policy=evolution_policy,
            evaluation_policy=evaluation_policy,
            windows=low_capacity,
            evaluation_code_commit=commit,
            effective_at=dt.datetime(2029, 12, 31, 15, 0, tzinfo=UTC),
        )
    assert not (tmp_path / "insufficient-evidence").exists()

    overlapping = list(_windows())
    overlapping[1] = EvaluationWindowSpec(
        ordinal=2,
        window_start=overlapping[0].window_end,
        window_end="2030-02-22",
        first_effective_at="2030-01-22T16:00:00Z",
        last_effective_at="2030-02-22T15:00:00Z",
        evaluation_as_of="2030-02-22T16:00:00Z",
        expected_tracked_sessions=21,
    )
    overlap_ledger = StrategyPromotionEvidenceLedger(
        tmp_path / "overlap-evidence",
        repo_root=repo,
        clock=_Clock(dt.datetime(2029, 12, 31, 16, 0, tzinfo=UTC)),
    )
    with pytest.raises(ValueError, match="overlap"):
        overlap_ledger.register(
            genome=_genome(),
            evolution_policy=evolution_policy,
            evaluation_policy=evaluation_policy,
            windows=overlapping,
            evaluation_code_commit=commit,
            effective_at=dt.datetime(2029, 12, 31, 15, 0, tzinfo=UTC),
        )
    assert not (tmp_path / "overlap-evidence").exists()


def test_registration_accepts_exact_evaluator_capacity_and_rejects_one_above(
    tmp_path,
):
    from tradingagents.strategy.promotion_evidence import (
        StrategyPromotionEvidenceLedger,
    )

    repo, commit = _calculation_repo(tmp_path)
    evolution_policy, evaluation_policy = _policies()
    exact = tuple(dataclasses.replace(window, expected_tracked_sessions=206) for window in _windows())
    ledger = StrategyPromotionEvidenceLedger(
        tmp_path / "exact-evidence",
        repo_root=repo,
        clock=_Clock(dt.datetime(2029, 12, 31, 16, 0, tzinfo=UTC)),
    )
    registration = ledger.register(
        genome=_genome(),
        evolution_policy=evolution_policy,
        evaluation_policy=evaluation_policy,
        windows=exact,
        evaluation_code_commit=commit,
        effective_at=dt.datetime(2029, 12, 31, 15, 0, tzinfo=UTC),
    )
    assert registration.windows[0].expected_tracked_sessions == 206

    above = list(exact)
    above[0] = dataclasses.replace(
        above[0],
        expected_tracked_sessions=211,
    )
    rejected = StrategyPromotionEvidenceLedger(
        tmp_path / "above-evidence",
        repo_root=repo,
        clock=_Clock(dt.datetime(2029, 12, 31, 16, 0, tzinfo=UTC)),
    )
    with pytest.raises(ValueError, match="capacity"):
        rejected.register(
            genome=_genome(),
            evolution_policy=evolution_policy,
            evaluation_policy=evaluation_policy,
            windows=above,
            evaluation_code_commit=commit,
            effective_at=dt.datetime(2029, 12, 31, 15, 0, tzinfo=UTC),
        )
    assert not (tmp_path / "above-evidence").exists()


@pytest.mark.parametrize(
    "field_value",
    [
        "2030-01-22T16:00:00+00:00",
        "2030-01-22T16:00:00.000001Z",
        "2030-01-22T11:00:00-05:00",
    ],
)
def test_window_spec_rejects_noncanonical_evaluator_time_ambiguity(field_value):
    with pytest.raises((TypeError, ValueError)):
        dataclasses.replace(_windows()[0], evaluation_as_of=field_value)


@pytest.mark.parametrize(
    "field",
    [
        "genome",
        "evaluation_policy_sha256",
        "evaluator_version",
        "evaluation_runtime_sha256",
        "effective_at",
    ],
)
def test_registration_identity_rejects_coherent_reader_tamper(tmp_path, field):
    from tradingagents.strategy.promotion_evidence import (
        StrategyEvaluationRegistration,
    )

    _ledger, registration, _repo, _commit = _register(tmp_path)
    payload = registration.to_dict()
    if field == "genome":
        payload[field] = _genome(
            generation=2,
            parent_id="different-parent",
        ).to_dict()
        payload["genome_canonical_sha256"] = hashlib.sha256(
            __import__("json")
            .dumps(
                payload[field],
                sort_keys=True,
                separators=(",", ":"),
            )
            .encode()
        ).hexdigest()
    elif field == "effective_at":
        payload[field] = "2029-12-31T14:59:59+00:00"
    elif field == "evaluator_version":
        payload[field] = "strategy-evaluator-v2"
    else:
        payload[field] = "f" * 64

    with pytest.raises(ValueError):
        StrategyEvaluationRegistration.from_dict(payload)


def test_window_admission_binds_exact_frames_result_commit_runtime_and_replay(
    tmp_path,
):
    from tradingagents.strategy.promotion_evidence import AdmittedGenomeWindow

    ledger, registration, _repo, _commit = _register(
        tmp_path,
        clock=_Clock(
            dt.datetime(2029, 12, 31, 16, 0, tzinfo=UTC),
            dt.datetime(2030, 1, 22, 16, 1, tzinfo=UTC),
            dt.datetime(2030, 1, 23, 16, 1, tzinfo=UTC),
        ),
    )
    frames, result = _evaluate_registered_window(registration, 1)

    admitted = ledger.admit_window(
        registration.registration_id,
        1,
        frames,
        result,
    )

    assert admitted.registration_id == registration.registration_id
    assert admitted.evaluation_code_commit == registration.evaluation_code_commit
    assert admitted.evaluation_runtime_sha256 == registration.evaluation_runtime_sha256
    assert admitted.ordinal == 1
    assert admitted.window_id == result.window_id
    assert admitted.result_sha256 == hashlib.sha256(result.canonical_json_bytes()).hexdigest()
    assert admitted.input_frames == frames
    assert admitted.result == result
    assert admitted.effective_at == "2030-01-22T16:00:00+00:00"
    assert admitted.result.evaluation_as_of == "2030-01-22T16:00:00Z"
    assert admitted.recorded_at == "2030-01-22T16:01:00+00:00"
    assert AdmittedGenomeWindow.from_dict(admitted.to_dict()) == admitted
    assert AdmittedGenomeWindow.from_dict(admitted.to_dict()).canonical_json_bytes() == admitted.canonical_json_bytes()

    durable = tmp_path / "evidence" / "objects" / "genome-window" / f"{admitted.admitted_window_id}.json"
    envelope = __import__("json").loads(durable.read_bytes())
    assert envelope["payload"]["input_frames"] == [frame.to_dict() for frame in frames]
    assert "admitted_window_id" not in envelope["payload"]
    assert "effective_at" not in envelope["payload"]
    assert "recorded_at" not in envelope["payload"]

    retried = ledger.admit_window(
        registration.registration_id,
        1,
        frames,
        result,
    )
    assert retried == admitted
    assert (tmp_path / "evidence" / "events.jsonl").read_bytes().count(b"\n") == 2


def test_window_admission_is_next_ordinal_only_and_rejects_claimed_result(
    tmp_path,
):
    ledger, registration, _repo, _commit = _register(
        tmp_path,
        clock=_Clock(
            dt.datetime(2029, 12, 31, 16, 0, tzinfo=UTC),
            dt.datetime(2030, 2, 22, 16, 1, tzinfo=UTC),
        ),
    )
    frames2, result2 = _evaluate_registered_window(registration, 2)

    with pytest.raises(ValueError, match="next ordinal"):
        ledger.admit_window(
            registration.registration_id,
            2,
            frames2,
            result2,
        )
    assert (tmp_path / "evidence" / "events.jsonl").read_bytes().count(b"\n") == 1

    frames1, result1 = _evaluate_registered_window(registration, 1)
    wrong_frames = list(frames1)
    wrong_frames[-1] = dataclasses.replace(
        wrong_frames[-1],
        benchmark_price=Decimal("101"),
    )
    with pytest.raises(ValueError, match="frame"):
        ledger.admit_window(
            registration.registration_id,
            1,
            wrong_frames,
            result1,
        )
    assert (tmp_path / "evidence" / "events.jsonl").read_bytes().count(b"\n") == 1


def test_window_allows_unrelated_descendant_head_but_rejects_source_drift(
    tmp_path,
):
    from tradingagents.strategy.promotion_evidence import EVALUATION_SOURCE_PATHS

    ledger, registration, repo, _commit = _register(
        tmp_path,
        clock=_Clock(
            dt.datetime(2029, 12, 31, 16, 0, tzinfo=UTC),
            dt.datetime(2030, 1, 22, 16, 1, tzinfo=UTC),
            dt.datetime(2030, 2, 22, 16, 1, tzinfo=UTC),
        ),
    )
    unrelated = repo / "README.md"
    unrelated.write_text("unrelated descendant\n", encoding="utf-8")
    _run_git(repo, "add", "README.md")
    _run_git(repo, "commit", "-qm", "unrelated descendant")
    assert _run_git(repo, "rev-parse", "HEAD") != registration.evaluation_code_commit

    frames1, result1 = _evaluate_registered_window(registration, 1)
    admitted = ledger.admit_window(
        registration.registration_id,
        1,
        frames1,
        result1,
    )
    assert admitted.ordinal == 1

    drifted = repo / EVALUATION_SOURCE_PATHS[1]
    drifted.write_bytes(drifted.read_bytes() + b"drift\n")
    frames2, result2 = _evaluate_registered_window(registration, 2)
    with pytest.raises(ValueError, match="manifest"):
        ledger.admit_window(
            registration.registration_id,
            2,
            frames2,
            result2,
        )
    assert (tmp_path / "evidence" / "events.jsonl").read_bytes().count(b"\n") == 2


def test_window_backdating_fails_without_new_event(tmp_path):
    from tradingagents.strategy._immutable_evidence_store import (
        EvidenceBackdatingError,
    )

    ledger, registration, _repo, _commit = _register(
        tmp_path,
        clock=_Clock(
            dt.datetime(2029, 12, 31, 16, 0, tzinfo=UTC),
            dt.datetime(2029, 12, 30, 16, 0, tzinfo=UTC),
        ),
    )
    frames, result = _evaluate_registered_window(registration, 1)

    with pytest.raises(EvidenceBackdatingError):
        ledger.admit_window(
            registration.registration_id,
            1,
            frames,
            result,
        )

    assert (tmp_path / "evidence" / "events.jsonl").read_bytes().count(b"\n") == 1


def test_concurrent_conflicting_next_window_writers_commit_only_one(tmp_path):
    ledger, registration, _repo, _commit = _register(
        tmp_path,
        clock=_Clock(
            dt.datetime(2029, 12, 31, 16, 0, tzinfo=UTC),
            dt.datetime(2030, 1, 22, 16, 1, tzinfo=UTC),
        ),
    )
    from tradingagents.strategy.evaluator import evaluate_genome_window

    spec = registration.windows[0]
    frames_a = _frames_for_window(spec, block_multiplier=Decimal("1.1"))
    frames_b = _frames_for_window(spec, block_multiplier=Decimal("1.05"))
    result_a = evaluate_genome_window(
        registration.genome,
        registration.evolution_policy,
        registration.evaluation_policy,
        frames_a,
        evaluation_as_of=dt.datetime.fromisoformat(spec.evaluation_as_of),
    )
    result_b = evaluate_genome_window(
        registration.genome,
        registration.evolution_policy,
        registration.evaluation_policy,
        frames_b,
        evaluation_as_of=dt.datetime.fromisoformat(spec.evaluation_as_of),
    )

    def admit(material):
        frames, result = material
        try:
            return ledger.admit_window(
                registration.registration_id,
                1,
                frames,
                result,
            )
        except ValueError as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = tuple(pool.map(admit, ((frames_a, result_a), (frames_b, result_b))))

    successes = tuple(outcome for outcome in outcomes if not isinstance(outcome, BaseException))
    failures = tuple(outcome for outcome in outcomes if isinstance(outcome, BaseException))
    assert len(successes) == 1
    assert len(failures) == 1
    assert "conflicting window ordinal" in str(failures[0])
    assert (tmp_path / "evidence" / "events.jsonl").read_bytes().count(b"\n") == 2


def test_store_callbacks_perform_zero_git_file_or_evaluator_io(
    tmp_path,
    monkeypatch,
):
    import tradingagents.strategy.promotion_evidence as module

    repo, commit = _calculation_repo(tmp_path)
    evolution_policy, evaluation_policy = _policies()
    ledger = module.StrategyPromotionEvidenceLedger(
        tmp_path / "evidence",
        repo_root=repo,
        clock=_Clock(
            dt.datetime(2029, 12, 31, 16, 0, tzinfo=UTC),
            dt.datetime(2030, 1, 22, 16, 1, tzinfo=UTC),
            dt.datetime(2030, 2, 22, 16, 1, tzinfo=UTC),
            dt.datetime(2030, 3, 22, 16, 1, tzinfo=UTC),
            dt.datetime(2030, 3, 22, 16, 2, tzinfo=UTC),
        ),
    )
    state = {"callback_active": False}
    original_admit = ledger._store.admit_checked

    def guarded_admit(candidate, *, validate):
        def guarded_validate(snapshot, envelope):
            state["callback_active"] = True
            try:
                return validate(snapshot, envelope)
            finally:
                state["callback_active"] = False

        return original_admit(candidate, validate=guarded_validate)

    monkeypatch.setattr(ledger._store, "admit_checked", guarded_admit)
    for name in (
        "_active_source_snapshot",
        "_git_text",
        "_git_bytes",
        "evaluate_genome_window",
    ):
        original = getattr(module, name)

        def guarded(*args, _original=original, _name=name, **kwargs):
            assert state["callback_active"] is False, f"{_name} ran inside store callback"
            return _original(*args, **kwargs)

        monkeypatch.setattr(module, name, guarded)

    registration = ledger.register(
        genome=_genome(),
        evolution_policy=evolution_policy,
        evaluation_policy=evaluation_policy,
        windows=_windows(),
        evaluation_code_commit=commit,
        effective_at=dt.datetime(2029, 12, 31, 15, 0, tzinfo=UTC),
    )
    _admit_all(ledger, registration)
    evidence = ledger.assemble(registration.registration_id)

    assert evidence.complete_internal_evidence is True
    assert state["callback_active"] is False


def test_aggregate_pools_reset_cash_exactly_and_orders_all_six_gates(tmp_path):
    from tradingagents.strategy.promotion_evidence import (
        StrategyPromotionEvidence,
    )

    ledger, registration, _repo, _commit = _register(
        tmp_path,
        clock=_Clock(
            dt.datetime(2029, 12, 31, 16, 0, tzinfo=UTC),
            dt.datetime(2030, 1, 22, 16, 1, tzinfo=UTC),
            dt.datetime(2030, 2, 22, 16, 1, tzinfo=UTC),
            dt.datetime(2030, 3, 22, 16, 1, tzinfo=UTC),
            dt.datetime(2030, 3, 22, 16, 2, tzinfo=UTC),
        ),
    )
    admitted = _admit_all(ledger, registration)

    evidence = ledger.assemble(registration.registration_id)

    assert evidence.registration_id == registration.registration_id
    assert evidence.evaluation_code_commit == registration.evaluation_code_commit
    assert evidence.evaluation_runtime_sha256 == registration.evaluation_runtime_sha256
    assert evidence.genome_id == registration.genome.genome_id
    assert evidence.genome_canonical_sha256 == registration.genome_canonical_sha256
    assert evidence.admitted_window_ids == tuple(item.admitted_window_id for item in admitted)
    assert evidence.result_sha256s == tuple(item.result_sha256 for item in admitted)
    assert evidence.total_windows == 3
    assert evidence.total_tracked_sessions == 63
    assert evidence.total_closed_trades == 12
    assert evidence.total_winning_trades == 12
    assert evidence.total_false_positives == 0
    assert evidence.pooled_starting_cash_usd == "600"
    assert evidence.pooled_ending_equity_usd == ("871.45379912699999999999999999999999999999999999997")
    assert evidence.pooled_net_return_fraction == ("0.45242299854499999999999999999999999999999999999995")
    assert evidence.pooled_benchmark_return_fraction == "0"
    assert evidence.pooled_benchmark_excess_fraction == ("0.45242299854499999999999999999999999999999999999995")
    assert evidence.latest_window_net_return_fraction == "0.452422998545"
    assert evidence.latest_window_benchmark_excess_fraction == "0.452422998545"
    assert evidence.worst_max_drawdown_fraction == "-0.001999"
    assert evidence.gates == (
        ("minimum_closed_trades", True),
        ("maximum_drawdown_within_policy", True),
        ("pooled_net_return_positive", True),
        ("pooled_benchmark_excess_positive", True),
        ("latest_window_net_return_positive", True),
        ("latest_window_benchmark_excess_positive", True),
    )
    assert evidence.issues == ()
    assert evidence.complete_internal_evidence is True
    assert evidence.paper_only is True
    assert evidence.execution_authority == "none"
    assert evidence.can_submit_orders is False
    assert evidence.effective_at == "2030-03-22T16:00:00+00:00"
    assert evidence.recorded_at == "2030-03-22T16:02:00+00:00"
    assert StrategyPromotionEvidence.from_dict(evidence.to_dict()) == evidence
    assert StrategyPromotionEvidence.from_dict(evidence.to_dict()).canonical_json_bytes() == evidence.canonical_json_bytes()


def test_aggregate_missing_windows_rejects_without_evidence_event(tmp_path):
    ledger, registration, _repo, _commit = _register(
        tmp_path,
        clock=_Clock(
            dt.datetime(2029, 12, 31, 16, 0, tzinfo=UTC),
            dt.datetime(2030, 1, 22, 16, 1, tzinfo=UTC),
        ),
    )
    frames, result = _evaluate_registered_window(registration, 1)
    ledger.admit_window(registration.registration_id, 1, frames, result)

    with pytest.raises(ValueError, match="complete"):
        ledger.assemble(registration.registration_id)

    assert (tmp_path / "evidence" / "events.jsonl").read_bytes().count(b"\n") == 2


@pytest.mark.parametrize(
    ("case_name", "block_multiplier", "eligible", "failed_gates"),
    [
        (
            "no-trades",
            Decimal("1.1"),
            False,
            {
                "minimum_closed_trades",
                "pooled_net_return_positive",
                "pooled_benchmark_excess_positive",
                "latest_window_net_return_positive",
                "latest_window_benchmark_excess_positive",
            },
        ),
        (
            "losses",
            Decimal("0.8"),
            True,
            {
                "maximum_drawdown_within_policy",
                "pooled_net_return_positive",
                "pooled_benchmark_excess_positive",
                "latest_window_net_return_positive",
                "latest_window_benchmark_excess_positive",
            },
        ),
    ],
)
def test_each_reachable_gate_can_fail_into_durable_paper_learning_evidence(
    tmp_path,
    case_name,
    block_multiplier,
    eligible,
    failed_gates,
):
    case_root = tmp_path / case_name
    case_root.mkdir()
    ledger, registration, _repo, _commit = _register(
        case_root,
        clock=_Clock(
            dt.datetime(2029, 12, 31, 16, 0, tzinfo=UTC),
            dt.datetime(2030, 1, 22, 16, 1, tzinfo=UTC),
            dt.datetime(2030, 2, 22, 16, 1, tzinfo=UTC),
            dt.datetime(2030, 3, 22, 16, 1, tzinfo=UTC),
            dt.datetime(2030, 3, 22, 16, 2, tzinfo=UTC),
        ),
    )
    _admit_all(
        ledger,
        registration,
        block_multiplier=block_multiplier,
        eligible=eligible,
    )

    evidence = ledger.assemble(registration.registration_id)
    observed_failed = {name for name, passed in evidence.gates if not passed}

    assert failed_gates <= observed_failed
    assert evidence.issues == tuple(name for name, passed in evidence.gates if not passed)
    assert evidence.complete_internal_evidence is False
    assert evidence.paper_only is True
    assert evidence.analysis_only is True
    assert evidence.execution_authority == "none"
    assert evidence.can_submit_orders is False
    assert (case_root / "evidence" / "objects" / "promotion-evidence" / f"{evidence.evidence_id}.json").is_file()


@pytest.mark.parametrize("source_index", range(5))
def test_every_calculation_source_drift_makes_registration_inert_on_verify(
    tmp_path,
    source_index,
):
    from tradingagents.strategy.promotion_evidence import EVALUATION_SOURCE_PATHS

    ledger, _registration, repo, _commit = _register(tmp_path)
    source = repo / EVALUATION_SOURCE_PATHS[source_index]
    source.write_bytes(source.read_bytes() + b"drift\n")

    with pytest.raises(ValueError, match="manifest"):
        ledger.verify()


def test_manifest_drift_blocks_assembly_verify_and_rebuild_without_event(
    tmp_path,
):
    from tradingagents.strategy.promotion_evidence import EVALUATION_SOURCE_PATHS

    ledger, registration, repo, _commit = _register(
        tmp_path,
        clock=_Clock(
            dt.datetime(2029, 12, 31, 16, 0, tzinfo=UTC),
            dt.datetime(2030, 1, 22, 16, 1, tzinfo=UTC),
            dt.datetime(2030, 2, 22, 16, 1, tzinfo=UTC),
            dt.datetime(2030, 3, 22, 16, 1, tzinfo=UTC),
        ),
    )
    _admit_all(ledger, registration)
    before = (tmp_path / "evidence" / "events.jsonl").read_bytes()
    source = repo / EVALUATION_SOURCE_PATHS[3]
    source.write_bytes(source.read_bytes() + b"drift\n")

    with pytest.raises(ValueError, match="manifest"):
        ledger.assemble(registration.registration_id)
    with pytest.raises(ValueError, match="manifest"):
        ledger.verify()
    with pytest.raises(ValueError, match="manifest"):
        ledger.rebuild()

    assert (tmp_path / "evidence" / "events.jsonl").read_bytes() == before


def test_crash_after_window_event_is_exactly_repairable_without_duplicate(
    tmp_path,
):
    ledger, registration, _repo, _commit = _register(
        tmp_path,
        clock=_Clock(
            dt.datetime(2029, 12, 31, 16, 0, tzinfo=UTC),
            dt.datetime(2030, 1, 22, 16, 1, tzinfo=UTC),
        ),
    )
    frames, result = _evaluate_registered_window(registration, 1)
    original = ledger._store._after_event_fsync

    def crash(_event):
        raise RuntimeError("simulated post-event crash")

    ledger._store._after_event_fsync = crash
    with pytest.raises(RuntimeError, match="post-event crash"):
        ledger.admit_window(
            registration.registration_id,
            1,
            frames,
            result,
        )
    ledger._store._after_event_fsync = original

    repaired = ledger.admit_window(
        registration.registration_id,
        1,
        frames,
        result,
    )

    assert repaired.ordinal == 1
    assert (tmp_path / "evidence" / "events.jsonl").read_bytes().count(b"\n") == 2
    assert not list((tmp_path / "evidence" / "latest").glob(".*.tmp"))


def test_verify_rejects_valid_window_without_durable_registration(tmp_path):
    from tradingagents.strategy._immutable_evidence_store import EvidenceCandidate
    from tradingagents.strategy.promotion_evidence import (
        StrategyPromotionEvidenceLedger,
    )

    source, registration, repo, _commit = _register(
        tmp_path,
        clock=_Clock(
            dt.datetime(2029, 12, 31, 16, 0, tzinfo=UTC),
            dt.datetime(2030, 1, 22, 16, 1, tzinfo=UTC),
        ),
    )
    frames, result = _evaluate_registered_window(registration, 1)
    admitted = source.admit_window(
        registration.registration_id,
        1,
        frames,
        result,
    )
    target = StrategyPromotionEvidenceLedger(
        tmp_path / "orphan-evidence",
        repo_root=repo,
        clock=_Clock(dt.datetime(2030, 1, 22, 16, 1, tzinfo=UTC)),
    )
    target._store.admit_checked(
        EvidenceCandidate(
            kind="genome-window",
            effective_at=admitted.effective_at,
            payload=admitted._evidence_payload(),
        ),
        validate=lambda _snapshot, _envelope: None,
    )

    with pytest.raises(ValueError, match="registration"):
        target.verify()


def test_legacy_percentage_point_and_tournament_shapes_are_rejected(tmp_path):
    ledger, registration, _repo, _commit = _register(tmp_path)
    _frames, result = _evaluate_registered_window(registration, 1)
    legacy_rows = [
        {
            "ticker": "NFLX",
            "return_pct": 10,
            "drawdown_pct": -5,
        }
    ]

    with pytest.raises(TypeError, match="EvaluationFrame"):
        ledger.admit_window(
            registration.registration_id,
            1,
            legacy_rows,
            result,
        )
    assert (tmp_path / "evidence" / "events.jsonl").read_bytes().count(b"\n") == 1


def test_public_exports_are_analysis_only_and_frozen(tmp_path):
    from tradingagents.strategy import (
        ADMITTED_GENOME_WINDOW_SCHEMA_VERSION,
        EVALUATION_SOURCE_MANIFEST_SCHEMA_VERSION,
        EVALUATION_WINDOW_SPEC_SCHEMA_VERSION,
        STRATEGY_EVALUATION_REGISTRATION_SCHEMA_VERSION,
        STRATEGY_PROMOTION_EVIDENCE_SCHEMA_VERSION,
        EvaluationSourceFile,
        EvaluationSourceManifest,
        EvaluationWindowSpec,
        StrategyEvaluationRegistration,
        StrategyPromotionEvidence,
        StrategyPromotionEvidenceLedger,
    )

    ledger, registration, _repo, _commit = _register(tmp_path)

    assert EVALUATION_WINDOW_SPEC_SCHEMA_VERSION == 1
    assert EVALUATION_SOURCE_MANIFEST_SCHEMA_VERSION == 1
    assert STRATEGY_EVALUATION_REGISTRATION_SCHEMA_VERSION == 1
    assert ADMITTED_GENOME_WINDOW_SCHEMA_VERSION == 1
    assert STRATEGY_PROMOTION_EVIDENCE_SCHEMA_VERSION == 1
    assert isinstance(ledger, StrategyPromotionEvidenceLedger)
    assert isinstance(registration, StrategyEvaluationRegistration)
    assert EvaluationSourceFile is not None
    assert EvaluationSourceManifest is not None
    assert EvaluationWindowSpec is not None
    assert StrategyPromotionEvidence is not None
    assert registration.analysis_only is True
    assert registration.execution_authority == "none"
    assert registration.can_submit_orders is False
    with pytest.raises(dataclasses.FrozenInstanceError):
        registration.recorded_at = "changed"  # type: ignore[misc]


def test_ast_import_isolation_and_zero_execution_authority_surfaces():
    module_path = REPO_ROOT / "tradingagents" / "strategy" / "promotion_evidence.py"
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    imported_modules = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module is not None}
    imported_modules.update(alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names)

    allowed_internal = {
        "tradingagents.strategy.genome",
        "tradingagents.strategy.evaluator",
        "tradingagents.strategy._immutable_evidence_store",
    }
    assert {name for name in imported_modules if name.startswith("tradingagents.")} <= allowed_internal
    assert not any(
        name.startswith(
            (
                "tradingagents.policy",
                "tradingagents.brokers",
                "tradingagents.execution",
                "tradingagents.graph",
                "tradingagents.orchestration",
            )
        )
        for name in imported_modules
    )
    public_methods = {node.name for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith("_")}
    assert not public_methods & {
        "submit",
        "approve",
        "promote",
        "rearm",
        "change_live_control",
    }
