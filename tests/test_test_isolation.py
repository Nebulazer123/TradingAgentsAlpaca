import os
import socket

import pytest


def test_autouse_api_key_placeholders_do_not_copy_host_secrets():
    assert os.environ["OPENAI_API_KEY"] == "placeholder"
    assert os.environ["ALPACA_LIVE_API_KEY"] == "placeholder"
    assert os.environ["ALPACA_LIVE_SECRET_KEY"] == "placeholder"
    assert os.environ["FINNHUB_API_KEY"] == "placeholder"


def test_external_socket_connections_are_blocked_by_default():
    with socket.socket() as sock, pytest.raises(RuntimeError, match="External network access is blocked"):
        sock.connect(("93.184.216.34", 80))


def test_localhost_socket_connections_are_not_blocked_by_guard():
    with socket.socket() as sock, pytest.raises(OSError) as excinfo:
        sock.connect(("127.0.0.1", 9))

    assert not isinstance(excinfo.value, RuntimeError)
