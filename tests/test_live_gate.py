import copy
import datetime
import hashlib
import json
from decimal import Decimal

import pytest

from tradingagents.brokers.alpaca_supervisor import (
    HourlySupervisorAction,
    validate_supervisor_live_submit_allowed,
)
from tradingagents.brokers.supervisor.loss_review import loss_exit_review_packet
from tradingagents.policy import live_gate as live_gate_module
from tradingagents.policy.exit_policy import apply_exit_policy_to_position
from tradingagents.policy.live_gate import LiveGateError, evaluate_go_live_guard
from tradingagents.policy.order_rate_limit import record_live_order_submission
from tradingagents.policy.promotion_sync import sync_promotion_state_file
from tradingagents.policy.risk_envelope import load_risk_envelope


def _write_envelope(
    path,
    *,
    live_budget_mode=None,
    per_name_cap_usd="50.00",
    account_hard_ceiling_usd=None,
    max_live_orders_per_window=None,
    live_order_window_minutes=None,
):
    lines = [
        "account_max_capital_at_risk_usd: 250.00",
        f"per_name_cap_usd: {per_name_cap_usd}",
        "per_sector_cap_pct: 0.20",
        "aggregate_beta_cap: 1.25",
        "daily_loss_halt_usd: 25.00",
        "max_drawdown_halt_pct: 0.05",
        "tiny_live_tranche_usd: 25.00",
        "tiny_live_max_loss_usd: 5.00",
        "new_sleeve_auto_promote: false",
        "alert_email: ops@example.com",
    ]
    if live_budget_mode:
        lines.append(f"live_budget_mode: {live_budget_mode}")
    if account_hard_ceiling_usd is not None:
        lines.append(f"account_hard_ceiling_usd: {account_hard_ceiling_usd}")
    if max_live_orders_per_window is not None:
        lines.append(f"max_live_orders_per_window: {max_live_orders_per_window}")
    if live_order_window_minutes is not None:
        lines.append(f"live_order_window_minutes: {live_order_window_minutes}")
    path.write_text(
        "\n".join(lines),
        encoding="utf-8",
    )


def _write_live_control(path, *, frozen=False, expires_at="2026-06-01T16:00:00+00:00"):
    path.write_text(
        json.dumps(
            {
                "frozen": frozen,
                "reason": "test control state",
                "dead_man_expires_at": expires_at,
            }
        ),
        encoding="utf-8",
    )


def test_risk_loader_rejects_retired_uncapped_mode(tmp_path):
    path = tmp_path / "risk.yaml"
    _write_envelope(path, live_budget_mode="autonomous_uncapped")
    envelope, issues = load_risk_envelope(path)

    assert envelope is None
    assert issues == [
        "live_budget_mode must be one of: autonomous_with_caps, fixed_tranche"
    ]


def test_live_gate_never_treats_uncapped_as_live_budget(tmp_path):
    envelope_path = tmp_path / "risk.yaml"
    _write_envelope(envelope_path, live_budget_mode="autonomous_uncapped")

    result = evaluate_go_live_guard(
        [_tiny_live_action()], risk_envelope_path=envelope_path
    )

    assert result.allowed is False
    assert any("live_budget_mode" in issue.reason for issue in result.issues)


#: Fresh for every gate clock used in this module (2026-06-01/03) while
#: staying strictly canonical UTC whole-second +00:00.
_LEGACY_FIXTURE_REPORT_STAMP = "2026-05-30T00:00:00+00:00"


def _promotion_record(**overrides):
    record = {
        "stage": "tiny_live_eligible",
        "live_enabled": True,
        "preregistered": True,
        "ci_green": True,
        "shadow_confirmed": True,
        "benchmark_gate_passed": True,
        "cost_gate_passed": True,
        "recent_alpha_gate_passed": True,
        "capacity_gate_passed": True,
        "validation_report_ref": "results/validation/pullback-support.json",
        "risk_envelope_ref": "config/risk_envelope.yaml",
        "source": {
            "kind": "paper_tournament",
            "tournament_id": "paper-tournament-freshness",
            "report_generated_at": _LEGACY_FIXTURE_REPORT_STAMP,
            "candidate_reason": "positive paper strategy",
        },
        "evidence_metrics": _persisted_evidence_metrics(),
    }
    record.update(overrides)
    return record


def _tiny_live_action(**overrides):
    values = {
        "action": "buy",
        "symbol": "MSFT",
        "notional": Decimal("20.00"),
        "limit_price": Decimal("410.00"),
        "side": "buy",
        "order_type": "limit",
        "reason": "promoted tiny-live sleeve",
        "account": "live",
        "execution_mode": "tiny_live",
        "sleeve": "pullback-support",
    }
    values.update(overrides)
    return HourlySupervisorAction(**values)


def _write_open_live_gate_inputs(tmp_path):
    envelope_path = tmp_path / "risk_envelope.yaml"
    promotion_path = tmp_path / "promotion.json"
    control_path = tmp_path / "live_control.json"
    _write_envelope(envelope_path, live_budget_mode="autonomous_with_caps")
    _write_live_control(control_path, expires_at="2026-06-03T16:00:00+00:00")
    promotion_path.write_text(
        json.dumps({"sleeves": {"pullback-support": _promotion_record()}}),
        encoding="utf-8",
    )
    return envelope_path, promotion_path, control_path


def test_live_gate_rejects_explicit_missing_autonomous_promotion_proof_before_io(
    tmp_path, monkeypatch
):
    envelope_path, promotion_path, control_path = _write_open_live_gate_inputs(
        tmp_path
    )
    reached = []
    monkeypatch.setattr(
        live_gate_module,
        "load_risk_envelope",
        lambda *_args, **_kwargs: reached.append("canonical gate") or (None, []),
    )

    with pytest.raises(LiveGateError):
        evaluate_go_live_guard(
            actions=[_tiny_live_action()],
            risk_envelope_path=envelope_path,
            promotion_state_path=promotion_path,
            control_state_path=control_path,
            live_buying_power=Decimal("100.00"),
            now=datetime.datetime(2026, 6, 3, 15, 0, tzinfo=datetime.timezone.utc),
            promotion_evidence=None,
        )

    assert reached == []


def test_live_gate_rejects_forged_normal_intent_before_io(tmp_path, monkeypatch):
    envelope_path, promotion_path, control_path = _write_open_live_gate_inputs(
        tmp_path
    )
    reached = []
    monkeypatch.setattr(
        live_gate_module,
        "load_risk_envelope",
        lambda *_args, **_kwargs: reached.append("canonical gate") or (None, []),
    )

    with pytest.raises(LiveGateError):
        evaluate_go_live_guard(
            actions=[_tiny_live_action()],
            risk_envelope_path=envelope_path,
            promotion_state_path=promotion_path,
            control_state_path=control_path,
            live_buying_power=Decimal("100.00"),
            now=datetime.datetime(2026, 6, 3, 15, 0, tzinfo=datetime.timezone.utc),
            normal_intent={"live_submit_authorized": True},
        )

    assert reached == []


@pytest.fixture(scope="module")
def _real_autonomous_live_gate_bundle(tmp_path_factory):
    """One genuine durable activation chain shared by adversarial gate checks."""

    from tests import test_strategy_staged_intent as staged_intent_tests
    from tests.test_alpaca_execution import (
        _activation_state_path,
        _real_normal_live_activation,
    )
    from tests.test_strategy_promotion_sync import _copy_isolated_source_tamper_repo
    from tradingagents.policy import strategy_promotion_sync as sync_module
    from tradingagents.strategy._immutable_evidence_store import (
        ImmutableStrategyEvidenceStore,
    )
    from tradingagents.strategy.promotion_evidence import StrategyPromotionEvidence

    patcher = pytest.MonkeyPatch()
    tmp_path = tmp_path_factory.mktemp("live-gate-authority")
    try:
        fixture_repo = _copy_isolated_source_tamper_repo(tmp_path / "fixture-source")
        patcher.setattr(staged_intent_tests, "REPO_ROOT", fixture_repo)
        root, repo_root, intent, receipt, activated_at = _real_normal_live_activation(
            tmp_path, patcher
        )
        patcher.setattr(
            sync_module,
            "_normal_live_policy_utc_now",
            lambda: activated_at,
        )
        state_path = _activation_state_path(root, receipt)
        activation = receipt.state["normal_live_activation"]
        sleeve_name = activation["sleeve"]
        source = receipt.state["sleeves"][sleeve_name]["source"]
        promotion_evidence = StrategyPromotionEvidence.from_envelope(
            next(
                envelope
                for envelope in ImmutableStrategyEvidenceStore(root).rebuild()
                if envelope.object_id == source["promotion_evidence_id"]
            )
        )
        yield {
            "root": root,
            "repo_root": repo_root,
            "intent": intent,
            "receipt": receipt,
            "promotion_evidence": promotion_evidence,
            "activated_at": activated_at,
            "state_path": state_path,
            "sleeve": sleeve_name,
        }
    finally:
        patcher.undo()


def _real_autonomous_gate_call(tmp_path, bundle, **overrides):
    activated_at = bundle["activated_at"]
    envelope_path = tmp_path / "risk_envelope.yaml"
    control_path = tmp_path / "live_control.json"
    _write_envelope(
        envelope_path,
        live_budget_mode="autonomous_with_caps",
        per_name_cap_usd="100.00",
    )
    _write_live_control(
        control_path,
        expires_at=(activated_at + datetime.timedelta(hours=1)).isoformat(),
    )
    values = {
        "actions": [
            _tiny_live_action(
                symbol=bundle["intent"].symbol,
                notional=Decimal(bundle["intent"].notional_usd),
                limit_price=Decimal(bundle["intent"].limit_price),
                sleeve=bundle["sleeve"],
            )
        ],
        "risk_envelope_path": envelope_path,
        "promotion_state_path": bundle["state_path"],
        "control_state_path": control_path,
        "live_buying_power": Decimal("100.00"),
        "now": activated_at,
        "normal_live_client_order_id": bundle["intent"].client_order_id,
        "promotion_evidence": bundle["promotion_evidence"],
        "normal_intent": bundle["intent"],
        "activation_receipt": bundle["receipt"],
        "proposal_ledger_root": bundle["root"],
        "repo_root": bundle["repo_root"],
    }
    values.update(overrides)
    return evaluate_go_live_guard(**values)


