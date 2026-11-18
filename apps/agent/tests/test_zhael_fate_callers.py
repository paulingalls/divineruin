from unittest.mock import patch

import pytest
from _patron_engine_fixtures import configure
from _unbound_path_fixtures import row
from _unbound_path_fixtures import world as world
from _zhael_fate_fixtures import attack, defend, game_tools
from acceptance._capstone_helpers import _build_state, _d20, _damage_die, _enemy, _player
from acceptance.test_kaelen_iron_resolve_capstone import required_player
from livekit.agents.llm import ToolError
from sample_fixtures import published_payloads
from test_aelora_gift import _live_party
from voice_condition_fixtures import place_actors

import db_mutations
from activate_tools import activate
from check_tools import check
from combat_death_save import request_death_save
from combat_end import end_combat
from combat_turn import declare_phase, resolve_phase
from session_data import SessionData


async def attack_choice(world):
    await configure(world, "zhael", "mage")
    player_id = world.ids[0]
    state = _build_state(player_id, player_id, [_enemy("foe", 30)])
    session = world.ctx.userdata
    session.combat_state = state
    call = game_tools(session, declare_phase, resolve_phase, activate)
    try:
        await call("declare_phase", declarations=[attack(player_id, "foe"), defend("foe")])
        with (
            patch("check_resolution.dice_roll", side_effect=[_d20(1), _d20(20)]),
            patch("check_resolution_attack.dice_roll", return_value=_damage_die(4)) as damage,
        ):
            offered = await call("resolve_phase")
            assert offered["next"] == {"phase": "resolution", "verbs": ["activate"], "waiting_on": None}
            offer = offered["fate_offer"]
            assert offer["roll_kind"] == "attack" and offer["roller_id"] == player_id
            assert offer["die"] == 1 and required_player(session.combat_state, "foe").hp_current == 30
            shown = await call("activate", id="zhael_fates_thread", offer_id=offer["offer_id"])
            assert shown["reroll"]["die"] == 20 and not damage.called
            settled = await call("activate", id="zhael_fates_thread", offer_id=offer["offer_id"], keep="reroll")
        packet = settled["packets"][0]
        assert packet["hit"] and packet["critical"] and packet["damage"] == 8
        saved = await db_mutations.load_combat_state(state.combat_id)
        assert required_player(saved, "foe").hp_current == 22
        assert (await row(world, 0))["patron_gifts"]["zhael_fates_thread"] == {"spent": True}
    finally:
        await db_mutations.delete_combat_state(state.combat_id)


SCENARIOS = {"zhael_fates_thread": ("zhael_fate:activate", attack_choice, [()])}


async def test_death_save_holds_revive_and_counters(world):
    await configure(world, "zhael", "mage", hp={"current": 0, "max": 20})
    pid = world.ids[0]
    session = world.ctx.userdata
    state = _build_state(pid, pid, [_enemy("foe", 30)])
    faller = required_player(state, pid)
    faller.hp_current, faller.is_fallen, faller.death_save_failures = 0, True, 2
    session.combat_state = state
    call = game_tools(session, request_death_save, activate)
    try:
        await db_mutations.save_combat_state(state.combat_id, state.to_dict())
        with patch("combat_resolution.dice_roll", side_effect=[_d20(1), _d20(20)]):
            offer = (await call("request_death_save"))["fate_offer"]
            assert offer["die"] == 1 and "dead" not in offer
            assert required_player(session.combat_state, pid).death_save_failures == 2
            await call("activate", id="zhael_fates_thread", offer_id=offer["offer_id"])
            kept = await call("activate", id="zhael_fates_thread", offer_id=offer["offer_id"], keep="reroll")
        assert kept["revived"]
        assert (await row(world, 0))["hp"]["current"] == 1
        stored = await db_mutations.load_combat_state(state.combat_id)
        assert required_player(stored, pid).death_save_failures == 0
    finally:
        await db_mutations.delete_combat_state(state.combat_id)


