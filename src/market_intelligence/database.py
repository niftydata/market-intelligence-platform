from __future__ import annotations

from collections.abc import Iterable
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, create_engine, text

MIGRATIONS_DIRECTORY = Path(__file__).resolve().parents[2] / "sql" / "migrations"
TRANSFORMS_DIRECTORY = Path(__file__).resolve().parents[2] / "sql" / "transforms"
REFRESH_ADVISORY_LOCK_ID = 6_407_202_026


def create_database_engine(database_url: str) -> Engine:
    normalized_url = database_url
    if database_url.startswith("postgresql://"):
        normalized_url = database_url.replace(
            "postgresql://",
            "postgresql+psycopg://",
            1,
        )
    elif database_url.startswith("postgres://"):
        normalized_url = database_url.replace(
            "postgres://",
            "postgresql+psycopg://",
            1,
        )
    return create_engine(
        normalized_url,
        pool_pre_ping=True,
        pool_size=3,
        max_overflow=2,
        pool_recycle=300,
    )


def apply_migrations(engine: Engine) -> None:
    migration_files = sorted(MIGRATIONS_DIRECTORY.glob("*.sql"))
    if not migration_files:
        raise RuntimeError(f"No database migrations found in {MIGRATIONS_DIRECTORY}")

    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE SCHEMA IF NOT EXISTS control")
        connection.exec_driver_sql(
            """
            CREATE TABLE IF NOT EXISTS control.schema_migration (
                version text PRIMARY KEY,
                applied_at timestamptz NOT NULL DEFAULT now()
            )
            """
        )
        applied = {
            row[0]
            for row in connection.execute(
                text("SELECT version FROM control.schema_migration")
            ).fetchall()
        }

        for migration_file in migration_files:
            if migration_file.name in applied:
                continue
            connection.exec_driver_sql(migration_file.read_text(encoding="utf-8"))
            connection.execute(
                text(
                    "INSERT INTO control.schema_migration (version) VALUES (:version)"
                ),
                {"version": migration_file.name},
            )


def latest_market_date(engine: Engine, instrument_code: str) -> date | None:
    with engine.connect() as connection:
        return connection.execute(
            text(
                """
                SELECT max(trading_date)
                FROM raw.market_index_daily
                WHERE instrument_code = :instrument_code
                """
            ),
            {"instrument_code": instrument_code},
        ).scalar_one()


def latest_rba_date(engine: Engine, series_code: str) -> date | None:
    with engine.connect() as connection:
        return connection.execute(
            text(
                """
                SELECT max(observation_date)
                FROM raw.rba_cash_rate_daily
                WHERE series_code = :series_code
                """
            ),
            {"series_code": series_code},
        ).scalar_one()


def market_date_bounds(engine: Engine) -> tuple[date, date, int]:
    with engine.connect() as connection:
        row = connection.execute(
            text(
                """
                SELECT
                    min(trading_date) AS first_date,
                    max(trading_date) AS last_date,
                    count(*) AS record_count
                FROM raw.market_index_daily
                """
            )
        ).one()
    if row.first_date is None or row.last_date is None:
        raise RuntimeError("Cannot transform an empty raw market dataset")
    return row.first_date, row.last_date, row.record_count


def start_pipeline_run(
    engine: Engine,
    *,
    pipeline_name: str,
    extraction_start_date: date,
    extraction_end_date: date,
    metadata: str,
) -> int:
    with engine.begin() as connection:
        return connection.execute(
            text(
                """
                INSERT INTO control.pipeline_run (
                    pipeline_name,
                    status,
                    extraction_start_date,
                    extraction_end_date,
                    run_metadata
                )
                VALUES (
                    :pipeline_name,
                    'running',
                    :extraction_start_date,
                    :extraction_end_date,
                    CAST(:metadata AS jsonb)
                )
                RETURNING pipeline_run_id
                """
            ),
            {
                "pipeline_name": pipeline_name,
                "extraction_start_date": extraction_start_date,
                "extraction_end_date": extraction_end_date,
                "metadata": metadata,
            },
        ).scalar_one()


