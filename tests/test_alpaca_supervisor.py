import datetime
import json
from decimal import Decimal
from pathlib import Path

import pytest

from tradingagents.brokers.alpaca import (
    AlpacaExecutionConfig,
    AlpacaRestClient,
    AlpacaSettings,
)
from tradingagents.brokers.alpaca_supervisor import (
    CandidateSignal,
    HourlySupervisorAction,
    HourlySupervisorConfig,
    HourlySupervisorDecision,
    aggressive_limit_price,
    build_buy_candidate_decision,
    build_candidate_signals,
    build_hourly_decision,
    build_hourly_decision_context,
    build_hourly_evidence,
    build_loss_review_decision,
    build_open_orders_review_decision,
    build_overnight_candidate_universe,
    build_portfolio_snapshot,
    build_premarket_brief_packet,
    build_profit_take_decision,
    build_trailing_hold_decision,
    calculate_dynamic_live_cap,
    choose_autonomous_live_buy_notional,
    classify_supervisor_alert,
    compact_hourly_supervisor_payload,
    compact_premarket_brief_payload,
    find_latest_hourly_packet,
    is_expected_hourly_safety_lock,
    is_order_action,
    load_latest_overnight_plan,
    load_latest_premarket_brief,
    loss_exit_review_packet,
    market_session_label,
    render_daily_supervisor_report,
    render_overnight_plan_markdown,
    render_premarket_brief_markdown,
    serialize_hourly_decision,
    should_notify_supervisor,
    submit_authorized_normal_live_order,
    supervisor_issue_category,
    supervisor_live_client_order_id,
    validate_hourly_supervisor_actions,
    validate_overnight_plan_against_candidates,
    validate_premarket_brief_against_candidates,
    write_hourly_decision_packet,
    write_overnight_plan_packet,
    write_premarket_brief_packet,
)
from tradingagents.brokers.supervisor import candidates as supervisor_candidates
from tradingagents.brokers.supervisor import daily_report as supervisor_daily_report
from tradingagents.brokers.supervisor import hourly as supervisor_hourly
from tradingagents.brokers.supervisor import loss_review as supervisor_loss_review
from tradingagents.brokers.supervisor import orders as supervisor_orders
from tradingagents.brokers.supervisor import overnight as supervisor_overnight
from tradingagents.brokers.supervisor import premarket as supervisor_premarket
from tradingagents.brokers.supervisor import session as supervisor_session
from tradingagents.brokers.supervisor import sizing as supervisor_sizing
from tradingagents.brokers.supervisor import types as supervisor_types
from tradingagents.evals.email_clarity import evaluate_email_clarity
from tradingagents.policy.strategy_promotion_sync import NormalLiveActivationReceipt


def test_candidate_helpers_are_extracted_but_legacy_facade_stays_compatible():
    assert supervisor_candidates.CandidateSignal is CandidateSignal
    assert supervisor_candidates.build_candidate_signals is build_candidate_signals
    assert supervisor_candidates.choose_autonomous_live_buy_notional is choose_autonomous_live_buy_notional
    assert supervisor_candidates.aggressive_limit_price is aggressive_limit_price
    assert supervisor_types.HourlySupervisorAction is HourlySupervisorAction
    assert supervisor_types.HourlySupervisorConfig is HourlySupervisorConfig
    assert supervisor_types.HourlySupervisorDecision is HourlySupervisorDecision
    assert supervisor_sizing.calculate_dynamic_live_cap is calculate_dynamic_live_cap
    assert supervisor_session.market_session_label is market_session_label
    assert supervisor_hourly.build_hourly_decision is not None
    assert supervisor_hourly.build_hourly_decision_context is build_hourly_decision_context
    assert supervisor_hourly.build_buy_candidate_decision is build_buy_candidate_decision
    assert supervisor_hourly.build_loss_review_decision is build_loss_review_decision
    assert supervisor_hourly.build_open_orders_review_decision is build_open_orders_review_decision
    assert supervisor_hourly.build_profit_take_decision is build_profit_take_decision
    assert supervisor_hourly.build_trailing_hold_decision is build_trailing_hold_decision
    assert supervisor_hourly.build_hourly_evidence is not None
    assert supervisor_hourly.find_latest_hourly_packet is find_latest_hourly_packet
    assert supervisor_hourly.compact_hourly_supervisor_payload is compact_hourly_supervisor_payload
    assert supervisor_hourly.serialize_hourly_decision is not None
    assert supervisor_hourly.write_hourly_decision_packet is not None
    assert supervisor_orders.should_notify_supervisor is should_notify_supervisor
    assert supervisor_orders.is_order_action is is_order_action
    assert supervisor_orders.build_supervisor_order_payload is not None
    assert supervisor_loss_review.loss_exit_review_packet is loss_exit_review_packet
    assert supervisor_premarket.is_expected_hourly_safety_lock is is_expected_hourly_safety_lock
    assert (
        supervisor_premarket.validate_premarket_brief_against_candidates
        is validate_premarket_brief_against_candidates
    )
    assert supervisor_premarket.compact_premarket_brief_payload is compact_premarket_brief_payload
    assert supervisor_premarket.write_premarket_brief_packet is write_premarket_brief_packet
    assert supervisor_premarket.render_premarket_brief_markdown is render_premarket_brief_markdown
    assert supervisor_premarket.load_latest_premarket_brief is load_latest_premarket_brief
    assert supervisor_overnight.write_overnight_plan_packet is write_overnight_plan_packet
    assert supervisor_overnight.render_overnight_plan_markdown is render_overnight_plan_markdown
    assert supervisor_overnight.load_latest_overnight_plan is load_latest_overnight_plan
    assert (
        supervisor_overnight.validate_overnight_plan_against_candidates
        is validate_overnight_plan_against_candidates
    )


def test_supervisor_forwards_the_identical_normal_intent_receipt_and_admission_to_live_client(
    tmp_path,
    monkeypatch,
):
    from tests.test_alpaca_execution import _normal_live_intent
    from tradingagents.brokers import alpaca_supervisor as supervisor_module

    intent = _normal_live_intent()
    receipt = NormalLiveActivationReceipt(
        activation_prepare_id="prepare",
        activation_receipt_id="receipt",
        intent_full_sha256="a" * 64,
        canonical_before_sha256="b" * 64,
        canonical_after_sha256="c" * 64,
        state={},
        created=True,
        status="activated",
    )
    class _FakeSession:
        pass

    live_client = AlpacaRestClient(
        AlpacaSettings(
            api_key="test-key",
            secret_key="test-secret",
            paper=False,
            base_url="https://api.alpaca.markets",
        ),
        session=_FakeSession(),
    )
    call = None

    def capture_submit(self, order, **kwargs):
        nonlocal call
        call = (order, kwargs)
        return {"id": "live-order"}

    monkeypatch.setattr(AlpacaRestClient, "submit_order", capture_submit)
    sentinel_admission = supervisor_module.NormalLiveSubmitAdmission(
        intent_full_sha256="a" * 64,
        issued_at="2026-07-28T12:00:00+00:00",
        expires_at="2026-07-28T12:01:00+00:00",
    )
    monkeypatch.setattr(
        supervisor_module,
        "_issue_normal_live_submit_risk_metrics",
        lambda *_args, **_kwargs: object(),
    )
    monkeypatch.setattr(
        supervisor_module,
        "_preflight_normal_live_submit_local_prerequisites",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        supervisor_module,
        "_issue_normal_live_submit_admission",
        lambda *_args, **_kwargs: sentinel_admission,
    )

    assert submit_authorized_normal_live_order(
        live_client=live_client,
        authorized_normal_trade_intent=intent,
        activation_receipt=receipt,
        risk_envelope_path=(tmp_path / "risk.yaml").resolve(),
        promotion_state_path=(tmp_path / "promotion.json").resolve(),
        control_state_path=(tmp_path / "control.json").resolve(),
        order_rate_state_path=(tmp_path / "rate.json").resolve(),
        decision_evidence={},
    ) == {"id": "live-order"}
    order, kwargs = call
    assert order == {
        "symbol": intent.symbol,
        "side": intent.side,
        "type": "limit",
        "time_in_force": "day",
        "notional": intent.notional_usd,
        "limit_price": intent.limit_price,
        "client_order_id": intent.client_order_id,
    }
    assert kwargs["authorized_normal_trade_intent"] is intent
    assert kwargs["activation_receipt"] is receipt
    assert kwargs["supervisor_admission"].intent_full_sha256


def test_supervisor_rejects_an_arbitrary_live_writer_before_issuing_admission(tmp_path):
    """A duck-typed writer cannot obtain the supervisor final-gate artifact."""

    class _ArbitraryWriter:
        def __init__(self):
            self.called = False

        def submit_order(self, _order, **_kwargs):
            self.called = True
            return {"id": "forged"}

    from tests.test_alpaca_execution import _normal_live_intent

    intent = _normal_live_intent()
    receipt = NormalLiveActivationReceipt(
        activation_prepare_id="prepare",
        activation_receipt_id="receipt",
        intent_full_sha256="a" * 64,
        canonical_before_sha256="b" * 64,
        canonical_after_sha256="c" * 64,
        state={},
        created=True,
        status="activated",
    )
    writer = _ArbitraryWriter()

    with pytest.raises(ValueError, match="owned AlpacaRestClient"):
        submit_authorized_normal_live_order(
            live_client=writer,
            authorized_normal_trade_intent=intent,
            activation_receipt=receipt,
            risk_envelope_path=(tmp_path / "risk.yaml").resolve(),
            promotion_state_path=(tmp_path / "promotion.json").resolve(),
            control_state_path=(tmp_path / "control.json").resolve(),
            order_rate_state_path=(tmp_path / "rate.json").resolve(),
        decision_evidence={},
        )

    assert writer.called is False


def test_extracted_hourly_packet_io_accepts_injected_facade_callbacks(tmp_path):
    class StubAlert:
        notify = False

        def as_dict(self, **kwargs):
            return {"severity": "QUIET", **kwargs}

    decision = HourlySupervisorDecision(
        decision="hold",
        material=False,
        reason="quiet extracted hourly module test",
        live_exposure=Decimal("12.345"),
        generated_at=datetime.datetime(2026, 6, 7, 14, 45, tzinfo=datetime.UTC),
    )

    payload = supervisor_hourly.serialize_hourly_decision(
        decision,
        classify_alert=lambda _decision: StubAlert(),
        alert_fingerprint=lambda _decision, _alert: "quiet|hold",
        should_throttle_alert=lambda *_args, **_kwargs: False,
        render_alert_email=lambda _decision: {"subject": "should-not-render"},
        client_order_id=lambda *_args, **_kwargs: "should-not-create-id",
        is_order_action=lambda _action: False,
    )
    packet_path = supervisor_hourly.write_hourly_decision_packet(
        decision,
        serialize_decision=lambda _decision, **_kwargs: payload,
        output_dir=tmp_path,
    )
    compact = json.loads(packet_path.with_suffix(".compact.json").read_text(encoding="utf-8"))

    assert payload["live_exposure"] == "12.34"
    assert payload["submitted"] == []
    assert "alert_email" not in payload
    assert compact["submitted_count"] == 0
    assert compact["can_submit_orders"] is False
    assert compact["execution_authority"] == "none"
    assert (tmp_path / "latest.json").exists()
    assert (tmp_path / "latest-compact.json").exists()


def test_hourly_supervisor_rejects_market_orders():
    action = HourlySupervisorAction(
        action="buy",
        symbol="MSFT",
        notional=Decimal("10"),
        limit_price=Decimal("420"),
        order_type="market",
    )

    issues = validate_hourly_supervisor_actions(
        [action],
        current_live_exposure=Decimal("50"),
        config=AlpacaExecutionConfig(live_exposure_limit=Decimal("100")),
    )

    assert "market orders are not allowed" in issues[0].reason


def test_new_live_buy_is_not_blocked_by_old_live_exposure_cap():
    buy = HourlySupervisorAction(
        action="buy",
        symbol="AMZN",
        notional=Decimal("15"),
        limit_price=Decimal("180"),
    )

    issues = validate_hourly_supervisor_actions(
        [buy],
        current_live_exposure=Decimal("100"),
        config=AlpacaExecutionConfig(live_exposure_limit=Decimal("100")),
    )

    assert issues == []


def test_new_live_buy_is_allowed_with_paired_reduction():
    reduce = HourlySupervisorAction(
        action="reduce",
        symbol="MSFT",
        notional=Decimal("20"),
        limit_price=Decimal("415"),
    )
    buy = HourlySupervisorAction(
        action="buy",
        symbol="AMZN",
        notional=Decimal("15"),
        limit_price=Decimal("180"),
    )

    issues = validate_hourly_supervisor_actions(
        [reduce, buy],
        current_live_exposure=Decimal("100"),
        config=AlpacaExecutionConfig(live_exposure_limit=Decimal("100")),
    )

    assert issues == []


def test_paper_first_buy_does_not_trip_live_exposure_cap():
    buy = HourlySupervisorAction(
        action="buy",
        symbol="ORCL",
        notional=Decimal("100"),
        limit_price=Decimal("240"),
        account="paper",
        execution_mode="paper_first",
    )

    issues = validate_hourly_supervisor_actions(
        [buy],
        current_live_exposure=Decimal("150"),
        config=AlpacaExecutionConfig(live_exposure_limit=Decimal("100")),
    )

    assert issues == []


