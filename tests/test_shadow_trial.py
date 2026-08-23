from __future__ import annotations

import copy
import datetime as dt
import hashlib
import inspect
import json
import shutil
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from cli import main as cli_main
from cli.main import app
from tradingagents.evals import runtime_identity, shadow_trial
from tradingagents.strategy import _immutable_evidence_store as evidence_store_module
from tradingagents.strategy._immutable_evidence_store import (
    EvidenceCandidate,
    ImmutableStrategyEvidenceStore,
    StrategyEvidenceStoreError,
)

UTC = dt.timezone.utc
REPO_ROOT = Path(__file__).resolve().parents[1]
runner = CliRunner()


class _CalendarFake:
    def __init__(self, dates: set[str]) -> None:
        self.dates = dates
        self.calls: list[tuple[str, str]] = []

    def list_calendar(self, *, start: str, end: str) -> list[dict[str, str]]:
        self.calls.append((start, end))
        # Producer-real entry shape: strict HH:MM exchange open/close walls.
        return (
            [{"date": start, "open": "09:30", "close": "16:00"}]
            if start == end and start in self.dates
            else []
        )

    def __getattr__(self, name: str):
        raise AssertionError(f"unexpected broker method: {name}")


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")


def _moment(date: str, hour: int = 14) -> dt.datetime:
    return dt.datetime.fromisoformat(f"{date}T{hour:02d}:00:00+00:00")


def _set_clock(monkeypatch: pytest.MonkeyPatch, date: str, hour: int = 14) -> None:
    monkeypatch.setattr(shadow_trial, "_utc_now", lambda: _moment(date, hour))


def _calendar(
    date: str,
    *,
    observed_at: str | None = None,
    dates: list[str] | None = None,
    open_text: str = "09:30",
    close_text: str = "16:00",
) -> dict:
    # Producer-real Alpaca calendar entries carry strict HH:MM exchange
    # (America/New_York) open/close wall times; early closes flow through data.
    return {
        "kind": "alpaca_regular_equities_calendar",
        "market_date": date,
        "observed_at": observed_at or f"{date}T13:59:00+00:00",
        "sessions": [
            {"date": item, "open": open_text, "close": close_text}
            for item in (dates if dates is not None else [date])
        ],
    }


# One ascending producer-real UTC timeline that is valid for both a CDT and a
# CST market date: the paper tick lands inside the 09:30-16:00 ET regular
# session either way, and the daily report follows the session close. The
# minutes mirror the canonical Central automation offsets (:20 sentinel,
# :35 supervisor, :50 board, :03 self-healer, :10 paper, :30 daily report).
def _stage_timeline(date: str) -> dict[str, str]:
    return {
        "overnight_research": f"{date}T14:05:00+00:00",
        "premarket_brief": f"{date}T14:10:00+00:00",
        "preopen_validation": f"{date}T14:15:00+00:00",
        "safety_sentinel": f"{date}T14:20:00+00:00",
        "hourly_supervisor": f"{date}T14:35:00+00:00",
        "loss_review": f"{date}T14:45:00+00:00",
        "execution_board": f"{date}T14:50:00+00:00",
        "self_heal_handoff": f"{date}T15:03:00+00:00",
        "self_heal_plan": f"{date}T15:04:00+00:00",
        "paper_tournament": f"{date}T15:10:00+00:00",
        "broker_reconciliation": f"{date}T15:45:00+00:00",
        "daily_report": f"{date}T21:30:00+00:00",
    }


# Adjudication happens after the daily-report stamp on every market date.
_DAY_CLOCK_HOUR = 22


def _write_schedule_fixture(
    root: Path,
    *,
    active_id: str | None = None,
    omit_id: str | None = None,
) -> tuple[Path, Path, Path]:
    contract = root / "schedule-contract.json"
    roles = root / "automation-roles.json"
    automation_root = root / "automations"
    contract_payload = json.loads(
        (REPO_ROOT / "config" / "automation_schedule_contract.json").read_text(
            encoding="utf-8"
        )
    )
    roles_payload = json.loads(
        (REPO_ROOT / "config" / "automation_roles.json").read_text(encoding="utf-8")
    )
    for automation_id, record in contract_payload["automations"].items():
        if automation_id == omit_id:
            continue
        prompt = " ".join(record["required_prompt_phrases"])
        record["prompt_sha256"] = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        toml_path = automation_root / automation_id / "automation.toml"
        toml_path.parent.mkdir(parents=True, exist_ok=True)
        toml_path.write_text(
            "\n".join(
                [
                    f"name = {json.dumps(record['name'])}",
                    f"prompt = {json.dumps(prompt)}",
                    f"status = {json.dumps('ACTIVE' if automation_id == active_id else 'PAUSED')}",
                    (
                        "target = { "
                        f"type = {json.dumps(record['target']['type'])}, "
                        f"project_id = {json.dumps(record['target']['project_id'])} "
                        "}"
                    ),
                    f"cwds = {json.dumps(record['cwds'])}",
                    f"execution_environment = {json.dumps(record['execution_environment'])}",
                    f"rrule = {json.dumps(record['rrule'])}",
                    f"model = {json.dumps(record['model'])}",
                    f"reasoning_effort = {json.dumps(record['reasoning_effort'])}",
                    f"notification_policy = {json.dumps(record['notification_policy'])}",
                ]
            ),
            encoding="utf-8",
        )
    _write_json(contract, contract_payload)
    _write_json(roles, roles_payload)
    return contract, roles, automation_root


def _control(
    path: Path,
    *,
    frozen: bool = True,
    malformed: bool = False,
    dead_man_expires_at: str = "2026-12-31T00:00:00+00:00",
) -> Path:
    _write_json(
        path,
        ({"frozen": "true"} if malformed else {
            "frozen": frozen,
            "reason": "manual safety hold",
            "dead_man_expires_at": dead_man_expires_at,
        }),
    )
    return path


def _canonical_json_text(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _json_digest(value: object) -> str:
    return hashlib.sha256(_canonical_json_text(value).encode("utf-8")).hexdigest()


def _file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _authority_file_digest(path: Path) -> str:
    """Digest a fixture authority file; deliberately absent files stay deterministic."""

    if path.exists():
        return _file_digest(path)
    return hashlib.sha256(f"missing:{path.as_posix()}".encode()).hexdigest()


def _runtime_identity_fixture(
    *,
    control: Path,
    contract: Path,
    roles: Path,
    automation_root: Path,
) -> dict:
    """A strict-schema flat runtime identity bound to real fixture authority files."""

    schema_versions = {
        "manual_shadow_day_start": shadow_trial.START_SCHEMA,
        "manual_shadow_day_result": shadow_trial.DAY_SCHEMA,
        "manual_shadow_final_report": shadow_trial.REPORT_SCHEMA,
    }
    overnight_route = {
        "llm_provider": "openai",
        "quick_think_llm": "gpt-5.4-mini",
        "deep_think_llm": "gpt-5.4",
    }
    identity = {
        "identity_schema": "runtime_identity/v1",
        "git_commit": "f" * 40,
        "worktree_clean": True,
        "required_files_sha256": {
            name: hashlib.sha256(name.encode("utf-8")).hexdigest()
            for name in (
                "pyproject.toml",
                "uv.lock",
                "requirements.txt",
                "requirements-crawler.txt",
            )
        },
        "schedule_contract_sha256": _file_digest(contract),
        "role_contract_sha256": _file_digest(roles),
        "live_control_sha256": _file_digest(control),
        "automation_tomls_sha256": {
            automation_id: _authority_file_digest(
                automation_root / automation_id / "automation.toml"
            )
            for automation_id in sorted(shadow_trial.EXPECTED_AUTOMATION_IDS)
        },
        "provider_routes": {},
        "provider_routes_sha256": hashlib.sha256(b"{}").hexdigest(),
        "schema_versions": schema_versions,
        "schema_versions_sha256": _json_digest(schema_versions),
        "overnight_route": overnight_route,
        "overnight_route_sha256": _json_digest(overnight_route),
        "python_executable": "/fixture/python",
        "package_inventory": ["fixture-package==1.0.0"],
        "package_inventory_sha256": _json_digest(["fixture-package==1.0.0"]),
    }
    body = {key: value for key, value in identity.items() if key != "identity_sha256"}
    identity["identity_sha256"] = _json_digest(body)
    return identity


def _recompute_identity_digests(identity: dict) -> dict:
    """Rebuild component and whole digests so mutations stay valid captures."""

    drifted = copy.deepcopy(identity)
    drifted["provider_routes_sha256"] = _json_digest(drifted["provider_routes"])
    drifted["schema_versions_sha256"] = _json_digest(drifted["schema_versions"])
    route = drifted["overnight_route"]
    drifted["overnight_route_sha256"] = None if route is None else _json_digest(route)
    drifted["package_inventory"] = sorted(
        {entry.strip().lower() for entry in drifted["package_inventory"]}
    )
    drifted["package_inventory_sha256"] = _json_digest(drifted["package_inventory"])
    body = {key: value for key, value in drifted.items() if key != "identity_sha256"}
    drifted["identity_sha256"] = _json_digest(body)
    return drifted


def _configure_environment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    frozen: bool = True,
    malformed_control: bool = False,
    active_id: str | None = None,
    omit_id: str | None = None,
    dead_man_expires_at: str = "2026-12-31T00:00:00+00:00",
) -> dict[str, Path]:
    manual_root = tmp_path / "results" / "manual_shadow"
    control = _control(
        tmp_path / "results" / "policy" / "live_control.json",
        frozen=frozen,
        malformed=malformed_control,
        dead_man_expires_at=dead_man_expires_at,
    )
    contract, roles, automation_root = _write_schedule_fixture(
        tmp_path / "schedule",
        active_id=active_id,
        omit_id=omit_id,
    )
    monkeypatch.setattr(shadow_trial, "_manual_shadow_root", lambda: manual_root)
    monkeypatch.setattr(shadow_trial, "_canonical_live_control_path", lambda: control)
    monkeypatch.setattr(shadow_trial, "_canonical_schedule_contract_path", lambda: contract)
    monkeypatch.setattr(shadow_trial, "_canonical_role_contract_path", lambda: roles)
    monkeypatch.setattr(shadow_trial, "_canonical_automation_root", lambda: automation_root)
    runtime_identity_holder = {
        "value": _runtime_identity_fixture(
            control=control,
            contract=contract,
            roles=roles,
            automation_root=automation_root,
        )
    }
    monkeypatch.setattr(
        shadow_trial,
        "_runtime_identity_capture",
        lambda: copy.deepcopy(runtime_identity_holder["value"]),
    )
    return {
        "manual_root": manual_root,
        "control": control,
        "contract": contract,
        "roles": roles,
        "automation_root": automation_root,
        "runtime_identity": runtime_identity_holder,
    }


