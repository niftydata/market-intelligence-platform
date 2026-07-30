CREATE TABLE IF NOT EXISTS raw.rba_cash_rate_daily (
    series_code text NOT NULL,
    observation_date date NOT NULL,
    rate_percent numeric(9, 6) NOT NULL,
    unit text NOT NULL,
    source_publication_date date,
    source_loaded_at timestamptz NOT NULL DEFAULT now(),
    pipeline_run_id bigint NOT NULL
        REFERENCES control.pipeline_run (pipeline_run_id),
    PRIMARY KEY (series_code, observation_date),
    CONSTRAINT ck_rba_cash_rate_range CHECK (
        rate_percent >= 0 AND rate_percent <= 100
    )
);
