"""Patron critical edges through the registered combat tools."""

from contextlib import asynccontextmanager
from unittest.mock import patch

import pytest
from _patron_engine_fixtures import configure
from _unbound_path_fixtures import world as world
from _zhael_fate_fixtures import attack, defend, game_tools
from acceptance._capstone_helpers import _build_state, _d20, _damage_die, _enemy, _player
from creature_combat_helpers import participant as creature_participant
from sample_fixtures import published_payloads
from test_aelora_gift import _live_party
from voice_condition_fixtures import participant, place_actors

import character_spells
import db_mutations
from _gods_content import load_gods
from activate_tools import activate
from combat_turn import declare_phase, resolve_phase
from conditions import apply_condition
from creature_combat_loader import load_creature_enemy
from query_tools import query_info

SPENT = {"zhael_fates_thread": {"spent": True}, "zhael_lucky": {"spent": True}}


@asynccontextmanager
async def fight(world, *, ac=40, hp=100, ally=False):
    host, guest = world.ids
    foe = _enemy("foe", hp)
    foe.ac = ac
    state = _build_state(host, host, [foe])
    state.terrain = "forest"
    if ally:
        state.participants.insert(1, _player(guest))
        state.initiative_order.insert(1, guest)
        place_actors(state)
    session = world.ctx.userdata
    session.combat_state = state
    try:
        yield state
    finally:
        await db_mutations.delete_combat_state(state.combat_id)


async def saved_hp(state, actor="foe"):
    saved = await db_mutations.load_combat_state(state.combat_id)
    return participant(saved, actor).hp_current


def dice_events(world):
    return [e for e in published_payloads(world.ctx.userdata.room) if e.get("roll_type") == "attack"]


def assert_critical(packet, world, *, damage, context="critical_hit", face=19, sneak=None):
    assert (packet["hit"], packet["critical"], packet["damage"]) == (True, True, damage)
    assert (packet["narrative_hint"], packet["dramatic"], packet["context"]) == ("critical success", True, context)
    event = dice_events(world)[-1]
    assert (event["roll"], event["success"], event["critical"], event["dramatic"]) == (face, True, True, True)
    assert (event["narrative"], event["context"]) == ("critical success", context)
    if face == 19:
        assert event["total"] < packet["target_ac"]
    if sneak is not None:
        for report in packet, event:
            assert (report["sneak_attack_dice"], report["sneak_attack_raw_damage"]) == ("2d6", sneak)


async def weapon_round(world, *, face: int | tuple[int, ...], damage, omit=()):
    host = world.ids[0]
    state = world.ctx.userdata.combat_state
    call = game_tools(world.ctx.userdata, declare_phase, resolve_phase)
    declarations = [
        attack(host, "foe"),
        *[defend(p.id) for p in state.participants if p.id != host and p.id not in omit],
    ]
    await call("declare_phase", declarations=declarations)
    d20s = (
        patch("check_resolution.dice_roll", side_effect=[_d20(f) for f in face])
        if isinstance(face, tuple)
        else patch("check_resolution.dice_roll", return_value=_d20(face))
    )
    with (
        d20s,
        patch("check_resolution_attack.dice_roll", side_effect=damage) as rolls,
        patch("patron_synergy_combat.dice_roll", rolls),
    ):
        result = await call("resolve_phase")
    return next(p for p in result["packets"] if p["actor_id"] == host), rolls


async def zhael_weapon(world):
    await configure(world, "zhael", "rogue", patron_gifts=SPENT)
    async with fight(world, ally=True) as state:
        participant(state, world.ids[0]).archetype_id = "rogue"
        packet, rolls = await weapon_round(world, face=19, damage=[_damage_die(5)] * 2 + [_damage_die(8)])
        assert_critical(packet, world, damage=18, sneak=8)
        assert [c.args[0] for c in rolls.call_args_list] == ["1d8", "1d8", "2d6"]
        assert await saved_hp(state) == 82


@pytest.mark.parametrize("archetype,face", [("rogue", 18), ("warrior", 19)])
async def test_zhael_weapon_control(world, archetype, face):
    await configure(world, "zhael", archetype, patron_gifts=SPENT)
    async with fight(world) as state:
        participant(state, world.ids[0]).archetype_id = archetype
        packet, rolls = await weapon_round(world, face=face, damage=[])
        assert (packet["hit"], packet["critical"], packet["damage"]) == (False, False, 0)
        assert not rolls.called
        assert await saved_hp(state) == 100


