"""Gameplay LLM selection and OpenAI strict-schema request coverage."""

import json
from unittest.mock import patch

import httpx2
import openai as openai_sdk
import pytest
from agent_tool_profiles import AGENT_TOOL_LISTS
from livekit.agents import llm
from livekit.plugins import openai as openai_plugin

from gameplay_llm import LUNA_MODEL, create_gameplay_llm, is_luna


def test_default_uses_strict_luna_without_anthropic_options(monkeypatch):
    monkeypatch.delenv("GAMEPLAY_LLM", raising=False)
    with patch("gameplay_llm.openai.LLM") as constructor:
        selected = create_gameplay_llm("claude-haiku-4-5-20251001")

    assert selected is constructor.return_value
    constructor.assert_called_once_with(
        model=LUNA_MODEL,
        reasoning_effort="none",
        _strict_tool_schema=True,
        max_retries=0,
    )


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


@pytest.mark.parametrize("profile,tools", AGENT_TOOL_LISTS)
@pytest.mark.asyncio
async def test_luna_pilot_emits_every_tool_as_strict(monkeypatch, profile, tools):
    assert tools, f"{profile} tool profile is empty"
    requests = []

    async def respond(request: httpx2.Request) -> httpx2.Response:
        requests.append(json.loads((await request.aread()).decode()))
        return httpx2.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=b"data: [DONE]\n\n",
        )

    http_client = httpx2.AsyncClient(transport=httpx2.MockTransport(respond))
    sdk_client = openai_sdk.AsyncOpenAI(api_key="test", base_url="http://localhost/v1", http_client=http_client)
    monkeypatch.delenv("GAMEPLAY_LLM", raising=False)
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
    assert requests[0]["model"] == "gpt-6-luna"
    assert requests[0]["reasoning_effort"] == "none"
    emitted = requests[0]["tools"]
    assert len(emitted) == len(tools)
    assert all(tool["function"]["strict"] is True for tool in emitted)

    functions = {t["function"]["name"]: t["function"] for t in emitted}
    if profile in {"exploration", "combat", "dispatch", "onboarding", "blacksmith"}:
        schema = functions["query_info"]["parameters"]
        assert schema["additionalProperties"] is False
        assert "creature" in schema["properties"]["kind"]["enum"]
    if profile == "exploration":
        schema = functions["enter_mode"]["parameters"]
        assert schema["additionalProperties"] is False
        assert set(schema["required"]) == {
            "mode",
            "encounter_id",
            "encounter_description",
            "difficulty",
            "tier",
            "initiated_by",
        }
        assert set(schema["properties"]) == set(schema["required"])
        assert schema["properties"]["difficulty"]["type"] == ["string", "null"]
        assert schema["properties"]["tier"]["type"] == ["integer", "null"]

    if profile == "combat":
        _assert_reshape_schema(functions["declare_phase"]["parameters"])

    if profile == "dispatch":
        function = next(t["function"] for t in emitted if t["function"]["name"] == "begin_activity")
        schema = function["parameters"]

        def resolve(node):
            if "$ref" in node:
                target = schema
                for part in node["$ref"].removeprefix("#/").split("/"):
                    target = target[part]
                return resolve(target)
            return node

        activity = resolve(schema["properties"]["activity"])
        branches = [resolve(branch) for branch in activity["anyOf"]]
        purification = next(
            branch
            for branch in branches
            if branch["properties"]["kind"].get("const") == "purification"
            or branch["properties"]["kind"].get("enum") == ["purification"]
        )
        assert set(purification["required"]) == {"kind", "item_id", "quantity"}
        assert purification["properties"]["quantity"]["type"] == "integer"
        assert purification["additionalProperties"] is False


def _assert_reshape_schema(schema):
    def branches(node):
        return [
            schema["$defs"][branch["$ref"].split("/")[-1]] if "$ref" in branch else branch for branch in node["anyOf"]
        ]

    def kind(branch):
        discriminator = branch["properties"]["kind"]
        return discriminator.get("const") or discriminator["enum"][0]

    expected = {
        "create_wall": {"start", "end"},
        "move_wall": {"wall_id", "start", "end"},
        "destroy_wall": {"wall_id"},
        "open_floor": {"min", "max"},
        "lower_ceiling": {"min", "max"},
    }
    declarations = branches(schema["properties"]["declarations"]["items"])
    assert len(declarations) == 13
    [surrender] = [declaration for declaration in declarations if kind(declaration) == "yield"]
    assert set(surrender["required"]) == {"kind", "actor_id"}
    assert surrender["additionalProperties"] is False
    combined = next(branch for branch in declarations if kind(branch) == "attack_consume")
    discriminator = combined["properties"]["kind"]
    assert discriminator.get("const") == "attack_consume" or discriminator.get("enum") == ["attack_consume"]
    assert set(combined["required"]) == {"kind", "actor_id", "action", "target_id", "item_id", "heal_target_id"}
    assert combined["additionalProperties"] is False
    [shadow_step] = [declaration for declaration in declarations if kind(declaration) == "ability_move"]
    assert set(shadow_step["required"]) == {"kind", "actor_id", "action", "destination"}
    for declaration in declarations:
        properties = declaration["properties"]
        assert set(declaration["required"]) == set(properties)
        if kind(declaration) == "move":
            assert set(properties["movement_mode"]["enum"]) == {"ground", "flying"}
            assert properties["nythera_step"]["type"] == "boolean"
        else:
            assert "movement_mode" not in properties
            assert "nythera_step" not in properties
        if kind(declaration) in {"attack", "move", "defend"}:
            operations = branches(properties["reshape"]["items"])
            assert len(operations) == len(expected)
            assert {kind(operation): set(operation["required"]) - {"kind"} for operation in operations} == expected
            assert all(operation["additionalProperties"] is False for operation in operations)
        else:
            assert "reshape" not in properties
