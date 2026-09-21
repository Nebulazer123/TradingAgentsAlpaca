"""Risk-envelope loading for live eligibility gates."""

from __future__ import annotations

import fcntl
import os
import stat
from contextlib import contextmanager
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
_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_DIRECTORY = getattr(os, "O_DIRECTORY", 0)


def risk_envelope_lock_path(path: str | Path) -> Path:
    """Canonical advisory lock adjacent to one mutable envelope file.

    Any future in-repository writer of risk-envelope *content* must acquire
    :func:`risk_envelope_lock` before replacing bytes.  There is currently no
    production content writer: owner authorization records snapshots elsewhere
    and never modify the envelope source itself.  Submit-time consumers hold
    this lock across their final hash proof and raw transport boundary.
    """

    envelope = Path(path)
    return envelope.with_name(f".{envelope.name}.risk-envelope.lock")


def _risk_envelope_path_error(detail: str) -> ValueError:
    return ValueError(f"risk envelope protected path is unsafe: {detail}")


def _validate_risk_envelope_directory(metadata: os.stat_result) -> None:
    if not stat.S_ISDIR(metadata.st_mode):
        raise _risk_envelope_path_error("directory component is not a directory")
    if metadata.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        raise _risk_envelope_path_error("directory component is group/other writable")
    if metadata.st_uid not in {0, os.geteuid()}:
        raise _risk_envelope_path_error("directory component has an unexpected owner")


def _validate_risk_envelope_file(metadata: os.stat_result) -> None:
    if not stat.S_ISREG(metadata.st_mode):
        raise _risk_envelope_path_error("final path is not a regular file")
    if metadata.st_uid != os.geteuid():
        raise _risk_envelope_path_error("file is not owned by effective uid")
    if metadata.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        raise _risk_envelope_path_error("file is group/other writable")


@contextmanager
def _risk_envelope_parent_fd(path: str | Path):
    """Pin every parent component without following a writable redirect."""

    target = Path(os.path.abspath(os.fspath(path)))
    if not target.is_absolute() or target.name in {"", ".", ".."}:
        raise _risk_envelope_path_error("final path name is unsafe")
    try:
        descriptor = os.open(target.anchor, os.O_RDONLY | _DIRECTORY | _NOFOLLOW)
    except OSError as exc:
        raise _risk_envelope_path_error(f"cannot open filesystem root: {exc}") from exc
    try:
        _validate_risk_envelope_directory(os.fstat(descriptor))
        for component in target.parent.parts[1:]:
            try:
                child = os.open(
                    component,
                    os.O_RDONLY | _DIRECTORY | _NOFOLLOW,
                    dir_fd=descriptor,
                )
            except OSError as exc:
                raise _risk_envelope_path_error(
                    f"cannot safely open directory component {component}: {exc}"
                ) from exc
            try:
                _validate_risk_envelope_directory(os.fstat(child))
            except BaseException:
                os.close(child)
                raise
            os.close(descriptor)
            descriptor = child
        yield descriptor, target.name, target
    finally:
        os.close(descriptor)


def read_risk_envelope_bytes_locked(path: str | Path) -> bytes:
    """No-follow, descriptor-relative bytes for a caller holding the shared lock.

    The final normal-live consumer invokes this immediately before raw broker
    transport.  The caller owns :func:`risk_envelope_lock`; this primitive
    deliberately does no second flock so lock ordering stays explicit.
    """

    with _risk_envelope_parent_fd(path) as (parent_fd, name, target):
        try:
            descriptor = os.open(name, os.O_RDONLY | _NOFOLLOW, dir_fd=parent_fd)
        except OSError as exc:
            raise _risk_envelope_path_error(f"cannot safely open {target}: {exc}") from exc
        try:
            _validate_risk_envelope_file(os.fstat(descriptor))
            chunks: list[bytes] = []
            while True:
                chunk = os.read(descriptor, 1 << 20)
                if not chunk:
                    return b"".join(chunks)
                chunks.append(chunk)
        except OSError as exc:
            raise _risk_envelope_path_error(f"cannot read {target}: {exc}") from exc
        finally:
            os.close(descriptor)