def test_dynamic_cap_scales_with_profitable_clean_live_strategy():
    cap = calculate_dynamic_live_cap(
        live_positions=[
            {
                "symbol": "MSFT",
                "cost_basis": "100",
                "unrealized_pl": "3.25",
            }
        ],
        recent_packets=[{"issues": []}],
    )

    assert cap == Decimal("150")
    assert calculate_dynamic_live_cap(
        live_positions=[{"symbol": "MSFT", "cost_basis": "100", "unrealized_pl": "12"}],
        recent_packets=[{"issues": []}],
    ) == Decimal("200")
    assert calculate_dynamic_live_cap(
        live_positions=[{"symbol": "MSFT", "cost_basis": "100", "unrealized_pl": "12"}],
        recent_packets=[{"issues": [{"ticket_id": "x", "reason": "blocked"}]}],
    ) == Decimal("100")


def test_autonomous_live_buy_notional_scales_with_candidate_strength():
    candidate = CandidateSignal(
        symbol="AMZN",
        score=Decimal("0.92"),
        current_price=Decimal("205"),
        time_sensitive=True,
        reason="major momentum event",
    )

    assert choose_autonomous_live_buy_notional(candidate, Decimal("80")) == Decimal("40.00")
    assert choose_autonomous_live_buy_notional(candidate, Decimal("20")) == Decimal("20.00")


def test_supervisor_live_client_order_id_is_stable_for_same_decision_day():
    action = HourlySupervisorAction(
        action="buy",
        symbol="AMZN",
        side="buy",
        notional=Decimal("40"),
        limit_price=Decimal("205.41"),
        account="live",
        execution_mode="tiny_live",
        sleeve="current-aggressive",
    )
    first = supervisor_live_client_order_id(
        action,
        generated_at=datetime.datetime(2026, 6, 2, 14, 5, tzinfo=datetime.timezone.utc),
    )
    retry = supervisor_live_client_order_id(
        action,
        generated_at=datetime.datetime(2026, 6, 2, 14, 45, tzinfo=datetime.timezone.utc),
    )
    changed_price = supervisor_live_client_order_id(
        action.__class__(
            **{
                **action.__dict__,
                "limit_price": Decimal("206.00"),
            }
        ),
        generated_at=datetime.datetime(2026, 6, 2, 14, 45, tzinfo=datetime.timezone.utc),
    )

    assert first == retry
    assert first != changed_price
    assert first.startswith("ta-tiny-20260602-current-amzn-buy-")
    assert len(first) <= 48


def test_market_session_labels_special_windows():
    assert market_session_label(
        datetime.datetime(2026, 5, 29, 13, 15, tzinfo=datetime.timezone.utc)
    ) == "pre_open"
    assert market_session_label(
        datetime.datetime(2026, 5, 29, 20, 15, tzinfo=datetime.timezone.utc)
    ) == "after_close"


def test_build_candidate_signals_prefers_controlled_dip_over_green_spike():
    signals = build_candidate_signals(
        {
            "AMZN": {
                "current_price": "205",
                "previous_close": "200",
                "volume_ratio": "2.0",
            },
            "MSFT": {
                "current_price": "435",
                "previous_close": "441",
                "volume_ratio": "1.1",
            },
        },
        held_symbols=[],
    )

    by_symbol = {signal.symbol: signal for signal in signals}
    assert signals[0].symbol == "MSFT"
    assert by_symbol["MSFT"].score >= Decimal("0.70")
    assert by_symbol["MSFT"].time_sensitive is True
    assert "controlled dip" in by_symbol["MSFT"].reason
    assert by_symbol["AMZN"].score < by_symbol["MSFT"].score
    assert by_symbol["AMZN"].time_sensitive is False
    assert "do not chase" in by_symbol["AMZN"].reason


def test_build_candidate_signals_downranks_bot_copycat_ai_beta_without_confirmation():
    signals = build_candidate_signals(
        {
            "AMD": {
                "current_price": "120",
                "previous_close": "121",
                "volume_ratio": "2.0",
                "macro_event_risk": True,
                "ai_beta_crowding_risk": True,
                "bot_copycat_attention": True,
                "institutional_confirmation": False,
            },
            "KO": {
                "current_price": "65",
                "previous_close": "66",
                "volume_ratio": "1.1",
            },
        },
        held_symbols=[],
    )

    by_symbol = {signal.symbol: signal for signal in signals}
    assert signals[0].symbol == "KO"
    assert by_symbol["AMD"].score < by_symbol["KO"].score
    assert "MiroFish bot-copycat" in by_symbol["AMD"].reason
    assert "crowded AI beta" in by_symbol["AMD"].reason


def test_build_candidate_signals_boosts_report33_positive_relative_bias_without_chasing():
    signals = build_candidate_signals(
        {
            "KO": {
                "current_price": "65",
                "previous_close": "65",
                "volume_ratio": "1.0",
                "deep_research_positive_relative_bias": True,
            },
            "NFLX": {
                "current_price": "100",
                "previous_close": "100",
                "volume_ratio": "1.0",
            },
            "XOM": {
                "current_price": "104",
                "previous_close": "100",
                "volume_ratio": "2.0",
                "deep_research_positive_relative_bias": True,
            },
        },
        held_symbols=[],
    )

    by_symbol = {signal.symbol: signal for signal in signals}
    assert signals[0].symbol == "KO"
    assert by_symbol["KO"].score > by_symbol["NFLX"].score
    assert "report-33 macro window favors" in by_symbol["KO"].reason
    assert by_symbol["XOM"].score < by_symbol["KO"].score
    assert "do not chase" in by_symbol["XOM"].reason
    assert "report-33 macro window favors" not in by_symbol["XOM"].reason


def test_build_candidate_signals_penalizes_unconfirmed_mirofish_gate_suppression():
    signals = build_candidate_signals(
        {
            "HOOD": {
                "current_price": "19.70",
                "previous_close": "20",
                "volume_ratio": "1.2",
                "deep_research_event_sensitive_watch": True,
                "mirofish_false_signal_suppression": True,
                "mirofish_triggered_advisory_gates": [
                    "broker_friction",
                    "attribution_error",
                ],
                "broker_flow_confirmation": False,
            },
            "KO": {
                "current_price": "65",
                "previous_close": "66",
                "volume_ratio": "1.1",
                "deep_research_positive_relative_bias": True,
            },
        },
        held_symbols=[],
    )

    by_symbol = {signal.symbol: signal for signal in signals}
    assert signals[0].symbol == "KO"
    assert by_symbol["HOOD"].score < by_symbol["KO"].score
    assert "broker/fintech rule-change watch names require real broker/flow confirmation" in by_symbol["HOOD"].reason
    assert "MiroFish advisory gates (broker_friction, attribution_error) suppress" in by_symbol["HOOD"].reason


def test_build_candidate_signals_excludes_explicitly_stale_quote_rows():
    signals = build_candidate_signals(
        {
            "MSFT": {
                "current_price": "435",
                "previous_close": "441",
                "volume_ratio": "1.1",
                "quote_fresh": False,
                "stale_quote": True,
            },
            "KO": {
                "current_price": "65",
                "previous_close": "66",
                "volume_ratio": "1.1",
                "quote_fresh": True,
            },
        },
        held_symbols=[],
    )

    assert [signal.symbol for signal in signals] == ["KO"]


def test_overnight_candidate_universe_merges_sources_without_holding_weight(tmp_path):
    market_packet = tmp_path / "market.md"
    market_packet.write_text(
        "Reviewed PLTR, ORCL, and GOOGL. Ignore GDP, PCE, ALPACA, CHECKS, and PROFIT REVIEW.",
        encoding="utf-8",
    )
    watchlist = tmp_path / "watchlist.txt"
    watchlist.write_text("SNOW\nmsft\n", encoding="utf-8")

    universe = build_overnight_candidate_universe(
        live_positions=[{"symbol": "GOOGL"}],
        paper_positions=[{"symbol": "NVDA"}],
        live_open_orders=[{"symbol": "AMZN"}],
        paper_open_orders=[{"symbol": "META"}],
        recent_supervisor_packets=[
            {
                "ranked_candidates": [{"symbol": "ORCL"}],
                "actions": [{"symbol": "CRM"}],
            }
        ],
        market_packet_paths=[market_packet],
        watchlist_paths=[watchlist],
        base_universe=("MSFT", "ORCL"),
    )

    symbols = [item["symbol"] for item in universe]
    assert symbols == sorted(set(symbols))
    assert {"GOOGL", "NVDA", "AMZN", "META", "ORCL", "CRM", "PLTR", "SNOW", "MSFT"} <= set(symbols)
    assert "GDP" not in symbols
    assert "ALPACA" not in symbols
    assert "CHECKS" not in symbols
    assert "PROFIT" not in symbols
    assert all(item["research_weight"] == "equal" for item in universe)
    assert {item["symbol"]: item["owned"] for item in universe}["GOOGL"] is True
    assert {item["symbol"]: item["owned"] for item in universe}["ORCL"] is False


def test_overnight_candidate_universe_reads_json_packets_structurally(tmp_path):
    market_packet = tmp_path / "hourly-supervisor.json"
    market_packet.write_text(
        """
        {
          "reason": "Fresh setup is still closed, but wait for market open",
          "portfolio": {
            "ranked_candidates": [{"symbol": "ADBE"}],
            "live": {"positions": [{"symbol": "MSFT"}]}
          },
          "actions": [{"symbol": "CRM"}]
        }
        """,
        encoding="utf-8",
    )

    universe = build_overnight_candidate_universe(
        live_positions=[],
        paper_positions=[],
        live_open_orders=[],
        paper_open_orders=[],
        market_packet_paths=[market_packet],
        base_universe=(),
    )

    symbols = {item["symbol"] for item in universe}
    assert {"ADBE", "MSFT", "CRM"} <= symbols
    assert {"FRESH", "BUT", "FOR"} & symbols == set()


def test_overnight_packet_writer_marks_analysis_only_and_loads_latest(tmp_path):
    packet_path = write_overnight_plan_packet(
        {
            "generated_at": "2026-05-30T00:30:00+00:00",
            "analysis_only": True,
            "ranked_candidates": [{"symbol": "ORCL", "score": "0.90"}],
            "ticker_results": [
                {
                    "symbol": "ORCL",
                    "status": "ok",
                    "creator_workflow": {
                        "packet_path": "results/overnight_plans/agent_runs/ORCL/creator_workflow_packet.json",
                        "complete_report_path": "results/overnight_plans/agent_runs/ORCL/complete_report.md",
                        "role_count": 9,
                        "execution_authority": "none",
                    },
                }
            ],
        },
        output_dir=tmp_path,
    )

    loaded = load_latest_overnight_plan(tmp_path)

    assert packet_path.name.startswith("overnight-plan-20260530-003000")
    assert loaded["analysis_only"] is True
    assert loaded["ranked_candidates"][0]["symbol"] == "ORCL"
    assert loaded["packet_path"] == str(packet_path)
    compact_path = packet_path.with_name(f"{packet_path.stem}.compact.json")
    latest_compact = json.loads((tmp_path / "latest-compact.json").read_text(encoding="utf-8"))
    compact = json.loads(compact_path.read_text(encoding="utf-8"))
    assert compact["schema"] == "compact_overnight_plan_v1"
    assert compact["raw_packet_path"] == str(packet_path)
    assert compact["top_candidate"]["symbol"] == "ORCL"
    assert compact["creator_workflow_summary"]["workflow_count"] == 1
    assert compact["creator_workflow_summary"]["symbols"] == ["ORCL"]
    assert compact["creator_workflow_summary"]["role_count_min"] == 9
    assert compact["creator_workflow_summary"]["packet_paths"] == [
        "results/overnight_plans/agent_runs/ORCL/creator_workflow_packet.json"
    ]
    assert compact["creator_workflow_summary"]["bad_authority_count"] == 0
    assert "ranked_candidates" not in compact
    assert "ticker_results" not in compact
    assert latest_compact == compact


def test_overnight_packet_writer_can_skip_latest_for_probe(tmp_path):
    production_path = write_overnight_plan_packet(
        {
            "generated_at": "2026-05-30T00:30:00+00:00",
            "analysis_only": True,
            "ranked_candidates": [{"symbol": "ORCL", "score": "0.90"}],
            "ticker_results": [],
        },
        output_dir=tmp_path,
    )
    probe_path = write_overnight_plan_packet(
        {
            "generated_at": "2026-05-30T00:31:00+00:00",
            "analysis_only": True,
            "ranked_candidates": [{"symbol": "MSFT", "score": "0.80"}],
            "ticker_results": [],
        },
        output_dir=tmp_path,
        write_latest=False,
    )

    loaded = load_latest_overnight_plan(tmp_path)

    assert probe_path.exists()
    assert probe_path.with_name(f"{probe_path.stem}.compact.json").exists()
    assert loaded["packet_path"] == str(production_path)
    assert loaded["ranked_candidates"][0]["symbol"] == "ORCL"
    latest_compact = json.loads((tmp_path / "latest-compact.json").read_text(encoding="utf-8"))
    assert latest_compact["raw_packet_path"] == str(production_path)
    assert latest_compact["top_candidate"]["symbol"] == "ORCL"


def test_load_latest_overnight_plan_prefers_newer_production_raw_over_stale_latest(tmp_path):
    stale_latest = {
        "generated_at": "2026-05-30T00:30:00+00:00",
        "analysis_only": True,
        "latest_alias_written": True,
        "ranked_candidates": [{"symbol": "OLD", "score": "0.10"}],
        "ticker_results": [],
    }
    fresh_path = tmp_path / "overnight-plan-20260531-003000.json"
    fresh_packet = {
        "generated_at": "2026-05-31T00:30:00+00:00",
        "analysis_only": True,
        "latest_alias_written": True,
        "packet_path": str(fresh_path),
        "ranked_candidates": [{"symbol": "FRESH", "score": "0.90"}],
        "ticker_results": [],
    }
    (tmp_path / "latest.json").write_text(json.dumps(stale_latest), encoding="utf-8")
    fresh_path.write_text(json.dumps(fresh_packet), encoding="utf-8")

    loaded = load_latest_overnight_plan(tmp_path)

    assert loaded["packet_path"] == str(fresh_path)
    assert loaded["ranked_candidates"][0]["symbol"] == "FRESH"


