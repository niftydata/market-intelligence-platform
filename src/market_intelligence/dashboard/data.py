from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import pandas as pd
from sqlalchemy import Engine, text


@dataclass(frozen=True)
class DashboardMetadata:
    latest_market_date: date
    latest_rba_date: date
    latest_curated_date: date
    latest_calculated_at: datetime
    latest_curated_run_status: str
    latest_curated_run_finished_at: datetime | None


def load_dashboard_frame(engine: Engine, *, window_days: int = 90) -> pd.DataFrame:
    query = text(
        """
        WITH latest AS (
            SELECT max(trading_date) AS latest_date
            FROM curated.market_intelligence_daily
        )
        SELECT
            curated.trading_date,
            curated.close_value,
            curated.rolling_average_20d,
            curated.return_20d_percent,
            curated.realized_volatility_14d_percent,
            curated.rba_observation_date,
            curated.rba_cash_rate_percent,
            curated.rba_observation_age_days,
            curated.volatility_p75_threshold,
            curated.volatility_p90_threshold,
            curated.rag_status
        FROM curated.market_intelligence_daily AS curated
        CROSS JOIN latest
        WHERE curated.trading_date >=
            latest.latest_date - (:window_days * INTERVAL '1 day')
        ORDER BY curated.trading_date
        """
    )
    frame = pd.read_sql_query(
        query,
        engine,
        params={"window_days": window_days},
        parse_dates=["trading_date", "rba_observation_date"],
    )
    if frame.empty:
        raise RuntimeError("The curated dashboard dataset is empty")

    numeric_columns = [
        "close_value",
        "rolling_average_20d",
        "return_20d_percent",
        "realized_volatility_14d_percent",
        "rba_cash_rate_percent",
        "volatility_p75_threshold",
        "volatility_p90_threshold",
    ]
    frame[numeric_columns] = frame[numeric_columns].apply(
        pd.to_numeric,
        errors="coerce",
    )
    return frame


def load_dashboard_metadata(engine: Engine) -> DashboardMetadata:
    query = text(
        """
        SELECT
            (SELECT max(trading_date) FROM raw.market_index_daily)
                AS latest_market_date,
            (SELECT max(observation_date) FROM raw.rba_cash_rate_daily)
                AS latest_rba_date,
            (SELECT max(trading_date)
                FROM curated.market_intelligence_daily)
                AS latest_curated_date,
            (SELECT max(calculated_at)
                FROM curated.market_intelligence_daily)
                AS latest_calculated_at,
            latest_run.status AS latest_curated_run_status,
            latest_run.finished_at AS latest_curated_run_finished_at
        FROM LATERAL (
            SELECT status, finished_at
            FROM control.pipeline_run
            WHERE pipeline_name = 'curated_market_intelligence_daily'
            ORDER BY started_at DESC
            LIMIT 1
        ) AS latest_run
        """
    )
    with engine.connect() as connection:
        row = connection.execute(query).one()
    values: dict[str, Any] = dict(row._mapping)
    if any(
        values[field] is None
        for field in (
            "latest_market_date",
            "latest_rba_date",
            "latest_curated_date",
            "latest_calculated_at",
        )
    ):
        raise RuntimeError("Dashboard freshness metadata is incomplete")
    return DashboardMetadata(**values)
