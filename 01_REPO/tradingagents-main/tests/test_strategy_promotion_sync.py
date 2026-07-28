"""Contract tests for immutable strategy-promotion state synchronization."""

import json
import os
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Barrier, Event
from types import SimpleNamespace

import pytest

from tradingagents.execution.authorized_normal_trade_intent import (
    AuthorizedNormalTradeIntent,
)
from tradingagents.orchestration import self_heal as self_heal_module
from tradingagents.policy import strategy_promotion_sync as sync_module
from tradingagents.policy.strategy_promotion_sync import (
    StrategyPromotionSyncPrepare,
    StrategyPromotionSyncReceipt,
)

_ISOLATED_SOURCE_TAMPER_ENV = "TRADINGAGENTS_ISOLATED_SOURCE_TAMPER"
_ISOLATED_SOURCE_TAMPER_READY_ENV = "TRADINGAGENTS_ISOLATED_SOURCE_TAMPER_READY"
_ISOLATED_SOURCE_TAMPER_CONTINUE_ENV = "TRADINGAGENTS_ISOLATED_SOURCE_TAMPER_CONTINUE"
_CAPPED_ACTIVATION_ISOLATED_ENV = "TRADINGAGENTS_CAPPED_ACTIVATION_ISOLATED"


def _normal_live_intent(
    proposal: object,
    *,
    state_sha256: str,
    receipt_id: str,
    receipt_sha256: str,
    recorded_at: str = "2030-03-22T16:05:00+00:00",
    expires_at: str = "2030-03-22T16:10:00+00:00",
    staged_intent: object | None = None,
    overrides: dict[str, object] | None = None,
) -> AuthorizedNormalTradeIntent:
    """Make a Task 2 intent bound to the real Task 6D test journal."""

    import hashlib
    import json

    payload: dict[str, object] = {
        "promotion_proposal_id": proposal.proposal_id,
        "promotion_proposal_sha256": sync_module._digest(
            proposal.canonical_json_bytes()
        ),
        "promotion_state_sha256": state_sha256,
        "promotion_sync_receipt_id": receipt_id,
        "promotion_sync_receipt_sha256": receipt_sha256,
        "staged_intent_id": "staged-live-intent-" + "1" * 64,
        "staged_intent_sha256": "2" * 64,
        "shadow_attestation_sha256": proposal.shadow_attestation_sha256,
        "genome_id": proposal.genome_id,
        "genome_canonical_sha256": proposal.genome_canonical_sha256,
        "evaluation_code_commit": proposal.evaluation_code_commit,
        "evaluation_runtime_sha256": proposal.evaluation_runtime_sha256,
        "market_observation_sha256": "3" * 64,
        "portfolio_snapshot_sha256": "4" * 64,
        "risk_snapshot_sha256": proposal.risk_attestation.risk_envelope_sha256,
        "symbol": "MSFT",
        "side": "buy",
        "order_type": "limit",
        "tif": "day",
        "notional_usd": "1.00",
        "limit_price": "100.00",
        "effective_at": recorded_at,
        "expires_at": expires_at,
        "recorded_at": recorded_at,
    }
    def canonical(value: object) -> bytes:
        return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    if staged_intent is not None:
        decision = staged_intent.decision
        assert decision.action.value == "buy"
        assert decision.symbol is not None
        assert decision.notional_usd is not None
        assert decision.limit_price is not None
        payload.update(
            {
                "staged_intent_id": staged_intent.staged_intent_id,
                "staged_intent_sha256": sync_module._digest(
                    staged_intent.canonical_json_bytes()
                ),
                "market_observation_sha256": staged_intent.observations_sha256,
                "portfolio_snapshot_sha256": staged_intent.candidate_state_sha256,
                "symbol": decision.symbol,
                "notional_usd": decision.notional_usd,
                "limit_price": decision.limit_price,
            }
        )
    if overrides is not None:
        payload.update(overrides)
    logical_order_sha256 = hashlib.sha256(canonical(payload)).hexdigest()
    payload["logical_order_sha256"] = logical_order_sha256
    payload["client_order_id"] = f"ta-l-{logical_order_sha256[:40]}"
    bound = {
        **payload,
        "owner_role": "portfolio_executive",
        "authorization_scope": "single_alpaca_live_order",
        "live_submit_authorized": True,
        "paper_submit_authorized": False,
    }
    bound["authorization_id"] = (
        "authorized-normal-trade-intent-"
        + hashlib.sha256(canonical(bound)).hexdigest()
    )
    return AuthorizedNormalTradeIntent.from_dict(bound)


def _complete_normal_live_intent(
    *,
    root: Path,
    repo_root: Path,
    proposal: object,
    state_sha256: str,
    receipt_id: str,
    receipt_sha256: str,
    recorded_at: str,
    expires_at: str,
    overrides: dict[str, object] | None = None,
) -> AuthorizedNormalTradeIntent:
    """Bind Task 2 material to a durable staged paper decision."""

    from tradingagents.strategy.staged_intent import StrategyStagedIntentLedger

    candidates = [
        staged
        for staged in StrategyStagedIntentLedger(root, repo_root=repo_root).rebuild()
        if (
            staged.promotion_evidence_id == proposal.promotion_evidence_id
            and staged.genome.genome_id == proposal.genome_id
            and staged.decision.action.value == "buy"
        )
    ]
    assert candidates
    staged = max(candidates, key=lambda item: item.effective_at)
    return _normal_live_intent(
        proposal,
        state_sha256=state_sha256,
        receipt_id=receipt_id,
        receipt_sha256=receipt_sha256,
        recorded_at=recorded_at,
        expires_at=expires_at,
        staged_intent=staged,
        overrides=overrides,
    )


def _copy_isolated_source_tamper_repo(tmp_path: Path) -> Path:
    """Create a disposable Git checkout whose loaded sources are its own files."""

    source_root = Path(__file__).parents[1]
    isolated_root = tmp_path / "isolated-source-tamper-repo"

    def ignore_ephemera(_directory: str, names: list[str]) -> set[str]:
        return {
            name
            for name in names
            if name in {".git", ".venv", ".pytest_cache", "__pycache__", "results"}
            or name.endswith(".pyc")
        }

    for name in ("tradingagents", "tests", "config"):
        shutil.copytree(
            source_root / name,
            isolated_root / name,
            ignore=ignore_ephemera,
        )
    for name in ("pyproject.toml",):
        shutil.copy2(source_root / name, isolated_root / name)

    for command in (
        ("git", "init", "-q"),
        ("git", "config", "user.email", "test@example.invalid"),
        ("git", "config", "user.name", "isolated source tamper test"),
        ("git", "add", "tradingagents", "tests", "config", "pyproject.toml"),
        ("git", "commit", "-qm", "isolated source tamper fixture"),
    ):
        subprocess.run(command, cwd=isolated_root, check=True)
    return isolated_root


def _wait_for_isolated_source_tamper(path: Path, process: subprocess.Popen[str]) -> None:
    deadline = time.monotonic() + 30
    while not path.exists():
        if process.poll() is not None:
            output, errors = process.communicate()
            pytest.fail(
                "isolated source-tamper process exited before its readiness signal:\n"
                f"stdout:\n{output}\nstderr:\n{errors}"
            )
        if time.monotonic() >= deadline:
            process.kill()
            output, errors = process.communicate()
            pytest.fail(
                "isolated source-tamper process did not reach its readiness signal:\n"
                f"stdout:\n{output}\nstderr:\n{errors}"
            )
        time.sleep(0.01)


