from __future__ import annotations

import ast
import dataclasses
import datetime as dt
import hashlib
import importlib
import json
import sys
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError
from decimal import Decimal, localcontext
from pathlib import Path

import pytest

from tests.test_strategy_staged_intent import (
    REPO_ROOT,
    UTC,
    _durable_internal_evidence,
    _stage_once,
)


@pytest.fixture(autouse=True)
def _treat_loaded_repo_as_clean_for_registration(monkeypatch):
    import tradingagents.strategy.promotion_evidence as module

    original = module._git_text

    def controlled_git_text(repo: Path, *args: str) -> str:
        if (
            repo.resolve() == REPO_ROOT.resolve()
            and args == ("status", "--porcelain")
        ):
            return ""
        return original(repo, *args)

    monkeypatch.setattr(module, "_git_text", controlled_git_text)


def test_shadow_attestation_module_exists() -> None:
    shadow_attestation = importlib.import_module(
        "tradingagents.strategy.shadow_attestation"
    )

    assert shadow_attestation is not None


def _paper_order_receipt_payload() -> dict[str, object]:
    return {
        "schema_version": 1,
        "authorization_id": "paper-execution-authorization-" + "1" * 64,
        "authorization_sha256": "2" * 64,
        "logical_order_sha256": "3" * 64,
        "client_order_id": "ta-p-" + "3" * 40,
        "broker_order_id": "paper-broker-order-123",
        "paper_account_fingerprint": "4" * 64,
        "account_environment": "paper",
        "symbol": "AAPL",
        "side": "buy",
        "order_type": "limit",
        "tif": "day",
        "requested_notional_usd": "1000.00",
        "requested_limit_price": "190.25",
        "status": "filled",
        "filled_qty": "5",
        "filled_avg_price": "190",
        "fees_usd": "0.15",
        "submitted_at": "2026-07-20T14:30:00+00:00",
        "last_seen_at": "2026-07-20T14:31:00+00:00",
        "submitted_by_role": "execution_operator",
        "analysis_only": True,
        "paper_only": True,
        "execution_authority": "none",
        "can_submit_orders": False,
    }


def _paper_reconciliation_receipt_payload() -> dict[str, object]:
    return {
        "schema_version": 1,
        "authorization_id": "paper-execution-authorization-" + "1" * 64,
        "authorization_sha256": "2" * 64,
        "logical_order_sha256": "3" * 64,
        "client_order_id": "ta-p-" + "3" * 40,
        "broker_order_id": "paper-broker-order-123",
        "paper_account_fingerprint": "4" * 64,
        "observed_status": "filled",
        "observed_symbol": "AAPL",
        "observed_side": "buy",
        "observed_order_type": "limit",
        "observed_tif": "day",
        "observed_requested_notional_usd": "1000.00",
        "observed_requested_limit_price": "190.25",
        "observed_filled_qty": "5",
        "observed_filled_avg_price": "190",
        "observed_fees_usd": "0.15",
        "checked_at": "2026-07-20T14:31:00+00:00",
        "verified_by_role": "integrity_verifier",
        "read_only": True,
        "broker_write_calls": 0,
        "analysis_only": True,
        "paper_only": True,
        "execution_authority": "none",
        "can_submit_orders": False,
    }


def _canonical_test_bytes(payload: object) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _reidentify_journal_payload(
    payload: dict[str, object],
    *,
    kind: str,
    id_field: str,
) -> None:
    evidence_payload = {
        key: value
        for key, value in payload.items()
        if key not in {id_field, "effective_at", "recorded_at"}
    }
    retry_material = {
        "kind": kind,
        "effective_at": payload["effective_at"],
        "payload": evidence_payload,
    }
    payload[id_field] = (
        f"{kind}-{hashlib.sha256(_canonical_test_bytes(retry_material)).hexdigest()}"
    )


def _hold_observation_payload() -> dict[str, object]:
    payload = {
        "schema_version": 1,
        "shadow_observation_id": "",
        "staged_intent_id": "staged-paper-intent-" + "6" * 64,
        "staged_intent_sha256": "7" * 64,
        "authorization_id": None,
        "authorization_sha256": None,
        "paper_account_fingerprint": None,
        "promotion_evidence_id": "promotion-evidence-" + "8" * 64,
        "genome_id": "genome-current-aggressive-" + "9" * 64,
        "genome_canonical_sha256": "9" * 64,
        "evaluation_code_commit": "a" * 40,
        "evaluation_runtime_sha256": "b" * 64,
        "session_date": "2026-07-20",
        "observed_at": "2026-07-20T14:30:00+00:00",
        "decision_action": "hold-cash",
        "paper_order_receipt": None,
        "reconciliation_receipt": None,
        "receipt_sha256": None,
        "reconciliation_sha256": None,
        "adverse_fill_vs_reference_fraction": "0",
        "gates": [["no_order_expected", True]],
        "issues": [],
        "operationally_reconciled": True,
        "verified_by_role": "integrity_verifier",
        "effective_at": "2026-07-20T14:30:00+00:00",
        "recorded_at": "2026-07-20T14:31:00+00:00",
        "analysis_only": True,
        "paper_only": True,
        "execution_authority": "none",
        "can_submit_orders": False,
    }
    _reidentify_journal_payload(
        payload,
        kind="paper-shadow-observation",
        id_field="shadow_observation_id",
    )
    return payload


def _buy_observation_payload() -> dict[str, object]:
    payload = _hold_observation_payload()
    order_receipt = _paper_order_receipt_payload()
    reconciliation = _paper_reconciliation_receipt_payload()
    payload.update(
        {
            "authorization_id": order_receipt["authorization_id"],
            "authorization_sha256": order_receipt["authorization_sha256"],
            "paper_account_fingerprint": order_receipt[
                "paper_account_fingerprint"
            ],
            "decision_action": "buy",
            "paper_order_receipt": order_receipt,
            "reconciliation_receipt": reconciliation,
            "receipt_sha256": hashlib.sha256(
                _canonical_test_bytes(order_receipt)
            ).hexdigest(),
            "reconciliation_sha256": hashlib.sha256(
                _canonical_test_bytes(reconciliation)
            ).hexdigest(),
            "gates": [
                ["terminal_filled", True],
                ["fill_respected_limit", True],
                ["operationally_reconciled", True],
            ],
        }
    )
    _reidentify_journal_payload(
        payload,
        kind="paper-shadow-observation",
        id_field="shadow_observation_id",
    )
    return payload


def _shadow_attestation_payload() -> dict[str, object]:
    gate_names = (
        "internal_evidence_complete",
        "minimum_tracked_sessions",
        "all_intents_current_when_observed",
        "all_buy_intents_paper_only",
        "all_order_fields_match",
        "all_buy_intents_terminal_filled",
        "all_reconciliations_clean",
        "at_least_one_reconciled_buy",
    )
    payload = {
        "schema_version": 1,
        "shadow_attestation_id": "",
        "registration_id": "evaluation-registration-" + "d" * 64,
        "promotion_evidence_id": "promotion-evidence-" + "8" * 64,
        "promotion_evidence_sha256": "e" * 64,
        "genome_id": "genome-current-aggressive-" + "9" * 64,
        "genome_canonical_sha256": "9" * 64,
        "evaluation_code_commit": "a" * 40,
        "evaluation_runtime_sha256": "b" * 64,
        "paper_account_fingerprint": "4" * 64,
        "shadow_observation_ids": [
            _hold_observation_payload()["shadow_observation_id"]
        ],
        "shadow_observation_sha256s": ["f" * 64],
        "first_session_date": "2026-07-20",
        "last_session_date": "2026-07-20",
        "tracked_sessions": 1,
        "total_intents": 1,
        "hold_intents": 0,
        "buy_intents": 1,
        "reconciled_buy_intents": 1,
        "filled_buy_intents": 1,
        "total_requested_notional_usd": "1000",
        "total_filled_notional_usd": "950",
        "total_fees_usd": "0.15",
        "worst_adverse_fill_vs_reference_fraction": "0",
        "gates": [[name, True] for name in gate_names],
        "issues": [],
        "shadow_sessions_sufficient": True,
        "reconciliation_confirmed": True,
        "assembled_by_role": "integrity_verifier",
        "effective_at": "2026-07-20T14:30:00+00:00",
        "recorded_at": "2026-07-20T14:31:00+00:00",
        "analysis_only": True,
        "paper_only": True,
        "execution_authority": "none",
        "can_submit_orders": False,
    }
    _reidentify_journal_payload(
        payload,
        kind="paper-shadow-attestation",
        id_field="shadow_attestation_id",
    )
    return payload


def test_paper_order_receipt_has_strict_canonical_round_trip() -> None:
    module = importlib.import_module("tradingagents.strategy.shadow_attestation")
    payload = _paper_order_receipt_payload()

    receipt = module.PaperOrderReceipt.from_dict(payload)

    assert receipt.to_dict() == payload
    assert receipt.canonical_json_bytes() == json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


@pytest.mark.parametrize("key", ["schema_version", "broker_order_id", "status"])
def test_paper_order_receipt_rejects_missing_schema_key(key: str) -> None:
    module = importlib.import_module("tradingagents.strategy.shadow_attestation")
    payload = _paper_order_receipt_payload()
    del payload[key]

    with pytest.raises((TypeError, ValueError)):
        module.PaperOrderReceipt.from_dict(payload)


def test_paper_order_receipt_rejects_unknown_schema_key() -> None:
    module = importlib.import_module("tradingagents.strategy.shadow_attestation")
    payload = _paper_order_receipt_payload()
    payload["unexpected"] = "value"

    with pytest.raises((TypeError, ValueError)):
        module.PaperOrderReceipt.from_dict(payload)


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("schema_version", 2),
        ("account_environment", "live"),
        ("side", "sell"),
        ("order_type", "market"),
        ("tif", "gtc"),
        ("analysis_only", False),
        ("paper_only", False),
        ("execution_authority", "paper"),
        ("can_submit_orders", True),
    ],
)
def test_paper_order_receipt_rejects_nonfixed_schema_value(
    key: str,
    value: object,
) -> None:
    module = importlib.import_module("tradingagents.strategy.shadow_attestation")
    payload = _paper_order_receipt_payload()
    payload[key] = value

    with pytest.raises((TypeError, ValueError)):
        module.PaperOrderReceipt.from_dict(payload)


def test_reconciliation_receipt_has_strict_canonical_round_trip() -> None:
    module = importlib.import_module("tradingagents.strategy.shadow_attestation")
    payload = _paper_reconciliation_receipt_payload()

    receipt = module.PaperReconciliationReceipt.from_dict(payload)

    assert receipt.to_dict() == payload
    assert receipt.canonical_json_bytes() == json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


@pytest.mark.parametrize(
    "key",
    ["schema_version", "broker_order_id", "broker_write_calls"],
)
def test_reconciliation_receipt_rejects_missing_schema_key(key: str) -> None:
    module = importlib.import_module("tradingagents.strategy.shadow_attestation")
    payload = _paper_reconciliation_receipt_payload()
    del payload[key]

    with pytest.raises((TypeError, ValueError)):
        module.PaperReconciliationReceipt.from_dict(payload)


def test_reconciliation_receipt_rejects_unknown_schema_key() -> None:
    module = importlib.import_module("tradingagents.strategy.shadow_attestation")
    payload = _paper_reconciliation_receipt_payload()
    payload["unexpected"] = "value"

    with pytest.raises((TypeError, ValueError)):
        module.PaperReconciliationReceipt.from_dict(payload)


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("schema_version", 2),
        ("read_only", False),
        ("broker_write_calls", 1),
        ("analysis_only", False),
        ("paper_only", False),
        ("execution_authority", "paper"),
        ("can_submit_orders", True),
    ],
)
def test_reconciliation_receipt_rejects_nonfixed_schema_value(
    key: str,
    value: object,
) -> None:
    module = importlib.import_module("tradingagents.strategy.shadow_attestation")
    payload = _paper_reconciliation_receipt_payload()
    payload[key] = value

    with pytest.raises((TypeError, ValueError)):
        module.PaperReconciliationReceipt.from_dict(payload)


class _StringSubclass(str):
    pass


@pytest.mark.parametrize(
    ("factory_name", "payload_factory", "field_name", "bad_value"),
    [
        (
            "PaperOrderReceipt",
            _paper_order_receipt_payload,
            "authorization_id",
            _StringSubclass("paper-execution-authorization-" + "1" * 64),
        ),
        (
            "PaperReconciliationReceipt",
            _paper_reconciliation_receipt_payload,
            "verified_by_role",
            _StringSubclass("integrity_verifier"),
        ),
        (
            "AdmittedPaperShadowObservation",
            _hold_observation_payload,
            "session_date",
            _StringSubclass("2026-07-20"),
        ),
        (
            "StrategyShadowAttestation",
            _shadow_attestation_payload,
            "assembled_by_role",
            _StringSubclass("integrity_verifier"),
        ),
    ],
)
def test_strict_type_rejects_string_subclasses(
    factory_name: str,
    payload_factory: object,
    field_name: str,
    bad_value: object,
) -> None:
    module = importlib.import_module("tradingagents.strategy.shadow_attestation")
    payload = payload_factory()  # type: ignore[operator]
    payload[field_name] = bad_value

    with pytest.raises((TypeError, ValueError)):
        getattr(module, factory_name).from_dict(payload)


@pytest.mark.parametrize(
    ("factory_name", "payload_factory", "field_name", "bad_value"),
    [
        (
            "PaperOrderReceipt",
            _paper_order_receipt_payload,
            "schema_version",
            True,
        ),
        (
            "PaperReconciliationReceipt",
            _paper_reconciliation_receipt_payload,
            "broker_write_calls",
            False,
        ),
        (
            "StrategyShadowAttestation",
            _shadow_attestation_payload,
            "tracked_sessions",
            True,
        ),
        (
            "StrategyShadowAttestation",
            _shadow_attestation_payload,
            "total_intents",
            1.0,
        ),
    ],
)
def test_strict_type_rejects_bool_and_float_as_int(
    factory_name: str,
    payload_factory: object,
    field_name: str,
    bad_value: object,
) -> None:
    module = importlib.import_module("tradingagents.strategy.shadow_attestation")
    payload = payload_factory()  # type: ignore[operator]
    payload[field_name] = bad_value

    with pytest.raises((TypeError, ValueError)):
        getattr(module, factory_name).from_dict(payload)


def test_constructor_domain_rejects_list_gates() -> None:
    module = importlib.import_module("tradingagents.strategy.shadow_attestation")
    payload = _hold_observation_payload()
    payload["gates"] = (("no_order_expected", True),)
    payload["issues"] = ()
    observation = module.AdmittedPaperShadowObservation.from_dict(
        _hold_observation_payload()
    )
    constructor_values = {
        key: getattr(observation, key)
        for key in _hold_observation_payload()
        if key
        not in {
            "schema_version",
            "analysis_only",
            "paper_only",
            "execution_authority",
            "can_submit_orders",
        }
    }
    constructor_values["gates"] = [["no_order_expected", True]]

    with pytest.raises((TypeError, ValueError)):
        module.AdmittedPaperShadowObservation(**constructor_values)


def test_gate_order_rejects_duplicate_or_reordered_attestation_gates() -> None:
    module = importlib.import_module("tradingagents.strategy.shadow_attestation")
    payload = _shadow_attestation_payload()
    payload["gates"][0], payload["gates"][1] = (  # type: ignore[index]
        payload["gates"][1],  # type: ignore[index]
        payload["gates"][0],  # type: ignore[index]
    )

    with pytest.raises((TypeError, ValueError)):
        module.StrategyShadowAttestation.from_dict(payload)

    duplicate = _shadow_attestation_payload()
    duplicate["gates"][1] = duplicate["gates"][0]  # type: ignore[index]
    with pytest.raises((TypeError, ValueError)):
        module.StrategyShadowAttestation.from_dict(duplicate)


def test_issue_order_rejects_nonderived_or_duplicate_issues() -> None:
    module = importlib.import_module("tradingagents.strategy.shadow_attestation")
    payload = _shadow_attestation_payload()
    payload["gates"][1][1] = False  # type: ignore[index]
    payload["gates"][5][1] = False  # type: ignore[index]
    payload["issues"] = [
        "buy_intent_not_terminal_filled",
        "insufficient_shadow_sessions",
    ]
    payload["shadow_sessions_sufficient"] = False
    payload["reconciliation_confirmed"] = False

    with pytest.raises((TypeError, ValueError)):
        module.StrategyShadowAttestation.from_dict(payload)

    payload["issues"] = [
        "insufficient_shadow_sessions",
        "insufficient_shadow_sessions",
        "buy_intent_not_terminal_filled",
    ]
    with pytest.raises((TypeError, ValueError)):
        module.StrategyShadowAttestation.from_dict(payload)


def test_constructor_domain_models_are_frozen() -> None:
    module = importlib.import_module("tradingagents.strategy.shadow_attestation")
    receipt = module.PaperOrderReceipt.from_dict(_paper_order_receipt_payload())

    with pytest.raises(FrozenInstanceError):
        receipt.status = "rejected"


