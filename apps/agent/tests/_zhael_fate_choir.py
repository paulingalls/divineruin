from unittest.mock import patch

from _patron_engine_fixtures import configure
from _unbound_path_fixtures import row
from _zhael_fate_fixtures import attack, defend, game_tools
from acceptance._capstone_helpers import _build_state, _d20, _damage_die, _enemy, _player
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
    choir.damage_affinities = catalog["damage_affinities"]
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


async def melody(world, save_succeeds, countercharm):
    from contextlib import nullcontext

    import pytest
    from livekit.agents.llm import ToolError
    from test_aelora_gift import _live_party
    from voice_condition_fixtures import place_actors

    from conditions import has_condition

    await configure(world, "zhael", "mage")
    await configure(world, "none", "bard", index=1)
    pid, bard = world.ids
    session, state, choir = await _choir_state(world)
    lifecycle = _live_party(session, *world.ids) if countercharm else None

    def acting(player_id):
        return (
            session._bind_authenticated_actor(player_id, 1, lifecycle.require_authorized)
            if lifecycle
            else nullcontext()
        )

    if countercharm:
        reactor = _player(bard)
        reactor.level, reactor.reaction_ids, reactor.has_reaction_ability = 5, ["bard_countercharm"], True
        state.participants.append(reactor)
        state.initiative_order.append(bard)
        place_actors(state)
    call = game_tools(session, declare_phase, resolve_phase, activate)
    # The bard makes their own aura save; Countercharm's advantage rolls a second Melody die.
    aura_dice = [_d20(19)] * (2 if countercharm else 1)
    melody_dice = [_d20(20 if save_succeeds else 8)] + ([_d20(8)] if countercharm else [])
    try:
        await call(
            "declare_phase",
            declarations=[
                defend(pid),
                {**defend(choir.id), "kind": "ability", "action": "Stolen Melody", "targets": [pid]},
                *([defend(bard)] if countercharm else []),
            ],
        )
        with (
            patch("check_resolution.dice_roll", side_effect=[*aura_dice, *melody_dice]) as dice,
            patch("dice.roll", return_value=_damage_die(3)) as duration,
            patch("combat_recharge.roll", return_value=_damage_die(3)),
        ):
            aura = (await call("resolve_phase"))["fate_offer"]
            with acting(pid):
                await _keep(call, aura)
            held = await call("resolve_phase")
            if countercharm:
                assert held["next"]["waiting_on"]["stage"] == "pre_roll"
                with acting(bard):
                    await call("activate", id="bard_countercharm")
                held = await call("resolve_phase")
                assert not [
                    packet for packet in held.get("packets", []) if packet.get("declaration_type") == "reaction"
                ]
            offer = held["fate_offer"]
            assert offer["roller_id"] == pid and offer["roll_kind"] == "save"
            assert duration.call_count == 0 and dice.call_count == len(aura_dice) + len(melody_dice)
            assert required_player(session.combat_state, choir.id).action_ledger["stolen melody"]["remaining"] == 0
            with acting(pid):
                result = await _keep(call, offer)
        reactions = [packet for packet in result["packets"] if packet.get("declaration_type") == "reaction"]
        assert [packet["mechanical_effect"] for packet in reactions] == (["save_advantage"] if countercharm else [])
        assert result["packets"][-1]["save_success"] is save_succeeds
        assert duration.call_count == (0 if save_succeeds else 1)
        target = required_player(session.combat_state, pid)
        assert has_condition(target.conditions, "charmed") is not save_succeeds
        with acting(pid), pytest.raises(ToolError, match="current Fate"):
            await _keep(call, offer)
    finally:
        if lifecycle:
            await lifecycle.aclose()
        await db_mutations.delete_combat_state(state.combat_id)


async def hostile_aura_reload(world):
    from sample_fixtures import make_context
    from voice_condition_fixtures import place_actors

    await configure(world, "zhael", "mage")
    pid = world.ids[0]
    session, state, choir = await _choir_state(world)
    guard = _enemy("guard", 30)
    state.participants.append(guard)
    state.initiative_order.append(guard.id)
    place_actors(state)
    call = game_tools(session, declare_phase, resolve_phase, activate)
    try:
        await call("declare_phase", declarations=[defend(pid), defend(choir.id), defend(guard.id)])
        with patch("check_resolution.dice_roll", side_effect=[_d20(19), _d20(17)]) as dice:
            ally = (await call("resolve_phase"))["fate_offer"]
            await _keep(call, ally)
            hostile = (await call("resolve_phase"))["fate_offer"]
            assert hostile["roller_id"] == guard.id and hostile["die"] == 17
            assert session.combat_state is not None and session.combat_state.choir_encounter is not None
            assert session.combat_state.choir_encounter["aura_receipts"] == {pid: 1}
            fresh = make_context(player_id=pid).userdata
            fresh.combat_state = await db_mutations.load_combat_state(state.combat_id)
            done = await game_tools(fresh, resolve_phase)("resolve_phase")
            assert dice.call_count == 2
        assert done["round"] == 2 and "fate_offer" not in done
        stored = await db_mutations.load_combat_state(state.combat_id)
        assert stored is not None and stored.choir_encounter is not None
        assert stored.choir_encounter["aura_receipts"] == {pid: 1, guard.id: 1}
    finally:
        await db_mutations.delete_combat_state(state.combat_id)


