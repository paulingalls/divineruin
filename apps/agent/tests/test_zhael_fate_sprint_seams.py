"""Zhael's held d20 composes with the sprint's melee approach, Sneak Attack and attack spells."""

from unittest.mock import patch

import pytest
from _patron_engine_fixtures import configure
from _unbound_path_fixtures import world as world
from _zhael_fate_fixtures import attack, defend, game_tools
from acceptance._capstone_helpers import _build_state, _d20, _damage_die, _enemy, _player
from acceptance.test_kaelen_iron_resolve_capstone import required_player

import check_resolution_attack
import db_mutations
from activate_tools import activate
from combat_attack_roll import attack_roll_inputs, roll_attack, spend_sneak_attack
from combat_turn import declare_phase, resolve_phase
from conditions import has_condition


async def _keep(call, offer):
    return await call("activate", id="zhael_fates_thread", offer_id=offer["offer_id"], keep="original")


async def test_held_melee_swing_closes_distance_once_before_the_offer(world):
    await configure(world, "zhael", "mage")
    pid = world.ids[0]
    state = _build_state(pid, pid, [_enemy("foe", 30)])
    assert state.spatial is not None
    state.spatial["positions"]["foe"] = {"x": 20, "y": 0, "z": 0}
    state.spatial["speeds"][pid] = 30
    session = world.ctx.userdata
    session.combat_state = state
    call = game_tools(session, declare_phase, resolve_phase, activate)
    try:
        await call("declare_phase", declarations=[attack(pid, "foe"), defend("foe")])
        with (
            patch("check_resolution.dice_roll", side_effect=[_d20(1), _d20(20)]),
            patch("check_resolution_attack.dice_roll", return_value=_damage_die(4)),
        ):
            offer = (await call("resolve_phase"))["fate_offer"]
            assert session.combat_state is not None and session.combat_state.spatial is not None
            moved = dict(session.combat_state.spatial["positions"][pid])
            assert moved["x"] == 15 and offer["die"] == 1
            await call("activate", id="zhael_fates_thread", offer_id=offer["offer_id"])
            settled = await call("activate", id="zhael_fates_thread", offer_id=offer["offer_id"], keep="reroll")
        packet = settled["packets"][0]
        assert packet["hit"] and packet["closed_distance"] and packet["moved_ft"] == 15
        saved = await db_mutations.load_combat_state(state.combat_id)
        assert saved is not None and saved.spatial is not None
        assert saved.spatial["positions"][pid] == moved == packet["destination"]
        assert required_player(saved, "foe").hp_current < 30
    finally:
        await db_mutations.delete_combat_state(state.combat_id)


async def test_held_spell_attack_outside_the_choir_waits_for_the_choice(world):
    await configure(world, "zhael", "mage")
    pid = world.ids[0]
    state = _build_state(pid, pid, [_enemy("foe", 30)])
    session = world.ctx.userdata
    session.combat_state = state
    call = game_tools(session, declare_phase, resolve_phase, activate)
    try:
        await call(
            "declare_phase",
            declarations=[
                {**defend(pid), "kind": "ability", "action": "arcane_bolt", "targets": ["foe"]},
                defend("foe"),
            ],
        )
        with (
            patch("check_resolution.dice_roll", side_effect=[_d20(1), _d20(20)]),
            patch("check_resolution_attack.dice_roll", return_value=_damage_die(4)) as damage,
        ):
            offer = (await call("resolve_phase"))["fate_offer"]
            assert offer["roll_kind"] == "attack" and offer["die"] == 1
            assert required_player(session.combat_state, "foe").hp_current == 30 and not damage.called
            await call("activate", id="zhael_fates_thread", offer_id=offer["offer_id"])
            settled = await call("activate", id="zhael_fates_thread", offer_id=offer["offer_id"], keep="reroll")
        landed = settled["packets"][0]["cast"]["damage_result"]
        assert landed["hit"] and landed["critical"] and landed["roll"] == 20
        saved = await db_mutations.load_combat_state(state.combat_id)
        assert required_player(saved, "foe").hp_current == 30 - landed["damage"] < 30
    finally:
        await db_mutations.delete_combat_state(state.combat_id)


