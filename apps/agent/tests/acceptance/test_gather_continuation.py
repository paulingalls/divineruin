"""Live OpenAI continuation after a committed gather result.

This uses the provider-specific ``openai_real_llm`` marker so the no-LLM acceptance lane
deselects it without applying the Anthropic test fixture's unrelated key requirement.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import uuid4

import pytest
from acceptance.seeds import seed_player
from livekit.agents import llm
from sample_fixtures import FixedRng, make_context, make_mock_room

import db
import db_queries
import gathering_tools
from exploration_agent import EXPLORATION_TOOLS
from system_prompts import build_system_prompt

openai = pytest.importorskip(
    "livekit.plugins.openai",
    reason="livekit-plugins-openai is installed ephemerally until story-213 pins it",
)

pytestmark = [
    pytest.mark.skipif(
        not os.environ.get("OPENAI_API_KEY") and not os.environ.get("REQUIRE_REAL_LLM"),
        reason="OpenAI continuation acceptance requires OPENAI_API_KEY",
    ),
    pytest.mark.openai_real_llm,
]

_LOCATION = "greyvale_south_road"
_MODEL = "gpt-5.6-luna"
_USAGE_PATH = Path("/tmp/divineruin_gather_continuation_usage.json")


def _require_openai_key() -> None:
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if key and not key.lower().startswith("your-"):
        return
    if os.environ.get("REQUIRE_REAL_LLM"):
        pytest.fail("REQUIRE_REAL_LLM=1 but OPENAI_API_KEY is absent, empty, or a your-... placeholder")
    pytest.skip("OpenAI continuation acceptance requires OPENAI_API_KEY")


if os.environ.get("REQUIRE_REAL_LLM"):
    _require_openai_key()


@pytest.fixture(autouse=True)
def _openai_key_required() -> None:
    _require_openai_key()


async def _set_expert_survival(pool, player_id: str) -> None:
    await pool.execute(
        "INSERT INTO skill_advancement "
        "(player_id, skill_id, tier, use_counter, narrative_moment_ready) "
        "VALUES ($1, 'survival', 'expert', 0, FALSE) "
        "ON CONFLICT (player_id, skill_id) DO UPDATE SET tier = EXCLUDED.tier",
        player_id,
    )


async def test_luna_narrates_committed_gather_without_duplicate_grant(reset_db_pool: str, record_property) -> None:
    pool = await db.get_pool()
    player_id = f"gather_continuation_{uuid4().hex}"
    await seed_player(pool, player_id=player_id, location_id=_LOCATION)
    await _set_expert_survival(pool, player_id)

    context = make_context(player_id, location_id=_LOCATION, room=make_mock_room())
    gather_output = await gathering_tools._check_gather_impl(context, "", rng=FixedRng(20))
    gather_result = json.loads(gather_output)
    assert gather_result["materials"]
    assert gather_result["inventory_updated"] is True

    counts: dict[str, int] = {}
    for material_id in gather_result["materials"]:
        counts[material_id] = counts.get(material_id, 0) + 1
    for material_id, quantity in counts.items():
        item = await db_queries.get_inventory_item(player_id, material_id, conn=pool)
        assert item is not None and item["quantity"] == quantity

    call_id = f"gather_{uuid4().hex}"
    chat_context = llm.ChatContext(
        items=[
            llm.ChatMessage(role="system", content=[build_system_prompt(_LOCATION)]),
            llm.ChatMessage(
                role="user",
                content=["I search the roadside brush for useful herbs. Please resolve the attempt."],
            ),
            llm.FunctionCall(
                call_id=call_id,
                name="check",
                arguments=json.dumps({"roll": {"kind": "gather", "category": "any"}}),
            ),
            llm.FunctionCallOutput(
                call_id=call_id,
                name="check",
                output=gather_output,
                is_error=False,
            ),
        ]
    )

    model = openai.LLM(model=_MODEL, reasoning_effort="none", _strict_tool_schema=True)
    try:
        response = await model.chat(chat_ctx=chat_context, tools=EXPLORATION_TOOLS).collect()
    finally:
        await model.aclose()

    assert response.usage is not None
    row = {
        "model": _MODEL,
        "prompt_tokens": response.usage.prompt_tokens,
        "cached_tokens": response.usage.prompt_cached_tokens,
        "completion_tokens": response.usage.completion_tokens,
        "call_names": [call.name for call in response.tool_calls],
        "narration_present": bool(response.text.strip()),
    }
    _USAGE_PATH.write_text(json.dumps(row, sort_keys=True) + "\n")
    record_property("gather_continuation_usage", row)
    print(f"\n[gather-continuation] {json.dumps(row, sort_keys=True)}")

    assert response.text.strip(), "Luna returned neither usable narration nor a completed turn"
    assert not response.tool_calls, "Luna requested a duplicate post-gather tool call: " + json.dumps(
        [{"name": call.name, "arguments": call.arguments} for call in response.tool_calls]
    )
    assert response.usage.prompt_tokens > 0
    assert response.usage.completion_tokens > 0