async def area_across_reload(world):
    from sample_fixtures import make_context, published_payloads
    from voice_condition_fixtures import place_actors

    from check_tools import check
    from conditions import has_condition

    host, guest = world.ids
    await configure(world, "zhael", "mage", hp={"current": 100, "max": 100})
    await configure(world, "aelora", "mage", index=1, hp={"current": 100, "max": 100})
    catalog = await load_creature_enemy("hollow_choir", encounter_id="choir", enemy_id="choir", role="named")
    choir = _enemy("choir", 200)
    choir.creature_id = "hollow_choir"
    choir.action_pool = catalog["action_pool"]
    choir.damage_affinities = catalog["damage_affinities"]
    state = _build_state(host, host, [choir])
    companion = _player("ally_companion")
    companion.type = "companion"
    state.participants[1:1] = [_player(guest), companion]
    target_ids = [host, guest, companion.id, choir.id]
    # An area action never includes its source (choir_actions.require_targets): the Choir is spared.
    area_ids = target_ids[:3]
    state.initiative_order = target_ids
    place_actors(state)
    session = world.ctx.userdata
    session.combat_state = state
    session.concentration.spell_id = "divine_bless"
    await update_player_concentration(host, "divine_bless")
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
                {**attack(choir.id, host), "action": "Cacophony"},
            ],
        )
        await call("resolve_phase")
        before = hp(session.combat_state)
        with (
            patch("check_resolution.dice_roll", side_effect=[_d20(7), _d20(19), _d20(15), _d20(8), _d20(20)]) as dice,
            patch("combat_enemy_action.dice_roll", return_value=_damage_die(8)) as damage,
        ):
            first = (await call("resolve_phase"))["fate_offer"]
            assert first["roller_id"] == host and hp(session.combat_state) == before
            nested = (await call("check", roll={"kind": "dice", "notation": "1d4"}))["fate_offer"]
            assert nested["roller_id"] == host and nested["die"] == 19 and nested["offer_id"] != first["offer_id"]
            assert session.concentration.spell_id == "divine_bless"
            assert not has_condition(required_player(session.combat_state, host).conditions, "stunned")
            second = (await call("activate", id="zhael_fates_thread", offer_id=nested["offer_id"], keep="original"))[
                "fate_offer"
            ]
            assert second["roller_id"] == guest and second["offer_id"] != nested["offer_id"]
            assert hp(session.combat_state) == [before[0] - 8, *before[1:]]
            assert not any(e.get("roll_type") == "narrative" for e in published_payloads(session.room))
            fresh = make_context(player_id=host, party_member_ids=[guest], room=session.room).userdata
            fresh.combat_state = await db_mutations.load_combat_state(state.combat_id)
            restored = game_tools(fresh, resolve_phase, activate)
            third = (await restored("resolve_phase"))["fate_offer"]
            assert third["roller_id"] == companion.id
            await restored("activate", id="zhael_fates_thread", offer_id=third["offer_id"])
            result = await restored("activate", id="zhael_fates_thread", offer_id=third["offer_id"], keep="reroll")
            assert dice.call_count == 5 and damage.call_count == 3
        assert [target["target_id"] for target in result["packets"][0]["targets"]] == area_ids
        assert hp(fresh.combat_state) == [initial - loss for initial, loss in zip(before, [8, 8, 4, 0], strict=True)]
        source = required_player(fresh.combat_state, choir.id)
        assert source.action_ledger["cacophony"]["remaining"] == 0
        assert not has_condition(source.conditions, "deafened") and not has_condition(source.conditions, "stunned")
        assert [
            entry["roll"] for entry in published_payloads(session.room) if entry.get("roll_type") == "saving_throw"
        ] == [
            7,
            15,
            20,
        ]
        assert has_condition(required_player(fresh.combat_state, guest).conditions, "stunned")
    finally:
        await db_mutations.delete_combat_state(state.combat_id)
