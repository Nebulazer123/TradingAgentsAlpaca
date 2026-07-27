from __future__ import annotations

import ast
import dataclasses
import datetime as dt
import hashlib
import importlib
import json
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from tests.test_strategy_staged_intent import (
    REPO_ROOT,
    UTC,
    _durable_internal_evidence,
    _reidentify_staged_payload,
    _stage_once,
)


@pytest.fixture(autouse=True)
def _treat_loaded_repo_as_clean_for_registration(monkeypatch):
    import tradingagents.strategy.promotion_evidence as module

    original = module._git_text

    def controlled_git_text(repo, *args):
        if (
            repo.resolve() == REPO_ROOT.resolve()
            and args == ("status", "--porcelain")
        ):
            return ""
        return original(repo, *args)

    monkeypatch.setattr(module, "_git_text", controlled_git_text)


def test_paper_execution_authorization_module_exists_with_durable_buy(
    tmp_path,
):
    # Break caught: Task 6D2A has no bounded authorization module for a
    # durable BUY staged by the accepted Task 6D1 ledger.
    root, registration, promotion_evidence = _durable_internal_evidence(
        tmp_path
    )
    _, staged_intent = _stage_once(
        root,
        registration,
        promotion_evidence,
    )
    assert staged_intent.decision.action.value == "buy"

    module = importlib.import_module(
        "tradingagents.strategy.paper_execution_authorization"
    )

    assert module.__name__ == (
        "tradingagents.strategy.paper_execution_authorization"
    )


def test_strategy_package_exports_authorization_surface():
    # Break caught: callers must reach the bounded data-only authorization API
    # through the stable strategy package surface.
    import tradingagents.strategy as strategy

    assert strategy.PAPER_EXECUTION_AUTHORIZATION_KIND == (
        "paper-execution-authorization"
    )
    assert strategy.PAPER_EXECUTION_AUTHORIZATION_SCHEMA_VERSION == 1
    assert strategy.PAPER_EXECUTION_AUTHORIZATION_MAX_TTL_SECONDS == 900
    assert strategy.AuthorizedPaperOrderRequest.__name__ == (
        "AuthorizedPaperOrderRequest"
    )
    assert strategy.StrategyPaperExecutionAuthorizationLedger.__name__ == (
        "StrategyPaperExecutionAuthorizationLedger"
    )
    assert callable(strategy.paper_account_fingerprint)


def test_fingerprint_uses_domain_separated_full_sha256_and_ascii_trim():
    # Break caught: the account identifier is hashed without domain separation
    # or surrounding ASCII whitespace changes the configured account identity.
    from tradingagents.strategy.paper_execution_authorization import (
        paper_account_fingerprint,
    )

    expected = (
        "bbc9bcbe7c9a68c51d96d77a529bc9f0"
        "af711fa509fb6c5ce3e3d14ef51bd2b1"
    )

    assert paper_account_fingerprint("paper-account-123") == expected
    assert (
        paper_account_fingerprint(
            " \t\n\r\v\fpaper-account-123 \t\n\r\v\f"
        )
        == expected
    )
    assert "paper-account-123" not in expected


def test_fingerprint_accepts_printable_unicode_and_256_utf8_byte_boundary():
    # Break caught: account validation counts code points or rejects printable
    # configured identifiers that are legal UTF-8.
    from tradingagents.strategy.paper_execution_authorization import (
        paper_account_fingerprint,
    )

    assert paper_account_fingerprint("纸张账户-α") == (
        "0d198d893710a6b63d03ebe01b8fbf9e"
        "041e1a1c1f9ff0ed0845449e760bb473"
    )
    exact = "é" * 128
    assert len(exact.encode("utf-8")) == 256
    assert len(paper_account_fingerprint(exact)) == 64


@pytest.mark.parametrize(
    "paper_account_id",
    (
        "",
        " \t\n\r\v\f",
        "paper\naccount",
        "paper\x00account",
        "paper\u200baccount",
        "é" * 128 + "a",
        "a" * 257,
    ),
)
def test_fingerprint_rejects_blank_nonprintable_and_oversized_ids(
    paper_account_id,
):
    # Break caught: unusable or over-bound raw account identifiers reach a
    # durable authorization identity.
    from tradingagents.strategy.paper_execution_authorization import (
        paper_account_fingerprint,
    )

    with pytest.raises(ValueError):
        paper_account_fingerprint(paper_account_id)


def test_fingerprint_rejects_lone_surrogate_without_identifier_leak():
    # Break caught: encoding a nonprintable surrogate before validation exposes
    # its escaped account-identifier material through UnicodeEncodeError text.
    from tradingagents.strategy.paper_execution_authorization import (
        paper_account_fingerprint,
    )

    raw_account_id = "\ud800"
    escaped_account_id = "\\ud800"

    with pytest.raises(ValueError) as captured:
        paper_account_fingerprint(raw_account_id)

    assert str(captured.value) == (
        "paper_account_id must contain only printable text"
    )
    assert raw_account_id not in str(captured.value)
    assert escaped_account_id not in str(captured.value)
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None


@pytest.mark.parametrize("paper_account_id", (b"paper", 1, True, None))
def test_fingerprint_requires_exact_str_type(paper_account_id):
    # Break caught: bytes, booleans, or other coercible values are persisted
    # under an account fingerprint the caller did not explicitly provide.
    from tradingagents.strategy.paper_execution_authorization import (
        paper_account_fingerprint,
    )

    with pytest.raises(TypeError):
        paper_account_fingerprint(paper_account_id)


def test_fingerprint_rejects_str_subclasses():
    # Break caught: an overridden string subtype controls normalization or
    # encoding side effects.
    from tradingagents.strategy.paper_execution_authorization import (
        paper_account_fingerprint,
    )

    class AccountId(str):
        pass

    with pytest.raises(TypeError):
        paper_account_fingerprint(AccountId("paper-account-123"))


def _canonical_test_bytes(payload):
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _logical_material(payload):
    return {
        "staged_intent_id": payload["staged_intent_id"],
        "staged_intent_sha256": payload["staged_intent_sha256"],
        "paper_account_fingerprint": payload["paper_account_fingerprint"],
        "session_date": payload["session_date"],
        "symbol": payload["symbol"],
        "side": payload["side"],
        "order_type": payload["order_type"],
        "tif": payload["tif"],
        "requested_notional_usd": payload["requested_notional_usd"],
        "requested_limit_price": payload["requested_limit_price"],
    }


def _reidentify_authorization_payload(payload):
    logical_digest = hashlib.sha256(
        _canonical_test_bytes(_logical_material(payload))
    ).hexdigest()
    payload["logical_order_sha256"] = logical_digest
    payload["client_order_id"] = f"ta-p-{logical_digest[:40]}"
    evidence_payload = {
        key: value
        for key, value in payload.items()
        if key not in {"authorization_id", "effective_at", "recorded_at"}
    }
    retry_material = {
        "kind": "paper-execution-authorization",
        "effective_at": payload["effective_at"],
        "payload": evidence_payload,
    }
    payload["authorization_id"] = (
        "paper-execution-authorization-"
        + hashlib.sha256(_canonical_test_bytes(retry_material)).hexdigest()
    )


def _authorization_payload(staged_intent=None, **overrides):
    if staged_intent is None:
        staged_intent_id = f"staged-paper-intent-{'1' * 64}"
        staged_intent_sha256 = "2" * 64
        promotion_evidence_id = f"promotion-evidence-{'3' * 64}"
        genome_id = f"genome-current-aggressive-{'4' * 64}"
        genome_canonical_sha256 = "5" * 64
        evaluation_code_commit = "6" * 40
        evaluation_runtime_sha256 = "7" * 64
        session_date = "2030-04-01"
        symbol = "NFLX"
        requested_notional_usd = "90.00"
        requested_limit_price = "100.20"
    else:
        staged_intent_id = staged_intent.staged_intent_id
        staged_intent_sha256 = hashlib.sha256(
            staged_intent.canonical_json_bytes()
        ).hexdigest()
        promotion_evidence_id = staged_intent.promotion_evidence_id
        genome_id = staged_intent.genome.genome_id
        genome_canonical_sha256 = staged_intent.genome_canonical_sha256
        evaluation_code_commit = staged_intent.evaluation_code_commit
        evaluation_runtime_sha256 = staged_intent.evaluation_runtime_sha256
        session_date = staged_intent.session_date
        symbol = staged_intent.decision.symbol
        requested_notional_usd = staged_intent.decision.notional_usd
        requested_limit_price = staged_intent.decision.limit_price
    payload = {
        "schema_version": 1,
        "authorization_id": "",
        "staged_intent_id": staged_intent_id,
        "staged_intent_sha256": staged_intent_sha256,
        "promotion_evidence_id": promotion_evidence_id,
        "genome_id": genome_id,
        "genome_canonical_sha256": genome_canonical_sha256,
        "evaluation_code_commit": evaluation_code_commit,
        "evaluation_runtime_sha256": evaluation_runtime_sha256,
        "paper_account_fingerprint": (
            "bbc9bcbe7c9a68c51d96d77a529bc9f0"
            "af711fa509fb6c5ce3e3d14ef51bd2b1"
        ),
        "session_date": session_date,
        "symbol": symbol,
        "side": "buy",
        "order_type": "limit",
        "tif": "day",
        "requested_notional_usd": requested_notional_usd,
        "requested_limit_price": requested_limit_price,
        "logical_order_sha256": "",
        "client_order_id": "",
        "expires_at": "2030-04-01T14:14:00+00:00",
        "effective_at": "2030-04-01T14:01:00+00:00",
        "recorded_at": "2030-04-01T14:01:05+00:00",
        "owner_role": "execution_operator",
        "authorization_scope": "single_alpaca_paper_order",
        "paper_submit_authorized": True,
        "live_submit_authorized": False,
        "analysis_only": True,
        "paper_only": True,
        "execution_authority": "paper_order_request_only",
        "can_submit_orders": False,
    }
    payload.update(overrides)
    _reidentify_authorization_payload(payload)
    return payload


