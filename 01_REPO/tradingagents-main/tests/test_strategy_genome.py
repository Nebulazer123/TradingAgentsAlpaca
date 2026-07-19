from __future__ import annotations

import ast
import dataclasses
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from tradingagents.strategy import (
    STRATEGY_EVOLUTION_POLICY_SCHEMA_VERSION,
    STRATEGY_GENOME_SCHEMA_VERSION,
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
    load_strategy_evolution_policy,
)

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "config" / "strategy_evolution.json"


def _genome(
    family: StrategyFamily = StrategyFamily.CURRENT_AGGRESSIVE,
    parameters: (
        HoldCashParameters
        | CurrentAggressiveParameters
        | PullbackSupportParameters
        | CatalystRelativeStrengthParameters
        | None
    ) = None,
    *,
    generation: int = 0,
    parent_id: str = "builtin-baseline",
) -> StrategyGenome:
    if parameters is None:
        parameters = CurrentAggressiveParameters("0.7")
    return StrategyGenome.create(
        family=family,
        parameters=parameters,
        generation=generation,
        parent_id=parent_id,
    )


def _policy_payload() -> dict[str, Any]:
    return json.loads(POLICY_PATH.read_text(encoding="utf-8"))


def _write_policy(tmp_path: Path, payload: dict[str, Any]) -> Path:
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


@pytest.mark.parametrize(
    ("family", "parameters", "serialized"),
    [
        (StrategyFamily.HOLD_CASH, HoldCashParameters(), {}),
        (
            StrategyFamily.CURRENT_AGGRESSIVE,
            CurrentAggressiveParameters("0.70"),
            {"min_score": "0.7"},
        ),
        (
            StrategyFamily.PULLBACK_SUPPORT,
            PullbackSupportParameters("-0.025", "-0.003", "1.50"),
            {
                "min_daily_change_fraction": "-0.025",
                "max_daily_change_fraction": "-0.003",
                "max_volume_ratio": "1.5",
            },
        ),
        (
            StrategyFamily.CATALYST_RELATIVE_STRENGTH,
            CatalystRelativeStrengthParameters("0.75"),
            {"min_score": "0.75"},
        ),
    ],
)
def test_exact_family_construction_and_round_trip(
    family: StrategyFamily,
    parameters: object,
    serialized: dict[str, str],
) -> None:
    genome = StrategyGenome.create(
        family=family.value,
        parameters=parameters,
        generation=7,
        parent_id="baseline.v1",
    )

    assert genome.family is family
    assert genome.to_dict() == {
        "schema_version": 1,
        "family": family.value,
        "parameters": serialized,
        "generation": 7,
        "parent_id": "baseline.v1",
        "genome_id": genome.genome_id,
        "analysis_only": True,
        "execution_authority": "none",
        "can_submit_orders": False,
    }
    assert StrategyGenome.from_dict(genome.to_dict()) == genome
    assert json.loads(genome.canonical_json_bytes()) == genome.to_dict()


def test_canonical_decimal_equivalence_and_semantic_identity() -> None:
    left = _genome(parameters=CurrentAggressiveParameters("0.70"))
    right = _genome(parameters=CurrentAggressiveParameters("0.7000"))

    assert left.parameters.min_score == "0.7"
    assert left.identity_json_bytes() == (
        b'{"family":"current-aggressive","parameters":{"min_score":"0.7"},'
        b'"schema_version":1}'
    )
    assert left.genome_id == right.genome_id
    digest = hashlib.sha256(left.identity_json_bytes()).hexdigest()
    assert left.genome_id == f"genome-current-aggressive-{digest}"


def test_lineage_changes_do_not_change_semantic_identity() -> None:
    first = _genome(generation=0, parent_id="baseline")
    descendant = _genome(generation=999, parent_id="genome-parent_2")

    assert first.genome_id == descendant.genome_id
    assert first.canonical_json_bytes() != descendant.canonical_json_bytes()


def test_parameter_change_changes_semantic_identity() -> None:
    assert _genome(parameters=CurrentAggressiveParameters("0.70")).genome_id != _genome(
        parameters=CurrentAggressiveParameters("0.71")
    ).genome_id


@pytest.mark.parametrize("value", ["0.50", "1.00"])
def test_score_boundaries_are_inclusive(value: str) -> None:
    assert CurrentAggressiveParameters(value).min_score in {"0.5", "1"}
    assert CatalystRelativeStrengthParameters(value).min_score in {"0.5", "1"}