def test_packet_writers_keep_same_second_packets_unique(tmp_path):
    first_overnight = write_overnight_plan_packet(
        {
            "generated_at": "2026-05-30T00:30:00+00:00",
            "analysis_only": True,
            "ranked_candidates": [{"symbol": "ORCL", "score": "0.90"}],
            "ticker_results": [],
        },
        output_dir=tmp_path / "overnight",
    )
    second_overnight = write_overnight_plan_packet(
        {
            "generated_at": "2026-05-30T00:30:00+00:00",
            "analysis_only": True,
            "ranked_candidates": [{"symbol": "MSFT", "score": "0.80"}],
            "ticker_results": [],
        },
        output_dir=tmp_path / "overnight",
    )

    decision = build_hourly_decision(
        live_positions=[],
        live_open_orders=[],
        config=HourlySupervisorConfig(),
    )
    first_hourly = write_hourly_decision_packet(decision, output_dir=tmp_path / "hourly")
    second_hourly = write_hourly_decision_packet(decision, output_dir=tmp_path / "hourly")

    assert first_overnight != second_overnight
    assert first_overnight.exists()
    assert second_overnight.exists()
    assert first_hourly != second_hourly
    assert first_hourly.exists()
    assert second_hourly.exists()
    assert first_hourly.with_suffix(".compact.json").exists()
    assert second_hourly.with_suffix(".compact.json").exists()
    latest_hourly = json.loads((tmp_path / "hourly" / "latest.json").read_text(encoding="utf-8"))
    latest_compact = json.loads(
        (tmp_path / "hourly" / "latest-compact.json").read_text(encoding="utf-8")
    )
    assert latest_hourly["decision"] == decision.decision
    assert latest_compact["schema"] == "compact_hourly_supervisor_v1"
    assert latest_compact["raw_packet_path"] == str(second_hourly)
    assert latest_compact["can_submit_orders"] is False
    assert find_latest_hourly_packet(tmp_path / "hourly") == second_hourly


def test_overnight_markdown_separates_fallback_and_failed_tickers():
    markdown = render_overnight_plan_markdown(
        {
            "generated_at": "2026-06-01T00:30:00+00:00",
            "analysis_only": True,
            "overnight_quality": {
                "full_graph_count": 1,
                "fallback_count": 1,
                "graph_failure_count": 1,
            },
            "ranked_candidates": [
                {"symbol": "ORCL", "score": "0.90", "rating": "Buy", "status": "fallback", "method": "market_snapshot_fallback"}
            ],
            "ticker_results": [
                {"symbol": "ORCL", "status": "fallback", "fallback_reason": "runtime bound"},
                {"symbol": "AAPL", "status": "failed", "error": "worker crashed"},
            ],
        }
    )

    assert "Full graph analyzed: 1" in markdown
    assert "Fallback Tickers" in markdown
    assert "ORCL: runtime bound" in markdown
    assert "Failed Tickers" in markdown
    assert "AAPL: worker crashed" in markdown


def test_overnight_validation_confirms_amends_invalidates_and_ignores_stale():
    fresh = {
        "generated_at": "2026-05-30T00:30:00+00:00",
        "ranked_candidates": [{"symbol": "ORCL"}, {"symbol": "MSFT"}],
    }
    now = datetime.datetime(2026, 5, 30, 12, 0, tzinfo=datetime.timezone.utc)

    assert validate_overnight_plan_against_candidates(
        fresh,
        [
            CandidateSignal(symbol="ORCL", score=Decimal("0.90"), current_price=Decimal("225")),
            CandidateSignal(symbol="MSFT", score=Decimal("0.80"), current_price=Decimal("450")),
        ],
        now=now,
    )["status"] == "confirmed"
    amended = validate_overnight_plan_against_candidates(
        fresh,
        [
            CandidateSignal(symbol="MSFT", score=Decimal("0.90"), current_price=Decimal("450")),
            CandidateSignal(symbol="ORCL", score=Decimal("0.80"), current_price=Decimal("225")),
        ],
        now=now,
    )
    assert amended["status"] == "amended"
    assert amended["current_top_symbol"] == "MSFT"
    assert validate_overnight_plan_against_candidates(
        fresh,
        [CandidateSignal(symbol="AAPL", score=Decimal("0.90"), current_price=Decimal("310"))],
        now=now,
    )["status"] == "invalidated"
    assert validate_overnight_plan_against_candidates(
        {"generated_at": "2026-05-28T00:30:00+00:00", "ranked_candidates": [{"symbol": "ORCL"}]},
        [],
        now=now,
    )["status"] == "stale_or_missing"
    assert validate_overnight_plan_against_candidates(
        {"generated_at": "2026-05-31T00:30:00+00:00", "ranked_candidates": [{"symbol": "ORCL"}]},
        [CandidateSignal(symbol="ORCL", score=Decimal("0.90"), current_price=Decimal("225"))],
        now=now,
    )["status"] == "stale_or_missing"


def test_overnight_validation_retains_recent_plan_on_saturday_no_market():
    plan = {
        "generated_at": "2026-06-05T10:17:40+00:00",
        "ranked_candidates": [{"symbol": "KO"}],
    }
    validation = validate_overnight_plan_against_candidates(
        plan,
        [CandidateSignal(symbol="KO", score=Decimal("0.90"), current_price=Decimal("72"))],
        now=datetime.datetime(2026, 6, 6, 19, 27, 12, tzinfo=datetime.timezone.utc),
    )

    assert validation["status"] == "not_required"
    assert validation["validation_skipped"] is True
    assert validation["skip_reason"] == "saturday_no_regular_market_morning"
    assert validation["overnight_top_symbol"] == "KO"


def test_overnight_validation_enforces_sunday_freshness():
    plan = {
        "generated_at": "2026-06-05T10:17:40+00:00",
        "ranked_candidates": [{"symbol": "KO"}],
    }
    validation = validate_overnight_plan_against_candidates(
        plan,
        [CandidateSignal(symbol="KO", score=Decimal("0.90"), current_price=Decimal("72"))],
        now=datetime.datetime(2026, 6, 7, 12, 30, tzinfo=datetime.timezone.utc),
    )

    assert validation["status"] == "stale_or_missing"


def test_quiet_hourly_hold_suppresses_material_only_notification():
    decision = build_hourly_decision(
        live_positions=[
            {
                "symbol": "GOOGL",
                "unrealized_plpc": "0.008",
                "market_value": "45",
                "current_price": "386",
            }
        ],
        live_open_orders=[],
        config=HourlySupervisorConfig(),
    )

    assert decision.decision == "hold"
    assert should_notify_supervisor(decision, notification_policy="material-only") is False
    assert should_notify_supervisor(decision, notification_policy="urgent-exceptions") is False


def test_hourly_decision_context_filters_held_symbols_and_finds_extremes():
    positions = [
        {"symbol": "MSFT", "unrealized_plpc": "0.061"},
        {"symbol": "TSM", "unrealized_plpc": "-0.041"},
    ]
    candidates = [
        CandidateSignal(symbol="MSFT", score=Decimal("0.92"), current_price=Decimal("421")),
        CandidateSignal(symbol="NVDA", score=Decimal("0.84"), current_price=Decimal("143")),
    ]

    context = build_hourly_decision_context(
        live_positions=positions,
        candidate_signals=candidates,
        current_live_exposure=Decimal("37.25"),
        dynamic_live_cap=Decimal("100.00"),
    )

    assert context.held_symbols == frozenset({"MSFT", "TSM"})
    assert context.live_unallocated == Decimal("62.75")
    assert context.best_candidate is candidates[1]
    assert context.worst_position is positions[1]
    assert context.best_position is positions[0]


def test_open_orders_review_decision_is_no_action_inspection_packet():
    decision = build_open_orders_review_decision(
        live_open_orders=[{"symbol": "MSFT"}, {"symbol": "TSM"}],
        live_exposure=Decimal("42.25"),
    )

    assert decision is not None
    assert decision.decision == "review-open-orders"
    assert decision.material is True
    assert decision.reason == "2 open live order(s) need inspection"
    assert decision.live_exposure == Decimal("42.25")
    assert decision.actions == []
    assert decision.submitted == []


def test_hourly_decision_reviews_open_orders_before_loss_or_buy_logic():
    decision = build_hourly_decision(
        live_positions=[
            {
                "symbol": "MSFT",
                "unrealized_plpc": "-0.20",
                "market_value": "50",
                "current_price": "350",
            }
        ],
        live_open_orders=[{"symbol": "MSFT"}],
        config=HourlySupervisorConfig(),
        candidate_signals=[
            CandidateSignal(symbol="NVDA", score=Decimal("0.95"), current_price=Decimal("143"))
        ],
    )

    assert decision.decision == "review-open-orders"
    assert decision.actions == []
    assert decision.evidence == {}


def test_extracted_hourly_decision_router_reviews_open_orders_before_loss_or_buy_logic():
    decision = supervisor_hourly.build_hourly_decision(
        live_positions=[
            {
                "symbol": "MSFT",
                "unrealized_plpc": "-0.20",
                "market_value": "50",
                "current_price": "350",
            }
        ],
        live_open_orders=[{"symbol": "MSFT"}],
        config=HourlySupervisorConfig(),
        candidate_signals=[
            CandidateSignal(symbol="NVDA", score=Decimal("0.95"), current_price=Decimal("143"))
        ],
        dynamic_live_cap=Decimal("100"),
        can_trade_session=lambda _session: True,
        positive_decimal_or_none=lambda value: Decimal(str(value)) if value else None,
        live_sleeve="current-aggressive",
    )

    assert decision.decision == "review-open-orders"
    assert decision.actions == []
    assert decision.evidence == {}


def test_hourly_decision_reviews_loss_without_exit_evidence():
    decision = build_hourly_decision(
        live_positions=[
            {
                "symbol": "MSFT",
                "unrealized_plpc": "-0.035",
                "market_value": "29.50",
                "qty": "0.071",
                "current_price": "413",
            }
        ],
        live_open_orders=[],
        config=HourlySupervisorConfig(),
    )

    assert decision.decision == "loss-review"
    assert decision.material is True
    assert decision.actions == []
    assert "no live sell was submitted" in decision.reason
    assert "Exact evidence gaps:" in decision.reason
    assert decision.evidence["loss_exit_review"]["allowed"] is False
    assert "allowed loss-exit reason is missing" in decision.evidence["loss_exit_review"]["blockers"]


def test_hourly_decision_blocks_orcl_like_broad_red_recent_loss_sell():
    decision = build_hourly_decision(
        live_positions=[
            {
                "symbol": "ORCL",
                "qty": "0.4101",
                "market_value": "95.66",
                "cost_basis": "100.00",
                "avg_entry_price": "243.85",
                "current_price": "233.37",
                "unrealized_pl": "-4.34",
                "unrealized_plpc": "-0.0434",
                "holding_period_trading_days": 1,
                "original_buy_thesis": "Controlled dip at support should rebound if AI infrastructure demand stays intact.",
                "current_thesis_status": "No company-specific invalidator found; broad market was red.",
                "relative_market_context": {
                    "spy": "-1.1%",
                    "qqq": "-1.4%",
                    "sector": "-1.8%",
                    "broad_market_weakness": True,
                    "sector_weakness": True,
                    "company_specific_damage": False,
                },
                "company_specific_news_check": "No ORCL-specific thesis break found.",
                "why_hold_is_worse_than_sell": "Not proven.",
                "loss_exit_confidence": "0.42",
            }
        ],
        live_open_orders=[],
        config=HourlySupervisorConfig(),
        market_session="regular",
    )

    review = decision.evidence["loss_exit_review"]
    assert decision.decision == "loss-review"
    assert decision.actions == []
    assert review["symbol"] == "ORCL"
    assert review["side"] == "sell"
    assert review["decision_id"]
    assert review["current_price"] == "233.37"
    assert review["average_entry_price"] == "243.85"
    assert review["estimated_realized_loss"] == "-4.34"
    assert review["broad_market_context"]
    assert "relative_performance_vs_SPY" in review
    assert "relative_performance_vs_QQQ" in review
    assert "why_this_is_not_broad_market_red_day_noise" in review
    assert "evidence_generated_at" in review
    assert isinstance(review["source_packet_ids"], list)
    assert review["allowed"] is False
    assert "allowed loss-exit reason is missing" in review["blocked_reasons"]
    assert "broad-market weakness is insufficient" in review["blocked_reasons"]


def test_bare_thesis_broken_flag_is_not_enough_for_loss_exit():
    decision = build_hourly_decision(
        live_positions=[
            {
                "symbol": "MSFT",
                "unrealized_plpc": "-0.035",
                "market_value": "29.50",
                "qty": "0.071",
                "current_price": "413",
                "avg_entry_price": "428",
                "unrealized_pl": "-1.07",
                "holding_period_trading_days": 5,
                "thesis_broken": True,
                "original_buy_thesis": "Support should hold if cloud growth guidance stays intact.",
                "current_thesis_status": "Thesis is claimed broken but no source is attached.",
                "relative_market_context": {
                    "spy": "flat",
                    "qqq": "+0.2%",
                    "sector": "+0.1%",
                    "company_specific_damage": True,
                },
                "company_specific_news_check": "No source packet attached.",
                "earnings_guidance_or_filing_check": "No filing/guidance packet attached.",
                "why_hold_is_worse_than_sell": "Claimed thesis break.",
                "why_this_is_not_broad_market_red_day_noise": "Market is not broadly red.",
                "loss_exit_confidence": "0.82",
            }
        ],
        live_open_orders=[],
        config=HourlySupervisorConfig(),
        market_session="regular",
    )

    review = decision.evidence["loss_exit_review"]
    assert decision.decision == "loss-review"
    assert review["allowed"] is False
    assert "allowed loss-exit reason source is missing" in review["blocked_reasons"]