def test_live_gate_accepts_one_exact_durable_autonomous_bundle(
    tmp_path, _real_autonomous_live_gate_bundle
):
    result = _real_autonomous_gate_call(
        tmp_path,
        _real_autonomous_live_gate_bundle,
    )

    assert result.allowed is True
    assert result.issues == []
    assert result.checks["autonomous_authority_proofs"] is True


@pytest.mark.parametrize(
    "field",
    (
        "promotion_evidence",
        "normal_intent",
        "activation_receipt",
        "proposal_ledger_root",
        "repo_root",
    ),
)
def test_live_gate_requires_the_complete_autonomous_bundle(
    tmp_path, _real_autonomous_live_gate_bundle, field
):
    with pytest.raises(LiveGateError):
        _real_autonomous_gate_call(
            tmp_path,
            _real_autonomous_live_gate_bundle,
            **{field: None},
        )


@pytest.mark.parametrize(
    "case",
    (
        "missing_activation",
        "malformed_activation",
        "missing_marker",
        "malformed_marker",
        "conflicting_marker",
        "extra_activation_field",
        "conflicting_activation_field",
        "altered_current_state",
    ),
)
def test_live_gate_rejects_nonexact_current_activation_state(
    tmp_path, _real_autonomous_live_gate_bundle, case
):
    state_path = _real_autonomous_live_gate_bundle["state_path"]
    before = state_path.read_bytes()
    state = json.loads(before)
    activation = state.get("normal_live_activation")
    if case == "missing_activation":
        state.pop("normal_live_activation")
    elif case == "malformed_activation":
        state["normal_live_activation"] = []
    elif case == "missing_marker":
        activation.pop("marker")
    elif case == "malformed_marker":
        activation["marker"] = "not-a-canonical-sha256"
    elif case == "conflicting_marker":
        activation["marker"] = "0" * 64
    elif case == "extra_activation_field":
        activation["unexpected"] = True
    elif case == "conflicting_activation_field":
        activation["proposal_id"] = "promotion-proposal-" + "0" * 64
    else:
        state["sleeves"][_real_autonomous_live_gate_bundle["sleeve"]][
            "validation_report_ref"
        ] = "results/validation/altered.json"
    state_path.write_text(json.dumps(state), encoding="utf-8")
    try:
        with pytest.raises(LiveGateError):
            _real_autonomous_gate_call(
                tmp_path,
                _real_autonomous_live_gate_bundle,
            )
    finally:
        state_path.write_bytes(before)


@pytest.mark.parametrize(
    "field,replacement",
    (
        ("promotion_proposal_id", "promotion-proposal-" + "0" * 64),
        ("promotion_proposal_sha256", "0" * 64),
        ("promotion_state_sha256", "0" * 64),
        ("promotion_sync_receipt_id", "strategy-promotion-sync-receipt-" + "0" * 64),
        ("promotion_sync_receipt_sha256", "0" * 64),
        ("staged_intent_id", "staged-live-intent-" + "0" * 64),
        ("staged_intent_sha256", "0" * 64),
        ("shadow_attestation_sha256", "0" * 64),
        ("evaluation_code_commit", "0" * 40),
        ("evaluation_runtime_sha256", "0" * 64),
        ("market_observation_sha256", "0" * 64),
        ("portfolio_snapshot_sha256", "0" * 64),
        ("risk_snapshot_sha256", "0" * 64),
    ),
)
def test_live_gate_rejects_every_mismatched_durable_intent_binding(
    tmp_path, _real_autonomous_live_gate_bundle, field, replacement
):
    forged = copy.copy(_real_autonomous_live_gate_bundle["intent"])
    object.__setattr__(forged, field, replacement)

    with pytest.raises(LiveGateError):
        _real_autonomous_gate_call(
            tmp_path,
            _real_autonomous_live_gate_bundle,
            normal_intent=forged,
        )


def test_live_gate_rejects_mismatched_supplied_promotion_evidence(
    tmp_path, _real_autonomous_live_gate_bundle
):
    forged = copy.copy(_real_autonomous_live_gate_bundle["promotion_evidence"])
    object.__setattr__(forged, "evidence_id", "promotion-evidence-" + "0" * 64)

    with pytest.raises(LiveGateError):
        _real_autonomous_gate_call(
            tmp_path,
            _real_autonomous_live_gate_bundle,
            promotion_evidence=forged,
        )


def test_live_gate_rejects_mismatched_activation_receipt(
    tmp_path, _real_autonomous_live_gate_bundle
):
    forged = copy.copy(_real_autonomous_live_gate_bundle["receipt"])
    object.__setattr__(forged, "canonical_after_sha256", "0" * 64)

    with pytest.raises(LiveGateError):
        _real_autonomous_gate_call(
            tmp_path,
            _real_autonomous_live_gate_bundle,
            activation_receipt=forged,
        )


def test_owned_alpaca_boundary_rejects_drifted_activation_before_any_broker_request(
    tmp_path, monkeypatch, _real_autonomous_live_gate_bundle
):
    """A genuine admission cannot carry changed activation state to Alpaca I/O."""

    from tests.test_alpaca_execution import (
        _bound_normal_live_order,
        _fake_live_client,
        _FakeLiveSession,
        _normal_live_admission,
    )
    from tradingagents.brokers import alpaca as alpaca_module

    bundle = _real_autonomous_live_gate_bundle
    intent = bundle["intent"]
    receipt = bundle["receipt"]
    activated_at = bundle["activated_at"]
    monkeypatch.setattr(
        alpaca_module,
        "_normal_live_utc_now",
        lambda: activated_at,
    )
    admission = _normal_live_admission(
        tmp_path,
        monkeypatch,
        root=bundle["root"],
        intent=intent,
        receipt=receipt,
        activated_at=activated_at,
    )
    session = _FakeLiveSession()
    client = _fake_live_client(
        bundle["root"],
        repo_root=bundle["repo_root"],
        session=session,
        clock=lambda: activated_at,
    )
    state_path = bundle["state_path"]
    before = state_path.read_bytes()
    state = json.loads(before)
    state["normal_live_activation"]["marker"] = "0" * 64
    state_path.write_text(json.dumps(state), encoding="utf-8")
    try:
        with pytest.raises(ValueError):
            client.submit_order(
                _bound_normal_live_order(intent),
                authorized_normal_trade_intent=intent,
                activation_receipt=receipt,
                supervisor_admission=admission,
            )
    finally:
        state_path.write_bytes(before)

    assert session.requests == []
    assert session.post_calls == 0


def _minimal_tournament_report():
    return {
        "generated_at": "2026-06-20T21:12:35+00:00",
        "tournament_id": "paper-tournament-byte-invariance",
        "rankings": [],
        "live_strategy_candidate": {"status": "none"},
    }


@pytest.mark.parametrize(
    "malformed",
    (
        b"\xff\xfe",
        b'{"sleeves":',
        b"[]",
        b'"not-an-object"',
        b"null",
    ),
    ids=("unreadable", "invalid-json", "array", "string", "null"),
)
def test_promotion_sync_rejects_existing_malformed_state_without_any_write(
    tmp_path, malformed
):
    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps(_minimal_tournament_report()), encoding="utf-8")
    state_path = tmp_path / "promotion.json"
    state_path.write_bytes(malformed)
    output_path = tmp_path / "staged" / "promotion.json"

    with pytest.raises(ValueError):
        sync_promotion_state_file(
            report_path,
            state_path,
            output_state_path=output_path,
            tiny_live_tranche_usd=Decimal("25"),
        )

    assert state_path.read_bytes() == malformed
    assert output_path.exists() is False


def _persisted_record_source():
    return {
        "kind": "paper_tournament",
        "tournament_id": "paper-tournament-byte-invariance",
        "report_generated_at": "2026-06-20T21:12:35+00:00",
        "candidate_reason": "positive paper strategy",
    }


def _persisted_evidence_metrics():
    return {
        "total_return": "5.00",
        "total_return_pct": "0.50",
        "max_drawdown_pct": "-0.10",
        "win_rate_pct": "60.00",
        "tracked_days": 5,
    }


