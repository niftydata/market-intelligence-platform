from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from market_intelligence.ingestion.yahoo import (
    YahooSchemaError,
    normalize_daily_history,
)


def test_normalizes_current_yfinance_multi_index_shape() -> None:
    columns = pd.MultiIndex.from_product(
        [["Open", "High", "Low", "Close", "Adj Close", "Volume"], ["^AXJO"]],
        names=["Price", "Ticker"],
    )
    frame = pd.DataFrame(
        [[8000.0, 8100.0, 7950.0, 8050.0, 8050.0, 123456.0]],
        index=pd.DatetimeIndex(["2026-07-29"], name="Date"),
        columns=columns,
    )

    result = normalize_daily_history(
        frame,
        symbol="^AXJO",
        instrument_code="ASX200",
        timezone_name="Australia/Sydney",
    )

    assert result.received_count == 1
    assert result.rejected_records == []
    assert result.records[0]["trading_date"] == date(2026, 7, 29)
    assert result.records[0]["volume"] == 123456


def test_rejects_invalid_ohlc_without_silently_dropping_record() -> None:
    frame = pd.DataFrame(
        {
            "Open": [8000.0, 8000.0],
            "High": [8100.0, 7900.0],
            "Low": [7950.0, 7950.0],
            "Close": [8050.0, 8050.0],
            "Adj Close": [8050.0, 8050.0],
            "Volume": [123456.0, 123456.0],
        },
        index=pd.DatetimeIndex(["2026-07-28", "2026-07-29"], name="Date"),
    )

    result = normalize_daily_history(
        frame,
        symbol="^AXJO",
        instrument_code="ASX200",
        timezone_name="Australia/Sydney",
    )

    assert len(result.records) == 1
    assert len(result.rejected_records) == 1
    assert result.rejected_records[0]["reason_code"] == "invalid_market_record"


def test_rejects_missing_required_schema() -> None:
    frame = pd.DataFrame(
        {"Open": [8000.0], "High": [8100.0], "Low": [7950.0]},
        index=pd.DatetimeIndex(["2026-07-29"], name="Date"),
    )

    with pytest.raises(YahooSchemaError, match="Close"):
        normalize_daily_history(
            frame,
            symbol="^AXJO",
            instrument_code="ASX200",
            timezone_name="Australia/Sydney",
        )