@pytest.mark.parametrize("value", ["0.499999", "1.000001"])
def test_score_just_outside_bounds_is_rejected(value: str) -> None:
    with pytest.raises(ValueError):
        CurrentAggressiveParameters(value)
    with pytest.raises(ValueError):
        CatalystRelativeStrengthParameters(value)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("min_daily_change_fraction", "-0.20"),
        ("min_daily_change_fraction", "0"),
        ("max_daily_change_fraction", "-0.20"),
        ("max_daily_change_fraction", "0.05"),
        ("max_volume_ratio", "0.10"),
        ("max_volume_ratio", "10"),
    ],
)
def test_pullback_numeric_boundaries_are_inclusive(field: str, value: str) -> None:
    values = {
        "min_daily_change_fraction": "-0.1",
        "max_daily_change_fraction": "0",
        "max_volume_ratio": "1",
    }
    values[field] = value
    if field == "max_daily_change_fraction" and value == "-0.20":
        values["min_daily_change_fraction"] = "-0.20"
    parameters = PullbackSupportParameters(**values)
    assert getattr(parameters, field) == {
        "-0.20": "-0.2",
        "0.05": "0.05",
        "0.10": "0.1",
    }.get(value, value)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("min_daily_change_fraction", "-0.200001"),
        ("min_daily_change_fraction", "0.000001"),
        ("max_daily_change_fraction", "-0.200001"),
        ("max_daily_change_fraction", "0.050001"),
        ("max_volume_ratio", "0.099999"),
        ("max_volume_ratio", "10.000001"),
    ],
)
def test_pullback_just_outside_bounds_is_rejected(field: str, value: str) -> None:
    values = {
        "min_daily_change_fraction": "-0.1",
        "max_daily_change_fraction": "0",
        "max_volume_ratio": "1",
    }
    values[field] = value
    with pytest.raises(ValueError):
        PullbackSupportParameters(**values)


def test_pullback_minimum_must_not_exceed_maximum() -> None:
    with pytest.raises(ValueError, match="minimum"):
        PullbackSupportParameters("0", "-0.001", "1")


@pytest.mark.parametrize("generation", [0, 1_000_000])
def test_generation_boundaries_are_inclusive(generation: int) -> None:
    assert _genome(generation=generation).generation == generation