def _bound_sentinel_shape(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[dict, dict]:
    """Build producer-real sentinel evidence plus its admitted source bindings."""

    from tradingagents.evals.safety_sentinel import build_safety_sentinel_packet

    environment = _configure_environment(monkeypatch, tmp_path)
    start = _start(monkeypatch, date="2026-08-21")
    preopen_path = tmp_path / "preopen.json"
    _write_json(
        preopen_path,
        {
            "kind": "tradingagents_preopen_validation",
            "generated_at": "2026-08-21T14:00:00+00:00",
            "analysis_only": True,
            "execution_authority": "none",
            "can_submit_orders": False,
            "overall_status": "pass",
            "submitted_count": 0,
            "failed_check_ids": [],
        },
    )
    broker_snapshot = _healthy_broker_snapshot(
        date="2026-08-21",
        account_id="live-account",
    )
    broker_snapshot["captured_at"] = "2026-08-21T14:00:00+00:00"
    broker_snapshot["clock"]["timestamp"] = "2026-08-21T14:00:00+00:00"
    packet = build_safety_sentinel_packet(
        live_control_path=environment["control"],
        preopen_validation_path=preopen_path,
        schedule_contract_path=environment["contract"],
        automation_root=environment["automation_root"],
        role_contract_path=environment["roles"],
        broker_snapshot=broker_snapshot,
        now=_moment("2026-08-21", 14),
    )
    start_payload = _payload(start)
    return packet, {
        "live_control": start_payload["live_control"],
        "schedule_configuration": start_payload["schedule"]["source_manifest"],
        "schedule_check": start_payload["schedule"]["result"],
        "preopen_validation": shadow_trial._artifact_binding(preopen_path),
    }


def _payload(admission) -> dict:
    return dict(admission.envelope.payload)


def _start(
    monkeypatch: pytest.MonkeyPatch,
    *,
    date: str,
    predecessor_object_id: str | None = None,
    calendar_kwargs: dict | None = None,
) -> object:
    _set_clock(monkeypatch, date)
    with monkeypatch.context() as calendar_patch:
        calendar_patch.setattr(
            shadow_trial,
            "_capture_calendar_evidence",
            lambda market_date: _calendar(market_date, **(calendar_kwargs or {})),
        )
        return shadow_trial.create_shadow_day_start_manifest(
            run_id=f"run-{date}",
            market_date=date,
            predecessor_object_id=predecessor_object_id,
        )


def _artifacts(
    root: Path,
    *,
    run_id: str,
    date: str,
    start_object_id: str | None = None,
    submitted_count: object = 0,
    sentinel_status: str = "FROZEN",
) -> dict[str, Path]:
    sentinel = root / "artifacts" / f"sentinel-{date}.json"
    paper = root / "artifacts" / f"paper-{date}.json"
    timeline = _stage_timeline(date)
    broker_snapshot = _healthy_broker_snapshot(date=date, account_id="live-account")
    _write_json(
        sentinel,
        {
            "kind": "safety_sentinel_audit",
            "run_id": run_id,
            "market_date": date,
            **({"shadow_start_object_id": start_object_id} if start_object_id else {}),
            "generated_at": timeline["safety_sentinel"],
            "status": sentinel_status,
            "reasons": ["frozen_control"],
            "analysis_only": True,
            "execution_authority": "none",
            "can_submit_orders": False,
            "actions_taken": [],
            "evidence": {
                "live_control": {
                    "status": "captured",
                    "sha256": "a" * 64,
                    "size_bytes": 1,
                },
                "preopen_validation": {
                    "status": "captured",
                    "sha256": "b" * 64,
                    "size_bytes": 1,
                },
            },
            "schedule_check": {
                "deployment_phase": "predeployment_paused",
                "contract_status": "pass",
                "safe_predeployment": True,
                "issues": [],
                "automations": [
                    {"automation_id": f"automation-{index}", "status": "match"}
                    for index in range(10)
                ],
            },
            "broker_snapshot": broker_snapshot,
        },
    )
    _write_json(
        paper,
        {
            "kind": "paper_tournament_run",
            "run_id": run_id,
            "market_date": date,
            **({"shadow_start_object_id": start_object_id} if start_object_id else {}),
            "generated_at": timeline["paper_tournament"],
            "status": "HOLD",
            "dry_run": True,
            "submitted_count": submitted_count,
            "submitted": [] if submitted_count == 0 else ["not-an-order"],
            "analysis_only": True,
            "execution_authority": "none",
            "can_submit_orders": False,
        },
    )
    return {"safety_sentinel": sentinel, "paper_tournament": paper}


def _healthy_broker_snapshot(*, date: str, account_id: str) -> dict[str, object]:
    return {
        "account": {"id": account_id, "status": "ACTIVE"},
        "positions": [],
        "open_orders": [],
        "clock": {"is_open": True, "timestamp": f"{date}T15:00:00+00:00"},
        "errors": {},
        "read_methods": ["get_account", "list_positions", "list_orders", "get_clock"],
        "captured_at": f"{date}T15:00:00+00:00",
    }


def _complete_daily_chain(
    root: Path,
    *,
    start,
    artifacts: dict[str, Path],
) -> dict[str, Path]:
    payload = _payload(start)
    timeline = _stage_timeline(payload["market_date"])
    stages: dict[str, Path] = {
        "safety_sentinel": artifacts["safety_sentinel"],
        "paper_tournament": artifacts["paper_tournament"],
    }
    for name in shadow_trial.DAILY_CHAIN_STAGES:
        if name in stages:
            continue
        path = root / "artifacts" / f"{name}-{payload['market_date']}.json"
        packet: dict[str, object] = {
            "kind": shadow_trial.DAILY_CHAIN_STAGE_KINDS[name],
            "generated_at": timeline[name],
            "status": "HOLD",
            "analysis_only": True,
            "execution_authority": "none",
            "can_submit_orders": False,
        }
        # These intentionally mirror the native persisted producer shapes,
        # rather than a synthetic one-size-fits-all test envelope.
        if name == "overnight_research":
            packet.update(
                {
                    "submitted": [],
                    "overnight_quality": {
                        "completion_status": "complete",
                        "graph_failure_count": 0,
                        "graph_attempt_failure_count": 0,
                        "top_provider_bundle_error_count": 0,
                        "requested_full_graph_limit": 1,
                        "full_graph_limit": 1,
                        "full_graph_count": 1,
                        "full_graph_attempt_count": 1,
                        "full_graph_success_count": 1,
                        "tradable_count": 1,
                        "per_ticker_timeout_minutes": 2,
                        "time_budget_minutes": 3,
                        "graph_config": {
                            "graph_profile": "market-only",
                            "selected_analysts": ["market"],
                            "tool_free_analysts": ["market"],
                            "max_output_tokens": 800,
                            "max_completion_tokens": 800,
                            "llm_timeout_seconds": 30,
                            "llm_max_retries": 0,
                            "max_debate_rounds": 0,
                            "max_risk_discuss_rounds": 0,
                        },
                        "research_context_enabled": False,
                        "research_context_packet_count": 0,
                        "research_context_blocked_count": 0,
                        "agent_intelligence_enabled": False,
                        "agent_ledger_append_enabled": False,
                        "top_provider_bundle_requested_count": 0,
                        "top_provider_bundle_count": 0,
                    },
                }
            )
        elif name == "premarket_brief":
            packet.update({"stale_warnings": [], "unresolved_blockers": []})
        elif name == "preopen_validation":
            packet.update({"overall_status": "pass", "submitted_count": 0, "failed_check_ids": []})
        elif name == "hourly_supervisor":
            packet.update(
                {
                    "decision": "hold",
                    "submitted": [],
                    "issues": [],
                    "shadow_dry_run": True,
                    "outbox_suppressed": True,
                    "outbox_write_allowed": False,
                }
            )
        elif name == "loss_review":
            packet.update(
                {
                    "evidence_type": "loss_review_evidence",
                    "payload": {
                        "analysis_only": True,
                        "execution_authority": "none",
                        "can_submit_orders": False,
                        "next_action": "autonomous_hold",
                        "submitted_order_count": 0,
                        "remaining_blockers": [],
                        "current_loss_review": {
                            "trade_decision_allowed": True,
                            "blockers": [],
                        },
                        "advisory_analysis": {
                            "route_summary": [
                                {
                                    "status": "packet_written",
                                    "blocked": False,
                                }
                            ]
                        },
                    },
                    "freshness": {"read_only": True, "can_submit_orders": False},
                }
            )
        elif name == "execution_board":
            packet.update(
                {
                    "metrics": {"submitted_order_count": 0},
                    "violations": [],
                    "warnings": [],
                }
            )
        elif name == "self_heal_handoff":
            packet.update({"active_trigger_count": 0, "max_severity": "none"})
        elif name == "self_heal_plan":
            packet.update(
                {
                    "active_plan_count": 0,
                    "escalation_count": 0,
                    "max_severity": "none",
                    "status": "quiet",
                    "executed_count": 0,
                }
            )
        elif name == "daily_report":
            packet.update({"packet_count": 0, "portfolio": {}})
        if name == "broker_reconciliation":
            packet.update(
                {
                    "kind": "broker_reconciliation_observer",
                    "run_id": payload["run_id"],
                    "market_date": payload["market_date"],
                    "shadow_start_object_id": start.envelope.object_id,
                    "read_only": True,
                    "submitted_count": 0,
                    "cancelled_count": 0,
                    "status": "COMPLETE",
                    "live": _healthy_broker_snapshot(
                        date=payload["market_date"], account_id="live-account"
                    ),
                    "paper": {
                        **_healthy_broker_snapshot(
                            date=payload["market_date"], account_id="paper-account"
                        ),
                        # Complete order-book evidence: an empty day must prove
                        # it holds no tournament orders.
                        "all_orders": [],
                    },
                }
            )
        _write_json(path, packet)
        stages[name] = path
    sentinel = json.loads(stages["safety_sentinel"].read_text(encoding="utf-8"))
    preopen_binding = shadow_trial._artifact_binding(stages["preopen_validation"])

    def captured_source(binding: dict) -> dict:
        return {
            "path": binding["path"],
            "status": binding["status"],
            "sha256": binding["sha256"],
            "size_bytes": binding["size_bytes"],
            "captured_at": timeline["safety_sentinel"],
            "freshness": {
                "status": "fresh",
                "rule": "direct_capture_current_audit",
            },
        }

    sentinel["schedule_check"] = shadow_trial._plain_json(
        payload["schedule"]["result"]
    )
    sentinel["evidence"] = {
        "live_control": captured_source(payload["live_control"]),
        "preopen_validation": captured_source(preopen_binding),
        "schedule_configuration": shadow_trial._plain_json(
            payload["schedule"]["source_manifest"]
        ),
    }
    _write_json(stages["safety_sentinel"], sentinel)
    manifest, manifest_path = shadow_trial.create_shadow_day_manifest(
        start_object_id=start.envelope.object_id,
        stages=stages,
        output_dir=root / "manifests",
    )
    assert manifest["run_id"] == payload["run_id"]
    return {**artifacts, "daily_chain_manifest": manifest_path}


def _rebind_daily_chain_manifest(
    root: Path,
    *,
    start,
    artifacts: dict[str, Path],
) -> Path:
    market_date = _payload(start)["market_date"]
    stages = {
        name: (
            artifacts[name]
            if name in artifacts
            else root / "artifacts" / f"{name}-{market_date}.json"
        )
        for name in shadow_trial.DAILY_CHAIN_STAGES
    }
    _, manifest_path = shadow_trial.create_shadow_day_manifest(
        start_object_id=start.envelope.object_id,
        stages=stages,
        output_dir=root / "rebound-manifests",
    )
    return manifest_path


def _day(
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
    start,
    *,
    date: str,
    artifacts: dict[str, Path] | None = None,
) -> object:
    _set_clock(monkeypatch, date, _DAY_CLOCK_HOUR)
    start_payload = _payload(start)
    with monkeypatch.context() as calendar_patch:
        calendar_patch.setattr(
            shadow_trial,
            "_capture_calendar_evidence",
            lambda market_date: _calendar(
                market_date,
                observed_at=f"{market_date}T15:59:00+00:00",
            ),
        )
        default_artifacts = None
        if artifacts is None:
            default_artifacts = _artifacts(
                root,
                run_id=start_payload["run_id"],
                date=date,
                start_object_id=start.envelope.object_id,
            )
        return shadow_trial.adjudicate_shadow_day(
            start_object_id=start.envelope.object_id,
            artifacts=(
                artifacts
                if artifacts is not None
                else _complete_daily_chain(root, start=start, artifacts=default_artifacts or {})
            ),
        )


def test_red_production_cli_exposes_only_pinned_non_authorizing_inputs(tmp_path, monkeypatch):
    environment = _configure_environment(monkeypatch, tmp_path)
    _set_clock(monkeypatch, "2026-08-21")
    calendar = _CalendarFake({"2026-08-21"})
    monkeypatch.setattr(cli_main, "_alpaca_live_client", lambda: calendar)

    help_result = runner.invoke(app, ["research", "shadow-day-start", "--help"])
    assert help_result.exit_code == 0
    for forbidden in (
        "--now", "--output-dir", "--live-control-path", "--schedule-contract-path",
        "--role-contract-path", "--automation-root", "--ledger-id", "--phase",
    ):
        assert forbidden not in help_result.output
    streak_help = runner.invoke(app, ["research", "shadow-streak-report", "--help"])
    assert streak_help.exit_code == 0
    assert "--day-record" not in streak_help.output
    assert "--final-no-go" in streak_help.output
    status_help = runner.invoke(app, ["research", "shadow-streak-status", "--help"])
    assert status_help.exit_code == 0
    assert not inspect.signature(shadow_trial.shadow_streak_status).parameters
    report_parameters = inspect.signature(shadow_trial.build_shadow_streak_report).parameters
    assert list(report_parameters) == ["final_no_go"]
    assert report_parameters["final_no_go"].kind is inspect.Parameter.KEYWORD_ONLY
    assert report_parameters["final_no_go"].default is False

    result = runner.invoke(
        app,
        ["research", "shadow-day-start", "--run-id", "cli-run", "--market-date", "2026-08-21", "--json-output"],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert calendar.calls == [("2026-08-21", "2026-08-21")]
    assert Path(payload["record_path"]).is_relative_to(environment["manual_root"])
    assert payload["execution_authority"] == "none"
    assert payload["can_submit_orders"] is False


def test_bound_sentinel_cli_derives_start_identity_and_requires_paused(tmp_path, monkeypatch):
    environment = _configure_environment(monkeypatch, tmp_path)
    start = _start(monkeypatch, date="2026-08-21")
    _write_json(
        tmp_path / "preopen.json",
        {
            "generated_at": "2026-08-21T14:00:00+00:00",
            "analysis_only": True,
            "execution_authority": "none",
            "can_submit_orders": False,
            "overall_status": "pass",
        },
    )

    class Broker:
        def get_account(self): return {"id": "live", "status": "ACTIVE"}
        def list_positions(self): return []
        def list_orders(self, *, status): return []
        def get_clock(self): return {"is_open": False, "timestamp": "2026-08-21T14:00:00+00:00"}
        def __getattr__(self, name):
            if name in {"submit_order", "cancel_order"}:
                raise AssertionError(f"forbidden write {name}")
            raise AttributeError(name)

    monkeypatch.setattr(cli_main, "_alpaca_live_client", Broker)
    monkeypatch.setattr(cli_main, "_alpaca_policy_now", lambda: _moment("2026-08-21", 14))
    result = runner.invoke(
        app,
        [
            "research", "safety-sentinel-audit", "--shadow-start-object-id", start.envelope.object_id,
            "--require-paused", "--live-control-path", str(environment["control"]),
            "--preopen-validation-path", str(tmp_path / "preopen.json"),
            "--schedule-contract-path", str(environment["contract"]),
            "--role-contract-path", str(environment["roles"]),
            "--automation-root", str(environment["automation_root"]),
            "--output-dir", str(tmp_path / "sentinel"), "--json-output",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["shadow_start_object_id"] == start.envelope.object_id
    assert payload["run_id"] == _payload(start)["run_id"]
    assert payload["market_date"] == "2026-08-21"
    assert payload["analysis_only"] is True and payload["can_submit_orders"] is False


def test_bound_reconciliation_and_public_manifest_cli_use_authenticated_start(tmp_path, monkeypatch):
    _configure_environment(monkeypatch, tmp_path)
    start = _start(monkeypatch, date="2026-08-21")

    class Broker:
        def __init__(self):
            self.order_reads = []

        def get_account(self): return {"id": "observer", "status": "ACTIVE"}
        def list_positions(self): return []
        def list_orders(self, *, status, after=None, limit=None):
            self.order_reads.append((status, after, limit))
            return []
        def get_clock(self): return {"is_open": False, "timestamp": "2026-08-21T14:00:00+00:00"}
        def __getattr__(self, name):
            if name in {"submit_order", "cancel_order", "replace_order"}:
                raise AssertionError(f"forbidden write {name}")
            raise AttributeError(name)

    broker = Broker()
    monkeypatch.setattr(cli_main, "_alpaca_live_client", lambda: broker)
    monkeypatch.setattr(cli_main, "_alpaca_paper_client", lambda: broker)
    monkeypatch.setattr(cli_main, "_alpaca_policy_now", lambda: _moment("2026-08-21", 14))
    reconcile = runner.invoke(
        app,
        [
            "alpaca", "reconcile-observer", "--shadow-start-object-id", start.envelope.object_id,
            "--output-dir", str(tmp_path / "reconcile"), "--json-output",
        ],
    )
    assert reconcile.exit_code == 0, reconcile.output
    reconcile_payload = json.loads(reconcile.stdout)
    assert reconcile_payload["shadow_start_object_id"] == start.envelope.object_id
    assert reconcile_payload["status"] == "COMPLETE"
    # A bound reconciliation must observe the full same-market-day paper book
    # with the documented bounded retrieval: status=all, day-start after, limit.
    assert broker.order_reads == [
        ("open", None, None),
        ("open", None, None),
        ("all", "2026-08-21T05:00:00+00:00", 500),
    ]
    assert reconcile_payload["paper"]["all_orders"] == []

    artifacts = _artifacts(
        tmp_path,
        run_id=_payload(start)["run_id"],
        date="2026-08-21",
        start_object_id=start.envelope.object_id,
    )
    _complete_daily_chain(tmp_path, start=start, artifacts=artifacts)
    stage_paths = {
        name: (
            artifacts["safety_sentinel"] if name == "safety_sentinel"
            else artifacts["paper_tournament"] if name == "paper_tournament"
            else tmp_path / "artifacts" / f"{name}-2026-08-21.json"
        )
        for name in shadow_trial.DAILY_CHAIN_STAGES
    }
    manifest = runner.invoke(
        app,
        [
            "research", "shadow-day-manifest", "--start-object-id", start.envelope.object_id,
            *[item for name, path in stage_paths.items() for item in ("--stage", f"{name}={path}")],
            "--output-dir", str(tmp_path / "public-manifest"), "--json-output",
        ],
    )
    assert manifest.exit_code == 0, manifest.output
    manifest_payload = json.loads(manifest.stdout)
    assert manifest_payload["shadow_start_object_id"] == start.envelope.object_id
    assert set(manifest_payload["stages"]) == set(shadow_trial.DAILY_CHAIN_STAGES)


def test_bound_reconciliation_records_hold_evidence_when_all_orders_read_fails(
    tmp_path, monkeypatch
):
    """A failed bound all_orders read becomes HOLD errors, never silent acceptance."""

    _configure_environment(monkeypatch, tmp_path)
    start = _start(monkeypatch, date="2026-08-21")

    class Broker:
        def get_account(self): return {"id": "observer", "status": "ACTIVE"}
        def list_positions(self): return []
        def list_orders(self, *, status, after=None, limit=None):
            if status == "all":
                raise RuntimeError("broker transport unavailable")
            return []
        def get_clock(self): return {"is_open": False, "timestamp": "2026-08-21T14:00:00+00:00"}
        def __getattr__(self, name):
            if name in {"submit_order", "cancel_order", "replace_order"}:
                raise AssertionError(f"forbidden write {name}")
            raise AttributeError(name)

    broker = Broker()
    monkeypatch.setattr(cli_main, "_alpaca_live_client", lambda: broker)
    monkeypatch.setattr(cli_main, "_alpaca_paper_client", lambda: broker)
    monkeypatch.setattr(cli_main, "_alpaca_policy_now", lambda: _moment("2026-08-21", 14))
    reconcile = runner.invoke(
        app,
        [
            "alpaca", "reconcile-observer", "--shadow-start-object-id", start.envelope.object_id,
            "--output-dir", str(tmp_path / "reconcile"), "--json-output",
        ],
    )
    assert reconcile.exit_code == 0, reconcile.output
    reconcile_payload = json.loads(reconcile.stdout)
    # The failure is preserved as evidence and the packet is HOLD, not COMPLETE.
    assert reconcile_payload["status"] == "HOLD"
    assert reconcile_payload["paper"]["errors"]["all_orders"] == (
        "list_orders(all) failed: broker transport unavailable"
    )
    assert "all_orders" not in reconcile_payload["paper"]
    # The same evidence is non-clean-compatible downstream stage evidence.
    assert "broker_reconciliation_stage_semantics_invalid" in (
        shadow_trial._stage_semantic_reasons("broker_reconciliation", reconcile_payload)
    )


def test_bound_reconciliation_winter_market_date_uses_cst_utc_offset(
    tmp_path, monkeypatch
):
    """The derived day-start bound follows the market date's UTC offset (CST 06:00Z)."""

    _configure_environment(
        monkeypatch,
        tmp_path,
        dead_man_expires_at="2027-12-31T00:00:00+00:00",
    )
    winter_start = _start(monkeypatch, date="2027-01-04")

    class Broker:
        def __init__(self):
            self.order_reads = []

        def get_account(self): return {"id": "observer", "status": "ACTIVE"}
        def list_positions(self): return []
        def list_orders(self, *, status, after=None, limit=None):
            self.order_reads.append((status, after, limit))
            return []
        def get_clock(self): return {"is_open": False, "timestamp": "2027-01-04T14:00:00+00:00"}
        def __getattr__(self, name):
            if name in {"submit_order", "cancel_order", "replace_order"}:
                raise AssertionError(f"forbidden write {name}")
            raise AttributeError(name)

    broker = Broker()
    monkeypatch.setattr(cli_main, "_alpaca_live_client", lambda: broker)
    monkeypatch.setattr(cli_main, "_alpaca_paper_client", lambda: broker)
    monkeypatch.setattr(cli_main, "_alpaca_policy_now", lambda: _moment("2027-01-04", 14))
    reconcile = runner.invoke(
        app,
        [
            "alpaca", "reconcile-observer", "--shadow-start-object-id", winter_start.envelope.object_id,
            "--output-dir", str(tmp_path / "reconcile"), "--json-output",
        ],
    )
    assert reconcile.exit_code == 0, reconcile.output
    reconcile_payload = json.loads(reconcile.stdout)
    assert reconcile_payload["status"] == "COMPLETE"
    # 2027-01-04 is Central Standard Time (UTC-6): midnight CT is 06:00Z.
    assert broker.order_reads[-1] == ("all", "2027-01-04T06:00:00+00:00", 500)
    assert reconcile_payload["paper"]["all_orders"] == []


def test_red_generic_self_sealed_files_never_load_or_become_candidate(tmp_path, monkeypatch):
    environment = _configure_environment(monkeypatch, tmp_path)
    environment["manual_root"].mkdir(parents=True)
    forged = environment["manual_root"] / "shadow-day-start-forged.json"
    _write_json(forged, {"kind": "shadow-day-start", "object_id": "shadow-day-start-" + "0" * 64, "recorded_at": "2026-08-21T14:00:00+00:00", "payload_sha256": "0" * 64, "payload": {}})
    assert not hasattr(shadow_trial, "_seal")
    assert not hasattr(shadow_trial, "write_shadow_trial_packet")
    with pytest.raises(ValueError, match="ledger|admitted|record"):
        shadow_trial.load_shadow_record(forged.name, expected_kind="manual-shadow-day-start")
    with pytest.raises(ValueError, match="ledger|candidate|record"):
        shadow_trial.build_shadow_streak_report()


def test_red_store_owns_envelope_identity_and_recorded_time(tmp_path, monkeypatch):
    _configure_environment(monkeypatch, tmp_path)
    start = _start(monkeypatch, date="2026-08-21")
    payload = _payload(start)
    assert start.envelope.kind == "manual-shadow-day-start"
    assert start.envelope.recorded_at == "2026-08-21T14:00:00+00:00"
    assert start.envelope.object_id.startswith("manual-shadow-day-start-")
    assert {"object_id", "recorded_at", "schema_version", "kind"}.isdisjoint(payload)
    loaded = shadow_trial.load_shadow_record(start.envelope.object_id, expected_kind="manual-shadow-day-start")
    assert loaded.object_id == start.envelope.object_id


@pytest.mark.parametrize(
    "kind",
    [
        "manual-shadow-day-start",
        "manual-shadow-day-result",
        "manual-shadow-final-report",
    ],
)
def test_red_generic_store_cannot_admit_reserved_manual_shadow_kinds(tmp_path, kind):
    root = tmp_path / "results" / "manual_shadow"
    root.parent.mkdir(parents=True)
    store = ImmutableStrategyEvidenceStore(
        root,
        clock=lambda: _moment("2026-08-21"),
    )
    with pytest.raises(StrategyEvidenceStoreError, match="reserved|allowed"):
        store.admit_checked(
            EvidenceCandidate(
                kind=kind,
                effective_at="2026-08-21T14:00:00+00:00",
                payload={"fabricated": True},
            ),
            validate=lambda _history, _candidate: None,
        )


def test_red_generic_manual_injection_cannot_create_a_reportable_shadow_ledger(tmp_path, monkeypatch):
    environment = _configure_environment(monkeypatch, tmp_path)
    store = ImmutableStrategyEvidenceStore(
        environment["manual_root"],
        clock=lambda: _moment("2026-08-21"),
    )
    with pytest.raises(StrategyEvidenceStoreError, match="reserved|allowed"):
        store.admit_checked(
            EvidenceCandidate(
                kind="manual-shadow-day-start",
                effective_at="2026-08-21T14:00:00+00:00",
                payload={"fabricated_calendar_and_control": True},
            ),
            validate=lambda _history, _candidate: None,
        )
    with pytest.raises(ValueError, match="terminal|ledger"):
        shadow_trial.build_shadow_streak_report()


def test_red_task3_ledger_route_is_not_a_generic_store_or_callback_escape(tmp_path, monkeypatch):
    environment = _configure_environment(monkeypatch, tmp_path)
    start = _start(monkeypatch, date="2026-08-21")
    assert not hasattr(shadow_trial, "_store")
    anchor = json.loads(
        (environment["manual_root"].parent / ".manual-shadow-trusted-head.json").read_text(
            encoding="utf-8"
        )
    )
    ledger_id = anchor["ledger_id"]
    with pytest.raises(TypeError, match="_manual_shadow_ledger_id"):
        ImmutableStrategyEvidenceStore(
            environment["manual_root"],
            clock=lambda: _moment("2026-08-21"),
            _manual_shadow_ledger_id=ledger_id,
        )
    assert not hasattr(
        ImmutableStrategyEvidenceStore,
        "_admit_reserved_manual_shadow",
    )
    assert start.envelope.admission_route == ledger_id


def test_round4_generic_store_instance_mutation_cannot_admit_manual_shadow(tmp_path):
    (tmp_path / "results").mkdir()
    store = ImmutableStrategyEvidenceStore(
        tmp_path / "results" / "manual_shadow",
        clock=lambda: _moment("2026-08-21"),
    )
    store._managed_kinds = frozenset({"manual-shadow-day-start"})
    store._admission_route = "manual-shadow-reserved-v1"

    with pytest.raises(StrategyEvidenceStoreError, match="reserved|allowed"):
        store.admit_checked(
            EvidenceCandidate(
                kind="manual-shadow-day-start",
                effective_at="2026-08-21T14:00:00+00:00",
                payload={"fabricated": True},
            ),
            validate=lambda _history, _candidate: None,
        )


def test_round4_rejected_reserved_factories_and_classes_are_absent():
    for name in (
        "_bind_reserved_manual_shadow_admission",
        "_open_reserved_manual_shadow_store",
        "_ReservedManualShadowBinding",
        "_ReservedManualShadowEvidenceStore",
    ):
        assert not hasattr(evidence_store_module, name)


def test_round5_raw_reserved_admission_surface_is_absent():
    constructor = inspect.signature(ImmutableStrategyEvidenceStore)
    assert "_manual_shadow_ledger_id" not in constructor.parameters
    assert not hasattr(
        ImmutableStrategyEvidenceStore,
        "_admit_reserved_manual_shadow",
    )
    assert not hasattr(shadow_trial, "_anchored_admission")
    assert not hasattr(shadow_trial, "_open_anchored_store")
    assert not hasattr(shadow_trial, "_validate_reserved_admission")


def test_round5_code_object_spoof_cannot_commit_a_fabricated_shadow_entry(
    tmp_path,
    monkeypatch,
):
    environment = _configure_environment(monkeypatch, tmp_path)
    _set_clock(monkeypatch, "2026-08-21")
    fabricated = EvidenceCandidate(
        kind="manual-shadow-day-start",
        effective_at="2026-08-21T14:00:00+00:00",
        payload={"fabricated_authority": True},
    )
    monkeypatch.setattr(
        shadow_trial,
        "_round5_fabricated_candidate",
        fabricated,
        raising=False,
    )
    monkeypatch.setattr(
        shadow_trial,
        "_validate_reserved_admission",
        lambda _history, _candidate: None,
        raising=False,
    )

    def spoofed_facade(
        *,
        run_id: str,
        market_date: str,
        predecessor_object_id: str | None = None,
    ):
        del run_id, market_date, predecessor_object_id
        with _anchored_admission(_round5_fabricated_candidate) as store:  # noqa: F821
            return store._admit_reserved_manual_shadow(  # noqa: SLF001
                _round5_fabricated_candidate  # noqa: F821
            )

    monkeypatch.setattr(
        shadow_trial.create_shadow_day_start_manifest,
        "__code__",
        spoofed_facade.__code__,
    )
    with pytest.raises((AttributeError, NameError, StrategyEvidenceStoreError)):
        shadow_trial.create_shadow_day_start_manifest(
            run_id="spoof",
            market_date="2026-08-21",
        )

    anchor_path = environment["manual_root"].parent / ".manual-shadow-trusted-head.json"
    assert not anchor_path.exists()
    assert not environment["manual_root"].exists()


def test_round5_method_code_spoof_cannot_bypass_generic_reserved_rejection(
    tmp_path,
    monkeypatch,
):
    root = tmp_path / "results" / "manual_shadow"
    root.parent.mkdir(parents=True)
    store = ImmutableStrategyEvidenceStore(
        root,
        clock=lambda: _moment("2026-08-21"),
    )
    store._managed_kinds = frozenset({"manual-shadow-day-start"})
    store._admission_route = "a" * 64
    candidate = EvidenceCandidate(
        kind="manual-shadow-day-start",
        effective_at="2026-08-21T14:00:00+00:00",
        payload={"fabricated_authority": True},
    )

    def spoofed_reserved_caller(store, candidate):
        return store._admit_candidate(  # noqa: SLF001
            candidate,
            validate=lambda _history, _candidate: None,
        )

    reserved = getattr(
        ImmutableStrategyEvidenceStore,
        "_admit_reserved_manual_shadow",
        None,
    )
    if reserved is not None:
        monkeypatch.setattr(reserved, "__code__", spoofed_reserved_caller.__code__)

    with pytest.raises(StrategyEvidenceStoreError, match="reserved|allowed"):
        spoofed_reserved_caller(store, candidate)
    assert not root.exists()


def test_round4_direct_api_owns_calendar_capture(tmp_path, monkeypatch):
    _configure_environment(monkeypatch, tmp_path)
    _set_clock(monkeypatch, "2026-08-21")
    captured_dates: list[str] = []

    def capture(market_date: str) -> dict:
        captured_dates.append(market_date)
        return _calendar(market_date)

    monkeypatch.setattr(
        shadow_trial,
        "_capture_calendar_evidence",
        capture,
        raising=False,
    )
    start_signature = inspect.signature(
        shadow_trial.create_shadow_day_start_manifest
    )
    day_signature = inspect.signature(shadow_trial.adjudicate_shadow_day)
    assert "calendar_evidence" not in start_signature.parameters
    assert "calendar_evidence" not in day_signature.parameters

    admission = shadow_trial.create_shadow_day_start_manifest(
        run_id="canonical-calendar",
        market_date="2026-08-21",
    )
    assert captured_dates == ["2026-08-21"]
    with pytest.raises(TypeError):
        shadow_trial.create_shadow_day_start_manifest(  # type: ignore[call-arg]
            run_id="caller-calendar",
            market_date="2026-08-21",
            calendar_evidence=_calendar("2026-08-21"),
        )
    assert _payload(admission)["calendar"]["market_date"] == "2026-08-21"


def test_round4_fully_consistent_copied_reserved_ledger_fails_closed(
    tmp_path,
    monkeypatch,
):
    environment = _configure_environment(monkeypatch, tmp_path)
    previous = _day(
        tmp_path,
        monkeypatch,
        _start(monkeypatch, date="2026-08-14"),
        date="2026-08-14",
    )
    for date in (
        "2026-08-17",
        "2026-08-18",
        "2026-08-19",
        "2026-08-20",
        "2026-08-21",
    ):
        previous = _day(
            tmp_path,
            monkeypatch,
            _start(
                monkeypatch,
                date=date,
                predecessor_object_id=previous.envelope.object_id,
            ),
            date=date,
        )
    assert shadow_trial.build_shadow_streak_report()["phase"] == "readiness_candidate"

    hostile_root = tmp_path / "hostile-copy" / "manual_shadow"
    shutil.copytree(environment["manual_root"], hostile_root)
    monkeypatch.setattr(shadow_trial, "_manual_shadow_root", lambda: hostile_root)

    with pytest.raises(ValueError, match="anchor|head|root|ledger"):
        shadow_trial.build_shadow_streak_report()


def test_round4_pre_failure_root_rollback_cannot_hide_later_history(
    tmp_path,
    monkeypatch,
):
    environment = _configure_environment(monkeypatch, tmp_path)
    qualification = _day(
        tmp_path,
        monkeypatch,
        _start(monkeypatch, date="2026-08-19"),
        date="2026-08-19",
    )
    old_root = tmp_path / "pre-failure-root"
    shutil.copytree(environment["manual_root"], old_root)

    failed_start = _start(
        monkeypatch,
        date="2026-08-20",
        predecessor_object_id=qualification.envelope.object_id,
    )
    _day(
        tmp_path,
        monkeypatch,
        failed_start,
        date="2026-08-20",
        artifacts={
            "safety_sentinel": tmp_path / "missing-sentinel",
            "paper_tournament": tmp_path / "missing-paper",
        },
    )
    shutil.rmtree(environment["manual_root"])
    shutil.copytree(old_root, environment["manual_root"])

    with pytest.raises(ValueError, match="anchor|head|rollback|ledger"):
        shadow_trial.build_shadow_streak_report()


def test_round4_uncommitted_anchor_advance_fails_closed(tmp_path, monkeypatch):
    environment = _configure_environment(monkeypatch, tmp_path)
    _set_clock(monkeypatch, "2026-08-21")
    monkeypatch.setattr(
        shadow_trial,
        "_capture_calendar_evidence",
        lambda market_date: _calendar(market_date),
    )
    original_write = shadow_trial._write_anchor
    write_count = 0

    def fail_after_ledger_append(parent_fd, anchor):
        nonlocal write_count
        write_count += 1
        if write_count == 3:
            raise ValueError("simulated trusted-head commit interruption")
        return original_write(parent_fd, anchor)

    monkeypatch.setattr(shadow_trial, "_write_anchor", fail_after_ledger_append)
    with pytest.raises(ValueError, match="commit interruption"):
        shadow_trial.create_shadow_day_start_manifest(
            run_id="interrupted-anchor",
            market_date="2026-08-21",
        )
    assert (environment["manual_root"] / "events.jsonl").is_file()

    with pytest.raises(ValueError, match="advanced|trusted head|anchor"):
        shadow_trial.load_shadow_record(
            "manual-shadow-day-start-" + "0" * 64,
            expected_kind="manual-shadow-day-start",
        )


def test_red_legacy_generic_manual_journal_without_reserved_route_cannot_replay(tmp_path, monkeypatch):
    environment = _configure_environment(monkeypatch, tmp_path)
    start = _start(monkeypatch, date="2026-08-21")
    journal = environment["manual_root"] / "events.jsonl"
    line = json.loads(journal.read_text(encoding="utf-8"))
    assert isinstance(line["admission_route"], str)
    assert len(line["admission_route"]) == 64
    int(line["admission_route"], 16)
    del line["admission_route"]
    journal.write_text(
        json.dumps(line, separators=(",", ":"), sort_keys=True) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="ledger|event|evidence"):
        shadow_trial.load_shadow_record(
            start.envelope.object_id,
            expected_kind="manual-shadow-day-start",
        )


def test_red_self_written_reserved_object_without_event_blocks_replay(tmp_path, monkeypatch):
    environment = _configure_environment(monkeypatch, tmp_path)
    start = _start(monkeypatch, date="2026-08-21")
    payload = _payload(start)
    payload["run_id"] = "self-written-unadmitted"
    candidate = EvidenceCandidate(
        kind="manual-shadow-day-start",
        effective_at=start.envelope.effective_at,
        payload=payload,
    )
    retry_material = evidence_store_module._retry_material_bytes(
        kind=candidate.kind,
        effective_at=candidate.effective_at,
        payload=candidate.payload,
    )
    retry_sha256 = hashlib.sha256(retry_material).hexdigest()
    orphan = evidence_store_module.EvidenceEnvelope(
        kind=candidate.kind,
        object_id=f"{candidate.kind}-{retry_sha256}",
        effective_at=candidate.effective_at,
        recorded_at=start.envelope.recorded_at,
        retry_material_sha256=retry_sha256,
        payload_sha256=hashlib.sha256(
            evidence_store_module._payload_bytes(candidate.payload)
        ).hexdigest(),
        payload=candidate.payload,
        admission_route=start.envelope.admission_route,
    )
    orphan_path = (
        environment["manual_root"]
        / "objects"
        / candidate.kind
        / f"{orphan.object_id}.json"
    )
    orphan_path.write_bytes(orphan.canonical_json_bytes())
    with pytest.raises(ValueError, match="unadmitted|ledger|evidence"):
        shadow_trial.load_shadow_record(
            start.envelope.object_id,
            expected_kind="manual-shadow-day-start",
        )


def test_red_reserved_manual_shadow_root_rejects_symlink_escape(tmp_path, monkeypatch):
    environment = _configure_environment(monkeypatch, tmp_path)
    escaped = tmp_path / "escaped"
    escaped.mkdir()
    environment["manual_root"].parent.mkdir(parents=True, exist_ok=True)
    environment["manual_root"].symlink_to(escaped, target_is_directory=True)
    with pytest.raises(ValueError, match="ledger|evidence|root|unsafe"):
        _start(monkeypatch, date="2026-08-21")


def test_red_start_api_has_no_caller_controlled_authority_paths_or_phase(tmp_path, monkeypatch):
    _configure_environment(monkeypatch, tmp_path)
    signature = inspect.signature(shadow_trial.create_shadow_day_start_manifest)
    for forbidden in (
        "ledger_id",
        "phase",
        "calendar_evidence",
        "live_control_path",
        "schedule_contract_path",
        "role_contract_path",
        "automation_root",
    ):
        assert forbidden not in signature.parameters
    with pytest.raises(TypeError):
        shadow_trial.create_shadow_day_start_manifest(  # type: ignore[call-arg]
            run_id="bad", market_date="2026-08-21", calendar_evidence=_calendar("2026-08-21"),
            live_control_path=tmp_path / "substitute.json",
        )


def test_red_schedule_binding_ignores_caller_controlled_codex_home(
    tmp_path,
    monkeypatch,
):
    codex_home = tmp_path / "caller-controlled-codex-home"
    contract, roles, alternate_root = _write_schedule_fixture(codex_home)
    captured_at = _moment("2026-08-21")
    alternate_snapshot = shadow_trial.capture_schedule_contract_snapshot(
        contract_path=contract,
        automation_root=alternate_root,
        role_contract_path=roles,
        captured_at=captured_at,
    )
    observed_roots: list[Path] = []

    def capture_only_alternate_root(**kwargs):
        observed_root = Path(kwargs["automation_root"])
        observed_roots.append(observed_root)
        if observed_root == alternate_root.resolve():
            return alternate_snapshot
        raise FileNotFoundError("canonical production root is absent from this fixture")

    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    monkeypatch.setattr(
        shadow_trial,
        "_canonical_schedule_contract_path",
        lambda: contract,
    )
    monkeypatch.setattr(
        shadow_trial,
        "_canonical_role_contract_path",
        lambda: roles,
    )
    monkeypatch.setattr(
        shadow_trial,
        "capture_schedule_contract_snapshot",
        capture_only_alternate_root,
    )

    binding, valid = shadow_trial._schedule_binding(captured_at=captured_at)

    assert binding["automation_root"] == "/Users/corbinfloyd/.codex/automations"
    assert binding["automation_root"] != str(alternate_root.resolve())
    assert observed_roots == [Path("/Users/corbinfloyd/.codex/automations")]
    assert valid is False


def test_private_automation_root_seam_preserves_positive_schedule_fixture(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "ignored-codex-home"))
    environment = _configure_environment(monkeypatch, tmp_path)

    binding, valid = shadow_trial._schedule_binding(
        captured_at=_moment("2026-08-21"),
    )

    assert valid is True
    assert binding["automation_root"] == str(environment["automation_root"].resolve())


def test_red_live_control_validation_uses_the_exact_captured_bytes(tmp_path, monkeypatch):
    environment = _configure_environment(monkeypatch, tmp_path)
    _set_clock(monkeypatch, "2026-08-21")
    capture = shadow_trial._read_regular_json

    def capture_then_replace(path):
        result = capture(path)
        if Path(path) == environment["control"]:
            _control(environment["control"], frozen=False)
        return result

    monkeypatch.setattr(shadow_trial, "_read_regular_json", capture_then_replace)
    monkeypatch.setattr(
        shadow_trial,
        "_capture_calendar_evidence",
        lambda market_date: _calendar(market_date),
    )
    start = shadow_trial.create_shadow_day_start_manifest(
        run_id="race-safe",
        market_date="2026-08-21",
    )
    assert _payload(start)["live_control"]["frozen"] is True
    assert json.loads(environment["control"].read_text(encoding="utf-8"))["frozen"] is False


@pytest.mark.parametrize("frozen,malformed", [(False, False), (True, True)])
def test_red_nonfrozen_or_malformed_canonical_control_cannot_start(tmp_path, monkeypatch, frozen, malformed):
    _configure_environment(monkeypatch, tmp_path, frozen=frozen, malformed_control=malformed)
    with pytest.raises(ValueError, match="live.control"):
        _start(monkeypatch, date="2026-08-21")


@pytest.mark.parametrize("active_id,omit_id", [("tradingagents-market-supervisor", None), (None, "tradingagents-market-supervisor")])
def test_red_exact_ten_paused_canonical_schedule_is_required(tmp_path, monkeypatch, active_id, omit_id):
    _configure_environment(monkeypatch, tmp_path, active_id=active_id, omit_id=omit_id)
    with pytest.raises(ValueError, match="schedule"):
        _start(monkeypatch, date="2026-08-21")


def test_red_calendar_is_mandatory_current_and_regular(tmp_path, monkeypatch):
    _configure_environment(monkeypatch, tmp_path)
    _set_clock(monkeypatch, "2026-08-21")
    substituted = _calendar("2026-08-21")
    substituted["kind"] = "caller-selected-calendar"
    for evidence in (
        None,
        _calendar("2026-08-21", dates=[]),
        _calendar("2026-08-21", dates=["2026-08-20"]),
        _calendar("2026-08-21", observed_at="2026-08-20T14:00:00+00:00"),
        _calendar("2026-08-21", observed_at="2026-08-21T14:00:01+00:00"),
        substituted,
    ):
        with monkeypatch.context() as calendar_patch:
            calendar_patch.setattr(
                shadow_trial,
                "_capture_calendar_evidence",
                lambda _market_date, captured=evidence: captured,
            )
            with pytest.raises(ValueError, match="calendar"):
                shadow_trial.create_shadow_day_start_manifest(
                    run_id="calendar-fail",
                    market_date="2026-08-21",
                )
    monkeypatch.setattr(
        shadow_trial,
        "_capture_calendar_evidence",
        lambda market_date: _calendar(market_date),
    )
    with pytest.raises(ValueError, match="current Central date"):
        shadow_trial.create_shadow_day_start_manifest(
            run_id="holiday",
            market_date="2026-08-20",
        )


def test_red_calendar_provider_failure_fails_closed(tmp_path, monkeypatch):
    _configure_environment(monkeypatch, tmp_path)
    _set_clock(monkeypatch, "2026-08-21")

    class FailingCalendar:
        def list_calendar(self, *, start: str, end: str):
            raise RuntimeError(f"unavailable calendar for {start} through {end}")

    monkeypatch.setattr(cli_main, "_alpaca_live_client", FailingCalendar)
    with pytest.raises(ValueError, match="calendar"):
        shadow_trial.create_shadow_day_start_manifest(
            run_id="calendar-provider-failure",
            market_date="2026-08-21",
        )


def test_red_repeated_adjudication_and_corrupt_or_deleted_ledger_fail_closed(tmp_path, monkeypatch):
    environment = _configure_environment(monkeypatch, tmp_path)
    start = _start(monkeypatch, date="2026-08-21")
    _day(tmp_path, monkeypatch, start, date="2026-08-21")
    with pytest.raises(ValueError, match="already has|successor|transition"):
        _day(tmp_path, monkeypatch, start, date="2026-08-21")
    journal = environment["manual_root"] / "events.jsonl"
    journal.write_text("{bad journal}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="ledger|evidence|journal"):
        shadow_trial.build_shadow_streak_report()


def test_red_deleted_admitted_object_fails_pinned_ledger_replay(tmp_path, monkeypatch):
    _configure_environment(monkeypatch, tmp_path)
    start = _start(monkeypatch, date="2026-08-21")
    start.path.unlink()
    with pytest.raises(ValueError, match="ledger|evidence|object"):
        shadow_trial.load_shadow_record(start.envelope.object_id)


def test_red_artifact_bindings_reject_bool_submission_unknown_and_missing_proof(tmp_path, monkeypatch):
    _configure_environment(monkeypatch, tmp_path)
    start = _start(monkeypatch, date="2026-08-21")
    bad_artifacts = _complete_daily_chain(
        tmp_path,
        start=start,
        artifacts=_artifacts(
            tmp_path,
            run_id=_payload(start)["run_id"],
            date="2026-08-21",
            start_object_id=start.envelope.object_id,
            submitted_count=False,
        ),
    )
    decision = _day(tmp_path, monkeypatch, start, date="2026-08-21", artifacts=bad_artifacts)
    decision_payload = _payload(decision)
    assert decision_payload["status"] == "failed"
    assert any("paper_tournament" in reason for reason in decision_payload["reasons"])
    assert set(decision_payload["artifacts"]) == {
        "safety_sentinel",
        "paper_tournament",
        "daily_chain_manifest",
    }
    assert all("sha256" in binding for binding in decision_payload["artifacts"].values())
    with pytest.raises(ValueError, match="terminal|trial_complete|final-no-go|refuses"):
        shadow_trial.build_shadow_streak_report()
    report = shadow_trial.build_shadow_streak_report(final_no_go=True)
    assert report["phase"] == "readiness_no_go"


def test_red_clean_hold_and_zero_submission_are_valid_only_with_complete_bound_evidence(tmp_path, monkeypatch):
    _configure_environment(monkeypatch, tmp_path)
    start = _start(monkeypatch, date="2026-08-21")
    decision = _day(tmp_path, monkeypatch, start, date="2026-08-21")
    payload = _payload(decision)
    assert payload["status"] == "clean"
    assert payload["phase"] == "qualification_clean"
    assert payload["artifacts"]["paper_tournament"]["payload"]["submitted_count"] == 0


def _tournament_order_fixture(
    *,
    client_order_id: str = "ta-paperbot-current-aggressive-2608211508-1-nvda",
    order_id: str = "broker-order-1",
    symbol: str = "NVDA",
    side: str = "buy",
    order_type: str = "limit",
    status: str = "filled",
    created_at: str = "2026-08-21T15:08:00+00:00",
) -> dict:
    return {
        "strategy_id": "current-aggressive",
        "reason": "shadow qualification paper tick",
        "symbol": symbol,
        "side": side,
        "type": order_type,
        "time_in_force": "day",
        "notional": "1000.00",
        "limit_price": "218.43",
        "extended_hours": False,
        "client_order_id": client_order_id,
        "id": order_id,
        "status": status,
        "created_at": created_at,
    }


def _write_submitted_paper_artifact(root: Path, *, start, orders: list[dict]) -> Path:
    payload = _payload(start)
    date = payload["market_date"]
    packet = {
        "kind": "paper_tournament_run",
        "run_id": payload["run_id"],
        "market_date": date,
        "shadow_start_object_id": start.envelope.object_id,
        "generated_at": _stage_timeline(date)["paper_tournament"],
        "status": "COMPLETE",
        "dry_run": False,
        "submitted_count": len(orders),
        "submitted": orders,
        "analysis_only": True,
        "execution_authority": "none",
        "can_submit_orders": False,
    }
    path = root / "artifacts" / f"paper-submitted-{date}.json"
    _write_json(path, packet)
    return path


def _bound_reconciliation_packet(start, *, all_orders: list[dict], captured_at: str) -> dict:
    payload = _payload(start)
    healthy_live = _healthy_broker_snapshot(date=payload["market_date"], account_id="live-account")
    healthy_paper = _healthy_broker_snapshot(date=payload["market_date"], account_id="paper-account")
    healthy_live["captured_at"] = captured_at
    healthy_paper["captured_at"] = captured_at
    healthy_paper["all_orders"] = all_orders
    return {
        "kind": "broker_reconciliation_observer",
        "run_id": payload["run_id"],
        "market_date": payload["market_date"],
        "shadow_start_object_id": start.envelope.object_id,
        "generated_at": captured_at,
        "status": "COMPLETE",
        "analysis_only": True,
        "execution_authority": "none",
        "can_submit_orders": False,
        "read_only": True,
        "submitted_count": 0,
        "cancelled_count": 0,
        "live": healthy_live,
        "paper": healthy_paper,
    }


def _adjudicate_day_with_paper_submission(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    mutate_reconciliation=None,
    mutate_manifest=None,
    orders: list[dict] | None = None,
    reconciliation_all_orders: list[dict] | None = None,
):
    _configure_environment(monkeypatch, tmp_path)
    start = _start(monkeypatch, date="2026-08-21")
    payload = _payload(start)
    date = payload["market_date"]
    submitted_orders = [_tournament_order_fixture()] if orders is None else orders
    observed_orders = (
        [dict(order) for order in submitted_orders]
        if reconciliation_all_orders is None
        else reconciliation_all_orders
    )
    sentinel_path = _artifacts(
        tmp_path,
        run_id=payload["run_id"],
        date=date,
        start_object_id=start.envelope.object_id,
    )["safety_sentinel"]
    paper_path = _write_submitted_paper_artifact(tmp_path, start=start, orders=submitted_orders)
    artifacts = {"safety_sentinel": sentinel_path, "paper_tournament": paper_path}
    _complete_daily_chain(tmp_path, start=start, artifacts=artifacts)
    reconciliation_packet = _bound_reconciliation_packet(
        start,
        all_orders=observed_orders,
        captured_at="2026-08-21T15:45:00+00:00",
    )
    if mutate_reconciliation is not None:
        mutate_reconciliation(reconciliation_packet)
    recon_path = tmp_path / "artifacts" / f"broker-reconciliation-bound-{date}.json"
    _write_json(recon_path, reconciliation_packet)
    stage_paths = {**artifacts, "broker_reconciliation": recon_path}
    _set_clock(monkeypatch, date, _DAY_CLOCK_HOUR)
    manifest_path = _rebind_daily_chain_manifest(tmp_path, start=start, artifacts=stage_paths)
    if mutate_manifest is not None:
        manifest_payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        mutate_manifest(manifest_payload)
        _write_json(manifest_path, manifest_payload)
    decision = _day(
        tmp_path,
        monkeypatch,
        start,
        date=date,
        artifacts={
            "safety_sentinel": stage_paths["safety_sentinel"],
            "paper_tournament": stage_paths["paper_tournament"],
            "daily_chain_manifest": manifest_path,
        },
    )
    return _payload(decision)


def test_red_clean_day_paper_orders_must_match_post_paper_reconciliation_exactly(tmp_path, monkeypatch):
    decision_payload = _adjudicate_day_with_paper_submission(tmp_path, monkeypatch)
    assert decision_payload["status"] == "clean"
    assert not any(reason.startswith("broker_reconciliation_") for reason in decision_payload["reasons"])


# Increment 6: the approved causal order of one shadow day.  The safety
# sentinel binds (:20) before the hourly dry-run (:35); the paper tick
# precedes its reconciliation; and the daily report follows the session
# close — an order that deliberately differs from the stage roster tuple.
APPROVED_DAILY_CHAIN_ORDER = (
    "overnight_research",
    "premarket_brief",
    "preopen_validation",
    "safety_sentinel",
    "hourly_supervisor",
    "loss_review",
    "execution_board",
    "self_heal_handoff",
    "self_heal_plan",
    "paper_tournament",
    "broker_reconciliation",
    "daily_report",
)
# Producer-precision exception: one self-healer automation run writes both
# packets back-to-back, so identical second-resolution stamps are a genuine
# tie.  Every other consecutive pair crosses separate scheduled producers.
LEGITIMATE_STAGE_TIES = {("self_heal_handoff", "self_heal_plan")}


def _adjudicate_chain_with_stage_stamps(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    date: str = "2026-08-21",
    stamps: dict[str, str] | None = None,
    calendar_kwargs: dict | None = None,
    dead_man_expires_at: str = "2027-06-30T00:00:00+00:00",
) -> dict:
    """Adjudicate one full day whose stage files carry explicit generated_at values."""

    _configure_environment(
        monkeypatch, tmp_path, dead_man_expires_at=dead_man_expires_at
    )
    start = _start(monkeypatch, date=date, calendar_kwargs=calendar_kwargs)
    payload = _payload(start)
    market_date = payload["market_date"]
    artifacts_map = _complete_daily_chain(
        tmp_path,
        start=start,
        artifacts=_artifacts(
            tmp_path,
            run_id=payload["run_id"],
            date=market_date,
            start_object_id=start.envelope.object_id,
        ),
    )
    stage_files = {
        "safety_sentinel": artifacts_map["safety_sentinel"],
        "paper_tournament": artifacts_map["paper_tournament"],
    }
    timeline = _stage_timeline(market_date)
    timeline.update(stamps or {})
    for name, stamp in timeline.items():
        path = stage_files.get(name) or (
            tmp_path / "artifacts" / f"{name}-{market_date}.json"
        )
        packet = json.loads(path.read_text(encoding="utf-8"))
        packet["generated_at"] = stamp
        _write_json(path, packet)
    _set_clock(monkeypatch, market_date, _DAY_CLOCK_HOUR)
    manifest_path = _rebind_daily_chain_manifest(tmp_path, start=start, artifacts=artifacts_map)
    decision = _day(
        tmp_path,
        monkeypatch,
        start,
        date=market_date,
        artifacts={**artifacts_map, "daily_chain_manifest": manifest_path},
    )
    return _payload(decision)


def test_red_valid_ascending_chain_with_in_session_paper_stays_clean(tmp_path, monkeypatch):
    payload = _adjudicate_chain_with_stage_stamps(tmp_path, monkeypatch)
    assert payload["status"] == "clean"
    for reason in payload["reasons"]:
        assert "order" not in reason
        assert "session" not in reason


@pytest.mark.parametrize(
    ("earlier_stage", "later_stage"),
    [
        *[
            pytest.param(a, b, id=f"{a}-after-{b}")
            for a, b in zip(APPROVED_DAILY_CHAIN_ORDER, APPROVED_DAILY_CHAIN_ORDER[1:], strict=False)
        ],
        pytest.param("overnight_research", "daily_report", id="far-swap-first-last"),
    ],
)
def test_red_backward_or_swapped_stage_timestamps_are_never_clean(
    tmp_path, monkeypatch, earlier_stage, later_stage
):
    timeline = _stage_timeline("2026-08-21")
    swapped = dict(timeline)
    swapped[earlier_stage] = timeline[later_stage]
    swapped[later_stage] = timeline[earlier_stage]
    payload = _adjudicate_chain_with_stage_stamps(tmp_path, monkeypatch, stamps=swapped)
    assert payload["status"] != "clean"
    assert "daily_chain_stage_order_backward" in payload["reasons"]


def test_red_paper_after_reconciliation_reversal_is_never_clean(tmp_path, monkeypatch):
    timeline = _stage_timeline("2026-08-21")
    payload = _adjudicate_chain_with_stage_stamps(
        tmp_path,
        monkeypatch,
        stamps={
            **timeline,
            "paper_tournament": timeline["broker_reconciliation"],
            "broker_reconciliation": timeline["paper_tournament"],
        },
    )
    assert payload["status"] != "clean"
    assert "daily_chain_stage_order_backward" in payload["reasons"]


@pytest.mark.parametrize(
    ("first_stage", "second_stage"),
    [
        pytest.param(a, b, id=f"tie-{a}-{b}")
        for a, b in zip(APPROVED_DAILY_CHAIN_ORDER, APPROVED_DAILY_CHAIN_ORDER[1:], strict=False)
    ],
)
def test_red_equal_stage_timestamps_fail_except_documented_producer_tie(
    tmp_path, monkeypatch, first_stage, second_stage
):
    timeline = _stage_timeline("2026-08-21")
    stamps = dict(timeline)
    stamps[second_stage] = timeline[first_stage]
    should_stay_clean = (first_stage, second_stage) in LEGITIMATE_STAGE_TIES
    payload = _adjudicate_chain_with_stage_stamps(tmp_path, monkeypatch, stamps=stamps)
    if should_stay_clean:
        assert payload["status"] == "clean"
        assert "daily_chain_stage_order_tie_illegitimate" not in payload["reasons"]
    else:
        assert payload["status"] != "clean"
        assert "daily_chain_stage_order_tie_illegitimate" in payload["reasons"]
        assert "daily_chain_stage_order_backward" not in payload["reasons"]


@pytest.mark.parametrize(
    ("paper_stamp", "calendar_kwargs", "expected_clean"),
    [
        pytest.param("2026-08-21T13:00:00+00:00", None, False, id="before-open-et"),
        pytest.param("2026-08-21T20:30:00+00:00", None, False, id="after-close-et"),
        pytest.param(
            "2026-08-21T17:30:00+00:00",
            {"close_text": "13:00"},
            False,
            id="after-early-close",
        ),
        pytest.param(
            "2026-08-21T16:30:00+00:00",
            {"close_text": "13:00", "reconciliation_stamp": "2026-08-21T17:10:00+00:00"},
            True,
            id="inside-early-close-stays-clean",
        ),
    ],
)
def test_red_paper_tick_outside_admitted_regular_session_is_never_clean(
    tmp_path, monkeypatch, paper_stamp, calendar_kwargs, expected_clean
):
    timeline = _stage_timeline("2026-08-21")
    stamps = {**timeline, "paper_tournament": paper_stamp}
    reconciliation_stamp = (calendar_kwargs or {}).pop("reconciliation_stamp", None)
    if reconciliation_stamp is not None:
        stamps["broker_reconciliation"] = reconciliation_stamp
    payload = _adjudicate_chain_with_stage_stamps(
        tmp_path,
        monkeypatch,
        stamps=stamps,
        calendar_kwargs=calendar_kwargs,
    )
    if expected_clean:
        assert payload["status"] == "clean"
        assert "paper_tournament_stage_outside_regular_session" not in payload["reasons"]
    else:
        assert payload["status"] != "clean"
        assert "paper_tournament_stage_outside_regular_session" in payload["reasons"]


@pytest.mark.parametrize(
    ("report_stamp", "calendar_kwargs", "expected_clean"),
    [
        pytest.param("2026-08-21T19:00:00+00:00", None, False, id="before-session-close"),
        pytest.param(
            "2026-08-21T16:00:00+00:00",
            {"close_text": "13:00"},
            False,
            id="before-early-close",
        ),
        pytest.param(
            "2026-08-21T17:00:00+00:00",
            {"close_text": "13:00"},
            True,
            id="at-early-close-or-later-stays-clean",
        ),
    ],
)
def test_red_daily_report_must_follow_the_admitted_session_close(
    tmp_path, monkeypatch, report_stamp, calendar_kwargs, expected_clean
):
    timeline = _stage_timeline("2026-08-21")
    payload = _adjudicate_chain_with_stage_stamps(
        tmp_path,
        monkeypatch,
        stamps={**timeline, "daily_report": report_stamp},
        calendar_kwargs=calendar_kwargs,
    )
    if expected_clean:
        assert payload["status"] == "clean"
        assert "daily_report_stage_before_session_close" not in payload["reasons"]
    else:
        assert payload["status"] != "clean"
        assert "daily_report_stage_before_session_close" in payload["reasons"]


def test_red_winter_session_window_is_derived_from_admitted_calendar_data(tmp_path, monkeypatch):
    # CST/EST date: 09:30-16:00 ET is 14:30-21:00 UTC, so the default ascending
    # chain stays clean while a stamp that only a fixed CDT assumption would
    # admit (14:11 UTC = 08:11 CST) is rejected as before the EST open.
    clean_payload = _adjudicate_chain_with_stage_stamps(tmp_path, monkeypatch, date="2027-01-04")
    assert clean_payload["status"] == "clean"
    assert "paper_tournament_stage_outside_regular_session" not in clean_payload["reasons"]

    rejected_payload = _adjudicate_chain_with_stage_stamps(
        tmp_path / "winter-rejected",
        monkeypatch,
        date="2027-01-04",
        stamps={
            **_stage_timeline("2027-01-04"),
            "overnight_research": "2027-01-04T14:02:00+00:00",
            "premarket_brief": "2027-01-04T14:03:00+00:00",
            "preopen_validation": "2027-01-04T14:04:00+00:00",
            "safety_sentinel": "2027-01-04T14:05:00+00:00",
            "hourly_supervisor": "2027-01-04T14:06:00+00:00",
            "loss_review": "2027-01-04T14:07:00+00:00",
            "execution_board": "2027-01-04T14:08:00+00:00",
            "self_heal_handoff": "2027-01-04T14:09:00+00:00",
            "self_heal_plan": "2027-01-04T14:10:00+00:00",
            "paper_tournament": "2027-01-04T14:11:00+00:00",
        },
    )
    assert rejected_payload["status"] != "clean"
    assert "paper_tournament_stage_outside_regular_session" in rejected_payload["reasons"]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        pytest.param("09:30", dt.time(9, 30), id="ascii-open"),
        pytest.param("16:00", dt.time(16, 0), id="ascii-close"),
        pytest.param("23:59", dt.time(23, 59), id="ascii-max"),
        pytest.param("9:30", None, id="short-hour"),
        pytest.param("09:60", None, id="minute-out-of-range"),
        pytest.param("²²:³³", None, id="superscript-digits"),
        pytest.param("١٦:٠٠", None, id="arabic-indic-digits"),
        pytest.param("0٩:30", None, id="mixed-ascii-and-unicode-digit"),
    ],
)
def test_red_exchange_wall_time_accepts_only_strict_ascii_digits(value, expected):
    assert shadow_trial._parse_exchange_wall_time(value) == expected


def test_red_unicode_digit_session_walls_fail_closed_without_raising(tmp_path, monkeypatch):
    # A start can be admitted with non-ASCII digit session walls because the
    # calendar binding validates the admitted date only.  Adjudication must
    # then yield a fail-closed non-clean day with the existing
    # daily_chain_session_window_unavailable reason — never a crash.
    payload = _adjudicate_chain_with_stage_stamps(
        tmp_path,
        monkeypatch,
        calendar_kwargs={"open_text": "²²:³³", "close_text": "¹⁶:⁰⁰"},
    )
    assert payload["status"] == "incomplete"
    assert "daily_chain_session_window_unavailable" in payload["reasons"]


def test_red_manifest_cannot_precede_its_bound_stage_evidence(tmp_path, monkeypatch):
    _configure_environment(monkeypatch, tmp_path)
    start = _start(monkeypatch, date="2026-08-21")
    payload = _payload(start)
    market_date = payload["market_date"]
    artifacts_map = _complete_daily_chain(
        tmp_path,
        start=start,
        artifacts=_artifacts(
            tmp_path,
            run_id=payload["run_id"],
            date=market_date,
            start_object_id=start.envelope.object_id,
        ),
    )
    # Seal the manifest before the daily-report evidence exists in time.
    _set_clock(monkeypatch, market_date, 15)
    manifest_path = _rebind_daily_chain_manifest(tmp_path, start=start, artifacts=artifacts_map)
    decision = _day(
        tmp_path,
        monkeypatch,
        start,
        date=market_date,
        artifacts={**artifacts_map, "daily_chain_manifest": manifest_path},
    )
    result = _payload(decision)
    assert result["status"] != "clean"
    assert "daily_chain_manifest_precedes_stage" in result["reasons"]


@pytest.mark.parametrize(
    ("mutate", "expected_reason"),
    [
        pytest.param(
            lambda packet: packet["paper"].__setitem__(
                "all_orders", []
            ),
            "broker_reconciliation_missing_tournament_order",
            id="missing",
        ),
        pytest.param(
            lambda packet: packet["paper"]["all_orders"].append(
                dict(packet["paper"]["all_orders"][0])
            ),
            "broker_reconciliation_duplicate_tournament_order",
            id="duplicate",
        ),
        pytest.param(
            lambda packet: packet["paper"]["all_orders"].append(
                _tournament_order_fixture(
                    client_order_id="ta-paperbot-current-aggressive-2608211545-9-tsla",
                    order_id="broker-order-9",
                    symbol="TSLA",
                )
            ),
            "broker_reconciliation_extra_tournament_order",
            id="extra",
        ),
        pytest.param(
            lambda packet: packet["paper"]["all_orders"][0].__setitem__(
                "id", "broker-order-999"
            ),
            "broker_reconciliation_mismatched_tournament_order",
            id="mismatched-broker-id",
        ),
        pytest.param(
            lambda packet: packet["paper"]["all_orders"][0].__setitem__(
                "symbol", "MSFT"
            ),
            "broker_reconciliation_mismatched_tournament_order",
            id="mismatched-symbol",
        ),
        pytest.param(
            lambda packet: packet["paper"]["all_orders"][0].__setitem__("side", "sell"),
            "broker_reconciliation_mismatched_tournament_order",
            id="mismatched-side",
        ),
        pytest.param(
            lambda packet: packet["paper"]["all_orders"][0].__setitem__("type", "market"),
            "broker_reconciliation_mismatched_tournament_order",
            id="mismatched-type",
        ),
        pytest.param(
            lambda packet: packet["paper"]["all_orders"][0].__setitem__(
                "created_at", "2026-08-21T15:19:00+00:00"
            ),
            "broker_reconciliation_mismatched_tournament_order",
            id="reverse-timestamp",
        ),
        pytest.param(
            lambda packet: packet["paper"]["all_orders"][0].__setitem__("status", "new"),
            "broker_reconciliation_nonterminal_tournament_order",
            id="nonterminal",
        ),
        pytest.param(
            lambda packet: packet["paper"].__setitem__(
                "open_orders", [dict(packet["paper"]["all_orders"][0])]
            ),
            "broker_reconciliation_open_tournament_order_present",
            id="still-open-in-open-orders",
        ),
        pytest.param(
            lambda packet: packet["paper"].__setitem__(
                "captured_at", "2026-08-21T15:05:00+00:00"
            ),
            "broker_reconciliation_captured_before_last_paper_submission",
            id="reconciliation-captured-before-paper",
        ),
        pytest.param(
            lambda packet: packet["paper"].pop("all_orders"),
            "broker_reconciliation_tournament_evidence_invalid",
            id="missing-all-orders-evidence",
        ),
        pytest.param(
            lambda packet: packet["paper"].__setitem__("all_orders", ["junk"]),
            "broker_reconciliation_tournament_evidence_invalid",
            id="malformed-all-orders-evidence",
        ),
        pytest.param(
            lambda packet: packet["paper"].pop("open_orders"),
            "broker_reconciliation_tournament_evidence_invalid",
            id="absent-open-orders-evidence",
        ),
        pytest.param(
            lambda packet: packet["paper"].__setitem__("open_orders", ["junk"]),
            "broker_reconciliation_tournament_evidence_invalid",
            id="malformed-open-orders-entry",
        ),
    ],
)
def test_red_broken_paper_to_reconciliation_binding_is_never_clean(
    tmp_path, monkeypatch, mutate, expected_reason
):
    decision_payload = _adjudicate_day_with_paper_submission(
        tmp_path,
        monkeypatch,
        mutate_reconciliation=mutate,
    )
    assert decision_payload["status"] != "clean"
    assert expected_reason in decision_payload["reasons"]


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(lambda packet: packet["paper"].pop("open_orders"), id="absent"),
        pytest.param(
            lambda packet: packet["paper"].__setitem__("open_orders", ["junk"]),
            id="nonmapping-entry",
        ),
    ],
)
def test_red_empty_day_open_orders_defects_fail_closed_in_both_layers(
    tmp_path, monkeypatch, mutate
):
    """Quiet-day open_orders defects never stay clean: stage layer fails them
    (governing status) while the hardened binding helper adds its explicit
    invalid evidence reason as defense in depth."""

    decision_payload = _adjudicate_day_with_paper_submission(
        tmp_path,
        monkeypatch,
        orders=[],
        reconciliation_all_orders=[],
        mutate_reconciliation=mutate,
    )
    assert decision_payload["status"] == "failed"
    assert "broker_reconciliation_stage_semantics_invalid" in decision_payload["reasons"]
    assert "broker_reconciliation_tournament_evidence_invalid" in decision_payload["reasons"]


