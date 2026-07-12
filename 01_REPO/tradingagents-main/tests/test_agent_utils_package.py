from tradingagents.agents.utils import RATINGS_5_TIER, parse_rating


def test_agent_utils_package_reexports_rating_helpers():
    assert "Buy" in RATINGS_5_TIER
    assert parse_rating("Rating: Buy") == "Buy"
