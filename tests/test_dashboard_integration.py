from __future__ import annotations

import os
from datetime import date
from pathlib import Path

import pytest

from market_intelligence.dashboard.data import load_market_events
from market_intelligence.database import create_database_engine

INTEGRATION_DATABASE_URL = os.getenv("INTEGRATION_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not INTEGRATION_DATABASE_URL,
    reason="INTEGRATION_DATABASE_URL is not configured",
)


def test_external_events_align_to_asx_sessions() -> None:
    engine = create_database_engine(INTEGRATION_DATABASE_URL)
    try:
        events = load_market_events(
            engine,
            window_start_date=date(2023, 3, 1),
            window_end_date=date(2023, 3, 31),
        )
    finally:
        engine.dispose()

    svb = events.loc[events["short_label"] == "US regional banking stress"].iloc[0]
    assert svb["event_date"].date() == date(2023, 3, 10)
    assert svb["plot_date"].date() == date(2023, 3, 13)
    assert svb["alignment_method"] == "Timestamp aligned to first ASX close after event"


def test_dashboard_renders_without_runtime_exceptions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from streamlit.testing.v1 import AppTest

    from market_intelligence.dashboard.auth import create_password_hash

    monkeypatch.setenv("DATABASE_URL", INTEGRATION_DATABASE_URL)
    monkeypatch.setenv("ENABLE_AI_ASSISTANT", "true")
    monkeypatch.setenv("AI_DEMO_USERNAME", "macquarie")
    monkeypatch.setenv(
        "AI_DEMO_PASSWORD_HASH",
        create_password_hash(
            "test-password",
            salt=b"0123456789abcdef",
            iterations=1_000,
        ),
    )
    monkeypatch.setenv(
        "FOUNDRY_AGENT_ENDPOINT",
        (
            "https://example.services.ai.azure.com/api/projects/example/"
            "agents/test-agent/endpoint/protocols/openai/responses"
        ),
    )
    monkeypatch.setenv("FOUNDRY_AGENT_NAME", "test-agent")
    monkeypatch.setenv("FOUNDRY_AGENT_VERSION", "4")
    monkeypatch.setenv("AZURE_TENANT_ID", "test-tenant")
    monkeypatch.setenv("AZURE_CLIENT_ID", "test-client")
    monkeypatch.setenv("AZURE_CLIENT_SECRET", "test-secret")
    app_path = Path(__file__).resolve().parents[1] / "app" / "streamlit_app.py"

    app = AppTest.from_file(str(app_path), default_timeout=15).run()

    assert not app.exception
    assert len(app.metric) == 4

    app.button[0].click().run()
    app.text_input[0].set_value("macquarie")
    app.text_input[1].set_value("test-password")
    app.button[0].click().run()

    assert not app.exception
    assert app.success[0].value == "Signed in as macquarie"
    assert len(app.chat_input) == 1
    assert len(app.date_input) == 1
    assert "Refresh Yahoo + RBA" in [button.label for button in app.button]

    app.date_input[0].set_value(date(2026, 6, 28)).run()

    assert not app.exception
    assert len(app.metric) == 4
