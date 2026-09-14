"""Deterministic dependence-aware statistics for weekly TA-Control results."""

from __future__ import annotations

import dataclasses
import datetime as dt
import hashlib
import json
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from types import MappingProxyType

from tradingagents.evals.economic_evaluation_protocol import CONTROL_ARM_IDS

__all__ = [
    "EconomicTournamentStatistics",
    "EconomicTournamentStatisticsError",
    "WeeklyArmObservation",
    "build_economic_tournament_statistics",
    "validate_economic_tournament_statistics",
]

_SCHEMA = "economic_tournament_statistics/v2"
_AUTHORITY = {
    "analysis_only": True,
    "execution_authority": "none",
    "can_submit_orders": False,
}
_REPLICATES = 256
_ALPHA = Decimal("0.05")


class EconomicTournamentStatisticsError(ValueError):
    """Registered weekly statistics are not canonical or dependence-aware."""


def _plain(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if type(value) is tuple:
        return [_plain(item) for item in value]
    return value


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        _plain(value), sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False,
    ).encode("utf-8")


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


def _decimal(value: object, *, label: str) -> Decimal:
    if type(value) is not str:
        raise EconomicTournamentStatisticsError(f"{label} must be a canonical decimal")
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise EconomicTournamentStatisticsError(
            f"{label} must be a canonical decimal"
        ) from exc
    canonical = "0" if parsed.is_zero() else format(parsed.normalize(), "f")
    if not parsed.is_finite() or canonical != value:
        raise EconomicTournamentStatisticsError(f"{label} must be a canonical decimal")
    return parsed


def _text(value: Decimal) -> str:
    return "0" if value.is_zero() else format(value.normalize(), "f")


def _date(value: object, *, label: str) -> str:
    if type(value) is not str:
        raise EconomicTournamentStatisticsError(f"{label} must be an ISO date")
    try:
        parsed = dt.date.fromisoformat(value)
    except ValueError as exc:
        raise EconomicTournamentStatisticsError(f"{label} must be an ISO date") from exc
    if parsed.isoformat() != value:
        raise EconomicTournamentStatisticsError(f"{label} must be an ISO date")
    return value


def _exact(value: object, fields: set[str], *, label: str) -> dict[str, object]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise EconomicTournamentStatisticsError(f"{label} fields are invalid")
    return dict(value)


@dataclasses.dataclass(frozen=True, slots=True)
class WeeklyArmObservation:
    """One weekly portfolio observation, the primary inference unit."""

    market_date: str
    gross_return: str
    net_return: str
    benchmark_net_return: str
    turnover: str
    buy_notional: str
    sell_notional: str
    cost_drag: str
    false_positive: bool
    positions: tuple[tuple[str, str], ...]
    factor_exposures: tuple[tuple[str, str], ...] = ()
    sector_exposures: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        _date(self.market_date, label="market_date")
        for label in (
            "gross_return", "net_return", "benchmark_net_return", "turnover",
            "buy_notional", "sell_notional", "cost_drag",
        ):
            parsed = _decimal(getattr(self, label), label=label)
            if label in {"turnover", "buy_notional", "sell_notional", "cost_drag"} and parsed < 0:
                raise EconomicTournamentStatisticsError(f"{label} cannot be negative")
        if Decimal(self.turnover) != Decimal(self.buy_notional) + Decimal(self.sell_notional):
            raise EconomicTournamentStatisticsError(
                "turnover must equal gross buy plus sell notional"
            )
        if type(self.false_positive) is not bool:
            raise EconomicTournamentStatisticsError("false_positive must be boolean")
        for label, rows in (
            ("positions", self.positions),
            ("factor_exposures", self.factor_exposures),
            ("sector_exposures", self.sector_exposures),
        ):
            if type(rows) is not tuple:
                raise EconomicTournamentStatisticsError(f"{label} must be an exact tuple")
            names = tuple(item[0] for item in rows)
            if names != tuple(sorted(names)) or len(set(names)) != len(names):
                raise EconomicTournamentStatisticsError(f"{label} must be canonical")
            for name, weight in rows:
                if type(name) is not str or not name:
                    raise EconomicTournamentStatisticsError(f"{label} name is invalid")
                _decimal(weight, label=f"{label} weight")