@pytest.mark.parametrize(
    "malformed_state",
    (
        {"sleeves": []},
        {"sleeves": {"protected-sleeve": []}},
        {
            "schema_version": "1.0.0",
            "sleeves": {
                "protected-sleeve": _promotion_record(issues="not-a-list")
            },
        },
        {
            "schema_version": "1.0.0",
            "sleeves": {"protected-sleeve": _promotion_record(metrics=[])},
        },
        {
            "schema_version": "1.0.0",
            "sleeves": {
                "protected-sleeve": _promotion_record(
                    source=[],
                    evidence_metrics=_persisted_evidence_metrics(),
                )
            },
        },
        {
            "schema_version": "1.0.0",
            "sleeves": {
                "protected-sleeve": _promotion_record(
                    source=_persisted_record_source(),
                    evidence_metrics=[],
                )
            },
        },
        {
            "schema_version": "1.0.0",
            "sleeves": {
                "protected-sleeve": _promotion_record(
                    source={
                        **_persisted_record_source(),
                        "protected_authority": "unknown",
                    },
                    evidence_metrics=_persisted_evidence_metrics(),
                )
            },
        },
        {
            "schema_version": "1.0.0",
            "sleeves": {
                "protected-sleeve": _promotion_record(
                    source=_persisted_record_source(),
                    evidence_metrics={
                        **_persisted_evidence_metrics(),
                        "tracked_days": "5",
                    },
                )
            },
        },
        {
            "schema_version": "1.0.0",
            "sleeves": {
                "protected-sleeve": _promotion_record(
                    protected_nested_state={"authority": "unknown"}
                )
            },
        },
    ),
    ids=(
        "non-object-sleeves",
        "non-object-sleeve-record",
        "non-list-issues",
        "non-object-metrics",
        "non-object-source",
        "non-object-evidence-metrics",
        "extra-source-field",
        "invalid-evidence-metric-type",
        "unknown-nested-state",
    ),
)
def test_promotion_sync_rejects_malformed_nested_state_without_any_write(
    tmp_path, malformed_state
):
    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps(_minimal_tournament_report()), encoding="utf-8")
    state_path = tmp_path / "promotion.json"
    malformed = json.dumps(malformed_state, separators=(",", ":")).encode("utf-8")
    state_path.write_bytes(malformed)
    output_path = tmp_path / "staged" / "promotion.json"

    with pytest.raises(ValueError):
        sync_promotion_state_file(
            report_path,
            state_path,
            output_state_path=output_path,
            tiny_live_tranche_usd=Decimal("25"),
        )

    assert state_path.read_bytes() == malformed
    assert output_path.exists() is False


def test_promotion_sync_reaccepts_the_exact_schema_it_persisted(tmp_path):
    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps(_minimal_tournament_report()), encoding="utf-8")
    state_path = tmp_path / "promotion.json"
    state_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "sleeves": {"protected-sleeve": _promotion_record()},
            }
        ),
        encoding="utf-8",
    )
    fixed_now = datetime.datetime(2026, 6, 21, tzinfo=datetime.timezone.utc)
    sync_promotion_state_file(
        report_path,
        state_path,
        tiny_live_tranche_usd=Decimal("25"),
        now=fixed_now,
    )
    first_persisted = state_path.read_bytes()
    output_path = tmp_path / "staged" / "promotion.json"

    result = sync_promotion_state_file(
        report_path,
        state_path,
        output_state_path=output_path,
        tiny_live_tranche_usd=Decimal("25"),
        now=fixed_now,
    )

    assert state_path.read_bytes() == first_persisted
    assert output_path.exists() is True
    assert result.state["source"]["canonical_input_sha256"] == hashlib.sha256(
        first_persisted
    ).hexdigest()


def test_verified_commitment_never_bypasses_frozen_live_control(
    tmp_path, monkeypatch
):
    envelope_path, promotion_path, control_path = _write_open_live_gate_inputs(
        tmp_path
    )
    _write_live_control(
        control_path,
        frozen=True,
        expires_at="2026-06-03T16:00:00+00:00",
    )
    monkeypatch.setattr(
        live_gate_module,
        "verify_pending_normal_live_submission_commitment",
        lambda *args, **kwargs: None,
    )

    result = evaluate_go_live_guard(
        actions=[_tiny_live_action()],
        risk_envelope_path=envelope_path,
        promotion_state_path=promotion_path,
        control_state_path=control_path,
        live_buying_power=Decimal("100.00"),
        now=datetime.datetime(2026, 6, 3, 15, 0, tzinfo=datetime.timezone.utc),
        normal_live_commitment={"rate_reservation_sha256": "a" * 64},
        normal_live_intent_full_sha256="b" * 64,
        normal_live_order_payload_sha256="c" * 64,
        normal_live_client_order_id="ta-l-bound-order",
    )

    assert result.allowed is False
    assert result.checks["live_not_frozen"] is False
    assert any("live control state is frozen" in issue.reason for issue in result.issues)


def _approved_loss_review(**overrides):
    review = {
        "symbol": "ORCL",
        "side": "sell",
        "decision_id": "decision-current",
        "client_order_id": "ta-tiny-current-orcl-sell",
        "current_price": "233.37",
        "proposed_limit_price": "233.37",
        "average_entry_price": "243.85",
        "estimated_realized_loss": "-4.34",
        "unrealized_pnl_percent": "-0.0434",
        "holding_period_trading_days": 5,
        "opened_at": "2026-05-28T14:30:00+00:00",
        "recent_same_symbol_fills": [
            {
                "side": "buy",
                "filled_at": "2026-05-28T14:30:00+00:00",
                "filled_avg_price": "243.85",
            }
        ],
        "original_entry_thesis": "Support should hold unless the cloud guidance thesis breaks.",
        "current_thesis_status": "Thesis invalidated by company-specific guidance break.",
        "allowed_exit_reason": "thesis_invalidated",
        "allowed_exit_reason_source": "earnings_guidance_packet",
        "broad_market_context": {"spy": "flat", "qqq": "+0.2%"},
        "relative_performance_vs_SPY": "-3.1%",
        "relative_performance_vs_QQQ": "-3.3%",
        "sector_or_peer_context": "software peers flat to slightly positive",
        "company_specific_negative_news_check": "Company-specific guidance cut confirmed.",
        "earnings_guidance_or_filing_check": "Guidance cut broke the support thesis.",
        "why_hold_is_worse_than_sell": "The original catalyst broke and recovery odds are worse than cash.",
        "why_this_is_not_broad_market_red_day_noise": "SPY/QQQ are not driving the loss; company guidance is.",
        "confidence": "0.82",
        "evidence_generated_at": "2026-06-03T15:00:00+00:00",
        "source_packet_ids": ["earnings-guidance-packet"],
        "allowed": True,
        "blocked_reasons": [],
    }
    review.update(overrides)
    return review


def _loss_position(**overrides):
    position = {
        "symbol": "ORCL",
        "qty": "0.4101",
        "avg_entry_price": "243.85",
        "current_price": "233.37",
        "market_value": "95.66",
        "cost_basis": "100.00",
        "unrealized_pl": "-4.34",
        "unrealized_plpc": "-0.0434",
    }
    position.update(overrides)
    return position


def test_risk_envelope_requires_all_operational_limits(tmp_path):
    envelope_path = tmp_path / "risk_envelope.yaml"
    envelope_path.write_text("tiny_live_tranche_usd: 25\n", encoding="utf-8")

    envelope, issues = load_risk_envelope(envelope_path)

    assert envelope is None
    assert any("account_max_capital_at_risk_usd" in issue for issue in issues)


def test_live_gate_blocks_missing_risk_envelope(tmp_path):
    result = evaluate_go_live_guard(
        actions=[_tiny_live_action()],
        risk_envelope_path=tmp_path / "missing.yaml",
        promotion_state_path=tmp_path / "promotion.json",
    )

    assert result.allowed is False
    assert any("risk envelope" in issue.reason.lower() for issue in result.issues)


def test_live_gate_blocks_unpromoted_sleeve_even_with_envelope(tmp_path):
    envelope_path = tmp_path / "risk_envelope.yaml"
    _write_envelope(envelope_path)

    result = evaluate_go_live_guard(
        actions=[_tiny_live_action()],
        risk_envelope_path=envelope_path,
        promotion_state_path=tmp_path / "missing-promotion.json",
    )

    assert result.allowed is False
    assert any("promotion" in issue.reason.lower() for issue in result.issues)


def test_live_gate_allows_only_promoted_tiny_live_sleeve(tmp_path):
    envelope_path = tmp_path / "risk_envelope.yaml"
    promotion_path = tmp_path / "promotion.json"
    control_path = tmp_path / "live_control.json"
    _write_envelope(envelope_path)
    _write_live_control(control_path, expires_at="2026-06-03T16:00:00+00:00")
    promotion_path.write_text(
        json.dumps(
            {
                "sleeves": {
                    "pullback-support": _promotion_record()
                }
            }
        ),
        encoding="utf-8",
    )

    result = evaluate_go_live_guard(
        actions=[_tiny_live_action()],
        risk_envelope_path=envelope_path,
        promotion_state_path=promotion_path,
        control_state_path=control_path,
        live_buying_power=Decimal("100.00"),
        now=datetime.datetime(2026, 6, 1, 15, 0, tzinfo=datetime.timezone.utc),
    )

    assert result.allowed is True
    assert result.issues == []


def test_live_gate_autonomous_budget_allows_size_above_fixed_tranche(tmp_path):
    envelope_path = tmp_path / "risk_envelope.yaml"
    promotion_path = tmp_path / "promotion.json"
    control_path = tmp_path / "live_control.json"
    _write_envelope(envelope_path, live_budget_mode="autonomous_with_caps")
    _write_live_control(control_path, expires_at="2026-06-03T16:00:00+00:00")
    promotion_path.write_text(
        json.dumps({"sleeves": {"pullback-support": _promotion_record()}}),
        encoding="utf-8",
    )

    result = evaluate_go_live_guard(
        actions=[_tiny_live_action(notional=Decimal("45.00"))],
        risk_envelope_path=envelope_path,
        promotion_state_path=promotion_path,
        control_state_path=control_path,
        live_buying_power=Decimal("100.00"),
        now=datetime.datetime(2026, 6, 1, 15, 0, tzinfo=datetime.timezone.utc),
    )

    assert result.allowed is True
    assert result.checks["autonomous_live_budget"] is True