def test_model_schema_canonical_bytes_fixed_authority_and_immutability():
    # Break caught: the authorization drops identity-bound material, mutates,
    # or grants this package broker submission authority.
    from tradingagents.strategy.paper_execution_authorization import (
        PAPER_EXECUTION_AUTHORIZATION_MAX_TTL_SECONDS,
        PAPER_EXECUTION_AUTHORIZATION_SCHEMA_VERSION,
        AuthorizedPaperOrderRequest,
    )

    payload = _authorization_payload()
    request = AuthorizedPaperOrderRequest.from_dict(payload)

    assert PAPER_EXECUTION_AUTHORIZATION_SCHEMA_VERSION == 1
    assert PAPER_EXECUTION_AUTHORIZATION_MAX_TTL_SECONDS == 900
    assert request.to_dict() == payload
    assert request.canonical_json_bytes() == _canonical_test_bytes(payload)
    assert AuthorizedPaperOrderRequest.from_dict(request.to_dict()) == request
    assert request.owner_role == "execution_operator"
    assert request.authorization_scope == "single_alpaca_paper_order"
    assert request.paper_submit_authorized is True
    assert request.live_submit_authorized is False
    assert request.analysis_only is True
    assert request.paper_only is True
    assert request.execution_authority == "paper_order_request_only"
    assert request.can_submit_orders is False
    with pytest.raises(dataclasses.FrozenInstanceError):
        request.expires_at = "changed"  # type: ignore[misc]


def test_model_is_active_uses_recorded_inclusive_expiry_exclusive():
    # Break caught: a connector can treat a request as active before durable
    # first-seen time or exactly at expiration.
    from tradingagents.strategy.paper_execution_authorization import (
        AuthorizedPaperOrderRequest,
    )

    request = AuthorizedPaperOrderRequest.from_dict(_authorization_payload())

    assert request.is_active(
        at=dt.datetime(2030, 4, 1, 14, 1, 5, tzinfo=UTC)
    )
    assert not request.is_active(
        at=dt.datetime(2030, 4, 1, 14, 1, 4, tzinfo=UTC)
    )
    assert not request.is_active(
        at=dt.datetime(2030, 4, 1, 14, 14, tzinfo=UTC)
    )


@pytest.mark.parametrize("invalid_version", (True, 1.0))
def test_model_schema_version_requires_exact_int(invalid_version):
    # Break caught: bool or float equality normalizes to durable schema 1.
    from tradingagents.strategy.paper_execution_authorization import (
        AuthorizedPaperOrderRequest,
    )

    payload = _authorization_payload()
    payload["schema_version"] = invalid_version
    _reidentify_authorization_payload(payload)

    with pytest.raises(ValueError, match="schema_version"):
        AuthorizedPaperOrderRequest.from_dict(payload)


def test_model_rejects_unknown_and_missing_fields():
    # Break caught: schema expansion or omission silently changes the
    # authorization contract.
    from tradingagents.strategy.paper_execution_authorization import (
        AuthorizedPaperOrderRequest,
    )

    with pytest.raises(ValueError, match="fields"):
        AuthorizedPaperOrderRequest.from_dict(
            {**_authorization_payload(), "broker_url": "live"}
        )
    missing = _authorization_payload()
    del missing["staged_intent_sha256"]
    with pytest.raises(ValueError, match="fields"):
        AuthorizedPaperOrderRequest.from_dict(missing)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("owner_role", "portfolio_executive"),
        ("authorization_scope", "normal_trade"),
        ("paper_submit_authorized", 1),
        ("live_submit_authorized", True),
        ("analysis_only", 1),
        ("paper_only", False),
        ("execution_authority", "paper_submit"),
        ("can_submit_orders", True),
        ("side", "sell"),
        ("order_type", "market"),
        ("tif", "gtc"),
    ),
)
def test_model_rejects_fixed_literal_and_boolean_drift(field, value):
    # Break caught: a parsed authorization broadens account, live, side, type,
    # time-in-force, role, or package execution authority.
    from tradingagents.strategy.paper_execution_authorization import (
        AuthorizedPaperOrderRequest,
    )

    payload = _authorization_payload(**{field: value})

    with pytest.raises((TypeError, ValueError)):
        AuthorizedPaperOrderRequest.from_dict(payload)


@pytest.mark.parametrize(
    "field",
    (
        "side",
        "order_type",
        "tif",
        "logical_order_sha256",
        "client_order_id",
    ),
)
def test_model_rejects_string_subclasses_for_fixed_and_client_fields(field):
    # Break caught: a string subtype with overridden equality or serialization
    # controls fixed order semantics or the shortened broker-facing identity.
    from tradingagents.strategy.paper_execution_authorization import (
        AuthorizedPaperOrderRequest,
    )

    class Token(str):
        pass

    payload = _authorization_payload()
    payload[field] = Token(payload[field])

    with pytest.raises((TypeError, ValueError)):
        AuthorizedPaperOrderRequest.from_dict(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("authorization_id", "paper-execution-authorization-" + "0" * 64),
        ("staged_intent_id", "staged-paper-intent-" + "0" * 64),
        ("staged_intent_sha256", "0" * 64),
        ("promotion_evidence_id", "promotion-evidence-" + "0" * 64),
        ("genome_canonical_sha256", "0" * 64),
        ("evaluation_code_commit", "A" * 40),
        ("evaluation_runtime_sha256", "short"),
        ("paper_account_fingerprint", "f" * 63),
        ("logical_order_sha256", "0" * 64),
        ("client_order_id", "ta-p-" + "0" * 40),
    ),
)
def test_model_rejects_identity_digest_commit_and_client_binding_drift(
    field,
    value,
):
    # Break caught: a shortened client ID or outer identity names different
    # full logical material.
    from tradingagents.strategy.paper_execution_authorization import (
        AuthorizedPaperOrderRequest,
    )

    payload = _authorization_payload()
    payload[field] = value

    with pytest.raises((TypeError, ValueError)):
        AuthorizedPaperOrderRequest.from_dict(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("requested_notional_usd", 90.0),
        ("requested_notional_usd", "90"),
        ("requested_notional_usd", "090.00"),
        ("requested_notional_usd", "90.0"),
        ("requested_notional_usd", "90.000"),
        ("requested_notional_usd", "0.00"),
        ("requested_notional_usd", "-1.00"),
        ("requested_limit_price", 100.2),
        ("requested_limit_price", "100.2"),
        ("requested_limit_price", "1e2"),
        ("requested_limit_price", "+100.20"),
        ("requested_limit_price", "0.00"),
    ),
)
def test_model_rejects_noncanonical_or_nonpositive_financial_text(field, value):
    # Break caught: binary floats, exponents, alternate spellings, or
    # nonpositive economics acquire canonical authorization identity.
    from tradingagents.strategy.paper_execution_authorization import (
        AuthorizedPaperOrderRequest,
    )

    payload = _authorization_payload(**{field: value})

    with pytest.raises((TypeError, ValueError)):
        AuthorizedPaperOrderRequest.from_dict(payload)


def test_model_copies_durable_staged_financial_bytes_exactly(tmp_path):
    # Break caught: Task 6D2A rounds, normalizes, or independently sizes the
    # virtual paper economics selected by the durable staged BUY.
    from tradingagents.strategy.paper_execution_authorization import (
        AuthorizedPaperOrderRequest,
    )

    root, registration, promotion_evidence = _durable_internal_evidence(
        tmp_path
    )
    _, staged_intent = _stage_once(
        root,
        registration,
        promotion_evidence,
    )
    request = AuthorizedPaperOrderRequest.from_dict(
        _authorization_payload(staged_intent)
    )

    assert request.symbol == staged_intent.decision.symbol
    assert request.requested_notional_usd == staged_intent.decision.notional_usd
    assert request.requested_limit_price == staged_intent.decision.limit_price


def _authorize_once(
    root,
    staged_intent,
    *,
    paper_account_id="paper-account-123",
    actor_role="execution_operator",
    clock_time=dt.datetime(2030, 4, 1, 14, 1, 5, tzinfo=UTC),
    effective_at=dt.datetime(2030, 4, 1, 14, 1, tzinfo=UTC),
    expires_at=dt.datetime(2030, 4, 1, 14, 14, tzinfo=UTC),
):
    from tradingagents.strategy.paper_execution_authorization import (
        StrategyPaperExecutionAuthorizationLedger,
    )

    ledger = StrategyPaperExecutionAuthorizationLedger(
        root,
        repo_root=REPO_ROOT,
        clock=lambda: clock_time,
    )
    request = ledger.authorize_buy(
        staged_intent=staged_intent,
        paper_account_id=paper_account_id,
        actor_role=actor_role,
        effective_at=effective_at,
        expires_at=expires_at,
    )
    return ledger, request