def test_red_reconciliation_tournament_entries_require_present_mapping_lists():
    healthy = {"all_orders": [], "open_orders": []}
    assert (
        shadow_trial._reconciliation_tournament_entries(healthy, "all_orders", "open_orders")
        == []
    )
    observed = shadow_trial._reconciliation_tournament_entries(
        {"open_orders": [{"client_order_id": "ta-paperbot-x-1"}]}, "open_orders"
    )
    assert observed == [{"client_order_id": "ta-paperbot-x-1"}]
    # Absent named list, non-list evidence, non-mapping item, bad snapshot.
    assert shadow_trial._reconciliation_tournament_entries({"all_orders": []}, "open_orders") is None
    assert shadow_trial._reconciliation_tournament_entries({"open_orders": "junk"}, "open_orders") is None
    assert shadow_trial._reconciliation_tournament_entries({"open_orders": ["x"]}, "open_orders") is None
    assert shadow_trial._reconciliation_tournament_entries("junk", "open_orders") is None


def test_red_stray_tournament_orders_in_reconciliation_block_an_empty_day(tmp_path, monkeypatch):
    stray = _tournament_order_fixture(
        client_order_id="ta-paperbot-current-aggressive-2608211520-7-amzn",
        order_id="broker-order-7",
        symbol="AMZN",
    )
    decision_payload = _adjudicate_day_with_paper_submission(
        tmp_path,
        monkeypatch,
        orders=[],
        reconciliation_all_orders=[stray],
    )
    assert decision_payload["status"] != "clean"
    assert "broker_reconciliation_unbound_tournament_order_present" in decision_payload["reasons"]


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(
            lambda packet: packet["paper"].pop("all_orders"),
            id="empty-day-missing-all-orders",
        ),
        pytest.param(
            lambda packet: packet["paper"].__setitem__("all_orders", "junk"),
            id="empty-day-malformed-all-orders",
        ),
        pytest.param(
            lambda packet: packet["paper"].__setitem__("all_orders", ["junk"]),
            id="empty-day-nonmapping-all-order-entry",
        ),
    ],
)
def test_red_empty_day_requires_valid_full_order_evidence_to_stay_clean(
    tmp_path, monkeypatch, mutate
):
    decision_payload = _adjudicate_day_with_paper_submission(
        tmp_path,
        monkeypatch,
        orders=[],
        reconciliation_all_orders=[],
        mutate_reconciliation=mutate,
    )
    assert decision_payload["status"] == "incomplete"
    assert "broker_reconciliation_tournament_evidence_invalid" in decision_payload["reasons"]


