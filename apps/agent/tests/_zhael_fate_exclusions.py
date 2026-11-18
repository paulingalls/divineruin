from types import SimpleNamespace
from unittest.mock import Mock, patch

from _patron_engine_fixtures import configure
from _zhael_fate_fixtures import attack, defend, game_tools
from acceptance._capstone_helpers import _build_state, _d20, _enemy
from acceptance.seeds import seed_player
from acceptance.test_inventory_taint import seed_stack
from acceptance.test_kaelen_iron_resolve_capstone import required_player
from test_aelora_gift import _live_party

import db_mutations
from activate_tools import activate
from activity_tools import begin_activity
from check_tools import check
from choice_tools import select
from combat_turn import declare_phase, resolve_phase
from conditions import has_condition
from mode_tools import enter_mode


async def initiative(world):
    pid = world.ids[0]
    await seed_player(world.pool, player_id=pid, class_="mage")
    await configure(world, "zhael", "mage", speed=30)
    await configure(world, "aelora", "mage", index=1, speed=30)
    session = world.ctx.userdata
    try:
        with patch("combat_resolution.dice_roll", return_value=_d20(12)) as dice:
            _, result = await game_tools(session, enter_mode)(
                "enter_mode",
                mode="combat",
                encounter_id="fragment_shadeling",
                encounter_description="An ambush",
            )
        assert len(result["initiative_order"]) >= 2
        assert {actor["roll"] for actor in result["initiative_order"]} == {12}
        assert dice.call_count == len(result["initiative_order"])
        assert "fate_offer" not in result and session.fate_offer is None
    finally:
        if session.combat_state is not None:
            await db_mutations.delete_combat_state(session.combat_state.combat_id)


async def shove(world):
    pid = world.ids[0]
    await configure(world, "zhael", "mage")
    foe = _enemy("foe", 30)
    state = _build_state(pid, pid, [foe])
    session = world.ctx.userdata
    session.combat_state = state
    call = game_tools(session, declare_phase, resolve_phase)
    try:
        await call(
            "declare_phase",
            declarations=[
                {"kind": "maneuver", "actor_id": pid, "target_id": foe.id},
                defend(foe.id),
            ],
        )
        roller = SimpleNamespace(randint=Mock(side_effect=[14, 11]))
        with patch("combat_maneuver.random", roller):
            result = await call("resolve_phase")
        packet = result["packets"][0]
        assert packet["shove"] == "knocked_prone" and roller.randint.call_count == 2
        assert "fate_offer" not in result and session.fate_offer is None
        assert has_condition(required_player(session.combat_state, foe.id).conditions, "prone")
    finally:
        await db_mutations.delete_combat_state(state.combat_id)


async def reaction_contest(world):
    host = world.ids[0]
    await configure(world, "zhael", "diplomat", stamina={"current": 20, "max": 20})
    foe = _enemy("foe", 30)
    foe.attributes["wisdom"] = 10
    state = _build_state(host, host, [foe])
    player = required_player(state, host)
    player.attributes["charisma"] = 10
    ability = "diplomat_objection"
    player.has_reaction_ability, player.reaction_ids = True, [ability]
    session = world.ctx.userdata
    session.combat_state = state
    lifecycle = _live_party(session, *world.ids)
    call = game_tools(session, declare_phase, resolve_phase, activate)
    try:
        await call("declare_phase", declarations=[defend(host), {**attack(foe.id, host), "action": "Scimitar"}])
        await call("resolve_phase")
        window = (await call("resolve_phase"))["next"]["waiting_on"]
        assert window["stage"] == "pre_roll"
        with session._bind_authenticated_actor(host, 1, lifecycle.require_authorized):
            await call("activate", id=ability)
        roller = SimpleNamespace(randint=Mock(side_effect=[14, 11]))
        with patch("combat_reaction_contest.random", roller):
            result = await call("resolve_phase")
        assert result["packets"][0]["mechanical_effect"] == "action_hesitated"
        assert roller.randint.call_count == 2 and session.fate_offer is None and "fate_offer" not in result
    finally:
        await lifecycle.aclose()
        await db_mutations.delete_combat_state(state.combat_id)


async def experimentation(world):
    pid = world.ids[0]
    await configure(world, "zhael", "mage")
    await seed_stack(world.pool, pid, "oak_wood", 1, False)
    session = world.ctx.userdata
    roller = SimpleNamespace(randint=Mock(return_value=11))
    try:
        with patch("experimentation.random", SimpleNamespace(Random=lambda: roller)):
            result = await game_tools(session, begin_activity)(
                "begin_activity",
                activity={
                    "kind": "experiment",
                    "materials": [{"material_id": "oak_wood", "quantity": 1}],
                    "intended_output": "club_wooden",
                },
            )
        assert result["roll"] == 11 and result["outcome"] in {"failure", "success"}
        assert roller.randint.call_count == 1 and "fate_offer" not in result and session.fate_offer is None
        assert (
            await world.pool.fetchval(
                "SELECT count(*) FROM player_inventory WHERE player_id=$1 AND item_id='oak_wood'", pid
            )
            == 0
        )
    finally:
        await world.pool.execute("DELETE FROM player_inventory WHERE player_id=$1 AND item_id='oak_wood'", pid)


async def echo_and_narrative(world):
    await configure(world, "zhael", "mage")
    session = world.ctx.userdata
    call = game_tools(session, activate, select, check)
    with patch("dice.roll", side_effect=[_d20(8), _d20(16)]) as dice:
        result = await call("activate", id="arcane_bolt")
        choice = result["pending_choice"]
        assert choice["kind"] == "hollow_echo" and "fate_offer" not in result
        assert dice.call_count == 2
        selected = await call("select", choice_id=choice["choice_id"], option="second")
        assert selected["hollow_echo"]["band"] == choice["options"][1]["band"]
    free_roll = await call("check", roll={"kind": "dice", "notation": "1d20"})
    assert 1 <= free_roll["total"] <= 20 and "fate_offer" not in free_roll and session.fate_offer is None