def test_hourly_decision_routes_discretionary_guidance_loss_to_board():
    decision = build_hourly_decision(
        live_positions=[
            {
                "symbol": "MSFT",
                "unrealized_plpc": "-0.035",
                "market_value": "29.50",
                "qty": "0.071",
                "current_price": "413",
                "avg_entry_price": "428",
                "unrealized_pl": "-1.07",
                "holding_period_trading_days": 5,
                "earnings_or_guidance_break": True,
                "allowed_exit_reason_source": {
                    "packet_id": "earnings-guidance-packet-20260603",
                    "path": "normalized_loss_review_evidence/earnings-guidance-packet-20260603.json",
                    "sha256": "a" * 64,
                },
                "exit_reason": "guidance cut broke the support thesis",
                "original_buy_thesis": "Support should hold if cloud growth guidance stays intact.",
                "current_thesis_status": "Guidance cut invalidated the support thesis.",
                "relative_market_context": {
                    "spy": "flat",
                    "qqq": "+0.2%",
                    "sector": "+0.1%",
                    "company_specific_damage": True,
                },
                "company_specific_news_check": "Company-specific guidance cut confirmed.",
                "earnings_guidance_or_filing_check": "Guidance cut confirmed in company filing.",
                "why_hold_is_worse_than_sell": "The original catalyst broke and capital can wait in cash.",
                "why_this_is_not_broad_market_red_day_noise": "SPY, QQQ, and sector were not down with MSFT.",
                "source_packet_ids": ["earnings-guidance-packet-20260603"],
                "loss_exit_confidence": "0.82",
            }
        ],
        live_open_orders=[],
        config=HourlySupervisorConfig(),
        market_session="regular",
    )

    assert decision.decision == "loss-review"
    assert decision.material is True
    assert decision.actions == []
    assert "autonomous portfolio BOARD" in decision.reason
    assert decision.evidence["loss_exit_review"]["allowed"] is False


def test_approved_loss_exit_requires_current_price_before_order():
    decision = build_hourly_decision(
        live_positions=[
            {
                "symbol": "MSFT",
                "unrealized_plpc": "-0.035",
                "market_value": "29.50",
                "qty": "0.071",
                "current_price": "",
                "avg_entry_price": "428",
                "unrealized_pl": "-1.07",
                "holding_period_trading_days": 5,
                "thesis_invalidated": True,
                "allowed_exit_reason_source": "earnings-guidance-packet-20260603",
                "exit_reason": "thesis invalidated: product guidance cut broke the support thesis",
                "original_buy_thesis": "Support should hold if cloud growth guidance stays intact.",
                "current_thesis_status": "Guidance cut invalidated the support thesis.",
                "relative_market_context": {
                    "spy": "flat",
                    "qqq": "+0.2%",
                    "sector": "+0.1%",
                    "company_specific_damage": True,
                },
                "company_specific_news_check": "Company-specific guidance cut confirmed.",
                "earnings_guidance_or_filing_check": "Guidance cut confirmed in company filing.",
                "why_hold_is_worse_than_sell": "The original catalyst broke and capital can wait in cash.",
                "why_this_is_not_broad_market_red_day_noise": "SPY, QQQ, and sector were not down with MSFT.",
                "source_packet_ids": ["earnings-guidance-packet-20260603"],
                "loss_exit_confidence": "0.82",
            }
        ],
        live_open_orders=[],
        config=HourlySupervisorConfig(),
        market_session="regular",
    )

    assert decision.decision == "loss-review"
    assert decision.actions == []
    assert "current price evidence is missing" in decision.reason
    assert "current price evidence is missing" in decision.evidence["loss_exit_review"]["blockers"]


def test_recent_loss_sell_requires_hard_stop_thesis_break_or_manual_override():
    decision = build_hourly_decision(
        live_positions=[
            {
                "symbol": "CRM",
                "unrealized_plpc": "-0.04",
                "market_value": "48",
                "qty": "0.20",
                "current_price": "240",
                "avg_entry_price": "250",
                "unrealized_pl": "-2",
                "holding_period_trading_days": 1,
                "allowed_exit_reason": "portfolio_exposure_limit",
                "original_buy_thesis": "Pullback should hold at support.",
                "current_thesis_status": "Exposure changed, but thesis is not broken.",
                "relative_market_context": {
                    "spy": "-0.1%",
                    "qqq": "-0.2%",
                    "sector": "-0.3%",
                    "company_specific_damage": False,
                },
                "company_specific_news_check": "No company-specific break found.",
                "why_hold_is_worse_than_sell": "Reduce concentration.",
                "loss_exit_confidence": "0.66",
            }
        ],
        live_open_orders=[],
        config=HourlySupervisorConfig(),
        market_session="regular",
    )

    review = decision.evidence["loss_exit_review"]
    assert decision.decision == "loss-review"
    assert decision.actions == []
    assert review["allowed_exit_reason"] == "portfolio_exposure_limit"
    assert "recent-position churn guard blocks opposite-side sell" in review["blockers"]


def test_aggressive_decision_can_live_buy_time_sensitive_controlled_dip():
    decision = build_hourly_decision(
        live_positions=[
            {
                "symbol": "GOOGL",
                "unrealized_plpc": "0.01",
                "market_value": "100",
                "cost_basis": "100",
                "current_price": "390",
            }
        ],
        live_open_orders=[],
        config=HourlySupervisorConfig(),
        candidate_signals=[
            CandidateSignal(
                symbol="AMZN",
                score=Decimal("0.82"),
                current_price=Decimal("205"),
                previous_close=Decimal("208"),
                day_change_pct=Decimal("-0.0144"),
                time_sensitive=True,
                reason="controlled dip; buy-the-dip candidate",
            )
        ],
        market_session="open_window",
        dynamic_live_cap=Decimal("125"),
    )

    assert decision.decision == "buy"
    assert decision.actions[0].account == "live"
    assert decision.actions[0].execution_mode == "tiny_live"
    assert decision.actions[0].sleeve == "current-aggressive"
    assert decision.actions[0].order_type == "limit"
    assert decision.actions[0].limit_price == Decimal("205.41")


def test_extracted_buy_candidate_helper_buys_controlled_dip():
    decision = supervisor_hourly.build_buy_candidate_decision(
        best_candidate=CandidateSignal(
            symbol="AMZN",
            score=Decimal("0.82"),
            current_price=Decimal("205"),
            previous_close=Decimal("208"),
            day_change_pct=Decimal("-0.0144"),
            time_sensitive=True,
            reason="controlled dip; buy-the-dip candidate",
        ),
        new_buys_suspended_reason=None,
        live_buy_threshold=Decimal("0.78"),
        paper_first_threshold=Decimal("0.62"),
        live_unallocated=Decimal("25"),
        market_session="open_window",
        live_exposure=Decimal("100"),
        can_trade_session=lambda _session: True,
        live_sleeve="current-aggressive",
    )

    assert decision is not None
    assert decision.decision == "buy"
    assert decision.actions[0].symbol == "AMZN"
    assert decision.actions[0].account == "live"
    assert decision.actions[0].execution_mode == "tiny_live"
    assert decision.actions[0].sleeve == "current-aggressive"
    assert decision.actions[0].limit_price == Decimal("205.41")


def test_aggressive_decision_refuses_green_spike_chase_buy():
    decision = build_hourly_decision(
        live_positions=[],
        live_open_orders=[],
        config=HourlySupervisorConfig(),
        candidate_signals=[
            CandidateSignal(
                symbol="AMZN",
                score=Decimal("0.92"),
                current_price=Decimal("205"),
                previous_close=Decimal("200"),
                day_change_pct=Decimal("0.025"),
                time_sensitive=True,
                reason="green spike; do not chase after the move",
            )
        ],
        market_session="open_window",
        dynamic_live_cap=Decimal("500"),
    )

    assert decision.decision == "hold"
    assert decision.actions == []
    assert "do not chase" in decision.reason


def test_extracted_buy_candidate_helper_refuses_green_spike_chase():
    decision = supervisor_hourly.build_buy_candidate_decision(
        best_candidate=CandidateSignal(
            symbol="AMZN",
            score=Decimal("0.92"),
            current_price=Decimal("205"),
            previous_close=Decimal("200"),
            day_change_pct=Decimal("0.025"),
            time_sensitive=True,
            reason="green spike; do not chase after the move",
        ),
        new_buys_suspended_reason=None,
        live_buy_threshold=Decimal("0.78"),
        paper_first_threshold=Decimal("0.62"),
        live_unallocated=Decimal("500"),
        market_session="open_window",
        live_exposure=Decimal("0"),
        can_trade_session=lambda _session: True,
        live_sleeve="current-aggressive",
    )

    assert decision is not None
    assert decision.decision == "hold"
    assert decision.actions == []
    assert "do not chase" in decision.reason


def test_board_pause_blocks_new_buys_but_keeps_decision_packet_material():
    decision = build_hourly_decision(
        live_positions=[],
        live_open_orders=[],
        config=HourlySupervisorConfig(),
        candidate_signals=[
            CandidateSignal(
                symbol="AMZN",
                score=Decimal("0.92"),
                current_price=Decimal("197"),
                previous_close=Decimal("200"),
                day_change_pct=Decimal("-0.015"),
                time_sensitive=True,
                reason="controlled dip; buy-the-dip candidate",
            )
        ],
        market_session="open_window",
        dynamic_live_cap=Decimal("500"),
        new_buys_suspended_reason="paired live sell and buy was found",
    )

    assert decision.decision == "hold"
    assert decision.material is True
    assert decision.actions == []
    assert "new live buys paused by BOARD review" in decision.reason


def test_extracted_buy_candidate_helper_respects_board_pause():
    decision = supervisor_hourly.build_buy_candidate_decision(
        best_candidate=CandidateSignal(
            symbol="AMZN",
            score=Decimal("0.92"),
            current_price=Decimal("197"),
            previous_close=Decimal("200"),
            day_change_pct=Decimal("-0.015"),
            time_sensitive=True,
            reason="controlled dip; buy-the-dip candidate",
        ),
        new_buys_suspended_reason="paired live sell and buy was found",
        live_buy_threshold=Decimal("0.78"),
        paper_first_threshold=Decimal("0.62"),
        live_unallocated=Decimal("500"),
        market_session="open_window",
        live_exposure=Decimal("0"),
        can_trade_session=lambda _session: True,
        live_sleeve="current-aggressive",
    )

    assert decision is not None
    assert decision.decision == "hold"
    assert decision.material is True
    assert decision.actions == []
    assert "new live buys paused by BOARD review" in decision.reason


def test_aggressive_decision_uses_paper_first_for_nonurgent_candidate():
    decision = build_hourly_decision(
        live_positions=[],
        live_open_orders=[],
        config=HourlySupervisorConfig(),
        candidate_signals=[
            CandidateSignal(
                symbol="AMZN",
                score=Decimal("0.68"),
                current_price=Decimal("205"),
                time_sensitive=False,
                reason="constructive but not urgent",
            )
        ],
        market_session="regular",
        dynamic_live_cap=Decimal("100"),
    )

    assert decision.decision == "paper-first"
    assert decision.actions[0].account == "paper"
    assert decision.actions[0].execution_mode == "paper_first"


def test_profit_take_still_outranks_clean_dip_buy_after_extraction():
    decision = build_hourly_decision(
        live_positions=[
            {
                "symbol": "NVDA",
                "unrealized_plpc": "0.062",
                "market_value": "52.50",
                "qty": "0.232",
                "current_price": "226",
            }
        ],
        live_open_orders=[],
        config=HourlySupervisorConfig(),
        candidate_signals=[
            CandidateSignal(
                symbol="AMZN",
                score=Decimal("0.91"),
                current_price=Decimal("197"),
                previous_close=Decimal("200"),
                day_change_pct=Decimal("-0.015"),
                time_sensitive=True,
                reason="controlled dip; buy-the-dip candidate",
            )
        ],
        market_session="regular",
        dynamic_live_cap=Decimal("1000"),
    )

    assert decision.decision == "profit-take"
    assert decision.actions[0].normalized_side() == "sell"


def test_extracted_trailing_hold_helper_returns_quiet_hold_without_trigger():
    decision = supervisor_hourly.build_trailing_hold_decision(
        best_position={
            "symbol": "MA",
            "unrealized_plpc": "0.020",
            "market_value": "39.00",
        },
        profit_review_plpc=Decimal("0.05"),
        live_exposure=Decimal("39.00"),
    )

    assert decision.decision == "hold"
    assert decision.material is False
    assert decision.actions == []
    assert "no risk, profit, order" in decision.reason


def test_extracted_trailing_hold_helper_reviews_profit_without_order():
    decision = supervisor_hourly.build_trailing_hold_decision(
        best_position={
            "symbol": "MA",
            "unrealized_plpc": "0.055",
            "market_value": "39.00",
        },
        profit_review_plpc=Decimal("0.05"),
        live_exposure=Decimal("39.00"),
    )

    assert decision.decision == "profit-review"
    assert decision.material is True
    assert decision.actions == []
    assert decision.reason == "MA reached profit review threshold"


def test_profit_take_still_outranks_trailing_profit_review_after_extraction():
    decision = build_hourly_decision(
        live_positions=[
            {
                "symbol": "NVDA",
                "unrealized_plpc": "0.062",
                "market_value": "52.50",
                "qty": "0.232",
                "current_price": "226",
            }
        ],
        live_open_orders=[],
        config=HourlySupervisorConfig(),
        market_session="regular",
        dynamic_live_cap=Decimal("1000"),
    )

    assert decision.decision == "profit-take"
    assert decision.actions[0].normalized_side() == "sell"


