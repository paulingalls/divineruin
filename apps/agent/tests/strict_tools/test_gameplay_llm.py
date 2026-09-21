"""Gameplay LLM selection and OpenAI strict-schema request coverage."""

import json
from unittest.mock import patch

import httpx
import openai as openai_sdk
import pytest
from livekit.agents import llm
from livekit.plugins import openai as openai_plugin

from blacksmith_agent import BLACKSMITH_TOOLS
from combat_agent import COMBAT_AGENT_TOOLS
from creation_agent import CREATION_TOOLS
from dispatch_agent import DISPATCH_TOOLS
from exploration_agent import EXPLORATION_TOOLS
from gameplay_llm import LUNA_MODEL, create_gameplay_llm, is_luna
from onboarding_agent import ONBOARDING_TOOLS

TOOL_PROFILES = [
    ("exploration", EXPLORATION_TOOLS),
    ("combat", COMBAT_AGENT_TOOLS),
    ("dispatch", DISPATCH_TOOLS),
    ("creation", CREATION_TOOLS),
    ("onboarding", ONBOARDING_TOOLS),
    ("blacksmith", BLACKSMITH_TOOLS),
]


def test_default_uses_strict_luna_without_anthropic_options(monkeypatch):
    monkeypatch.delenv("GAMEPLAY_LLM", raising=False)
    with patch("gameplay_llm.openai.LLM") as constructor:
        selected = create_gameplay_llm("claude-haiku-4-5-20251001")

    assert selected is constructor.return_value
    constructor.assert_called_once_with(
        model=LUNA_MODEL,
        reasoning_effort="none",
        _strict_tool_schema=True,
    )
    assert is_luna(selected) is True


def test_anthropic_override_keeps_anthropic_options(monkeypatch):
    monkeypatch.setenv("GAMEPLAY_LLM", "anthropic")
    with patch("gameplay_llm.anthropic.LLM") as constructor:
        selected = create_gameplay_llm("claude-haiku-4-5-20251001")

    assert selected is constructor.return_value
    constructor.assert_called_once_with(
        model="claude-haiku-4-5-20251001",
        temperature=0.8,
        caching="ephemeral",
        _strict_tool_schema=False,
    )
    assert is_luna(selected) is False


def test_unknown_gameplay_llm_fails_loud(monkeypatch):
    monkeypatch.setenv("GAMEPLAY_LLM", "openai-auto")
    with pytest.raises(ValueError, match="GAMEPLAY_LLM"):
        create_gameplay_llm("claude-haiku-4-5-20251001")


@pytest.mark.parametrize("profile,tools", TOOL_PROFILES)
@pytest.mark.asyncio
async def test_luna_pilot_emits_every_tool_as_strict(monkeypatch, profile, tools):
    assert tools, f"{profile} tool profile is empty"
    requests = []

    async def respond(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads((await request.aread()).decode()))
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=b"data: [DONE]\n\n",
        )

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    sdk_client = openai_sdk.AsyncOpenAI(api_key="test", http_client=http_client)
    monkeypatch.setenv("GAMEPLAY_LLM", "openai-luna")
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    selected = create_gameplay_llm("unused-anthropic-model")
    assert isinstance(selected, openai_plugin.LLM)
    owned_client = selected._client
    selected._client = sdk_client
    try:
        context = llm.ChatContext(items=[llm.ChatMessage(role="user", content=["hello"])])
        async with selected.chat(chat_ctx=context, tools=tools) as stream:
            _ = [chunk async for chunk in stream]
    finally:
        await owned_client.close()
        await sdk_client.close()

    assert len(requests) == 1
    emitted = requests[0]["tools"]
    assert len(emitted) == len(tools)
    assert all(tool["function"]["strict"] is True for tool in emitted)
