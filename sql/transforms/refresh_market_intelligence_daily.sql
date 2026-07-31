WITH market_bounds AS (
    SELECT max(trading_date) AS latest_market_date
    FROM raw.market_index_daily
),
market_window AS (
    SELECT
        market.instrument_code,
        market.trading_date,
        market.close_value,
        market.source_loaded_at AS source_market_loaded_at,
        lag(market.close_value, 1) OVER (
            PARTITION BY market.instrument_code
            ORDER BY market.trading_date
        ) AS previous_close_value,
        lag(market.close_value, 20) OVER (
            PARTITION BY market.instrument_code
            ORDER BY market.trading_date
        ) AS close_value_20_observations_ago,
        avg(market.close_value) OVER (
            PARTITION BY market.instrument_code
            ORDER BY market.trading_date
            ROWS BETWEEN 19 PRECEDING AND CURRENT ROW
        ) AS rolling_average_20d_unchecked,
        count(market.close_value) OVER (
            PARTITION BY market.instrument_code
            ORDER BY market.trading_date
            ROWS BETWEEN 19 PRECEDING AND CURRENT ROW
        ) AS rolling_average_observation_count
    FROM raw.market_index_daily AS market
    CROSS JOIN market_bounds AS bounds
    WHERE market.trading_date >=
        bounds.latest_market_date - INTERVAL '5 years'
),
return_metrics AS (
    SELECT
        *,
        CASE
            WHEN previous_close_value IS NOT NULL
            THEN ln(close_value / previous_close_value)
        END AS daily_log_return,
        CASE
            WHEN rolling_average_observation_count = 20
            THEN rolling_average_20d_unchecked
        END AS rolling_average_20d,
        CASE
            WHEN close_value_20_observations_ago IS NOT NULL
            THEN ((close_value / close_value_20_observations_ago) - 1) * 100
        END AS return_20d_percent
    FROM market_window
),
volatility_metrics AS (
    SELECT
        *,
        CASE
            WHEN count(daily_log_return) OVER (
                PARTITION BY instrument_code
                ORDER BY trading_date
                ROWS BETWEEN 13 PRECEDING AND CURRENT ROW
            ) = 14
            THEN stddev_samp(daily_log_return) OVER (
                PARTITION BY instrument_code
                ORDER BY trading_date
                ROWS BETWEEN 13 PRECEDING AND CURRENT ROW
            ) * sqrt(252.0) * 100
        END AS realized_volatility_14d_percent
    FROM return_metrics
),
aligned AS (
    SELECT
        market.*,
        macro.series_code AS rba_series_code,
        macro.observation_date AS rba_observation_date,
        macro.rate_percent AS rba_cash_rate_percent,
        macro.source_loaded_at AS source_rba_loaded_at
    FROM volatility_metrics AS market
    LEFT JOIN LATERAL (
        SELECT
            rba.series_code,
            rba.observation_date,
            rba.rate_percent,
            rba.source_loaded_at
        FROM raw.rba_cash_rate_daily AS rba
        WHERE rba.observation_date <= market.trading_date
        ORDER BY rba.observation_date DESC
        LIMIT 1
    ) AS macro ON true
),
thresholded AS (
    SELECT
        aligned.*,
        thresholds.baseline_observation_count,
        thresholds.volatility_p75_threshold,
        thresholds.volatility_p90_threshold
    FROM aligned
    LEFT JOIN LATERAL (
        SELECT
            count(*) AS baseline_observation_count,
            percentile_cont(0.75) WITHIN GROUP (
                ORDER BY baseline.realized_volatility_14d_percent
            ) AS volatility_p75_threshold,
            percentile_cont(0.90) WITHIN GROUP (
                ORDER BY baseline.realized_volatility_14d_percent
            ) AS volatility_p90_threshold
        FROM volatility_metrics AS baseline
        WHERE baseline.instrument_code = aligned.instrument_code
            AND baseline.trading_date <= aligned.trading_date
            AND baseline.trading_date >=
                aligned.trading_date - INTERVAL '5 years'
            AND baseline.realized_volatility_14d_percent IS NOT NULL
    ) AS thresholds ON true
)
INSERT INTO curated.market_intelligence_daily (
    trading_date,
    instrument_code,
    close_value,
    rolling_average_20d,
    return_20d_percent,
    realized_volatility_14d_percent,
    rba_series_code,
    rba_observation_date,
    rba_cash_rate_percent,
    rba_observation_age_days,
    volatility_p75_threshold,
    volatility_p90_threshold,
    rag_status,
    source_market_loaded_at,
    source_rba_loaded_at,
    calculated_at,
    pipeline_run_id
)
SELECT
    thresholded.trading_date,
    thresholded.instrument_code,
    thresholded.close_value,
    thresholded.rolling_average_20d,
    thresholded.return_20d_percent,
    thresholded.realized_volatility_14d_percent,
    thresholded.rba_series_code,
    thresholded.rba_observation_date,
    thresholded.rba_cash_rate_percent,
    CASE
        WHEN thresholded.rba_observation_date IS NOT NULL
        THEN thresholded.trading_date - thresholded.rba_observation_date
    END AS rba_observation_age_days,
    thresholded.volatility_p75_threshold,
    thresholded.volatility_p90_threshold,
    CASE
        WHEN thresholded.realized_volatility_14d_percent IS NULL
            OR thresholded.baseline_observation_count < 60
            OR thresholded.volatility_p75_threshold IS NULL
            OR thresholded.volatility_p90_threshold IS NULL
        THEN 'insufficient_data'
        WHEN thresholded.realized_volatility_14d_percent
            >= thresholded.volatility_p90_threshold
        THEN 'red'
        WHEN thresholded.realized_volatility_14d_percent
            >= thresholded.volatility_p75_threshold
        THEN 'amber'
        ELSE 'green'
    END AS rag_status,
    thresholded.source_market_loaded_at,
    thresholded.source_rba_loaded_at,
    now(),
    :pipeline_run_id
FROM thresholded
ORDER BY thresholded.trading_date;
