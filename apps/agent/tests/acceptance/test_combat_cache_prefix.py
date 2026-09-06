"""AC3: a combat round READS the cached prefix instead of rewriting it.

Measured against the provider's own numbers, not against a model of them (constraint 9).
The number is `llm.CompletionUsage.cache_creation_tokens`, set by the anthropic plugin from
`usage.cache_creation_input_tokens` onto the final ChatChunk; `metrics_collected` cannot see
it, because livekit builds LLMMetrics from that same usage object and drops the field.

Two arms, and the SECOND ARM IS THE FAULT INJECTION: it restores the story-023 regression by
rewriting the system prompt each round, which is what debt ce06dd8c named. Without it a
green here would certify nothing — a session that never cached at all passes every
"does not grow" assertion.
"""

from __future__ import annotations

import os

import pytest
from acceptance.seeds import seed_player
from livekit.agents.llm import ChatMessage
from livekit.agents.voice import AgentSession
from livekit.plugins import anthropic
from prompt_fixtures import sample_combat_state

import db
from combat_agent import create_combat_agent
from session_data import SessionData
from system_prompts import COMBAT_SYSTEM_PROMPT
from token_tracker import TokenTracker
from warm_prompts import build_full_prompt, format_combat_hot_line

pytestmark = [
    pytest.mark.skipif(
        not os.environ.get("ANTHROPIC_API_KEY") and not os.environ.get("REQUIRE_REAL_LLM"),
        reason="LLM acceptance runs require ANTHROPIC_API_KEY (ADR 0003 pre-sprint-close schedule)",
    ),
    pytest.mark.real_llm,
]

# Production gameplay model (agent.py) — acceptance runs at production parity.
_AGENT_MODEL = "claude-haiku-4-5-20251001"

_UTTERANCE = "I hold my guard and watch Grosh."


async def _drive_fight(rounds: int, *, rewrite_system_prompt: bool) -> tuple[TokenTracker, list[list[int]]]:
    """Run `rounds` combat turns and return the tracker plus each round's cache writes.

    Per round rather than flat, because a turn may fan out into tool-call requests: the
    comparable number is the FIRST request of each round, the one that either reads the
    standing prefix or rewrites it.
    """
    sd = SessionData(player_id="player_1", location_id="accord_guild_hall")
    sd.combat_state = sample_combat_state(round_number=1)
    session = AgentSession(
        # Parity with agent.py, which is the whole point: caching="ephemeral" is what puts
        # the breakpoint on the last system block, and strict schemas are interim-OFF.
        llm=anthropic.LLM(model=_AGENT_MODEL, caching="ephemeral", _strict_tool_schema=False),
        max_tool_steps=5,
        userdata=sd,
    )
    agent = create_combat_agent()
    await session.start(agent)

    per_round: list[list[int]] = []
    try:
        for round_number in range(1, rounds + 1):
            sd.combat_state.round_number = round_number
            if rewrite_system_prompt:
                # The regression, restored on purpose: the warm layer carrying the fight.
                warm = format_combat_hot_line(sd.combat_state)
                assert warm is not None
                await agent.update_instructions(build_full_prompt(COMBAT_SYSTEM_PROMPT, warm))

            # The production turn shape. `session.run()` cannot drive this measurement: it
            # goes generate_reply -> _generate_reply -> _pipeline_reply_task directly, and
            # on_user_turn_completed has exactly one call site (_user_turn_completed_task),
            # reachable only from on_end_of_turn — so run() would send three requests with
            # no combat line in any of them and pass MORE easily.
            turn_ctx = agent.chat_ctx.copy()
            await agent.on_user_turn_completed(turn_ctx, ChatMessage(role="user", content=[_UTTERANCE]))

            # Anti-vacuity: this round's line is in the context the request is built from.
            assert f"Round {round_number}" in "\n".join(
                str(item.content)
                for item in turn_ctx.items
                if isinstance(item, ChatMessage) and item.role == "assistant"
            ), f"round {round_number} sent no combat line — the arm below would measure a fight it never ran"

            mark = len(sd.tokens.cache_writes)
            await session.generate_reply(user_input=_UTTERANCE, chat_ctx=turn_ctx)
            per_round.append(sd.tokens.cache_writes[mark:])
    finally:
        await session.aclose()

    return sd.tokens, per_round


async def test_a_combat_round_reads_the_prefix_instead_of_rewriting_it(reset_db_pool: str) -> None:
    pool = await db.get_pool()
    await seed_player(pool, player_id="player_1")

    hot, hot_rounds = await _drive_fight(3, rewrite_system_prompt=False)
    print(f"\n[measured] hot-layer cache writes per round: {hot_rounds}")
    print(f"[measured] hot-layer summary: {hot.summary()}")

    firsts = [writes[0] for writes in hot_rounds]
    assert all(writes for writes in hot_rounds), "a round issued no LLM request at all"
    assert firsts[0] > 0, (
        "round 1 created no cache entry — the prefix is under this model's 4096-token minimum, "
        "so every assertion below would be vacuously true"
    )
    assert hot.summary()["total_cache_read"] > 0, "nothing was ever read from cache"
    assert firsts[2] < firsts[0], f"round 3 still rewrote the prefix: {firsts}"
    assert firsts[2] <= firsts[1] * 1.5 + 1, f"cache writes grow with the fight: {firsts}"

    injected, injected_rounds = await _drive_fight(3, rewrite_system_prompt=True)
    print(f"[measured] system-prompt-rewrite cache writes per round: {injected_rounds}")
    print(f"[measured] system-prompt-rewrite summary: {injected.summary()}")

    injected_firsts = [writes[0] for writes in injected_rounds]
    assert injected_firsts[2] > injected_firsts[0], (
        f"the fault injection did not reproduce the regression: {injected_firsts}"
    )
    assert injected_firsts[2] > firsts[2] * 2, (
        f"the guard cannot tell the regression from the fix: injected={injected_firsts} hot={firsts}"
    )
