from __future__ import annotations

import math
import os
import statistics
from datetime import date

import pytest
from sqlalchemy import create_engine, text

import market_intelligence.database as database
from market_intelligence.dashboard.data import load_dashboard_frame

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


def test_dashboard_window_ends_on_or_before_selected_date() -> None:
    engine = create_engine(INTEGRATION_DATABASE_URL, pool_pre_ping=True)
    try:
        frame = load_dashboard_frame(
            engine,
            analysis_end_date=date(2026, 6, 28),
            window_days=90,
        )
    finally:
        engine.dispose()

    assert frame["trading_date"].max().date() <= date(2026, 6, 28)
    assert (
        frame["trading_date"].max() - frame["trading_date"].min()
    ).days <= 90


def test_failed_curated_validation_rolls_back_replacement(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    engine = create_engine(INTEGRATION_DATABASE_URL, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            before = connection.execute(
                text(
                    """
                    SELECT count(*) AS row_count, max(trading_date) AS latest_date
                    FROM curated.market_intelligence_daily
                    """
                )
            ).one()
            pipeline_run_id = connection.execute(
                text(
                    """
                    SELECT pipeline_run_id
                    FROM control.pipeline_run
                    ORDER BY pipeline_run_id DESC
                    LIMIT 1
                    """
                )
            ).scalar_one()

        transform_path = tmp_path / "refresh_market_intelligence_daily.sql"
        transform_path.write_text("SELECT 1 WHERE false;", encoding="utf-8")
        monkeypatch.setattr(database, "TRANSFORMS_DIRECTORY", tmp_path)

        with pytest.raises(RuntimeError, match="curated dataset is empty"):
            database.refresh_market_intelligence_daily(
                engine,
                pipeline_run_id=pipeline_run_id,
            )

        with engine.connect() as connection:
            after = connection.execute(
                text(
                    """
                    SELECT count(*) AS row_count, max(trading_date) AS latest_date
                    FROM curated.market_intelligence_daily
                    """
                )
            ).one()
    finally:
        engine.dispose()

    assert after == before