def _run_source_tamper_in_isolated_repo(tmp_path: Path) -> None:
    """Exercise real source drift beside an independent shared-repo manifest read."""

    from tradingagents.strategy.promotion_evidence import (
        EVALUATION_SOURCE_PATHS,
        build_evaluation_source_manifest,
    )

    source_root = Path(__file__).parents[1]
    source_before = {
        relative: (source_root / relative).read_bytes()
        for relative in EVALUATION_SOURCE_PATHS
    }
    isolated_root = _copy_isolated_source_tamper_repo(tmp_path)
    ready = tmp_path / "isolated-source-tamper.ready"
    continue_path = tmp_path / "isolated-source-tamper.continue"
    environment = {
        **os.environ,
        _ISOLATED_SOURCE_TAMPER_ENV: "1",
        _ISOLATED_SOURCE_TAMPER_READY_ENV: str(ready),
        _ISOLATED_SOURCE_TAMPER_CONTINUE_ENV: str(continue_path),
        "PYTHONPATH": os.pathsep.join(
            part
            for part in (str(isolated_root), os.environ.get("PYTHONPATH", ""))
            if part
        ),
    }
    process = subprocess.Popen(
        (
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "tests/test_strategy_promotion_sync.py::"
            "test_real_immutable_source_tamper_refuses_without_new_state_or_event"
            "[active_manifest_source]",
        ),
        cwd=isolated_root,
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    _wait_for_isolated_source_tamper(ready, process)
    active = build_evaluation_source_manifest(source_root)
    assert tuple(item.path for item in active.files) == EVALUATION_SOURCE_PATHS
    assert {
        relative: (source_root / relative).read_bytes()
        for relative in EVALUATION_SOURCE_PATHS
    } == source_before
    continue_path.write_text("continue\n", encoding="utf-8")
    output, errors = process.communicate(timeout=60)
    assert process.returncode == 0, f"stdout:\n{output}\nstderr:\n{errors}"
    assert {
        relative: (source_root / relative).read_bytes()
        for relative in EVALUATION_SOURCE_PATHS
    } == source_before


def _run_capped_activation_in_isolated_repo(tmp_path: Path, nodeid: str) -> None:
    """Run the positive activation chain where loaded sources match its repo."""

    isolated = _copy_isolated_source_tamper_repo(tmp_path)
    subprocess.run(
        ("git", "config", "status.showUntrackedFiles", "no"),
        cwd=isolated,
        check=True,
    )
    environment = {
        **os.environ,
        _CAPPED_ACTIVATION_ISOLATED_ENV: "1",
        "PYTHONPATH": os.pathsep.join(
            part for part in (str(isolated), os.environ.get("PYTHONPATH", "")) if part
        ),
    }
    result = subprocess.run(
        (sys.executable, "-m", "pytest", "-q", nodeid),
        cwd=isolated,
        env=environment,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, (
        f"isolated activation fixture failed:\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )


def _controlled_proposal() -> tuple[object, str]:
    digest = "a" * 64
    validation = SimpleNamespace(
        report_ref="report.json",
        report_sha256=sync_module._digest(b"report"),
        completed_at="2026-07-28T12:00:00+00:00",
    )
    risk_attestation = SimpleNamespace(
        risk_envelope_ref="risk.yaml",
        risk_envelope_sha256=sync_module._digest(b"risk"),
        live_budget_mode="fixed_tranche",
        account_hard_ceiling_usd=None,
        new_sleeve_auto_promote=True,
        reviewed_at="2026-07-28T12:00:00+00:00",
        account_max_capital_at_risk_usd="100",
        per_name_cap_usd="100",
        tiny_live_tranche_usd="1",
    )
    Proposal = type("Proposal", (), {})
    proposal = Proposal()
    proposal_values = {
        "proposal_id": "strategy-promotion-proposal-" + digest,
        "sleeve": "sleeve",
        "proposed_stage": "tiny_live_eligible",
        "effective_at": "2026-07-28T11:59:00+00:00",
        "recorded_at": "2026-07-28T11:59:00+00:00",
        "expires_at": "2026-07-28T12:05:00+00:00",
        "validation_attestation": validation,
        "risk_attestation": risk_attestation,
        "evaluation_runtime_sha256": digest,
        "promotion_runtime_commit": "b" * 40,
        "registration_id": "r",
        "promotion_evidence_id": "p",
        "promotion_evidence_sha256": digest,
        "shadow_attestation_id": "s",
        "shadow_attestation_sha256": digest,
        "validation_attestation_sha256": digest,
        "risk_attestation_sha256": digest,
        "genome_id": "g",
        "genome_canonical_sha256": digest,
        "evaluation_code_commit": "c" * 40,
        "benchmark_excess_return_fraction": "0.1",
        "cost_adjusted_alpha_fraction": "0.1",
        "recent_alpha_fraction": "0.1",
        "capacity_usd": "100",
        "requested_tiny_live_tranche_usd": "1",
        "gates": (
            ("ci_green", True),
            ("shadow_sessions_sufficient", True),
            ("reconciliation_confirmed", True),
            ("capacity_gate_passed", True),
            ("risk_budget_mode_capped", True),
            ("risk_auto_promotion_allowed", True),
        ),
        "issues": (),
    }
    for name, value in proposal_values.items():
        setattr(proposal, name, value)
    proposal.canonical_json_bytes = lambda: b"proposal"
    return proposal, digest


def _real_immutable_journal(tmp_path: Path, monkeypatch):
    """Build one current, immutable paper-only 6D evidence chain.

    This intentionally uses the public ledgers rather than a sync seam.  The
    existing durable BUY helper cannot be used because its March promotion
    evidence is stale at its April paper observation.
    """
    import tradingagents.policy.strategy_promotion as promotion_module
    import tradingagents.strategy.promotion_evidence as evidence_module
    from tests.test_strategy_paper_execution_authorization import _authorize_once
    from tests.test_strategy_shadow_attestation import _receipt_pair_for_authorization
    from tests.test_strategy_staged_intent import (
        REPO_ROOT,
        UTC,
        _durable_internal_evidence,
        _stage_with_times,
    )
    from tradingagents.orchestration.authority import ActionClass, authority_for
    from tradingagents.policy.strategy_promotion import (
        REQUIRED_STRATEGY_PROMOTION_VALIDATION_COMMANDS,
        StrategyOperationalPromotionLedger,
        build_risk_attestation,
        build_validation_attestation,
    )
    from tradingagents.strategy.shadow_attestation import StrategyShadowEvidenceLedger

    original_git_text = evidence_module._git_text

    def clean_loaded_checkout(repo: Path, *args: str) -> str:
        if repo.resolve() == REPO_ROOT.resolve() and args == ("status", "--porcelain"):
            return ""
        return original_git_text(repo, *args)

    monkeypatch.setattr(evidence_module, "_git_text", clean_loaded_checkout)
    root, registration, promotion = _durable_internal_evidence(tmp_path)
    base = datetime(2030, 3, 22, 16, 3, tzinfo=UTC)
    _, staged = _stage_with_times(
        root,
        registration,
        promotion,
        clock_time=base + timedelta(seconds=5),
        effective_at=base,
        expires_at=base + timedelta(minutes=10),
        session_date="2030-03-22",
    )
    _, authorization = _authorize_once(
        root,
        staged,
        clock_time=base + timedelta(minutes=1, seconds=5),
        effective_at=base + timedelta(minutes=1),
        expires_at=base + timedelta(minutes=9),
    )
    receipt, reconciliation = _receipt_pair_for_authorization(
        authorization,
        submitted_at="2030-03-22T16:04:05+00:00",
        last_seen_at="2030-03-22T16:05:00+00:00",
        checked_at="2030-03-22T16:05:00+00:00",
    )
    shadow_ledger = StrategyShadowEvidenceLedger(
        root,
        repo_root=REPO_ROOT,
        clock=lambda: base + timedelta(minutes=3, seconds=5),
    )
    observation = shadow_ledger.admit_observation(
        staged_intent=staged,
        authorization=authorization,
        observed_at=base + timedelta(minutes=2),
        paper_order_receipt=receipt,
        reconciliation_receipt=reconciliation,
        actor_role="integrity_verifier",
    )
    shadow = shadow_ledger.assemble(
        promotion_evidence=promotion,
        observations=(observation,),
        actor_role="integrity_verifier",
    )

    original_promotion_git = promotion_module._git
    commit = original_promotion_git(REPO_ROOT, "rev-parse", "HEAD")

    def clean_promotion_checkout(_repo: Path, *args: str) -> str:
        if args == ("rev-parse", "HEAD"):
            return commit
        if args == ("status", "--porcelain"):
            return ""
        return original_promotion_git(_repo, *args)

    monkeypatch.setattr(promotion_module, "_git", clean_promotion_checkout)
    attested_at = base + timedelta(minutes=4)
    validation = build_validation_attestation(
        repo_root=REPO_ROOT,
        tested_commit=commit,
        completed_at=attested_at,
        commands=REQUIRED_STRATEGY_PROMOTION_VALIDATION_COMMANDS,
        exit_code=0,
        report_ref="config/strategy_evaluation.json",
        verifier_role=authority_for(ActionClass.VERIFY).owner_role,
        clock=lambda: attested_at,
    )
    risk = build_risk_attestation(
        repo_root=REPO_ROOT,
        risk_envelope_ref="config/risk_envelope.example.yaml",
        reviewed_at=attested_at,
        reviewer_role=authority_for(ActionClass.RISK_CHANGE).owner_role,
        clock=lambda: attested_at,
    )
    proposal = StrategyOperationalPromotionLedger(
        root,
        clock=lambda: base + timedelta(minutes=4, seconds=1),
    ).propose(
        promotion_evidence=promotion,
        shadow_attestation=shadow,
        validation_attestation=validation,
        risk_attestation=risk,
        effective_at=attested_at,
        expires_at=base + timedelta(minutes=19),
    )
    return root, REPO_ROOT, proposal, base + timedelta(minutes=4, seconds=30), commit


def _capped_activation_journal(tmp_path: Path, monkeypatch):
    """Build a disposable complete chain with the explicit capped opt-in on."""

    import tradingagents.policy.strategy_promotion as promotion_module
    from tests.test_strategy_paper_execution_authorization import _authorize_once
    from tests.test_strategy_shadow_attestation import _receipt_pair_for_authorization
    from tests.test_strategy_staged_intent import REPO_ROOT, _stage_with_times
    from tradingagents.orchestration.authority import ActionClass, authority_for
    from tradingagents.policy.strategy_promotion import (
        REQUIRED_STRATEGY_PROMOTION_VALIDATION_COMMANDS,
        StrategyOperationalPromotionLedger,
        build_risk_attestation,
        build_validation_attestation,
    )
    from tradingagents.strategy._immutable_evidence_store import (
        ImmutableStrategyEvidenceStore,
    )
    from tradingagents.strategy.promotion_evidence import (
        StrategyEvaluationRegistration,
        StrategyPromotionEvidence,
    )
    from tradingagents.strategy.shadow_attestation import StrategyShadowEvidenceLedger

    root, _repo_root, prior, synced_at, _commit = _real_immutable_journal(
        tmp_path, monkeypatch
    )

    def actual_git(repo: Path, *args: str) -> str:
        return subprocess.run(
            ("git", *args),
            cwd=repo,
            check=True,
            text=True,
            capture_output=True,
        ).stdout.strip()

    monkeypatch.setattr(promotion_module, "_git", actual_git)
    monkeypatch.setattr(sync_module, "_git", actual_git)
    isolated = (
        Path(__file__).parents[1]
        if os.environ.get(_CAPPED_ACTIVATION_ISOLATED_ENV) == "1"
        else _copy_isolated_source_tamper_repo(tmp_path)
    )
    envelope = isolated / "config" / "risk_envelope.example.yaml"
    envelope.write_text(
        envelope.read_text(encoding="utf-8").replace(
            "new_sleeve_auto_promote: false", "new_sleeve_auto_promote: true"
        ),
        encoding="utf-8",
    )
    for command in (
        ("git", "add", "config/risk_envelope.example.yaml"),
        ("git", "commit", "-qm", "enable capped activation fixture"),
    ):
        subprocess.run(command, cwd=isolated, check=True)
    commit = subprocess.check_output(
        ("git", "rev-parse", "HEAD"), cwd=isolated, text=True
    ).strip()
    snapshot = ImmutableStrategyEvidenceStore(root).rebuild()
    promotion = StrategyPromotionEvidence.from_envelope(
        next(item for item in snapshot if item.object_id == prior.promotion_evidence_id)
    )
    registration = StrategyEvaluationRegistration.from_envelope(
        next(item for item in snapshot if item.object_id == prior.registration_id)
    )
    observations = []
    for day in range(1, 6):
        session_at = synced_at + timedelta(days=day)
        _ledger, staged = _stage_with_times(
            root,
            registration,
            promotion,
            clock_time=session_at + timedelta(seconds=5),
            effective_at=session_at,
            expires_at=session_at + timedelta(minutes=10),
            session_date=session_at.date().isoformat(),
        )
        _auth_ledger, authorization = _authorize_once(
            root,
            staged,
            clock_time=session_at + timedelta(minutes=1, seconds=5),
            effective_at=session_at + timedelta(minutes=1),
            expires_at=session_at + timedelta(minutes=9),
        )
        order_receipt, reconciliation = _receipt_pair_for_authorization(
            authorization,
            submitted_at=(session_at + timedelta(minutes=2)).isoformat(),
            last_seen_at=(session_at + timedelta(minutes=3)).isoformat(),
            checked_at=(session_at + timedelta(minutes=3)).isoformat(),
            broker_order_id=f"paper-capped-activation-{day}",
        )
        observation_ledger = StrategyShadowEvidenceLedger(
            root, repo_root=REPO_ROOT,
            clock=lambda session_at=session_at: session_at + timedelta(minutes=3),
        )
        observations.append(
            observation_ledger.admit_observation(
                staged_intent=staged,
                authorization=authorization,
                observed_at=session_at + timedelta(minutes=3),
                paper_order_receipt=order_receipt,
                reconciliation_receipt=reconciliation,
                actor_role="integrity_verifier",
            )
        )
    shadow = StrategyShadowEvidenceLedger(
        root, repo_root=REPO_ROOT,
        clock=lambda: synced_at + timedelta(days=5, minutes=4),
    ).assemble(
        promotion_evidence=promotion,
        observations=observations,
        actor_role="integrity_verifier",
    )
    attested_at = synced_at + timedelta(days=5, minutes=5)
    validation = build_validation_attestation(
        repo_root=isolated,
        tested_commit=commit,
        completed_at=attested_at,
        commands=REQUIRED_STRATEGY_PROMOTION_VALIDATION_COMMANDS,
        exit_code=0,
        report_ref="config/strategy_evaluation.json",
        verifier_role=authority_for(ActionClass.VERIFY).owner_role,
        clock=lambda: attested_at,
    )
    risk = build_risk_attestation(
        repo_root=isolated,
        risk_envelope_ref="config/risk_envelope.example.yaml",
        reviewed_at=attested_at,
        reviewer_role=authority_for(ActionClass.RISK_CHANGE).owner_role,
        clock=lambda: attested_at,
    )
    proposal = StrategyOperationalPromotionLedger(root, clock=lambda: attested_at).propose(
        promotion_evidence=promotion,
        shadow_attestation=shadow,
        validation_attestation=validation,
        risk_attestation=risk,
        effective_at=attested_at,
        expires_at=attested_at + timedelta(minutes=10),
    )
    assert proposal.proposed_stage == "tiny_live_eligible", proposal.gates
    return root, isolated, proposal, attested_at + timedelta(seconds=30), commit


def test_real_immutable_journal_recomputes_before_sync_prepare(tmp_path, monkeypatch) -> None:
    """A genuine current evidence chain reaches the non-duck-typed recompute path."""
    root, repo_root, proposal, synced_at, commit = _real_immutable_journal(
        tmp_path, monkeypatch
    )
    state = tmp_path / "promotion.json"
    before = b'{"sleeves":{}}'
    state.write_bytes(before)
    events_before = (root / "events.jsonl").read_bytes()

    monkeypatch.setattr(
        sync_module,
        "_git",
        lambda _root, *args: commit if args == ("rev-parse", "HEAD") else "",
    )
    result = sync_module.sync_strategy_promotion_state_file(
        proposal_ledger_root=root,
        repo_root=repo_root,
        proposal=proposal,
        state_path=state,
        expected_current_state_sha256=sync_module._digest(before),
        actor_role="strategy_learning",
        clock=lambda: synced_at,
    )

    assert result.created is True
    sleeve_record = result.state["sleeves"][proposal.sleeve]
    assert sleeve_record["live_enabled"] is False
    assert self_heal_module._valid_promotion_sleeve_record(
        sleeve_record,
        symbol=proposal.sleeve,
    ), sleeve_record
    assert (root / "events.jsonl").read_bytes() != events_before


def test_real_immutable_clean_unrelated_head_advance_with_bound_manifest_is_allowed(
    tmp_path,
    monkeypatch,
) -> None:
    """A clean descendant checkout is not drift when the five source bytes bind."""
    root, repo_root, proposal, synced_at, _commit = _real_immutable_journal(
        tmp_path, monkeypatch
    )
    state = tmp_path / "promotion.json"
    before = b'{"sleeves":{}}'
    state.write_bytes(before)
    original_git = sync_module._git
    descendant = "d" * 40

    def clean_descendant_checkout(repo: Path, *args: str) -> str:
        if args == ("rev-parse", "HEAD"):
            return descendant
        if args == ("status", "--porcelain"):
            return ""
        if args == (
            "merge-base",
            "--is-ancestor",
            proposal.promotion_runtime_commit,
            descendant,
        ):
            return ""
        if args == (
            "diff",
            "--name-only",
            "-z",
            "--no-renames",
            f"{proposal.promotion_runtime_commit}..{descendant}",
        ):
            return "README.md\0"
        return original_git(repo, *args)

    monkeypatch.setattr(sync_module, "_git", clean_descendant_checkout)

    result = sync_module.sync_strategy_promotion_state_file(
        proposal_ledger_root=root,
        repo_root=repo_root,
        proposal=proposal,
        state_path=state,
        expected_current_state_sha256=sync_module._digest(before),
        actor_role="strategy_learning",
        clock=lambda: synced_at,
    )

    assert result.state["sleeves"][proposal.sleeve]["live_enabled"] is False
    assert state.read_bytes() != before


@pytest.mark.parametrize(
    "changed_paths",
    (
        ("README.md",),
        ("docs/promotion-notes.md", "tests/test_strategy_promotion_sync.py"),
    ),
)
def test_clean_runtime_descendant_allows_only_non_runtime_paths(
    tmp_path,
    monkeypatch,
    changed_paths,
) -> None:
    """A clean descendant may advance only outside runtime and config inputs."""
    attested = "a" * 40
    head = "b" * 40
    calls: list[tuple[str, ...]] = []

    def clean_descendant_git(_repo: Path, *args: str) -> str:
        calls.append(args)
        if args == ("rev-parse", "HEAD"):
            return head
        if args == ("status", "--porcelain"):
            return ""
        if args == ("merge-base", "--is-ancestor", attested, head):
            return ""
        if args == ("diff", "--name-only", "-z", "--no-renames", f"{attested}..{head}"):
            return "\0".join((*changed_paths, ""))
        pytest.fail(f"unexpected Git command: {args!r}")

    monkeypatch.setattr(sync_module, "_git", clean_descendant_git)

    sync_module._require_clean_runtime_descendant(tmp_path, attested)

    assert ("diff", "--name-only", "-z", "--no-renames", f"{attested}..{head}") in calls


@pytest.mark.parametrize(
    "changed_path",
    (
        "tradingagents/policy/strategy_promotion.py",
        "tradingagents/policy/strategy_promotion_sync.py",
        "tradingagents/orchestration/self_heal.py",
        "tradingagents/strategy/promotion_evidence.py",
        "config/risk/live_caps.yaml",
        "cli/main.py",
        "scripts/automation_context_snapshot.py",
        "pyproject.toml",
    ),
)
def test_new_prepare_refuses_clean_descendant_runtime_or_config_change_before_event(
    tmp_path,
    monkeypatch,
    changed_path,
) -> None:
    """Protected clean-head drift cannot create state or a durable prepare."""
    state = tmp_path / "promotion.json"
    preimage = b'{"sleeves":{}}'
    state.write_bytes(preimage)
    (tmp_path / "report.json").write_text("report")
    (tmp_path / "risk.yaml").write_text("risk")
    proposal, _digest = _controlled_proposal()
    Proposal = type(proposal)
    monkeypatch.setattr(sync_module, "StrategyPromotionProposal", Proposal)

    class Store:
        def envelopes(self, *, kind):
            assert kind == sync_module.STRATEGY_PROMOTION_SYNC_PREPARE_KIND
            return ()

        def admit_checked(self, *_args, **_kwargs):
            pytest.fail("protected runtime drift must not admit a prepare")

    monkeypatch.setattr(
        sync_module,
        "StrategyOperationalPromotionLedger",
        lambda *args, **kwargs: SimpleNamespace(rebuild=lambda: (proposal,)),
    )
    monkeypatch.setattr(sync_module, "ImmutableStrategyEvidenceStore", lambda *args, **kwargs: Store())
    descendant = "d" * 40

    def protected_descendant_git(_repo: Path, *args: str) -> str:
        if args == ("rev-parse", "HEAD"):
            return descendant
        if args == ("status", "--porcelain"):
            return ""
        if args == (
            "merge-base",
            "--is-ancestor",
            proposal.promotion_runtime_commit,
            descendant,
        ):
            return ""
        if args == (
            "diff",
            "--name-only",
            "-z",
            "--no-renames",
            f"{proposal.promotion_runtime_commit}..{descendant}",
        ):
            return changed_path + "\0"
        pytest.fail(f"unexpected Git command: {args!r}")

    monkeypatch.setattr(sync_module, "_git", protected_descendant_git)
    monkeypatch.setattr(
        sync_module,
        "_safe_repo_file",
        lambda _root, reference, _label: (tmp_path / reference, str(reference)),
    )

    with pytest.raises(ValueError, match="promotion runtime changed after attestation"):
        sync_module.sync_strategy_promotion_state_file(
            proposal_ledger_root=tmp_path,
            repo_root=tmp_path,
            proposal=proposal,
            state_path=state,
            expected_current_state_sha256=sync_module._digest(preimage),
            actor_role="strategy_learning",
            clock=lambda: datetime(2026, 7, 28, 12, 1, tzinfo=timezone.utc),
        )

    assert state.read_bytes() == preimage


@pytest.mark.parametrize(
    ("attestation_name", "attribute", "unsafe_ref"),
    (
        ("validation", "report_ref", "../outside-validation.json"),
        ("risk", "risk_envelope_ref", "config/../outside-risk.yaml"),
    ),
)
def test_real_journal_propose_refuses_tampered_unsafe_anchor_ref_before_event_write(
    tmp_path,
    monkeypatch,
    attestation_name,
    attribute,
    unsafe_ref,
) -> None:
    """A forged paper attestation ref cannot create another durable proposal."""
    from tradingagents.policy.strategy_promotion import StrategyOperationalPromotionLedger
    from tradingagents.strategy._immutable_evidence_store import ImmutableStrategyEvidenceStore
    from tradingagents.strategy.promotion_evidence import StrategyPromotionEvidence
    from tradingagents.strategy.shadow_attestation import _attestation_from_envelope

    root, _repo_root, proposal, synced_at, _commit = _real_immutable_journal(tmp_path, monkeypatch)
    snapshot = ImmutableStrategyEvidenceStore(root).rebuild()
    promotion = StrategyPromotionEvidence.from_envelope(
        next(item for item in snapshot if item.object_id == proposal.promotion_evidence_id)
    )
    shadow = _attestation_from_envelope(
        next(item for item in snapshot if item.object_id == proposal.shadow_attestation_id)
    )
    attestation = getattr(proposal, f"{attestation_name}_attestation")
    object.__setattr__(attestation, attribute, unsafe_ref)
    events_before = (root / "events.jsonl").read_bytes()

    with pytest.raises(ValueError, match="safe canonical repo-relative"):
        StrategyOperationalPromotionLedger(
            root,
            clock=lambda: synced_at,
        ).propose(
            promotion_evidence=promotion,
            shadow_attestation=shadow,
            validation_attestation=proposal.validation_attestation,
            risk_attestation=proposal.risk_attestation,
            effective_at=synced_at,
            expires_at=datetime.fromisoformat(proposal.expires_at),
        )

    assert (root / "events.jsonl").read_bytes() == events_before


def test_real_shadow_attestation_currentness_is_half_open_at_exact_deadline(
    tmp_path,
    monkeypatch,
) -> None:
    """The actual shadow timestamp is current before, but stale at, its deadline.

    This is deliberately a direct currentness proof rather than an impossible
    active-proposal sync: shadow is derived after promotion evidence and both
    sources have the same seven-day lifetime, so internal evidence expires no
    later than shadow evidence.
    """
    from tradingagents.policy.strategy_promotion import (
        INTERNAL_EVIDENCE_MAX_AGE_SECONDS,
        SHADOW_ATTESTATION_MAX_AGE_SECONDS,
        _current,
    )
    from tradingagents.strategy._immutable_evidence_store import ImmutableStrategyEvidenceStore
    from tradingagents.strategy.promotion_evidence import StrategyPromotionEvidence
    from tradingagents.strategy.shadow_attestation import _attestation_from_envelope

    root, _repo_root, proposal, _synced_at, _commit = _real_immutable_journal(tmp_path, monkeypatch)
    snapshot = ImmutableStrategyEvidenceStore(root).rebuild()
    promotion = StrategyPromotionEvidence.from_envelope(
        next(item for item in snapshot if item.object_id == proposal.promotion_evidence_id)
    )
    shadow = _attestation_from_envelope(
        next(item for item in snapshot if item.object_id == proposal.shadow_attestation_id)
    )
    shadow_start = datetime.fromisoformat(shadow.effective_at)
    shadow_deadline = shadow_start + timedelta(seconds=SHADOW_ATTESTATION_MAX_AGE_SECONDS)
    internal_deadline = datetime.fromisoformat(promotion.effective_at) + timedelta(
        seconds=INTERNAL_EVIDENCE_MAX_AGE_SECONDS
    )

    assert _current(
        shadow.effective_at,
        shadow_deadline - timedelta(seconds=1),
        SHADOW_ATTESTATION_MAX_AGE_SECONDS,
        "shadow attestation",
    )
    assert not _current(
        shadow.effective_at,
        shadow_deadline,
        SHADOW_ATTESTATION_MAX_AGE_SECONDS,
        "shadow attestation",
    )
    assert internal_deadline <= shadow_deadline
    assert datetime.fromisoformat(proposal.expires_at) <= internal_deadline


def test_real_immutable_journal_rejects_risk_deadline_equality_without_mutation(
    tmp_path, monkeypatch
) -> None:
    """The store's real risk attestation is stale at its exact half-open deadline."""
    root, repo_root, proposal, _synced_at, commit = _real_immutable_journal(
        tmp_path, monkeypatch
    )
    state = tmp_path / "promotion.json"
    before = b'{"sleeves":{}}'
    state.write_bytes(before)
    events_before = (root / "events.jsonl").read_bytes()
    risk_deadline = datetime.fromisoformat(proposal.risk_attestation.reviewed_at) + timedelta(
        seconds=sync_module.RISK_ATTESTATION_MAX_AGE_SECONDS
    )
    monkeypatch.setattr(
        sync_module,
        "_git",
        lambda _root, *args: commit if args == ("rev-parse", "HEAD") else "",
    )

    with pytest.raises(ValueError, match="proposal is inactive"):
        sync_module.sync_strategy_promotion_state_file(
            proposal_ledger_root=root,
            repo_root=repo_root,
            proposal=proposal,
            state_path=state,
            expected_current_state_sha256=sync_module._digest(before),
            actor_role="strategy_learning",
            clock=lambda: risk_deadline,
        )

    assert state.read_bytes() == before
    assert (root / "events.jsonl").read_bytes() == events_before


def test_real_immutable_proposal_deadline_stamp_refuses_without_journal_mutation(
    tmp_path,
    monkeypatch,
) -> None:
    """A store stamp at the earliest deadline cannot leave a dead proposal event."""
    from tradingagents.policy.strategy_promotion import StrategyOperationalPromotionLedger
    from tradingagents.strategy.promotion_evidence import StrategyPromotionEvidence
    from tradingagents.strategy.shadow_attestation import _attestation_from_envelope

    root, _repo_root, proposal, _synced_at, _commit = _real_immutable_journal(
        tmp_path, monkeypatch
    )
    events_before = (root / "events.jsonl").read_bytes()
    snapshot = sync_module.ImmutableStrategyEvidenceStore(root).rebuild()
    promotion = StrategyPromotionEvidence.from_envelope(
        next(item for item in snapshot if item.object_id == proposal.promotion_evidence_id)
    )
    shadow = _attestation_from_envelope(
        next(item for item in snapshot if item.object_id == proposal.shadow_attestation_id)
    )
    deadline = datetime.fromisoformat(proposal.risk_attestation.reviewed_at) + timedelta(
        seconds=sync_module.RISK_ATTESTATION_MAX_AGE_SECONDS
    )

    with pytest.raises(ValueError, match="store clock left no active proposal interval"):
        StrategyOperationalPromotionLedger(root, clock=lambda: deadline).propose(
            promotion_evidence=promotion,
            shadow_attestation=shadow,
            validation_attestation=proposal.validation_attestation,
            risk_attestation=proposal.risk_attestation,
            effective_at=datetime.fromisoformat(proposal.effective_at) + timedelta(minutes=1),
            expires_at=deadline,
        )

    assert (root / "events.jsonl").read_bytes() == events_before


def test_real_immutable_risk_deadline_blocks_crash_resume_without_mutation(
    tmp_path,
    monkeypatch,
) -> None:
    """A real prepared replacement may not resume at its risk-source equality."""
    root, repo_root, proposal, synced_at, commit = _real_immutable_journal(
        tmp_path, monkeypatch
    )
    state = tmp_path / "promotion.json"
    before = b'{"sleeves":{}}'
    state.write_bytes(before)
    monkeypatch.setattr(
        sync_module,
        "_git",
        lambda _root, *args: commit if args == ("rev-parse", "HEAD") else "",
    )
    real_writer = sync_module.atomic_write_text
    monkeypatch.setattr(
        sync_module,
        "atomic_write_text",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("injected crash")),
    )

    with pytest.raises(OSError, match="injected crash"):
        sync_module.sync_strategy_promotion_state_file(
            proposal_ledger_root=root,
            repo_root=repo_root,
            proposal=proposal,
            state_path=state,
            expected_current_state_sha256=sync_module._digest(before),
            actor_role="strategy_learning",
            clock=lambda: synced_at,
        )

    events_after_crash = (root / "events.jsonl").read_bytes()
    assert events_after_crash != b""
    assert state.read_bytes() == before
    monkeypatch.setattr(sync_module, "atomic_write_text", real_writer)
    deadline = datetime.fromisoformat(proposal.risk_attestation.reviewed_at) + timedelta(
        seconds=sync_module.RISK_ATTESTATION_MAX_AGE_SECONDS
    )

    with pytest.raises(ValueError, match="prepared promotion state transaction is expired"):
        sync_module.sync_strategy_promotion_state_file(
            proposal_ledger_root=root,
            repo_root=repo_root,
            proposal=proposal,
            state_path=state,
            expected_current_state_sha256=sync_module._digest(before),
            actor_role="strategy_learning",
            clock=lambda: deadline,
        )

    assert state.read_bytes() == before
    assert (root / "events.jsonl").read_bytes() == events_after_crash


def test_real_immutable_validation_deadline_blocks_new_and_crash_resume(
    tmp_path,
    monkeypatch,
) -> None:
    """Validation-deadline equality is stale for both new and prepared syncs."""
    from dataclasses import replace

    from tradingagents.policy.strategy_promotion import StrategyOperationalPromotionLedger
    from tradingagents.strategy.promotion_evidence import StrategyPromotionEvidence
    from tradingagents.strategy.shadow_attestation import _attestation_from_envelope

    root, repo_root, original, synced_at, commit = _real_immutable_journal(
        tmp_path, monkeypatch
    )
    snapshot = sync_module.ImmutableStrategyEvidenceStore(root).rebuild()
    promotion = StrategyPromotionEvidence.from_envelope(
        next(item for item in snapshot if item.object_id == original.promotion_evidence_id)
    )
    shadow = _attestation_from_envelope(
        next(item for item in snapshot if item.object_id == original.shadow_attestation_id)
    )
    deadline = synced_at + timedelta(seconds=1)
    validation = replace(
        original.validation_attestation,
        completed_at=(
            deadline
            - timedelta(seconds=sync_module.VALIDATION_ATTESTATION_MAX_AGE_SECONDS)
        ).isoformat(timespec="seconds"),
    )
    proposal = StrategyOperationalPromotionLedger(root, clock=lambda: synced_at).propose(
        promotion_evidence=promotion,
        shadow_attestation=shadow,
        validation_attestation=validation,
        risk_attestation=original.risk_attestation,
        effective_at=synced_at,
        expires_at=deadline,
    )
    monkeypatch.setattr(
        sync_module,
        "_git",
        lambda _root, *args: commit if args == ("rev-parse", "HEAD") else "",
    )
    new_state = tmp_path / "new-promotion.json"
    before = b'{"sleeves":{}}'
    new_state.write_bytes(before)
    events_before_new = (root / "events.jsonl").read_bytes()

    with pytest.raises(ValueError, match="proposal is inactive"):
        sync_module.sync_strategy_promotion_state_file(
            proposal_ledger_root=root,
            repo_root=repo_root,
            proposal=proposal,
            state_path=new_state,
            expected_current_state_sha256=sync_module._digest(before),
            actor_role="strategy_learning",
            clock=lambda: deadline,
        )

    assert new_state.read_bytes() == before
    assert (root / "events.jsonl").read_bytes() == events_before_new

    resumed_state = tmp_path / "resumed-promotion.json"
    resumed_state.write_bytes(before)
    real_writer = sync_module.atomic_write_text
    monkeypatch.setattr(
        sync_module,
        "atomic_write_text",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("injected crash")),
    )
    with pytest.raises(OSError, match="injected crash"):
        sync_module.sync_strategy_promotion_state_file(
            proposal_ledger_root=root,
            repo_root=repo_root,
            proposal=proposal,
            state_path=resumed_state,
            expected_current_state_sha256=sync_module._digest(before),
            actor_role="strategy_learning",
            clock=lambda: synced_at,
        )
    events_after_crash = (root / "events.jsonl").read_bytes()
    monkeypatch.setattr(sync_module, "atomic_write_text", real_writer)

    with pytest.raises(ValueError, match="prepared promotion state transaction is expired"):
        sync_module.sync_strategy_promotion_state_file(
            proposal_ledger_root=root,
            repo_root=repo_root,
            proposal=proposal,
            state_path=resumed_state,
            expected_current_state_sha256=sync_module._digest(before),
            actor_role="strategy_learning",
            clock=lambda: deadline,
        )

    assert resumed_state.read_bytes() == before
    assert (root / "events.jsonl").read_bytes() == events_after_crash


def test_real_immutable_internal_deadline_blocks_new_and_crash_resume(
    tmp_path,
    monkeypatch,
) -> None:
    """The upstream internal-evidence deadline rejects new and prepared syncs."""
    from dataclasses import replace

    from tradingagents.policy.strategy_promotion import StrategyOperationalPromotionLedger
    from tradingagents.strategy.promotion_evidence import StrategyPromotionEvidence
    from tradingagents.strategy.shadow_attestation import _attestation_from_envelope

    root, repo_root, original, _synced_at, commit = _real_immutable_journal(
        tmp_path, monkeypatch
    )
    snapshot = sync_module.ImmutableStrategyEvidenceStore(root).rebuild()
    promotion = StrategyPromotionEvidence.from_envelope(
        next(item for item in snapshot if item.object_id == original.promotion_evidence_id)
    )
    shadow = _attestation_from_envelope(
        next(item for item in snapshot if item.object_id == original.shadow_attestation_id)
    )
    deadline = datetime.fromisoformat(promotion.effective_at) + timedelta(
        seconds=sync_module.INTERNAL_EVIDENCE_MAX_AGE_SECONDS
    )
    active_at = deadline - timedelta(seconds=1)
    validation = replace(
        original.validation_attestation,
        completed_at=active_at.isoformat(timespec="seconds"),
    )
    risk = replace(
        original.risk_attestation,
        reviewed_at=active_at.isoformat(timespec="seconds"),
    )
    proposal = StrategyOperationalPromotionLedger(root, clock=lambda: active_at).propose(
        promotion_evidence=promotion,
        shadow_attestation=shadow,
        validation_attestation=validation,
        risk_attestation=risk,
        effective_at=active_at,
        expires_at=deadline,
    )
    monkeypatch.setattr(
        sync_module,
        "_git",
        lambda _root, *args: commit if args == ("rev-parse", "HEAD") else "",
    )
    new_state = tmp_path / "new-promotion.json"
    before = b'{"sleeves":{}}'
    new_state.write_bytes(before)
    events_before_new = (root / "events.jsonl").read_bytes()

    with pytest.raises(ValueError, match="proposal is inactive"):
        sync_module.sync_strategy_promotion_state_file(
            proposal_ledger_root=root,
            repo_root=repo_root,
            proposal=proposal,
            state_path=new_state,
            expected_current_state_sha256=sync_module._digest(before),
            actor_role="strategy_learning",
            clock=lambda: deadline,
        )

    assert new_state.read_bytes() == before
    assert (root / "events.jsonl").read_bytes() == events_before_new

    resumed_state = tmp_path / "resumed-promotion.json"
    resumed_state.write_bytes(before)
    real_writer = sync_module.atomic_write_text
    monkeypatch.setattr(
        sync_module,
        "atomic_write_text",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("injected crash")),
    )
    with pytest.raises(OSError, match="injected crash"):
        sync_module.sync_strategy_promotion_state_file(
            proposal_ledger_root=root,
            repo_root=repo_root,
            proposal=proposal,
            state_path=resumed_state,
            expected_current_state_sha256=sync_module._digest(before),
            actor_role="strategy_learning",
            clock=lambda: active_at,
        )
    events_after_crash = (root / "events.jsonl").read_bytes()
    monkeypatch.setattr(sync_module, "atomic_write_text", real_writer)

    with pytest.raises(ValueError, match="prepared promotion state transaction is expired"):
        sync_module.sync_strategy_promotion_state_file(
            proposal_ledger_root=root,
            repo_root=repo_root,
            proposal=proposal,
            state_path=resumed_state,
            expected_current_state_sha256=sync_module._digest(before),
            actor_role="strategy_learning",
            clock=lambda: deadline,
        )

    assert resumed_state.read_bytes() == before
    assert (root / "events.jsonl").read_bytes() == events_after_crash


