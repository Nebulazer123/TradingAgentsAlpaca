"""Contracts for the complete, pure LangGraph checkpoint run identity."""

from __future__ import annotations

from copy import deepcopy

import pytest

from tradingagents.graph.checkpoint_identity import (
    CHECKPOINT_RUN_IDENTITY_SCHEMA_VERSION,
    CheckpointRunIdentityError,
    build_checkpoint_run_identity,
    validate_checkpoint_run_identity,
)


def _args(**changes: object) -> dict[str, object]:
    values: dict[str, object] = {
        "identity_schema_version": CHECKPOINT_RUN_IDENTITY_SCHEMA_VERSION,
        "clean_source_revision": "a" * 40,
        "source_tree_dirty": False,
        "uv_lock_sha256": "b" * 64,
        "selected_analysts": ("market", "news"),
        "asset_type": "stock",
        "max_debate_rounds": 1,
        "max_risk_discuss_rounds": 2,
        "max_analyst_tool_rounds": 3,
        "max_recur_limit": 100,
        "analyst_concurrency_limit": 1,
        "tool_free_analysts": ("news", "market"),
        "requested_provider": "openrouter",
        "requested_quick_model": "openai/gpt-5-mini",
        "requested_deep_model": "anthropic/claude-sonnet-4-5",
        "backend_route_identity": (
            "https://user:password@router.example/v1?api_key=secret&region=us"
        ),
        "output_language": "English",
        "provider_reasoning_settings": {
            "thinking": {"effort": "high"},
            "temperature": "0",
        },
        "graph_topology_sha256": "c" * 64,
        "agent_prompt_surface_sha256": "d" * 64,
        "bound_tool_surface_sha256": "e" * 64,
        "data_route_surface_sha256": "f" * 64,
        "packet_handoff_schema_version": 1,
        "learning_context_policy_identity": "learning-context-policy-v2",
        "trade_date_cutoff_policy_identity": "market-date-cutoff-v1",
        "learning_evidence_predecessor": "1" * 64,
        "decision_ledger_predecessor": "2" * 64,
    }
    values.update(changes)
    return values


def test_identity_is_canonical_complete_and_secret_safe():
    identity = build_checkpoint_run_identity(**_args())

    assert identity.identity_schema_version == CHECKPOINT_RUN_IDENTITY_SCHEMA_VERSION
    assert identity.source_tree_dirty is False
    assert identity.tool_free_analysts == ("market", "news")
    assert identity.backend_route_identity == "https://router.example/v1?region=us"
    assert len(identity.identity_sha256) == 64
    assert validate_checkpoint_run_identity(identity.to_dict()) == identity
    assert b"password" not in identity.canonical_json_bytes()
    assert b"api_key" not in identity.canonical_json_bytes()
    assert b"secret" not in identity.canonical_json_bytes()


def test_identity_binds_two_separate_required_predecessor_digests():
    fields = _args()
    fields.pop("evidence_ledger_predecessor_identity", None)
    fields.update(learning_evidence_predecessor="1" * 64, decision_ledger_predecessor="2" * 64)
    identity = build_checkpoint_run_identity(**fields)
    assert identity.to_dict()["learning_evidence_predecessor"] == "1" * 64
    assert identity.to_dict()["decision_ledger_predecessor"] == "2" * 64
    assert "evidence_ledger_predecessor_identity" not in identity.to_dict()
    for field in ("learning_evidence_predecessor", "decision_ledger_predecessor"):
        changed = build_checkpoint_run_identity(**{**fields, field: "3" * 64})
        assert changed.identity_sha256 != identity.identity_sha256
        with pytest.raises(CheckpointRunIdentityError):
            build_checkpoint_run_identity(**{**fields, field: None})


def test_identity_removes_generic_secret_query_parameters_from_backend_route():
    identity = build_checkpoint_run_identity(
        **_args(
            backend_route_identity="https://router.example/v1?key=secret&region=us",
        )
    )

    assert identity.backend_route_identity == "https://router.example/v1?region=us"
    assert b"key=secret" not in identity.canonical_json_bytes()


def test_identity_removes_camel_case_secret_query_parameters_from_backend_route():
    identity = build_checkpoint_run_identity(
        **_args(
            backend_route_identity="https://router.example/v1?accessKey=secret&region=us",
        )
    )

    assert identity.backend_route_identity == "https://router.example/v1?region=us"
    assert b"accessKey" not in identity.canonical_json_bytes()
    assert b"secret" not in identity.canonical_json_bytes()


