import copy
import datetime as dt
import hashlib
import inspect
import json
import os
import subprocess
import sys
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path

import pytest

from tradingagents.brokers import alpaca_reconciliation
from tradingagents.brokers.supervisor.loss_review import loss_exit_review_packet
from tradingagents.orchestration.recovery import (
    rearm_after_verified_recovery,
)
from tradingagents.orchestration.self_heal import (
    RECOVERY_FOCUSED_TESTS,
    build_production_recovery_request,
    coordinate_verified_recovery,
)
from tradingagents.policy.exit_policy import apply_exit_policy_to_position
from tradingagents.policy.live_control import (
    load_live_control_state,
    write_live_control_state,
)
from tradingagents.policy.live_gate import evaluate_go_live_guard
from tradingagents.policy.promotion_sync import sync_promotion_state_file
from tradingagents.research.loss_review_evidence import build_loss_review_evidence_packet
from tradingagents.research.provider_orchestrator import TickerProviderResearchResult

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_ROOT = REPO_ROOT / "tests" / "fixtures" / "autonomous_recovery"
NOW = dt.datetime(2026, 7, 18, 12, 0, tzinfo=dt.timezone.utc)
SOURCE_REVISION = "c" * 40

PRODUCTION_AUTHORITY_PATHS = (
    REPO_ROOT / "results" / "policy" / "live_control.json",
    REPO_ROOT / "results" / "policy" / ".live_control.json.control.lock",
    REPO_ROOT / "results" / "policy" / "promotion_state.json",
    REPO_ROOT / "results" / "policy" / ".promotion_state.json.recovery.lock",
    REPO_ROOT / "config" / "risk_envelope.yaml",
    REPO_ROOT / "config" / "research_integrations.json",
)
SECRET_SUFFIXES = (
    ".secret",
    ".secrets",
    ".token",
    ".tokens",
    ".key",
    ".keys",
    ".pem",
    ".p12",
    ".pfx",
    ".crt",
    ".cer",
    ".der",
    ".kdbx",
)
SNAPSHOT_EXCLUDED_PARTS = {
    ".cache",
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    "__pycache__",
    "node_modules",
}
PHASE_PACKET_NAMES = (
    "resolve_authority",
    "regenerate_evidence",
    "reconcile",
    "focused_verify",
    "promotion_prepare",
    "promotion_commit",
    "sync_promotion",
    "ready_incident",
    "manifest",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _is_bounded_credential_surface(relative: Path) -> bool:
    parts = relative.parts
    name = relative.name
    if name == ".env" or name.startswith(".env.") or name == ".envrc":
        return True
    if name.endswith(SECRET_SUFFIXES):
        return True
    if parts[:2] == ("config", "n8n"):
        return True
    if parts and parts[0] == "n8n":
        if len(parts) >= 2 and parts[1] in {
            ".n8n",
            "data",
            "credentials",
        }:
            return True
        if "credentials" in name and name.endswith(".json"):
            return True
    return False


def _authority_fingerprint(path: Path) -> str:
    if path.is_symlink():
        return "non-file:symlink"
    if path.is_file():
        return f"file:{_sha256(path)}"
    if path.is_dir():
        return "non-file:directory"
    if path.exists():
        return "non-file:other"
    return "absent"


def _snapshot_production_authority() -> dict[str, str]:
    snapshot = {
        str(path.relative_to(REPO_ROOT)): _authority_fingerprint(path)
        for path in PRODUCTION_AUTHORITY_PATHS
    }
    for current_root, directory_names, file_names in os.walk(REPO_ROOT):
        retained_directories = [
            name
            for name in directory_names
            if name not in SNAPSHOT_EXCLUDED_PARTS
        ]
        directory_names[:] = retained_directories
        current = Path(current_root)
        for entry_name in (*retained_directories, *file_names):
            path = current / entry_name
            relative = path.relative_to(REPO_ROOT)
            if any(
                part in SNAPSHOT_EXCLUDED_PARTS for part in relative.parts
            ):
                continue
            if _is_bounded_credential_surface(relative):
                snapshot[str(relative)] = _authority_fingerprint(path)
    return dict(sorted(snapshot.items()))


def _snapshot_fixtures() -> dict[str, str]:
    return {
        str(path.relative_to(REPO_ROOT)): _sha256(path)
        for path in sorted(FIXTURE_ROOT.rglob("*"))
        if path.is_file()
    }


def _load_fixture(name: str) -> dict:
    return json.loads(
        (FIXTURE_ROOT / name).read_text(encoding="utf-8")
    )


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _copy_fixture(name: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes((FIXTURE_ROOT / name).read_bytes())


def _genuine_policy_authority(position: dict, *, supervisor_path: Path) -> dict:
    enriched = apply_exit_policy_to_position(position, generated_at=NOW)
    supervisor = loss_exit_review_packet(
        enriched,
        generated_at=NOW,
        decision_id="loss-exit-NFLX-20260718",
        proposed_limit_price=enriched["exit_policy_limit_price"],
    )
    hourly_packet = {
        "generated_at": NOW.isoformat(),
        "decision": "close",
        "actions": [],
        "submitted": [],
        "evidence": {"loss_exit_review": supervisor},
        "portfolio": {
            "live": {
                "positions": [
                    {
                        "symbol": supervisor["symbol"],
                        "qty": position["qty"],
                        "current_price": position["current_price"],
                        "avg_entry_price": position["avg_entry_price"],
                        "unrealized_pl": position["unrealized_pl"],
                        "unrealized_plpc": position["unrealized_plpc"],
                    }
                ]
            }
        },
    }
    evidence = build_loss_review_evidence_packet(
        hourly_packet_path=supervisor_path,
        hourly_packet=hourly_packet,
        provider_result=TickerProviderResearchResult(symbol=supervisor["symbol"]),
        entry_context={"symbol": supervisor["symbol"], "account": "live"},
    )
    return {
        "supervisor_review_authority": supervisor,
        "advisory_analysis": evidence.payload["advisory_analysis"],
    }


class _ReadOnlyBroker:
    def __init__(self, snapshot: dict):
        self.positions = copy.deepcopy(snapshot["positions"])
        self.orders = copy.deepcopy(snapshot["orders"])
        self.read_calls: list[tuple] = []
        self.write_calls: list[tuple] = []

    def list_positions(self):
        self.read_calls.append(("list_positions",))
        return self.positions

    def list_orders(self, status="all"):
        self.read_calls.append(("list_orders", status))
        return self.orders

    def get_order_by_client_order_id(self, client_order_id):
        self.read_calls.append(
            ("get_order_by_client_order_id", client_order_id)
        )
        return next(
            (
                order
                for order in self.orders
                if order["client_order_id"] == client_order_id
            ),
            None,
        )

    def _reject_write(self, name, args, kwargs):
        self.write_calls.append((name, args, kwargs))
        raise AssertionError("recovery reconciliation attempted a broker write")

    def submit_order(self, *args, **kwargs):
        return self._reject_write("submit_order", args, kwargs)

    def cancel_order(self, *args, **kwargs):
        return self._reject_write("cancel_order", args, kwargs)

    def replace_order(self, *args, **kwargs):
        return self._reject_write("replace_order", args, kwargs)

    def close_position(self, *args, **kwargs):
        return self._reject_write("close_position", args, kwargs)


class _CommandResult:
    def __init__(
        self,
        *,
        stdout: str = "",
        stderr: str = "",
        returncode: int = 0,
    ):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


def _build_fixture_recovery_request(
    tmp_path: Path,
    *,
    focused_gate_records: list[dict],
) -> dict:
    supervisor_path = (
        tmp_path / "results" / "hourly_supervisor" / "supervisor.json"
    )
    advisory_path = (
        tmp_path / "results" / "hourly_supervisor" / "advisory.json"
    )
    hourly_dir = tmp_path / "results" / "hourly_supervisor"
    report_path = (
        tmp_path / "results" / "paper_strategy_tournament" / "latest.json"
    )
    state_path = tmp_path / "results" / "policy" / "promotion_state.json"
    envelope_path = tmp_path / "config" / "risk_envelope.yaml"
    reconciliation_path = (
        tmp_path / "results" / "alpaca_reconciliation" / "latest.json"
    )
    authority = _genuine_policy_authority(
        _load_fixture("policy_authority.json")["position"],
        supervisor_path=supervisor_path,
    )
    evidence = _load_fixture("loss_review_evidence.json")
    evidence_path = (
        tmp_path / "results" / "loss_review_evidence" / "latest.json"
    )
    evidence["packet_path"] = str(evidence_path.resolve())
    evidence["payload"].update(copy.deepcopy(authority))

    _write_json(
        supervisor_path,
        authority["supervisor_review_authority"],
    )
    _write_json(advisory_path, authority["advisory_analysis"])
    _write_json(evidence_path, evidence)
    _copy_fixture("paper_tournament_latest.json", report_path)
    _copy_fixture("promotion_state.json", state_path)
    _copy_fixture("risk_envelope.yaml", envelope_path)
    _copy_fixture("reconciliation_input.json", reconciliation_path)

    immutable_paths = (
        supervisor_path,
        advisory_path,
        evidence_path,
        report_path,
        envelope_path,
        reconciliation_path,
    )
    immutable_inputs = {path: _sha256(path) for path in immutable_paths}
    fixture_hashes = _snapshot_fixtures()
    broker = _ReadOnlyBroker(_load_fixture("broker_snapshot.json"))
    invocations: list[list[str]] = []

    def runner(argv, **_kwargs):
        command = list(argv)
        invocations.append(command)
        if command[:3] == ["git", "rev-parse", "HEAD"]:
            return _CommandResult(stdout=f"{SOURCE_REVISION}\n")
        if "loss-review-evidence" in command:
            return _CommandResult(stdout=json.dumps(evidence))
        if "reconcile-symbol-incident" in command:
            reconciliation = (
                alpaca_reconciliation.reconcile_symbol_incident(
                    symbol="NFLX",
                    packet_paths=[reconciliation_path],
                    live_client=broker,
                    expected_qty=Decimal("1"),
                )
            )
            return _CommandResult(
                stdout=json.dumps(
                    {
                        "schema_version": 1,
                        "kind": "symbol_broker_reconciliation",
                        "generated_at": NOW.isoformat(),
                        "read_only": True,
                        "analysis_only": True,
                        "can_submit_orders": False,
                        "execution_authority": "none",
                        **asdict(reconciliation),
                    }
                )
            )
        if "pytest" in command:
            expected_command = [
                sys.executable,
                "-m",
                "pytest",
                *RECOVERY_FOCUSED_TESTS,
                "-q",
            ]
            gate_is_exact = (
                len(focused_gate_records) == 1
                and focused_gate_records[0].get("command")
                == expected_command
                and focused_gate_records[0].get("cwd") == REPO_ROOT
                and focused_gate_records[0].get("returncode") == 0
            )
            if command != expected_command or not gate_is_exact:
                return _CommandResult(
                    stderr="real focused subprocess proof is absent",
                    returncode=1,
                )
            return _CommandResult(stdout="focused subprocess passed")
        if "sync-promotion" in command:
            arm_live = (
                "--arm-live" in command and "--no-arm-live" not in command
            )
            ci_green = (
                "--ci-green" in command and "--no-ci-green" not in command
            )
            generated_at = dt.datetime.fromisoformat(
                command[command.index("--generated-at") + 1]
            )
            canonical_input_path = command[
                command.index("--state-path") + 1
            ]
            output_state_path = command[
                command.index("--output-state-path") + 1
            ]
            result = sync_promotion_state_file(
                command[command.index("--report-path") + 1],
                canonical_input_path,
                output_state_path=output_state_path,
                tiny_live_tranche_usd=Decimal("25.00"),
                arm_live=arm_live,
                ci_green=ci_green,
                now=generated_at,
            )
            return _CommandResult(
                stdout=json.dumps(
                    {
                        "summary": result.summary,
                        "promoted": result.promoted,
                        "demoted": result.demoted,
                        "issues_by_sleeve": result.issues_by_sleeve,
                        "state_path": output_state_path,
                        "canonical_state_path": canonical_input_path,
                        "report_path": command[
                            command.index("--report-path") + 1
                        ],
                        "arm_live": arm_live,
                        "ci_green": ci_green,
                        "can_submit_orders": False,
                        "execution_authority": "none",
                        "state": result.state,
                    }
                )
            )
        raise AssertionError(command)

    context = {
        "symbol": "NFLX",
        "broker_account": "live",
        "environment": "production",
        "source_revision": SOURCE_REVISION,
        "supervisor_path": str(supervisor_path),
        "advisory_path": str(advisory_path),
        "hourly_dir": str(hourly_dir),
        "report_path": str(report_path),
        "envelope_path": str(envelope_path),
        "promotion_state_path": str(state_path),
        "reconciliation_packet_paths": [str(reconciliation_path)],
        "supervisor_record": authority["supervisor_review_authority"],
        "advisory_record": authority["advisory_analysis"],
    }
    request = build_production_recovery_request(
        {
            "label": "policy_rule_conflict",
            "reason": "approval_conflict",
            "symbol": "NFLX",
            "recovery_context": context,
        },
        repo_root=tmp_path,
        command_runner=runner,
    )
    assert request["ready"] is True, request
    assert request["bindings"]["broker_account"] == "live"
    assert request["bindings"]["environment"] == "production"
    return {
        "request": request,
        "canonical_path": state_path,
        "invocations": invocations,
        "broker": broker,
        "immutable_inputs": immutable_inputs,
        "fixture_hashes": fixture_hashes,
    }


def _frozen_control(tmp_path: Path) -> Path:
    path = tmp_path / "live_control.json"
    if path.exists():
        return path
    write_live_control_state(
        path,
        frozen=True,
        reason="incident",
        dead_man_expires_at=NOW + dt.timedelta(days=1),
        now=NOW,
    )
    return path


def _coordinator_args(request: dict) -> dict:
    args = dict(request)
    assert args.pop("ready") is True
    return args


def _with_focused_subprocess_verifier(
    adapters: dict,
    *,
    records: list[dict],
    runner=None,
) -> dict:
    production_adapter = adapters["focused_verify"]
    verifier_runner = subprocess.run if runner is None else runner

    def focused_verify(arguments):
        command = [
            sys.executable,
            "-m",
            "pytest",
            *RECOVERY_FOCUSED_TESTS,
            "-q",
        ]
        try:
            result = verifier_runner(
                command,
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                timeout=120,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            records.append(
                {
                    "command": command,
                    "cwd": REPO_ROOT,
                    "returncode": None,
                    "error": type(error).__name__,
                }
            )
            return {
                "outcome": "failed",
                "failure_type": "transient",
                "detail": (
                    "focused_verify: fixed focused verification failed"
                ),
            }
        records.append(
            {
                "command": command,
                "cwd": REPO_ROOT,
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }
        )
        if result.returncode != 0:
            return {
                "outcome": "failed",
                "failure_type": "transient",
                "detail": (
                    "focused_verify: fixed focused verification failed"
                ),
            }
        return production_adapter(arguments)

    wrapped = dict(adapters)
    wrapped["focused_verify"] = focused_verify
    return wrapped


def _live_buy_guard(*, root: Path, state_path: Path):
    return evaluate_go_live_guard(
        [
            {
                "action": "buy",
                "symbol": "NFLX",
                "notional": Decimal("20"),
                "limit_price": Decimal("100"),
                "side": "buy",
                "order_type": "limit",
                "account": "live",
                "execution_mode": "tiny_live",
                "asset_class": "stock",
                "sleeve": "pullback-support",
            }
        ],
        risk_envelope_path=root / "config" / "risk_envelope.yaml",
        promotion_state_path=state_path,
        control_state_path=root / "live_control.json",
        live_buying_power=Decimal("1000"),
        now=NOW,
    )


def _phase_packet_paths(run_root: Path) -> dict[str, Path]:
    return {
        name: run_root / "packets" / f"{name}.json"
        for name in PHASE_PACKET_NAMES
    }


def _snapshot_packet_bytes(packet_root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(packet_root)): path.read_bytes()
        for path in sorted(packet_root.rglob("*"))
        if path.is_file()
    }


def _commands_containing(
    invocations: list[list[str]],
    marker: str,
) -> list[list[str]]:
    return [command for command in invocations if marker in command]


def test_clean_nflx_recovery_closes_the_exact_task6_task5_chain(tmp_path):
    production_before = _snapshot_production_authority()
    focused_runs: list[dict] = []
    harness = _build_fixture_recovery_request(
        tmp_path,
        focused_gate_records=focused_runs,
    )
    request = harness["request"]
    canonical_path = harness["canonical_path"]
    invocations = harness["invocations"]
    broker = harness["broker"]
    args = _coordinator_args(request)
    assert args["bindings"]["broker_account"] == "live"
    assert args["bindings"]["environment"] == "production"
    args["adapters"] = _with_focused_subprocess_verifier(
        args["adapters"],
        records=focused_runs,
    )

    control_path = _frozen_control(tmp_path)
    initial_promotion = json.loads(
        canonical_path.read_text(encoding="utf-8")
    )
    assert initial_promotion["sleeves"] == {}
    assert not any(
        record.get("live_enabled") is True
        for record in initial_promotion["sleeves"].values()
    )
    canonical_before_sha256 = _sha256(canonical_path)
    receipt_dir = tmp_path / "receipts"
    recovery_root = tmp_path / "results" / "control_plane" / "recovery"
    run_root = (
        recovery_root / request["incident_id"] / request["recovery_run_id"]
    )
    pre_promotion_observations = []

    def stop_before_rearm(boundary):
        if boundary["boundary"] == "before_promotion_adapter":
            pre_promotion = json.loads(
                canonical_path.read_text(encoding="utf-8")
            )
            pre_promotion_observations.append(
                {
                    "has_live_enabled_sleeve": any(
                        record.get("live_enabled") is True
                        for record in pre_promotion["sleeves"].values()
                    ),
                    "focused_exists": (
                        run_root / "packets" / "focused_verify.json"
                    ).is_file(),
                }
            )
        if (
            boundary["boundary"] == "after_phase_fsync"
            and boundary["phase"] == "manifest"
        ):
            raise SystemExit("inspect frozen live gate before Task 5")

    with pytest.raises(
        SystemExit,
        match="inspect frozen live gate before Task 5",
    ):
        coordinate_verified_recovery(
            **args,
            control_path=control_path,
            receipt_dir=receipt_dir,
            recovery_root=recovery_root,
            now=NOW,
            fault_hook=stop_before_rearm,
        )

    invocations_before_resume = copy.deepcopy(invocations)
    focused_runs_before_resume = copy.deepcopy(focused_runs)
    broker_reads_before_resume = copy.deepcopy(broker.read_calls)
    broker_writes_before_resume = copy.deepcopy(broker.write_calls)
    reconcile_invocations = _commands_containing(
        invocations,
        "reconcile-symbol-incident",
    )
    focused_invocations = _commands_containing(invocations, "pytest")
    promotion_invocations = _commands_containing(
        invocations,
        "sync-promotion",
    )
    assert len(reconcile_invocations) == 1
    assert len(focused_invocations) == 1
    assert len(promotion_invocations) == 1
    assert set(RECOVERY_FOCUSED_TESTS).issubset(focused_invocations[0])
    assert invocations.index(reconcile_invocations[0]) < invocations.index(
        focused_invocations[0]
    ) < invocations.index(promotion_invocations[0])
    assert "--ci-green" in promotion_invocations[0]
    assert pre_promotion_observations == [
        {
            "has_live_enabled_sleeve": False,
            "focused_exists": True,
        }
    ]

    promoted = json.loads(canonical_path.read_text(encoding="utf-8"))
    assert promoted["sleeves"]["pullback-support"]["live_enabled"] is True
    frozen, frozen_issues = load_live_control_state(control_path, now=NOW)
    assert frozen_issues
    assert frozen["frozen"] is True
    assert list(receipt_dir.glob("verified-rearm-*.json")) == []
    blocked_guard = _live_buy_guard(
        root=tmp_path,
        state_path=canonical_path,
    )
    assert blocked_guard.allowed is False
    assert blocked_guard.checks["live_not_frozen"] is False

    phase_paths = _phase_packet_paths(run_root)
    assert set(phase_paths) == set(PHASE_PACKET_NAMES)
    assert all(path.is_file() for path in phase_paths.values())
    phase_bytes_before_rearm = {
        name: path.read_bytes() for name, path in phase_paths.items()
    }

    resumed = coordinate_verified_recovery(
        **args,
        control_path=control_path,
        receipt_dir=receipt_dir,
        recovery_root=recovery_root,
        now=NOW,
    )

    assert resumed["status"] == "monitoring"
    assert invocations == invocations_before_resume
    assert focused_runs == focused_runs_before_resume
    assert broker.read_calls == broker_reads_before_resume
    assert broker.write_calls == broker_writes_before_resume
    assert len(focused_runs) == 1
    assert focused_runs[0]["command"] == [
        sys.executable,
        "-m",
        "pytest",
        *RECOVERY_FOCUSED_TESTS,
        "-q",
    ]
    assert focused_runs[0]["cwd"] == REPO_ROOT
    assert focused_runs[0]["returncode"] == 0
    assert "passed" in focused_runs[0]["stdout"]
    assert (
        inspect.signature(coordinate_verified_recovery)
        .parameters["rearm"]
        .default
        is rearm_after_verified_recovery
    )
    assert (
        len(
            _commands_containing(
                invocations,
                "reconcile-symbol-incident",
            )
        )
        == 1
    )
    assert len(_commands_containing(invocations, "pytest")) == 1
    assert len(_commands_containing(invocations, "sync-promotion")) == 1
    assert broker.write_calls == []
    assert broker.read_calls
    assert {
        name: path.read_bytes() for name, path in phase_paths.items()
    } == phase_bytes_before_rearm

    packets = run_root / "packets"
    incident_path = packets / "ready_incident.json"
    reconciliation_path = packets / "reconcile.json"
    focused_path = packets / "focused_verify.json"
    promotion_path = packets / "sync_promotion.json"
    manifest_path = packets / "manifest.json"
    prepare_path = packets / "promotion_prepare.json"
    commit_path = packets / "promotion_commit.json"
    promotion = json.loads(promotion_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    prepare = json.loads(prepare_path.read_text(encoding="utf-8"))
    commit = json.loads(commit_path.read_text(encoding="utf-8"))
    ready_incident = json.loads(incident_path.read_text(encoding="utf-8"))
    focused = json.loads(focused_path.read_text(encoding="utf-8"))
    reconciliation = json.loads(
        reconciliation_path.read_text(encoding="utf-8")
    )
    stage_path = Path(promotion["staged_state_path"])
    recovery_commit = promotion["recovery_commit"]

    assert ready_incident["schema_version"] == "tradingagents.incident.v1"
    assert ready_incident["stage"] == "ready"
    assert ready_incident["root_cause_resolved"] is True
    assert ready_incident["external_blockers"] == []
    assert any(
        event.get("to_stage") == "ready"
        for event in ready_incident["history"]
    )
    assert ready_incident["evidence_refs"] == [
        str(packets / f"{phase}.json")
        for phase in (
            "resolve_authority",
            "regenerate_evidence",
            "reconcile",
            "focused_verify",
            "sync_promotion",
        )
    ]
    expected_sources = {
        "incident": incident_path,
        "reconciliation": reconciliation_path,
        "promotion": promotion_path,
        "focused": focused_path,
    }
    assert manifest["packet_paths"] == {
        name: str(path.resolve()) for name, path in expected_sources.items()
    }
    assert manifest["packet_sha256"] == {
        name: _sha256(path) for name, path in expected_sources.items()
    }
    assert {
        key: manifest[key] for key in request["bindings"]
    } == request["bindings"]
    assert focused["passing_tests"] == list(RECOVERY_FOCUSED_TESTS)
    assert reconciliation["matched"] is True
    assert reconciliation["read_only"] is True
    assert reconciliation["broker_write_calls"] == 0

    stage_sha256 = _sha256(stage_path)
    canonical_sha256 = _sha256(canonical_path)
    prepare_sha256 = _sha256(prepare_path)
    commit_sha256 = _sha256(commit_path)
    assert promotion["promotion_prepare"] == {
        "path": str(prepare_path.resolve()),
        "sha256": prepare_sha256,
    }
    assert promotion["promotion_commit"] == {
        "path": str(commit_path.resolve()),
        "sha256": commit_sha256,
    }
    assert prepare["recovery_commit"] == recovery_commit
    assert commit["recovery_commit"] == recovery_commit
    assert prepare["expected_stage_sha256"] == stage_sha256
    assert commit["staged_sha256"] == stage_sha256
    assert promotion["staged_state_sha256"] == stage_sha256
    assert (
        promotion["canonical_after_sha256"]
        == canonical_sha256
        == stage_sha256
    )
    assert commit["canonical_after_sha256"] == canonical_sha256
    assert (
        commit["canonical_before_sha256"]
        == recovery_commit["canonical_before_sha256"]
    )
    assert (
        recovery_commit["canonical_before_sha256"]
        == canonical_before_sha256
    )
    assert recovery_commit["focused_sha256"] == _sha256(focused_path)
    assert recovery_commit["reconciliation_sha256"] == _sha256(
        reconciliation_path
    )
    assert recovery_commit["report_sha256"] == _sha256(
        tmp_path / "results" / "paper_strategy_tournament" / "latest.json"
    )
    assert recovery_commit["envelope_sha256"] == _sha256(
        tmp_path / "config" / "risk_envelope.yaml"
    )

    control, control_issues = load_live_control_state(control_path, now=NOW)
    assert control_issues == []
    assert control["frozen"] is False
    receipt_path = Path(control["recovery_receipt_path"])
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    issued_at = dt.datetime.fromisoformat(receipt["issued_at"])
    expires_at = dt.datetime.fromisoformat(control["dead_man_expires_at"])
    assert dt.timedelta(0) < expires_at - issued_at <= dt.timedelta(
        minutes=90
    )
    assert control["recovery_receipt_sha256"] == _sha256(receipt_path)
    assert control["dead_man_expires_at"] == receipt["expires_at"]
    assert control["recovery_incident_id"] == request["incident_id"]
    assert receipt["broker_write_calls"] == 0
    assert receipt["ttl_minutes"] <= 90
    assert receipt["source_bindings"] == request["bindings"]
    assert receipt["source_packet_paths"] == manifest["packet_paths"]
    assert receipt["source_packet_sha256"] == manifest["packet_sha256"]
    assert receipt["recovery_manifest_path"] == str(
        manifest_path.resolve()
    )
    assert receipt["recovery_manifest_sha256"] == _sha256(manifest_path)
    assert receipt["repairer_run_id"] == ready_incident["repairer_run_id"]
    assert receipt["verifier_run_id"] == focused["verifier_run_id"]
    assert receipt["repairer_role_id"] == ready_incident["repairer_role_id"]
    assert receipt["verifier_role_id"] == focused["verifier_role_id"]
    assert receipt["control_binding"]["incident_id"] == request["incident_id"]
    assert receipt["control_binding"]["control_path"] == str(
        control_path.resolve()
    )
    admitted_guard = _live_buy_guard(
        root=tmp_path,
        state_path=canonical_path,
    )
    assert admitted_guard.allowed is True
    assert admitted_guard.checks["live_not_frozen"] is True
    assert admitted_guard.checks["dead_man_fresh"] is True
    assert admitted_guard.checks["promotion_state_loaded"] is True
    assert admitted_guard.checks["promotion"] is True
    expected_closure = {
        "incident": incident_path,
        "reconciliation": reconciliation_path,
        "promotion": promotion_path,
        "focused": focused_path,
        "manifest": manifest_path,
        "promotion_report": Path(recovery_commit["report_path"]),
        "promotion_envelope": Path(recovery_commit["envelope_path"]),
        "promotion_prepare": prepare_path,
        "promotion_stage": stage_path,
        "promotion_commit": commit_path,
        "promotion_canonical": canonical_path,
    }
    assert set(receipt["promotion_transaction_closure"]) == set(
        expected_closure
    )
    for name, source_path in expected_closure.items():
        closure = receipt["promotion_transaction_closure"][name]
        assert closure["source_path"] == str(source_path.resolve())
        assert closure["sha256"] == _sha256(source_path)
        assert _sha256(Path(closure["snapshot_path"])) == closure["sha256"]

    incident = json.loads(
        (
            tmp_path
            / "results"
            / "control_plane"
            / "incidents"
            / request["incident_id"]
            / "latest.json"
        ).read_text(encoding="utf-8")
    )
    assert incident["subject"] == "NFLX"
    assert incident["owner_role"] == "reliability_controller"
    assert incident["stage"] == "monitoring"
    assert any(
        event.get("to_stage") == "monitoring"
        for event in incident["history"]
    )

    invocations_before_duplicate = copy.deepcopy(invocations)
    focused_runs_before_duplicate = copy.deepcopy(focused_runs)
    broker_reads_before_duplicate = copy.deepcopy(broker.read_calls)
    broker_writes_before_duplicate = copy.deepcopy(broker.write_calls)
    receipt_before_duplicate = receipt_path.read_bytes()
    control_before_duplicate = control_path.read_bytes()
    packets_before_duplicate = _snapshot_packet_bytes(packets)
    assert "rearm.json" in packets_before_duplicate

    duplicate = coordinate_verified_recovery(
        **args,
        control_path=control_path,
        receipt_dir=receipt_dir,
        recovery_root=recovery_root,
        now=NOW,
    )

    assert duplicate["status"] == "duplicate"
    assert invocations == invocations_before_duplicate
    assert focused_runs == focused_runs_before_duplicate
    assert broker.read_calls == broker_reads_before_duplicate
    assert broker.write_calls == broker_writes_before_duplicate
    assert receipt_path.read_bytes() == receipt_before_duplicate
    assert control_path.read_bytes() == control_before_duplicate
    assert _snapshot_packet_bytes(packets) == packets_before_duplicate
    assert len(focused_runs) == 1
    assert (
        len(
            _commands_containing(
                invocations,
                "reconcile-symbol-incident",
            )
        )
        == 1
    )
    assert len(_commands_containing(invocations, "pytest")) == 1
    assert len(_commands_containing(invocations, "sync-promotion")) == 1
    assert len(list(receipt_dir.glob("verified-rearm-*.json"))) == 1
    assert {
        path: _sha256(path)
        for path in harness["immutable_inputs"]
    } == harness["immutable_inputs"]
    assert _snapshot_fixtures() == harness["fixture_hashes"]
    assert _snapshot_production_authority() == production_before


def test_nonzero_focused_verifier_stops_before_promotion_or_rearm(
    tmp_path,
):
    production_before = _snapshot_production_authority()
    focused_runs: list[dict] = []
    harness = _build_fixture_recovery_request(
        tmp_path,
        focused_gate_records=focused_runs,
    )
    request = harness["request"]
    canonical_path = harness["canonical_path"]
    invocations = harness["invocations"]
    broker = harness["broker"]
    args = _coordinator_args(request)
    assert args["bindings"]["broker_account"] == "live"
    assert args["bindings"]["environment"] == "production"
    canonical_before = canonical_path.read_bytes()

    def failing_runner(command, **_kwargs):
        return subprocess.CompletedProcess(
            command,
            returncode=1,
            stdout="",
            stderr="injected focused verification failure",
        )

    args["adapters"] = _with_focused_subprocess_verifier(
        args["adapters"],
        records=focused_runs,
        runner=failing_runner,
    )
    control_path = _frozen_control(tmp_path)
    receipt_dir = tmp_path / "receipts"
    recovery_root = tmp_path / "results" / "control_plane" / "recovery"

    result = coordinate_verified_recovery(
        **args,
        control_path=control_path,
        receipt_dir=receipt_dir,
        recovery_root=recovery_root,
        now=NOW,
    )

    assert result["status"] == "frozen"
    assert result["phase"] == "focused_verify"
    assert result["failure"] == {
        "kind": "transient",
        "detail": "focused_verify: fixed focused verification failed",
        "external": False,
    }
    assert focused_runs == [
        {
            "command": [
                sys.executable,
                "-m",
                "pytest",
                *RECOVERY_FOCUSED_TESTS,
                "-q",
            ],
            "cwd": REPO_ROOT,
            "returncode": 1,
            "stdout": "",
            "stderr": "injected focused verification failure",
        }
    ]
    assert canonical_path.read_bytes() == canonical_before
    assert json.loads(canonical_path.read_text(encoding="utf-8"))[
        "sleeves"
    ] == {}
    assert not _commands_containing(invocations, "pytest")
    assert not _commands_containing(invocations, "sync-promotion")
    assert broker.write_calls == []
    assert broker.read_calls
    assert list(
        (recovery_root / request["incident_id"]).rglob(
            "promotion_prepare.json"
        )
    ) == []
    assert list(
        (recovery_root / request["incident_id"]).rglob(
            "promotion_commit.json"
        )
    ) == []
    assert list(receipt_dir.glob("verified-rearm-*.json")) == []
    control, _issues = load_live_control_state(control_path, now=NOW)
    assert control["frozen"] is True
    incident = json.loads(
        (
            tmp_path
            / "results"
            / "control_plane"
            / "incidents"
            / request["incident_id"]
            / "latest.json"
        ).read_text(encoding="utf-8")
    )
    assert incident["stage"] == "repairing"
    assert incident["recovery"]["phase"] == "focused_verify"
    assert {
        path: _sha256(path)
        for path in harness["immutable_inputs"]
    } == harness["immutable_inputs"]
    assert _snapshot_fixtures() == harness["fixture_hashes"]
    assert _snapshot_production_authority() == production_before


def test_mismatched_broker_evidence_keeps_nflx_owned_and_frozen(tmp_path):
    production_before = _snapshot_production_authority()
    focused_runs: list[dict] = []
    harness = _build_fixture_recovery_request(
        tmp_path,
        focused_gate_records=focused_runs,
    )
    request = harness["request"]
    canonical_path = harness["canonical_path"]
    invocations = harness["invocations"]
    broker = harness["broker"]
    args = _coordinator_args(request)
    assert args["bindings"]["broker_account"] == "live"
    assert args["bindings"]["environment"] == "production"
    canonical_before = canonical_path.read_bytes()
    broker.positions[0]["qty"] = "0"
    control_path = _frozen_control(tmp_path)
    receipt_dir = tmp_path / "receipts"
    recovery_root = tmp_path / "results" / "control_plane" / "recovery"

    result = coordinate_verified_recovery(
        **args,
        control_path=control_path,
        receipt_dir=receipt_dir,
        recovery_root=recovery_root,
        now=NOW,
    )

    assert result["status"] == "frozen"
    assert result["phase"] == "reconcile"
    assert canonical_path.read_bytes() == canonical_before
    assert json.loads(canonical_path.read_text(encoding="utf-8"))[
        "sleeves"
    ] == {}
    assert focused_runs == []
    assert not _commands_containing(invocations, "pytest")
    assert not _commands_containing(invocations, "sync-promotion")
    assert broker.write_calls == []
    assert broker.read_calls
    assert list(
        (recovery_root / request["incident_id"]).rglob(
            "promotion_prepare.json"
        )
    ) == []
    assert list(
        (recovery_root / request["incident_id"]).rglob(
            "promotion_commit.json"
        )
    ) == []
    assert list(receipt_dir.glob("verified-rearm-*.json")) == []
    control, _issues = load_live_control_state(control_path, now=NOW)
    assert control["frozen"] is True
    incident = json.loads(
        (
            tmp_path
            / "results"
            / "control_plane"
            / "incidents"
            / request["incident_id"]
            / "latest.json"
        ).read_text(encoding="utf-8")
    )
    assert incident["subject"] == "NFLX"
    assert incident["owner_role"] == "reliability_controller"
    assert incident["stage"] == "repairing"
    assert incident["repairer_run_id"] == request["owner_run_id"]
    assert dt.datetime.fromisoformat(incident["lease_expires_at"]) > NOW
    assert incident["recovery"]["phase"] == "reconcile"
    assert {
        path: _sha256(path)
        for path in harness["immutable_inputs"]
    } == harness["immutable_inputs"]
    assert _snapshot_fixtures() == harness["fixture_hashes"]
    assert _snapshot_production_authority() == production_before
