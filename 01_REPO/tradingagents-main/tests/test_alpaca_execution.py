import datetime
import hashlib
import json
import threading
from decimal import Decimal
from pathlib import Path

import pytest

from tradingagents.brokers import alpaca as alpaca_module
from tradingagents.brokers.alpaca import (
    AlpacaExecutionConfig,
    AlpacaExecutionError,
    AlpacaModeError,
    AlpacaRestClient,
    AlpacaSettings,
    LiveExecutionPolicy,
    StrategyOrder,
    build_order_pairs,
    build_paper_orders,
    build_tiny_live_order_payload,
    classify_alpaca_submit_error,
    compare_alpaca_order_to_intent,
    execute_order_pairs,
    find_order_by_client_order_id,
    validate_live_entry_allowed,
    validate_live_management_action,
)
from tradingagents.execution.authorized_normal_trade_intent import AuthorizedNormalTradeIntent
from tradingagents.policy.promotion_sync import promotion_state_lock
from tradingagents.policy.strategy_promotion_sync import NormalLiveActivationReceipt
from tradingagents.schemas.trading import TradeIntent
from tradingagents.strategy._immutable_evidence_store import (
    NORMAL_LIVE_ACTIVATION_PREPARE_KIND,
    NORMAL_LIVE_ACTIVATION_RECEIPT_KIND,
    NORMAL_LIVE_BROKER_SUBMIT_PREPARE_KIND,
    EvidenceCandidate,
    ImmutableStrategyEvidenceStore,
)

_NORMAL_LIVE_TEST_NOW = datetime.datetime(
    2026, 7, 28, 12, 0, 1, tzinfo=datetime.timezone.utc
)


@pytest.fixture(autouse=True)
def _fixed_normal_live_utc_now(monkeypatch):
    """Keep fake broker-boundary tests on a deterministic private clock."""

    global _NORMAL_LIVE_TEST_NOW
    _NORMAL_LIVE_TEST_NOW = datetime.datetime(
        2026, 7, 28, 12, 0, 1, tzinfo=datetime.timezone.utc
    )
    monkeypatch.setattr(
        alpaca_module,
        "_normal_live_utc_now",
        lambda: _NORMAL_LIVE_TEST_NOW,
    )


def _strategy_order(
    ticket_id="googl-starter",
    symbol="GOOGL",
    notional="400",
    limit_price="383.50",
    extended_hours=True,
):
    return StrategyOrder(
        ticket_id=ticket_id,
        symbol=symbol,
        side="buy",
        notional=Decimal(notional),
        limit_price=Decimal(limit_price),
        extended_hours=extended_hours,
    )


def test_build_order_pairs_applies_10_percent_live_notional():
    config = AlpacaExecutionConfig()

    result = build_order_pairs(
        [_strategy_order(notional="400")],
        config=config,
        run_id="20260526-preopen",
    )

    assert len(result.accepted) == 1
    pair = result.accepted[0]
    assert pair.paper.order["notional"] == "400.00"
    assert pair.live.order["notional"] == "40.00"
    assert pair.paper.order["client_order_id"] == "ta-20260526-preopen-paper-googl-starter"
    assert pair.live.order["client_order_id"] == "ta-20260526-preopen-live-googl-starter"
    assert pair.live.parent_client_order_id == pair.paper.order["client_order_id"]


def test_build_order_pairs_rejects_orders_over_paper_exposure_cap():
    config = AlpacaExecutionConfig(paper_exposure_limit=Decimal("1000"))

    result = build_order_pairs(
        [_strategy_order(ticket_id="too-big", notional="1000.01")],
        config=config,
        run_id="20260526-preopen",
    )

    assert result.accepted == []
    assert result.rejected[0].ticket_id == "too-big"
    assert "paper exposure limit" in result.rejected[0].reason


def test_build_order_pairs_does_not_apply_old_live_exposure_cap():
    config = AlpacaExecutionConfig(
        paper_exposure_limit=Decimal("1000"),
        live_exposure_limit=Decimal("100"),
        live_mirror_ratio=Decimal("0.10"),
    )

    result = build_order_pairs(
        [_strategy_order(ticket_id="live-too-big", notional="100")],
        config=config,
        run_id="20260526-preopen",
        existing_live_exposure=Decimal("95"),
    )

    assert len(result.accepted) == 1
    assert result.rejected == []
    assert result.accepted[0].live.order["notional"] == "10.00"


def test_build_order_pairs_skips_duplicate_open_order_ids():
    config = AlpacaExecutionConfig()

    result = build_order_pairs(
        [_strategy_order(ticket_id="googl-starter")],
        config=config,
        run_id="20260526-preopen",
        existing_open_client_order_ids={"ta-20260526-preopen-paper-googl-starter"},
    )

    assert result.accepted == []
    assert result.skipped[0].ticket_id == "googl-starter"
    assert "duplicate open order" in result.skipped[0].reason


