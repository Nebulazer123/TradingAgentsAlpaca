"""Small reversible cache for local JSON/text artifacts.

This is intentionally narrower than a database migration. TradingAgents keeps
raw JSON/JSONL packets as the audit trail, while hot context builders can avoid
parsing the same unchanged files repeatedly inside one process.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

FALSE_VALUES = {"0", "false", "no", "off", "disabled"}


@dataclass(frozen=True)
class TextMetric:
    """Cheap text/file-size metrics used by compact context summaries."""

    byte_count: int
    char_count: int
    line_count: int


@dataclass
class JsonFileCacheStats:
    enabled: bool
    json_reads: int = 0
    json_hits: int = 0
    json_misses: int = 0
    json_errors: int = 0
    text_metric_reads: int = 0
    text_metric_hits: int = 0
    text_metric_misses: int = 0
    text_metric_errors: int = 0

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["json_hit_rate"] = (
            round(self.json_hits / self.json_reads, 4) if self.json_reads else None
        )
        payload["text_metric_hit_rate"] = (
            round(self.text_metric_hits / self.text_metric_reads, 4)
            if self.text_metric_reads
            else None
        )
        return payload


def cache_enabled_from_env(
    env: Mapping[str, str] | None = None,
    *,
    env_names: tuple[str, ...] = (
        "TRADINGAGENTS_CONTEXT_SNAPSHOT_CACHE",
        "TRADINGAGENTS_STORAGE_CACHE",
    ),
    default: bool = False,
) -> bool:
    """Return cache setting from env.

    The default is deliberately off because the context-snapshot benchmark found
    that stat/key overhead can be slower than reparsing small local JSON files.
    Set an env var to a truthy value for large-artifact experiments.
    """

    values = env or os.environ
    for name in env_names:
        raw = values.get(name)
        if raw is None:
            continue
        return raw.strip().lower() not in FALSE_VALUES
    return default


class JsonFileCache:
    """Cache parsed JSON and text metrics for unchanged local files."""

    def __init__(self, *, enabled: bool = True, max_entries: int = 1024) -> None:
        self.enabled = enabled
        self.max_entries = max(1, int(max_entries))
        self._json_cache: dict[tuple[str, int, int], Any] = {}
        self._text_metric_cache: dict[tuple[str, int, int], TextMetric] = {}
        self.stats = JsonFileCacheStats(enabled=enabled)

    @classmethod
    def from_env(
        cls,
        *,
        env: Mapping[str, str] | None = None,
        env_names: tuple[str, ...] = (
            "TRADINGAGENTS_CONTEXT_SNAPSHOT_CACHE",
            "TRADINGAGENTS_STORAGE_CACHE",
        ),
        max_entries: int = 1024,
        default: bool = False,
    ) -> JsonFileCache:
        return cls(
            enabled=cache_enabled_from_env(env, env_names=env_names, default=default),
            max_entries=max_entries,
        )

    def clear(self) -> None:
        self._json_cache.clear()
        self._text_metric_cache.clear()
        self.stats = JsonFileCacheStats(enabled=self.enabled)

    def stats_dict(self) -> dict[str, Any]:
        return self.stats.as_dict()

    def _key(self, path: Path) -> tuple[str, int, int] | None:
        try:
            stat = path.stat()
        except OSError:
            return None
        absolute = str(path.resolve(strict=False))
        return absolute, int(stat.st_mtime_ns), int(stat.st_size)

    def _trim_if_needed(self, cache: dict[tuple[str, int, int], Any]) -> None:
        if len(cache) > self.max_entries:
            cache.clear()

    def read_json(self, path: Path) -> Any | None:
        self.stats.json_reads += 1
        if not self.enabled:
            return self._read_json_uncached(path)
        key = self._key(path)
        if key is None:
            self.stats.json_errors += 1
            return None
        if key in self._json_cache:
            self.stats.json_hits += 1
            return self._json_cache[key]
        self.stats.json_misses += 1
        value = self._read_json_uncached(path)
        if value is not None:
            self._json_cache[key] = value
            self._trim_if_needed(self._json_cache)
        return value

    def _read_json_uncached(self, path: Path) -> Any | None:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            self.stats.json_errors += 1
            return None

    def text_metric(self, path: Path) -> TextMetric | None:
        self.stats.text_metric_reads += 1
        if not self.enabled:
            return self._text_metric_uncached(path)
        key = self._key(path)
        if key is None:
            self.stats.text_metric_errors += 1
            return None
        if key in self._text_metric_cache:
            self.stats.text_metric_hits += 1
            return self._text_metric_cache[key]
        self.stats.text_metric_misses += 1
        metric = self._text_metric_uncached(path)
        if metric is not None:
            self._text_metric_cache[key] = metric
            self._trim_if_needed(self._text_metric_cache)
        return metric

    def _text_metric_uncached(self, path: Path) -> TextMetric | None:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
            byte_count = path.stat().st_size
        except OSError:
            self.stats.text_metric_errors += 1
            return None
        return TextMetric(
            byte_count=byte_count,
            char_count=len(text),
            line_count=text.count("\n") + (1 if text else 0),
        )
