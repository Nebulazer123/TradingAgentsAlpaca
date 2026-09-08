import datetime
import hashlib
import json
from decimal import Decimal
from pathlib import Path

import pytest

from tradingagents.brokers.alpaca_supervisor import (
    LIVE_AGGRESSIVE_SLEEVE,
    resolve_live_sleeve,
)
from tradingagents.policy.io import atomic_write_text
from tradingagents.policy.promotion_sync import (
    supersede_legacy_readiness,
    sync_promotion_state_file,
    sync_promotion_state_from_tournament,
)
from tradingagents.policy.strategy_promotion import INTERNAL_EVIDENCE_MAX_AGE_SECONDS

SYNC_NOW = datetime.datetime(2026, 6, 22, 12, 0, 0, tzinfo=datetime.timezone.utc)


def _write_json_bytes(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(payload, sort_keys=True).encode("utf-8")
    path.write_bytes(data)
    return data


def _legacy_supersession_inputs(tmp_path):
    go_path = tmp_path / "historical-go.json"
    state_path = tmp_path / "promotion-state.json"
    tournament_path = tmp_path / "expired-tournament.json"
    receipt_path = tmp_path / "supersession.json"
    go_bytes = _write_json_bytes(go_path, {"status": "GO", "historical": True})
    state = _incumbent_state()
    state["sleeves"]["paper-sleeve"] = {
        **state["sleeves"]["current-aggressive"],
        "stage": "paper_only",
        "live_enabled": False,
    }
    state_bytes = _write_json_bytes(state_path, state)
    tournament_bytes = _write_json_bytes(
        tournament_path,
        {
            "tournament_id": "retired-paper-root",
            "ends_at": "2026-06-01T00:00:00+00:00",
        },
    )
    kwargs = {
        "go_packet_path": go_path,
        "promotion_state_path": state_path,
        "expired_tournament_ledger_path": tournament_path,
        "receipt_path": receipt_path,
        "expected_go_packet_sha256": hashlib.sha256(go_bytes).hexdigest(),
        "expected_promotion_state_sha256": hashlib.sha256(state_bytes).hexdigest(),
        "expected_expired_tournament_sha256": hashlib.sha256(
            tournament_bytes
        ).hexdigest(),
        "now": SYNC_NOW,
    }
    return kwargs, go_bytes, state_bytes, tournament_bytes


def test_legacy_readiness_supersession_is_immutable_paper_only_and_retryable(tmp_path):
    kwargs, go_before, state_before, tournament_before = (
        _legacy_supersession_inputs(tmp_path)
    )

    result = supersede_legacy_readiness(**kwargs)

    assert result.resumed is False
    assert result.prepared_receipt_path.exists()
    assert result.completed_receipt_path.exists()
    assert Path(kwargs["go_packet_path"]).read_bytes() == go_before
    assert Path(kwargs["expired_tournament_ledger_path"]).read_bytes() == tournament_before
    assert Path(kwargs["promotion_state_path"]).read_bytes() != state_before
    assert all(
        record["stage"] == "paper_only" and record["live_enabled"] is False
        for record in result.state["sleeves"].values()
    )
    prepared_before = result.prepared_receipt_path.read_bytes()
    completed_before = result.completed_receipt_path.read_bytes()
    completed = json.loads(completed_before)
    assert completed["execution_authority"] == "none"
    assert completed["can_promote"] is False
    assert completed["can_submit_orders"] is False

    retry_kwargs = dict(kwargs)
    retry_kwargs["now"] = SYNC_NOW + datetime.timedelta(days=1)
    retry = supersede_legacy_readiness(**retry_kwargs)
    assert retry.resumed is True
    assert retry.prepared_receipt_path.read_bytes() == prepared_before
    assert retry.completed_receipt_path.read_bytes() == completed_before


def test_legacy_readiness_supersession_keeps_prepare_after_interrupted_write(
    monkeypatch, tmp_path
):
    kwargs, _, state_before, _ = _legacy_supersession_inputs(tmp_path)

    def fail_write(*args, **call_kwargs):
        raise OSError("synthetic interruption")

    with monkeypatch.context() as interruption:
        interruption.setattr(
            "tradingagents.policy.promotion_sync._write_promotion_state_unlocked",
            fail_write,
        )
        with pytest.raises(OSError, match="synthetic interruption"):
            supersede_legacy_readiness(**kwargs)

    receipt_path = Path(kwargs["receipt_path"])
    assert receipt_path.with_name(receipt_path.name + ".prepared").exists()
    assert not receipt_path.exists()
    assert Path(kwargs["promotion_state_path"]).read_bytes() == state_before

    recovered = supersede_legacy_readiness(**kwargs)
    assert recovered.resumed is False
    assert receipt_path.exists()
    assert all(
        record["live_enabled"] is False
        for record in recovered.state["sleeves"].values()
    )


def test_legacy_readiness_supersession_rejects_stale_or_unexpired_inputs(tmp_path):
    kwargs, _, state_before, _ = _legacy_supersession_inputs(tmp_path)
    kwargs["expected_promotion_state_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="before-image digest mismatch"):
        supersede_legacy_readiness(**kwargs)
    assert Path(kwargs["promotion_state_path"]).read_bytes() == state_before
    assert not Path(kwargs["receipt_path"]).exists()

    kwargs, _, state_before, _ = _legacy_supersession_inputs(tmp_path / "fresh")
    tournament_path = Path(kwargs["expired_tournament_ledger_path"])
    fresh_bytes = _write_json_bytes(
        tournament_path,
        {"tournament_id": "current-root", "ends_at": "2026-07-01T00:00:00+00:00"},
    )
    kwargs["expected_expired_tournament_sha256"] = hashlib.sha256(fresh_bytes).hexdigest()
    with pytest.raises(ValueError, match="not verifiably expired"):
        supersede_legacy_readiness(**kwargs)
    assert Path(kwargs["promotion_state_path"]).read_bytes() == state_before


def _iso(moment):
    return moment.isoformat(timespec="seconds")


def _ranking(
    strategy_id,
    *,
    total_return="311.36",
    total_return_pct="3.11",
    max_drawdown_pct="-1.91",
    win_rate_pct="85.71",
    tracked_days=11,
    equity="10311.36",
):
    return {
        "strategy_id": strategy_id,
        "name": strategy_id,
        "equity": equity,
        "total_return": total_return,
        "total_return_pct": total_return_pct,
        "max_drawdown_pct": max_drawdown_pct,
        "win_rate_pct": win_rate_pct,
        "tracked_days": tracked_days,
    }


def _report(candidate="pullback-support"):
    return {
        "generated_at": "2026-06-20T21:12:35+00:00",
        "tournament_id": "paper-tournament-20260531-080741",
        "rankings": [
            _ranking("pullback-support"),
            _ranking(
                "current-aggressive",
                total_return="-1225.06",
                total_return_pct="-12.25",
                max_drawdown_pct="-3.00",
                win_rate_pct="55.71",
                equity="8774.94",
            ),
            _ranking(
                "catalyst-relative-strength",
                total_return="-1313.05",
                total_return_pct="-13.13",
                max_drawdown_pct="-14.42",
                win_rate_pct="20.00",
                equity="8686.95",
            ),
        ],
        "live_strategy_candidate": {
            "status": "candidate",
            "strategy_id": candidate,
            "reason": "best positive paper strategy after 11 tracked day(s)",
        },
    }


def _incumbent_state():
    return {
        "schema_version": "1.0.0",
        "sleeves": {
            "current-aggressive": {
                "stage": "tiny_live_eligible",
                "live_enabled": True,
                "preregistered": True,
                "ci_green": True,
                "shadow_confirmed": True,
                "benchmark_gate_passed": True,
                "cost_gate_passed": True,
                "recent_alpha_gate_passed": True,
                "capacity_gate_passed": True,
                "validation_report_ref": "results/paper_strategy_tournament/latest.json",
                "risk_envelope_ref": "config/risk_envelope.yaml",
            }
        },
    }


def _fresh_report():
    """Report whose incumbent evidence is positive, floor-clean, and fresh."""

    return {
        "generated_at": "2026-06-20T21:12:35+00:00",
        "tournament_id": "paper-tournament-20260531-080741",
        "rankings": [
            _ranking("pullback-support"),
            _ranking("current-aggressive", total_return="120.00"),
        ],
        "live_strategy_candidate": {
            "status": "candidate",
            "strategy_id": "pullback-support",
            "reason": "best positive paper strategy after 11 tracked day(s)",
        },
    }


def _sync_incumbent(report, *, now=SYNC_NOW):
    return sync_promotion_state_from_tournament(
        report,
        _incumbent_state(),
        tiny_live_tranche_usd=Decimal("25"),
        arm_live=True,
        ci_green=True,
        now=now,
    )


def test_sync_promotes_candidate_and_demotes_negative_incumbent():
    result = sync_promotion_state_from_tournament(
        _report(),
        _incumbent_state(),
        tiny_live_tranche_usd=Decimal("25"),
        arm_live=True,
        ci_green=True,
        now=datetime.datetime(2026, 6, 21, 12, 0, 0, tzinfo=datetime.timezone.utc),
    )
    assert result.promoted == ["pullback-support"]
    assert result.demoted == ["current-aggressive"]

    promoted = result.state["sleeves"]["pullback-support"]
    assert promoted["stage"] == "tiny_live_eligible"
    assert promoted["live_enabled"] is True
    assert promoted["preregistered"] is True
    assert promoted["shadow_confirmed"] is True
    assert promoted["benchmark_gate_passed"] is True
    assert promoted["recent_alpha_gate_passed"] is True
    assert promoted["evidence_metrics"]["tracked_days"] == 11

    demoted = result.state["sleeves"]["current-aggressive"]
    assert demoted["stage"] == "paper_only"
    assert demoted["live_enabled"] is False
    assert "turned negative" in demoted["demotion_reason"]


def test_sync_without_arm_live_stays_fail_closed():
    result = sync_promotion_state_from_tournament(
        _report(),
        _incumbent_state(),
        tiny_live_tranche_usd=Decimal("25"),
        arm_live=False,
        ci_green=True,
        now=SYNC_NOW,
    )
    promoted = result.state["sleeves"]["pullback-support"]
    assert promoted["stage"] == "tiny_live_eligible"
    assert promoted["live_enabled"] is False
    assert "none (fail-closed)" in result.summary


def test_sync_quality_gates_block_weak_candidate():
    report = _report()
    report["rankings"][0]["max_drawdown_pct"] = "-12.50"
    result = sync_promotion_state_from_tournament(
        report,
        None,
        tiny_live_tranche_usd=Decimal("25"),
        arm_live=True,
        ci_green=True,
        now=SYNC_NOW,
    )
    assert result.promoted == []
    record = result.state["sleeves"]["pullback-support"]
    assert record["stage"] == "paper_only"
    assert record["live_enabled"] is False
    assert any("max_drawdown_pct" in issue for issue in record["issues"])


def test_sync_requires_ci_attestation():
    result = sync_promotion_state_from_tournament(
        _report(),
        None,
        tiny_live_tranche_usd=Decimal("25"),
        arm_live=True,
        ci_green=False,
        now=SYNC_NOW,
    )
    assert result.promoted == []
    record = result.state["sleeves"]["pullback-support"]
    assert record["stage"] == "paper_only"
    assert "ci_green" in record["issues"]



def _tournament_owner_kwargs(
    monkeypatch,
    tmp_path,
    *,
    report,
    report_bytes: bytes,
    input_state_bytes: bytes,
    output_path,
    risk_envelope_ref: str | None = None,
    risk_envelope_sha256: str | None = None,
    tiny_live_tranche_usd: Decimal = Decimal("25"),
):
    import hashlib

    """Sign one approval bound to the EXACT deterministic transition.

    Mirrors the writer's derivation: parse the same report bytes, run the
    pure tournament sync, embed canonical_input into state, serialize, and
    bind report digest / tournament id / generated_at / input state digest /
    full promoted+demoted+unchanged outcome / resolved output path / full
    resulting state digest.  The risk-envelope binding defaults to a real
    temp envelope file created here (hermetic; no repo/CWD dependence).
    """
    if risk_envelope_ref is None:
        envelope_file = tmp_path / "risk_envelope.yaml"
        envelope_file.write_text(
            "\n".join(
                [
                    "account_max_capital_at_risk_usd: 250.00",
                    "per_name_cap_usd: 50.00",
                    "per_sector_cap_pct: 0.20",
                    "aggregate_beta_cap: 1.25",
                    "daily_loss_halt_usd: 25.00",
                    "max_drawdown_halt_pct: 0.05",
                    "tiny_live_tranche_usd: 25.00",
                    "tiny_live_max_loss_usd: 5.00",
                    "new_sleeve_auto_promote: false",
                    "alert_email: ops@example.com",
                ]
            ),
            encoding="utf-8",
        )
        risk_envelope_ref = str(envelope_file)
        risk_envelope_sha256 = hashlib.sha256(envelope_file.read_bytes()).hexdigest()
    if risk_envelope_sha256 is None:
        risk_envelope_sha256 = hashlib.sha256(
            Path(risk_envelope_ref).read_bytes()
        ).hexdigest()

    import hashlib

    from tests._owner_approval_testing import (
        build_owner_approval,
        install_isolated_owner_trust,
    )
    from tradingagents.policy import promotion_sync as promotion_sync_module
    from tradingagents.policy.promotion_sync import sync_promotion_state_from_tournament

    handle = install_isolated_owner_trust(monkeypatch, tmp_path / "owner", seed=b"promotion-sync-seed")
    # Deterministic fixtures control the private policy clock directly; public
    # ``now`` remains tournament-evaluation evidence and cannot control TTL.
    monkeypatch.setattr(
        promotion_sync_module,
        "_owner_approval_authority_utc_now",
        lambda: SYNC_NOW,
    )
    result = sync_promotion_state_from_tournament(
        json.loads(report_bytes.decode("utf-8")),
        json.loads(input_state_bytes.decode("utf-8")) if input_state_bytes else None,
        tiny_live_tranche_usd=tiny_live_tranche_usd,
        arm_live=True,
        ci_green=True,
        risk_envelope_ref=risk_envelope_ref,
        now=SYNC_NOW,
    )
    result.state["source"]["canonical_input_sha256"] = hashlib.sha256(
        input_state_bytes
    ).hexdigest()
    serialized = json.dumps(result.state, indent=2)
    output_digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    subject = {
        "kind": "tournament_promotion_sync",
        "tournament_id": str(report.get("tournament_id") or ""),
        "report_generated_at": str(report.get("generated_at") or ""),
        "report_sha256": hashlib.sha256(report_bytes).hexdigest(),
        "input_state_sha256": hashlib.sha256(input_state_bytes).hexdigest(),
        "promoted": sorted(result.promoted),
        "demoted": sorted(result.demoted),
        "unchanged": sorted(result.unchanged),
        "output_path": str(Path(output_path).resolve()),
        "output_state_sha256": output_digest,
    }
    source_binding = {
        "kind": "paper_tournament_sync",
        "tournament_id": subject["tournament_id"],
        "report_sha256": subject["report_sha256"],
        "canonical_input_sha256": subject["input_state_sha256"],
    }
    approval = build_owner_approval(
        private_key_hex=handle.private_hex,
        action="live_promotion",
        issued_at=SYNC_NOW,
        ttl_minutes=90,
        subject=subject,
        source_binding=source_binding,
        risk_envelope_ref=risk_envelope_ref,
        risk_envelope_sha256=risk_envelope_sha256,
    )
    return {
        "owner_approval": approval,
        "owner_approval_envelope_ref": risk_envelope_ref,
        "owner_approval_envelope_sha256": risk_envelope_sha256,
        "risk_envelope_ref": risk_envelope_ref,
    }


def test_sync_promotion_state_file_roundtrip(tmp_path, monkeypatch):
    report_path = tmp_path / "latest.json"
    report_bytes = json.dumps(_report()).encode("utf-8")
    report_path.write_bytes(report_bytes)
    state_path = tmp_path / "promotion_state.json"
    incumbent_bytes = json.dumps(_incumbent_state()).encode("utf-8")
    state_path.write_text(json.dumps(_incumbent_state()), encoding="utf-8")
    owner_kwargs = _tournament_owner_kwargs(
        monkeypatch,
        tmp_path,
        report=_report(),
        report_bytes=report_bytes,
        input_state_bytes=incumbent_bytes,
        output_path=state_path,
    )

    result = sync_promotion_state_file(
        report_path,
        state_path,
        tiny_live_tranche_usd=Decimal("25"),
        arm_live=True,
        ci_green=True,
        now=SYNC_NOW,
        **owner_kwargs,
    )
    assert result.promoted == ["pullback-support"]
    written = json.loads(state_path.read_text(encoding="utf-8"))
    assert written["sleeves"]["pullback-support"]["live_enabled"] is True
    assert written["sleeves"]["current-aggressive"]["live_enabled"] is False
    assert written["source"]["kind"] == "paper_tournament_sync"


def test_sync_promotion_historical_evaluation_cannot_rewind_owner_authority_clock(
    tmp_path, monkeypatch
):
    """The public tournament timestamp is evidence, never approval authority."""

    from tradingagents.policy.owner_approval import (
        OwnerApprovalError,
        owner_approval_has_consumption,
    )

    report = _report()
    report_bytes = json.dumps(report).encode("utf-8")
    report_path = tmp_path / "report.json"
    report_path.write_bytes(report_bytes)
    state_path = tmp_path / "promotion_state.json"
    before = json.dumps(_incumbent_state()).encode("utf-8")
    state_path.write_bytes(before)
    owner_kwargs = _tournament_owner_kwargs(
        monkeypatch,
        tmp_path,
        report=report,
        report_bytes=report_bytes,
        input_state_bytes=before,
        output_path=state_path,
    )
    from tradingagents.policy import promotion_sync as promotion_sync_module

    monkeypatch.setattr(
        promotion_sync_module,
        "_owner_approval_authority_utc_now",
        lambda: datetime.datetime.now(tz=datetime.timezone.utc),
    )

    with pytest.raises(OwnerApprovalError, match="expired"):
        sync_promotion_state_file(
            report_path,
            state_path,
            tiny_live_tranche_usd=Decimal("25"),
            arm_live=True,
            ci_green=True,
            # This is deliberately historical tournament-evaluation time.
            now=SYNC_NOW,
            **owner_kwargs,
        )

    assert state_path.read_bytes() == before
    assert owner_approval_has_consumption(
        owner_kwargs["owner_approval"]["approval_id"]
    ) is False


def test_sync_promotion_state_file_can_stage_without_mutating_canonical(tmp_path, monkeypatch):
    report_bytes = json.dumps(_report()).encode("utf-8")
    report_path = tmp_path / "latest.json"
    report_path.write_bytes(report_bytes)
    canonical_path = tmp_path / "promotion_state.json"
    canonical_path.write_text(json.dumps(_incumbent_state()), encoding="utf-8")
    before = canonical_path.read_bytes()
    staged_path = tmp_path / "staging" / "promotion_state.json"
    owner_kwargs = _tournament_owner_kwargs(
        monkeypatch,
        tmp_path,
        report=_report(),
        report_bytes=report_bytes,
        input_state_bytes=before,
        output_path=staged_path,
    )

    result = sync_promotion_state_file(
        report_path,
        canonical_path,
        output_state_path=staged_path,
        tiny_live_tranche_usd=Decimal("25"),
        arm_live=True,
        ci_green=True,
        now=SYNC_NOW,
        **owner_kwargs,
    )

    assert result.promoted == ["pullback-support"]
    assert canonical_path.read_bytes() == before
    staged = json.loads(staged_path.read_text(encoding="utf-8"))
    assert staged["sleeves"]["pullback-support"]["live_enabled"] is True


def test_sync_result_preserves_issues_for_every_sleeve():
    current = _incumbent_state()
    current["sleeves"]["current-aggressive"]["issues"] = [
        "incumbent evidence requires review"
    ]

    result = sync_promotion_state_from_tournament(
        _report(),
        current,
        tiny_live_tranche_usd=Decimal("25"),
        arm_live=True,
        ci_green=True,
        now=SYNC_NOW,
    )

    assert result.issues_by_sleeve == {
        "current-aggressive": ["incumbent evidence requires review"],
        "pullback-support": [],
    }
    assert result.state["sleeves"]["current-aggressive"]["issues"] == [
        "incumbent evidence requires review"
    ]


def test_sync_demotes_live_incumbent_when_ranking_absent():
    report = _fresh_report()
    report["rankings"] = [
        ranking
        for ranking in report["rankings"]
        if ranking["strategy_id"] != "current-aggressive"
    ]

    result = _sync_incumbent(report)

    assert result.demoted == ["current-aggressive"]
    record = result.state["sleeves"]["current-aggressive"]
    assert record["stage"] == "paper_only"
    assert record["live_enabled"] is False
    assert record["demoted_at"] == "2026-06-22T12:00:00+00:00"
    assert "ranking" in record["demotion_reason"]
    assert record["validation_report_ref"] == (
        "results/paper_strategy_tournament/latest.json"
    )
    assert "current-aggressive" not in result.unchanged


def test_sync_demotes_live_incumbent_when_report_generated_at_stale():
    now = datetime.datetime(2026, 6, 30, 12, 0, 0, tzinfo=datetime.timezone.utc)
    assert now - datetime.datetime(
        2026, 6, 20, 21, 12, 35, tzinfo=datetime.timezone.utc
    ) > datetime.timedelta(days=7)

    result = _sync_incumbent(_fresh_report(), now=now)

    assert result.demoted == ["current-aggressive"]
    record = result.state["sleeves"]["current-aggressive"]
    assert record["stage"] == "paper_only"
    assert record["live_enabled"] is False
    assert "stale" in record["demotion_reason"]
    assert "turned negative" not in record["demotion_reason"]


def test_sync_demotes_live_incumbent_when_report_generated_at_invalid():
    report = _fresh_report()
    report["generated_at"] = "not-a-timestamp"

    result = _sync_incumbent(report)

    assert result.demoted == ["current-aggressive"]
    record = result.state["sleeves"]["current-aggressive"]
    assert record["stage"] == "paper_only"
    assert record["live_enabled"] is False
    assert "invalid" in record["demotion_reason"]
    assert "turned negative" not in record["demotion_reason"]


def test_sync_demotes_live_incumbent_when_report_generated_at_future():
    report = _fresh_report()
    report["generated_at"] = "2026-06-23T00:00:00+00:00"

    result = _sync_incumbent(report)

    assert result.demoted == ["current-aggressive"]
    record = result.state["sleeves"]["current-aggressive"]
    assert record["stage"] == "paper_only"
    assert record["live_enabled"] is False
    assert "future" in record["demotion_reason"]
    assert "turned negative" not in record["demotion_reason"]


def test_sync_accepts_fresh_canonical_generated_at():
    result = _sync_incumbent(_fresh_report())

    assert result.promoted == ["pullback-support"]
    assert result.demoted == []
    promoted = result.state["sleeves"]["pullback-support"]
    assert promoted["stage"] == "tiny_live_eligible"
    assert promoted["live_enabled"] is True
    assert result.state["sleeves"]["current-aggressive"]["live_enabled"] is True


def test_sync_accepts_report_one_second_inside_evidence_ceiling():
    report = _fresh_report()
    report["generated_at"] = _iso(
        SYNC_NOW
        - datetime.timedelta(seconds=INTERNAL_EVIDENCE_MAX_AGE_SECONDS)
        + datetime.timedelta(seconds=1)
    )

    result = _sync_incumbent(report)

    assert result.promoted == ["pullback-support"]
    assert result.demoted == []


@pytest.mark.parametrize(
    ("case", "generated_at", "expected_fragment"),
    [
        ("missing", None, "generated_at is missing"),
        ("invalid", "not-a-timestamp", "generated_at is invalid"),
        ("naive", "2026-06-20T21:12:35", "timezone-naive"),
        ("future", _iso(SYNC_NOW + datetime.timedelta(seconds=1)), "in the future"),
        (
            "stale_exact_boundary",
            _iso(SYNC_NOW - datetime.timedelta(seconds=INTERNAL_EVIDENCE_MAX_AGE_SECONDS)),
            "is stale",
        ),
        # Python >=3.10 support: a Z suffix may parse as non-canonical UTC
        # (3.11+) or fail fromisoformat outright (3.10); both are rejections.
        ("z_suffix", "2026-06-20T21:12:35Z", ("generated_at is invalid", "not canonical UTC")),
        ("fractional_seconds", "2026-06-20T21:12:35.250000+00:00", "not canonical UTC"),
        ("non_utc_offset", "2026-06-20T16:12:35-05:00", "not canonical UTC"),
    ],
)
def test_sync_rejects_non_canonical_generated_at(case, generated_at, expected_fragment):
    report = _fresh_report()
    if generated_at is None:
        report.pop("generated_at")
    else:
        report["generated_at"] = generated_at

    result = _sync_incumbent(report)

    assert result.promoted == []
    assert result.demoted == ["current-aggressive"]

    candidate = result.state["sleeves"]["pullback-support"]
    assert candidate["stage"] == "paper_only"
    assert candidate["live_enabled"] is False
    assert any(
        issue.startswith("tournament evidence rejected:")
        for issue in candidate["issues"]
    )
    fragments = (
        expected_fragment if isinstance(expected_fragment, tuple) else (expected_fragment,)
    )
    assert any(
        any(fragment in issue for fragment in fragments)
        for issue in candidate["issues"]
    )

    incumbent = result.state["sleeves"]["current-aggressive"]
    assert incumbent["stage"] == "paper_only"
    assert incumbent["live_enabled"] is False
    assert "tournament evidence rejected:" in incumbent["demotion_reason"]


def test_sync_stale_incumbent_demotes_and_blocks_candidate_in_same_call():
    report = _fresh_report()
    report["generated_at"] = _iso(SYNC_NOW - datetime.timedelta(days=8))

    result = _sync_incumbent(report)

    assert result.demoted == ["current-aggressive"]
    assert result.promoted == []
    assert result.state["sleeves"]["current-aggressive"]["stage"] == "paper_only"
    candidate = result.state["sleeves"]["pullback-support"]
    assert candidate["stage"] == "paper_only"
    assert candidate["live_enabled"] is False
    assert any("stale" in issue for issue in candidate["issues"])


@pytest.mark.parametrize(
    ("overrides", "metric"),
    [
        ({"tracked_days": 4}, "tracked_days"),
        ({"max_drawdown_pct": "-10.50"}, "max_drawdown_pct"),
        ({"win_rate_pct": "49.99"}, "win_rate_pct"),
    ],
)
def test_sync_demotes_quality_floor_breaching_incumbent(overrides, metric):
    report = _fresh_report()
    for ranking in report["rankings"]:
        if ranking["strategy_id"] == "current-aggressive":
            ranking.update(overrides)

    result = _sync_incumbent(report)

    assert result.demoted == ["current-aggressive"]
    record = result.state["sleeves"]["current-aggressive"]
    assert record["stage"] == "paper_only"
    assert record["live_enabled"] is False
    assert "quality floor" in record["demotion_reason"]
    assert metric in record["demotion_reason"]
    assert "turned negative" not in record["demotion_reason"]


def test_resolve_live_sleeve_prefers_backed_selection():
    selection = {"status": "active", "strategy_id": "pullback-support"}
    promotion_state = {
        "sleeves": {
            "pullback-support": {
                "stage": "tiny_live_eligible",
                "live_enabled": True,
            }
        }
    }
    sleeve, reason = resolve_live_sleeve(selection, promotion_state)
    assert sleeve == "pullback-support"
    assert "live-enabled promotion record" in reason


def test_resolve_live_sleeve_falls_back_to_enabled_sleeve():
    selection = {"status": "active", "strategy_id": "pullback-support"}
    promotion_state = {
        "sleeves": {
            "current-aggressive": {
                "stage": "tiny_live_eligible",
                "live_enabled": True,
            },
            "pullback-support": {"stage": "paper_only", "live_enabled": False},
        }
    }
    sleeve, reason = resolve_live_sleeve(selection, promotion_state)
    assert sleeve == "current-aggressive"
    assert "not live-enabled" in reason


def test_resolve_live_sleeve_fail_closed_default():
    sleeve, reason = resolve_live_sleeve(None, None)
    assert sleeve == LIVE_AGGRESSIVE_SLEEVE
    assert "fail-closed" in reason


def _empty_state() -> bytes:
    return json.dumps({"schema_version": "1.0.0", "sleeves": {}}).encode("utf-8")


def _incumbent_valid_state() -> bytes:
    return json.dumps(_incumbent_state()).encode("utf-8")


def test_approval_for_report_or_tournament_a_cannot_write_b(tmp_path, monkeypatch):
    from tradingagents.policy.owner_approval import OwnerApprovalError

    report_a = _report()
    report_a_bytes = json.dumps(report_a).encode("utf-8")
    input_state = _empty_state()
    output_path = tmp_path / "promotion.json"
    owner_kwargs = _tournament_owner_kwargs(
        monkeypatch,
        tmp_path,
        report=report_a,
        report_bytes=report_a_bytes,
        input_state_bytes=input_state,
        output_path=output_path,
    )
    approval = owner_kwargs["owner_approval"]

    # Tournament B: different id and metrics, same schema.
    report_b = _report()
    report_b["tournament_id"] = "paper-tournament-B"
    report_b["rankings"][0]["total_return"] = "312.36"
    report_b_file = tmp_path / "report-b.json"
    report_b_file.write_text(json.dumps(report_b), encoding="utf-8")
    in_b = tmp_path / "state-b.json"
    in_b.write_bytes(input_state)
    out_b = tmp_path / "out-b.json"

    with pytest.raises(OwnerApprovalError):
        sync_promotion_state_file(
            report_b_file,
            in_b,
            output_state_path=out_b,
            tiny_live_tranche_usd=Decimal("25"),
            arm_live=True,
            ci_green=True,
            now=SYNC_NOW,
            owner_approval=approval,
            owner_approval_envelope_ref=owner_kwargs["owner_approval_envelope_ref"],
            owner_approval_envelope_sha256=owner_kwargs["owner_approval_envelope_sha256"],
        )
    assert not out_b.exists()

    # Report A content changed (different digest) with tournament A id kept.
    report_a_mutated = dict(report_a)
    report_a_mutated["generated_at"] = "2026-06-20T21:12:36+00:00"
    report_a2_file = tmp_path / "report-a2.json"
    report_a2_file.write_text(json.dumps(report_a_mutated), encoding="utf-8")
    in_a2 = tmp_path / "state-a2.json"
    in_a2.write_bytes(input_state)
    out_a2 = tmp_path / "out-a2.json"

    with pytest.raises(OwnerApprovalError):
        sync_promotion_state_file(
            report_a2_file,
            in_a2,
            output_state_path=out_a2,
            tiny_live_tranche_usd=Decimal("25"),
            arm_live=True,
            ci_green=True,
            now=SYNC_NOW,
            owner_approval=approval,
            owner_approval_envelope_ref=owner_kwargs["owner_approval_envelope_ref"],
            owner_approval_envelope_sha256=owner_kwargs["owner_approval_envelope_sha256"],
        )
    assert not out_a2.exists()


def test_changed_output_path_or_preimage_denies(tmp_path, monkeypatch):
    from tradingagents.policy.owner_approval import OwnerApprovalError

    report = _report()
    report_bytes = json.dumps(report).encode("utf-8")
    intended_output = tmp_path / "intended.json"
    kwargs = {
        "report": report,
        "report_bytes": report_bytes,
        "input_state_bytes": _empty_state(),
        "output_path": intended_output,
    }
    owner_kwargs = _tournament_owner_kwargs(monkeypatch, tmp_path, **kwargs)
    approval = owner_kwargs["owner_approval"]

    # Changed resolved output path.
    other_dir = tmp_path / "other"
    other_dir.mkdir()
    other_output = other_dir / "promotion.json"
    in1 = tmp_path / "in1.json"
    in1.write_bytes(_empty_state())
    report1 = tmp_path / "report1.json"
    report1.write_bytes(report_bytes)

    with pytest.raises(OwnerApprovalError):
        sync_promotion_state_file(
            report1,
            in1,
            output_state_path=other_output,
            tiny_live_tranche_usd=Decimal("25"),
            arm_live=True,
            ci_green=True,
            now=SYNC_NOW,
            owner_approval=approval,
            owner_approval_envelope_ref=owner_kwargs["owner_approval_envelope_ref"],
            owner_approval_envelope_sha256=owner_kwargs["owner_approval_envelope_sha256"],
        )
    assert not other_output.exists()

    # Changed input-state preimage: a valid incumbent state instead of empty.
    in2 = tmp_path / "in2.json"
    in2.write_bytes(_incumbent_valid_state())
    report2 = tmp_path / "report2.json"
    report2.write_bytes(report_bytes)

    with pytest.raises(OwnerApprovalError):
        sync_promotion_state_file(
            report2,
            in2,
            output_state_path=intended_output,
            tiny_live_tranche_usd=Decimal("25"),
            arm_live=True,
            ci_green=True,
            now=SYNC_NOW,
            owner_approval=approval,
            owner_approval_envelope_ref=owner_kwargs["owner_approval_envelope_ref"],
            owner_approval_envelope_sha256=owner_kwargs["owner_approval_envelope_sha256"],
        )
    assert not intended_output.exists()

    # Different full decision outcome while retaining the tournament id:
    # shifted generated_at changes embedded source and resulting state.
    mutated = dict(report)
    mutated["generated_at"] = "2026-06-20T21:12:36+00:00"
    in3 = tmp_path / "in3.json"
    in3.write_bytes(_empty_state())
    report3 = tmp_path / "report3.json"
    report3.write_text(json.dumps(mutated), encoding="utf-8")

    with pytest.raises(OwnerApprovalError):
        sync_promotion_state_file(
            report3,
            in3,
            output_state_path=intended_output,
            tiny_live_tranche_usd=Decimal("25"),
            arm_live=True,
            ci_green=True,
            now=SYNC_NOW,
            owner_approval=approval,
            owner_approval_envelope_ref=owner_kwargs["owner_approval_envelope_ref"],
            owner_approval_envelope_sha256=owner_kwargs["owner_approval_envelope_sha256"],
        )
    assert not intended_output.exists()


def test_batch_consumption_is_all_or_nothing(tmp_path, monkeypatch):
    """A rejected second artifact must not burn the first: preflight catches
    the replay before any durable consumption is written."""

    from tests._owner_approval_testing import (
        build_owner_approval,
        install_isolated_owner_trust,
    )
    from tradingagents.policy.owner_approval import (
        consume_owner_approvals_batch,
        owner_approval_has_consumption,
    )

    handle = install_isolated_owner_trust(monkeypatch, tmp_path / "owner", seed=b"promotion-sync-seed")
    first = build_owner_approval(
        private_key_hex=handle.private_hex,
        action="live_promotion",
        issued_at=SYNC_NOW,
        ttl_minutes=30,
        subject={"k": "1"},
        source_binding={},
        risk_envelope_ref="config/risk_envelope.yaml",
        risk_envelope_sha256="e" * 64,
    )
    second = dict(first)  # same approval_id -> replay inside the batch

    entries = [
        {
            "approval_id": first["approval_id"],
            "action": "live_promotion",
            "purpose": "p1",
            "transaction_binding_sha256": "a" * 64,
        },
        {
            "approval_id": second["approval_id"],
            "action": "live_promotion",
            "purpose": "p2",
            "transaction_binding_sha256": "b" * 64,
        },
    ]
    with pytest.raises(Exception, match="duplicate approval id"):
        consume_owner_approvals_batch(entries, now=SYNC_NOW)
    assert not handle.ledger.exists()
    assert owner_approval_has_consumption(first["approval_id"]) is False


def test_cli_sync_promotion_valid_artifact_promotes_end_to_end(tmp_path, monkeypatch):
    """A valid owner artifact promotes end-to-end through the CLI: the
    live-eligible state is written. Envelope binding is derived internally
    from the selected envelope file's bytes."""

    from typer.testing import CliRunner

    from cli.main import app

    envelope_path = tmp_path / "risk_envelope.yaml"
    envelope_path.write_text(
        "\n".join(
            [
                "account_max_capital_at_risk_usd: 250.00",
                "per_name_cap_usd: 50.00",
                "per_sector_cap_pct: 0.20",
                "aggregate_beta_cap: 1.25",
                "daily_loss_halt_usd: 25.00",
                "max_drawdown_halt_pct: 0.05",
                "tiny_live_tranche_usd: 25.00",
                "tiny_live_max_loss_usd: 5.00",
                "new_sleeve_auto_promote: false",
                "alert_email: ops@example.com",
            ]
        ),
        encoding="utf-8",
    )
    report = _report()
    report_bytes = json.dumps(report).encode("utf-8")
    input_state = _empty_state()
    state_path = tmp_path / "promotion_state.json"
    state_path.write_bytes(input_state)
    report_path = tmp_path / "report.json"
    report_path.write_bytes(report_bytes)

    kwargs = _tournament_owner_kwargs(
        monkeypatch,
        tmp_path,
        report=report,
        report_bytes=report_bytes,
        input_state_bytes=input_state,
        output_path=state_path,
        risk_envelope_ref=str(envelope_path.resolve()),
        risk_envelope_sha256=hashlib.sha256(
            envelope_path.read_bytes()
        ).hexdigest(),
        tiny_live_tranche_usd=Decimal("25.00"),
    )
    artifact_file = tmp_path / "owner-approval.json"
    artifact_file.write_text(
        json.dumps(kwargs["owner_approval"]), encoding="utf-8"
    )

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "policy", "sync-promotion",
            "--report-path", str(report_path),
            "--state-path", str(state_path),
            "--envelope-path", str(envelope_path),
            "--arm-live",
            "--ci-green",
            "--generated-at", SYNC_NOW.isoformat(),
            "--json-output",
            "--owner-approval-path", str(artifact_file),
        ],
        catch_exceptions=False,
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["promoted"] == ["pullback-support"]
    written = json.loads(state_path.read_text(encoding="utf-8"))
    assert written["sleeves"]["pullback-support"]["stage"] == "tiny_live_eligible"
    assert written["sleeves"]["pullback-support"]["live_enabled"] is True
    # The stored promotion state describes the same policy-owned envelope the
    # CLI validated and the artifact signed — not a default alias.
    assert (
        written["sleeves"]["pullback-support"]["risk_envelope_ref"]
        == str(envelope_path.resolve())
    )


def test_cli_historical_generated_at_cannot_rewind_owner_approval_ttl(
    tmp_path, monkeypatch
):
    """``--generated-at`` remains evidence time and cannot revive an approval."""

    from typer.testing import CliRunner

    from cli.main import app
    from tradingagents.policy.owner_approval import owner_approval_has_consumption

    envelope_path = tmp_path / "risk_envelope.yaml"
    envelope_path.write_text(
        "\n".join(
            [
                "account_max_capital_at_risk_usd: 250.00",
                "per_name_cap_usd: 50.00",
                "per_sector_cap_pct: 0.20",
                "aggregate_beta_cap: 1.25",
                "daily_loss_halt_usd: 25.00",
                "max_drawdown_halt_pct: 0.05",
                "tiny_live_tranche_usd: 25.00",
                "tiny_live_max_loss_usd: 5.00",
                "new_sleeve_auto_promote: false",
                "alert_email: ops@example.com",
            ]
        ),
        encoding="utf-8",
    )
    report = _report()
    report_bytes = json.dumps(report).encode("utf-8")
    report_path = tmp_path / "report.json"
    report_path.write_bytes(report_bytes)
    state_path = tmp_path / "promotion_state.json"
    before = _empty_state()
    state_path.write_bytes(before)
    owner_kwargs = _tournament_owner_kwargs(
        monkeypatch,
        tmp_path,
        report=report,
        report_bytes=report_bytes,
        input_state_bytes=before,
        output_path=state_path,
        risk_envelope_ref=str(envelope_path.resolve()),
        risk_envelope_sha256=hashlib.sha256(envelope_path.read_bytes()).hexdigest(),
        tiny_live_tranche_usd=Decimal("25.00"),
    )
    from tradingagents.policy import promotion_sync as promotion_sync_module

    monkeypatch.setattr(
        promotion_sync_module,
        "_owner_approval_authority_utc_now",
        lambda: datetime.datetime.now(tz=datetime.timezone.utc),
    )
    artifact_path = tmp_path / "expired-owner-approval.json"
    artifact_path.write_text(
        json.dumps(owner_kwargs["owner_approval"]), encoding="utf-8"
    )

    result = CliRunner().invoke(
        app,
        [
            "policy",
            "sync-promotion",
            "--report-path",
            str(report_path),
            "--state-path",
            str(state_path),
            "--envelope-path",
            str(envelope_path),
            "--arm-live",
            "--ci-green",
            "--generated-at",
            SYNC_NOW.isoformat(),
            "--owner-approval-path",
            str(artifact_path),
        ],
    )

    assert result.exit_code != 0
    assert result.exception is not None
    assert "expired" in str(result.exception).lower()
    assert state_path.read_bytes() == before
    assert owner_approval_has_consumption(
        owner_kwargs["owner_approval"]["approval_id"]
    ) is False


def test_cli_sync_promotion_changed_custom_envelope_refuses(tmp_path, monkeypatch):
    """An approval signed against custom-envelope v1 is refused when the
    envelope file has changed to v2 before invocation; no output write."""

    from typer.testing import CliRunner

    from cli.main import app

    envelope_v1 = "\n".join(
        [
            "account_max_capital_at_risk_usd: 250.00",
            "per_name_cap_usd: 50.00",
            "per_sector_cap_pct: 0.20",
            "aggregate_beta_cap: 1.25",
            "daily_loss_halt_usd: 25.00",
            "max_drawdown_halt_pct: 0.05",
            "tiny_live_tranche_usd: 25.00",
            "tiny_live_max_loss_usd: 5.00",
            "new_sleeve_auto_promote: false",
            "alert_email: ops@example.com",
        ]
    )
    envelope_v2 = envelope_v1.replace("per_name_cap_usd: 50.00", "per_name_cap_usd: 40.00")
    envelope_path = tmp_path / "risk_envelope.yaml"

    report = _report()
    report_bytes = json.dumps(report).encode("utf-8")
    input_state = _empty_state()
    state_path = tmp_path / "promotion_state.json"
    state_path.write_bytes(input_state)
    report_path = tmp_path / "report.json"
    report_path.write_bytes(report_bytes)

    # Sign against v1 bytes.
    kwargs = _tournament_owner_kwargs(
        monkeypatch,
        tmp_path,
        report=report,
        report_bytes=report_bytes,
        input_state_bytes=input_state,
        output_path=state_path,
        risk_envelope_ref=str(envelope_path.resolve()),
        risk_envelope_sha256=hashlib.sha256(envelope_v1.encode("utf-8")).hexdigest(),
        tiny_live_tranche_usd=Decimal("25.00"),
    )
    artifact_file = tmp_path / "owner-approval.json"
    artifact_file.write_text(json.dumps(kwargs["owner_approval"]), encoding="utf-8")

    # Swap to v2 (still a valid envelope) before invocation.
    envelope_path.write_text(envelope_v2, encoding="utf-8")
    before = state_path.read_bytes()

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "policy", "sync-promotion",
            "--report-path", str(report_path),
            "--state-path", str(state_path),
            "--envelope-path", str(envelope_path),
            "--arm-live",
            "--ci-green",
            "--generated-at", SYNC_NOW.isoformat(),
            "--json-output",
            "--owner-approval-path", str(artifact_file),
        ],
        catch_exceptions=True,
    )
    assert result.exit_code != 0
    combined = f"{result.output}{result.exception}"
    assert "risk envelope" in combined
    assert state_path.read_bytes() == before