def test_red_forged_embedded_reconciliation_cannot_launder_broken_stage_evidence(
    tmp_path, monkeypatch
):
    def restore_orders_in_embedded_copy(manifest):
        manifest["broker_reconciliation"]["paper"]["all_orders"] = [
            _tournament_order_fixture()
        ]

    decision_payload = _adjudicate_day_with_paper_submission(
        tmp_path,
        monkeypatch,
        mutate_reconciliation=lambda packet: packet["paper"].__setitem__("all_orders", []),
        mutate_manifest=restore_orders_in_embedded_copy,
    )
    assert decision_payload["status"] != "clean"
    assert "broker_reconciliation_embedded_copy_mismatch" in decision_payload["reasons"]


def test_stage_semantics_accept_native_shapes_and_reject_provider_graph_and_broker_errors():
    overnight = {
        "generated_at": "2026-08-21T15:00:00+00:00",
        "analysis_only": True,
        "submitted": [],
        "overnight_quality": {
            "completion_status": "complete",
            "graph_failure_count": 0,
            "graph_attempt_failure_count": 0,
            "top_provider_bundle_error_count": 0,
            "requested_full_graph_limit": 1,
            "full_graph_limit": 1,
            "full_graph_count": 1,
            "full_graph_attempt_count": 1,
            "full_graph_success_count": 1,
            # The graph cap is one, but the real candidate universe may have
            # multiple tradable symbols.  Only one is graph-selected here.
            "tradable_count": 4,
            "per_ticker_timeout_minutes": 2,
            "time_budget_minutes": 3,
            "graph_config": {
                "graph_profile": "market-only",
                "selected_analysts": ["market"],
                "tool_free_analysts": ["market"],
                "max_output_tokens": 800,
                "max_completion_tokens": 800,
                "llm_timeout_seconds": 30,
                "llm_max_retries": 0,
                "max_debate_rounds": 0,
                "max_risk_discuss_rounds": 0,
            },
            "research_context_enabled": False,
            "research_context_packet_count": 0,
            "research_context_blocked_count": 0,
            "agent_intelligence_enabled": False,
            "agent_ledger_append_enabled": False,
            "top_provider_bundle_requested_count": 0,
            "top_provider_bundle_count": 0,
        },
    }
    assert shadow_trial._stage_semantic_reasons("overnight_research", overnight) == []
    broken_overnight = {
        **overnight,
        "overnight_quality": {**overnight["overnight_quality"], "graph_failure_count": 1},
    }
    assert "overnight_research_stage_provider_or_graph_failure" in shadow_trial._stage_semantic_reasons(
        "overnight_research", broken_overnight
    )
    assert "overnight_research_stage_graph_cap_invalid" in shadow_trial._stage_semantic_reasons(
        "overnight_research",
        {"overnight_quality": {**overnight["overnight_quality"], "full_graph_attempt_count": 2}},
    )
    for key in ("requested_full_graph_limit", "full_graph_limit"):
        assert "overnight_research_stage_graph_cap_invalid" in shadow_trial._stage_semantic_reasons(
            "overnight_research",
            {
                **overnight,
                "overnight_quality": {**overnight["overnight_quality"], key: True},
            },
        )
    for key in ("per_ticker_timeout_minutes", "time_budget_minutes"):
        assert "overnight_research_stage_bounds_invalid" in shadow_trial._stage_semantic_reasons(
            "overnight_research",
            {
                **overnight,
                "overnight_quality": {**overnight["overnight_quality"], key: 0},
            },
        )
    missing_graph_config = dict(overnight["overnight_quality"])
    missing_graph_config.pop("graph_config")
    assert "overnight_research_stage_graph_config_invalid" in shadow_trial._stage_semantic_reasons(
        "overnight_research",
        {**overnight, "overnight_quality": missing_graph_config},
    )

    hourly = {
        "shadow_dry_run": True,
        "outbox_suppressed": True,
        "outbox_write_allowed": False,
        "decision": "profit-take",
        "submitted": [],
        "issues": [],
    }
    assert shadow_trial._stage_semantic_reasons("hourly_supervisor", hourly) == []
    assert "hourly_supervisor_stage_issue_present" in shadow_trial._stage_semantic_reasons(
        "hourly_supervisor", {**hourly, "issues": [{"category": "lock", "reason": "stale evidence"}]}
    )

    reconciliation = {
        "kind": "broker_reconciliation_observer",
        "status": "COMPLETE",
        "analysis_only": True,
        "execution_authority": "none",
        "can_submit_orders": False,
        "read_only": True,
        "submitted_count": 0,
        "cancelled_count": 0,
        "live": _healthy_broker_snapshot(date="2026-08-21", account_id="live-account"),
        "paper": _healthy_broker_snapshot(date="2026-08-21", account_id="paper-account"),
    }
    assert shadow_trial._stage_semantic_reasons("broker_reconciliation", reconciliation) == []
    broken_reconciliation = {
        **reconciliation,
        "live": {**reconciliation["live"], "errors": {"orders": "timeout"}},
    }
    assert "broker_reconciliation_stage_semantics_invalid" in shadow_trial._stage_semantic_reasons(
        "broker_reconciliation", broken_reconciliation
    )
    empty_snapshot = {
        **reconciliation,
        "live": {
            **reconciliation["live"],
            "account": {},
            "clock": {},
        },
    }
    assert "broker_reconciliation_stage_semantics_invalid" in shadow_trial._stage_semantic_reasons(
        "broker_reconciliation", empty_snapshot
    )

    loss_review = {
        "evidence_type": "loss_review_evidence",
        "payload": {
            "analysis_only": True,
            "execution_authority": "none",
            "can_submit_orders": False,
            "next_action": "autonomous_hold",
            "submitted_order_count": 0,
            "remaining_blockers": [],
            "current_loss_review": {
                "trade_decision_allowed": True,
                "blockers": [],
            },
            "advisory_analysis": {
                "route_summary": [
                    {
                        "status": "packet_written",
                        "blocked": False,
                    }
                ]
            },
        },
        "freshness": {"read_only": True, "can_submit_orders": False},
    }
    assert shadow_trial._stage_semantic_reasons("loss_review", loss_review) == []
    assert "loss_review_stage_schema_invalid" in shadow_trial._stage_semantic_reasons(
        "loss_review", {**loss_review, "evidence_type": "provider_summary"}
    )
    blocked_loss_review = {
        **loss_review,
        "payload": {
            **loss_review["payload"],
            "advisory_analysis": {
                "route_summary": [
                    {
                        "status": "packet_written",
                        "blocked": True,
                    }
                ]
            },
        },
    }
    blocked_reasons = shadow_trial._stage_semantic_reasons(
        "loss_review",
        blocked_loss_review,
    )
    assert "loss_review_stage_provider_failure" in blocked_reasons
    assert "loss_review_stage_incomplete" not in blocked_reasons
    incomplete_loss_review = {
        **loss_review,
        "payload": {
            **loss_review["payload"],
            "remaining_blockers": ["refreshed evidence is incomplete"],
            "current_loss_review": {
                "trade_decision_allowed": False,
                "blockers": ["refreshed evidence is incomplete"],
            },
        },
    }
    incomplete_reasons = shadow_trial._stage_semantic_reasons(
        "loss_review",
        incomplete_loss_review,
    )
    assert "loss_review_stage_incomplete" in incomplete_reasons
    assert "loss_review_stage_provider_failure" not in incomplete_reasons
    error_reasons = shadow_trial._stage_semantic_reasons(
        "loss_review",
        {
            **loss_review,
            "payload": {
                **loss_review["payload"],
                "errors": {"provider": "transport failed"},
            },
        },
    )
    assert "loss_review_stage_error_present" in error_reasons

    valid_empty_overnight = {
        **overnight,
        "overnight_quality": {
            **overnight["overnight_quality"],
            "full_graph_count": 0,
            "full_graph_attempt_count": 0,
            "full_graph_success_count": 0,
            "tradable_count": 0,
        },
        "ranked_candidates": [],
    }
    clean_day_stage_examples = {
        "overnight_research": valid_empty_overnight,
        "preopen_validation": {
            "analysis_only": True,
            "execution_authority": "none",
            "can_submit_orders": False,
            "submitted_count": 0,
            "overall_status": "pass",
            "failed_check_ids": [],
        },
        "hourly_supervisor": hourly,
        "daily_report": {"packet_count": 0, "portfolio": {}},
        "paper_tournament": {
            "analysis_only": True,
            "execution_authority": "none",
            "can_submit_orders": False,
            "status": "NO_PAPER_SIGNAL",
            "submitted": [],
            "submitted_count": 0,
        },
    }
    for stage, valid_empty_or_no_signal in clean_day_stage_examples.items():
        assert shadow_trial._stage_semantic_reasons(stage, valid_empty_or_no_signal) == []
        reasons = shadow_trial._stage_semantic_reasons(
            stage,
            {
                **valid_empty_or_no_signal,
                "errors": {"market_data": "provider transport failed"},
            },
        )
        assert f"{stage}_stage_error_present" in reasons

    execution_board = {
        "analysis_only": True,
        "execution_authority": "none",
        "can_submit_orders": False,
        "metrics": {"submitted_order_count": 0},
        "violations": [],
        "warnings": [],
    }
    assert shadow_trial._stage_semantic_reasons("execution_board", execution_board) == []
    assert "execution_board_stage_issue_present" in shadow_trial._stage_semantic_reasons(
        "execution_board", {**execution_board, "warnings": ["stale preopen evidence"]}
    )

    self_heal_handoff = {
        "analysis_only": True,
        "execution_authority": "none",
        "can_submit_orders": False,
        "active_trigger_count": 0,
        "max_severity": "none",
    }
    assert shadow_trial._stage_semantic_reasons("self_heal_handoff", self_heal_handoff) == []
    assert "self_heal_handoff_stage_active_trigger_present" in shadow_trial._stage_semantic_reasons(
        "self_heal_handoff", {**self_heal_handoff, "active_trigger_count": 1}
    )

    self_heal_plan = {
        "analysis_only": True,
        "execution_authority": "none",
        "can_submit_orders": False,
        "active_trigger_count": 0,
        "active_plan_count": 0,
        "escalation_count": 0,
        "max_severity": "none",
        "status": "quiet",
        "executed_count": 0,
    }
    assert shadow_trial._stage_semantic_reasons("self_heal_plan", self_heal_plan) == []
    self_heal_reasons = shadow_trial._stage_semantic_reasons(
        "self_heal_plan",
        {**self_heal_plan, "active_plan_count": 1, "status": "safe_plan_ready"},
    )
    assert "self_heal_plan_stage_active_plan_present" in self_heal_reasons
    assert "self_heal_plan_stage_status_invalid" in self_heal_reasons


