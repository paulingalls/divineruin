"""Unravel Fate refuses to cross a durable timed oath's history."""

import pytest
from _zhael_fate_fixtures import attack, defend
from _zhael_unravel_fixtures import activate, cached, durable, opening, patch_player
from _zhael_unravel_fixtures import unravel as unravel
from acceptance.test_paladin_oath_swear import stored, timed
from livekit.agents.llm import ToolError
from test_encounter_facts_damage import dice
from voice_condition_fixtures import participant
from weapon_fixtures import LONGSWORD

import combat_spatial


async def swear(fight, deadline: int, *, actor=None, objective="defeat_target") -> dict:
    offer = (await fight.call("query_info", kind="combat", actor=actor))["oath_choice"]
    target = offer["eligible_targets"][objective][0]
    return await fight.call(
        "select", actor=actor, **timed(offer, objective=objective, target=target, deadline=deadline)
    )


async def end_round(fight, next_round: int, action=None) -> dict:
    state = fight.session.combat_state
    if action is None:
        await fight.declare()
    else:
        await fight.declare(action, *(defend(p.id) for p in state.participants if p.id != action["actor_id"]))
    change = {}
    for _ in range(10):
        with dice(*([19] if action is not None else [])):
            result = await fight.call("resolve_phase")
        if changes := result.get("oath_changes"):
            [change] = changes
        if result["round"] == next_round and result["beat"] == "declaration":
            await fight.reload()
            return change
    raise AssertionError("Round did not wrap")


async def assert_unchanged_refusal(fight, reason: str) -> None:
    before, memory = await durable(fight), cached(fight)
    refusal = None
    try:
        await activate(fight)
    except ToolError as error:
        refusal = str(error)
    assert await durable(fight) == before
    assert cached(fight) == memory
    assert refusal is not None and reason in refusal


async def test_registration_touches_current_and_previous_openings(unravel) -> None:
    await patch_player(unravel, unravel.ids[0], **{"class": "paladin"})
    await opening(unravel, 1)
    oath = await swear(unravel, 8)
    await unravel.reload()
    await assert_unchanged_refusal(unravel, "sworn Promised Hour")
    await end_round(unravel, 3)
    await assert_unchanged_refusal(unravel, "sworn Promised Hour")
    await end_round(unravel, 4)
    assert (await activate(unravel))["round"] == 3
    book = await stored(unravel.ids[0])
    assert book is not None
    [record] = book["records"]
    assert (record["id"], record["round_number"], record["status"]) == (oath["oath_id"], 2, "active")


@pytest.mark.parametrize(
    ("event", "control"),
    [
        ("deadline", "next_round"),
        ("deadline", "departed"),
        ("deadline", "other_encounter"),
        ("defeat", "next_round"),
        ("ally_fell", "next_round"),
    ],
)
async def test_transition_blocks_exactly_the_round_it_settled(unravel, event, control) -> None:
    hero, ally = unravel.ids
    owner = ally if control == "departed" else hero
    spent = {"zhael_fates_thread": {"spent": True}, "zhael_lucky": {"spent": True}}
    await patch_player(unravel, hero, patron_gifts=spent)
    await patch_player(
        unravel,
        owner,
        **{"class": "paladin", "patron_gifts": spent, "divine_favor": {"patron": "zhael", "level": 90, "max": 100}},
    )
    await opening(unravel, 0)
    objective = "keep_ally_standing" if event == "ally_fell" else "defeat_target"
    oath = await swear(unravel, 2, actor=owner, objective=objective)
    await end_round(unravel, 2)
    action = None
    state = unravel.session.combat_state
    if event != "deadline":
        victim = participant(state, oath["target_id"])
        striker = hero if event == "defeat" else "mawling_1"
        opponent = participant(state, striker)
        victim.hp_current, victim.temp_hp = 1, 0
        combat_spatial.place(state, victim.id, combat_spatial.position(state.spatial, striker))
        name = LONGSWORD["name"] if event == "defeat" else opponent.action_pool[0]["name"]
        action = attack(striker, victim.id, name)
    change = await end_round(unravel, 3, action)
    expected = "fulfilled" if event == "defeat" else "lapsed"
    assert (change["oath_id"], change["new_status"], change["round_number"]) == (oath["oath_id"], expected, 2)
    if control == "departed":
        unravel.session.party.members = [m for m in unravel.session.party.members if m.player_id != owner]
        assert owner in state.round_checkpoints[-1]["players"]
    book = await stored(owner)
    await assert_unchanged_refusal(unravel, "settled Promised Hour")
    if control == "other_encounter":
        await unravel.call("end_combat", outcome="fled")
        await opening(unravel, 1)
        assert (await activate(unravel))["round"] == 1
    else:
        await end_round(unravel, 4)
        assert (await activate(unravel))["round"] == 3
    assert await stored(owner) == book
