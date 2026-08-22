import datetime as dt
import gc
import hashlib
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

import tradingagents.evals.automation_health_audit as automation_health_audit
from cli import main as cli_main
from cli.main import app
from tradingagents.evals import safety_sentinel
from tradingagents.evals.automation_health_audit import (
    capture_schedule_contract_snapshot,
    evaluate_schedule_contract,
)
from tradingagents.evals.safety_sentinel import (
    build_safety_sentinel_packet,
    write_safety_sentinel_packet,
)

UTC = dt.timezone.utc
runner = CliRunner()
REPO_ROOT = Path(__file__).resolve().parents[1]


class _ReadOnlyBrokerFake:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def assert_expected_mode(self, paper: bool) -> None:
        self.calls.append(("assert_expected_mode", paper))
        assert paper is False

    def get_account(self) -> dict:
        self.calls.append(("get_account", None))
        return {"id": "account-1", "status": "ACTIVE", "buying_power": "100", "equity": "100"}

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
    contract_payload = json.loads(
        (REPO_ROOT / "config" / "automation_schedule_contract.json").read_text(encoding="utf-8")
    )
    roles_payload = json.loads(
        (REPO_ROOT / "config" / "automation_roles.json").read_text(encoding="utf-8")
    )
    for automation_id, record in contract_payload["automations"].items():
        prompt = " ".join(record["required_prompt_phrases"])
        record["prompt_sha256"] = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        toml_path = automation_root / automation_id / "automation.toml"
        toml_path.parent.mkdir(parents=True, exist_ok=True)
        toml_path.write_text(
            "\n".join(
                [
                    f"name = {json.dumps(record['name'])}",
                    f"prompt = {json.dumps(prompt)}",
                    'status = "PAUSED"',
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
            "account": {"id": "account-1", "status": "ACTIVE"},
            "positions": [],
            "open_orders": [],
            "clock": {"is_open": False, "timestamp": "2026-08-21T13:30:00+00:00"},
            "errors": {},
            "read_methods": ["get_account", "list_positions", "list_orders", "get_clock"],
            "captured_at": "2026-08-21T13:30:00+00:00",
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


def test_safety_sentinel_captures_and_evaluates_complete_schedule_snapshot(tmp_path):
    packet = _packet(tmp_path)

    assert packet["status"] == "CLEAR"
    schedule_evidence = packet["evidence"]["schedule_configuration"]
    assert schedule_evidence["provenance"] == "direct_current_configuration_capture"
    assert schedule_evidence["freshness"]["status"] == "not_applicable"
    assert schedule_evidence["captured_at"] == "2026-08-21T13:30:00+00:00"
    assert len(schedule_evidence["automation_tomls"]) == 10
    assert all(
        entry["status"] == "captured"
        and entry["sha256"]
        and entry["size_bytes"] > 0
        and Path(entry["path"]).is_absolute()
        and entry["automation_root"] == str(Path(entry["path"]).parents[1])
        and entry["relative_path"] == f"{entry['automation_id']}/automation.toml"
        and entry["descriptor_relative"] is True
        and entry["file_kind"] == "regular"
        and entry["symlink"] is False
        and entry["file_identity"]
        for entry in schedule_evidence["automation_tomls"]
    )
    assert all(row["status"] == "match" for row in packet["schedule_check"]["automations"])


def test_captured_schedule_snapshot_evaluates_without_rereading_paths_and_rejects_tampering(tmp_path):
    contract, roles, automation_root = _write_schedule_fixture(tmp_path)
    snapshot = capture_schedule_contract_snapshot(
        contract_path=contract,
        automation_root=automation_root,
        role_contract_path=roles,
        captured_at=dt.datetime(2026, 8, 21, 13, 30, tzinfo=UTC),
    )
    contract.unlink()
    roles.unlink()

    result = evaluate_schedule_contract(captured_snapshot=snapshot)

    assert result["contract_status"] == "pass"
    assert all(row["status"] == "match" for row in result["automations"])
    assert not isinstance(snapshot, dict)
    tampered = evaluate_schedule_contract(captured_snapshot={"captured_at": "2026-08-21T13:30:00+00:00"})
    assert tampered["issues"] == ["captured_snapshot_invalid"]


def test_captured_schedule_snapshot_consumes_immutable_bytes_after_manifest_check(tmp_path, monkeypatch):
    contract, roles, automation_root = _write_schedule_fixture(tmp_path)
    automation_id = next(iter(json.loads(contract.read_text(encoding="utf-8"))["automations"]))
    toml_path = automation_root / automation_id / "automation.toml"
    valid_toml = toml_path.read_bytes()
    toml_path.write_bytes(valid_toml.replace(b'status = "PAUSED"', b'status = "ACTIVE"'))
    snapshot = capture_schedule_contract_snapshot(
        contract_path=contract,
        automation_root=automation_root,
        role_contract_path=roles,
        captured_at=dt.datetime(2026, 8, 21, 13, 30, tzinfo=UTC),
    )
    toml_path.write_bytes(valid_toml)
    original_manifest = automation_health_audit.schedule_contract_snapshot_manifest
    assert original_manifest(snapshot)["capture_issues"] == []
    with pytest.raises(AttributeError):
        snapshot.automation_tomls = []

    def authenticate_then_attempt_mutation(captured):
        manifest = original_manifest(captured)
        if isinstance(captured, dict):
            source = captured["automation_tomls"][0]
            source["_bytes"] = valid_toml
            source["sha256"] = hashlib.sha256(valid_toml).hexdigest()
            source["size_bytes"] = len(valid_toml)
        return manifest

    monkeypatch.setattr(
        automation_health_audit,
        "schedule_contract_snapshot_manifest",
        authenticate_then_attempt_mutation,
    )

    result = evaluate_schedule_contract(captured_snapshot=snapshot)

    row = next(item for item in result["automations"] if item["automation_id"] == automation_id)
    assert row["status"] == "mismatch"
    assert "deployment_phase_status" in {item["field"] for item in row["mismatches"]}


def test_captured_schedule_snapshot_rejects_malformed_top_level_capture_time(tmp_path, monkeypatch):
    contract, roles, automation_root = _write_schedule_fixture(tmp_path)
    monkeypatch.setattr(automation_health_audit, "_now_iso", lambda _now: "not-a-timestamp")
    snapshot = capture_schedule_contract_snapshot(
        contract_path=contract,
        automation_root=automation_root,
        role_contract_path=roles,
        captured_at=dt.datetime(2026, 8, 21, 13, 30, tzinfo=UTC),
    )

    result = evaluate_schedule_contract(captured_snapshot=snapshot)

    assert result["issues"] == ["captured_snapshot_invalid"]


def test_trusted_schedule_capture_lifecycle_does_not_accumulate_global_state(tmp_path):
    contract, roles, automation_root = _write_schedule_fixture(tmp_path)
    baseline = automation_health_audit._trusted_capture_store_size()
    for _ in range(12):
        snapshot = capture_schedule_contract_snapshot(
            contract_path=contract,
            automation_root=automation_root,
            role_contract_path=roles,
            captured_at=dt.datetime(2026, 8, 21, 13, 30, tzinfo=UTC),
        )
        assert evaluate_schedule_contract(captured_snapshot=snapshot)["contract_status"] == "pass"
    del snapshot
    gc.collect()

    assert automation_health_audit._trusted_capture_store_size() == baseline


def test_safety_sentinel_holds_missing_or_changed_schedule_capture(tmp_path, monkeypatch):
    control, preopen, contract, roles, automation_root = _write_clear_evidence(tmp_path / "missing")
    roles.unlink()
    missing = build_safety_sentinel_packet(
        live_control_path=control,
        preopen_validation_path=preopen,
        schedule_contract_path=contract,
        automation_root=automation_root,
        role_contract_path=roles,
        broker_snapshot={
            "account": {},
            "positions": [],
            "open_orders": [],
            "clock": {},
            "errors": {},
            "read_methods": ["get_account", "list_positions", "list_orders", "get_clock"],
            "captured_at": "2026-08-21T13:30:00+00:00",
        },
        now=dt.datetime(2026, 8, 21, 13, 30, tzinfo=UTC),
    )
    control, preopen, contract, roles, automation_root = _write_clear_evidence(tmp_path / "changed")
    automation_id = next(iter(json.loads(contract.read_text(encoding="utf-8"))["automations"]))
    toml_path = automation_root / automation_id / "automation.toml"
    outside_toml = tmp_path / "changed-outside.toml"
    outside_toml.write_bytes(toml_path.read_bytes())
    toml_path.unlink()
    toml_path.symlink_to(outside_toml)
    changed_snapshot = capture_schedule_contract_snapshot(
        contract_path=contract,
        automation_root=automation_root,
        role_contract_path=roles,
        captured_at=dt.datetime(2026, 8, 21, 13, 30, tzinfo=UTC),
    )
    monkeypatch.setattr(
        safety_sentinel,
        "capture_schedule_contract_snapshot",
        lambda **_kwargs: changed_snapshot,
    )
    changed = _packet(tmp_path / "changed-packet")

    assert missing["status"] == "HOLD"
    assert "schedule_configuration_capture_invalid" in missing["reasons"]
    assert changed["status"] == "HOLD"
    assert "schedule_configuration_capture_invalid" in changed["reasons"]


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
    monkeypatch.setattr(cli_main, "_alpaca_live_client", lambda: client)
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


def test_safety_sentinel_holds_malformed_broker_values_even_when_all_keys_exist(tmp_path):
    control, preopen, contract, roles, automation_root = _write_clear_evidence(tmp_path)

    packet = build_safety_sentinel_packet(
        live_control_path=control,
        preopen_validation_path=preopen,
        schedule_contract_path=contract,
        automation_root=automation_root,
        role_contract_path=roles,
        broker_snapshot={
            "account": None,
            "positions": "not-a-list",
            "open_orders": {},
            "clock": [],
            "errors": {},
            "read_methods": ["get_account", "list_positions", "list_orders", "get_clock"],
            "captured_at": "2026-08-21T13:30:00+00:00",
        },
        now=dt.datetime(2026, 8, 21, 13, 30, tzinfo=UTC),
    )

    assert packet["status"] == "HOLD"
    assert set(packet["reasons"]) >= {
        "broker_snapshot_account_invalid",
        "broker_snapshot_positions_invalid",
        "broker_snapshot_open_orders_invalid",
        "broker_snapshot_clock_invalid",
    }


def test_safety_sentinel_accepts_the_minimum_well_formed_populated_broker_snapshot(tmp_path):
    control, preopen, contract, roles, automation_root = _write_clear_evidence(tmp_path)

    packet = build_safety_sentinel_packet(
        live_control_path=control,
        preopen_validation_path=preopen,
        schedule_contract_path=contract,
        automation_root=automation_root,
        role_contract_path=roles,
        broker_snapshot={
            "account": {"id": "account-1", "status": "ACTIVE"},
            "positions": [{"symbol": "AAPL", "qty": "1"}],
            "open_orders": [
                {
                    "id": "order-1",
                    "symbol": "MSFT",
                    "side": "buy",
                    "qty": "2",
                    "status": "new",
                }
            ],
            "clock": {"is_open": False, "timestamp": "2026-08-21T13:30:00+00:00"},
            "errors": {},
            "read_methods": ["get_account", "list_positions", "list_orders", "get_clock"],
            "captured_at": "2026-08-21T13:30:00+00:00",
        },
        now=dt.datetime(2026, 8, 21, 13, 30, tzinfo=UTC),
    )

    assert packet["status"] == "CLEAR"


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("account", {"id": [], "status": "ACTIVE"}, "broker_snapshot_account_invalid"),
        ("positions", [None], "broker_snapshot_position_0_invalid"),
        ("open_orders", ["not-an-order"], "broker_snapshot_open_order_0_invalid"),
        (
            "clock",
            {"is_open": "false", "timestamp": []},
            "broker_snapshot_clock_invalid",
        ),
    ],
)
def test_safety_sentinel_holds_nested_malformed_broker_values(tmp_path, field, value, reason):
    control, preopen, contract, roles, automation_root = _write_clear_evidence(tmp_path)
    snapshot = {
        "account": {"id": "account-1", "status": "ACTIVE"},
        "positions": [],
        "open_orders": [],
        "clock": {"is_open": False, "timestamp": "2026-08-21T13:30:00+00:00"},
        "errors": {},
        "read_methods": ["get_account", "list_positions", "list_orders", "get_clock"],
        "captured_at": "2026-08-21T13:30:00+00:00",
    }
    snapshot[field] = value

    packet = build_safety_sentinel_packet(
        live_control_path=control,
        preopen_validation_path=preopen,
        schedule_contract_path=contract,
        automation_root=automation_root,
        role_contract_path=roles,
        broker_snapshot=snapshot,
        now=dt.datetime(2026, 8, 21, 13, 30, tzinfo=UTC),
    )

    assert packet["status"] == "HOLD"
    assert reason in packet["reasons"]


def test_automatic_schedule_capture_ignores_unrelated_automation_namespace(tmp_path):
    contract, roles, automation_root = _write_schedule_fixture(tmp_path)
    unrelated_toml = automation_root / "weekly-review" / "automation.toml"
    unrelated_toml.parent.mkdir(parents=True)
    unrelated_toml.write_text('name = "unrelated"\nstatus = "ACTIVE"\n', encoding="utf-8")

    result = evaluate_schedule_contract(
        contract_path=contract,
        automation_root=automation_root,
        role_contract_path=roles,
    )

    assert result["contract_status"] == "pass"
    assert {row["automation_id"] for row in result["automations"]} == set(
        json.loads(contract.read_text(encoding="utf-8"))["automations"]
    )


def test_captured_schedule_snapshot_rejects_hidden_unexpected_automation(tmp_path):
    contract, roles, automation_root = _write_schedule_fixture(tmp_path)
    unexpected_id = "tradingagents-unexpected-observer"
    unexpected_toml = automation_root / unexpected_id / "automation.toml"
    unexpected_toml.parent.mkdir(parents=True)
    unexpected_toml.write_text('name = "unexpected"\nstatus = "PAUSED"\n', encoding="utf-8")
    snapshot = capture_schedule_contract_snapshot(
        contract_path=contract,
        automation_root=automation_root,
        role_contract_path=roles,
        captured_at=dt.datetime(2026, 8, 21, 13, 30, tzinfo=UTC),
    )
    result = evaluate_schedule_contract(captured_snapshot=snapshot)

    assert result["issues"] == ["captured_snapshot_invalid"]


def test_captured_schedule_snapshot_rejects_unexpected_regular_file_automation_entry(tmp_path):
    contract, roles, automation_root = _write_schedule_fixture(tmp_path)
    unexpected_entry = automation_root / "tradingagents-unexpected-file"
    unexpected_entry.write_text("not an automation directory\n", encoding="utf-8")
    snapshot = capture_schedule_contract_snapshot(
        contract_path=contract,
        automation_root=automation_root,
        role_contract_path=roles,
        captured_at=dt.datetime(2026, 8, 21, 13, 30, tzinfo=UTC),
    )

    result = evaluate_schedule_contract(captured_snapshot=snapshot)

    assert result["issues"] == ["captured_snapshot_invalid"]


def test_captured_schedule_snapshot_rejects_unexpected_automation_directory_without_toml(
    tmp_path,
):
    contract, roles, automation_root = _write_schedule_fixture(tmp_path)
    (automation_root / "tradingagents-unexpected-directory").mkdir()
    snapshot = capture_schedule_contract_snapshot(
        contract_path=contract,
        automation_root=automation_root,
        role_contract_path=roles,
        captured_at=dt.datetime(2026, 8, 21, 13, 30, tzinfo=UTC),
    )

    result = evaluate_schedule_contract(captured_snapshot=snapshot)

    assert result["issues"] == ["captured_snapshot_invalid"]


def test_captured_schedule_snapshot_rejects_extra_and_symlinked_automation_tomls(tmp_path):
    contract, roles, automation_root = _write_schedule_fixture(tmp_path / "extra")
    unexpected_id = "tradingagents-unexpected-observer"
    unexpected_toml = automation_root / unexpected_id / "automation.toml"
    unexpected_toml.parent.mkdir(parents=True)
    unexpected_toml.write_text('name = "unexpected"\nstatus = "PAUSED"\n', encoding="utf-8")
    extra = capture_schedule_contract_snapshot(
        contract_path=contract,
        automation_root=automation_root,
        role_contract_path=roles,
        captured_at=dt.datetime(2026, 8, 21, 13, 30, tzinfo=UTC),
    )

    assert evaluate_schedule_contract(captured_snapshot=extra)["issues"] == [
        "captured_snapshot_invalid"
    ]

    contract, roles, automation_root = _write_schedule_fixture(tmp_path / "symlink")
    automation_id = next(iter(json.loads(contract.read_text(encoding="utf-8"))["automations"]))
    toml_path = automation_root / automation_id / "automation.toml"
    outside_toml = tmp_path / "outside.toml"
    outside_toml.write_bytes(toml_path.read_bytes())
    toml_path.unlink()
    toml_path.symlink_to(outside_toml)
    symlinked = capture_schedule_contract_snapshot(
        contract_path=contract,
        automation_root=automation_root,
        role_contract_path=roles,
        captured_at=dt.datetime(2026, 8, 21, 13, 30, tzinfo=UTC),
    )

    assert evaluate_schedule_contract(captured_snapshot=symlinked)["issues"] == [
        "captured_snapshot_invalid"
    ]


@pytest.mark.parametrize(
    "hand_built",
    [
        {},
        {"captured_at": "2026-08-21T13:30:00+00:00", "automation_tomls": []},
        {"automation_root": "/outside-root", "discovered_automation_ids": []},
        {"automation_tomls": [{"automation_id": "mismatched-id", "_bytes": b"substituted"}]},
    ],
)
def test_captured_schedule_snapshot_rejects_each_hand_built_or_mutable_mapping(hand_built):
    result = evaluate_schedule_contract(captured_snapshot=hand_built)

    assert result["issues"] == ["captured_snapshot_invalid"]


def test_safety_sentinel_writer_refuses_collision_and_failed_publication(tmp_path, monkeypatch):
    packet = _packet(tmp_path / "packet")
    output_dir = tmp_path / "output"
    first = write_safety_sentinel_packet(packet, output_dir=output_dir)
    original = first.read_bytes()

    with pytest.raises(FileExistsError):
        write_safety_sentinel_packet(packet, output_dir=output_dir)
    assert first.read_bytes() == original

    failed_dir = tmp_path / "failed-publication"
    monkeypatch.setattr(safety_sentinel.os, "link", lambda *_args: (_ for _ in ()).throw(OSError("fail")))
    with pytest.raises(OSError, match="fail"):
        write_safety_sentinel_packet(packet, output_dir=failed_dir)
    assert list(failed_dir.glob("safety-sentinel-*.json")) == []
    assert list(failed_dir.glob(".*.tmp")) == []
