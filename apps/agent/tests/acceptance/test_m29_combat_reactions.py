"""The combat scenario the real LLM never ran (M29, story-022).

Two things no schema walk can give, and story-019 (note be977959) is why: the walk certified a
green the live API refused, because "a walk over an emitted artifact is a proxy for a boundary".

(a) A REAL Haiku turn filling ``declare_phase``'s discriminated union — validated by
``TypeAdapter(list[DeclPayload])``, the same annotation the tool is compiled from, against the
model's own bytes off the wire. No payload here is constructed by the test.
(b) The restored Beat-3 interrupt loop end to end: the DM narrates a held enemy blow, the player
shouts a reaction in conversational time, and the reaction halves the damage BEFORE it is written.

PRODUCTION PARITY IS THE POINT (constraint 9). Model, ``caching="ephemeral"``,
``_strict_tool_schema=False`` and a literal ``max_tool_steps=5`` all match agent.py; a harness on
the plugin defaults exercises a different ceiling than production and proves nothing about it.
``tests/test_strict_tool_budget.py`` AST-scans this file for both.

ONE DELIBERATE DIVERGENCE, stated rather than hidden: ``combat_prompts.py:15`` tells the DM to
decide each enemy's action "from its tactics", and
  ``tactics`` occurs NOWHERE else in the repo — not in content, not in any producer. Measured:
  without it, Haiku omitted the enemy from ``declare_phase`` entirely in ~1 run in 8, declaring the
  player alone for every round of the fight, so no enemy action was ever held and no reaction
  window ever opened.

Supplying tactics makes this green easier than production on that axis, and nowhere else.

``session.run()`` skips ``on_user_turn_completed``, so the per-turn hot layer is REPRODUCED here
(``_apply_hot_line``) rather than diverged from — see that function for why it is load-bearing.

Determinism: the two dice seams are patched for the whole scenario (``harness.stack``) so the real
resolvers, the real hold pump and the real reaction effect run end to end against a forced blow.
"""

from __future__ import annotations

import json
import os
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch
from uuid import uuid4

import pytest
from acceptance._capstone_helpers import _build_state, _d20, _damage_die, _enemy, _start_combat
from acceptance._m29_guards import (
    DECLARATIONS,
    TRUNCATION_WARNING,
    assert_halved,
    assert_within_ceiling,
    capture_livekit_warnings,
)
from acceptance._m29_transcript import (
    calls,
    output_for,
    reaction_packet,
    resolve_packets,
    tool_names,
    turn_shapes,
)
from livekit.agents.llm import ChatContext, ChatMessage
from livekit.agents.voice import AgentSession
from livekit.plugins import anthropic
from pytest_bdd import given, parsers, scenarios, then, when
from sample_fixtures import make_mock_room

import abilities
import db
import db_mutations
import reaction_windows
from combat_agent import create_combat_agent
from combat_support import _participant_roster
from session_data import SessionData

pytestmark = [
    # The skipif is the not-opted-in path; REQUIRE_REAL_LLM=1 suppresses it so the real_llm
    # fixture fails the lane LOUD instead of keeping a false green (story-019 AC1).
    pytest.mark.skipif(
        not os.environ.get("ANTHROPIC_API_KEY") and not os.environ.get("REQUIRE_REAL_LLM"),
        reason="LLM acceptance runs require ANTHROPIC_API_KEY (ADR 0003 pre-sprint-close schedule)",
    ),
    pytest.mark.real_llm,
]

# Production gameplay model (agent.py) — acceptance runs at production parity.
_AGENT_MODEL = "claude-haiku-4-5-20251001"

