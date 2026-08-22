"""Pinned immutable evidence ledger for the non-authorizing shadow-day trial.

Task 3 owns the calendar and other canonical authority-source captures, trusted
clock, fixed ledger root, exact semantic record construction, and trusted-head
lifecycle.  Normal callers can select only a run identifier, market date,
predecessor record, and local artifact paths through the three semantic
facades.  Every read replays the dedicated journal before using an object; a
JSON file under the root is never evidence merely because it exists.

The adjacent trusted-head anchor detects root-only copies and rollbacks.  It is
not an external root of trust: a hostile process with the same filesystem-user
authority can coherently replace both local surfaces or introspect/monkeypatch
the running process.  Defeating that stronger attacker requires protected
storage or a monotonic service outside this module.
"""

from __future__ import annotations

import datetime as dt
import fcntl
import hashlib
import json
import os
import stat
import threading
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from tradingagents.evals.automation_health_audit import (
    FROZEN_OBSERVER_ACTIVE_AUTOMATION_IDS,
    FROZEN_OBSERVER_PAUSED_AUTOMATION_IDS,
    PREDEPLOYMENT_PAUSED_PHASE,
    capture_schedule_contract_snapshot,
    evaluate_schedule_contract,
    schedule_contract_snapshot_manifest,
)
from tradingagents.evals.safety_sentinel import broker_snapshot_shape_reasons
from tradingagents.strategy._immutable_evidence_store import (
    MANUAL_SHADOW_DAY_RESULT_KIND,
    MANUAL_SHADOW_DAY_START_KIND,
    MANUAL_SHADOW_FINAL_REPORT_KIND,
    EvidenceAdmission,
    EvidenceEnvelope,
    EvidenceEvent,
    EvidenceJournalHead,
    StrategyEvidenceStoreError,
    _payload_bytes,
    _retry_material_bytes,
)

UTC = dt.timezone.utc
CENTRAL = ZoneInfo("America/Chicago")
START_SCHEMA = "manual_shadow_day_start_v1"
DAY_SCHEMA = "manual_shadow_day_result_v1"
REPORT_SCHEMA = "manual_shadow_final_report_v1"
ARTIFACT_KEYS = ("safety_sentinel", "paper_tournament", "daily_chain_manifest")
OPERATOR_ABORT_REASON = "shadow_day_aborted_by_operator"
PENDING_DAY_EXPIRED_REASON = "pending_day_expired_without_adjudication"
ABORT_NOTES_LIMIT = 500
DAILY_CHAIN_STAGES = (
    "overnight_research",
    "premarket_brief",
    "preopen_validation",
    "hourly_supervisor",
    "safety_sentinel",
    "loss_review",
    "execution_board",
    "self_heal_handoff",
    "self_heal_plan",
    "daily_report",
    "broker_reconciliation",
    "paper_tournament",
)
DAILY_CHAIN_STAGE_KINDS = {
    "overnight_research": "overnight_plan",
    "premarket_brief": "premarket_brief",
    "preopen_validation": "tradingagents_preopen_validation",
    "hourly_supervisor": "hourly_supervisor",
    "safety_sentinel": "safety_sentinel_audit",
    "loss_review": "loss_review_evidence",
    "execution_board": "execution_board_review",
    "self_heal_handoff": "tradingagents_self_heal_handoff",
    "self_heal_plan": "tradingagents_self_heal_plan",
    "daily_report": "supervisor_daily_report",
    "broker_reconciliation": "broker_reconciliation_observer",
    "paper_tournament": "paper_tournament_run",
}
SHADOW_DAY_STOP_STAGES = ("day_start", *DAILY_CHAIN_STAGES)


def _has_nonempty_error(value: object) -> bool:
    """Return true only for an explicit, populated failure channel.

    Observer producers carry useful ordinary strings such as ``reason`` and
    ``warnings``.  Those are not errors by themselves.  A result packet may
    count toward a clean day only when its explicit error channels are empty.
    """

    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = str(key).strip().lower()
            if normalized in {"error", "errors", "exception", "exceptions"} and item not in (None, "", [], {}, ()):
                return True
            if _has_nonempty_error(item):
                return True
    elif isinstance(value, (list, tuple)):
        return any(_has_nonempty_error(item) for item in value)
    return False


def _no_submissions(payload: Mapping[str, object]) -> bool:
    submitted = payload.get("submitted")
    submitted_count = payload.get("submitted_count")
    return (
        (submitted is None or submitted in ([], ()))
        and (submitted_count is None or submitted_count == 0)
    )


_BROKER_OBSERVER_READ_METHODS = [
    "get_account",
    "list_positions",
    "list_orders",
    "get_clock",
]


def _broker_observer_snapshot_is_valid(value: object) -> bool:
    if not isinstance(value, Mapping):
        return False
    errors = value.get("errors")
    return (
        isinstance(errors, Mapping)
        and not errors
        and value.get("read_methods") == _BROKER_OBSERVER_READ_METHODS
        and _parse_timestamp(value.get("captured_at")) is not None
        and not broker_snapshot_shape_reasons(value)
    )


def _captured_source_is_valid(value: object) -> bool:
    return (
        isinstance(value, Mapping)
        and value.get("status") == "captured"
        and isinstance(value.get("path"), str)
        and bool(value["path"])
        and Path(value["path"]).is_absolute()
        and _is_sha256(value.get("sha256"))
        and type(value.get("size_bytes")) is int
        and value["size_bytes"] > 0
    )


def _captured_source_matches(value: object, expected: object) -> bool:
    return (
        _captured_source_is_valid(value)
        and isinstance(value, Mapping)
        and isinstance(expected, Mapping)
        and value.get("path") == expected.get("path")
        and value.get("sha256") == expected.get("sha256")
        and value.get("size_bytes") == expected.get("size_bytes")
    )


_SCHEDULE_TOML_IDENTITY_KEYS = (
    "automation_id",
    "automation_root",
    "relative_path",
    "path",
    "status",
    "sha256",
    "size_bytes",
    "descriptor_relative",
    "file_kind",
    "symlink",
    "root_identity",
    "file_identity",
)


def _schedule_configuration_identity(value: object) -> dict[str, object] | None:
    """Project stable source identities from one trusted schedule capture manifest."""

    value = _plain_json(value)
    if (
        not isinstance(value, Mapping)
        or value.get("provenance") != "direct_current_configuration_capture"
        or value.get("capture_issues") not in ([], ())
        or _parse_timestamp(value.get("captured_at")) is None
    ):
        return None
    freshness = value.get("freshness")
    if not isinstance(freshness, Mapping) or (
        freshness.get("status") != "not_applicable"
        or freshness.get("rule") != "static_configuration_captured_this_audit"
    ):
        return None
    contract = value.get("contract")
    role_contract = value.get("role_contract")
    rows = value.get("automation_tomls")
    if (
        not _captured_source_is_valid(contract)
        or not _captured_source_is_valid(role_contract)
        or not isinstance(rows, list)
        or len(rows) != len(EXPECTED_AUTOMATION_IDS)
    ):
        return None
    row_ids = [row.get("automation_id") for row in rows if isinstance(row, Mapping)]
    if (
        len(row_ids) != len(rows)
        or len(set(row_ids)) != len(rows)
        or set(row_ids) != EXPECTED_AUTOMATION_IDS
    ):
        return None
    projected_rows: list[dict[str, object]] = []
    for row in rows:
        if (
            not _captured_source_is_valid(row)
            or row.get("relative_path") != f"{row.get('automation_id')}/automation.toml"
            or row.get("descriptor_relative") is not True
            or row.get("file_kind") != "regular"
            or row.get("symlink") is not False
            or not isinstance(row.get("root_identity"), Mapping)
            or not isinstance(row.get("file_identity"), Mapping)
        ):
            return None
        projected_rows.append(
            {key: _plain_json(row.get(key)) for key in _SCHEDULE_TOML_IDENTITY_KEYS}
        )
    source_paths = [
        contract.get("path"),
        role_contract.get("path"),
        *(row.get("path") for row in rows),
    ]
    if len(source_paths) != len(set(source_paths)):
        return None
    return {
        "contract": {
            key: contract.get(key)
            for key in ("path", "status", "sha256", "size_bytes")
        },
        "role_contract": {
            key: role_contract.get(key)
            for key in ("path", "status", "sha256", "size_bytes")
        },
        "automation_tomls": sorted(
            projected_rows,
            key=lambda row: str(row["automation_id"]),
        ),
    }


def _sentinel_sources_match(
    evidence: object,
    schedule_check: object,
    bindings: object,
) -> bool:
    if not isinstance(evidence, Mapping) or not isinstance(bindings, Mapping):
        return False
    expected_schedule = bindings.get("schedule_check")
    observed_configuration = _schedule_configuration_identity(
        evidence.get("schedule_configuration")
    )
    expected_configuration = _schedule_configuration_identity(
        bindings.get("schedule_configuration")
    )
    return (
        _captured_source_matches(
            evidence.get("live_control"),
            bindings.get("live_control"),
        )
        and _captured_source_matches(
            evidence.get("preopen_validation"),
            bindings.get("preopen_validation"),
        )
        and observed_configuration is not None
        and observed_configuration == expected_configuration
        and isinstance(expected_schedule, Mapping)
        and _plain_json(schedule_check) == _plain_json(expected_schedule)
    )