def test_real_risk_source_auto_promotion_demotion_has_exact_tuple_and_issue(
    tmp_path,
    monkeypatch,
) -> None:
    """A real risk-source result demotes one existing eligible sleeve in place."""

    root, repo_root, original, synced_at, commit = _real_immutable_journal(
        tmp_path, monkeypatch
    )
    state = tmp_path / "promotion.json"
    before = (
        b'{"sleeves":{"current-aggressive":'
        b'{"live_enabled":false,"stage":"tiny_live_eligible"}}}'
    )
    state.write_bytes(before)
    monkeypatch.setattr(
        sync_module,
        "_git",
        lambda _root, *args: commit if args == ("rev-parse", "HEAD") else "",
    )
    result = sync_module.sync_strategy_promotion_state_file(
        proposal_ledger_root=root,
        repo_root=repo_root,
        proposal=original,
        state_path=state,
        expected_current_state_sha256=sync_module._digest(before),
        actor_role="strategy_learning",
        clock=lambda: synced_at,
    )

    assert original.issues == (
        "shadow_sessions_sufficient",
        "reconciliation_confirmed",
        "risk_auto_promotion_disabled",
    )
    assert original.proposed_stage == "paper_only"
    assert result.promoted == ()
    assert result.demoted == (original.sleeve,)
    assert result.unchanged == ()
    assert result.state["sleeves"][original.sleeve]["live_enabled"] is False
    assert result.state["sleeves"][original.sleeve]["issues"] == list(original.issues)


def test_real_validation_source_ci_demotion_has_exact_tuple_and_issue(
    tmp_path,
    monkeypatch,
) -> None:
    """A real nonzero validation attestation adds only the CI demotion cause."""
    from tradingagents.orchestration.authority import ActionClass, authority_for
    from tradingagents.policy.strategy_promotion import (
        REQUIRED_STRATEGY_PROMOTION_VALIDATION_COMMANDS,
        StrategyOperationalPromotionLedger,
        build_validation_attestation,
    )
    from tradingagents.strategy.promotion_evidence import StrategyPromotionEvidence
    from tradingagents.strategy.shadow_attestation import _attestation_from_envelope

    root, repo_root, original, synced_at, commit = _real_immutable_journal(
        tmp_path, monkeypatch
    )
    snapshot = sync_module.ImmutableStrategyEvidenceStore(root).rebuild()
    promotion = StrategyPromotionEvidence.from_envelope(
        next(item for item in snapshot if item.object_id == original.promotion_evidence_id)
    )
    shadow = _attestation_from_envelope(
        next(item for item in snapshot if item.object_id == original.shadow_attestation_id)
    )
    failed_validation = build_validation_attestation(
        repo_root=repo_root,
        tested_commit=commit,
        completed_at=synced_at,
        commands=REQUIRED_STRATEGY_PROMOTION_VALIDATION_COMMANDS,
        exit_code=1,
        report_ref="config/strategy_evaluation.json",
        verifier_role=authority_for(ActionClass.VERIFY).owner_role,
        clock=lambda: synced_at,
    )
    demotion = StrategyOperationalPromotionLedger(root, clock=lambda: synced_at).propose(
        promotion_evidence=promotion,
        shadow_attestation=shadow,
        validation_attestation=failed_validation,
        risk_attestation=original.risk_attestation,
        effective_at=synced_at,
        expires_at=datetime.fromisoformat(original.expires_at),
    )
    state = tmp_path / "promotion.json"
    before = (
        b'{"sleeves":{"current-aggressive":'
        b'{"live_enabled":false,"stage":"tiny_live_eligible"}}}'
    )
    state.write_bytes(before)
    monkeypatch.setattr(
        sync_module,
        "_git",
        lambda _root, *args: commit if args == ("rev-parse", "HEAD") else "",
    )
    result = sync_module.sync_strategy_promotion_state_file(
        proposal_ledger_root=root,
        repo_root=repo_root,
        proposal=demotion,
        state_path=state,
        expected_current_state_sha256=sync_module._digest(before),
        actor_role="strategy_learning",
        clock=lambda: synced_at,
    )

    assert demotion.issues == (
        "ci_green",
        "shadow_sessions_sufficient",
        "reconciliation_confirmed",
        "risk_auto_promotion_disabled",
    )
    assert result.promoted == ()
    assert result.demoted == (demotion.sleeve,)
    assert result.unchanged == ()
    assert result.state["sleeves"][demotion.sleeve]["issues"] == list(demotion.issues)


def test_real_immutable_proposal_ledger_verify_rebuild_and_replay_preserve_cost_alpha(
    tmp_path,
    monkeypatch,
) -> None:
    """Public proposal replay preserves the durable, already-costed evidence value."""
    from tradingagents.policy.strategy_promotion import StrategyOperationalPromotionLedger
    from tradingagents.strategy._immutable_evidence_store import ImmutableStrategyEvidenceStore
    from tradingagents.strategy.promotion_evidence import StrategyPromotionEvidence

    root, _repo_root, proposal, _synced_at, _commit = _real_immutable_journal(
        tmp_path, monkeypatch
    )
    ledger = StrategyOperationalPromotionLedger(root)
    verified = ledger.verify()
    rebuilt = ledger.rebuild()
    assert verified == rebuilt == (proposal,)
    promotion_envelope = next(
        envelope
        for envelope in ImmutableStrategyEvidenceStore(root).rebuild()
        if envelope.object_id == proposal.promotion_evidence_id
    )
    promotion = StrategyPromotionEvidence.from_envelope(promotion_envelope)
    assert proposal.cost_adjusted_alpha_fraction == promotion.pooled_benchmark_excess_fraction
    assert proposal.benchmark_excess_return_fraction == promotion.pooled_benchmark_excess_fraction


def test_real_immutable_proposal_admission_refuses_foreign_store_and_backdating(
    tmp_path,
    monkeypatch,
) -> None:
    """Proposal admission cannot import sources or first-see them in the past."""
    from tradingagents.policy.strategy_promotion import StrategyOperationalPromotionLedger
    from tradingagents.strategy._immutable_evidence_store import (
        EvidenceBackdatingError,
        ImmutableStrategyEvidenceStore,
    )
    from tradingagents.strategy.promotion_evidence import StrategyPromotionEvidence
    from tradingagents.strategy.shadow_attestation import _attestation_from_envelope

    root, _repo_root, proposal, _synced_at, _commit = _real_immutable_journal(
        tmp_path, monkeypatch
    )
    snapshot = ImmutableStrategyEvidenceStore(root).rebuild()
    promotion = StrategyPromotionEvidence.from_envelope(
        next(item for item in snapshot if item.object_id == proposal.promotion_evidence_id)
    )
    shadow = _attestation_from_envelope(
        next(item for item in snapshot if item.object_id == proposal.shadow_attestation_id)
    )
    effective = datetime.fromisoformat(proposal.effective_at)
    expires = datetime.fromisoformat(proposal.expires_at)

    with pytest.raises(ValueError, match="required durable evidence is absent"):
        StrategyOperationalPromotionLedger(tmp_path / "foreign").propose(
            promotion_evidence=promotion,
            shadow_attestation=shadow,
            validation_attestation=proposal.validation_attestation,
            risk_attestation=proposal.risk_attestation,
            effective_at=effective,
            expires_at=expires,
        )
    with pytest.raises(EvidenceBackdatingError):
        StrategyOperationalPromotionLedger(
            root,
            clock=lambda: effective,
        ).propose(
            promotion_evidence=promotion,
            shadow_attestation=shadow,
            validation_attestation=proposal.validation_attestation,
            risk_attestation=proposal.risk_attestation,
            effective_at=effective,
            expires_at=expires,
        )