_PLAYER_ID = "m29_rogue"
_ENEMY_ID = "mawling_1"
_DODGE = "rogue_uncanny_dodge"
# What a player says next depends on what the machine is waiting on, and ONE utterance cannot serve
# both pauses — each wording below was measured against the wrong state and failed there:
#   "I hold my ground — what happens?"      the DM read a DEFEND declaration and opened a new round.
#   "And the mawling — what is it doing?"   declined nothing, so the DM re-narrated the open window.
#   "I've no reaction for that — what happens?"  declined the round's reaction outright, so the DM
#       closed the pre-roll window AND the post-roll one in the same turn and wrote the blow — the
#       pause this scenario exists to reach never survived a turn boundary.
# Neither constant carries a player ACTION, because anything that does gets declared as one. The
# pre-roll wording declines only THIS window: Uncanny Dodge fires on_hit, so the rogue genuinely
# has nothing to spend before the roll and everything to spend after it.
_DECLINE_WINDOW = "Not yet — I want to see whether the blow lands first."
_BRING_IT_FORWARD = "Come on then — what does the mawling do?"

scenarios("features/m29_combat_reactions.feature")


def _entry_context(state) -> ChatContext:
    """The combat-entry system message, mirroring combat_init's handoff — plus tactics.

    combat_init's handoff ChatContext carries the scene line and ``Combatants: <_participant_roster>``;
    ``session.run()`` performs no handoff, so both ride the entry context here. Only ``tactics`` is
    hand-fed — the module docstring's one divergence.
    """
    roster = _participant_roster(state.participants)
    for summary in roster:
        if summary["type"] == "enemy":
            summary["tactics"] = f"Attacks the nearest living enemy with {summary['actions'][0]} every round."
    ctx = ChatContext()
    ctx.add_message(
        role="system",
        content=(
            "Combat begins: a mawling lunges out of the dark, claws scraping stone. "
            "Location: Accord Guild Hall. "
            f"Combatants: {json.dumps(roster)}"
        ),
    )
    # Beat 1's FIRST HALF, which production runs as its own turn and a harness would otherwise
    # skip: start_combat hands back, the DM narrates the opening and asks "What do you do?", and
    # only THEN does the player answer. Without it the player's opening line arrives before the
    # question, and the DM reasonably spends its turn opening the scene and asking — measured, no
    # tool call at all in 3 of 9 runs, which reds scenarios 1 and 3 for a reason neither is about.
    ctx.add_message(
        role="assistant",
        content=["Claws scrape stone. The mawling comes out of the dark low and fast. What do you do?"],
    )
    return ctx


async def _db_hp(player_id: str) -> int:
    pool = await db.get_pool()
    row = await pool.fetchrow("SELECT (data->'hp'->>'current')::int AS hp FROM players WHERE player_id = $1", player_id)
    return row["hp"]


_HOT_PREFIX = "[COMBAT Round"


async def _apply_hot_line(agent, utterance: str) -> None:
    """Put THIS turn's combat hot line in front of the model, exactly one at a time.

    ``session.run()`` reaches ``generate_reply`` directly and never calls
    ``on_user_turn_completed`` (measured at test_combat_cache_prefix.py:76-79), so CombatAgent's
    per-turn hot layer — the round and every participant's HP status — would be absent from a
    harness turn. It is not cosmetic: without it the DM declared the PLAYER ONLY in 2 of 6 measured
    runs, never held an enemy action, and no reaction window ever opened.

    Production hands ``on_user_turn_completed`` a throwaway copy and keeps none of it
    (agent_activity.py:2211-2217). ``run()`` takes no chat_ctx, so the line is committed to the
    agent instead — with the previous turn's line dropped first, or the model would read a stack of
    stale rounds production never shows it.
    """
    turn_ctx = agent.chat_ctx.copy()
    turn_ctx.items = [
        item
        for item in turn_ctx.items
        if not (isinstance(item, ChatMessage) and str(item.text_content or "").startswith(_HOT_PREFIX))
    ]
    await agent.on_user_turn_completed(turn_ctx, ChatMessage(role="user", content=[utterance]))
    await agent.update_chat_ctx(turn_ctx)