async def test_prepared_sneak_attack_spends_its_allowance_only_when_finished(world):
    pid = world.ids[0]
    state = _build_state(pid, pid, [_enemy("foe", 50)])
    rogue, foe = required_player(state, pid), required_player(state, "foe")
    rogue.archetype_id, rogue.level = "rogue", 1
    action = {**rogue.action_pool[0], "advantage": True}
    data, ac, mod = attack_roll_inputs(rogue, foe, 0, state, action, weapon_profile=action, player={"class": "rogue"})
    assert data["sneak_attack_available"]
    with patch("check_resolution.dice_roll", side_effect=[_d20(3), _d20(4)]):
        prepared = check_resolution_attack.prepare_attack(data, action, ac, attack_mod=mod)
    assert rogue.sneak_attack_round != state.round_number
    with patch("check_resolution_attack.dice_roll", return_value=_damage_die(3)):
        kept = check_resolution_attack.finish_attack(data, action, ac, 50, prepared, prepared.d20.evaluate(20))
    assert kept.critical_success and kept.sneak_attack_dice == "2d6"
    spend_sneak_attack(rogue, state, kept)
    assert rogue.sneak_attack_round == state.round_number
    assert not attack_roll_inputs(rogue, foe, 0, state, action, weapon_profile=action, player={"class": "rogue"})[0][
        "sneak_attack_available"
    ]


def test_finished_attack_keeps_the_prepared_disadvantage_cancel():
    rogue = {"level": 1, "attributes": {}, "sneak_attack_available": True, "conditions": [{"type": "prone"}]}
    weapon = {"damage": "1d8", "advantage": True}
    with patch("check_resolution.dice_roll", side_effect=[_d20(15)]):
        prepared = check_resolution_attack.prepare_attack(rogue, weapon, 10)
    assert prepared.d20.advantage and prepared.d20.disadvantage
    with patch("check_resolution_attack.dice_roll", return_value=_damage_die(5)):
        result = check_resolution_attack.finish_attack(rogue, weapon, 10, 50, prepared, prepared.d20.evaluate(15))
    assert result.hit and result.sneak_attack_dice is None


async def _rogue_swings(world):
    """A Zhael rogue with Extra Attack and an ally beside the target: both swings are held and kept."""
    await configure(world, "zhael", "rogue")
    pid = world.ids[0]
    state = _build_state(pid, pid, [_enemy("foe", 60)])
    rogue = required_player(state, pid)
    rogue.archetype_id, rogue.level, rogue.attack_mod, rogue.enhancers = "rogue", 5, 25, ["extra_attack"]
    ally = _player("ally")
    state.participants.append(ally)
    state.initiative_order.append(ally.id)
    assert state.spatial is not None
    state.spatial["positions"].update(foe={"x": 5, "y": 0, "z": 0}, ally={"x": 10, "y": 0, "z": 0})
    state.spatial["speeds"]["ally"] = 30
    session = world.ctx.userdata
    session.combat_state = state
    call = game_tools(session, declare_phase, resolve_phase, activate)
    try:
        await call("declare_phase", declarations=[attack(pid, "foe"), defend("foe"), defend("ally")])
        with (
            patch("check_resolution.dice_roll", side_effect=[_d20(15), _d20(14)]),
            patch("check_resolution_attack.dice_roll", return_value=_damage_die(3)),
        ):
            first = (await call("resolve_phase"))["fate_offer"]
            second = (await _keep(call, first))["fate_offer"]
            assert second["roller_id"] == pid and second["roll_kind"] == "attack"
            return (await _keep(call, second))["packets"][0], state
    finally:
        await db_mutations.delete_combat_state(state.combat_id)


async def test_held_extra_attack_swings_land_sneak_attack_once(world):
    """F2: the held ally swing spends the round's Sneak Attack, so the second held swing gets none."""
    packet, _ = await _rogue_swings(world)
    assert [(a["sneak_attack_dice"], a["damage"]) for a in packet["attacks"]] == [("2d6", 6), (None, 3)]


