"""Deterministic dependence-aware statistics for weekly TA-Control results."""

from __future__ import annotations

import dataclasses
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


_SCHEMA = "economic_tournament_statistics/v1"
_AUTHORITY = {
    "analysis_only": True,
    "execution_authority": "none",
    "can_submit_orders": False,
}


class EconomicTournamentStatisticsError(ValueError):
    """Registered weekly statistics are not canonical or dependence-aware."""


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
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
    if not parsed.is_finite() or value != canonical:
        raise EconomicTournamentStatisticsError(f"{label} must be a canonical decimal")
    return parsed


def _text(value: Decimal) -> str:
    return "0" if value.is_zero() else format(value.normalize(), "f")


@dataclasses.dataclass(frozen=True, slots=True)
class WeeklyArmObservation:
    """One weekly portfolio observation, the primary inference unit."""

    market_date: str
    gross_return: str
    net_return: str
    benchmark_net_return: str
    turnover: str
    cost_drag: str
    false_positive: bool
    positions: tuple[tuple[str, str], ...]
    factor_exposures: tuple[tuple[str, str], ...] = ()
    sector_exposures: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        if type(self.market_date) is not str or len(self.market_date) != 10:
            raise EconomicTournamentStatisticsError("market_date must be an ISO date")
        for label in (
            "gross_return",
            "net_return",
            "benchmark_net_return",
            "turnover",
            "cost_drag",
        ):
            _decimal(getattr(self, label), label=label)
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
                "replicates": 256,
                "interval_level": "0.95",
                "intervals": [dict(item) for item in self.bootstrap_intervals],
            },
            "arm_diagnostics": [
                {
                    **dict(item),
                    "factor_exposures": [dict(row) for row in item["factor_exposures"]],
                    "sector_exposures": [dict(row) for row in item["sector_exposures"]],
                }
                for item in self.arm_diagnostics
            ],
            "walk_forward": {
                "method": "purged_embargoed_market_date_folds",
                "purge_sessions": 5,
                "embargo_sessions": 5,
                "folds": [dict(item) for item in self.walk_forward_folds],
            },
            "multiple_testing": dict(self.multiple_testing),
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


def _block_bootstrap(
    *, arm_id: str, market_dates: tuple[str, ...], returns: tuple[Decimal, ...]
) -> tuple[str, str, str]:
    point = _compound(returns)
    if len(returns) < 2:
        text = _text(point)
        return text, text, text
    block = min(4, len(returns))
    seed = int(
        hashlib.sha256(
            _canonical_json_bytes([arm_id, list(market_dates)])
        ).hexdigest()[:16],
        16,
    )
    samples: list[Decimal] = []
    for _replicate in range(256):
        selected: list[Decimal] = []
        while len(selected) < len(returns):
            seed = (6364136223846793005 * seed + 1442695040888963407) % (2**64)
            start = seed % len(returns)
            selected.extend(
                returns[(start + offset) % len(returns)] for offset in range(block)
            )
        samples.append(_compound(tuple(selected[: len(returns)])))
    samples.sort()
    return _text(samples[6]), _text(point), _text(samples[249])


def _concentration(values: tuple[Decimal, ...]) -> Decimal:
    absolute = tuple(abs(item) for item in values)
    total = sum(absolute, Decimal("0"))
    return Decimal("0") if total == 0 else max(absolute) / total


