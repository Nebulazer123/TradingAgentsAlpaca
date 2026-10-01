"""Transport boundary checks use a fake SMTP client and isolated queue."""
import importlib.util
import json
from pathlib import Path

import pytest

from tradingagents.notifications.outbox import list_undelivered, write_outbox_message


def _transport(monkeypatch, tmp_path):
    path = Path(__file__).resolve().parents[1] / "scripts/mac/deliver_outbox.py"
    spec = importlib.util.spec_from_file_location("deliver_outbox", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)
    for key, value in {"SMTP_HOST": "example.invalid", "SMTP_PORT": "587", "SMTP_USERNAME": "owner@example.invalid",
                       "SMTP_PASSWORD": "test-password", "SMTP_TO": "owner@example.invalid"}.items():
        monkeypatch.setenv(key, value)
    return module


def _queue(tmp_path, subject="test"):
    return write_outbox_message({"subject": subject, "body": "local fixture"}, tmp_path / "results/outbox")


def test_configured_credentials_and_trading_flags_cannot_send(monkeypatch, tmp_path):
    module = _transport(monkeypatch, tmp_path)
    _queue(tmp_path)
    monkeypatch.setenv("TA_LIVE_SUBMIT", "1")
    def forbidden(*args, **kwargs):
        raise AssertionError("preview must not open SMTP")
    monkeypatch.setattr(module.smtplib, "SMTP", forbidden)
    assert module.main([]) == 0
    assert len(list_undelivered(tmp_path / "results/outbox")) == 1


@pytest.mark.parametrize("args", [["--send"], ["--message-id", "unknown"], ["--send", "--message-id", "unknown"]])
def test_partial_or_wrong_delivery_scope_fails_before_transport(monkeypatch, tmp_path, args):
    module = _transport(monkeypatch, tmp_path)
    _queue(tmp_path)
    def forbidden(*args, **kwargs):
        raise AssertionError("invalid delivery scope must not open SMTP")
    monkeypatch.setattr(module.smtplib, "SMTP", forbidden)
    with pytest.raises(SystemExit) as error:
        module.main(args)
    assert error.value.code == 2
    assert len(list_undelivered(tmp_path / "results/outbox")) == 1


def test_explicit_send_delivers_only_the_selected_message(monkeypatch, tmp_path):
    module = _transport(monkeypatch, tmp_path)
    _queue(tmp_path, "selected")
    _queue(tmp_path, "unselected")
    pending = list_undelivered(tmp_path / "results/outbox")
    selected = next(item for item in pending if item["subject"] == "selected")
    sent = []
    class FakeSMTP:
        def __init__(self, *args, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def starttls(self): pass
        def login(self, *args): pass
        def send_message(self, message): sent.append(message["Subject"])
    monkeypatch.setattr(module.smtplib, "SMTP", FakeSMTP)
    assert module.main(["--send", "--message-id", selected["id"]]) == 0
    assert sent == ["selected"]
    assert [item["subject"] for item in list_undelivered(tmp_path / "results/outbox")] == ["unselected"]


def test_duplicate_queue_identity_is_rejected_before_smtp(monkeypatch, tmp_path):
    module = _transport(monkeypatch, tmp_path)
    path = _queue(tmp_path)
    message = json.loads(path.read_text())
    path.with_name("outbox-duplicate.json").write_text(path.read_text())
    def forbidden(*args, **kwargs):
        raise AssertionError("ambiguous scope must not open SMTP")
    monkeypatch.setattr(module.smtplib, "SMTP", forbidden)
    with pytest.raises(SystemExit):
        module.main(["--send", "--message-id", message["id"]])


def test_failed_delivery_leaves_selected_message_queued(monkeypatch, tmp_path):
    module = _transport(monkeypatch, tmp_path)
    path = _queue(tmp_path)
    message_id = json.loads(path.read_text())["id"]
    def failed_connection(*args, **kwargs):
        raise OSError("simulated SMTP failure")
    monkeypatch.setattr(module.smtplib, "SMTP", failed_connection)
    with pytest.raises(OSError, match="simulated SMTP failure"):
        module.main(["--send", "--message-id", message_id])
    assert [item["id"] for item in list_undelivered(tmp_path / "results/outbox")] == [message_id]