def test_cli_sync_promotion_binding_mismatch_writes_nothing(tmp_path, monkeypatch):
    """An approval bound to a different tournament report digest is refused;
    no output state is written."""

    from typer.testing import CliRunner

    from cli.main import app

    envelope_path = tmp_path / "risk_envelope.yaml"
    envelope_path.write_text(
        "\n".join(
            [
                "account_max_capital_at_risk_usd: 250.00",
                "per_name_cap_usd: 50.00",
                "per_sector_cap_pct: 0.20",
                "aggregate_beta_cap: 1.25",
                "daily_loss_halt_usd: 25.00",
                "max_drawdown_halt_pct: 0.05",
                "tiny_live_tranche_usd: 25.00",
                "tiny_live_max_loss_usd: 5.00",
                "new_sleeve_auto_promote: false",
                "alert_email: ops@example.com",
            ]
        ),
        encoding="utf-8",
    )
    report = _report()
    report_bytes = json.dumps(report).encode("utf-8")
    input_state = _empty_state()
    state_path = tmp_path / "promotion_state.json"
    state_path.write_bytes(input_state)
    report_path = tmp_path / "report.json"
    report_path.write_bytes(report_bytes)

    # Sign against DIFFERENT report bytes (mutated metrics) than the file on
    # disk: the derived report digest will mismatch.
    mutated_report = dict(report)
    mutated_report["rankings"] = [
        dict(item, total_return="999.99") for item in report["rankings"]
    ]
    kwargs = _tournament_owner_kwargs(
        monkeypatch,
        tmp_path,
        report=mutated_report,
        report_bytes=json.dumps(mutated_report).encode("utf-8"),
        input_state_bytes=input_state,
        output_path=state_path,
        risk_envelope_ref=str(envelope_path.resolve()),
        risk_envelope_sha256=hashlib.sha256(
            envelope_path.read_bytes()
        ).hexdigest(),
        tiny_live_tranche_usd=Decimal("25.00"),
    )
    artifact_file = tmp_path / "owner-approval.json"
    artifact_file.write_text(
        json.dumps(kwargs["owner_approval"]), encoding="utf-8"
    )
    before = state_path.read_bytes()

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "policy", "sync-promotion",
            "--report-path", str(report_path),
            "--state-path", str(state_path),
            "--envelope-path", str(envelope_path),
            "--arm-live",
            "--ci-green",
            "--generated-at", SYNC_NOW.isoformat(),
            "--json-output",
            "--owner-approval-path", str(artifact_file),
        ],
        catch_exceptions=True,
    )
    assert result.exit_code != 0
    assert state_path.read_bytes() == before