def _turn(harness: SimpleNamespace, utterance: str) -> Any:
    """One player turn against the live session, recorded for the assertions that follow."""
    session = harness.state["session"]

    async def _run() -> Any:
        await _apply_hot_line(session.current_agent, utterance)
        return await session.run(user_input=utterance)

    # session.run() builds its RunResult eagerly (needs a running loop), so it runs on the
    # loop thread rather than the main thread.
    result = harness.run_sync(_run())
    harness.state["turns"].append(result)
    return result


def _nudge_until(harness: SimpleNamespace, ready, *, attempts: int, unmet) -> None:
    """Run bounded nudge turns until ``ready()`` holds — checked BEFORE the first and AFTER the last.

    A ``for/else`` that only tests at the top of the loop reports failure on a state the final turn
    had already reached; that is exactly how this guard first "failed" against a fault injection it
    had in fact driven correctly. ``unmet`` is a callable so the diagnostic reads the FINAL state.

    The utterance is chosen from what the machine is PAUSED ON, not fixed: see the two constants.
    """
    for attempt in range(attempts + 1):
        if ready():
            return
        if attempt == attempts:
            break
        state = harness.state["sd"].combat_state
        _turn(harness, _DECLINE_WINDOW if state.open_window is not None else _BRING_IT_FORWARD)
    raise AssertionError(unmet())


@given("a rogue in combat against a mawling")
def _given_rogue_in_combat(harness: SimpleNamespace) -> None:
    state = _build_state(f"combat_m29_{uuid4().hex[:8]}", _PLAYER_ID, [_enemy(_ENEMY_ID, hp=30)])
    session_data = SessionData(player_id=_PLAYER_ID, location_id="accord_guild_hall", room=make_mock_room())

    async def _setup() -> None:
        pool = await db.get_pool()
        # activate and the reaction packet both read the ability catalog.
        await abilities.load_abilities()
        # player_class="rogue": owns_ability gates a reaction on players.data.class matching the
        # ability's archetype, and Uncanny Dodge costs 2 Stamina the default seed has no pool for.
        await _start_combat(pool, _PLAYER_ID, state, SimpleNamespace(userdata=session_data), player_class="rogue")
        session = AgentSession(
            llm=anthropic.LLM(model=_AGENT_MODEL, caching="ephemeral", _strict_tool_schema=False),
            max_tool_steps=5,
            userdata=session_data,
        )
        await session.start(create_combat_agent(chat_ctx=_entry_context(state)))
        harness.state.update(session=session, sd=session_data, turns=[], handles=[])
        session.on("speech_created", lambda ev: harness.state["handles"].append(ev.speech_handle))

    harness.run_sync(_setup())
    harness.stack.callback(lambda: harness.run_sync(db_mutations.delete_combat_state(state.combat_id)))
    harness.state["warnings"] = capture_livekit_warnings(harness.stack)
    # d20 15 + the mawling's +2 (attribute 0 + level-1 proficiency 2) = 17 vs the player's AC 14:
    # a hit, and not a nat-20, whose doubled dice would change the figure being halved.
    harness.stack.enter_context(patch("check_resolution.dice_roll", return_value=_d20(15)))
    # A real 1d6 can roll 1, and 1 // 2 == 0 makes "halved" indistinguishable from "missed".
    harness.stack.enter_context(patch("check_resolution_attack.dice_roll", return_value=_damage_die(6)))


@given("the session's tool-step ceiling is lowered to 1")
def _given_ceiling_lowered(harness: SimpleNamespace) -> None:
    """Lower the LIVE ceiling through the public AgentSession.options property.

    Not a ``max_tool_steps=1`` constructor literal: test_strict_tool_budget AST-scans this file
    and demands a literal >= 5 at every construction site. Lowering it after construction keeps
    that pin honest and still exercises the real vendor loop.
    """
    harness.state["session"].options.max_tool_steps = 1


@when(parsers.parse('the player says "{utterance}"'))
def _player_says(harness: SimpleNamespace, utterance: str) -> None:
    _turn(harness, utterance)


