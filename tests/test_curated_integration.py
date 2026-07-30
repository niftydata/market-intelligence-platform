from __future__ import annotations

import math
import os
import statistics

import pytest
from sqlalchemy import create_engine, text

INTEGRATION_DATABASE_URL = os.getenv("INTEGRATION_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not INTEGRATION_DATABASE_URL,
    reason="INTEGRATION_DATABASE_URL is not configured",
)


def test_latest_curated_metrics_match_independent_calculation() -> None:
    engine = create_engine(INTEGRATION_DATABASE_URL, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            closes_descending = [
                float(row.close_value)
                for row in connection.execute(
                    text(
                        """
                        SELECT close_value
                        FROM raw.market_index_daily
                        WHERE instrument_code = 'ASX200'
                        ORDER BY trading_date DESC
                        LIMIT 21
                        """
                    )
                )
            ]
            latest = connection.execute(
                text(
                    """
                    SELECT
                        rolling_average_20d,
                        return_20d_percent,
                        realized_volatility_14d_percent,
                        rba_observation_date,
                        trading_date
                    FROM curated.market_intelligence_daily
                    ORDER BY trading_date DESC
                    LIMIT 1
                    """
                )
            ).one()
    finally:
        engine.dispose()

    closes = list(reversed(closes_descending))
    expected_rolling_average = sum(closes[-20:]) / 20
    expected_return = ((closes[-1] / closes[-21]) - 1) * 100
    latest_14_log_returns = [
        math.log(current / previous)
        for previous, current in zip(closes[-15:-1], closes[-14:], strict=True)
    ]
    expected_volatility = (
        statistics.stdev(latest_14_log_returns) * math.sqrt(252) * 100
    )

    assert float(latest.rolling_average_20d) == pytest.approx(
        expected_rolling_average,
        abs=1e-5,
    )
    assert float(latest.return_20d_percent) == pytest.approx(
        expected_return,
        abs=1e-5,
    )
    assert float(latest.realized_volatility_14d_percent) == pytest.approx(
        expected_volatility,
        abs=1e-5,
    )
    assert latest.rba_observation_date <= latest.trading_date