def test_live_gate_fixed_tranche_still_blocks_larger_size(tmp_path):
    envelope_path = tmp_path / "risk_envelope.yaml"
    promotion_path = tmp_path / "promotion.json"
    control_path = tmp_path / "live_control.json"
    _write_envelope(envelope_path)
    _write_live_control(control_path, expires_at="2026-06-03T16:00:00+00:00")
    promotion_path.write_text(
        json.dumps({"sleeves": {"pullback-support": _promotion_record()}}),
        encoding="utf-8",
    )

    result = evaluate_go_live_guard(
        actions=[_tiny_live_action(notional=Decimal("45.00"))],
        risk_envelope_path=envelope_path,
        promotion_state_path=promotion_path,
        control_state_path=control_path,
        now=datetime.datetime(2026, 6, 1, 15, 0, tzinfo=datetime.timezone.utc),
    )

    assert result.allowed is False
    assert any("tiny_live_tranche_usd" in issue.reason for issue in result.issues)


def test_live_gate_autonomous_budget_still_blocks_over_per_name_cap(tmp_path):
    envelope_path = tmp_path / "risk_envelope.yaml"
    promotion_path = tmp_path / "promotion.json"
    control_path = tmp_path / "live_control.json"
    _write_envelope(envelope_path, live_budget_mode="autonomous_with_caps")
    _write_live_control(control_path, expires_at="2026-06-03T16:00:00+00:00")
    promotion_path.write_text(
        json.dumps({"sleeves": {"pullback-support": _promotion_record()}}),
        encoding="utf-8",
    )

    result = evaluate_go_live_guard(
        actions=[_tiny_live_action(notional=Decimal("55.00"))],
        risk_envelope_path=envelope_path,
        promotion_state_path=promotion_path,
        control_state_path=control_path,
        now=datetime.datetime(2026, 6, 1, 15, 0, tzinfo=datetime.timezone.utc),
    )

    assert result.allowed is False
    assert any("per_name_cap_usd" in issue.reason for issue in result.issues)


def test_live_gate_autonomous_budget_counts_existing_live_exposure_for_new_buys(tmp_path):
    envelope_path = tmp_path / "risk_envelope.yaml"
    promotion_path = tmp_path / "promotion.json"
    control_path = tmp_path / "live_control.json"
    _write_envelope(envelope_path, live_budget_mode="autonomous_with_caps")
    _write_live_control(control_path, expires_at="2026-06-03T16:00:00+00:00")
    promotion_path.write_text(
        json.dumps({"sleeves": {"pullback-support": _promotion_record()}}),
        encoding="utf-8",
    )

    result = evaluate_go_live_guard(
        actions=[_tiny_live_action(notional=Decimal("40.00"))],
        risk_envelope_path=envelope_path,
        promotion_state_path=promotion_path,
        control_state_path=control_path,
        current_live_exposure=Decimal("225.00"),
        now=datetime.datetime(2026, 6, 1, 15, 0, tzinfo=datetime.timezone.utc),
    )

    assert result.allowed is False
    assert result.checks["current_live_exposure_considered"] is True
    assert any("projected live exposure" in issue.reason for issue in result.issues)


def test_live_gate_autonomous_budget_enforces_repo_dollar_caps(tmp_path):
    envelope_path = tmp_path / "risk_envelope.yaml"
    promotion_path = tmp_path / "promotion.json"
    control_path = tmp_path / "live_control.json"
    _write_envelope(envelope_path, live_budget_mode="autonomous_with_caps")
    _write_live_control(control_path, expires_at="2026-06-03T16:00:00+00:00")
    promotion_path.write_text(
        json.dumps({"sleeves": {"pullback-support": _promotion_record()}}),
        encoding="utf-8",
    )

    result = evaluate_go_live_guard(
        actions=[_tiny_live_action(notional=Decimal("275.00"))],
        risk_envelope_path=envelope_path,
        promotion_state_path=promotion_path,
        control_state_path=control_path,
        live_buying_power=Decimal("500.00"),
        now=datetime.datetime(2026, 6, 1, 15, 0, tzinfo=datetime.timezone.utc),
    )

    assert result.allowed is False
    assert result.checks["autonomous_live_budget"] is True
    assert result.checks["risk_caps"] is False
    assert any("per_name_cap_usd" in issue.reason for issue in result.issues)


def test_live_gate_blocks_live_buy_when_broker_buying_power_missing(tmp_path):
    envelope_path = tmp_path / "risk_envelope.yaml"
    promotion_path = tmp_path / "promotion.json"
    control_path = tmp_path / "live_control.json"
    _write_envelope(envelope_path, live_budget_mode="autonomous_with_caps")
    _write_live_control(control_path, expires_at="2026-06-03T16:00:00+00:00")
    promotion_path.write_text(
        json.dumps({"sleeves": {"pullback-support": _promotion_record()}}),
        encoding="utf-8",
    )

    result = evaluate_go_live_guard(
        actions=[_tiny_live_action(notional=Decimal("20.00"))],
        risk_envelope_path=envelope_path,
        promotion_state_path=promotion_path,
        control_state_path=control_path,
        now=datetime.datetime(2026, 6, 1, 15, 0, tzinfo=datetime.timezone.utc),
    )

    assert result.allowed is False
    assert result.checks["broker_buying_power"] is False
    assert any("broker buying_power" in issue.reason for issue in result.issues)


def test_live_gate_blocks_live_buy_above_broker_buying_power(tmp_path):
    envelope_path = tmp_path / "risk_envelope.yaml"
    promotion_path = tmp_path / "promotion.json"
    control_path = tmp_path / "live_control.json"
    _write_envelope(envelope_path, live_budget_mode="autonomous_with_caps")
    _write_live_control(control_path, expires_at="2026-06-03T16:00:00+00:00")
    promotion_path.write_text(
        json.dumps({"sleeves": {"pullback-support": _promotion_record()}}),
        encoding="utf-8",
    )

    result = evaluate_go_live_guard(
        actions=[_tiny_live_action(notional=Decimal("275.00"))],
        risk_envelope_path=envelope_path,
        promotion_state_path=promotion_path,
        control_state_path=control_path,
        live_buying_power=Decimal("150.00"),
        now=datetime.datetime(2026, 6, 1, 15, 0, tzinfo=datetime.timezone.utc),
    )

    assert result.allowed is False
    assert result.checks["broker_buying_power"] is False
    assert any("exceeds broker buying_power" in issue.reason for issue in result.issues)


def test_supervisor_submit_guard_uses_live_account_buying_power(tmp_path):
    envelope_path = tmp_path / "risk_envelope.yaml"
    promotion_path = tmp_path / "promotion.json"
    control_path = tmp_path / "live_control.json"
    _write_envelope(envelope_path, live_budget_mode="autonomous_with_caps")
    _write_live_control(control_path, expires_at="2026-06-03T16:00:00+00:00")
    promotion_path.write_text(
        json.dumps({"sleeves": {"pullback-support": _promotion_record()}}),
        encoding="utf-8",
    )

    issues = validate_supervisor_live_submit_allowed(
        actions=[_tiny_live_action(notional=Decimal("275.00"))],
        risk_envelope_path=envelope_path,
        promotion_state_path=promotion_path,
        control_state_path=control_path,
        live_account={"buying_power": "150.00"},
        now=datetime.datetime(2026, 6, 1, 15, 0, tzinfo=datetime.timezone.utc),
    )

    assert any("exceeds broker buying_power" in issue.reason for issue in issues)


def test_live_gate_circuit_breaker_blocks_new_buys_under_capped_mode(tmp_path):
    envelope_path = tmp_path / "risk_envelope.yaml"
    promotion_path = tmp_path / "promotion.json"
    control_path = tmp_path / "live_control.json"
    _write_envelope(envelope_path, live_budget_mode="autonomous_with_caps")
    _write_live_control(control_path, expires_at="2026-06-03T16:00:00+00:00")
    promotion_path.write_text(
        json.dumps({"sleeves": {"pullback-support": _promotion_record()}}),
        encoding="utf-8",
    )

    result = evaluate_go_live_guard(
        actions=[_tiny_live_action(notional=Decimal("275.00"))],
        risk_envelope_path=envelope_path,
        promotion_state_path=promotion_path,
        control_state_path=control_path,
        current_daily_loss_usd=Decimal("25.00"),
        current_drawdown_pct=Decimal("0.0500"),
        now=datetime.datetime(2026, 6, 1, 15, 0, tzinfo=datetime.timezone.utc),
    )

    assert result.allowed is False
    assert result.checks["autonomous_live_budget"] is True
    assert result.checks["portfolio_circuit_breakers"] is False
    assert result.checks["daily_loss_considered"] is True
    assert result.checks["drawdown_considered"] is True
    reasons = "\n".join(issue.reason for issue in result.issues)
    assert "daily_loss_halt_usd" in reasons
    assert "max_drawdown_halt_pct" in reasons


def test_live_gate_circuit_breaker_allows_profit_taking_sells(tmp_path):
    envelope_path = tmp_path / "risk_envelope.yaml"
    promotion_path = tmp_path / "promotion.json"
    control_path = tmp_path / "live_control.json"
    _write_envelope(envelope_path, live_budget_mode="autonomous_with_caps")
    _write_live_control(control_path, expires_at="2026-06-03T16:00:00+00:00")
    promotion_path.write_text(
        json.dumps({"sleeves": {"pullback-support": _promotion_record()}}),
        encoding="utf-8",
    )

    result = evaluate_go_live_guard(
        actions=[
            _tiny_live_action(
                action="close",
                side="sell",
                symbol="ORCL",
                notional=Decimal("105.00"),
                limit_price=Decimal("255.00"),
                decision_id="profit-decision",
            )
        ],
        live_positions=[_loss_position(current_price="255.00")],
        decision_evidence={},
        risk_envelope_path=envelope_path,
        promotion_state_path=promotion_path,
        control_state_path=control_path,
        current_daily_loss_usd=Decimal("25.00"),
        current_drawdown_pct=Decimal("0.0500"),
        now=datetime.datetime(2026, 6, 3, 15, 0, tzinfo=datetime.timezone.utc),
    )

    assert result.allowed is True
    assert result.checks["portfolio_circuit_breakers"] is True
    assert result.checks["daily_loss_considered"] is True
    assert result.checks["drawdown_considered"] is True


