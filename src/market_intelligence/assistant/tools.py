from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import Engine, text

from market_intelligence.dashboard.data import load_dashboard_metadata

METRICS = {
    "asx_200_close": ("close_value", "S&P/ASX 200 close", "index points"),
    "rolling_average_20d": (
        "rolling_average_20d",
        "20-day rolling average",
        "index points",
    ),
    "return_20d_percent": (
        "return_20d_percent",
        "20-day return",
        "percent",
    ),
    "realized_volatility_14d_percent": (
        "realized_volatility_14d_percent",
        "14-day annualised realised volatility",
        "percent",
    ),
    "rba_cash_rate_percent": (
        "rba_cash_rate_percent",
        "RBA cash rate",
        "percent",
    ),
}

MAX_HISTORY_DAYS = 366
MAX_HISTORY_ROWS = 270
MAX_EXTREME_ROWS = 10


def _parse_date(value: str, *, field_name: str) -> date:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must use YYYY-MM-DD format") from exc


def _date_range(start_date: str, end_date: str) -> tuple[date, date]:
    start = _parse_date(start_date, field_name="start_date")
    end = _parse_date(end_date, field_name="end_date")
    if start > end:
        raise ValueError("start_date must be on or before end_date")
    return start, end


def _metric(metric: str) -> tuple[str, str, str]:
    try:
        return METRICS[metric]
    except KeyError as exc:
        allowed = ", ".join(sorted(METRICS))
        raise ValueError(f"metric must be one of: {allowed}") from exc


def _number(value: Any) -> float | int | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (float, int)):
        return value
    return float(value)


