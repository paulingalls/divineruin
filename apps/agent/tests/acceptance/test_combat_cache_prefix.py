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
from sample_fixtures import make_mock_room

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
    sd = SessionData(player_id="player_1", location_id="accord_guild_hall", room=make_mock_room())
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


@pytest.mark.skip(
    reason="MEASUREMENT TOOL, not a gate — flaky 1-in-3 and unfixably so; run it deliberately. "
    "The regression IS guarded, deterministically and in the fast lane, by "
    "tests/test_warm_layer_during_combat.py's `update_instructions.await_count == 0` "
    "(story-024 AC1), which reds on the mutation this test fault-injects. What this test adds "
    "is provider-level confirmation, and it made that measurement once: hot 195 total cache "
    "writes against the system-prompt rewrite's 11348, the rewrite's per-round writes GROWING "
    "3712 -> 4485 -> 5225 as the prefix does. The noise cannot be removed without removing the "
    "phenomenon: the DM's tool-calling varies run to run (arms of 3 and 11 requests measured), "
    "which moves where the one-time cache creation lands; and forcing tool_choice='none' to "
    "make both arms one-request makes the history too short to reach the 4096-token minimum, "
    "so nothing caches at all and every arm reads [[0],[0],[0]]. Redesign is debt."
)
async def test_a_combat_round_reads_the_prefix_instead_of_rewriting_it(reset_db_pool: str) -> None:
    pool = await db.get_pool()
    await seed_player(pool, player_id="player_1")

    hot, hot_rounds = await _drive_fight(3, rewrite_system_prompt=False)
    print(f"\n[measured] hot-layer cache writes per round: {hot_rounds}")
    print(f"[measured] hot-layer summary: {hot.summary()}")

    assert all(writes for writes in hot_rounds), "a round issued no LLM request at all"

    # Anti-vacuity on the FIGHT, not on request one. The first request of a session has
    # nothing cached yet AND sits under this model's 4096-token minimum until the history
    # grows past it, so it legitimately creates no entry — measured round 1 is
    # [0, 163, 85, 212]. Requiring a write on request one asserted a wrong model of when
    # prefix caching begins and aborted before the arm below could run at all.
    hot_summary = hot.summary()
    assert hot_summary["total_cache_write"] > 0, (
        f"the fight created no cache entry at all — nothing below can measure a prefix "
        f"that was never cached: {hot_rounds}"
    )
    assert hot_summary["total_cache_read"] > 0, "nothing was ever read from cache"

    # NOT asserted here: a read/write ratio, or a per-round decay shape. Both are too
    # noisy to be a guard. The DM's tool-calling varies run to run, so the number of
    # requests per round varies with it — two measured runs of this same fight gave
    # 8 requests ([[0,163,85,212],[377...]] shaped) and 3 ([[8742],[377],[98]]). The
    # second decays beautifully and the first does not, and NEITHER is a defect: the
    # first request that crosses the 4096-token minimum pays the one-time creation,
    # and where that lands depends on how many tool calls preceded it. The claim this
    # test exists to defend is a COMPARISON, and it is made against the arm below.

    injected, injected_rounds = await _drive_fight(3, rewrite_system_prompt=True)
    print(f"[measured] system-prompt-rewrite cache writes per round: {injected_rounds}")
    print(f"[measured] system-prompt-rewrite summary: {injected.summary()}")

    # Compare ARMS on fight totals, not request-one values: the per-round request count
    # varies with the tool chain (measured 4/3/1), so a single request is not comparable
    # across rounds while the fight total is.
    injected_summary = injected.summary()
    assert injected_summary["total_cache_write"] > hot_summary["total_cache_write"] * 2, (
        f"the fault injection did not reproduce the regression — rewriting the system prompt "
        f"each round cost no more than leaving it alone: "
        f"injected={injected_summary} hot={hot_summary}"
    )