def test_live_gate_does_not_count_close_sell_as_new_budget(tmp_path):
    envelope_path = tmp_path / "risk_envelope.yaml"
    promotion_path = tmp_path / "promotion.json"
    control_path = tmp_path / "live_control.json"
    _write_envelope(envelope_path)
    _write_live_control(control_path, expires_at="2026-06-03T16:00:00+00:00")
    promotion_path.write_text(
        json.dumps({"sleeves": {"pullback-support": _promotion_record()}}),
        encoding="utf-8",
    )

    result = evaluate_go_live_guard(
        actions=[
            _tiny_live_action(
                action="close",
                side="sell",
                notional=Decimal("300.00"),
            )
        ],
        risk_envelope_path=envelope_path,
        promotion_state_path=promotion_path,
        control_state_path=control_path,
        current_live_exposure=Decimal("250.00"),
        live_positions=[
            {
                "symbol": "MSFT",
                "avg_entry_price": "390.00",
                "current_price": "410.00",
            }
        ],
        now=datetime.datetime(2026, 6, 1, 15, 0, tzinfo=datetime.timezone.utc),
    )

    assert result.allowed is True


def test_live_gate_blocks_sell_when_avg_entry_is_nonpositive_without_review(tmp_path):
    envelope_path = tmp_path / "risk_envelope.yaml"
    promotion_path = tmp_path / "promotion.json"
    control_path = tmp_path / "live_control.json"
    _write_envelope(envelope_path, live_budget_mode="autonomous_with_caps")
    _write_live_control(control_path, expires_at="2026-06-03T16:00:00+00:00")
    promotion_path.write_text(
        json.dumps({"sleeves": {"pullback-support": _promotion_record()}}),
        encoding="utf-8",
    )

    result = evaluate_go_live_guard(
        actions=[
            _tiny_live_action(
                action="close",
                side="sell",
                symbol="ORCL",
                notional=Decimal("95.66"),
                limit_price=Decimal("233.37"),
                decision_id="decision-current",
            )
        ],
        live_positions=[
            {
                "symbol": "ORCL",
                "avg_entry_price": "0",
                "current_price": "233.37",
            }
        ],
        decision_evidence={},
        risk_envelope_path=envelope_path,
        promotion_state_path=promotion_path,
        control_state_path=control_path,
        now=datetime.datetime(2026, 6, 3, 15, 0, tzinfo=datetime.timezone.utc),
    )

    assert result.allowed is False
    reasons = "\n".join(issue.reason for issue in result.issues)
    assert "final_submit_loss_gate_blocked" in reasons
    assert "loss_exit_review is missing" in reasons


def test_live_gate_blocks_loss_sell_without_structured_loss_exit_review(tmp_path):
    envelope_path = tmp_path / "risk_envelope.yaml"
    promotion_path = tmp_path / "promotion.json"
    control_path = tmp_path / "live_control.json"
    _write_envelope(envelope_path, live_budget_mode="autonomous_with_caps")
    _write_live_control(control_path, expires_at="2026-06-03T16:00:00+00:00")
    promotion_path.write_text(
        json.dumps({"sleeves": {"pullback-support": _promotion_record()}}),
        encoding="utf-8",
    )

    result = evaluate_go_live_guard(
        actions=[
            _tiny_live_action(
                action="close",
                side="sell",
                symbol="ORCL",
                notional=Decimal("95.66"),
                limit_price=Decimal("233.37"),
                decision_id="decision-current",
            )
        ],
        live_positions=[_loss_position()],
        decision_evidence={},
        risk_envelope_path=envelope_path,
        promotion_state_path=promotion_path,
        control_state_path=control_path,
        now=datetime.datetime(2026, 6, 3, 15, 0, tzinfo=datetime.timezone.utc),
    )

    assert result.allowed is False
    reasons = "\n".join(issue.reason for issue in result.issues)
    assert "final_submit_loss_gate_blocked" in reasons
    assert "loss_exit_review is missing" in reasons


def test_live_gate_blocks_sell_when_position_snapshot_missing(tmp_path):
    envelope_path = tmp_path / "risk_envelope.yaml"
    promotion_path = tmp_path / "promotion.json"
    control_path = tmp_path / "live_control.json"
    _write_envelope(envelope_path, live_budget_mode="autonomous_with_caps")
    _write_live_control(
        control_path,
        expires_at="2026-06-03T16:00:00+00:00",
    )
    promotion_path.write_text(
        json.dumps({"sleeves": {"pullback-support": _promotion_record()}}),
        encoding="utf-8",
    )

    result = evaluate_go_live_guard(
        actions=[
            _tiny_live_action(
                action="close",
                side="sell",
                symbol="ORCL",
                notional=Decimal("95.66"),
                limit_price=Decimal("233.37"),
                decision_id="decision-current",
            )
        ],
        live_positions=[],
        decision_evidence={"loss_exit_review": _approved_loss_review()},
        risk_envelope_path=envelope_path,
        promotion_state_path=promotion_path,
        control_state_path=control_path,
        now=datetime.datetime(2026, 6, 3, 15, 0, tzinfo=datetime.timezone.utc),
    )

    assert result.allowed is False
    assert any(
        "current live position snapshot is missing" in issue.reason
        for issue in result.issues
    )


def test_live_gate_blocks_stale_loss_exit_review_decision_id(tmp_path):
    envelope_path = tmp_path / "risk_envelope.yaml"
    promotion_path = tmp_path / "promotion.json"
    control_path = tmp_path / "live_control.json"
    _write_envelope(envelope_path, live_budget_mode="autonomous_with_caps")
    _write_live_control(control_path, expires_at="2026-06-03T16:00:00+00:00")
    promotion_path.write_text(
        json.dumps({"sleeves": {"pullback-support": _promotion_record()}}),
        encoding="utf-8",
    )

    result = evaluate_go_live_guard(
        actions=[
            _tiny_live_action(
                action="close",
                side="sell",
                symbol="ORCL",
                notional=Decimal("95.66"),
                limit_price=Decimal("233.37"),
                decision_id="decision-current",
            )
        ],
        live_positions=[_loss_position()],
        decision_evidence={
            "loss_exit_review": _approved_loss_review(decision_id="old-decision")
        },
        risk_envelope_path=envelope_path,
        promotion_state_path=promotion_path,
        control_state_path=control_path,
        now=datetime.datetime(2026, 6, 3, 15, 0, tzinfo=datetime.timezone.utc),
    )

    assert result.allowed is False
    assert any("decision_id does not match current action" in issue.reason for issue in result.issues)


def test_live_gate_blocks_loss_exit_review_allowed_false(tmp_path):
    envelope_path = tmp_path / "risk_envelope.yaml"
    promotion_path = tmp_path / "promotion.json"
    control_path = tmp_path / "live_control.json"
    _write_envelope(envelope_path, live_budget_mode="autonomous_with_caps")
    _write_live_control(control_path, expires_at="2026-06-03T16:00:00+00:00")
    promotion_path.write_text(
        json.dumps({"sleeves": {"pullback-support": _promotion_record()}}),
        encoding="utf-8",
    )

    result = evaluate_go_live_guard(
        actions=[
            _tiny_live_action(
                action="close",
                side="sell",
                symbol="ORCL",
                notional=Decimal("95.66"),
                limit_price=Decimal("233.37"),
                decision_id="decision-current",
            )
        ],
        live_positions=[_loss_position()],
        decision_evidence={
            "loss_exit_review": _approved_loss_review(
                allowed=False,
                blocked_reasons=["broad market weakness alone is insufficient"],
            )
        },
        risk_envelope_path=envelope_path,
        promotion_state_path=promotion_path,
        control_state_path=control_path,
        now=datetime.datetime(2026, 6, 3, 15, 0, tzinfo=datetime.timezone.utc),
    )

    assert result.allowed is False
    assert any("loss_exit_review.allowed is not true" in issue.reason for issue in result.issues)


def test_live_gate_allows_strict_current_approved_loss_exit_review(tmp_path):
    envelope_path = tmp_path / "risk_envelope.yaml"
    promotion_path = tmp_path / "promotion.json"
    control_path = tmp_path / "live_control.json"
    _write_envelope(envelope_path, live_budget_mode="autonomous_with_caps")
    _write_live_control(control_path, expires_at="2026-06-03T16:00:00+00:00")
    promotion_path.write_text(
        json.dumps({"sleeves": {"pullback-support": _promotion_record()}}),
        encoding="utf-8",
    )

    result = evaluate_go_live_guard(
        actions=[
            _tiny_live_action(
                action="close",
                side="sell",
                symbol="ORCL",
                notional=Decimal("95.66"),
                limit_price=Decimal("233.37"),
                decision_id="decision-current",
            )
        ],
        live_positions=[_loss_position()],
        decision_evidence={"loss_exit_review": _approved_loss_review()},
        risk_envelope_path=envelope_path,
        promotion_state_path=promotion_path,
        control_state_path=control_path,
        now=datetime.datetime(2026, 6, 3, 15, 0, tzinfo=datetime.timezone.utc),
    )

    assert result.allowed is True


def test_live_gate_allows_current_pre_registered_policy_stop_review(tmp_path):
    result = _policy_exit_gate_result(tmp_path, _policy_exit_review())

    assert result.allowed is True