def test_hourly_stage_requires_explicit_persisted_dry_run_marker():
    hourly = {"kind": "hourly_supervisor", "decision": "hold", "submitted": []}
    assert "hourly_supervisor_stage_not_dry_run" in shadow_trial._stage_semantic_reasons(
        "hourly_supervisor", hourly
    )
    assert shadow_trial._stage_semantic_reasons(
        "hourly_supervisor",
        {
            **hourly,
            "shadow_dry_run": True,
            "outbox_suppressed": True,
            "outbox_write_allowed": False,
        },
    ) == []


def test_safety_sentinel_rejects_extra_reason_or_missing_observer_proof(
    tmp_path,
    monkeypatch,
):
    sentinel, source_bindings = _bound_sentinel_shape(tmp_path, monkeypatch)

    assert shadow_trial._stage_semantic_reasons(
        "safety_sentinel",
        sentinel,
        sentinel_source_bindings=source_bindings,
    ) == []
    assert "safety_sentinel_stage_failure_reason_present" in shadow_trial._stage_semantic_reasons(
        "safety_sentinel",
        {**sentinel, "reasons": ["frozen_control", "preopen_validation_stale"]},
        sentinel_source_bindings=source_bindings,
    )
    missing_broker = dict(sentinel)
    missing_broker.pop("broker_snapshot")
    assert "safety_sentinel_stage_broker_proof_invalid" in shadow_trial._stage_semantic_reasons(
        "safety_sentinel",
        missing_broker,
        sentinel_source_bindings=source_bindings,
    )


