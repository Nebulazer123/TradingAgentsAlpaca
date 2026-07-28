"""Contract tests for immutable strategy-promotion proposals."""

import datetime as dt
import subprocess
from pathlib import Path

import pytest

from tradingagents.orchestration.authority import ActionClass, authority_for
from tradingagents.policy.strategy_promotion import (
    REQUIRED_STRATEGY_PROMOTION_VALIDATION_COMMANDS,
    StrategyPromotionProposal,
    StrategyRiskAttestation,
    StrategyValidationAttestation,
    build_risk_attestation,
    build_validation_attestation,
)


def _clean_git_repo(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "tests@example.invalid"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Tests"], cwd=repo, check=True)
    (repo / "artifacts").mkdir()
    (repo / "artifacts" / "validation.json").write_text("{}", encoding="utf-8")
    (repo / "config").mkdir()
    (repo / "config" / "risk.yaml").write_text(
        "\n".join(
            (
                "live_budget_mode: fixed_tranche",
                "account_max_capital_at_risk_usd: 100",
                "per_name_cap_usd: 100",
                "per_sector_cap_pct: 0.20",
                "aggregate_beta_cap: 1.25",
                "daily_loss_halt_usd: 10",
                "max_drawdown_halt_pct: 0.05",
                "tiny_live_tranche_usd: 10",
                "tiny_live_max_loss_usd: 2",
                "new_sleeve_auto_promote: true",
                "alert_email: tests@example.invalid",
            )
        ),
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "fixture"], cwd=repo, check=True)
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, text=True, capture_output=True
    ).stdout.strip()
    return repo, commit


def _validation_attestation(**changes: object) -> StrategyValidationAttestation:
    values: dict[str, object] = {
        "tested_commit": "a" * 40,
        "completed_at": "2026-07-28T12:00:00+00:00",
        "commands": REQUIRED_STRATEGY_PROMOTION_VALIDATION_COMMANDS,
        "exit_code": 0,
        "report_ref": "artifacts/validation.json",
        "report_sha256": "b" * 64,
        "verifier_role": authority_for(ActionClass.VERIFY).owner_role,
    }
    values.update(changes)
    return StrategyValidationAttestation(**values)  # type: ignore[arg-type]


def test_validation_attestation_ci_green_requires_safe_repo_relative_ref() -> None:
    assert _validation_attestation().ci_green is True


@pytest.mark.parametrize(
    "report_ref",
    ("", "/tmp/validation.json", "../validation.json", "artifacts/../validation.json", "./artifacts/validation.json", "artifacts//validation.json"),
)
def test_validation_attestation_rejects_unsafe_report_ref_at_construction(report_ref: str) -> None:
    with pytest.raises(ValueError, match="report_ref"):
        _validation_attestation(report_ref=report_ref)


def test_validation_attestation_rejects_unknown_schema_fields() -> None:
    payload = _validation_attestation().to_dict()
    payload["unknown"] = "nope"
    with pytest.raises(ValueError, match="fields do not match schema"):
        StrategyValidationAttestation.from_dict(payload)


def test_validation_attestation_ci_green_requires_exact_commands_and_exit_code() -> None:
    assert _validation_attestation(commands=()).ci_green is False
    assert _validation_attestation(exit_code=1).ci_green is False


def test_real_builders_refuse_repo_internal_symlink_references(tmp_path) -> None:
    """A symlink inside a clean checkout cannot substitute for an anchored file."""
    repo, commit = _clean_git_repo(tmp_path)
    (repo / "artifacts" / "validation-link.json").symlink_to("validation.json")
    (repo / "config" / "risk-link.yaml").symlink_to("risk.yaml")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "symlink fixture"], cwd=repo, check=True)
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, text=True, capture_output=True
    ).stdout.strip()
    at = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)

    with pytest.raises(ValueError, match="cannot use symlinks"):
        build_validation_attestation(
            repo_root=repo,
            tested_commit=commit,
            completed_at=at,
            commands=REQUIRED_STRATEGY_PROMOTION_VALIDATION_COMMANDS,
            exit_code=0,
            report_ref="artifacts/validation-link.json",
            verifier_role=authority_for(ActionClass.VERIFY).owner_role,
            clock=lambda: at,
        )
    with pytest.raises(ValueError, match="cannot use symlinks"):
        build_risk_attestation(
            repo_root=repo,
            risk_envelope_ref="config/risk-link.yaml",
            reviewed_at=at,
            reviewer_role=authority_for(ActionClass.RISK_CHANGE).owner_role,
            clock=lambda: at,
        )


