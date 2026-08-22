import datetime as dt
import json
from pathlib import Path

from typer.testing import CliRunner

from cli import main as cli_main
from cli.main import app
from tradingagents.evals import safety_sentinel
from tradingagents.evals.safety_sentinel import build_safety_sentinel_packet

UTC = dt.timezone.utc
runner = CliRunner()


class _ReadOnlyBrokerFake:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def assert_expected_mode(self, paper: bool) -> None:
        self.calls.append(("assert_expected_mode", paper))
        assert paper is False

    def get_account(self) -> dict:
        self.calls.append(("get_account", None))
        return {"status": "ACTIVE", "buying_power": "100", "equity": "100"}

    def list_positions(self) -> list[dict]:
        self.calls.append(("list_positions", None))
        return []

    def list_orders(self, status: str = "open") -> list[dict]:
        self.calls.append(("list_orders", status))
        return []

    def get_clock(self) -> dict:
        self.calls.append(("get_clock", None))
        return {"is_open": False, "timestamp": "2026-08-21T13:00:00Z"}

    def __getattr__(self, name: str):
        if name in {
            "submit_order",
            "cancel_order",
            "close_position",
            "freeze_live_control",
            "rearm_live_control",
            "update_automation",
            "send_email",
        }:
            raise AssertionError(f"forbidden mutation method accessed: {name}")
        raise AttributeError(name)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")


def _write_schedule_fixture(root: Path) -> tuple[Path, Path, Path]:
    contract = root / "schedule-contract.json"
    roles = root / "automation-roles.json"
    automation_root = root / "automations"
    automation_id = "tradingagents-autonomous-safety-sentinel"
    prompt = "deterministic verification escalate uncertain diagnosis to the self-healer fail closed"
    import hashlib

    _write_json(
        contract,
        {
            "schema_version": 1,
            "kind": "tradingagents_automation_schedule_contract",
            "timezone": "America/Chicago",
            "deployment_policy": {
                "allowed_status_phase": "predeployment_paused",
                "safe_statuses": ["PAUSED"],
                "paused_is_safe_but_not_deployed": True,
                "deployment_proof_requires": [
                    "contract_match",
                    "api_returned_next_run_central_and_utc",
                    "current_no_submit_shadow_evidence",
                    "current_artifact_health",
                ],
                "deployment_phases": {
                    "predeployment_paused": {
                        "active_automation_ids": [],
                        "paused_automation_ids": [automation_id],
                    },
                    "frozen_observer": {
                        "active_automation_ids": [],
                        "paused_automation_ids": [automation_id],
                    },
                },
            },
            "automations": {
                automation_id: {
                    "role": "integrity_verifier",
                    "name": "Safety sentinel",
                    "target": {"type": "project", "project_id": "test-project"},
                    "cwds": ["/tmp/tradingagents"],
                    "execution_environment": "local",
                    "allowed_status_phase": "predeployment_paused",
                    "rrule": "RRULE:FREQ=DAILY;BYHOUR=8;BYMINUTE=20",
                    "model": "test-model",
                    "reasoning_effort": "medium",
                    "notification_policy": "failed_runs_only",
                    "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
                    "required_prompt_phrases": [
                        "deterministic verification",
                        "escalate uncertain diagnosis to the self-healer",
                        "fail closed",
                    ],
                    "forbidden_prompt_phrases": [],
                    "expected_artifact_patterns": ["results/safety_sentinel/safety-sentinel-*.json"],
                    "depends_on": [],
                    "no_submit": True,
                }
            },
        },
    )
    _write_json(roles, {"automations": {automation_id: "integrity_verifier"}})
    toml_path = automation_root / automation_id / "automation.toml"
    toml_path.parent.mkdir(parents=True, exist_ok=True)
    toml_path.write_text(
        "\n".join(
            [
                'name = "Safety sentinel"',
                f'prompt = "{prompt}"',
                'status = "PAUSED"',
                'target = { type = "project", project_id = "test-project" }',
                'cwds = ["/tmp/tradingagents"]',
                'execution_environment = "local"',
                'rrule = "RRULE:FREQ=DAILY;BYHOUR=8;BYMINUTE=20"',
                'model = "test-model"',
                'reasoning_effort = "medium"',
                'notification_policy = "failed_runs_only"',
            ]
        ),
        encoding="utf-8",
    )
    return contract, roles, automation_root


