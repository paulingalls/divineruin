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
from acceptance._judged_turn import last_assistant_message_index
from acceptance._midpoint_order import assert_training_midpoint
from acceptance._training_trace import (
    assert_no_training_start,
    assert_persisted_training,
    eligible_spell_pairs,
    offered_spell,
    spell_programs,
    training_program_result,
    training_start,
)
from acceptance.seeds import clear_training_activities, seed_player, seed_training_activity
from livekit.agents import llm
from livekit.agents.llm import ChatContext
from livekit.agents.voice import AgentSession
from livekit.agents.voice.run_result import RunResult
from livekit.plugins import anthropic
from pytest_bdd import given, parsers, scenarios, then, when
from sample_fixtures import make_mock_room

import db
import db_training
from dispatch_agent import create_dispatch_agent
from session_data import SessionData
from training_rules import get_midpoint_decision
from warm_prompts import format_training_section

pytestmark = [
    # The skipif is the not-opted-in path (CI: ci.yml runs the whole suite with no key).
    # REQUIRE_REAL_LLM=1 suppresses it so the real_llm fixture can fail the lane LOUD instead
    # — a skipif firing first would keep the false green (story-019 AC1).
    pytest.mark.skipif(
        not os.environ.get("ANTHROPIC_API_KEY") and not os.environ.get("REQUIRE_REAL_LLM"),
        reason="LLM acceptance runs require ANTHROPIC_API_KEY (ADR 0003 pre-sprint-close schedule)",
    ),
    pytest.mark.real_llm,
]

# Production gameplay model (agent.py) — acceptance runs at production parity.
_AGENT_MODEL = "claude-haiku-4-5-20251001"

_ACTIVE_CYCLE_INTENT = (
    "States both that an existing training cycle is already in progress and that another cannot start until "
    "the existing cycle finishes or resolves. Compatible follow-up conversation is allowed; fail only if it "
    "omits either required fact or contradicts the begin_activity result."
)
_NO_SPELL_INTENT = (
    "Plainly states that no spell can currently be studied. It must not offer an unavailable spell or claim "
    "spell training began. Arcane Study is the name of a training program, not a spell: saying that program is "
    "available while clearly saying it has no eligible spells is valid and is not a spell offer. Honest physical "
    "training or future spell possibilities are allowed."
)
_ELIGIBLE_SPELL_INTENT = (
    "Offers at least one spell, and only spells from the exhaustive actual eligible choices: {choices}. "
    "Human-readable names that clearly correspond to those ids are allowed. It must not say that no spell is "
    "currently available."
)

scenarios("features/m1_5_training_cycle.feature")

# The `harness` fixture (per-scenario event loop on a background thread + run_sync)
# lives in conftest.py, shared with the M1.6 errand acceptance test.


async def _start_training_session(harness: SimpleNamespace, chat_ctx: ChatContext | None = None) -> None:
    session_data = SessionData(player_id="player_1", location_id="accord_training_hall", room=make_mock_room())
    session = AgentSession(
        # Parity with agent.py: strict schemas are interim-OFF. At the plugin default this
        # dispatch session 400s before any turn runs ("compiled grammar is too large").
        llm=anthropic.LLM(model=_AGENT_MODEL, caching="ephemeral", _strict_tool_schema=False),
        # Parity with agent.py again: the cap decides where livekit silently truncates a
        # tool chain, so a harness on the plugin default would exercise a different ceiling
        # than production and prove nothing about it.
        max_tool_steps=5,
        userdata=session_data,
    )
    await session.start(create_dispatch_agent(chat_ctx=chat_ctx))
    harness.state["session"] = session
    harness.state["judge_llm"] = anthropic.LLM(model=_AGENT_MODEL)


async def _seed_training_player(harness: SimpleNamespace, *, class_: str, level: int) -> None:
    pool = await db.get_pool()
    await seed_player(
        pool,
        player_id="player_1",
        class_=class_,
        location_id="accord_training_hall",
    )
    await pool.execute(
        "UPDATE players SET data = jsonb_set(data, '{level}', $2::jsonb) WHERE player_id = $1",
        "player_1",
        str(level),
    )
    await clear_training_activities(pool, "player_1")
    await _start_training_session(harness)


@given("a player at the training hall with no active training")
def _given_no_active_training(harness: SimpleNamespace) -> None:
    async def _setup() -> None:
        pool = await db.get_pool()
        await seed_player(pool, player_id="player_1")
        await clear_training_activities(pool, "player_1")
        await _start_training_session(harness)

    harness.run_sync(_setup())


@given("a martial player at the training hall with no active training")
def _given_martial_player(harness: SimpleNamespace) -> None:
    harness.run_sync(_seed_training_player(harness, class_="warrior", level=2))


@given("an eligible caster at the training hall with no active training")
def _given_eligible_caster(harness: SimpleNamespace) -> None:
    harness.run_sync(_seed_training_player(harness, class_="mage", level=3))


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
    """Judge the LAST assistant message of the turn, wherever it sits in the event order.

    The selection lives in ``_judged_turn`` because it is pure and has been wrong twice: its
    falsifiers run in the fast lane, not only when a real turn is paid for (constraint 1).
    """
    result = harness.state["result"]
    message = result.expect[last_assistant_message_index(result.events)].is_message(role="assistant")
    harness.run_sync(message.judge(harness.state["judge_llm"], intent=intent))


@then("the agent narrates that the training has begun")
def _narrates_begun(harness: SimpleNamespace) -> None:
    _judge(harness, "Tells the player their training has begun")


