from __future__ import annotations

import os
from datetime import date
from pathlib import Path

import pytest

INTEGRATION_DATABASE_URL = os.getenv("INTEGRATION_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not INTEGRATION_DATABASE_URL,
    reason="INTEGRATION_DATABASE_URL is not configured",
)


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
            "holeydollar",
            salt=b"0123456789abcdef",
            iterations=1_000,
        ),
    )
    app_path = Path(__file__).resolve().parents[1] / "app" / "streamlit_app.py"

    app = AppTest.from_file(str(app_path), default_timeout=15).run()

    assert not app.exception
    assert len(app.metric) == 4

    app.button[0].click().run()
    app.text_input[0].set_value("macquarie")
    app.text_input[1].set_value("holeydollar")
    app.button[0].click().run()

    assert not app.exception
    assert app.success[0].value == "Signed in as macquarie"
    assert len(app.date_input) == 1

    app.date_input[0].set_value(date(2026, 6, 28)).run()

    assert not app.exception
    assert len(app.metric) == 4
