import pytest

from tradingagents.policy import io as policy_io
from tradingagents.policy.live_control import load_live_control_state, write_live_control_state


def test_atomic_write_text_preserves_existing_file_when_replace_fails(tmp_path, monkeypatch):
    target = tmp_path / "live_control.json"
    target.write_text("original-state", encoding="utf-8")

    def fail_replace(_source, _destination):
        raise PermissionError("locked")

    monkeypatch.setattr(policy_io.os, "replace", fail_replace)
    monkeypatch.setattr(policy_io, "_ATOMIC_REPLACE_RETRY_DELAYS_SECONDS", ())

    with pytest.raises(PermissionError):
        policy_io.atomic_write_text(target, "new-state")

    assert target.read_text(encoding="utf-8") == "original-state"
    assert list(tmp_path.glob(".live_control.json.*.tmp")) == []


def test_atomic_append_line_preserves_lines_and_cleans_temp_files(tmp_path):
    target = tmp_path / "preregistrations.jsonl"

    policy_io.atomic_append_line(target, '{"id":"first"}')
    policy_io.atomic_append_line(target, '{"id":"second"}')

    assert target.read_text(encoding="utf-8").splitlines() == [
        '{"id":"first"}',
        '{"id":"second"}',
    ]
    assert list(tmp_path.glob(".preregistrations.jsonl.*.tmp")) == []


def test_atomic_write_text_fsyncs_file_and_parent_directory(tmp_path, monkeypatch):
    target = tmp_path / "promotion_state.json"
    fsync_calls: list[int] = []
    monkeypatch.setattr(policy_io.os, "fsync", fsync_calls.append)

    policy_io.atomic_write_text(target, "durable-state")

    assert target.read_text(encoding="utf-8") == "durable-state"
    assert len(fsync_calls) == 2


def test_unique_packet_path_allocates_suffix_without_creating_file(tmp_path):
    existing = tmp_path / "packet.json"
    existing.write_text("{}", encoding="utf-8")

    candidate = policy_io.unique_packet_path(tmp_path, "packet")

    assert candidate == tmp_path / "packet-001.json"
    assert not candidate.exists()


def test_unique_packet_path_supports_custom_suffix(tmp_path):
    (tmp_path / "packet.md").write_text("# existing", encoding="utf-8")

    candidate = policy_io.unique_packet_path(tmp_path, "packet", ".md")

    assert candidate == tmp_path / "packet-001.md"


def test_live_control_writer_uses_atomic_temp_cleanup(tmp_path):
    target = tmp_path / "live_control.json"

    written = write_live_control_state(
        target,
        frozen=False,
        reason="heartbeat",
    )
    state, issues = load_live_control_state(written)

    assert issues == []
    assert state is not None
    assert state["reason"] == "heartbeat"
    assert list(tmp_path.glob(".live_control.json.*.tmp")) == []
