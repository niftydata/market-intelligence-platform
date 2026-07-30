# Market Intelligence Platform

An end-to-end market intelligence platform featuring repeatable data ingestion,
data-quality validation, curated analytics, and interactive visualisation.

The current vertical slice ingests five years of daily S&P/ASX 200 (`^AXJO`)
history from Yahoo Finance into PostgreSQL. It validates each record, retains
rejected records, records pipeline outcomes, and loads accepted observations
idempotently.

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

For a reproducible historical run:

```powershell
market-intelligence ingest-yahoo --as-of 2026-07-30
```

The first run requests five years of history. Subsequent runs start seven
calendar days before the latest stored observation and upsert by
`(instrument_code, trading_date)`.

## Current data contract

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

## Tests

```powershell
pytest
```

The current tests cover Yahoo's multi-level response columns, timezone-aware
trading dates, schema changes, and invalid OHLC records.
