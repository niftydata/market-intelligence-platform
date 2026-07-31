from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from market_intelligence.config import Settings
from market_intelligence.database import (
    complete_pipeline_run,
    create_database_engine,
    data_refresh_lock,
    fail_pipeline_run,
    insert_quality_result,
    insert_rejected_records,
    latest_market_date,
    latest_rba_date,
    market_date_bounds,
    pipeline_run_result,
    refresh_market_intelligence_daily,
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
CURATED_PIPELINE_NAME = "curated_market_intelligence_daily"
MAX_FAILURE_SUMMARY_LENGTH = 250


@dataclass(frozen=True)
class RefreshStageResult:
    stage: str
    status: str
    records_received: int
    records_accepted: int
    records_rejected: int
    pipeline_run_id: int | None
    failure_summary: str | None = None


@dataclass(frozen=True)
class FullRefreshResult:
    stages: tuple[RefreshStageResult, ...]

    @property
    def succeeded(self) -> bool:
        return all(stage.status == "succeeded" for stage in self.stages)


class PipelineExecutionError(RuntimeError):
    def __init__(self, pipeline_name: str, pipeline_run_id: int) -> None:
        self.pipeline_name = pipeline_name
        self.pipeline_run_id = pipeline_run_id
        super().__init__(f"Pipeline failed: {pipeline_name}")


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
        raise PipelineExecutionError(PIPELINE_NAME, pipeline_run_id) from error
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
        raise PipelineExecutionError(RBA_PIPELINE_NAME, pipeline_run_id) from error
    finally:
        engine.dispose()


def run_curated_pipeline(settings: Settings) -> int:
    engine = create_database_engine(settings.database_url)
    first_market_date, latest_market_date, raw_record_count = market_date_bounds(engine)
    pipeline_run_id = start_pipeline_run(
        engine,
        pipeline_name=CURATED_PIPELINE_NAME,
        extraction_start_date=first_market_date,
        extraction_end_date=latest_market_date,
        metadata=json.dumps(
            {
                "grain": "one row per ASX200 trading date",
                "macro_alignment": "latest RBA observation on or before trading date",
                "history_window": "five years",
                "metric_contract": "docs/metric_definitions.md",
            }
        ),
    )
    LOGGER.info(
        "Started curated market-intelligence transformation",
        extra={"pipeline_run_id": pipeline_run_id, "source": "curated"},
    )

    try:
        refreshed_count, snapshot = refresh_market_intelligence_daily(
            engine,
            pipeline_run_id=pipeline_run_id,
        )

        macro_missing = int(snapshot["missing_macro_count"])
        insert_quality_result(
            engine,
            pipeline_run_id=pipeline_run_id,
            check_name="curated_macro_alignment",
            status="passed" if macro_missing == 0 else "warning",
            records_checked=int(snapshot["curated_count"]),
            records_failed=macro_missing,
            details=json.dumps(
                {
                    "alignment_rule": (
                        "latest RBA observation on or before market trading date"
                    ),
                    "future_macro_observations": snapshot["future_macro_count"],
                }
            ),
        )

        incomplete_metrics = int(snapshot["recent_incomplete_metric_count"])
        insert_quality_result(
            engine,
            pipeline_run_id=pipeline_run_id,
            check_name="curated_recent_metric_completeness",
            status="passed" if incomplete_metrics == 0 else "failed",
            records_checked=int(snapshot["curated_count"]),
            records_failed=incomplete_metrics,
            details=json.dumps({"window": "latest 90 calendar days"}),
        )
        complete_pipeline_run(
            engine,
            pipeline_run_id=pipeline_run_id,
            records_received=raw_record_count,
            records_accepted=refreshed_count,
            records_rejected=0,
        )
        LOGGER.info(
            "Completed curated market-intelligence transformation",
            extra={
                "pipeline_run_id": pipeline_run_id,
                "source": "curated",
                "records": refreshed_count,
            },
        )
        return pipeline_run_id
    except Exception as error:
        fail_pipeline_run(
            engine,
            pipeline_run_id=pipeline_run_id,
            error=error,
            records_received=raw_record_count,
        )
        LOGGER.exception(
            "Curated market-intelligence transformation failed",
            extra={"pipeline_run_id": pipeline_run_id, "source": "curated"},
        )
        raise PipelineExecutionError(CURATED_PIPELINE_NAME, pipeline_run_id) from error
    finally:
        engine.dispose()


def _subtract_years(value: date, years: int) -> date:
    try:
        return value.replace(year=value.year - years)
    except ValueError:
        # 29 February maps to 28 February in a non-leap target year.
        return value.replace(month=2, day=28, year=value.year - years)


def run_full_refresh(settings: Settings, *, as_of_date: date) -> FullRefreshResult:
    engine = create_database_engine(settings.database_url)
    stages: list[RefreshStageResult] = []
    source_succeeded = True
    try:
        with data_refresh_lock(engine):
            source_pipelines: tuple[
                tuple[str, Callable[..., int]],
                ...,
            ] = (
                ("Yahoo Finance", run_yahoo_pipeline),
                ("RBA cash rate", run_rba_pipeline),
            )
            for stage_name, pipeline in source_pipelines:
                stage = _execute_refresh_stage(
                    stage_name,
                    engine,
                    lambda pipeline=pipeline: pipeline(
                        settings,
                        as_of_date=as_of_date,
                    ),
                )
                stages.append(stage)
                source_succeeded = source_succeeded and stage.status == "succeeded"

            if source_succeeded:
                stages.append(
                    _execute_refresh_stage(
                        "Curated analytics",
                        engine,
                        lambda: run_curated_pipeline(settings),
                    )
                )
            else:
                stages.append(
                    RefreshStageResult(
                        stage="Curated analytics",
                        status="skipped",
                        records_received=0,
                        records_accepted=0,
                        records_rejected=0,
                        pipeline_run_id=None,
                        failure_summary=(
                            "Curated analytics was skipped because a source "
                            "refresh failed."
                        ),
                    )
                )
    finally:
        engine.dispose()
    return FullRefreshResult(stages=tuple(stages))


def _execute_refresh_stage(
    stage_name: str,
    engine: Any,
    pipeline: Callable[[], int],
) -> RefreshStageResult:
    try:
        pipeline_run_id = pipeline()
    except PipelineExecutionError as error:
        return _refresh_stage_from_run(
            stage_name,
            pipeline_run_result(engine, error.pipeline_run_id),
        )
    except Exception:
        LOGGER.exception("Refresh stage failed before a pipeline run was created")
        return RefreshStageResult(
            stage=stage_name,
            status="failed",
            records_received=0,
            records_accepted=0,
            records_rejected=0,
            pipeline_run_id=None,
            failure_summary=(
                f"{stage_name} failed before a pipeline run could be created."
            ),
        )
    return _refresh_stage_from_run(
        stage_name,
        pipeline_run_result(engine, pipeline_run_id),
    )


def _refresh_stage_from_run(
    stage_name: str,
    run: dict[str, Any],
) -> RefreshStageResult:
    return RefreshStageResult(
        stage=stage_name,
        status=str(run["status"]),
        records_received=int(run["records_received"]),
        records_accepted=int(run["records_accepted"]),
        records_rejected=int(run["records_rejected"]),
        pipeline_run_id=int(run["pipeline_run_id"]),
        failure_summary=_safe_failure_summary(stage_name, run),
    )


def _safe_failure_summary(
    stage_name: str,
    run: dict[str, Any],
) -> str | None:
    if run["status"] != "failed":
        return None

    raw_detail = str(
        run.get("error_message")
        or run.get("error_type")
        or "the refresh encountered an unexpected error"
    )
    detail = re.sub(
        r"(?i)\b(?:postgres(?:ql)?(?:\+\w+)?://)\S+",
        "[database connection redacted]",
        raw_detail,
    )
    detail = re.sub(r"(?i)\bhttps?://\S+", "[upstream endpoint]", detail)
    detail = re.sub(
        r"(?i)\b(password|token|secret)\s*[=:]\s*[^\s,;.!?]+",
        r"\1=[redacted]",
        detail,
    )
    detail = re.sub(r"\s+", " ", detail).strip()
    detail = re.split(r"(?<=[.!?])\s+", detail, maxsplit=1)[0]
    detail = detail.rstrip(".!?")

    summary = f"{stage_name} failed: {detail}"
    if len(summary) >= MAX_FAILURE_SUMMARY_LENGTH:
        summary = summary[: MAX_FAILURE_SUMMARY_LENGTH - 3].rstrip() + "..."
    else:
        summary += "."
    return summary