def test_ledger_authorizes_one_durable_active_buy_with_copied_economics(
    tmp_path,
):
    # Break caught: admission trusts free order fields or fails to bind the
    # durable staged BUY and its active paper-only identity.
    root, registration, promotion_evidence = _durable_internal_evidence(
        tmp_path
    )
    _, staged_intent = _stage_once(
        root,
        registration,
        promotion_evidence,
    )

    _, request = _authorize_once(root, staged_intent)

    assert request.staged_intent_id == staged_intent.staged_intent_id
    assert request.staged_intent_sha256 == hashlib.sha256(
        staged_intent.canonical_json_bytes()
    ).hexdigest()
    assert request.promotion_evidence_id == (
        staged_intent.promotion_evidence_id
    )
    assert request.genome_id == staged_intent.genome.genome_id
    assert request.genome_canonical_sha256 == (
        staged_intent.genome_canonical_sha256
    )
    assert request.evaluation_code_commit == (
        staged_intent.evaluation_code_commit
    )
    assert request.evaluation_runtime_sha256 == (
        staged_intent.evaluation_runtime_sha256
    )
    assert request.symbol == staged_intent.decision.symbol
    assert request.requested_notional_usd == (
        staged_intent.decision.notional_usd
    )
    assert request.requested_limit_price == (
        staged_intent.decision.limit_price
    )
    assert request.is_active(
        at=dt.datetime(2030, 4, 1, 14, 1, 5, tzinfo=UTC)
    )


def test_ledger_rejects_wrong_actor_and_hold_without_event(tmp_path):
    # Break caught: a non-owner or HOLD intent can manufacture paper order
    # authorization evidence.
    root, registration, promotion_evidence = _durable_internal_evidence(
        tmp_path
    )
    _, staged_buy = _stage_once(root, registration, promotion_evidence)
    before = (root / "events.jsonl").read_bytes()

    with pytest.raises(ValueError, match="execution_operator"):
        _authorize_once(
            root,
            staged_buy,
            actor_role="portfolio_executive",
        )
    assert (root / "events.jsonl").read_bytes() == before

    hold_parent = tmp_path / "hold"
    hold_parent.mkdir()
    second_root = hold_parent / "evidence"
    hold_root, hold_registration, hold_evidence = _durable_internal_evidence(
        hold_parent
    )
    assert second_root == hold_root
    _, staged_hold = _stage_once(
        hold_root,
        hold_registration,
        hold_evidence,
        market_session="closed",
    )
    hold_before = (hold_root / "events.jsonl").read_bytes()
    with pytest.raises(ValueError, match="BUY"):
        _authorize_once(hold_root, staged_hold)
    assert (hold_root / "events.jsonl").read_bytes() == hold_before


def test_ledger_rejects_missing_and_foreign_store_staged_dependency(tmp_path):
    # Break caught: caller-held or foreign staged bytes satisfy a dependency
    # that is not event-admitted in this authorization journal.
    first_parent = tmp_path / "first"
    first_parent.mkdir()
    first_root, registration, promotion_evidence = _durable_internal_evidence(
        first_parent
    )
    _, staged_intent = _stage_once(
        first_root,
        registration,
        promotion_evidence,
    )
    empty_root = tmp_path / "empty"

    with pytest.raises(ValueError, match="durable"):
        _authorize_once(empty_root, staged_intent)
    assert not empty_root.exists()

    second_parent = tmp_path / "second"
    second_parent.mkdir()
    second_root, _, _ = _durable_internal_evidence(second_parent)
    before = (second_root / "events.jsonl").read_bytes()
    with pytest.raises(ValueError, match="durable"):
        _authorize_once(second_root, staged_intent)
    assert (second_root / "events.jsonl").read_bytes() == before


@pytest.mark.parametrize(
    ("clock_time", "effective_at", "expires_at", "message"),
    (
        (
            dt.datetime(2030, 4, 1, 14, 1, tzinfo=UTC),
            dt.datetime(2030, 4, 1, 14, 1, 1, tzinfo=UTC),
            dt.datetime(2030, 4, 1, 14, 14, tzinfo=UTC),
            "future-effective",
        ),
        (
            dt.datetime(2030, 4, 1, 14, 14, tzinfo=UTC),
            dt.datetime(2030, 4, 1, 14, 1, tzinfo=UTC),
            dt.datetime(2030, 4, 1, 14, 14, tzinfo=UTC),
            "expired",
        ),
        (
            dt.datetime(2030, 4, 1, 14, 1, 5, tzinfo=UTC),
            dt.datetime(2030, 4, 1, 14, 1, tzinfo=UTC),
            dt.datetime(2030, 4, 1, 14, 15, 1, tzinfo=UTC),
            "staged",
        ),
    ),
)
def test_ledger_rejects_invalid_timing_without_capping_or_event(
    tmp_path,
    clock_time,
    effective_at,
    expires_at,
    message,
):
    # Break caught: caller expiry is silently capped or future/stale authority
    # reaches the journal.
    root, registration, promotion_evidence = _durable_internal_evidence(
        tmp_path
    )
    _, staged_intent = _stage_once(
        root,
        registration,
        promotion_evidence,
    )
    before = (root / "events.jsonl").read_bytes()

    with pytest.raises(ValueError, match=message):
        _authorize_once(
            root,
            staged_intent,
            clock_time=clock_time,
            effective_at=effective_at,
            expires_at=expires_at,
        )

    assert (root / "events.jsonl").read_bytes() == before


def test_ledger_accepts_exact_900_second_authorization_boundary(tmp_path):
    # Break caught: the inclusive maximum TTL is treated as over-limit even
    # when it remains exactly within the staged-intent deadline.
    root, registration, promotion_evidence = _durable_internal_evidence(
        tmp_path
    )
    _, staged_intent = _stage_once(
        root,
        registration,
        promotion_evidence,
        clock=lambda: dt.datetime(
            2030,
            4,
            1,
            14,
            0,
            tzinfo=UTC,
        ),
    )

    _, request = _authorize_once(
        root,
        staged_intent,
        clock_time=dt.datetime(
            2030,
            4,
            1,
            14,
            0,
            tzinfo=UTC,
        ),
        effective_at=dt.datetime(
            2030,
            4,
            1,
            14,
            0,
            tzinfo=UTC,
        ),
        expires_at=dt.datetime(
            2030,
            4,
            1,
            14,
            15,
            tzinfo=UTC,
        ),
    )

    assert (
        dt.datetime.fromisoformat(request.expires_at)
        - dt.datetime.fromisoformat(request.effective_at)
    ) == dt.timedelta(seconds=900)


def test_ledger_exact_retry_is_event_silent_and_one_authorization_per_buy(
    tmp_path,
):
    # Break caught: an exact retry appends another event or changed expiry gives
    # one staged BUY two operational meanings.
    root, registration, promotion_evidence = _durable_internal_evidence(
        tmp_path
    )
    _, staged_intent = _stage_once(
        root,
        registration,
        promotion_evidence,
    )
    _, first = _authorize_once(root, staged_intent)
    first_events = (root / "events.jsonl").read_bytes()

    _, retry = _authorize_once(
        root,
        staged_intent,
        clock_time=dt.datetime(2030, 4, 1, 14, 2, tzinfo=UTC),
    )

    assert retry == first
    assert retry.recorded_at == first.recorded_at
    assert (root / "events.jsonl").read_bytes() == first_events

    with pytest.raises(ValueError, match="already has"):
        _authorize_once(
            root,
            staged_intent,
            clock_time=dt.datetime(2030, 4, 1, 14, 2, tzinfo=UTC),
            expires_at=dt.datetime(2030, 4, 1, 14, 13, tzinfo=UTC),
        )
    assert (root / "events.jsonl").read_bytes() == first_events


def test_ledger_never_persists_raw_or_normalized_account_identifier(tmp_path):
    # Break caught: the account ID leaks through the return object, immutable
    # object, journal, or derived latest pointer.
    raw_account_id = " \tSensitive Paper Account α\n "
    normalized_account_id = "Sensitive Paper Account α"
    root, registration, promotion_evidence = _durable_internal_evidence(
        tmp_path
    )
    _, staged_intent = _stage_once(
        root,
        registration,
        promotion_evidence,
    )

    _, request = _authorize_once(
        root,
        staged_intent,
        paper_account_id=raw_account_id,
    )

    assert normalized_account_id not in request.canonical_json_bytes().decode()
    for path in root.rglob("*"):
        if path.is_file():
            durable_bytes = path.read_bytes()
            assert raw_account_id.encode() not in durable_bytes
            assert normalized_account_id.encode() not in durable_bytes


def test_evaluation_runtime_brackets_authorization_exactly_twice_outside_callbacks(
    tmp_path,
    monkeypatch,
):
    # Break caught: active calculation evidence is skipped, sampled once, or
    # re-entered while the immutable store callback holds its lock.
    import tradingagents.strategy.paper_execution_authorization as module

    root, registration, promotion_evidence = _durable_internal_evidence(
        tmp_path
    )
    _, staged_intent = _stage_once(
        root,
        registration,
        promotion_evidence,
    )
    ledger = module.StrategyPaperExecutionAuthorizationLedger(
        root,
        repo_root=REPO_ROOT,
        clock=lambda: dt.datetime(2030, 4, 1, 14, 1, 5, tzinfo=UTC),
    )
    original_runtime = module.require_active_evaluation_runtime
    original_admit = ledger._store.admit_checked
    calls = []
    inside_callback = False

    def guarded_runtime(repo_root, durable_registration):
        assert inside_callback is False
        calls.append((repo_root, durable_registration))
        return original_runtime(repo_root, durable_registration)

    def wrapped_admit(
        candidate,
        *,
        validate,
        validate_orphans=None,
        validate_combined=None,
    ):
        assert validate_combined is not None

        def wrap(callback):
            def guarded(*args):
                nonlocal inside_callback
                inside_callback = True
                try:
                    return callback(*args)
                finally:
                    inside_callback = False

            return guarded

        return original_admit(
            candidate,
            validate=wrap(validate),
            validate_orphans=(
                wrap(validate_orphans)
                if validate_orphans is not None
                else None
            ),
            validate_combined=(
                wrap(validate_combined)
                if validate_combined is not None
                else None
            ),
        )

    monkeypatch.setattr(
        module,
        "require_active_evaluation_runtime",
        guarded_runtime,
    )
    monkeypatch.setattr(ledger._store, "admit_checked", wrapped_admit)

    request = ledger.authorize_buy(
        staged_intent=staged_intent,
        paper_account_id="paper-account-123",
        actor_role="execution_operator",
        effective_at=dt.datetime(2030, 4, 1, 14, 1, tzinfo=UTC),
        expires_at=dt.datetime(2030, 4, 1, 14, 14, tzinfo=UTC),
    )

    assert request.staged_intent_id == staged_intent.staged_intent_id
    assert len(calls) == 2
    assert all(call[0] == REPO_ROOT for call in calls)
    assert all(call[1] == registration for call in calls)


