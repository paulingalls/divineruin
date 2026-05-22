"""pytest-bdd step defs for the M1.5 training-cycle acceptance scenarios.

Drives the real DispatchAgent (Haiku) + a real Postgres testcontainer via the
LiveKit test framework. Training tools live in DispatchAgent, reached
when the player enters the training hall. Skips entirely without ANTHROPIC_API_KEY
(the pre-sprint-close / test-creation schedule in ADR 0003).

Steps are SYNC and drive the async agent work through a per-scenario event loop on
a background thread (harness.run_sync): pytest-bdd 8.1 does not await async step
functions, so async steps would silently skip their assertions (decision
bdd-async-step-pattern). session.start() spawns background tasks that must keep
running across the discrete when/then steps, so the loop runs forever on its own
thread rather than one run_until_complete per step.
"""

from __future__ import annotations

import os
from types import SimpleNamespace
from typing import Any

import pytest
from acceptance.seeds import clear_training_activities, seed_player, seed_training_activity
from livekit.agents.llm import ChatContext
from livekit.agents.voice import AgentSession
from livekit.plugins import anthropic
from pytest_bdd import given, parsers, scenarios, then, when

import db
from dispatch_agent import create_dispatch_agent
from session_data import SessionData
from training_rules import get_midpoint_decision
from warm_prompts import format_training_section

pytestmark = pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="LLM acceptance runs require ANTHROPIC_API_KEY (ADR 0003 pre-sprint-close schedule)",
)

# Production gameplay model (agent.py) — acceptance runs at production parity.
_AGENT_MODEL = "claude-haiku-4-5-20251001"

scenarios("features/m1_5_training_cycle.feature")

# The `harness` fixture (per-scenario event loop on a background thread + run_sync)
# lives in conftest.py, shared with the M1.6 errand acceptance test.


async def _start_training_session(harness: SimpleNamespace, chat_ctx: ChatContext | None = None) -> None:
    session_data = SessionData(player_id="player_1", location_id="accord_training_hall")
    session = AgentSession(
        llm=anthropic.LLM(model=_AGENT_MODEL, caching="ephemeral"),
        userdata=session_data,
    )
    await session.start(create_dispatch_agent(chat_ctx=chat_ctx))
    harness.state["session"] = session
    harness.state["judge_llm"] = anthropic.LLM(model=_AGENT_MODEL)


@given("a player at the training hall with no active training")
def _given_no_active_training(harness: SimpleNamespace) -> None:
    async def _setup() -> None:
        pool = await db.get_pool()
        await seed_player(pool, player_id="player_1")
        await clear_training_activities(pool, "player_1")
        await _start_training_session(harness)

    harness.run_sync(_setup())


@given("a player at the training hall awaiting a midpoint decision")
def _given_awaiting_midpoint(harness: SimpleNamespace) -> None:
    async def _setup() -> None:
        pool = await db.get_pool()
        await seed_player(pool, player_id="player_1")
        await clear_training_activities(pool, "player_1")
        # Build the awaiting_decision payload exactly as async_worker does at the
        # midpoint transition, from the REAL activity-type config — so the seed
        # mirrors production content rather than hand-authored prose.
        decision = get_midpoint_decision("technique_base")
        cycle_data = {
            "program_id": "combat_basics",
            "program_name": "Combat Fundamentals",
            "decision_prompt": decision.prompt,
            "decision_options": [{"id": o.id, "label": o.label} for o in decision.options],
        }
        await seed_training_activity(pool, activity_id="train_mid01", state="awaiting_decision", data=cycle_data)
        # Carry the cycle id + options into context the way the production warm-prompt
        # layer does — by formatting through the SAME helper, so this scenario drives
        # the real surface (format drift fails here, not just a unit test). STATE only,
        # no tool instruction, so the assertion tests the agent's own tool choice.
        row = {
            "id": "train_mid01",
            "activity_type": "technique_base",
            "state": "awaiting_decision",
            "data": cycle_data,
        }
        training_block = format_training_section([row])
        assert training_block is not None  # awaiting_decision row always yields a block
        ctx = ChatContext()
        ctx.add_message(role="system", content=training_block)
        await _start_training_session(harness, chat_ctx=ctx)

    harness.run_sync(_setup())


@given("a player at the training hall with a cycle already in progress")
def _given_cycle_in_progress(harness: SimpleNamespace) -> None:
    async def _setup() -> None:
        pool = await db.get_pool()
        await seed_player(pool, player_id="player_1")
        await clear_training_activities(pool, "player_1")
        await seed_training_activity(pool, activity_id="train_run01", state="running_first_half")
        await _start_training_session(harness)

    harness.run_sync(_setup())


@when(parsers.parse('the player says "{utterance}"'))
def _player_says(harness: SimpleNamespace, utterance: str) -> None:
    session = harness.state["session"]

    # session.run() builds its RunResult eagerly (needs a running loop), so call
    # it inside the loop thread rather than on the main thread.
    async def _run() -> Any:
        return await session.run(user_input=utterance)

    harness.state["result"] = harness.run_sync(_run())


@then(parsers.parse('the agent calls the "{tool_name}" tool'))
def _agent_calls_tool(harness: SimpleNamespace, tool_name: str) -> None:
    harness.state["result"].expect.contains_function_call(name=tool_name)


def _judge(harness: SimpleNamespace, intent: str) -> None:
    # The agent emits several assistant messages per turn (e.g. a "let me check"
    # line before a tool call); the meaningful narration is the LAST one.
    message = harness.state["result"].expect[-1].is_message(role="assistant")
    harness.run_sync(message.judge(harness.state["judge_llm"], intent=intent))


@then("the agent narrates that the training has begun")
def _narrates_begun(harness: SimpleNamespace) -> None:
    _judge(harness, "Tells the player their training has begun")


@then("the agent narrates the training continuing")
def _narrates_continuing(harness: SimpleNamespace) -> None:
    _judge(harness, "Tells the player their training continues into its second half")


@then("the agent narrates that a cycle is already in progress")
def _narrates_in_progress(harness: SimpleNamespace) -> None:
    _judge(harness, "Tells the player they already have a training cycle in progress and cannot start another")