def _walk_forward_folds(market_dates: tuple[str, ...]) -> tuple[Mapping[str, object], ...]:
    if len(market_dates) < 6:
        return ()
    folds: list[Mapping[str, object]] = []
    for index, split in enumerate((len(market_dates) // 2, (len(market_dates) * 3) // 4), 1):
        train = market_dates[: max(1, split - 1)]
        purge = market_dates[max(1, split - 1) : split]
        embargo = market_dates[split : split + 1]
        test = market_dates[split + 1 :]
        if not test:
            continue
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
        raw_source_row_count,
        decision_event_count,
        packet_event_cluster_count,
        market_event_cluster_count,
    )
    if any(type(item) is not int or item < 0 for item in counts):
        raise EconomicTournamentStatisticsError("registered counts must be nonnegative integers")
    if not isinstance(observations_by_arm, Mapping) or set(observations_by_arm) != set(
        CONTROL_ARM_IDS
    ):
        raise EconomicTournamentStatisticsError("statistics require the exact five arms")
    observations = {
        arm: observations_by_arm[arm] for arm in CONTROL_ARM_IDS
    }
    market_dates = tuple(item.market_date for item in observations["cash"])
    if not market_dates or market_dates != tuple(sorted(market_dates)):
        raise EconomicTournamentStatisticsError("weekly market dates must be canonical")
    for arm, rows in observations.items():
        if type(rows) is not tuple or tuple(item.market_date for item in rows) != market_dates:
            raise EconomicTournamentStatisticsError(
                f"{arm} observations must cover the exact weekly market dates"
            )

    intervals: list[Mapping[str, object]] = []
    diagnostics: list[Mapping[str, object]] = []
    means: list[tuple[str, Decimal]] = []
    for arm in CONTROL_ARM_IDS:
        rows = observations[arm]
        returns = tuple(_decimal(item.net_return, label="net_return") for item in rows)
        lower, point, upper = _block_bootstrap(
            arm_id=arm,
            market_dates=market_dates,
            returns=returns,
        )
        intervals.append(
            MappingProxyType(
                {"arm_id": arm, "lower": lower, "point": point, "upper": upper}
            )
        )
        turnovers = tuple(_decimal(item.turnover, label="turnover") for item in rows)
        cost_drag = sum(
            (_decimal(item.cost_drag, label="cost_drag") for item in rows),
            Decimal("0"),
        )
        capital = Decimal("1")
        peak = capital
        drawdown = Decimal("0")
        for returned in returns:
            capital *= Decimal("1") + returned
            peak = max(peak, capital)
            drawdown = min(drawdown, capital / peak - Decimal("1"))
        position_weights = tuple(
            _decimal(weight, label="position weight")
            for row in rows
            for symbol, weight in row.positions
            if symbol != "CASH"
        )
        year_returns: dict[str, Decimal] = {}
        for row in rows:
            year = row.market_date[:4]
            year_returns[year] = year_returns.get(year, Decimal("0")) + _decimal(
                row.net_return, label="net_return"
            )
        factor_rows = rows[-1].factor_exposures
        sector_rows = rows[-1].sector_exposures
        diagnostics.append(
            MappingProxyType(
                {
                    "arm_id": arm,
                    "turnover": _text(sum(turnovers, Decimal("0"))),
                    "max_drawdown": _text(drawdown),
                    "false_positive_rate": _text(
                        Decimal(sum(1 for row in rows if row.false_positive))
                        / Decimal(len(rows))
                    ),
                    "cost_drag": _text(cost_drag),
                    "factor_exposure_status": "available" if factor_rows else "unavailable",
                    "factor_exposures": tuple(
                        MappingProxyType({"factor": name, "exposure": value})
                        for name, value in factor_rows
                    ),
                    "sector_exposure_status": "available" if sector_rows else "unavailable",
                    "sector_exposures": tuple(
                        MappingProxyType({"sector": name, "weight": value})
                        for name, value in sector_rows
                    ),
                    "year_concentration": _text(
                        _concentration(tuple(year_returns.values()))
                    ),
                    "event_concentration": _text(_concentration(returns)),
                    "position_concentration": _text(
                        _concentration(position_weights)
                    ),
                }
            )
        )
        means.append((arm, sum(returns, Decimal("0")) / Decimal(len(returns))))

    tested = tuple(item for item in means if item[0] != "cash")
    ranked = sorted(tested, key=lambda item: (-abs(item[1]), item[0]))
    multiple_testing = MappingProxyType(
        {
            "method": "holm_bonferroni_registered_contrasts",
            "familywise_alpha": "0.05",
            "registered_hypothesis_count": len(ranked),
            "diagnostics": [
                {
                    "arm_id": arm,
                    "observed_mean_weekly_return": _text(mean),
                    "holm_threshold": _text(
                        Decimal("0.05") / Decimal(len(ranked) - index)
                    ),
                    "significance_claim": False,
                }
                for index, (arm, mean) in enumerate(ranked)
            ],
        }
    )
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
    material = {
        "schema_version": _SCHEMA,
        **fields,
    }
    material["bootstrap_intervals"] = [dict(item) for item in intervals]
    material["arm_diagnostics"] = [
        {
            **dict(item),
            "factor_exposures": [dict(row) for row in item["factor_exposures"]],
            "sector_exposures": [dict(row) for row in item["sector_exposures"]],
        }
        for item in diagnostics
    ]
    material["walk_forward_folds"] = [dict(item) for item in fields["walk_forward_folds"]]
    material["multiple_testing"] = dict(multiple_testing)
    statistics_id = "economic-tournament-statistics-" + _sha256(material)
    value = _new_statistics(
        statistics_id=statistics_id,
        statistics_sha256="",
        **fields,
    )
    canonical_without_digest = value.to_dict()
    canonical_without_digest["statistics_sha256"] = ""
    object.__setattr__(
        value,
        "statistics_sha256",
        _sha256(canonical_without_digest),
    )
    return value


def validate_economic_tournament_statistics(
    value: object,
) -> EconomicTournamentStatistics:
    """Validate statistics by canonical rebuilding from weekly observations is separate.

    The result validator uses the full canonical bytes and identity here; the
    builder remains the only path that computes intervals and diagnostics.
    """

    if not isinstance(value, Mapping):
        raise EconomicTournamentStatisticsError("statistics must be a JSON object")
    expected = {
        "schema_version",
        "statistics_id",
        "statistics_sha256",
        "primary_unit",
        "raw_source_row_count",
        "decision_event_count",
        "packet_event_cluster_count",
        "market_event_cluster_count",
        "unique_decision_date_count",
        "market_dates",
        "bootstrap",
        "arm_diagnostics",
        "walk_forward",
        "multiple_testing",
        "status",
        *_AUTHORITY,
    }
    if set(value) != expected:
        raise EconomicTournamentStatisticsError("statistics fields are invalid")
    if (
        value["schema_version"] != _SCHEMA
        or value["primary_unit"] != "weekly_market_date"
        or value["status"] != "completed"
        or any(value[key] != expected_value for key, expected_value in _AUTHORITY.items())
    ):
        raise EconomicTournamentStatisticsError("statistics schema or authority is invalid")
    submitted = dict(value)
    digest = submitted["statistics_sha256"]
    submitted["statistics_sha256"] = ""
    if type(digest) is not str or digest != _sha256(submitted):
        raise EconomicTournamentStatisticsError("statistics digest is invalid")
    if (
        type(value["statistics_id"]) is not str
        or not value["statistics_id"].startswith("economic-tournament-statistics-")
    ):
        raise EconomicTournamentStatisticsError("statistics identity is invalid")
    if "effective_sample_size" in _canonical_json_bytes(value).decode("utf-8"):
        raise EconomicTournamentStatisticsError(
            "cluster counts cannot be labeled effective sample size"
        )
    count_fields = (
        "raw_source_row_count",
        "decision_event_count",
        "packet_event_cluster_count",
        "market_event_cluster_count",
        "unique_decision_date_count",
    )
    if any(type(value[field]) is not int or value[field] < 0 for field in count_fields):
        raise EconomicTournamentStatisticsError("statistics counts are invalid")
    market_dates = value["market_dates"]
    if (
        type(market_dates) is not list
        or tuple(market_dates) != tuple(sorted(market_dates))
        or len(set(market_dates)) != len(market_dates)
        or value["unique_decision_date_count"] != len(market_dates)
    ):
        raise EconomicTournamentStatisticsError("statistics market dates are invalid")
    bootstrap = value["bootstrap"]
    if (
        not isinstance(bootstrap, Mapping)
        or set(bootstrap)
        != {"method", "block_length_dates", "replicates", "interval_level", "intervals"}
        or bootstrap["method"] != "deterministic_market_date_block_bootstrap"
        or bootstrap["replicates"] != 256
        or bootstrap["interval_level"] != "0.95"
        or type(bootstrap["intervals"]) is not list
    ):
        raise EconomicTournamentStatisticsError("statistics bootstrap is invalid")
    intervals = tuple(MappingProxyType(dict(item)) for item in bootstrap["intervals"])
    if tuple(item.get("arm_id") for item in intervals) != CONTROL_ARM_IDS:
        raise EconomicTournamentStatisticsError("statistics intervals are invalid")
    raw_diagnostics = value["arm_diagnostics"]
    if type(raw_diagnostics) is not list:
        raise EconomicTournamentStatisticsError("statistics diagnostics are invalid")
    diagnostics: list[Mapping[str, object]] = []
    for item in raw_diagnostics:
        if not isinstance(item, Mapping):
            raise EconomicTournamentStatisticsError("statistics diagnostic is invalid")
        row = dict(item)
        if type(row.get("factor_exposures")) is not list or type(
            row.get("sector_exposures")
        ) is not list:
            raise EconomicTournamentStatisticsError("statistics exposures are invalid")
        row["factor_exposures"] = tuple(
            MappingProxyType(dict(exposure)) for exposure in row["factor_exposures"]
        )
        row["sector_exposures"] = tuple(
            MappingProxyType(dict(exposure)) for exposure in row["sector_exposures"]
        )
        diagnostics.append(MappingProxyType(row))
    if tuple(item.get("arm_id") for item in diagnostics) != CONTROL_ARM_IDS:
        raise EconomicTournamentStatisticsError("statistics diagnostics are invalid")
    walk_forward = value["walk_forward"]
    if (
        not isinstance(walk_forward, Mapping)
        or set(walk_forward) != {"method", "purge_sessions", "embargo_sessions", "folds"}
        or walk_forward["method"] != "purged_embargoed_market_date_folds"
        or walk_forward["purge_sessions"] != 5
        or walk_forward["embargo_sessions"] != 5
        or type(walk_forward["folds"]) is not list
    ):
        raise EconomicTournamentStatisticsError("statistics walk-forward folds are invalid")
    rebuilt = _new_statistics(
        statistics_id=value["statistics_id"],
        statistics_sha256=digest,
        raw_source_row_count=value["raw_source_row_count"],
        decision_event_count=value["decision_event_count"],
        packet_event_cluster_count=value["packet_event_cluster_count"],
        market_event_cluster_count=value["market_event_cluster_count"],
        unique_decision_date_count=value["unique_decision_date_count"],
        market_dates=tuple(market_dates),
        bootstrap_intervals=intervals,
        arm_diagnostics=tuple(diagnostics),
        walk_forward_folds=tuple(
            MappingProxyType(dict(item)) for item in walk_forward["folds"]
        ),
        multiple_testing=MappingProxyType(dict(value["multiple_testing"])),
    )
    if rebuilt.canonical_json_bytes() != _canonical_json_bytes(value):
        raise EconomicTournamentStatisticsError(
            "statistics bytes do not match canonical rebuild"
        )
    return rebuilt