@pytest.mark.parametrize(
    "broker_order_id",
    [
        "",
        " ",
        "\tbroker",
        "broker\n",
        " broker",
        "broker ",
        "broker\x00id",
        "broker\x1fid",
        "x" * 129,
        "é" * 65,
    ],
)
@pytest.mark.parametrize(
    "payload_factory",
    [_paper_order_receipt_payload, _paper_reconciliation_receipt_payload],
)
def test_broker_order_id_rejects_blank_control_or_oversized_values(
    payload_factory: object,
    broker_order_id: str,
) -> None:
    module = importlib.import_module("tradingagents.strategy.shadow_attestation")
    payload = payload_factory()  # type: ignore[operator]
    payload["broker_order_id"] = broker_order_id
    receipt_type = (
        module.PaperOrderReceipt
        if "status" in payload
        else module.PaperReconciliationReceipt
    )

    with pytest.raises((TypeError, ValueError)):
        receipt_type.from_dict(payload)


def test_broker_order_id_accepts_printable_unicode_within_byte_bound() -> None:
    module = importlib.import_module("tradingagents.strategy.shadow_attestation")
    payload = _paper_order_receipt_payload()
    payload["broker_order_id"] = "ordre-papier-é"

    receipt = module.PaperOrderReceipt.from_dict(payload)

    assert receipt.broker_order_id == "ordre-papier-é"


def test_broker_order_id_must_match_between_buy_receipts() -> None:
    module = importlib.import_module("tradingagents.strategy.shadow_attestation")
    payload = _buy_observation_payload()
    payload["reconciliation_receipt"]["broker_order_id"] = (  # type: ignore[index]
        "different-paper-order"
    )

    with pytest.raises((TypeError, ValueError)):
        module.AdmittedPaperShadowObservation.from_dict(payload)


def _durable_buy_case(tmp_path):
    from tests.test_strategy_paper_execution_authorization import _authorize_once

    root, registration, promotion = _durable_internal_evidence(tmp_path)
    _, staged = _stage_once(root, registration, promotion)
    _, authorization = _authorize_once(root, staged)
    module = importlib.import_module("tradingagents.strategy.shadow_attestation")
    authorization_sha256 = hashlib.sha256(
        authorization.canonical_json_bytes()
    ).hexdigest()
    order_payload = _paper_order_receipt_payload()
    order_payload.update(
        {
            "authorization_id": authorization.authorization_id,
            "authorization_sha256": authorization_sha256,
            "logical_order_sha256": authorization.logical_order_sha256,
            "client_order_id": authorization.client_order_id,
            "paper_account_fingerprint": (
                authorization.paper_account_fingerprint
            ),
            "symbol": authorization.symbol,
            "requested_notional_usd": (
                authorization.requested_notional_usd
            ),
            "requested_limit_price": authorization.requested_limit_price,
            "filled_qty": "0.9",
            "filled_avg_price": "100",
            "submitted_at": "2030-04-01T14:01:05+00:00",
            "last_seen_at": "2030-04-01T14:02:00+00:00",
            "submitted_by_role": authorization.owner_role,
        }
    )
    reconciliation_payload = _paper_reconciliation_receipt_payload()
    reconciliation_payload.update(
        {
            "authorization_id": authorization.authorization_id,
            "authorization_sha256": authorization_sha256,
            "logical_order_sha256": authorization.logical_order_sha256,
            "client_order_id": authorization.client_order_id,
            "paper_account_fingerprint": (
                authorization.paper_account_fingerprint
            ),
            "observed_symbol": authorization.symbol,
            "observed_requested_notional_usd": (
                authorization.requested_notional_usd
            ),
            "observed_requested_limit_price": (
                authorization.requested_limit_price
            ),
            "observed_filled_qty": "0.9",
            "observed_filled_avg_price": "100",
            "checked_at": "2030-04-01T14:02:00+00:00",
        }
    )
    return (
        root,
        registration,
        promotion,
        staged,
        authorization,
        module.PaperOrderReceipt.from_dict(order_payload),
        module.PaperReconciliationReceipt.from_dict(reconciliation_payload),
    )


def _receipt_pair_for_authorization(
    authorization,
    *,
    submitted_at: str,
    last_seen_at: str,
    checked_at: str,
    status: str = "filled",
    broker_order_id: str = "paper-broker-order-123",
):
    module = importlib.import_module("tradingagents.strategy.shadow_attestation")
    authorization_sha256 = hashlib.sha256(
        authorization.canonical_json_bytes()
    ).hexdigest()
    order_payload = _paper_order_receipt_payload()
    order_payload.update(
        {
            "authorization_id": authorization.authorization_id,
            "authorization_sha256": authorization_sha256,
            "logical_order_sha256": authorization.logical_order_sha256,
            "client_order_id": authorization.client_order_id,
            "broker_order_id": broker_order_id,
            "paper_account_fingerprint": (
                authorization.paper_account_fingerprint
            ),
            "symbol": authorization.symbol,
            "requested_notional_usd": (
                authorization.requested_notional_usd
            ),
            "requested_limit_price": authorization.requested_limit_price,
            "status": status,
            "filled_qty": "0.9",
            "filled_avg_price": "100",
            "submitted_at": submitted_at,
            "last_seen_at": last_seen_at,
            "submitted_by_role": authorization.owner_role,
        }
    )
    reconciliation_payload = _paper_reconciliation_receipt_payload()
    reconciliation_payload.update(
        {
            "authorization_id": authorization.authorization_id,
            "authorization_sha256": authorization_sha256,
            "logical_order_sha256": authorization.logical_order_sha256,
            "client_order_id": authorization.client_order_id,
            "broker_order_id": broker_order_id,
            "paper_account_fingerprint": (
                authorization.paper_account_fingerprint
            ),
            "observed_status": status,
            "observed_symbol": authorization.symbol,
            "observed_requested_notional_usd": (
                authorization.requested_notional_usd
            ),
            "observed_requested_limit_price": (
                authorization.requested_limit_price
            ),
            "observed_filled_qty": "0.9",
            "observed_filled_avg_price": "100",
            "checked_at": checked_at,
        }
    )
    return (
        module.PaperOrderReceipt.from_dict(order_payload),
        module.PaperReconciliationReceipt.from_dict(reconciliation_payload),
    )


def test_repo_root_is_required_by_shadow_ledger(tmp_path) -> None:
    module = importlib.import_module("tradingagents.strategy.shadow_attestation")

    with pytest.raises(TypeError):
        module.StrategyShadowEvidenceLedger(tmp_path / "evidence")


def test_repo_root_rejects_wrong_root_before_shadow_event(tmp_path) -> None:
    (
        root,
        _,
        _,
        staged,
        authorization,
        receipt,
        reconciliation,
    ) = _durable_buy_case(tmp_path)
    module = importlib.import_module("tradingagents.strategy.shadow_attestation")
    before = (root / "events.jsonl").read_bytes()
    ledger = module.StrategyShadowEvidenceLedger(
        root,
        repo_root=tmp_path / "not-the-repository",
        clock=lambda: dt.datetime(2030, 4, 1, 14, 2, 5, tzinfo=UTC),
    )

    with pytest.raises((TypeError, ValueError)):
        ledger.admit_observation(
            staged_intent=staged,
            authorization=authorization,
            observed_at=dt.datetime(2030, 4, 1, 14, 2, tzinfo=UTC),
            paper_order_receipt=receipt,
            reconciliation_receipt=reconciliation,
            actor_role="integrity_verifier",
        )

    assert (root / "events.jsonl").read_bytes() == before


def test_runtime_bracket_wraps_buy_candidate_outside_callbacks(
    tmp_path,
    monkeypatch,
) -> None:
    (
        root,
        _,
        _,
        staged,
        authorization,
        receipt,
        reconciliation,
    ) = _durable_buy_case(tmp_path)
    module = importlib.import_module("tradingagents.strategy.shadow_attestation")
    import tradingagents.strategy._immutable_evidence_store as store_module

    original = module.require_active_evaluation_runtime
    calls: list[tuple[Path, bool]] = []

    def runtime_spy(repo_root, registration):
        calls.append(
            (
                Path(repo_root),
                bool(
                    getattr(
                        store_module._VALIDATOR_ACTIVITY,
                        "active",
                        False,
                    )
                ),
            )
        )
        return original(repo_root, registration)

    monkeypatch.setattr(
        module,
        "require_active_evaluation_runtime",
        runtime_spy,
    )
    ledger = module.StrategyShadowEvidenceLedger(
        root,
        repo_root=REPO_ROOT,
        clock=lambda: dt.datetime(2030, 4, 1, 14, 2, 5, tzinfo=UTC),
    )

    observation = ledger.admit_observation(
        staged_intent=staged,
        authorization=authorization,
        observed_at=dt.datetime(2030, 4, 1, 14, 2, tzinfo=UTC),
        paper_order_receipt=receipt,
        reconciliation_receipt=reconciliation,
        actor_role="integrity_verifier",
    )

    assert observation is not None
    assert calls == [(REPO_ROOT, False), (REPO_ROOT, False)]


def _durable_hold_case(tmp_path):
    root, registration, promotion = _durable_internal_evidence(tmp_path)
    _, staged = _stage_once(
        root,
        registration,
        promotion,
        market_session="closed",
    )
    assert staged.decision.action.value == "hold-cash"
    return root, registration, promotion, staged


def test_hold_admits_observation_without_any_order_fact(tmp_path) -> None:
    root, _, _, staged = _durable_hold_case(tmp_path)
    module = importlib.import_module("tradingagents.strategy.shadow_attestation")
    before_lines = (root / "events.jsonl").read_text().splitlines()
    ledger = module.StrategyShadowEvidenceLedger(
        root,
        repo_root=REPO_ROOT,
        clock=lambda: dt.datetime(2030, 4, 1, 14, 2, 5, tzinfo=UTC),
    )

    observation = ledger.admit_observation(
        staged_intent=staged,
        authorization=None,
        observed_at=dt.datetime(2030, 4, 1, 14, 2, tzinfo=UTC),
        paper_order_receipt=None,
        reconciliation_receipt=None,
        actor_role="integrity_verifier",
    )

    assert observation is not None
    assert observation.staged_intent_id == staged.staged_intent_id
    assert observation.decision_action == "hold-cash"
    assert observation.authorization_id is None
    assert observation.paper_order_receipt is None
    assert observation.reconciliation_receipt is None
    assert observation.gates == (("no_order_expected", True),)
    assert observation.issues == ()
    assert observation.operationally_reconciled is True
    assert observation.verified_by_role == "integrity_verifier"
    assert observation.observed_at == "2030-04-01T14:02:00+00:00"
    assert observation.effective_at == observation.observed_at
    assert observation.recorded_at == "2030-04-01T14:02:05+00:00"
    after_lines = (root / "events.jsonl").read_text().splitlines()
    assert len(after_lines) == len(before_lines) + 1
    assert json.loads(after_lines[-1])["kind"] == (
        "paper-shadow-observation"
    )


def test_hold_rejects_role_drift_and_order_facts_without_event(tmp_path) -> None:
    root, _, _, staged = _durable_hold_case(tmp_path)
    module = importlib.import_module("tradingagents.strategy.shadow_attestation")
    before = (root / "events.jsonl").read_bytes()
    ledger = module.StrategyShadowEvidenceLedger(
        root,
        repo_root=REPO_ROOT,
        clock=lambda: dt.datetime(2030, 4, 1, 14, 2, 5, tzinfo=UTC),
    )

    with pytest.raises(ValueError, match="integrity_verifier"):
        ledger.admit_observation(
            staged_intent=staged,
            authorization=None,
            observed_at=dt.datetime(2030, 4, 1, 14, 2, tzinfo=UTC),
            paper_order_receipt=None,
            reconciliation_receipt=None,
            actor_role="execution_operator",
        )
    receipt = importlib.import_module(
        "tradingagents.strategy.shadow_attestation"
    ).PaperOrderReceipt.from_dict(_paper_order_receipt_payload())
    with pytest.raises(ValueError, match="HOLD"):
        ledger.admit_observation(
            staged_intent=staged,
            authorization=None,
            observed_at=dt.datetime(2030, 4, 1, 14, 2, tzinfo=UTC),
            paper_order_receipt=receipt,
            reconciliation_receipt=None,
            actor_role="integrity_verifier",
        )

    assert (root / "events.jsonl").read_bytes() == before


def test_hold_runtime_bracket_is_exact_and_outside_store_callbacks(
    tmp_path,
    monkeypatch,
) -> None:
    root, _, _, staged = _durable_hold_case(tmp_path)
    module = importlib.import_module("tradingagents.strategy.shadow_attestation")
    import tradingagents.strategy._immutable_evidence_store as store_module

    original = module.require_active_evaluation_runtime
    calls: list[bool] = []

    def runtime_spy(repo_root, registration):
        calls.append(
            bool(
                getattr(store_module._VALIDATOR_ACTIVITY, "active", False)
            )
        )
        return original(repo_root, registration)

    monkeypatch.setattr(
        module,
        "require_active_evaluation_runtime",
        runtime_spy,
    )
    ledger = module.StrategyShadowEvidenceLedger(
        root,
        repo_root=REPO_ROOT,
        clock=lambda: dt.datetime(2030, 4, 1, 14, 2, 5, tzinfo=UTC),
    )

    observation = ledger.admit_observation(
        staged_intent=staged,
        authorization=None,
        observed_at=dt.datetime(2030, 4, 1, 14, 2, tzinfo=UTC),
        paper_order_receipt=None,
        reconciliation_receipt=None,
        actor_role="integrity_verifier",
    )

    assert observation is not None
    assert calls == [False, False]


def test_review_fix_runtime_brackets_partial_assembly_verify_rebuild(
    tmp_path,
    monkeypatch,
) -> None:
    (
        root,
        _,
        promotion,
        staged,
        authorization,
        receipt,
        reconciliation,
    ) = _durable_buy_case(tmp_path)
    module = importlib.import_module("tradingagents.strategy.shadow_attestation")
    import tradingagents.strategy._immutable_evidence_store as store_module

    original = module.require_active_evaluation_runtime
    calls: list[bool] = []

    def runtime_spy(repo_root, registration):
        calls.append(
            bool(
                getattr(
                    store_module._VALIDATOR_ACTIVITY,
                    "active",
                    False,
                )
            )
        )
        return original(repo_root, registration)

    monkeypatch.setattr(
        module,
        "require_active_evaluation_runtime",
        runtime_spy,
    )
    partial_receipt, partial_reconciliation = _partial_pair(
        module,
        receipt,
        reconciliation,
    )
    ledger = module.StrategyShadowEvidenceLedger(
        root,
        repo_root=REPO_ROOT,
        clock=lambda: dt.datetime(2030, 4, 1, 14, 2, 5, tzinfo=UTC),
    )
    assert (
        ledger.admit_observation(
            staged_intent=staged,
            authorization=authorization,
            observed_at=dt.datetime(2030, 4, 1, 14, 2, tzinfo=UTC),
            paper_order_receipt=partial_receipt,
            reconciliation_receipt=partial_reconciliation,
            actor_role="integrity_verifier",
        )
        is None
    )
    assert calls == [False, False]

    calls.clear()
    observation = ledger.admit_observation(
        staged_intent=staged,
        authorization=authorization,
        observed_at=dt.datetime(2030, 4, 1, 14, 2, tzinfo=UTC),
        paper_order_receipt=receipt,
        reconciliation_receipt=reconciliation,
        actor_role="integrity_verifier",
    )
    assert observation is not None
    calls.clear()
    attestation = module.StrategyShadowEvidenceLedger(
        root,
        repo_root=REPO_ROOT,
        clock=lambda: dt.datetime(2030, 4, 1, 14, 3, tzinfo=UTC),
    ).assemble(
        promotion_evidence=promotion,
        observations=(observation,),
        actor_role="integrity_verifier",
    )
    assert calls == [False, False]

    calls.clear()
    verifier = module.StrategyShadowEvidenceLedger(root, repo_root=REPO_ROOT)
    assert verifier.verify() == (attestation,)
    assert calls == [False, False, False, False]

    calls.clear()
    assert verifier.rebuild() == (attestation,)
    assert calls == [False, False, False, False]


