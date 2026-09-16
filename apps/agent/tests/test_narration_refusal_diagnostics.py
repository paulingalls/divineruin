"""A refused narration payload reports what is needed to tell its two candidate causes apart.

An undecodable `segments` string is either a response cut off at max_tokens or malformed JSON, and
the two have different fixes. So the refusal carries the response's stop reason, its output token
count and the whole payload, never a clipped repr.
"""

from unittest.mock import AsyncMock, patch

import pytest
from anthropic.types import Message, ToolUseBlock, Usage

import narration

_OUTCOME = {
    "tier": "success",
    "narrative_context": {
        "tier": "success",
        "roll": 18,
        "total": 22,
        "dc": 13,
        "skill": "athletics",
        "recipe_name": "Iron Sword",
        "bonus_property": None,
        "flaw": None,
        "npc_id": "grimjaw_blacksmith",
    },
    "decision_options": [{"id": "keep", "label": "Keep the item"}, {"id": "sell", "label": "Sell it"}],
}


def _cut_off_response(segments: str) -> Message:
    return Message(
        id="msg_test",
        type="message",
        role="assistant",
        model=narration.MODEL,
        content=[
            ToolUseBlock(
                id="toolu_test",
                type="tool_use",
                name="narration_result",
                input={"segments": segments, "summary": "The blade holds."},
            )
        ],
        stop_reason="max_tokens",
        usage=Usage(input_tokens=900, output_tokens=narration.MAX_TOKENS),
    )


@pytest.mark.asyncio
async def test_a_refused_payload_reports_the_stop_reason_the_tokens_and_the_whole_payload():
    undecodable = '[{"character": "DM_NARRATOR", "emotion": "neutral", "text": "' + "The mill wheel groans. " * 30
    undecodable += "END-OF-OUTPUT"
    response = _cut_off_response(undecodable)

    with patch("narration._client.messages.create", new_callable=AsyncMock, return_value=response):
        with pytest.raises(ValueError, match="no speakable narration") as refused:
            await narration.generate_activity_narration(
                _OUTCOME, {"name": "Kael", "level": 3, "class": "warrior"}, {"activity_type": "crafting"}
            )

    message = str(refused.value)
    assert "stop_reason='max_tokens'" in message
    assert f"output_tokens={narration.MAX_TOKENS}" in message
    assert "END-OF-OUTPUT" in message
