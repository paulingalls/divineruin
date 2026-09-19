import os

import pytest

import narration

pytestmark = [
    pytest.mark.real_llm,
    pytest.mark.skipif(
        not os.environ.get("ANTHROPIC_API_KEY") and not os.environ.get("REQUIRE_REAL_LLM"),
        reason="Paid provider-contract acceptance requires ANTHROPIC_API_KEY",
    ),
]


@pytest.mark.asyncio
async def test_provider_requires_a_narration_segment_even_when_asked_for_silence():
    response = await narration._client.messages.create(
        model=narration.MODEL,
        max_tokens=narration.MAX_TOKENS,
        tools=[narration._build_narration_tool([])],
        tool_choice={"type": "tool", "name": "narration_result"},
        messages=[
            {
                "role": "user",
                "content": "Submit narration_result with segments exactly [] and summary 'No narration'. Do not invent any segments.",
            }
        ],
    )
    assert response.stop_reason == "tool_use"
    result = narration._extract_tool_input(response)
    assert result is not None
    assert isinstance(result.get("segments"), list)
    assert result["segments"], "Provider accepted an empty audio result under the production strict schema"
