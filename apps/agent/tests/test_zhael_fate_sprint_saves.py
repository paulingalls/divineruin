"""Zhael's Fate's Thread holds the save d20s the Hollow bosses and save spells introduced.

The gift reaches "a d20 result (yours or anyone's)" (game_mechanics_patrons.md, Zhael layer 1), so a
player's own save and an enemy's save are both in scope. Each test holds the save, then either
reloads (the original stands) or chooses the reroll.
"""

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from _patron_engine_fixtures import configure
from _unbound_path_fixtures import world as world
from _zhael_fate_fixtures import attack, defend, game_tools
from acceptance._capstone_helpers import _build_state, _d20, _damage_die, _enemy
from acceptance.seeds import seed_known_spells
from acceptance.test_kaelen_iron_resolve_capstone import required_player
from sample_fixtures import make_context

import db_mutations
from activate_tools import activate
from combat_turn import declare_phase, resolve_phase
from conditions import has_condition


async def _keep(call, offer):
    return await call("activate", id="zhael_fates_thread", offer_id=offer["offer_id"], keep="original")


async def _reroll(call, offer):
    await call("activate", id="zhael_fates_thread", offer_id=offer["offer_id"])
    return await call("activate", id="zhael_fates_thread", offer_id=offer["offer_id"], keep="reroll")


async def _reloaded(session, combat_id, pid):
    fresh = make_context(player_id=pid, room=session.room).userdata
    fresh.combat_state = await db_mutations.load_combat_state(combat_id)
    return fresh, game_tools(fresh, resolve_phase, activate)


async def _settle(world, session, state, call, offer, reload):
    """Reload (the held original stands) or choose the reroll; returns the final payload and state."""
    pid = world.ids[0]
    if reload:
        fresh, restored = await _reloaded(session, state.combat_id, pid)
        result = await restored("resolve_phase")
        return result, fresh.combat_state
    return await _reroll(call, offer), session.combat_state


@pytest.mark.parametrize("reload", [False, True])
async def test_knight_critical_save_is_held(world, reload):
    await configure(world, "zhael", "mage")
    pid = world.ids[0]
    knight = _enemy("knight", 30)
    knight.action_pool = [
        {
            **knight.action_pool[0],
            "critical_save": {"save": "CON", "dc": 14, "applies_condition": "hollowed", "stage": 1},
        }
    ]
    state = _build_state(pid, pid, [knight])
    session = world.ctx.userdata
    session.combat_state = state
    call = game_tools(session, declare_phase, resolve_phase, activate)
    try:
        await call("declare_phase", declarations=[defend(pid), {**attack("knight", pid), "action": "Scimitar"}])
        with (
            patch("check_resolution.dice_roll", side_effect=[_d20(20), _d20(3), _d20(19)]) as dice,
            patch("check_resolution_attack.dice_roll", return_value=_damage_die(2)),
        ):
            await call("resolve_phase")
            blow = (await call("resolve_phase"))["fate_offer"]
            assert blow["roll_kind"] == "attack" and blow["roller_id"] == "knight"
            save = (await _keep(call, blow))["fate_offer"]
            assert save["roll_kind"] == "save" and save["roller_id"] == pid and save["die"] == 3
            assert not has_condition(required_player(session.combat_state, pid).conditions, "hollowed")
            result, final = await _settle(world, session, state, call, save, reload)
            assert dice.call_count == (2 if reload else 3)
        packet = next(p for p in result["packets"] if p.get("critical_save"))
        assert packet["critical_save"]["roll"] == (3 if reload else 19)
        assert packet["critical_save"]["success"] is not reload
        assert has_condition(required_player(final, pid).conditions, "hollowed") is reload
    finally:
        await db_mutations.delete_combat_state(state.combat_id)