def test_safety_sentinel_accepts_only_real_shape_bound_to_admitted_sources(
    tmp_path,
    monkeypatch,
):
    sentinel, source_bindings = _bound_sentinel_shape(tmp_path, monkeypatch)

    assert shadow_trial._stage_semantic_reasons(
        "safety_sentinel",
        sentinel,
        sentinel_source_bindings=source_bindings,
    ) == []


@pytest.mark.parametrize(
    "mutation,expected_reason",
    [
        ("wrong_automation_id", "safety_sentinel_stage_schedule_proof_invalid"),
        ("active_automation", "safety_sentinel_stage_schedule_proof_invalid"),
        ("wrong_exact_counts", "safety_sentinel_stage_schedule_proof_invalid"),
        ("alternate_live_control", "safety_sentinel_stage_source_proof_invalid"),
        ("alternate_preopen", "safety_sentinel_stage_source_proof_invalid"),
        ("alternate_schedule_contract", "safety_sentinel_stage_source_proof_invalid"),
    ],
)
def test_safety_sentinel_false_clean_roster_and_source_identities_fail_closed(
    tmp_path,
    monkeypatch,
    mutation,
    expected_reason,
):
    sentinel, source_bindings = _bound_sentinel_shape(tmp_path, monkeypatch)
    forged = copy.deepcopy(sentinel)
    if mutation == "wrong_automation_id":
        forged["schedule_check"]["automations"][0]["automation_id"] = "wrong-id"
    elif mutation == "active_automation":
        forged["schedule_check"]["automations"][0]["config_status"] = "ACTIVE"
    elif mutation == "wrong_exact_counts":
        forged["schedule_check"]["paused_count"] = 9
    elif mutation == "alternate_live_control":
        forged["evidence"]["live_control"]["path"] = "/tmp/alternate-live-control.json"
    elif mutation == "alternate_preopen":
        forged["evidence"]["preopen_validation"]["path"] = "/tmp/alternate-preopen.json"
    else:
        forged["evidence"]["schedule_configuration"]["contract"]["path"] = (
            "/tmp/alternate-schedule-contract.json"
        )

    assert expected_reason in shadow_trial._stage_semantic_reasons(
        "safety_sentinel",
        forged,
        sentinel_source_bindings=source_bindings,
    )


def test_daily_chain_manifest_rejects_missing_stage_and_replaced_stage_file(tmp_path, monkeypatch):
    _configure_environment(monkeypatch, tmp_path)
    start = _start(monkeypatch, date="2026-08-21")
    artifacts = _complete_daily_chain(
        tmp_path,
        start=start,
        artifacts=_artifacts(
            tmp_path,
            run_id=_payload(start)["run_id"],
            date="2026-08-21",
            start_object_id=start.envelope.object_id,
        ),
    )
    manifest_payload = json.loads(artifacts["daily_chain_manifest"].read_text(encoding="utf-8"))
    manifest_payload["stages"].pop("daily_report")
    _write_json(artifacts["daily_chain_manifest"], manifest_payload)
    decision = _day(tmp_path, monkeypatch, start, date="2026-08-21", artifacts=artifacts)
    assert _payload(decision)["status"] in {"failed", "incomplete"}
    assert any("daily_chain_manifest" in reason for reason in _payload(decision)["reasons"])

    _configure_environment(monkeypatch, tmp_path / "replacement")
    second = _start(monkeypatch, date="2026-08-21")
    replacement = _complete_daily_chain(
        tmp_path / "replacement",
        start=second,
        artifacts=_artifacts(
            tmp_path / "replacement",
            run_id=_payload(second)["run_id"],
            date="2026-08-21",
            start_object_id=second.envelope.object_id,
        ),
    )
    _write_json(replacement["safety_sentinel"], {"kind": "replaced"})
    decision = _day(tmp_path / "replacement", monkeypatch, second, date="2026-08-21", artifacts=replacement)
    assert _payload(decision)["status"] == "failed"
    assert "safety_sentinel_stage_hash_or_path_changed" in _payload(decision)["reasons"]


def test_stale_safety_sentinel_with_rebound_manifest_yields_non_clean_timestamp_reason(tmp_path, monkeypatch):
    _configure_environment(monkeypatch, tmp_path)
    start = _start(monkeypatch, date="2026-08-21")
    artifacts = _complete_daily_chain(
        tmp_path,
        start=start,
        artifacts=_artifacts(
            tmp_path,
            run_id=_payload(start)["run_id"],
            date="2026-08-21",
            start_object_id=start.envelope.object_id,
        ),
    )
    stale = json.loads(artifacts["safety_sentinel"].read_text(encoding="utf-8"))
    stale["generated_at"] = "2026-08-20T15:00:00+00:00"
    _write_json(artifacts["safety_sentinel"], stale)
    rebound = _rebind_daily_chain_manifest(tmp_path, start=start, artifacts=artifacts)
    decision = _day(
        tmp_path,
        monkeypatch,
        start,
        date="2026-08-21",
        artifacts={**artifacts, "daily_chain_manifest": rebound},
    )
    payload = _payload(decision)
    assert payload["status"] in {"failed", "incomplete"}
    assert "safety_sentinel_timestamp_out_of_window" in payload["reasons"]
    assert "safety_sentinel_stage_timestamp_invalid" in payload["reasons"]
    assert "safety_sentinel_stage_hash_or_path_changed" not in payload["reasons"]


def test_malformed_paper_tournament_with_rebound_manifest_yields_non_clean_unreadable_reason(tmp_path, monkeypatch):
    _configure_environment(monkeypatch, tmp_path)
    start = _start(monkeypatch, date="2026-08-21")
    artifacts = _complete_daily_chain(
        tmp_path,
        start=start,
        artifacts=_artifacts(
            tmp_path,
            run_id=_payload(start)["run_id"],
            date="2026-08-21",
            start_object_id=start.envelope.object_id,
        ),
    )
    artifacts["paper_tournament"].write_text('{"kind": "paper_tournament_run"', encoding="utf-8")
    rebound = _rebind_daily_chain_manifest(tmp_path, start=start, artifacts=artifacts)
    decision = _day(
        tmp_path,
        monkeypatch,
        start,
        date="2026-08-21",
        artifacts={**artifacts, "daily_chain_manifest": rebound},
    )
    payload = _payload(decision)
    assert payload["status"] in {"failed", "incomplete"}
    assert "paper_tournament_unreadable_or_unbound" in payload["reasons"]
    assert "paper_tournament_stage_unreadable" in payload["reasons"]
    assert "paper_tournament_stage_hash_or_path_changed" not in payload["reasons"]


def test_red_abort_shadow_day_closes_pending_terminal_failed_and_blocks_duplicates(tmp_path, monkeypatch):
    _configure_environment(monkeypatch, tmp_path)
    start = _start(monkeypatch, date="2026-08-21")
    artifacts = _artifacts(
        tmp_path,
        run_id=_payload(start)["run_id"],
        date="2026-08-21",
        start_object_id=start.envelope.object_id,
    )

    admission = shadow_trial.abort_shadow_day(
        start_object_id=start.envelope.object_id,
        stopped_at_stage="paper_tournament",
        notes="process interrupted after paper persistence",
        artifacts=artifacts,
    )
    payload = _payload(admission)
    assert payload["status"] == "failed"
    assert payload["status"] != "clean"
    assert payload["phase"] == "repair_required"
    assert payload["closure_kind"] == "operator_abort"
    assert payload["stopped_at_stage"] == "paper_tournament"
    assert payload["notes"] == "process interrupted after paper persistence"
    assert "shadow_day_aborted_by_operator" in payload["reasons"]
    assert "daily_chain_manifest_unreadable_or_unbound" in payload["reasons"]
    assert payload["start_object_id"] == start.envelope.object_id
    assert payload["run_id"] == _payload(start)["run_id"]
    assert payload["market_date"] == "2026-08-21"
    assert payload["role"] == "qualification"
    assert payload["artifacts"]["safety_sentinel"]["status"] == "captured"
    assert payload["artifacts"]["paper_tournament"]["status"] == "captured"
    assert payload["artifacts"]["daily_chain_manifest"]["status"] == "missing"
    assert admission.envelope.analysis_only is True
    assert admission.envelope.execution_authority == "none"
    assert admission.envelope.can_submit_orders is False

    with pytest.raises(ValueError, match="pending|abort"):
        shadow_trial.abort_shadow_day(
            start_object_id=start.envelope.object_id,
            stopped_at_stage="day_start",
            notes="duplicate closure attempt",
        )
    with pytest.raises(ValueError, match="admissible pending"):
        shadow_trial.adjudicate_shadow_day(start_object_id=start.envelope.object_id, artifacts={})

    status = shadow_trial.shadow_streak_status()
    assert status["clean_trial_streak"] == 0
    assert status["last_result"]["object_id"] == admission.envelope.object_id
    assert status["last_result"]["status"] == "failed"
    assert status["last_result"]["phase"] == "repair_required"
    assert status["pending_start"] is None
    assert status["can_start_next_day"] is True
    assert status["predecessor_object_id"] == admission.envelope.object_id

    _set_clock(monkeypatch, "2026-08-22")
    with monkeypatch.context() as calendar_patch:
        calendar_patch.setattr(
            shadow_trial,
            "_capture_calendar_evidence",
            lambda market_date: _calendar(market_date),
        )
        repair_start = shadow_trial.create_shadow_day_start_manifest(
            run_id="repair-after-abort",
            market_date="2026-08-22",
            predecessor_object_id=admission.envelope.object_id,
        )
    repair_payload = _payload(repair_start)
    assert repair_payload["role"] == "repair"
    assert repair_payload["phase"] == "repair_in_progress"
    assert repair_payload["predecessor_object_id"] == admission.envelope.object_id


def test_red_abort_refuses_wrong_identity_stale_date_and_nonpending_ledger(tmp_path, monkeypatch):
    _configure_environment(monkeypatch, tmp_path)
    start = _start(monkeypatch, date="2026-08-21")

    wrong_identity = "manual-shadow-day-start-" + "0" * 64
    with pytest.raises(ValueError, match="pending"):
        shadow_trial.abort_shadow_day(
            start_object_id=wrong_identity,
            stopped_at_stage="day_start",
            notes="wrong identity must be refused",
        )
    with pytest.raises(ValueError, match="stage"):
        shadow_trial.abort_shadow_day(
            start_object_id=start.envelope.object_id,
            stopped_at_stage="not-a-real-stage",
            notes="unknown stage key must be refused",
        )

    day = _day(tmp_path, monkeypatch, start, date="2026-08-21")
    assert _payload(day)["status"] == "clean"
    with pytest.raises(ValueError, match="pending"):
        shadow_trial.abort_shadow_day(
            start_object_id=start.envelope.object_id,
            stopped_at_stage="day_start",
            notes="already adjudicated ledger has no pending abort",
        )


def test_red_abort_refuses_when_market_date_is_no_longer_current(tmp_path, monkeypatch):
    _configure_environment(monkeypatch, tmp_path)
    start = _start(monkeypatch, date="2026-08-21")
    _set_clock(monkeypatch, "2026-08-22", 15)
    with pytest.raises(ValueError, match="Central"):
        shadow_trial.abort_shadow_day(
            start_object_id=start.envelope.object_id,
            stopped_at_stage="day_start",
            notes="stale abort must be refused; expire-pending owns this state",
        )
    admission = shadow_trial.expire_pending_shadow_day()
    assert admission is not None
    assert _payload(admission)["closure_kind"] == "pending_expired"


def test_red_expire_pending_converts_stale_start_to_immutable_incomplete(tmp_path, monkeypatch):
    environment = _configure_environment(monkeypatch, tmp_path)
    start = _start(monkeypatch, date="2026-08-21")

    _set_clock(monkeypatch, "2026-08-22", 14)
    admission = shadow_trial.expire_pending_shadow_day()
    assert admission is not None
    payload = _payload(admission)
    assert payload["status"] == "incomplete"
    assert payload["phase"] == "repair_required"
    assert payload["closure_kind"] == "pending_expired"
    assert payload["stopped_at_stage"] is None
    assert payload["notes"] is None
    assert list(payload["reasons"]) == ["pending_day_expired_without_adjudication"]
    assert set(payload["artifacts"]) == set(shadow_trial.ARTIFACT_KEYS)
    assert all(item["status"] == "missing" for item in payload["artifacts"].values())
    assert payload["start_object_id"] == start.envelope.object_id
    assert admission.envelope.analysis_only is True
    assert admission.envelope.execution_authority == "none"
    assert admission.envelope.can_submit_orders is False

    assert shadow_trial.expire_pending_shadow_day() is None
    with pytest.raises(ValueError, match="admissible pending"):
        shadow_trial.adjudicate_shadow_day(start_object_id=start.envelope.object_id, artifacts={})

    status = shadow_trial.shadow_streak_status()
    assert status["clean_trial_streak"] == 0
    assert status["last_result"]["object_id"] == admission.envelope.object_id
    assert status["last_result"]["status"] == "incomplete"
    assert status["can_start_next_day"] is True
    assert status["predecessor_object_id"] == admission.envelope.object_id

    with monkeypatch.context() as calendar_patch:
        calendar_patch.setattr(
            shadow_trial,
            "_capture_calendar_evidence",
            lambda market_date: _calendar(market_date),
        )
        repair_start = shadow_trial.create_shadow_day_start_manifest(
            run_id="repair-after-expiry",
            market_date="2026-08-22",
            predecessor_object_id=admission.envelope.object_id,
        )
    assert _payload(repair_start)["role"] == "repair"
    assert not (environment["manual_root"] / "objects" / "manual-shadow-final-report").exists()


def test_red_expire_leaves_same_date_pending_untouched(tmp_path, monkeypatch):
    environment = _configure_environment(monkeypatch, tmp_path)
    results_parent = environment["manual_root"].parent
    start = _start(monkeypatch, date="2026-08-21")

    before = _ledger_surface_snapshot(results_parent)
    assert shadow_trial.expire_pending_shadow_day() is None
    assert before == _ledger_surface_snapshot(results_parent)
    assert (
        shadow_trial.load_shadow_record(
            start.envelope.object_id,
            expected_kind="manual-shadow-day-start",
        ).object_id
        == start.envelope.object_id
    )


def test_red_expire_empty_ledger_is_observationally_pure(tmp_path, monkeypatch):
    environment = _configure_environment(monkeypatch, tmp_path)
    results_parent = environment["manual_root"].parent

    before = _ledger_surface_snapshot(results_parent)
    assert shadow_trial.expire_pending_shadow_day() is None
    assert before == _ledger_surface_snapshot(results_parent)
    assert not (results_parent / ".manual-shadow-trusted-head.lock").exists()


@pytest.mark.parametrize("stage", list(shadow_trial.SHADOW_DAY_STOP_STAGES))
def test_red_abort_interruption_matrix_admits_one_non_clean_result_per_stage(tmp_path, monkeypatch, stage):
    _environment = _configure_environment(monkeypatch, tmp_path)
    start = _start(monkeypatch, date="2026-08-21")

    admission = shadow_trial.abort_shadow_day(
        start_object_id=start.envelope.object_id,
        stopped_at_stage=stage,
        notes=f"interruption drill immediately after {stage}",
    )
    payload = _payload(admission)
    assert payload["status"] == "failed"
    assert payload["phase"] == "repair_required"
    assert payload["stopped_at_stage"] == stage
    assert "shadow_day_aborted_by_operator" in payload["reasons"]
    assert all(item["status"] == "missing" for item in payload["artifacts"].values())
    assert admission.envelope.can_submit_orders is False

    journal_lines = (
        _environment["manual_root"] / "events.jsonl"
    ).read_bytes().splitlines()
    assert len(journal_lines) == 2

    _set_clock(monkeypatch, "2026-08-22")
    with monkeypatch.context() as calendar_patch:
        calendar_patch.setattr(
            shadow_trial,
            "_capture_calendar_evidence",
            lambda market_date: _calendar(market_date),
        )
        recovery = shadow_trial.create_shadow_day_start_manifest(
            run_id=f"recover-{stage}",
            market_date="2026-08-22",
            predecessor_object_id=admission.envelope.object_id,
        )
    assert _payload(recovery)["predecessor_object_id"] == admission.envelope.object_id
    assert shadow_trial.shadow_streak_status()["can_start_next_day"] is False