async def test_guest_uses_own_row(world):
    host, guest = world.ids
    await configure(world, "kaelen", "warrior")
    await configure(world, "zhael", "rogue", index=1, patron_gifts=SPENT)
    world.ctx.userdata.party.members[1].patron_id = "kaelen"
    async with fight(world, ally=True) as state:
        participant(state, guest).archetype_id = "warrior"
        lifecycle = _live_party(world.ctx.userdata, host, guest)
        try:
            call = game_tools(world.ctx.userdata, declare_phase, resolve_phase)
            await call("declare_phase", declarations=[attack(host, "foe"), attack(guest, "foe"), defend("foe")])
            with (
                patch("check_resolution.dice_roll", return_value=_d20(19)),
                patch("check_resolution_attack.dice_roll", return_value=_damage_die(5)),
            ):
                result = await call("resolve_phase")
            first, second = result["packets"]
            assert (first["actor_id"], first["hit"], first["critical"], first["damage"]) == (host, False, False, 0)
            assert second["actor_id"] == guest
            assert_critical(second, world, damage=10)
            assert [(e["roll"], e["critical"]) for e in dice_events(world)] == [(19, False), (19, True)]
            assert await saved_hp(state) == 90
        finally:
            await lifecycle.aclose()


async def thyra_weapon(world, archetype, *, face=20, resistant=False):
    await configure(world, "thyra", archetype)
    async with fight(world, ac=10) as state:
        target = participant(state, "foe")
        if resistant:
            target.damage_affinities = {"resistant": ["lightning"]}
        packet, rolls = await weapon_round(world, face=face, damage=[_damage_die(5)] * 2 + [_damage_die(3)])
        rider = face == 20 and archetype != "bard"
        extra = (1 if resistant else 3) if rider else 0
        expected = (10 if face == 20 else 5) + extra
        assert (packet["damage"], packet.get("synergy_damage", 0), packet.get("synergy_damage_type")) == (
            expected,
            extra,
            "lightning" if rider else None,
        )
        assert [c.args[0] for c in rolls.call_args_list].count("1d4") == int(rider)
        if rider:
            event = dice_events(world)[-1]
            assert (event["synergy_damage"], event["synergy_damage_type"]) == (extra, "lightning")
        assert await saved_hp(state) == 100 - expected


@pytest.mark.parametrize(
    "archetype,face,resistant", [("warrior", 20, True), ("warrior", 15, False), ("bard", 20, False)]
)
async def test_thyra_weapon_edges(world, archetype, face, resistant):
    await thyra_weapon(world, archetype, face=face, resistant=resistant)


async def test_resisted_lightning_cannot_turn_critical_damage_into_healing(world):
    await configure(world, "thyra", "warrior")
    async with fight(world, ac=10, hp=90) as state:
        participant(state, world.ids[0]).attributes = {"strength": 5}
        participant(state, "foe").hp_max = 100
        participant(state, "foe").damage_affinities = {"resistant": ["lightning"]}
        packet, rolls = await weapon_round(world, face=20, damage=[_damage_die(1)] * 3)
        assert [c.args[0] for c in rolls.call_args_list] == ["1d8", "1d8", "1d4"]
        assert (packet["damage"], packet["synergy_damage"], await saved_hp(state)) == (0, 0, 90)


async def assert_active_clause(world, patron, archetype, synergy_type, implementation):
    authored = next(g for g in load_gods() if g["god_id"] == patron)["layer_4_synergy_matrix"][archetype]
    reported = (await game_tools(world.ctx.userdata, query_info)("query_info", kind="patron"))["synergy"]
    assert reported == authored
    assert authored["type"] == synergy_type
    assert [(c["status"], c["resolution"], c.get("implementation_id")) for c in authored["clauses"]] == [
        ("active", "engine", implementation)
    ]


