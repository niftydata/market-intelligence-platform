# Market Intelligence Platform

An end-to-end market intelligence platform featuring repeatable data ingestion,
data-quality validation, curated analytics, and interactive visualisation.

The current vertical slice ingests five years of daily S&P/ASX 200 (`^AXJO`)
history from Yahoo Finance and the RBA Interbank Overnight Cash Rate into
PostgreSQL. It validates each record, retains rejected records, records pipeline
outcomes, and loads accepted observations idempotently.

**Live dashboard:**
[market-intelligence.niftydata.com.au](https://market-intelligence.niftydata.com.au/)

## Key design decisions

- **Public, replaceable sources:** Yahoo Finance and the RBA satisfy the
  public-data requirement without coupling the solution to a brokerage account.
- **PostgreSQL as the system of record:** application restarts do not remove
  history, audit results or curated data. Local and hosted environments share
  the same migrations.
- **Layered data model:** raw tables preserve source-aligned observations,
  curated tables hold management-ready measures, reference tables hold governed
  context, and control tables provide operational evidence.
- **Idempotent incremental ingestion:** overlapping extraction windows and
  database upserts allow safe reruns without creating duplicate business keys.
- **Quality failures are visible:** invalid records are quarantined rather than
  silently repaired. Pipeline counts, checks and error details remain queryable.
- **Transactional analytical handoff:** curated data is replaced only after its
  validation succeeds. A failed refresh leaves the last validated dashboard in
  service.
- **Measures before narrative:** returns, volatility, correlations and signal
  thresholds are calculated deterministically. The AI assistant receives
  governed tool outputs rather than unrestricted database or SQL access.
- **Time-aware management context:** event timestamps are converted to the
  relevant ASX session using the Sydney timezone and trading calendar. An
  explicit reviewed override is used when historical timing is uncertain.
- **Operational separation:** the Singapore-hosted dashboard can serve the
  validated data, while the RBA ingestion can run from an Australian machine if
  the source rejects the hosted region.
- **Simple demo security:** username/password authentication protects AI and
  refresh functions. Production use would require enterprise identity,
  authorization, managed secrets and stronger audit controls.

## Persistence model

Data is persisted in PostgreSQL rather than in the application container or
repository:

- Local development uses the PostgreSQL service in `compose.yaml`. Its named
  Docker volume survives container recreation.
- The hosted application uses Render PostgreSQL.
- Both environments are selected with `DATABASE_URL` and use the same schema
  migrations.

The ordered database migrations create:

- `raw.market_index_daily` for source-aligned daily index records;
- `raw.rba_cash_rate_daily` for the RBA F1 `FIRMMCRID` series;
- `curated.market_intelligence_daily` for the aligned analytical dataset;
- `reference.market_event` for approved, source-cited contextual annotations;
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

The volatility chart overlays at most five major context markers in its visible
window. Material RBA cash-rate movements of at least 0.10 percentage points and
entries into the red volatility state are derived deterministically. External
events are displayed only when approved in `reference.market_event`, retain
their source, and are mapped to the next
available ASX trading date when they occur on a non-trading day. These markers
provide context and do not assert causation.

External-event alignment is timezone and trading-calendar aware. Where a precise
UTC timestamp is available, the event is mapped to the first curated ASX session
whose 4:00 pm Australia/Sydney close follows it. A governed effective-market-date
override is retained for historical events where the source does not provide a
defensible timestamp. Tooltips show the occurrence time, plotted ASX session,
alignment method, country, scope, transmission channel and source.

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
- `AZURE_CLIENT_SECRET`: service-principal secret used by the server to call
  the agent-scoped Microsoft Foundry Responses endpoint. Add it directly in
  Render.

The non-secret AI demo settings are defined in `render.yaml`. The dashboard
remains public; only the Ask AI panel requires authentication. Five failed
sign-in attempts lock that browser session for 60 seconds. Authenticated
sessions are limited to 20 Foundry questions before the conversation is reset.

The same authenticated sidebar includes an operational data refresh. It runs
the Yahoo Finance and RBA incremental ingestions, then rebuilds the curated
analytics only when both sources succeed. PostgreSQL advisory locking prevents
overlapping refreshes. The dashboard reports received, accepted, and rejected
rows for each stage, and the curated replacement is rolled back if its quality
checks fail so the last validated dashboard remains available.

The dashboard is read-only and queries only curated and operational metadata.
Only an authenticated refresh action performs ingestion or transformation
work in the web process.

The complete Render and DNS handoff is in
[`docs/render-deployment.md`](docs/render-deployment.md).

## Team-member handover

This handover assumes the receiving developer is junior and may be new to Git,
GitHub, PostgreSQL and hosted data applications. They should not be expected to
operate production alone after reading a document. Use paired practice,
teach-back and progressively increased access.

### 1. Handover outcomes

At the end of handover, the developer should be able to:

1. explain the raw, curated, reference and control layers in plain language;
2. create a branch, make a small change, run checks and open a pull request;
3. build the application locally without using production credentials;
4. run and verify each ingestion and transformation stage;
5. distinguish a source failure from a validation or deployment failure;
6. explain why the last validated dashboard remains available after failure;
7. deploy an additive change under supervision; and
8. recognise changes that require senior review or escalation.

### 2. Access and security preparation

A senior owner should provision access rather than sharing personal accounts:

- add the developer to the GitHub repository with the least privilege required;
- give read-only Render access initially, adding deployment access only after a
  successful supervised release;
- use a local PostgreSQL database for development;
- provide production database, Render and Microsoft Foundry secrets through an
  approved password manager or secret store;
- keep `.env` and `.env.local` outside Git; and
- rotate any secret immediately if it appears in Git history, logs, screenshots
  or chat.

The developer must never paste production credentials into source code, a pull
request, an issue, a test fixture or a support message. They must never run
`DROP`, `TRUNCATE`, an unbounded `DELETE`, or a destructive Git command against
shared resources without explicit senior approval and a recovery plan.

### 3. Repository orientation

Walk through these locations together before making a change:

| Location | Purpose |
|---|---|
| `app/streamlit_app.py` | Dashboard layout, charts and authenticated sidebar |
| `src/market_intelligence/ingestion/` | Yahoo and RBA source adapters and validation |
| `src/market_intelligence/pipeline.py` | Pipeline orchestration, stage outcomes and handoff |
| `src/market_intelligence/database.py` | Connections, migrations, persistence and curated refresh |
| `src/market_intelligence/dashboard/` | Dashboard queries and authentication helpers |
| `src/market_intelligence/assistant/` | Foundry client and deterministic AI tools |
| `sql/migrations/` | Immutable, ordered database schema changes |
| `sql/transforms/` | Curated analytical transformation |
| `tests/` | Unit and opt-in PostgreSQL integration tests |
| `docs/` | Metrics, deployment, AI design and AI-development log |
| `render.yaml` | Hosted service definition and non-secret configuration |

The key execution path is:

```text
Yahoo + RBA -> validation -> raw tables -> curated transformation
             -> control evidence        -> dashboard + grounded AI tools
```

### 4. Git and GitHub starter workflow

Explain that **Git** records versions locally and **GitHub** hosts the shared
repository and pull-request review. Protect `main`: normal work starts from a
short-lived branch and reaches `main` only through a reviewed pull request.

Clone and inspect the repository:

```powershell
git clone https://github.com/niftydata/market-intelligence-platform.git
Set-Location market-intelligence-platform
git status
git log --oneline -5
```

Start each change from current `main`:

```powershell
git switch main
git pull --ff-only
git switch -c docs/junior-practice
```

After editing, review and test before staging:

```powershell
git status
git diff
ruff check app src tests
pytest
git add README.md
git diff --staged
git commit -m "docs: clarify local setup"
git push -u origin docs/junior-practice
```

Open a GitHub pull request, describe what changed and how it was verified, then
request review. The first exercise should be a documentation-only improvement.
The second should add or amend a test without changing production behaviour.

Avoid `git add .` until the developer can confidently explain every listed
file. Never commit `.env`, `.env.local`, database exports, credentials or local
logs. Do not force-push shared branches, commit directly to `main`, or resolve a
merge conflict by discarding changes that are not understood.

### 5. Local onboarding exercise

Complete the [Local setup](#local-setup) together using local PostgreSQL. Confirm
that `DATABASE_URL` points to `localhost` before running migrations or ingestion.
Then ask the developer to perform the sequence while the senior observes:

```powershell
market-intelligence init-db
market-intelligence ingest-yahoo
market-intelligence ingest-rba
market-intelligence transform-curated
pytest
streamlit run app/streamlit_app.py
```

The developer should verify dashboard freshness, four management metrics, both
charts, the analysis-date selector and event annotations. They should also use
DBeaver or `psql` to inspect, without editing, the latest rows in:

- `control.pipeline_run`;
- `control.data_quality_result`;
- `control.rejected_record`; and
- `curated.market_intelligence_daily`.

### 6. Routine production refresh

The RBA source can reject requests from the Singapore-hosted service. The
scheduled production refresh therefore runs from the always-on Australian PC
and writes to the Render PostgreSQL database using its external connection URL.
The task runs these commands in order:

```powershell
market-intelligence ingest-yahoo
market-intelligence ingest-rba
market-intelligence transform-curated
```

Do not run the curated transformation if either source stage fails. Review the
command exit code, structured log, pipeline-run status and accepted/rejected
counts. Confirm the dashboard freshness only after all three stages succeed.
The authenticated web refresh is useful for demonstration and Yahoo refreshes,
but an RBA HTTP 403 from Singapore is an expected network-location constraint,
not evidence that the validated database has been damaged.

### 7. Database and deployment workflow

Schema changes are forward-only: create a new numbered SQL migration and never
edit a migration that has already been applied to a shared database. Prefer
additive, backward-compatible changes.

For a supervised release:

1. review the code, migration, tests and rollback implications in the PR;
2. verify that no secrets or unrelated files are included;
3. run unit tests and the PostgreSQL integration suite;
4. apply a backward-compatible migration before deploying code that requires it;
5. merge the approved PR and allow Render's automatic deployment to complete;
6. check the Render build log and `/_stcore/health` endpoint;
7. open the live dashboard and verify freshness, charts, authentication and AI;
8. inspect the latest pipeline and quality records; and
9. record the release result and any follow-up work.

Configure the integration suite only for an approved disposable or shared test
database—not casually against production:

```powershell
$env:INTEGRATION_DATABASE_URL = $env:DATABASE_URL
pytest
Remove-Item Env:INTEGRATION_DATABASE_URL
```

Application rollback is performed through a reviewed Git revert and redeploy.
Database rollback must be designed for the specific migration; do not assume
that reversing arbitrary schema or data changes is safe.

### 8. First-line troubleshooting

| Symptom | First checks | Action or escalation |
|---|---|---|
| RBA returns HTTP 403 | Execution region and source URL | Run from the Australian scheduler; retain the last validated dataset |
| Yahoo or RBA rows rejected | Pipeline counts and `control.rejected_record` | Confirm whether the upstream schema/value changed before modifying validation |
| Curated refresh fails | Pipeline error, transform file and quality results | Do not bypass checks; confirm the prior curated data remains available |
| Dashboard is stale | Latest three pipeline runs and scheduler history | Rerun only the failed stage after identifying the cause |
| Event marker is missing | Selected 90-day window, approval flag and effective ASX date | Verify timezone/trading-day alignment and wait for the five-minute cache |
| AI is unavailable | Dashboard health, Render secrets and Foundry role/endpoint | Treat AI as isolated; the dashboard and data should remain available |
| Migration is missing | `control.schema_migration` and deployment order | Stop deployment and ask a senior to review before applying it |

Escalate immediately for suspected credential exposure, destructive or
irreversible data changes, unexplained metric changes, an upstream contract
change, repeated production failures, authentication concerns, or any request
to weaken a validation rule merely to make a pipeline pass.

### 9. Definition of done for future changes

A change is not complete until:

- requirements and assumptions are written down;
- source contracts and timezone/trading-date effects have been considered;
- code, SQL and documentation agree;
- appropriate unit and integration tests pass;
- invalid data and failure behaviour have been tested;
- secrets and unrelated files are absent from the diff;
- a reviewer can reproduce the verification steps;
- operational monitoring and rollback implications are understood; and
- the live service is checked after deployment.

### 10. Suggested handover schedule

- **Session 1 — architecture and local setup:** senior demonstrates, junior
  takes notes and explains the data flow back.
- **Session 2 — GitHub practice:** junior creates the documentation PR above;
  senior reviews it in GitHub and explains comments, approvals and merging.
- **Session 3 — pipeline operations:** junior runs a local refresh, identifies
  accepted/rejected counts and explains a simulated failure.
- **Session 4 — reverse shadow:** junior leads a low-risk release while the
  senior observes and retains production authority.
- **First two production changes:** mandatory senior review and paired release.
- **Afterwards:** review access and independence only when the junior can
  complete the outcomes in section 1 without unsafe shortcuts.