async def test_receipt_branch_lands_the_critical_save_rider(world):
    """F3: with a Zhael follower present the blow lands through the damage receipt, which must still
    roll the Hollowed Knight's on-crit save and land its condition."""
    await configure(world, "zhael", "mage")
    pid = world.ids[0]
    knight = _enemy("knight", 30)
    rider = {"save": "CON", "dc": 14, "applies_condition": "hollowed", "stage": 1}
    knight.action_pool = [{**knight.action_pool[0], "critical_save": rider}]
    state = _build_state(pid, pid, [knight])
    session = world.ctx.userdata
    session.combat_state = state
    call = game_tools(session, declare_phase, resolve_phase, activate)
    try:
        await call("declare_phase", declarations=[defend(pid), {**attack("knight", pid), "action": "Scimitar"}])
        with (
            patch("check_resolution.dice_roll", side_effect=[_d20(20), _d20(3)]),
            patch("check_resolution_attack.dice_roll", return_value=_damage_die(2)),
        ):
            await call("resolve_phase")
            blow = (await call("resolve_phase"))["fate_offer"]
            save = (await _keep(call, blow))["fate_offer"]
            result = await _keep(call, save)
        packet = next(p for p in result["packets"] if p.get("actor_id") == "knight" and p.get("hit"))
        assert packet["critical"] and packet["critical_save"] == {"dc": 14, "roll": 3, "total": 3, "success": False}
        assert packet["condition_inflicted"] == "hollowed"
        assert has_condition(required_player(session.combat_state, pid).conditions, "hollowed")
    finally:
        await db_mutations.delete_combat_state(state.combat_id)


@pytest.mark.parametrize("first_face", [2, 15], ids=["miss", "hit_without_advantage"])
def test_sneak_attack_is_spent_only_when_its_dice_land(first_face):
    """F5: a swing that adds no Sneak dice (a miss, or a hit with no advantage or adjacent ally)
    leaves the round's allowance for a later swing that earns it."""
    state = _build_state("rogue", "rogue", [_enemy("foe", 50)])
    rogue, foe = required_player(state, "rogue"), required_player(state, "foe")
    rogue.archetype_id, rogue.level = "rogue", 1
    plain = rogue.action_pool[0]
    with (
        patch("check_resolution.dice_roll", side_effect=[_d20(first_face), _d20(15), _d20(15)]),
        patch("check_resolution_attack.dice_roll", return_value=_damage_die(3)),
    ):
        first, _ = roll_attack(rogue, plain, foe, combat_state=state, weapon_profile=plain, player={"class": "rogue"})
        assert first.sneak_attack_dice is None and rogue.sneak_attack_round != state.round_number
        earned, _ = roll_attack(
            rogue,
            {**plain, "advantage": True},
            foe,
            combat_state=state,
            weapon_profile=plain,
            player={"class": "rogue"},
        )
    assert earned.hit and earned.sneak_attack_dice == "1d6"
    assert rogue.sneak_attack_round == state.round_number


async def _held_bolt(world, setup, during_hold=lambda state: None):
    """A Zhael mage's Arcane Bolt is held, ``during_hold`` runs on the live state, then the original is kept."""
    await configure(world, "zhael", "mage")
    pid = world.ids[0]
    state = _build_state(pid, pid, [_enemy("foe", 30)])
    setup(state, pid)
    session = world.ctx.userdata
    session.combat_state = state
    call = game_tools(session, declare_phase, resolve_phase, activate)
    bolt = {**defend(pid), "kind": "ability", "action": "arcane_bolt", "targets": ["foe"]}
    try:
        await call("declare_phase", declarations=[bolt, *(defend(p.id) for p in state.participants[1:])])
        with (
            patch("check_resolution.dice_roll", side_effect=[_d20(15)]),
            patch("check_resolution_attack.dice_roll", return_value=_damage_die(4)),
        ):
            offer = (await call("resolve_phase"))["fate_offer"]
            during_hold(session.combat_state)
            settled = await _keep(call, offer)
        return settled["packets"][0]["cast"]["damage_result"]
    finally:
        await db_mutations.delete_combat_state(state.combat_id)


async def test_held_spell_attack_never_earns_sneak_attack(world):
    """M17: spell attacks pass weapon_attack=False on the held path too, so a rogue caster beside an
    ally gets no Sneak Attack."""

    def rogue_beside_ally(state, pid):
        required_player(state, pid).archetype_id = "rogue"
        ally = _player("ally")
        state.participants.append(ally)
        state.initiative_order.append(ally.id)
        state.spatial["positions"]["ally"] = dict(state.spatial["positions"]["foe"])
        state.spatial["speeds"]["ally"] = 30

    landed = await _held_bolt(world, rogue_beside_ally)
    assert landed["hit"] and landed["sneak_attack_dice"] is None


async def test_held_spell_attack_finishes_against_a_target_downed_mid_hold(world):
    """M16: a held bolt resumes against its recipient even if something dropped it during the pause."""

    def down(state):
        foe = required_player(state, "foe")
        foe.hp_current, foe.is_fallen = 0, True

    landed = await _held_bolt(world, lambda state, pid: None, down)
    assert landed["hit"] and landed["damage"] > 0 and "resolved" not in landed
