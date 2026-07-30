from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


class RbaSourceError(RuntimeError):
    """Base error for RBA ingestion."""


class RbaEmptyResponseError(RbaSourceError):
    """Raised when the RBA returns no usable content."""


class RbaSchemaError(RbaSourceError):
    """Raised when the RBA F1 contract changes unexpectedly."""


@dataclass(frozen=True)
class RbaNormalizationResult:
    received_count: int
    records: list[dict[str, Any]]
    rejected_records: list[dict[str, Any]]
    duplicate_count: int


def fetch_f1_csv(*, url: str) -> str:
    retry = Retry(
        total=3,
        backoff_factor=0.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
    )
    with requests.Session() as session:
        session.mount("https://", HTTPAdapter(max_retries=retry))
        response = session.get(
            url,
            timeout=(5, 30),
            headers={"User-Agent": "market-intelligence-platform/0.1"},
        )
        response.raise_for_status()
        if not response.content:
            raise RbaEmptyResponseError("RBA F1 response was empty")
        return response.content.decode("utf-8-sig")


def normalize_interbank_cash_rate(
    csv_text: str,
    *,
    series_code: str,
    start_date: date,
    end_date: date,
) -> RbaNormalizationResult:
    rows = list(csv.reader(io.StringIO(csv_text)))
    if not rows:
        raise RbaEmptyResponseError("RBA F1 CSV contained no rows")

    metadata = _metadata_rows(rows)
    series_row = metadata.get("Series ID")
    if not series_row or series_code not in series_row:
        raise RbaSchemaError(f"RBA F1 CSV does not contain series {series_code}")
    series_column = series_row.index(series_code)

    _validate_series_metadata(metadata, series_column)
    publication_date = _parse_publication_date(metadata, series_column)
    data_start_index = rows.index(series_row) + 1

    candidates: list[dict[str, Any]] = []
    rejected_records: list[dict[str, Any]] = []
    for row in rows[data_start_index:]:
        if not row or not row[0].strip():
            continue
        try:
            observation_date = datetime.strptime(row[0].strip(), "%d-%b-%Y").date()
        except ValueError as error:
            raise RbaSchemaError(
                f"Unexpected RBA observation date value: {row[0]!r}"
            ) from error
        if observation_date < start_date or observation_date > end_date:
            continue

        raw_value = row[series_column].strip() if len(row) > series_column else ""
        payload = {
            "series_code": series_code,
            "observation_date": observation_date.isoformat(),
            "raw_value": raw_value or None,
        }
        if not raw_value:
            rejected_records.append(
                _rejection(
                    "missing_series_value",
                    "The F1 row exists but the Interbank Overnight Cash Rate is blank.",
                    payload,
                )
            )
            continue

        try:
            rate_percent = Decimal(raw_value)
        except InvalidOperation:
            rejected_records.append(
                _rejection(
                    "invalid_numeric_value",
                    f"Cash-rate value is not numeric: {raw_value!r}",
                    payload,
                )
            )
            continue
        if rate_percent < 0 or rate_percent > 100:
            rejected_records.append(
                _rejection(
                    "rate_out_of_range",
                    "Cash-rate value must be between 0 and 100 per cent.",
                    payload,
                )
            )
            continue

        candidates.append(
            {
                "series_code": series_code,
                "observation_date": observation_date,
                "rate_percent": rate_percent,
                "unit": "Per cent",
                "source_publication_date": publication_date,
            }
        )

    received_count = len(candidates) + len(rejected_records)
    if received_count == 0:
        raise RbaEmptyResponseError(
            f"RBA F1 contained no {series_code} observations from "
            f"{start_date} through {end_date}"
        )

    records_by_date: dict[date, dict[str, Any]] = {}
    duplicate_count = 0
    for record in candidates:
        observation_date = record["observation_date"]
        if observation_date in records_by_date:
            duplicate_count += 1
            rejected_records.append(
                _rejection(
                    "duplicate_business_key",
                    "A duplicate observation date was superseded by the last record.",
                    {
                        "series_code": series_code,
                        "observation_date": observation_date.isoformat(),
                        "rate_percent": str(record["rate_percent"]),
                    },
                )
            )
        records_by_date[observation_date] = record

    records = list(records_by_date.values())
    if not records:
        raise RbaSourceError("All RBA cash-rate records failed validation")

    return RbaNormalizationResult(
        received_count=received_count,
        records=records,
        rejected_records=rejected_records,
        duplicate_count=duplicate_count,
    )


def _metadata_rows(rows: list[list[str]]) -> dict[str, list[str]]:
    labels = {"Title", "Frequency", "Units", "Source", "Publication date", "Series ID"}
    return {row[0]: row for row in rows if row and row[0] in labels}


def _validate_series_metadata(
    metadata: dict[str, list[str]], series_column: int
) -> None:
    expected = {
        "Title": "Interbank Overnight Cash Rate",
        "Frequency": "Daily",
        "Units": "Per cent",
        "Source": "RBA",
    }
    for label, expected_value in expected.items():
        row = metadata.get(label)
        actual_value = row[series_column].strip() if row and len(row) > series_column else None
        if actual_value != expected_value:
            raise RbaSchemaError(
                f"Unexpected {label} for {expected['Title']}: "
                f"expected {expected_value!r}, received {actual_value!r}"
            )


def _parse_publication_date(
    metadata: dict[str, list[str]], series_column: int
) -> date | None:
    row = metadata.get("Publication date")
    raw_value = row[series_column].strip() if row and len(row) > series_column else ""
    if not raw_value:
        return None
    try:
        return datetime.strptime(raw_value, "%d-%b-%Y").date()
    except ValueError as error:
        raise RbaSchemaError(
            f"Unexpected RBA publication date value: {raw_value!r}"
        ) from error


def _rejection(reason_code: str, reason_detail: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "reason_code": reason_code,
        "reason_detail": reason_detail,
        "raw_payload": json.dumps(payload),
    }
