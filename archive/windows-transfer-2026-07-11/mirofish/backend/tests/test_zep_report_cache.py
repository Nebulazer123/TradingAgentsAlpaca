from app.services.zep_report_cache import (
    MirrorFishQueryPack,
    ReportLock,
    ZepCacheConfig,
    ZepReportCache,
    parse_rate_limit_reset_epoch,
    parse_retry_after_seconds,
)


def test_cache_key_is_deterministic(tmp_path):
    cache = ZepReportCache(ZepCacheConfig(cache_root=tmp_path, graph_id="g1"))
    a = cache.cache_key(tool_name="quick_search", query="Macro rates", limit=10, scope="edges")
    b = cache.cache_key(tool_name="quick_search", query="  Macro   rates  ", limit=10, scope="edges")
    assert a == b


def test_cache_key_caps_query_limit(tmp_path):
    cache = ZepReportCache(ZepCacheConfig(cache_root=tmp_path, graph_id="g1", max_query_limit=15))
    capped = cache.cache_key(tool_name="quick_search", query="Macro rates", limit=15, scope="edges")
    oversized = cache.cache_key(tool_name="quick_search", query="Macro rates", limit=100, scope="edges")
    assert capped == oversized


def test_retry_after_parser_reads_header_text():
    text = "headers: {'retry-after': '46'}, status_code: 429"
    assert parse_retry_after_seconds(text) == 46


def test_rate_limit_reset_parser_reads_epoch():
    text = "headers: {'x-ratelimit-reset': '1780509000'}"
    assert parse_rate_limit_reset_epoch(text) == 1780509000


def test_query_pack_has_required_twenty_sections():
    pack = MirrorFishQueryPack.default()
    assert len(pack.required_sections) == 20
    assert pack.required_sections[0] == "Executive summary"
    assert "Machine-readable summary if practical" in pack.required_sections
    assert all(len(q) <= 260 for q in pack.all_queries())


def test_report_lock_blocks_duplicate_owner(tmp_path):
    lock_path = tmp_path / "sim.lock"
    first = ReportLock.acquire(lock_path, owner="report_a")
    assert first.acquired
    second = ReportLock.acquire(lock_path, owner="report_b")
    assert not second.acquired
    assert second.current_owner["owner"] == "report_a"
    first.release()