def test_real_immutable_risk_anchor_drift_refuses_before_state_or_prepare(
    tmp_path,
    monkeypatch,
) -> None:
    """The public sync rejects a changed real risk file, not a mocked checker."""
    root, repo_root, proposal, synced_at, commit = _real_immutable_journal(
        tmp_path, monkeypatch
    )
    state = tmp_path / "promotion.json"
    before = b'{"sleeves":{}}'
    state.write_bytes(before)
    events_before = (root / "events.jsonl").read_bytes()
    risk = repo_root / proposal.risk_attestation.risk_envelope_ref
    original = risk.read_bytes()
    monkeypatch.setattr(
        sync_module,
        "_git",
        lambda _root, *args: commit if args == ("rev-parse", "HEAD") else "",
    )
    try:
        risk.write_bytes(original + b"\n# test-only drift\n")
        with pytest.raises(ValueError, match="external promotion anchor changed"):
            sync_module.sync_strategy_promotion_state_file(
                proposal_ledger_root=root,
                repo_root=repo_root,
                proposal=proposal,
                state_path=state,
                expected_current_state_sha256=sync_module._digest(before),
                actor_role="strategy_learning",
                clock=lambda: synced_at,
            )
    finally:
        risk.write_bytes(original)

    assert state.read_bytes() == before
    assert (root / "events.jsonl").read_bytes() == events_before


@pytest.mark.parametrize(
    "tamper",
    (
        "active_manifest_source",
        "journal_promotion_evidence",
        "journal_shadow_attestation",
        "journal_registration",
    ),
)
def test_real_immutable_source_tamper_refuses_without_new_state_or_event(
    tmp_path,
    monkeypatch,
    tamper,
) -> None:
    """Neither a loaded five-path source nor immutable source journal may drift."""
    from tradingagents.strategy.promotion_evidence import StrategyEvaluationRegistration

    if tamper == "active_manifest_source" and os.environ.get(
        _ISOLATED_SOURCE_TAMPER_ENV
    ) != "1":
        _run_source_tamper_in_isolated_repo(tmp_path)
        return

    root, repo_root, proposal, synced_at, commit = _real_immutable_journal(
        tmp_path, monkeypatch
    )
    state = tmp_path / "promotion.json"
    before = b'{"sleeves":{}}'
    state.write_bytes(before)
    events = root / "events.jsonl"
    events_before = events.read_bytes()
    monkeypatch.setattr(
        sync_module,
        "_git",
        lambda _root, *args: commit if args == ("rev-parse", "HEAD") else "",
    )
    restore_source: Path | None = None
    restore_bytes: bytes | None = None
    if tamper == "active_manifest_source":
        registration = StrategyEvaluationRegistration.from_envelope(
            next(
                envelope
                for envelope in sync_module.ImmutableStrategyEvidenceStore(root).rebuild()
                if envelope.object_id == proposal.registration_id
            )
        )
        source = repo_root / registration.evaluation_source_manifest.files[0].path
        original = source.read_bytes()
        source.write_bytes(original + b"\n# task-4 temporary source drift\n")
        restore_source = source
        restore_bytes = original
        ready_path = os.environ.get(_ISOLATED_SOURCE_TAMPER_READY_ENV)
        continue_path = os.environ.get(_ISOLATED_SOURCE_TAMPER_CONTINUE_ENV)
        if ready_path is not None or continue_path is not None:
            if not ready_path or not continue_path:
                raise ValueError("isolated source-tamper handshake is incomplete")
            Path(ready_path).write_text("ready\n", encoding="utf-8")
            deadline = time.monotonic() + 30
            while not Path(continue_path).exists():
                if time.monotonic() >= deadline:
                    raise TimeoutError("isolated source-tamper handshake timed out")
                time.sleep(0.01)
    else:
        token = {
            "journal_promotion_evidence": b"promotion-evidence",
            "journal_shadow_attestation": b"paper-shadow-attestation",
            "journal_registration": b"evaluation-registration",
        }[tamper]
        changed = events_before.replace(token, token.upper(), 1)
        assert changed != events_before
        events.write_bytes(changed)
    events_before_sync = events.read_bytes()

    try:
        with pytest.raises(ValueError):
            sync_module.sync_strategy_promotion_state_file(
                proposal_ledger_root=root,
                repo_root=repo_root,
                proposal=proposal,
                state_path=state,
                expected_current_state_sha256=sync_module._digest(before),
                actor_role="strategy_learning",
                clock=lambda: synced_at,
            )
    finally:
        if restore_source is not None and restore_bytes is not None:
            restore_source.write_bytes(restore_bytes)

    assert state.read_bytes() == before
    assert events.read_bytes() == events_before_sync


def test_real_immutable_journal_refuses_stale_prior_proposal_without_mutation(
    tmp_path,
    monkeypatch,
) -> None:
    root, repo_root, proposal, synced_at, commit = _real_immutable_journal(
        tmp_path, monkeypatch
    )
    state = tmp_path / "promotion.json"
    initial = b'{"sleeves":{}}'
    state.write_bytes(initial)
    monkeypatch.setattr(
        sync_module,
        "_git",
        lambda _root, *args: commit if args == ("rev-parse", "HEAD") else "",
    )
    first = sync_module.sync_strategy_promotion_state_file(
        proposal_ledger_root=root,
        repo_root=repo_root,
        proposal=proposal,
        state_path=state,
        expected_current_state_sha256=sync_module._digest(initial),
        actor_role="strategy_learning",
        clock=lambda: synced_at,
    )
    state_before = state.read_bytes()
    events_before = (root / "events.jsonl").read_bytes()

    with pytest.raises(ValueError, match="proposal is stale relative to current"):
        sync_module.sync_strategy_promotion_state_file(
            proposal_ledger_root=root,
            repo_root=repo_root,
            proposal=proposal,
            state_path=state,
            expected_current_state_sha256=first.canonical_after_sha256,
            actor_role="strategy_learning",
            clock=lambda: synced_at + timedelta(seconds=1),
        )

    assert state.read_bytes() == state_before
    assert (root / "events.jsonl").read_bytes() == events_before


@pytest.mark.parametrize("preimage_existed", (True, False))
def test_replacement_post_write_mismatch_preserves_preimage(
    tmp_path,
    monkeypatch,
    preimage_existed,
) -> None:
    state = tmp_path / "promotion.json"
    preimage = b'{"sleeves":{}}' if preimage_existed else b""
    if preimage_existed:
        state.write_bytes(preimage)
    report = tmp_path / "report.json"
    report.write_text("report")
    risk = tmp_path / "risk.yaml"
    risk.write_text("risk")
    proposal, digest = _controlled_proposal()
    Proposal = type(proposal)
    monkeypatch.setattr(sync_module, "StrategyPromotionProposal", Proposal)
    monkeypatch.setattr(
        sync_module,
        "StrategyOperationalPromotionLedger",
        lambda *args, **kwargs: SimpleNamespace(rebuild=lambda: (proposal,)),
    )
    monkeypatch.setattr(
        sync_module,
        "_git",
        lambda _root, *args: proposal.promotion_runtime_commit
        if args[0] == "rev-parse"
        else "",
    )
    monkeypatch.setattr(
        sync_module,
        "_safe_repo_file",
        lambda _root, reference, _label: (tmp_path / reference, str(reference)),
    )
    monkeypatch.setattr(
        sync_module,
        "_envelope_object",
        lambda _envelope, _cls: SimpleNamespace(
            sync_prepare_id="strategy-promotion-sync-prepare-" + digest,
            effective_at="2026-07-28T12:00:00+00:00",
            sync_receipt_id="strategy-promotion-sync-receipt-" + digest,
        ),
    )
    monkeypatch.setattr(
        sync_module,
        "ImmutableStrategyEvidenceStore",
        lambda *args, **kwargs: SimpleNamespace(
            envelopes=lambda **kwargs: (),
            admit_checked=lambda *args, **kwargs: SimpleNamespace(
                envelope=object(),
                created=True,
            )
        ),
    )
    original_atomic_write_text = sync_module.atomic_write_text
    original_fsync_parent_directory = sync_module._fsync_parent_directory
    fsynced: list[Path] = []
    writes = 0

    def corrupt_once(path, text):
        nonlocal writes
        writes += 1
        if writes == 1:
            Path(path).write_bytes(b'{"corrupted":true}')
            return Path(path)
        return original_atomic_write_text(path, text)

    monkeypatch.setattr(sync_module, "atomic_write_text", corrupt_once)
    monkeypatch.setattr(
        sync_module,
        "_fsync_parent_directory",
        lambda directory: (
            fsynced.append(Path(directory)),
            original_fsync_parent_directory(Path(directory)),
        )[1],
    )
    with pytest.raises(ValueError, match="replacement digest"):
        sync_module.sync_strategy_promotion_state_file(
            proposal_ledger_root=tmp_path,
            repo_root=tmp_path,
            proposal=proposal,
            state_path=state,
            expected_current_state_sha256=sync_module._digest(preimage),
            actor_role="strategy_learning",
            clock=lambda: datetime(2026, 7, 28, 12, tzinfo=timezone.utc),
        )
    # The guarded writer verifies the staged image before it can exchange the
    # live pathname, so a corrupt staging write needs no destructive rollback.
    assert writes == 1
    if preimage_existed:
        assert state.read_bytes() == preimage
    else:
        assert not state.exists()
        assert fsynced == []
    assert not list(tmp_path.glob(".promotion.json.*.tmp"))


@pytest.mark.parametrize(
    ("recovery_phase", "state_bytes"),
    (
        ("normal-sync", b'{"sleeves":{}}'),
        ("crash-before-replace-resume", b'{"sleeves":{}}'),
        ("receipt-only-repair", b'{"sleeves":{"sleeve":{}}}'),
    ),
)
def test_sync_refuses_symlink_state_path_before_any_recovery_phase_mutates(
    tmp_path,
    monkeypatch,
    recovery_phase,
    state_bytes,
) -> None:
    """A state-file symlink must never split lock, prepare, and replacement paths."""
    target = tmp_path / f"{recovery_phase}-target.json"
    target.write_bytes(state_bytes)
    state_link = tmp_path / f"{recovery_phase}-state.json"
    state_link.symlink_to(target)
    proposal, _digest = _controlled_proposal()
    Proposal = type(proposal)
    constructor_calls: list[str] = []

    monkeypatch.setattr(sync_module, "StrategyPromotionProposal", Proposal)
    monkeypatch.setattr(
        sync_module,
        "StrategyOperationalPromotionLedger",
        lambda *args, **kwargs: (
            constructor_calls.append("ledger"),
            pytest.fail("symlink state path must fail before durable proposal lookup"),
        )[1],
    )
    monkeypatch.setattr(
        sync_module,
        "ImmutableStrategyEvidenceStore",
        lambda *args, **kwargs: (
            constructor_calls.append("store"),
            pytest.fail("symlink state path must fail before evidence access"),
        )[1],
    )

    with pytest.raises(ValueError, match="symlink state path"):
        sync_module.sync_strategy_promotion_state_file(
            proposal_ledger_root=tmp_path,
            repo_root=tmp_path,
            proposal=proposal,
            state_path=state_link,
            expected_current_state_sha256=sync_module._digest(state_bytes),
            actor_role="strategy_learning",
            clock=lambda: datetime(2026, 7, 28, 12, tzinfo=timezone.utc),
        )

    assert constructor_calls == []
    assert state_link.is_symlink()
    assert target.read_bytes() == state_bytes


def test_sync_rejects_symlinked_parent_before_lock_or_evidence_access(
    tmp_path,
    monkeypatch,
) -> None:
    """The state parent itself must be a real directory before any side effect."""
    actual_parent = tmp_path / "actual-state-parent"
    actual_parent.mkdir()
    linked_parent = tmp_path / "linked-state-parent"
    linked_parent.symlink_to(actual_parent, target_is_directory=True)
    state = linked_parent / "promotion.json"
    state_bytes = b'{"sleeves":{}}'
    (actual_parent / state.name).write_bytes(state_bytes)
    proposal, _digest = _controlled_proposal()
    Proposal = type(proposal)
    calls: list[str] = []

    monkeypatch.setattr(sync_module, "StrategyPromotionProposal", Proposal)
    monkeypatch.setattr(
        sync_module,
        "promotion_state_lock",
        lambda *_args, **_kwargs: pytest.fail(
            "symlinked state parent must fail before lock acquisition"
        ),
    )
    monkeypatch.setattr(
        sync_module,
        "ImmutableStrategyEvidenceStore",
        lambda *_args, **_kwargs: (
            calls.append("store"),
            pytest.fail("symlinked state parent must fail before evidence access"),
        )[1],
    )
    monkeypatch.setattr(
        sync_module,
        "StrategyOperationalPromotionLedger",
        lambda *_args, **_kwargs: (
            calls.append("ledger"),
            pytest.fail("symlinked state parent must fail before durable lookup"),
        )[1],
    )

    with pytest.raises(ValueError, match="symlink state parent"):
        sync_module.sync_strategy_promotion_state_file(
            proposal_ledger_root=tmp_path,
            repo_root=tmp_path,
            proposal=proposal,
            state_path=state,
            expected_current_state_sha256=sync_module._digest(state_bytes),
            actor_role="strategy_learning",
            clock=lambda: datetime(2026, 7, 28, 12, tzinfo=timezone.utc),
        )

    assert calls == []
    assert linked_parent.is_symlink()
    assert (actual_parent / state.name).read_bytes() == state_bytes


@pytest.mark.parametrize(
    "recovery_phase",
    ("normal-sync", "crash-before-replace-resume", "receipt-only-repair"),
)
def test_sync_refuses_parent_swap_after_lock_before_any_recovery_phase_binds_target(
    tmp_path,
    monkeypatch,
    recovery_phase,
) -> None:
    """A post-lock parent replacement cannot redirect any evidence or state path.

    The entry path is a real directory.  The lock seam then moves it aside and
    replaces its name with a symlink, which must stop every recovery phase
    before it can look up, prepare, or receipt a transaction against the new
    target.
    """
    parent = tmp_path / f"{recovery_phase}-state-parent"
    parent.mkdir()
    state = parent / "promotion.json"
    original_state = b'{"sleeves":{}}'
    state.write_bytes(original_state)
    redirected_parent = tmp_path / f"{recovery_phase}-redirected-parent"
    redirected_parent.mkdir()
    redirected_state = redirected_parent / state.name
    redirected_bytes = b'{"target":"must-not-change"}'
    redirected_state.write_bytes(redirected_bytes)
    parked_parent = tmp_path / f"{recovery_phase}-parked-parent"
    proposal, _digest = _controlled_proposal()
    Proposal = type(proposal)
    candidates: list[object] = []
    original_lock = sync_module.promotion_state_lock

    @contextmanager
    def swap_parent_after_lock(path):
        with original_lock(path):
            parent.rename(parked_parent)
            parent.symlink_to(redirected_parent, target_is_directory=True)
            yield

    class Store:
        def envelopes(self, **_kwargs):
            return ()

        def admit_checked(self, candidate, **_kwargs):
            candidates.append(candidate)
            pytest.fail("parent swap must not admit prepare or receipt evidence")

    monkeypatch.setattr(sync_module, "StrategyPromotionProposal", Proposal)
    monkeypatch.setattr(sync_module, "promotion_state_lock", swap_parent_after_lock)
    monkeypatch.setattr(sync_module, "ImmutableStrategyEvidenceStore", lambda *_args, **_kwargs: Store())
    monkeypatch.setattr(
        sync_module,
        "StrategyOperationalPromotionLedger",
        lambda *_args, **_kwargs: pytest.fail(
            "parent swap must fail before durable proposal lookup"
        ),
    )

    with pytest.raises(ValueError, match="state path parent changed"):
        sync_module.sync_strategy_promotion_state_file(
            proposal_ledger_root=tmp_path,
            repo_root=tmp_path,
            proposal=proposal,
            state_path=state,
            expected_current_state_sha256=sync_module._digest(original_state),
            actor_role="strategy_learning",
            clock=lambda: datetime(2026, 7, 28, 12, tzinfo=timezone.utc),
        )

    assert parent.is_symlink()
    assert (parked_parent / state.name).read_bytes() == original_state
    assert redirected_state.read_bytes() == redirected_bytes
    assert candidates == []


def test_missing_preimage_link_then_corrupt_fsyncs_before_and_after_rollback_deletion(
    tmp_path,
    monkeypatch,
) -> None:
    """A failed missing-file replacement durably records both namespace changes."""
    state = tmp_path / "promotion.json"
    snapshot = sync_module.read_promotion_state_snapshot(state)
    after = b'{"sleeves":{"sleeve":{}}}'
    staged = sync_module._stage_state_replacement(state, after)
    fsynced: list[Path] = []
    original_link = sync_module.os.link

    def link_then_corrupt(source, destination, *args, **kwargs):
        result = original_link(source, destination, *args, **kwargs)
        Path(destination).write_bytes(b'{"corrupted":true}')
        return result

    monkeypatch.setattr(sync_module.os, "link", link_then_corrupt)
    monkeypatch.setattr(
        sync_module,
        "_fsync_parent_directory",
        lambda directory: fsynced.append(Path(directory)),
    )

    with pytest.raises(ValueError, match="replacement digest mismatch"):
        sync_module._replace_state_after_final_guard(
            state_file=state,
            snapshot=snapshot,
            staged=staged,
            after=after,
            after_sha256=sync_module._digest(after),
        )

    assert not state.exists()
    assert fsynced == [state.parent, state.parent]