@pytest.mark.parametrize(
    ("tested_commit", "dirty", "error"),
    [
        ("0" * 40, False, "validation checkout must be current and clean"),
        (None, True, "validation checkout must be current and clean"),
    ],
)
def test_real_validation_builder_refuses_wrong_commit_and_dirty_checkout(
    tmp_path,
    tested_commit,
    dirty,
    error,
) -> None:
    repo, commit = _clean_git_repo(tmp_path)
    if dirty:
        (repo / "untracked.txt").write_text("dirty", encoding="utf-8")
    at = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    with pytest.raises(ValueError, match=error):
        build_validation_attestation(
            repo_root=repo,
            tested_commit=commit if tested_commit is None else tested_commit,
            completed_at=at,
            commands=REQUIRED_STRATEGY_PROMOTION_VALIDATION_COMMANDS,
            exit_code=0,
            report_ref="artifacts/validation.json",
            verifier_role=authority_for(ActionClass.VERIFY).owner_role,
            clock=lambda: at,
        )


def _risk_attestation(**changes: object) -> StrategyRiskAttestation:
    values: dict[str, object] = {
        "risk_envelope_ref": "config/risk_envelope.yaml",
        "risk_envelope_sha256": "c" * 64,
        "live_budget_mode": "fixed_tranche",
        "account_max_capital_at_risk_usd": "500",
        "per_name_cap_usd": "300",
        "account_hard_ceiling_usd": None,
        "tiny_live_tranche_usd": "100",
        "tiny_live_max_loss_usd": "10",
        "max_drawdown_halt_fraction": "0.08",
        "new_sleeve_auto_promote": True,
        "reviewed_at": "2026-07-28T12:00:00+00:00",
        "reviewer_role": authority_for(ActionClass.RISK_CHANGE).owner_role,
    }
    values.update(changes)
    return StrategyRiskAttestation(**values)  # type: ignore[arg-type]


def test_risk_attestation_rejects_non_fraction_drawdown_units() -> None:
    with pytest.raises(ValueError, match="max_drawdown_halt_fraction"):
        _risk_attestation(max_drawdown_halt_fraction="2")


@pytest.mark.parametrize(
    ("ceiling", "expected"),
    [(None, "300"), ("50", "50"), ("100", "100"), ("700", "300")],
)
def test_risk_attestation_capacity_applies_optional_hard_ceiling(ceiling: str | None, expected: str) -> None:
    assert _risk_attestation(account_hard_ceiling_usd=ceiling).capacity_usd == pytest.approx(float(expected))


@pytest.mark.parametrize("value", ["0", "-1", "01", "not-money"])
def test_risk_attestation_rejects_malformed_hard_ceiling(value: str) -> None:
    with pytest.raises((TypeError, ValueError)):
        _risk_attestation(account_hard_ceiling_usd=value)


def test_risk_attestation_uncapped_mode_is_never_capped() -> None:
    assert _risk_attestation(live_budget_mode="autonomous_uncapped").capped_mode is False


@pytest.mark.parametrize(
    "risk_envelope_ref",
    ("", "/tmp/risk.yaml", "../risk.yaml", "config/../risk.yaml", "./config/risk.yaml", "config//risk.yaml"),
)
def test_risk_attestation_rejects_unsafe_envelope_ref_at_construction(
    risk_envelope_ref: str,
) -> None:
    with pytest.raises(ValueError, match="risk_envelope_ref"):
        _risk_attestation(risk_envelope_ref=risk_envelope_ref)