@when("the DM brings the mawling's blow forward until the strike is rolled")
def _bring_the_blow_forward(harness: SimpleNamespace) -> None:
    sd = harness.state["sd"]

    def _at_post_roll() -> bool:
        window = sd.combat_state.open_window
        return window is not None and window["stage"] == reaction_windows.POST_ROLL

    _nudge_until(
        harness,
        _at_post_roll,
        attempts=3,
        unmet=lambda: (
            f"never reached the post-roll pause: beat={sd.combat_state.beat} "
            f"held={len(sd.combat_state.held_actions)} window={sd.combat_state.open_window} "
            # Per turn, because "the DM did nothing" and "the DM narrated instead" look identical
            # in a flat tool list and have opposite fixes.
            f"turns={turn_shapes(harness.state['turns'])} "
            # The declarations, because one usual cause is an enemy action that opens no window:
            # combat_hold._opens_windows pauses only for a held action that NAMES A TARGET.
            f"declared={[c.arguments for c in calls(harness.state['turns'], 'declare_phase')]}"
        ),
    )

    # The premise, captured AT the pause and before the dodge turn. Without it a missed blow or a
    # window at the wrong stage would leave hp_current unchanged and every halving assertion below
    # would pass on a fight that never landed.
    window = sd.combat_state.open_window
    attack = sd.combat_state.held_actions[0]["roll"]["attack_result"]
    assert "on_hit" in window["triggers"], f"the post-roll window offers {window['triggers']}"
    assert attack["hit"] is True, "the held blow missed — a halved figure would be indistinguishable"
    # What the DM was HANDED at the pause, not engine state: the producer of the id it must pass
    # (constraint 6). A DM that guesses, is refused, and looks the id up still passes the activate step.
    turns = harness.state["turns"]
    paused_on = [o for o in (output_for(turns, c) for c in calls(turns, "resolve_phase")) if not o.is_error][-1]
    offered = [reaction["id"] for reaction in json.loads(paused_on.output)["next"]["waiting_on"]["reactions"]]
    assert _DODGE in offered, f"the post-roll pause offered the DM {offered}"
    harness.state["premise"] = {
        "window_id": window["id"],
        "full": attack["damage"],
        "hp_before": sd.combat_state.get_participant(_PLAYER_ID).hp_current,
    }


@then(parsers.parse('the agent calls the "{tool_name}" tool'))
def _agent_calls_tool(harness: SimpleNamespace, tool_name: str) -> None:
    assert calls(harness.state["turns"], tool_name), (
        f"no {tool_name} call; the turn called {tool_names(harness.state['turns'])}"
    )


@then("every declaration it sent is a well-formed variant of the declaration union")
def _declarations_are_well_formed(harness: SimpleNamespace) -> None:
    declared = calls(harness.state["turns"], "declare_phase")
    assert declared, f"no declare_phase call; the turn called {tool_names(harness.state['turns'])}"
    accepted: list[list[dict]] = []
    for call in declared:
        payload = json.loads(call.arguments)["declarations"]
        # EVERY call, not just an accepted one: the AC is about the union the model filled, and a
        # malformed payload the engine happened to refuse is exactly the defect it names.
        DECLARATIONS.validate_python(payload)
        if not output_for(harness.state["turns"], call).is_error:
            accepted.append(payload)
    assert accepted, f"the engine refused every declaration the model sent: {[c.arguments for c in declared]}"
    assert any(d["kind"] == "attack" and d["actor_id"] == _PLAYER_ID for p in accepted for d in p), accepted


@then(parsers.parse('the agent calls "activate" with the id "{ability_id}"'))
def _agent_activates(harness: SimpleNamespace, ability_id: str) -> None:
    spent = [c for c in calls(harness.state["turns"], "activate") if json.loads(c.arguments).get("id") == ability_id]
    assert spent, f"no activate({ability_id}); the turn called {tool_names(harness.state['turns'])}"
    output = output_for(harness.state["turns"], spent[-1])
    assert output.is_error is False, f"activate({ability_id}) was refused: {output.output}"