@pytest.mark.parametrize(
    ("recovery_phase", "state_bytes", "expected_preimage"),
    (
        ("normal-sync", b'{"sleeves":{}}', b'{"sleeves":{}}'),
        ("crash-before-replace-resume", b'{"sleeves":{}}', b'{"sleeves":{}}'),
        (
            "receipt-only-repair",
            b'{"sleeves":{"sleeve":{"stage":"paper_only"}}}',
            b'{"sleeves":{}}',
        ),
    ),
)
def test_sync_rejects_state_path_swapped_to_symlink_after_entry_before_locked_recovery(
    tmp_path,
    monkeypatch,
    recovery_phase,
    state_bytes,
    expected_preimage,
) -> None:
    """A post-entry pathname swap must stop before any recovery path reads evidence.

    The lock seam simulates a hostile/accidental filesystem replacement after
    the public pre-check but before the guarded snapshot.  The three parameter
    values represent new replacement, prepared-replacement resume, and receipt
    repair respectively; all must fail before they can inspect or append
    immutable evidence.
    """
    state = tmp_path / f"{recovery_phase}-promotion.json"
    state.write_bytes(state_bytes)
    target = tmp_path / f"{recovery_phase}-target.json"
    target.write_bytes(b'{"target":"must-not-change"}')
    proposal, _digest = _controlled_proposal()
    Proposal = type(proposal)
    original_lock = sync_module.promotion_state_lock

    @contextmanager
    def swap_after_lock(path):
        with original_lock(path):
            state.unlink()
            state.symlink_to(target)
            yield

    monkeypatch.setattr(sync_module, "StrategyPromotionProposal", Proposal)
    monkeypatch.setattr(sync_module, "promotion_state_lock", swap_after_lock)
    monkeypatch.setattr(
        sync_module,
        "ImmutableStrategyEvidenceStore",
        lambda *args, **kwargs: SimpleNamespace(),
    )
    monkeypatch.setattr(
        sync_module,
        "StrategyOperationalPromotionLedger",
        lambda *args, **kwargs: pytest.fail(
            "a swapped state path must fail before durable evidence lookup"
        ),
    )

    with pytest.raises(ValueError, match="symlink state path"):
        sync_module.sync_strategy_promotion_state_file(
            proposal_ledger_root=tmp_path,
            repo_root=tmp_path,
            proposal=proposal,
            state_path=state,
            expected_current_state_sha256=sync_module._digest(expected_preimage),
            actor_role="strategy_learning",
            clock=lambda: datetime(2026, 7, 28, 12, tzinfo=timezone.utc),
        )

    assert state.is_symlink()
    assert target.read_bytes() == b'{"target":"must-not-change"}'


@pytest.mark.parametrize("race", ("created", "deleted", "swapped"))
def test_snapshot_rejects_existence_and_byte_races_without_splitting_preimage(
    tmp_path,
    monkeypatch,
    race,
) -> None:
    """The preimage is one filesystem observation, never ``exists`` plus read."""
    state = tmp_path / "promotion.json"
    preimage = b'{"sleeves":{}}'
    target = tmp_path / "target.json"
    target.write_bytes(b'{"target":"must-not-change"}')
    if race != "created":
        state.write_bytes(preimage)

    original_lstat = sync_module.os.lstat
    original_open = sync_module.os.open

    if race == "created":
        lstat_calls = 0

        def create_after_first_absence(path, *args, **kwargs):
            nonlocal lstat_calls
            if Path(path) == state and lstat_calls == 0:
                lstat_calls += 1
                state.write_bytes(preimage)
                raise FileNotFoundError(path)
            return original_lstat(path, *args, **kwargs)

        monkeypatch.setattr(sync_module.os, "lstat", create_after_first_absence)
    elif race == "deleted":

        def delete_before_guarded_open(path, *args, **kwargs):
            if Path(path) == state:
                state.unlink()
            return original_open(path, *args, **kwargs)

        monkeypatch.setattr(sync_module.os, "open", delete_before_guarded_open)
    else:

        def swap_before_guarded_open(path, *args, **kwargs):
            if Path(path) == state:
                state.unlink()
                state.symlink_to(target)
            return original_open(path, *args, **kwargs)

        monkeypatch.setattr(sync_module.os, "open", swap_before_guarded_open)

    with pytest.raises(ValueError, match="state path changed"):
        sync_module.read_promotion_state_snapshot(state)

    assert target.read_bytes() == b'{"target":"must-not-change"}'


def test_post_guard_state_swap_recovers_exact_preimage_without_receipt(
    tmp_path,
    monkeypatch,
) -> None:
    """A swap after the final guard cannot turn the replacement into a receipt."""
    state = tmp_path / "promotion.json"
    preimage = b'{"sleeves":{}}'
    state.write_bytes(preimage)
    target = tmp_path / "target.json"
    target.write_bytes(b'{"target":"must-not-change"}')
    report = tmp_path / "report.json"
    report.write_text("report")
    risk = tmp_path / "risk.yaml"
    risk.write_text("risk")
    proposal, digest = _controlled_proposal()
    Proposal = type(proposal)
    candidates: list[object] = []

    class Store:
        def envelopes(self, **_kwargs):
            return ()

        def admit_checked(self, candidate, **_kwargs):
            candidates.append(candidate)
            return SimpleNamespace(envelope=object(), created=True)

    monkeypatch.setattr(sync_module, "StrategyPromotionProposal", Proposal)
    monkeypatch.setattr(
        sync_module,
        "StrategyOperationalPromotionLedger",
        lambda *args, **kwargs: SimpleNamespace(rebuild=lambda: (proposal,)),
    )
    monkeypatch.setattr(sync_module, "ImmutableStrategyEvidenceStore", lambda *args, **kwargs: Store())
    monkeypatch.setattr(
        sync_module,
        "_git",
        lambda _root, *args: proposal.promotion_runtime_commit
        if args[0] == "rev-parse"
        else "",
    )
    monkeypatch.setattr(
        sync_module,
        "_safe_repo_file",
        lambda _root, reference, _label: (tmp_path / reference, str(reference)),
    )
    monkeypatch.setattr(
        sync_module,
        "_envelope_object",
        lambda _envelope, _cls: SimpleNamespace(
            sync_prepare_id="strategy-promotion-sync-prepare-" + digest,
            effective_at="2026-07-28T12:00:00+00:00",
            sync_receipt_id="strategy-promotion-sync-receipt-" + digest,
        ),
    )
    original_guard = sync_module._require_snapshot_current
    guard_calls = 0

    def swap_after_final_guard(snapshot):
        nonlocal guard_calls
        original_guard(snapshot)
        guard_calls += 1
        if guard_calls == 2:
            state.unlink()
            state.symlink_to(target)

    monkeypatch.setattr(sync_module, "_require_snapshot_current", swap_after_final_guard)

    with pytest.raises(ValueError, match="state path changed during guarded replacement"):
        sync_module.sync_strategy_promotion_state_file(
            proposal_ledger_root=tmp_path,
            repo_root=tmp_path,
            proposal=proposal,
            state_path=state,
            expected_current_state_sha256=sync_module._digest(preimage),
            actor_role="strategy_learning",
            clock=lambda: datetime(2026, 7, 28, 12, tzinfo=timezone.utc),
        )

    assert state.read_bytes() == preimage
    assert target.read_bytes() == b'{"target":"must-not-change"}'
    assert [candidate.kind for candidate in candidates] == [
        sync_module.STRATEGY_PROMOTION_SYNC_PREPARE_KIND
    ]


def test_guarded_state_exchange_fails_closed_when_platform_exchange_is_unavailable(
    tmp_path,
    monkeypatch,
) -> None:
    """A platform without atomic name exchange cannot fall back to unsafe replace."""
    monkeypatch.setattr(sync_module.ctypes, "CDLL", lambda *_args, **_kwargs: object())

    with pytest.raises(ValueError, match="atomic state identity exchange is unavailable"):
        sync_module._rename_exchange(tmp_path / "before", tmp_path / "after")


def test_restore_of_missing_preimage_fsyncs_parent_directory_after_deletion(
    tmp_path,
    monkeypatch,
) -> None:
    """Rollback deletion is not durable until the state directory is synced."""
    state = tmp_path / "promotion.json"
    state.write_bytes(b'{"partial":true}')
    fsynced: list[Path] = []
    monkeypatch.setattr(
        sync_module,
        "_fsync_parent_directory",
        lambda directory: fsynced.append(Path(directory)),
        raising=False,
    )

    assert sync_module._restore_state_preimage(
        state_file=state,
        preimage=b"",
        preimage_sha256=sync_module._digest(b""),
        preimage_existed=False,
    )

    assert not state.exists()
    assert fsynced == [state.parent]


@pytest.mark.parametrize(
    ("receipt_created", "expected_created", "mismatched_after_hash"),
    [(True, True, False), (False, False, False), (True, False, True)],
    ids=["missing-receipt-repair", "exact-retry", "mismatched-receipt"],
)
def test_crash_after_replace_repairs_or_retries_without_writing_state(
    tmp_path,
    monkeypatch,
    receipt_created,
    expected_created,
    mismatched_after_hash,
) -> None:
    state = tmp_path / "promotion.json"
    preimage = b'{"sleeves":{}}'
    report = tmp_path / "report.json"
    report.write_text("report")
    risk = tmp_path / "risk.yaml"
    risk.write_text("risk")
    proposal, digest = _controlled_proposal()
    Proposal = type(proposal)
    synced_at = datetime(2026, 7, 28, 12, tzinfo=timezone.utc)
    monkeypatch.setattr(sync_module, "StrategyPromotionProposal", Proposal)
    after_state = sync_module.build_strategy_promotion_state(
        proposal=proposal,
        current_state={"sleeves": {}},
        canonical_input_sha256=sync_module._digest(preimage),
        actor_role="strategy_learning",
        synced_at=synced_at,
    )
    after = sync_module._canonical(after_state)
    state.write_bytes(after)
    prepared = StrategyPromotionSyncPrepare(
        sync_prepare_id="strategy-promotion-sync-prepare-" + "b" * 64,
        proposal_id=proposal.proposal_id,
        proposal_sha256=sync_module._digest(proposal.canonical_json_bytes()),
        evaluation_runtime_sha256=proposal.evaluation_runtime_sha256,
        promotion_runtime_commit=proposal.promotion_runtime_commit,
        validation_report_sha256=proposal.validation_attestation.report_sha256,
        risk_envelope_sha256=proposal.risk_attestation.risk_envelope_sha256,
        canonical_before_sha256=sync_module._digest(preimage),
        canonical_after_sha256=sync_module._digest(after),
        state_path=str(state.resolve()),
        effective_at="2026-07-28T12:00:00+00:00",
        recorded_at="2026-07-28T12:00:00+00:00",
        promoted=(proposal.sleeve,),
    )
    receipt = StrategyPromotionSyncReceipt(
        sync_receipt_id="strategy-promotion-sync-receipt-" + "c" * 64,
        sync_prepare_id=prepared.sync_prepare_id,
        sync_prepare_sha256=sync_module._digest(prepared.canonical_json_bytes()),
        proposal_id=proposal.proposal_id,
        proposal_sha256=prepared.proposal_sha256,
        evaluation_runtime_sha256=proposal.evaluation_runtime_sha256,
        promotion_runtime_commit=proposal.promotion_runtime_commit,
        validation_report_sha256=proposal.validation_attestation.report_sha256,
        risk_envelope_sha256=proposal.risk_attestation.risk_envelope_sha256,
        canonical_before_sha256=prepared.canonical_before_sha256,
        canonical_after_sha256=(
            "d" * 64 if mismatched_after_hash else prepared.canonical_after_sha256
        ),
        state_path=prepared.state_path,
        effective_at=prepared.effective_at,
        recorded_at=prepared.recorded_at,
        promoted=prepared.promoted,
        demoted=prepared.demoted,
        unchanged=prepared.unchanged,
    )
    prepare_envelope = object()
    receipt_envelope = object()
    candidates: list[object] = []

    class Store:
        def envelopes(self, *, kind):
            if kind == sync_module.STRATEGY_PROMOTION_SYNC_PREPARE_KIND:
                return (prepare_envelope,)
            return ()

        def admit_checked(self, candidate, **_kwargs):
            candidates.append(candidate)
            return SimpleNamespace(
                envelope=receipt_envelope,
                created=receipt_created,
            )

    monkeypatch.setattr(
        sync_module,
        "StrategyOperationalPromotionLedger",
        lambda *args, **kwargs: SimpleNamespace(rebuild=lambda: (proposal,)),
    )
    monkeypatch.setattr(sync_module, "ImmutableStrategyEvidenceStore", lambda *args, **kwargs: Store())
    monkeypatch.setattr(
        sync_module,
        "_git",
        lambda _root, *args: proposal.promotion_runtime_commit
        if args[0] == "rev-parse"
        else "",
    )
    monkeypatch.setattr(
        sync_module,
        "_safe_repo_file",
        lambda _root, reference, _label: (tmp_path / reference, str(reference)),
    )
    monkeypatch.setattr(
        sync_module,
        "_envelope_object",
        lambda envelope, _cls: prepared
        if envelope is prepare_envelope
        else receipt,
    )
    monkeypatch.setattr(
        sync_module,
        "atomic_write_text",
        lambda *args, **kwargs: pytest.fail("receipt-only repair must not replace state"),
    )

    if mismatched_after_hash:
        with pytest.raises(ValueError, match="sync receipt does not match prepared replacement"):
            sync_module.sync_strategy_promotion_state_file(
                proposal_ledger_root=tmp_path,
                repo_root=tmp_path,
                proposal=proposal,
                state_path=state,
                expected_current_state_sha256=sync_module._digest(preimage),
                actor_role="strategy_learning",
                clock=lambda: datetime(2026, 7, 28, 13, tzinfo=timezone.utc),
            )
        assert [candidate.kind for candidate in candidates] == [
            sync_module.STRATEGY_PROMOTION_SYNC_RECEIPT_KIND
        ]
        assert state.read_bytes() == after
        return

    result = sync_module.sync_strategy_promotion_state_file(
        proposal_ledger_root=tmp_path,
        repo_root=tmp_path,
        proposal=proposal,
        state_path=state,
        expected_current_state_sha256=sync_module._digest(preimage),
        actor_role="strategy_learning",
        clock=lambda: datetime(2026, 7, 28, 13, tzinfo=timezone.utc),
    )

    assert [candidate.kind for candidate in candidates] == [
        sync_module.STRATEGY_PROMOTION_SYNC_RECEIPT_KIND
    ]
    assert candidates[0].effective_at == prepared.effective_at
    assert state.read_bytes() == after
    assert result.sync_prepare_id == prepared.sync_prepare_id
    assert result.sync_receipt_id == receipt.sync_receipt_id
    assert result.canonical_before_sha256 == prepared.canonical_before_sha256
    assert result.canonical_after_sha256 == prepared.canonical_after_sha256
    assert result.promoted == prepared.promoted
    assert result.demoted == prepared.demoted
    assert result.unchanged == prepared.unchanged
    assert result.created is expected_created


def test_crash_before_replace_resumes_only_the_durable_prepared_after_image(
    tmp_path,
    monkeypatch,
) -> None:
    state = tmp_path / "promotion.json"
    preimage = b'{"sleeves":{}}'
    state.write_bytes(preimage)
    report = tmp_path / "report.json"
    report.write_text("report")
    risk = tmp_path / "risk.yaml"
    risk.write_text("risk")
    proposal, _digest = _controlled_proposal()
    Proposal = type(proposal)
    prepared_at = datetime(2026, 7, 28, 12, tzinfo=timezone.utc)
    monkeypatch.setattr(sync_module, "StrategyPromotionProposal", Proposal)
    prepared_after = sync_module._canonical(
        sync_module.build_strategy_promotion_state(
            proposal=proposal,
            current_state={"sleeves": {}},
            canonical_input_sha256=sync_module._digest(preimage),
            actor_role="strategy_learning",
            synced_at=prepared_at,
        )
    )
    prepared = StrategyPromotionSyncPrepare(
        sync_prepare_id="strategy-promotion-sync-prepare-" + "d" * 64,
        proposal_id=proposal.proposal_id,
        proposal_sha256=sync_module._digest(proposal.canonical_json_bytes()),
        evaluation_runtime_sha256=proposal.evaluation_runtime_sha256,
        promotion_runtime_commit=proposal.promotion_runtime_commit,
        validation_report_sha256=proposal.validation_attestation.report_sha256,
        risk_envelope_sha256=proposal.risk_attestation.risk_envelope_sha256,
        canonical_before_sha256=sync_module._digest(preimage),
        canonical_after_sha256=sync_module._digest(prepared_after),
        state_path=str(state.resolve()),
        effective_at="2026-07-28T12:00:00+00:00",
        recorded_at="2026-07-28T12:00:00+00:00",
        promoted=(proposal.sleeve,),
    )
    receipt = StrategyPromotionSyncReceipt(
        sync_receipt_id="strategy-promotion-sync-receipt-" + "e" * 64,
        sync_prepare_id=prepared.sync_prepare_id,
        sync_prepare_sha256=sync_module._digest(prepared.canonical_json_bytes()),
        proposal_id=prepared.proposal_id,
        proposal_sha256=prepared.proposal_sha256,
        evaluation_runtime_sha256=prepared.evaluation_runtime_sha256,
        promotion_runtime_commit=prepared.promotion_runtime_commit,
        validation_report_sha256=prepared.validation_report_sha256,
        risk_envelope_sha256=prepared.risk_envelope_sha256,
        canonical_before_sha256=prepared.canonical_before_sha256,
        canonical_after_sha256=prepared.canonical_after_sha256,
        state_path=prepared.state_path,
        effective_at=prepared.effective_at,
        recorded_at=prepared.recorded_at,
        promoted=prepared.promoted,
        demoted=prepared.demoted,
        unchanged=prepared.unchanged,
    )
    prepare_envelope = object()
    receipt_envelope = object()
    candidates: list[object] = []

    class Store:
        def envelopes(self, *, kind):
            if kind == sync_module.STRATEGY_PROMOTION_SYNC_PREPARE_KIND:
                return (prepare_envelope,)
            return ()

        def admit_checked(self, candidate, **_kwargs):
            candidates.append(candidate)
            return SimpleNamespace(envelope=receipt_envelope, created=True)

    monkeypatch.setattr(
        sync_module,
        "StrategyOperationalPromotionLedger",
        lambda *args, **kwargs: SimpleNamespace(rebuild=lambda: (proposal,)),
    )
    monkeypatch.setattr(sync_module, "ImmutableStrategyEvidenceStore", lambda *args, **kwargs: Store())
    monkeypatch.setattr(
        sync_module,
        "_git",
        lambda _root, *args: proposal.promotion_runtime_commit
        if args[0] == "rev-parse"
        else "",
    )
    monkeypatch.setattr(
        sync_module,
        "_safe_repo_file",
        lambda _root, reference, _label: (tmp_path / reference, str(reference)),
    )
    monkeypatch.setattr(
        sync_module,
        "_envelope_object",
        lambda envelope, _cls: prepared
        if envelope is prepare_envelope
        else receipt,
    )

    result = sync_module.sync_strategy_promotion_state_file(
        proposal_ledger_root=tmp_path,
        repo_root=tmp_path,
        proposal=proposal,
        state_path=state,
        expected_current_state_sha256=sync_module._digest(preimage),
        actor_role="strategy_learning",
        clock=lambda: datetime(2026, 7, 28, 12, 1, tzinfo=timezone.utc),
    )

    assert [candidate.kind for candidate in candidates] == [
        sync_module.STRATEGY_PROMOTION_SYNC_RECEIPT_KIND
    ]
    assert state.read_bytes() == prepared_after
    assert result.sync_prepare_id == prepared.sync_prepare_id
    assert result.sync_receipt_id == receipt.sync_receipt_id


