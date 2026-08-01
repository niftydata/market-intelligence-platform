from __future__ import annotations

import os
from itertools import combinations

import pytest

from market_intelligence.assistant.tools import METRICS, MarketDataTools
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


def test_market_volatility_relationship_is_deterministic(
    tools: MarketDataTools,
) -> None:
    relationship = tools.analyse_market_volatility_relationship(
        "2025-03-14",
        "2026-03-13",
    )

    assert relationship["effective_start_date"] == "2025-03-14"
    assert relationship["effective_end_date"] == "2026-03-13"
    assert relationship["start_close"] == pytest.approx(7_789.7, abs=0.1)
    assert relationship["end_close"] == pytest.approx(8_617.1, abs=0.1)
    assert relationship["market_direction"] == "rose"
    assert relationship["change_points"] == pytest.approx(827.4, abs=0.1)
    assert relationship["change_percent"] == pytest.approx(10.6217, abs=0.001)
    correlations = relationship["correlations"]
    assert correlations["close_level_vs_volatility"]["coefficient"] == pytest.approx(
        -0.4625,
        abs=0.001,
    )
    assert correlations["return_20d_vs_volatility"]["coefficient"] == pytest.approx(
        -0.3178,
        abs=0.001,
    )
    assert correlations["daily_return_vs_volatility"]["coefficient"] == pytest.approx(
        0.1095,
        abs=0.001,
    )


def test_rba_cash_rate_and_return_correlation_is_deterministic(
    tools: MarketDataTools,
) -> None:
    analysis = tools.analyse_metric_correlation(
        "rba_cash_rate_percent",
        "return_20d_percent",
        "2025-03-14",
        "2026-03-13",
    )

    assert analysis["effective_start_date"] == "2025-03-14"
    assert analysis["effective_end_date"] == "2026-03-13"
    assert analysis["paired_observation_count"] == 253
    assert analysis["metric_one"]["direction"] == "decreased"
    assert analysis["metric_one"]["change"] == pytest.approx(-0.24)
    assert analysis["metric_one"]["distinct_value_count"] == 5
    assert analysis["correlation"]["coefficient"] == pytest.approx(0.0466)
    assert analysis["correlation"]["direction"] == "positive"
    assert analysis["correlation"]["strength"] == "negligible"
    assert any("forward-filled step series" in note for note in analysis["methodology_notes"])


def test_every_allowlisted_metric_pair_can_be_analysed(
    tools: MarketDataTools,
) -> None:
    for metric_one, metric_two in combinations(METRICS, 2):
        analysis = tools.analyse_metric_correlation(
            metric_one,
            metric_two,
            "2025-03-14",
            "2026-03-13",
        )

        assert analysis["paired_observation_count"] > 0
        assert analysis["correlation"]["coefficient"] is not None