@pytest.mark.parametrize(
    "operation",
    ("partial", "assembly", "verify", "rebuild"),
)
def test_review_fix_runtime_change_between_bracket_calls_fails_closed(
    tmp_path,
    monkeypatch,
    operation: str,
) -> None:
    module = importlib.import_module("tradingagents.strategy.shadow_attestation")
    (
        root,
        _,
        promotion,
        staged,
        authorization,
        receipt,
        reconciliation,
    ) = _durable_buy_case(tmp_path)
    stable_ledger = module.StrategyShadowEvidenceLedger(
        root,
        repo_root=REPO_ROOT,
        clock=lambda: dt.datetime(2030, 4, 1, 14, 2, 5, tzinfo=UTC),
    )
    if operation == "partial":
        receipt, reconciliation = _partial_pair(
            module,
            receipt,
            reconciliation,
        )
        observation = None
    else:
        observation = stable_ledger.admit_observation(
            staged_intent=staged,
            authorization=authorization,
            observed_at=dt.datetime(2030, 4, 1, 14, 2, tzinfo=UTC),
            paper_order_receipt=receipt,
            reconciliation_receipt=reconciliation,
            actor_role="integrity_verifier",
        )
        assert observation is not None
    if operation in {"verify", "rebuild"}:
        module.StrategyShadowEvidenceLedger(
            root,
            repo_root=REPO_ROOT,
            clock=lambda: dt.datetime(2030, 4, 1, 14, 3, tzinfo=UTC),
        ).assemble(
            promotion_evidence=promotion,
            observations=(observation,),
            actor_role="integrity_verifier",
        )

    original = module.require_active_evaluation_runtime
    calls = 0

    def changing_runtime(repo_root, registration):
        nonlocal calls
        manifest = original(repo_root, registration)
        calls += 1
        if calls % 2 == 0:
            changed_file = dataclasses.replace(
                manifest.files[0],
                sha256="0" * 64,
            )
            return dataclasses.replace(
                manifest,
                files=(changed_file, *manifest.files[1:]),
            )
        return manifest

    monkeypatch.setattr(
        module,
        "require_active_evaluation_runtime",
        changing_runtime,
    )
    before = _durable_file_bytes(root)
    ledger = module.StrategyShadowEvidenceLedger(
        root,
        repo_root=REPO_ROOT,
        clock=lambda: dt.datetime(2030, 4, 1, 14, 3, tzinfo=UTC),
    )

    with pytest.raises(ValueError, match="runtime changed"):
        if operation == "partial":
            ledger.admit_observation(
                staged_intent=staged,
                authorization=authorization,
                observed_at=dt.datetime(2030, 4, 1, 14, 2, tzinfo=UTC),
                paper_order_receipt=receipt,
                reconciliation_receipt=reconciliation,
                actor_role="integrity_verifier",
            )
        elif operation == "assembly":
            ledger.assemble(
                promotion_evidence=promotion,
                observations=(observation,),
                actor_role="integrity_verifier",
            )
        else:
            getattr(ledger, operation)()

    assert _durable_file_bytes(root) == before


def test_buy_authorization_receipts_and_account_admit_exactly(tmp_path) -> None:
    (
        root,
        _,
        _,
        staged,
        authorization,
        receipt,
        reconciliation,
    ) = _durable_buy_case(tmp_path)
    module = importlib.import_module("tradingagents.strategy.shadow_attestation")
    ledger = module.StrategyShadowEvidenceLedger(
        root,
        repo_root=REPO_ROOT,
        clock=lambda: dt.datetime(2030, 4, 1, 14, 2, 5, tzinfo=UTC),
    )

    observation = ledger.admit_observation(
        staged_intent=staged,
        authorization=authorization,
        observed_at=dt.datetime(2030, 4, 1, 14, 2, tzinfo=UTC),
        paper_order_receipt=receipt,
        reconciliation_receipt=reconciliation,
        actor_role="integrity_verifier",
    )

    assert observation is not None
    assert observation.authorization_id == authorization.authorization_id
    assert observation.paper_account_fingerprint == (
        authorization.paper_account_fingerprint
    )
    assert observation.paper_order_receipt == receipt
    assert observation.reconciliation_receipt == reconciliation
    assert observation.receipt_sha256 == hashlib.sha256(
        receipt.canonical_json_bytes()
    ).hexdigest()
    assert observation.reconciliation_sha256 == hashlib.sha256(
        reconciliation.canonical_json_bytes()
    ).hexdigest()
    assert observation.gates == (
        ("terminal_filled", True),
        ("fill_respected_limit", True),
        ("operationally_reconciled", True),
    )
    assert observation.issues == ()
    assert observation.operationally_reconciled is True


def test_buy_missing_authorization_or_receipt_rejects_without_event(
    tmp_path,
) -> None:
    (
        root,
        _,
        _,
        staged,
        authorization,
        receipt,
        reconciliation,
    ) = _durable_buy_case(tmp_path)
    module = importlib.import_module("tradingagents.strategy.shadow_attestation")
    before = (root / "events.jsonl").read_bytes()
    ledger = module.StrategyShadowEvidenceLedger(
        root,
        repo_root=REPO_ROOT,
        clock=lambda: dt.datetime(2030, 4, 1, 14, 2, 5, tzinfo=UTC),
    )

    for auth, order, recon in (
        (None, receipt, reconciliation),
        (authorization, None, reconciliation),
        (authorization, receipt, None),
    ):
        with pytest.raises(ValueError):
            ledger.admit_observation(
                staged_intent=staged,
                authorization=auth,
                observed_at=dt.datetime(2030, 4, 1, 14, 2, tzinfo=UTC),
                paper_order_receipt=order,
                reconciliation_receipt=recon,
                actor_role="integrity_verifier",
            )

    assert (root / "events.jsonl").read_bytes() == before


def test_buy_receipt_account_must_match_durable_authorization(
    tmp_path,
) -> None:
    (
        root,
        _,
        _,
        staged,
        authorization,
        receipt,
        reconciliation,
    ) = _durable_buy_case(tmp_path)
    module = importlib.import_module("tradingagents.strategy.shadow_attestation")
    changed = receipt.to_dict()
    changed["paper_account_fingerprint"] = "f" * 64
    changed_receipt = module.PaperOrderReceipt.from_dict(changed)
    before = (root / "events.jsonl").read_bytes()
    ledger = module.StrategyShadowEvidenceLedger(
        root,
        repo_root=REPO_ROOT,
        clock=lambda: dt.datetime(2030, 4, 1, 14, 2, 5, tzinfo=UTC),
    )

    with pytest.raises(ValueError, match="account"):
        ledger.admit_observation(
            staged_intent=staged,
            authorization=authorization,
            observed_at=dt.datetime(2030, 4, 1, 14, 2, tzinfo=UTC),
            paper_order_receipt=changed_receipt,
            reconciliation_receipt=reconciliation,
            actor_role="integrity_verifier",
        )

    assert (root / "events.jsonl").read_bytes() == before


def test_buy_receipt_producer_and_verifier_roles_are_rederived(
    tmp_path,
) -> None:
    (
        root,
        _,
        _,
        staged,
        authorization,
        receipt,
        reconciliation,
    ) = _durable_buy_case(tmp_path)
    module = importlib.import_module("tradingagents.strategy.shadow_attestation")
    wrong_producer_payload = receipt.to_dict()
    wrong_producer_payload["submitted_by_role"] = "integrity_verifier"
    wrong_verifier_payload = reconciliation.to_dict()
    wrong_verifier_payload["verified_by_role"] = "execution_operator"
    before = (root / "events.jsonl").read_bytes()
    ledger = module.StrategyShadowEvidenceLedger(
        root,
        repo_root=REPO_ROOT,
        clock=lambda: dt.datetime(2030, 4, 1, 14, 2, 5, tzinfo=UTC),
    )

    with pytest.raises(ValueError, match="execution_operator"):
        wrong_producer = module.PaperOrderReceipt.from_dict(
            wrong_producer_payload
        )
        ledger.admit_observation(
            staged_intent=staged,
            authorization=authorization,
            observed_at=dt.datetime(2030, 4, 1, 14, 2, tzinfo=UTC),
            paper_order_receipt=wrong_producer,
            reconciliation_receipt=reconciliation,
            actor_role="integrity_verifier",
        )
    with pytest.raises(ValueError, match="integrity_verifier"):
        wrong_verifier = module.PaperReconciliationReceipt.from_dict(
            wrong_verifier_payload
        )
        ledger.admit_observation(
            staged_intent=staged,
            authorization=authorization,
            observed_at=dt.datetime(2030, 4, 1, 14, 2, tzinfo=UTC),
            paper_order_receipt=receipt,
            reconciliation_receipt=wrong_verifier,
            actor_role="integrity_verifier",
        )

    assert (root / "events.jsonl").read_bytes() == before


@pytest.mark.parametrize(
    ("field_name", "bad_value"),
    [
        ("authorization_id", "paper-execution-authorization-" + "0" * 64),
        ("authorization_sha256", "0" * 64),
        ("logical_order_sha256", "0" * 64),
        ("client_order_id", "ta-p-" + "0" * 40),
        ("broker_order_id", "different-broker-order"),
        ("paper_account_fingerprint", "0" * 64),
        ("observed_symbol", "MSFT"),
        ("observed_side", "sell"),
        ("observed_order_type", "market"),
        ("observed_tif", "gtc"),
        ("observed_requested_notional_usd", "91.00"),
        ("observed_requested_limit_price", "100.19"),
        ("observed_status", "canceled"),
        ("observed_filled_qty", "0.8"),
        ("observed_filled_avg_price", "99"),
        ("observed_fees_usd", "0.14"),
    ],
)
def test_malformed_mismatch_rejects_before_shadow_event(
    tmp_path,
    field_name: str,
    bad_value: str,
) -> None:
    (
        root,
        _,
        _,
        staged,
        authorization,
        receipt,
        reconciliation,
    ) = _durable_buy_case(tmp_path)
    module = importlib.import_module("tradingagents.strategy.shadow_attestation")
    changed_payload = reconciliation.to_dict()
    changed_payload[field_name] = bad_value
    before = (root / "events.jsonl").read_bytes()
    ledger = module.StrategyShadowEvidenceLedger(
        root,
        repo_root=REPO_ROOT,
        clock=lambda: dt.datetime(2030, 4, 1, 14, 2, 5, tzinfo=UTC),
    )

    with pytest.raises((TypeError, ValueError)):
        changed = module.PaperReconciliationReceipt.from_dict(changed_payload)
        ledger.admit_observation(
            staged_intent=staged,
            authorization=authorization,
            observed_at=dt.datetime(2030, 4, 1, 14, 2, tzinfo=UTC),
            paper_order_receipt=receipt,
            reconciliation_receipt=changed,
            actor_role="integrity_verifier",
        )

    assert (root / "events.jsonl").read_bytes() == before


