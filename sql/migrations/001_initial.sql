CREATE SCHEMA IF NOT EXISTS raw;
CREATE SCHEMA IF NOT EXISTS control;

CREATE TABLE IF NOT EXISTS control.schema_migration (
    version text PRIMARY KEY,
    applied_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS control.pipeline_run (
    pipeline_run_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    pipeline_name text NOT NULL,
    status text NOT NULL CHECK (status IN ('running', 'succeeded', 'failed')),
    extraction_start_date date,
    extraction_end_date date,
    records_received integer NOT NULL DEFAULT 0,
    records_accepted integer NOT NULL DEFAULT 0,
    records_rejected integer NOT NULL DEFAULT 0,
    started_at timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz,
    error_type text,
    error_message text,
    run_metadata jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS ix_pipeline_run_started_at
    ON control.pipeline_run (started_at DESC);

CREATE TABLE IF NOT EXISTS raw.market_index_daily (
    instrument_code text NOT NULL,
    trading_date date NOT NULL,
    open_value numeric(18, 6) NOT NULL,
    high_value numeric(18, 6) NOT NULL,
    low_value numeric(18, 6) NOT NULL,
    close_value numeric(18, 6) NOT NULL,
    adjusted_close_value numeric(18, 6),
    volume bigint,
    source_loaded_at timestamptz NOT NULL DEFAULT now(),
    pipeline_run_id bigint NOT NULL
        REFERENCES control.pipeline_run (pipeline_run_id),
    PRIMARY KEY (instrument_code, trading_date),
    CONSTRAINT ck_market_price_positive CHECK (
        open_value > 0
        AND high_value > 0
        AND low_value > 0
        AND close_value > 0
    ),
    CONSTRAINT ck_market_high_low CHECK (high_value >= low_value),
    CONSTRAINT ck_market_volume_nonnegative CHECK (volume IS NULL OR volume >= 0)
);

CREATE TABLE IF NOT EXISTS control.data_quality_result (
    data_quality_result_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    pipeline_run_id bigint NOT NULL
        REFERENCES control.pipeline_run (pipeline_run_id),
    check_name text NOT NULL,
    status text NOT NULL CHECK (status IN ('passed', 'warning', 'failed')),
    records_checked integer NOT NULL DEFAULT 0,
    records_failed integer NOT NULL DEFAULT 0,
    details jsonb NOT NULL DEFAULT '{}'::jsonb,
    checked_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS control.rejected_record (
    rejected_record_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    pipeline_run_id bigint NOT NULL
        REFERENCES control.pipeline_run (pipeline_run_id),
    source_name text NOT NULL,
    reason_code text NOT NULL,
    reason_detail text NOT NULL,
    raw_payload jsonb NOT NULL,
    rejected_at timestamptz NOT NULL DEFAULT now()
);
