from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from market_intelligence.ingestion.rba import (
    RbaSchemaError,
    normalize_interbank_cash_rate,
)

CSV_FIXTURE = """F1 INTEREST RATES AND YIELDS - MONEY MARKET
Title,Cash Rate Target,Interbank Overnight Cash Rate
Frequency,Daily,Daily
Units,Per cent,Per cent
Source,RBA,RBA
Publication date,30-Jul-2026,30-Jul-2026
Series ID,FIRMMCRTD,FIRMMCRID
28-Jul-2026,3.60,3.60
29-Jul-2026,3.60,3.60
30-Jul-2026,3.60,
"""


def test_normalizes_cash_rate_and_retains_blank_as_rejection() -> None:
    result = normalize_interbank_cash_rate(
        CSV_FIXTURE,
        series_code="FIRMMCRID",
        start_date=date(2026, 7, 28),
        end_date=date(2026, 7, 30),
    )

    assert result.received_count == 3
    assert len(result.records) == 2
    assert result.records[0]["rate_percent"] == Decimal("3.60")
    assert result.records[0]["source_publication_date"] == date(2026, 7, 30)
    assert len(result.rejected_records) == 1
    assert result.rejected_records[0]["reason_code"] == "missing_series_value"


def test_filters_to_requested_window() -> None:
    result = normalize_interbank_cash_rate(
        CSV_FIXTURE,
        series_code="FIRMMCRID",
        start_date=date(2026, 7, 29),
        end_date=date(2026, 7, 29),
    )

    assert result.received_count == 1
    assert result.records[0]["observation_date"] == date(2026, 7, 29)


def test_fails_when_series_contract_changes() -> None:
    with pytest.raises(RbaSchemaError, match="FIRMMCRID"):
        normalize_interbank_cash_rate(
            CSV_FIXTURE.replace("FIRMMCRID", "RENAMED_SERIES"),
            series_code="FIRMMCRID",
            start_date=date(2026, 7, 28),
            end_date=date(2026, 7, 30),
        )
