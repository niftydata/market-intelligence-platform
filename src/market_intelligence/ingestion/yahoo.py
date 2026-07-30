from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf

REQUIRED_COLUMNS = ("Open", "High", "Low", "Close")


class YahooSourceError(RuntimeError):
    """Base error for Yahoo Finance ingestion."""


class YahooEmptyResponseError(YahooSourceError):
    """Raised when Yahoo Finance returns no records."""


class YahooSchemaError(YahooSourceError):
    """Raised when Yahoo Finance returns an unexpected schema."""


@dataclass(frozen=True)
class NormalizationResult:
    received_count: int
    records: list[dict[str, Any]]
    rejected_records: list[dict[str, Any]]
    duplicate_count: int


def fetch_daily_history(
    *, symbol: str, start_date: date, end_date: date
) -> pd.DataFrame:
    if start_date > end_date:
        raise ValueError("start_date cannot be after end_date")

    # yfinance treats end as exclusive, so include the requested final date.
    exclusive_end = end_date + timedelta(days=1)
    data = yf.download(
        tickers=symbol,
        start=start_date.isoformat(),
        end=exclusive_end.isoformat(),
        interval="1d",
        auto_adjust=False,
        actions=False,
        progress=False,
        threads=False,
        timeout=20,
    )
    if data.empty:
        raise YahooEmptyResponseError(
            f"Yahoo Finance returned no rows for {symbol} from "
            f"{start_date} through {end_date}"
        )
    return data


def normalize_daily_history(
    data: pd.DataFrame,
    *,
    symbol: str,
    instrument_code: str,
    timezone_name: str,
) -> NormalizationResult:
    frame = _flatten_yfinance_columns(data.copy(), symbol)
    missing_columns = sorted(set(REQUIRED_COLUMNS) - set(frame.columns))
    if missing_columns:
        raise YahooSchemaError(
            f"Yahoo Finance response is missing required columns: {missing_columns}"
        )

    received_count = len(frame)
    frame = frame.reset_index()
    date_column = "Date" if "Date" in frame.columns else frame.columns[0]
    duplicate_mask = frame.duplicated(subset=[date_column], keep="last")
    duplicate_count = int(duplicate_mask.sum())

    rejected_records: list[dict[str, Any]] = []
    for _, duplicate in frame.loc[duplicate_mask].iterrows():
        rejected_records.append(
            _rejection(
                "duplicate_business_key",
                "A duplicate source trading date was superseded by the last record.",
                duplicate.to_dict(),
            )
        )
    frame = frame.loc[~duplicate_mask].copy()

    records: list[dict[str, Any]] = []
    timezone = ZoneInfo(timezone_name)
    for _, row in frame.iterrows():
        payload = row.to_dict()
        try:
            record = _normalize_row(
                row,
                date_column=date_column,
                instrument_code=instrument_code,
                timezone=timezone,
            )
            _validate_record(record)
        except (TypeError, ValueError) as error:
            rejected_records.append(
                _rejection("invalid_market_record", str(error), payload)
            )
            continue
        records.append(record)

    if not records:
        raise YahooSourceError("All Yahoo Finance records failed validation")

    return NormalizationResult(
        received_count=received_count,
        records=records,
        rejected_records=rejected_records,
        duplicate_count=duplicate_count,
    )


def _flatten_yfinance_columns(frame: pd.DataFrame, symbol: str) -> pd.DataFrame:
    if not isinstance(frame.columns, pd.MultiIndex):
        return frame

    for level in range(frame.columns.nlevels):
        level_values = frame.columns.get_level_values(level)
        if symbol in level_values:
            return frame.xs(symbol, axis=1, level=level, drop_level=True)

    raise YahooSchemaError(
        f"Yahoo Finance returned multi-level columns without expected symbol {symbol}"
    )


def _normalize_row(
    row: pd.Series,
    *,
    date_column: str,
    instrument_code: str,
    timezone: ZoneInfo,
) -> dict[str, Any]:
    timestamp = pd.Timestamp(row[date_column])
    if pd.isna(timestamp):
        raise ValueError("Trading date is missing")
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize(timezone)
    else:
        timestamp = timestamp.tz_convert(timezone)

    adjusted_close = _optional_decimal(row.get("Adj Close"))
    volume = _optional_integer(row.get("Volume"))

    return {
        "instrument_code": instrument_code,
        "trading_date": timestamp.date(),
        "open_value": _required_decimal(row["Open"], "Open"),
        "high_value": _required_decimal(row["High"], "High"),
        "low_value": _required_decimal(row["Low"], "Low"),
        "close_value": _required_decimal(row["Close"], "Close"),
        "adjusted_close_value": adjusted_close,
        "volume": volume,
    }


def _validate_record(record: dict[str, Any]) -> None:
    for field in ("open_value", "high_value", "low_value", "close_value"):
        if record[field] <= 0:
            raise ValueError(f"{field} must be positive")

    high = record["high_value"]
    low = record["low_value"]
    if high < low:
        raise ValueError("High price cannot be below low price")
    if high < max(record["open_value"], record["close_value"]):
        raise ValueError("High price cannot be below open or close price")
    if low > min(record["open_value"], record["close_value"]):
        raise ValueError("Low price cannot be above open or close price")
    if record["volume"] is not None and record["volume"] < 0:
        raise ValueError("Volume cannot be negative")


def _required_decimal(value: Any, field_name: str) -> Decimal:
    if pd.isna(value):
        raise ValueError(f"{field_name} is missing")
    return Decimal(str(value))


def _optional_decimal(value: Any) -> Decimal | None:
    if value is None or pd.isna(value):
        return None
    return Decimal(str(value))


def _optional_integer(value: Any) -> int | None:
    if value is None or pd.isna(value):
        return None
    return int(value)


def _rejection(reason_code: str, reason_detail: str, payload: dict[str, Any]) -> dict[str, Any]:
    serializable_payload = {
        str(key): _json_safe(value) for key, value in payload.items()
    }
    return {
        "reason_code": reason_code,
        "reason_detail": reason_detail,
        "raw_payload": json.dumps(serializable_payload),
    }


def _json_safe(value: Any) -> Any:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, (date, datetime, pd.Timestamp)):
        return value.isoformat()
    if hasattr(value, "item"):
        return value.item()
    return value