async def test_ally_stealth_uses_original_roller_for_concealment_and_advancement(world):
    host, guest = world.ids
    await configure(world, "zhael", "mage", flags={"concealed": False})
    await configure(world, "aelora", "mage", index=1, flags={"concealed": False})
    session = world.ctx.userdata
    lifecycle = _live_party(session, *world.ids)
    call = game_tools(session, check, activate)
    read_counter = "SELECT use_counter FROM skill_advancement WHERE player_id=$1 AND skill_id='stealth'"
    roll = {
        "kind": "skill",
        "skill": "stealth",
        "difficulty": "moderate",
        "context_description": "Hide from the guard",
        "hearing_only": False,
    }
    try:
        with patch("check_resolution.dice_roll", side_effect=[_d20(1), _d20(20)]):
            with session._bind_authenticated_actor(guest, 1, lifecycle.require_authorized):
                offer = (await call("check", roll=roll))["fate_offer"]
            assert offer["roller_id"] == guest
            assert not (await row(world, 1))["flags"]["concealed"]
            assert await world.pool.fetchval(read_counter, guest) is None
            args = {"id": "zhael_fates_thread", "offer_id": offer["offer_id"]}
            with session._bind_authenticated_actor(host, 1, lifecycle.require_authorized):
                await call("activate", **args)
                result = await call("activate", **args, keep="reroll")
        assert result["roll"] == 20 and (await row(world, 1))["flags"]["concealed"]
        assert not (await row(world, 0))["flags"]["concealed"]
        assert await world.pool.fetchval(read_counter, guest) == 1
        assert await world.pool.fetchval(read_counter, host) is None
    finally:
        await lifecycle.aclose()


async def test_nested_ally_offers_delay_incoming_tool_until_both_settle(world):
    host, guest = world.ids
    await configure(world, "zhael", "mage")
    state = _build_state(host, host, [_enemy("foe", 30)], first_attack_resolved=True)
    state.participants.append(_player(guest))
    state.initiative_order.insert(1, guest)
    required_player(state, host).initiative = 20
    place_actors(state)
    session = world.ctx.userdata
    session.combat_state = state
    call = game_tools(session, declare_phase, resolve_phase, check)
    narrative = {"kind": "dice", "notation": "1d4"}
    try:
        await call("declare_phase", declarations=[attack(host, "foe"), attack(guest, "foe"), defend("foe")])
        with (
            patch("check_resolution.dice_roll", side_effect=[_d20(19), _d20(19)]),
            patch("check_resolution_attack.dice_roll", return_value=_damage_die(4)),
        ):
            original = (await call("resolve_phase"))["fate_offer"]
            partial = await call("check", roll=narrative)
            assert partial["fate_offer"]["offer_id"] != original["offer_id"]
            assert partial["fate_offer"]["roller_id"] == guest and partial["packets"][0]["actor_id"] == host
            assert required_player(session.combat_state, "foe").hp_current == 26
            assert [e.get("roll_type") for e in published_payloads(session.room) if e["type"] == "dice_roll"] == [
                "attack"
            ]
            result = await call("check", roll=narrative)
        assert result["notation"] == "1d4" and result["settled_fate"]["packets"][0]["actor_id"] == guest
        assert required_player(session.combat_state, "foe").hp_current == 22
        assert [e.get("roll_type") for e in published_payloads(session.room) if e["type"] == "dice_roll"] == [
            "attack",
            "attack",
            "narrative",
        ]
    finally:
        await db_mutations.delete_combat_state(state.combat_id)


async def test_reload_applies_original_and_preserves_spend(world):
    host = world.ids[0]
    await configure(world, "zhael", "mage")
    state = _build_state(host, host, [_enemy("foe", 30)])
    world.ctx.userdata.combat_state = state
    call = game_tools(world.ctx.userdata, declare_phase, resolve_phase, activate)
    try:
        await call("declare_phase", declarations=[attack(host, "foe"), defend("foe")])
        with patch("check_resolution.dice_roll", side_effect=[_d20(19), _d20(1)]) as dice:
            offer = (await call("resolve_phase"))["fate_offer"]
            await call("activate", id="zhael_fates_thread", offer_id=offer["offer_id"])
            fresh = SessionData(player_id=host, location_id="accord_guild_hall")
            fresh.combat_state = await db_mutations.load_combat_state(state.combat_id)
            with pytest.raises(ToolError, match="resolve_phase"):
                await game_tools(fresh, end_combat)("end_combat", outcome="fled")
            assert await db_mutations.load_combat_state(state.combat_id) is not None
            with patch("check_resolution_attack.dice_roll", return_value=_damage_die(4)):
                done = await game_tools(fresh, resolve_phase)("resolve_phase")
            assert dice.call_count == 2
        assert done["beat"] == "narration" and "fate_offer" not in done
        assert done["packets"][0]["hit"] and required_player(fresh.combat_state, "foe").hp_current == 26
        assert (await row(world, 0))["patron_gifts"]["zhael_fates_thread"] == {"spent": True}
        assert fresh.combat_state is not None
        assert fresh.combat_state.ally_continuation is None and len(fresh.combat_state.held_actions) == 1
    finally:
        await db_mutations.delete_combat_state(state.combat_id)


