from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from types import SimpleNamespace
from typing import Any

import pytest

from market_intelligence.assistant.foundry import (
    TOOL_SCHEMAS,
    FoundryAssistant,
    FoundrySettings,
)


@dataclass
class FakeToken:
    expires_on: int = 1234567890


class FakeCredential:
    def __init__(self) -> None:
        self.scope = ""

    def get_token(self, scope: str) -> FakeToken:
        self.scope = scope
        return FakeToken()


class FakeDataTools:
    def get_available_date_range(self) -> dict[str, Any]:
        return {
            "first_date": "2021-07-01",
            "latest_date": "2026-07-31",
            "observation_count": 1260,
        }


class FakeResponses:
    def __init__(self, responses: list[Any]) -> None:
        self._responses = responses
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return self._responses.pop(0)


class FakeClient:
    def __init__(self, responses: list[Any]) -> None:
        self.responses = FakeResponses(responses)


def test_foundry_settings_require_every_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in (
        "FOUNDRY_AGENT_ENDPOINT",
        "FOUNDRY_AGENT_NAME",
        "FOUNDRY_AGENT_VERSION",
        "AZURE_TENANT_ID",
        "AZURE_CLIENT_ID",
        "AZURE_CLIENT_SECRET",
    ):
        monkeypatch.delenv(name, raising=False)

    with pytest.raises(ValueError, match="configuration is incomplete"):
        FoundrySettings.from_environment()


def test_agent_endpoint_is_converted_to_openai_base_url() -> None:
    settings = FoundrySettings(
        agent_endpoint=(
            "https://example.services.ai.azure.com/api/projects/project/"
            "agents/agent/endpoint/protocols/openai/responses"
        ),
        agent_name="agent",
        agent_version="2",
        tenant_id="tenant",
        client_id="client",
        client_secret="secret",
    )

    assert settings.base_url.endswith("/agents/agent/endpoint/protocols/openai")


def test_relationship_tool_is_persisted_in_agent_schema() -> None:
    tool_names = {tool["name"] for tool in TOOL_SCHEMAS}

    assert "analyse_market_volatility_relationship" in tool_names
    assert "analyse_metric_correlation" in tool_names


def test_answer_executes_function_call_and_returns_final_text() -> None:
    function_call = SimpleNamespace(
        type="function_call",
        name="get_available_date_range",
        arguments="{}",
        call_id="call-1",
    )
    first_response = SimpleNamespace(
        id="response-1",
        output=[function_call],
        output_text="",
    )
    final_response = SimpleNamespace(
        id="response-2",
        output=[],
        output_text="Grounded answer",
    )
    client = FakeClient([first_response, final_response])
    assistant = FoundryAssistant(
        client,
        data_tools=FakeDataTools(),  # type: ignore[arg-type]
    )

    answer = assistant.answer(
        "What changed?",
        analysis_end_date=date(2026, 7, 31),
        conversation=[
            {"role": "user", "content": "How is volatility measured?"},
            {"role": "assistant", "content": "Using a 14-day annualised measure."},
        ],
    )

    assert answer == "Grounded answer"
    assert "2026-07-31" in client.responses.calls[0]["input"]
    assert "How is volatility measured?" in client.responses.calls[0]["input"]
    assert "tools" not in client.responses.calls[0]
    second_input = client.responses.calls[1]["input"]
    assert second_input[0]["type"] == "function_call_output"
    assert json.loads(second_input[0]["output"])["latest_date"] == "2026-07-31"
    assert "tools" not in client.responses.calls[1]


def test_diagnostic_separates_database_token_and_agent_checks() -> None:
    response = SimpleNamespace(output_text="CONNECTED")
    client = FakeClient([response])
    credential = FakeCredential()
    assistant = FoundryAssistant(
        client,
        credential=credential,
        data_tools=FakeDataTools(),  # type: ignore[arg-type]
        agent_name="agent-req",
        agent_version="2",
    )

    result = assistant.diagnose()

    assert result["database"] == "connected (2021-07-01 to 2026-07-31)"
    assert result["azure_token"] == "acquired (expires 1234567890)"
    assert result["foundry_agent"] == "connected (agent-req version 2)"
    assert credential.scope == "https://ai.azure.com/.default"