def test_evaluation_runtime_change_between_checks_rejects_without_event(
    tmp_path,
    monkeypatch,
):
    # Break caught: candidate construction spans two different calculation
    # manifests and still gains an immutable event.
    import tradingagents.strategy.paper_execution_authorization as module

    root, registration, promotion_evidence = _durable_internal_evidence(
        tmp_path
    )
    _, staged_intent = _stage_once(
        root,
        registration,
        promotion_evidence,
    )
    before = (root / "events.jsonl").read_bytes()
    original_runtime = module.require_active_evaluation_runtime
    calls = 0

    def changed_runtime(*args, **kwargs):
        nonlocal calls
        calls += 1
        manifest = original_runtime(*args, **kwargs)
        if calls == 2:
            changed_file = dataclasses.replace(
                manifest.files[0],
                sha256="f" * 64,
            )
            return dataclasses.replace(
                manifest,
                files=(changed_file, *manifest.files[1:]),
            )
        return manifest

    monkeypatch.setattr(
        module,
        "require_active_evaluation_runtime",
        changed_runtime,
    )

    with pytest.raises(ValueError, match="runtime changed"):
        _authorize_once(root, staged_intent)

    assert calls == 2
    assert (root / "events.jsonl").read_bytes() == before


def test_source_drift_rejects_authorization_before_event(
    tmp_path,
    monkeypatch,
):
    # Break caught: compiler/evaluator/genome/config drift can authorize stale
    # staged economics.
    import tradingagents.strategy.promotion_evidence as promotion_module

    root, registration, promotion_evidence = _durable_internal_evidence(
        tmp_path
    )
    _, staged_intent = _stage_once(
        root,
        registration,
        promotion_evidence,
    )
    before = (root / "events.jsonl").read_bytes()
    original = promotion_module._read_regular_source

    def drifted(repo_root, candidate):
        active = original(repo_root, candidate)
        if candidate == promotion_module.EVALUATION_SOURCE_PATHS[0]:
            return active + b"drift\n"
        return active

    monkeypatch.setattr(
        promotion_module,
        "_read_regular_source",
        drifted,
    )

    with pytest.raises(
        ValueError,
        match="loaded calculation source|active calculation manifest",
    ):
        _authorize_once(root, staged_intent)

    assert (root / "events.jsonl").read_bytes() == before


def test_head_advance_allows_authorization_when_calculation_bytes_match(
    tmp_path,
    monkeypatch,
):
    # Break caught: an unrelated descendant HEAD is mistaken for calculation
    # source drift.
    import tradingagents.strategy.promotion_evidence as promotion_module

    root, registration, promotion_evidence = _durable_internal_evidence(
        tmp_path
    )
    _, staged_intent = _stage_once(
        root,
        registration,
        promotion_evidence,
    )
    original_git_text = promotion_module._git_text

    def descendant_git_text(repo_root, *args):
        if args == ("rev-parse", "HEAD"):
            return "f" * 40
        return original_git_text(repo_root, *args)

    monkeypatch.setattr(
        promotion_module,
        "_git_text",
        descendant_git_text,
    )

    _, request = _authorize_once(root, staged_intent)

    assert request.evaluation_code_commit == (
        registration.evaluation_code_commit
    )


def test_evaluation_runtime_constructor_binds_explicit_repository(
    tmp_path,
):
    # Break caught: the ledger ignores its explicit repo_root and validates the
    # process checkout instead.
    import tradingagents.strategy.paper_execution_authorization as module

    root, registration, promotion_evidence = _durable_internal_evidence(
        tmp_path
    )
    _, staged_intent = _stage_once(
        root,
        registration,
        promotion_evidence,
    )
    wrong_repo = tmp_path / "wrong-repo"
    wrong_repo.mkdir()
    ledger = module.StrategyPaperExecutionAuthorizationLedger(
        root,
        repo_root=wrong_repo,
        clock=lambda: dt.datetime(2030, 4, 1, 14, 1, 5, tzinfo=UTC),
    )

    with pytest.raises(ValueError):
        ledger.authorize_buy(
            staged_intent=staged_intent,
            paper_account_id="paper-account-123",
            actor_role="execution_operator",
            effective_at=dt.datetime(2030, 4, 1, 14, 1, tzinfo=UTC),
            expires_at=dt.datetime(2030, 4, 1, 14, 14, tzinfo=UTC),
        )


def test_concurrent_changed_authorization_material_admits_exactly_one(
    tmp_path,
):
    # Break caught: two account bindings race past a pre-lock staged-intent
    # uniqueness check and both become durable execution authority.
    from tradingagents.strategy._immutable_evidence_store import (
        PAPER_EXECUTION_AUTHORIZATION_KIND,
        ImmutableStrategyEvidenceStore,
    )

    root, registration, promotion_evidence = _durable_internal_evidence(
        tmp_path
    )
    _, staged_intent = _stage_once(
        root,
        registration,
        promotion_evidence,
    )
    barrier = threading.Barrier(2)

    def authorize(account_id):
        barrier.wait()
        return _authorize_once(
            root,
            staged_intent,
            paper_account_id=account_id,
        )[1]

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = (
            executor.submit(authorize, "paper-account-one"),
            executor.submit(authorize, "paper-account-two"),
        )
        outcomes = []
        for future in futures:
            try:
                outcomes.append(future.result())
            except ValueError as exc:
                outcomes.append(exc)

    assert sum(not isinstance(outcome, Exception) for outcome in outcomes) == 1
    errors = [outcome for outcome in outcomes if isinstance(outcome, Exception)]
    assert len(errors) == 1
    assert "already has" in str(errors[0])
    assert sum(
        envelope.kind == PAPER_EXECUTION_AUTHORIZATION_KIND
        for envelope in ImmutableStrategyEvidenceStore(root).verify()
    ) == 1


def test_concurrent_identical_authorization_retry_is_event_silent(tmp_path):
    # Break caught: two byte-identical callers race into duplicate events or
    # receive different first-seen authorization timestamps.
    from tradingagents.strategy._immutable_evidence_store import (
        PAPER_EXECUTION_AUTHORIZATION_KIND,
        ImmutableStrategyEvidenceStore,
    )

    root, registration, promotion_evidence = _durable_internal_evidence(
        tmp_path
    )
    _, staged_intent = _stage_once(
        root,
        registration,
        promotion_evidence,
    )
    before_events = (root / "events.jsonl").read_bytes()
    barrier = threading.Barrier(2)

    def authorize():
        barrier.wait()
        return _authorize_once(root, staged_intent)[1]

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = (
            executor.submit(authorize),
            executor.submit(authorize),
        )
        requests = tuple(future.result() for future in futures)

    assert requests[0].canonical_json_bytes() == (
        requests[1].canonical_json_bytes()
    )
    assert requests[0].authorization_id == requests[1].authorization_id
    assert requests[0].recorded_at == requests[1].recorded_at
    assert requests[0].recorded_at == "2030-04-01T14:01:05+00:00"
    assert (root / "events.jsonl").read_bytes().count(b"\n") == (
        before_events.count(b"\n") + 1
    )
    assert sum(
        envelope.kind == PAPER_EXECUTION_AUTHORIZATION_KIND
        for envelope in ImmutableStrategyEvidenceStore(root).verify()
    ) == 1


def _crash_authorization_after_object_fsync(
    root,
    staged_intent,
    *,
    paper_account_id="paper-account-123",
):
    from tradingagents.strategy.paper_execution_authorization import (
        StrategyPaperExecutionAuthorizationLedger,
    )

    ledger = StrategyPaperExecutionAuthorizationLedger(
        root,
        repo_root=REPO_ROOT,
        clock=lambda: dt.datetime(2030, 4, 1, 14, 1, 5, tzinfo=UTC),
    )
    original = ledger._store._after_object_fsync

    def crash(_path):
        raise RuntimeError("simulated authorization object fsync crash")

    ledger._store._after_object_fsync = crash
    with pytest.raises(RuntimeError, match="object fsync crash"):
        ledger.authorize_buy(
            staged_intent=staged_intent,
            paper_account_id=paper_account_id,
            actor_role="execution_operator",
            effective_at=dt.datetime(2030, 4, 1, 14, 1, tzinfo=UTC),
            expires_at=dt.datetime(2030, 4, 1, 14, 14, tzinfo=UTC),
        )
    ledger._store._after_object_fsync = original


