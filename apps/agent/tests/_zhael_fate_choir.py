from unittest.mock import patch

from _patron_engine_fixtures import configure
from _unbound_path_fixtures import row
from _zhael_fate_fixtures import defend, game_tools
from acceptance._capstone_helpers import _build_state, _d20, _damage_die, _enemy
from acceptance.test_kaelen_iron_resolve_capstone import required_player

import choir_encounter
import db_mutations
from ability_persistence import set_elective_equipped
from activate_tools import activate
from combat_turn import declare_phase, resolve_phase
from creature_combat_loader import load_creature_enemy
from db_mutations_concentration import update_player_concentration


async def _choir_state(world, *, exposed=False):
    pid = world.ids[0]
    session = world.ctx.userdata
    catalog = await load_creature_enemy("hollow_choir", encounter_id="choir", enemy_id="choir", role="named")
    choir = _enemy("choir", 200)
    choir.creature_id = "hollow_choir"
    choir.action_pool = catalog["action_pool"]
    choir.choir_reaction = catalog["choir_reaction"]
    state = _build_state(pid, pid, [choir])
    choir_encounter.initialize(state)
    if exposed:
        assert state.choir_encounter is not None
        state.choir_encounter["phase"] = "exposed"
    session.combat_state = state
    return session, state, choir


async def _keep(call, offer):
    return await call("activate", id="zhael_fates_thread", offer_id=offer["offer_id"], keep="original")


async def aura_and_search(world):
    await configure(world, "zhael", "mage")
    pid = world.ids[0]
    session, state, choir = await _choir_state(world)
    session.concentration.spell_id = "divine_bless"
    await update_player_concentration(pid, "divine_bless")
    call = game_tools(session, declare_phase, resolve_phase, activate)
    try:
        await call(
            "declare_phase",
            declarations=[
                {"kind": "interact", "actor_id": pid, "action": "choir_search_arcana"},
                defend(choir.id),
            ],
        )
        with patch("check_resolution.dice_roll", side_effect=[_d20(9), _d20(20)]) as dice:
            aura = (await call("resolve_phase"))["fate_offer"]
            assert aura["roll_kind"] == "save" and aura["die"] == 9
            assert session.concentration.spell_id == "divine_bless"
            search = (await _keep(call, aura))["fate_offer"]
            assert search["roll_kind"] == "skill" and search["die"] == 20
            assert session.concentration.spell_id is None
            assert session.combat_state.choir_encounter["phase"] == "search"
            result = await _keep(call, search)
            assert dice.call_count == 2
        assert result["choir"]["phase"] == "exposed"
        stored = await db_mutations.load_combat_state(state.combat_id)
        assert stored is not None and stored.choir_encounter is not None
        assert stored.choir_encounter["aura_receipts"] == {pid: 1}
    finally:
        await db_mutations.delete_combat_state(state.combat_id)


async def shield_and_bolt(world):
    await configure(world, "zhael", "mage")
    pid = world.ids[0]
    session, state, choir = await _choir_state(world, exposed=True)
    call = game_tools(session, declare_phase, resolve_phase, activate)
    try:
        await call(
            "declare_phase",
            declarations=[
                {**defend(pid), "kind": "ability", "action": "arcane_bolt", "targets": [choir.id]},
                defend(choir.id),
            ],
        )
        with (
            patch("check_resolution.dice_roll", side_effect=[_d20(19), _d20(20), _d20(19)]) as dice,
            patch("check_resolution_attack.dice_roll", return_value=_damage_die(4)) as damage,
        ):
            aura = (await call("resolve_phase"))["fate_offer"]
            shield = (await _keep(call, aura))["fate_offer"]
            assert shield["roll_kind"] == "save" and shield["die"] == 20
            strike = (await _keep(call, shield))["fate_offer"]
            assert strike["roll_kind"] == "attack" and strike["die"] == 19 and not damage.called
            assert required_player(session.combat_state, choir.id).hp_current == 200
            result = await _keep(call, strike)
            assert dice.call_count == 3
        assert result["packets"][0]["cast"]["damage_result"]["hit"]
        assert required_player(await db_mutations.load_combat_state(state.combat_id), choir.id).hp_current < 200
    finally:
        await db_mutations.delete_combat_state(state.combat_id)


async def hostile_condition_ability(world):
    from conditions import has_condition

    pid = world.ids[0]
    await configure(world, "zhael", "warrior", level=8, stamina={"current": 20, "max": 20})
    ability_id = "warrior_unstoppable_charge"
    await set_elective_equipped(pid, ability_id, True)
    foe = _enemy("foe", 30)
    state = _build_state(pid, pid, [foe])
    required_player(state, pid).attributes["strength"] = 16
    required_player(state, pid).level = 8
    session = world.ctx.userdata
    session.combat_state = state
    call = game_tools(session, declare_phase, resolve_phase, activate)
    try:
        await call(
            "declare_phase",
            declarations=[
                {**defend(pid), "kind": "ability", "action": ability_id, "targets": [foe.id]},
                defend(foe.id),
            ],
        )
        with patch("check_resolution.dice_roll", return_value=_d20(8)) as dice:
            offer = (await call("resolve_phase"))["fate_offer"]
            assert offer["roller_id"] == foe.id
            assert not has_condition(required_player(session.combat_state, foe.id).conditions, "prone")
            charged = (await row(world, 0))["stamina"]["current"]
            assert charged < 20
            result = await _keep(call, offer)
            assert dice.call_count == 1
        assert result["packets"][0]["condition_inflicted"] == "prone"
        assert (await row(world, 0))["stamina"]["current"] == charged
    finally:
        await db_mutations.delete_combat_state(state.combat_id)


async def melody(world, save_succeeds):
    import pytest
    from livekit.agents.llm import ToolError

    from conditions import has_condition

    await configure(world, "zhael", "mage")
    pid = world.ids[0]
    session, state, choir = await _choir_state(world)
    call = game_tools(session, declare_phase, resolve_phase, activate)
    try:
        await call(
            "declare_phase",
            declarations=[
                defend(pid),
                {**defend(choir.id), "kind": "ability", "action": "Stolen Melody", "targets": [pid]},
            ],
        )
        with (
            patch("check_resolution.dice_roll", side_effect=[_d20(19), _d20(20 if save_succeeds else 8)]),
            patch("dice.roll", return_value=_damage_die(3)) as duration,
            patch("combat_recharge.roll", return_value=_damage_die(3)),
        ):
            aura = (await call("resolve_phase"))["fate_offer"]
            await _keep(call, aura)
            offer = (await call("resolve_phase"))["fate_offer"]
            assert offer["roller_id"] == pid and offer["roll_kind"] == "save"
            assert duration.call_count == 0
            assert required_player(session.combat_state, choir.id).action_ledger["stolen melody"]["remaining"] == 0
            result = await _keep(call, offer)
        assert result["packets"][0]["save_success"] is save_succeeds
        assert duration.call_count == (0 if save_succeeds else 1)
        target = required_player(session.combat_state, pid)
        assert has_condition(target.conditions, "charmed") is not save_succeeds
        with pytest.raises(ToolError, match="current Fate"):
            await _keep(call, offer)
    finally:
        await db_mutations.delete_combat_state(state.combat_id)
