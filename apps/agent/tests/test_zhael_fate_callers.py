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


async def test_area_holds_each_catalog_target_in_order_across_reload(world):
    from sample_fixtures import make_context

    from conditions import has_condition
    from creature_combat_loader import load_creature_enemy

    host, guest = world.ids
    await configure(world, "zhael", "mage")
    catalog = await load_creature_enemy("hollow_choir", encounter_id="choir", enemy_id="choir", role="named")
    choir = _enemy("choir", 200)
    choir.creature_id = "hollow_choir"
    choir.action_pool = catalog["action_pool"]
    state = _build_state(host, host, [choir])
    companion = _player("ally_companion")
    companion.type = "companion"
    state.participants[1:1] = [_player(guest), companion]
    target_ids = [host, guest, companion.id, choir.id]
    state.initiative_order = target_ids
    place_actors(state)
    session = world.ctx.userdata
    session.combat_state = state
    call = game_tools(session, declare_phase, resolve_phase, activate, check)

    def hp(current):
        return [required_player(current, pid).hp_current for pid in target_ids]

    try:
        await call(
            "declare_phase",
            declarations=[
                defend(host),
                defend(guest),
                defend(companion.id),
                {**attack(choir.id, host), "action": "Memory Scream"},
            ],
        )
        await call("resolve_phase")
        before = hp(session.combat_state)
        with (
            patch("check_resolution.dice_roll", side_effect=[_d20(7), _d20(15), _d20(19), _d20(20)]) as dice,
            patch("combat_enemy_action.dice_roll", return_value=_damage_die(8)) as damage,
        ):
            first = (await call("resolve_phase"))["fate_offer"]
            assert first["roller_id"] == host and hp(session.combat_state) == before
            second = (await call("check", roll={"kind": "dice", "notation": "1d4"}))["fate_offer"]
            assert second["roller_id"] == guest and second["offer_id"] != first["offer_id"]
            assert hp(session.combat_state) == [before[0] - 8, *before[1:]]
            assert not any(e.get("roll_type") == "narrative" for e in published_payloads(session.room))
            fresh = make_context(player_id=host, party_member_ids=[guest]).userdata
            fresh.combat_state = await db_mutations.load_combat_state(state.combat_id)
            restored = game_tools(fresh, resolve_phase, activate)
            third = (await restored("resolve_phase"))["fate_offer"]
            assert third["roller_id"] == companion.id
            last = (await restored("activate", id="zhael_fates_thread", offer_id=third["offer_id"], keep="original"))[
                "fate_offer"
            ]
            assert last["roller_id"] == choir.id
            result = await restored("activate", id="zhael_fates_thread", offer_id=last["offer_id"], keep="original")
            assert dice.call_count == damage.call_count == 4
        assert [target["target_id"] for target in result["packets"][0]["targets"]] == target_ids
        assert hp(fresh.combat_state) == [before[0] - 8, before[1] - 8, *before[2:]]
        assert has_condition(required_player(fresh.combat_state, guest).conditions, "stunned")
    finally:
        await db_mutations.delete_combat_state(state.combat_id)


async def test_combined_attack_pauses_concentration_before_condition_save(world):
    from conditions import apply_condition, has_condition
    from db_mutations_concentration import update_player_concentration

    await configure(world, "zhael", "mage")
    pid = world.ids[0]
    foe = _enemy("foe", 30)
    foe.action_pool = [
        {
            **foe.action_pool[0],
            "applies_condition": "deafened",
            "save": "constitution",
            "dc": 15,
        }
    ]
    state = _build_state(pid, pid, [foe])
    required_player(state, pid).conditions = apply_condition([], "blessed", source="divine_bless")
    session = world.ctx.userdata
    session.combat_state = state
    session.concentration.spell_id = "divine_bless"
    await update_player_concentration(pid, "divine_bless")
    call = game_tools(session, declare_phase, resolve_phase, activate)

    async def keep(offer):
        return await call("activate", id="zhael_fates_thread", offer_id=offer["offer_id"], keep="original")

    try:
        await call("declare_phase", declarations=[defend(pid), {**attack(foe.id, pid), "action": "Scimitar"}])
        await call("resolve_phase")
        with (
            patch("check_resolution.dice_roll", side_effect=[_d20(19), _d20(7), _d20(11)]) as dice,
            patch("check_resolution_attack.dice_roll", return_value=_damage_die(4)) as damage,
        ):
            strike = (await call("resolve_phase"))["fate_offer"]
            held_concentration = (await keep(strike))["fate_offer"]
            assert held_concentration["roller_id"] == pid and held_concentration["die"] == 7
            assert session.concentration.spell_id == "divine_bless"
            assert required_player(session.combat_state, pid).hp_current == 96
            assert has_condition(required_player(session.combat_state, pid).conditions, "blessed")
            held_condition = (await keep(held_concentration))["fate_offer"]
            assert held_condition["die"] == 11 and held_condition["offer_id"] != held_concentration["offer_id"]
            assert session.concentration.spell_id is None
            assert not has_condition(required_player(session.combat_state, pid).conditions, "deafened")
            result = await keep(held_condition)
            assert dice.call_count == 3 and damage.call_count == 1
        player = required_player(await db_mutations.load_combat_state(state.combat_id), pid)
        assert player.hp_current == 96
        assert has_condition(player.conditions, "deafened") and not has_condition(player.conditions, "blessed")
        assert result["packets"][0]["concentration_broken"] == "divine_bless"
    finally:
        await db_mutations.delete_combat_state(state.combat_id)


async def test_choir_aura_and_search_offer_in_order(world):
    from _zhael_fate_choir import aura_and_search

    await aura_and_search(world)


async def test_choir_shield_saves_before_arcane_bolt_attacks(world):
    from _zhael_fate_choir import shield_and_bolt

    await shield_and_bolt(world)


async def test_hostile_ability_holds_foes_save_after_one_charge(world):
    from _zhael_fate_choir import hostile_condition_ability

    await hostile_condition_ability(world)


@pytest.mark.parametrize("save_succeeds", [True, False])
async def test_choir_melody_waits_before_duration(world, save_succeeds):
    from _zhael_fate_choir import melody

    await melody(world, save_succeeds)


@pytest.mark.parametrize("reload", [False, True])
async def test_inner_fire_applies_one_burn_before_concentration_choice(world, reload):
    from _zhael_fate_damage import inner_fire

    await inner_fire(world, reload)


async def test_mawling_turn_start_resumes_after_concentration_without_reburn(world):
    from _zhael_fate_damage import mawling_turn_start

    await mawling_turn_start(world)


async def test_default_hostile_fate_leaves_the_new_reaction_unspent(world):
    from _zhael_fate_damage import post_roll_window

    await post_roll_window(world)