@pytest.mark.parametrize("generation", [-1, 1_000_001, True, 1.0])
def test_invalid_generation_is_rejected(generation: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        _genome(generation=generation)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "value",
    [
        True,
        1,
        0.7,
        "7e-1",
        "NaN",
        "Infinity",
        "-Infinity",
        " 0.7",
        "0.7 ",
        "+0.7",
        "0,7",
        ".7",
        "00.7",
        "-0",
        "-0.0",
    ],
)
def test_noncanonical_decimal_input_types_and_forms_are_rejected(value: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        CurrentAggressiveParameters(value)  # type: ignore[arg-type]


@pytest.mark.parametrize("value", ["-2", "-2.0", "2", "0.5"])
def test_daily_fraction_fields_reject_percentage_point_confusion(value: str) -> None:
    with pytest.raises(ValueError):
        PullbackSupportParameters(value, "0", "1")


@pytest.mark.parametrize(
    ("family", "parameters"),
    [
        (StrategyFamily.HOLD_CASH, CurrentAggressiveParameters("0.7")),
        (StrategyFamily.CURRENT_AGGRESSIVE, HoldCashParameters()),
        (
            StrategyFamily.PULLBACK_SUPPORT,
            CatalystRelativeStrengthParameters("0.7"),
        ),
        (
            StrategyFamily.CATALYST_RELATIVE_STRENGTH,
            CurrentAggressiveParameters("0.7"),
        ),
    ],
)
def test_family_parameter_mismatch_is_rejected(
    family: StrategyFamily, parameters: object
) -> None:
    with pytest.raises((TypeError, ValueError)):
        StrategyGenome.create(
            family=family,
            parameters=parameters,  # type: ignore[arg-type]
            generation=0,
            parent_id="baseline",
        )


def test_hold_cash_has_exactly_empty_parameters() -> None:
    genome = _genome(
        family=StrategyFamily.HOLD_CASH,
        parameters=HoldCashParameters(),
    )
    assert genome.to_dict()["parameters"] == {}
    with pytest.raises(TypeError):
        HoldCashParameters(min_score="0.7")  # type: ignore[call-arg]


@pytest.mark.parametrize(
    "mutate",
    [
        lambda payload: payload["parameters"].update({"unknown": "1"}),
        lambda payload: payload.update({"unknown": "1"}),
        lambda payload: payload["parameters"].pop("min_score"),
        lambda payload: payload.pop("generation"),
        lambda payload: payload.update({"family": "unknown-family"}),
    ],
)
def test_from_dict_rejects_missing_unknown_and_extra_fields(mutate: object) -> None:
    payload = _genome().to_dict()
    mutate(payload)  # type: ignore[operator]
    with pytest.raises((TypeError, ValueError)):
        StrategyGenome.from_dict(payload)


def test_nested_objects_and_genome_are_frozen() -> None:
    parameters = CurrentAggressiveParameters("0.7")
    genome = _genome(parameters=parameters)

    with pytest.raises(dataclasses.FrozenInstanceError):
        parameters.min_score = "0.8"  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        genome.parent_id = "other"  # type: ignore[misc]
    assert all(
        not isinstance(value, (dict, list, set))
        for value in dataclasses.astuple(genome)
    )


def test_from_dict_rejects_genome_id_mismatch() -> None:
    payload = _genome().to_dict()
    payload["genome_id"] = (
        "genome-current-aggressive-"
        "0" * 64
    )
    with pytest.raises(ValueError, match="genome_id"):
        StrategyGenome.from_dict(payload)


@pytest.mark.parametrize(
    "parent_id",
    [
        "",
        "-leading-dash",
        "has space",
        "../escape",
        "https://example.com",
        "a/b",
        "a" * 129,
        "é",
    ],
)
def test_parent_id_rejects_malformed_or_path_like_tokens(parent_id: str) -> None:
    with pytest.raises(ValueError, match="parent_id"):
        _genome(parent_id=parent_id)


@pytest.mark.parametrize(
    "parent_id",
    ["a", "BuiltIn_1", "genome-parent.v2", "A" * 128],
)
def test_parent_id_accepts_only_safe_tokens(parent_id: str) -> None:
    assert _genome(parent_id=parent_id).parent_id == parent_id


def test_direct_constructor_cannot_override_fixed_genome_fields() -> None:
    parameters = CurrentAggressiveParameters("0.7")
    with pytest.raises(TypeError):
        StrategyGenome(  # type: ignore[call-arg]
            family=StrategyFamily.CURRENT_AGGRESSIVE,
            parameters=parameters,
            generation=0,
            parent_id="baseline",
            schema_version=999,
        )
    with pytest.raises(TypeError):
        StrategyGenome(  # type: ignore[call-arg]
            family=StrategyFamily.CURRENT_AGGRESSIVE,
            parameters=parameters,
            generation=0,
            parent_id="baseline",
            can_submit_orders=True,
        )
    with pytest.raises((TypeError, ValueError)):
        StrategyGenome(
            family=StrategyFamily.HOLD_CASH,
            parameters=parameters,
            generation=0,
            parent_id="baseline",
        )


def test_direct_parameter_construction_validates_and_canonicalizes() -> None:
    assert CurrentAggressiveParameters("0.700").min_score == "0.7"
    with pytest.raises(ValueError):
        CurrentAggressiveParameters("0.4")


def test_exact_source_controlled_policy_loads_as_frozen_typed_data() -> None:
    policy = load_strategy_evolution_policy(POLICY_PATH)

    assert STRATEGY_GENOME_SCHEMA_VERSION == 1
    assert STRATEGY_EVOLUTION_POLICY_SCHEMA_VERSION == 1
    assert policy.to_dict() == _policy_payload()
    assert policy.experiment_starting_cash_usd == "200"
    assert policy.candidate_min_order_usd == "10"
    assert policy.analysis_only is True
    assert policy.execution_authority == "none"
    assert policy.can_submit_orders is False
    assert isinstance(
        policy.mutation_bounds.current_aggressive,
        CurrentAggressiveMutationBounds,
    )
    assert isinstance(
        policy.mutation_bounds.pullback_support,
        PullbackSupportMutationBounds,
    )
    assert isinstance(
        policy.mutation_bounds.catalyst_relative_strength,
        CatalystRelativeStrengthMutationBounds,
    )
    assert json.loads(policy.canonical_json_bytes()) == _policy_payload()
    with pytest.raises(dataclasses.FrozenInstanceError):
        policy.max_active_candidates = 8  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        policy.mutation_bounds.current_aggressive.min_score = "0.1"  # type: ignore[misc]


def test_policy_direct_construction_validates_and_fixed_fields_cannot_be_set() -> None:
    loaded = load_strategy_evolution_policy(POLICY_PATH)
    kwargs = {
        field.name: getattr(loaded, field.name)
        for field in dataclasses.fields(loaded)
        if field.init
    }
    assert StrategyEvolutionPolicy(**kwargs) == loaded
    kwargs["max_active_candidates"] = 0
    with pytest.raises(ValueError):
        StrategyEvolutionPolicy(**kwargs)
    with pytest.raises(TypeError):
        StrategyEvolutionPolicy(  # type: ignore[call-arg]
            **{
                field.name: getattr(loaded, field.name)
                for field in dataclasses.fields(loaded)
                if field.init
            },
            execution_authority="orders",
        )


def test_bound_direct_construction_validates_and_is_frozen() -> None:
    with pytest.raises(ValueError):
        CurrentAggressiveMutationBounds("0")
    with pytest.raises(ValueError):
        PullbackSupportMutationBounds("0.005", "0.005", "10")
    with pytest.raises(ValueError):
        CatalystRelativeStrengthMutationBounds("0.500001")
    bounds = StrategyMutationBounds(
        current_aggressive=CurrentAggressiveMutationBounds("0.05"),
        pullback_support=PullbackSupportMutationBounds(
            "0.005", "0.005", "0.5"
        ),
        catalyst_relative_strength=CatalystRelativeStrengthMutationBounds(
            "0.05"
        ),
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        bounds.current_aggressive = CurrentAggressiveMutationBounds("0.1")  # type: ignore[misc]


def test_every_mutation_bound_has_canonical_full_serialization() -> None:
    aggressive = CurrentAggressiveMutationBounds("0.050")
    pullback = PullbackSupportMutationBounds("0.0050", "0.0050", "0.50")
    catalyst = CatalystRelativeStrengthMutationBounds("0.050")
    bounds = StrategyMutationBounds(
        current_aggressive=aggressive,
        pullback_support=pullback,
        catalyst_relative_strength=catalyst,
    )

    for item in (aggressive, pullback, catalyst, bounds):
        assert json.loads(item.canonical_json_bytes()) == item.to_dict()
        assert b" " not in item.canonical_json_bytes()
        assert item.canonical_json_bytes().endswith(b"}")


@pytest.mark.parametrize(
    "mutate",
    [
        lambda payload: payload.update({"unknown": 1}),
        lambda payload: payload.pop("enabled"),
        lambda payload: payload.update({"schema_version": 2}),
        lambda payload: payload.update({"enabled": 1}),
        lambda payload: payload.update({"experiment_starting_cash_usd": 200}),
        lambda payload: payload.update({"experiment_starting_cash_usd": "0"}),
        lambda payload: payload.update({"experiment_starting_cash_usd": "1000001"}),
        lambda payload: payload.update({"candidate_min_order_usd": "0"}),
        lambda payload: payload.update({"candidate_min_order_usd": "201"}),
        lambda payload: payload.update({"max_active_candidates": 0}),
        lambda payload: payload.update({"max_active_candidates": 65}),
        lambda payload: payload.update({"max_active_candidates": True}),
        lambda payload: payload.update({"mutations_per_cycle": 5}),
        lambda payload: payload.update({"minimum_tracked_days": 0}),
        lambda payload: payload.update({"minimum_tracked_days": 3651}),
        lambda payload: payload.update({"minimum_closed_trades": 0}),
        lambda payload: payload.update({"minimum_closed_trades": 1_000_001}),
        lambda payload: payload.update({"minimum_walk_forward_windows": 0}),
        lambda payload: payload.update({"minimum_walk_forward_windows": 10_001}),
        lambda payload: payload.update({"maximum_paper_drawdown_pct": "-100.1"}),
        lambda payload: payload.update({"maximum_paper_drawdown_pct": "0.1"}),
        lambda payload: payload.update({"analysis_only": False}),
        lambda payload: payload.update({"execution_authority": "live"}),
        lambda payload: payload.update({"can_submit_orders": True}),
        lambda payload: payload["mutation_bounds"].update({"hold-cash": {}}),
        lambda payload: payload["mutation_bounds"].pop("current-aggressive"),
        lambda payload: payload["mutation_bounds"]["current-aggressive"].update(
            {"unknown": "0.1"}
        ),
        lambda payload: payload["mutation_bounds"]["current-aggressive"].update(
            {"min_score": "0"}
        ),
        lambda payload: payload["mutation_bounds"]["pullback-support"].update(
            {"max_volume_ratio": "10"}
        ),
    ],
)
def test_policy_rejects_unknown_missing_type_bound_cross_field_and_authority(
    tmp_path: Path, mutate: object
) -> None:
    payload = _policy_payload()
    mutate(payload)  # type: ignore[operator]
    with pytest.raises((TypeError, ValueError)):
        load_strategy_evolution_policy(_write_policy(tmp_path, payload))


@pytest.mark.parametrize(
    ("field", "valid"),
    [
        ("experiment_starting_cash_usd", ["1", "1000000"]),
        ("maximum_paper_drawdown_pct", ["-100", "0"]),
    ],
)
def test_policy_decimal_boundaries_are_inclusive(
    tmp_path: Path, field: str, valid: list[str]
) -> None:
    for value in valid:
        payload = _policy_payload()
        payload[field] = value
        if field == "experiment_starting_cash_usd":
            payload["candidate_min_order_usd"] = "1"
        assert load_strategy_evolution_policy(
            _write_policy(tmp_path, payload)
        ).to_dict()[field] == value


@pytest.mark.parametrize(
    ("field", "valid"),
    [
        ("max_active_candidates", [1, 64]),
        ("minimum_tracked_days", [1, 3650]),
        ("minimum_closed_trades", [1, 1_000_000]),
        ("minimum_walk_forward_windows", [1, 10_000]),
    ],
)
def test_policy_integer_boundaries_are_inclusive(
    tmp_path: Path, field: str, valid: list[int]
) -> None:
    for value in valid:
        payload = _policy_payload()
        payload[field] = value
        if field == "max_active_candidates":
            payload["mutations_per_cycle"] = 1
        assert load_strategy_evolution_policy(
            _write_policy(tmp_path, payload)
        ).to_dict()[field] == value


def test_policy_mutations_per_cycle_cross_field_boundary(tmp_path: Path) -> None:
    payload = _policy_payload()
    payload["max_active_candidates"] = 64
    payload["mutations_per_cycle"] = 64
    policy = load_strategy_evolution_policy(_write_policy(tmp_path, payload))
    assert policy.mutations_per_cycle == 64


def test_production_model_is_stdlib_only_and_has_no_runtime_integration() -> None:
    path = ROOT / "tradingagents" / "strategy" / "genome.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imports.update(
        (node.module or "").split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    )
    assert imports <= {
        "__future__",
        "collections",
        "dataclasses",
        "decimal",
        "enum",
        "hashlib",
        "json",
        "pathlib",
        "re",
        "typing",
    }

    forbidden_fragments = {
        "broker",
        "tournament",
        "execution",
        "live_control",
        "risk_override",
        "langchain",
        "langgraph",
        "openai",
        "anthropic",
        "callable",
        "eval",
        "exec",
        "compile",
        "__import__",
        "getattr",
        "setattr",
    }
    call_names = {
        node.func.id.lower()
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    source = path.read_text(encoding="utf-8").lower()
    assert not (forbidden_fragments & call_names)
    assert "tradingagents." not in source


def test_strategy_import_has_no_environment_network_or_runtime_side_effect(
    tmp_path: Path,
) -> None:
    script = """
import json
import os
from pathlib import Path
import socket

before_env = dict(os.environ)
before_files = sorted(str(path.relative_to(Path.cwd())) for path in Path.cwd().rglob("*"))

def blocked_connect(*args, **kwargs):
    raise AssertionError("network attempted during import")

socket.socket.connect = blocked_connect
import tradingagents.strategy

after_files = sorted(str(path.relative_to(Path.cwd())) for path in Path.cwd().rglob("*"))
assert dict(os.environ) == before_env
assert after_files == before_files
print(json.dumps({"ok": True}))
"""
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONPATH"] = str(ROOT)
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"ok": True}
