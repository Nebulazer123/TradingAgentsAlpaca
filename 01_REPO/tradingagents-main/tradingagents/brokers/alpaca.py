"""Alpaca paper/live execution helpers.

The module is deliberately small and explicit: paper and live credentials are
loaded separately, account mode is checked before submit, and live mirroring is
represented as a deterministic child order of the paper strategy order.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import ROUND_DOWN, Decimal

import requests

from tradingagents.execution.authorized_normal_trade_intent import AuthorizedNormalTradeIntent
from tradingagents.policy.strategy_promotion_sync import (
    NormalLiveActivationReceipt,
    execute_normal_live_broker_submit,
)
from tradingagents.schemas.trading import TradeIntent

PAPER_BASE_URL = "https://paper-api.alpaca.markets"
LIVE_BASE_URL = "https://api.alpaca.markets"


class AlpacaConfigError(RuntimeError):
    """Raised when required Alpaca configuration is missing."""


class AlpacaModeError(RuntimeError):
    """Raised when a paper/live client is pointed at the wrong endpoint."""


class AlpacaExecutionError(RuntimeError):
    """Raised when Alpaca rejects or fails an HTTP request."""


@dataclass(frozen=True)
class AlpacaSubmitErrorClassification:
    category: str
    retry_action: str
    message: str
    retry_safe: bool = False
    idempotency_conflict: bool = False


UTC = datetime.timezone.utc
TUESDAY_LIVE_RUN_ID = "20260526-tuesday"


def _as_decimal(value: Decimal | int | float | str) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _money(value: Decimal | int | float | str) -> str:
    return str(_as_decimal(value).quantize(Decimal("0.01"), rounding=ROUND_DOWN))


def _price(value: Decimal | int | float | str) -> str:
    return str(_as_decimal(value).quantize(Decimal("0.01"), rounding=ROUND_DOWN))


@dataclass(frozen=True)
class AlpacaExecutionConfig:
    paper_enabled: bool = False
    live_mirror_enabled: bool = False
    paper_exposure_limit: Decimal = Decimal("1000")
    live_mirror_ratio: Decimal = Decimal("0.10")
    live_exposure_limit: Decimal = Decimal("100")

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> AlpacaExecutionConfig:
        env = os.environ if environ is None else environ
        return cls(
            paper_enabled=_env_bool(env, "TRADINGAGENTS_ALPACA_PAPER_ENABLED", False),
            live_mirror_enabled=_env_bool(
                env, "TRADINGAGENTS_ALPACA_LIVE_MIRROR_ENABLED", False
            ),
            paper_exposure_limit=_env_decimal(
                env, "TRADINGAGENTS_PAPER_EXPOSURE_LIMIT", Decimal("1000")
            ),
            live_mirror_ratio=_env_decimal(
                env, "TRADINGAGENTS_LIVE_MIRROR_RATIO", Decimal("0.10")
            ),
            live_exposure_limit=_env_decimal(
                env, "TRADINGAGENTS_LIVE_EXPOSURE_LIMIT", Decimal("100")
            ),
        )


@dataclass(frozen=True)
class LiveExecutionPolicy:
    """One-time live-money policy for the Tuesday 2026-05-26 strategy run."""

    allowed_live_run_id: str = TUESDAY_LIVE_RUN_ID
    live_entry_starts_at: datetime.datetime = datetime.datetime(
        2026, 5, 26, 12, 45, tzinfo=UTC
    )
    live_entry_ends_at: datetime.datetime = datetime.datetime(
        2026, 5, 26, 14, 30, tzinfo=UTC
    )
    live_management_ends_at: datetime.datetime = datetime.datetime(
        2026, 5, 29, 20, 0, tzinfo=UTC
    )
    allowed_management_actions: frozenset[str] = frozenset(
        {"hold", "cancel", "reduce", "close"}
    )


def _env_bool(env: Mapping[str, str], name: str, default: bool) -> bool:
    raw = _get_env(env, name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in ("true", "1", "yes", "on")


def _env_decimal(env: Mapping[str, str], name: str, default: Decimal) -> Decimal:
    raw = _get_env(env, name)
    if raw is None or raw == "":
        return default
    return Decimal(raw)


def _read_windows_user_env(name: str) -> str | None:
    if os.name != "nt":
        return None
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            value, _ = winreg.QueryValueEx(key, name)
            return value
    except OSError:
        return None


def _get_env(env: Mapping[str, str], name: str) -> str:
    return env.get(name) or _read_windows_user_env(name) or ""


def _normalize_base_url(url: str) -> str:
    clean = url.rstrip("/")
    if clean.lower().endswith("/v2"):
        return clean[:-3]
    return clean


def classify_alpaca_submit_error(
    exc: Exception,
    *,
    account: str = "",
    client_order_id: str = "",
) -> AlpacaSubmitErrorClassification:
    raw = str(exc).strip() or exc.__class__.__name__
    lower = raw.lower()
    account_label = account.lower() or "broker"
    id_label = client_order_id or "unknown"
    duplicate_id = (
        ("client_order_id" in lower or "client order id" in lower)
        and any(
            marker in lower
            for marker in (
                "already",
                "duplicate",
                "exists",
                "must be unique",
                "40310000",
            )
        )
    )
    if duplicate_id:
        return AlpacaSubmitErrorClassification(
            category="duplicate_client_order_id",
            retry_action="reconcile_existing_order",
            retry_safe=False,
            idempotency_conflict=True,
            message=(
                f"{account_label} submit hit duplicate client_order_id {id_label}; "
                "do not create a replacement order id. Reconcile broker open/recent "
                f"orders before retrying. Broker said: {raw}"
            ),
        )
    return AlpacaSubmitErrorClassification(
        category="broker_submit_failed",
        retry_action="inspect_broker_response_then_retry_if_safe",
        retry_safe=False,
        message=f"{account_label} submit failed for {id_label}: {raw}",
    )


_ORDER_SUMMARY_FIELDS = (
    "id",
    "client_order_id",
    "symbol",
    "side",
    "type",
    "time_in_force",
    "qty",
    "notional",
    "limit_price",
    "status",
    "filled_qty",
    "filled_avg_price",
    "submitted_at",
    "updated_at",
)
_UNSAFE_RECONCILED_ORDER_STATUSES = {
    "canceled",
    "cancelled",
    "expired",
    "rejected",
    "stopped",
    "suspended",
}


def compact_alpaca_order(order: Mapping) -> dict:
    return {
        field: order.get(field)
        for field in _ORDER_SUMMARY_FIELDS
        if order.get(field) not in (None, "")
    }


def _decimal_equal(
    left: object,
    right: object,
    *,
    quantum: Decimal,
) -> bool:
    try:
        return _as_decimal(left).quantize(quantum, rounding=ROUND_DOWN) == _as_decimal(
            right
        ).quantize(quantum, rounding=ROUND_DOWN)
    except Exception:
        return False


def compare_alpaca_order_to_intent(
    existing_order: Mapping,
    intended_order: Mapping,
) -> list[str]:
    issues: list[str] = []
    status = str(existing_order.get("status") or "").lower()
    if status in _UNSAFE_RECONCILED_ORDER_STATUSES:
        issues.append(f"existing order status is {status}")

    for order_field in ("symbol", "side", "type"):
        intended_value = str(intended_order.get(order_field) or "").lower()
        existing_value = str(existing_order.get(order_field) or "").lower()
        if intended_value and existing_value != intended_value:
            issues.append(
                f"{order_field} mismatch intended={intended_order.get(order_field)} existing={existing_order.get(order_field)}"
            )

    if intended_order.get("limit_price") not in (None, "") and not _decimal_equal(
        existing_order.get("limit_price"),
        intended_order.get("limit_price"),
        quantum=Decimal("0.01"),
    ):
        issues.append(
            "limit_price mismatch "
            f"intended={intended_order.get('limit_price')} "
            f"existing={existing_order.get('limit_price')}"
        )

    if intended_order.get("notional") not in (None, "") and not _decimal_equal(
        existing_order.get("notional"),
        intended_order.get("notional"),
        quantum=Decimal("0.01"),
    ):
        issues.append(
            "notional mismatch "
            f"intended={intended_order.get('notional')} "
            f"existing={existing_order.get('notional')}"
        )

    if intended_order.get("qty") not in (None, "") and not _decimal_equal(
        existing_order.get("qty"),
        intended_order.get("qty"),
        quantum=Decimal("0.000001"),
    ):
        issues.append(
            f"qty mismatch intended={intended_order.get('qty')} existing={existing_order.get('qty')}"
        )

    return issues


def find_order_by_client_order_id(client: object, client_order_id: str) -> dict | None:
    if not client_order_id:
        return None
    get_by_client_id = getattr(client, "get_order_by_client_order_id", None)
    if callable(get_by_client_id):
        order = get_by_client_id(client_order_id)
        return compact_alpaca_order(order) if isinstance(order, Mapping) else None

    list_orders = getattr(client, "list_orders", None)
    if not callable(list_orders):
        return None
    for status in ("open", "all", "closed"):
        try:
            orders = list_orders(status=status)
        except TypeError:
            orders = list_orders()
        for order in orders or []:
            if not isinstance(order, Mapping):
                continue
            if str(order.get("client_order_id", "")) == client_order_id:
                return compact_alpaca_order(order)
    return None


@dataclass(frozen=True)
class AlpacaSettings:
    api_key: str
    secret_key: str
    paper: bool
    base_url: str
    timeout: int = 15

    @classmethod
    def from_env(
        cls, *, paper: bool, environ: Mapping[str, str] | None = None
    ) -> AlpacaSettings:
        env = os.environ if environ is None else environ
        prefix = "PAPER" if paper else "LIVE"
        key_name = f"ALPACA_{prefix}_API_KEY"
        secret_name = f"ALPACA_{prefix}_SECRET_KEY"
        api_key = _get_env(env, key_name)
        secret_key = _get_env(env, secret_name)
        if not api_key or not secret_key:
            raise AlpacaConfigError(f"{key_name} and {secret_name} must be set")
        endpoint_name = f"ALPACA_{prefix}_API_ENDPOINT"
        base_name = f"ALPACA_{prefix}_BASE_URL"
        return cls(
            api_key=api_key,
            secret_key=secret_key,
            paper=paper,
            base_url=_normalize_base_url(
                _get_env(env, endpoint_name)
                or _get_env(env, base_name)
                or (PAPER_BASE_URL if paper else LIVE_BASE_URL)
            ),
        )


@dataclass(frozen=True)
class StrategyOrder:
    ticket_id: str
    symbol: str
    side: str
    notional: Decimal
    limit_price: Decimal
    extended_hours: bool = False
    time_in_force: str = "day"

    def __post_init__(self):
        side = self.side.lower()
        if side != "buy":
            raise ValueError("v1 Alpaca execution only supports buy orders")
        if _as_decimal(self.notional) <= 0:
            raise ValueError("notional must be positive")
        if _as_decimal(self.limit_price) <= 0:
            raise ValueError("limit_price must be positive")


@dataclass(frozen=True)
class PlannedOrder:
    ticket_id: str
    order: dict
    parent_client_order_id: str | None = None


@dataclass(frozen=True)
class OrderPair:
    paper: PlannedOrder
    live: PlannedOrder


@dataclass(frozen=True)
class OrderIssue:
    ticket_id: str
    reason: str


@dataclass(frozen=True)
class BuildOrderPairsResult:
    accepted: list[OrderPair] = field(default_factory=list)
    rejected: list[OrderIssue] = field(default_factory=list)
    skipped: list[OrderIssue] = field(default_factory=list)


@dataclass(frozen=True)
class BuildPaperOrdersResult:
    accepted: list[PlannedOrder] = field(default_factory=list)
    rejected: list[OrderIssue] = field(default_factory=list)
    skipped: list[OrderIssue] = field(default_factory=list)


@dataclass(frozen=True)
class SubmittedOrderPair:
    pair: OrderPair
    paper_response: dict
    live_response: dict


@dataclass(frozen=True)
class ExecutionReport:
    submitted: list[SubmittedOrderPair] = field(default_factory=list)
    failed: list[OrderIssue] = field(default_factory=list)


@dataclass(frozen=True)
class PaperExecutionReport:
    submitted: list[dict] = field(default_factory=list)
    failed: list[OrderIssue] = field(default_factory=list)


def validate_live_entry_allowed(
    *,
    run_id: str,
    now: datetime.datetime | None = None,
    policy: LiveExecutionPolicy | None = None,
) -> list[OrderIssue]:
    policy = policy or LiveExecutionPolicy()
    current = _as_utc(now or datetime.datetime.now(tz=UTC))
    issues: list[OrderIssue] = []

    if _safe_component(run_id) != _safe_component(policy.allowed_live_run_id):
        issues.append(
            OrderIssue(
                "live-entry",
                f"{run_id} is not the approved one-time live run "
                f"({policy.allowed_live_run_id})",
            )
        )
    if not (
        _as_utc(policy.live_entry_starts_at)
        <= current
        <= _as_utc(policy.live_entry_ends_at)
    ):
        issues.append(
            OrderIssue(
                "live-entry",
                "live entry window is closed; new live buy orders are blocked",
            )
        )
    return issues


def validate_live_management_action(
    *,
    client_order_id: str,
    action: str,
    now: datetime.datetime | None = None,
    policy: LiveExecutionPolicy | None = None,
) -> OrderIssue | None:
    policy = policy or LiveExecutionPolicy()
    action_name = action.strip().lower()
    if action_name not in policy.allowed_management_actions:
        return OrderIssue(
            client_order_id,
            f"{action} is not a live management action",
        )

    current = _as_utc(now or datetime.datetime.now(tz=UTC))
    if current > _as_utc(policy.live_management_ends_at):
        return OrderIssue(
            client_order_id,
            "live management window is closed",
        )

    if not client_order_id.startswith(_live_client_order_id_prefix(policy.allowed_live_run_id)):
        return OrderIssue(
            client_order_id,
            "live order is not tied to the approved Tuesday live run",
        )
    return None


def build_order_pairs(
    orders: Sequence[StrategyOrder],
    *,
    config: AlpacaExecutionConfig,
    run_id: str,
    existing_paper_exposure: Decimal = Decimal("0"),
    existing_live_exposure: Decimal = Decimal("0"),
    existing_open_client_order_ids: Iterable[str] | None = None,
) -> BuildOrderPairsResult:
    result = BuildOrderPairsResult()
    open_ids = set(existing_open_client_order_ids or ())
    paper_used = _as_decimal(existing_paper_exposure)
    live_used = _as_decimal(existing_live_exposure)

    for order in orders:
        paper_client_order_id = _client_order_id(run_id, "paper", order.ticket_id)
        live_client_order_id = _client_order_id(run_id, "live", order.ticket_id)
        if paper_client_order_id in open_ids or live_client_order_id in open_ids:
            result.skipped.append(
                OrderIssue(order.ticket_id, "duplicate open order client_order_id")
            )
            continue

        paper_notional = _as_decimal(order.notional)
        live_notional = (paper_notional * config.live_mirror_ratio).quantize(
            Decimal("0.01"), rounding=ROUND_DOWN
        )
        if paper_used + paper_notional > config.paper_exposure_limit:
            result.rejected.append(
                OrderIssue(order.ticket_id, "order would exceed paper exposure limit")
            )
            continue
        paper_payload = _limit_payload(order, paper_client_order_id, paper_notional)
        live_payload = _limit_payload(order, live_client_order_id, live_notional)
        result.accepted.append(
            OrderPair(
                paper=PlannedOrder(order.ticket_id, paper_payload),
                live=PlannedOrder(
                    order.ticket_id,
                    live_payload,
                    parent_client_order_id=paper_client_order_id,
                ),
            )
        )
        paper_used += paper_notional
        live_used += live_notional

    return result


def build_paper_orders(
    orders: Sequence[StrategyOrder],
    *,
    config: AlpacaExecutionConfig,
    run_id: str,
    existing_paper_exposure: Decimal = Decimal("0"),
    existing_open_client_order_ids: Iterable[str] | None = None,
) -> BuildPaperOrdersResult:
    result = BuildPaperOrdersResult()
    open_ids = set(existing_open_client_order_ids or ())
    paper_used = _as_decimal(existing_paper_exposure)

    for order in orders:
        paper_client_order_id = _client_order_id(run_id, "paper", order.ticket_id)
        if paper_client_order_id in open_ids:
            result.skipped.append(
                OrderIssue(order.ticket_id, "duplicate open order client_order_id")
            )
            continue

        paper_notional = _as_decimal(order.notional)
        if paper_used + paper_notional > config.paper_exposure_limit:
            result.rejected.append(
                OrderIssue(order.ticket_id, "order would exceed paper exposure limit")
            )
            continue

        result.accepted.append(
            PlannedOrder(
                ticket_id=order.ticket_id,
                order=_limit_payload(order, paper_client_order_id, paper_notional),
            )
        )
        paper_used += paper_notional

    return result


def _client_order_id(run_id: str, mode: str, ticket_id: str) -> str:
    return _safe_component(f"ta-{run_id}-{mode}-{ticket_id}")[:48]


def _safe_component(value: str) -> str:
    raw = str(value).lower()
    allowed = [ch if ch.isalnum() or ch in ("-", "_") else "-" for ch in raw]
    return "".join(allowed)


def _live_client_order_id_prefix(run_id: str) -> str:
    return f"ta-{_safe_component(run_id)}-live-"


def _as_utc(value: datetime.datetime) -> datetime.datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _limit_payload(order: StrategyOrder, client_order_id: str, notional: Decimal) -> dict:
    return {
        "symbol": order.symbol.upper(),
        "notional": _money(notional),
        "side": order.side.lower(),
        "type": "limit",
        "time_in_force": order.time_in_force.lower(),
        "limit_price": _price(order.limit_price),
        "extended_hours": bool(order.extended_hours),
        "client_order_id": client_order_id,
    }


def build_tiny_live_order_payload(intent: TradeIntent) -> dict:
    """Build a tiny-live Alpaca payload using the intent idempotency key."""

    if intent.environment != "tiny_live":
        raise ValueError("tiny-live payload requires intent.environment='tiny_live'")
    if intent.side != "buy":
        raise ValueError("tiny-live v1 supports buy intents only")
    if intent.order_type != "limit":
        raise ValueError("tiny-live payload requires limit orders")
    if not intent.idempotency_key:
        raise ValueError("tiny-live intent requires an idempotency key")
    client_order_id = _safe_component(intent.idempotency_key)[:48]
    return {
        "symbol": intent.symbol.upper(),
        "side": intent.side,
        "type": "limit",
        "time_in_force": intent.tif.lower(),
        "limit_price": _price(intent.limit_price),
        "notional": _money(intent.size_usd),
        "client_order_id": client_order_id,
        "extended_hours": False,
    }


def _normal_live_utc_now() -> datetime.datetime:
    """Private production clock for the normal-live broker boundary."""

    return datetime.datetime.now(UTC).replace(microsecond=0)


def _normal_live_submit_time() -> datetime.datetime:
    checked_at = _normal_live_utc_now()
    if (
        type(checked_at) is not datetime.datetime
        or checked_at.tzinfo is None
        or checked_at.utcoffset() is None
        or checked_at.microsecond
    ):
        raise ValueError("live submit requires a timezone-aware whole-second time")
    return checked_at.astimezone(UTC)


def _require_normal_live_intent(value: object) -> AuthorizedNormalTradeIntent:
    if type(value) is not AuthorizedNormalTradeIntent:
        raise ValueError("live submit requires an exact AuthorizedNormalTradeIntent")
    if value.live_submit_authorized is not True or value.paper_submit_authorized is not False:
        raise ValueError("normal live intent authorization flags are invalid")
    return value


def _canonical_live_state(state: object) -> bytes:
    if type(state) is not dict:
        raise ValueError("normal live activation receipt state is invalid")
    try:
        return json.dumps(
            state, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("normal live activation receipt state is invalid") from exc


def _require_normal_live_receipt(
    intent: AuthorizedNormalTradeIntent,
    value: object,
) -> NormalLiveActivationReceipt:
    if type(value) is not NormalLiveActivationReceipt:
        raise ValueError("live submit requires an exact NormalLiveActivationReceipt")
    intent_full_sha256 = hashlib.sha256(intent.canonical_json_bytes()).hexdigest()
    if (
        type(value.activation_prepare_id) is not str
        or not value.activation_prepare_id
        or type(value.activation_receipt_id) is not str
        or not value.activation_receipt_id
        or value.intent_full_sha256 != intent_full_sha256
        or value.canonical_before_sha256 != intent.promotion_state_sha256
        or value.canonical_after_sha256
        != hashlib.sha256(_canonical_live_state(value.state)).hexdigest()
        or type(value.created) is not bool
        or value.status not in {"activated", "receipt_repaired", "read_only_retry"}
        or value.can_submit_orders is not False
        or value.execution_authority != "none"
    ):
        raise ValueError("normal live activation receipt does not link to exact intent")
    return value


def _normal_live_order_facts(order: Mapping[str, object]) -> dict[str, object]:
    fields = (
        "symbol",
        "side",
        "type",
        "time_in_force",
        "notional",
        "limit_price",
        "client_order_id",
    )
    if any(field not in order for field in fields):
        raise ValueError("live broker response is ambiguous; refusing retry")
    return {field: order[field] for field in fields}


def _require_matching_broker_order(
    broker_order: object, expected: Mapping[str, object]
) -> None:
    if type(broker_order) is not dict:
        raise ValueError("live broker response is ambiguous; refusing retry")
    actual = _normal_live_order_facts(broker_order)
    if actual != dict(expected):
        raise ValueError("live broker order does not match authorized intent")


class AlpacaRestClient:
    def __init__(
        self,
        settings: AlpacaSettings,
        session=None,
        *,
        normal_live_evidence_root=None,
        normal_live_repo_root=None,
    ):
        self.settings = settings
        self.session = session or requests.Session()
        self.normal_live_evidence_root = normal_live_evidence_root
        self.normal_live_repo_root = normal_live_repo_root

    def assert_expected_mode(self, *, paper: bool) -> None:
        base_url = self.settings.base_url.lower()
        points_to_paper = "paper-api.alpaca.markets" in base_url
        if paper and (not self.settings.paper or not points_to_paper):
            raise AlpacaModeError("paper order client is not configured for paper trading")
        if not paper and (self.settings.paper or points_to_paper):
            raise AlpacaModeError("live order client is not configured for live trading")

    def get_account(self) -> dict:
        self.assert_expected_mode(paper=self.settings.paper)
        return self._request("GET", "/v2/account")

    def list_orders(self, status: str = "open") -> list[dict]:
        self.assert_expected_mode(paper=self.settings.paper)
        return self._request("GET", "/v2/orders", params={"status": status})

    def list_positions(self) -> list[dict]:
        self.assert_expected_mode(paper=self.settings.paper)
        return self._request("GET", "/v2/positions")

    def get_asset(self, symbol: str) -> dict:
        self.assert_expected_mode(paper=self.settings.paper)
        return self._request("GET", f"/v2/assets/{symbol.upper()}")

    def get_clock(self) -> dict:
        self.assert_expected_mode(paper=self.settings.paper)
        return self._request("GET", "/v2/clock")

    def list_calendar(self, *, start: str, end: str) -> list[dict]:
        self.assert_expected_mode(paper=self.settings.paper)
        return self._request("GET", "/v2/calendar", params={"start": start, "end": end})

    def list_open_client_order_ids(self) -> set[str]:
        return {
            order.get("client_order_id", "")
            for order in self.list_orders(status="open")
            if order.get("client_order_id")
        }

    def get_order_by_client_order_id(self, client_order_id: str) -> dict:
        self.assert_expected_mode(paper=self.settings.paper)
        return self._request(
            "GET",
            "/v2/orders:by_client_order_id",
            params={"client_order_id": client_order_id},
        )

    def submit_order(
        self,
        order: Mapping,
        *,
        authorized_normal_trade_intent=None,
        activation_receipt=None,
    ) -> dict:
        self.assert_expected_mode(paper=self.settings.paper)
        if self.settings.paper is True:
            return self._request("POST", "/v2/orders", json=dict(order))

        intent = _require_normal_live_intent(authorized_normal_trade_intent)
        if type(activation_receipt) is not NormalLiveActivationReceipt:
            raise ValueError("live submit requires an exact NormalLiveActivationReceipt")
        checked_at = _normal_live_submit_time()
        if (
            self.normal_live_evidence_root is None
            or self.normal_live_repo_root is None
        ):
            raise ValueError("live submit requires durable normal-live evidence roots")
        receipt = _require_normal_live_receipt(intent, activation_receipt)
        intent.verify_order_payload(order, at=checked_at)
        payload = dict(order)
        client_order_id = intent.client_order_id
        immutable_facts = _normal_live_order_facts(payload)
        facts_bytes = json.dumps(
            dict(immutable_facts),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        broker_result = execute_normal_live_broker_submit(
            intent,
            receipt,
            proposal_ledger_root=self.normal_live_evidence_root,
            repo_root=self.normal_live_repo_root,
            immutable_order_sha256=hashlib.sha256(facts_bytes).hexdigest(),
            lookup=lambda: self._lookup_live_order_by_client_order_id(client_order_id),
            post=lambda: self._request("POST", "/v2/orders", json=payload),
        )
        _require_matching_broker_order(broker_result, immutable_facts)
        return broker_result

    def _lookup_live_order_by_client_order_id(self, client_order_id: str) -> dict | None:
        try:
            result = self.get_order_by_client_order_id(client_order_id)
        except AlpacaExecutionError as exc:
            if " 404:" in str(exc):
                return None
            raise ValueError("live retry lookup is ambiguous; refusing POST") from exc
        if type(result) is not dict:
            raise ValueError("live retry lookup is ambiguous; refusing POST")
        return result

    def _request(self, method: str, path: str, **kwargs):
        url = f"{self.settings.base_url.rstrip('/')}{path}"
        response = self.session.request(
            method,
            url,
            headers={
                "APCA-API-KEY-ID": self.settings.api_key,
                "APCA-API-SECRET-KEY": self.settings.secret_key,
                "Content-Type": "application/json",
            },
            timeout=self.settings.timeout,
            **kwargs,
        )
        if response.status_code >= 400:
            raise AlpacaExecutionError(
                f"Alpaca {method} {path} failed with {response.status_code}: {response.text}"
            )
        return response.json()


def _rollback_paper_leg(
    paper_client,
    paper_response: Mapping,
    *,
    client_order_id: str,
) -> str:
    """Best-effort cancel of an already-submitted paper leg when the mirrored
    live order fails, so the paper and live accounts do not drift out of balance.

    Returns a human-readable note describing the rollback outcome. If the paper
    order cannot be canceled automatically, the note explicitly flags that manual
    reconciliation is required rather than leaving a silent imbalance.
    """
    order_id = str((paper_response or {}).get("id") or "")
    label = client_order_id or order_id or "unknown"
    cancel = getattr(paper_client, "cancel_order", None)
    if callable(cancel) and order_id:
        try:
            cancel(order_id)
        except Exception as cancel_exc:  # pragma: no cover - exercised by tests
            return (
                f"paper leg {label} (order {order_id}) rollback cancel FAILED: "
                f"{cancel_exc}; manual reconciliation required"
            )
        return (
            f"paper leg {label} (order {order_id}) was canceled to keep "
            "paper/live balanced"
        )
    return (
        f"paper leg {label} (order {order_id or 'unknown'}) could not be rolled "
        "back automatically (no cancel capability); manual reconciliation required"
    )


def execute_order_pairs(
    pairs: Sequence[OrderPair],
    *,
    paper_client,
    live_client,
    live_guard_approved: bool = False,
) -> ExecutionReport:
    report = ExecutionReport()
    if pairs:
        for pair in pairs:
            report.failed.append(
                OrderIssue(
                    pair.live.ticket_id,
                    (
                        "execute_order_pairs is permanently disabled for nonempty "
                        "paper/live mirror pairs; neither leg was submitted"
                    ),
                )
            )
        return report

    paper_client.assert_expected_mode(paper=True)
    live_client.assert_expected_mode(paper=False)

    for pair in pairs:
        live_side = str(pair.live.order.get("side", "")).lower()
        if live_side != "buy":
            report.failed.append(
                OrderIssue(
                    pair.live.ticket_id,
                    (
                        "execute_order_pairs only supports paper/live mirrored buy "
                        "orders; live sells must use the supervisor submit path with "
                        "loss_exit_review evidence"
                    ),
                )
            )
            continue
        try:
            paper_response = paper_client.submit_order(pair.paper.order)
        except Exception as exc:  # pragma: no cover - exercised by integration paths
            report.failed.append(
                OrderIssue(
                    pair.paper.ticket_id,
                    f"paper submit failed (no live order attempted): {exc}",
                )
            )
            continue
        try:
            live_response = live_client.submit_order(pair.live.order)
        except Exception as exc:  # pragma: no cover - exercised by integration paths
            rollback_note = _rollback_paper_leg(
                paper_client,
                paper_response,
                client_order_id=str(pair.paper.order.get("client_order_id", "")),
            )
            report.failed.append(
                OrderIssue(
                    pair.live.ticket_id,
                    (
                        "live submit failed AFTER paper submit succeeded: "
                        f"{exc}. {rollback_note}"
                    ),
                )
            )
            continue
        report.submitted.append(
            SubmittedOrderPair(
                pair=pair,
                paper_response=paper_response,
                live_response=live_response,
            )
        )

    return report


def execute_paper_orders(
    orders: Sequence[PlannedOrder],
    *,
    paper_client,
) -> PaperExecutionReport:
    report = PaperExecutionReport()
    paper_client.assert_expected_mode(paper=True)

    for planned in orders:
        try:
            response = paper_client.submit_order(planned.order)
        except Exception as exc:  # pragma: no cover - exercised by integration paths
            report.failed.append(OrderIssue(planned.ticket_id, str(exc)))
            continue
        report.submitted.append(response)

    return report