def test_registered_model_token_limits_are_safe_reasoning_settings():
    identity = build_checkpoint_run_identity(
        **_args(
            provider_reasoning_settings={
                "max_completion_tokens": 1024,
                "max_output_tokens": 2048,
                "max_retries": 2,
                "max_tokens": 4096,
                "timeout_seconds": 120.0,
            }
        )
    )

    assert identity.provider_reasoning_settings == {
        "max_completion_tokens": 1024,
        "max_output_tokens": 2048,
        "max_retries": 2,
        "max_tokens": 4096,
        "timeout_seconds": 120.0,
    }


def test_identity_rejects_unknown_route_dimensions_and_provider_route_settings():
    with pytest.raises(CheckpointRunIdentityError):
        build_checkpoint_run_identity(
            **_args(backend_route_identity="https://router.example/v1?opaque=change")
        )
    with pytest.raises(CheckpointRunIdentityError):
        build_checkpoint_run_identity(
            **_args(
                provider_reasoning_settings={
                    "base_url": "https://user:hunter2@router.example/v1",
                }
            )
        )


@pytest.mark.parametrize(
    "changes",
    (
        {"clean_source_revision": "0" * 40},
        {"uv_lock_sha256": "0" * 64},
        {"selected_analysts": ("news", "market")},
        {"asset_type": "crypto"},
        {"max_debate_rounds": 4},
        {"max_risk_discuss_rounds": 4},
        {"max_analyst_tool_rounds": 4},
        {"max_recur_limit": 101},
        {"analyst_concurrency_limit": 2},
        {"tool_free_analysts": ("market",)},
        {"requested_provider": "anthropic"},
        {"requested_quick_model": "anthropic/claude-haiku-4-5"},
        {"requested_deep_model": "anthropic/claude-opus-4-5"},
        {"backend_route_identity": "https://router.example/v2?region=us"},
        {"output_language": "Spanish"},
        {"provider_reasoning_settings": {"thinking": {"effort": "low"}}},
        {"graph_topology_sha256": "0" * 64},
        {"agent_prompt_surface_sha256": "0" * 64},
        {"bound_tool_surface_sha256": "0" * 64},
        {"data_route_surface_sha256": "0" * 64},
        {"packet_handoff_schema_version": 2},
        {"learning_context_policy_identity": "learning-context-policy-v3"},
        {"trade_date_cutoff_policy_identity": "market-date-cutoff-v2"},
        {"learning_evidence_predecessor": "0" * 64},
        {"decision_ledger_predecessor": "0" * 64},
    ),
)
def test_every_behavior_affecting_input_changes_identity_digest(changes):
    baseline = build_checkpoint_run_identity(**_args())
    changed = build_checkpoint_run_identity(**_args(**changes))

    assert changed.identity_sha256 != baseline.identity_sha256


@pytest.mark.parametrize(
    "changes",
    (
        {"source_tree_dirty": True},
        {"clean_source_revision": "not-a-revision"},
        {"clean_source_revision": "A" * 40},
        {"uv_lock_sha256": "bad"},
        {"selected_analysts": ("market", "market")},
        {"tool_free_analysts": "market"},
        {"requested_provider": "openrouter api_key=secret"},
        {"backend_route_identity": "not a route"},
        {"provider_reasoning_settings": {"api_key": "secret"}},
        {"graph_topology_sha256": "not-a-digest"},
        {"packet_handoff_schema_version": 0},
        {"learning_context_policy_identity": "contains whitespace"},
    ),
)
def test_identity_rejects_dirty_malformed_and_secret_bearing_inputs(changes):
    with pytest.raises(CheckpointRunIdentityError):
        build_checkpoint_run_identity(**_args(**changes))


def test_mapping_and_set_order_canonicalize_without_changing_identity_bytes():
    first = build_checkpoint_run_identity(
        **_args(
            tool_free_analysts=("news", "market", "market"),
            provider_reasoning_settings={
                "temperature": "0",
                "thinking": {"effort": "high", "budget": 1024},
            },
        )
    )
    second = build_checkpoint_run_identity(
        **_args(
            tool_free_analysts=("market", "news"),
            provider_reasoning_settings={
                "thinking": {"budget": 1024, "effort": "high"},
                "temperature": "0",
            },
        )
    )

    assert first.canonical_json_bytes() == second.canonical_json_bytes()
    assert first.identity_sha256 == second.identity_sha256


@pytest.mark.parametrize("mutation", ("missing", "extra", "noncanonical", "digest"))
def test_validator_rebuilds_the_exact_canonical_identity(mutation):
    payload = deepcopy(build_checkpoint_run_identity(**_args()).to_dict())
    if mutation == "missing":
        payload.pop("uv_lock_sha256")
    elif mutation == "extra":
        payload["unexpected"] = "field"
    elif mutation == "noncanonical":
        payload["tool_free_analysts"] = ["news", "market"]
    else:
        payload["identity_sha256"] = "0" * 64

    with pytest.raises(CheckpointRunIdentityError):
        validate_checkpoint_run_identity(payload)
