from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pytest

from market_intelligence.assistant.foundry import FoundryAssistant, FoundrySettings


@dataclass
class FakeResponse:
    text: str


class FakeAgent:
    def __init__(self) -> None:
        self.prompt = ""

    async def run(self, prompt: str) -> FakeResponse:
        self.prompt = prompt
        return FakeResponse("Grounded answer")


def test_foundry_settings_require_every_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in (
        "FOUNDRY_PROJECT_ENDPOINT",
        "FOUNDRY_MODEL",
        "AZURE_TENANT_ID",
        "AZURE_CLIENT_ID",
        "AZURE_CLIENT_SECRET",
    ):
        monkeypatch.delenv(name, raising=False)

    with pytest.raises(ValueError, match="configuration is incomplete"):
        FoundrySettings.from_environment()


def test_answer_includes_dashboard_date_and_recent_context() -> None:
    fake_agent = FakeAgent()
    assistant = FoundryAssistant(fake_agent)

    answer = assistant.answer(
        "What changed?",
        analysis_end_date=date(2026, 7, 31),
        conversation=[
            {"role": "user", "content": "How is volatility measured?"},
            {"role": "assistant", "content": "Using a 14-day annualised measure."},
        ],
    )

    assert answer == "Grounded answer"
    assert "2026-07-31" in fake_agent.prompt
    assert "How is volatility measured?" in fake_agent.prompt
    assert "Current user question:\nWhat changed?" in fake_agent.prompt