async def test_second_swing_after_a_rerolled_held_swing_uses_its_own_die(world):
    await configure(world, "zhael", "mage")
    pid = world.ids[0]
    target = _enemy("foe", 60)
    state = _build_state(pid, pid, [target])
    attacker = required_player(state, pid)
    attacker.attack_mod = 25
    attacker.enhancers = ["extra_attack"]
    session = world.ctx.userdata
    session.combat_state = state
    call = game_tools(session, declare_phase, resolve_phase, activate)
    try:
        await call("declare_phase", declarations=[attack(pid, "foe"), defend("foe")])
        with (
            patch("check_resolution.dice_roll", side_effect=[_d20(20), _d20(15), _d20(14)]),
            patch("check_resolution_attack.dice_roll", return_value=_damage_die(4)),
        ):
            offer = (await call("resolve_phase"))["fate_offer"]
            fate = {"id": "zhael_fates_thread", "offer_id": offer["offer_id"]}
            await call("activate", **fate)
            result = await call("activate", **fate, keep="reroll")
        assert "fate_offer" not in result
        rolls = [e["roll"] for e in published_payloads(session.room) if e["type"] == "dice_roll"]
        assert rolls == [15, 14]
    finally:
        await db_mutations.delete_combat_state(state.combat_id)


@pytest.mark.parametrize(("original", "kept", "damage"), [(1, 19, 4), (19, 1, 0)])
async def test_hostile_attack_holds_before_impact(world, original, kept, damage):
    await configure(world, "zhael", "mage")
    player_id = world.ids[0]
    state = _build_state(player_id, player_id, [_enemy("foe", 30)])
    session = world.ctx.userdata
    session.combat_state = state
    call = game_tools(session, declare_phase, resolve_phase, activate)
    strike = {**attack("foe", player_id), "action": "Scimitar"}
    try:
        await call("declare_phase", declarations=[defend(player_id), strike])
        await call("resolve_phase")
        with (
            patch("check_resolution.dice_roll", side_effect=[_d20(original), _d20(kept)]),
            patch("check_resolution_attack.dice_roll", return_value=_damage_die(4)) as damage_die,
        ):
            offered = await call("resolve_phase")
            offer = offered["fate_offer"]
            assert offer["roller_id"] == "foe" and offer["roll_kind"] == "attack"
            assert offer["die"] == original and player_id in offer["eligible_followers"]
            held = await db_mutations.load_combat_state(state.combat_id)
            assert required_player(held, player_id).hp_current == 100
            args = {"id": "zhael_fates_thread", "offer_id": offer["offer_id"]}
            await call("activate", **args)
            assert not damage_die.called
            settled = await call("activate", **args, keep="reroll")
        assert settled["packets"][0]["roll"] == kept
        assert settled["packets"][0]["damage"] == damage
        persisted = await db_mutations.load_combat_state(state.combat_id)
        assert required_player(persisted, player_id).hp_current == 100 - damage
        with pytest.raises(ToolError, match="current"):
            await call("activate", **args, keep="reroll")
    finally:
        await db_mutations.delete_combat_state(state.combat_id)


async def test_wrap_holds_clearing_saves_and_recovers_next_original(world):
    from conditions import apply_condition, has_condition

    await configure(world, "zhael", "mage")
    pid = world.ids[0]
    foe = _enemy("foe", 30)
    state = _build_state(pid, pid, [foe])
    player = required_player(state, pid)
    player.conditions = apply_condition([], "frightened", source=foe.id, duration=3)
    foe.conditions = apply_condition([], "frightened", source=pid, duration=3)
    session = world.ctx.userdata
    session.combat_state = state
    call = game_tools(session, declare_phase, resolve_phase, activate)
    try:
        await call("declare_phase", declarations=[defend(pid), defend(foe.id)])
        await call("resolve_phase")
        with patch("check_resolution.dice_roll", side_effect=[_d20(19), _d20(18)]) as dice:
            held = (await call("resolve_phase"))["fate_offer"]
            assert held["roll_kind"] == "save" and held["roller_id"] == pid
            assert has_condition(required_player(session.combat_state, pid).conditions, "frightened")
            next_result = await call("activate", id="zhael_fates_thread", offer_id=held["offer_id"], keep="original")
            next_offer = next_result["fate_offer"]
            assert next_offer["roller_id"] == foe.id and next_offer["offer_id"] != held["offer_id"]
            fresh = SessionData(player_id=pid, location_id="accord_guild_hall")
            fresh.combat_state = await db_mutations.load_combat_state(state.combat_id)
            assert not has_condition(required_player(fresh.combat_state, pid).conditions, "frightened")
            assert has_condition(required_player(fresh.combat_state, foe.id).conditions, "frightened")
            result = await game_tools(fresh, resolve_phase)("resolve_phase")
            assert dice.call_count == 2
        assert result["round"] == 2 and result["beat"] == "declaration"
        persisted = await db_mutations.load_combat_state(state.combat_id)
        assert not has_condition(required_player(persisted, foe.id).conditions, "frightened")
    finally:
        await db_mutations.delete_combat_state(state.combat_id)
