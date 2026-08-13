"""Risk-envelope loading for live eligibility gates."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path


@dataclass(frozen=True)
class RiskEnvelope:
    account_max_capital_at_risk_usd: Decimal
    per_name_cap_usd: Decimal
    per_sector_cap_pct: Decimal
    aggregate_beta_cap: Decimal
    daily_loss_halt_usd: Decimal
    max_drawdown_halt_pct: Decimal
    tiny_live_tranche_usd: Decimal
    tiny_live_max_loss_usd: Decimal
    new_sleeve_auto_promote: bool
    alert_email: str
    live_budget_mode: str = "fixed_tranche"
    # Optional hard account-exposure ceiling. Absent (None) -> inert.
    account_hard_ceiling_usd: Decimal | None = None
    # Optional rolling-window live-order rate limit. Both must be set to enforce.
    # Absent (None) -> inert / no behavior change.
    max_live_orders_per_window: int | None = None
    live_order_window_minutes: int | None = None


_DECIMAL_FIELDS = {
    "account_max_capital_at_risk_usd",
    "per_name_cap_usd",
    "per_sector_cap_pct",
    "aggregate_beta_cap",
    "daily_loss_halt_usd",
    "max_drawdown_halt_pct",
    "tiny_live_tranche_usd",
    "tiny_live_max_loss_usd",
}
_BOOL_FIELDS = {"new_sleeve_auto_promote"}
_STRING_FIELDS = {"alert_email"}
_REQUIRED_FIELDS = _DECIMAL_FIELDS | _BOOL_FIELDS | _STRING_FIELDS
_OPTIONAL_STRING_FIELDS = {"live_budget_mode"}
_OPTIONAL_DECIMAL_FIELDS = {"account_hard_ceiling_usd"}
_OPTIONAL_INT_FIELDS = {"max_live_orders_per_window", "live_order_window_minutes"}
_LIVE_BUDGET_MODES = {"fixed_tranche", "autonomous_with_caps"}


def _parse_simple_yaml(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        values[key.strip()] = value.strip().strip("\"'")
    return values


def _decimal(value: str, field_name: str, issues: list[str]) -> Decimal | None:
    try:
        parsed = Decimal(value)
    except (InvalidOperation, ValueError):
        issues.append(f"{field_name} must be a decimal value")
        return None
    if parsed <= 0:
        issues.append(f"{field_name} must be greater than zero")
        return None
    return parsed


def _int(value: str, field_name: str, issues: list[str]) -> int | None:
    try:
        parsed = int(str(value).strip())
    except (ValueError, TypeError):
        issues.append(f"{field_name} must be an integer value")
        return None
    if parsed <= 0:
        issues.append(f"{field_name} must be greater than zero")
        return None
    return parsed


def _boolean(value: str, field_name: str, issues: list[str]) -> bool | None:
    normalized = value.strip().lower()
    if normalized in {"true", "yes", "1"}:
        return True
    if normalized in {"false", "no", "0"}:
        return False
    issues.append(f"{field_name} must be true or false")
    return None


def load_risk_envelope(path: str | Path) -> tuple[RiskEnvelope | None, list[str]]:
    envelope_path = Path(path)
    if not envelope_path.exists():
        return None, [f"risk envelope missing at {envelope_path}"]

    raw_values = _parse_simple_yaml(envelope_path)
    issues: list[str] = []
    for field_name in sorted(_REQUIRED_FIELDS - raw_values.keys()):
        issues.append(f"missing required risk envelope field: {field_name}")

    parsed: dict[str, Decimal | bool | str | int] = {}
    for field_name in sorted(_DECIMAL_FIELDS & raw_values.keys()):
        value = _decimal(raw_values[field_name], field_name, issues)
        if value is not None:
            parsed[field_name] = value
    for field_name in sorted(_OPTIONAL_DECIMAL_FIELDS & raw_values.keys()):
        value = _decimal(raw_values[field_name], field_name, issues)
        if value is not None:
            parsed[field_name] = value
    for field_name in sorted(_OPTIONAL_INT_FIELDS & raw_values.keys()):
        int_value = _int(raw_values[field_name], field_name, issues)
        if int_value is not None:
            parsed[field_name] = int_value
    for field_name in sorted(_BOOL_FIELDS & raw_values.keys()):
        value = _boolean(raw_values[field_name], field_name, issues)
        if value is not None:
            parsed[field_name] = value
    for field_name in sorted(_STRING_FIELDS & raw_values.keys()):
        value = raw_values[field_name].strip()
        if value:
            parsed[field_name] = value
        else:
            issues.append(f"{field_name} must not be blank")
    for field_name in sorted(_OPTIONAL_STRING_FIELDS & raw_values.keys()):
        value = raw_values[field_name].strip()
        if value:
            parsed[field_name] = value
        else:
            issues.append(f"{field_name} must not be blank")

    for pct_field in ("per_sector_cap_pct", "max_drawdown_halt_pct"):
        pct_value = parsed.get(pct_field)
        if isinstance(pct_value, Decimal) and pct_value > 1:
            issues.append(f"{pct_field} must be less than or equal to 1.0")
    live_budget_mode = str(parsed.get("live_budget_mode", "fixed_tranche"))
    if live_budget_mode not in _LIVE_BUDGET_MODES:
        issues.append(
            "live_budget_mode must be one of: "
            + ", ".join(sorted(_LIVE_BUDGET_MODES))
        )

    if issues:
        return None, issues

    return RiskEnvelope(
        **{
            field_name: parsed[field_name]
            for field_name in _REQUIRED_FIELDS
        },
        live_budget_mode=live_budget_mode,
        account_hard_ceiling_usd=parsed.get("account_hard_ceiling_usd"),
        max_live_orders_per_window=parsed.get("max_live_orders_per_window"),
        live_order_window_minutes=parsed.get("live_order_window_minutes"),
    ), []
