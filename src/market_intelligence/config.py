from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    database_url: str
    market_symbol: str = "^AXJO"
    market_instrument_code: str = "ASX200"
    market_history_years: int = 5
    market_incremental_overlap_days: int = 7
    market_timezone: str = "Australia/Sydney"
    rba_f1_url: str = "https://www.rba.gov.au/statistics/tables/csv/f1-data.csv"
    rba_series_code: str = "FIRMMCRID"
    rba_history_years: int = 5
    rba_incremental_overlap_days: int = 7
    log_level: str = "INFO"

    @classmethod
    def from_environment(cls) -> Settings:
        load_dotenv()
        database_url = os.getenv("DATABASE_URL")
        if not database_url:
            raise ValueError(
                "DATABASE_URL is required. Copy .env.example to .env for local development."
            )

        history_years = _positive_int("MARKET_HISTORY_YEARS", default=5)
        overlap_days = _nonnegative_int("MARKET_INCREMENTAL_OVERLAP_DAYS", default=7)
        rba_history_years = _positive_int("RBA_HISTORY_YEARS", default=5)
        rba_overlap_days = _nonnegative_int("RBA_INCREMENTAL_OVERLAP_DAYS", default=7)

        return cls(
            database_url=database_url,
            market_symbol=os.getenv("MARKET_SYMBOL", "^AXJO"),
            market_instrument_code=os.getenv("MARKET_INSTRUMENT_CODE", "ASX200"),
            market_history_years=history_years,
            market_incremental_overlap_days=overlap_days,
            market_timezone=os.getenv("MARKET_TIMEZONE", "Australia/Sydney"),
            rba_f1_url=os.getenv(
                "RBA_F1_URL",
                "https://www.rba.gov.au/statistics/tables/csv/f1-data.csv",
            ),
            rba_series_code=os.getenv("RBA_SERIES_CODE", "FIRMMCRID"),
            rba_history_years=rba_history_years,
            rba_incremental_overlap_days=rba_overlap_days,
            log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        )


def _positive_int(name: str, default: int) -> int:
    value = int(os.getenv(name, str(default)))
    if value <= 0:
        raise ValueError(f"{name} must be greater than zero")
    return value


def _nonnegative_int(name: str, default: int) -> int:
    value = int(os.getenv(name, str(default)))
    if value < 0:
        raise ValueError(f"{name} must be zero or greater")
    return value