def test_exact_object_fsync_orphan_retry_adopts_original_first_seen(
    tmp_path,
):
    # Break caught: a byte-exact authorization orphan cannot be recovered with
    # its original immutable store timestamp after a crash.
    root, registration, promotion_evidence = _durable_internal_evidence(
        tmp_path
    )
    _, staged_intent = _stage_once(
        root,
        registration,
        promotion_evidence,
    )
    _crash_authorization_after_object_fsync(root, staged_intent)
    before = (root / "events.jsonl").read_bytes()

    _, repaired = _authorize_once(
        root,
        staged_intent,
        clock_time=dt.datetime(2030, 4, 1, 14, 1, 10, tzinfo=UTC),
    )

    assert repaired.recorded_at == "2030-04-01T14:01:05+00:00"
    assert (root / "events.jsonl").read_bytes().count(b"\n") == (
        before.count(b"\n") + 1
    )


def test_changed_material_same_staged_orphan_blocks_before_new_bytes(
    tmp_path,
):
    # Break caught: an authorization object-fsync orphan and a changed account
    # retry create two meanings for one staged BUY.
    root, registration, promotion_evidence = _durable_internal_evidence(
        tmp_path
    )
    _, staged_intent = _stage_once(
        root,
        registration,
        promotion_evidence,
    )
    _crash_authorization_after_object_fsync(root, staged_intent)
    before_events = (root / "events.jsonl").read_bytes()
    before_objects = {
        path.relative_to(root): path.read_bytes()
        for path in (root / "objects").rglob("*.json")
    }

    with pytest.raises(ValueError, match="already has"):
        _authorize_once(
            root,
            staged_intent,
            paper_account_id="changed-paper-account",
            clock_time=dt.datetime(2030, 4, 1, 14, 1, 10, tzinfo=UTC),
        )

    assert (root / "events.jsonl").read_bytes() == before_events
    assert {
        path.relative_to(root): path.read_bytes()
        for path in (root / "objects").rglob("*.json")
    } == before_objects


def test_unrelated_kind_orphan_is_authorization_neutral(tmp_path):
    # Break caught: strict orphan filtering blocks a bounded authorization
    # because an unrelated evidence kind was interrupted after object fsync.
    from tradingagents.strategy._immutable_evidence_store import (
        EvidenceCandidate,
    )
    from tradingagents.strategy.paper_execution_authorization import (
        StrategyPaperExecutionAuthorizationLedger,
    )

    root, registration, promotion_evidence = _durable_internal_evidence(
        tmp_path
    )
    _, staged_intent = _stage_once(
        root,
        registration,
        promotion_evidence,
    )
    ledger = StrategyPaperExecutionAuthorizationLedger(
        root,
        repo_root=REPO_ROOT,
        clock=lambda: dt.datetime(2030, 4, 1, 14, 1, 5, tzinfo=UTC),
    )
    original = ledger._store._after_object_fsync

    def crash(_path):
        raise RuntimeError("simulated unrelated object crash")

    ledger._store._after_object_fsync = crash
    with pytest.raises(RuntimeError, match="unrelated object crash"):
        ledger._store.admit_checked(
            EvidenceCandidate(
                kind="baseline-genome",
                effective_at="2030-04-01T14:01:00+00:00",
                payload={"unrelated": True},
            ),
            validate=lambda _snapshot, _envelope: None,
        )
    ledger._store._after_object_fsync = original

    request = ledger.authorize_buy(
        staged_intent=staged_intent,
        paper_account_id="paper-account-123",
        actor_role="execution_operator",
        effective_at=dt.datetime(2030, 4, 1, 14, 1, tzinfo=UTC),
        expires_at=dt.datetime(2030, 4, 1, 14, 14, tzinfo=UTC),
    )

    assert request.staged_intent_id == staged_intent.staged_intent_id


def test_strict_valid_unrelated_authorization_orphan_is_neutral(tmp_path):
    # Break caught: the orphan callback rejects any strict-valid authorization
    # object instead of only a staged, logical-digest, or client-ID conflict.
    from tradingagents.strategy import (
        AuthorizedPaperOrderRequest,
        StagedPaperIntent,
    )
    from tradingagents.strategy._immutable_evidence_store import (
        PAPER_EXECUTION_AUTHORIZATION_KIND,
        STAGED_PAPER_INTENT_KIND,
        EvidenceCandidate,
        ImmutableStrategyEvidenceStore,
    )

    root, registration, promotion_evidence = _durable_internal_evidence(
        tmp_path
    )
    _, staged_intent = _stage_once(
        root,
        registration,
        promotion_evidence,
    )
    alternate_payload = staged_intent.to_dict()
    alternate_payload.update(
        {
            "session_date": "2030-04-02",
            "recorded_at": "2030-04-01T14:00:06+00:00",
        }
    )
    _reidentify_staged_payload(alternate_payload)
    alternate_staged = StagedPaperIntent.from_dict(alternate_payload)
    ImmutableStrategyEvidenceStore(
        root,
        clock=lambda: dt.datetime(
            2030,
            4,
            1,
            14,
            0,
            6,
            tzinfo=UTC,
        ),
    ).admit_checked(
        EvidenceCandidate(
            kind=STAGED_PAPER_INTENT_KIND,
            effective_at=alternate_staged.effective_at,
            payload={
                key: value
                for key, value in alternate_staged.to_dict().items()
                if key
                not in {
                    "staged_intent_id",
                    "effective_at",
                    "recorded_at",
                }
            },
        ),
        validate=lambda _snapshot, _envelope: None,
    )
    orphan_request = AuthorizedPaperOrderRequest.from_dict(
        _authorization_payload(alternate_staged)
    )
    crashing_store = ImmutableStrategyEvidenceStore(
        root,
        clock=lambda: dt.datetime(
            2030,
            4,
            1,
            14,
            1,
            5,
            tzinfo=UTC,
        ),
    )

    def crash(_path):
        raise RuntimeError("simulated unrelated authorization crash")

    crashing_store._after_object_fsync = crash
    with pytest.raises(RuntimeError, match="unrelated authorization"):
        crashing_store.admit_checked(
            EvidenceCandidate(
                kind=PAPER_EXECUTION_AUTHORIZATION_KIND,
                effective_at=orphan_request.effective_at,
                payload={
                    key: value
                    for key, value in orphan_request.to_dict().items()
                    if key
                    not in {
                        "authorization_id",
                        "effective_at",
                        "recorded_at",
                    }
                },
            ),
            validate=lambda _snapshot, _envelope: None,
        )
    before_events = (root / "events.jsonl").read_bytes()
    orphan_path = (
        root
        / "objects"
        / PAPER_EXECUTION_AUTHORIZATION_KIND
        / f"{orphan_request.authorization_id}.json"
    )
    assert orphan_path.is_file()

    ledger, request = _authorize_once(
        root,
        staged_intent,
        clock_time=dt.datetime(
            2030,
            4,
            1,
            14,
            1,
            6,
            tzinfo=UTC,
        ),
    )

    assert request.staged_intent_id != orphan_request.staged_intent_id
    assert request.logical_order_sha256 != (
        orphan_request.logical_order_sha256
    )
    assert request.client_order_id != orphan_request.client_order_id
    assert (root / "events.jsonl").read_bytes().count(b"\n") == (
        before_events.count(b"\n") + 1
    )
    assert ledger.verify() == (request,)
    assert orphan_path.is_file()


def test_orphan_staged_intent_never_satisfies_authorization_dependency(
    tmp_path,
):
    # Break caught: a strict-valid staged object without a journal event is
    # treated as durable execution lineage.
    from tradingagents.strategy._immutable_evidence_store import (
        EvidenceCandidate,
        ImmutableStrategyEvidenceStore,
    )
    from tradingagents.strategy.paper_execution_authorization import (
        StrategyPaperExecutionAuthorizationLedger,
    )

    source_root, registration, promotion_evidence = (
        _durable_internal_evidence(tmp_path)
    )
    _, staged_intent = _stage_once(
        source_root,
        registration,
        promotion_evidence,
    )
    source_snapshot = ImmutableStrategyEvidenceStore(source_root).verify()
    registration_envelope = next(
        envelope
        for envelope in source_snapshot
        if envelope.object_id == registration.registration_id
    )
    staged_envelope = next(
        envelope
        for envelope in source_snapshot
        if envelope.object_id == staged_intent.staged_intent_id
    )
    target_root = tmp_path / "orphan-dependency"
    _admit_envelope_copy(
        target_root,
        registration_envelope,
        recorded_at=dt.datetime(
            2029,
            12,
            31,
            16,
            0,
            tzinfo=UTC,
        ),
    )
    crashing_store = ImmutableStrategyEvidenceStore(
        target_root,
        clock=lambda: dt.datetime(
            2030,
            4,
            1,
            14,
            0,
            5,
            tzinfo=UTC,
        ),
    )

    def crash(_path):
        raise RuntimeError("simulated orphan staged dependency")

    crashing_store._after_object_fsync = crash
    with pytest.raises(RuntimeError, match="orphan staged"):
        crashing_store.admit_checked(
            EvidenceCandidate(
                kind=staged_envelope.kind,
                effective_at=staged_envelope.effective_at,
                payload=json.loads(
                    staged_envelope.canonical_json_bytes()
                )["payload"],
            ),
            validate=lambda _snapshot, _envelope: None,
        )
    before = (target_root / "events.jsonl").read_bytes()
    ledger = StrategyPaperExecutionAuthorizationLedger(
        target_root,
        repo_root=REPO_ROOT,
        clock=lambda: dt.datetime(
            2030,
            4,
            1,
            14,
            1,
            5,
            tzinfo=UTC,
        ),
    )

    with pytest.raises(ValueError, match="durable"):
        ledger.authorize_buy(
            staged_intent=staged_intent,
            paper_account_id="paper-account-123",
            actor_role="execution_operator",
            effective_at=dt.datetime(
                2030,
                4,
                1,
                14,
                1,
                tzinfo=UTC,
            ),
            expires_at=dt.datetime(
                2030,
                4,
                1,
                14,
                14,
                tzinfo=UTC,
            ),
        )

    assert (target_root / "events.jsonl").read_bytes() == before
    assert not tuple(
        (
            target_root
            / "objects"
            / "paper-execution-authorization"
        ).glob("*.json")
    )