def test_crash_before_replace_refuses_related_prepare_with_mismatched_preimage(
    tmp_path,
    monkeypatch,
) -> None:
    state = tmp_path / "promotion.json"
    preimage = b'{"sleeves":{}}'
    state.write_bytes(preimage)
    report = tmp_path / "report.json"
    report.write_text("report")
    risk = tmp_path / "risk.yaml"
    risk.write_text("risk")
    proposal, _digest = _controlled_proposal()
    Proposal = type(proposal)
    monkeypatch.setattr(sync_module, "StrategyPromotionProposal", Proposal)
    prepared = StrategyPromotionSyncPrepare(
        sync_prepare_id="strategy-promotion-sync-prepare-" + "f" * 64,
        proposal_id=proposal.proposal_id,
        proposal_sha256=sync_module._digest(proposal.canonical_json_bytes()),
        evaluation_runtime_sha256=proposal.evaluation_runtime_sha256,
        promotion_runtime_commit=proposal.promotion_runtime_commit,
        validation_report_sha256=proposal.validation_attestation.report_sha256,
        risk_envelope_sha256=proposal.risk_attestation.risk_envelope_sha256,
        canonical_before_sha256="f" * 64,
        canonical_after_sha256="e" * 64,
        state_path=str(state.resolve()),
        effective_at="2026-07-28T12:00:00+00:00",
        recorded_at="2026-07-28T12:00:00+00:00",
        promoted=(proposal.sleeve,),
    )
    prepare_envelope = object()

    class Store:
        def envelopes(self, *, kind):
            if kind == sync_module.STRATEGY_PROMOTION_SYNC_PREPARE_KIND:
                return (prepare_envelope,)
            return ()

        def admit_checked(self, *_args, **_kwargs):
            pytest.fail("mismatched prepare must not admit a replacement transaction")

    monkeypatch.setattr(
        sync_module,
        "StrategyOperationalPromotionLedger",
        lambda *args, **kwargs: SimpleNamespace(rebuild=lambda: (proposal,)),
    )
    monkeypatch.setattr(sync_module, "ImmutableStrategyEvidenceStore", lambda *args, **kwargs: Store())
    monkeypatch.setattr(
        sync_module,
        "_git",
        lambda _root, *args: proposal.promotion_runtime_commit
        if args[0] == "rev-parse"
        else "",
    )
    monkeypatch.setattr(
        sync_module,
        "_safe_repo_file",
        lambda _root, reference, _label: (tmp_path / reference, str(reference)),
    )
    monkeypatch.setattr(sync_module, "_envelope_object", lambda *_args: prepared)

    with pytest.raises(ValueError, match="matching state preimage"):
        sync_module.sync_strategy_promotion_state_file(
            proposal_ledger_root=tmp_path,
            repo_root=tmp_path,
            proposal=proposal,
            state_path=state,
            expected_current_state_sha256=sync_module._digest(preimage),
            actor_role="strategy_learning",
            clock=lambda: datetime(2026, 7, 28, 12, 1, tzinfo=timezone.utc),
        )

    assert state.read_bytes() == preimage


def test_crash_before_replace_refuses_expired_durable_prepare_without_writing(
    tmp_path,
    monkeypatch,
) -> None:
    state = tmp_path / "promotion.json"
    preimage = b'{"sleeves":{}}'
    state.write_bytes(preimage)
    report = tmp_path / "report.json"
    report.write_text("report")
    risk = tmp_path / "risk.yaml"
    risk.write_text("risk")
    proposal, _digest = _controlled_proposal()
    Proposal = type(proposal)
    monkeypatch.setattr(sync_module, "StrategyPromotionProposal", Proposal)
    prepared = StrategyPromotionSyncPrepare(
        sync_prepare_id="strategy-promotion-sync-prepare-" + "1" * 64,
        proposal_id=proposal.proposal_id,
        proposal_sha256=sync_module._digest(proposal.canonical_json_bytes()),
        evaluation_runtime_sha256=proposal.evaluation_runtime_sha256,
        promotion_runtime_commit=proposal.promotion_runtime_commit,
        validation_report_sha256=proposal.validation_attestation.report_sha256,
        risk_envelope_sha256=proposal.risk_attestation.risk_envelope_sha256,
        canonical_before_sha256=sync_module._digest(preimage),
        canonical_after_sha256="2" * 64,
        state_path=str(state.resolve()),
        effective_at="2026-07-28T12:00:00+00:00",
        recorded_at="2026-07-28T12:00:00+00:00",
        promoted=(proposal.sleeve,),
    )
    prepare_envelope = object()

    class Store:
        def envelopes(self, *, kind):
            if kind == sync_module.STRATEGY_PROMOTION_SYNC_PREPARE_KIND:
                return (prepare_envelope,)
            return ()

        def admit_checked(self, *_args, **_kwargs):
            pytest.fail("expired prepared transaction must not admit evidence")

    monkeypatch.setattr(
        sync_module,
        "StrategyOperationalPromotionLedger",
        lambda *args, **kwargs: SimpleNamespace(rebuild=lambda: (proposal,)),
    )
    monkeypatch.setattr(sync_module, "ImmutableStrategyEvidenceStore", lambda *args, **kwargs: Store())
    monkeypatch.setattr(sync_module, "_envelope_object", lambda *_args: prepared)

    with pytest.raises(ValueError, match="prepared promotion state transaction is expired"):
        sync_module.sync_strategy_promotion_state_file(
            proposal_ledger_root=tmp_path,
            repo_root=tmp_path,
            proposal=proposal,
            state_path=state,
            expected_current_state_sha256=sync_module._digest(preimage),
            actor_role="strategy_learning",
            clock=lambda: datetime(2026, 7, 28, 12, 5, tzinfo=timezone.utc),
        )

    assert state.read_bytes() == preimage


def test_stale_preimage_refuses_a_racing_different_proposal_without_writing(
    tmp_path,
    monkeypatch,
) -> None:
    state = tmp_path / "promotion.json"
    committed_state = b'{"sleeves":{"other":{}}}'
    state.write_bytes(committed_state)
    proposal, _digest = _controlled_proposal()
    Proposal = type(proposal)
    proposal.proposal_id = "strategy-promotion-proposal-" + "3" * 64
    monkeypatch.setattr(sync_module, "StrategyPromotionProposal", Proposal)

    class Store:
        def envelopes(self, *, kind):
            assert kind == sync_module.STRATEGY_PROMOTION_SYNC_PREPARE_KIND
            return ()

        def admit_checked(self, *_args, **_kwargs):
            pytest.fail("stale preimage must not admit a transaction")

    monkeypatch.setattr(
        sync_module,
        "StrategyOperationalPromotionLedger",
        lambda *args, **kwargs: SimpleNamespace(rebuild=lambda: (proposal,)),
    )
    monkeypatch.setattr(sync_module, "ImmutableStrategyEvidenceStore", lambda *args, **kwargs: Store())
    monkeypatch.setattr(
        sync_module,
        "atomic_write_text",
        lambda *args, **kwargs: pytest.fail("stale preimage must not replace state"),
    )

    with pytest.raises(ValueError, match="stale promotion state preimage"):
        sync_module.sync_strategy_promotion_state_file(
            proposal_ledger_root=tmp_path,
            repo_root=tmp_path,
            proposal=proposal,
            state_path=state,
            expected_current_state_sha256=sync_module._digest(b'{"sleeves":{}}'),
            actor_role="strategy_learning",
            clock=lambda: datetime(2026, 7, 28, 12, 1, tzinfo=timezone.utc),
        )

    assert state.read_bytes() == committed_state


@pytest.mark.parametrize(
    "previous",
    (
        {"ineligible_at": "2026-07-28T12:00:00+00:00"},
        {
            "source": {
                "proposal_effective_at": "2026-07-28T12:00:00+00:00"
            }
        },
        {
            "source": {
                "proposal_recorded_at": "2026-07-28T12:00:00+00:00"
            }
        },
    ),
)
def test_stale_prior_sleeve_or_provenance_time_is_refused(previous) -> None:
    proposal, _digest = _controlled_proposal()
    proposal.effective_at = "2026-07-28T12:00:00+00:00"
    with pytest.raises(ValueError, match="proposal is stale"):
        sync_module._require_not_stale_prior(previous, proposal)


def test_crash_before_replace_revalidates_stale_validation_attestation(
    tmp_path,
    monkeypatch,
) -> None:
    state = tmp_path / "promotion.json"
    preimage = b'{"sleeves":{}}'
    state.write_bytes(preimage)
    report = tmp_path / "report.json"
    report.write_text("report")
    risk = tmp_path / "risk.yaml"
    risk.write_text("risk")
    proposal, _digest = _controlled_proposal()
    proposal.validation_attestation.completed_at = "2026-07-27T12:00:00+00:00"
    Proposal = type(proposal)
    prepared_at = datetime(2026, 7, 28, 12, tzinfo=timezone.utc)
    monkeypatch.setattr(sync_module, "StrategyPromotionProposal", Proposal)
    prepared_after = sync_module._canonical(
        sync_module.build_strategy_promotion_state(
            proposal=proposal,
            current_state={"sleeves": {}},
            canonical_input_sha256=sync_module._digest(preimage),
            actor_role="strategy_learning",
            synced_at=prepared_at,
        )
    )
    prepared = StrategyPromotionSyncPrepare(
        sync_prepare_id="strategy-promotion-sync-prepare-" + "4" * 64,
        proposal_id=proposal.proposal_id,
        proposal_sha256=sync_module._digest(proposal.canonical_json_bytes()),
        evaluation_runtime_sha256=proposal.evaluation_runtime_sha256,
        promotion_runtime_commit=proposal.promotion_runtime_commit,
        validation_report_sha256=proposal.validation_attestation.report_sha256,
        risk_envelope_sha256=proposal.risk_attestation.risk_envelope_sha256,
        canonical_before_sha256=sync_module._digest(preimage),
        canonical_after_sha256=sync_module._digest(prepared_after),
        state_path=str(state.resolve()),
        effective_at="2026-07-28T12:00:00+00:00",
        recorded_at="2026-07-28T12:00:00+00:00",
        promoted=(proposal.sleeve,),
    )
    prepare_envelope = object()

    class Store:
        def envelopes(self, *, kind):
            if kind == sync_module.STRATEGY_PROMOTION_SYNC_PREPARE_KIND:
                return (prepare_envelope,)
            return ()

        def admit_checked(self, *_args, **_kwargs):
            pytest.fail("stale validation proof must not admit a receipt")

    monkeypatch.setattr(
        sync_module,
        "StrategyOperationalPromotionLedger",
        lambda *args, **kwargs: SimpleNamespace(rebuild=lambda: (proposal,)),
    )
    monkeypatch.setattr(sync_module, "ImmutableStrategyEvidenceStore", lambda *args, **kwargs: Store())
    monkeypatch.setattr(
        sync_module,
        "_git",
        lambda _root, *args: proposal.promotion_runtime_commit
        if args[0] == "rev-parse"
        else "",
    )
    monkeypatch.setattr(
        sync_module,
        "_safe_repo_file",
        lambda _root, reference, _label: (tmp_path / reference, str(reference)),
    )
    monkeypatch.setattr(sync_module, "_envelope_object", lambda *_args: prepared)
    monkeypatch.setattr(
        sync_module,
        "atomic_write_text",
        lambda *args, **kwargs: pytest.fail("stale validation proof must not replace state"),
    )

    with pytest.raises(ValueError, match="validation attestation is stale"):
        sync_module.sync_strategy_promotion_state_file(
            proposal_ledger_root=tmp_path,
            repo_root=tmp_path,
            proposal=proposal,
            state_path=state,
            expected_current_state_sha256=sync_module._digest(preimage),
            actor_role="strategy_learning",
            clock=lambda: datetime(2026, 7, 28, 12, 1, tzinfo=timezone.utc),
        )

    assert state.read_bytes() == preimage


@pytest.mark.parametrize(
    ("attestation_name", "timestamp_name", "label"),
    [
        ("validation_attestation", "completed_at", "validation attestation"),
        ("risk_attestation", "reviewed_at", "risk attestation"),
    ],
)
def test_new_prepare_revalidates_stale_attestation_before_admission(
    tmp_path,
    monkeypatch,
    attestation_name,
    timestamp_name,
    label,
) -> None:
    state = tmp_path / "promotion.json"
    preimage = b'{"sleeves":{}}'
    state.write_bytes(preimage)
    report = tmp_path / "report.json"
    report.write_text("report")
    risk = tmp_path / "risk.yaml"
    risk.write_text("risk")
    proposal, _digest = _controlled_proposal()
    setattr(
        getattr(proposal, attestation_name),
        timestamp_name,
        "2026-07-27T12:00:00+00:00",
    )
    Proposal = type(proposal)
    monkeypatch.setattr(sync_module, "StrategyPromotionProposal", Proposal)

    class Store:
        def envelopes(self, *, kind):
            assert kind == sync_module.STRATEGY_PROMOTION_SYNC_PREPARE_KIND
            return ()

        def admit_checked(self, *_args, **_kwargs):
            pytest.fail("stale validation proof must not admit a prepare")

    monkeypatch.setattr(
        sync_module,
        "StrategyOperationalPromotionLedger",
        lambda *args, **kwargs: SimpleNamespace(rebuild=lambda: (proposal,)),
    )
    monkeypatch.setattr(sync_module, "ImmutableStrategyEvidenceStore", lambda *args, **kwargs: Store())
    monkeypatch.setattr(
        sync_module,
        "_git",
        lambda _root, *args: proposal.promotion_runtime_commit
        if args[0] == "rev-parse"
        else "",
    )
    monkeypatch.setattr(
        sync_module,
        "_safe_repo_file",
        lambda _root, reference, _label: (tmp_path / reference, str(reference)),
    )
    monkeypatch.setattr(
        sync_module,
        "atomic_write_text",
        lambda *args, **kwargs: pytest.fail("stale validation proof must not replace state"),
    )

    with pytest.raises(ValueError, match=label + " is stale"):
        sync_module.sync_strategy_promotion_state_file(
            proposal_ledger_root=tmp_path,
            repo_root=tmp_path,
            proposal=proposal,
            state_path=state,
            expected_current_state_sha256=sync_module._digest(preimage),
            actor_role="strategy_learning",
            clock=lambda: datetime(2026, 7, 28, 12, 1, tzinfo=timezone.utc),
        )

    assert state.read_bytes() == preimage


def test_new_prepare_revalidates_hard_cap_and_risk_gate_projection(
    tmp_path,
    monkeypatch,
) -> None:
    state = tmp_path / "promotion.json"
    preimage = b'{"sleeves":{}}'
    state.write_bytes(preimage)
    report = tmp_path / "report.json"
    report.write_text("report")
    risk = tmp_path / "risk.yaml"
    risk.write_text("risk")
    proposal, _digest = _controlled_proposal()
    proposal.risk_attestation.account_hard_ceiling_usd = "0.5"
    Proposal = type(proposal)
    monkeypatch.setattr(sync_module, "StrategyPromotionProposal", Proposal)

    class Store:
        def envelopes(self, *, kind):
            assert kind == sync_module.STRATEGY_PROMOTION_SYNC_PREPARE_KIND
            return ()

        def admit_checked(self, *_args, **_kwargs):
            pytest.fail("risk projection drift must not admit a prepare")

    monkeypatch.setattr(
        sync_module,
        "StrategyOperationalPromotionLedger",
        lambda *args, **kwargs: SimpleNamespace(rebuild=lambda: (proposal,)),
    )
    monkeypatch.setattr(sync_module, "ImmutableStrategyEvidenceStore", lambda *args, **kwargs: Store())
    monkeypatch.setattr(
        sync_module,
        "_git",
        lambda _root, *args: proposal.promotion_runtime_commit
        if args[0] == "rev-parse"
        else "",
    )
    monkeypatch.setattr(
        sync_module,
        "_safe_repo_file",
        lambda _root, reference, _label: (tmp_path / reference, str(reference)),
    )

    with pytest.raises(ValueError, match="risk gate projection"):
        sync_module.sync_strategy_promotion_state_file(
            proposal_ledger_root=tmp_path,
            repo_root=tmp_path,
            proposal=proposal,
            state_path=state,
            expected_current_state_sha256=sync_module._digest(preimage),
            actor_role="strategy_learning",
            clock=lambda: datetime(2026, 7, 28, 12, 1, tzinfo=timezone.utc),
        )

    assert state.read_bytes() == preimage