def test_live_entry_policy_allows_only_tuesday_strategy_window():
    policy = LiveExecutionPolicy(
        allowed_live_run_id="20260526-tuesday",
        live_entry_starts_at=datetime.datetime(
            2026, 5, 26, 8, 45, tzinfo=datetime.timezone.utc
        ),
        live_entry_ends_at=datetime.datetime(
            2026, 5, 26, 10, 30, tzinfo=datetime.timezone.utc
        ),
        live_management_ends_at=datetime.datetime(
            2026, 5, 29, 20, 0, tzinfo=datetime.timezone.utc
        ),
    )

    allowed = validate_live_entry_allowed(
        run_id="20260526-tuesday",
        now=datetime.datetime(2026, 5, 26, 9, 5, tzinfo=datetime.timezone.utc),
        policy=policy,
    )
    after_window = validate_live_entry_allowed(
        run_id="20260526-tuesday",
        now=datetime.datetime(2026, 5, 26, 11, 0, tzinfo=datetime.timezone.utc),
        policy=policy,
    )
    wrong_run = validate_live_entry_allowed(
        run_id="20260527-paper",
        now=datetime.datetime(2026, 5, 26, 9, 5, tzinfo=datetime.timezone.utc),
        policy=policy,
    )

    assert allowed == []
    assert "live entry window is closed" in after_window[0].reason
    assert "not the approved one-time live run" in wrong_run[0].reason


def test_live_management_policy_only_allows_tuesday_live_order_ids_through_friday():
    policy = LiveExecutionPolicy(allowed_live_run_id="20260526-tuesday")

    allowed = validate_live_management_action(
        client_order_id="ta-20260526-tuesday-live-googl-starter",
        action="close",
        now=datetime.datetime(2026, 5, 28, 15, 0, tzinfo=datetime.timezone.utc),
        policy=policy,
    )
    wrong_order = validate_live_management_action(
        client_order_id="ta-20260527-paper-live-msft-third",
        action="close",
        now=datetime.datetime(2026, 5, 28, 15, 0, tzinfo=datetime.timezone.utc),
        policy=policy,
    )
    new_buy = validate_live_management_action(
        client_order_id="ta-20260526-tuesday-live-googl-starter",
        action="buy",
        now=datetime.datetime(2026, 5, 28, 15, 0, tzinfo=datetime.timezone.utc),
        policy=policy,
    )

    assert allowed is None
    assert "not tied to the approved Tuesday live run" in wrong_order.reason
    assert "not a live management action" in new_buy.reason


def test_build_paper_orders_never_builds_live_child_orders():
    config = AlpacaExecutionConfig(paper_exposure_limit=Decimal("1000"))

    result = build_paper_orders(
        [_strategy_order(ticket_id="paper-only", notional="300")],
        config=config,
        run_id="20260527-paper",
    )

    assert len(result.accepted) == 1
    assert result.accepted[0].order["client_order_id"] == "ta-20260527-paper-paper-paper-only"
    assert result.accepted[0].order["notional"] == "300.00"


def test_alpaca_rest_client_rejects_paper_mode_on_live_base_url():
    settings = AlpacaSettings(
        api_key="key",
        secret_key="secret",
        paper=True,
        base_url="https://api.alpaca.markets",
    )
    client = AlpacaRestClient(settings=settings)

    with pytest.raises(AlpacaModeError):
        client.assert_expected_mode(paper=True)


def test_alpaca_settings_reads_user_endpoint_env_names():
    settings = AlpacaSettings.from_env(
        paper=True,
        environ={
            "ALPACA_PAPER_API_KEY": "paper-key",
            "ALPACA_PAPER_SECRET_KEY": "paper-secret",
            "ALPACA_PAPER_API_ENDPOINT": "https://paper-api.alpaca.markets/custom",
        },
    )

    assert settings.base_url == "https://paper-api.alpaca.markets/custom"


def test_alpaca_settings_strips_trailing_v2_from_endpoint():
    settings = AlpacaSettings.from_env(
        paper=True,
        environ={
            "ALPACA_PAPER_API_KEY": "paper-key",
            "ALPACA_PAPER_SECRET_KEY": "paper-secret",
            "ALPACA_PAPER_API_ENDPOINT": "https://paper-api.alpaca.markets/v2",
        },
    )

    assert settings.base_url == "https://paper-api.alpaca.markets"


def test_alpaca_settings_falls_back_to_windows_user_env(monkeypatch):
    values = {
        "ALPACA_PAPER_API_KEY": "paper-key",
        "ALPACA_PAPER_SECRET_KEY": "paper-secret",
        "ALPACA_PAPER_API_ENDPOINT": "https://paper-api.alpaca.markets/custom",
    }
    monkeypatch.setattr(alpaca_module, "_read_windows_user_env", values.get)

    settings = AlpacaSettings.from_env(paper=True, environ={})

    assert settings.api_key == "paper-key"
    assert settings.secret_key == "paper-secret"
    assert settings.base_url == "https://paper-api.alpaca.markets/custom"


def test_alpaca_execution_config_falls_back_to_windows_user_env(monkeypatch):
    values = {
        "TRADINGAGENTS_ALPACA_PAPER_ENABLED": "true",
        "TRADINGAGENTS_ALPACA_LIVE_MIRROR_ENABLED": "true",
        "TRADINGAGENTS_PAPER_EXPOSURE_LIMIT": "1000",
        "TRADINGAGENTS_LIVE_MIRROR_RATIO": "0.10",
        "TRADINGAGENTS_LIVE_EXPOSURE_LIMIT": "100",
    }
    monkeypatch.setattr(alpaca_module, "_read_windows_user_env", values.get)

    config = AlpacaExecutionConfig.from_env(environ={})

    assert config.paper_enabled is True
    assert config.live_mirror_enabled is True
    assert config.paper_exposure_limit == Decimal("1000")
    assert config.live_mirror_ratio == Decimal("0.10")
    assert config.live_exposure_limit == Decimal("100")


class _FakeClient:
    def __init__(self, paper):
        self.paper = paper
        self.submitted = []

    def assert_expected_mode(self, paper):
        assert self.paper is paper

    def submit_order(self, order):
        self.submitted.append(order)
        return {"id": f"{'paper' if self.paper else 'live'}-order", **order}


