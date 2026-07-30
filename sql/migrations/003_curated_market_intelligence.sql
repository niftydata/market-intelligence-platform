CREATE SCHEMA IF NOT EXISTS curated;

CREATE TABLE IF NOT EXISTS curated.market_intelligence_daily (
    trading_date date PRIMARY KEY,
    instrument_code text NOT NULL,
    close_value numeric(18, 6) NOT NULL,
    rolling_average_20d numeric(18, 6),
    return_20d_percent numeric(18, 6),
    realized_volatility_14d_percent numeric(18, 6),
    rba_series_code text,
    rba_observation_date date,
    rba_cash_rate_percent numeric(9, 6),
    rba_observation_age_days integer,
    volatility_p75_threshold numeric(18, 6),
    volatility_p90_threshold numeric(18, 6),
    rag_status text NOT NULL CHECK (
        rag_status IN ('green', 'amber', 'red', 'insufficient_data')
    ),
    source_market_loaded_at timestamptz NOT NULL,
    source_rba_loaded_at timestamptz,
    calculated_at timestamptz NOT NULL DEFAULT now(),
    pipeline_run_id bigint NOT NULL
        REFERENCES control.pipeline_run (pipeline_run_id),
    CONSTRAINT ck_rba_observation_not_future CHECK (
        rba_observation_date IS NULL OR rba_observation_date <= trading_date
    ),
    CONSTRAINT ck_rba_observation_age_nonnegative CHECK (
        rba_observation_age_days IS NULL OR rba_observation_age_days >= 0
    )
);

CREATE INDEX IF NOT EXISTS ix_market_intelligence_daily_rag_date
    ON curated.market_intelligence_daily (rag_status, trading_date DESC);