def _proposal(**changes: object) -> StrategyPromotionProposal:
    validation = _validation_attestation()
    risk = _risk_attestation()
    values: dict[str, object] = {
        "proposal_id": "strategy-promotion-proposal-" + "d" * 64,
        "sleeve": "current_aggressive",
        "registration_id": "evaluation-registration-" + "1" * 64,
        "promotion_evidence_id": "promotion-evidence-" + "2" * 64,
        "promotion_evidence_sha256": "3" * 64,
        "shadow_attestation_id": "paper-shadow-attestation-" + "4" * 64,
        "shadow_attestation_sha256": "5" * 64,
        "validation_attestation": validation,
        "validation_attestation_sha256": __import__("hashlib").sha256(validation.canonical_json_bytes()).hexdigest(),
        "risk_attestation": risk,
        "risk_attestation_sha256": __import__("hashlib").sha256(risk.canonical_json_bytes()).hexdigest(),
        "genome_id": "genome-current-aggressive-" + "6" * 32,
        "genome_canonical_sha256": "7" * 64,
        "evaluation_code_commit": "8" * 40,
        "evaluation_runtime_sha256": "9" * 64,
        "promotion_runtime_commit": "a" * 40,
        "benchmark_excess_return_fraction": "0.01",
        "cost_adjusted_alpha_fraction": "0.01",
        "recent_alpha_fraction": "0.01",
        "capacity_usd": "300",
        "requested_tiny_live_tranche_usd": "100",
        "admission_invariants": (
            "internal_evidence_complete",
            "preregistered_schedule",
            "identity_chain_complete",
            "evaluation_code_commit_bound",
            "evaluation_runtime_bound",
            "benchmark_gate_already_passed",
            "cost_gate_already_passed",
            "recent_alpha_gate_already_passed",
            "validation_report_present",
            "risk_envelope_ref_present",
            "promotion_authority_confirmed",
            "internal_evidence_current",
            "validation_attestation_current",
            "shadow_attestation_current",
            "risk_attestation_current",
        ),
        "gates": (
            ("ci_green", True),
            ("shadow_sessions_sufficient", True),
            ("reconciliation_confirmed", True),
            ("capacity_gate_passed", True),
            ("risk_budget_mode_capped", True),
            ("risk_auto_promotion_allowed", True),
        ),
        "issues": (),
        "proposed_stage": "tiny_live_eligible",
        "expires_at": "2026-07-28T12:05:00+00:00",
        "effective_at": "2026-07-28T12:00:00+00:00",
        "recorded_at": "2026-07-28T12:00:01+00:00",
    }
    values.update(changes)
    return StrategyPromotionProposal(**values)  # type: ignore[arg-type]


def test_proposal_requires_exact_admission_invariant_order() -> None:
    with pytest.raises(ValueError, match="admission_invariants"):
        _proposal(admission_invariants=("identity_chain_complete",))


def test_proposal_requires_failed_gate_issues_in_frozen_order() -> None:
    gates = list(_proposal().gates)
    gates[1] = ("shadow_sessions_sufficient", False)
    gates[5] = ("risk_auto_promotion_allowed", False)
    with pytest.raises(ValueError, match="issues"):
        _proposal(
            gates=tuple(gates),
            issues=("risk_auto_promotion_disabled", "shadow_sessions_sufficient"),
            proposed_stage="paper_only",
        )


@pytest.mark.parametrize(
    ("failed_gate", "issue"),
    (
        ("ci_green", "ci_green"),
        ("shadow_sessions_sufficient", "shadow_sessions_sufficient"),
        ("reconciliation_confirmed", "reconciliation_confirmed"),
        ("capacity_gate_passed", "capacity_gate_passed"),
        ("risk_budget_mode_capped", "risk_budget_mode_not_capped"),
        ("risk_auto_promotion_allowed", "risk_auto_promotion_disabled"),
    ),
)
def test_each_operational_gate_has_a_paper_only_demotion_outcome(
    failed_gate: str,
    issue: str,
) -> None:
    """Each independently reachable gate has one durable, disabled outcome."""
    gates = tuple(
        (name, False if name == failed_gate else passed)
        for name, passed in _proposal().gates
    )
    proposal = _proposal(
        gates=gates,
        issues=(issue,),
        proposed_stage="paper_only",
    )

    assert proposal.proposed_stage == "paper_only"
    assert proposal.proposed_live_enabled is False
    assert proposal.issues == (issue,)
    assert dict(proposal.gates)[failed_gate] is False


def test_proposal_requires_full_immutable_object_ids() -> None:
    with pytest.raises(ValueError, match="proposal_id"):
        _proposal(proposal_id="strategy-promotion-proposal-not-a-full-digest")