@then("the agent narrates the training continuing")
def _narrates_continuing(harness: SimpleNamespace) -> None:
    result = harness.state["result"]

    async def _assert_midpoint() -> None:
        async def _evaluate(index: int, intent: str) -> None:
            message = result.expect[index].is_message(role="assistant")
            await message.judge(harness.state["judge_llm"], intent=intent)

        await assert_training_midpoint(
            result,
            _evaluate,
            transition_intent="Tells the player their training continues into its second half",
        )

    harness.run_sync(_assert_midpoint())


@then("the agent narrates that a cycle is already in progress")
def _narrates_in_progress(harness: SimpleNamespace) -> None:
    _judge(harness, _ACTIVE_CYCLE_INTENT)


@then("the returned spell programs have no eligible choices")
def _spell_programs_are_ineligible(harness: SimpleNamespace) -> None:
    payload = training_program_result(harness.state["result"])
    rows = spell_programs(payload)
    assert all(not row["studiable_spell_ids"] for row in rows), rows


@then("the returned spell programs include eligible choices")
def _spell_programs_are_eligible(harness: SimpleNamespace) -> None:
    payload = training_program_result(harness.state["result"])
    pairs = eligible_spell_pairs(payload)
    assert pairs, "the real training query returned no eligible spell choices"
    harness.state["eligible_spell_pairs"] = pairs


@then("no training starts during the inquiry")
def _no_training_starts(harness: SimpleNamespace) -> None:
    assert_no_training_start(harness.state["result"])


@then("the agent plainly says no spell can be studied now")
def _says_no_spell_can_be_studied(harness: SimpleNamespace) -> None:
    _judge(harness, _NO_SPELL_INTENT)


@then("the agent offers an eligible returned spell")
def _offers_eligible_spell(harness: SimpleNamespace) -> None:
    pairs = harness.state["eligible_spell_pairs"]
    choices = sorted({spell_id for _, spell_id in pairs})
    _judge(harness, _ELIGIBLE_SPELL_INTENT.format(choices=choices))


@when("the player consents to one offered spell")
def _player_consents_to_offered_spell(harness: SimpleNamespace) -> None:
    pair = offered_spell(harness.state["result"], harness.state["eligible_spell_pairs"])
    harness.state["consented_spell_pair"] = pair[:2]
    _player_says(harness, f"Yes, begin training {pair[2]}")


@then("the selected returned spell training begins")
def _selected_spell_training_begins(harness: SimpleNamespace) -> None:
    start = training_start(harness.state["result"], {harness.state["consented_spell_pair"]})

    async def _read_persisted() -> dict[str, Any] | None:
        return await db_training.get_training_activity(start.activity_id)

    row = harness.run_sync(_read_persisted())
    assert_persisted_training(row, start)


def _synthetic_message(text: str):
    result: RunResult = RunResult(user_input="test", output_type=None)
    result._item_added(llm.ChatMessage(role="assistant", content=[text]))
    return result.expect[0].is_message(role="assistant")


async def _judge_synthetic(text: str, intent: str) -> None:
    await _synthetic_message(text).judge(anthropic.LLM(model=_AGENT_MODEL), intent=intent)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        pytest.param(
            "You've already got a training cycle underway. You'll need to finish or resolve what you're "
            "working on before you can start something new. What's the focus of your current training?",
            id="captured-follow-up",
        ),
        pytest.param(
            "A training cycle is already underway, so another cannot begin until it finishes.",
            id="direct-valid",
        ),
        pytest.param(
            "Your current training cycle must resolve before another can start. Would you like a progress recap?",
            id="compatible-follow-up",
        ),
    ],
)
async def test_active_cycle_judge_accepts_valid_responses(response: str) -> None:
    await _judge_synthetic(response, _ACTIVE_CYCLE_INTENT)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        pytest.param("You cannot start another training cycle right now.", id="omits-existing-cycle"),
        pytest.param(
            "A training cycle is underway, but we can start a second one before it finishes.",
            id="permits-second-cycle",
        ),
        pytest.param(
            "No training cycle is underway, so there is nothing blocking a new one.",
            id="contradicts-result",
        ),
    ],
)
async def test_active_cycle_judge_rejects_invalid_responses(response: str) -> None:
    with pytest.raises(AssertionError):
        await _judge_synthetic(response, _ACTIVE_CYCLE_INTENT)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("response", "intent"),
    [
        pytest.param(
            "No spell can be studied right now, though physical training remains available.",
            _NO_SPELL_INTENT,
            id="valid-empty-eligibility",
        ),
        pytest.param(
            "You have Arcane Study available right now — that's with Scholar Emris — but there are no spells "
            "you can study in that program at the moment. The path forward there isn't open yet. You could "
            "focus on physical training instead.",
            _NO_SPELL_INTENT,
            id="captured-empty-program",
        ),
        pytest.param(
            "You've got Arcane Study available through Scholar Emris, but there aren't any spells open for you "
            "to learn right now. You could still work on physical training though.",
            _NO_SPELL_INTENT,
            id="captured-program-is-not-spell",
        ),
        pytest.param(
            "Counterspell is available for you to study now. Would you like to begin?",
            _ELIGIBLE_SPELL_INTENT.format(choices=["arcane_counterspell"]),
            id="valid-returned-offer",
        ),
    ],
)
async def test_training_narration_judge_accepts_valid_responses(response: str, intent: str) -> None:
    await _judge_synthetic(response, intent)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("response", "intent"),
    [
        pytest.param(
            "Arcane Fireball is available for you to study now.",
            _NO_SPELL_INTENT,
            id="invented-martial-offer",
        ),
        pytest.param(
            "There are no spells available for you to study.",
            _ELIGIBLE_SPELL_INTENT.format(choices=["arcane_counterspell"]),
            id="eligible-blanket-refusal",
        ),
    ],
)
async def test_training_narration_judge_rejects_eligibility_faults(response: str, intent: str) -> None:
    with pytest.raises(AssertionError):
        await _judge_synthetic(response, intent)