@pytest.mark.parametrize("reload", [False, True])
async def test_unholy_fortitude_save_is_held(world, reload):
    """An enemy's save is "anyone's" d20: the Knight's Fortitude roll waits for the follower."""
    await configure(world, "zhael", "mage")
    pid = world.ids[0]
    knight = _enemy("knight", 5)
    knight.unholy_fortitude = {"save": "CON", "dc": 10, "increment": 5, "narration_cue": "It rises."}
    state = _build_state(pid, pid, [knight])
    session = world.ctx.userdata
    session.combat_state = state
    call = game_tools(session, declare_phase, resolve_phase, activate)
    try:
        await call("declare_phase", declarations=[attack(pid, "knight"), defend("knight")])
        with (
            patch("check_resolution.dice_roll", side_effect=[_d20(15), _d20(2), _d20(18)]) as dice,
            patch("check_resolution_attack.dice_roll", return_value=_damage_die(8)),
        ):
            swing = (await call("resolve_phase"))["fate_offer"]
            assert swing["roll_kind"] == "attack" and swing["roller_id"] == pid
            save = (await _keep(call, swing))["fate_offer"]
            assert save["roll_kind"] == "save" and save["roller_id"] == "knight" and save["die"] == 2
            assert required_player(session.combat_state, "knight").hp_current == 5
            result, final = await _settle(world, session, state, call, save, reload)
            assert dice.call_count == (2 if reload else 3)
        fortitude = result["packets"][0]["unholy_fortitude"]
        assert fortitude["roll"] == (2 if reload else 18) and fortitude["success"] is not reload
        fallen = required_player(final, "knight")
        assert fallen.is_fallen is reload and fallen.hp_current == (0 if reload else 1)
    finally:
        await db_mutations.delete_combat_state(state.combat_id)


def _cast(actor_id, spell_id, targets):
    return {**defend(actor_id), "kind": "ability", "action": spell_id, "targets": targets}


@pytest.mark.parametrize("reload", [False, True])
async def test_single_target_save_spell_is_held(world, reload):
    await configure(world, "zhael", "cleric")
    pid = world.ids[0]
    state = _build_state(pid, pid, [_enemy("foe", 30)])
    session = world.ctx.userdata
    session.combat_state = state
    call = game_tools(session, declare_phase, resolve_phase, activate)
    try:
        await call("declare_phase", declarations=[_cast(pid, "divine_sacred_flame", ["foe"]), defend("foe")])
        with (
            patch("check_resolution.dice_roll", side_effect=[_d20(3), _d20(18)]) as dice,
            patch("dice.roll", return_value=SimpleNamespace(total=5)),
        ):
            save = (await call("resolve_phase"))["fate_offer"]
            assert save["roll_kind"] == "save" and save["roller_id"] == "foe" and save["die"] == 3
            assert required_player(session.combat_state, "foe").hp_current == 30
            result, final = await _settle(world, session, state, call, save, reload)
            assert dice.call_count == (1 if reload else 2)
        landed = result["packets"][0]["cast"]["damage_result"]
        assert landed["save"]["roll"] == (3 if reload else 18) and landed["save"]["success"] is not reload
        assert required_player(final, "foe").hp_current == 30 - landed["damage"]
        assert (landed["damage"] > 0) is reload
    finally:
        await db_mutations.delete_combat_state(state.combat_id)


@pytest.mark.parametrize("reload", [False, True])
async def test_area_save_spell_holds_each_recipient_in_order(world, reload):
    await configure(world, "zhael", "mage", focus={"current": 20, "max": 20})
    pid = world.ids[0]
    await seed_known_spells(world.pool, pid, ("arcane_fireball",))
    state = _build_state(pid, pid, [_enemy("foe", 30), _enemy("other", 30)])
    assert state.spatial is not None
    state.spatial["positions"].update(foe={"x": 30, "y": 0, "z": 0}, other={"x": 40, "y": 0, "z": 0})
    session = world.ctx.userdata
    session.combat_state = state
    call = game_tools(session, declare_phase, resolve_phase, activate)
    try:
        await call(
            "declare_phase",
            declarations=[_cast(pid, "arcane_fireball", ["foe"]), defend("foe"), defend("other")],
        )
        with (
            patch("check_resolution.dice_roll", side_effect=[_d20(3), _d20(4), _d20(19)]) as dice,
            patch("dice.roll", return_value=SimpleNamespace(total=6)),
        ):
            first = (await call("resolve_phase"))["fate_offer"]
            assert first["roll_kind"] == "save" and first["roller_id"] == "foe" and first["die"] == 3
            second = (await _keep(call, first))["fate_offer"]
            assert second["roller_id"] == "other" and second["die"] == 4
            assert required_player(session.combat_state, "foe").hp_current == 30 - 6
            assert required_player(session.combat_state, "other").hp_current == 30
            result, final = await _settle(world, session, state, call, second, reload)
            assert dice.call_count == (2 if reload else 3)
        landed = {r["target_id"]: r for r in result["packets"][0]["cast"]["damage_results"]}
        assert [r["save"]["roll"] for r in landed.values()] == [3, 4 if reload else 19]
        assert required_player(final, "foe").hp_current == 30 - 6
        assert required_player(final, "other").hp_current == 30 - (6 if reload else 3)
    finally:
        await db_mutations.delete_combat_state(state.combat_id)