def _stage_semantic_reasons(
    stage: str,
    payload: Mapping[str, object],
    *,
    sentinel_source_bindings: Mapping[str, object] | None = None,
) -> list[str]:
    """Validate real producer shapes without pretending they share one schema.

    The daily observer chain deliberately binds persisted output from several
    existing writers.  Some of those legacy packets predate the common
    ``kind``/authority fields.  This validator therefore checks their native
    safe predicates instead of accepting test-only uniform envelopes.
    """

    reasons: list[str] = []
    expected_kind = DAILY_CHAIN_STAGE_KINDS[stage]
    supplied_kind = payload.get("kind")
    if supplied_kind is not None and supplied_kind != expected_kind:
        reasons.append(f"{stage}_stage_kind_invalid")
    if _has_nonempty_error(payload):
        reasons.append(f"{stage}_stage_error_present")

    if stage == "overnight_research":
        quality = payload.get("overnight_quality")
        if payload.get("analysis_only") is not True or not _no_submissions(payload):
            reasons.append("overnight_research_stage_authority_invalid")
        if not isinstance(quality, Mapping):
            reasons.append("overnight_research_stage_quality_missing")
        else:
            if str(quality.get("completion_status") or "").lower() != "complete":
                reasons.append("overnight_research_stage_incomplete")
            for key in (
                "graph_failure_count",
                "graph_attempt_failure_count",
                "top_provider_bundle_error_count",
            ):
                if quality.get(key) != 0:
                    reasons.append("overnight_research_stage_provider_or_graph_failure")
                    break
            # ``--full-graph-tickers 1`` bounds graph work, not the candidate
            # universe.  A healthy producer can therefore report several
            # tradable symbols while selecting or attempting at most one for
            # the bounded graph.  Require the recorded requested/effective
            # cap and every native graph counter to prove that constraint.
            graph_counts = (
                "full_graph_count",
                "full_graph_attempt_count",
                "full_graph_success_count",
            )
            if (
                type(quality.get("requested_full_graph_limit")) is not int
                or quality["requested_full_graph_limit"] != 1
                or type(quality.get("full_graph_limit")) is not int
                or quality["full_graph_limit"] != 1
                or any(
                    type(quality.get(key)) is not int
                    or quality[key] < 0
                    or quality[key] > 1
                    for key in graph_counts
                )
                or quality["full_graph_success_count"] > quality["full_graph_count"]
                or quality["full_graph_count"] > quality["full_graph_attempt_count"]
            ):
                reasons.append("overnight_research_stage_graph_cap_invalid")
            if type(quality.get("tradable_count")) is not int or quality["tradable_count"] < 0:
                reasons.append("overnight_research_stage_tradable_count_invalid")
            ticker_timeout = quality.get("per_ticker_timeout_minutes")
            total_budget = quality.get("time_budget_minutes")
            if (
                type(ticker_timeout) not in {int, float}
                or not 0 < float(ticker_timeout) <= 2
                or type(total_budget) not in {int, float}
                or not 0 < float(total_budget) <= 3
            ):
                reasons.append("overnight_research_stage_bounds_invalid")
            graph_config = quality.get("graph_config")
            if not isinstance(graph_config, Mapping) or (
                graph_config.get("graph_profile") != "market-only"
                or graph_config.get("selected_analysts") != ["market"]
                or graph_config.get("tool_free_analysts") != ["market"]
                or type(graph_config.get("max_output_tokens")) is not int
                or graph_config["max_output_tokens"] != 800
                or type(graph_config.get("max_completion_tokens")) is not int
                or graph_config["max_completion_tokens"] != 800
                or type(graph_config.get("llm_timeout_seconds")) not in {int, float}
                or float(graph_config["llm_timeout_seconds"]) != 30.0
                or type(graph_config.get("llm_max_retries")) is not int
                or graph_config["llm_max_retries"] != 0
                or type(graph_config.get("max_debate_rounds")) is not int
                or graph_config["max_debate_rounds"] != 0
                or type(graph_config.get("max_risk_discuss_rounds")) is not int
                or graph_config["max_risk_discuss_rounds"] != 0
            ):
                reasons.append("overnight_research_stage_graph_config_invalid")
            disabled_features = (
                "research_context_enabled",
                "agent_intelligence_enabled",
                "agent_ledger_append_enabled",
            )
            zero_counts = (
                "research_context_packet_count",
                "research_context_blocked_count",
                "top_provider_bundle_requested_count",
                "top_provider_bundle_count",
            )
            if any(quality.get(key) is not False for key in disabled_features) or any(
                type(quality.get(key)) is not int or quality[key] != 0
                for key in zero_counts
            ):
                reasons.append("overnight_research_stage_expansion_enabled")
    elif stage == "premarket_brief":
        if payload.get("analysis_only") is not True or not _no_submissions(payload):
            reasons.append("premarket_brief_stage_authority_invalid")
        if payload.get("stale_warnings") not in ([], ()) or payload.get("unresolved_blockers") not in ([], ()):
            reasons.append("premarket_brief_stage_stale_or_blocked")
    elif stage == "preopen_validation":
        if not _is_non_authorizing(payload) or payload.get("submitted_count") != 0:
            reasons.append("preopen_validation_stage_authority_invalid")
        if payload.get("overall_status") not in {"pass", "pass_with_warnings"}:
            reasons.append("preopen_validation_stage_not_complete")
        if payload.get("failed_check_ids") not in ([], ()):
            reasons.append("preopen_validation_stage_failed_check")
    elif stage == "hourly_supervisor":
        # Only the explicit CLI dry-run metadata turns a normal supervisor
        # packet into observer-chain evidence.  Submit-capable normal packets
        # remain unchanged and cannot qualify accidentally.
        if payload.get("shadow_dry_run") is not True or not _no_submissions(payload):
            reasons.append("hourly_supervisor_stage_not_dry_run")
        if (
            payload.get("outbox_path")
            or payload.get("outbox_suppressed") is not True
            or payload.get("outbox_write_allowed") is not False
        ):
            reasons.append("hourly_supervisor_stage_outbox_forbidden")
        if payload.get("issues") not in (None, [], ()):
            reasons.append("hourly_supervisor_stage_issue_present")
    elif stage == "safety_sentinel":
        if not _is_non_authorizing(payload) or payload.get("status") != "FROZEN":
            reasons.append("safety_sentinel_stage_semantics_invalid")
        sentinel_reasons = payload.get("reasons")
        if sentinel_reasons != ["frozen_control"]:
            reasons.append("safety_sentinel_stage_failure_reason_present")
        schedule_check = payload.get("schedule_check")
        schedule_rows = (
            schedule_check.get("automations")
            if isinstance(schedule_check, Mapping)
            else None
        )
        schedule_ids = (
            [row.get("automation_id") for row in schedule_rows if isinstance(row, Mapping)]
            if isinstance(schedule_rows, list)
            else []
        )
        if (
            not isinstance(schedule_check, Mapping)
            or schedule_check.get("deployment_phase") != PREDEPLOYMENT_PAUSED_PHASE
            or schedule_check.get("contract_status") != "pass"
            or schedule_check.get("safe_predeployment") is not True
            or schedule_check.get("deployment_proven") is not False
            or schedule_check.get("issues") not in ([], ())
            or type(schedule_check.get("automation_count")) is not int
            or schedule_check["automation_count"] != len(EXPECTED_AUTOMATION_IDS)
            or type(schedule_check.get("configured_count")) is not int
            or schedule_check["configured_count"] != len(EXPECTED_AUTOMATION_IDS)
            or type(schedule_check.get("paused_count")) is not int
            or schedule_check["paused_count"] != len(EXPECTED_AUTOMATION_IDS)
            or not isinstance(schedule_rows, list)
            or len(schedule_rows) != len(EXPECTED_AUTOMATION_IDS)
            or len(schedule_ids) != len(schedule_rows)
            or len(set(schedule_ids)) != len(schedule_rows)
            or set(schedule_ids) != EXPECTED_AUTOMATION_IDS
            or any(
                not isinstance(row, Mapping)
                or row.get("status") != "match"
                or row.get("config_status") != "PAUSED"
                or row.get("mismatches") not in ([], ())
                for row in schedule_rows
            )
        ):
            reasons.append("safety_sentinel_stage_schedule_proof_invalid")
        evidence = payload.get("evidence")
        if not _sentinel_sources_match(
            evidence,
            schedule_check,
            sentinel_source_bindings,
        ):
            reasons.append("safety_sentinel_stage_source_proof_invalid")
        if payload.get("actions_taken") not in ([], ()) or not _broker_observer_snapshot_is_valid(
            payload.get("broker_snapshot")
        ):
            reasons.append("safety_sentinel_stage_broker_proof_invalid")
    elif stage == "loss_review":
        nested = payload.get("payload")
        freshness = payload.get("freshness")
        if (
            payload.get("evidence_type") != "loss_review_evidence"
            or not isinstance(nested, Mapping)
            or not isinstance(freshness, Mapping)
        ):
            reasons.append("loss_review_stage_schema_invalid")
        elif (
            not _is_non_authorizing(nested)
            or freshness.get("read_only") is not True
            or freshness.get("can_submit_orders") is not False
            or nested.get("next_action") != "autonomous_hold"
            or nested.get("submitted_order_count") != 0
        ):
            reasons.append("loss_review_stage_authority_invalid")
        if isinstance(nested, Mapping):
            current_review = nested.get("current_loss_review")
            remaining_blockers = nested.get("remaining_blockers")
            if (
                remaining_blockers not in ([], ())
                or not isinstance(current_review, Mapping)
                or current_review.get("trade_decision_allowed") is not True
                or current_review.get("blockers") not in ([], ())
            ):
                reasons.append("loss_review_stage_incomplete")
            advisory_analysis = nested.get("advisory_analysis")
            route_summary = (
                advisory_analysis.get("route_summary")
                if isinstance(advisory_analysis, Mapping)
                else None
            )
            provider_failure = (
                not isinstance(route_summary, (list, tuple))
                or not route_summary
            )
            if isinstance(route_summary, (list, tuple)):
                for attempt in route_summary:
                    if not isinstance(attempt, Mapping):
                        provider_failure = True
                        break
                    status = str(attempt.get("status") or "").strip().lower()
                    if (
                        type(attempt.get("blocked")) is not bool
                        or attempt.get("blocked") is True
                        or not status
                        or status in {"blocked", "error", "failed", "exception"}
                        or "error" in status
                        or "failed" in status
                    ):
                        provider_failure = True
                        break
            if provider_failure:
                reasons.append("loss_review_stage_provider_failure")
    elif stage == "execution_board":
        metrics = payload.get("metrics")
        if not _is_non_authorizing(payload) or not isinstance(metrics, Mapping):
            reasons.append("execution_board_stage_authority_invalid")
        elif metrics.get("submitted_order_count") != 0:
            reasons.append("execution_board_stage_submission_present")
        if payload.get("violations") not in ([], ()) or payload.get("warnings") not in ([], ()):
            reasons.append("execution_board_stage_issue_present")
    elif stage in {"self_heal_handoff", "self_heal_plan"}:
        if not _is_non_authorizing(payload):
            reasons.append(f"{stage}_stage_authority_invalid")
        if str(payload.get("max_severity") or "").lower() not in {"none", "low"}:
            reasons.append(f"{stage}_stage_elevated_severity_present")
        if stage == "self_heal_handoff":
            if type(payload.get("active_trigger_count")) is not int or payload["active_trigger_count"] != 0:
                reasons.append("self_heal_handoff_stage_active_trigger_present")
        else:
            if payload.get("executed_count", 0) not in (0, None):
                reasons.append("self_heal_plan_stage_execution_forbidden")
            if type(payload.get("active_plan_count")) is not int or payload["active_plan_count"] != 0:
                reasons.append("self_heal_plan_stage_active_plan_present")
            if type(payload.get("escalation_count")) is not int or payload["escalation_count"] != 0:
                reasons.append("self_heal_plan_stage_escalation_present")
            if str(payload.get("status") or "").lower() not in {"quiet", "deduped"}:
                reasons.append("self_heal_plan_stage_status_invalid")
    elif stage == "daily_report":
        if payload.get("outbox_path"):
            reasons.append("daily_report_stage_outbox_forbidden")
        if payload.get("packet_count") is None or payload.get("portfolio") is None:
            reasons.append("daily_report_stage_schema_invalid")
    elif stage == "broker_reconciliation":
        live = payload.get("live")
        paper = payload.get("paper")
        if (
            not _is_non_authorizing(payload)
            or payload.get("status") != "COMPLETE"
            or payload.get("read_only") is not True
            or payload.get("submitted_count") != 0
            or payload.get("cancelled_count") != 0
            or not isinstance(live, Mapping)
            or not isinstance(paper, Mapping)
            or _has_nonempty_error(live)
            or _has_nonempty_error(paper)
            or not _broker_observer_snapshot_is_valid(live)
            or not _broker_observer_snapshot_is_valid(paper)
        ):
            reasons.append("broker_reconciliation_stage_semantics_invalid")
    elif stage == "paper_tournament":
        if not _is_non_authorizing(payload) or payload.get("status") not in {"HOLD", "NO_PAPER_SIGNAL", "COMPLETE"}:
            reasons.append("paper_tournament_stage_semantics_invalid")
        if (
            not isinstance(payload.get("submitted_count"), int)
            or not isinstance(payload.get("submitted"), list)
            or len(payload["submitted"]) != payload["submitted_count"]
        ):
            reasons.append("paper_tournament_stage_submissions_invalid")
    return reasons
EXPECTED_AUTOMATION_IDS = frozenset(
    FROZEN_OBSERVER_ACTIVE_AUTOMATION_IDS
    | FROZEN_OBSERVER_PAUSED_AUTOMATION_IDS
)
_START_FIELDS = frozenset(
    {
        "payload_schema",
        "run_id",
        "market_date",
        "role",
        "phase",
        "predecessor_object_id",
        "live_control",
        "schedule",
        "calendar",
    }
)
_DAY_FIELDS = frozenset(
    {
        "payload_schema",
        "start_object_id",
        "run_id",
        "market_date",
        "role",
        "status",
        "phase",
        "predecessor_object_id",
        "live_control",
        "schedule",
        "calendar",
        "artifacts",
        "reasons",
        "closure_kind",
        "stopped_at_stage",
        "notes",
    }
)
_REPORT_FIELDS = frozenset(
    {
        "payload_schema",
        "ledger_head_object_id",
        "day_object_ids",
        "status",
        "phase",
        "clean_trial_streak",
        "required_clean_trial_days",
        "reasons",
    }
)
_CONTROL_FIELDS = frozenset(
    {
        "path",
        "status",
        "sha256",
        "canonical_sha256",
        "size_bytes",
        "modified_at",
        "frozen",
        "reason",
        "dead_man_expires_at",
        "payload",
    }
)
_SCHEDULE_FIELDS = frozenset(
    {
        "contract_path",
        "automation_root",
        "role_contract_path",
        "result",
        "source_manifest",
        "canonical_sha256",
    }
)
_CALENDAR_FIELDS = frozenset(
    {
        "kind",
        "market_date",
        "observed_at",
        "sessions",
        "canonical_sha256",
    }
)
_ARTIFACT_FIELDS = frozenset(
    {
        "path",
        "status",
        "sha256",
        "canonical_sha256",
        "size_bytes",
        "modified_at",
        "kind",
        "run_id",
        "market_date",
        "generated_at",
        "payload",
    }
)
_MANIFEST_FIELDS = frozenset(
    {
        "kind",
        "generated_at",
        "shadow_start_object_id",
        "run_id",
        "market_date",
        "analysis_only",
        "execution_authority",
        "can_submit_orders",
        "live_control",
        "schedule",
        "stages",
        "paper_order_ids",
        "paper_order_count",
        "broker_reconciliation",
    }
)
_ANCHOR_FIELDS = frozenset(
    {
        "schema_version",
        "kind",
        "canonical_root",
        "ledger_id",
        "committed_head",
        "pending_next",
    }
)
_HEAD_FIELDS = frozenset(
    {
        "sequence",
        "kind",
        "object_id",
        "event_sha256",
        "admission_route",
    }
)
_PENDING_FIELDS = frozenset(
    {
        "prior_head",
        "sequence",
        "kind",
        "object_id",
        "retry_material_sha256",
        "admission_route",
    }
)
_ZERO_HASH = "0" * 64
_MANUAL_SHADOW_KINDS = frozenset(
    {
        MANUAL_SHADOW_DAY_START_KIND,
        MANUAL_SHADOW_DAY_RESULT_KIND,
        MANUAL_SHADOW_FINAL_REPORT_KIND,
    }
)
_MAX_LEDGER_FILE_BYTES = 1_048_576
_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_DIRECTORY = getattr(os, "O_DIRECTORY", 0)


def _utc_now() -> dt.datetime:
    """Private trusted-clock seam; production commands expose no time option."""

    return dt.datetime.now(tz=UTC)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _manual_shadow_root() -> Path:
    return _repo_root() / "results" / "manual_shadow"


def _manual_shadow_anchor_path() -> Path:
    """Durable trusted head kept outside the replaceable ledger root."""

    return _manual_shadow_root().parent / ".manual-shadow-trusted-head.json"


def _manual_shadow_anchor_lock_path() -> Path:
    return _manual_shadow_root().parent / ".manual-shadow-trusted-head.lock"


def _canonical_live_control_path() -> Path:
    return _repo_root() / "results" / "policy" / "live_control.json"


def _canonical_schedule_contract_path() -> Path:
    return _repo_root() / "config" / "automation_schedule_contract.json"


def _canonical_role_contract_path() -> Path:
    return _repo_root() / "config" / "automation_roles.json"


def _canonical_automation_root() -> Path:
    return Path("/Users/corbinfloyd/.codex/automations")


