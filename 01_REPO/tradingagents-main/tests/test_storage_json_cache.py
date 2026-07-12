import json
import time

from tradingagents.storage.json_cache import JsonFileCache, cache_enabled_from_env


def test_json_file_cache_reuses_unchanged_json_and_invalidates_on_rewrite(tmp_path):
    path = tmp_path / "packet.json"
    path.write_text(json.dumps({"value": 1}), encoding="utf-8")
    cache = JsonFileCache(enabled=True)

    assert cache.read_json(path) == {"value": 1}
    assert cache.read_json(path) == {"value": 1}
    assert cache.stats.json_reads == 2
    assert cache.stats.json_hits == 1
    assert cache.stats.json_misses == 1

    time.sleep(0.01)
    path.write_text(json.dumps({"value": 2}), encoding="utf-8")

    assert cache.read_json(path) == {"value": 2}
    assert cache.stats.json_misses == 2


def test_text_metric_cache_reuses_unchanged_file_and_tracks_lines(tmp_path):
    path = tmp_path / "packet.json"
    path.write_text('{"a": 1}\n{"b": 2}\n', encoding="utf-8")
    cache = JsonFileCache(enabled=True)

    first = cache.text_metric(path)
    second = cache.text_metric(path)

    assert first == second
    assert first is not None
    assert first.line_count == 3
    assert cache.stats.text_metric_reads == 2
    assert cache.stats.text_metric_hits == 1
    assert cache.stats.text_metric_misses == 1


def test_json_file_cache_can_be_disabled_by_env():
    assert cache_enabled_from_env({}) is False
    assert cache_enabled_from_env({"TRADINGAGENTS_CONTEXT_SNAPSHOT_CACHE": "0"}) is False
    assert cache_enabled_from_env({"TRADINGAGENTS_STORAGE_CACHE": "false"}) is False
    assert cache_enabled_from_env({"TRADINGAGENTS_STORAGE_CACHE": "1"}) is True