def test_loss_review_does_not_rotate_into_green_spike():
    decision = build_hourly_decision(
        live_positions=[
            {
                "symbol": "GOOGL",
                "unrealized_plpc": "-0.075",
                "market_value": "45.00",
                "cost_basis": "50.00",
                "qty": "0.12",
                "current_price": "375",
            }
        ],
        live_open_orders=[],
        config=HourlySupervisorConfig(),
        candidate_signals=[
            CandidateSignal(
                symbol="AMZN",
                score=Decimal("0.91"),
                current_price=Decimal("205"),
                previous_close=Decimal("200"),
                day_change_pct=Decimal("0.025"),
                time_sensitive=True,
                reason="green spike; do not chase after the move",
            )
        ],
        market_session="regular",
        dynamic_live_cap=Decimal("500"),
    )

    assert decision.decision == "loss-review"
    assert decision.actions == []
    assert "no live sell was submitted" in decision.reason


def test_loss_review_does_not_pair_sell_with_clean_dip_candidate():
    decision = build_hourly_decision(
        live_positions=[
            {
                "symbol": "GOOGL",
                "unrealized_plpc": "-0.075",
                "market_value": "45.00",
                "cost_basis": "50.00",
                "qty": "0.12",
                "current_price": "375",
            }
        ],
        live_open_orders=[],
        config=HourlySupervisorConfig(),
        candidate_signals=[
            CandidateSignal(
                symbol="AMZN",
                score=Decimal("0.91"),
                current_price=Decimal("197"),
                previous_close=Decimal("200"),
                day_change_pct=Decimal("-0.015"),
                time_sensitive=True,
                reason="controlled dip; buy-the-dip candidate",
            )
        ],
        market_session="regular",
        dynamic_live_cap=Decimal("500"),
    )

    assert decision.decision == "loss-review"
    assert decision.actions == []
    assert "The BOARD must decide" in decision.reason


def test_hourly_decision_sells_profit_spike_instead_of_only_reviewing():
    decision = build_hourly_decision(
        live_positions=[
            {
                "symbol": "NVDA",
                "unrealized_plpc": "0.062",
                "market_value": "52.50",
                "qty": "0.232",
                "current_price": "226",
            }
        ],
        live_open_orders=[],
        config=HourlySupervisorConfig(),
        market_session="regular",
        dynamic_live_cap=Decimal("1000"),
    )

    assert decision.decision == "profit-take"
    assert decision.actions[0].symbol == "NVDA"
    assert decision.actions[0].normalized_side() == "sell"
    assert decision.actions[0].execution_mode == "tiny_live"
    assert "Sell the spike" in decision.actions[0].reason


def test_extracted_loss_review_helper_blocks_without_exit_evidence():
    decision = supervisor_hourly.build_loss_review_decision(
        worst_position={
            "symbol": "MSFT",
            "unrealized_plpc": "-0.035",
            "market_value": "29.50",
            "qty": "0.071",
            "current_price": "413",
        },
        loss_review_plpc=Decimal("-0.03"),
        market_session="regular",
        live_exposure=Decimal("29.50"),
        generated_at=datetime.datetime(2026, 6, 7, 15, 0, tzinfo=datetime.UTC),
        can_trade_session=lambda _session: True,
        positive_decimal_or_none=lambda value: Decimal(str(value)) if value not in (None, "") else None,
        live_sleeve="current-aggressive",
    )

    assert decision is not None
    assert decision.decision == "loss-review"
    assert decision.actions == []
    assert "no live sell was submitted" in decision.reason
    assert decision.evidence["loss_exit_review"]["allowed"] is False
    assert "allowed loss-exit reason is missing" in decision.evidence["loss_exit_review"]["blockers"]


def test_extracted_loss_review_helper_routes_discretionary_sell_to_board():
    decision = supervisor_hourly.build_loss_review_decision(
        worst_position={
            "symbol": "MSFT",
            "unrealized_plpc": "-0.035",
            "market_value": "29.50",
            "qty": "0.071",
            "current_price": "413",
            "avg_entry_price": "428",
            "unrealized_pl": "-1.07",
            "holding_period_trading_days": 5,
            "earnings_or_guidance_break": True,
            "allowed_exit_reason_source": {
                "packet_id": "earnings-guidance-packet-20260603",
                "path": "normalized_loss_review_evidence/earnings-guidance-packet-20260603.json",
                "sha256": "a" * 64,
            },
            "exit_reason": "guidance cut broke the support thesis",
            "original_buy_thesis": "Support should hold if cloud growth guidance stays intact.",
            "current_thesis_status": "Guidance cut invalidated the support thesis.",
            "relative_market_context": {
                "spy": "flat",
                "qqq": "+0.2%",
                "sector": "+0.1%",
                "company_specific_damage": True,
            },
            "company_specific_news_check": "Company-specific guidance cut confirmed.",
            "earnings_guidance_or_filing_check": "Guidance cut confirmed in company filing.",
            "why_hold_is_worse_than_sell": "The original catalyst broke and capital can wait in cash.",
            "why_this_is_not_broad_market_red_day_noise": "SPY, QQQ, and sector were not down with MSFT.",
            "source_packet_ids": ["earnings-guidance-packet-20260603"],
            "loss_exit_confidence": "0.82",
        },
        loss_review_plpc=Decimal("-0.03"),
        market_session="regular",
        live_exposure=Decimal("29.50"),
        generated_at=datetime.datetime(2026, 6, 7, 15, 0, tzinfo=datetime.UTC),
        can_trade_session=lambda _session: True,
        positive_decimal_or_none=lambda value: Decimal(str(value)) if value not in (None, "") else None,
        live_sleeve="current-aggressive",
    )

    assert decision is not None
    assert decision.decision == "loss-review"
    assert decision.actions == []
    assert "autonomous portfolio BOARD" in decision.reason
    assert decision.evidence["loss_exit_review"]["allowed"] is False


def test_extracted_profit_take_helper_sells_spike_with_current_price():
    decision = supervisor_hourly.build_profit_take_decision(
        best_position={
            "symbol": "NVDA",
            "unrealized_plpc": "0.062",
            "market_value": "52.50",
            "qty": "0.232",
            "current_price": "226",
        },
        profit_review_plpc=Decimal("0.05"),
        market_session="regular",
        live_exposure=Decimal("52.50"),
        generated_at=datetime.datetime(2026, 6, 7, 15, 0, tzinfo=datetime.UTC),
        can_trade_session=lambda _session: True,
        positive_decimal_or_none=lambda value: Decimal(str(value)) if value not in (None, "") else None,
        live_sleeve="current-aggressive",
    )

    assert decision is not None
    assert decision.decision == "profit-take"
    assert decision.actions[0].symbol == "NVDA"
    assert decision.actions[0].qty == Decimal("0.232")
    assert decision.actions[0].limit_price == Decimal("226")
    assert decision.actions[0].sleeve == "current-aggressive"


def test_profit_take_requires_current_price_before_order():
    decision = build_hourly_decision(
        live_positions=[
            {
                "symbol": "NVDA",
                "unrealized_plpc": "0.062",
                "market_value": "52.50",
                "qty": "0.232",
                "current_price": "",
            }
        ],
        live_open_orders=[],
        config=HourlySupervisorConfig(),
        market_session="regular",
        dynamic_live_cap=Decimal("1000"),
    )

    assert decision.decision == "profit-review"
    assert decision.actions == []
    assert "current price evidence is missing" in decision.reason
    assert decision.evidence["profit_exit_review"]["blockers"] == [
        "current price evidence is missing"
    ]


def test_open_orders_still_outrank_profit_take_after_extraction():
    decision = build_hourly_decision(
        live_positions=[
            {
                "symbol": "NVDA",
                "unrealized_plpc": "0.062",
                "market_value": "52.50",
                "qty": "0.232",
                "current_price": "226",
            }
        ],
        live_open_orders=[{"symbol": "NVDA", "side": "sell", "status": "new"}],
        config=HourlySupervisorConfig(),
        market_session="regular",
        dynamic_live_cap=Decimal("1000"),
    )

    assert decision.decision == "review-open-orders"
    assert decision.actions == []


def test_loss_review_still_outranks_profit_take_after_extraction():
    decision = build_hourly_decision(
        live_positions=[
            {
                "symbol": "TSM",
                "unrealized_plpc": "-0.075",
                "market_value": "22.00",
                "qty": "0.05",
                "current_price": "415",
            },
            {
                "symbol": "NVDA",
                "unrealized_plpc": "0.062",
                "market_value": "52.50",
                "qty": "0.232",
                "current_price": "226",
            },
        ],
        live_open_orders=[],
        config=HourlySupervisorConfig(),
        market_session="regular",
        dynamic_live_cap=Decimal("1000"),
    )

    assert decision.decision == "loss-review"
    assert decision.actions == []


def test_hold_cash_after_reduction_is_valid_without_reinvestment():
    close = HourlySupervisorAction(
        action="close",
        symbol="MSFT",
        side="sell",
        notional=Decimal("30"),
        limit_price=Decimal("415"),
    )
    hold_cash = HourlySupervisorAction(
        action="hold_cash",
        symbol="CASH",
        notional=Decimal("0"),
        limit_price=Decimal("0"),
        order_type="none",
        reason="replacement quality is weak",
    )

    issues = validate_hourly_supervisor_actions(
        [close, hold_cash],
        current_live_exposure=Decimal("100"),
        config=AlpacaExecutionConfig(live_exposure_limit=Decimal("100")),
    )

    assert issues == []


def test_paired_reduction_rotation_is_not_blocked_by_old_live_cap_math():
    close = HourlySupervisorAction(
        action="close",
        symbol="GOOGL",
        side="sell",
        notional=Decimal("42.96"),
        limit_price=Decimal("366.17"),
    )
    buy = HourlySupervisorAction(
        action="buy",
        symbol="QCOM",
        side="buy",
        notional=Decimal("25.00"),
        limit_price=Decimal("242.59"),
    )

    issues = validate_hourly_supervisor_actions(
        [close, buy],
        current_live_exposure=Decimal("150.00"),
        config=AlpacaExecutionConfig(live_exposure_limit=Decimal("100.00")),
    )

    assert issues == []


def test_aggressive_limit_builder_uses_limit_price_buffers():
    assert aggressive_limit_price(Decimal("100"), side="buy") == Decimal("100.20")
    assert aggressive_limit_price(Decimal("100"), side="sell") == Decimal("99.80")
    assert aggressive_limit_price(Decimal("100"), side="buy", extended_hours=True) == Decimal("100.30")


def test_duplicate_open_order_is_rejected():
    buy = HourlySupervisorAction(
        action="buy",
        symbol="AMZN",
        notional=Decimal("10"),
        limit_price=Decimal("205"),
    )

    issues = validate_hourly_supervisor_actions(
        [buy],
        current_live_exposure=Decimal("50"),
        config=AlpacaExecutionConfig(live_exposure_limit=Decimal("100")),
        open_orders=[{"symbol": "AMZN", "side": "buy"}],
    )

    assert "duplicate open order" in issues[0].reason


def test_non_stock_order_is_rejected():
    buy = HourlySupervisorAction(
        action="buy",
        symbol="BTCUSD",
        notional=Decimal("10"),
        limit_price=Decimal("100000"),
        asset_class="crypto",
    )

    issues = validate_hourly_supervisor_actions(
        [buy],
        current_live_exposure=Decimal("50"),
        config=AlpacaExecutionConfig(live_exposure_limit=Decimal("100")),
    )

    assert "only stock orders are allowed" in [issue.reason for issue in issues]


def test_urgent_exception_notification_policy():
    decision = build_hourly_decision(
        live_positions=[
            {
                "symbol": "MSFT",
                "unrealized_plpc": "-0.035",
                "market_value": "29.50",
                "qty": "0.071",
                "current_price": "413",
            }
        ],
        live_open_orders=[],
        config=HourlySupervisorConfig(),
    )

    assert should_notify_supervisor(decision, notification_policy="urgent-exceptions") is True


def test_alert_classifier_separates_routine_notable_and_critical():
    routine = build_hourly_decision(
        live_positions=[],
        live_open_orders=[],
        config=HourlySupervisorConfig(),
    )
    assert classify_supervisor_alert(routine).severity == "ROUTINE"
    assert classify_supervisor_alert(routine).notify is False

    notable = build_hourly_decision(
        live_positions=[],
        live_open_orders=[],
        config=HourlySupervisorConfig(),
        candidate_signals=[
            CandidateSignal(
                symbol="MSFT",
                score=Decimal("0.65"),
                current_price=Decimal("410"),
                reason="paper test",
            )
        ],
        market_session="regular",
    )
    assert notable.decision == "paper-first"
    assert classify_supervisor_alert(notable).severity == "NOTABLE"

    critical = build_hourly_decision(
        live_positions=[],
        live_open_orders=[],
        config=HourlySupervisorConfig(),
    )
    critical = critical.__class__(
        decision="blocked",
        material=True,
        reason="hourly supervisor action failed guardrail validation",
        live_exposure=Decimal("0"),
        issues=[
            type("Issue", (), {"ticket_id": "live-submit-guard", "reason": "risk envelope missing"})()
        ],
    )
    alert = classify_supervisor_alert(critical)
    assert alert.severity == "CRITICAL"
    assert alert.notify is True
    assert "repair its own setup" in alert.approval_prompt
    assert "stays stopped" in alert.approval_prompt
    assert "fix configuration" not in alert.approval_prompt