async def zhael_spell_or_fate(world, archetype, *, held=False):
    host = world.ids[0]
    spell = archetype == "mage"
    gifts = {"zhael_lucky": {"spent": True}} if held else SPENT
    await configure(world, "zhael", archetype, level=1, patron_gifts=gifts, resonance={"current": 0})
    world.ctx.userdata.resonance.current = 0
    if spell:
        await character_spells.record_learned(host, "arcane_bolt", "training", is_prepared=True, conn=world.pool)
    async with fight(world, ally=not spell) as state:
        participant(state, host).archetype_id = archetype
        call = game_tools(world.ctx.userdata, declare_phase, resolve_phase, activate)
        strike = (
            {**defend(host), "kind": "ability", "action": "arcane_bolt", "targets": ["foe"]}
            if spell
            else attack(host, "foe")
        )
        await call("declare_phase", declarations=[strike, *[defend(p.id) for p in state.participants if p.id != host]])
        with (
            patch("check_resolution.dice_roll", side_effect=[_d20(1), _d20(19)] if held else [_d20(19)]) as d20s,
            patch("check_resolution_attack.dice_roll", side_effect=[_damage_die(5)] * 2 + [_damage_die(8)]) as rolls,
        ):
            result = await call("resolve_phase")
            if held:
                offer = result["fate_offer"]
                assert offer["roller_id"] == host and offer["die"] == 1
                assert await saved_hp(state) == 100
                args = {"id": "zhael_fates_thread", "offer_id": offer["offer_id"]}
                await call("activate", **args)
                assert not rolls.called
                world.ctx.userdata.combat_state = await db_mutations.load_combat_state(state.combat_id)
                result = await call("activate", **args, keep="reroll")
                assert d20s.call_count == 2
        packet = result["packets"][0]
        if spell:
            packet = packet["cast"]["damage_result"]
        expected = 10 if spell else 18
        assert_critical(packet, world, damage=expected, sneak=None if spell else 8)
        assert [c.args[0] for c in rolls.call_args_list] == (["1d6", "1d6"] if spell else ["1d8", "1d8", "2d6"])
        assert await saved_hp(state) == 100 - expected


@pytest.mark.parametrize("archetype", ["rogue", "mage"])
async def test_fate_reroll_roundtrip(world, archetype):
    await zhael_spell_or_fate(world, archetype, held=True)


@pytest.mark.parametrize("face,context", [(19, "critical_hit"), (20, "natural_20")])
async def test_adjusted_lethal_critical_keeps_context(world, face, context):
    await configure(world, "zhael", "rogue", patron_gifts=SPENT)
    async with fight(world, hp=4) as state:
        state.participants.append(_enemy("survivor", 100))
        state.initiative_order.append("survivor")
        place_actors(state)
        participant(state, "foe").damage_affinities = {"resistant": ["slashing"]}
        packet, _ = await weapon_round(world, face=face, damage=[_damage_die(5)] * 2)
        assert_critical(packet, world, damage=5, context=context, face=face)
        assert packet["target_fallen"]
        assert await saved_hp(state) == 0


async def test_thyra_second_swing_carries_lightning_type(world):
    await configure(world, "thyra", "warrior")
    async with fight(world, ac=10) as state:
        participant(state, world.ids[0]).enhancers = ["extra_attack"]
        packet, _ = await weapon_round(world, face=(15, 20), damage=[_damage_die(5)] * 3 + [_damage_die(3)])
        assert [(s["damage"], s.get("synergy_damage"), s.get("synergy_damage_type")) for s in packet["attacks"]] == [
            (5, 0, None),
            (13, 3, "lightning"),
        ]
        assert (packet["damage"], packet["synergy_damage"], packet["synergy_damage_type"]) == (18, 3, "lightning")
        assert await saved_hp(state) == 82


async def test_condition_crit_keeps_all_three_typed_components(world):
    await configure(world, "thyra", "warrior")
    async with fight(world, ac=10) as state:
        attacker = participant(state, world.ids[0])
        attacker.action_pool = [
            {
                **attacker.action_pool[0],
                "bonus_damage": {"dice": "1d6", "damage_type": "fire"},
            }
        ]
        attacker.pending_preparation = {"on_hit": {"damage": "1d8", "damage_type": "cold", "ignores_resistance": True}}
        target = participant(state, "foe")
        target.conditions = apply_condition([], "paralyzed")
        target.damage_affinities = {"resistant": ["cold"]}
        packet, rolls = await weapon_round(
            world, face=(15, 15), omit=("foe",), damage=[_damage_die(n) for n in (5, 5, 4, 6, 3)]
        )
        assert packet["critical"]
        assert [(packet[k], packet[f"{k}_type"]) for k in ("bonus_damage", "rider_damage", "synergy_damage")] == [
            (4, "fire"),
            (6, "cold"),
            (3, "lightning"),
        ]
        assert [c.args[0] for c in rolls.call_args_list] == ["1d8", "1d8", "1d6", "1d8", "1d4"]
        assert packet["damage"] == 23 and await saved_hp(state) == 77