def test_event_fsync_crash_retry_repairs_without_duplicate_event(tmp_path):
    # Break caught: a journal-visible authorization is duplicated while its
    # latest pointer is recovered after an event-fsync crash.
    from tradingagents.strategy.paper_execution_authorization import (
        StrategyPaperExecutionAuthorizationLedger,
    )

    root, registration, promotion_evidence = _durable_internal_evidence(
        tmp_path
    )
    _, staged_intent = _stage_once(
        root,
        registration,
        promotion_evidence,
    )
    ledger = StrategyPaperExecutionAuthorizationLedger(
        root,
        repo_root=REPO_ROOT,
        clock=lambda: dt.datetime(2030, 4, 1, 14, 1, 5, tzinfo=UTC),
    )
    original = ledger._store._after_event_fsync

    def crash(_event):
        raise RuntimeError("simulated authorization event fsync crash")

    ledger._store._after_event_fsync = crash
    with pytest.raises(RuntimeError, match="event fsync crash"):
        ledger.authorize_buy(
            staged_intent=staged_intent,
            paper_account_id="paper-account-123",
            actor_role="execution_operator",
            effective_at=dt.datetime(2030, 4, 1, 14, 1, tzinfo=UTC),
            expires_at=dt.datetime(2030, 4, 1, 14, 14, tzinfo=UTC),
        )
    ledger._store._after_event_fsync = original
    before = (root / "events.jsonl").read_bytes()

    repaired_ledger, request = _authorize_once(
        root,
        staged_intent,
        clock_time=dt.datetime(2030, 4, 1, 14, 1, 10, tzinfo=UTC),
    )

    assert request.recorded_at == "2030-04-01T14:01:05+00:00"
    assert (root / "events.jsonl").read_bytes() == before
    assert repaired_ledger._store.rebuild()[-1].object_id == (
        request.authorization_id
    )


def _admit_envelope_copy(root, envelope, *, recorded_at):
    from tradingagents.strategy._immutable_evidence_store import (
        EvidenceCandidate,
        ImmutableStrategyEvidenceStore,
    )

    payload = json.loads(envelope.canonical_json_bytes())["payload"]
    return ImmutableStrategyEvidenceStore(
        root,
        clock=lambda: recorded_at,
    ).admit_checked(
        EvidenceCandidate(
            kind=envelope.kind,
            effective_at=envelope.effective_at,
            payload=payload,
        ),
        validate=lambda _snapshot, _envelope: None,
    )


def _authorization_replay_fixture(
    tmp_path,
    *,
    registration_after_staged=False,
    authorization_before_staged=False,
    duplicate_authorization=False,
):
    from tradingagents.strategy._immutable_evidence_store import (
        EvidenceCandidate,
        ImmutableStrategyEvidenceStore,
    )
    from tradingagents.strategy.paper_execution_authorization import (
        AuthorizedPaperOrderRequest,
        StrategyPaperExecutionAuthorizationLedger,
    )

    source_root, registration, promotion_evidence = (
        _durable_internal_evidence(tmp_path)
    )
    _, staged_intent = _stage_once(
        source_root,
        registration,
        promotion_evidence,
    )
    _, request = _authorize_once(source_root, staged_intent)
    snapshot = ImmutableStrategyEvidenceStore(source_root).verify()
    registration_envelope = next(
        envelope
        for envelope in snapshot
        if envelope.object_id == registration.registration_id
    )
    staged_envelope = next(
        envelope
        for envelope in snapshot
        if envelope.object_id == staged_intent.staged_intent_id
    )
    authorization_envelope = next(
        envelope
        for envelope in snapshot
        if envelope.object_id == request.authorization_id
    )
    target_root = tmp_path / "target-evidence"

    if authorization_before_staged:
        ordered = (
            (
                registration_envelope,
                dt.datetime(2030, 4, 1, 14, 0, 4, tzinfo=UTC),
            ),
            (
                authorization_envelope,
                dt.datetime(2030, 4, 1, 14, 1, 5, tzinfo=UTC),
            ),
            (
                staged_envelope,
                dt.datetime(2030, 4, 1, 14, 1, 6, tzinfo=UTC),
            ),
        )
    elif registration_after_staged:
        ordered = (
            (
                staged_envelope,
                dt.datetime(2030, 4, 1, 14, 0, 5, tzinfo=UTC),
            ),
            (
                registration_envelope,
                dt.datetime(2030, 4, 1, 14, 0, 6, tzinfo=UTC),
            ),
            (
                authorization_envelope,
                dt.datetime(2030, 4, 1, 14, 1, 5, tzinfo=UTC),
            ),
        )
    else:
        ordered = (
            (
                registration_envelope,
                dt.datetime(2029, 12, 31, 16, 0, tzinfo=UTC),
            ),
            (
                staged_envelope,
                dt.datetime(2030, 4, 1, 14, 0, 5, tzinfo=UTC),
            ),
            (
                authorization_envelope,
                dt.datetime(2030, 4, 1, 14, 1, 5, tzinfo=UTC),
            ),
        )
    for envelope, recorded_at in ordered:
        _admit_envelope_copy(
            target_root,
            envelope,
            recorded_at=recorded_at,
        )

    changed_request = None
    if duplicate_authorization:
        changed_payload = request.to_dict()
        changed_payload["paper_account_fingerprint"] = "a" * 64
        _reidentify_authorization_payload(changed_payload)
        changed_request = AuthorizedPaperOrderRequest.from_dict(
            changed_payload
        )
        _admission = ImmutableStrategyEvidenceStore(
            target_root,
            clock=lambda: dt.datetime(
                2030,
                4,
                1,
                14,
                1,
                6,
                tzinfo=UTC,
            ),
        ).admit_checked(
            EvidenceCandidate(
                kind="paper-execution-authorization",
                effective_at=changed_request.effective_at,
                payload={
                    key: value
                    for key, value in changed_request.to_dict().items()
                    if key
                    not in {
                        "authorization_id",
                        "effective_at",
                        "recorded_at",
                    }
                },
            ),
            validate=lambda _snapshot, _envelope: None,
        )

    ledger = StrategyPaperExecutionAuthorizationLedger(
        target_root,
        repo_root=REPO_ROOT,
        clock=lambda: dt.datetime(2030, 4, 1, 15, 0, tzinfo=UTC),
    )
    return ledger, request, changed_request


def test_verify_and_rebuild_return_journal_ordered_authorizations(tmp_path):
    # Break caught: the authorization ledger exposes admission but no strict,
    # journal-ordered replay surface for operators and recovery.
    ledger, request, _changed = _authorization_replay_fixture(tmp_path)

    assert ledger.verify() == (request,)
    assert ledger.rebuild() == (request,)


@pytest.mark.parametrize("operation", ("verify", "rebuild"))
def test_replay_rejects_authorization_before_staged_dependency(
    tmp_path,
    operation,
):
    # Break caught: replay resolves an authorization from a staged intent
    # appended later in the journal.
    ledger, _request, _changed = _authorization_replay_fixture(
        tmp_path,
        authorization_before_staged=True,
    )

    with pytest.raises(ValueError, match="staged intent"):
        getattr(ledger, operation)()


@pytest.mark.parametrize("operation", ("verify", "rebuild"))
def test_replay_rejects_registration_appended_after_staged_dependency(
    tmp_path,
    operation,
):
    # Break caught: a later registration is allowed to retroactively satisfy
    # the staged lineage of an earlier paper authorization.
    ledger, _request, _changed = _authorization_replay_fixture(
        tmp_path,
        registration_after_staged=True,
    )

    with pytest.raises(ValueError, match="registration"):
        getattr(ledger, operation)()


@pytest.mark.parametrize("operation", ("verify", "rebuild"))
def test_replay_rejects_two_authorizations_for_one_staged_intent(
    tmp_path,
    operation,
):
    # Break caught: direct-store history preserves two account meanings for
    # the same staged BUY.
    ledger, original, changed = _authorization_replay_fixture(
        tmp_path,
        duplicate_authorization=True,
    )
    assert changed is not None
    assert changed.authorization_id != original.authorization_id

    with pytest.raises(ValueError, match="already has"):
        getattr(ledger, operation)()