@dataclasses.dataclass(frozen=True, slots=True, init=False)
class EconomicTournamentStatistics:
    statistics_id: str
    statistics_sha256: str
    raw_source_row_count: int
    decision_event_count: int
    packet_event_cluster_count: int
    market_event_cluster_count: int
    unique_decision_date_count: int
    market_dates: tuple[str, ...]
    bootstrap_intervals: tuple[Mapping[str, object], ...]
    arm_diagnostics: tuple[Mapping[str, object], ...]
    walk_forward_folds: tuple[Mapping[str, object], ...]
    multiple_testing: Mapping[str, object]

    def __init__(self, *args: object, **kwargs: object) -> None:
        raise TypeError("EconomicTournamentStatistics instances require its builder")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": _SCHEMA,
            "statistics_id": self.statistics_id,
            "statistics_sha256": self.statistics_sha256,
            "primary_unit": "weekly_market_date",
            "raw_source_row_count": self.raw_source_row_count,
            "decision_event_count": self.decision_event_count,
            "packet_event_cluster_count": self.packet_event_cluster_count,
            "market_event_cluster_count": self.market_event_cluster_count,
            "unique_decision_date_count": self.unique_decision_date_count,
            "market_dates": list(self.market_dates),
            "bootstrap": {
                "method": "deterministic_market_date_block_bootstrap",
                "block_length_dates": min(4, len(self.market_dates)),
                "replicates": _REPLICATES,
                "interval_level": "0.95",
                "intervals": _plain(self.bootstrap_intervals),
            },
            "arm_diagnostics": _plain(self.arm_diagnostics),
            "walk_forward": {
                "method": "purged_embargoed_market_date_folds",
                "purge_sessions": 5,
                "embargo_sessions": 5,
                "folds": _plain(self.walk_forward_folds),
            },
            "multiple_testing": _plain(self.multiple_testing),
            "status": "completed",
            **_AUTHORITY,
        }

    def canonical_json_bytes(self) -> bytes:
        return _canonical_json_bytes(self.to_dict())


def _new_statistics(**fields: object) -> EconomicTournamentStatistics:
    value = object.__new__(EconomicTournamentStatistics)
    for field in dataclasses.fields(EconomicTournamentStatistics):
        object.__setattr__(value, field.name, fields[field.name])
    return value


def _compound(values: tuple[Decimal, ...]) -> Decimal:
    capital = Decimal("1")
    for value in values:
        capital *= Decimal("1") + value
    return capital - Decimal("1")


def _bootstrap_samples(
    *, label: str, market_dates: tuple[str, ...], values: tuple[Decimal, ...]
) -> tuple[Decimal, ...]:
    block = min(4, len(values))
    seed = int(_sha256([label, list(market_dates)])[:16], 16)
    samples: list[Decimal] = []
    for _replicate in range(_REPLICATES):
        selected: list[Decimal] = []
        while len(selected) < len(values):
            seed = (6364136223846793005 * seed + 1442695040888963407) % (2**64)
            start = seed % len(values)
            selected.extend(
                values[(start + offset) % len(values)] for offset in range(block)
            )
        samples.append(_compound(tuple(selected[: len(values)])))
    return tuple(samples)


def _block_bootstrap(
    *, arm_id: str, market_dates: tuple[str, ...], returns: tuple[Decimal, ...]
) -> tuple[str, str, str]:
    point = _compound(returns)
    if len(returns) < 2:
        text = _text(point)
        return text, text, text
    samples = sorted(
        _bootstrap_samples(label=arm_id, market_dates=market_dates, values=returns)
    )
    return (
        _text(min(samples[6], point)),
        _text(point),
        _text(max(samples[249], point)),
    )