def _as_utc(value: dt.datetime) -> dt.datetime:
    if not isinstance(value, dt.datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("trusted clock must be timezone-aware")
    return value.astimezone(UTC).replace(microsecond=0)


def _now_stamp() -> tuple[dt.datetime, str]:
    now = _as_utc(_utc_now())
    return now, now.isoformat(timespec="seconds")


def _parse_timestamp(value: object) -> dt.datetime | None:
    if type(value) is not str or not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(UTC)


def _parse_market_date(value: object) -> dt.date | None:
    if type(value) is not str:
        return None
    try:
        parsed = dt.date.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.isoformat() == value else None


def _current_central_date(moment: dt.datetime) -> str:
    return moment.astimezone(CENTRAL).date().isoformat()


def _plain_json(value: object) -> object:
    """Thaw store-frozen mappings/tuples before canonical JSON validation."""

    if isinstance(value, Mapping):
        return {str(key): _plain_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain_json(item) for item in value]
    return value


def _canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            _plain_json(value),
            ensure_ascii=True,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("value is not canonical JSON") from exc


def canonical_json_sha256(value: object) -> str:
    """Digest canonical JSON for bound local observation evidence."""

    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _reject_nonfinite(value: str) -> None:
    raise ValueError(f"non-finite JSON value: {value}")


def _absolute(path: str | Path) -> Path:
    return Path(os.path.abspath(os.fspath(Path(path).expanduser())))


def _is_sha256(value: object) -> bool:
    return (
        type(value) is str
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _read_regular_json(path_value: str | Path) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Capture one regular JSON file with descriptor/no-follow semantics."""

    path = _absolute(path_value)
    evidence: dict[str, Any] = {
        "path": str(path),
        "status": "missing",
        "sha256": None,
        "canonical_sha256": None,
        "size_bytes": None,
        "modified_at": None,
    }
    if path.is_symlink():
        evidence["status"] = "symlink"
        return evidence, None
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError:
        return evidence, None
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            evidence["status"] = "not_regular_file"
            return evidence, None
        with os.fdopen(descriptor, "rb") as source:
            raw = source.read()
        descriptor = -1
    except OSError:
        return evidence, None
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    evidence.update(
        {
            "sha256": hashlib.sha256(raw).hexdigest(),
            "size_bytes": len(raw),
            "modified_at": dt.datetime.fromtimestamp(metadata.st_mtime, tz=UTC).isoformat(
                timespec="seconds"
            ),
        }
    )
    try:
        payload = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonfinite,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        evidence["status"] = "malformed_json"
        return evidence, None
    if type(payload) is not dict:
        evidence["status"] = "invalid_top_level"
        return evidence, None
    evidence["status"] = "captured"
    evidence["canonical_sha256"] = canonical_json_sha256(payload)
    return evidence, payload


def _require_exact_fields(value: object, fields: frozenset[str], *, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    keys = set(value)
    if not all(type(key) is str for key in value) or keys != fields:
        missing = sorted(fields - keys)
        unknown = sorted(keys - fields)
        detail = []
        if missing:
            detail.append("missing " + ", ".join(missing))
        if unknown:
            detail.append("unknown " + ", ".join(unknown))
        raise ValueError(f"{label} fields are invalid" + (": " + "; ".join(detail) if detail else ""))
    return value


def _require_text(value: object, *, label: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{label} must be a nonblank string")
    return value


def _is_non_authorizing(payload: Mapping[str, object]) -> bool:
    return (
        payload.get("analysis_only") is True
        and payload.get("execution_authority") == "none"
        and payload.get("can_submit_orders") is False
    )


def _reject_symlink_components(path: Path) -> None:
    absolute = _absolute(path)
    current = Path(absolute.anchor)
    for component in absolute.parts[1:]:
        current /= component
        try:
            metadata = current.lstat()
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise ValueError("trusted-head path could not be inspected") from exc
        if stat.S_ISLNK(metadata.st_mode):
            raise ValueError("trusted-head path must not contain a symlink")


def _require_anchor_file_state(metadata: os.stat_result, *, label: str) -> None:
    if not stat.S_ISREG(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
        raise ValueError(f"{label} must be a regular no-follow file")
    if metadata.st_nlink != 1 or stat.S_IMODE(metadata.st_mode) != 0o600:
        raise ValueError(f"{label} has an unsafe identity or mode")


@contextmanager
def _locked_anchor_parent() -> Iterator[int]:
    anchor_path = _absolute(_manual_shadow_anchor_path())
    lock_path = _absolute(_manual_shadow_anchor_lock_path())
    if anchor_path.parent != lock_path.parent:
        raise ValueError("trusted-head paths do not share one parent")
    _reject_symlink_components(anchor_path.parent)
    try:
        parent_fd = os.open(
            anchor_path.parent,
            os.O_RDONLY | _DIRECTORY | _NOFOLLOW,
        )
    except OSError as exc:
        raise ValueError("trusted-head parent is missing or unsafe") from exc
    lock_fd: int | None = None
    try:
        try:
            lock_fd = os.open(
                lock_path.name,
                os.O_RDWR | os.O_CREAT | _NOFOLLOW,
                0o600,
                dir_fd=parent_fd,
            )
        except OSError as exc:
            raise ValueError("trusted-head lock could not be opened safely") from exc
        _require_anchor_file_state(os.fstat(lock_fd), label="trusted-head lock")
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        yield parent_fd
    finally:
        if lock_fd is not None:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
            finally:
                os.close(lock_fd)
        os.close(parent_fd)


def _anchor_entry_state(parent_fd: int) -> os.stat_result | None:
    try:
        return os.stat(
            _manual_shadow_anchor_path().name,
            dir_fd=parent_fd,
            follow_symlinks=False,
        )
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise ValueError("trusted-head anchor could not be inspected") from exc


def _head_mapping(head: EvidenceJournalHead) -> dict[str, object]:
    return {
        "sequence": head.sequence,
        "kind": head.kind,
        "object_id": head.object_id,
        "event_sha256": head.event_sha256,
        "admission_route": head.admission_route,
    }


def _valid_head_mapping(value: object, *, ledger_id: str) -> bool:
    try:
        head = _require_exact_fields(value, _HEAD_FIELDS, label="trusted head")
    except ValueError:
        return False
    sequence = head["sequence"]
    if type(sequence) is not int or sequence < 0:
        return False
    if sequence == 0:
        return (
            head["kind"] is None
            and head["object_id"] is None
            and head["event_sha256"] == _ZERO_HASH
            and head["admission_route"] == ledger_id
        )
    return (
        head["kind"]
        in {
            MANUAL_SHADOW_DAY_START_KIND,
            MANUAL_SHADOW_DAY_RESULT_KIND,
            MANUAL_SHADOW_FINAL_REPORT_KIND,
        }
        and type(head["object_id"]) is str
        and str(head["object_id"]).startswith(f"{head['kind']}-")
        and _is_sha256(head["event_sha256"])
        and head["admission_route"] == ledger_id
    )


def _head_matches(mapping: object, head: EvidenceJournalHead) -> bool:
    return isinstance(mapping, Mapping) and dict(mapping) == _head_mapping(head)


def _validate_anchor(value: object) -> dict[str, object]:
    anchor = _require_exact_fields(value, _ANCHOR_FIELDS, label="trusted-head anchor")
    plain = dict(anchor)
    ledger_id = plain["ledger_id"]
    if (
        plain["schema_version"] != 1
        or plain["kind"] != "manual-shadow-trusted-head"
        or plain["canonical_root"] != str(_absolute(_manual_shadow_root()))
        or not _is_sha256(ledger_id)
        or not isinstance(ledger_id, str)
        or not _valid_head_mapping(plain["committed_head"], ledger_id=ledger_id)
    ):
        raise ValueError("trusted-head anchor root or identity is invalid")
    pending = plain["pending_next"]
    if pending is not None:
        pending_map = _require_exact_fields(
            pending,
            _PENDING_FIELDS,
            label="trusted-head pending append",
        )
        committed = plain["committed_head"]
        if not isinstance(committed, Mapping):
            raise ValueError("trusted-head committed state is invalid")
        sequence = pending_map["sequence"]
        kind = pending_map["kind"]
        retry_digest = pending_map["retry_material_sha256"]
        if (
            dict(pending_map["prior_head"])
            if isinstance(pending_map["prior_head"], Mapping)
            else None
        ) != dict(committed) or (
            type(sequence) is not int
            or sequence != committed["sequence"] + 1
            or kind
            not in {
                MANUAL_SHADOW_DAY_START_KIND,
                MANUAL_SHADOW_DAY_RESULT_KIND,
                MANUAL_SHADOW_FINAL_REPORT_KIND,
            }
            or not _is_sha256(retry_digest)
            or pending_map["object_id"] != f"{kind}-{retry_digest}"
            or pending_map["admission_route"] != ledger_id
        ):
            raise ValueError("trusted-head pending append is invalid")
        plain["pending_next"] = dict(pending_map)
    plain["committed_head"] = dict(plain["committed_head"])
    return plain


def _read_anchor(parent_fd: int) -> dict[str, object] | None:
    state = _anchor_entry_state(parent_fd)
    if state is None:
        return None
    _require_anchor_file_state(state, label="trusted-head anchor")
    try:
        descriptor = os.open(
            _manual_shadow_anchor_path().name,
            os.O_RDONLY | _NOFOLLOW,
            dir_fd=parent_fd,
        )
    except OSError as exc:
        raise ValueError("trusted-head anchor could not be opened safely") from exc
    try:
        descriptor_state = os.fstat(descriptor)
        _require_anchor_file_state(descriptor_state, label="trusted-head anchor")
        if (state.st_dev, state.st_ino) != (
            descriptor_state.st_dev,
            descriptor_state.st_ino,
        ):
            raise ValueError("trusted-head anchor changed while opening")
        raw = b""
        while True:
            chunk = os.read(descriptor, 64 * 1024)
            if not chunk:
                break
            raw += chunk
            if len(raw) > 1_048_576:
                raise ValueError("trusted-head anchor is too large")
    finally:
        os.close(descriptor)
    try:
        decoded = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonfinite,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError("trusted-head anchor is malformed") from exc
    if not isinstance(decoded, Mapping) or _canonical_bytes(decoded) != raw:
        raise ValueError("trusted-head anchor is noncanonical")
    return _validate_anchor(decoded)


def _write_anchor(parent_fd: int, anchor: Mapping[str, object]) -> None:
    validated = _validate_anchor(anchor)
    payload = _canonical_bytes(validated)
    temp_name = (
        f".manual-shadow-anchor.{os.getpid()}.{threading.get_ident()}."
        f"{time.time_ns()}.tmp"
    )
    descriptor: int | None = None
    try:
        descriptor = os.open(
            temp_name,
            os.O_CREAT | os.O_EXCL | os.O_WRONLY | _NOFOLLOW,
            0o600,
            dir_fd=parent_fd,
        )
        _require_anchor_file_state(os.fstat(descriptor), label="staged trusted-head anchor")
        offset = 0
        while offset < len(payload):
            written = os.write(descriptor, payload[offset:])
            if written <= 0:
                raise OSError("incomplete trusted-head write")
            offset += written
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = None
        os.replace(
            temp_name,
            _manual_shadow_anchor_path().name,
            src_dir_fd=parent_fd,
            dst_dir_fd=parent_fd,
        )
        os.fsync(parent_fd)
    except OSError as exc:
        raise ValueError("trusted-head anchor could not be made durable") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
        with suppress(FileNotFoundError):
            os.unlink(temp_name, dir_fd=parent_fd)


def _initial_anchor() -> dict[str, object]:
    canonical_root = str(_absolute(_manual_shadow_root()))
    ledger_id = hashlib.sha256(
        os.urandom(32) + canonical_root.encode("utf-8")
    ).hexdigest()
    return {
        "schema_version": 1,
        "kind": "manual-shadow-trusted-head",
        "canonical_root": canonical_root,
        "ledger_id": ledger_id,
        "committed_head": {
            "sequence": 0,
            "kind": None,
            "object_id": None,
            "event_sha256": _ZERO_HASH,
            "admission_route": ledger_id,
        },
        "pending_next": None,
    }


def _ledger_entry_state(
    parent_fd: int,
    name: str,
    *,
    label: str,
) -> os.stat_result | None:
    if "/" in name or name in {"", ".", ".."}:
        raise ValueError(f"{label} name is unsafe")
    try:
        return os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise ValueError(f"{label} could not be inspected") from exc


def _require_ledger_directory_state(metadata: os.stat_result, *, label: str) -> None:
    if not stat.S_ISDIR(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
        raise ValueError(f"{label} must be a no-follow directory")


def _require_ledger_file_state(metadata: os.stat_result, *, label: str) -> None:
    if not stat.S_ISREG(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
        raise ValueError(f"{label} must be a regular no-follow file")
    if metadata.st_nlink != 1 or stat.S_IMODE(metadata.st_mode) != 0o600:
        raise ValueError(f"{label} has an unsafe identity or mode")


def _open_ledger_directory(
    parent_fd: int,
    name: str,
    *,
    label: str,
    create: bool,
) -> int | None:
    state = _ledger_entry_state(parent_fd, name, label=label)
    if state is None:
        if not create:
            return None
        try:
            os.mkdir(name, 0o700, dir_fd=parent_fd)
            os.fsync(parent_fd)
        except OSError as exc:
            raise ValueError(f"{label} could not be created safely") from exc
        state = _ledger_entry_state(parent_fd, name, label=label)
    if state is None:
        raise ValueError(f"{label} disappeared")
    _require_ledger_directory_state(state, label=label)
    try:
        descriptor = os.open(
            name,
            os.O_RDONLY | _DIRECTORY | _NOFOLLOW,
            dir_fd=parent_fd,
        )
    except OSError as exc:
        raise ValueError(f"{label} could not be opened safely") from exc
    descriptor_state = os.fstat(descriptor)
    try:
        _require_ledger_directory_state(descriptor_state, label=label)
        if (state.st_dev, state.st_ino) != (
            descriptor_state.st_dev,
            descriptor_state.st_ino,
        ):
            raise ValueError(f"{label} changed while opening")
    except BaseException:
        os.close(descriptor)
        raise
    return descriptor


def _open_manual_shadow_root(parent_fd: int, *, create: bool) -> int | None:
    root = _absolute(_manual_shadow_root())
    anchor_parent = _absolute(_manual_shadow_anchor_path()).parent
    if root.parent != anchor_parent:
        raise ValueError("manual-shadow ledger root is not anchor-adjacent")
    return _open_ledger_directory(
        parent_fd,
        root.name,
        label="manual-shadow ledger root",
        create=create,
    )


def _read_ledger_file(
    parent_fd: int,
    name: str,
    *,
    label: str,
    max_bytes: int,
) -> bytes:
    state = _ledger_entry_state(parent_fd, name, label=label)
    if state is None:
        raise ValueError(f"{label} is missing")
    _require_ledger_file_state(state, label=label)
    try:
        descriptor = os.open(name, os.O_RDONLY | _NOFOLLOW, dir_fd=parent_fd)
    except OSError as exc:
        raise ValueError(f"{label} could not be opened safely") from exc
    try:
        descriptor_state = os.fstat(descriptor)
        _require_ledger_file_state(descriptor_state, label=label)
        if (state.st_dev, state.st_ino) != (
            descriptor_state.st_dev,
            descriptor_state.st_ino,
        ):
            raise ValueError(f"{label} changed while opening")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(descriptor, 64 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > max_bytes:
                raise ValueError(f"{label} is too large")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _write_exclusive_ledger_file(
    parent_fd: int,
    name: str,
    payload: bytes,
    *,
    label: str,
) -> None:
    if _ledger_entry_state(parent_fd, name, label=label) is not None:
        raise ValueError(f"{label} already exists")
    try:
        descriptor = os.open(
            name,
            os.O_CREAT | os.O_EXCL | os.O_WRONLY | _NOFOLLOW,
            0o600,
            dir_fd=parent_fd,
        )
    except OSError as exc:
        raise ValueError(f"{label} could not be created safely") from exc
    try:
        _require_ledger_file_state(os.fstat(descriptor), label=label)
        offset = 0
        while offset < len(payload):
            written = os.write(descriptor, payload[offset:])
            if written <= 0:
                raise OSError(f"incomplete {label} write")
            offset += written
        os.fsync(descriptor)
    except OSError as exc:
        raise ValueError(f"{label} could not be made durable") from exc
    finally:
        os.close(descriptor)
    os.fsync(parent_fd)


def _replay_manual_shadow_ledger(
    parent_fd: int,
    *,
    ledger_id: str,
) -> tuple[
    tuple[EvidenceEnvelope, ...],
    tuple[EvidenceEvent, ...],
    EvidenceJournalHead,
]:
    root_fd = _open_manual_shadow_root(parent_fd, create=False)
    if root_fd is None:
        return (
            (),
            (),
            EvidenceJournalHead(
                sequence=0,
                kind=None,
                object_id=None,
                event_sha256=_ZERO_HASH,
                admission_route=ledger_id,
            ),
        )
    objects_fd: int | None = None
    kind_fds: dict[str, int] = {}
    try:
        try:
            root_entries = set(os.listdir(root_fd))
        except OSError as exc:
            raise ValueError("manual-shadow ledger root could not be listed") from exc
        unknown_root = root_entries - {"events.jsonl", "objects"}
        if unknown_root:
            raise ValueError("manual-shadow ledger contains an unknown root entry")
        if not root_entries:
            return (
                (),
                (),
                EvidenceJournalHead(
                    sequence=0,
                    kind=None,
                    object_id=None,
                    event_sha256=_ZERO_HASH,
                    admission_route=ledger_id,
                ),
            )
        if root_entries != {"events.jsonl", "objects"}:
            raise ValueError("manual-shadow ledger structure is incomplete")

        journal = _read_ledger_file(
            root_fd,
            "events.jsonl",
            label="manual-shadow event journal",
            max_bytes=16 * _MAX_LEDGER_FILE_BYTES,
        )
        if not journal or not journal.endswith(b"\n"):
            raise ValueError("manual-shadow event journal is incomplete")
        raw_lines = journal[:-1].split(b"\n")
        events: list[EvidenceEvent] = []
        expected_previous = _ZERO_HASH
        object_ids: set[str] = set()
        for expected_sequence, line in enumerate(raw_lines, start=1):
            if not line or len(line) > _MAX_LEDGER_FILE_BYTES:
                raise ValueError("manual-shadow event journal line is invalid")
            try:
                decoded = json.loads(
                    line.decode("utf-8"),
                    object_pairs_hook=_reject_duplicate_keys,
                    parse_constant=_reject_nonfinite,
                )
                event = EvidenceEvent.from_dict(decoded)
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
                raise ValueError(
                    f"manual-shadow event journal line {expected_sequence} is invalid"
                ) from exc
            if (
                event.canonical_json_bytes() != line
                or event.sequence != expected_sequence
                or event.previous_event_sha256 != expected_previous
                or event.kind not in _MANUAL_SHADOW_KINDS
                or event.admission_route != ledger_id
                or event.object_id in object_ids
            ):
                raise ValueError("manual-shadow event journal chain is invalid")
            events.append(event)
            object_ids.add(event.object_id)
            expected_previous = hashlib.sha256(line).hexdigest()

        objects_fd = _open_ledger_directory(
            root_fd,
            "objects",
            label="manual-shadow objects directory",
            create=False,
        )
        if objects_fd is None:
            raise ValueError("manual-shadow objects directory is missing")
        try:
            object_kinds = set(os.listdir(objects_fd))
        except OSError as exc:
            raise ValueError("manual-shadow objects directory could not be listed") from exc
        if not object_kinds.issubset(_MANUAL_SHADOW_KINDS):
            raise ValueError("manual-shadow ledger contains an unknown object kind")

        discovered: set[str] = set()
        for kind in sorted(object_kinds):
            kind_fd = _open_ledger_directory(
                objects_fd,
                kind,
                label="manual-shadow object kind directory",
                create=False,
            )
            if kind_fd is None:
                raise ValueError("manual-shadow object kind directory is missing")
            kind_fds[kind] = kind_fd
            try:
                names = tuple(os.listdir(kind_fd))
            except OSError as exc:
                raise ValueError("manual-shadow object kind could not be listed") from exc
            prefix = f"{kind}-"
            for name in names:
                if (
                    not name.startswith(prefix)
                    or not name.endswith(".json")
                    or not _is_sha256(name[len(prefix) : -5])
                ):
                    raise ValueError("manual-shadow ledger contains an unknown object")
                discovered.add(name[:-5])
        if discovered != object_ids:
            raise ValueError("manual-shadow ledger has unadmitted or missing objects")

        envelopes: list[EvidenceEnvelope] = []
        for event in events:
            kind_fd = kind_fds.get(event.kind)
            if kind_fd is None:
                raise ValueError("manual-shadow object kind is missing")
            raw = _read_ledger_file(
                kind_fd,
                f"{event.object_id}.json",
                label="manual-shadow evidence object",
                max_bytes=_MAX_LEDGER_FILE_BYTES,
            )
            try:
                decoded = json.loads(
                    raw.decode("utf-8"),
                    object_pairs_hook=_reject_duplicate_keys,
                    parse_constant=_reject_nonfinite,
                )
                envelope = EvidenceEnvelope.from_dict(decoded)
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
                raise ValueError("manual-shadow evidence object is invalid") from exc
            if (
                envelope.canonical_json_bytes() != raw
                or hashlib.sha256(raw).hexdigest() != event.object_sha256
                or envelope.kind != event.kind
                or envelope.object_id != event.object_id
                or envelope.retry_material_sha256 != event.retry_material_sha256
                or envelope.effective_at != event.effective_at
                or envelope.recorded_at != event.recorded_at
                or envelope.admission_route != ledger_id
            ):
                raise ValueError("manual-shadow event and object binding is invalid")
            envelopes.append(envelope)

        last = events[-1]
        return (
            tuple(envelopes),
            tuple(events),
            EvidenceJournalHead(
                sequence=last.sequence,
                kind=last.kind,
                object_id=last.object_id,
                event_sha256=hashlib.sha256(last.canonical_json_bytes()).hexdigest(),
                admission_route=last.admission_route,
            ),
        )
    finally:
        for descriptor in kind_fds.values():
            os.close(descriptor)
        if objects_fd is not None:
            os.close(objects_fd)
        os.close(root_fd)


def _open_anchored_ledger(
    parent_fd: int,
    *,
    initialize: bool,
) -> tuple[
    dict[str, object],
    tuple[EvidenceEnvelope, ...],
    tuple[EvidenceEvent, ...],
    EvidenceJournalHead,
] | None:
    anchor = _read_anchor(parent_fd)
    if anchor is None:
        root_state = _ledger_entry_state(
            parent_fd,
            _manual_shadow_root().name,
            label="manual-shadow ledger root",
        )
        if root_state is not None:
            raise ValueError("manual-shadow ledger exists without its trusted-head anchor")
        if not initialize:
            return None
        anchor = _initial_anchor()
        _write_anchor(parent_fd, anchor)
    ledger_id = anchor["ledger_id"]
    if not isinstance(ledger_id, str):
        raise ValueError("trusted-head ledger identity is invalid")
    envelopes, events, head = _replay_manual_shadow_ledger(
        parent_fd,
        ledger_id=ledger_id,
    )
    pending = anchor["pending_next"]
    committed = anchor["committed_head"]
    if pending is not None:
        if _head_matches(committed, head):
            anchor["pending_next"] = None
            _write_anchor(parent_fd, anchor)
        else:
            raise ValueError(
                "manual-shadow ledger advanced without a committed trusted head"
            )
    if not _head_matches(anchor["committed_head"], head):
        raise ValueError("manual-shadow ledger rollback or head mismatch")
    return anchor, envelopes, events, head


def _peek_anchored_ledger(
    parent_fd: int,
) -> tuple[
    dict[str, object],
    tuple[EvidenceEnvelope, ...],
    tuple[EvidenceEvent, ...],
    EvidenceJournalHead,
] | None:
    """Validate and replay the anchored ledger without creating or repairing."""

    anchor = _read_anchor(parent_fd)
    if anchor is None:
        root_state = _ledger_entry_state(
            parent_fd,
            _manual_shadow_root().name,
            label="manual-shadow ledger root",
        )
        if root_state is not None:
            raise ValueError("manual-shadow ledger exists without its trusted-head anchor")
        return None
    if anchor["pending_next"] is not None:
        raise ValueError(
            "manual-shadow ledger has an unresolved trusted-head pending append"
        )
    ledger_id = anchor["ledger_id"]
    if not isinstance(ledger_id, str):
        raise ValueError("trusted-head ledger identity is invalid")
    envelopes, events, head = _replay_manual_shadow_ledger(
        parent_fd,
        ledger_id=ledger_id,
    )
    if not _head_matches(anchor["committed_head"], head):
        raise ValueError("manual-shadow ledger rollback or head mismatch")
    return anchor, envelopes, events, head


def _store_envelopes(*, initialize: bool = False) -> tuple[EvidenceEnvelope, ...]:
    with _locked_anchor_parent() as parent_fd:
        opened = _open_anchored_ledger(parent_fd, initialize=initialize)
        if opened is None:
            return ()
        _anchor, envelopes, _events, _head = opened
        return envelopes


def _store_envelopes_readonly() -> tuple[EvidenceEnvelope, ...]:
    """Replay without O_CREAT, anchor repair, or any journal/object/anchor write.

    The admission lock is honored only when it already exists; a missing lock
    proves no admission transaction ever started against this trusted head.
    """

    anchor_path = _absolute(_manual_shadow_anchor_path())
    lock_path = _absolute(_manual_shadow_anchor_lock_path())
    if anchor_path.parent != lock_path.parent:
        raise ValueError("trusted-head paths do not share one parent")
    _reject_symlink_components(anchor_path.parent)
    try:
        parent_fd = os.open(anchor_path.parent, os.O_RDONLY | _DIRECTORY | _NOFOLLOW)
    except OSError as exc:
        raise ValueError("trusted-head parent is missing or unsafe") from exc
    lock_fd: int | None = None
    try:
        try:
            lock_fd = os.open(lock_path.name, os.O_RDONLY | _NOFOLLOW, dir_fd=parent_fd)
        except FileNotFoundError:
            lock_fd = None
        except OSError as exc:
            raise ValueError("trusted-head lock could not be inspected safely") from exc
        try:
            if lock_fd is not None:
                _require_anchor_file_state(os.fstat(lock_fd), label="trusted-head lock")
                fcntl.flock(lock_fd, fcntl.LOCK_SH)
            opened = _peek_anchored_ledger(parent_fd)
        finally:
            if lock_fd is not None:
                try:
                    fcntl.flock(lock_fd, fcntl.LOCK_UN)
                finally:
                    os.close(lock_fd)
    finally:
        os.close(parent_fd)
    if opened is None:
        return ()
    _anchor, envelopes, _events, _head = opened
    return envelopes


def _control_binding(now: dt.datetime) -> tuple[dict[str, object], bool]:
    path = _absolute(_canonical_live_control_path())
    evidence, payload = _read_regular_json(path)
    mapping: dict[str, object] = {
        **evidence,
        "frozen": payload.get("frozen") if isinstance(payload, Mapping) else None,
        "reason": payload.get("reason") if isinstance(payload, Mapping) else None,
        "dead_man_expires_at": payload.get("dead_man_expires_at") if isinstance(payload, Mapping) else None,
        "payload": dict(payload) if isinstance(payload, Mapping) else None,
    }
    return mapping, _valid_control_binding(mapping, now=now)


def _valid_control_binding(value: object, *, now: dt.datetime) -> bool:
    try:
        binding = _require_exact_fields(value, _CONTROL_FIELDS, label="live control binding")
    except ValueError:
        return False
    expected_path = str(_absolute(_canonical_live_control_path()))
    expiry = _parse_timestamp(binding["dead_man_expires_at"])
    payload = _plain_json(binding["payload"])
    return (
        binding["path"] == expected_path
        and binding["status"] == "captured"
        and _is_sha256(binding["sha256"])
        and _is_sha256(binding["canonical_sha256"])
        and type(binding["size_bytes"]) is int
        and binding["size_bytes"] >= 0
        and _parse_timestamp(binding["modified_at"]) is not None
        and isinstance(payload, Mapping)
        and binding["canonical_sha256"] == canonical_json_sha256(payload)
        and binding["frozen"] == payload.get("frozen")
        and binding["reason"] == payload.get("reason")
        and binding["dead_man_expires_at"] == payload.get("dead_man_expires_at")
        and binding["frozen"] is True
        and type(binding["reason"]) is str
        and bool(binding["reason"].strip())
        and expiry is not None
        and expiry > now
    )


def _schedule_binding(
    *,
    captured_at: dt.datetime | None = None,
) -> tuple[dict[str, object], bool]:
    contract = _absolute(_canonical_schedule_contract_path())
    roles = _absolute(_canonical_role_contract_path())
    automations = _absolute(_canonical_automation_root())
    try:
        snapshot = capture_schedule_contract_snapshot(
            contract_path=contract,
            automation_root=automations,
            role_contract_path=roles,
            captured_at=captured_at,
        )
        result = dict(
            evaluate_schedule_contract(
                deployment_phase=PREDEPLOYMENT_PAUSED_PHASE,
                captured_snapshot=snapshot,
            )
        )
        result["deployment_phase"] = PREDEPLOYMENT_PAUSED_PHASE
        source_manifest = schedule_contract_snapshot_manifest(snapshot)
    except Exception as exc:  # noqa: BLE001 - source-read failure is an unsafe schedule proof.
        result = {"error": f"schedule evaluator failed: {type(exc).__name__}"}
        source_manifest = schedule_contract_snapshot_manifest(None)
    binding: dict[str, object] = {
        "contract_path": str(contract),
        "automation_root": str(automations),
        "role_contract_path": str(roles),
        "result": dict(result) if isinstance(result, Mapping) else {"error": "invalid evaluator result"},
        "source_manifest": source_manifest,
        "canonical_sha256": canonical_json_sha256(result),
    }
    return binding, _valid_schedule_binding(binding)


def _valid_schedule_binding(value: object) -> bool:
    try:
        binding = _require_exact_fields(value, _SCHEDULE_FIELDS, label="schedule binding")
    except ValueError:
        return False
    if (
        binding["contract_path"] != str(_absolute(_canonical_schedule_contract_path()))
        or binding["role_contract_path"] != str(_absolute(_canonical_role_contract_path()))
        or binding["automation_root"] != str(_absolute(_canonical_automation_root()))
        or not isinstance(binding["result"], Mapping)
        or _schedule_configuration_identity(binding["source_manifest"]) is None
        or not _is_sha256(binding["canonical_sha256"])
        or binding["canonical_sha256"] != canonical_json_sha256(binding["result"])
    ):
        return False
    source_identity = _schedule_configuration_identity(binding["source_manifest"])
    if source_identity is None:
        return False
    automation_root = str(_absolute(_canonical_automation_root()))
    source_rows = source_identity["automation_tomls"]
    if (
        not isinstance(source_rows, list)
        or source_identity["contract"].get("path") != binding["contract_path"]
        or source_identity["role_contract"].get("path") != binding["role_contract_path"]
        or any(
            row.get("automation_root") != automation_root
            or row.get("path")
            != str(
                _absolute(
                    Path(automation_root)
                    / str(row.get("automation_id"))
                    / "automation.toml"
                )
            )
            for row in source_rows
        )
    ):
        return False
    result = _plain_json(binding["result"])
    if not isinstance(result, Mapping):
        return False
    rows = result.get("automations")
    if not isinstance(rows, list):
        return False
    row_ids = [row.get("automation_id") for row in rows if isinstance(row, Mapping)]
    return (
        result.get("deployment_phase") == PREDEPLOYMENT_PAUSED_PHASE
        and result.get("contract_status") == "pass"
        and result.get("safe_predeployment") is True
        and result.get("deployment_proven") is False
        and type(result.get("automation_count")) is int
        and result["automation_count"] == len(EXPECTED_AUTOMATION_IDS)
        and type(result.get("configured_count")) is int
        and result["configured_count"] == len(EXPECTED_AUTOMATION_IDS)
        and type(result.get("paused_count")) is int
        and result["paused_count"] == len(EXPECTED_AUTOMATION_IDS)
        and result.get("issues") == []
        and len(rows) == len(EXPECTED_AUTOMATION_IDS)
        and len(row_ids) == len(EXPECTED_AUTOMATION_IDS)
        and set(row_ids) == EXPECTED_AUTOMATION_IDS
        and len(set(row_ids)) == 10
        and all(
            isinstance(row, Mapping)
            and row.get("status") == "match"
            and row.get("config_status") == "PAUSED"
            and row.get("mismatches") == []
            for row in rows
        )
    )


def _capture_calendar_evidence(market_date: str) -> dict[str, object]:
    """Capture the canonical read-only calendar response inside Task 3.

    Tests replace this private seam with local fakes.  Production callers do
    not provide calendar mappings, clients, roots, clocks, or validators.
    """

    from cli.main import _alpaca_live_client

    observed_at = _as_utc(_utc_now()).isoformat(timespec="seconds")
    sessions: list[Mapping[str, object]] = []
    try:
        response = _alpaca_live_client().list_calendar(
            start=market_date,
            end=market_date,
        )
        if isinstance(response, list):
            sessions = [item for item in response if isinstance(item, Mapping)]
    except Exception:  # noqa: BLE001 - unavailable calendar evidence fails closed.
        sessions = []
    return {
        "kind": "alpaca_regular_equities_calendar",
        "market_date": market_date,
        "observed_at": observed_at,
        "sessions": sessions,
    }


def _calendar_binding(
    evidence: Mapping[str, object] | None,
    *,
    market_date: str,
) -> dict[str, object]:
    source = dict(evidence) if isinstance(evidence, Mapping) else {}
    return {
        "kind": source.get("kind"),
        "market_date": source.get("market_date"),
        "observed_at": source.get("observed_at"),
        "sessions": source.get("sessions"),
        "canonical_sha256": canonical_json_sha256(source),
    }


def _valid_calendar_binding(value: object, *, market_date: str, now: dt.datetime) -> bool:
    try:
        binding = _require_exact_fields(value, _CALENDAR_FIELDS, label="calendar binding")
    except ValueError:
        return False
    observed_at = _parse_timestamp(binding["observed_at"])
    sessions = _plain_json(binding["sessions"])
    exact_session = (
        isinstance(sessions, list)
        and len(sessions) == 1
        and isinstance(sessions[0], Mapping)
        and sessions[0].get("date") == market_date
    )
    source = {
        "kind": binding["kind"],
        "market_date": binding["market_date"],
        "observed_at": binding["observed_at"],
        "sessions": sessions,
    }
    return (
        binding["canonical_sha256"] == canonical_json_sha256(source)
        and binding["kind"] == "alpaca_regular_equities_calendar"
        and binding["market_date"] == market_date
        and observed_at is not None
        and observed_at <= now
        and _current_central_date(observed_at) == market_date
        and exact_session
    )


def _artifact_binding(path_value: object) -> dict[str, object]:
    if not isinstance(path_value, (str, Path)):
        path: Path | None = None
        evidence: dict[str, object] = {
            "path": None,
            "status": "missing",
            "sha256": None,
            "canonical_sha256": None,
            "size_bytes": None,
            "modified_at": None,
        }
        payload: dict[str, object] | None = None
    else:
        path = _absolute(path_value)
        evidence, payload = _read_regular_json(path)
    return {
        **evidence,
        "kind": payload.get("kind") if isinstance(payload, Mapping) else None,
        "run_id": payload.get("run_id") if isinstance(payload, Mapping) else None,
        "market_date": payload.get("market_date") if isinstance(payload, Mapping) else None,
        "generated_at": payload.get("generated_at") if isinstance(payload, Mapping) else None,
        "payload": dict(payload) if isinstance(payload, Mapping) else None,
    }


def _write_daily_chain_manifest(payload: Mapping[str, object], *, output_dir: Path) -> Path:
    """Publish one local observer manifest without creating a mutable alias."""

    output_dir = _absolute(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    generated_at = _parse_timestamp(payload.get("generated_at")) or _as_utc(_utc_now())
    stem = generated_at.strftime("shadow-daily-chain-%Y%m%d-%H%M%S")
    path = output_dir / f"{stem}-{time.time_ns()}.json"
    raw = _canonical_bytes(payload)
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | _NOFOLLOW, 0o600)
    except OSError as exc:
        raise ValueError("shadow daily-chain manifest could not be created") from exc
    try:
        offset = 0
        while offset < len(raw):
            written = os.write(descriptor, raw[offset:])
            if written <= 0:
                raise OSError("incomplete shadow daily-chain manifest write")
            offset += written
        os.fsync(descriptor)
    except OSError as exc:
        path.unlink(missing_ok=True)
        raise ValueError("shadow daily-chain manifest could not be written") from exc
    finally:
        os.close(descriptor)
    return path


def _paper_order_ids(payload: Mapping[str, object]) -> list[str]:
    submitted = payload.get("submitted")
    if not isinstance(submitted, (list, tuple)):
        return []
    ids: list[str] = []
    for item in submitted:
        if isinstance(item, str):
            ids.append(item)
        elif isinstance(item, Mapping) and isinstance(item.get("id"), str):
            ids.append(item["id"])
    return ids


def create_shadow_day_manifest(
    *,
    start_object_id: str,
    stages: Mapping[str, Path],
    output_dir: str | Path,
) -> tuple[dict[str, object], Path]:
    """Bind the fixed observer-chain files to an admitted pending start.

    This deliberately has no caller-provided clock, root, calendar, control,
    or automation mapping.  The manifest records exactly what was read now;
    adjudication reads all of those files again before it can call a day clean.
    """

    start = load_shadow_record(start_object_id, expected_kind=MANUAL_SHADOW_DAY_START_KIND)
    now, _ = _now_stamp()
    if set(stages) != set(DAILY_CHAIN_STAGES):
        raise ValueError("daily-chain stages must contain the exact required roster")
    if len(set(str(path) for path in stages.values())) != len(DAILY_CHAIN_STAGES):
        raise ValueError("daily-chain stages must use distinct artifact paths")
    bindings = {name: _artifact_binding(stages[name]) for name in DAILY_CHAIN_STAGES}
    control, _ = _control_binding(now)
    schedule, _ = _schedule_binding(captured_at=now)
    paper_payload = bindings["paper_tournament"].get("payload")
    reconciliation_payload = bindings["broker_reconciliation"].get("payload")
    if not isinstance(paper_payload, Mapping):
        paper_payload = {}
    if not isinstance(reconciliation_payload, Mapping):
        reconciliation_payload = {}
    start_payload = start.payload
    payload: dict[str, object] = {
        "kind": "shadow_daily_chain_manifest",
        "generated_at": now.isoformat(timespec="seconds"),
        "shadow_start_object_id": start.object_id,
        "run_id": start_payload["run_id"],
        "market_date": start_payload["market_date"],
        "analysis_only": True,
        "execution_authority": "none",
        "can_submit_orders": False,
        "live_control": control,
        "schedule": schedule,
        "stages": bindings,
        "paper_order_ids": _paper_order_ids(paper_payload),
        "paper_order_count": paper_payload.get("submitted_count"),
        "broker_reconciliation": reconciliation_payload,
    }
    path = _write_daily_chain_manifest(payload, output_dir=Path(output_dir))
    return payload, path


def _manifest_reasons(
    binding: object,
    *,
    start: EvidenceEnvelope,
    now: dt.datetime,
) -> tuple[list[str], list[str]]:
    """Verify the immutable wrapper and every currently reachable stage file."""

    failed: list[str] = []
    incomplete: list[str] = []
    try:
        record = _require_exact_fields(binding, _ARTIFACT_FIELDS, label="daily_chain_manifest artifact binding")
    except ValueError:
        return [], ["daily_chain_manifest_binding_invalid"]
    payload = _plain_json(record["payload"])
    if record["status"] != "captured" or not isinstance(payload, Mapping):
        return [], ["daily_chain_manifest_unreadable_or_unbound"]
    if record["canonical_sha256"] != canonical_json_sha256(payload):
        return [], ["daily_chain_manifest_unreadable_or_unbound"]
    try:
        manifest = _require_exact_fields(payload, _MANIFEST_FIELDS, label="daily-chain manifest")
    except ValueError:
        return ["daily_chain_manifest_schema_invalid"], incomplete
    start_payload = start.payload
    if (
        manifest["kind"] != "shadow_daily_chain_manifest"
        or manifest["shadow_start_object_id"] != start.object_id
        or manifest["run_id"] != start_payload["run_id"]
        or manifest["market_date"] != start_payload["market_date"]
    ):
        failed.append("daily_chain_manifest_start_binding_invalid")
    if not _is_non_authorizing(manifest):
        failed.append("daily_chain_manifest_authority_invalid")
    generated_at = _parse_timestamp(manifest["generated_at"])
    start_at = _parse_timestamp(start.recorded_at) or now
    if generated_at is None or generated_at < start_at or generated_at > now:
        incomplete.append("daily_chain_manifest_timestamp_out_of_window")
    control = manifest["live_control"]
    schedule = manifest["schedule"]
    if not _valid_control_binding(control, now=now) or not isinstance(control, Mapping) or control.get("sha256") != start_payload["live_control"].get("sha256"):
        failed.append("daily_chain_manifest_live_control_invalid")
    if (
        not _valid_schedule_binding(schedule)
        or not isinstance(schedule, Mapping)
        or schedule.get("canonical_sha256")
        != start_payload["schedule"].get("canonical_sha256")
        or _schedule_configuration_identity(schedule.get("source_manifest"))
        != _schedule_configuration_identity(
            start_payload["schedule"].get("source_manifest")
        )
    ):
        failed.append("daily_chain_manifest_schedule_invalid")
    stages = manifest["stages"]
    if not isinstance(stages, Mapping) or set(stages) != set(DAILY_CHAIN_STAGES):
        return [*failed, "daily_chain_manifest_stage_roster_invalid"], incomplete
    sentinel_source_bindings: dict[str, object] = {
        "live_control": control,
        "schedule_configuration": (
            schedule.get("source_manifest") if isinstance(schedule, Mapping) else None
        ),
        "schedule_check": (
            schedule.get("result") if isinstance(schedule, Mapping) else None
        ),
        "preopen_validation": stages["preopen_validation"],
    }
    for stage in DAILY_CHAIN_STAGES:
        value = stages[stage]
        try:
            stage_record = _require_exact_fields(value, _ARTIFACT_FIELDS, label=f"{stage} stage binding")
        except ValueError:
            incomplete.append(f"{stage}_stage_binding_invalid")
            continue
        path = stage_record["path"]
        current = _artifact_binding(path)
        # File mtimes have one-second filesystem resolution and may advance
        # while a manifest is being published.  Identity is the no-follow
        # path plus exact raw/canonical hashes and size, not that incidental
        # timestamp formatting detail.
        identity_keys = ("path", "status", "sha256", "canonical_sha256", "size_bytes", "payload")
        if any(current.get(key) != stage_record.get(key) for key in identity_keys):
            failed.append(f"{stage}_stage_hash_or_path_changed")
            continue
        stage_payload = _plain_json(stage_record["payload"])
        if stage_record["status"] != "captured" or not isinstance(stage_payload, Mapping):
            incomplete.append(f"{stage}_stage_unreadable")
            continue
        stage_time = _parse_timestamp(stage_record["generated_at"])
        if stage_time is None or stage_time < start_at or stage_time > now:
            incomplete.append(f"{stage}_stage_timestamp_invalid")
        # Existing persisted producers are intentionally not force-shaped into
        # a synthetic common packet.  Require the native safe semantics for
        # each role, including explicit dry-run evidence for hourly work.
        failed.extend(
            _stage_semantic_reasons(
                stage,
                stage_payload,
                sentinel_source_bindings=(
                    sentinel_source_bindings if stage == "safety_sentinel" else None
                ),
            )
        )
        stage_status = stage_payload.get("status")
        if stage_status is not None and (type(stage_status) is not str or not stage_status.strip()):
            failed.append(f"{stage}_stage_status_invalid")
        # Explicitly bound producer packets are required where the run has an
        # authority-sensitive boundary.  Other observer packets are bound by
        # this authenticated manifest and their exact file identities.
        if stage in {"safety_sentinel", "paper_tournament", "broker_reconciliation"} and (
            stage_payload.get("run_id") != start_payload["run_id"]
            or stage_payload.get("market_date") != start_payload["market_date"]
            or stage_payload.get("shadow_start_object_id") != start.object_id
        ):
            failed.append(f"{stage}_stage_cross_run")
    reconciliation = manifest["broker_reconciliation"]
    if not isinstance(reconciliation, Mapping) or reconciliation.get("kind") != "broker_reconciliation_observer" or reconciliation.get("read_only") is not True or reconciliation.get("submitted_count") != 0 or reconciliation.get("cancelled_count") != 0 or not _is_non_authorizing(reconciliation):
        failed.append("broker_reconciliation_invalid")
    paper = stages.get("paper_tournament") if isinstance(stages, Mapping) else None
    paper_payload = paper.get("payload") if isinstance(paper, Mapping) else None
    paper_order_ids = manifest["paper_order_ids"]
    if (
        not isinstance(paper_payload, Mapping)
        or type(manifest["paper_order_count"]) is not int
        or manifest["paper_order_count"] < 0
        or not isinstance(paper_order_ids, list)
        or any(type(order_id) is not str or not order_id for order_id in paper_order_ids)
        or manifest["paper_order_count"] != paper_payload.get("submitted_count")
        or paper_order_ids != _paper_order_ids(paper_payload)
    ):
        failed.append("paper_order_manifest_mismatch")
    return sorted(set(failed)), sorted(set(incomplete))


def _artifact_reasons(
    key: str,
    binding: object,
    *,
    run_id: str,
    market_date: str,
    start_at: dt.datetime,
    now: dt.datetime,
) -> tuple[list[str], list[str]]:
    failed: list[str] = []
    incomplete: list[str] = []
    try:
        record = _require_exact_fields(binding, _ARTIFACT_FIELDS, label=f"{key} artifact binding")
    except ValueError:
        return [], [f"{key}_binding_invalid"]
    payload = _plain_json(record["payload"])
    if (
        record["status"] != "captured"
        or not _is_sha256(record["sha256"])
        or not _is_sha256(record["canonical_sha256"])
        or type(record["size_bytes"]) is not int
        or record["size_bytes"] < 0
        or _parse_timestamp(record["modified_at"]) is None
        or not isinstance(payload, Mapping)
        or record["canonical_sha256"] != canonical_json_sha256(payload)
    ):
        return [], [f"{key}_unreadable_or_unbound"]
    if key == "daily_chain_manifest":
        expected_kind = "shadow_daily_chain_manifest"
    else:
        expected_kind = "safety_sentinel_audit" if key == "safety_sentinel" else "paper_tournament_run"
    if record["kind"] != expected_kind or payload.get("kind") != expected_kind:
        failed.append(f"{key}_kind_invalid")
    if record["run_id"] != run_id or payload.get("run_id") != run_id:
        failed.append(f"{key}_cross_run")
    if record["market_date"] != market_date or payload.get("market_date") != market_date:
        failed.append(f"{key}_market_date_mismatch")
    if not _is_non_authorizing(payload):
        failed.append(f"{key}_authority_invalid")
    generated_at = _parse_timestamp(record["generated_at"])
    if generated_at is None or payload.get("generated_at") != record["generated_at"]:
        incomplete.append(f"{key}_timestamp_invalid")
    elif generated_at < start_at or generated_at > now or _current_central_date(generated_at) != market_date:
        incomplete.append(f"{key}_timestamp_out_of_window")
    if key == "daily_chain_manifest":
        return failed, incomplete
    if key == "safety_sentinel":
        if payload.get("status") not in {"FROZEN", "HOLD"}:
            failed.append("safety_sentinel_not_frozen_or_hold")
    else:
        count = payload.get("submitted_count")
        if type(count) is not int or count < 0:
            failed.append("paper_tournament_submission_count_invalid")
        elif not isinstance(payload.get("submitted"), (list, tuple)) or len(payload["submitted"]) != count:
            failed.append("paper_tournament_submissions_invalid")
        if payload.get("status") not in {"HOLD", "NO_PAPER_SIGNAL", "COMPLETE"}:
            failed.append("paper_tournament_status_invalid")
        if payload.get("status") in {"HOLD", "NO_PAPER_SIGNAL"} and count != 0:
            failed.append("paper_tournament_hold_has_submissions")
    return failed, incomplete


def _start_spec(previous: EvidenceEnvelope | None) -> tuple[str, str, str | None]:
    if previous is None:
        return "qualification_pending", "qualification", None
    payload = previous.payload
    if payload.get("status") != "clean":
        return "repair_in_progress", "repair", previous.object_id
    phase = payload.get("phase")
    if phase == "repair_in_progress":
        return "qualification_pending", "qualification", previous.object_id
    if phase in {"qualification_clean", "five_day_trial"}:
        return "five_day_trial", "trial", previous.object_id
    raise ValueError("shadow ledger cannot start after terminal trial")


def _day_phase(
    *,
    start: EvidenceEnvelope,
    status: str,
    earlier_days: tuple[EvidenceEnvelope, ...],
) -> str:
    if status != "clean":
        return "repair_required"
    role = start.payload["role"]
    if role == "qualification":
        return "qualification_clean"
    if role == "repair":
        return "repair_in_progress"
    trial_count = 0
    for day in reversed(earlier_days):
        prior = day.payload
        if (
            prior.get("status") == "clean"
            and prior.get("phase") == "qualification_clean"
        ):
            break
        if (
            prior.get("status") == "clean"
            and prior.get("phase") in {"five_day_trial", "trial_complete"}
        ):
            trial_count += 1
    return "trial_complete" if trial_count == 4 else "five_day_trial"


def _validate_start_envelope(envelope: EvidenceEnvelope, *, now: dt.datetime) -> None:
    payload = _require_exact_fields(envelope.payload, _START_FIELDS, label="shadow start payload")
    if payload["payload_schema"] != START_SCHEMA:
        raise ValueError("shadow start payload schema is invalid")
    _require_text(payload["run_id"], label="shadow start run_id")
    market_date = payload["market_date"]
    if _parse_market_date(market_date) is None:
        raise ValueError("shadow start market date is invalid")
    recorded_at = _parse_timestamp(envelope.recorded_at)
    effective_at = _parse_timestamp(envelope.effective_at)
    if (
        recorded_at is None
        or effective_at is None
        or recorded_at > now
        or _current_central_date(recorded_at) != market_date
        or _current_central_date(effective_at) != market_date
    ):
        raise ValueError("shadow start is backfilled or future")
    if not _valid_control_binding(payload["live_control"], now=recorded_at):
        raise ValueError("shadow start live control proof is invalid")
    if not _valid_schedule_binding(payload["schedule"]):
        raise ValueError("shadow start schedule proof is invalid")
    if not _valid_calendar_binding(payload["calendar"], market_date=market_date, now=recorded_at):
        raise ValueError("shadow start calendar proof is invalid")


def _evaluate_day_payload(
    start: EvidenceEnvelope,
    payload: Mapping[str, object],
    *,
    now: dt.datetime,
) -> tuple[list[str], list[str]]:
    failed: list[str] = []
    incomplete: list[str] = []
    start_payload = start.payload
    if payload["start_object_id"] != start.object_id:
        failed.append("start_reference_invalid")
    for field in ("run_id", "market_date", "role", "predecessor_object_id"):
        if payload[field] != start_payload[field]:
            failed.append(f"{field}_start_binding_mismatch")
    closure_kind = payload["closure_kind"]
    if closure_kind == "operator_abort":
        failed.append(OPERATOR_ABORT_REASON)
    elif closure_kind == "pending_expired":
        incomplete.append(PENDING_DAY_EXPIRED_REASON)
    elif closure_kind is not None:
        failed.append("shadow_day_closure_kind_invalid")
    market_date = start_payload["market_date"]
    if not isinstance(market_date, str):
        return ["start_market_date_invalid"], incomplete
    if _current_central_date(now) != market_date:
        incomplete.append("current_central_date_mismatch")
    control = payload["live_control"]
    if not _valid_control_binding(control, now=now):
        failed.append("live_control_not_frozen_or_malformed")
    elif not isinstance(control, Mapping) or control.get("sha256") != start_payload["live_control"].get("sha256"):
        failed.append("live_control_hash_changed")
    schedule = payload["schedule"]
    if not _valid_schedule_binding(schedule):
        failed.append("schedule_contract_not_exact_ten_paused")
    elif (
        not isinstance(schedule, Mapping)
        or schedule.get("canonical_sha256")
        != start_payload["schedule"].get("canonical_sha256")
        or _schedule_configuration_identity(schedule.get("source_manifest"))
        != _schedule_configuration_identity(
            start_payload["schedule"].get("source_manifest")
        )
    ):
        failed.append("schedule_evaluation_hash_changed")
    if not _valid_calendar_binding(payload["calendar"], market_date=market_date, now=now):
        incomplete.append("calendar_evidence_unavailable_or_invalid")
    artifacts = payload["artifacts"]
    if not isinstance(artifacts, Mapping) or set(artifacts) != set(ARTIFACT_KEYS):
        incomplete.append("artifact_roster_invalid")
    else:
        start_at = _parse_timestamp(start.recorded_at) or now
        run_id = start_payload["run_id"]
        if not isinstance(run_id, str):
            failed.append("start_run_id_invalid")
        else:
            for key in ARTIFACT_KEYS:
                item_failed, item_incomplete = _artifact_reasons(
                    key,
                    artifacts[key],
                    run_id=run_id,
                    market_date=market_date,
                    start_at=start_at,
                    now=now,
                )
                failed.extend(item_failed)
                incomplete.extend(item_incomplete)
            manifest_failed, manifest_incomplete = _manifest_reasons(
                artifacts["daily_chain_manifest"],
                start=start,
                now=now,
            )
            failed.extend(manifest_failed)
            incomplete.extend(manifest_incomplete)
    return sorted(set(failed)), sorted(set(incomplete))


def _validate_day_envelope(
    envelope: EvidenceEnvelope,
    *,
    start: EvidenceEnvelope,
    earlier_days: tuple[EvidenceEnvelope, ...],
    now: dt.datetime,
) -> None:
    payload = _require_exact_fields(envelope.payload, _DAY_FIELDS, label="shadow day payload")
    if payload["payload_schema"] != DAY_SCHEMA:
        raise ValueError("shadow day payload schema is invalid")
    recorded_at = _parse_timestamp(envelope.recorded_at)
    if recorded_at is None or recorded_at > now:
        raise ValueError("shadow day is backfilled or future")
    market_date = payload["market_date"]
    if _parse_market_date(market_date) is None:
        raise ValueError("shadow day date is invalid")
    closure_kind = payload["closure_kind"]
    stopped_at_stage = payload["stopped_at_stage"]
    notes = payload["notes"]
    recorded_central_date = _current_central_date(recorded_at)
    if closure_kind is None:
        if stopped_at_stage is not None or notes is not None:
            raise ValueError("unclosed shadow day carries operator closure fields")
        if recorded_central_date != market_date:
            raise ValueError("shadow day date is invalid")
    elif closure_kind == "operator_abort":
        if (
            stopped_at_stage not in SHADOW_DAY_STOP_STAGES
            or type(notes) is not str
            or not notes.strip()
            or len(notes) > ABORT_NOTES_LIMIT
        ):
            raise ValueError("aborted shadow day stop stage or notes are invalid")
        if recorded_central_date != market_date:
            raise ValueError("aborted shadow day must close on its own Central date")
    elif closure_kind == "pending_expired":
        if stopped_at_stage is not None or notes is not None:
            raise ValueError("expired shadow day carries operator closure fields")
        if recorded_central_date <= market_date:
            raise ValueError("expired shadow day must close after its market date")
    else:
        raise ValueError("shadow day closure kind is invalid")
    if not isinstance(payload["reasons"], (list, tuple)) or any(type(item) is not str for item in payload["reasons"]):
        raise ValueError("shadow day reasons are invalid")
    failed, incomplete = _evaluate_day_payload(start, payload, now=recorded_at)
    expected_status = "failed" if failed else ("incomplete" if incomplete else "clean")
    if payload["status"] != expected_status:
        raise ValueError("shadow day status does not match bound evidence")
    expected_reasons = sorted(set([*failed, *incomplete]))
    if list(payload["reasons"]) != expected_reasons:
        raise ValueError("shadow day reasons do not match bound evidence")
    expected_phase = _day_phase(start=start, status=expected_status, earlier_days=earlier_days)
    if payload["phase"] != expected_phase:
        raise ValueError("shadow day phase does not match state transition")


def _candidate_state(days: tuple[EvidenceEnvelope, ...]) -> tuple[bool, int]:
    if len(days) < 6:
        return False, 0
    terminal = days[-1].payload
    if terminal.get("status") != "clean" or terminal.get("phase") != "trial_complete":
        return False, 0
    trials = days[-5:]
    if any(day.payload.get("status") != "clean" for day in trials):
        return False, 0
    if [day.payload.get("phase") for day in trials] != [
        "five_day_trial",
        "five_day_trial",
        "five_day_trial",
        "five_day_trial",
        "trial_complete",
    ]:
        return False, 0
    qualification = days[-6].payload
    if qualification.get("status") != "clean" or qualification.get("phase") != "qualification_clean":
        return False, 0
    return True, 5


def _LedgerState(envelopes: tuple[EvidenceEnvelope, ...], *, now: dt.datetime) -> tuple[tuple[EvidenceEnvelope, ...], EvidenceEnvelope | None, EvidenceEnvelope | None, EvidenceEnvelope | None]:
    """Replay all admitted events; return day events, pending start, last day, report."""

    days: list[EvidenceEnvelope] = []
    pending: EvidenceEnvelope | None = None
    last_day: EvidenceEnvelope | None = None
    report: EvidenceEnvelope | None = None
    dates: set[str] = set()
    for envelope in envelopes:
        if envelope.kind == MANUAL_SHADOW_DAY_START_KIND:
            if report is not None or pending is not None:
                raise ValueError("shadow ledger has an invalid start transition")
            _validate_start_envelope(envelope, now=now)
            payload = envelope.payload
            market_date = payload["market_date"]
            if not isinstance(market_date, str) or market_date in dates:
                raise ValueError("shadow ledger has duplicate market date")
            phase, role, predecessor = _start_spec(last_day)
            if payload["phase"] != phase or payload["role"] != role or payload["predecessor_object_id"] != predecessor:
                raise ValueError("shadow ledger start predecessor transition is invalid")
            pending = envelope
        elif envelope.kind == MANUAL_SHADOW_DAY_RESULT_KIND:
            if report is not None or pending is None:
                raise ValueError("shadow ledger has an unbound day result")
            _validate_day_envelope(envelope, start=pending, earlier_days=tuple(days), now=now)
            payload = envelope.payload
            market_date = payload["market_date"]
            if not isinstance(market_date, str) or market_date in dates:
                raise ValueError("shadow ledger has duplicate market date")
            dates.add(market_date)
            days.append(envelope)
            last_day = envelope
            pending = None
        elif envelope.kind == MANUAL_SHADOW_FINAL_REPORT_KIND:
            if report is not None or pending is not None:
                raise ValueError("shadow ledger final report is not terminal")
            report = envelope
        else:
            raise ValueError("shadow ledger contains a disallowed evidence kind")
    if report is not None:
        _validate_report_envelope(report, days=tuple(days), now=now)
    return tuple(days), pending, last_day, report


def _validate_report_envelope(
    envelope: EvidenceEnvelope,
    *,
    days: tuple[EvidenceEnvelope, ...],
    now: dt.datetime,
) -> None:
    payload = _require_exact_fields(envelope.payload, _REPORT_FIELDS, label="shadow report payload")
    if payload["payload_schema"] != REPORT_SCHEMA:
        raise ValueError("shadow report payload schema is invalid")
    recorded_at = _parse_timestamp(envelope.recorded_at)
    if recorded_at is None or recorded_at > now or not days:
        raise ValueError("shadow report timestamp or ledger is invalid")
    candidate, streak = _candidate_state(days)
    expected = {
        "ledger_head_object_id": days[-1].object_id,
        "day_object_ids": [day.object_id for day in days],
        "status": "candidate" if candidate else "no_go",
        "phase": "readiness_candidate" if candidate else "readiness_no_go",
        "clean_trial_streak": streak if candidate else 0,
        "required_clean_trial_days": 5,
        "reasons": [] if candidate else ["full_ledger_not_terminal_candidate"],
    }
    for key, expected_value in expected.items():
        actual_value = list(payload[key]) if key in {"day_object_ids", "reasons"} and isinstance(payload[key], tuple) else payload[key]
        if actual_value != expected_value:
            raise ValueError("shadow report does not match complete ledger")


def _validate_semantic_envelope(
    snapshot: tuple[EvidenceEnvelope, ...],
    candidate: EvidenceEnvelope,
) -> None:
    """Validate one facade-constructed envelope against the complete replay."""

    now = _as_utc(_utc_now())
    days, pending, last_day, report = _LedgerState(snapshot, now=now)
    if candidate.kind == MANUAL_SHADOW_DAY_START_KIND:
        if pending is not None or report is not None:
            raise ValueError("shadow ledger does not allow another start")
        _validate_start_envelope(candidate, now=now)
        expected_phase, expected_role, expected_parent = _start_spec(last_day)
        candidate_payload = candidate.payload
        if (
            candidate_payload["phase"] != expected_phase
            or candidate_payload["role"] != expected_role
            or candidate_payload["predecessor_object_id"] != expected_parent
            or candidate_payload["market_date"]
            in {day.payload["market_date"] for day in days}
        ):
            raise ValueError("shadow start transition is invalid")
        return
    if candidate.kind == MANUAL_SHADOW_DAY_RESULT_KIND:
        if report is not None or pending is None:
            raise ValueError("shadow start already has a day successor")
        _validate_day_envelope(candidate, start=pending, earlier_days=days, now=now)
        return
    if candidate.kind == MANUAL_SHADOW_FINAL_REPORT_KIND:
        if pending is not None or report is not None or not days:
            raise ValueError("shadow ledger is not reportable")
        _validate_report_envelope(candidate, days=days, now=now)
        return
    raise ValueError("reserved manual-shadow admission kind is invalid")


def _require_known_start(envelopes: tuple[EvidenceEnvelope, ...], object_id: str) -> EvidenceEnvelope:
    for envelope in envelopes:
        if envelope.object_id == object_id and envelope.kind == MANUAL_SHADOW_DAY_START_KIND:
            return envelope
    raise ValueError("shadow start record is not an admitted ledger object")


def _record_view(envelope: EvidenceEnvelope, *, path: Path | None = None) -> dict[str, object]:
    plain_payload = _plain_json(envelope.payload)
    if not isinstance(plain_payload, dict):
        raise ValueError("shadow record payload is invalid")
    view = plain_payload
    view.update(
        {
            "schema_version": envelope.schema_version,
            "kind": envelope.kind,
            "object_id": envelope.object_id,
            "effective_at": envelope.effective_at,
            "recorded_at": envelope.recorded_at,
            "analysis_only": envelope.analysis_only,
            "execution_authority": envelope.execution_authority,
            "can_submit_orders": envelope.can_submit_orders,
        }
    )
    if path is not None:
        view["record_path"] = str(path)
    return view


def admitted_shadow_record_view(admission: EvidenceAdmission) -> dict[str, object]:
    """Render a just-admitted immutable shadow object for analysis-only CLI output."""

    if not isinstance(admission, EvidenceAdmission):
        raise ValueError("shadow admission is invalid")
    return _record_view(admission.envelope, path=admission.path)


def load_shadow_record(object_id: str, *, expected_kind: str | None = None) -> EvidenceEnvelope:
    """Load one exact object only after verifying the pinned store journal."""

    if type(object_id) is not str or not object_id:
        raise ValueError("shadow record identity is invalid")
    envelopes = _store_envelopes()
    _LedgerState(envelopes, now=_as_utc(_utc_now()))
    matches = [item for item in envelopes if item.object_id == object_id]
    if len(matches) != 1:
        raise ValueError("shadow record is not an admitted ledger object")
    record = matches[0]
    if expected_kind is not None and record.kind != expected_kind:
        raise ValueError("shadow record kind is invalid")
    return record


def create_shadow_day_start_manifest(
    *,
    run_id: str,
    market_date: str,
    predecessor_object_id: str | None = None,
) -> EvidenceAdmission:
    """Admit a current-day start only from the canonical local source helpers."""

    now, effective_at = _now_stamp()
    _require_text(run_id, label="run_id")
    if _parse_market_date(market_date) is None:
        raise ValueError("market_date is invalid")
    if market_date != _current_central_date(now):
        raise ValueError("market_date must be the current Central date")
    control, control_valid = _control_binding(now)
    if not control_valid:
        raise ValueError("live control gate failed")
    schedule, schedule_valid = _schedule_binding(captured_at=now)
    if not schedule_valid:
        raise ValueError("schedule gate failed")
    calendar = _calendar_binding(
        _capture_calendar_evidence(market_date),
        market_date=market_date,
    )
    if not _valid_calendar_binding(calendar, market_date=market_date, now=now):
        raise ValueError("calendar gate failed")
    prior = _store_envelopes(initialize=True)
    days, pending, last_day, report = _LedgerState(prior, now=now)
    if pending is not None or report is not None:
        raise ValueError("shadow ledger does not allow another start")
    phase, role, expected_predecessor = _start_spec(last_day)
    if predecessor_object_id != expected_predecessor:
        raise ValueError("shadow predecessor record is missing or invalid")
    payload: dict[str, object] = {
        "payload_schema": START_SCHEMA,
        "run_id": run_id,
        "market_date": market_date,
        "role": role,
        "phase": phase,
        "predecessor_object_id": predecessor_object_id,
        "live_control": control,
        "schedule": schedule,
        "calendar": calendar,
    }

    return _admit_shadow_envelope(
        kind=MANUAL_SHADOW_DAY_START_KIND,
        payload=payload,
        now=now,
        effective_at=effective_at,
    )


def _admit_shadow_envelope(
    *,
    kind: str,
    payload: Mapping[str, object],
    now: dt.datetime,
    effective_at: str,
) -> EvidenceAdmission:
    """Run the single anchored admission transaction for one semantic facade.

    Every shadow facade reuses exactly this append path: locked trusted head,
    replay validation, semantic candidate validation, exclusive object write,
    journaled event append, committed-head advance, and rollback detection.
    """

    try:
        with _locked_anchor_parent() as parent_fd:
            opened = _open_anchored_ledger(parent_fd, initialize=True)
            if opened is None:  # pragma: no cover - initialize=True always opens.
                raise ValueError("trusted-head anchor initialization failed")
            anchor, envelopes, _events, head = opened
            _LedgerState(envelopes, now=now)
            ledger_id = anchor["ledger_id"]
            if not isinstance(ledger_id, str):
                raise ValueError("trusted-head ledger identity is invalid")
            retry_digest = hashlib.sha256(
                _retry_material_bytes(
                    kind=kind,
                    effective_at=effective_at,
                    payload=payload,
                )
            ).hexdigest()
            envelope = EvidenceEnvelope(
                kind=kind,
                object_id=f"{kind}-{retry_digest}",
                effective_at=effective_at,
                recorded_at=effective_at,
                retry_material_sha256=retry_digest,
                payload_sha256=hashlib.sha256(_payload_bytes(payload)).hexdigest(),
                payload=payload,
                admission_route=ledger_id,
            )
            # Keep admission inside this semantic facade.  A reusable
            # candidate appender would recreate the rejected raw route.
            _validate_semantic_envelope(envelopes, envelope)
            envelope_bytes = envelope.canonical_json_bytes()
            event = EvidenceEvent(
                sequence=head.sequence + 1,
                kind=envelope.kind,
                object_id=envelope.object_id,
                object_sha256=hashlib.sha256(envelope_bytes).hexdigest(),
                retry_material_sha256=envelope.retry_material_sha256,
                effective_at=envelope.effective_at,
                recorded_at=envelope.recorded_at,
                previous_event_sha256=head.event_sha256,
                admission_route=ledger_id,
            )
            pending_next = {
                "prior_head": _head_mapping(head),
                "sequence": event.sequence,
                "kind": event.kind,
                "object_id": event.object_id,
                "retry_material_sha256": event.retry_material_sha256,
                "admission_route": ledger_id,
            }
            anchor["pending_next"] = pending_next
            _write_anchor(parent_fd, anchor)

            root_fd = _open_manual_shadow_root(parent_fd, create=True)
            if root_fd is None:  # pragma: no cover - create=True always opens.
                raise ValueError("manual-shadow ledger root could not be opened")
            objects_fd: int | None = None
            kind_fd: int | None = None
            try:
                objects_fd = _open_ledger_directory(
                    root_fd,
                    "objects",
                    label="manual-shadow objects directory",
                    create=True,
                )
                if objects_fd is None:  # pragma: no cover - create=True always opens.
                    raise ValueError("manual-shadow objects directory is missing")
                kind_fd = _open_ledger_directory(
                    objects_fd,
                    envelope.kind,
                    label="manual-shadow object kind directory",
                    create=True,
                )
                if kind_fd is None:  # pragma: no cover - create=True always opens.
                    raise ValueError("manual-shadow object kind directory is missing")
                _write_exclusive_ledger_file(
                    kind_fd,
                    f"{envelope.object_id}.json",
                    envelope_bytes,
                    label="manual-shadow evidence object",
                )
                line = event.canonical_json_bytes() + b"\n"
                if len(line) - 1 > _MAX_LEDGER_FILE_BYTES:
                    raise ValueError("manual-shadow event journal line is too large")
                state = _ledger_entry_state(
                    root_fd,
                    "events.jsonl",
                    label="manual-shadow event journal",
                )
                if state is not None:
                    _require_ledger_file_state(
                        state,
                        label="manual-shadow event journal",
                    )
                journal_fd = os.open(
                    "events.jsonl",
                    os.O_APPEND | os.O_CREAT | os.O_WRONLY | _NOFOLLOW,
                    0o600,
                    dir_fd=root_fd,
                )
                try:
                    journal_state = os.fstat(journal_fd)
                    _require_ledger_file_state(
                        journal_state,
                        label="manual-shadow event journal",
                    )
                    current_state = _ledger_entry_state(
                        root_fd,
                        "events.jsonl",
                        label="manual-shadow event journal",
                    )
                    if current_state is None or (
                        current_state.st_dev,
                        current_state.st_ino,
                    ) != (journal_state.st_dev, journal_state.st_ino):
                        raise ValueError(
                            "manual-shadow event journal changed while opening"
                        )
                    offset = 0
                    while offset < len(line):
                        written = os.write(journal_fd, line[offset:])
                        if written <= 0:
                            raise OSError("incomplete manual-shadow event write")
                        offset += written
                    os.fsync(journal_fd)
                finally:
                    os.close(journal_fd)
                os.fsync(root_fd)
            finally:
                if kind_fd is not None:
                    os.close(kind_fd)
                if objects_fd is not None:
                    os.close(objects_fd)
                os.close(root_fd)

            current, _current_events, current_head = _replay_manual_shadow_ledger(
                parent_fd,
                ledger_id=ledger_id,
            )
            _LedgerState(current, now=now)
            if not (
                current_head.sequence == pending_next["sequence"]
                and current_head.kind == pending_next["kind"]
                and current_head.object_id == pending_next["object_id"]
                and current_head.admission_route == ledger_id
            ):
                raise ValueError("shadow ledger admission did not reach the anchored head")
            anchor["committed_head"] = _head_mapping(current_head)
            anchor["pending_next"] = None
            _write_anchor(parent_fd, anchor)
            return EvidenceAdmission(
                envelope=envelope,
                path=(
                    _absolute(_manual_shadow_root())
                    / "objects"
                    / envelope.kind
                    / f"{envelope.object_id}.json"
                ),
                event=event,
                created=True,
            )
    except (OSError, StrategyEvidenceStoreError) as exc:
        raise ValueError(f"shadow ledger admission failed: {exc}") from exc


def adjudicate_shadow_day(
    *,
    start_object_id: str,
    artifacts: Mapping[str, Path] | None,
) -> EvidenceAdmission:
    """Admit exactly one current-day result for an authenticated pending start."""

    now, effective_at = _now_stamp()
    prior = _store_envelopes()
    days, pending, _last_day, report = _LedgerState(prior, now=now)
    if report is not None or pending is None or pending.object_id != start_object_id:
        raise ValueError("shadow start has no admissible pending transition")
    start = _require_known_start(prior, start_object_id)
    start_payload = start.payload
    market_date = start_payload["market_date"]
    run_id = start_payload["run_id"]
    if not isinstance(market_date, str) or not isinstance(run_id, str):
        raise ValueError("shadow start payload is invalid")
    if _current_central_date(now) != market_date:
        raise ValueError("shadow day must be adjudicated on its current Central date")
    control, _ = _control_binding(now)
    schedule, _ = _schedule_binding(captured_at=now)
    calendar = _calendar_binding(
        _capture_calendar_evidence(market_date),
        market_date=market_date,
    )
    artifact_paths = artifacts if isinstance(artifacts, Mapping) else {}
    artifact_bindings = {key: _artifact_binding(artifact_paths.get(key)) for key in ARTIFACT_KEYS}
    provisional: dict[str, object] = {
        "payload_schema": DAY_SCHEMA,
        "start_object_id": start.object_id,
        "run_id": run_id,
        "market_date": market_date,
        "role": start_payload["role"],
        "status": "incomplete",
        "phase": "repair_required",
        "predecessor_object_id": start_payload["predecessor_object_id"],
        "live_control": control,
        "schedule": schedule,
        "calendar": calendar,
        "artifacts": artifact_bindings,
        "reasons": [],
        "closure_kind": None,
        "stopped_at_stage": None,
        "notes": None,
    }
    failed, incomplete = _evaluate_day_payload(start, provisional, now=now)
    unknown_artifacts = set(artifact_paths) - set(ARTIFACT_KEYS)
    if unknown_artifacts:
        incomplete.append("unknown_artifact_keys")
    status = "failed" if failed else ("incomplete" if incomplete else "clean")
    provisional["status"] = status
    provisional["phase"] = _day_phase(start=start, status=status, earlier_days=days)
    provisional["reasons"] = sorted(set([*failed, *incomplete]))

    return _admit_shadow_envelope(
        kind=MANUAL_SHADOW_DAY_RESULT_KIND,
        payload=provisional,
        now=now,
        effective_at=effective_at,
    )


def _closure_day_payload(
    *,
    start: EvidenceEnvelope,
    start_payload: Mapping[str, object],
    days: tuple[EvidenceEnvelope, ...],
    now: dt.datetime,
    closure_kind: str,
    stopped_at_stage: str | None,
    notes: str | None,
    artifact_paths: Mapping[str, Path] | None,
) -> dict[str, object]:
    """Build one terminal non-clean day payload bound to current local proof.

    Fresh control, schedule, and calendar captures are bound at closure time;
    artifacts bind only files that actually exist right now.  Nothing is
    manufactured for stages that never produced evidence.
    """

    control, _ = _control_binding(now)
    schedule, _ = _schedule_binding(captured_at=now)
    market_date = start_payload["market_date"]
    calendar = _calendar_binding(
        _capture_calendar_evidence(market_date),
        market_date=market_date,
    )
    supplied = artifact_paths if isinstance(artifact_paths, Mapping) else {}
    artifact_bindings = {key: _artifact_binding(supplied.get(key)) for key in ARTIFACT_KEYS}
    provisional: dict[str, object] = {
        "payload_schema": DAY_SCHEMA,
        "start_object_id": start.object_id,
        "run_id": start_payload["run_id"],
        "market_date": market_date,
        "role": start_payload["role"],
        "status": "incomplete",
        "phase": "repair_required",
        "predecessor_object_id": start_payload["predecessor_object_id"],
        "live_control": control,
        "schedule": schedule,
        "calendar": calendar,
        "artifacts": artifact_bindings,
        "reasons": [],
        "closure_kind": closure_kind,
        "stopped_at_stage": stopped_at_stage,
        "notes": notes,
    }
    failed, incomplete = _evaluate_day_payload(start, provisional, now=now)
    unknown_artifacts = set(supplied) - set(ARTIFACT_KEYS)
    if unknown_artifacts:
        incomplete.append("unknown_artifact_keys")
    status = "failed" if failed else ("incomplete" if incomplete else "clean")
    provisional["status"] = status
    provisional["phase"] = _day_phase(start=start, status=status, earlier_days=days)
    provisional["reasons"] = sorted(set([*failed, *incomplete]))
    return provisional


def abort_shadow_day(
    *,
    start_object_id: str,
    stopped_at_stage: str,
    notes: str,
    artifacts: Mapping[str, Path] | None = None,
) -> EvidenceAdmission:
    """Crash-safe terminal closure of today's authenticated pending start.

    The admitted day result is always terminal (never clean), carries phase
    ``repair_required``, records the interrupted stage plus every present
    artifact binding, and grants zero broker, schedule, control, or execution
    authority.
    """

    now, effective_at = _now_stamp()
    if type(start_object_id) is not str or not start_object_id:
        raise ValueError("start_object_id is invalid")
    if stopped_at_stage not in SHADOW_DAY_STOP_STAGES:
        raise ValueError("stopped_at_stage is not a known interruption stage")
    if (
        type(notes) is not str
        or not notes.strip()
        or len(notes) > ABORT_NOTES_LIMIT
    ):
        raise ValueError(f"abort notes are required (at most {ABORT_NOTES_LIMIT} characters)")
    prior = _store_envelopes()
    days, pending, _last_day, report = _LedgerState(prior, now=now)
    if report is not None or pending is None or pending.object_id != start_object_id:
        raise ValueError("shadow start has no admissible pending abort transition")
    start = _require_known_start(prior, start_object_id)
    start_payload = start.payload
    market_date = start_payload["market_date"]
    run_id = start_payload["run_id"]
    if not isinstance(market_date, str) or not isinstance(run_id, str):
        raise ValueError("shadow start payload is invalid")
    if _current_central_date(now) != market_date:
        raise ValueError("shadow day can be aborted only on its current Central date")
    payload = _closure_day_payload(
        start=start,
        start_payload=start_payload,
        days=days,
        now=now,
        closure_kind="operator_abort",
        stopped_at_stage=stopped_at_stage,
        notes=notes,
        artifact_paths=artifacts,
    )
    return _admit_shadow_envelope(
        kind=MANUAL_SHADOW_DAY_RESULT_KIND,
        payload=payload,
        now=now,
        effective_at=effective_at,
    )


def expire_pending_shadow_day() -> EvidenceAdmission | None:
    """Close a stale pending start whose Central market date has passed.

    The stale start converts into exactly one immutable ``incomplete`` day
    result with reason ``pending_day_expired_without_adjudication`` and phase
    ``repair_required``.  Missing evidence stays missing; nothing is backfilled.
    Returns ``None`` when no pending start has expired, so repeated calls are
    safe.
    """

    now, effective_at = _now_stamp()
    prior = _store_envelopes()
    days, pending, _last_day, report = _LedgerState(prior, now=now)
    if report is not None or pending is None:
        return None
    start_payload = pending.payload
    market_date = start_payload["market_date"]
    parsed_market_date = _parse_market_date(market_date)
    if parsed_market_date is None or not isinstance(start_payload.get("run_id"), str):
        raise ValueError("shadow start payload is invalid")
    current_central_date = _parse_market_date(_current_central_date(now))
    if current_central_date is None or parsed_market_date >= current_central_date:
        return None
    payload = _closure_day_payload(
        start=pending,
        start_payload=start_payload,
        days=days,
        now=now,
        closure_kind="pending_expired",
        stopped_at_stage=None,
        notes=None,
        artifact_paths=None,
    )
    return _admit_shadow_envelope(
        kind=MANUAL_SHADOW_DAY_RESULT_KIND,
        payload=payload,
        now=now,
        effective_at=effective_at,
    )


def _clean_trial_streak(days: tuple[EvidenceEnvelope, ...]) -> int:
    """Count trailing clean trial-role days; qualification/repair never count."""

    streak = 0
    for day in reversed(days):
        payload = day.payload
        if payload.get("status") == "clean" and payload.get("role") == "trial":
            streak += 1
        else:
            break
    return streak


def shadow_streak_status() -> dict[str, object]:
    """Read-only progress inspection; never appends to the pinned ledger."""

    now, _effective_at = _now_stamp()
    envelopes = _store_envelopes_readonly()
    days, pending, last_day, report = _LedgerState(envelopes, now=now)
    try:
        next_phase, _next_role, expected_predecessor = _start_spec(last_day)
    except ValueError:
        next_phase, _next_role, expected_predecessor = None, None, None

    phase: object
    head_object_id: str | None
    report_payload: Mapping[str, object] | None = None
    pending_view: dict[str, object] | None = None
    predecessor_view: str | None
    if report is not None:
        report_payload = report.payload
        phase = report_payload.get("phase")
        head_object_id = report.object_id
        predecessor_view = None
    elif pending is not None:
        pending_payload = pending.payload
        phase = pending_payload.get("phase")
        head_object_id = pending.object_id
        predecessor_view = None
    else:
        phase = next_phase
        head_object_id = last_day.object_id if last_day is not None else None
        predecessor_view = expected_predecessor if next_phase is not None else None

    last_result: dict[str, object] | None = None
    if last_day is not None:
        day_payload = last_day.payload
        last_result = {
            "object_id": last_day.object_id,
            "run_id": day_payload["run_id"],
            "market_date": day_payload["market_date"],
            "role": day_payload["role"],
            "status": day_payload["status"],
            "phase": day_payload["phase"],
            "reasons": list(day_payload["reasons"]),
        }
    if pending is not None:
        pending_payload = pending.payload
        pending_view = {
            "object_id": pending.object_id,
            "run_id": pending_payload["run_id"],
            "market_date": pending_payload["market_date"],
            "role": pending_payload["role"],
            "phase": pending_payload["phase"],
        }

    return {
        "analysis_only": True,
        "execution_authority": "none",
        "can_submit_orders": False,
        "ledger_head_object_id": head_object_id,
        "phase": phase,
        "last_result": last_result,
        "clean_trial_streak": _clean_trial_streak(days),
        "required_clean_trial_days": 5,
        "terminal_report_present": report is not None,
        "pending_start": pending_view,
        "predecessor_object_id": predecessor_view,
        "can_start_next_day": (
            report is None and pending is None and type(next_phase) is str
        ),
    }


def build_shadow_streak_report(*, final_no_go: bool = False) -> dict[str, object]:
    """Admit exactly one terminal non-authorizing readiness report.

    This operation closes the ledger permanently.  It refuses to run before a
    clean ``trial_complete`` chain unless the caller explicitly terminates the
    whole program as a final NO-GO with ``final_no_go=True``.
    """

    if type(final_no_go) is not bool:
        raise ValueError("final_no_go must be an exact boolean")
    now, effective_at = _now_stamp()
    prior = _store_envelopes()
    days, pending, _last_day, existing_report = _LedgerState(prior, now=now)
    if existing_report is not None:
        return _record_view(existing_report)
    if pending is not None or not days:
        raise ValueError("shadow ledger has no terminal day chain")
    candidate, streak = _candidate_state(days)
    if not candidate and not final_no_go:
        raise ValueError(
            "shadow-streak-report is terminal and refuses to run before a clean "
            "trial_complete; inspect progress with shadow-streak-status or pass "
            "--final-no-go only to terminate the program as a final NO-GO"
        )
    payload: dict[str, object] = {
        "payload_schema": REPORT_SCHEMA,
        "ledger_head_object_id": days[-1].object_id,
        "day_object_ids": [day.object_id for day in days],
        "status": "candidate" if candidate else "no_go",
        "phase": "readiness_candidate" if candidate else "readiness_no_go",
        "clean_trial_streak": streak if candidate else 0,
        "required_clean_trial_days": 5,
        "reasons": [] if candidate else ["full_ledger_not_terminal_candidate"],
    }

    admission = _admit_shadow_envelope(
        kind=MANUAL_SHADOW_FINAL_REPORT_KIND,
        payload=payload,
        now=now,
        effective_at=effective_at,
    )
    return _record_view(admission.envelope, path=admission.path)
    return _record_view(admission.envelope, path=admission.path)