def test_critical_alert_serializes_clear_exception_email():
    portfolio = build_portfolio_snapshot(
        live_account={"status": "ACTIVE", "buying_power": "250", "equity": "500", "cash": "150"},
        paper_account={"status": "ACTIVE", "buying_power": "100000", "equity": "100000"},
        live_positions=[
            {
                "symbol": "GOOGL",
                "market_value": "114.99",
                "unrealized_pl": "-1.25",
                "unrealized_plpc": "-0.011",
                "current_price": "172.50",
            }
        ],
        live_open_orders=[],
        paper_positions=[],
        paper_open_orders=[],
    )
    decision = build_hourly_decision(
        live_positions=[],
        live_open_orders=[],
        config=HourlySupervisorConfig(),
    )
    decision = decision.__class__(
        decision="blocked",
        material=True,
        reason="hourly supervisor live submit failed guard validation",
        live_exposure=Decimal("0"),
        issues=[
            type("Issue", (), {"ticket_id": "live-submit-guard", "reason": "risk envelope missing"})()
        ],
        portfolio=portfolio,
    )

    payload = serialize_hourly_decision(decision)
    body = payload["alert_email"]["body"]
    clarity = evaluate_email_clarity(
        body,
        subject=payload["alert_email"]["subject"],
        report_type="urgent",
    )

    assert payload["alert"]["severity"] == "CRITICAL"
    assert payload["human_summary"] == (
        "Stopped before trading because a policy blocker needs review: risk envelope missing."
    )
    assert payload["issues"] == [
        {
            "ticket_id": "live-submit-guard",
            "reason": "risk envelope missing",
            "category": "policy",
        }
    ]
    assert payload["issue_category_counts"] == {"policy": 1}
    assert payload["alert_email"]["subject"].startswith("Action may be needed:")
    assert "Plain English" in body
    assert "The bot stopped before live money moved." in body
    assert "Trading stays blocked" in body
    assert "Where you stand" in body
    assert "Spent today: $0.00 real money, $0.00 practice" in body
    assert "Real-money account: holdings GOOGL; waiting orders 0; money in the market $114.99." in body
    assert "Practice account: holdings none; waiting orders 0; total value $100,000.00." in body
    assert "Problem: risk envelope missing" in body
    assert "(policy | live-submit-guard)" in body
    assert "Why it matters" in body
    assert "What to do next" in body
    assert "repair its own setup" in body
    assert "What the bot did or refused to do" not in body
    assert "fix configuration" not in body
    assert "live_exposure_limit" not in body
    assert clarity["status"] == "pass"
    assert len(body.splitlines()) <= 30


def test_supervisor_issue_category_splits_human_blocker_types():
    assert supervisor_issue_category("live-submit-guard", "risk envelope missing") == "policy"
    assert supervisor_issue_category("buying-power", "cash is too low for the order") == "cash"
    assert supervisor_issue_category("quotes", "source freshness is stale") == "stale"
    assert supervisor_issue_category("alpaca", "broker rejected order") == "broker"
    assert supervisor_issue_category("source", "price provider unavailable") == "data"
    assert supervisor_issue_category("setup", "green-spike chase detected") == "strategy"
    assert supervisor_issue_category("MSFT", "duplicate open order for symbol and side") == "actionability"


def test_clean_material_alert_email_does_not_claim_self_heal_is_needed():
    portfolio = build_portfolio_snapshot(
        live_account={"status": "ACTIVE", "buying_power": "62.44", "equity": "199.25", "cash": "62.44"},
        paper_account={"status": "ACTIVE", "buying_power": "100000", "equity": "100000"},
        live_positions=[{"symbol": "ORCL", "market_value": "23.74"}],
        live_open_orders=[],
        paper_positions=[],
        paper_open_orders=[],
    )
    decision = build_hourly_decision(
        live_positions=[],
        live_open_orders=[],
        config=HourlySupervisorConfig(),
    ).__class__(
        decision="profit-take",
        material=True,
        reason="Sell the spike: ORCL reached profit review threshold",
        live_exposure=Decimal("139.99"),
        actions=[
            HourlySupervisorAction(
                action="close",
                symbol="ORCL",
                side="sell",
                notional=Decimal("23.74"),
                limit_price=Decimal("231.18"),
                account="live",
                execution_mode="tiny_live",
            ),
            HourlySupervisorAction(
                action="hold_cash",
                symbol="CASH",
                side="hold",
                notional=Decimal("0"),
                limit_price=Decimal("0"),
                account="none",
                execution_mode="hold_cash",
            ),
        ],
        issues=[],
        portfolio=portfolio,
    )

    body = serialize_hourly_decision(decision)["alert_email"]["body"]

    assert "Problem: none" in body
    assert "No approval needed" in body
    assert "re-verify" in body
    assert "repair its own setup" not in body
    assert "trading stays blocked" not in body.lower()


def test_loss_review_email_requests_board_review_without_claiming_repair_needed():
    portfolio = build_portfolio_snapshot(
        live_account={"status": "ACTIVE", "buying_power": "86.38", "equity": "198.70", "cash": "86.38"},
        paper_account={"status": "ACTIVE", "buying_power": "100000", "equity": "100000"},
        live_positions=[
            {
                "symbol": "MA",
                "market_value": "36.94",
                "cost_basis": "38.23",
                "unrealized_plpc": "-0.0334",
            }
        ],
        live_open_orders=[],
        paper_positions=[],
        paper_open_orders=[],
    )
    decision = build_hourly_decision(
        live_positions=[
            {
                "symbol": "MA",
                "unrealized_plpc": "-0.0334",
                "market_value": "36.94",
                "cost_basis": "38.23",
                "qty": "0.079",
                "current_price": "465.22",
            }
        ],
        live_open_orders=[],
        config=HourlySupervisorConfig(),
        market_session="regular",
    )
    decision = decision.__class__(**{**decision.__dict__, "portfolio": portfolio})

    body = serialize_hourly_decision(decision)["alert_email"]["body"]
    clarity = evaluate_email_clarity(body, report_type="urgent")

    assert "Problem: MA is down enough to trigger a loss review." in body
    assert "Nothing was sold" in body
    assert "A review must finish before any sale at a loss" in body
    assert "review before" in body
    assert "allowed loss-exit reason is missing" not in body
    assert "held, not sold" in body
    assert "practice" in body.lower()
    assert "No repair needed" not in body
    assert "self-heal safe setup problems" not in body
    assert clarity["status"] == "pass"
    assert clarity["max_line_length"] <= 180


def test_loss_review_email_uses_refreshed_board_evidence_counts():
    decision = build_hourly_decision(
        live_positions=[
            {
                "symbol": "MA",
                "unrealized_plpc": "-0.0334",
                "market_value": "36.94",
                "cost_basis": "38.23",
                "qty": "0.079",
                "current_price": "465.22",
            }
        ],
        live_open_orders=[],
        config=HourlySupervisorConfig(),
        market_session="regular",
    )
    evidence = {
        **decision.evidence,
        "execution_board_review": {
            "recommendation": "review_underperformers_before_new_buys",
            "loss_review_evidence": {
                "symbol": "MA",
                "review_allowed": False,
                "remaining_blocker_count": 5,
                "resolved_blocker_count": 8,
                "next_action": "manual_board_review_with_refreshed_evidence_required",
            },
        },
    }
    decision = decision.__class__(**{**decision.__dict__, "evidence": evidence})

    payload = serialize_hourly_decision(decision)
    body = payload["alert_email"]["body"]
    clarity = evaluate_email_clarity(body, report_type="urgent")

    assert "5 evidence item(s) still open after refresh" in body
    assert "13 evidence item(s) still missing" not in body
    assert "held, not sold" in body
    assert len(body.splitlines()) <= 32
    assert clarity["status"] == "pass"
    assert clarity["max_line_length"] <= 180


def test_loss_review_email_ignores_board_evidence_for_another_symbol():
    decision = build_hourly_decision(
        live_positions=[
            {
                "symbol": "NFLX",
                "unrealized_plpc": "-0.1151",
                "market_value": "23.67",
                "cost_basis": "26.76",
                "qty": "0.320946047",
                "current_price": "73.78",
            }
        ],
        live_open_orders=[],
        config=HourlySupervisorConfig(),
        market_session="closed",
    )
    evidence = {
        **decision.evidence,
        "execution_board_review": {
            "recommendation": "review_underperformers_before_new_buys",
            "loss_review_evidence": {
                "symbol": "TSM",
                "review_allowed": False,
                "remaining_blocker_count": 5,
                "resolved_blocker_count": 8,
            },
        },
    }
    decision = decision.__class__(**{**decision.__dict__, "evidence": evidence})

    body = serialize_hourly_decision(decision)["alert_email"]["body"]

    assert "Problem: NFLX is down enough to trigger a loss review." in body
    assert "TSM is down enough" not in body
    assert "5 evidence item(s) still open after refresh" not in body


def test_same_cause_alert_throttle_suppresses_duplicate_email_only():
    issue = type("Issue", (), {"ticket_id": "live-submit-guard", "reason": "risk envelope missing"})()
    first = build_hourly_decision(
        live_positions=[],
        live_open_orders=[],
        config=HourlySupervisorConfig(),
    ).__class__(
        decision="blocked",
        material=True,
        reason="hourly supervisor live submit failed guard validation",
        live_exposure=Decimal("0"),
        issues=[issue],
        generated_at=datetime.datetime(2026, 6, 1, 15, 0, tzinfo=datetime.timezone.utc),
    )
    first_payload = serialize_hourly_decision(first)
    duplicate = first.__class__(
        decision=first.decision,
        material=first.material,
        reason=first.reason,
        live_exposure=first.live_exposure,
        issues=first.issues,
        generated_at=datetime.datetime(2026, 6, 1, 16, 0, tzinfo=datetime.timezone.utc),
    )

    duplicate_payload = serialize_hourly_decision(
        duplicate,
        recent_packets=[first_payload],
    )

    assert "alert_email" in first_payload
    assert "alert_email" not in duplicate_payload
    assert duplicate_payload["alert"]["base_notify"] is True
    assert duplicate_payload["alert"]["notify"] is False
    assert duplicate_payload["alert"]["email_suppressed"] is True
    assert duplicate_payload["alert"]["fingerprint"] == first_payload["alert"]["fingerprint"]


def test_alert_throttle_allows_new_cause_and_stale_repeat():
    first_issue = type("Issue", (), {"ticket_id": "live-submit-guard", "reason": "risk envelope missing"})()
    first = build_hourly_decision(
        live_positions=[],
        live_open_orders=[],
        config=HourlySupervisorConfig(),
    ).__class__(
        decision="blocked",
        material=True,
        reason="hourly supervisor live submit failed guard validation",
        live_exposure=Decimal("0"),
        issues=[first_issue],
        generated_at=datetime.datetime(2026, 6, 1, 15, 0, tzinfo=datetime.timezone.utc),
    )
    first_payload = serialize_hourly_decision(first)
    new_issue = type("Issue", (), {"ticket_id": "reconciliation", "reason": "position mismatch"})()
    new_cause = first.__class__(
        decision="blocked",
        material=True,
        reason="hourly supervisor reconciliation failed",
        live_exposure=Decimal("0"),
        issues=[new_issue],
        generated_at=datetime.datetime(2026, 6, 1, 16, 0, tzinfo=datetime.timezone.utc),
    )
    stale_repeat = first.__class__(
        decision=first.decision,
        material=first.material,
        reason=first.reason,
        live_exposure=first.live_exposure,
        issues=first.issues,
        generated_at=datetime.datetime(2026, 6, 1, 20, 1, tzinfo=datetime.timezone.utc),
    )

    new_cause_payload = serialize_hourly_decision(
        new_cause,
        recent_packets=[first_payload],
    )
    stale_repeat_payload = serialize_hourly_decision(
        stale_repeat,
        recent_packets=[first_payload],
    )

    assert "alert_email" in new_cause_payload
    assert new_cause_payload["alert"]["email_suppressed"] is False
    assert "alert_email" in stale_repeat_payload
    assert stale_repeat_payload["alert"]["email_suppressed"] is False


def test_portfolio_snapshot_and_daily_digest_formats_key_balances_and_gains():
    portfolio = build_portfolio_snapshot(
        live_account={
            "status": "ACTIVE",
            "buying_power": "100",
            "equity": "1201.34",
            "portfolio_value": "1201.34",
        },
        paper_account={
            "status": "ACTIVE",
            "buying_power": "197928.04",
            "equity": "100028.04",
        },
        live_positions=[
            {
                "symbol": "GOOGL",
                "qty": "0.117",
                "market_value": "45.57",
                "cost_basis": "45",
                "unrealized_pl": "0.57",
                "unrealized_plpc": "0.0128",
                "current_price": "388.43",
                "avg_entry_price": "383.49",
            }
        ],
        live_open_orders=[
            {
                "symbol": "NVDA",
                "side": "buy",
                "type": "limit",
                "status": "open",
                "limit_price": "212.25",
                "client_order_id": "ta-test",
            }
        ],
    )
    body = render_daily_supervisor_report(
        portfolio=portfolio,
        packets=[
            {
                "generated_at": "2026-05-29T20:00:00+00:00",
                "decision": "paper-first",
                "reason": "Paper-first candidate before live rotation",
                "material": True,
                "actions": [
                    {
                        "account": "paper",
                        "symbol": "ORCL",
                        "side": "buy",
                        "notional": "100",
                    }
                ],
                "submitted": [
                    {
                        "symbol": "ORCL",
                        "side": "buy",
                        "notional": "100",
                        "limit_price": "240.12",
                        "client_order_id": "ta-hourly-paper-orcl",
                    }
                ],
                "evidence": {
                    "overnight_plan": {
                        "status": "confirmed",
                        "overnight_top_symbol": "ORCL",
                        "current_top_symbol": "ORCL",
                    }
                },
            }
        ],
        email_to="nebulazer2003@gmail.com",
    )

    assert portfolio["live"]["unrealized_pl"] == "0.57"
    assert "Real-money account: $1,201.34 total" in body
    assert "position P/L $0.57 (1.26%)" in body
    assert "Live buying power:" not in body
    assert "Live exposure:" not in body
    assert "Paper equity:" not in body
    assert "GOOGL" in body
    assert "Plain English" in body
    assert "Where you stand" in body
    assert "What happened" in body
    assert "Problem: none" in body
    assert "Why it matters" in body
    assert "What to do next" in body
    assert "Spent today: $0.00 real money, $100.00 practice" in body
    assert "What to do next" in body
    assert "Nothing needed from you today" in body
    assert len(body.splitlines()) <= 45