@then("the reaction packet reports the damage halved")
def _reaction_packet_reports_halved(harness: SimpleNamespace) -> None:
    sd = harness.state["sd"]
    # The window the DM was paused on has to CLOSE for the reaction to take effect; the combat
    # prompt tells the DM to call resolve_phase right after activate. One bounded nudge covers the
    # turn that ends on the activate — the AC is about the figure written, not which turn wrote it.
    _nudge_until(
        harness,
        lambda: reaction_packet(harness.state["turns"]) is not None,
        attempts=2,
        unmet=lambda: (
            f"the reaction window never closed: window={sd.combat_state.open_window} "
            f"held={len(sd.combat_state.held_actions)} tools={tool_names(harness.state['turns'])}"
        ),
    )
    packet = reaction_packet(harness.state["turns"])
    assert packet is not None  # _nudge_until returned, so the window closed and the packet exists
    premise = harness.state["premise"]
    assert packet["ability_id"] == _DODGE, packet
    # Stage + window id are the engine's own record that the spend landed INSIDE the open
    # post-roll window — proven by what it answered, not by the order the calls happen to appear in.
    assert packet["stage"] == reaction_windows.POST_ROLL, packet
    assert packet["window_id"] == premise["window_id"], (
        f"the reaction answered {packet['window_id']}, not the window open at the pause ({premise['window_id']})"
    )
    assert packet["mechanical_effect"] == "damage_halved", packet


@then("the halved figure is what reached hp_current")
def _halved_figure_reached_hp(harness: SimpleNamespace) -> None:
    sd = harness.state["sd"]
    premise = harness.state["premise"]
    blows = [p for p in resolve_packets(harness.state["turns"]) if p.get("actor_id") == _ENEMY_ID and "damage" in p]
    assert len(blows) == 1, f"expected exactly one resolved mawling blow, got {blows}"
    assert blows[0]["damage"] == premise["full"] // 2, (
        f"the blow the DM was handed still reports {blows[0]['damage']} of {premise['full']} damage"
    )
    assert_halved(
        premise["hp_before"],
        premise["full"],
        sd.combat_state.get_participant(_PLAYER_ID).hp_current,
        harness.run_sync(_db_hp(_PLAYER_ID)),
    )


@then("no turn was truncated at the tool-step ceiling")
def _no_turn_truncated(harness: SimpleNamespace) -> None:
    assert_within_ceiling(harness.state["handles"], harness.state["warnings"], max_tool_steps=5)


@then("the turn was truncated at the tool-step ceiling")
def _turn_truncated(harness: SimpleNamespace) -> None:
    warnings = harness.state["warnings"]
    # Drive on the VENDOR'S OWN signal, bounded. Truncation needs two consecutive tool-calling
    # generations; measured over 7 runs, one turn produced only one and the ceiling was never
    # reached — the fault injection simply failed to inject. The claim is that a lowered ceiling
    # truncates, not that the first turn does, so the nudges are bounded rather than the intent
    # loosened (note 02283f04).
    _nudge_until(
        harness,
        lambda: any(TRUNCATION_WARNING in w for w in warnings),
        attempts=2,
        unmet=lambda: (
            "no reply was regenerated with tool_choice='none' at the lowered ceiling — the fault "
            f"injection did not inject: steps={[h.num_steps for h in harness.state['handles']]} "
            f"tools={tool_names(harness.state['turns'])} warnings={warnings}"
        ),
    )
    # ...and the step arm reds INDEPENDENTLY, matched on its own message. The two arms cannot
    # falsify each other: livekit increments num_steps AFTER emitting the warning, so a real
    # truncation always breaks the step assertion too — which is why a scenario resting on the step
    # arm alone would stay green with the log capture entirely broken (constraint 1).
    with pytest.raises(AssertionError, match="are permitted"):
        assert_within_ceiling(harness.state["handles"], warnings, max_tool_steps=1)