def _policy_exit_review(**overrides):
    generated_at = datetime.datetime(2026, 6, 3, 15, 0, tzinfo=datetime.timezone.utc)
    is_time_stop = (
        overrides.get("allowed_exit_reason") == "policy_time_stop"
        and overrides.get("exit_policy_rule") == "time_stop"
    )
    position = {
        "symbol": "NFLX",
        "qty": "0.4101",
        "avg_entry_price": "83.37",
        "current_price": "69.00",
        "market_value": "22.23",
        "estimated_realized_loss": "-4.52",
        "unrealized_pl": "-4.52",
        "unrealized_plpc": "-0.172364159769701331414177762",
        "opened_at": "2026-05-20T15:00:00+00:00",
    }
    if is_time_stop:
        position.update(
            {
                "avg_entry_price": "100.00",
                "current_price": "94.00",
                "unrealized_plpc": "-0.06",
                "holding_period_trading_days": 20,
                "opened_at": "2026-05-06T15:00:00+00:00",
            }
        )
    enriched = apply_exit_policy_to_position(position, generated_at=generated_at)
    review = loss_exit_review_packet(
        enriched,
        generated_at=generated_at,
        decision_id="decision-current",
        proposed_limit_price=enriched["exit_policy_limit_price"],
    )
    review.update(overrides)
    return review


def _policy_exit_gate_result(
    tmp_path,
    review,
    *,
    action_overrides=None,
    live_position_overrides=None,
    now=datetime.datetime(2026, 6, 3, 15, 0, tzinfo=datetime.timezone.utc),
):
    envelope_path = tmp_path / "risk_envelope.yaml"
    promotion_path = tmp_path / "promotion.json"
    control_path = tmp_path / "live_control.json"
    _write_envelope(envelope_path, live_budget_mode="autonomous_with_caps")
    _write_live_control(control_path, expires_at="2026-06-03T16:00:00+00:00")
    promotion_path.write_text(
        json.dumps({"sleeves": {"pullback-support": _promotion_record()}}),
        encoding="utf-8",
    )
    is_policy_exit = review.get("policy_rule_exit") is True
    action_values = {
        "action": "close",
        "side": "sell",
        "symbol": "NFLX",
        "notional": Decimal("22.23"),
        "limit_price": Decimal(
            str(review.get("proposed_limit_price") or "68.79")
            if is_policy_exit
            else "69.07"
        ),
        "decision_id": "decision-current",
    }
    action_values.update(action_overrides or {})
    action = _tiny_live_action(**action_values)
    if is_policy_exit:
        try:
            current_price = Decimal(str(review.get("current_price")))
            average_entry_price = Decimal(str(review.get("average_entry_price")))
            if current_price <= 0 or average_entry_price <= 0:
                raise ValueError
            unrealized_plpc = (current_price - average_entry_price) / average_entry_price
        except Exception:
            current_price = Decimal("69.00")
            average_entry_price = Decimal("83.37")
            unrealized_plpc = Decimal("-0.172364159769701331414177762")
    else:
        current_price = Decimal("69.28")
        average_entry_price = Decimal("83.37")
        unrealized_plpc = Decimal("-0.1690")
    live_position = _loss_position(
        symbol=action.symbol,
        avg_entry_price=str(average_entry_price),
        current_price=str(current_price),
        market_value="22.23",
        cost_basis="26.76",
        unrealized_pl="-4.52",
        unrealized_plpc=str(unrealized_plpc),
    )
    if review.get("holding_period_trading_days") is not None:
        live_position["holding_period_trading_days"] = review[
            "holding_period_trading_days"
        ]
    if review.get("opened_at") is not None:
        live_position["opened_at"] = review["opened_at"]
    live_position.update(live_position_overrides or {})
    return evaluate_go_live_guard(
        actions=[action],
        live_positions=[live_position],
        decision_evidence={"loss_exit_review": review},
        risk_envelope_path=envelope_path,
        promotion_state_path=promotion_path,
        control_state_path=control_path,
        now=now,
    )


def test_live_gate_allows_current_pre_registered_policy_time_stop_review(tmp_path):
    result = _policy_exit_gate_result(
        tmp_path,
        _policy_exit_review(
            allowed_exit_reason="policy_time_stop",
            exit_policy_rule="time_stop",
        ),
    )

    assert result.allowed is True


def test_live_gate_denies_internally_inconsistent_policy_review_before_submit(tmp_path):
    """A self-consistent policy claim cannot launder a mismatched loss return."""
    review = _policy_exit_review()
    review["unrealized_plpc"] = "-17.22"
    review["exit_policy_loss_pct"] = "17.22"
    review["exit_policy_rationale"] = review["exit_policy_rationale"].replace(
        "17.24%", "17.22%"
    )

    result = _policy_exit_gate_result(tmp_path, review)

    assert result.allowed is False
    assert any("policy" in issue.reason.lower() for issue in result.issues)


def test_live_gate_denies_policy_review_with_forged_quantity_before_submit(tmp_path):
    review = _policy_exit_review()
    review["quantity"] = "0.3000"

    result = _policy_exit_gate_result(tmp_path, review)

    assert result.allowed is False
    assert any("policy" in issue.reason.lower() for issue in result.issues)


def test_live_gate_denies_policy_review_when_current_broker_position_conflicts(tmp_path):
    """The final gate must bind the review to the independently read position."""
    review = _policy_exit_review()

    result = _policy_exit_gate_result(
        tmp_path,
        review,
        live_position_overrides={"current_price": "71.00"},
    )

    assert result.allowed is False
    assert any("policy" in issue.reason.lower() for issue in result.issues)


def test_live_gate_denies_policy_review_when_broker_return_conflicts(tmp_path):
    result = _policy_exit_gate_result(
        tmp_path,
        _policy_exit_review(),
        live_position_overrides={"unrealized_plpc": "-0.10"},
    )

    assert result.allowed is False
    assert any("policy" in issue.reason.lower() for issue in result.issues)


def test_live_gate_denies_policy_review_when_opened_at_and_holding_days_conflict(tmp_path):
    review = _policy_exit_review(
        opened_at="2026-05-27T15:00:00+00:00",
        holding_period_trading_days=20,
    )

    result = _policy_exit_gate_result(tmp_path, review)

    assert result.allowed is False
    assert any("policy" in issue.reason.lower() for issue in result.issues)


def test_live_gate_denies_policy_review_when_action_limit_conflicts(tmp_path):
    result = _policy_exit_gate_result(
        tmp_path,
        _policy_exit_review(),
        action_overrides={"limit_price": Decimal("68.78")},
    )

    assert result.allowed is False
    assert any("limit" in issue.reason.lower() for issue in result.issues)


@pytest.mark.parametrize("reason", [["policy_stop_floor"], {"reason": "policy_stop_floor"}])
def test_live_gate_fails_closed_for_unhashable_policy_reason(tmp_path, reason):
    result = _policy_exit_gate_result(
        tmp_path,
        _policy_exit_review(allowed_exit_reason=reason),
    )

    assert result.allowed is False


def test_live_gate_fails_closed_for_nonstring_nonpolicy_reason(tmp_path):
    result = _policy_exit_gate_result(
        tmp_path,
        _policy_exit_review(
            allowed_exit_reason=["policy_stop_floor"],
            policy_rule_exit=False,
        ),
    )

    assert result.allowed is False


@pytest.mark.parametrize(
    "field",
    [
        "symbol",
        "side",
        "decision_id",
        "allowed_exit_reason",
        "allowed_exit_reason_source",
        "exit_policy_rule",
        "exit_policy_rationale",
        "evidence_generated_at",
    ],
)
@pytest.mark.parametrize("value", [{"invalid": True}, ["invalid"], True])
def test_live_gate_rejects_nonstring_policy_text_fields(tmp_path, field, value):
    result = _policy_exit_gate_result(tmp_path, _policy_exit_review(**{field: value}))

    assert result.allowed is False


@pytest.mark.parametrize(
    "field",
    [
        "current_price",
        "average_entry_price",
        "estimated_realized_loss",
        "unrealized_pnl_percent",
    ],
)
@pytest.mark.parametrize(
    "value",
    [{"invalid": True}, True, 0, "not-a-number", "NaN", "Infinity"],
)
def test_live_gate_rejects_invalid_policy_numeric_fields(tmp_path, field, value):
    result = _policy_exit_gate_result(tmp_path, _policy_exit_review(**{field: value}))

    assert result.allowed is False


@pytest.mark.parametrize(
    "field,value",
    [
        ("current_price", "83.37"),
        ("average_entry_price", "69.00"),
        ("estimated_realized_loss", "0.01"),
        ("unrealized_pnl_percent", "0.01"),
    ],
)
def test_live_gate_rejects_policy_values_that_do_not_prove_a_loss(tmp_path, field, value):
    result = _policy_exit_gate_result(tmp_path, _policy_exit_review(**{field: value}))

    assert result.allowed is False


@pytest.mark.parametrize("source_packet_ids", ["packet", {"packet": True}])
def test_live_gate_rejects_malformed_policy_source_packet_ids(tmp_path, source_packet_ids):
    result = _policy_exit_gate_result(
        tmp_path,
        _policy_exit_review(source_packet_ids=source_packet_ids),
    )

    assert result.allowed is False


@pytest.mark.parametrize("value", [{}, (), False, 0])
def test_live_gate_rejects_malformed_or_falsey_policy_timestamp(tmp_path, value):
    result = _policy_exit_gate_result(
        tmp_path,
        _policy_exit_review(evidence_generated_at=value),
    )

    assert result.allowed is False