@pytest.mark.parametrize(
    ("prior_stage", "next_stage", "expected"),
    [
        (None, "tiny_live_eligible", (("sleeve",), (), ())),
        (None, "paper_only", ((), ("sleeve",), ())),
        ("paper_only", "tiny_live_eligible", (("sleeve",), (), ())),
        ("paper_only", "paper_only", ((), (), ("sleeve",))),
        ("tiny_live_eligible", "tiny_live_eligible", ((), (), ("sleeve",))),
        ("tiny_live_eligible", "paper_only", ((), ("sleeve",), ())),
    ],
)
def test_transition_table_is_exact_and_paper_only_never_enables_live(
    prior_stage,
    next_stage,
    expected,
) -> None:
    prior = None if prior_stage is None else {"stage": prior_stage, "live_enabled": False}
    assert sync_module._transition(prior, next_stage, "sleeve") == expected


@pytest.mark.parametrize(
    ("report_text", "status", "error"),
    [
        ("changed after attestation", "", "external promotion anchor changed"),
        ("report", "dirty", "promotion runtime checkout is not clean and attested"),
    ],
)
def test_new_prepare_refuses_dirty_runtime_or_changed_external_anchor(
    tmp_path,
    monkeypatch,
    report_text,
    status,
    error,
) -> None:
    state = tmp_path / "promotion.json"
    preimage = b'{"sleeves":{}}'
    state.write_bytes(preimage)
    report = tmp_path / "report.json"
    report.write_text(report_text)
    risk = tmp_path / "risk.yaml"
    risk.write_text("risk")
    proposal, _digest = _controlled_proposal()
    Proposal = type(proposal)
    monkeypatch.setattr(sync_module, "StrategyPromotionProposal", Proposal)

    class Store:
        def envelopes(self, *, kind):
            assert kind == sync_module.STRATEGY_PROMOTION_SYNC_PREPARE_KIND
            return ()

        def admit_checked(self, *_args, **_kwargs):
            pytest.fail("changed external anchor must not admit a prepare")

    monkeypatch.setattr(
        sync_module,
        "StrategyOperationalPromotionLedger",
        lambda *args, **kwargs: SimpleNamespace(rebuild=lambda: (proposal,)),
    )
    monkeypatch.setattr(sync_module, "ImmutableStrategyEvidenceStore", lambda *args, **kwargs: Store())
    monkeypatch.setattr(
        sync_module,
        "_git",
        lambda _root, *args: proposal.promotion_runtime_commit
        if args[0] == "rev-parse"
        else status,
    )
    monkeypatch.setattr(
        sync_module,
        "_safe_repo_file",
        lambda _root, reference, _label: (tmp_path / reference, str(reference)),
    )

    with pytest.raises(ValueError, match=error):
        sync_module.sync_strategy_promotion_state_file(
            proposal_ledger_root=tmp_path,
            repo_root=tmp_path,
            proposal=proposal,
            state_path=state,
            expected_current_state_sha256=sync_module._digest(preimage),
            actor_role="strategy_learning",
            clock=lambda: datetime(2026, 7, 28, 12, 1, tzinfo=timezone.utc),
        )

    assert state.read_bytes() == preimage


def test_concurrent_different_proposals_with_one_preimage_commit_once(tmp_path, monkeypatch) -> None:
    state = tmp_path / "promotion.json"
    preimage = b'{"sleeves":{}}'
    state.write_bytes(preimage)
    report = tmp_path / "report.json"
    report.write_text("report")
    risk = tmp_path / "risk.yaml"
    risk.write_text("risk")
    proposal_a, _digest = _controlled_proposal()
    Proposal = type(proposal_a)
    proposal_b = Proposal()
    for name, value in vars(proposal_a).items():
        setattr(proposal_b, name, value)
    proposal_b.proposal_id = "strategy-promotion-proposal-" + "5" * 64
    proposal_b.canonical_json_bytes = lambda: b"proposal-b"
    monkeypatch.setattr(sync_module, "StrategyPromotionProposal", Proposal)
    envelopes: list[SimpleNamespace] = []
    candidates: list[object] = []

    class Store:
        def envelopes(self, *, kind):
            return tuple(
                envelope for envelope in envelopes if envelope.kind == kind
            )

        def admit_checked(self, candidate, **_kwargs):
            candidates.append(candidate)
            if candidate.kind == sync_module.STRATEGY_PROMOTION_SYNC_PREPARE_KIND:
                envelope = SimpleNamespace(
                    kind=candidate.kind,
                    object_id="strategy-promotion-sync-prepare-" + "6" * 64,
                    payload=candidate.payload,
                    effective_at=candidate.effective_at,
                    recorded_at=candidate.effective_at,
                )
                envelopes.append(envelope)
                return SimpleNamespace(envelope=envelope, created=True)
            envelope = SimpleNamespace(
                kind=candidate.kind,
                object_id="strategy-promotion-sync-receipt-" + "7" * 64,
                payload=candidate.payload,
                effective_at=candidate.effective_at,
                recorded_at=candidate.effective_at,
            )
            envelopes.append(envelope)
            return SimpleNamespace(envelope=envelope, created=True)

    monkeypatch.setattr(
        sync_module,
        "StrategyOperationalPromotionLedger",
        lambda *args, **kwargs: SimpleNamespace(rebuild=lambda: (proposal_a, proposal_b)),
    )
    monkeypatch.setattr(sync_module, "ImmutableStrategyEvidenceStore", lambda *args, **kwargs: Store())
    monkeypatch.setattr(
        sync_module,
        "_git",
        lambda _root, *args: proposal_a.promotion_runtime_commit
        if args[0] == "rev-parse"
        else "",
    )
    monkeypatch.setattr(
        sync_module,
        "_safe_repo_file",
        lambda _root, reference, _label: (tmp_path / reference, str(reference)),
    )
    barrier = Barrier(2)

    def sync(proposal):
        barrier.wait()
        return sync_module.sync_strategy_promotion_state_file(
            proposal_ledger_root=tmp_path,
            repo_root=tmp_path,
            proposal=proposal,
            state_path=state,
            expected_current_state_sha256=sync_module._digest(preimage),
            actor_role="strategy_learning",
            clock=lambda: datetime(2026, 7, 28, 12, 1, tzinfo=timezone.utc),
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(sync, proposal) for proposal in (proposal_a, proposal_b)]
        outcomes = []
        for future in futures:
            try:
                outcomes.append(future.result())
            except ValueError as error:
                outcomes.append(error)

    successful = [outcome for outcome in outcomes if not isinstance(outcome, ValueError)]
    failures = [outcome for outcome in outcomes if isinstance(outcome, ValueError)]
    assert len(successful) == 1
    assert len(failures) == 1
    assert "stale promotion state preimage" in str(failures[0])
    assert [candidate.kind for candidate in candidates] == [
        sync_module.STRATEGY_PROMOTION_SYNC_PREPARE_KIND,
        sync_module.STRATEGY_PROMOTION_SYNC_RECEIPT_KIND,
    ]
    snapshot = sync_module.read_promotion_state_snapshot(state)
    assert snapshot.sha256 == successful[0].canonical_after_sha256
    assert snapshot.state["source"]["proposal_id"] == successful[0].proposal_id


def test_exact_retry_is_byte_and_event_silent_with_real_immutable_store(
    tmp_path,
    monkeypatch,
) -> None:
    state = tmp_path / "promotion.json"
    preimage = b'{"sleeves":{}}'
    proposal, _digest = _controlled_proposal()
    Proposal = type(proposal)
    prepared_at = datetime(2026, 7, 28, 12, tzinfo=timezone.utc)
    monkeypatch.setattr(sync_module, "StrategyPromotionProposal", Proposal)
    after = sync_module._canonical(
        sync_module.build_strategy_promotion_state(
            proposal=proposal,
            current_state={"sleeves": {}},
            canonical_input_sha256=sync_module._digest(preimage),
            actor_role="strategy_learning",
            synced_at=prepared_at,
        )
    )
    state.write_bytes(after)
    store_root = tmp_path / "evidence"
    proposal_sha = sync_module._digest(proposal.canonical_json_bytes())
    prepare_candidate = sync_module.EvidenceCandidate(
        kind=sync_module.STRATEGY_PROMOTION_SYNC_PREPARE_KIND,
        effective_at="2026-07-28T12:00:00+00:00",
        payload={
            "schema_version": 1,
            "proposal_id": proposal.proposal_id,
            "proposal_sha256": proposal_sha,
            "evaluation_runtime_sha256": proposal.evaluation_runtime_sha256,
            "promotion_runtime_commit": proposal.promotion_runtime_commit,
            "validation_report_sha256": proposal.validation_attestation.report_sha256,
            "risk_envelope_sha256": proposal.risk_attestation.risk_envelope_sha256,
            "canonical_before_sha256": sync_module._digest(preimage),
            "canonical_after_sha256": sync_module._digest(after),
            "state_path": str(state.resolve()),
            "promoted": [proposal.sleeve],
            "demoted": [],
            "unchanged": [],
            "analysis_only": True,
            "execution_authority": "none",
            "can_submit_orders": False,
        },
    )
    prepopulate = sync_module.ImmutableStrategyEvidenceStore(
        store_root,
        clock=lambda: prepared_at,
    )
    prepopulate.admit_checked(
        prepare_candidate,
        validate=lambda _snapshot, envelope: sync_module._envelope_object(
            envelope,
            StrategyPromotionSyncPrepare,
        ),
    )
    monkeypatch.setattr(
        sync_module,
        "StrategyOperationalPromotionLedger",
        lambda *args, **kwargs: SimpleNamespace(rebuild=lambda: (proposal,)),
    )

    first = sync_module.sync_strategy_promotion_state_file(
        proposal_ledger_root=store_root,
        repo_root=tmp_path,
        proposal=proposal,
        state_path=state,
        expected_current_state_sha256=sync_module._digest(preimage),
        actor_role="strategy_learning",
        clock=lambda: datetime(2026, 7, 28, 13, tzinfo=timezone.utc),
    )
    bytes_after_first = state.read_bytes()
    events_after_first = (store_root / "events.jsonl").read_bytes()
    second = sync_module.sync_strategy_promotion_state_file(
        proposal_ledger_root=store_root,
        repo_root=tmp_path,
        proposal=proposal,
        state_path=state,
        expected_current_state_sha256=sync_module._digest(preimage),
        actor_role="strategy_learning",
        clock=lambda: datetime(2026, 7, 28, 13, tzinfo=timezone.utc),
    )

    assert first.created is True
    assert second.created is False
    assert first.promoted == second.promoted == (proposal.sleeve,)
    assert first.demoted == second.demoted == ()
    assert first.unchanged == second.unchanged == ()
    assert state.read_bytes() == bytes_after_first == after
    assert (store_root / "events.jsonl").read_bytes() == events_after_first
    receipts = sync_module.ImmutableStrategyEvidenceStore(store_root).envelopes(
        kind=sync_module.STRATEGY_PROMOTION_SYNC_RECEIPT_KIND,
    )
    assert len(receipts) == 1


def _prepare_payload(**changes: object) -> dict[str, object]:
    values: dict[str, object] = {
        "sync_prepare_id": "strategy-promotion-sync-prepare-" + "a" * 64,
        "proposal_id": "strategy-promotion-proposal-" + "b" * 64,
        "proposal_sha256": "b" * 64,
        "evaluation_runtime_sha256": "c" * 64,
        "promotion_runtime_commit": "d" * 40,
        "validation_report_sha256": "e" * 64,
        "risk_envelope_sha256": "f" * 64,
        "canonical_before_sha256": "1" * 64,
        "canonical_after_sha256": "2" * 64,
        "state_path": "/tmp/promotion_state.json",
        "promoted": ["sleeve"],
        "demoted": [],
        "unchanged": [],
        "effective_at": "2026-07-28T12:00:00+00:00",
        "recorded_at": "2026-07-28T12:00:01+00:00",
        "schema_version": 1,
        "analysis_only": True,
        "execution_authority": "none",
        "can_submit_orders": False,
    }
    values.update(changes)
    return values


def test_sync_prepare_rejects_malformed_immutable_object_ids() -> None:
    with pytest.raises(ValueError, match="sync_prepare_id"):
        StrategyPromotionSyncPrepare.from_dict(_prepare_payload(sync_prepare_id="bad"))
    with pytest.raises(ValueError, match="proposal_id"):
        StrategyPromotionSyncPrepare.from_dict(_prepare_payload(proposal_id="bad"))


def test_sync_receipt_rejects_malformed_prepare_digest() -> None:
    payload = _prepare_payload()
    payload.pop("sync_prepare_id")
    payload["sync_receipt_id"] = "strategy-promotion-sync-receipt-" + "a" * 64
    payload["sync_prepare_id"] = "strategy-promotion-sync-prepare-" + "a" * 64
    payload["sync_prepare_sha256"] = "not-a-digest"
    with pytest.raises(ValueError, match="sync_prepare_sha256"):
        StrategyPromotionSyncReceipt.from_dict(payload)


@pytest.mark.parametrize(
    ("changes", "error"),
    [
        ({"promotion_runtime_commit": "D" * 40}, "promotion_runtime_commit"),
        ({"state_path": ""}, "state_path"),
        ({"state_path": "promotion.json"}, "state_path"),
        ({"state_path": "/tmp/../tmp/promotion.json"}, "state_path"),
        ({"state_path": "/tmp//promotion.json"}, "state_path"),
        ({"canonical_before_sha256": "A" * 64}, "canonical_before_sha256"),
        ({"canonical_after_sha256": "1" * 64}, "canonical images"),
        ({"promoted": [" sleeve "]}, "transition tuple"),
    ],
)
def test_sync_prepare_parser_rejects_noncanonical_runtime_paths_hashes_and_transitions(
    changes,
    error,
) -> None:
    with pytest.raises(ValueError, match=error):
        StrategyPromotionSyncPrepare.from_dict(_prepare_payload(**changes))


@pytest.mark.parametrize(
    "source_label",
    ("internal evidence", "shadow evidence", "calculation manifest", "gate projection"),
)
def test_source_recompute_refusal_precedes_prepare_and_state_mutation(
    tmp_path,
    monkeypatch,
    source_label,
) -> None:
    """A current proposal cannot bypass a failed durable-source recheck."""
    state = tmp_path / "promotion.json"
    preimage = b'{"sleeves":{}}'
    state.write_bytes(preimage)
    report = tmp_path / "report.json"
    report.write_text("report")
    risk = tmp_path / "risk.yaml"
    risk.write_text("risk")
    proposal, _digest = _controlled_proposal()
    Proposal = type(proposal)
    candidates: list[object] = []

    class Store:
        def envelopes(self, **_kwargs):
            return ()

        def admit_checked(self, candidate, **_kwargs):
            candidates.append(candidate)
            raise AssertionError("source recomputation must run before prepare")

    monkeypatch.setattr(sync_module, "StrategyPromotionProposal", Proposal)
    monkeypatch.setattr(
        sync_module,
        "StrategyOperationalPromotionLedger",
        lambda *args, **kwargs: SimpleNamespace(rebuild=lambda: (proposal,)),
    )
    monkeypatch.setattr(sync_module, "ImmutableStrategyEvidenceStore", lambda *args, **kwargs: Store())
    monkeypatch.setattr(
        sync_module,
        "_git",
        lambda _root, *args: proposal.promotion_runtime_commit
        if args[0] == "rev-parse"
        else "",
    )
    monkeypatch.setattr(
        sync_module,
        "_safe_repo_file",
        lambda _root, reference, _label: (tmp_path / reference, str(reference)),
    )

    def reject(**_kwargs) -> None:
        raise ValueError(f"{source_label} changed")

    monkeypatch.setattr(
        sync_module,
        "_require_durable_source_recomputation",
        reject,
        raising=False,
    )

    with pytest.raises(ValueError, match=source_label):
        sync_module.sync_strategy_promotion_state_file(
            proposal_ledger_root=tmp_path,
            repo_root=tmp_path,
            proposal=proposal,
            state_path=state,
            expected_current_state_sha256=sync_module._digest(preimage),
            actor_role="strategy_learning",
            clock=lambda: datetime(2026, 7, 28, 12, tzinfo=timezone.utc),
        )

    assert candidates == []
    assert state.read_bytes() == preimage


def test_activation_requires_exact_current_intent_and_state_preimage(
    tmp_path, monkeypatch
) -> None:
    """An intent for any other canonical image cannot activate a sleeve."""

    root, repo_root, proposal, synced_at, commit = _real_immutable_journal(
        tmp_path, monkeypatch
    )
    state = tmp_path / "promotion.json"
    state.write_bytes(b'{"sleeves":{}}')
    monkeypatch.setattr(
        sync_module,
        "_git",
        lambda _root, *args: commit if args == ("rev-parse", "HEAD") else "",
    )
    synced = sync_module.sync_strategy_promotion_state_file(
        proposal_ledger_root=root,
        repo_root=repo_root,
        proposal=proposal,
        state_path=state,
        expected_current_state_sha256=sync_module._digest(b'{"sleeves":{}}'),
        actor_role="strategy_learning",
        clock=lambda: synced_at,
    )
    receipt = next(
        envelope
        for envelope in sync_module.ImmutableStrategyEvidenceStore(root).rebuild()
        if envelope.object_id == synced.sync_receipt_id
    )
    intent = _normal_live_intent(
        proposal,
        state_sha256="0" * 64,
        receipt_id=synced.sync_receipt_id,
        receipt_sha256=sync_module._digest(receipt.canonical_json_bytes()),
    )

    with pytest.raises(ValueError, match="promotion state preimage"):
        sync_module.activate_normal_live_intent(
            proposal,
            intent,
            proposal_ledger_root=root,
            repo_root=repo_root,
            state_path=state,
            clock=lambda: synced_at,
        )

    assert state.read_bytes() == synced.state_path.read_bytes() if hasattr(synced, "state_path") else state.read_bytes()