def _contrast_test(
    *, contrast_id: str, market_dates: tuple[str, ...], values: tuple[Decimal, ...]
) -> tuple[str, str]:
    observed = sum(values, Decimal("0")) / Decimal(len(values))
    if len(values) < 2:
        return _text(observed), "1"
    centered = tuple(value - observed for value in values)
    block = min(4, len(values))
    seed = int(_sha256([contrast_id, list(market_dates)])[:16], 16)
    samples: list[Decimal] = []
    for _replicate in range(_REPLICATES):
        selected: list[Decimal] = []
        while len(selected) < len(values):
            seed = (6364136223846793005 * seed + 1442695040888963407) % (2**64)
            start = seed % len(values)
            selected.extend(
                centered[(start + offset) % len(values)] for offset in range(block)
            )
        samples.append(sum(selected[: len(values)], Decimal("0")) / Decimal(len(values)))
    extreme = sum(
        1
        for sample in samples
        if abs(sample) >= abs(observed)
    )
    p_value = Decimal(extreme + 1) / Decimal(_REPLICATES + 1)
    return _text(observed), _text(p_value)


def _walk_forward_folds(
    market_dates: tuple[str, ...],
) -> tuple[Mapping[str, object], ...]:
    if len(market_dates) < 6:
        return ()
    folds: list[Mapping[str, object]] = []
    for index, split in enumerate(
        (len(market_dates) // 2, (len(market_dates) * 3) // 4), 1
    ):
        train = market_dates[: max(1, split - 1)]
        purge = market_dates[max(1, split - 1) : split]
        embargo = market_dates[split : split + 1]
        test = market_dates[split + 1 :]
        if test:
            folds.append(
                MappingProxyType(
                    {
                        "fold_id": f"fold-{index}",
                        "training_dates": list(train),
                        "purged_dates": list(purge),
                        "embargoed_dates": list(embargo),
                        "test_dates": list(test),
                    }
                )
            )
    return tuple(folds)


def _aggregate_exposures(
    rows: tuple[WeeklyArmObservation, ...], *, attribute: str, key_name: str
) -> tuple[str, tuple[Mapping[str, object], ...]]:
    all_rows = tuple(getattr(row, attribute) for row in rows)
    if not all(all_rows):
        return "unavailable", ()
    names = tuple(name for name, _value in all_rows[0])
    if any(tuple(name for name, _value in row) != names for row in all_rows):
        return "unavailable", ()
    result = []
    for name in names:
        mean = sum(
            (_decimal(dict(row)[name], label="exposure") for row in all_rows),
            Decimal("0"),
        ) / Decimal(len(all_rows))
        result.append(MappingProxyType({key_name: name, "value": _text(mean)}))
    return "available", tuple(result)


def _position_concentration(
    rows: tuple[WeeklyArmObservation, ...],
) -> Mapping[str, object]:
    per_date: list[Mapping[str, object]] = []
    max_values: list[Decimal] = []
    hhi_values: list[Decimal] = []
    for row in rows:
        weights = tuple(
            abs(_decimal(weight, label="position weight"))
            for _name, weight in row.positions
        )
        total = sum(weights, Decimal("0"))
        normalized = tuple(weight / total for weight in weights) if total else ()
        maximum = max(normalized, default=Decimal("0"))
        hhi = sum((weight * weight for weight in normalized), Decimal("0"))
        max_values.append(maximum)
        hhi_values.append(hhi)
        per_date.append(
            MappingProxyType(
                {"market_date": row.market_date, "max_weight": _text(maximum), "hhi": _text(hhi)}
            )
        )
    return MappingProxyType(
        {
            "method": "weekly_weight_hhi_and_max",
            "cross_date_aggregation": "arithmetic_mean",
            "per_date": tuple(per_date),
            "mean_max_weight": _text(sum(max_values) / Decimal(len(max_values))),
            "mean_hhi": _text(sum(hhi_values) / Decimal(len(hhi_values))),
        }
    )


def build_economic_tournament_statistics(
    *,
    raw_source_row_count: int,
    decision_event_count: int,
    packet_event_cluster_count: int,
    market_event_cluster_count: int,
    observations_by_arm: Mapping[str, tuple[WeeklyArmObservation, ...]],
) -> EconomicTournamentStatistics:
    """Build registered statistics without treating clusters as sample size."""

    counts = (
        raw_source_row_count, decision_event_count,
        packet_event_cluster_count, market_event_cluster_count,
    )
    if any(type(item) is not int or item < 0 for item in counts):
        raise EconomicTournamentStatisticsError(
            "registered counts must be nonnegative integers"
        )
    if not isinstance(observations_by_arm, Mapping) or set(observations_by_arm) != set(CONTROL_ARM_IDS):
        raise EconomicTournamentStatisticsError("statistics require the exact five arms")
    observations = {arm: observations_by_arm[arm] for arm in CONTROL_ARM_IDS}
    market_dates = tuple(item.market_date for item in observations["cash"])
    if not market_dates or market_dates != tuple(sorted(market_dates)) or len(set(market_dates)) != len(market_dates):
        raise EconomicTournamentStatisticsError("weekly market dates must be canonical")
    for arm, rows in observations.items():
        if type(rows) is not tuple or tuple(item.market_date for item in rows) != market_dates:
            raise EconomicTournamentStatisticsError(
                f"{arm} observations must cover the exact weekly market dates"
            )

    intervals: list[Mapping[str, object]] = []
    diagnostics: list[Mapping[str, object]] = []
    for arm in CONTROL_ARM_IDS:
        rows = observations[arm]
        returns = tuple(Decimal(item.net_return) for item in rows)
        lower, point, upper = _block_bootstrap(
            arm_id=arm, market_dates=market_dates, returns=returns
        )
        intervals.append(MappingProxyType(
            {"arm_id": arm, "lower": lower, "point": point, "upper": upper}
        ))
        capital = Decimal("1")
        peak = capital
        drawdown = Decimal("0")
        for returned in returns:
            capital *= Decimal("1") + returned
            peak = max(peak, capital)
            drawdown = min(drawdown, capital / peak - Decimal("1"))
        factor_status, factor_rows = _aggregate_exposures(
            rows, attribute="factor_exposures", key_name="factor"
        )
        sector_status, sector_rows = _aggregate_exposures(
            rows, attribute="sector_exposures", key_name="sector"
        )
        diagnostics.append(MappingProxyType({
            "arm_id": arm,
            "turnover_convention": "gross_security_traded_notional",
            "turnover": _text(sum((Decimal(row.turnover) for row in rows), Decimal("0"))),
            "buy_notional": _text(sum((Decimal(row.buy_notional) for row in rows), Decimal("0"))),
            "sell_notional": _text(sum((Decimal(row.sell_notional) for row in rows), Decimal("0"))),
            "max_drawdown": _text(drawdown),
            "false_positive_rate": _text(
                Decimal(sum(1 for row in rows if row.false_positive)) / Decimal(len(rows))
            ),
            "cost_drag": _text(sum((Decimal(row.cost_drag) for row in rows), Decimal("0"))),
            "factor_exposure_status": factor_status,
            "factor_exposures": factor_rows,
            "sector_exposure_status": sector_status,
            "sector_exposures": sector_rows,
            "position_concentration": _position_concentration(rows),
        }))

    cash_returns = tuple(Decimal(row.net_return) for row in observations["cash"])
    raw_contrasts: list[dict[str, object]] = []
    for arm in CONTROL_ARM_IDS:
        if arm == "cash":
            continue
        rows = observations[arm]
        arm_returns = tuple(Decimal(row.net_return) for row in rows)
        benchmark_returns = tuple(Decimal(row.benchmark_net_return) for row in rows)
        for comparator, comparison in (("benchmark", benchmark_returns), ("cash", cash_returns)):
            contrast_id = f"{arm}_minus_{comparator}"
            statistic, p_value = _contrast_test(
                contrast_id=contrast_id,
                market_dates=market_dates,
                values=tuple(
                    arm_value - comparison_value
                    for arm_value, comparison_value in zip(arm_returns, comparison, strict=True)
                ),
            )
            raw_contrasts.append({
                "contrast_id": contrast_id, "arm_id": arm,
                "comparator": comparator, "test_statistic": statistic,
                "raw_p_value": p_value,
            })
    ranked = sorted(
        raw_contrasts,
        key=lambda row: (Decimal(row["raw_p_value"]), row["contrast_id"]),
    )
    adjusted_floor = Decimal("0")
    still_rejecting = True
    holm_rows: list[Mapping[str, object]] = []
    for index, row in enumerate(ranked):
        remaining = len(ranked) - index
        raw_p = Decimal(row["raw_p_value"])
        adjusted_floor = max(adjusted_floor, min(Decimal("1"), raw_p * remaining))
        threshold = _ALPHA / Decimal(remaining)
        reject = still_rejecting and raw_p <= threshold
        still_rejecting = reject
        holm_rows.append(MappingProxyType({
            **row, "holm_rank": index + 1, "holm_threshold": _text(threshold),
            "holm_adjusted_p_value": _text(adjusted_floor), "reject_null": reject,
        }))
    multiple_testing = MappingProxyType({
        "method": "holm_bonferroni_registered_contrasts",
        "contrast_test": "deterministic_centered_market_date_block_bootstrap_mean",
        "familywise_alpha": "0.05",
        "registered_hypothesis_count": len(holm_rows),
        "diagnostics": tuple(holm_rows),
    })
    fields: dict[str, object] = {
        "raw_source_row_count": raw_source_row_count,
        "decision_event_count": decision_event_count,
        "packet_event_cluster_count": packet_event_cluster_count,
        "market_event_cluster_count": market_event_cluster_count,
        "unique_decision_date_count": len(market_dates),
        "market_dates": market_dates,
        "bootstrap_intervals": tuple(intervals),
        "arm_diagnostics": tuple(diagnostics),
        "walk_forward_folds": _walk_forward_folds(market_dates),
        "multiple_testing": multiple_testing,
    }
    result = _new_statistics(statistics_id="", statistics_sha256="", **fields)
    material = result.to_dict()
    material.pop("statistics_id")
    material.pop("statistics_sha256")
    object.__setattr__(
        result, "statistics_id", "economic-tournament-statistics-" + _sha256(material)
    )
    digest_material = result.to_dict()
    digest_material["statistics_sha256"] = ""
    object.__setattr__(result, "statistics_sha256", _sha256(digest_material))
    return result


def _validate_exposures(
    value: object, *, key_name: str, status: object
) -> tuple[Mapping[str, object], ...]:
    if type(value) is not list:
        raise EconomicTournamentStatisticsError("statistics exposures are invalid")
    rows: list[Mapping[str, object]] = []
    names: list[str] = []
    for item in value:
        row = _exact(item, {key_name, "value"}, label="exposure")
        if type(row[key_name]) is not str or not row[key_name]:
            raise EconomicTournamentStatisticsError("exposure name is invalid")
        _decimal(row["value"], label="exposure value")
        names.append(row[key_name])
        rows.append(MappingProxyType(row))
    if names != sorted(names) or len(set(names)) != len(names):
        raise EconomicTournamentStatisticsError("exposures are not canonical")
    if status not in {"available", "unavailable"} or (status == "available") != bool(rows):
        raise EconomicTournamentStatisticsError("exposure status is inconsistent")
    return tuple(rows)


def validate_economic_tournament_statistics(value: object) -> EconomicTournamentStatistics:
    """Strictly rebuild nested fields and both statistics identities."""

    payload = _exact(value, {
        "schema_version", "statistics_id", "statistics_sha256", "primary_unit",
        "raw_source_row_count", "decision_event_count", "packet_event_cluster_count",
        "market_event_cluster_count", "unique_decision_date_count", "market_dates",
        "bootstrap", "arm_diagnostics", "walk_forward", "multiple_testing", "status",
        *_AUTHORITY,
    }, label="statistics")
    if (
        payload["schema_version"] != _SCHEMA
        or payload["primary_unit"] != "weekly_market_date"
        or payload["status"] != "completed"
        or any(payload[key] != expected for key, expected in _AUTHORITY.items())
    ):
        raise EconomicTournamentStatisticsError("statistics schema or authority is invalid")
    count_fields = (
        "raw_source_row_count", "decision_event_count", "packet_event_cluster_count",
        "market_event_cluster_count", "unique_decision_date_count",
    )
    if any(type(payload[field]) is not int or payload[field] < 0 for field in count_fields):
        raise EconomicTournamentStatisticsError("statistics counts are invalid")
    if type(payload["market_dates"]) is not list:
        raise EconomicTournamentStatisticsError("statistics market dates are invalid")
    market_dates = tuple(_date(item, label="market_date") for item in payload["market_dates"])
    if market_dates != tuple(sorted(market_dates)) or len(set(market_dates)) != len(market_dates) or payload["unique_decision_date_count"] != len(market_dates):
        raise EconomicTournamentStatisticsError("statistics market dates are invalid")

    bootstrap = _exact(payload["bootstrap"], {
        "method", "block_length_dates", "replicates", "interval_level", "intervals"
    }, label="bootstrap")
    if (
        bootstrap["method"] != "deterministic_market_date_block_bootstrap"
        or bootstrap["block_length_dates"] != min(4, len(market_dates))
        or bootstrap["replicates"] != _REPLICATES
        or bootstrap["interval_level"] != "0.95"
        or type(bootstrap["intervals"]) is not list
    ):
        raise EconomicTournamentStatisticsError("statistics bootstrap is invalid")
    intervals: list[Mapping[str, object]] = []
    for item in bootstrap["intervals"]:
        row = _exact(item, {"arm_id", "lower", "point", "upper"}, label="interval")
        lower = _decimal(row["lower"], label="lower")
        point = _decimal(row["point"], label="point")
        upper = _decimal(row["upper"], label="upper")
        if lower > point or point > upper:
            raise EconomicTournamentStatisticsError("bootstrap interval order is invalid")
        intervals.append(MappingProxyType(row))
    if tuple(item["arm_id"] for item in intervals) != CONTROL_ARM_IDS:
        raise EconomicTournamentStatisticsError("statistics intervals are invalid")

    if type(payload["arm_diagnostics"]) is not list:
        raise EconomicTournamentStatisticsError("statistics diagnostics are invalid")
    diagnostic_fields = {
        "arm_id", "turnover_convention", "turnover", "buy_notional", "sell_notional",
        "max_drawdown", "false_positive_rate", "cost_drag", "factor_exposure_status",
        "factor_exposures", "sector_exposure_status", "sector_exposures",
        "position_concentration",
    }
    diagnostics: list[Mapping[str, object]] = []
    for item in payload["arm_diagnostics"]:
        row = _exact(item, diagnostic_fields, label="arm diagnostic")
        if row["turnover_convention"] != "gross_security_traded_notional":
            raise EconomicTournamentStatisticsError("turnover convention is invalid")
        for field in ("turnover", "buy_notional", "sell_notional", "max_drawdown", "false_positive_rate", "cost_drag"):
            _decimal(row[field], label=field)
        if Decimal(row["turnover"]) != Decimal(row["buy_notional"]) + Decimal(row["sell_notional"]):
            raise EconomicTournamentStatisticsError("traded notional is inconsistent")
        row["factor_exposures"] = _validate_exposures(
            row["factor_exposures"], key_name="factor", status=row["factor_exposure_status"]
        )
        row["sector_exposures"] = _validate_exposures(
            row["sector_exposures"], key_name="sector", status=row["sector_exposure_status"]
        )
        concentration = _exact(row["position_concentration"], {
            "method", "cross_date_aggregation", "per_date", "mean_max_weight", "mean_hhi"
        }, label="position concentration")
        if (
            concentration["method"] != "weekly_weight_hhi_and_max"
            or concentration["cross_date_aggregation"] != "arithmetic_mean"
            or type(concentration["per_date"]) is not list
        ):
            raise EconomicTournamentStatisticsError("position concentration is invalid")
        per_date = []
        for value_at_date in concentration["per_date"]:
            parsed = _exact(value_at_date, {"market_date", "max_weight", "hhi"}, label="date concentration")
            _date(parsed["market_date"], label="concentration market date")
            _decimal(parsed["max_weight"], label="max weight")
            _decimal(parsed["hhi"], label="hhi")
            per_date.append(MappingProxyType(parsed))
        if tuple(item["market_date"] for item in per_date) != market_dates:
            raise EconomicTournamentStatisticsError("concentration dates are invalid")
        mean_max = _decimal(concentration["mean_max_weight"], label="mean max weight")
        mean_hhi = _decimal(concentration["mean_hhi"], label="mean hhi")
        if (
            mean_max
            != sum((Decimal(item["max_weight"]) for item in per_date), Decimal("0"))
            / Decimal(len(per_date))
            or mean_hhi
            != sum((Decimal(item["hhi"]) for item in per_date), Decimal("0"))
            / Decimal(len(per_date))
        ):
            raise EconomicTournamentStatisticsError(
                "concentration aggregation is inconsistent"
            )
        concentration["per_date"] = tuple(per_date)
        row["position_concentration"] = MappingProxyType(concentration)
        diagnostics.append(MappingProxyType(row))
    if tuple(item["arm_id"] for item in diagnostics) != CONTROL_ARM_IDS:
        raise EconomicTournamentStatisticsError("statistics diagnostics are invalid")

    walk = _exact(payload["walk_forward"], {
        "method", "purge_sessions", "embargo_sessions", "folds"
    }, label="walk forward")
    if (
        walk["method"] != "purged_embargoed_market_date_folds"
        or walk["purge_sessions"] != 5 or walk["embargo_sessions"] != 5
        or type(walk["folds"]) is not list
    ):
        raise EconomicTournamentStatisticsError("statistics walk-forward is invalid")
    folds: list[Mapping[str, object]] = []
    for index, item in enumerate(walk["folds"], 1):
        row = _exact(item, {
            "fold_id", "training_dates", "purged_dates", "embargoed_dates", "test_dates"
        }, label="walk-forward fold")
        if row["fold_id"] != f"fold-{index}":
            raise EconomicTournamentStatisticsError("fold identity is invalid")
        groups = []
        for field in ("training_dates", "purged_dates", "embargoed_dates", "test_dates"):
            if type(row[field]) is not list:
                raise EconomicTournamentStatisticsError("fold dates are invalid")
            dates = tuple(_date(item, label="fold date") for item in row[field])
            if dates != tuple(sorted(dates)):
                raise EconomicTournamentStatisticsError("fold dates are unordered")
            groups.append(set(dates))
        if any(groups[left] & groups[right] for left in range(4) for right in range(left + 1, 4)):
            raise EconomicTournamentStatisticsError("fold partitions overlap")
        if set.union(*groups) - set(market_dates):
            raise EconomicTournamentStatisticsError("fold dates are outside the sample")
        folds.append(MappingProxyType(row))

    multiple = _exact(payload["multiple_testing"], {
        "method", "contrast_test", "familywise_alpha", "registered_hypothesis_count", "diagnostics"
    }, label="multiple testing")
    if (
        multiple["method"] != "holm_bonferroni_registered_contrasts"
        or multiple["contrast_test"] != "deterministic_centered_market_date_block_bootstrap_mean"
        or multiple["familywise_alpha"] != "0.05"
        or type(multiple["diagnostics"]) is not list
    ):
        raise EconomicTournamentStatisticsError("multiple-testing method is invalid")
    holm: list[Mapping[str, object]] = []
    prior_p = Decimal("-1")
    prior_adjusted = Decimal("-1")
    prior_rejected = True
    expected_adjusted = Decimal("0")
    for index, item in enumerate(multiple["diagnostics"], 1):
        row = _exact(item, {
            "contrast_id", "arm_id", "comparator", "test_statistic", "raw_p_value",
            "holm_rank", "holm_threshold", "holm_adjusted_p_value", "reject_null",
        }, label="Holm diagnostic")
        remaining = len(multiple["diagnostics"]) - index + 1
        raw_p = _decimal(row["raw_p_value"], label="raw p-value")
        adjusted = _decimal(row["holm_adjusted_p_value"], label="adjusted p-value")
        threshold = _decimal(row["holm_threshold"], label="Holm threshold")
        _decimal(row["test_statistic"], label="test statistic")
        expected_reject = prior_rejected and raw_p <= threshold
        expected_adjusted = max(
            expected_adjusted,
            min(Decimal("1"), raw_p * remaining),
        )
        if (
            type(row["contrast_id"]) is not str
            or row["contrast_id"] != f"{row['arm_id']}_minus_{row['comparator']}"
            or row["arm_id"] not in set(CONTROL_ARM_IDS) - {"cash"}
            or row["comparator"] not in {"benchmark", "cash"}
            or row["holm_rank"] != index
            or type(row["reject_null"]) is not bool
            or row["reject_null"] != expected_reject
            or threshold != _ALPHA / Decimal(remaining)
            or adjusted != expected_adjusted
            or not Decimal("0") <= raw_p <= Decimal("1")
            or not Decimal("0") <= adjusted <= Decimal("1")
            or raw_p < prior_p or adjusted < prior_adjusted
        ):
            raise EconomicTournamentStatisticsError("Holm diagnostic is invalid")
        prior_p, prior_adjusted, prior_rejected = raw_p, adjusted, expected_reject
        holm.append(MappingProxyType(row))
    if multiple["registered_hypothesis_count"] != len(holm):
        raise EconomicTournamentStatisticsError("hypothesis count is invalid")
    multiple["diagnostics"] = tuple(holm)

    rebuilt = _new_statistics(
        statistics_id=payload["statistics_id"], statistics_sha256=payload["statistics_sha256"],
        raw_source_row_count=payload["raw_source_row_count"],
        decision_event_count=payload["decision_event_count"],
        packet_event_cluster_count=payload["packet_event_cluster_count"],
        market_event_cluster_count=payload["market_event_cluster_count"],
        unique_decision_date_count=payload["unique_decision_date_count"],
        market_dates=market_dates, bootstrap_intervals=tuple(intervals),
        arm_diagnostics=tuple(diagnostics), walk_forward_folds=tuple(folds),
        multiple_testing=MappingProxyType(multiple),
    )
    canonical = rebuilt.to_dict()
    identity_material = dict(canonical)
    identity_material.pop("statistics_id")
    identity_material.pop("statistics_sha256")
    expected_id = "economic-tournament-statistics-" + _sha256(identity_material)
    digest_material = dict(canonical)
    digest_material["statistics_sha256"] = ""
    if rebuilt.statistics_id != expected_id or rebuilt.statistics_sha256 != _sha256(digest_material):
        raise EconomicTournamentStatisticsError("statistics identity or digest is invalid")
    if rebuilt.canonical_json_bytes() != _canonical_json_bytes(value):
        raise EconomicTournamentStatisticsError("statistics bytes do not match canonical rebuild")
    if "effective_sample_size" in rebuilt.canonical_json_bytes().decode("utf-8"):
        raise EconomicTournamentStatisticsError(
            "cluster counts cannot be labeled effective sample size"
        )
    return rebuilt
