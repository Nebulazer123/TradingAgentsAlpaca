import pytest

from tradingagents.research.release_calendar import load_release_calendar_config


def test_release_calendar_config_rejects_non_object_root(tmp_path):
    config_path = tmp_path / "release-calendar.json"
    config_path.write_text("[]", encoding="utf-8")

    with pytest.raises(ValueError, match="must contain a JSON object"):
        load_release_calendar_config(config_path)
