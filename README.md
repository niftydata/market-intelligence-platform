# Market Intelligence Platform

An end-to-end market intelligence platform featuring repeatable data ingestion,
data-quality validation, curated analytics, and interactive visualisation.

The current vertical slice ingests five years of daily S&P/ASX 200 (`^AXJO`)
history from Yahoo Finance and the RBA Interbank Overnight Cash Rate into
PostgreSQL. It validates each record, retains rejected records, records pipeline
outcomes, and loads accepted observations idempotently.

## Persistence model

Data is persisted in PostgreSQL rather than in the application container or
repository:

- Local development uses the PostgreSQL service in `compose.yaml`. Its named
  Docker volume survives container recreation.
- The hosted application will use Render PostgreSQL.
- Both environments are selected with `DATABASE_URL` and use the same schema
  migrations.

The first migration creates:

- `raw.market_index_daily` for source-aligned daily index records;
- `raw.rba_cash_rate_daily` for the RBA F1 `FIRMMCRID` series;
- `curated.market_intelligence_daily` for the aligned analytical dataset;
- `control.pipeline_run` for run status and record counts;
- `control.data_quality_result` for explicit validation outcomes;
- `control.rejected_record` for records that must not be silently discarded.

## Local setup

Prerequisites:

- Python 3.12
- Docker with Docker Compose

Create the local configuration:

```powershell
Copy-Item .env.example .env
```

Start PostgreSQL:

```powershell
docker compose up -d postgres
```

Create a virtual environment and install the project:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

Apply database migrations:

```powershell
market-intelligence init-db
```

Run the Yahoo Finance ingestion through today's date:

```powershell
market-intelligence ingest-yahoo
```

Run the RBA ingestion:

```powershell
market-intelligence ingest-rba
```

Refresh the curated analytical dataset:

```powershell
market-intelligence transform-curated
```

Start the dashboard locally:

```powershell
streamlit run app/streamlit_app.py
```

For a reproducible historical run:

```powershell
market-intelligence ingest-yahoo --as-of 2026-07-30
```

The first run requests five years of history. Subsequent runs start seven
calendar days before the latest stored observation and upsert by
`(instrument_code, trading_date)`.

## Current data contracts

### Yahoo Finance

- Source: Yahoo Finance
- Symbol: `^AXJO`
- Instrument code: `ASX200`
- Frequency: daily
- Canonical date: Australian market date (`Australia/Sydney`)
- Required values: open, high, low, close
- Optional values: adjusted close and volume
- Initial history: five years
- Incremental overlap: seven calendar days

Yahoo Finance is the data source; `yfinance` is the transport library. The
source response is treated as an external contract and is validated before
persistence.

### Reserve Bank of Australia

- Source: RBA Statistical Table F1 CSV
- Series: `FIRMMCRID`
- Measure: Interbank Overnight Cash Rate
- Frequency: daily
- Unit: per cent
- Business key: `(series_code, observation_date)`
- Initial history: five years
- Incremental overlap: seven calendar days

The F1 download contains metadata rows before its observations. The ingestion
validates the series identifier, title, frequency, unit, source, and publication
date before accepting data. A dated row with a blank cash-rate value is retained
in `control.rejected_record` and produces a quality warning; it is not silently
dropped or forward-filled in the raw layer.

## Curated analytical dataset

`curated.market_intelligence_daily` has one row per ASX 200 trading date. It
contains:

- the closing index value and 20-trading-day rolling average;
- 20-trading-day percentage return;
- 14-trading-day annualised realised volatility;
- the most recent RBA cash-rate observation on or before the trading date;
- the RBA observation date and its age;
- five-year volatility percentile thresholds and the resulting RAG status;
- raw-source load timestamps and the transformation pipeline-run identifier.

The transformation refreshes the table transactionally and checks that its
latest date matches the raw market layer, no future macro observation is used,
and the latest 90 days contain complete calculated metrics. Definitions and
assumptions are documented in
[`docs/metric_definitions.md`](docs/metric_definitions.md).

The dashboard includes an analysis end-date selector. It resolves weekends and
market holidays to the most recent available trading date and displays the
trailing 90 calendar days. Historical RAG thresholds use only observations
available on or before the selected date, avoiding look-ahead bias.

AI-assisted development decisions and corrections are recorded in
[`docs/ai-agent-log.md`](docs/ai-agent-log.md).

The optional, tool-grounded Microsoft Foundry assistant design is documented in
[`docs/ai-assistant-design.md`](docs/ai-assistant-design.md).

## Tests

```powershell
pytest
```

The current tests cover Yahoo's multi-level response columns, timezone-aware
trading dates, schema changes, invalid OHLC records, RBA metadata validation,
date-window filtering, and missing RBA observations.

The curated metric integration test is opt-in because it requires PostgreSQL:

```powershell
$env:INTEGRATION_DATABASE_URL = $env:DATABASE_URL
pytest tests/test_curated_integration.py
Remove-Item Env:INTEGRATION_DATABASE_URL
```

It independently recalculates the latest rolling average, return, and
volatility from raw closing values and compares them with the persisted curated
metrics.

## Render dashboard deployment

`render.yaml` defines a Singapore-region Streamlit web service with a health
check and the custom domain
`market-intelligence.niftydata.com.au`.

The Render web service requires these secret environment variables:

- `DATABASE_URL`: use the Render PostgreSQL **internal** database URL when the
  web service and database are both in Singapore.
- `AI_DEMO_PASSWORD_HASH`: PBKDF2 hash for the password protecting the optional
  Ask AI panel. Never store the plaintext password in source control.

The non-secret AI demo settings are defined in `render.yaml`. The dashboard
remains public; only the Ask AI panel requires authentication. Five failed
sign-in attempts lock that browser session for 60 seconds.

The dashboard is read-only and queries only curated and operational metadata.
It does not perform ingestion or transformation work in a web request.

The complete Render and DNS handoff is in
[`docs/render-deployment.md`](docs/render-deployment.md).
