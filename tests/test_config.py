from __future__ import annotations

import pytest

import market_intelligence.config as config
from market_intelligence.config import Settings


def test_settings_require_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "load_dotenv", lambda: False)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(ValueError, match="DATABASE_URL is required"):
        Settings.from_environment()


def test_settings_default_to_five_years(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "load_dotenv", lambda: False)
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://example")
    monkeypatch.delenv("MARKET_HISTORY_YEARS", raising=False)

    settings = Settings.from_environment()

    assert settings.market_history_years == 5
