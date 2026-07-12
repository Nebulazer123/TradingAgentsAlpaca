from app.utils.zep_paging import _fetch_page_with_retry


def test_fetch_page_retries_zep_rate_limit_with_retry_after(monkeypatch):
    calls = {"count": 0}
    sleeps = []

    def fake_sleep(seconds):
        sleeps.append(seconds)

    def flaky_page():
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("headers: {'retry-after': '6'}, status_code: 429, body: Rate limit exceeded")
        return ["node"]

    monkeypatch.setattr("app.utils.zep_paging.time.sleep", fake_sleep)

    result = _fetch_page_with_retry(flaky_page, page_description="test page")

    assert result == ["node"]
    assert calls["count"] == 2
    assert sleeps == [6.0]


def test_fetch_page_does_not_retry_non_transient_error(monkeypatch):
    sleeps = []

    def fake_sleep(seconds):
        sleeps.append(seconds)

    def broken_page():
        raise ValueError("bad caller input")

    monkeypatch.setattr("app.utils.zep_paging.time.sleep", fake_sleep)

    try:
        _fetch_page_with_retry(broken_page, page_description="test page")
    except ValueError as exc:
        assert "bad caller input" in str(exc)
    else:
        raise AssertionError("expected ValueError")

    assert sleeps == []