@pytest.mark.parametrize(
    "field,value",
    [
        ("current_price", 69),
        ("average_entry_price", Decimal("83.37")),
        ("estimated_realized_loss", "-4.52"),
        ("unrealized_pnl_percent", Decimal("-17.24")),
    ],
)
def test_live_gate_allows_valid_policy_numeric_scalar_forms(tmp_path, field, value):
    result = _policy_exit_gate_result(tmp_path, _policy_exit_review(**{field: value}))

    assert result.allowed is True


@pytest.mark.parametrize("value", [{}, (), False, 0])
def test_live_gate_rejects_malformed_or_falsey_discretionary_timestamp(tmp_path, value):
    result = _policy_exit_gate_result(
        tmp_path,
        _approved_loss_review(evidence_generated_at=value),
    )

    assert result.allowed is False


@pytest.mark.parametrize(
    "field,value",
    [
        ("allowed", "true"),
        ("allowed", "false"),
        ("policy_rule_exit", "true"),
        ("policy_rule_exit", "false"),
    ],
)
def test_live_gate_rejects_string_policy_booleans(tmp_path, field, value):
    result = _policy_exit_gate_result(tmp_path, _policy_exit_review(**{field: value}))

    assert result.allowed is False
    assert any("final_submit_loss_gate_blocked" in issue.reason for issue in result.issues)


@pytest.mark.parametrize(
    "field",
    [
        "symbol",
        "decision_id",
        "allowed_exit_reason_source",
        "exit_policy_rule",
        "exit_policy_rationale",
    ],
)
def test_live_gate_rejects_policy_review_missing_required_field(tmp_path, field):
    review = _policy_exit_review()
    review.pop(field)

    result = _policy_exit_gate_result(tmp_path, review)

    assert result.allowed is False
    assert any("final_submit_loss_gate_blocked" in issue.reason for issue in result.issues)


@pytest.mark.parametrize(
    "field,value",
    [
        ("blockers", ["blocked"]),
        ("blocked_reasons", ["blocked"]),
        ("blockers", "blocked"),
        ("blocked_reasons", "blocked"),
    ],
)
def test_live_gate_rejects_policy_review_with_blockers(tmp_path, field, value):
    result = _policy_exit_gate_result(tmp_path, _policy_exit_review(**{field: value}))

    assert result.allowed is False
    assert any("final_submit_loss_gate_blocked" in issue.reason for issue in result.issues)


def test_live_gate_fails_closed_without_raising_for_malformed_policy_review(tmp_path):
    result = _policy_exit_gate_result(
        tmp_path,
        {"policy_rule_exit": True},
    )

    assert result.allowed is False
    assert any("final_submit_loss_gate_blocked" in issue.reason for issue in result.issues)


@pytest.mark.parametrize(
    "review,action_overrides",
    [
        (_policy_exit_review(allowed_exit_reason="unknown_policy_reason"), {}),
        (_policy_exit_review(exit_policy_rule="unknown_policy_rule"), {}),
        (_policy_exit_review(symbol="TSM"), {}),
        (_policy_exit_review(decision_id="other-decision"), {}),
        (_policy_exit_review(side="buy"), {}),
        (_policy_exit_review(), {"symbol": "TSM"}),
        (_policy_exit_review(), {"decision_id": "other-decision"}),
    ],
)
def test_live_gate_rejects_policy_review_with_conflicting_authority_or_identity(
    tmp_path, review, action_overrides
):
    result = _policy_exit_gate_result(
        tmp_path,
        review,
        action_overrides=action_overrides,
    )

    assert result.allowed is False
    assert any("final_submit_loss_gate_blocked" in issue.reason for issue in result.issues)


@pytest.mark.parametrize(
    "timestamp",
    ["2026-06-03T08:59:59+00:00", "2026-06-03T15:00:01+00:00"],
)
def test_live_gate_rejects_stale_or_future_policy_review(tmp_path, timestamp):
    result = _policy_exit_gate_result(
        tmp_path,
        _policy_exit_review(evidence_generated_at=timestamp),
    )

    assert result.allowed is False
    assert any("stale for current submit" in issue.reason for issue in result.issues)


def test_live_gate_does_not_require_loss_review_for_profit_taking_sell(tmp_path):
    envelope_path = tmp_path / "risk_envelope.yaml"
    promotion_path = tmp_path / "promotion.json"
    control_path = tmp_path / "live_control.json"
    _write_envelope(envelope_path, live_budget_mode="autonomous_with_caps")
    _write_live_control(control_path, expires_at="2026-06-03T16:00:00+00:00")
    promotion_path.write_text(
        json.dumps({"sleeves": {"pullback-support": _promotion_record()}}),
        encoding="utf-8",
    )

    result = evaluate_go_live_guard(
        actions=[
            _tiny_live_action(
                action="close",
                side="sell",
                symbol="ORCL",
                notional=Decimal("105.00"),
                limit_price=Decimal("255.00"),
                decision_id="profit-decision",
            )
        ],
        live_positions=[_loss_position(current_price="255.00")],
        decision_evidence={},
        risk_envelope_path=envelope_path,
        promotion_state_path=promotion_path,
        control_state_path=control_path,
        now=datetime.datetime(2026, 6, 3, 15, 0, tzinfo=datetime.timezone.utc),
    )

    assert result.allowed is True


def test_live_gate_blocks_frozen_control_state(tmp_path):
    envelope_path = tmp_path / "risk_envelope.yaml"
    promotion_path = tmp_path / "promotion.json"
    control_path = tmp_path / "live_control.json"
    _write_envelope(envelope_path)
    _write_live_control(control_path, frozen=True)
    promotion_path.write_text(
        json.dumps(
            {
                "sleeves": {
                    "pullback-support": _promotion_record()
                }
            }
        ),
        encoding="utf-8",
    )

    result = evaluate_go_live_guard(
        actions=[_tiny_live_action()],
        risk_envelope_path=envelope_path,
        promotion_state_path=promotion_path,
        control_state_path=control_path,
        now=datetime.datetime(2026, 6, 1, 15, 0, tzinfo=datetime.timezone.utc),
    )

    assert result.allowed is False
    assert any("frozen" in issue.reason.lower() for issue in result.issues)


def test_supervisor_guard_rejects_legacy_live_now_even_when_files_exist(tmp_path):
    envelope_path = tmp_path / "risk_envelope.yaml"
    promotion_path = tmp_path / "promotion.json"
    _write_envelope(envelope_path)
    promotion_path.write_text(
        json.dumps(
            {
                "sleeves": {
                    "legacy-supervisor": _promotion_record()
                }
            }
        ),
        encoding="utf-8",
    )

    issues = validate_supervisor_live_submit_allowed(
        actions=[
            _tiny_live_action(
                execution_mode="live_now",
                sleeve="legacy-supervisor",
            )
        ],
        risk_envelope_path=envelope_path,
        promotion_state_path=promotion_path,
    )

    assert any("tiny_live" in issue.reason for issue in issues)