def test_red_closure_facades_fail_closed_on_anchor_or_journal_damage(tmp_path, monkeypatch):
    environment = _configure_environment(monkeypatch, tmp_path)
    results_parent = environment["manual_root"].parent
    anchor_path = results_parent / ".manual-shadow-trusted-head.json"

    qualification_start = _start(monkeypatch, date="2026-08-21")
    qualification = _day(tmp_path, monkeypatch, qualification_start, date="2026-08-21")
    stranded = _start(
        monkeypatch,
        date="2026-08-22",
        predecessor_object_id=qualification.envelope.object_id,
    )
    _set_clock(monkeypatch, "2026-08-22", 18)

    anchor = json.loads(anchor_path.read_text(encoding="utf-8"))
    lines = (environment["manual_root"] / "events.jsonl").read_bytes().splitlines()

    def head_of(line: bytes, sequence: int) -> dict[str, object]:
        event = json.loads(line)
        return {
            "sequence": sequence,
            "kind": event["kind"],
            "object_id": event["object_id"],
            "event_sha256": hashlib.sha256(line).hexdigest(),
            "admission_route": event["admission_route"],
        }

    prior_head = head_of(lines[-2], len(lines) - 1)
    last_event = json.loads(lines[-1])
    anchor["committed_head"] = prior_head
    anchor["pending_next"] = {
        "prior_head": prior_head,
        "sequence": len(lines),
        "kind": last_event["kind"],
        "object_id": last_event["object_id"],
        "retry_material_sha256": last_event["retry_material_sha256"],
        "admission_route": last_event["admission_route"],
    }
    anchor_path.write_text(
        json.dumps(
            anchor,
            ensure_ascii=True,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    damaged_before = _ledger_surface_snapshot(results_parent)
    with pytest.raises(ValueError, match="advanced|unresolved|pending"):
        shadow_trial.abort_shadow_day(
            start_object_id=stranded.envelope.object_id,
            stopped_at_stage="day_start",
            notes="anchor damage must fail closed",
        )
    with pytest.raises(ValueError, match="advanced|unresolved|pending"):
        shadow_trial.expire_pending_shadow_day()
    assert damaged_before == _ledger_surface_snapshot(results_parent)

    anchor["committed_head"] = head_of(lines[-1], len(lines) - 1)
    anchor["pending_next"] = None
    anchor_path.write_text(
        json.dumps(
            anchor,
            ensure_ascii=True,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    object_path = (
        environment["manual_root"]
        / "objects"
        / "manual-shadow-day-start"
        / f"{stranded.envelope.object_id}.json"
    )
    object_path.unlink()
    journal_before = _ledger_surface_snapshot(results_parent)
    with pytest.raises(ValueError):
        shadow_trial.abort_shadow_day(
            start_object_id=stranded.envelope.object_id,
            stopped_at_stage="day_start",
            notes="journal damage must fail closed",
        )
    with pytest.raises(ValueError):
        shadow_trial.expire_pending_shadow_day()
    assert journal_before == _ledger_surface_snapshot(results_parent)


def test_red_cli_closure_commands_are_pinned_fail_closed_and_non_authorizing(tmp_path, monkeypatch):
    _configure_environment(monkeypatch, tmp_path)
    calendar = _CalendarFake({"2026-08-21"})
    monkeypatch.setattr(cli_main, "_alpaca_live_client", lambda: calendar)
    _set_clock(monkeypatch, "2026-08-21")

    abort_help = runner.invoke(app, ["research", "shadow-day-abort", "--help"])
    assert abort_help.exit_code == 0
    for forbidden in (
        "--now",
        "--ledger-id",
        "--live-control-path",
        "--schedule-contract-path",
        "--automation-root",
        "--force",
        "--dry-run",
        "--market-date",
    ):
        assert forbidden not in abort_help.output
    assert "--stopped-at-stage" in abort_help.output
    assert "--notes" in abort_help.output
    expire_help = runner.invoke(app, ["research", "shadow-day-expire-pending", "--help"])
    assert expire_help.exit_code == 0
    assert "--now" not in expire_help.output

    abort_parameters = inspect.signature(shadow_trial.abort_shadow_day).parameters
    assert list(abort_parameters) == ["start_object_id", "stopped_at_stage", "notes", "artifacts"]
    assert all(item.kind is inspect.Parameter.KEYWORD_ONLY for item in abort_parameters.values())
    assert abort_parameters["notes"].default is inspect.Parameter.empty
    assert abort_parameters["artifacts"].default is None
    assert not inspect.signature(shadow_trial.expire_pending_shadow_day).parameters

    started = runner.invoke(
        app,
        ["research", "shadow-day-start", "--run-id", "cli-abort-drill", "--market-date", "2026-08-21", "--json-output"],
    )
    assert started.exit_code == 0, started.output
    start_id = json.loads(started.stdout)["object_id"]
    calendar_calls_after_start = list(calendar.calls)

    same_date_expire = runner.invoke(app, ["research", "shadow-day-expire-pending", "--json-output"])
    assert same_date_expire.exit_code == 0, same_date_expire.output
    assert json.loads(same_date_expire.stdout)["expired"] is False

    bad_stage = runner.invoke(
        app,
        [
            "research", "shadow-day-abort",
            "--start-object-id", start_id,
            "--stopped-at-stage", "not-a-real-stage",
            "--notes", "bad stage",
        ],
    )
    assert bad_stage.exit_code != 0

    aborted = runner.invoke(
        app,
        [
            "research", "shadow-day-abort",
            "--start-object-id", start_id,
            "--stopped-at-stage", "safety_sentinel",
            "--notes", "cli interruption drill",
            "--json-output",
        ],
    )
    assert aborted.exit_code == 0, aborted.output
    aborted_payload = json.loads(aborted.stdout)
    assert aborted_payload["status"] == "failed"
    assert aborted_payload["phase"] == "repair_required"
    assert aborted_payload["closure_kind"] == "operator_abort"
    assert aborted_payload["stopped_at_stage"] == "safety_sentinel"
    assert aborted_payload["execution_authority"] == "none"
    assert aborted_payload["can_submit_orders"] is False
    assert calendar.calls == calendar_calls_after_start + [("2026-08-21", "2026-08-21")]

    duplicate = runner.invoke(
        app,
        [
            "research", "shadow-day-abort",
            "--start-object-id", start_id,
            "--stopped-at-stage", "day_start",
            "--notes", "duplicate closure attempt",
        ],
    )
    assert duplicate.exit_code != 0

    stale_second_start = runner.invoke(
        app,
        [
            "research", "shadow-day-start",
            "--run-id", "cli-repair-without-predecessor",
            "--market-date", "2026-08-21",
        ],
    )
    assert stale_second_start.exit_code != 0


def test_red_full_ledger_replay_requires_repair_then_fresh_qualification_and_five_days(tmp_path, monkeypatch):
    _configure_environment(monkeypatch, tmp_path)
    qualification_start = _start(monkeypatch, date="2026-08-14")
    qualification = _day(tmp_path, monkeypatch, qualification_start, date="2026-08-14")
    failed_start = _start(monkeypatch, date="2026-08-17", predecessor_object_id=qualification.envelope.object_id)
    failed = _day(tmp_path, monkeypatch, failed_start, date="2026-08-17", artifacts={"safety_sentinel": tmp_path / "missing", "paper_tournament": tmp_path / "missing-paper"})
    assert _payload(failed)["phase"] == "repair_required"
    repair_start = _start(monkeypatch, date="2026-08-18", predecessor_object_id=failed.envelope.object_id)
    repair = _day(tmp_path, monkeypatch, repair_start, date="2026-08-18")
    assert _payload(repair)["phase"] == "repair_in_progress"
    requalification_start = _start(monkeypatch, date="2026-08-19", predecessor_object_id=repair.envelope.object_id)
    previous = _day(tmp_path, monkeypatch, requalification_start, date="2026-08-19")
    assert _payload(previous)["phase"] == "qualification_clean"
    for date in ("2026-08-20", "2026-08-21", "2026-08-24", "2026-08-25", "2026-08-26"):
        start = _start(monkeypatch, date=date, predecessor_object_id=previous.envelope.object_id)
        previous = _day(tmp_path, monkeypatch, start, date=date)
    report = shadow_trial.build_shadow_streak_report()
    assert report["phase"] == "readiness_candidate"
    assert report["clean_trial_streak"] == 5
    assert report["record_path"].startswith(str(tmp_path / "results" / "manual_shadow"))


def test_red_trial_count_resets_to_latest_fresh_qualification_after_failure(tmp_path, monkeypatch):
    _configure_environment(monkeypatch, tmp_path)
    qualification_start = _start(monkeypatch, date="2026-08-10")
    qualification = _day(tmp_path, monkeypatch, qualification_start, date="2026-08-10")
    first_trial_start = _start(
        monkeypatch,
        date="2026-08-11",
        predecessor_object_id=qualification.envelope.object_id,
    )
    first_trial = _day(tmp_path, monkeypatch, first_trial_start, date="2026-08-11")
    failed_start = _start(
        monkeypatch,
        date="2026-08-12",
        predecessor_object_id=first_trial.envelope.object_id,
    )
    failed = _day(
        tmp_path,
        monkeypatch,
        failed_start,
        date="2026-08-12",
        artifacts={"safety_sentinel": tmp_path / "missing", "paper_tournament": tmp_path / "missing-paper"},
    )
    repair_start = _start(
        monkeypatch,
        date="2026-08-13",
        predecessor_object_id=failed.envelope.object_id,
    )
    repair = _day(tmp_path, monkeypatch, repair_start, date="2026-08-13")
    fresh_start = _start(
        monkeypatch,
        date="2026-08-14",
        predecessor_object_id=repair.envelope.object_id,
    )
    previous = _day(tmp_path, monkeypatch, fresh_start, date="2026-08-14")

    for date in ("2026-08-17", "2026-08-18", "2026-08-19", "2026-08-20"):
        trial_start = _start(monkeypatch, date=date, predecessor_object_id=previous.envelope.object_id)
        previous = _day(tmp_path, monkeypatch, trial_start, date=date)
        assert _payload(previous)["phase"] == "five_day_trial"

    fifth_start = _start(
        monkeypatch,
        date="2026-08-21",
        predecessor_object_id=previous.envelope.object_id,
    )
    fifth = _day(tmp_path, monkeypatch, fifth_start, date="2026-08-21")
    assert _payload(fifth)["phase"] == "trial_complete"
    report = shadow_trial.build_shadow_streak_report()
    assert report["phase"] == "readiness_candidate"
    assert report["clean_trial_streak"] == 5


def test_red_cli_predecessor_transitions_allow_trial_repair_and_fresh_qualification(tmp_path, monkeypatch):
    _configure_environment(monkeypatch, tmp_path)
    calendar = _CalendarFake({"2026-08-17", "2026-08-18", "2026-08-19", "2026-08-20"})
    monkeypatch.setattr(cli_main, "_alpaca_live_client", lambda: calendar)
    _set_clock(monkeypatch, "2026-08-17")
    first = runner.invoke(app, ["research", "shadow-day-start", "--run-id", "q", "--market-date", "2026-08-17", "--json-output"])
    assert first.exit_code == 0, first.output
    first_id = json.loads(first.stdout)["object_id"]
    first_start = shadow_trial.load_shadow_record(first_id, expected_kind="manual-shadow-day-start")
    first_day = _day(tmp_path, monkeypatch, type("Admission", (), {"envelope": first_start})(), date="2026-08-17")
    _set_clock(monkeypatch, "2026-08-18")
    missing = runner.invoke(app, ["research", "shadow-day-start", "--run-id", "missing", "--market-date", "2026-08-18"])
    assert missing.exit_code != 0
    invalid = runner.invoke(app, ["research", "shadow-day-start", "--run-id", "bad", "--market-date", "2026-08-18", "--predecessor-object-id", "manual-shadow-day-result-" + "0" * 64])
    assert invalid.exit_code != 0
    trial = runner.invoke(app, ["research", "shadow-day-start", "--run-id", "trial", "--market-date", "2026-08-18", "--predecessor-object-id", first_day.envelope.object_id, "--json-output"])
    assert trial.exit_code == 0, trial.output
    failed_start = shadow_trial.load_shadow_record(json.loads(trial.stdout)["object_id"], expected_kind="manual-shadow-day-start")
    failed = _day(tmp_path, monkeypatch, type("Admission", (), {"envelope": failed_start})(), date="2026-08-18", artifacts={"safety_sentinel": tmp_path / "missing", "paper_tournament": tmp_path / "missing-paper"})
    _set_clock(monkeypatch, "2026-08-19")
    repair = runner.invoke(app, ["research", "shadow-day-start", "--run-id", "repair", "--market-date", "2026-08-19", "--predecessor-object-id", failed.envelope.object_id, "--json-output"])
    assert repair.exit_code == 0, repair.output
    repair_start = shadow_trial.load_shadow_record(json.loads(repair.stdout)["object_id"], expected_kind="manual-shadow-day-start")
    repair_day = _day(tmp_path, monkeypatch, type("Admission", (), {"envelope": repair_start})(), date="2026-08-19")
    _set_clock(monkeypatch, "2026-08-20")
    requalification = runner.invoke(app, ["research", "shadow-day-start", "--run-id", "q2", "--market-date", "2026-08-20", "--predecessor-object-id", repair_day.envelope.object_id, "--json-output"])
    assert requalification.exit_code == 0, requalification.output
    assert json.loads(requalification.stdout)["role"] == "qualification"


def test_red_shadow_streak_status_is_read_only_non_authorizing_and_admissible(tmp_path, monkeypatch):
    environment = _configure_environment(monkeypatch, tmp_path)
    _set_clock(monkeypatch, "2026-08-21")

    def ledger_state():
        journal = environment["manual_root"] / "events.jsonl"
        objects = sorted(
            str(path.relative_to(environment["manual_root"]))
            for path in environment["manual_root"].rglob("*")
            if path.is_file()
        ) if environment["manual_root"].exists() else []
        return (
            journal.read_bytes() if journal.exists() else b"",
            tuple(objects),
        )

    empty = shadow_trial.shadow_streak_status()
    assert empty["analysis_only"] is True
    assert empty["execution_authority"] == "none"
    assert empty["can_submit_orders"] is False
    assert empty["phase"] == "qualification_pending"
    assert empty["last_result"] is None
    assert empty["pending_start"] is None
    assert empty["predecessor_object_id"] is None
    assert empty["clean_trial_streak"] == 0
    assert empty["required_clean_trial_days"] == 5
    assert empty["can_start_next_day"] is True

    start = _start(monkeypatch, date="2026-08-21")
    pending_before = ledger_state()
    assert pending_before[0]
    pending_status = shadow_trial.shadow_streak_status()
    after = ledger_state()
    assert pending_before == after
    assert pending_status["analysis_only"] is True
    assert pending_status["can_submit_orders"] is False
    assert pending_status["phase"] == "qualification_pending"
    assert pending_status["pending_start"]["object_id"] == start.envelope.object_id
    assert pending_status["pending_start"]["market_date"] == "2026-08-21"
    assert pending_status["can_start_next_day"] is False
    assert pending_status["predecessor_object_id"] is None

    day = _day(tmp_path, monkeypatch, start, date="2026-08-21")
    qualified = shadow_trial.shadow_streak_status()
    assert qualified["phase"] == "five_day_trial"
    assert qualified["pending_start"] is None
    assert qualified["last_result"]["object_id"] == day.envelope.object_id
    assert qualified["last_result"]["status"] == "clean"
    assert qualified["last_result"]["phase"] == "qualification_clean"
    assert qualified["last_result"]["market_date"] == "2026-08-21"
    assert qualified["clean_trial_streak"] == 0
    assert qualified["predecessor_object_id"] == day.envelope.object_id
    assert qualified["can_start_next_day"] is True


def test_red_status_after_clean_qualification_does_not_block_trial_day_1(tmp_path, monkeypatch):
    environment = _configure_environment(monkeypatch, tmp_path)
    calendar = _CalendarFake({"2026-08-21", "2026-08-22"})
    monkeypatch.setattr(cli_main, "_alpaca_live_client", lambda: calendar)
    qualification_start = _start(monkeypatch, date="2026-08-21")
    qualification = _day(tmp_path, monkeypatch, qualification_start, date="2026-08-21")

    status = shadow_trial.shadow_streak_status()
    assert status["phase"] == "five_day_trial"
    report_objects = environment["manual_root"] / "objects" / "manual-shadow-final-report"
    assert not report_objects.exists()

    _set_clock(monkeypatch, "2026-08-22")
    with monkeypatch.context() as calendar_patch:
        calendar_patch.setattr(
            shadow_trial,
            "_capture_calendar_evidence",
            lambda market_date: _calendar(market_date),
        )
        trial_start = shadow_trial.create_shadow_day_start_manifest(
            run_id="trial-day-1",
            market_date="2026-08-22",
            predecessor_object_id=qualification.envelope.object_id,
        )
    assert _payload(trial_start)["role"] == "trial"
    assert _payload(trial_start)["phase"] == "five_day_trial"
    trial_day = _day(tmp_path, monkeypatch, trial_start, date="2026-08-22")
    assert _payload(trial_day)["status"] == "clean"

    progress = shadow_trial.shadow_streak_status()
    assert progress["clean_trial_streak"] == 1
    assert progress["last_result"]["phase"] == "five_day_trial"
    assert progress["can_start_next_day"] is True
    assert not (environment["manual_root"] / "objects" / "manual-shadow-final-report").exists()


def test_red_terminal_report_refuses_before_clean_trial_complete_unless_final_no_go(tmp_path, monkeypatch):
    _configure_environment(monkeypatch, tmp_path)
    failed_start = _start(monkeypatch, date="2026-08-21")
    failed_day = _day(
        tmp_path,
        monkeypatch,
        failed_start,
        date="2026-08-21",
        artifacts={
            "safety_sentinel": tmp_path / "missing-sentinel",
            "paper_tournament": tmp_path / "missing-paper",
        },
    )
    assert _payload(failed_day)["status"] in {"failed", "incomplete"}
    with pytest.raises(ValueError, match="terminal|trial_complete|final-no-go|refuses"):
        shadow_trial.build_shadow_streak_report()

    _configure_environment(monkeypatch, tmp_path / "midtrial")
    qualification_start = _start(monkeypatch, date="2026-08-21")
    qualification = _day(tmp_path, monkeypatch, qualification_start, date="2026-08-21")
    trial_start = _start(
        monkeypatch,
        date="2026-08-22",
        predecessor_object_id=qualification.envelope.object_id,
    )
    _day(tmp_path, monkeypatch, trial_start, date="2026-08-22")
    with pytest.raises(ValueError, match="terminal|trial_complete|final-no-go|refuses"):
        shadow_trial.build_shadow_streak_report()
    no_go = shadow_trial.build_shadow_streak_report(final_no_go=True)
    assert no_go["phase"] == "readiness_no_go"
    assert no_go["status"] == "no_go"


def test_red_cli_status_is_read_only_and_report_requires_clean_trial_or_flag(tmp_path, monkeypatch):
    _configure_environment(monkeypatch, tmp_path)
    calendar = _CalendarFake({"2026-08-21"})
    monkeypatch.setattr(cli_main, "_alpaca_live_client", lambda: calendar)
    _set_clock(monkeypatch, "2026-08-21")

    refused_empty = runner.invoke(app, ["research", "shadow-streak-report"])
    assert refused_empty.exit_code != 0

    started = runner.invoke(
        app,
        ["research", "shadow-day-start", "--run-id", "cli-status", "--market-date", "2026-08-21", "--json-output"],
    )
    assert started.exit_code == 0, started.output
    start_id = json.loads(started.stdout)["object_id"]
    start_record = shadow_trial.load_shadow_record(start_id, expected_kind="manual-shadow-day-start")

    status_result = runner.invoke(app, ["research", "shadow-streak-status", "--json-output"])
    assert status_result.exit_code == 0, status_result.output
    status_payload = json.loads(status_result.stdout)
    assert status_payload["analysis_only"] is True
    assert status_payload["execution_authority"] == "none"
    assert status_payload["can_submit_orders"] is False
    assert status_payload["pending_start"]["object_id"] == start_id
    assert status_payload["can_start_next_day"] is False

    refused = runner.invoke(app, ["research", "shadow-streak-report"])
    assert refused.exit_code != 0

    qualification = _day(
        tmp_path,
        monkeypatch,
        type("Admission", (), {"envelope": start_record})(),
        date="2026-08-21",
    )
    status_after = runner.invoke(app, ["research", "shadow-streak-status", "--json-output"])
    assert status_after.exit_code == 0, status_after.output
    after_payload = json.loads(status_after.stdout)
    assert after_payload["phase"] == "five_day_trial"
    assert after_payload["last_result"]["object_id"] == qualification.envelope.object_id
    assert after_payload["clean_trial_streak"] == 0
    assert after_payload["can_start_next_day"] is True

    refused_after = runner.invoke(app, ["research", "shadow-streak-report"])
    assert refused_after.exit_code != 0
    final_no_go = runner.invoke(
        app,
        ["research", "shadow-streak-report", "--final-no-go", "--json-output"],
    )
    assert final_no_go.exit_code == 0, final_no_go.output
    no_go_payload = json.loads(final_no_go.stdout)
    assert no_go_payload["phase"] == "readiness_no_go"
    assert no_go_payload["execution_authority"] == "none"


def _ledger_surface_snapshot(root_parent: Path) -> dict[str, object]:
    """Capture every file name, digest, mode, size, and mtime under one parent."""

    if not root_parent.exists():
        return {"exists": False}
    entries: dict[str, object] = {}
    for path in sorted(root_parent.rglob("*")):
        meta = path.lstat()
        if path.is_file() and not path.is_symlink():
            entries[str(path.relative_to(root_parent))] = (
                hashlib.sha256(path.read_bytes()).hexdigest(),
                meta.st_mode,
                meta.st_size,
                meta.st_mtime_ns,
            )
        else:
            entries[str(path.relative_to(root_parent))] = ("non-regular", meta.st_mode)
    return {"exists": True, "entries": entries}


def test_red_status_never_creates_repairs_or_mutates_ledger_surfaces(tmp_path, monkeypatch):
    environment = _configure_environment(monkeypatch, tmp_path)
    results_parent = environment["manual_root"].parent
    anchor_path = results_parent / ".manual-shadow-trusted-head.json"
    lock_path = results_parent / ".manual-shadow-trusted-head.lock"

    empty_before = _ledger_surface_snapshot(results_parent)
    assert shadow_trial.shadow_streak_status()["phase"] == "qualification_pending"
    assert empty_before == _ledger_surface_snapshot(results_parent)

    qualification_start = _start(monkeypatch, date="2026-08-21")
    qualification = _day(tmp_path, monkeypatch, qualification_start, date="2026-08-21")
    assert _payload(qualification)["status"] == "clean"
    assert lock_path.is_file()
    lock_path.unlink()

    clean_before = _ledger_surface_snapshot(results_parent)
    clean_status = shadow_trial.shadow_streak_status()
    clean_after = _ledger_surface_snapshot(results_parent)
    assert clean_before == clean_after
    assert clean_status["phase"] == "five_day_trial"
    assert clean_status["last_result"]["object_id"] == qualification.envelope.object_id

    anchor = json.loads(anchor_path.read_text(encoding="utf-8"))
    committed = dict(anchor["committed_head"])
    anchor["pending_next"] = {
        "prior_head": committed,
        "sequence": committed["sequence"] + 1,
        "kind": "manual-shadow-day-start",
        "object_id": f"manual-shadow-day-start-{'a' * 64}",
        "retry_material_sha256": "a" * 64,
        "admission_route": anchor["ledger_id"],
    }
    anchor_path.write_text(
        json.dumps(
            anchor,
            ensure_ascii=True,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    recover_before = _ledger_surface_snapshot(results_parent)
    with pytest.raises(ValueError, match="unresolved|pending"):
        shadow_trial.shadow_streak_status()
    recover_after = _ledger_surface_snapshot(results_parent)
    assert recover_before == recover_after

    _set_clock(monkeypatch, "2026-08-22")
    with monkeypatch.context() as calendar_patch:
        calendar_patch.setattr(
            shadow_trial,
            "_capture_calendar_evidence",
            lambda market_date: _calendar(market_date),
        )
        trial = shadow_trial.create_shadow_day_start_manifest(
            run_id="trial-day-1",
            market_date="2026-08-22",
            predecessor_object_id=qualification.envelope.object_id,
        )
    pending_before = _ledger_surface_snapshot(results_parent)
    pending_status = shadow_trial.shadow_streak_status()
    pending_after = _ledger_surface_snapshot(results_parent)
    assert pending_before == pending_after
    assert pending_status["phase"] == "five_day_trial"
    assert pending_status["pending_start"]["object_id"] == trial.envelope.object_id
    assert pending_status["can_start_next_day"] is False


def test_red_status_fails_closed_on_any_unresolved_pending_next(tmp_path, monkeypatch):
    environment = _configure_environment(monkeypatch, tmp_path)
    results_parent = environment["manual_root"].parent
    anchor_path = results_parent / ".manual-shadow-trusted-head.json"

    qualification_start = _start(monkeypatch, date="2026-08-21")
    qualification = _day(tmp_path, monkeypatch, qualification_start, date="2026-08-21")
    assert _payload(qualification)["status"] == "clean"

    anchor = json.loads(anchor_path.read_text(encoding="utf-8"))
    committed = dict(anchor["committed_head"])
    anchor["pending_next"] = {
        "prior_head": committed,
        "sequence": committed["sequence"] + 1,
        "kind": "manual-shadow-day-start",
        "object_id": f"manual-shadow-day-start-{'a' * 64}",
        "retry_material_sha256": "a" * 64,
        "admission_route": anchor["ledger_id"],
    }
    anchor_path.write_text(
        json.dumps(
            anchor,
            ensure_ascii=True,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    equal_head_before = _ledger_surface_snapshot(results_parent)
    with pytest.raises(ValueError, match="unresolved|pending"):
        shadow_trial.shadow_streak_status()
    assert equal_head_before == _ledger_surface_snapshot(results_parent)

    lines = (environment["manual_root"] / "events.jsonl").read_bytes().splitlines()

    def head_of(line: bytes, sequence: int) -> dict[str, object]:
        event = json.loads(line)
        return {
            "sequence": sequence,
            "kind": event["kind"],
            "object_id": event["object_id"],
            "event_sha256": hashlib.sha256(line).hexdigest(),
            "admission_route": event["admission_route"],
        }

    prior_head = head_of(lines[-2], len(lines) - 1)
    last_event = json.loads(lines[-1])
    anchor = json.loads(anchor_path.read_text(encoding="utf-8"))
    anchor["committed_head"] = prior_head
    anchor["pending_next"] = {
        "prior_head": prior_head,
        "sequence": len(lines),
        "kind": last_event["kind"],
        "object_id": last_event["object_id"],
        "retry_material_sha256": last_event["retry_material_sha256"],
        "admission_route": last_event["admission_route"],
    }
    anchor_path.write_text(
        json.dumps(
            anchor,
            ensure_ascii=True,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    advanced_before = _ledger_surface_snapshot(results_parent)
    with pytest.raises(ValueError, match="advanced|unresolved|pending"):
        shadow_trial.shadow_streak_status()
    assert advanced_before == _ledger_surface_snapshot(results_parent)


def test_red_runtime_identity_fixture_matches_strict_schema(tmp_path):
    contract, roles, automation_root = _write_schedule_fixture(tmp_path / "schedule")
    control = _control(tmp_path / "results" / "policy" / "live_control.json")
    fixture = _runtime_identity_fixture(
        control=control,
        contract=contract,
        roles=roles,
        automation_root=automation_root,
    )
    assert runtime_identity.validate_runtime_identity(copy.deepcopy(fixture)) == fixture
    with pytest.raises(runtime_identity.RuntimeIdentityError):
        runtime_identity.validate_runtime_identity(
            {
                "schema_version": "runtime_identity_v1",
                **fixture,
            }
        )


def test_red_start_and_day_payloads_bind_identical_runtime_identity(tmp_path, monkeypatch):
    environment = _configure_environment(monkeypatch, tmp_path)
    expected_identity = environment["runtime_identity"]["value"]

    start = _start(monkeypatch, date="2026-08-21")
    start_payload = _payload(start)
    assert shadow_trial._plain_json(start_payload["runtime_identity"]) == expected_identity

    day = _day(tmp_path, monkeypatch, start, date="2026-08-21")
    day_payload = _payload(day)
    assert day_payload["status"] == "clean"
    assert shadow_trial._plain_json(day_payload["runtime_identity"]) == expected_identity


def test_red_start_refuses_when_identity_capture_is_dirty_or_unparseable(tmp_path, monkeypatch):
    _configure_environment(monkeypatch, tmp_path)
    monkeypatch.setattr(
        shadow_trial,
        "_capture_calendar_evidence",
        lambda market_date: _calendar(market_date),
    )

    def dirty_capture():
        raise runtime_identity.RuntimeIdentityError("tracked tree is dirty")

    monkeypatch.setattr(shadow_trial, "_runtime_identity_capture", dirty_capture)
    with pytest.raises(ValueError, match="dirty"):
        _start(monkeypatch, date="2026-08-21")

    def malformed_capture():
        return {"schema_version": "runtime_identity_v1"}

    monkeypatch.setattr(shadow_trial, "_runtime_identity_capture", malformed_capture)
    with pytest.raises(ValueError):
        _start(monkeypatch, date="2026-08-21")

    manual_root = tmp_path / "results" / "manual_shadow"
    admitted_objects = (
        list(manual_root.glob("objects/*/*.json")) if manual_root.exists() else []
    )
    assert admitted_objects == []


def test_red_midday_lockfile_drift_marks_day_failed_with_runtime_identity_mismatch(
    tmp_path, monkeypatch
):
    environment = _configure_environment(monkeypatch, tmp_path)
    start = _start(monkeypatch, date="2026-08-21")

    drifted = copy.deepcopy(environment["runtime_identity"]["value"])
    drifted["required_files_sha256"]["uv.lock"] = "9" * 64
    environment["runtime_identity"]["value"] = _recompute_identity_digests(drifted)

    day = _day(tmp_path, monkeypatch, start, date="2026-08-21")
    payload = _payload(day)
    assert payload["status"] == "failed"
    assert "runtime_identity_mismatch" in payload["reasons"]
    assert payload["phase"] == "repair_required"


def test_red_cross_day_documentation_only_commit_drift_is_hard_non_clean(
    tmp_path, monkeypatch
):
    environment = _configure_environment(monkeypatch, tmp_path)
    qualification_start = _start(monkeypatch, date="2026-08-20")
    qualification = _day(tmp_path, monkeypatch, qualification_start, date="2026-08-20")
    assert _payload(qualification)["status"] == "clean"

    drifted = copy.deepcopy(environment["runtime_identity"]["value"])
    drifted["git_commit"] = "b" * 40
    environment["runtime_identity"]["value"] = _recompute_identity_digests(drifted)

    trial_start = _start(
        monkeypatch,
        date="2026-08-21",
        predecessor_object_id=qualification.envelope.object_id,
    )
    trial_day = _day(tmp_path, monkeypatch, trial_start, date="2026-08-21")
    payload = _payload(trial_day)
    assert payload["status"] == "failed"
    assert "runtime_identity_mismatch" in payload["reasons"]
    assert payload["phase"] == "repair_required"


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(
            lambda identity: identity["package_inventory"].append(
                "hostile-drift==9.9.9"
            ),
            id="package_inventory",
        ),
        pytest.param(
            lambda identity: identity["overnight_route"].update(
                {"deep_think_llm": "gpt-5.5-pro"}
            ),
            id="overnight_model_route",
        ),
        pytest.param(
            lambda identity: identity["automation_tomls_sha256"].update(
                {"tradingagents-auto-03": "7" * 64}
            ),
            id="automation_toml",
        ),
        pytest.param(
            lambda identity: identity.update({"live_control_sha256": "6" * 64}),
            id="live_control_bytes",
        ),
        pytest.param(
            lambda identity: identity.update({"schedule_contract_sha256": "5" * 64}),
            id="schedule_contract",
        ),
    ],
)
def test_red_identity_surface_drift_each_fails_closed(tmp_path, monkeypatch, mutate):
    environment = _configure_environment(monkeypatch, tmp_path)
    start = _start(monkeypatch, date="2026-08-21")

    drifted = copy.deepcopy(environment["runtime_identity"]["value"])
    mutate(drifted)
    environment["runtime_identity"]["value"] = _recompute_identity_digests(drifted)

    day = _day(tmp_path, monkeypatch, start, date="2026-08-21")
    payload = _payload(day)
    assert payload["status"] == "failed"
    assert "runtime_identity_mismatch" in payload["reasons"]


def test_red_closure_facades_inherit_start_identity_without_recapture(
    tmp_path, monkeypatch
):
    _configure_environment(monkeypatch, tmp_path)
    monkeypatch.setattr(
        shadow_trial,
        "_capture_calendar_evidence",
        lambda market_date: _calendar(market_date),
    )
    start = _start(monkeypatch, date="2026-08-21")
    inherited_identity = _payload(start)["runtime_identity"]

    def unavailable_capture():
        raise runtime_identity.RuntimeIdentityError(
            "tracked tree became dirty after start"
        )

    monkeypatch.setattr(shadow_trial, "_runtime_identity_capture", unavailable_capture)
    aborted = shadow_trial.abort_shadow_day(
        start_object_id=start.envelope.object_id,
        stopped_at_stage="paper_tournament",
        notes="crashed after the paper tick; source tree became dirty",
    )
    abort_payload = _payload(aborted)
    assert abort_payload["runtime_identity"] == inherited_identity
    assert abort_payload["status"] == "failed"
    assert "runtime_identity_mismatch" not in abort_payload["reasons"]

    _configure_environment(monkeypatch, tmp_path / "fresh-expiry-root")
    expire_start = _start(monkeypatch, date="2026-08-24")
    expire_inherited = _payload(expire_start)["runtime_identity"]
    monkeypatch.setattr(shadow_trial, "_runtime_identity_capture", unavailable_capture)
    _set_clock(monkeypatch, "2026-08-25", 14)
    expired = shadow_trial.expire_pending_shadow_day()
    assert expired is not None
    expired_payload = _payload(expired)
    assert expired_payload["runtime_identity"] == expire_inherited
    assert expired_payload["status"] == "incomplete"
    assert list(expired_payload["reasons"]) == [
        "pending_day_expired_without_adjudication"
    ]
    assert "runtime_identity_mismatch" not in expired_payload["reasons"]


def test_red_runtime_identity_adjudication_refusal_admits_nothing(
    tmp_path, monkeypatch
):
    environment = _configure_environment(monkeypatch, tmp_path)
    monkeypatch.setattr(
        shadow_trial,
        "_capture_calendar_evidence",
        lambda market_date: _calendar(market_date),
    )
    start = _start(monkeypatch, date="2026-08-21")
    artifacts = _complete_daily_chain(
        tmp_path,
        start=start,
        artifacts=_artifacts(
            tmp_path,
            run_id=_payload(start)["run_id"],
            date="2026-08-21",
            start_object_id=start.envelope.object_id,
        ),
    )
    results_parent = environment["manual_root"].parent
    before = _ledger_surface_snapshot(results_parent)

    def unavailable_capture():
        raise runtime_identity.RuntimeIdentityError("tracked tree dirty midday")

    monkeypatch.setattr(shadow_trial, "_runtime_identity_capture", unavailable_capture)
    with pytest.raises(ValueError, match="runtime identity"):
        shadow_trial.adjudicate_shadow_day(
            start_object_id=start.envelope.object_id,
            artifacts={
                name: artifacts[name]
                for name in ("safety_sentinel", "paper_tournament", "daily_chain_manifest")
            },
        )
    assert before == _ledger_surface_snapshot(results_parent)


def test_red_runtime_identity_production_seam_binds_exact_canonical_inputs(monkeypatch):
    for environment_key in (
        "TRADINGAGENTS_OVERNIGHT_LLM_PROVIDER",
        "TRADINGAGENTS_OVERNIGHT_QUICK_THINK_LLM",
        "TRADINGAGENTS_OVERNIGHT_DEEP_THINK_LLM",
    ):
        monkeypatch.delenv(environment_key, raising=False)
    captured_kwargs: dict[str, object] = {}

    def recording_capture(**kwargs):
        captured_kwargs.update(kwargs)
        return {"identity_schema": "runtime_identity/v1"}

    monkeypatch.setattr(shadow_trial, "capture_runtime_identity", recording_capture)
    monkeypatch.setattr(
        shadow_trial,
        "_installed_package_inventory",
        lambda: ["fixture-package==1.0.0"],
    )
    identity = shadow_trial._runtime_identity_capture()

    assert identity == {"identity_schema": "runtime_identity/v1"}
    root = shadow_trial._repo_root()
    assert captured_kwargs["repo_root"] == root
    assert set(captured_kwargs["required_files"]) == {
        "pyproject.toml",
        "uv.lock",
        "requirements.txt",
        "requirements-crawler.txt",
    }
    assert all(
        Path(path) == root / name
        for name, path in captured_kwargs["required_files"].items()
    )
    assert Path(captured_kwargs["schedule_contract"]) == (
        shadow_trial._canonical_schedule_contract_path()
    )
    assert Path(captured_kwargs["role_contract"]) == (
        shadow_trial._canonical_role_contract_path()
    )
    assert Path(captured_kwargs["live_control"]) == (
        shadow_trial._canonical_live_control_path()
    )
    automation_root = Path(
        shadow_trial._absolute(shadow_trial._canonical_automation_root())
    )
    assert Path(captured_kwargs["automation_root"]) == automation_root
    assert set(captured_kwargs["automation_tomls"]) == set(
        shadow_trial.EXPECTED_AUTOMATION_IDS
    )
    assert len(captured_kwargs["automation_tomls"]) == 10
    assert all(
        Path(path) == automation_root / automation_id / "automation.toml"
        for automation_id, path in captured_kwargs["automation_tomls"].items()
    )
    assert captured_kwargs["schema_versions"] == {
        "manual_shadow_day_start": shadow_trial.START_SCHEMA,
        "manual_shadow_day_result": shadow_trial.DAY_SCHEMA,
        "manual_shadow_final_report": shadow_trial.REPORT_SCHEMA,
    }
    assert captured_kwargs["provider_routes"] == {}
    assert captured_kwargs["python_executable"] == sys.executable
    inventory = shadow_trial._installed_package_inventory()
    assert inventory == sorted(set(inventory))
    assert all(entry == entry.strip().lower() for entry in inventory)
    assert all("==" in entry for entry in inventory)
    route = shadow_trial._allowlisted_overnight_route()
    assert set(route) == {"llm_provider", "quick_think_llm", "deep_think_llm"}
    from tradingagents.llm_clients.model_catalog import MODEL_OPTIONS

    options = MODEL_OPTIONS[route["llm_provider"].lower()]
    assert route["quick_think_llm"] in {name for _, name in options["quick"]}
    assert route["deep_think_llm"] in {name for _, name in options["deep"]}


def test_red_runtime_identity_seam_refuses_non_allowlisted_route(monkeypatch):
    monkeypatch.setenv("TRADINGAGENTS_OVERNIGHT_DEEP_THINK_LLM", "gpt-5.6-terra")
    with pytest.raises(runtime_identity.RuntimeIdentityError, match="allowlisted"):
        shadow_trial._allowlisted_overnight_route()


def test_red_runtime_identity_overnight_route_binds_configured_names_only(monkeypatch):
    for environment_key in (
        "TRADINGAGENTS_OVERNIGHT_LLM_PROVIDER",
        "TRADINGAGENTS_OVERNIGHT_QUICK_THINK_LLM",
        "TRADINGAGENTS_OVERNIGHT_DEEP_THINK_LLM",
    ):
        monkeypatch.delenv(environment_key, raising=False)
    from tradingagents.default_config import DEFAULT_CONFIG

    configured_defaults = {
        "llm_provider": str(DEFAULT_CONFIG["llm_provider"]),
        "quick_think_llm": str(DEFAULT_CONFIG["quick_think_llm"]),
        "deep_think_llm": str(DEFAULT_CONFIG["deep_think_llm"]),
    }
    assert shadow_trial._allowlisted_overnight_route() == configured_defaults

    monkeypatch.setenv("TRADINGAGENTS_OVERNIGHT_QUICK_THINK_LLM", "gpt-5.4-nano")
    monkeypatch.setenv("TRADINGAGENTS_OVERNIGHT_DEEP_THINK_LLM", "gpt-5.5")
    assert shadow_trial._allowlisted_overnight_route() == {
        "llm_provider": configured_defaults["llm_provider"],
        "quick_think_llm": "gpt-5.4-nano",
        "deep_think_llm": "gpt-5.5",
    }