def _write_clear_evidence(root: Path) -> tuple[Path, Path, Path, Path, Path]:
    control = root / "policy" / "live_control.json"
    preopen = root / "preopen" / "preopen-validation.json"
    _write_json(
        control,
        {
            "frozen": False,
            "reason": "test control remains observer-only",
            "dead_man_expires_at": "2026-08-21T14:00:00+00:00",
        },
    )
    _write_json(
        preopen,
        {
            "generated_at": "2026-08-21T13:00:00+00:00",
            "analysis_only": True,
            "execution_authority": "none",
            "can_submit_orders": False,
            "overall_status": "pass",
        },
    )
    contract, roles, automation_root = _write_schedule_fixture(root)
    return control, preopen, contract, roles, automation_root


def _packet(
    root: Path,
    *,
    control_payload: dict | None = None,
    preopen_text: str | None = None,
    max_evidence_age_minutes: float = 60,
) -> dict:
    control, preopen, contract, roles, automation_root = _write_clear_evidence(root)
    if control_payload is not None:
        _write_json(control, control_payload)
    if preopen_text is not None:
        preopen.write_text(preopen_text, encoding="utf-8")
    return build_safety_sentinel_packet(
        live_control_path=control,
        preopen_validation_path=preopen,
        schedule_contract_path=contract,
        automation_root=automation_root,
        role_contract_path=roles,
        broker_snapshot={
            "account": {"status": "ACTIVE"},
            "positions": [],
            "open_orders": [],
            "clock": {"is_open": False},
            "errors": {},
        },
        now=dt.datetime(2026, 8, 21, 13, 30, tzinfo=UTC),
        max_evidence_age_minutes=max_evidence_age_minutes,
    )


def test_safety_sentinel_frozen_control_is_frozen_and_remains_non_authorizing(tmp_path):
    packet = _packet(root=tmp_path, control_payload={"frozen": True, "reason": "manual hold"})

    assert packet["schema_version"] == "safety_sentinel_v1"
    assert packet["status"] == "FROZEN"
    assert packet["analysis_only"] is True
    assert packet["execution_authority"] == "none"
    assert packet["can_submit_orders"] is False
    assert packet["evidence"]["live_control"]["sha256"]
    assert packet["schedule_check"]["deployment_phase"] == "predeployment_paused"
    assert "frozen_control" in packet["reasons"]


def test_safety_sentinel_missing_stale_and_corrupt_evidence_hold(tmp_path):
    control, missing_path, contract, roles, automation_root = _write_clear_evidence(tmp_path / "missing")
    missing_path.unlink()
    missing = build_safety_sentinel_packet(
        live_control_path=control,
        preopen_validation_path=missing_path,
        schedule_contract_path=contract,
        automation_root=automation_root,
        role_contract_path=roles,
        broker_snapshot={"errors": {}},
        now=dt.datetime(2026, 8, 21, 13, 30, tzinfo=UTC),
    )
    stale = _packet(tmp_path / "stale", max_evidence_age_minutes=20)
    corrupt = _packet(tmp_path / "corrupt", preopen_text="not json")

    assert missing["status"] == "HOLD"
    assert "preopen_validation_missing" in missing["reasons"]
    assert stale["status"] == "HOLD"
    assert "preopen_validation_stale" in stale["reasons"]
    assert corrupt["status"] == "HOLD"
    assert "preopen_validation_corrupt" in corrupt["reasons"]


def test_safety_sentinel_cli_uses_only_narrow_read_only_broker_adapter(tmp_path, monkeypatch):
    control, preopen, contract, roles, automation_root = _write_clear_evidence(tmp_path)
    client = _ReadOnlyBrokerFake()
    output_dir = tmp_path / "safety-sentinel-output"
    monkeypatch.setattr(cli_main, "_alpaca_clients", lambda: (object(), client))
    monkeypatch.setattr(
        safety_sentinel,
        "evaluate_schedule_contract",
        lambda **kwargs: {
            "status": "not_deployed",
            "contract_status": "pass",
            "safe_predeployment": True,
            "issues": [],
            "deployment_proven": False,
        },
    )
    monkeypatch.setattr(
        cli_main,
        "_alpaca_policy_now",
        lambda: dt.datetime(2026, 8, 21, 13, 30, tzinfo=UTC),
    )

    result = runner.invoke(
        app,
        [
            "research",
            "safety-sentinel-audit",
            "--json-output",
            "--output-dir",
            str(output_dir),
            "--live-control-path",
            str(control),
            "--preopen-validation-path",
            str(preopen),
            "--schedule-contract-path",
            str(contract),
            "--automation-root",
            str(automation_root),
            "--role-contract-path",
            str(roles),
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["status"] == "CLEAR"
    assert payload["analysis_only"] is True
    assert payload["execution_authority"] == "none"
    assert payload["can_submit_orders"] is False
    assert Path(payload["packet_path"]).parent == output_dir
    assert Path(payload["packet_path"]).exists()
    assert client.calls == [
        ("get_account", None),
        ("list_positions", None),
        ("list_orders", "open"),
        ("get_clock", None),
    ]
