import datetime

from tradingagents.policy.order_rate_limit import (
    count_live_submissions_in_window,
    evaluate_order_rate_limit,
    record_live_order_submission,
)

UTC = datetime.timezone.utc
NOW = datetime.datetime(2026, 6, 4, 15, 0, tzinfo=UTC)


def test_missing_ledger_counts_zero(tmp_path):
    path = tmp_path / "rate.json"
    assert count_live_submissions_in_window(path, now=NOW, window_minutes=60) == 0


def test_records_and_counts_within_window(tmp_path):
    path = tmp_path / "rate.json"
    record_live_order_submission(path, client_order_id="ta-a", now=NOW)
    record_live_order_submission(
        path, client_order_id="ta-b", now=NOW - datetime.timedelta(minutes=30)
    )

    assert count_live_submissions_in_window(path, now=NOW, window_minutes=60) == 2


def test_recording_the_same_client_order_id_is_idempotent(tmp_path):
    """Break caught: a GET-only retry could consume the live-order budget twice."""
    path = tmp_path / "rate.json"
    record_live_order_submission(path, client_order_id="ta-once", now=NOW)
    record_live_order_submission(
        path,
        client_order_id="ta-once",
        now=NOW + datetime.timedelta(seconds=30),
    )

    assert count_live_submissions_in_window(path, now=NOW, window_minutes=60) == 1


def test_counts_exclude_submissions_outside_window(tmp_path):
    path = tmp_path / "rate.json"
    record_live_order_submission(
        path, client_order_id="old", now=NOW - datetime.timedelta(hours=2)
    )
    record_live_order_submission(
        path, client_order_id="recent", now=NOW - datetime.timedelta(minutes=10)
    )

    assert count_live_submissions_in_window(path, now=NOW, window_minutes=60) == 1


def test_evaluate_blocks_when_window_would_exceed_max(tmp_path):
    path = tmp_path / "rate.json"
    record_live_order_submission(path, client_order_id="ta-a", now=NOW)
    record_live_order_submission(path, client_order_id="ta-b", now=NOW)

    issues = evaluate_order_rate_limit(
        path=path,
        now=NOW,
        window_minutes=60,
        max_orders=2,
        new_order_count=1,
    )

    assert len(issues) == 1
    assert "max_live_orders_per_window" in issues[0]


def test_evaluate_allows_when_under_max(tmp_path):
    path = tmp_path / "rate.json"
    record_live_order_submission(path, client_order_id="ta-a", now=NOW)

    issues = evaluate_order_rate_limit(
        path=path,
        now=NOW,
        window_minutes=60,
        max_orders=5,
        new_order_count=1,
    )

    assert issues == []


def test_reservation_does_not_truncate_more_than_five_hundred_active_orders(tmp_path):
    """Break caught: a 500-record tail silently reopened rate capacity."""
    path = tmp_path / "rate.json"
    for index in range(501):
        record_live_order_submission(
            path, client_order_id=f"active-{index}", now=NOW
        )

    issues = evaluate_order_rate_limit(
        path=path,
        now=NOW,
        window_minutes=60,
        max_orders=501,
        new_order_count=1,
    )

    assert len(issues) == 1
    assert "501 live order(s)" in issues[0]


def test_confirmed_submission_replaces_reservation_time_with_broker_acceptance_time(
    tmp_path,
):
    """Break caught: slow broker I/O shortened the real rolling window."""
    from tradingagents.policy.order_rate_limit import reserve_live_order_submission

    path = tmp_path / "rate.json"
    reserved_at = NOW
    accepted_at = NOW + datetime.timedelta(minutes=5)
    reserve_live_order_submission(
        path,
        client_order_id="slow-live-order",
        now=reserved_at,
        window_minutes=60,
        max_orders=2,
    )
    record_live_order_submission(
        path, client_order_id="slow-live-order", now=accepted_at
    )

    assert count_live_submissions_in_window(
        path,
        now=accepted_at + datetime.timedelta(minutes=56),
        window_minutes=60,
    ) == 1