def _durable_file_bytes(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def test_partial_nonterminal_writes_nothing_and_leaves_slot_open(
    tmp_path,
) -> None:
    (
        root,
        _,
        _,
        staged,
        authorization,
        receipt,
        reconciliation,
    ) = _durable_buy_case(tmp_path)
    module = importlib.import_module("tradingagents.strategy.shadow_attestation")
    partial_receipt_payload = receipt.to_dict()
    partial_receipt_payload["status"] = "partially_filled"
    partial_receipt = module.PaperOrderReceipt.from_dict(
        partial_receipt_payload
    )
    partial_reconciliation_payload = reconciliation.to_dict()
    partial_reconciliation_payload["observed_status"] = "partially_filled"
    partial_reconciliation = module.PaperReconciliationReceipt.from_dict(
        partial_reconciliation_payload
    )
    ledger = module.StrategyShadowEvidenceLedger(
        root,
        repo_root=REPO_ROOT,
        clock=lambda: dt.datetime(2030, 4, 1, 14, 2, 5, tzinfo=UTC),
    )
    before = _durable_file_bytes(root)

    deferred = ledger.admit_observation(
        staged_intent=staged,
        authorization=authorization,
        observed_at=dt.datetime(2030, 4, 1, 14, 2, tzinfo=UTC),
        paper_order_receipt=partial_receipt,
        reconciliation_receipt=partial_reconciliation,
        actor_role="integrity_verifier",
    )

    assert deferred is None
    assert _durable_file_bytes(root) == before

    admitted = ledger.admit_observation(
        staged_intent=staged,
        authorization=authorization,
        observed_at=dt.datetime(2030, 4, 1, 14, 2, tzinfo=UTC),
        paper_order_receipt=receipt,
        reconciliation_receipt=reconciliation,
        actor_role="integrity_verifier",
    )
    assert admitted is not None
    assert dict(admitted.gates)["terminal_filled"] is True


def test_partial_nonterminal_still_strictly_validates_before_none(
    tmp_path,
) -> None:
    (
        root,
        _,
        _,
        staged,
        authorization,
        receipt,
        reconciliation,
    ) = _durable_buy_case(tmp_path)
    module = importlib.import_module("tradingagents.strategy.shadow_attestation")
    partial_receipt_payload = receipt.to_dict()
    partial_receipt_payload["status"] = "partially_filled"
    partial_receipt = module.PaperOrderReceipt.from_dict(
        partial_receipt_payload
    )
    partial_reconciliation_payload = reconciliation.to_dict()
    partial_reconciliation_payload.update(
        {
            "observed_status": "partially_filled",
            "observed_symbol": "MSFT",
        }
    )
    malformed = module.PaperReconciliationReceipt.from_dict(
        partial_reconciliation_payload
    )
    ledger = module.StrategyShadowEvidenceLedger(
        root,
        repo_root=REPO_ROOT,
        clock=lambda: dt.datetime(2030, 4, 1, 14, 2, 5, tzinfo=UTC),
    )
    before = _durable_file_bytes(root)

    with pytest.raises(ValueError):
        ledger.admit_observation(
            staged_intent=staged,
            authorization=authorization,
            observed_at=dt.datetime(2030, 4, 1, 14, 2, tzinfo=UTC),
            paper_order_receipt=partial_receipt,
            reconciliation_receipt=malformed,
            actor_role="integrity_verifier",
        )

    assert _durable_file_bytes(root) == before


@pytest.mark.parametrize(
    ("status", "qty", "average", "fees"),
    [
        ("filled", "1", "100", "0"),
        ("partially_filled", "1", "100", "0.25"),
        ("rejected", "0", "0", "0"),
        ("canceled", "0", "0", "0"),
        ("canceled", "1", "100", "0.25"),
        ("expired", "0", "0", "0"),
        ("expired", "1", "100", "0.25"),
    ],
)
def test_status_matrix_accepts_every_legal_shape(
    status: str,
    qty: str,
    average: str,
    fees: str,
) -> None:
    module = importlib.import_module("tradingagents.strategy.shadow_attestation")
    order_payload = _paper_order_receipt_payload()
    order_payload.update(
        {
            "status": status,
            "filled_qty": qty,
            "filled_avg_price": average,
            "fees_usd": fees,
        }
    )
    reconciliation_payload = _paper_reconciliation_receipt_payload()
    reconciliation_payload.update(
        {
            "observed_status": status,
            "observed_filled_qty": qty,
            "observed_filled_avg_price": average,
            "observed_fees_usd": fees,
        }
    )

    order = module.PaperOrderReceipt.from_dict(order_payload)
    reconciliation = module.PaperReconciliationReceipt.from_dict(
        reconciliation_payload
    )

    assert (
        order.status,
        order.filled_qty,
        order.filled_avg_price,
        order.fees_usd,
    ) == (status, qty, average, fees)
    assert (
        reconciliation.observed_status,
        reconciliation.observed_filled_qty,
        reconciliation.observed_filled_avg_price,
        reconciliation.observed_fees_usd,
    ) == (status, qty, average, fees)


@pytest.mark.parametrize(
    ("status", "qty", "average", "fees"),
    [
        ("unknown", "1", "100", "0"),
        ("filled", "0", "0", "0"),
        ("filled", "1", "0", "0"),
        ("partially_filled", "0", "0", "0"),
        ("rejected", "1", "100", "0"),
        ("rejected", "0", "0", "0.01"),
        ("canceled", "1", "0", "0"),
        ("canceled", "0", "100", "0"),
        ("canceled", "0", "0", "0.01"),
        ("expired", "1", "0", "0"),
        ("expired", "0", "100", "0"),
        ("expired", "0", "0", "0.01"),
        ("filled", "-1", "100", "0"),
        ("filled", "1", "-100", "0"),
        ("filled", "1", "100", "-0.01"),
    ],
)
def test_status_matrix_rejects_every_illegal_shape(
    status: str,
    qty: str,
    average: str,
    fees: str,
) -> None:
    module = importlib.import_module("tradingagents.strategy.shadow_attestation")
    for payload, receipt_type in (
        (_paper_order_receipt_payload(), module.PaperOrderReceipt),
        (
            _paper_reconciliation_receipt_payload(),
            module.PaperReconciliationReceipt,
        ),
    ):
        if "status" in payload:
            payload.update(
                {
                    "status": status,
                    "filled_qty": qty,
                    "filled_avg_price": average,
                    "fees_usd": fees,
                }
            )
        else:
            payload.update(
                {
                    "observed_status": status,
                    "observed_filled_qty": qty,
                    "observed_filled_avg_price": average,
                    "observed_fees_usd": fees,
                }
            )
        with pytest.raises((TypeError, ValueError)):
            receipt_type.from_dict(payload)


@pytest.mark.parametrize(
    "timestamp",
    [
        "2030-04-01T14:01:05Z",
        "2030-04-01T14:01:05",
        "2030-04-01T10:01:05-04:00",
        "2030-04-01T14:01:05.000000+00:00",
    ],
)
def test_timing_matrix_receipts_require_canonical_whole_second_utc(
    timestamp: str,
) -> None:
    module = importlib.import_module("tradingagents.strategy.shadow_attestation")
    order_payload = _paper_order_receipt_payload()
    order_payload["submitted_at"] = timestamp
    reconciliation_payload = _paper_reconciliation_receipt_payload()
    reconciliation_payload["checked_at"] = timestamp

    with pytest.raises((TypeError, ValueError)):
        module.PaperOrderReceipt.from_dict(order_payload)
    with pytest.raises((TypeError, ValueError)):
        module.PaperReconciliationReceipt.from_dict(reconciliation_payload)


def test_timing_matrix_observation_effective_and_recorded_bounds() -> None:
    module = importlib.import_module("tradingagents.strategy.shadow_attestation")
    changed_effective = _hold_observation_payload()
    changed_effective["effective_at"] = "2026-07-20T14:30:01+00:00"
    with pytest.raises((TypeError, ValueError)):
        module.AdmittedPaperShadowObservation.from_dict(changed_effective)

    future = _hold_observation_payload()
    future["recorded_at"] = "2026-07-20T14:29:59+00:00"
    with pytest.raises((TypeError, ValueError)):
        module.AdmittedPaperShadowObservation.from_dict(future)


@pytest.mark.parametrize("session_date", ["2030-4-1", "2030-02-30", 20300401])
def test_session_label_rejects_noncanonical_dates(session_date: object) -> None:
    module = importlib.import_module("tradingagents.strategy.shadow_attestation")
    observation = _hold_observation_payload()
    observation["session_date"] = session_date
    with pytest.raises((TypeError, ValueError)):
        module.AdmittedPaperShadowObservation.from_dict(observation)

    attestation = _shadow_attestation_payload()
    attestation["first_session_date"] = session_date
    with pytest.raises((TypeError, ValueError)):
        module.StrategyShadowAttestation.from_dict(attestation)


def test_review_fix_dst_label_and_exact_86400_second_boundary(
    tmp_path,
) -> None:
    from tests.test_strategy_paper_execution_authorization import _authorize_once
    from tests.test_strategy_staged_intent import _stage_with_times

    root, registration, promotion = _durable_internal_evidence(tmp_path)
    _, staged = _stage_with_times(
        root,
        registration,
        promotion,
        clock_time=dt.datetime(2030, 11, 3, 4, 0, 5, tzinfo=UTC),
        effective_at=dt.datetime(2030, 11, 3, 4, 0, tzinfo=UTC),
        expires_at=dt.datetime(2030, 11, 3, 4, 15, tzinfo=UTC),
        session_date="2030-11-03",
    )
    _, authorization = _authorize_once(
        root,
        staged,
        paper_account_id="dst-paper-account",
        clock_time=dt.datetime(2030, 11, 3, 4, 1, tzinfo=UTC),
        effective_at=dt.datetime(2030, 11, 3, 4, 1, tzinfo=UTC),
        expires_at=dt.datetime(2030, 11, 3, 4, 14, tzinfo=UTC),
    )
    module = importlib.import_module("tradingagents.strategy.shadow_attestation")
    equality_receipt, equality_reconciliation = (
        _receipt_pair_for_authorization(
            authorization,
            submitted_at="2030-11-03T04:01:00+00:00",
            last_seen_at="2030-11-04T04:01:00+00:00",
            checked_at="2030-11-04T04:01:00+00:00",
        )
    )
    over_receipt, over_reconciliation = _receipt_pair_for_authorization(
        authorization,
        submitted_at="2030-11-03T04:01:00+00:00",
        last_seen_at="2030-11-04T04:01:01+00:00",
        checked_at="2030-11-04T04:01:01+00:00",
    )
    ledger = module.StrategyShadowEvidenceLedger(
        root,
        repo_root=REPO_ROOT,
        clock=lambda: dt.datetime(
            2030, 11, 4, 4, 1, 2, tzinfo=UTC
        ),
    )
    before = _durable_file_bytes(root)

    with pytest.raises(ValueError, match="86400"):
        ledger.admit_observation(
            staged_intent=staged,
            authorization=authorization,
            observed_at=dt.datetime(
                2030, 11, 4, 4, 1, 1, tzinfo=UTC
            ),
            paper_order_receipt=over_receipt,
            reconciliation_receipt=over_reconciliation,
            actor_role="integrity_verifier",
        )
    assert _durable_file_bytes(root) == before

    observation = ledger.admit_observation(
        staged_intent=staged,
        authorization=authorization,
        observed_at=dt.datetime(2030, 11, 4, 4, 1, tzinfo=UTC),
        paper_order_receipt=equality_receipt,
        reconciliation_receipt=equality_reconciliation,
        actor_role="integrity_verifier",
    )

    assert observation is not None
    assert observation.session_date == "2030-11-03"


@pytest.mark.parametrize(
    ("submitted", "last_seen", "checked", "observed"),
    [
        (
            "2030-04-01T14:01:06+00:00",
            "2030-04-01T14:01:05+00:00",
            "2030-04-01T14:02:00+00:00",
            dt.datetime(2030, 4, 1, 14, 2, tzinfo=UTC),
        ),
        (
            "2030-04-01T14:01:05+00:00",
            "2030-04-01T14:02:00+00:00",
            "2030-04-01T14:02:01+00:00",
            dt.datetime(2030, 4, 1, 14, 2, tzinfo=UTC),
        ),
        (
            "2030-04-01T14:00:59+00:00",
            "2030-04-01T14:02:00+00:00",
            "2030-04-01T14:02:00+00:00",
            dt.datetime(2030, 4, 1, 14, 2, tzinfo=UTC),
        ),
    ],
)
def test_timing_matrix_buy_rejects_reversal_and_observation_mismatch(
    tmp_path,
    submitted: str,
    last_seen: str,
    checked: str,
    observed: dt.datetime,
) -> None:
    (
        root,
        _,
        _,
        staged,
        authorization,
        receipt,
        reconciliation,
    ) = _durable_buy_case(tmp_path)
    module = importlib.import_module("tradingagents.strategy.shadow_attestation")
    order_payload = receipt.to_dict()
    order_payload.update(
        {"submitted_at": submitted, "last_seen_at": last_seen}
    )
    reconciliation_payload = reconciliation.to_dict()
    reconciliation_payload["checked_at"] = checked
    before = (root / "events.jsonl").read_bytes()

    with pytest.raises(ValueError):
        changed_order = module.PaperOrderReceipt.from_dict(order_payload)
        changed_reconciliation = module.PaperReconciliationReceipt.from_dict(
            reconciliation_payload
        )
        ledger = module.StrategyShadowEvidenceLedger(
            root,
            repo_root=REPO_ROOT,
            clock=lambda: dt.datetime(2030, 4, 1, 14, 2, 5, tzinfo=UTC),
        )
        ledger.admit_observation(
            staged_intent=staged,
            authorization=authorization,
            observed_at=observed,
            paper_order_receipt=changed_order,
            reconciliation_receipt=changed_reconciliation,
            actor_role="integrity_verifier",
        )

    assert (root / "events.jsonl").read_bytes() == before


@pytest.mark.parametrize(
    ("field_name", "bad_value"),
    [
        ("filled_qty", "1e2"),
        ("filled_qty", "+1"),
        ("filled_qty", "01"),
        ("filled_qty", "1.0"),
        ("filled_qty", "9" * 35),
        ("filled_qty", "0.0000000000001"),
        ("filled_qty", "1" + "0" * 34),
        ("filled_avg_price", "100.230"),
        ("fees_usd", "-0"),
        ("fees_usd", "0.00"),
    ],
)
def test_decimal_bound_receipt_operands_reject_noncanonical_or_unbounded(
    field_name: str,
    bad_value: str,
) -> None:
    module = importlib.import_module("tradingagents.strategy.shadow_attestation")
    payload = _paper_order_receipt_payload()
    payload[field_name] = bad_value

    with pytest.raises((TypeError, ValueError)):
        module.PaperOrderReceipt.from_dict(payload)


def test_decimal_bound_accepts_exact_operand_boundaries() -> None:
    module = importlib.import_module("tradingagents.strategy.shadow_attestation")
    payload = _paper_order_receipt_payload()
    payload.update(
        {
            "filled_qty": "1234567890123456789012.123456789012",
            "filled_avg_price": "0.000000000001",
            "fees_usd": "9999999999999999999999999999999999",
        }
    )

    receipt = module.PaperOrderReceipt.from_dict(payload)

    assert len(Decimal(receipt.filled_qty).as_tuple().digits) == 34
    assert Decimal(receipt.filled_qty).as_tuple().exponent == -12


@pytest.mark.parametrize(
    "bad_fraction",
    [
        "1." + "1" * 80,
        "0." + "0" * 125 + "1",
        "1" + "0" * 46,
        "0.00",
        "1e-3",
    ],
)
def test_decimal_bound_derived_adverse_fraction_rejects_wrong_domain(
    bad_fraction: str,
) -> None:
    module = importlib.import_module("tradingagents.strategy.shadow_attestation")
    payload = _hold_observation_payload()
    payload["adverse_fill_vs_reference_fraction"] = bad_fraction

    with pytest.raises((TypeError, ValueError)):
        module.AdmittedPaperShadowObservation.from_dict(payload)


@pytest.mark.parametrize(
    ("field_name", "bad_money"),
    [
        ("total_requested_notional_usd", "1." + "1" * 74),
        ("total_filled_notional_usd", "0.001"),
        ("total_fees_usd", "1" + "0" * 72),
        ("total_fees_usd", "0.00"),
    ],
)
def test_decimal_bound_derived_money_rejects_wrong_domain(
    field_name: str,
    bad_money: str,
) -> None:
    module = importlib.import_module("tradingagents.strategy.shadow_attestation")
    payload = _shadow_attestation_payload()
    payload[field_name] = bad_money

    with pytest.raises((TypeError, ValueError)):
        module.StrategyShadowAttestation.from_dict(payload)


def test_hostile_context_does_not_change_adverse_fraction(tmp_path) -> None:
    (
        root,
        _,
        _,
        staged,
        authorization,
        receipt,
        reconciliation,
    ) = _durable_buy_case(tmp_path)
    module = importlib.import_module("tradingagents.strategy.shadow_attestation")
    order_payload = receipt.to_dict()
    order_payload["filled_avg_price"] = "100.123456789012"
    changed_order = module.PaperOrderReceipt.from_dict(order_payload)
    reconciliation_payload = reconciliation.to_dict()
    reconciliation_payload["observed_filled_avg_price"] = "100.123456789012"
    changed_reconciliation = module.PaperReconciliationReceipt.from_dict(
        reconciliation_payload
    )
    ledger = module.StrategyShadowEvidenceLedger(
        root,
        repo_root=REPO_ROOT,
        clock=lambda: dt.datetime(2030, 4, 1, 14, 2, 5, tzinfo=UTC),
    )

    with localcontext() as hostile:
        hostile.prec = 5
        observation = ledger.admit_observation(
            staged_intent=staged,
            authorization=authorization,
            observed_at=dt.datetime(2030, 4, 1, 14, 2, tzinfo=UTC),
            paper_order_receipt=changed_order,
            reconciliation_receipt=changed_reconciliation,
            actor_role="integrity_verifier",
        )

    assert observation is not None
    assert observation.adverse_fill_vs_reference_fraction == (
        "0.00123456789012"
    )


@pytest.mark.parametrize(
    ("status", "quantity", "average", "fees"),
    [
        ("rejected", "0", "0", "0"),
        ("canceled", "0", "0", "0"),
        ("expired", "0", "0", "0"),
    ],
)
def test_terminal_failed_observation_gate_is_durable_and_reconciled(
    tmp_path,
    status: str,
    quantity: str,
    average: str,
    fees: str,
) -> None:
    (
        root,
        _,
        _,
        staged,
        authorization,
        receipt,
        reconciliation,
    ) = _durable_buy_case(tmp_path)
    module = importlib.import_module("tradingagents.strategy.shadow_attestation")
    order_payload = receipt.to_dict()
    order_payload.update(
        {
            "status": status,
            "filled_qty": quantity,
            "filled_avg_price": average,
            "fees_usd": fees,
        }
    )
    reconciliation_payload = reconciliation.to_dict()
    reconciliation_payload.update(
        {
            "observed_status": status,
            "observed_filled_qty": quantity,
            "observed_filled_avg_price": average,
            "observed_fees_usd": fees,
        }
    )
    ledger = module.StrategyShadowEvidenceLedger(
        root,
        repo_root=REPO_ROOT,
        clock=lambda: dt.datetime(2030, 4, 1, 14, 2, 5, tzinfo=UTC),
    )

    observation = ledger.admit_observation(
        staged_intent=staged,
        authorization=authorization,
        observed_at=dt.datetime(2030, 4, 1, 14, 2, tzinfo=UTC),
        paper_order_receipt=module.PaperOrderReceipt.from_dict(order_payload),
        reconciliation_receipt=(
            module.PaperReconciliationReceipt.from_dict(
                reconciliation_payload
            )
        ),
        actor_role="integrity_verifier",
    )

    assert observation is not None
    assert observation.gates == (
        ("terminal_filled", False),
        ("fill_respected_limit", True),
        ("operationally_reconciled", True),
    )
    assert observation.issues == ("buy_not_terminal_filled",)
    assert observation.operationally_reconciled is True


def test_fill_above_limit_fails_only_fill_gate(tmp_path) -> None:
    (
        root,
        _,
        _,
        staged,
        authorization,
        receipt,
        reconciliation,
    ) = _durable_buy_case(tmp_path)
    module = importlib.import_module("tradingagents.strategy.shadow_attestation")
    order_payload = receipt.to_dict()
    order_payload["filled_avg_price"] = "100.21"
    reconciliation_payload = reconciliation.to_dict()
    reconciliation_payload["observed_filled_avg_price"] = "100.21"
    ledger = module.StrategyShadowEvidenceLedger(
        root,
        repo_root=REPO_ROOT,
        clock=lambda: dt.datetime(2030, 4, 1, 14, 2, 5, tzinfo=UTC),
    )

    observation = ledger.admit_observation(
        staged_intent=staged,
        authorization=authorization,
        observed_at=dt.datetime(2030, 4, 1, 14, 2, tzinfo=UTC),
        paper_order_receipt=module.PaperOrderReceipt.from_dict(order_payload),
        reconciliation_receipt=(
            module.PaperReconciliationReceipt.from_dict(
                reconciliation_payload
            )
        ),
        actor_role="integrity_verifier",
    )

    assert observation is not None
    assert observation.gates == (
        ("terminal_filled", True),
        ("fill_respected_limit", False),
        ("operationally_reconciled", True),
    )
    assert observation.issues == ("fill_above_staged_limit",)
    assert observation.operationally_reconciled is True


def test_operational_reconciliation_gate_is_an_admission_invariant() -> None:
    module = importlib.import_module("tradingagents.strategy.shadow_attestation")
    payload = _buy_observation_payload()
    payload["gates"] = [
        ["terminal_filled", True],
        ["fill_respected_limit", True],
        ["operationally_reconciled", False],
    ]
    payload["issues"] = ["reconciliation_not_clean"]
    payload["operationally_reconciled"] = False

    with pytest.raises(ValueError, match="invariant"):
        module.AdmittedPaperShadowObservation.from_dict(payload)


def test_unique_observation_slot_rejects_conflicting_terminal_retry(
    tmp_path,
) -> None:
    (
        root,
        _,
        _,
        staged,
        authorization,
        receipt,
        reconciliation,
    ) = _durable_buy_case(tmp_path)
    module = importlib.import_module("tradingagents.strategy.shadow_attestation")
    ledger = module.StrategyShadowEvidenceLedger(
        root,
        repo_root=REPO_ROOT,
        clock=lambda: dt.datetime(2030, 4, 1, 14, 2, 5, tzinfo=UTC),
    )
    first = ledger.admit_observation(
        staged_intent=staged,
        authorization=authorization,
        observed_at=dt.datetime(2030, 4, 1, 14, 2, tzinfo=UTC),
        paper_order_receipt=receipt,
        reconciliation_receipt=reconciliation,
        actor_role="integrity_verifier",
    )
    order_payload = receipt.to_dict()
    order_payload["fees_usd"] = "0.16"
    reconciliation_payload = reconciliation.to_dict()
    reconciliation_payload["observed_fees_usd"] = "0.16"
    before = (root / "events.jsonl").read_bytes()

    with pytest.raises(ValueError, match="one shadow observation"):
        ledger.admit_observation(
            staged_intent=staged,
            authorization=authorization,
            observed_at=dt.datetime(2030, 4, 1, 14, 2, tzinfo=UTC),
            paper_order_receipt=module.PaperOrderReceipt.from_dict(
                order_payload
            ),
            reconciliation_receipt=(
                module.PaperReconciliationReceipt.from_dict(
                    reconciliation_payload
                )
            ),
            actor_role="integrity_verifier",
        )

    assert first is not None
    assert (root / "events.jsonl").read_bytes() == before


def test_concurrent_identical_observation_has_one_event(tmp_path) -> None:
    (
        root,
        _,
        _,
        staged,
        authorization,
        receipt,
        reconciliation,
    ) = _durable_buy_case(tmp_path)
    module = importlib.import_module("tradingagents.strategy.shadow_attestation")

    def admit_once():
        ledger = module.StrategyShadowEvidenceLedger(
            root,
            repo_root=REPO_ROOT,
            clock=lambda: dt.datetime(2030, 4, 1, 14, 2, 5, tzinfo=UTC),
        )
        return ledger.admit_observation(
            staged_intent=staged,
            authorization=authorization,
            observed_at=dt.datetime(2030, 4, 1, 14, 2, tzinfo=UTC),
            paper_order_receipt=receipt,
            reconciliation_receipt=reconciliation,
            actor_role="integrity_verifier",
        )

    before_lines = (root / "events.jsonl").read_bytes().splitlines()
    with ThreadPoolExecutor(max_workers=2) as executor:
        observations = tuple(executor.map(lambda _: admit_once(), range(2)))
    after_lines = (root / "events.jsonl").read_bytes().splitlines()

    assert all(observation is not None for observation in observations)
    assert observations[0] == observations[1]
    assert len(after_lines) == len(before_lines) + 1


class _CrashShadowStore:
    @staticmethod
    def make(store_type, root, *, clock, seam: str):
        class CrashingStore(store_type):
            def _after_object_fsync(self, path: Path) -> None:
                if seam == "object":
                    raise RuntimeError("observation crash after object fsync")
                return super()._after_object_fsync(path)

            def _after_event_fsync(self, event) -> None:
                if seam == "event":
                    raise RuntimeError("observation crash after event fsync")
                return super()._after_event_fsync(event)

        return CrashingStore(root, clock=clock)


@pytest.mark.parametrize("seam", ("object", "event"))
def test_observation_crash_fsync_retry_adopts_exact_recorded_time(
    tmp_path,
    seam: str,
) -> None:
    (
        root,
        _,
        _,
        staged,
        authorization,
        receipt,
        reconciliation,
    ) = _durable_buy_case(tmp_path)
    module = importlib.import_module("tradingagents.strategy.shadow_attestation")
    from tradingagents.strategy._immutable_evidence_store import (
        ImmutableStrategyEvidenceStore,
    )

    def first_clock():
        return dt.datetime(2030, 4, 1, 14, 2, 5, tzinfo=UTC)
    ledger = module.StrategyShadowEvidenceLedger(
        root,
        repo_root=REPO_ROOT,
        clock=first_clock,
    )
    ledger._store = _CrashShadowStore.make(
        ImmutableStrategyEvidenceStore,
        root,
        clock=first_clock,
        seam=seam,
    )
    before = len((root / "events.jsonl").read_bytes().splitlines())

    with pytest.raises(RuntimeError, match=f"{seam} fsync"):
        ledger.admit_observation(
            staged_intent=staged,
            authorization=authorization,
            observed_at=dt.datetime(2030, 4, 1, 14, 2, tzinfo=UTC),
            paper_order_receipt=receipt,
            reconciliation_receipt=reconciliation,
            actor_role="integrity_verifier",
        )

    repaired = module.StrategyShadowEvidenceLedger(
        root,
        repo_root=REPO_ROOT,
        clock=lambda: dt.datetime(
            2030, 4, 1, 14, 2, 30, tzinfo=UTC
        ),
    )
    observation = repaired.admit_observation(
        staged_intent=staged,
        authorization=authorization,
        observed_at=dt.datetime(2030, 4, 1, 14, 2, tzinfo=UTC),
        paper_order_receipt=receipt,
        reconciliation_receipt=reconciliation,
        actor_role="integrity_verifier",
    )

    assert observation is not None
    assert observation.recorded_at == "2030-04-01T14:02:05+00:00"
    assert len((root / "events.jsonl").read_bytes().splitlines()) == before + 1
    assert repaired.verify() == ()


def _admitted_buy_case(tmp_path):
    (
        root,
        registration,
        promotion,
        staged,
        authorization,
        receipt,
        reconciliation,
    ) = _durable_buy_case(tmp_path)
    module = importlib.import_module("tradingagents.strategy.shadow_attestation")
    ledger = module.StrategyShadowEvidenceLedger(
        root,
        repo_root=REPO_ROOT,
        clock=lambda: dt.datetime(2030, 4, 1, 14, 2, 5, tzinfo=UTC),
    )
    observation = ledger.admit_observation(
        staged_intent=staged,
        authorization=authorization,
        observed_at=dt.datetime(2030, 4, 1, 14, 2, tzinfo=UTC),
        paper_order_receipt=receipt,
        reconciliation_receipt=reconciliation,
        actor_role="integrity_verifier",
    )
    assert observation is not None
    return root, registration, promotion, observation


def test_aggregate_assembles_exact_counts_arithmetic_and_gates(tmp_path) -> None:
    root, registration, promotion, observation = _admitted_buy_case(tmp_path)
    module = importlib.import_module("tradingagents.strategy.shadow_attestation")
    ledger = module.StrategyShadowEvidenceLedger(
        root,
        repo_root=REPO_ROOT,
        clock=lambda: dt.datetime(2030, 4, 1, 14, 3, tzinfo=UTC),
    )

    attestation = ledger.assemble(
        promotion_evidence=promotion,
        observations=[observation],
        actor_role="integrity_verifier",
    )

    assert attestation.registration_id == registration.registration_id
    assert attestation.shadow_observation_ids == (
        observation.shadow_observation_id,
    )
    assert attestation.shadow_observation_sha256s == (
        hashlib.sha256(observation.canonical_json_bytes()).hexdigest(),
    )
    assert attestation.tracked_sessions == 1
    assert attestation.total_intents == 1
    assert attestation.hold_intents == 0
    assert attestation.buy_intents == 1
    assert attestation.reconciled_buy_intents == 1
    assert attestation.filled_buy_intents == 1
    assert attestation.total_requested_notional_usd == "90"
    assert attestation.total_filled_notional_usd == "90"
    assert attestation.total_fees_usd == "0.15"
    assert attestation.worst_adverse_fill_vs_reference_fraction == "0"
    assert attestation.effective_at == observation.observed_at
    assert dict(attestation.gates) == {
        "internal_evidence_complete": True,
        "minimum_tracked_sessions": (
            registration.evolution_policy.minimum_tracked_days <= 1
        ),
        "all_intents_current_when_observed": True,
        "all_buy_intents_paper_only": True,
        "all_order_fields_match": True,
        "all_buy_intents_terminal_filled": True,
        "all_reconciliations_clean": True,
        "at_least_one_reconciled_buy": True,
    }
    assert attestation.reconciliation_confirmed is True
    assert ledger.verify() == (attestation,)
    assert ledger.rebuild() == (attestation,)


def test_aggregate_hostile_decimal_context_and_exact_retry(tmp_path) -> None:
    root, _, promotion, observation = _admitted_buy_case(tmp_path)
    module = importlib.import_module("tradingagents.strategy.shadow_attestation")
    ledger = module.StrategyShadowEvidenceLedger(
        root,
        repo_root=REPO_ROOT,
        clock=lambda: dt.datetime(2030, 4, 1, 14, 3, tzinfo=UTC),
    )
    before = (root / "events.jsonl").read_bytes().splitlines()

    with localcontext() as hostile:
        hostile.prec = 3
        first = ledger.assemble(
            promotion_evidence=promotion,
            observations=(observation,),
            actor_role="integrity_verifier",
        )
        second = ledger.assemble(
            promotion_evidence=promotion,
            observations=(observation,),
            actor_role="integrity_verifier",
        )

    after = (root / "events.jsonl").read_bytes().splitlines()
    assert first == second
    assert len(after) == len(before) + 1


def test_review_fix_multi_session_stable_account_and_permutation(
    tmp_path,
) -> None:
    from tests.test_strategy_paper_execution_authorization import _authorize_once
    from tests.test_strategy_staged_intent import _stage_with_times

    root, registration, promotion = _durable_internal_evidence(tmp_path)
    module = importlib.import_module("tradingagents.strategy.shadow_attestation")
    observations = []
    required_days = registration.evolution_policy.minimum_tracked_days
    for offset in range(required_days):
        day = dt.date(2030, 4, 1) + dt.timedelta(days=offset)
        effective = dt.datetime.combine(
            day,
            dt.time(14, 0),
            tzinfo=UTC,
        )
        _, staged = _stage_with_times(
            root,
            registration,
            promotion,
            clock_time=effective + dt.timedelta(seconds=5),
            effective_at=effective,
            expires_at=effective + dt.timedelta(minutes=15),
            session_date=day.isoformat(),
        )
        _, authorization = _authorize_once(
            root,
            staged,
            paper_account_id="stable-multi-session-account",
            clock_time=effective + dt.timedelta(minutes=1, seconds=5),
            effective_at=effective + dt.timedelta(minutes=1),
            expires_at=effective + dt.timedelta(minutes=14),
        )
        submitted = (
            effective + dt.timedelta(minutes=1, seconds=5)
        ).isoformat(timespec="seconds")
        checked_time = effective + dt.timedelta(minutes=2)
        checked = checked_time.isoformat(timespec="seconds")
        receipt, reconciliation = _receipt_pair_for_authorization(
            authorization,
            submitted_at=submitted,
            last_seen_at=checked,
            checked_at=checked,
            broker_order_id=f"multi-session-broker-{offset}",
        )
        observation = module.StrategyShadowEvidenceLedger(
            root,
            repo_root=REPO_ROOT,
            clock=lambda value=checked_time: value
            + dt.timedelta(seconds=5),
        ).admit_observation(
            staged_intent=staged,
            authorization=authorization,
            observed_at=checked_time,
            paper_order_receipt=receipt,
            reconciliation_receipt=reconciliation,
            actor_role="integrity_verifier",
        )
        assert observation is not None
        observations.append(observation)

    ledger = module.StrategyShadowEvidenceLedger(
        root,
        repo_root=REPO_ROOT,
        clock=lambda: dt.datetime.fromisoformat(
            observations[-1].recorded_at
        )
        + dt.timedelta(minutes=1),
    )
    before = len((root / "events.jsonl").read_bytes().splitlines())
    first = ledger.assemble(
        promotion_evidence=promotion,
        observations=tuple(reversed(observations)),
        actor_role="integrity_verifier",
    )
    second = ledger.assemble(
        promotion_evidence=promotion,
        observations=tuple(observations),
        actor_role="integrity_verifier",
    )

    assert first == second
    assert first.tracked_sessions == required_days
    assert first.buy_intents == required_days
    assert dict(first.gates)["minimum_tracked_sessions"] is True
    assert dict(first.gates)["at_least_one_reconciled_buy"] is True
    assert first.paper_account_fingerprint == (
        observations[0].paper_account_fingerprint
    )
    assert first.shadow_observation_ids == tuple(
        item.shadow_observation_id
        for item in sorted(
            observations,
            key=lambda item: (item.session_date, item.staged_intent_id),
        )
    )
    assert len((root / "events.jsonl").read_bytes().splitlines()) == before + 1


def test_aggregate_rejects_empty_duplicate_and_wrong_role_without_event(
    tmp_path,
) -> None:
    root, _, promotion, observation = _admitted_buy_case(tmp_path)
    module = importlib.import_module("tradingagents.strategy.shadow_attestation")
    ledger = module.StrategyShadowEvidenceLedger(
        root,
        repo_root=REPO_ROOT,
        clock=lambda: dt.datetime(2030, 4, 1, 14, 3, tzinfo=UTC),
    )
    before = (root / "events.jsonl").read_bytes()

    with pytest.raises(ValueError, match="at least one"):
        ledger.assemble(
            promotion_evidence=promotion,
            observations=(),
            actor_role="integrity_verifier",
        )
    with pytest.raises(ValueError, match="duplicate"):
        ledger.assemble(
            promotion_evidence=promotion,
            observations=(observation, observation),
            actor_role="integrity_verifier",
        )
    with pytest.raises(ValueError, match="integrity_verifier"):
        ledger.assemble(
            promotion_evidence=promotion,
            observations=(observation,),
            actor_role="execution_operator",
        )

    assert (root / "events.jsonl").read_bytes() == before


def test_concurrent_identical_attestation_has_one_event(tmp_path) -> None:
    root, _, promotion, observation = _admitted_buy_case(tmp_path)
    module = importlib.import_module("tradingagents.strategy.shadow_attestation")

    def assemble_once():
        ledger = module.StrategyShadowEvidenceLedger(
            root,
            repo_root=REPO_ROOT,
            clock=lambda: dt.datetime(2030, 4, 1, 14, 3, tzinfo=UTC),
        )
        return ledger.assemble(
            promotion_evidence=promotion,
            observations=(observation,),
            actor_role="integrity_verifier",
        )

    before_lines = (root / "events.jsonl").read_bytes().splitlines()
    with ThreadPoolExecutor(max_workers=2) as executor:
        attestations = tuple(executor.map(lambda _: assemble_once(), range(2)))
    after_lines = (root / "events.jsonl").read_bytes().splitlines()

    assert attestations[0] == attestations[1]
    assert len(after_lines) == len(before_lines) + 1


def test_review_fix_aggregate_locked_recomputation_rejects_drift(
    tmp_path,
    monkeypatch,
) -> None:
    root, _, promotion, observation = _admitted_buy_case(tmp_path)
    module = importlib.import_module("tradingagents.strategy.shadow_attestation")
    original = module._aggregate_payload
    calls = 0

    def drifting_aggregate(**kwargs):
        nonlocal calls
        calls += 1
        effective_at, payload = original(**kwargs)
        if calls == 2:
            payload["total_fees_usd"] = "0.16"
        return effective_at, payload

    monkeypatch.setattr(module, "_aggregate_payload", drifting_aggregate)
    ledger = module.StrategyShadowEvidenceLedger(
        root,
        repo_root=REPO_ROOT,
        clock=lambda: dt.datetime(2030, 4, 1, 14, 3, tzinfo=UTC),
    )
    before = _durable_file_bytes(root)

    with pytest.raises(ValueError, match="locked aggregate"):
        ledger.assemble(
            promotion_evidence=promotion,
            observations=(observation,),
            actor_role="integrity_verifier",
        )

    assert calls == 2
    assert _durable_file_bytes(root) == before


def test_review_fix_aggregate_tuple_conflict_and_later_unrelated_event(
    tmp_path,
) -> None:
    from tests.test_strategy_staged_intent import _stage_with_times
    from tradingagents.strategy._immutable_evidence_store import (
        ImmutableStrategyEvidenceStore,
    )

    root, registration, promotion, observation = _admitted_buy_case(tmp_path)
    module = importlib.import_module("tradingagents.strategy.shadow_attestation")
    ledger = module.StrategyShadowEvidenceLedger(
        root,
        repo_root=REPO_ROOT,
        clock=lambda: dt.datetime(2030, 4, 1, 14, 3, tzinfo=UTC),
    )
    attestation = ledger.assemble(
        promotion_evidence=promotion,
        observations=(observation,),
        actor_role="integrity_verifier",
    )
    snapshot = ImmutableStrategyEvidenceStore(root).rebuild()
    envelope = next(
        item
        for item in snapshot
        if item.kind == "paper-shadow-attestation"
    )
    changed_payload = attestation.to_dict()
    changed_payload["total_fees_usd"] = "0.16"
    _reidentify_journal_payload(
        changed_payload,
        kind="paper-shadow-attestation",
        id_field="shadow_attestation_id",
    )
    changed = module.StrategyShadowAttestation.from_dict(changed_payload)
    with pytest.raises(ValueError, match="tuple collision"):
        module._require_attestation_tuple_unique((envelope,), changed)

    _stage_with_times(
        root,
        registration,
        promotion,
        clock_time=dt.datetime(2030, 4, 2, 14, 0, 5, tzinfo=UTC),
        effective_at=dt.datetime(2030, 4, 2, 14, 0, tzinfo=UTC),
        expires_at=dt.datetime(2030, 4, 2, 14, 15, tzinfo=UTC),
        session_date="2030-04-02",
        market_session="closed",
    )
    before_retry = len((root / "events.jsonl").read_bytes().splitlines())
    retry = module.StrategyShadowEvidenceLedger(
        root,
        repo_root=REPO_ROOT,
        clock=lambda: dt.datetime(2030, 4, 2, 14, 1, tzinfo=UTC),
    ).assemble(
        promotion_evidence=promotion,
        observations=(observation,),
        actor_role="integrity_verifier",
    )

    assert retry == attestation
    assert (
        len((root / "events.jsonl").read_bytes().splitlines())
        == before_retry
    )


@pytest.mark.parametrize("seam", ("object", "event"))
def test_attestation_crash_fsync_retry_adopts_exact_recorded_time(
    tmp_path,
    seam: str,
) -> None:
    root, _, promotion, observation = _admitted_buy_case(tmp_path)
    module = importlib.import_module("tradingagents.strategy.shadow_attestation")
    from tradingagents.strategy._immutable_evidence_store import (
        ImmutableStrategyEvidenceStore,
    )

    def first_clock():
        return dt.datetime(2030, 4, 1, 14, 3, tzinfo=UTC)
    ledger = module.StrategyShadowEvidenceLedger(
        root,
        repo_root=REPO_ROOT,
        clock=first_clock,
    )
    ledger._store = _CrashShadowStore.make(
        ImmutableStrategyEvidenceStore,
        root,
        clock=first_clock,
        seam=seam,
    )
    before = len((root / "events.jsonl").read_bytes().splitlines())

    with pytest.raises(RuntimeError, match=f"{seam} fsync"):
        ledger.assemble(
            promotion_evidence=promotion,
            observations=(observation,),
            actor_role="integrity_verifier",
        )

    repaired = module.StrategyShadowEvidenceLedger(
        root,
        repo_root=REPO_ROOT,
        clock=lambda: dt.datetime(
            2030, 4, 1, 14, 3, 30, tzinfo=UTC
        ),
    )
    attestation = repaired.assemble(
        promotion_evidence=promotion,
        observations=(observation,),
        actor_role="integrity_verifier",
    )

    assert attestation.recorded_at == "2030-04-01T14:03:00+00:00"
    assert len((root / "events.jsonl").read_bytes().splitlines()) == before + 1
    assert repaired.verify() == (attestation,)


def test_shadow_gate_hold_only_is_durable_but_not_deployment_ready(
    tmp_path,
) -> None:
    root, registration, promotion, staged = _durable_hold_case(tmp_path)
    module = importlib.import_module("tradingagents.strategy.shadow_attestation")
    observation_ledger = module.StrategyShadowEvidenceLedger(
        root,
        repo_root=REPO_ROOT,
        clock=lambda: dt.datetime(2030, 4, 1, 14, 2, 5, tzinfo=UTC),
    )
    observation = observation_ledger.admit_observation(
        staged_intent=staged,
        authorization=None,
        observed_at=dt.datetime(2030, 4, 1, 14, 2, tzinfo=UTC),
        paper_order_receipt=None,
        reconciliation_receipt=None,
        actor_role="integrity_verifier",
    )
    assert observation is not None
    ledger = module.StrategyShadowEvidenceLedger(
        root,
        repo_root=REPO_ROOT,
        clock=lambda: dt.datetime(2030, 4, 1, 14, 3, tzinfo=UTC),
    )

    attestation = ledger.assemble(
        promotion_evidence=promotion,
        observations=(observation,),
        actor_role="integrity_verifier",
    )

    assert attestation.paper_account_fingerprint is None
    assert attestation.buy_intents == 0
    assert attestation.reconciliation_confirmed is False
    assert dict(attestation.gates)["at_least_one_reconciled_buy"] is False
    expected_issues = []
    if registration.evolution_policy.minimum_tracked_days > 1:
        expected_issues.append("insufficient_shadow_sessions")
    expected_issues.append("no_reconciled_buy")
    assert attestation.issues == tuple(expected_issues)


def test_standalone_malformed_observation_fails_verify_and_rebuild(
    tmp_path,
) -> None:
    (
        root,
        _,
        _,
        staged,
        authorization,
        receipt,
        reconciliation,
    ) = _durable_buy_case(tmp_path)
    module = importlib.import_module("tradingagents.strategy.shadow_attestation")
    from tradingagents.strategy._immutable_evidence_store import (
        EvidenceCandidate,
        ImmutableStrategyEvidenceStore,
    )

    payload = module._observation_payload(
        staged_intent=staged,
        observed_at="2030-04-01T14:02:00+00:00",
        verified_by_role="integrity_verifier",
        authorization=authorization,
        paper_order_receipt=receipt,
        reconciliation_receipt=reconciliation,
    )
    payload["gates"][2][1] = False
    payload["issues"] = ["reconciliation_not_clean"]
    payload["operationally_reconciled"] = False
    store = ImmutableStrategyEvidenceStore(
        root,
        clock=lambda: dt.datetime(2030, 4, 1, 14, 2, 5, tzinfo=UTC),
    )
    store.admit_checked(
        EvidenceCandidate(
            kind="paper-shadow-observation",
            effective_at="2030-04-01T14:02:00+00:00",
            payload=payload,
        ),
        validate=lambda _snapshot, _envelope: None,
    )
    ledger = module.StrategyShadowEvidenceLedger(root, repo_root=REPO_ROOT)

    with pytest.raises(ValueError, match="invariant"):
        ledger.verify()
    with pytest.raises(ValueError, match="invariant"):
        ledger.rebuild()


def _admit_envelope_payload_at(
    *,
    root: Path,
    envelope,
    recorded_at: dt.datetime,
    payload: dict[str, object] | None = None,
):
    from tradingagents.strategy._immutable_evidence_store import (
        EvidenceCandidate,
        ImmutableStrategyEvidenceStore,
    )

    module = importlib.import_module("tradingagents.strategy.shadow_attestation")
    material = (
        module._thaw_json(envelope.payload)
        if payload is None
        else payload
    )
    assert type(material) is dict
    return ImmutableStrategyEvidenceStore(
        root,
        clock=lambda: recorded_at,
    ).admit_checked(
        EvidenceCandidate(
            kind=envelope.kind,
            effective_at=envelope.effective_at,
            payload=material,
        ),
        validate=lambda _snapshot, _envelope: None,
    ).envelope


@pytest.mark.parametrize("dependency_target", ("observation", "attestation"))
def test_review_fix_later_dependencies_never_repair_earlier_objects(
    tmp_path,
    dependency_target: str,
) -> None:
    from tradingagents.strategy._immutable_evidence_store import (
        ImmutableStrategyEvidenceStore,
    )

    root, _, promotion, observation = _admitted_buy_case(tmp_path)
    module = importlib.import_module("tradingagents.strategy.shadow_attestation")
    if dependency_target == "attestation":
        module.StrategyShadowEvidenceLedger(
            root,
            repo_root=REPO_ROOT,
            clock=lambda: dt.datetime(2030, 4, 1, 14, 3, tzinfo=UTC),
        ).assemble(
            promotion_evidence=promotion,
            observations=(observation,),
            actor_role="integrity_verifier",
        )
    snapshot = ImmutableStrategyEvidenceStore(root).rebuild()
    target_kind = (
        "paper-shadow-observation"
        if dependency_target == "observation"
        else "paper-shadow-attestation"
    )
    target = next(item for item in snapshot if item.kind == target_kind)
    destination = tmp_path / f"later-{dependency_target}-dependencies"
    start = dt.datetime(2031, 1, 1, tzinfo=UTC)
    _admit_envelope_payload_at(
        root=destination,
        envelope=target,
        recorded_at=start,
    )
    for offset, envelope in enumerate(
        (item for item in snapshot if item.object_id != target.object_id),
        start=1,
    ):
        _admit_envelope_payload_at(
            root=destination,
            envelope=envelope,
            recorded_at=start + dt.timedelta(seconds=offset),
        )
    replay = module.StrategyShadowEvidenceLedger(
        destination,
        repo_root=REPO_ROOT,
    )

    with pytest.raises(ValueError, match="durable|promotion|staged|dependency"):
        replay.verify()
    with pytest.raises(ValueError, match="durable|promotion|staged|dependency"):
        replay.rebuild()


def test_review_fix_tampered_source_observation_invalidates_attestation(
    tmp_path,
) -> None:
    from tradingagents.strategy._immutable_evidence_store import (
        ImmutableStrategyEvidenceStore,
    )

    root, _, promotion, observation = _admitted_buy_case(tmp_path)
    module = importlib.import_module("tradingagents.strategy.shadow_attestation")
    module.StrategyShadowEvidenceLedger(
        root,
        repo_root=REPO_ROOT,
        clock=lambda: dt.datetime(2030, 4, 1, 14, 3, tzinfo=UTC),
    ).assemble(
        promotion_evidence=promotion,
        observations=(observation,),
        actor_role="integrity_verifier",
    )
    snapshot = ImmutableStrategyEvidenceStore(root).rebuild()
    source_observation = next(
        item
        for item in snapshot
        if item.kind == "paper-shadow-observation"
    )
    source_attestation = next(
        item
        for item in snapshot
        if item.kind == "paper-shadow-attestation"
    )
    tampered_payload = module._thaw_json(source_observation.payload)
    assert type(tampered_payload) is dict
    order = dict(tampered_payload["paper_order_receipt"])
    reconciliation = dict(tampered_payload["reconciliation_receipt"])
    order["fees_usd"] = "0.16"
    reconciliation["observed_fees_usd"] = "0.16"
    tampered_payload.update(
        {
            "paper_order_receipt": order,
            "reconciliation_receipt": reconciliation,
            "receipt_sha256": hashlib.sha256(
                _canonical_test_bytes(order)
            ).hexdigest(),
            "reconciliation_sha256": hashlib.sha256(
                _canonical_test_bytes(reconciliation)
            ).hexdigest(),
        }
    )
    destination = tmp_path / "tampered-source"
    tampered_envelope = None
    for envelope in snapshot:
        recorded = dt.datetime.fromisoformat(envelope.recorded_at)
        if envelope.object_id == source_observation.object_id:
            tampered_envelope = _admit_envelope_payload_at(
                root=destination,
                envelope=envelope,
                recorded_at=recorded,
                payload=tampered_payload,
            )
            continue
        if envelope.object_id == source_attestation.object_id:
            assert tampered_envelope is not None
            tampered_observation = module._observation_from_envelope(
                tampered_envelope
            )
            attestation_payload = module._thaw_json(envelope.payload)
            assert type(attestation_payload) is dict
            attestation_payload["shadow_observation_ids"] = [
                tampered_observation.shadow_observation_id
            ]
            attestation_payload["shadow_observation_sha256s"] = [
                hashlib.sha256(
                    tampered_observation.canonical_json_bytes()
                ).hexdigest()
            ]
            _admit_envelope_payload_at(
                root=destination,
                envelope=envelope,
                recorded_at=recorded,
                payload=attestation_payload,
            )
            continue
        _admit_envelope_payload_at(
            root=destination,
            envelope=envelope,
            recorded_at=recorded,
        )
    replay = module.StrategyShadowEvidenceLedger(
        destination,
        repo_root=REPO_ROOT,
    )

    with pytest.raises(ValueError, match="aggregate|observation"):
        replay.verify()
    with pytest.raises(ValueError, match="aggregate|observation"):
        replay.rebuild()


def test_verify_recomputes_attestation_money_and_rejects_tamper(
    tmp_path,
) -> None:
    root, _, promotion, observation = _admitted_buy_case(tmp_path)
    module = importlib.import_module("tradingagents.strategy.shadow_attestation")
    from tradingagents.strategy._immutable_evidence_store import (
        EvidenceCandidate,
        ImmutableStrategyEvidenceStore,
    )

    snapshot = ImmutableStrategyEvidenceStore(root).rebuild()
    _, registration = module._staged_with_registration_from_snapshot(
        snapshot,
        observation.staged_intent_id,
    )
    effective_at, payload = module._aggregate_payload(
        promotion_evidence=promotion,
        registration=registration,
        observations=(observation,),
        assembled_by_role="integrity_verifier",
    )
    payload["total_fees_usd"] = "0.14"
    store = ImmutableStrategyEvidenceStore(
        root,
        clock=lambda: dt.datetime(2030, 4, 1, 14, 3, tzinfo=UTC),
    )
    store.admit_checked(
        EvidenceCandidate(
            kind="paper-shadow-attestation",
            effective_at=effective_at,
            payload=payload,
        ),
        validate=lambda _snapshot, _envelope: None,
    )
    ledger = module.StrategyShadowEvidenceLedger(root, repo_root=REPO_ROOT)

    with pytest.raises(ValueError, match="replayed aggregate"):
        ledger.verify()
    with pytest.raises(ValueError, match="replayed aggregate"):
        ledger.rebuild()


def _admit_selected_envelopes(
    *,
    source_root: Path,
    destination_root: Path,
    selected: Sequence[object],
) -> None:
    from tradingagents.strategy._immutable_evidence_store import (
        EvidenceCandidate,
        ImmutableStrategyEvidenceStore,
    )

    module = importlib.import_module("tradingagents.strategy.shadow_attestation")
    for envelope in selected:
        recorded_at = dt.datetime.fromisoformat(envelope.recorded_at)  # type: ignore[attr-defined]
        store = ImmutableStrategyEvidenceStore(
            destination_root,
            clock=lambda value=recorded_at: value,
        )
        payload = module._thaw_json(envelope.payload)  # type: ignore[attr-defined]
        assert type(payload) is dict
        store.admit_checked(
            EvidenceCandidate(
                kind=envelope.kind,  # type: ignore[attr-defined]
                effective_at=envelope.effective_at,  # type: ignore[attr-defined]
                payload=payload,
            ),
            validate=lambda _snapshot, _envelope: None,
        )


def test_review_fix_promotion_is_required_before_observation_admission(
    tmp_path,
) -> None:
    from tradingagents.strategy._immutable_evidence_store import (
        STAGED_PAPER_INTENT_KIND,
        ImmutableStrategyEvidenceStore,
    )

    source_parent = tmp_path / "source"
    source_parent.mkdir()
    source_root, _, _, staged = _durable_hold_case(source_parent)
    snapshot = ImmutableStrategyEvidenceStore(source_root).rebuild()
    destination_root = tmp_path / "prefix-without-promotion"
    selected = tuple(
        envelope
        for envelope in snapshot
        if envelope.kind
        in {"evaluation-registration", STAGED_PAPER_INTENT_KIND}
    )
    _admit_selected_envelopes(
        source_root=source_root,
        destination_root=destination_root,
        selected=selected,
    )
    module = importlib.import_module("tradingagents.strategy.shadow_attestation")
    before = _durable_file_bytes(destination_root)
    ledger = module.StrategyShadowEvidenceLedger(
        destination_root,
        repo_root=REPO_ROOT,
        clock=lambda: dt.datetime(2030, 4, 1, 14, 2, 5, tzinfo=UTC),
    )

    with pytest.raises(ValueError, match="promotion"):
        ledger.admit_observation(
            staged_intent=staged,
            authorization=None,
            observed_at=dt.datetime(2030, 4, 1, 14, 2, tzinfo=UTC),
            paper_order_receipt=None,
            reconciliation_receipt=None,
            actor_role="integrity_verifier",
        )

    assert _durable_file_bytes(destination_root) == before


@pytest.mark.parametrize("drift_kind", ("promotion_digest", "evolution_policy"))
def test_review_fix_full_staged_lineage_rejects_schema_valid_drift(
    tmp_path,
    drift_kind: str,
) -> None:
    from tradingagents.strategy._immutable_evidence_store import (
        ImmutableStrategyEvidenceStore,
    )
    from tradingagents.strategy.staged_intent import StagedPaperIntent

    source_parent = tmp_path / "source"
    source_parent.mkdir()
    source_root, _, _, staged = _durable_hold_case(source_parent)
    staged_payload = staged.to_dict()
    if drift_kind == "promotion_digest":
        staged_payload["promotion_evidence_sha256"] = "0" * 64
    else:
        policy = dict(staged_payload["evolution_policy"])  # type: ignore[arg-type]
        policy["minimum_tracked_days"] = (
            int(policy["minimum_tracked_days"]) + 1
        )
        staged_payload["evolution_policy"] = policy
        staged_payload["evolution_policy_sha256"] = hashlib.sha256(
            _canonical_test_bytes(policy)
        ).hexdigest()
    _reidentify_journal_payload(
        staged_payload,
        kind="staged-paper-intent",
        id_field="staged_intent_id",
    )
    changed_staged = StagedPaperIntent.from_dict(staged_payload)

    source_snapshot = ImmutableStrategyEvidenceStore(source_root).rebuild()
    destination_root = tmp_path / f"drift-{drift_kind}"
    selected = tuple(
        envelope
        for envelope in source_snapshot
        if envelope.kind
        in {"evaluation-registration", "promotion-evidence"}
    )
    _admit_selected_envelopes(
        source_root=source_root,
        destination_root=destination_root,
        selected=selected,
    )
    from tradingagents.strategy._immutable_evidence_store import EvidenceCandidate

    ImmutableStrategyEvidenceStore(
        destination_root,
        clock=lambda: dt.datetime.fromisoformat(changed_staged.recorded_at),
    ).admit_checked(
        EvidenceCandidate(
            kind="staged-paper-intent",
            effective_at=changed_staged.effective_at,
            payload=changed_staged._evidence_payload(),
        ),
        validate=lambda _snapshot, _envelope: None,
    )
    module = importlib.import_module("tradingagents.strategy.shadow_attestation")
    ledger = module.StrategyShadowEvidenceLedger(
        destination_root,
        repo_root=REPO_ROOT,
        clock=lambda: dt.datetime(2030, 4, 1, 14, 2, 5, tzinfo=UTC),
    )
    before = _durable_file_bytes(destination_root)

    with pytest.raises(ValueError, match="lineage|promotion|policy"):
        ledger.admit_observation(
            staged_intent=changed_staged,
            authorization=None,
            observed_at=dt.datetime(2030, 4, 1, 14, 2, tzinfo=UTC),
            paper_order_receipt=None,
            reconciliation_receipt=None,
            actor_role="integrity_verifier",
        )

    assert _durable_file_bytes(destination_root) == before


def _partial_pair(module, receipt, reconciliation):
    order_payload = receipt.to_dict()
    order_payload["status"] = "partially_filled"
    reconciliation_payload = reconciliation.to_dict()
    reconciliation_payload["observed_status"] = "partially_filled"
    return (
        module.PaperOrderReceipt.from_dict(order_payload),
        module.PaperReconciliationReceipt.from_dict(reconciliation_payload),
    )


def test_review_fix_partial_uses_store_clock_for_future_rejection(
    tmp_path,
) -> None:
    (
        root,
        _,
        _,
        staged,
        authorization,
        receipt,
        reconciliation,
    ) = _durable_buy_case(tmp_path)
    module = importlib.import_module("tradingagents.strategy.shadow_attestation")
    partial_receipt, partial_reconciliation = _partial_pair(
        module,
        receipt,
        reconciliation,
    )
    before = _durable_file_bytes(root)
    ledger = module.StrategyShadowEvidenceLedger(
        root,
        repo_root=REPO_ROOT,
        clock=lambda: dt.datetime(2030, 4, 1, 14, 1, 59, tzinfo=UTC),
    )

    with pytest.raises(ValueError, match="future"):
        ledger.admit_observation(
            staged_intent=staged,
            authorization=authorization,
            observed_at=dt.datetime(2030, 4, 1, 14, 2, tzinfo=UTC),
            paper_order_receipt=partial_receipt,
            reconciliation_receipt=partial_reconciliation,
            actor_role="integrity_verifier",
        )

    assert _durable_file_bytes(root) == before


def test_review_fix_partial_clock_equality_writes_nothing_then_terminal(
    tmp_path,
) -> None:
    (
        root,
        _,
        _,
        staged,
        authorization,
        receipt,
        reconciliation,
    ) = _durable_buy_case(tmp_path)
    module = importlib.import_module("tradingagents.strategy.shadow_attestation")
    partial_receipt, partial_reconciliation = _partial_pair(
        module,
        receipt,
        reconciliation,
    )
    ledger = module.StrategyShadowEvidenceLedger(
        root,
        repo_root=REPO_ROOT,
        clock=lambda: dt.datetime(2030, 4, 1, 14, 2, tzinfo=UTC),
    )
    before = _durable_file_bytes(root)

    assert (
        ledger.admit_observation(
            staged_intent=staged,
            authorization=authorization,
            observed_at=dt.datetime(2030, 4, 1, 14, 2, tzinfo=UTC),
            paper_order_receipt=partial_receipt,
            reconciliation_receipt=partial_reconciliation,
            actor_role="integrity_verifier",
        )
        is None
    )
    assert _durable_file_bytes(root) == before

    terminal = ledger.admit_observation(
        staged_intent=staged,
        authorization=authorization,
        observed_at=dt.datetime(2030, 4, 1, 14, 2, tzinfo=UTC),
        paper_order_receipt=receipt,
        reconciliation_receipt=reconciliation,
        actor_role="integrity_verifier",
    )
    assert terminal is not None


def test_review_fix_partial_rejects_global_broker_collision(
    tmp_path,
) -> None:
    from tests.test_strategy_paper_execution_authorization import _authorize_once
    from tests.test_strategy_staged_intent import _stage_with_times

    (
        root,
        registration,
        promotion,
        first_staged,
        first_authorization,
        first_receipt,
        first_reconciliation,
    ) = _durable_buy_case(tmp_path)
    module = importlib.import_module("tradingagents.strategy.shadow_attestation")
    first_ledger = module.StrategyShadowEvidenceLedger(
        root,
        repo_root=REPO_ROOT,
        clock=lambda: dt.datetime(2030, 4, 1, 14, 2, 5, tzinfo=UTC),
    )
    assert first_ledger.admit_observation(
        staged_intent=first_staged,
        authorization=first_authorization,
        observed_at=dt.datetime(2030, 4, 1, 14, 2, tzinfo=UTC),
        paper_order_receipt=first_receipt,
        reconciliation_receipt=first_reconciliation,
        actor_role="integrity_verifier",
    )
    _, second_staged = _stage_with_times(
        root,
        registration,
        promotion,
        clock_time=dt.datetime(2030, 4, 2, 14, 0, 5, tzinfo=UTC),
        effective_at=dt.datetime(2030, 4, 2, 14, 0, tzinfo=UTC),
        expires_at=dt.datetime(2030, 4, 2, 14, 15, tzinfo=UTC),
        session_date="2030-04-02",
    )
    _, second_authorization = _authorize_once(
        root,
        second_staged,
        paper_account_id="paper-account-456",
        clock_time=dt.datetime(2030, 4, 2, 14, 1, 5, tzinfo=UTC),
        effective_at=dt.datetime(2030, 4, 2, 14, 1, tzinfo=UTC),
        expires_at=dt.datetime(2030, 4, 2, 14, 14, tzinfo=UTC),
    )
    authorization_sha256 = hashlib.sha256(
        second_authorization.canonical_json_bytes()
    ).hexdigest()
    order_payload = first_receipt.to_dict()
    order_payload.update(
        {
            "authorization_id": second_authorization.authorization_id,
            "authorization_sha256": authorization_sha256,
            "logical_order_sha256": second_authorization.logical_order_sha256,
            "client_order_id": second_authorization.client_order_id,
            "paper_account_fingerprint": (
                second_authorization.paper_account_fingerprint
            ),
            "symbol": second_authorization.symbol,
            "requested_notional_usd": (
                second_authorization.requested_notional_usd
            ),
            "requested_limit_price": second_authorization.requested_limit_price,
            "status": "partially_filled",
            "submitted_at": "2030-04-02T14:01:05+00:00",
            "last_seen_at": "2030-04-02T14:02:00+00:00",
        }
    )
    reconciliation_payload = first_reconciliation.to_dict()
    reconciliation_payload.update(
        {
            "authorization_id": second_authorization.authorization_id,
            "authorization_sha256": authorization_sha256,
            "logical_order_sha256": second_authorization.logical_order_sha256,
            "client_order_id": second_authorization.client_order_id,
            "paper_account_fingerprint": (
                second_authorization.paper_account_fingerprint
            ),
            "observed_symbol": second_authorization.symbol,
            "observed_requested_notional_usd": (
                second_authorization.requested_notional_usd
            ),
            "observed_requested_limit_price": (
                second_authorization.requested_limit_price
            ),
            "observed_status": "partially_filled",
            "checked_at": "2030-04-02T14:02:00+00:00",
        }
    )
    partial_receipt = module.PaperOrderReceipt.from_dict(order_payload)
    partial_reconciliation = module.PaperReconciliationReceipt.from_dict(
        reconciliation_payload
    )
    ledger = module.StrategyShadowEvidenceLedger(
        root,
        repo_root=REPO_ROOT,
        clock=lambda: dt.datetime(2030, 4, 2, 14, 2, 5, tzinfo=UTC),
    )
    before = _durable_file_bytes(root)

    with pytest.raises(ValueError, match="broker_order_id"):
        ledger.admit_observation(
            staged_intent=second_staged,
            authorization=second_authorization,
            observed_at=dt.datetime(2030, 4, 2, 14, 2, tzinfo=UTC),
            paper_order_receipt=partial_receipt,
            reconciliation_receipt=partial_reconciliation,
            actor_role="integrity_verifier",
        )

    assert _durable_file_bytes(root) == before


def _envelope_for_payload(
    *,
    kind: str,
    effective_at: str,
    recorded_at: str,
    payload: dict[str, object],
):
    from tradingagents.strategy._immutable_evidence_store import EvidenceEnvelope

    payload_sha256 = hashlib.sha256(_canonical_test_bytes(payload)).hexdigest()
    retry_sha256 = hashlib.sha256(
        _canonical_test_bytes(
            {
                "kind": kind,
                "effective_at": effective_at,
                "payload": payload,
            }
        )
    ).hexdigest()
    return EvidenceEnvelope(
        kind=kind,
        object_id=f"{kind}-{retry_sha256}",
        effective_at=effective_at,
        recorded_at=recorded_at,
        retry_material_sha256=retry_sha256,
        payload_sha256=payload_sha256,
        payload=payload,
    )


def _change_nested_order_identity(
    payload: dict[str, object],
    *,
    logical: str,
    client: str,
    broker: str,
) -> None:
    order = dict(payload["paper_order_receipt"])
    reconciliation = dict(payload["reconciliation_receipt"])
    for nested in (order, reconciliation):
        nested["logical_order_sha256"] = logical
        nested["client_order_id"] = client
        nested["broker_order_id"] = broker
    payload.update(
        {
            "paper_order_receipt": order,
            "reconciliation_receipt": reconciliation,
            "receipt_sha256": hashlib.sha256(
                _canonical_test_bytes(order)
            ).hexdigest(),
            "reconciliation_sha256": hashlib.sha256(
                _canonical_test_bytes(reconciliation)
            ).hexdigest(),
        }
    )
    _reidentify_journal_payload(
        payload,
        kind="paper-shadow-observation",
        id_field="shadow_observation_id",
    )


@pytest.mark.parametrize("source_kind", ("event", "orphan"))
@pytest.mark.parametrize(
    "collision",
    ("logical_order_sha256", "client_order_id", "broker_order_id"),
)
def test_review_fix_partial_global_identity_collision_indexes(
    tmp_path,
    source_kind: str,
    collision: str,
) -> None:
    _, registration, promotion, _ = _durable_hold_case(tmp_path)
    module = importlib.import_module("tradingagents.strategy.shadow_attestation")
    first_payload = _aggregate_observation_payload(
        registration=registration,
        promotion=promotion,
        ordinal=1,
        decision_action="buy",
    )
    second_payload = _aggregate_observation_payload(
        registration=registration,
        promotion=promotion,
        ordinal=2,
        decision_action="buy",
    )
    if collision == "logical_order_sha256":
        _change_nested_order_identity(
            second_payload,
            logical="3" * 64,
            client="ta-p-" + "3" * 40,
            broker="different-broker",
        )
    elif collision == "client_order_id":
        _change_nested_order_identity(
            second_payload,
            logical="3" * 40 + "4" * 24,
            client="ta-p-" + "3" * 40,
            broker="different-broker",
        )
    else:
        _change_nested_order_identity(
            second_payload,
            logical="5" * 64,
            client="ta-p-" + "5" * 40,
            broker="paper-broker-order-123",
        )
    first = module.AdmittedPaperShadowObservation.from_dict(first_payload)
    second = module.AdmittedPaperShadowObservation.from_dict(second_payload)
    envelope = _envelope_for_payload(
        kind="paper-shadow-observation",
        effective_at=first.effective_at,
        recorded_at=first.recorded_at,
        payload=first._evidence_payload(),
    )

    with pytest.raises(ValueError, match=collision):
        module._require_observation_uniqueness(
            (envelope,),
            second,
            tolerate_invalid=source_kind == "orphan",
        )


@pytest.mark.parametrize("collision", ("logical_order_sha256", "client_order_id"))
def test_review_fix_partial_authorization_orphan_collision(
    tmp_path,
    collision: str,
) -> None:
    (
        _,
        registration,
        promotion,
        _,
        authorization,
        _,
        _,
    ) = _durable_buy_case(tmp_path)
    module = importlib.import_module("tradingagents.strategy.shadow_attestation")
    payload = _aggregate_observation_payload(
        registration=registration,
        promotion=promotion,
        ordinal=33,
        decision_action="buy",
    )
    logical = authorization.logical_order_sha256
    if collision == "client_order_id":
        logical = logical[:40] + (
            "0" if logical[40] != "0" else "1"
        ) + logical[41:]
    _change_nested_order_identity(
        payload,
        logical=logical,
        client=authorization.client_order_id,
        broker="unrelated-broker",
    )
    candidate = module.AdmittedPaperShadowObservation.from_dict(payload)
    envelope = _envelope_for_payload(
        kind="paper-execution-authorization",
        effective_at=authorization.effective_at,
        recorded_at=authorization.recorded_at,
        payload=authorization._evidence_payload(),
    )

    with pytest.raises(ValueError, match=collision):
        module._require_observation_uniqueness(
            (envelope,),
            candidate,
            tolerate_invalid=True,
        )


def test_review_fix_invalid_and_unrelated_orphans_are_neutral(tmp_path) -> None:
    _, registration, promotion, _ = _durable_hold_case(tmp_path)
    module = importlib.import_module("tradingagents.strategy.shadow_attestation")
    candidate = module.AdmittedPaperShadowObservation.from_dict(
        _aggregate_observation_payload(
            registration=registration,
            promotion=promotion,
            ordinal=90,
            decision_action="buy",
        )
    )
    malformed = candidate._evidence_payload()
    malformed["verified_by_role"] = "human"
    invalid = _envelope_for_payload(
        kind="paper-shadow-observation",
        effective_at=candidate.effective_at,
        recorded_at=candidate.recorded_at,
        payload=malformed,
    )
    unrelated = _envelope_for_payload(
        kind="promotion-evidence",
        effective_at=candidate.effective_at,
        recorded_at=candidate.recorded_at,
        payload={"unrelated": True},
    )

    module._require_observation_uniqueness(
        (invalid, unrelated),
        candidate,
        tolerate_invalid=True,
    )


@pytest.mark.parametrize(
    "action",
    ("hold", "terminal", "partial", "aggregate"),
)
def test_review_fix_locked_write_rederives_verify_authority(
    tmp_path,
    monkeypatch,
    action: str,
) -> None:
    module = importlib.import_module("tradingagents.strategy.shadow_attestation")
    if action == "hold":
        root, _, _, staged = _durable_hold_case(tmp_path)
        authorization = receipt = reconciliation = promotion = observation = None
        clock = dt.datetime(2030, 4, 1, 14, 2, 5, tzinfo=UTC)
    else:
        (
            root,
            _,
            promotion,
            staged,
            authorization,
            receipt,
            reconciliation,
        ) = _durable_buy_case(tmp_path)
        clock = dt.datetime(2030, 4, 1, 14, 2, 5, tzinfo=UTC)
        observation = None
        if action == "partial":
            receipt, reconciliation = _partial_pair(
                module,
                receipt,
                reconciliation,
            )
        elif action == "aggregate":
            stable_ledger = module.StrategyShadowEvidenceLedger(
                root,
                repo_root=REPO_ROOT,
                clock=lambda: clock,
            )
            observation = stable_ledger.admit_observation(
                staged_intent=staged,
                authorization=authorization,
                observed_at=dt.datetime(2030, 4, 1, 14, 2, tzinfo=UTC),
                paper_order_receipt=receipt,
                reconciliation_receipt=reconciliation,
                actor_role="integrity_verifier",
            )
            assert observation is not None
            clock = dt.datetime(2030, 4, 1, 14, 3, tzinfo=UTC)
    original = module.authority_for
    verify_calls = 0

    def drifting_authority(action_class):
        nonlocal verify_calls
        verdict = original(action_class)
        if action_class is module.ActionClass.VERIFY:
            verify_calls += 1
            if verify_calls > 1:
                return dataclasses.replace(
                    verdict,
                    owner_role="drifted_verifier",
                )
        return verdict

    monkeypatch.setattr(module, "authority_for", drifting_authority)
    ledger = module.StrategyShadowEvidenceLedger(
        root,
        repo_root=REPO_ROOT,
        clock=lambda: clock,
    )
    before = _durable_file_bytes(root)

    with pytest.raises(ValueError, match="VERIFY|actor_role|drifted"):
        if action == "aggregate":
            ledger.assemble(
                promotion_evidence=promotion,
                observations=(observation,),
                actor_role="integrity_verifier",
            )
        else:
            ledger.admit_observation(
                staged_intent=staged,
                authorization=authorization,
                observed_at=dt.datetime(2030, 4, 1, 14, 2, tzinfo=UTC),
                paper_order_receipt=receipt,
                reconciliation_receipt=reconciliation,
                actor_role="integrity_verifier",
            )

    assert _durable_file_bytes(root) == before


@pytest.mark.parametrize("authority_kind", ("verify", "order_submit"))
@pytest.mark.parametrize(
    "operation",
    ("admission", "partial", "assembly", "verify", "rebuild"),
)
def test_review_fix_authority_drift_fails_every_shadow_path(
    tmp_path,
    monkeypatch,
    authority_kind: str,
    operation: str,
) -> None:
    module = importlib.import_module("tradingagents.strategy.shadow_attestation")
    (
        root,
        _,
        promotion,
        staged,
        authorization,
        receipt,
        reconciliation,
    ) = _durable_buy_case(tmp_path)
    ledger = module.StrategyShadowEvidenceLedger(
        root,
        repo_root=REPO_ROOT,
        clock=lambda: dt.datetime(2030, 4, 1, 14, 2, 5, tzinfo=UTC),
    )
    observation = None
    if operation not in {"admission", "partial"}:
        observation = ledger.admit_observation(
            staged_intent=staged,
            authorization=authorization,
            observed_at=dt.datetime(2030, 4, 1, 14, 2, tzinfo=UTC),
            paper_order_receipt=receipt,
            reconciliation_receipt=reconciliation,
            actor_role="integrity_verifier",
        )
        assert observation is not None
    if operation in {"verify", "rebuild"}:
        module.StrategyShadowEvidenceLedger(
            root,
            repo_root=REPO_ROOT,
            clock=lambda: dt.datetime(2030, 4, 1, 14, 3, tzinfo=UTC),
        ).assemble(
            promotion_evidence=promotion,
            observations=(observation,),
            actor_role="integrity_verifier",
        )
    if operation == "partial":
        receipt, reconciliation = _partial_pair(
            module,
            receipt,
            reconciliation,
        )

    original = module.authority_for
    drift_class = (
        module.ActionClass.VERIFY
        if authority_kind == "verify"
        else module.ActionClass.ORDER_SUBMIT
    )

    def drifted_authority(action_class):
        authority = original(action_class)
        if action_class is drift_class:
            return dataclasses.replace(
                authority,
                owner_role=f"drifted_{authority_kind}",
            )
        return authority

    monkeypatch.setattr(module, "authority_for", drifted_authority)
    before = _durable_file_bytes(root)
    replay = module.StrategyShadowEvidenceLedger(
        root,
        repo_root=REPO_ROOT,
        clock=lambda: dt.datetime(2030, 4, 1, 14, 3, tzinfo=UTC),
    )

    with pytest.raises(ValueError, match="role|VERIFY|actor|submit"):
        if operation in {"admission", "partial"}:
            replay.admit_observation(
                staged_intent=staged,
                authorization=authorization,
                observed_at=dt.datetime(2030, 4, 1, 14, 2, tzinfo=UTC),
                paper_order_receipt=receipt,
                reconciliation_receipt=reconciliation,
                actor_role="integrity_verifier",
            )
        elif operation == "assembly":
            replay.assemble(
                promotion_evidence=promotion,
                observations=(observation,),
                actor_role="integrity_verifier",
            )
        else:
            getattr(replay, operation)()

    assert _durable_file_bytes(root) == before


@pytest.mark.parametrize(
    ("field_name", "nested_field"),
    (
        ("receipt_sha256", "paper_order_receipt"),
        ("reconciliation_sha256", "reconciliation_receipt"),
    ),
)
def test_review_fix_nested_receipt_digest_is_recomputed(
    field_name: str,
    nested_field: str,
) -> None:
    module = importlib.import_module("tradingagents.strategy.shadow_attestation")
    valid = module.AdmittedPaperShadowObservation.from_dict(
        _buy_observation_payload()
    )
    with pytest.raises(ValueError, match="digest"):
        dataclasses.replace(valid, **{field_name: "0" * 64})

    payload = _buy_observation_payload()
    payload[field_name] = "0" * 64
    _reidentify_journal_payload(
        payload,
        kind="paper-shadow-observation",
        id_field="shadow_observation_id",
    )
    with pytest.raises(ValueError, match="digest"):
        module.AdmittedPaperShadowObservation.from_dict(payload)
    assert getattr(valid, field_name) == hashlib.sha256(
        getattr(valid, nested_field).canonical_json_bytes()
    ).hexdigest()


class _OversizedHostileSequence(Sequence):
    def __init__(self) -> None:
        self.accesses = 0

    def __len__(self) -> int:
        return 4097

    def __getitem__(self, index):
        self.accesses += 1
        raise AssertionError("oversized sequence was consumed")


def test_review_fix_aggregate_checks_len_before_snapshot(tmp_path) -> None:
    root, _, promotion, _ = _admitted_buy_case(tmp_path)
    module = importlib.import_module("tradingagents.strategy.shadow_attestation")
    hostile = _OversizedHostileSequence()
    ledger = module.StrategyShadowEvidenceLedger(
        root,
        repo_root=REPO_ROOT,
        clock=lambda: dt.datetime(2030, 4, 1, 14, 3, tzinfo=UTC),
    )

    with pytest.raises(ValueError, match="too many"):
        ledger.assemble(
            promotion_evidence=promotion,
            observations=hostile,
            actor_role="integrity_verifier",
        )

    assert hostile.accesses == 0


class _ChangingBoundedSequence(Sequence):
    def __init__(self, observation) -> None:
        self.observation = observation

    def __len__(self) -> int:
        return 1

    def __getitem__(self, index):
        if index in (0, 1):
            return self.observation
        raise IndexError(index)


def test_review_fix_bounded_sequence_materialization_change_rejects(
    tmp_path,
) -> None:
    root, _, promotion, observation = _admitted_buy_case(tmp_path)
    module = importlib.import_module("tradingagents.strategy.shadow_attestation")
    before = _durable_file_bytes(root)

    with pytest.raises(ValueError, match="changed during snapshot"):
        module.StrategyShadowEvidenceLedger(
            root,
            repo_root=REPO_ROOT,
            clock=lambda: dt.datetime(2030, 4, 1, 14, 3, tzinfo=UTC),
        ).assemble(
            promotion_evidence=promotion,
            observations=_ChangingBoundedSequence(observation),
            actor_role="integrity_verifier",
        )

    assert _durable_file_bytes(root) == before


def _aggregate_observation_payload(
    *,
    registration,
    promotion,
    ordinal: int,
    decision_action: str = "hold-cash",
) -> dict[str, object]:
    payload = (
        _hold_observation_payload()
        if decision_action == "hold-cash"
        else _buy_observation_payload()
    )
    payload.update(
        {
            "staged_intent_id": (
                "staged-paper-intent-" + f"{ordinal:064x}"
            ),
            "staged_intent_sha256": f"{ordinal + 1:064x}",
            "promotion_evidence_id": promotion.evidence_id,
            "genome_id": promotion.genome_id,
            "genome_canonical_sha256": (
                promotion.genome_canonical_sha256
            ),
            "evaluation_code_commit": promotion.evaluation_code_commit,
            "evaluation_runtime_sha256": (
                promotion.evaluation_runtime_sha256
            ),
            "session_date": "2030-04-01",
            "observed_at": "2030-04-01T14:02:00+00:00",
            "effective_at": "2030-04-01T14:02:00+00:00",
            "recorded_at": "2030-04-01T14:02:05+00:00",
        }
    )
    assert registration.registration_id == promotion.registration_id
    _reidentify_journal_payload(
        payload,
        kind="paper-shadow-observation",
        id_field="shadow_observation_id",
    )
    return payload


def test_review_fix_exactly_4096_observations_are_aggregated(tmp_path) -> None:
    _, registration, promotion, _ = _durable_hold_case(tmp_path)
    module = importlib.import_module(
        "tradingagents.strategy.shadow_attestation"
    )
    observations = tuple(
        module.AdmittedPaperShadowObservation.from_dict(
            _aggregate_observation_payload(
                registration=registration,
                promotion=promotion,
                ordinal=ordinal,
            )
        )
        for ordinal in range(4096)
    )

    _, payload = module._aggregate_payload(
        promotion_evidence=promotion,
        registration=registration,
        observations=observations,
        assembled_by_role="integrity_verifier",
    )

    assert payload["total_intents"] == 4096
    assert payload["hold_intents"] == 4096


def test_review_fix_precision_96_cross_scale_cent_boundary(tmp_path) -> None:
    _, registration, promotion, _ = _durable_hold_case(tmp_path)
    module = importlib.import_module(
        "tradingagents.strategy.shadow_attestation"
    )
    observations = []
    operands = (
        (
            "9999999999999999999999999999999999",
            "9999999999999999999999999999999999",
        ),
        ("0.099999999999", "0.100000000001"),
    )
    for ordinal, (quantity, average) in enumerate(operands, start=1):
        payload = _aggregate_observation_payload(
            registration=registration,
            promotion=promotion,
            ordinal=ordinal,
            decision_action="buy",
        )
        order = dict(payload["paper_order_receipt"])
        order.update(
            {
                "filled_qty": quantity,
                "filled_avg_price": average,
            }
        )
        reconciliation = dict(payload["reconciliation_receipt"])
        reconciliation.update(
            {
                "observed_filled_qty": quantity,
                "observed_filled_avg_price": average,
            }
        )
        payload.update(
            {
                "paper_order_receipt": order,
                "reconciliation_receipt": reconciliation,
                "receipt_sha256": hashlib.sha256(
                    _canonical_test_bytes(order)
                ).hexdigest(),
                "reconciliation_sha256": hashlib.sha256(
                    _canonical_test_bytes(reconciliation)
                ).hexdigest(),
            }
        )
        _reidentify_journal_payload(
            payload,
            kind="paper-shadow-observation",
            id_field="shadow_observation_id",
        )
        observations.append(
            module.AdmittedPaperShadowObservation.from_dict(payload)
        )

    _, payload = module._aggregate_payload(
        promotion_evidence=promotion,
        registration=registration,
        observations=tuple(observations),
        assembled_by_role="integrity_verifier",
    )

    assert payload["total_filled_notional_usd"] == (
        "99999999999999999999999999999999980000000000000000000000000000000001"
    )


@pytest.mark.parametrize(
    ("factory_name", "payload_factory", "field_name", "bad_value"),
    (
        (
            "PaperOrderReceipt",
            _paper_order_receipt_payload,
            "authorization_sha256",
            "A" * 64,
        ),
        (
            "PaperOrderReceipt",
            _paper_order_receipt_payload,
            "authorization_id",
            "wrong-" + "1" * 64,
        ),
        (
            "PaperOrderReceipt",
            _paper_order_receipt_payload,
            "client_order_id",
            "ta-p-" + "g" * 40,
        ),
        (
            "PaperOrderReceipt",
            _paper_order_receipt_payload,
            "paper_account_fingerprint",
            " ",
        ),
        (
            "PaperOrderReceipt",
            _paper_order_receipt_payload,
            "symbol",
            " aapl",
        ),
        (
            "PaperReconciliationReceipt",
            _paper_reconciliation_receipt_payload,
            "verified_by_role",
            "human",
        ),
        (
            "AdmittedPaperShadowObservation",
            _hold_observation_payload,
            "staged_intent_sha256",
            "",
        ),
        (
            "AdmittedPaperShadowObservation",
            _hold_observation_payload,
            "evaluation_code_commit",
            "F" * 40,
        ),
        (
            "StrategyShadowAttestation",
            _shadow_attestation_payload,
            "promotion_evidence_id",
            "promotion-evidence-" + "F" * 64,
        ),
        (
            "StrategyShadowAttestation",
            _shadow_attestation_payload,
            "assembled_by_role",
            " ",
        ),
    ),
)
def test_review_fix_public_models_reject_malformed_identity_domains(
    factory_name: str,
    payload_factory,
    field_name: str,
    bad_value: object,
) -> None:
    module = importlib.import_module("tradingagents.strategy.shadow_attestation")
    payload = payload_factory()
    payload[field_name] = bad_value
    if factory_name == "AdmittedPaperShadowObservation":
        _reidentify_journal_payload(
            payload,
            kind="paper-shadow-observation",
            id_field="shadow_observation_id",
        )
    elif factory_name == "StrategyShadowAttestation":
        _reidentify_journal_payload(
            payload,
            kind="paper-shadow-attestation",
            id_field="shadow_attestation_id",
        )

    with pytest.raises((TypeError, ValueError)):
        getattr(module, factory_name).from_dict(payload)


@pytest.mark.parametrize(
    ("factory_name", "payload_factory", "id_field"),
    (
        (
            "AdmittedPaperShadowObservation",
            _hold_observation_payload,
            "shadow_observation_id",
        ),
        (
            "StrategyShadowAttestation",
            _shadow_attestation_payload,
            "shadow_attestation_id",
        ),
    ),
)
def test_review_fix_journal_object_identity_is_recomputed(
    factory_name: str,
    payload_factory,
    id_field: str,
) -> None:
    module = importlib.import_module("tradingagents.strategy.shadow_attestation")
    valid = getattr(module, factory_name).from_dict(payload_factory())
    valid_id = getattr(valid, id_field)
    with pytest.raises(ValueError, match="identity"):
        dataclasses.replace(valid, **{id_field: valid_id[:-1] + "0"})

    payload = payload_factory()
    payload[id_field] = payload[id_field][:-1] + "0"
    with pytest.raises(ValueError, match="identity"):
        getattr(module, factory_name).from_dict(payload)


def test_isolation_ast_has_no_execution_network_cli_or_model_path() -> None:
    source_path = (
        REPO_ROOT / "tradingagents" / "strategy" / "shadow_attestation.py"
    )
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    imported: set[str] = set()
    called_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imported.add(node.module)
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                called_names.add(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                called_names.add(node.func.attr)

    forbidden_import_prefixes = (
        "requests",
        "httpx",
        "socket",
        "subprocess",
        "tradingagents.cli",
        "tradingagents.execution",
        "tradingagents.llm_clients",
        "tradingagents.live_control",
        "tradingagents.live_gate",
    )
    forbidden_calls = {
        "submit",
        "submit_order",
        "cancel",
        "cancel_order",
        "replace",
        "replace_order",
        "get_order",
        "query_order",
        "invoke",
        "ainvoke",
    }

    assert not any(
        name.startswith(prefix)
        for name in imported
        for prefix in forbidden_import_prefixes
    )
    assert called_names.isdisjoint(forbidden_calls)


def test_review_fix_callback_and_reachable_action_spies(
    tmp_path,
    monkeypatch,
) -> None:
    (
        root,
        _,
        promotion,
        staged,
        authorization,
        receipt,
        reconciliation,
    ) = _durable_buy_case(tmp_path)
    module = importlib.import_module("tradingagents.strategy.shadow_attestation")
    import tradingagents.strategy._immutable_evidence_store as store_module

    path_activity: list[bool] = []
    original_read_bytes = Path.read_bytes
    original_read_text = Path.read_text

    def read_bytes_spy(path):
        path_activity.append(
            bool(
                getattr(
                    store_module._VALIDATOR_ACTIVITY,
                    "active",
                    False,
                )
            )
        )
        return original_read_bytes(path)

    def read_text_spy(path, *args, **kwargs):
        path_activity.append(
            bool(
                getattr(
                    store_module._VALIDATOR_ACTIVITY,
                    "active",
                    False,
                )
            )
        )
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_bytes", read_bytes_spy)
    monkeypatch.setattr(Path, "read_text", read_text_spy)
    production_path = str(
        REPO_ROOT / "tradingagents" / "strategy" / "shadow_attestation.py"
    )
    called: set[str] = set()

    def profile(frame, event, _arg):
        if event == "call" and frame.f_code.co_filename == production_path:
            called.add(frame.f_code.co_name)

    sys.setprofile(profile)
    try:
        observation = module.StrategyShadowEvidenceLedger(
            root,
            repo_root=REPO_ROOT,
            clock=lambda: dt.datetime(
                2030, 4, 1, 14, 2, 5, tzinfo=UTC
            ),
        ).admit_observation(
            staged_intent=staged,
            authorization=authorization,
            observed_at=dt.datetime(2030, 4, 1, 14, 2, tzinfo=UTC),
            paper_order_receipt=receipt,
            reconciliation_receipt=reconciliation,
            actor_role="integrity_verifier",
        )
        assert observation is not None
        ledger = module.StrategyShadowEvidenceLedger(
            root,
            repo_root=REPO_ROOT,
            clock=lambda: dt.datetime(2030, 4, 1, 14, 3, tzinfo=UTC),
        )
        attestation = ledger.assemble(
            promotion_evidence=promotion,
            observations=(observation,),
            actor_role="integrity_verifier",
        )
        assert ledger.verify() == (attestation,)
        assert ledger.rebuild() == (attestation,)
    finally:
        sys.setprofile(None)

    assert not any(path_activity)
    forbidden_actions = {
        "submit",
        "submit_order",
        "cancel",
        "cancel_order",
        "replace",
        "replace_order",
        "get_order",
        "query_order",
        "request",
        "urlopen",
        "connect",
        "invoke",
        "ainvoke",
        "run_cli",
        "call_model",
        "call_tool",
        "write_live_control",
        "open_live_gate",
    }
    assert called.isdisjoint(forbidden_actions)


def test_isolation_exact_forbidden_literals_are_absent() -> None:
    source = (
        REPO_ROOT / "tradingagents" / "strategy" / "shadow_attestation.py"
    ).read_text(encoding="utf-8")

    for forbidden in (
        "tradingagents.execution",
        "tradingagents.cli",
        "tradingagents.llm_clients",
        "live_control.json",
        "live_gate",
        "submit_order(",
        "cancel_order(",
        "replace_order(",
        "get_order(",
        "requests.",
        "httpx.",
    ):
        assert forbidden not in source