def test_cli_sync_promotion_rejects_unreadable_owner_artifact(tmp_path):
    from typer.testing import CliRunner

    from cli.main import app

    bad_artifact = tmp_path / "bad-owner.json"
    bad_artifact.write_text("{not json", encoding="utf-8")
    report_path = tmp_path / "report.json"
    report_path.write_text("{}", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "policy", "sync-promotion",
            "--report-path", str(report_path),
            "--owner-approval-path", str(bad_artifact),
        ],
        catch_exceptions=True,
    )
    combined = str(result.exception) if result.exception else ""
    output = result.output or ""
    assert (
        "owner approval artifact unreadable" in output
        or "owner approval artifact unreadable" in combined
    )


def test_envelope_race_before_consumption_denies_and_writes_nothing(
    tmp_path, monkeypatch
):
    """P2-3 injected race: if the bound envelope file is changed between
    signing and the writer's final source validation, the promotion refuses
    with no output write and the approval remains unconsumed."""

    from tradingagents.policy.owner_approval import (
        owner_approval_has_consumption,
    )

    report = _report()
    report_bytes = json.dumps(report).encode("utf-8")
    input_state = _empty_state()
    intended_output = tmp_path / "intended.json"
    kwargs = _tournament_owner_kwargs(
        monkeypatch,
        tmp_path,
        report=report,
        report_bytes=report_bytes,
        input_state_bytes=input_state,
        output_path=intended_output,
    )
    approval = kwargs["owner_approval"]
    envelope_ref = kwargs["risk_envelope_ref"]

    in_file = tmp_path / "in-race.json"
    in_file.write_bytes(input_state)
    report_file = tmp_path / "report-race.json"
    report_file.write_bytes(report_bytes)

    # Inject the race: mutate the envelope after the artifact was signed but
    # before the writer's final validation runs.
    original_read_bytes = Path.read_bytes

    def racing_read_bytes(self, *args, **kwargs):
        data = original_read_bytes(self, *args, **kwargs)
        if str(self) == str(envelope_ref):
            mutated = data.replace(b"50.00", b"45.00", 1)
            if mutated != data:
                envelope_ref_path = Path(str(self) + ".mutated-marker")
                envelope_ref_path.write_bytes(b"1")
            return mutated
        return data

    monkeypatch.setattr(Path, "read_bytes", racing_read_bytes)

    with pytest.raises(ValueError, match="bound risk envelope"):
        sync_promotion_state_file(
            report_file,
            in_file,
            output_state_path=intended_output,
            tiny_live_tranche_usd=Decimal("25"),
            arm_live=True,
            ci_green=True,
            now=SYNC_NOW,
            owner_approval=approval,
            owner_approval_envelope_ref=envelope_ref,
            owner_approval_envelope_sha256=kwargs[
                "owner_approval_envelope_sha256"
            ],
        )

    assert not intended_output.exists()
    assert owner_approval_has_consumption(approval["approval_id"]) is False