def test_live_gate_rejects_incomplete_promotion_record(tmp_path):
    envelope_path = tmp_path / "risk_envelope.yaml"
    promotion_path = tmp_path / "promotion.json"
    control_path = tmp_path / "live_control.json"
    _write_envelope(envelope_path)
    _write_live_control(control_path)
    promotion_path.write_text(
        json.dumps(
            {
                "sleeves": {
                    "pullback-support": {
                        "stage": "tiny_live_eligible",
                        "live_enabled": True,
                        "ci_green": True,
                        "shadow_confirmed": True,
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    result = evaluate_go_live_guard(
        actions=[_tiny_live_action()],
        risk_envelope_path=envelope_path,
        promotion_state_path=promotion_path,
        control_state_path=control_path,
        now=datetime.datetime(2026, 6, 1, 15, 0, tzinfo=datetime.timezone.utc),
    )

    assert result.allowed is False
    reasons = "\n".join(issue.reason for issue in result.issues)
    assert "preregistered" in reasons
    assert "benchmark_gate_passed" in reasons
    assert "validation_report_ref" in reasons


def _promotion_record_with_tournament_source(report_generated_at):
    source = {
        "kind": "paper_tournament",
        "tournament_id": "paper-tournament-freshness",
        "candidate_reason": "positive paper strategy",
    }
    if report_generated_at is not None:
        source["report_generated_at"] = report_generated_at
    return _promotion_record(
        source=source,
        evidence_metrics=_persisted_evidence_metrics(),
    )


def _legacy_gate_result(tmp_path, record):
    envelope_path = tmp_path / "risk_envelope.yaml"
    promotion_path = tmp_path / "promotion.json"
    control_path = tmp_path / "live_control.json"
    _write_envelope(envelope_path)
    _write_live_control(control_path, expires_at="2026-06-03T16:00:00+00:00")
    promotion_path.write_text(
        json.dumps({"sleeves": {"pullback-support": record}}),
        encoding="utf-8",
    )
    return evaluate_go_live_guard(
        actions=[_tiny_live_action()],
        risk_envelope_path=envelope_path,
        promotion_state_path=promotion_path,
        control_state_path=control_path,
        live_buying_power=Decimal("100.00"),
        now=datetime.datetime(2026, 6, 3, 15, 0, tzinfo=datetime.timezone.utc),
    )


def test_live_gate_allows_persisted_fresh_paper_tournament_source(tmp_path):
    result = _legacy_gate_result(
        tmp_path,
        _promotion_record_with_tournament_source("2026-06-02T21:12:35+00:00"),
    )

    assert result.allowed is True
    assert result.issues == []


def test_live_gate_allows_paper_tournament_source_one_second_inside_ceiling(
    tmp_path,
):
    result = _legacy_gate_result(
        tmp_path,
        _promotion_record_with_tournament_source("2026-05-27T15:00:01+00:00"),
    )

    assert result.allowed is True
    assert result.issues == []


@pytest.mark.parametrize(
    ("case", "report_generated_at", "expected_fragment"),
    [
        ("missing", None, "report_generated_at is missing"),
        ("invalid", "not-a-timestamp", "report_generated_at is invalid"),
        ("naive", "2026-06-02T21:12:35", "timezone-naive"),
        ("future", "2026-06-05T15:00:00+00:00", "in the future"),
        ("stale_exact_boundary", "2026-05-27T15:00:00+00:00", "is stale"),
        (
            "z_suffix",
            "2026-06-02T21:12:35Z",
            ("report_generated_at is invalid", "not canonical UTC"),
        ),
        (
            "fractional_seconds",
            "2026-06-02T21:12:35.250000+00:00",
            "not canonical UTC",
        ),
        ("non_utc_offset", "2026-06-02T16:12:35-05:00", "not canonical UTC"),
    ],
)
def test_live_gate_rejects_persisted_stale_or_invalid_tournament_source(
    tmp_path, case, report_generated_at, expected_fragment
):
    result = _legacy_gate_result(
        tmp_path,
        _promotion_record_with_tournament_source(report_generated_at),
    )

    assert result.allowed is False
    assert result.checks["promotion"] is False
    fragments = (
        expected_fragment if isinstance(expected_fragment, tuple) else (expected_fragment,)
    )
    assert any(
        any(fragment in issue.reason for fragment in fragments)
        for issue in result.issues
    )


_FRESH_CANONICAL_REPORT_STAMP = "2026-06-02T21:12:35+00:00"


def _paper_tournament_source(**overrides):
    source = {
        "kind": "paper_tournament",
        "tournament_id": "paper-tournament-freshness",
        "report_generated_at": _FRESH_CANONICAL_REPORT_STAMP,
        "candidate_reason": "positive paper strategy",
    }
    source.update(overrides)
    return source


def _source_missing(key):
    source = _paper_tournament_source()
    del source[key]
    return source


@pytest.mark.parametrize(
    ("case", "source", "expected_fragment"),
    [
        ("non_mapping_source", "paper-tournament", "source must be a JSON object"),
        (
            "missing_kind",
            _source_missing("kind"),
            "source.kind must be paper_tournament",
        ),
        (
            "unknown_kind",
            _paper_tournament_source(kind="spreadsheet"),
            "source.kind must be paper_tournament",
        ),
        (
            "missing_tournament_id",
            _source_missing("tournament_id"),
            "source.tournament_id is missing",
        ),
        (
            "mistyped_tournament_id",
            _paper_tournament_source(tournament_id=123),
            "source.tournament_id must be a non-empty string",
        ),
        (
            "mistyped_candidate_reason",
            _paper_tournament_source(candidate_reason=None),
            "source.candidate_reason must be a non-empty string",
        ),
        (
            "extra_source_field",
            _paper_tournament_source(protected_authority="unknown"),
            "unexpected extra fields",
        ),
    ],
)
def test_live_gate_fails_closed_on_unusable_legacy_promotion_source(
    tmp_path, case, source, expected_fragment
):
    record = _promotion_record(
        source=source,
        evidence_metrics=_persisted_evidence_metrics(),
    )

    result = _legacy_gate_result(tmp_path, record)

    assert result.allowed is False
    assert result.checks["promotion"] is False
    assert any(expected_fragment in issue.reason for issue in result.issues)


def test_live_gate_fails_closed_on_sourceless_legacy_promotion_record(tmp_path):
    """A fully flag-complete legacy record without provenance must fail closed."""

    record = _promotion_record()
    record.pop("source", None)
    record.pop("evidence_metrics", None)
    assert "source" not in record

    result = _legacy_gate_result(tmp_path, record)

    assert result.allowed is False
    assert result.checks["promotion"] is False
    assert any("source is missing" in issue.reason for issue in result.issues)


@pytest.mark.parametrize(
    "immutable_report_generated_at",
    [None, "2020-01-01T00:00:00+00:00"],
)
def test_live_gate_retains_immutable_strategy_evidence_exemption(
    tmp_path, immutable_report_generated_at
):
    source = {
        "kind": "immutable_strategy_evidence",
        "promotion_evidence_id": "promotion-evidence-" + "0" * 64,
    }
    if immutable_report_generated_at is not None:
        source["report_generated_at"] = immutable_report_generated_at
    record = _promotion_record(
        source=source,
        evidence_metrics=_persisted_evidence_metrics(),
    )

    result = _legacy_gate_result(tmp_path, record)

    assert result.allowed is True
    assert result.issues == []


def test_live_gate_account_hard_ceiling_blocks_capped_mode(tmp_path):
    envelope_path = tmp_path / "risk_envelope.yaml"
    promotion_path = tmp_path / "promotion.json"
    control_path = tmp_path / "live_control.json"
    _write_envelope(
        envelope_path,
        live_budget_mode="autonomous_with_caps",
        account_hard_ceiling_usd="50.00",
    )
    _write_live_control(control_path, expires_at="2026-06-03T16:00:00+00:00")
    promotion_path.write_text(
        json.dumps({"sleeves": {"pullback-support": _promotion_record()}}),
        encoding="utf-8",
    )

    result = evaluate_go_live_guard(
        actions=[_tiny_live_action(notional=Decimal("20.00"))],
        risk_envelope_path=envelope_path,
        promotion_state_path=promotion_path,
        control_state_path=control_path,
        current_live_exposure=Decimal("40.00"),
        live_buying_power=Decimal("500.00"),
        now=datetime.datetime(2026, 6, 1, 15, 0, tzinfo=datetime.timezone.utc),
    )

    assert result.allowed is False
    assert result.checks["account_hard_ceiling"] is False
    assert any("account_hard_ceiling_usd" in issue.reason for issue in result.issues)


def test_live_gate_account_hard_ceiling_allows_when_projected_under(tmp_path):
    envelope_path = tmp_path / "risk_envelope.yaml"
    promotion_path = tmp_path / "promotion.json"
    control_path = tmp_path / "live_control.json"
    _write_envelope(
        envelope_path,
        live_budget_mode="autonomous_with_caps",
        account_hard_ceiling_usd="100.00",
    )
    _write_live_control(control_path, expires_at="2026-06-03T16:00:00+00:00")
    promotion_path.write_text(
        json.dumps({"sleeves": {"pullback-support": _promotion_record()}}),
        encoding="utf-8",
    )

    result = evaluate_go_live_guard(
        actions=[_tiny_live_action(notional=Decimal("20.00"))],
        risk_envelope_path=envelope_path,
        promotion_state_path=promotion_path,
        control_state_path=control_path,
        current_live_exposure=Decimal("40.00"),
        live_buying_power=Decimal("500.00"),
        now=datetime.datetime(2026, 6, 1, 15, 0, tzinfo=datetime.timezone.utc),
    )

    assert result.allowed is True
    assert result.checks["account_hard_ceiling"] is True


def test_live_gate_order_rate_limit_blocks_when_window_exceeded(tmp_path):
    envelope_path = tmp_path / "risk_envelope.yaml"
    promotion_path = tmp_path / "promotion.json"
    control_path = tmp_path / "live_control.json"
    rate_path = tmp_path / "rate.json"
    _write_envelope(
        envelope_path,
        live_budget_mode="autonomous_with_caps",
        max_live_orders_per_window=2,
        live_order_window_minutes=60,
    )
    _write_live_control(control_path, expires_at="2026-06-03T16:00:00+00:00")
    promotion_path.write_text(
        json.dumps({"sleeves": {"pullback-support": _promotion_record()}}),
        encoding="utf-8",
    )
    now = datetime.datetime(2026, 6, 3, 15, 0, tzinfo=datetime.timezone.utc)
    record_live_order_submission(rate_path, client_order_id="ta-1", now=now)
    record_live_order_submission(rate_path, client_order_id="ta-2", now=now)

    result = evaluate_go_live_guard(
        actions=[_tiny_live_action(notional=Decimal("20.00"))],
        risk_envelope_path=envelope_path,
        promotion_state_path=promotion_path,
        control_state_path=control_path,
        order_rate_state_path=rate_path,
        live_buying_power=Decimal("500.00"),
        now=now,
    )

    assert result.allowed is False
    assert result.checks["order_rate_limit"] is False
    assert any("max_live_orders_per_window" in issue.reason for issue in result.issues)


def test_live_gate_order_rate_limit_inert_when_unconfigured(tmp_path):
    envelope_path = tmp_path / "risk_envelope.yaml"
    promotion_path = tmp_path / "promotion.json"
    control_path = tmp_path / "live_control.json"
    rate_path = tmp_path / "rate.json"
    _write_envelope(envelope_path, live_budget_mode="autonomous_with_caps")
    _write_live_control(control_path, expires_at="2026-06-03T16:00:00+00:00")
    promotion_path.write_text(
        json.dumps({"sleeves": {"pullback-support": _promotion_record()}}),
        encoding="utf-8",
    )
    now = datetime.datetime(2026, 6, 3, 15, 0, tzinfo=datetime.timezone.utc)
    for index in range(5):
        record_live_order_submission(rate_path, client_order_id=f"ta-{index}", now=now)

    result = evaluate_go_live_guard(
        actions=[_tiny_live_action(notional=Decimal("20.00"))],
        risk_envelope_path=envelope_path,
        promotion_state_path=promotion_path,
        control_state_path=control_path,
        order_rate_state_path=rate_path,
        live_buying_power=Decimal("500.00"),
        now=now,
    )

    assert result.allowed is True
    assert result.checks["order_rate_limit"] is True
