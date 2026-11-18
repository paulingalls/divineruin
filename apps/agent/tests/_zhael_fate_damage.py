from unittest.mock import patch

import pytest
from _patron_engine_fixtures import configure
from _unbound_path_fixtures import row
from _zhael_fate_fixtures import attack, defend, game_tools
from acceptance._capstone_helpers import _build_state, _d20, _damage_die, _enemy
from acceptance.test_kaelen_iron_resolve_capstone import required_player
from livekit.agents.llm import ToolError
from test_aelora_gift import _live_party

import db_mutations
from activate_tools import activate
from combat_end import end_combat
from combat_turn import declare_phase, resolve_phase
from conditions import apply_condition, has_condition
from creature_combat_loader import load_creature_enemy
from db_mutations_concentration import update_player_concentration
from session_data import SessionData


async def inner_fire(world, reload):
    await configure(world, "zhael", "mage", race="draethar", hp={"current": 100, "max": 100})
    pid = world.ids[0]
    state = _build_state(pid, pid, [_enemy("foe", 30)])
    session = world.ctx.userdata
    session.combat_state = state
    required_player(state, pid).conditions = apply_condition([], "blessed", source="divine_bless")
    session.concentration.spell_id = "divine_bless"
    await update_player_concentration(pid, "divine_bless")
    call = game_tools(session, activate)
    try:
        with (
            patch("check_resolution.dice_roll", side_effect=[_d20(8), _d20(19)]) as dice,
            patch("dice.roll", return_value=_damage_die(4)) as burn,
        ):
            held = await call("activate", id="draethar_inner_fire")
            offer = held["fate_offer"]
            assert offer["roller_id"] == pid and offer["roll_kind"] == "save" and offer["die"] == 8
            assert held["fire_damage"] == 4
            assert (await row(world, 0))["hp"]["current"] == 96
            assert session.resonance.current == 6 and session.concentration.spell_id == "divine_bless"
            if reload:
                session = SessionData(player_id=pid, location_id=state.location_id)
                session.combat_state = await db_mutations.load_combat_state(state.combat_id)
                session.concentration.spell_id = "divine_bless"
                fresh = game_tools(session, activate, resolve_phase, end_combat)
                with pytest.raises(ToolError, match="spent"):
                    await fresh("activate", id="draethar_inner_fire")
                with pytest.raises(ToolError, match="resolve_phase"):
                    await fresh("end_combat", outcome="fled")
                result = await fresh("resolve_phase")
            else:
                args = {"id": "zhael_fates_thread", "offer_id": offer["offer_id"]}
                await call("activate", **args)
                result = await call("activate", **args, keep="reroll")
            assert dice.call_count == (1 if reload else 2)
            assert burn.call_count == 1
        assert result["fire_damage"] == 4
        assert result["concentration_broken"] == ("divine_bless" if reload else None)
        stored = await db_mutations.load_combat_state(state.combat_id)
        assert stored is not None and stored.beat == "declaration"
        assert (await row(world, 0))["resonance"]["current"] == 6
        assert has_condition(required_player(stored, pid).conditions, "blessed") is not reload
    finally:
        await db_mutations.delete_combat_state(state.combat_id)


async def mawling_turn_start(world):
    await configure(world, "zhael", "mage", hp={"current": 100, "max": 100})
    pid = world.ids[0]
    catalog = await load_creature_enemy("hollow_mawling", encounter_id="maw", enemy_id="maw", role="standard")
    maw = _enemy("maw", 30)
    maw.creature_id = "hollow_mawling"
    maw.turn_start_damage = catalog["turn_start_damage"]
    maw.action_pool = catalog["action_pool"]
    state = _build_state(pid, pid, [maw])
    player = required_player(state, pid)
    player.conditions = apply_condition([], "grappled", source=maw.id)
    session = world.ctx.userdata
    session.combat_state = state
    session.concentration.spell_id = "divine_bless"
    await update_player_concentration(pid, "divine_bless")
    call = game_tools(session, declare_phase, resolve_phase)
    try:
        await call("declare_phase", declarations=[defend(pid), defend(maw.id)])
        with (
            patch("check_resolution.dice_roll", return_value=_d20(8)) as dice,
            patch("combat_turn_start.dice_roll", return_value=_damage_die(4)) as damage,
        ):
            held = (await call("resolve_phase"))["fate_offer"]
            assert held["roller_id"] == pid and held["roll_kind"] == "save"
            assert required_player(session.combat_state, pid).hp_current == 96
            assert session.concentration.spell_id == "divine_bless"
            fresh = SessionData(player_id=pid, location_id=state.location_id)
            fresh.combat_state = await db_mutations.load_combat_state(state.combat_id)
            fresh.concentration.spell_id = "divine_bless"
            result = await game_tools(fresh, resolve_phase)("resolve_phase")
            assert dice.call_count == damage.call_count == 1
        automatic, defense = result["packets"]
        assert automatic["automatic"] and automatic["concentration_broken"] == "divine_bless"
        assert defense["actor_id"] == pid and defense["resolved"]
        assert (await row(world, 0))["hp"]["current"] == 96
    finally:
        await db_mutations.delete_combat_state(state.combat_id)


async def post_roll_window(world):
    await configure(world, "zhael", "rogue", level=5, stamina={"current": 20, "max": 20})
    pid = world.ids[0]
    foe = _enemy("foe", 30)
    state = _build_state(pid, pid, [foe])
    player = required_player(state, pid)
    reaction = "rogue_uncanny_dodge"
    player.level = 5
    player.reaction_ids = [reaction]
    player.has_reaction_ability = True
    session = world.ctx.userdata
    session.combat_state = state
    lifecycle = _live_party(session, *world.ids)
    call = game_tools(session, declare_phase, resolve_phase, activate)
    try:
        await call("declare_phase", declarations=[defend(pid), {**attack(foe.id, pid), "action": "Scimitar"}])
        await call("resolve_phase")
        with (
            patch("check_resolution.dice_roll", return_value=_d20(19)) as dice,
            patch("check_resolution_attack.dice_roll", return_value=_damage_die(6)),
        ):
            held = (await call("resolve_phase"))["fate_offer"]
            assert held["roller_id"] == foe.id
            window = (await call("activate", id=reaction))["next"]["waiting_on"]
            assert window["stage"] == "post_roll" and "on_hit" in window["triggers"]
            assert (await row(world, 0))["stamina"]["current"] == 20
            assert required_player(session.combat_state, pid).hp_current == 100
            with session._bind_authenticated_actor(pid, 1, lifecycle.require_authorized):
                await call("activate", id=reaction)
            result = await call("resolve_phase")
            assert dice.call_count == 1
        blows = [packet for packet in result["packets"] if packet.get("attacker") == foe.name]
        assert [packet["damage"] for packet in blows] == [3]
        assert required_player(session.combat_state, pid).hp_current == 97
    finally:
        await lifecycle.aclose()
        await db_mutations.delete_combat_state(state.combat_id)