@contextmanager
def risk_envelope_lock(path: str | Path):
    """Serialize envelope-content writers with final submit-time verification.

    The lock is intentionally independent of live-control state: callers may
    hold it around broker I/O without preventing a safety freeze from taking
    the live-control lock.  A link, non-regular file, foreign owner, or
    group/other-writable lock fails closed rather than becoming an alias for
    another process' coordination file.
    """

    envelope = Path(path)
    lock_path = risk_envelope_lock_path(envelope)
    with _risk_envelope_parent_fd(envelope) as (parent_fd, _name, _target):
        try:
            descriptor = os.open(
                lock_path.name,
                os.O_CREAT | os.O_RDWR | _NOFOLLOW,
                0o600,
                dir_fd=parent_fd,
            )
        except OSError as exc:
            raise ValueError(f"risk envelope lock is unavailable: {exc}") from exc
        try:
            _validate_risk_envelope_file(os.fstat(descriptor))
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            yield lock_path
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)


def _parse_simple_yaml_text(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        values[key.strip()] = value.strip().strip("\"'")
    return values


def _parse_simple_yaml(path: Path) -> dict[str, str]:
    return _parse_simple_yaml_text(path.read_text(encoding="utf-8"))


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


def _load_risk_envelope_values(
    raw_values: dict[str, str],
) -> tuple[RiskEnvelope | None, list[str]]:
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


def load_risk_envelope_text(
    text: str,
) -> tuple[RiskEnvelope | None, list[str]]:
    """Parse one stored UTF-8 envelope snapshot without filesystem I/O."""

    if type(text) is not str:
        return None, ["risk envelope snapshot must be text"]
    return _load_risk_envelope_values(_parse_simple_yaml_text(text))


def load_risk_envelope(path: str | Path) -> tuple[RiskEnvelope | None, list[str]]:
    envelope_path = Path(path)
    if not envelope_path.exists():
        return None, [f"risk envelope missing at {envelope_path}"]

    return _load_risk_envelope_values(_parse_simple_yaml(envelope_path))


def is_monotonic_risk_tightening(
    previous: RiskEnvelope,
    current: RiskEnvelope,
) -> bool:
    """Return True only when no live-risk capability becomes broader.

    Lower numeric exposure/loss/drawdown caps are tighter.  A newly configured
    hard ceiling or rate window is tighter; removing one is expansion.  For a
    configured rate window, a lower/equal count across a longer/equal window
    is tighter.  Budget-mode changes and automatic-promotion enablement are
    deliberately unclassifiable/expansive and therefore require owner review.
    Alert routing is operational metadata and does not affect risk authority.
    """

    numeric_caps = (
        "account_max_capital_at_risk_usd",
        "per_name_cap_usd",
        "per_sector_cap_pct",
        "aggregate_beta_cap",
        "daily_loss_halt_usd",
        "max_drawdown_halt_pct",
        "tiny_live_tranche_usd",
        "tiny_live_max_loss_usd",
    )
    if any(
        getattr(current, field) > getattr(previous, field)
        for field in numeric_caps
    ):
        return False
    if previous.live_budget_mode != current.live_budget_mode:
        return False
    if not previous.new_sleeve_auto_promote and current.new_sleeve_auto_promote:
        return False

    previous_ceiling = previous.account_hard_ceiling_usd
    current_ceiling = current.account_hard_ceiling_usd
    if previous_ceiling is not None and (
        current_ceiling is None or current_ceiling > previous_ceiling
    ):
        return False

    previous_rate = (
        previous.max_live_orders_per_window,
        previous.live_order_window_minutes,
    )
    current_rate = (
        current.max_live_orders_per_window,
        current.live_order_window_minutes,
    )
    previous_configured = all(value is not None for value in previous_rate)
    current_configured = all(value is not None for value in current_rate)
    previous_unconfigured = all(value is None for value in previous_rate)
    current_unconfigured = all(value is None for value in current_rate)
    if not (previous_configured or previous_unconfigured):
        return False
    if not (current_configured or current_unconfigured):
        return False
    if previous_configured and not current_configured:
        return False
    if previous_configured and current_configured:
        assert previous_rate[0] is not None and previous_rate[1] is not None
        assert current_rate[0] is not None and current_rate[1] is not None
        if (
            current_rate[0] > previous_rate[0]
            or current_rate[1] < previous_rate[1]
        ):
            return False
    return True
