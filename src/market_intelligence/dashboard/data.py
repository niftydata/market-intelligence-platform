from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import pandas as pd
from sqlalchemy import Engine, text


@dataclass(frozen=True)
class DashboardMetadata:
    first_curated_date: date
    latest_market_date: date
    latest_rba_date: date
    latest_curated_date: date
    latest_calculated_at: datetime
    latest_curated_run_status: str
    latest_curated_run_finished_at: datetime | None


def load_dashboard_frame(
    engine: Engine,
    *,
    analysis_end_date: date,
    window_days: int = 90,
) -> pd.DataFrame:
    query = text(
        """
        WITH effective_end AS (
            SELECT max(trading_date) AS end_date
            FROM curated.market_intelligence_daily
            WHERE trading_date <= :analysis_end_date
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
        CROSS JOIN effective_end
        WHERE curated.trading_date >=
            effective_end.end_date - (:window_days * INTERVAL '1 day')
            AND curated.trading_date <= effective_end.end_date
        ORDER BY curated.trading_date
        """
    )
    frame = pd.read_sql_query(
        query,
        engine,
        params={
            "analysis_end_date": analysis_end_date,
            "window_days": window_days,
        },
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


def load_market_events(
    engine: Engine,
    *,
    window_start_date: date,
    window_end_date: date,
    max_events: int = 5,
) -> pd.DataFrame:
    """Load governed and deterministic context markers for the visible chart."""
    query = text(
        """
        WITH market_series AS (
            SELECT
                trading_date,
                rba_observation_date,
                rba_cash_rate_percent,
                rag_status,
                lag(rba_cash_rate_percent) OVER (
                    ORDER BY trading_date
                ) AS previous_cash_rate,
                lag(rag_status) OVER (
                    ORDER BY trading_date
                ) AS previous_rag_status
            FROM curated.market_intelligence_daily
            WHERE trading_date <= :window_end_date
        ),
        external_events AS (
            SELECT
                event.event_date,
                event.event_timestamp_utc,
                effective_date.plot_date,
                event.short_label,
                event.description,
                event.category,
                event.country_code,
                event.transmission_channel,
                event.event_scope,
                event.source_name,
                event.source_url,
                CASE
                    WHEN event.effective_market_date IS NOT NULL
                        THEN 'Governed market-date alignment'
                    WHEN event.event_timestamp_utc IS NOT NULL
                        THEN 'Timestamp aligned to first ASX close after event'
                    ELSE 'Event date aligned to available ASX session'
                END AS alignment_method,
                event.display_priority
            FROM reference.market_event AS event
            CROSS JOIN LATERAL (
                SELECT coalesce(
                    event.effective_market_date,
                    (
                        SELECT min(trading_date)
                        FROM curated.market_intelligence_daily
                        WHERE (
                            (trading_date::timestamp + TIME '16:00')
                            AT TIME ZONE 'Australia/Sydney'
                        ) >= coalesce(
                            event.event_timestamp_utc,
                            event.event_date::timestamp
                                AT TIME ZONE 'Australia/Sydney'
                        )
                    )
                ) AS plot_date
            ) AS effective_date
            WHERE event.is_approved
                AND effective_date.plot_date >= :window_start_date
                AND effective_date.plot_date <= :window_end_date
        ),
        cash_rate_changes AS (
            SELECT DISTINCT ON (rba_observation_date)
                rba_observation_date AS event_date,
                NULL::timestamptz AS event_timestamp_utc,
                trading_date AS plot_date,
                'RBA cash rate change'::text AS short_label,
                (
                    'The RBA cash rate changed from '
                    || trim(to_char(previous_cash_rate, 'FM990.00'))
                    || '% to '
                    || trim(to_char(rba_cash_rate_percent, 'FM990.00'))
                    || '%.'
                )::text AS description,
                'monetary_policy'::text AS category,
                'AU'::text AS country_code,
                'domestic monetary policy'::text AS transmission_channel,
                'domestic'::text AS event_scope,
                'Reserve Bank of Australia'::text AS source_name,
                'https://www.rba.gov.au/statistics/cash-rate/'::text AS source_url,
                'Observed on curated ASX trading date'::text AS alignment_method,
                80 AS display_priority
            FROM market_series
            WHERE trading_date >= :window_start_date
                AND rba_observation_date IS NOT NULL
                AND previous_cash_rate IS NOT NULL
                AND rba_cash_rate_percent IS DISTINCT FROM previous_cash_rate
                AND abs(rba_cash_rate_percent - previous_cash_rate) >= 0.10
            ORDER BY rba_observation_date, trading_date
        ),
        red_signal_entries AS (
            SELECT
                trading_date AS event_date,
                NULL::timestamptz AS event_timestamp_utc,
                trading_date AS plot_date,
                'Red volatility signal'::text AS short_label,
                'The 14-day realised-volatility measure entered the red monitoring state.'::text
                    AS description,
                'market_shock'::text AS category,
                NULL::text AS country_code,
                'calculated market volatility'::text AS transmission_channel,
                'domestic'::text AS event_scope,
                'NiftyData calculated metric'::text AS source_name,
                ''::text AS source_url,
                'Calculated on curated ASX trading date'::text AS alignment_method,
                60 AS display_priority
            FROM market_series
            WHERE trading_date >= :window_start_date
                AND rag_status = 'red'
                AND previous_rag_status IS DISTINCT FROM 'red'
            ORDER BY trading_date
            LIMIT 1
        ),
        ranked_events AS (
            SELECT * FROM external_events
            UNION ALL
            SELECT * FROM cash_rate_changes
            UNION ALL
            SELECT * FROM red_signal_entries
        ),
        limited_events AS (
            SELECT *
            FROM ranked_events
            ORDER BY display_priority DESC, event_date DESC
            LIMIT :max_events
        )
        SELECT
            event_date,
            event_timestamp_utc,
            plot_date,
            short_label,
            description,
            category,
            country_code,
            transmission_channel,
            event_scope,
            source_name,
            source_url,
            alignment_method,
            display_priority
        FROM limited_events
        ORDER BY plot_date, display_priority DESC
        """
    )
    return pd.read_sql_query(
        query,
        engine,
        params={
            "window_start_date": window_start_date,
            "window_end_date": window_end_date,
            "max_events": max_events,
        },
        parse_dates=["event_date", "event_timestamp_utc", "plot_date"],
    )


def load_dashboard_metadata(engine: Engine) -> DashboardMetadata:
    query = text(
        """
        SELECT
            (SELECT min(trading_date)
                FROM curated.market_intelligence_daily)
                AS first_curated_date,
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
            "first_curated_date",
        )
    ):
        raise RuntimeError("Dashboard freshness metadata is incomplete")
    return DashboardMetadata(**values)