def complete_pipeline_run(
    engine: Engine,
    *,
    pipeline_run_id: int,
    records_received: int,
    records_accepted: int,
    records_rejected: int,
) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                UPDATE control.pipeline_run
                SET status = 'succeeded',
                    records_received = :records_received,
                    records_accepted = :records_accepted,
                    records_rejected = :records_rejected,
                    finished_at = now()
                WHERE pipeline_run_id = :pipeline_run_id
                """
            ),
            {
                "pipeline_run_id": pipeline_run_id,
                "records_received": records_received,
                "records_accepted": records_accepted,
                "records_rejected": records_rejected,
            },
        )


def fail_pipeline_run(
    engine: Engine,
    *,
    pipeline_run_id: int,
    error: Exception,
    records_received: int = 0,
) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                UPDATE control.pipeline_run
                SET status = 'failed',
                    records_received = :records_received,
                    finished_at = now(),
                    error_type = :error_type,
                    error_message = :error_message
                WHERE pipeline_run_id = :pipeline_run_id
                """
            ),
            {
                "pipeline_run_id": pipeline_run_id,
                "records_received": records_received,
                "error_type": type(error).__name__,
                "error_message": str(error)[:2000],
            },
        )


def upsert_market_records(
    engine: Engine, *, pipeline_run_id: int, records: Iterable[dict[str, Any]]
) -> int:
    record_list = [dict(record, pipeline_run_id=pipeline_run_id) for record in records]
    if not record_list:
        return 0

    statement = text(
        """
        INSERT INTO raw.market_index_daily (
            instrument_code,
            trading_date,
            open_value,
            high_value,
            low_value,
            close_value,
            adjusted_close_value,
            volume,
            pipeline_run_id
        )
        VALUES (
            :instrument_code,
            :trading_date,
            :open_value,
            :high_value,
            :low_value,
            :close_value,
            :adjusted_close_value,
            :volume,
            :pipeline_run_id
        )
        ON CONFLICT (instrument_code, trading_date)
        DO UPDATE SET
            open_value = EXCLUDED.open_value,
            high_value = EXCLUDED.high_value,
            low_value = EXCLUDED.low_value,
            close_value = EXCLUDED.close_value,
            adjusted_close_value = EXCLUDED.adjusted_close_value,
            volume = EXCLUDED.volume,
            source_loaded_at = now(),
            pipeline_run_id = EXCLUDED.pipeline_run_id
        """
    )
    with engine.begin() as connection:
        connection.execute(statement, record_list)
    return len(record_list)