def test_daily_report_payload_builder_collects_context_lines():
    portfolio = {
        "live": {
            "status": "ACTIVE",
            "equity": "1200.00",
            "unrealized_pl": "12.00",
            "exposure": "600.00",
            "positions": [],
            "open_orders": [],
        },
        "paper": {
            "status": "ACTIVE",
            "unrealized_pl": "40.00",
            "positions": [],
            "open_orders": [],
        },
        "ranked_candidates": [{"symbol": "XOM", "day_change_pct": "-1.2", "score": "8.5"}],
    }
    packets = [
        {
            "generated_at": "2026-06-07T14:00:00+00:00",
            "decision": "hold",
            "material": False,
            "reason": "no trigger",
            "submitted": [],
            "issues": [],
        }
    ]

    payload = supervisor_daily_report.build_supervisor_daily_report_payload(
        portfolio=portfolio,
        packets=packets,
        email_to="owner@example.test",
        paper_tournament_report={
            "rankings": [
                {
                    "strategy_id": "buy_the_dip",
                    "total_return": "12.34",
                    "total_return_pct": "1.23",
                }
            ],
            "live_strategy_candidate": {
                "status": "watching",
                "strategy_id": "buy_the_dip",
            },
        },
        premarket_brief={
            "generated_at": "2026-06-07T12:30:00+00:00",
            "premarket_instructions": {"top_symbol": "XOM"},
            "source_packets": [{"kind": "overnight"}, {"kind": "quote"}],
        },
        premarket_brief_validation={"status": "pass"},
        premarket_brief_path=Path("results/premarket_briefs/latest.json"),
        model_telemetry_report={"operator_summary": "Mac helper reachable; Codex remains judge."},
        execution_board_review={
            "recommendation": "pause_new_buys_and_review",
            "metrics": {"submitted_order_count": 0},
            "violations": [{"kind": "late_chase"}],
            "warnings": [{"kind": "source_stale"}],
        },
        alpaca_reference_summary={
            "status": "warning",
            "material": True,
            "material_summary": "Alpaca reference: explicit IEX feed is current; calendar settlement fields are stale.",
            "operation_count": 99,
            "route_statuses": {"trading.get.v2_calendar": "stale"},
        },
    )

    assert payload["subject"].startswith("Your trading update for ")
    assert payload["subject"].endswith("[TradingAgents]")
    assert payload["packet_count"] == 1
    assert payload["material_count"] == 0
    assert Path(payload["premarket_brief_path"]).as_posix() == "results/premarket_briefs/latest.json"
    assert "Practice-strategy race:" in payload["body"]
    assert "Tomorrow's top stock to watch: XOM." in payload["body"]
    assert "path results" not in payload["body"]
    assert "Model telemetry" not in payload["body"]
    assert "calendar settlement fields are stale" in payload["body"]
    assert payload["alpaca_reference_summary"]["operation_count"] == 99

    compact = supervisor_daily_report.compact_supervisor_daily_report_payload(
        payload,
        "results/daily_reports/example.json",
    )
    assert compact["context_summary"]["alpaca_reference"]["operation_count"] == 99
    assert compact["context_summary"]["alpaca_reference"]["route_statuses"] == {
        "trading.get.v2_calendar": "stale"
    }


def test_daily_digest_excludes_rejected_orders_from_spent_today():
    portfolio = build_portfolio_snapshot(
        live_account={"status": "ACTIVE", "equity": "1200"},
        paper_account={"status": "ACTIVE", "equity": "100000"},
        live_positions=[],
        live_open_orders=[],
    )
    body = render_daily_supervisor_report(
        portfolio=portfolio,
        packets=[
            {
                "generated_at": "2026-05-29T20:00:00+00:00",
                "decision": "paper-first",
                "reason": "paper order accepted and live order rejected",
                "material": True,
                "actions": [
                    {
                        "account": "paper",
                        "symbol": "ORCL",
                        "side": "buy",
                    },
                    {
                        "account": "live",
                        "symbol": "MSFT",
                        "side": "buy",
                    },
                ],
                "submitted": [
                    {
                        "symbol": "ORCL",
                        "side": "buy",
                        "notional": "100",
                        "limit_price": "240.12",
                        "status": "accepted",
                        "client_order_id": "ta-hourly-paper-orcl",
                    },
                    {
                        "symbol": "MSFT",
                        "side": "buy",
                        "notional": "75",
                        "limit_price": "410.00",
                        "status": "rejected",
                        "client_order_id": "ta-hourly-live-msft",
                    },
                ],
            }
        ],
        email_to="nebulazer2003@gmail.com",
    )

    assert "Spent today: $0.00 real money, $100.00 practice" in body
    assert "Spent today: $0.00 real money" in body
    assert "rejected or canceled before any money moved" in body
    assert "Failed, rejected, or canceled order details" not in body


def test_daily_digest_explains_uncapped_live_budget_without_cap_room():
    portfolio = build_portfolio_snapshot(
        live_account={"status": "ACTIVE", "equity": "202.20", "buying_power": "126.16"},
        paper_account={"status": "ACTIVE", "equity": "100000"},
        live_positions=[],
        live_open_orders=[],
    )

    body = render_daily_supervisor_report(
        portfolio=portfolio,
        packets=[
            {
                "generated_at": "2026-06-02T18:16:00+00:00",
                "decision": "profit-take",
                "reason": "Sell the spike: AVGO reached profit review threshold",
                "material": True,
                "evidence": {"live_budget": {"mode": "autonomous_uncapped"}},
            }
        ],
        email_to="nebulazer2003@gmail.com",
    )

    assert "Real-money account:" in body
    assert "Live sizing room:" not in body
    assert "Unused live sizing room:" not in body


def test_daily_digest_uses_self_heal_proposal_for_blockers():
    portfolio = build_portfolio_snapshot(
        live_account={"status": "ACTIVE", "equity": "1200"},
        paper_account={"status": "ACTIVE", "equity": "100000"},
        live_positions=[],
        live_open_orders=[],
    )
    body = render_daily_supervisor_report(
        portfolio=portfolio,
        packets=[
            {
                "generated_at": "2026-05-29T20:00:00+00:00",
                "decision": "blocked",
                "reason": "risk envelope missing",
                "material": True,
                "submitted": [],
                "issues": [
                    {
                        "ticket_id": "live-submit-guard",
                        "reason": "risk envelope missing",
                    }
                ],
            }
        ],
        email_to="nebulazer2003@gmail.com",
    )

    assert "Problem:" in body
    assert "What to do next" in body
    assert "approve the safe" in body.lower()
    assert "paused" in body.lower()
    assert "fix configuration" not in body
    assert "Ops only question" not in body


def test_daily_digest_clears_historical_blocker_after_later_clean_packet():
    portfolio = build_portfolio_snapshot(
        live_account={"status": "ACTIVE", "equity": "202.20", "buying_power": "152.44"},
        paper_account={"status": "ACTIVE", "equity": "100000"},
        live_positions=[],
        live_open_orders=[],
    )

    body = render_daily_supervisor_report(
        portfolio=portfolio,
        packets=[
            {
                "generated_at": "2026-06-02T17:03:41+00:00",
                "decision": "blocked",
                "reason": "hourly supervisor action failed guardrail validation",
                "material": True,
                "issues": [
                    {
                        "reason": (
                            "paired live sell is not large enough to bring exposure under "
                            "the live cap: current $150.00 - release $43.16 + buy $25.00 "
                            "= projected $131.83, cap $100.00"
                        )
                    }
                ],
            },
            {
                "generated_at": "2026-06-02T18:31:55+00:00",
                "decision": "profit-take",
                "reason": "Sell the spike: NVDA reached profit review threshold",
                "material": True,
                "issues": [],
                "submitted": [
                    {
                        "symbol": "NVDA",
                        "side": "sell",
                        "qty": "0.11778674",
                        "limit_price": "223.11",
                        "status": "filled",
                        "client_order_id": "ta-tiny-20260602-current-nvda-sell",
                    }
                ],
            },
        ],
        email_to="nebulazer2003@gmail.com",
    )

    assert "Problem: none" in body
    assert "The bot found a safety problem and kept live trading blocked." not in body
    assert "approve the safe auto-repair" not in body.lower()
    assert (
        "An earlier issue cleared on its own: An earlier real-money buy was "
        "stopped by a spending limit. Later checks came back clean."
    ) in body
    assert "projected $131.83, cap $100.00" not in body


def test_daily_digest_formats_sell_to_close_as_quantity_not_zero_spend():
    portfolio = build_portfolio_snapshot(
        live_account={"status": "ACTIVE", "equity": "202.20", "buying_power": "152.44"},
        paper_account={"status": "ACTIVE", "equity": "100000"},
        live_positions=[],
        live_open_orders=[],
    )

    body = render_daily_supervisor_report(
        portfolio=portfolio,
        packets=[
            {
                "generated_at": "2026-06-02T18:14:57+00:00",
                "decision": "profit-take",
                "reason": "Sell the spike: AVGO reached profit review threshold",
                "material": True,
                "submitted": [
                    {
                        "symbol": "AVGO",
                        "side": "sell",
                        "qty": "0.05579062",
                        "limit_price": "472.76",
                        "status": "filled",
                        "client_order_id": "ta-tiny-20260602-current-avgo-sell",
                    }
                ],
            }
        ],
        email_to="nebulazer2003@gmail.com",
    )

    assert "Spent today: $0.00 real money" in body
    assert "live AVGO sell qty 0.05579062 limit 472.76 status=filled" in body
    assert "live AVGO sell $0.00" not in body


def test_hourly_evidence_separates_baseline_from_delta(tmp_path):
    previous = tmp_path / "hourly-supervisor-20260526-150500.json"
    previous.write_text(
        '{"generated_at":"2026-05-26T15:05:00+00:00","decision":"hold","live_exposure":"100.00"}',
        encoding="utf-8",
    )

    evidence = build_hourly_evidence(
        live_account={"status": "ACTIVE", "buying_power": "100", "equity": "200"},
        paper_account={"status": "ACTIVE", "buying_power": "1000", "equity": "100000"},
        live_positions=[{"symbol": "GOOGL"}],
        live_open_orders=[],
        previous_packet=previous,
    )
    decision = build_hourly_decision(
        live_positions=[],
        live_open_orders=[],
        config=HourlySupervisorConfig(),
    )
    payload = serialize_hourly_decision(
        decision.__class__(
            decision=decision.decision,
            material=decision.material,
            reason=decision.reason,
            live_exposure=decision.live_exposure,
            evidence=evidence,
            generated_at=decision.generated_at,
        )
    )

    assert payload["evidence"]["baseline"][0]["category"] == "previous_hourly_packet"
    assert payload["evidence"]["delta"][0]["category"] == "live_account"
    assert "GOOGL" in payload["evidence"]["delta"][2]["summary"]
    market_structure = [
        item for item in payload["evidence"]["delta"]
        if item["category"] == "market_structure"
    ][0]
    assert "effective date" in market_structure["summary"]
    assert "Preserve current account restrictions" in market_structure["summary"]


