from __future__ import annotations

import os
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

    monkeypatch.setenv("DATABASE_URL", INTEGRATION_DATABASE_URL)
    app_path = Path(__file__).resolve().parents[1] / "app" / "streamlit_app.py"

    app = AppTest.from_file(str(app_path), default_timeout=15).run()

    assert not app.exception
    assert len(app.metric) == 4
