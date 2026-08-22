from __future__ import annotations

import copy
import datetime as dt
import hashlib
import inspect
import json
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from cli import main as cli_main
from cli.main import app
from tradingagents.evals import shadow_trial
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
        return [{"date": start}] if start == end and start in self.dates else []

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
) -> dict:
    return {
        "kind": "alpaca_regular_equities_calendar",
        "market_date": date,
        "observed_at": observed_at or f"{date}T13:59:00+00:00",
        "sessions": [{"date": item} for item in (dates if dates is not None else [date])],
    }


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


def _control(path: Path, *, frozen: bool = True, malformed: bool = False) -> Path:
    _write_json(
        path,
        ({"frozen": "true"} if malformed else {
            "frozen": frozen,
            "reason": "manual safety hold",
            "dead_man_expires_at": "2026-12-31T00:00:00+00:00",
        }),
    )
    return path


def _configure_environment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    frozen: bool = True,
    malformed_control: bool = False,
    active_id: str | None = None,
    omit_id: str | None = None,
) -> dict[str, Path]:
    manual_root = tmp_path / "results" / "manual_shadow"
    control = _control(
        tmp_path / "results" / "policy" / "live_control.json",
        frozen=frozen,
        malformed=malformed_control,
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
    return {
        "manual_root": manual_root,
        "control": control,
        "contract": contract,
        "roles": roles,
        "automation_root": automation_root,
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
) -> object:
    _set_clock(monkeypatch, date)
    with monkeypatch.context() as calendar_patch:
        calendar_patch.setattr(
            shadow_trial,
            "_capture_calendar_evidence",
            lambda market_date: _calendar(market_date),
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
    generated_at = f"{date}T15:00:00+00:00"
    broker_snapshot = _healthy_broker_snapshot(date=date, account_id="live-account")
    _write_json(
        sentinel,
        {
            "kind": "safety_sentinel_audit",
            "run_id": run_id,
            "market_date": date,
            **({"shadow_start_object_id": start_object_id} if start_object_id else {}),
            "generated_at": generated_at,
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
            "generated_at": generated_at,
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
    generated_at = f"{payload['market_date']}T15:00:00+00:00"
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
            "generated_at": generated_at,
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
                    "paper": _healthy_broker_snapshot(
                        date=payload["market_date"], account_id="paper-account"
                    ),
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
            "captured_at": generated_at,
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


def _day(
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
    start,
    *,
    date: str,
    artifacts: dict[str, Path] | None = None,
) -> object:
    _set_clock(monkeypatch, date, 16)
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
    assert not inspect.signature(shadow_trial.build_shadow_streak_report).parameters

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
        def get_account(self): return {"id": "observer", "status": "ACTIVE"}
        def list_positions(self): return []
        def list_orders(self, *, status): return []
        def get_clock(self): return {"is_open": False, "timestamp": "2026-08-21T14:00:00+00:00"}
        def __getattr__(self, name):
            if name in {"submit_order", "cancel_order", "replace_order"}:
                raise AssertionError(f"forbidden write {name}")
            raise AttributeError(name)

    monkeypatch.setattr(cli_main, "_alpaca_live_client", Broker)
    monkeypatch.setattr(cli_main, "_alpaca_paper_client", Broker)
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
    report = shadow_trial.build_shadow_streak_report()
    assert report["phase"] == "readiness_no_go"


def test_red_clean_hold_and_zero_submission_are_valid_only_with_complete_bound_evidence(tmp_path, monkeypatch):
    _configure_environment(monkeypatch, tmp_path)
    start = _start(monkeypatch, date="2026-08-21")
    decision = _day(tmp_path, monkeypatch, start, date="2026-08-21")
    payload = _payload(decision)
    assert payload["status"] == "clean"
    assert payload["phase"] == "qualification_clean"
    assert payload["artifacts"]["paper_tournament"]["payload"]["submitted_count"] == 0


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
        },
        "freshness": {"read_only": True, "can_submit_orders": False},
    }
    assert shadow_trial._stage_semantic_reasons("loss_review", loss_review) == []
    assert "loss_review_stage_schema_invalid" in shadow_trial._stage_semantic_reasons(
        "loss_review", {**loss_review, "evidence_type": "provider_summary"}
    )

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