def test_premarket_brief_aggregates_timestamped_packets_and_writes_latest(tmp_path):
    hourly_dir = tmp_path / "hourly"
    overnight_dir = tmp_path / "overnight"
    tournament_dir = tmp_path / "tournament"
    output_dir = tmp_path / "briefs"
    hourly_dir.mkdir()
    overnight_dir.mkdir()
    tournament_dir.mkdir()
    (hourly_dir / "hourly-supervisor-20260601-010000.json").write_text(
        """
        {
          "generated_at": "2026-06-01T01:00:00+00:00",
          "decision": "hold",
          "reason": "quiet weekend check",
          "material": false,
          "submitted": [],
          "issues": [],
          "portfolio": {
            "live": {
              "unrealized_pl": "1.25",
              "positions": [{"symbol": "GOOGL", "unrealized_pl": "0.50"}],
              "open_orders": []
            },
            "ranked_candidates": [{"symbol": "ORCL", "score": "0.90"}]
          }
        }
        """,
        encoding="utf-8",
    )
    (overnight_dir / "overnight-plan-20260601-003000.json").write_text(
        """
        {
          "generated_at": "2026-06-01T00:30:00+00:00",
          "analysis_only": true,
          "overnight_quality": {"full_graph_count": 1, "fallback_count": 1, "graph_failure_count": 1},
          "research_context": {
            "analysis_only": true,
            "packet_count": 8,
            "execution_authority": "none",
            "prior_feed": {
              "schema": "overnight_prior_feed_v1",
              "path": "results/overnight_plans/research_context/overnight-prior-feed-20260601-003000.json",
              "latest_path": "results/overnight_plans/research_context/overnight-prior-feed-latest.json",
              "packet_count": 8,
              "blocked_count": 0,
              "analysis_only": true,
              "execution_authority": "none",
              "forbidden_effects": ["submit_order", "promote_sleeve"]
            },
            "provider_fallbacks": {
              "market_news": {
                "active_source_names": ["google_news_rss", "reddit_watchlist"],
                "skipped_source_names": ["marketaux"],
                "limited_sources_active": [],
                "preferred_free_or_mcp_count": 2
              }
            },
            "watchlists": {
              "reddit": {"target_count": 90, "raw_comment_threads_by_default": false},
              "social": {"target_count": 100, "counts_by_platform": {"x": 13}}
            },
            "blocked_packets": []
          },
          "ranked_candidates": [{"symbol": "ORCL", "score": "0.91", "rating": "Buy"}],
          "ticker_results": [
            {"symbol": "ORCL", "status": "ok"},
            {"symbol": "MSFT", "status": "fallback"},
            {"symbol": "AMD", "status": "error"}
          ],
          "submitted": []
        }
        """,
        encoding="utf-8",
    )
    (tournament_dir / "latest.json").write_text(
        """
        {
          "generated_at": "2026-06-01T01:05:00+00:00",
          "kind": "paper_tournament_run",
          "submitted_count": 0,
          "report": {
            "rankings": [{"strategy_id": "current-aggressive", "equity": "10001.00"}],
            "live_strategy_candidate": {"status": "pending", "strategy_id": "current-aggressive"}
          }
        }
        """,
        encoding="utf-8",
    )

    packet = build_premarket_brief_packet(
        hourly_log_dir=hourly_dir,
        overnight_log_dir=overnight_dir,
        paper_tournament_log_dir=tournament_dir,
        generated_at=datetime.datetime(2026, 6, 1, 2, 0, tzinfo=datetime.timezone.utc),
    )
    packet_path = write_premarket_brief_packet(packet, output_dir=output_dir)
    loaded = load_latest_premarket_brief(output_dir)
    compact_path = packet_path.with_suffix(".compact.json")

    assert packet["analysis_only"] is True
    assert [item["kind"] for item in packet["source_packets"]] == [
        "overnight_plan",
        "hourly_supervisor",
        "paper_tournament",
    ]
    assert packet["timeline"][0]["generated_at"] == "2026-06-01T00:30:00+00:00"
    assert packet["timeline"][0]["fallback_count"] == 1
    assert packet["timeline"][0]["graph_failure_count"] == 1
    assert packet["timeline"][0]["failure_count"] == 1
    assert packet["timeline"][0]["research_context"]["packet_count"] == 8
    assert packet["timeline"][0]["research_context"]["prior_feed"]["schema"] == "overnight_prior_feed_v1"
    assert packet["timeline"][0]["research_context"]["prior_feed"]["execution_authority"] == "none"
    assert "submit_order" in packet["timeline"][0]["research_context"]["prior_feed"]["forbidden_effects"]
    assert packet["timeline"][0]["research_context"]["provider_fallback_needs"] == ["market_news"]
    assert packet["timeline"][0]["research_context"]["watchlists"] == ["reddit", "social"]
    assert packet["timeline"][0]["research_context"]["skipped_source_names"] == ["marketaux"]
    assert packet["premarket_instructions"]["latest_research_context"]["execution_authority"] == "none"
    assert packet["premarket_instructions"]["latest_research_context"]["prior_feed"]["path"].endswith(
        "overnight-prior-feed-20260601-003000.json"
    )
    assert packet["premarket_instructions"]["top_symbol"] == "ORCL"
    assert packet["material_changes"][0]["category"] == "initial_brief"
    assert packet_path.name.startswith("premarket-brief-20260601-020000")
    assert loaded["generated_at"] == "2026-06-01T02:00:00+00:00"
    assert loaded["packet_path"] == str(packet_path)
    assert (output_dir / "latest.md").exists()
    assert compact_path.exists()
    assert (output_dir / "latest-compact.json").exists()
    compact = json.loads(compact_path.read_text(encoding="utf-8"))
    latest_compact = json.loads((output_dir / "latest-compact.json").read_text(encoding="utf-8"))
    assert compact == latest_compact
    assert compact["schema"] == "compact_premarket_brief_v1"
    assert compact["raw_packet_path"] == str(packet_path)
    assert compact["counts"]["source_packets"] == 3
    assert compact["premarket_instructions"]["top_symbol"] == "ORCL"
    assert compact["premarket_instructions"]["summary"].startswith(
        "Use this rolling brief as context only"
    )
    assert compact["premarket_instructions"]["must_validate_fresh"] == [
        "premarket quotes and spreads",
        "overnight and morning news/social deltas",
        "open live and paper orders",
        "current positions and P/L",
        "live sizing room and buying power",
    ]


def test_premarket_brief_writer_can_skip_latest_compact_for_probe(tmp_path):
    packet = {
        "generated_at": "2026-06-01T02:00:00+00:00",
        "analysis_only": True,
        "source_packets": [],
        "timeline": [],
        "premarket_instructions": {"top_symbol": "ORCL"},
        "unresolved_blockers": [],
        "stale_warnings": [],
    }

    output_dir = tmp_path / "briefs"
    first_path = write_premarket_brief_packet(packet, output_dir=output_dir)
    first_latest_compact = (output_dir / "latest-compact.json").read_text(encoding="utf-8")
    probe_packet = {**packet, "premarket_instructions": {"top_symbol": "MSFT"}}
    probe_path = write_premarket_brief_packet(
        probe_packet,
        output_dir=output_dir,
        write_latest=False,
    )

    assert first_path.exists()
    assert probe_path.exists()
    assert probe_path.with_suffix(".compact.json").exists()
    assert json.loads(probe_path.with_suffix(".compact.json").read_text(encoding="utf-8"))[
        "premarket_instructions"
    ]["top_symbol"] == "MSFT"
    assert (output_dir / "latest-compact.json").read_text(encoding="utf-8") == first_latest_compact


def test_premarket_brief_enriches_prior_feed_pointer_from_feed_file(tmp_path):
    hourly_dir = tmp_path / "hourly"
    overnight_dir = tmp_path / "overnight"
    tournament_dir = tmp_path / "tournament"
    hourly_dir.mkdir()
    overnight_dir.mkdir()
    tournament_dir.mkdir()
    prior_feed_path = overnight_dir / "research_context" / "overnight-prior-feed-20260601-003000.json"
    prior_feed_path.parent.mkdir()
    prior_feed_path.write_text(
        json.dumps(
            {
                "schema": "overnight_prior_feed_v1",
                "analysis_only": True,
                "execution_authority": "none",
                "packet_count": 4,
                "blocked_count": 0,
                "prior_applied": True,
                "dedupe_applied": True,
                "input_packet_ref_count": 5,
                "unique_packet_ref_count": 4,
                "duplicate_packet_ref_count": 1,
                "carry_forward_scope": ["source_packet_refs", "provider_fallbacks"],
                "forbidden_effects": ["submit_order", "waive_live_gate"],
            }
        ),
        encoding="utf-8",
    )
    (overnight_dir / "overnight-plan-20260601-003000.json").write_text(
        json.dumps(
            {
                "generated_at": "2026-06-01T00:30:00+00:00",
                "analysis_only": True,
                "research_context": {
                    "analysis_only": True,
                    "packet_count": 4,
                    "execution_authority": "none",
                    "prior_feed": {
                        "schema": "overnight_prior_feed_v1",
                        "path": str(prior_feed_path),
                        "latest_path": str(prior_feed_path.parent / "overnight-prior-feed-latest.json"),
                        "packet_count": 4,
                        "blocked_count": 0,
                        "execution_authority": "none",
                    },
                },
                "ranked_candidates": [{"symbol": "TXN", "score": "0.91", "rating": "Buy"}],
                "ticker_results": [{"symbol": "TXN", "status": "ok"}],
                "submitted": [],
            }
        ),
        encoding="utf-8",
    )

    packet = build_premarket_brief_packet(
        hourly_log_dir=hourly_dir,
        overnight_log_dir=overnight_dir,
        paper_tournament_log_dir=tournament_dir,
        generated_at=datetime.datetime(2026, 6, 1, 2, 0, tzinfo=datetime.timezone.utc),
    )

    prior_feed = packet["premarket_instructions"]["latest_research_context"]["prior_feed"]
    assert prior_feed["analysis_only"] is True
    assert prior_feed["execution_authority"] == "none"
    assert prior_feed["prior_applied"] is True
    assert prior_feed["dedupe_applied"] is True
    assert prior_feed["input_packet_ref_count"] == 5
    assert prior_feed["unique_packet_ref_count"] == 4
    assert prior_feed["duplicate_packet_ref_count"] == 1
    assert prior_feed["carry_forward_scope"] == ["source_packet_refs", "provider_fallbacks"]
    assert "submit_order" in prior_feed["forbidden_effects"]


def test_premarket_brief_keeps_expected_live_lock_out_of_active_blockers(tmp_path):
    hourly_dir = tmp_path / "hourly"
    overnight_dir = tmp_path / "overnight"
    tournament_dir = tmp_path / "tournament"
    for path in (hourly_dir, overnight_dir, tournament_dir):
        path.mkdir()

    (overnight_dir / "overnight-plan-20260602-080000.json").write_text(
        """
        {
          "generated_at": "2026-06-02T08:00:00+00:00",
          "analysis_only": true,
          "overnight_quality": {"full_graph_count": 3, "fallback_count": 0, "graph_failure_count": 0},
          "ranked_candidates": [{"symbol": "NOW", "score": "0.91"}],
          "ticker_results": [{"symbol": "NOW", "status": "ok"}],
          "submitted": []
        }
        """,
        encoding="utf-8",
    )
    (hourly_dir / "hourly-supervisor-20260601-180000.json").write_text(
        """
        {
          "generated_at": "2026-06-01T18:00:00+00:00",
          "decision": "blocked",
          "reason": "hourly supervisor action failed guardrail validation",
          "material": true,
          "submitted": [],
          "issues": [{"ticket_id": "live-submit-guard", "reason": "risk envelope missing"}],
          "portfolio": {"live": {"open_orders": [], "positions": []}}
        }
        """,
        encoding="utf-8",
    )
    (hourly_dir / "hourly-supervisor-20260602-081000.json").write_text(
        """
        {
          "generated_at": "2026-06-02T08:10:00+00:00",
          "decision": "blocked",
          "reason": "hourly supervisor live submit failed guard validation",
          "material": true,
          "submitted": [],
          "issues": [
            {"ticket_id": "GOOGL", "reason": "risk envelope missing at config/risk_envelope.yaml"},
            {"ticket_id": "GOOGL", "reason": "promotion state missing at results/policy/promotion_state.json"},
            {"ticket_id": "GOOGL", "reason": "live control state missing at results/policy/live_control.json"},
            {"ticket_id": "GOOGL", "reason": "live action must use tiny_live execution_mode; got live_now"}
          ],
          "portfolio": {"live": {"open_orders": [], "positions": [{"symbol": "GOOGL"}]}}
        }
        """,
        encoding="utf-8",
    )
    (tournament_dir / "latest.json").write_text(
        '{"generated_at": "2026-06-02T08:11:00+00:00", "report": {"rankings": [{"strategy_id": "current-aggressive"}]}}',
        encoding="utf-8",
    )

    packet = build_premarket_brief_packet(
        hourly_log_dir=hourly_dir,
        overnight_log_dir=overnight_dir,
        paper_tournament_log_dir=tournament_dir,
        generated_at=datetime.datetime(2026, 6, 2, 8, 15, tzinfo=datetime.timezone.utc),
    )
    markdown = render_premarket_brief_markdown(packet)

    assert packet["unresolved_blockers"] == []
    assert len(packet["control_plane_locks"]) == 1
    assert packet["control_plane_locks"][0]["blocker_status"] == "expected_safety_lock"
    assert len(packet["historical_blockers"]) == 1
    assert packet["premarket_instructions"]["current_control_lock"].startswith(
        "Hourly supervisor blocked"
    )
    assert "## Safety Locks" in markdown
    assert "expected: no orders submitted" in markdown


def test_premarket_brief_validation_confirms_and_marks_stale():
    brief = {
        "generated_at": "2026-06-01T10:00:00+00:00",
        "premarket_instructions": {
            "top_symbol": "ORCL",
            "latest_research_context": {
                "packet_count": 8,
                "blocked_count": 0,
                "prior_feed": {
                    "schema": "overnight_prior_feed_v1",
                    "path": "results/overnight_plans/research_context/overnight-prior-feed-20260601-003000.json",
                    "packet_count": 8,
                    "blocked_count": 0,
                    "analysis_only": True,
                    "execution_authority": "none",
                    "forbidden_effects": ["submit_order"],
                },
                "provider_fallback_needs": ["market_news"],
                "watchlists": ["reddit"],
                "execution_authority": "none",
            },
        },
        "source_packets": [{"kind": "hourly_supervisor"}],
    }

    confirmed = validate_premarket_brief_against_candidates(
        brief,
        [CandidateSignal(symbol="ORCL", score=Decimal("0.90"), current_price=Decimal("225"))],
        now=datetime.datetime(2026, 6, 1, 12, 0, tzinfo=datetime.timezone.utc),
    )
    stale = validate_premarket_brief_against_candidates(
        brief,
        [CandidateSignal(symbol="ORCL", score=Decimal("0.90"), current_price=Decimal("225"))],
        now=datetime.datetime(2026, 6, 5, 12, 0, tzinfo=datetime.timezone.utc),
    )
    future = validate_premarket_brief_against_candidates(
        {
            "generated_at": "2026-06-01T14:00:00+00:00",
            "premarket_instructions": {"top_symbol": "ORCL"},
            "source_packets": [{"kind": "hourly_supervisor"}],
        },
        [CandidateSignal(symbol="ORCL", score=Decimal("0.90"), current_price=Decimal("225"))],
        now=datetime.datetime(2026, 6, 1, 12, 0, tzinfo=datetime.timezone.utc),
    )

    assert confirmed["status"] == "confirmed"
    assert confirmed["brief_top_symbol"] == "ORCL"
    assert confirmed["source_packet_count"] == 1
    assert confirmed["latest_research_context"]["prior_feed"]["schema"] == "overnight_prior_feed_v1"
    assert "submit_order" in confirmed["latest_research_context"]["prior_feed"]["forbidden_effects"]
    assert stale["status"] == "stale_or_missing"
    assert future["status"] == "stale_or_missing"