def test_activation_never_promotes_an_expired_intent(
    tmp_path, monkeypatch
) -> None:
    """An expired Task 2 authorization never changes the promotion state."""

    root, repo_root, proposal, synced_at, commit = _real_immutable_journal(
        tmp_path, monkeypatch
    )
    state = tmp_path / "promotion.json"
    preimage = b'{"sleeves":{}}'
    state.write_bytes(preimage)
    monkeypatch.setattr(
        sync_module,
        "_git",
        lambda _root, *args: commit if args == ("rev-parse", "HEAD") else "",
    )
    synced = sync_module.sync_strategy_promotion_state_file(
        proposal_ledger_root=root,
        repo_root=repo_root,
        proposal=proposal,
        state_path=state,
        expected_current_state_sha256=sync_module._digest(preimage),
        actor_role="strategy_learning",
        clock=lambda: synced_at,
    )
    receipt = next(
        envelope
        for envelope in sync_module.ImmutableStrategyEvidenceStore(root).rebuild()
        if envelope.object_id == synced.sync_receipt_id
    )
    intent = _normal_live_intent(
        proposal,
        state_sha256=synced.canonical_after_sha256,
        receipt_id=synced.sync_receipt_id,
        receipt_sha256=sync_module._digest(receipt.canonical_json_bytes()),
        expires_at="2030-03-22T16:05:01+00:00",
    )
    before = state.read_bytes()

    with pytest.raises(ValueError, match="active capped intent"):
        sync_module.activate_normal_live_intent(
            proposal,
            intent,
            proposal_ledger_root=root,
            repo_root=repo_root,
            state_path=state,
            clock=lambda: datetime(2030, 3, 22, 16, 6, tzinfo=timezone.utc),
        )

    assert state.read_bytes() == before


def _sync_capped_activation_state(
    *,
    root: Path,
    repo_root: Path,
    proposal: object,
    state: Path,
    synced_at: datetime,
    intent_recorded_at: datetime | None = None,
    intent_expires_at: datetime | None = None,
    overrides: dict[str, object] | None = None,
) -> AuthorizedNormalTradeIntent:
    state.write_bytes(b'{"sleeves":{}}')
    synced = sync_module.sync_strategy_promotion_state_file(
        proposal_ledger_root=root,
        repo_root=repo_root,
        proposal=proposal,
        state_path=state,
        expected_current_state_sha256=sync_module._digest(b'{"sleeves":{}}'),
        actor_role="strategy_learning",
        clock=lambda: synced_at,
    )
    receipt = next(
        item
        for item in sync_module.ImmutableStrategyEvidenceStore(root).rebuild()
        if item.object_id == synced.sync_receipt_id
    )
    recorded = intent_recorded_at or synced_at
    expires = intent_expires_at or (recorded + timedelta(minutes=5))
    return _complete_normal_live_intent(
        root=root,
        repo_root=repo_root,
        proposal=proposal,
        state_sha256=synced.canonical_after_sha256,
        receipt_id=synced.sync_receipt_id,
        receipt_sha256=sync_module._digest(receipt.canonical_json_bytes()),
        recorded_at=recorded.isoformat(),
        expires_at=expires.isoformat(),
        overrides=overrides,
    )


def test_activation_rechecks_expiry_after_waiting_for_state_lock(
    tmp_path, monkeypatch
) -> None:
    """A lock wait cannot preserve the active timestamp captured before it."""

    if os.environ.get(_CAPPED_ACTIVATION_ISOLATED_ENV) != "1":
        _run_capped_activation_in_isolated_repo(
            tmp_path,
            "tests/test_strategy_promotion_sync.py::"
            "test_activation_rechecks_expiry_after_waiting_for_state_lock",
        )
        return
    root, repo_root, proposal, synced_at, _commit = _capped_activation_journal(
        tmp_path, monkeypatch
    )
    state = tmp_path / "promotion.json"
    intent = _sync_capped_activation_state(
        root=root,
        repo_root=repo_root,
        proposal=proposal,
        state=state,
        synced_at=synced_at,
    )
    before = state.read_bytes()
    entered = Event()
    release = Event()
    moment = {"value": synced_at}
    original_lock = sync_module.promotion_state_lock

    @contextmanager
    def delayed_lock(path: Path):
        with original_lock(path):
            entered.set()
            assert release.wait(timeout=5)
            yield

    monkeypatch.setattr(sync_module, "promotion_state_lock", delayed_lock)
    with ThreadPoolExecutor(max_workers=1) as executor:
        result = executor.submit(
            sync_module.activate_normal_live_intent,
            proposal,
            intent,
            proposal_ledger_root=root,
            repo_root=repo_root,
            state_path=state,
            clock=lambda: moment["value"],
        )
        assert entered.wait(timeout=5)
        moment["value"] = datetime.fromisoformat(intent.expires_at)
        release.set()
        with pytest.raises(ValueError, match="active capped intent"):
            result.result(timeout=10)
    assert state.read_bytes() == before


def test_activation_rechecks_stale_6d_attestations_under_lock(
    tmp_path, monkeypatch
) -> None:
    """An active Task 2 intent cannot outlive the current 6D risk attestation."""

    if os.environ.get(_CAPPED_ACTIVATION_ISOLATED_ENV) != "1":
        _run_capped_activation_in_isolated_repo(
            tmp_path,
            "tests/test_strategy_promotion_sync.py::"
            "test_activation_rechecks_stale_6d_attestations_under_lock",
        )
        return
    root, repo_root, proposal, synced_at, _commit = _capped_activation_journal(
        tmp_path, monkeypatch
    )
    state = tmp_path / "promotion.json"
    stale_at = datetime.fromisoformat(proposal.risk_attestation.reviewed_at) + timedelta(
        seconds=901
    )
    intent = _sync_capped_activation_state(
        root=root,
        repo_root=repo_root,
        proposal=proposal,
        state=state,
        synced_at=synced_at,
        intent_recorded_at=stale_at,
        intent_expires_at=stale_at + timedelta(minutes=5),
    )
    before = state.read_bytes()

    with pytest.raises(ValueError, match="risk attestation is stale"):
        sync_module.activate_normal_live_intent(
            proposal,
            intent,
            proposal_ledger_root=root,
            repo_root=repo_root,
            state_path=state,
            clock=lambda: stale_at,
        )

    assert state.read_bytes() == before


def test_activation_rechecks_changed_6d_validation_report_under_lock(
    tmp_path, monkeypatch
) -> None:
    """A changed 6D validation source is rejected before a live-state write."""

    if os.environ.get(_CAPPED_ACTIVATION_ISOLATED_ENV) != "1":
        _run_capped_activation_in_isolated_repo(
            tmp_path,
            "tests/test_strategy_promotion_sync.py::"
            "test_activation_rechecks_changed_6d_validation_report_under_lock",
        )
        return
    root, repo_root, proposal, synced_at, _commit = _capped_activation_journal(
        tmp_path, monkeypatch
    )
    state = tmp_path / "promotion.json"
    intent = _sync_capped_activation_state(
        root=root,
        repo_root=repo_root,
        proposal=proposal,
        state=state,
        synced_at=synced_at,
    )
    before = state.read_bytes()
    report = repo_root / proposal.validation_attestation.report_ref
    report.write_text(report.read_text(encoding="utf-8") + "\nchanged", encoding="utf-8")
    monkeypatch.setattr(
        sync_module, "_require_clean_runtime_descendant", lambda *_args: None
    )

    with pytest.raises(ValueError, match="external promotion anchor changed"):
        sync_module.activate_normal_live_intent(
            proposal,
            intent,
            proposal_ledger_root=root,
            repo_root=repo_root,
            state_path=state,
            clock=lambda: synced_at,
        )

    assert state.read_bytes() == before


def test_activation_rejects_each_tampered_task2_evidence_binding(
    tmp_path, monkeypatch
) -> None:
    """Every Task 2 digest/value binding is checked against durable sources."""

    if os.environ.get(_CAPPED_ACTIVATION_ISOLATED_ENV) != "1":
        _run_capped_activation_in_isolated_repo(
            tmp_path,
            "tests/test_strategy_promotion_sync.py::"
            "test_activation_rejects_each_tampered_task2_evidence_binding",
        )
        return
    root, repo_root, proposal, synced_at, _commit = _capped_activation_journal(
        tmp_path, monkeypatch
    )
    replacements = {
        "promotion_proposal_id": "strategy-promotion-proposal-" + "0" * 64,
        "promotion_proposal_sha256": "0" * 64,
        "promotion_state_sha256": "0" * 64,
        "promotion_sync_receipt_id": "strategy-promotion-sync-receipt-" + "0" * 64,
        "promotion_sync_receipt_sha256": "0" * 64,
        "staged_intent_id": "staged-paper-intent-" + "0" * 64,
        "staged_intent_sha256": "0" * 64,
        "shadow_attestation_sha256": "0" * 64,
        "genome_id": "strategy-genome-" + "0" * 64,
        "genome_canonical_sha256": "0" * 64,
        "evaluation_code_commit": "0" * 40,
        "evaluation_runtime_sha256": "0" * 64,
        "market_observation_sha256": "0" * 64,
        "portfolio_snapshot_sha256": "0" * 64,
        "risk_snapshot_sha256": "0" * 64,
        "symbol": "AAPL",
        "notional_usd": "2.00",
        "limit_price": "101.00",
    }
    for field, replacement in replacements.items():
        state = tmp_path / f"{field}.json"
        intent = _sync_capped_activation_state(
            root=root,
            repo_root=repo_root,
            proposal=proposal,
            state=state,
            synced_at=synced_at,
            overrides={field: replacement},
        )
        before = state.read_bytes()
        with pytest.raises(ValueError):
            sync_module.activate_normal_live_intent(
                proposal,
                intent,
                proposal_ledger_root=root,
                repo_root=repo_root,
                state_path=state,
                clock=lambda: synced_at,
            )
        assert state.read_bytes() == before, field


def test_activation_rejects_active_intent_with_uncapped_risk_evidence(
    tmp_path, monkeypatch
) -> None:
    """Uncapped risk evidence is rejected independently of intent expiry."""

    if os.environ.get(_CAPPED_ACTIVATION_ISOLATED_ENV) != "1":
        _run_capped_activation_in_isolated_repo(
            tmp_path,
            "tests/test_strategy_promotion_sync.py::"
            "test_activation_rejects_active_intent_with_uncapped_risk_evidence",
        )
        return
    root, repo_root, proposal, synced_at, _commit = _capped_activation_journal(
        tmp_path, monkeypatch
    )
    uncapped = tmp_path / "uncapped-risk-envelope.yaml"
    uncapped.write_text("new_sleeve_auto_promote: false\n", encoding="utf-8")
    state = tmp_path / "promotion.json"
    intent = _sync_capped_activation_state(
        root=root,
        repo_root=repo_root,
        proposal=proposal,
        state=state,
        synced_at=synced_at,
        overrides={"risk_snapshot_sha256": sync_module._digest(uncapped.read_bytes())},
    )
    before = state.read_bytes()

    with pytest.raises(ValueError, match="active capped intent"):
        sync_module.activate_normal_live_intent(
            proposal,
            intent,
            proposal_ledger_root=root,
            repo_root=repo_root,
            state_path=state,
            clock=lambda: synced_at,
        )

    assert state.read_bytes() == before


def test_activation_is_one_use_and_duplicate_is_read_only_retry(
    tmp_path, monkeypatch
) -> None:
    if os.environ.get(_CAPPED_ACTIVATION_ISOLATED_ENV) != "1":
        _run_capped_activation_in_isolated_repo(
            tmp_path,
            "tests/test_strategy_promotion_sync.py::"
            "test_activation_is_one_use_and_duplicate_is_read_only_retry",
        )
        return
    root, repo_root, proposal, synced_at, _commit = _capped_activation_journal(
        tmp_path, monkeypatch
    )
    state = tmp_path / "promotion.json"
    preimage = b'{"sleeves":{}}'
    state.write_bytes(preimage)
    synced = sync_module.sync_strategy_promotion_state_file(
        proposal_ledger_root=root,
        repo_root=repo_root,
        proposal=proposal,
        state_path=state,
        expected_current_state_sha256=sync_module._digest(preimage),
        actor_role="strategy_learning",
        clock=lambda: synced_at,
    )
    receipt = next(
        item
        for item in sync_module.ImmutableStrategyEvidenceStore(root).rebuild()
        if item.object_id == synced.sync_receipt_id
    )
    intent = _complete_normal_live_intent(
        root=root,
        repo_root=repo_root,
        proposal=proposal,
        state_sha256=synced.canonical_after_sha256,
        receipt_id=synced.sync_receipt_id,
        receipt_sha256=sync_module._digest(receipt.canonical_json_bytes()),
        recorded_at=synced_at.isoformat(),
        expires_at=(synced_at + timedelta(minutes=5)).isoformat(),
    )

    first = sync_module.activate_normal_live_intent(
        proposal, intent, proposal_ledger_root=root, repo_root=repo_root,
        state_path=state, clock=lambda: synced_at,
    )
    bytes_after_first = state.read_bytes()
    retry = sync_module.activate_normal_live_intent(
        proposal, intent, proposal_ledger_root=root, repo_root=repo_root,
        state_path=state, clock=lambda: synced_at,
    )

    assert first.status == "activated"
    assert first.created is True
    assert json.loads(state.read_text())["sleeves"][proposal.sleeve]["live_enabled"] is True
    assert retry.status == "read_only_retry"
    assert retry.created is False
    assert state.read_bytes() == bytes_after_first


@pytest.mark.parametrize("boundary", ("after_prepare", "after_replace"))
def test_activation_crash_repair_never_widens_the_bound_intent(
    tmp_path, monkeypatch, boundary
) -> None:
    if os.environ.get(_CAPPED_ACTIVATION_ISOLATED_ENV) != "1":
        _run_capped_activation_in_isolated_repo(
            tmp_path,
            "tests/test_strategy_promotion_sync.py::"
            f"test_activation_crash_repair_never_widens_the_bound_intent[{boundary}]",
        )
        return
    root, repo_root, proposal, synced_at, _commit = _capped_activation_journal(
        tmp_path, monkeypatch
    )
    state = tmp_path / "promotion.json"
    preimage = b'{"sleeves":{}}'
    state.write_bytes(preimage)
    synced = sync_module.sync_strategy_promotion_state_file(
        proposal_ledger_root=root,
        repo_root=repo_root,
        proposal=proposal,
        state_path=state,
        expected_current_state_sha256=sync_module._digest(preimage),
        actor_role="strategy_learning",
        clock=lambda: synced_at,
    )
    receipt = next(
        item
        for item in sync_module.ImmutableStrategyEvidenceStore(root).rebuild()
        if item.object_id == synced.sync_receipt_id
    )
    intent = _complete_normal_live_intent(
        root=root,
        repo_root=repo_root,
        proposal=proposal,
        state_sha256=synced.canonical_after_sha256,
        receipt_id=synced.sync_receipt_id,
        receipt_sha256=sync_module._digest(receipt.canonical_json_bytes()),
        recorded_at=synced_at.isoformat(),
        expires_at=(synced_at + timedelta(minutes=5)).isoformat(),
    )

    def crash(actual: str) -> None:
        if actual == boundary:
            raise SystemExit(actual)

    with pytest.raises(SystemExit, match=boundary):
        sync_module.activate_normal_live_intent(
            proposal, intent, proposal_ledger_root=root, repo_root=repo_root,
            state_path=state, clock=lambda: synced_at, fault_hook=crash,
        )
    repaired = sync_module.activate_normal_live_intent(
        proposal, intent, proposal_ledger_root=root, repo_root=repo_root,
        state_path=state, clock=lambda: synced_at,
    )

    assert repaired.status == (
        "activated" if boundary == "after_prepare" else "receipt_repaired"
    )
    assert json.loads(state.read_text())["sleeves"][proposal.sleeve]["live_enabled"] is True




def test_late_external_anchor_drift_after_recompute_refuses_prepare_and_state(
    tmp_path,
    monkeypatch,
) -> None:
    """A report changed after durable recomputation cannot reach prepare admission."""
    state = tmp_path / "promotion.json"
    preimage = b'{"sleeves":{}}'
    state.write_bytes(preimage)
    report = tmp_path / "report.json"
    report.write_text("report")
    risk = tmp_path / "risk.yaml"
    risk.write_text("risk")
    proposal, _digest = _controlled_proposal()
    Proposal = type(proposal)
    candidates: list[object] = []

    class Store:
        def envelopes(self, **_kwargs):
            return ()

        def admit_checked(self, candidate, **_kwargs):
            candidates.append(candidate)
            pytest.fail("late external-anchor drift must not admit a prepare")

    monkeypatch.setattr(sync_module, "StrategyPromotionProposal", Proposal)
    monkeypatch.setattr(
        sync_module,
        "StrategyOperationalPromotionLedger",
        lambda *args, **kwargs: SimpleNamespace(rebuild=lambda: (proposal,)),
    )
    monkeypatch.setattr(sync_module, "ImmutableStrategyEvidenceStore", lambda *args, **kwargs: Store())
    monkeypatch.setattr(
        sync_module,
        "_git",
        lambda _root, *args: proposal.promotion_runtime_commit
        if args[0] == "rev-parse"
        else "",
    )
    monkeypatch.setattr(
        sync_module,
        "_safe_repo_file",
        lambda _root, reference, _label: (tmp_path / reference, str(reference)),
    )

    def mutate_report_after_recompute(**_kwargs):
        report.write_text("changed after recompute")
        return None

    monkeypatch.setattr(
        sync_module,
        "_require_durable_source_recomputation",
        mutate_report_after_recompute,
    )

    with pytest.raises(ValueError, match="external promotion anchor drift"):
        sync_module.sync_strategy_promotion_state_file(
            proposal_ledger_root=tmp_path,
            repo_root=tmp_path,
            proposal=proposal,
            state_path=state,
            expected_current_state_sha256=sync_module._digest(preimage),
            actor_role="strategy_learning",
            clock=lambda: datetime(2026, 7, 28, 12, tzinfo=timezone.utc),
        )

    assert candidates == []
    assert state.read_bytes() == preimage