class MarketDataTools:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def get_available_date_range(self) -> dict[str, Any]:
        query = text(
            """
            SELECT
                min(trading_date) AS first_date,
                max(trading_date) AS latest_date,
                count(*) AS observation_count
            FROM curated.market_intelligence_daily
            """
        )
        with self._engine.connect() as connection:
            row = connection.execute(query).one()
        if row.first_date is None or row.latest_date is None:
            raise RuntimeError("No curated market observations are available")
        return {
            "first_date": row.first_date.isoformat(),
            "latest_date": row.latest_date.isoformat(),
            "observation_count": row.observation_count,
            "available_metrics": sorted(METRICS),
        }

    def get_market_snapshot(self, as_of_date: str) -> dict[str, Any]:
        requested_date = _parse_date(as_of_date, field_name="as_of_date")
        query = text(
            """
            SELECT
                trading_date,
                close_value,
                rolling_average_20d,
                return_20d_percent,
                realized_volatility_14d_percent,
                volatility_p75_threshold,
                volatility_p90_threshold,
                rag_status,
                rba_cash_rate_percent,
                rba_observation_date
            FROM curated.market_intelligence_daily
            WHERE trading_date <= :requested_date
            ORDER BY trading_date DESC
            LIMIT 1
            """
        )
        with self._engine.connect() as connection:
            row = connection.execute(
                query,
                {"requested_date": requested_date},
            ).one_or_none()
        if row is None:
            raise ValueError("No market observation exists on or before that date")
        return {
            "requested_date": requested_date.isoformat(),
            "effective_trading_date": row.trading_date.isoformat(),
            "asx_200_close": _number(row.close_value),
            "rolling_average_20d": _number(row.rolling_average_20d),
            "return_20d_percent": _number(row.return_20d_percent),
            "realized_volatility_14d_percent": _number(
                row.realized_volatility_14d_percent
            ),
            "volatility_p75_threshold": _number(row.volatility_p75_threshold),
            "volatility_p90_threshold": _number(row.volatility_p90_threshold),
            "signal_status": row.rag_status,
            "rba_cash_rate_percent": _number(row.rba_cash_rate_percent),
            "rba_observation_date": row.rba_observation_date.isoformat(),
        }

    def get_metric_history(
        self,
        metric: str,
        start_date: str,
        end_date: str,
    ) -> dict[str, Any]:
        column, label, unit = _metric(metric)
        start, end = _date_range(start_date, end_date)
        if (end - start).days > MAX_HISTORY_DAYS:
            raise ValueError(
                f"Metric history is limited to {MAX_HISTORY_DAYS} calendar days; "
                "use period comparison or extreme observations for longer ranges"
            )
        query = text(
            f"""
            SELECT trading_date, {column} AS metric_value
            FROM curated.market_intelligence_daily
            WHERE trading_date BETWEEN :start_date AND :end_date
                AND {column} IS NOT NULL
            ORDER BY trading_date
            LIMIT :row_limit
            """
        )
        with self._engine.connect() as connection:
            rows = connection.execute(
                query,
                {
                    "start_date": start,
                    "end_date": end,
                    "row_limit": MAX_HISTORY_ROWS,
                },
            ).all()
        return {
            "metric": metric,
            "label": label,
            "unit": unit,
            "requested_start_date": start.isoformat(),
            "requested_end_date": end.isoformat(),
            "observation_count": len(rows),
            "observations": [
                {
                    "date": row.trading_date.isoformat(),
                    "value": _number(row.metric_value),
                }
                for row in rows
            ],
        }

    def compare_periods(
        self,
        period_one_start: str,
        period_one_end: str,
        period_two_start: str,
        period_two_end: str,
    ) -> dict[str, Any]:
        first_start, first_end = _date_range(period_one_start, period_one_end)
        second_start, second_end = _date_range(period_two_start, period_two_end)
        return {
            "period_one": self._period_summary(first_start, first_end),
            "period_two": self._period_summary(second_start, second_end),
        }

    def get_extreme_observations(
        self,
        metric: str,
        direction: str,
        limit: int,
        start_date: str,
        end_date: str,
    ) -> dict[str, Any]:
        column, label, unit = _metric(metric)
        if direction not in {"highest", "lowest"}:
            raise ValueError("direction must be highest or lowest")
        if limit < 1 or limit > MAX_EXTREME_ROWS:
            raise ValueError(f"limit must be between 1 and {MAX_EXTREME_ROWS}")
        start, end = _date_range(start_date, end_date)
        order = "DESC" if direction == "highest" else "ASC"
        query = text(
            f"""
            SELECT
                trading_date,
                {column} AS metric_value,
                close_value,
                realized_volatility_14d_percent,
                rba_cash_rate_percent,
                rag_status
            FROM curated.market_intelligence_daily
            WHERE trading_date BETWEEN :start_date AND :end_date
                AND {column} IS NOT NULL
            ORDER BY {column} {order}, trading_date
            LIMIT :row_limit
            """
        )
        with self._engine.connect() as connection:
            rows = connection.execute(
                query,
                {
                    "start_date": start,
                    "end_date": end,
                    "row_limit": limit,
                },
            ).all()
        return {
            "metric": metric,
            "label": label,
            "unit": unit,
            "direction": direction,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "observations": [
                {
                    "date": row.trading_date.isoformat(),
                    "value": _number(row.metric_value),
                    "asx_200_close": _number(row.close_value),
                    "realized_volatility_14d_percent": _number(
                        row.realized_volatility_14d_percent
                    ),
                    "rba_cash_rate_percent": _number(row.rba_cash_rate_percent),
                    "signal_status": row.rag_status,
                }
                for row in rows
            ],
        }

    def get_data_freshness(self) -> dict[str, Any]:
        metadata = load_dashboard_metadata(self._engine)
        return {
            "first_curated_date": metadata.first_curated_date.isoformat(),
            "latest_curated_date": metadata.latest_curated_date.isoformat(),
            "latest_market_source_date": metadata.latest_market_date.isoformat(),
            "latest_rba_source_date": metadata.latest_rba_date.isoformat(),
            "latest_calculated_at": metadata.latest_calculated_at.isoformat(),
            "latest_pipeline_status": metadata.latest_curated_run_status,
        }

    def _period_summary(self, start: date, end: date) -> dict[str, Any]:
        query = text(
            """
            SELECT
                trading_date,
                close_value,
                return_20d_percent,
                realized_volatility_14d_percent,
                rba_cash_rate_percent
            FROM curated.market_intelligence_daily
            WHERE trading_date BETWEEN :start_date AND :end_date
            ORDER BY trading_date
            """
        )
        with self._engine.connect() as connection:
            rows = connection.execute(
                query,
                {"start_date": start, "end_date": end},
            ).all()
        if not rows:
            raise ValueError(
                f"No observations are available from {start.isoformat()} "
                f"through {end.isoformat()}"
            )

        start_close = float(rows[0].close_value)
        end_close = float(rows[-1].close_value)
        volatilities = [
            float(row.realized_volatility_14d_percent)
            for row in rows
            if row.realized_volatility_14d_percent is not None
        ]
        returns = [
            float(row.return_20d_percent)
            for row in rows
            if row.return_20d_percent is not None
        ]
        return {
            "requested_start_date": start.isoformat(),
            "requested_end_date": end.isoformat(),
            "effective_start_date": rows[0].trading_date.isoformat(),
            "effective_end_date": rows[-1].trading_date.isoformat(),
            "observation_count": len(rows),
            "start_close": start_close,
            "end_close": end_close,
            "period_change_percent": (end_close / start_close - 1) * 100,
            "average_volatility_percent": (
                sum(volatilities) / len(volatilities) if volatilities else None
            ),
            "maximum_volatility_percent": max(volatilities) if volatilities else None,
            "lowest_20d_return_percent": min(returns) if returns else None,
            "highest_20d_return_percent": max(returns) if returns else None,
            "start_cash_rate_percent": _number(rows[0].rba_cash_rate_percent),
            "end_cash_rate_percent": _number(rows[-1].rba_cash_rate_percent),
        }