@pytest.mark.parametrize("tamper_consumed_sidecar", (False, True))
def test_sync_promotion_prepare_crash_recovers_after_approval_expiry(
    tmp_path, monkeypatch, tamper_consumed_sidecar
):
    """Crash-safe contract for tournament sync: a crash between approval
    consumption and the durable write leaves a strict sibling prepare; an
    exact retry after the artifact TTL expires finalizes from prepare plus
    ledger evidence without a second consumption."""
    report = _report()
    report_bytes = json.dumps(report).encode("utf-8")
    input_state = _empty_state()
    state_path = tmp_path / "promotion_state.json"
    state_path.write_bytes(input_state)
    report_file = tmp_path / "report.json"
    report_file.write_bytes(report_bytes)
    output_path = tmp_path / "out.json"
    owner_kwargs = _tournament_owner_kwargs(
        monkeypatch,
        tmp_path,
        report=report,
        report_bytes=report_bytes,
        input_state_bytes=input_state,
        output_path=output_path,
    )
    # Crash injection: fail the atomic write on the first attempt only.
    real_write = atomic_write_text
    calls = {"n": 0}

    def flaky_write(path, text, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1 and Path(path) == output_path:
            raise OSError("simulated promotion state write failure")
        return real_write(path, text, **kwargs)

    monkeypatch.setattr(
        __import__("tradingagents.policy.promotion_sync", fromlist=["atomic_write_text"]),
        "atomic_write_text",
        flaky_write,
    )

    with pytest.raises(OSError, match="simulated promotion state write failure"):
        sync_promotion_state_file(
            tmp_path / "report.json",
            state_path,
            output_state_path=output_path,
            tiny_live_tranche_usd=Decimal("25"),
            arm_live=True,
            ci_green=True,
            now=SYNC_NOW,
            **owner_kwargs,
    )
    assert not output_path.exists()

    # Move the policy-owned authority clock past the artifact TTL.  Exact
    # prepare-plus-ledger recovery below must not ask the expired signature to
    # become current again, while a tampered sidecar remains inert.
    from tradingagents.policy import promotion_sync as promotion_sync_module

    late_now = SYNC_NOW + datetime.timedelta(hours=2)
    monkeypatch.setattr(
        promotion_sync_module,
        "_owner_approval_authority_utc_now",
        lambda: late_now,
    )

    if tamper_consumed_sidecar:
        from tradingagents.policy.owner_approval import (
            OwnerApprovalError,
            owner_approval_has_consumption,
            owner_approval_prepare_path,
        )

        # The first attempt reached durable generic consumption before its
        # output write failed.  A changed sidecar cannot finalize that burned
        # approval after expiry, nor can it write the promotion state.
        assert owner_approval_has_consumption(owner_kwargs["owner_approval"]["approval_id"])
        sidecar = owner_approval_prepare_path(output_path)
        raw = json.loads(sidecar.read_text(encoding="utf-8"))
        raw["transaction"]["serialized_output"] = "{}"
        sidecar.write_text(json.dumps(raw), encoding="utf-8")
        with pytest.raises(OwnerApprovalError, match="prepare|transaction|expired"):
            sync_promotion_state_file(
                tmp_path / "report.json",
                state_path,
                output_state_path=output_path,
                tiny_live_tranche_usd=Decimal("25"),
                arm_live=True,
                ci_green=True,
                now=late_now,
                **owner_kwargs,
            )
        assert not output_path.exists()
        assert owner_approval_has_consumption(owner_kwargs["owner_approval"]["approval_id"])
        return

    # Retry after TTL expiry (artifact issued at SYNC_NOW with 30-min TTL;
    # retry clock is far later) finalizes exactly once.
    result = sync_promotion_state_file(
        tmp_path / "report.json",
        state_path,
        output_state_path=output_path,
        tiny_live_tranche_usd=Decimal("25"),
        arm_live=True,
        ci_green=True,
        now=late_now,
        **owner_kwargs,
    )
    assert result.promoted == ["pullback-support"]
    assert json.loads(output_path.read_text(encoding="utf-8"))["sleeves"][
        "pullback-support"
    ]["live_enabled"] is True
    from tradingagents.policy.owner_approval import (
        canonical_owner_consumption_ledger_path,
        owner_approval_has_consumption,
    )

    approval_id = owner_kwargs["owner_approval"]["approval_id"]
    assert owner_approval_has_consumption(approval_id)
    matching = [
        json.loads(line)
        for line in canonical_owner_consumption_ledger_path().read_text(
            encoding="utf-8"
        ).splitlines()
        if json.loads(line)["approval_id"] == approval_id
    ]
    assert len(matching) == 1