def _append_colliding_authorization_history(
    ledger,
    original_request,
    monkeypatch,
    *,
    collision_kind,
    leave_authorization_orphan=False,
):
    import tradingagents.strategy.paper_execution_authorization as module
    from tradingagents.strategy import StagedPaperIntent
    from tradingagents.strategy._immutable_evidence_store import (
        STAGED_PAPER_INTENT_KIND,
        EvidenceCandidate,
        ImmutableStrategyEvidenceStore,
    )
    from tradingagents.strategy.staged_intent import (
        _staged_intent_from_envelope,
    )

    snapshot = ledger._store.verify()
    original_staged = _staged_intent_from_envelope(
        next(
            envelope
            for envelope in snapshot
            if envelope.kind == STAGED_PAPER_INTENT_KIND
            and envelope.object_id == original_request.staged_intent_id
        )
    )
    staged_payload = original_staged.to_dict()
    staged_payload.update(
        {
            "session_date": "2030-04-02",
            "effective_at": "2030-04-01T14:01:06+00:00",
            "recorded_at": "2030-04-01T14:01:06+00:00",
        }
    )
    _reidentify_staged_payload(staged_payload)
    alternate_staged = StagedPaperIntent.from_dict(staged_payload)
    ImmutableStrategyEvidenceStore(
        ledger._store.root,
        clock=lambda: dt.datetime(
            2030,
            4,
            1,
            14,
            1,
            6,
            tzinfo=UTC,
        ),
    ).admit_checked(
        EvidenceCandidate(
            kind=STAGED_PAPER_INTENT_KIND,
            effective_at=alternate_staged.effective_at,
            payload={
                key: value
                for key, value in alternate_staged.to_dict().items()
                if key
                not in {
                    "staged_intent_id",
                    "effective_at",
                    "recorded_at",
                }
            },
        ),
        validate=lambda _snapshot, _envelope: None,
    )

    authorization_payload = original_request.to_dict()
    authorization_payload.update(
        {
            "staged_intent_id": alternate_staged.staged_intent_id,
            "staged_intent_sha256": hashlib.sha256(
                alternate_staged.canonical_json_bytes()
            ).hexdigest(),
            "session_date": alternate_staged.session_date,
            "effective_at": "2030-04-01T14:01:06+00:00",
            "recorded_at": "2030-04-01T14:01:07+00:00",
        }
    )
    logical_bytes = _canonical_test_bytes(
        _logical_material(authorization_payload)
    )
    if collision_kind == "logical":
        forced_digest = original_request.logical_order_sha256
    else:
        tail = "f" * 24
        if original_request.logical_order_sha256.endswith(tail):
            tail = "e" * 24
        forced_digest = (
            original_request.logical_order_sha256[:40] + tail
        )
    real_sha256 = hashlib.sha256

    class ForcedDigest:
        def digest(self):
            return bytes.fromhex(forced_digest)

        def hexdigest(self):
            return forced_digest

    def collision_sha256(data=b""):
        if data == logical_bytes:
            return ForcedDigest()
        return real_sha256(data)

    monkeypatch.setattr(hashlib, "sha256", collision_sha256)
    _reidentify_authorization_payload(authorization_payload)
    alternate_request = module.AuthorizedPaperOrderRequest.from_dict(
        authorization_payload
    )
    authorization_store = ImmutableStrategyEvidenceStore(
        ledger._store.root,
        clock=lambda: dt.datetime(
            2030,
            4,
            1,
            14,
            1,
            7,
            tzinfo=UTC,
        ),
    )
    candidate = EvidenceCandidate(
        kind="paper-execution-authorization",
        effective_at=alternate_request.effective_at,
        payload={
            key: value
            for key, value in alternate_request.to_dict().items()
            if key
            not in {
                "authorization_id",
                "effective_at",
                "recorded_at",
            }
        },
    )
    if leave_authorization_orphan:
        def crash(_path):
            raise RuntimeError("simulated same-client authorization crash")

        authorization_store._after_object_fsync = crash
        with pytest.raises(RuntimeError, match="same-client"):
            authorization_store.admit_checked(
                candidate,
                validate=lambda _snapshot, _envelope: None,
            )
    else:
        authorization_store.admit_checked(
            candidate,
            validate=lambda _snapshot, _envelope: None,
        )
    return alternate_request


def _durable_authorization_file_bytes(root):
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def _admit_staged_variant(
    root,
    source,
    *,
    session_date,
    effective_at,
    recorded_at,
):
    from tradingagents.strategy import StagedPaperIntent
    from tradingagents.strategy._immutable_evidence_store import (
        STAGED_PAPER_INTENT_KIND,
        EvidenceCandidate,
        ImmutableStrategyEvidenceStore,
    )

    payload = source.to_dict()
    payload.update(
        {
            "session_date": session_date,
            "effective_at": effective_at,
            "recorded_at": recorded_at,
        }
    )
    _reidentify_staged_payload(payload)
    staged = StagedPaperIntent.from_dict(payload)
    ImmutableStrategyEvidenceStore(
        root,
        clock=lambda: dt.datetime.fromisoformat(recorded_at),
    ).admit_checked(
        EvidenceCandidate(
            kind=STAGED_PAPER_INTENT_KIND,
            effective_at=staged.effective_at,
            payload=staged._evidence_payload(),
        ),
        validate=lambda _snapshot, _envelope: None,
    )
    return staged


@pytest.mark.parametrize(
    ("global_identity", "message"),
    (
        ("staged", "staged intent already has"),
        ("logical", "logical order digest"),
        ("client", "client_order_id"),
    ),
)
def test_prerequisite_cross_set_authorization_conflict_blocks_unrelated_candidate(
    tmp_path,
    monkeypatch,
    global_identity,
    message,
):
    # Break caught: admitted A and strict-valid orphan B build separate global
    # indexes, so later unrelated candidate C can write over their conflict.
    from tradingagents.strategy import AuthorizedPaperOrderRequest
    from tradingagents.strategy._immutable_evidence_store import (
        PAPER_EXECUTION_AUTHORIZATION_KIND,
        STAGED_PAPER_INTENT_KIND,
        EvidenceCandidate,
        ImmutableStrategyEvidenceStore,
    )
    from tradingagents.strategy.staged_intent import (
        _staged_intent_from_envelope,
    )

    ledger, admitted, _changed = _authorization_replay_fixture(tmp_path)
    snapshot = ledger._store.verify()
    admitted_staged = _staged_intent_from_envelope(
        next(
            envelope
            for envelope in snapshot
            if envelope.kind == STAGED_PAPER_INTENT_KIND
            and envelope.object_id == admitted.staged_intent_id
        )
    )
    if global_identity == "staged":
        orphan_payload = admitted.to_dict()
        orphan_payload["paper_account_fingerprint"] = "a" * 64
        _reidentify_authorization_payload(orphan_payload)
        orphan = AuthorizedPaperOrderRequest.from_dict(orphan_payload)
        orphan_store = ImmutableStrategyEvidenceStore(
            ledger._store.root,
            clock=lambda: dt.datetime(
                2030,
                4,
                1,
                14,
                1,
                6,
                tzinfo=UTC,
            ),
        )

        def crash(_path):
            raise RuntimeError("simulated staged-identity orphan")

        orphan_store._after_object_fsync = crash
        with pytest.raises(RuntimeError, match="staged-identity orphan"):
            orphan_store.admit_checked(
                EvidenceCandidate(
                    kind=PAPER_EXECUTION_AUTHORIZATION_KIND,
                    effective_at=orphan.effective_at,
                    payload=orphan._evidence_payload(),
                ),
                validate=lambda _snapshot, _envelope: None,
            )
    else:
        orphan = _append_colliding_authorization_history(
            ledger,
            admitted,
            monkeypatch,
            collision_kind=global_identity,
            leave_authorization_orphan=True,
        )

    ImmutableStrategyEvidenceStore(
        ledger._store.root,
        clock=lambda: dt.datetime(
            2030,
            4,
            1,
            14,
            1,
            8,
            tzinfo=UTC,
        ),
    ).admit_checked(
        EvidenceCandidate(
            kind="baseline-genome",
            effective_at="2030-04-01T14:01:08+00:00",
            payload={"later_unrelated": True},
        ),
        validate=lambda _snapshot, _envelope: None,
    )
    unrelated_staged = _admit_staged_variant(
        ledger._store.root,
        admitted_staged,
        session_date="2030-04-03",
        effective_at="2030-04-01T14:01:09+00:00",
        recorded_at="2030-04-01T14:01:09+00:00",
    )
    before = _durable_authorization_file_bytes(ledger._store.root)
    raw_account_id = " \tSensitive Candidate Account α\n "

    with pytest.raises(ValueError, match=message) as exc_info:
        _authorize_once(
            ledger._store.root,
            unrelated_staged,
            paper_account_id=raw_account_id,
            clock_time=dt.datetime(
                2030,
                4,
                1,
                14,
                1,
                11,
                tzinfo=UTC,
            ),
            effective_at=dt.datetime(
                2030,
                4,
                1,
                14,
                1,
                10,
                tzinfo=UTC,
            ),
        )

    error_text = str(exc_info.value)
    assert admitted.authorization_id != orphan.authorization_id
    assert unrelated_staged.staged_intent_id not in {
        admitted.staged_intent_id,
        orphan.staged_intent_id,
    }
    assert raw_account_id not in error_text
    assert raw_account_id.strip() not in error_text
    assert raw_account_id.encode("unicode_escape").decode() not in error_text
    assert _durable_authorization_file_bytes(ledger._store.root) == before


def test_prerequisite_malformed_authorization_orphan_is_neutral(tmp_path):
    # Break caught: domain-invalid authorization orphan parsing escapes the
    # narrow orphan error boundary and blocks a valid unrelated admission.
    from tradingagents.strategy._immutable_evidence_store import (
        PAPER_EXECUTION_AUTHORIZATION_KIND,
        EvidenceCandidate,
        ImmutableStrategyEvidenceStore,
    )

    root, registration, promotion_evidence = _durable_internal_evidence(
        tmp_path
    )
    _, staged_intent = _stage_once(
        root,
        registration,
        promotion_evidence,
    )
    malformed_payload = _authorization_payload(staged_intent)
    malformed_payload["client_order_id"] = "not-a-canonical-client-id"
    malformed_store = ImmutableStrategyEvidenceStore(
        root,
        clock=lambda: dt.datetime(
            2030,
            4,
            1,
            14,
            1,
            4,
            tzinfo=UTC,
        ),
    )

    def crash(_path):
        raise RuntimeError("simulated malformed authorization orphan")

    malformed_store._after_object_fsync = crash
    with pytest.raises(RuntimeError, match="malformed authorization orphan"):
        malformed_store.admit_checked(
            EvidenceCandidate(
                kind=PAPER_EXECUTION_AUTHORIZATION_KIND,
                effective_at=malformed_payload["effective_at"],
                payload={
                    key: value
                    for key, value in malformed_payload.items()
                    if key
                    not in {
                        "authorization_id",
                        "effective_at",
                        "recorded_at",
                    }
                },
            ),
            validate=lambda _snapshot, _envelope: None,
        )

    _ledger, request = _authorize_once(root, staged_intent)

    assert request.staged_intent_id == staged_intent.staged_intent_id


