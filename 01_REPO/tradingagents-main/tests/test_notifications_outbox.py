import json

from tradingagents.notifications.outbox import (
    list_undelivered,
    mark_delivered,
    write_outbox_message,
)


def test_outbox_roundtrip(tmp_path):
    outbox = tmp_path / "outbox"
    path = write_outbox_message(
        {"subject": "Test subject", "body": "Body", "email_to": "owner@example.com"},
        outbox,
        report_type="daily",
        severity="ROUTINE",
    )
    assert path.exists()
    assert (outbox / "latest.json").exists()

    pending = list_undelivered(outbox)
    assert len(pending) == 1
    message = pending[0]
    assert message["subject"] == "Test subject"
    assert message["delivered"] is False
    assert message["report_type"] == "daily"

    assert mark_delivered(message["id"], outbox) is True
    assert list_undelivered(outbox) == []
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored["delivered"] is True
    assert stored["delivered_at"]


def test_outbox_uses_environment_override_when_directory_omitted(
    monkeypatch, tmp_path
):
    isolated_outbox = tmp_path / "isolated-outbox"
    monkeypatch.setenv("TRADINGAGENTS_OUTBOX_DIR", str(isolated_outbox))

    path = write_outbox_message({"subject": "Test", "body": "Body"})

    assert path.parent == isolated_outbox
    assert path.exists()


def test_mark_delivered_missing_id(tmp_path):
    assert mark_delivered("nope", tmp_path) is False


def test_list_undelivered_empty_dir(tmp_path):
    assert list_undelivered(tmp_path / "missing") == []
