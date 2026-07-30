from __future__ import annotations

import json
import logging
from datetime import date, timedelta

from market_intelligence.config import Settings
from market_intelligence.database import (
    complete_pipeline_run,
    create_database_engine,
    fail_pipeline_run,
    insert_quality_result,
    insert_rejected_records,
    latest_market_date,
    latest_rba_date,
    start_pipeline_run,
    upsert_market_records,
    upsert_rba_records,
)
from market_intelligence.ingestion.rba import (
    fetch_f1_csv,
    normalize_interbank_cash_rate,
)
from market_intelligence.ingestion.yahoo import (
    fetch_daily_history,
    normalize_daily_history,
)

LOGGER = logging.getLogger(__name__)
PIPELINE_NAME = "yahoo_market_index_daily"
RBA_PIPELINE_NAME = "rba_interbank_cash_rate_daily"


def run_yahoo_pipeline(settings: Settings, *, as_of_date: date) -> int:
    engine = create_database_engine(settings.database_url)
    history_floor = _subtract_years(as_of_date, settings.market_history_years)
    current_latest_date = latest_market_date(engine, settings.market_instrument_code)
    extraction_start_date = history_floor
    if current_latest_date is not None:
        extraction_start_date = max(
            history_floor,
            current_latest_date
            - timedelta(days=settings.market_incremental_overlap_days),
        )

    pipeline_run_id = start_pipeline_run(
        engine,
        pipeline_name=PIPELINE_NAME,
        extraction_start_date=extraction_start_date,
        extraction_end_date=as_of_date,
        metadata=json.dumps(
            {
                "source": "yahoo_finance",
                "symbol": settings.market_symbol,
                "instrument_code": settings.market_instrument_code,
                "history_years": settings.market_history_years,
                "incremental_overlap_days": settings.market_incremental_overlap_days,
                "timezone": settings.market_timezone,
            }
        ),
    )
    LOGGER.info(
        "Started Yahoo Finance ingestion",
        extra={"pipeline_run_id": pipeline_run_id, "source": "yahoo_finance"},
    )

    records_received = 0
    try:
        source_data = fetch_daily_history(
            symbol=settings.market_symbol,
            start_date=extraction_start_date,
            end_date=as_of_date,
        )
        records_received = len(source_data)
        result = normalize_daily_history(
            source_data,
            symbol=settings.market_symbol,
            instrument_code=settings.market_instrument_code,
            timezone_name=settings.market_timezone,
        )

        insert_rejected_records(
            engine,
            pipeline_run_id=pipeline_run_id,
            source_name="yahoo_finance",
            records=result.rejected_records,
        )
        upsert_market_records(
            engine,
            pipeline_run_id=pipeline_run_id,
            records=result.records,
        )

        rejected_count = len(result.rejected_records)
        quality_status = "passed" if rejected_count == 0 else "warning"
        insert_quality_result(
            engine,
            pipeline_run_id=pipeline_run_id,
            check_name="market_record_validity",
            status=quality_status,
            records_checked=result.received_count,
            records_failed=rejected_count,
            details=json.dumps(
                {
                    "duplicate_business_keys": result.duplicate_count,
                    "accepted_records": len(result.records),
                }
            ),
        )
        complete_pipeline_run(
            engine,
            pipeline_run_id=pipeline_run_id,
            records_received=result.received_count,
            records_accepted=len(result.records),
            records_rejected=rejected_count,
        )
        LOGGER.info(
            "Completed Yahoo Finance ingestion",
            extra={
                "pipeline_run_id": pipeline_run_id,
                "source": "yahoo_finance",
                "records": len(result.records),
            },
        )
        return pipeline_run_id
    except Exception as error:
        fail_pipeline_run(
            engine,
            pipeline_run_id=pipeline_run_id,
            error=error,
            records_received=records_received,
        )
        LOGGER.exception(
            "Yahoo Finance ingestion failed",
            extra={"pipeline_run_id": pipeline_run_id, "source": "yahoo_finance"},
        )
        raise
    finally:
        engine.dispose()


def run_rba_pipeline(settings: Settings, *, as_of_date: date) -> int:
    engine = create_database_engine(settings.database_url)
    history_floor = _subtract_years(as_of_date, settings.rba_history_years)
    current_latest_date = latest_rba_date(engine, settings.rba_series_code)
    extraction_start_date = history_floor
    if current_latest_date is not None:
        extraction_start_date = max(
            history_floor,
            current_latest_date
            - timedelta(days=settings.rba_incremental_overlap_days),
        )

    pipeline_run_id = start_pipeline_run(
        engine,
        pipeline_name=RBA_PIPELINE_NAME,
        extraction_start_date=extraction_start_date,
        extraction_end_date=as_of_date,
        metadata=json.dumps(
            {
                "source": "reserve_bank_of_australia",
                "series_code": settings.rba_series_code,
                "source_url": settings.rba_f1_url,
                "history_years": settings.rba_history_years,
                "incremental_overlap_days": settings.rba_incremental_overlap_days,
            }
        ),
    )
    LOGGER.info(
        "Started RBA cash-rate ingestion",
        extra={
            "pipeline_run_id": pipeline_run_id,
            "source": "reserve_bank_of_australia",
        },
    )

    records_received = 0
    try:
        csv_text = fetch_f1_csv(url=settings.rba_f1_url)
        result = normalize_interbank_cash_rate(
            csv_text,
            series_code=settings.rba_series_code,
            start_date=extraction_start_date,
            end_date=as_of_date,
        )
        records_received = result.received_count

        insert_rejected_records(
            engine,
            pipeline_run_id=pipeline_run_id,
            source_name="reserve_bank_of_australia",
            records=result.rejected_records,
        )
        upsert_rba_records(
            engine,
            pipeline_run_id=pipeline_run_id,
            records=result.records,
        )

        rejected_count = len(result.rejected_records)
        quality_status = "passed" if rejected_count == 0 else "warning"
        insert_quality_result(
            engine,
            pipeline_run_id=pipeline_run_id,
            check_name="rba_cash_rate_record_validity",
            status=quality_status,
            records_checked=result.received_count,
            records_failed=rejected_count,
            details=json.dumps(
                {
                    "duplicate_business_keys": result.duplicate_count,
                    "accepted_records": len(result.records),
                    "series_code": settings.rba_series_code,
                }
            ),
        )
        complete_pipeline_run(
            engine,
            pipeline_run_id=pipeline_run_id,
            records_received=result.received_count,
            records_accepted=len(result.records),
            records_rejected=rejected_count,
        )
        LOGGER.info(
            "Completed RBA cash-rate ingestion",
            extra={
                "pipeline_run_id": pipeline_run_id,
                "source": "reserve_bank_of_australia",
                "records": len(result.records),
            },
        )
        return pipeline_run_id
    except Exception as error:
        fail_pipeline_run(
            engine,
            pipeline_run_id=pipeline_run_id,
            error=error,
            records_received=records_received,
        )
        LOGGER.exception(
            "RBA cash-rate ingestion failed",
            extra={
                "pipeline_run_id": pipeline_run_id,
                "source": "reserve_bank_of_australia",
            },
        )
        raise
    finally:
        engine.dispose()


def _subtract_years(value: date, years: int) -> date:
    try:
        return value.replace(year=value.year - years)
    except ValueError:
        # 29 February maps to 28 February in a non-leap target year.
        return value.replace(month=2, day=28, year=value.year - years)