@pytest.mark.parametrize("operation", ("verify", "rebuild"))
@pytest.mark.parametrize(
    ("collision_kind", "message"),
    (
        ("logical", "logical order digest"),
        ("client", "client_order_id"),
    ),
)
def test_replay_rejects_full_logical_and_client_id_collisions(
    tmp_path,
    monkeypatch,
    operation,
    collision_kind,
    message,
):
    # Break caught: store-global replay indexes fail to distinguish full
    # logical material from the deliberately shortened client identity.
    ledger, original, _changed = _authorization_replay_fixture(tmp_path)
    alternate = _append_colliding_authorization_history(
        ledger,
        original,
        monkeypatch,
        collision_kind=collision_kind,
    )
    assert alternate.staged_intent_id != original.staged_intent_id
    if collision_kind == "client":
        assert alternate.logical_order_sha256 != (
            original.logical_order_sha256
        )
        assert alternate.client_order_id == original.client_order_id

    with pytest.raises(ValueError, match=message):
        getattr(ledger, operation)()


def test_strict_valid_same_client_orphan_blocks_exact_retry_before_new_bytes(
    tmp_path,
    monkeypatch,
):
    # Break caught: a strict-valid orphan for another full logical digest is
    # ignored because the candidate itself is an exact event-admitted retry.
    ledger, original, _changed = _authorization_replay_fixture(tmp_path)
    alternate = _append_colliding_authorization_history(
        ledger,
        original,
        monkeypatch,
        collision_kind="client",
        leave_authorization_orphan=True,
    )
    assert alternate.client_order_id == original.client_order_id
    before = {
        path.relative_to(ledger._store.root): path.read_bytes()
        for path in ledger._store.root.rglob("*")
        if path.is_file()
    }
    staged_envelope = next(
        envelope
        for envelope in ledger._store.verify()
        if envelope.object_id == original.staged_intent_id
    )
    from tradingagents.strategy.staged_intent import (
        _staged_intent_from_envelope,
    )

    staged_intent = _staged_intent_from_envelope(staged_envelope)
    with pytest.raises(ValueError, match="client_order_id"):
        _authorize_once(
            ledger._store.root,
            staged_intent,
            clock_time=dt.datetime(
                2030,
                4,
                1,
                14,
                1,
                8,
                tzinfo=UTC,
            ),
        )

    assert {
        path.relative_to(ledger._store.root): path.read_bytes()
        for path in ledger._store.root.rglob("*")
        if path.is_file()
    } == before


def test_replay_checks_runtime_exactly_twice_per_authorization(
    tmp_path,
    monkeypatch,
):
    # Break caught: replay trusts historical source identity without verifying
    # the currently loaded calculation bytes before and after each request.
    import tradingagents.strategy.paper_execution_authorization as module

    ledger, request, _changed = _authorization_replay_fixture(tmp_path)
    original_runtime = module.require_active_evaluation_runtime
    calls = []

    def counted_runtime(repo_root, registration):
        calls.append((repo_root, registration))
        return original_runtime(repo_root, registration)

    monkeypatch.setattr(
        module,
        "require_active_evaluation_runtime",
        counted_runtime,
    )

    assert ledger.verify() == (request,)
    assert len(calls) == 2
    assert all(repo_root == REPO_ROOT for repo_root, _ in calls)


def test_replay_rejects_runtime_change_between_bracketing_checks(
    tmp_path,
    monkeypatch,
):
    # Break caught: replay observes two different active calculation manifests
    # and still returns durable execution authority.
    import tradingagents.strategy.paper_execution_authorization as module

    ledger, _request, _changed = _authorization_replay_fixture(tmp_path)
    original_runtime = module.require_active_evaluation_runtime
    calls = 0

    def changed_runtime(*args, **kwargs):
        nonlocal calls
        calls += 1
        manifest = original_runtime(*args, **kwargs)
        if calls == 2:
            changed_file = dataclasses.replace(
                manifest.files[0],
                sha256="f" * 64,
            )
            return dataclasses.replace(
                manifest,
                files=(changed_file, *manifest.files[1:]),
            )
        return manifest

    monkeypatch.setattr(
        module,
        "require_active_evaluation_runtime",
        changed_runtime,
    )

    with pytest.raises(ValueError, match="runtime changed"):
        ledger.verify()
    assert calls == 2


def test_replay_accepts_expired_history_and_later_unrelated_event(tmp_path):
    # Break caught: recovery treats historical expiry as corruption or lets a
    # later unrelated evidence event alter authorization meaning.
    from tradingagents.strategy._immutable_evidence_store import (
        EvidenceCandidate,
    )

    ledger, request, _changed = _authorization_replay_fixture(tmp_path)
    ledger._store.admit_checked(
        EvidenceCandidate(
            kind="baseline-genome",
            effective_at="2030-04-01T14:14:01+00:00",
            payload={"later": "unrelated"},
        ),
        validate=lambda _snapshot, _envelope: None,
    )

    assert ledger.verify() == (request,)
    assert ledger.rebuild() == (request,)


def _authorization_imported_modules(source):
    tree = ast.parse(source)
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imported.add(node.module)
    return imported


def _authorization_forbidden_imports(source):
    forbidden_prefixes = {
        "brokers",
        "execution",
        "live_control",
        "live_gate",
        "promotion_sync",
        "cli",
        "requests",
        "httpx",
        "aiohttp",
        "openai",
        "anthropic",
        "tradingagents.brokers",
        "tradingagents.cli",
        "tradingagents.execution",
        "tradingagents.llm_clients",
        "tradingagents.policy.live_control",
        "tradingagents.policy.live_gate",
        "tradingagents.policy.promotion_sync",
    }
    imported = _authorization_imported_modules(source)
    return {
        imported_module
        for imported_module in imported
        for forbidden_prefix in forbidden_prefixes
        if imported_module == forbidden_prefix
        or imported_module.startswith(f"{forbidden_prefix}.")
    }


def test_forbidden_import_guard_detects_fully_qualified_paths():
    # Break caught: checking only a first path component misses fully qualified
    # TradingAgents broker, execution, gate, sync, CLI, and model imports.
    source = """
import tradingagents.brokers.alpaca
from tradingagents.execution.orders import submit
from tradingagents.policy.live_control import refresh
from tradingagents.policy.live_gate import require_gate
from tradingagents.policy.promotion_sync import sync
from tradingagents.cli.paper import run
from tradingagents.llm_clients.openai import client
import httpx
"""

    assert _authorization_forbidden_imports(source) == {
        "tradingagents.brokers.alpaca",
        "tradingagents.execution.orders",
        "tradingagents.policy.live_control",
        "tradingagents.policy.live_gate",
        "tradingagents.policy.promotion_sync",
        "tradingagents.cli.paper",
        "tradingagents.llm_clients.openai",
        "httpx",
    }


def test_authorization_module_import_and_call_isolation():
    # Break caught: immutable authorization evidence acquires broker, network,
    # model, or order-submission behavior.
    source = (
        REPO_ROOT
        / "tradingagents"
        / "strategy"
        / "paper_execution_authorization.py"
    ).read_text()
    tree = ast.parse(source)
    called_names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                called_names.add(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                called_names.add(node.func.attr)

    assert _authorization_forbidden_imports(source) == set()
    assert called_names.isdisjoint(
        {"submit_order", "cancel_order", "replace_order"}
    )


def test_authorization_forbidden_authority_literals_are_absent():
    # Break caught: dormant live or broad-trade hooks enter the paper-only
    # immutable authorization module.
    tree = ast.parse(
        (
            REPO_ROOT
            / "tradingagents"
            / "strategy"
            / "paper_execution_authorization.py"
        ).read_text()
    )
    exact_tokens = {
        node.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Name)
    }
    exact_tokens.update(
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
    )
    exact_tokens.update(
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and type(node.value) is str
    )

    for forbidden in (
        "submit_order",
        "cancel_order",
        "replace_order",
        "TA_LIVE_SUBMIT",
        "authorized_normal_trade_intent",
    ):
        assert forbidden not in exact_tokens


def test_backdated_exact_retry_rejects_without_event_or_pointer_change(
    tmp_path,
):
    # Break caught: an exact retry can move durable first-seen time backward or
    # repair derived state under a clock older than the authorization.
    root, registration, promotion_evidence = _durable_internal_evidence(
        tmp_path
    )
    _, staged_intent = _stage_once(
        root,
        registration,
        promotion_evidence,
    )
    _, request = _authorize_once(root, staged_intent)
    before = {
        path.relative_to(root): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }

    with pytest.raises(ValueError, match="earlier"):
        _authorize_once(
            root,
            staged_intent,
            clock_time=dt.datetime(
                2030,
                4,
                1,
                14,
                1,
                4,
                tzinfo=UTC,
            ),
        )

    after = {
        path.relative_to(root): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }
    assert request.recorded_at == "2030-04-01T14:01:05+00:00"
    assert after == before