async def test_lightning_does_not_count_as_radiant(world):
    await configure(world, "thyra", "warrior")
    async with fight(world, ac=10) as state:
        attacker = participant(state, world.ids[0])
        attacker.action_pool = [{**attacker.action_pool[0], "damage_type": "radiant"}]
        boss = await load_creature_enemy(
            "hollow_veilrender", encounter_id=state.combat_id, enemy_id="foe", role="standard"
        )
        target = creature_participant(boss)
        target.hp_current = 100
        target.damage_affinities = {"immune": ["radiant"]}
        state.participants[1] = target
        attacker.veilrender_turn_round = state.round_number
        packet, _ = await weapon_round(world, face=20, omit=("foe",), damage=[_damage_die(5)] * 2 + [_damage_die(3)])
        assert (packet["damage"], packet["synergy_damage"]) == (3, 3)
        saved = await db_mutations.load_combat_state(state.combat_id)
        target = participant(saved, "foe")
        assert target.hp_current == 97 and not target.radiant_suppression_pending


async def zhael_engine(world, archetype):
    if archetype == "rogue":
        await zhael_weapon(world)
    else:
        await zhael_spell_or_fate(world, archetype)
    await assert_active_clause(world, "zhael", archetype, "divine", "zhael_bent_probability")


async def thyra_engine(world, archetype):
    await thyra_weapon(world, archetype)
    await assert_active_clause(world, "thyra", archetype, "unexpected", "thyra_natures_edge")


SCENARIOS = {
    "zhael_bent_probability": ("patron_synergy_combat:expanded_critical", zhael_engine, [("rogue",), ("mage",)]),
    "thyra_natures_edge": ("patron_synergy_combat:critical_rider", thyra_engine, [("warrior",), ("skirmisher",)]),
}


@pytest.mark.parametrize("held", [False, True])
async def test_risen_thyra_warrior_keeps_both_riders(world, held):
    host, guest = world.ids
    hollowed = [{"type": "hollowed", "source": "veil", "duration": None, "stage": 2}]
    await configure(world, "thyra", "warrior", conditions=hollowed, hp={"current": 5, "max": 100})
    await configure(world, "none", "mage", index=1, hp={"current": 100, "max": 100})
    async with fight(world, ac=10, ally=True) as state:
        actor = participant(state, host)
        actor.hp_current = 5
        actor.conditions = hollowed
        target = participant(state, guest)
        target.damage_affinities = {"resistant": ["slashing", "lightning"], "vulnerable": ["necrotic"]}
        session = world.ctx.userdata
        lifecycle = _live_party(session, host, guest)
        call = game_tools(session, declare_phase, resolve_phase, activate)
        try:
            strike = {**attack("foe", host), "action": "Scimitar"}
            await call("declare_phase", declarations=[defend(host), defend(guest), strike])
            with (
                patch("check_resolution.dice_roll", return_value=_d20(15)),
                patch("check_resolution_attack.dice_roll", return_value=_damage_die(6)),
            ):
                await call("resolve_phase")
                result = await call("resolve_phase")
            assert result["packets"][0]["target_rose_hollowed"]
            risen = participant(session.combat_state, host)
            assert risen.type == "temporary_hollowed" and risen.id == host
            assert session.combat_state.beat == "declaration"

            if held:
                await configure(world, "zhael", "mage", index=1, hp={"current": 100, "max": 100})
            await call("declare_phase", declarations=[attack(host, guest), defend(guest), defend("foe")])
            await call("resolve_phase")
            with (
                patch("check_resolution.dice_roll", return_value=_d20(20)),
                patch("check_resolution_attack.dice_roll", side_effect=[_damage_die(5)] * 2 + [_damage_die(3)]) as base,
                patch("patron_synergy_combat.dice_roll", return_value=_damage_die(3)) as rider,
            ):
                result = await call("resolve_phase")
                if held:
                    offer = result["fate_offer"]
                    assert offer["roller_id"] == host and guest in offer["eligible_followers"]
                    assert not base.called and not rider.called
                    assert await saved_hp(state, guest) == 100
                    session.combat_state = await db_mutations.load_combat_state(state.combat_id)
                    with session._bind_authenticated_actor(guest, 1, lifecycle.require_authorized):
                        result = await call(
                            "activate", id="zhael_fates_thread", offer_id=offer["offer_id"], keep="original"
                        )
            packet = next(p for p in result["packets"] if p.get("actor_id") == host)
            assert packet["critical"]
            assert (packet["damage"], packet["bonus_damage"], packet["bonus_damage_type"]) == (12, 6, "necrotic")
            assert (packet["synergy_damage"], packet["synergy_damage_type"]) == (1, "lightning")
            assert rider.call_count == 1
            assert await saved_hp(state, guest) == 88
        finally:
            await lifecycle.aclose()