def insert_rejected_records(
    engine: Engine,
    *,
    pipeline_run_id: int,
    source_name: str,
    records: Iterable[dict[str, Any]],
) -> int:
    record_list = [
        {
            "pipeline_run_id": pipeline_run_id,
            "source_name": source_name,
            "reason_code": record["reason_code"],
            "reason_detail": record["reason_detail"],
            "raw_payload": record["raw_payload"],
        }
        for record in records
    ]
    if not record_list:
        return 0

    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO control.rejected_record (
                    pipeline_run_id,
                    source_name,
                    reason_code,
                    reason_detail,
                    raw_payload
                )
                VALUES (
                    :pipeline_run_id,
                    :source_name,
                    :reason_code,
                    :reason_detail,
                    CAST(:raw_payload AS jsonb)
                )
                """
            ),
            record_list,
        )
    return len(record_list)


def upsert_rba_records(
    engine: Engine, *, pipeline_run_id: int, records: Iterable[dict[str, Any]]
) -> int:
    record_list = [dict(record, pipeline_run_id=pipeline_run_id) for record in records]
    if not record_list:
        return 0

    statement = text(
        """
        INSERT INTO raw.rba_cash_rate_daily (
            series_code,
            observation_date,
            rate_percent,
            unit,
            source_publication_date,
            pipeline_run_id
        )
        VALUES (
            :series_code,
            :observation_date,
            :rate_percent,
            :unit,
            :source_publication_date,
            :pipeline_run_id
        )
        ON CONFLICT (series_code, observation_date)
        DO UPDATE SET
            rate_percent = EXCLUDED.rate_percent,
            unit = EXCLUDED.unit,
            source_publication_date = EXCLUDED.source_publication_date,
            source_loaded_at = now(),
            pipeline_run_id = EXCLUDED.pipeline_run_id
        """
    )
    with engine.begin() as connection:
        connection.execute(statement, record_list)
    return len(record_list)


def refresh_market_intelligence_daily(
    engine: Engine, *, pipeline_run_id: int
) -> tuple[int, dict[str, Any]]:
    transform_path = (
        TRANSFORMS_DIRECTORY / "refresh_market_intelligence_daily.sql"
    )
    if not transform_path.exists():
        raise RuntimeError(f"Curated transformation not found: {transform_path}")
    statement = text(transform_path.read_text(encoding="utf-8"))

    with engine.begin() as connection:
        connection.execute(
            text("DELETE FROM curated.market_intelligence_daily")
        )
        result = connection.execute(
            statement,
            {"pipeline_run_id": pipeline_run_id},
        )
        snapshot = _curated_quality_snapshot(connection)
        hard_failures: list[str] = []
        if snapshot["curated_count"] == 0:
            hard_failures.append("curated dataset is empty")
        if snapshot["latest_curated_date"] != snapshot["latest_raw_market_date"]:
            hard_failures.append("curated latest date does not match raw market data")
        if snapshot["future_macro_count"] != 0:
            hard_failures.append("curated rows contain future macro observations")
        if snapshot["recent_incomplete_metric_count"] != 0:
            hard_failures.append(
                f"{snapshot['recent_incomplete_metric_count']} recent curated rows "
                "have incomplete metrics"
            )
        if hard_failures:
            raise RuntimeError("; ".join(hard_failures))
        return result.rowcount, snapshot


def curated_quality_snapshot(engine: Engine) -> dict[str, Any]:
    with engine.connect() as connection:
        return _curated_quality_snapshot(connection)


def _curated_quality_snapshot(connection: Any) -> dict[str, Any]:
    row = connection.execute(
        text(
            """
            WITH latest AS (
                SELECT
                    max(trading_date) AS latest_curated_date
                FROM curated.market_intelligence_daily
            )
            SELECT
                count(*) AS curated_count,
                min(curated.trading_date) AS first_curated_date,
                max(curated.trading_date) AS latest_curated_date,
                (SELECT max(trading_date) FROM raw.market_index_daily)
                    AS latest_raw_market_date,
                count(*) FILTER (
                    WHERE curated.rba_cash_rate_percent IS NULL
                ) AS missing_macro_count,
                count(*) FILTER (
                    WHERE curated.trading_date >=
                        latest.latest_curated_date - INTERVAL '90 days'
                        AND (
                            curated.rolling_average_20d IS NULL
                            OR curated.return_20d_percent IS NULL
                            OR curated.realized_volatility_14d_percent IS NULL
                        )
                ) AS recent_incomplete_metric_count,
                count(*) FILTER (
                    WHERE curated.rba_observation_date >
                        curated.trading_date
                ) AS future_macro_count
            FROM curated.market_intelligence_daily AS curated
            CROSS JOIN latest
            """
        )
    ).one()
    return dict(row._mapping)


def pipeline_run_result(engine: Engine, pipeline_run_id: int) -> dict[str, Any]:
    with engine.connect() as connection:
        row = connection.execute(
            text(
                """
                SELECT
                    pipeline_run_id,
                    pipeline_name,
                    status,
                    records_received,
                    records_accepted,
                    records_rejected,
                    started_at,
                    finished_at,
                    error_type,
                    error_message
                FROM control.pipeline_run
                WHERE pipeline_run_id = :pipeline_run_id
                """
            ),
            {"pipeline_run_id": pipeline_run_id},
        ).one()
    return dict(row._mapping)


@contextmanager
def data_refresh_lock(engine: Engine):
    with engine.connect() as connection:
        acquired = bool(
            connection.execute(
                text("SELECT pg_try_advisory_lock(:lock_id)"),
                {"lock_id": REFRESH_ADVISORY_LOCK_ID},
            ).scalar_one()
        )
        connection.commit()
        if not acquired:
            raise RefreshAlreadyRunningError(
                "Another data refresh is already running"
            )
        try:
            yield
        finally:
            connection.execute(
                text("SELECT pg_advisory_unlock(:lock_id)"),
                {"lock_id": REFRESH_ADVISORY_LOCK_ID},
            )
            connection.commit()


class RefreshAlreadyRunningError(RuntimeError):
    pass


def insert_quality_result(
    engine: Engine,
    *,
    pipeline_run_id: int,
    check_name: str,
    status: str,
    records_checked: int,
    records_failed: int,
    details: str,
) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO control.data_quality_result (
                    pipeline_run_id,
                    check_name,
                    status,
                    records_checked,
                    records_failed,
                    details
                )
                VALUES (
                    :pipeline_run_id,
                    :check_name,
                    :status,
                    :records_checked,
                    :records_failed,
                    CAST(:details AS jsonb)
                )
                """
            ),
            {
                "pipeline_run_id": pipeline_run_id,
                "check_name": check_name,
                "status": status,
                "records_checked": records_checked,
                "records_failed": records_failed,
                "details": details,
            },
        )
