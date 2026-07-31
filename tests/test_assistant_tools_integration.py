from __future__ import annotations

import os

import pytest

from market_intelligence.assistant.tools import MarketDataTools
from market_intelligence.database import create_database_engine

INTEGRATION_DATABASE_URL = os.getenv("INTEGRATION_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not INTEGRATION_DATABASE_URL,
    reason="INTEGRATION_DATABASE_URL is not configured",
)


@pytest.fixture
def tools() -> MarketDataTools:
    return MarketDataTools(create_database_engine(INTEGRATION_DATABASE_URL))


def test_snapshot_resolves_non_trading_date(tools: MarketDataTools) -> None:
    snapshot = tools.get_market_snapshot("2026-06-28")

    assert snapshot["effective_trading_date"] <= "2026-06-28"
    assert snapshot["asx_200_close"] > 0
    assert snapshot["signal_status"] in {"green", "amber", "red", "insufficient_data"}


def test_history_and_extremes_are_bounded(tools: MarketDataTools) -> None:
    history = tools.get_metric_history(
        "realized_volatility_14d_percent",
        "2026-01-01",
        "2026-06-30",
    )
    extremes = tools.get_extreme_observations(
        "return_20d_percent",
        "lowest",
        3,
        "2022-01-01",
        "2026-06-30",
    )

    assert 0 < history["observation_count"] <= 270
    assert len(extremes["observations"]) == 3
    assert extremes["observations"][0]["value"] <= extremes["observations"][1]["value"]


def test_compare_periods_and_freshness(tools: MarketDataTools) -> None:
    comparison = tools.compare_periods(
        "2025-01-01",
        "2025-03-31",
        "2026-01-01",
        "2026-03-31",
    )
    freshness = tools.get_data_freshness()

    assert comparison["period_one"]["observation_count"] > 0
    assert comparison["period_two"]["observation_count"] > 0
    assert freshness["latest_pipeline_status"] == "succeeded"