def test_execute_order_pairs_is_hard_disabled_even_with_legacy_approval():
    config = AlpacaExecutionConfig()
    pairs = build_order_pairs(
        [_strategy_order(ticket_id="googl-starter", notional="400")],
        config=config,
        run_id="20260526-preopen",
    ).accepted
    paper_client = _FakeClient(paper=True)
    live_client = _FakeClient(paper=False)

    report = execute_order_pairs(
        pairs,
        paper_client=paper_client,
        live_client=live_client,
        live_guard_approved=True,
    )

    assert paper_client.submitted == []
    assert live_client.submitted == []
    assert report.submitted == []
    assert len(report.failed) == 1
    assert "permanently disabled" in report.failed[0].reason


def _normal_live_intent() -> AuthorizedNormalTradeIntent:
    digests = {
        name: hashlib.sha256(name.encode("utf-8")).hexdigest()
        for name in (
            "promotion_proposal",
            "promotion_state",
            "promotion_sync_receipt",
            "staged_intent",
            "shadow_attestation",
            "genome",
            "runtime",
            "observation",
            "portfolio",
            "risk",
        )
    }
    payload = {
        "promotion_proposal_id": "proposal-" + digests["promotion_proposal"],
        "promotion_proposal_sha256": digests["promotion_proposal"],
        "promotion_state_sha256": digests["promotion_state"],
        "promotion_sync_receipt_id": "receipt-" + digests["promotion_sync_receipt"],
        "promotion_sync_receipt_sha256": digests["promotion_sync_receipt"],
        "staged_intent_id": "staged-" + digests["staged_intent"],
        "staged_intent_sha256": digests["staged_intent"],
        "shadow_attestation_sha256": digests["shadow_attestation"],
        "genome_id": "genome-" + digests["genome"],
        "genome_canonical_sha256": digests["genome"],
        "evaluation_code_commit": "a" * 40,
        "evaluation_runtime_sha256": digests["runtime"],
        "market_observation_sha256": digests["observation"],
        "portfolio_snapshot_sha256": digests["portfolio"],
        "risk_snapshot_sha256": digests["risk"],
        "symbol": "MSFT",
        "side": "buy",
        "order_type": "limit",
        "tif": "day",
        "notional_usd": "25.00",
        "limit_price": "100.00",
        "effective_at": "2026-07-28T12:00:00+00:00",
        "expires_at": "2026-07-28T12:15:00+00:00",
        "recorded_at": "2026-07-28T12:00:00+00:00",
    }
    logical_material = dict(payload)
    logical = hashlib.sha256(
        json.dumps(logical_material, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    payload["logical_order_sha256"] = logical
    payload["client_order_id"] = f"ta-l-{logical[:40]}"
    authorization_material = {
        **payload,
        "owner_role": "portfolio_executive",
        "authorization_scope": "single_alpaca_live_order",
        "live_submit_authorized": True,
        "paper_submit_authorized": False,
    }
    authorization_material["authorization_id"] = "authorized-normal-trade-intent-" + hashlib.sha256(
        json.dumps(authorization_material, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return AuthorizedNormalTradeIntent.from_dict(authorization_material)


def _bound_normal_live_order(intent: AuthorizedNormalTradeIntent) -> dict[str, object]:
    return {
        "symbol": intent.symbol,
        "side": intent.side,
        "type": intent.order_type,
        "time_in_force": intent.tif,
        "notional": intent.notional_usd,
        "limit_price": intent.limit_price,
        "client_order_id": intent.client_order_id,
    }


def _activation_receipt(
    intent: AuthorizedNormalTradeIntent, state: dict[str, object] | None = None
) -> NormalLiveActivationReceipt:
    state = state or {"sleeves": {"normal": {"live_enabled": True}}}
    state_bytes = json.dumps(
        state, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return NormalLiveActivationReceipt(
        activation_prepare_id="normal_live_activation_prepare-" + "a" * 64,
        activation_receipt_id="normal_live_activation_receipt-" + "b" * 64,
        intent_full_sha256=hashlib.sha256(intent.canonical_json_bytes()).hexdigest(),
        canonical_before_sha256=intent.promotion_state_sha256,
        canonical_after_sha256=hashlib.sha256(state_bytes).hexdigest(),
        state=state,
        created=True,
        status="activated",
    )


def _manually_admitted_activation_receipt(
    evidence_root,
    intent: AuthorizedNormalTradeIntent,
    *,
    state_path,
    sleeve="normal",
) -> NormalLiveActivationReceipt:
    state = {
        "sleeves": {
            sleeve: {"stage": "tiny_live_eligible", "live_enabled": True}
        }
    }
    state_bytes = json.dumps(
        state, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    state_path.write_bytes(state_bytes)
    after_sha256 = hashlib.sha256(state_bytes).hexdigest()
    intent_full_sha256 = hashlib.sha256(intent.canonical_json_bytes()).hexdigest()
    store = ImmutableStrategyEvidenceStore(
        evidence_root,
        clock=lambda: datetime.datetime(2026, 7, 28, 12, 0, tzinfo=datetime.timezone.utc),
    )
    prepare_payload = {
        "schema_version": 1,
        "intent_full_sha256": intent_full_sha256,
        "logical_order_sha256": intent.logical_order_sha256,
        "proposal_id": intent.promotion_proposal_id,
        "proposal_sha256": intent.promotion_proposal_sha256,
        "promotion_sync_receipt_id": intent.promotion_sync_receipt_id,
        "promotion_sync_receipt_sha256": intent.promotion_sync_receipt_sha256,
        "risk_snapshot_sha256": intent.risk_snapshot_sha256,
        "risk_envelope_sha256": intent.risk_snapshot_sha256,
        "evaluation_runtime_sha256": intent.evaluation_runtime_sha256,
        "promotion_runtime_commit": intent.evaluation_code_commit,
        "canonical_before_sha256": intent.promotion_state_sha256,
        "canonical_after_sha256": after_sha256,
        "activation_state_marker": "c" * 64,
        "state_path": str(state_path),
        "promoted": [sleeve],
        "demoted": [],
        "unchanged": [],
        "live_enabled": True,
    }
    prepare = store.admit_checked(
        EvidenceCandidate(
            kind=NORMAL_LIVE_ACTIVATION_PREPARE_KIND,
            effective_at="2026-07-28T12:00:00+00:00",
            payload=prepare_payload,
        ),
        validate=lambda _snapshot, _envelope: None,
    ).envelope
    receipt = store.admit_checked(
        EvidenceCandidate(
            kind=NORMAL_LIVE_ACTIVATION_RECEIPT_KIND,
            effective_at="2026-07-28T12:00:00+00:00",
            payload={
                **prepare_payload,
                "activation_prepare_id": prepare.object_id,
                "activation_prepare_sha256": hashlib.sha256(
                    prepare.canonical_json_bytes()
                ).hexdigest(),
            },
        ),
        validate=lambda _snapshot, _envelope: None,
    ).envelope
    return NormalLiveActivationReceipt(
        activation_prepare_id=prepare.object_id,
        activation_receipt_id=receipt.object_id,
        intent_full_sha256=intent_full_sha256,
        canonical_before_sha256=intent.promotion_state_sha256,
        canonical_after_sha256=after_sha256,
        state=state,
        created=True,
        status="activated",
    )


class _FakeResponse:
    def __init__(self, status_code: int, payload: object):
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


class _FakeLiveSession:
    def __init__(self, *, fail_post=False):
        self.requests = []
        self.existing = {}
        self.post_calls = 0
        self.fail_post = fail_post

    def add_existing_order(self, order: dict[str, object]) -> None:
        self.existing[str(order["client_order_id"])] = dict(order)

    def request(self, method, url, **kwargs):
        self.requests.append((method, url, kwargs))
        if method == "GET":
            client_order_id = kwargs["params"]["client_order_id"]
            existing = self.existing.get(client_order_id)
            return _FakeResponse(200, existing) if existing else _FakeResponse(404, {"message": "not found"})
        if method == "POST":
            self.post_calls += 1
            if self.fail_post:
                return _FakeResponse(500, {"message": "interrupted"})
            order = dict(kwargs["json"])
            self.existing[str(order["client_order_id"])] = order
            return _FakeResponse(200, order)
        raise AssertionError(f"unexpected method: {method}")


def _fake_live_client(
    evidence_root=None, *, repo_root=None, session=None, clock=None
) -> AlpacaRestClient:
    if clock is not None:
        global _NORMAL_LIVE_TEST_NOW
        _NORMAL_LIVE_TEST_NOW = clock()
    return AlpacaRestClient(
        settings=AlpacaSettings(
            api_key="test-key",
            secret_key="test-secret",
            paper=False,
            base_url="https://api.alpaca.markets",
        ),
        session=session or _FakeLiveSession(),
        normal_live_evidence_root=evidence_root,
        normal_live_repo_root=repo_root,
    )


def _real_normal_live_activation(tmp_path, monkeypatch):
    import tradingagents.strategy.promotion_evidence as promotion_evidence_module
    from tests.test_strategy_promotion_sync import (
        _capped_activation_journal,
        _sync_capped_activation_state,
    )
    from tradingagents.policy.strategy_promotion_sync import activate_normal_live_intent

    # The production runtime deliberately binds calculation modules to the
    # checkout that imported them. This fixture uses Task 3's disposable
    # committed checkout, so preserve that fixture's existing source bytes
    # while letting its runtime registration be constructed in-process.
    monkeypatch.setattr(
        promotion_evidence_module,
        "_require_loaded_source_binding",
        lambda *_args, **_kwargs: None,
    )
    root, repo_root, proposal, activated_at, _commit = _capped_activation_journal(
        tmp_path, monkeypatch
    )
    state = tmp_path / "real-promotion-state.json"
    intent = _sync_capped_activation_state(
        root=root,
        repo_root=repo_root,
        proposal=proposal,
        state=state,
        synced_at=activated_at,
    )
    receipt = activate_normal_live_intent(
        proposal,
        intent,
        proposal_ledger_root=root,
        repo_root=repo_root,
        state_path=state,
        clock=lambda: activated_at,
    )
    return root, repo_root, intent, receipt, activated_at


def _activation_state_path(root, receipt: NormalLiveActivationReceipt) -> Path:
    envelope = next(
        item
        for item in ImmutableStrategyEvidenceStore(root).envelopes(
            kind=NORMAL_LIVE_ACTIVATION_RECEIPT_KIND
        )
        if item.object_id == receipt.activation_receipt_id
    )
    return Path(str(envelope.payload["state_path"]))


def _reconstructed_activation_receipt(
    receipt: NormalLiveActivationReceipt,
) -> NormalLiveActivationReceipt:
    """Build the kind of value a fresh process could reconstruct from disk."""

    return NormalLiveActivationReceipt(
        activation_prepare_id=receipt.activation_prepare_id,
        activation_receipt_id=receipt.activation_receipt_id,
        intent_full_sha256=receipt.intent_full_sha256,
        canonical_before_sha256=receipt.canonical_before_sha256,
        canonical_after_sha256=receipt.canonical_after_sha256,
        state=dict(receipt.state),
        created=receipt.created,
        status=receipt.status,
    )


def test_live_client_does_not_expose_a_caller_controlled_clock():
    with pytest.raises(TypeError, match="normal_live_clock"):
        AlpacaRestClient(
            settings=AlpacaSettings(
                api_key="test-key",
                secret_key="test-secret",
                paper=False,
                base_url="https://api.alpaca.markets",
            ),
            normal_live_clock=lambda: datetime.datetime(
                2026, 7, 28, 12, 0, tzinfo=datetime.timezone.utc
            ),
        )


def test_manual_self_consistent_receipt_cannot_create_first_live_post(
    tmp_path, monkeypatch
):
    root, repo_root, intent, receipt, activated_at = _real_normal_live_activation(
        tmp_path, monkeypatch
    )
    client = _fake_live_client(root, repo_root=repo_root, clock=lambda: activated_at)

    with pytest.raises(ValueError, match="in-process Task 3 issuance capability"):
        client.submit_order(
            _bound_normal_live_order(intent),
            authorized_normal_trade_intent=intent,
            activation_receipt=_reconstructed_activation_receipt(receipt),
        )

    assert client.session.requests == []
    assert client.session.post_calls == 0


def test_live_client_rejects_mapping_without_intent_before_request():
    client = _fake_live_client()

    with pytest.raises(ValueError, match="AuthorizedNormalTradeIntent"):
        client.submit_order(_bound_normal_live_order(_normal_live_intent()))

    assert client.session.requests == []


def test_live_client_rejects_manually_admitted_activation_envelopes_before_request(tmp_path):
    intent = _normal_live_intent()
    client = _fake_live_client(tmp_path, repo_root=tmp_path)

    with pytest.raises(ValueError, match="Task 3 state marker"):
        client.submit_order(
            _bound_normal_live_order(intent),
            authorized_normal_trade_intent=intent,
            activation_receipt=_manually_admitted_activation_receipt(
                tmp_path,
                intent,
                state_path=tmp_path / "absolute-promotion-state.json",
            ),
        )

    assert client.session.requests == []


def test_live_client_accepts_real_activation_and_lookup_is_read_only(tmp_path, monkeypatch):
    root, repo_root, intent, receipt, activated_at = _real_normal_live_activation(
        tmp_path, monkeypatch
    )
    client = _fake_live_client(root, repo_root=repo_root, clock=lambda: activated_at)
    order = _bound_normal_live_order(intent)
    client.session.add_existing_order(order)

    response = client.submit_order(
        order,
        authorized_normal_trade_intent=intent,
        activation_receipt=receipt,
    )

    assert response["client_order_id"] == intent.client_order_id
    assert client.session.post_calls == 0
    assert [request[0] for request in client.session.requests] == ["GET"]


def test_live_client_rejects_expired_intent_from_its_trusted_clock_before_request(
    tmp_path, monkeypatch
):
    root, repo_root, intent, receipt, activated_at = _real_normal_live_activation(
        tmp_path, monkeypatch
    )
    expired_at = activated_at + datetime.timedelta(minutes=6)
    monkeypatch.setattr(alpaca_module, "_normal_live_utc_now", lambda: expired_at)
    client = _fake_live_client(root, repo_root=repo_root)

    with pytest.raises(ValueError, match="inactive|not active"):
        client.submit_order(
            _bound_normal_live_order(intent),
            authorized_normal_trade_intent=intent,
            activation_receipt=receipt,
        )

    assert client.session.requests == []
    with pytest.raises(TypeError, match="unexpected keyword argument 'now'"):
        client.submit_order(
            _bound_normal_live_order(intent),
            authorized_normal_trade_intent=intent,
            activation_receipt=receipt,
            now=activated_at,
        )
    assert client.session.requests == []


def test_task3_admission_holds_state_lock_until_durable_prepare(tmp_path, monkeypatch):
    root, repo_root, intent, receipt, activated_at = _real_normal_live_activation(
        tmp_path, monkeypatch
    )
    state_path = _activation_state_path(root, receipt)
    session = _FakeLiveSession()
    session.add_existing_order(_bound_normal_live_order(intent))
    client = _fake_live_client(
        root, repo_root=repo_root, session=session, clock=lambda: activated_at
    )
    original_admit = ImmutableStrategyEvidenceStore.admit_checked
    attempted_demotion = threading.Event()
    completed_demotion = threading.Event()
    worker: list[threading.Thread] = []

    def demote_after_handoff():
            attempted_demotion.set()
            with promotion_state_lock(state_path):
                state = json.loads(state_path.read_text(encoding="utf-8"))
                sleeve = state["normal_live_activation"]["sleeve"]
                state["sleeves"][sleeve]["live_enabled"] = False
            state_path.write_text(
                json.dumps(state, sort_keys=True, separators=(",", ":")),
                encoding="utf-8",
            )
            completed_demotion.set()

    def intercept_admission(self, candidate, *, validate):
        if candidate.kind == NORMAL_LIVE_BROKER_SUBMIT_PREPARE_KIND:
            thread = threading.Thread(target=demote_after_handoff)
            worker.append(thread)
            thread.start()
            assert attempted_demotion.wait(timeout=1)
            assert not completed_demotion.wait(timeout=0.05)
        return original_admit(self, candidate, validate=validate)

    monkeypatch.setattr(ImmutableStrategyEvidenceStore, "admit_checked", intercept_admission)
    response = client.submit_order(
        _bound_normal_live_order(intent),
        authorized_normal_trade_intent=intent,
        activation_receipt=receipt,
    )
    worker[0].join(timeout=1)

    assert response["client_order_id"] == intent.client_order_id
    assert completed_demotion.is_set()
    assert [request[0] for request in session.requests] == ["GET"]
    assert len(
        ImmutableStrategyEvidenceStore(root).envelopes(
            kind=NORMAL_LIVE_BROKER_SUBMIT_PREPARE_KIND
        )
    ) == 1


def test_demotion_cannot_complete_before_the_first_live_post(tmp_path, monkeypatch):
    root, repo_root, intent, receipt, activated_at = _real_normal_live_activation(
        tmp_path, monkeypatch
    )
    state_path = _activation_state_path(root, receipt)
    attempted_demotion = threading.Event()
    completed_demotion = threading.Event()
    worker: list[threading.Thread] = []

    def demote_under_the_policy_lock():
        attempted_demotion.set()
        with promotion_state_lock(state_path):
            state = json.loads(state_path.read_text(encoding="utf-8"))
            sleeve = state["normal_live_activation"]["sleeve"]
            state["sleeves"][sleeve]["live_enabled"] = False
            state_path.write_text(
                json.dumps(state, sort_keys=True, separators=(",", ":")),
                encoding="utf-8",
            )
        completed_demotion.set()

    class InterleavingSession(_FakeLiveSession):
        def request(self, method, url, **kwargs):
            if method == "POST":
                thread = threading.Thread(target=demote_under_the_policy_lock)
                worker.append(thread)
                thread.start()
                assert attempted_demotion.wait(timeout=1)
                assert not completed_demotion.wait(timeout=0.05)
            return super().request(method, url, **kwargs)

    session = InterleavingSession()
    client = _fake_live_client(
        root, repo_root=repo_root, session=session, clock=lambda: activated_at
    )

    response = client.submit_order(
        _bound_normal_live_order(intent),
        authorized_normal_trade_intent=intent,
        activation_receipt=receipt,
    )
    worker[0].join(timeout=1)

    assert response["client_order_id"] == intent.client_order_id
    assert session.post_calls == 1
    assert completed_demotion.is_set()
    final_state = json.loads(state_path.read_text(encoding="utf-8"))
    sleeve = final_state["normal_live_activation"]["sleeve"]
    assert final_state["sleeves"][sleeve]["live_enabled"] is False


def test_live_client_blocks_mismatched_real_retry_lookup_without_post(tmp_path, monkeypatch):
    root, repo_root, intent, receipt, activated_at = _real_normal_live_activation(
        tmp_path, monkeypatch
    )
    client = _fake_live_client(root, repo_root=repo_root, clock=lambda: activated_at)
    order = _bound_normal_live_order(intent)
    client.session.add_existing_order({**order, "symbol": "AAPL"})

    with pytest.raises(ValueError, match="does not match authorized intent"):
        client.submit_order(
            order,
            authorized_normal_trade_intent=intent,
            activation_receipt=receipt,
        )

    assert client.session.post_calls == 0


def test_live_client_rejects_untyped_receipt_before_request():
    client = _fake_live_client()
    intent = _normal_live_intent()

    with pytest.raises(ValueError, match="NormalLiveActivationReceipt"):
        client.submit_order(
            _bound_normal_live_order(intent),
            authorized_normal_trade_intent=intent,
            activation_receipt={"intent_full_sha256": hashlib.sha256(intent.canonical_json_bytes()).hexdigest()},
        )

    assert client.session.requests == []


def test_live_client_rejects_forged_direct_receipt_before_broker_request(tmp_path):
    client = _fake_live_client(tmp_path, repo_root=tmp_path)
    intent = _normal_live_intent()

    with pytest.raises(ValueError, match="activation receipt evidence is unavailable"):
        client.submit_order(
            _bound_normal_live_order(intent),
            authorized_normal_trade_intent=intent,
            activation_receipt=_activation_receipt(intent),
        )

    assert client.session.requests == []


def test_fresh_live_client_after_uncertain_post_only_performs_lookup(tmp_path, monkeypatch):
    root, repo_root, intent, receipt, activated_at = _real_normal_live_activation(
        tmp_path, monkeypatch
    )
    failed_session = _FakeLiveSession(fail_post=True)
    initial = _fake_live_client(
        root, repo_root=repo_root, session=failed_session, clock=lambda: activated_at
    )
    order = _bound_normal_live_order(intent)
    kwargs = {
        "authorized_normal_trade_intent": intent,
        "activation_receipt": receipt,
    }

    with pytest.raises(AlpacaExecutionError):
        initial.submit_order(order, **kwargs)
    assert len(
        ImmutableStrategyEvidenceStore(root).envelopes(
            kind=NORMAL_LIVE_BROKER_SUBMIT_PREPARE_KIND
        )
    ) == 1
    retry_session = _FakeLiveSession()
    retry = _fake_live_client(
        root, repo_root=repo_root, session=retry_session, clock=lambda: activated_at
    )
    with pytest.raises(ValueError, match="retry lookup found no order"):
        retry.submit_order(
            order,
            authorized_normal_trade_intent=intent,
            activation_receipt=_reconstructed_activation_receipt(receipt),
        )

    assert failed_session.post_calls == 1
    assert retry_session.post_calls == 0
    assert [request[0] for request in retry_session.requests] == ["GET"]


def test_live_client_rejects_different_receipt_for_consumed_logical_order_before_lookup(
    tmp_path, monkeypatch
):
    root, repo_root, intent, receipt, activated_at = _real_normal_live_activation(
        tmp_path, monkeypatch
    )
    order = _bound_normal_live_order(intent)
    immutable_facts = alpaca_module._normal_live_order_facts(order)
    facts_bytes = json.dumps(
        immutable_facts, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    conflicting_payload = {
        "schema_version": 1,
        "intent_full_sha256": hashlib.sha256(intent.canonical_json_bytes()).hexdigest(),
        "logical_order_sha256": intent.logical_order_sha256,
        "client_order_id": intent.client_order_id,
        "activation_prepare_id": receipt.activation_prepare_id,
        "activation_receipt_id": receipt.activation_receipt_id,
        "immutable_order_sha256": hashlib.sha256(facts_bytes).hexdigest(),
        "canonical_state_sha256": receipt.canonical_after_sha256,
        "activation_state_marker": receipt.state["normal_live_activation"]["marker"],
    }
    conflicting_payload["activation_receipt_id"] = (
        "normal-live-activation-receipt-" + "0" * 64
    )
    ImmutableStrategyEvidenceStore(root, clock=lambda: activated_at).admit_checked(
        EvidenceCandidate(
            kind=NORMAL_LIVE_BROKER_SUBMIT_PREPARE_KIND,
            effective_at=intent.recorded_at,
            payload=conflicting_payload,
        ),
        validate=lambda _snapshot, _envelope: None,
    )
    client = _fake_live_client(root, repo_root=repo_root, clock=lambda: activated_at)

    with pytest.raises(ValueError, match="logical/client order ID"):
        client.submit_order(
            order,
            authorized_normal_trade_intent=intent,
            activation_receipt=receipt,
        )

    assert client.session.requests == []
    assert client.session.post_calls == 0


def test_execute_order_pairs_is_disabled_without_legacy_approval():
    config = AlpacaExecutionConfig()
    pairs = build_order_pairs(
        [_strategy_order(ticket_id="googl-starter", notional="400")],
        config=config,
        run_id="20260526-preopen",
    ).accepted
    paper_client = _FakeClient(paper=True)
    live_client = _FakeClient(paper=False)

    report = execute_order_pairs(
        pairs,
        paper_client=paper_client,
        live_client=live_client,
    )

    assert paper_client.submitted == []
    assert live_client.submitted == []
    assert report.submitted == []
    assert len(report.failed) == 1
    assert "permanently disabled" in report.failed[0].reason


def test_execute_order_pairs_disables_live_sell_before_either_leg_submits():
    config = AlpacaExecutionConfig()
    pairs = build_order_pairs(
        [_strategy_order(ticket_id="googl-exit", notional="400")],
        config=config,
        run_id="20260526-preopen",
    ).accepted
    pairs[0].live.order["side"] = "sell"
    paper_client = _FakeClient(paper=True)
    live_client = _FakeClient(paper=False)

    report = execute_order_pairs(
        pairs,
        paper_client=paper_client,
        live_client=live_client,
        live_guard_approved=True,
    )

    assert paper_client.submitted == []
    assert live_client.submitted == []
    assert report.submitted == []
    assert len(report.failed) == 1
    assert "permanently disabled" in report.failed[0].reason


class _CancelTrackingPaperClient(_FakeClient):
    def __init__(self):
        super().__init__(paper=True)
        self.canceled = []

    def cancel_order(self, order_id):
        self.canceled.append(order_id)


class _FailingLiveClient(_FakeClient):
    def __init__(self):
        super().__init__(paper=False)

    def submit_order(self, order):
        raise RuntimeError("insufficient buying power")


def test_execute_order_pairs_does_not_submit_or_roll_back_when_live_would_fail():
    config = AlpacaExecutionConfig()
    pairs = build_order_pairs(
        [_strategy_order(ticket_id="googl-starter", notional="400")],
        config=config,
        run_id="20260526-preopen",
    ).accepted
    paper_client = _CancelTrackingPaperClient()
    live_client = _FailingLiveClient()

    report = execute_order_pairs(
        pairs,
        paper_client=paper_client,
        live_client=live_client,
        live_guard_approved=True,
    )

    assert paper_client.submitted == []
    assert report.submitted == []
    assert len(report.failed) == 1
    assert "permanently disabled" in report.failed[0].reason
    assert paper_client.canceled == []


def test_execute_order_pairs_does_not_submit_paper_without_rollback_capability():
    config = AlpacaExecutionConfig()
    pairs = build_order_pairs(
        [_strategy_order(ticket_id="googl-starter", notional="400")],
        config=config,
        run_id="20260526-preopen",
    ).accepted
    paper_client = _FakeClient(paper=True)  # no cancel_order method
    live_client = _FailingLiveClient()

    report = execute_order_pairs(
        pairs,
        paper_client=paper_client,
        live_client=live_client,
        live_guard_approved=True,
    )

    assert paper_client.submitted == []
    assert report.submitted == []
    assert len(report.failed) == 1
    assert "permanently disabled" in report.failed[0].reason


def test_execute_order_pairs_never_invokes_paper_failure_path():
    config = AlpacaExecutionConfig()
    pairs = build_order_pairs(
        [_strategy_order(ticket_id="googl-starter", notional="400")],
        config=config,
        run_id="20260526-preopen",
    ).accepted

    class _FailingPaperClient(_FakeClient):
        def __init__(self):
            super().__init__(paper=True)

        def submit_order(self, order):
            raise RuntimeError("paper venue rejected order")

    paper_client = _FailingPaperClient()
    live_client = _FakeClient(paper=False)

    report = execute_order_pairs(
        pairs,
        paper_client=paper_client,
        live_client=live_client,
        live_guard_approved=True,
    )

    assert live_client.submitted == []
    assert report.submitted == []
    assert len(report.failed) == 1
    assert "permanently disabled" in report.failed[0].reason


def test_tiny_live_payload_uses_intent_idempotency_key():
    intent = TradeIntent(
        idempotency_key="tiny-live-msft-support-20260601",
        symbol="msft",
        sleeve="pullback-support",
        environment="tiny_live",
        limit_price="410.123",
        size_usd="25.456",
    )

    payload = build_tiny_live_order_payload(intent)

    assert payload["client_order_id"] == "tiny-live-msft-support-20260601"
    assert payload["symbol"] == "MSFT"
    assert payload["type"] == "limit"
    assert payload["notional"] == "25.45"
    assert payload["limit_price"] == "410.12"


def test_tiny_live_payload_rejects_non_tiny_live_or_market_intent():
    paper_intent = TradeIntent(
        idempotency_key="paper-msft",
        symbol="MSFT",
        sleeve="pullback-support",
        environment="paper",
        limit_price="410",
        size_usd="25",
    )

    with pytest.raises(ValueError):
        build_tiny_live_order_payload(paper_intent)


def test_classify_alpaca_duplicate_client_order_id_requires_reconciliation():
    classification = classify_alpaca_submit_error(
        AlpacaExecutionError(
            'Alpaca POST /v2/orders failed with 422: '
            '{"code":40310000,"message":"client_order_id already exists"}'
        ),
        account="live",
        client_order_id="ta-tiny-20260602-current-amzn-buy-abc123",
    )

    assert classification.category == "duplicate_client_order_id"
    assert classification.retry_action == "reconcile_existing_order"
    assert classification.retry_safe is False
    assert classification.idempotency_conflict is True
    assert "do not create a replacement order id" in classification.message
    assert "Reconcile broker open/recent orders" in classification.message


def test_classify_alpaca_generic_submit_error_preserves_broker_text():
    classification = classify_alpaca_submit_error(
        RuntimeError("network timeout"),
        account="paper",
        client_order_id="ta-hourly-abc",
    )

    assert classification.category == "broker_submit_failed"
    assert classification.retry_action == "inspect_broker_response_then_retry_if_safe"
    assert classification.retry_safe is False
    assert classification.idempotency_conflict is False
    assert classification.message == "paper submit failed for ta-hourly-abc: network timeout"


def test_find_order_by_client_order_id_prefers_direct_broker_lookup():
    class _LookupClient:
        def __init__(self):
            self.requested = None

        def get_order_by_client_order_id(self, client_order_id):
            self.requested = client_order_id
            return {
                "id": "order-123",
                "client_order_id": client_order_id,
                "symbol": "AMZN",
                "status": "new",
                "secret_extra": "not-needed",
            }

    client = _LookupClient()

    order = find_order_by_client_order_id(client, "ta-tiny-amzn")

    assert client.requested == "ta-tiny-amzn"
    assert order == {
        "id": "order-123",
        "client_order_id": "ta-tiny-amzn",
        "symbol": "AMZN",
        "status": "new",
    }


def test_find_order_by_client_order_id_falls_back_to_list_orders():
    class _ListOnlyClient:
        def __init__(self):
            self.statuses = []

        def list_orders(self, status="open"):
            self.statuses.append(status)
            if status == "all":
                return [
                    {"id": "other", "client_order_id": "different"},
                    {
                        "id": "order-456",
                        "client_order_id": "ta-tiny-msft",
                        "symbol": "MSFT",
                        "status": "accepted",
                    },
                ]
            return []

    client = _ListOnlyClient()

    order = find_order_by_client_order_id(client, "ta-tiny-msft")

    assert client.statuses == ["open", "all"]
    assert order == {
        "id": "order-456",
        "client_order_id": "ta-tiny-msft",
        "symbol": "MSFT",
        "status": "accepted",
    }


def test_compare_alpaca_order_to_intent_accepts_matching_order_summary():
    issues = compare_alpaca_order_to_intent(
        {
            "symbol": "AMZN",
            "side": "buy",
            "type": "limit",
            "notional": "25",
            "limit_price": "208.410",
            "status": "new",
        },
        {
            "symbol": "AMZN",
            "side": "buy",
            "type": "limit",
            "notional": "25.00",
            "limit_price": "208.41",
        },
    )

    assert issues == []


def test_compare_alpaca_order_to_intent_flags_mismatch_or_unsafe_status():
    issues = compare_alpaca_order_to_intent(
        {
            "symbol": "TSLA",
            "side": "sell",
            "type": "limit",
            "notional": "30.00",
            "limit_price": "211.00",
            "status": "canceled",
        },
        {
            "symbol": "AMZN",
            "side": "buy",
            "type": "limit",
            "notional": "25.00",
            "limit_price": "208.41",
        },
    )

    assert "existing order status is canceled" in issues
    assert any("symbol mismatch" in issue for issue in issues)
    assert any("side mismatch" in issue for issue in issues)
    assert any("notional mismatch" in issue for issue in issues)
    assert any("limit_price mismatch" in issue for issue in issues)
