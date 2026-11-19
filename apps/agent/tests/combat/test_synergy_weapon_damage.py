"""Kaelen weapon damage through registered combat tools and persisted players."""

from unittest.mock import MagicMock, patch

import pytest
from _patron_engine_fixtures import configure
from _unbound_path_fixtures import row
from _unbound_path_fixtures import world as world
from _zhael_fate_fixtures import attack, defend, game_tools
from acceptance._capstone_helpers import _d20, _damage_die
from acceptance.seeds import seed_player_with_pools
from test_aelora_gift import _live_party
from voice_condition_fixtures import participant, place_actors

import db_mutations
import milestones
from _gods_content import load_gods
from activate_tools import activate
from combat_turn import declare_phase, resolve_phase
from mode_tools import enter_mode
from query_tools import query_info
from quest_tools import update_quest
from rules_engine import XP_FOR_LEVEL

ARCHETYPES = ("warrior", "guardian", "skirmisher")
IMPLEMENTATION = "kaelen_extra_attack_damage"


async def weapon_round(
    world,
    archetype,
    *,
    faces,
    expected,
    bonus_dice,
    patron="kaelen",
    level=10,
    flagged=True,
    resistant=False,
    held=False,
    earn_extra_attack=False,
):
    host, guest = world.ids
    session = world.ctx.userdata
    damage_type = "piercing" if resistant else "slashing"
    weapon = "Rapier" if resistant else "Longsword"
    await seed_player_with_pools(world.pool, player_id=host, class_=archetype)
    attributes = {"strength": 10, "dexterity": 10}
    if earn_extra_attack:
        seeded = await row(world, index=0)
        attributes = {**seeded["attributes"], **attributes}
    await configure(
        world,
        patron,
        archetype,
        level=9 if earn_extra_attack else level,
        flags={"extra_attack": True} if flagged and not earn_extra_attack else {},
        attributes=attributes,
        hp={"current": 100, "max": 100},
        equipment={"main_hand": {"name": weapon, "damage": "1d8", "damage_type": damage_type, "properties": []}},
        **({"xp": XP_FOR_LEVEL[10] - 1} if earn_extra_attack else {}),
    )
    await seed_player_with_pools(world.pool, player_id=guest, class_="mage")
    if earn_extra_attack:
        await milestones.load_milestones()
        quest = "greyvale_anomaly"
        await db_mutations.set_player_quest(host, quest, {"current_stage": 1})
        result = await game_tools(session, update_quest)("update_quest", quest_id=quest, new_stage_id=2)
        earned = await row(world, index=0)
        assert earned["level"] == 10, result
        assert earned.get("flags", {}).get("extra_attack") is True
        assert [grant["name"] for grant in result["milestone_grants"]] == ["Extra Attack and Shield Mastery"]
    if held:
        await configure(world, "zhael", "mage", index=1, patron_gifts={"zhael_lucky": {"spent": True}})
    lifecycle = _live_party(session, host, guest) if held else None
    call = game_tools(session, enter_mode, declare_phase, resolve_phase, activate)
    try:
        with patch("combat_agent.create_combat_agent", return_value=MagicMock()):
            await call("enter_mode", mode="combat", encounter_id="ruins_mawling_pair")
        state = session.combat_state
        assert participant(state, host).enhancers == (["extra_attack"] if flagged else [])
        foe = participant(state, "mawling_1")
        state.terrain = "forest"
        foe.hp_current = foe.hp_max = 100
        foe.ac = 10
        foe.damage_affinities = {"resistant": [damage_type]} if resistant else {}
        foe.resist_nonmagical_physical = False
        place_actors(state)
        strike = {**attack(host, foe.id), "action": weapon}
        await call("declare_phase", declarations=[strike, *[defend(p.id) for p in state.participants if p.id != host]])

        def damage_roll(notation, *, rng):
            return _damage_die({"1d8": 7 if resistant else 5, "1d4": 3, "2d4": 6}[notation])

        async def saved_hp():
            saved = await db_mutations.load_combat_state(state.combat_id)
            return participant(saved, foe.id).hp_current

        with (
            patch("check_resolution.dice_roll", side_effect=[_d20(face) for face in faces]) as d20s,
            patch("check_resolution_attack.dice_roll", side_effect=damage_roll) as base_rolls,
            patch("patron_synergy_combat.dice_roll", side_effect=damage_roll) as bonus_rolls,
        ):
            packets = []
            offers = 0
            for _ in range(len(state.participants) + 1):
                result = await call("resolve_phase")
                while "fate_offer" in result:
                    assert held and offers < len(faces)
                    offer = result["fate_offer"]
                    assert offer["roller_id"] == host and offer["die"] == faces[offers]
                    assert guest in offer["eligible_followers"]
                    assert base_rolls.call_count == offers
                    if offers == 0:
                        assert not bonus_rolls.called
                        assert await saved_hp() == 100
                    offers += 1
                    session.combat_state = await db_mutations.load_combat_state(state.combat_id)
                    assert lifecycle is not None
                    with session._bind_authenticated_actor(guest, 1, lifecycle.require_authorized):
                        result = await call(
                            "activate", id="zhael_fates_thread", offer_id=offer["offer_id"], keep="original"
                        )
                packets.extend(result.get("packets", []))
                if result.get("beat") == "declaration":
                    break
            else:
                raise AssertionError("round did not finish")

        assert offers == (len(faces) if held else 0)
        packet = next(p for p in packets if p["actor_id"] == host)
        assert packet["resolved"] is True
        assert ("attacks" in packet) is flagged
        if not flagged:
            assert "riders" not in packet
        swings = packet.get("attacks", [packet])
        assert tuple(s["damage"] for s in swings) == expected
        assert tuple((s["hit"], s["critical"]) for s in swings) == tuple((f != 1, f == 20) for f in faces)
        assert all(s["damage_type"] == damage_type for s in swings if s["hit"])
        assert packet["damage"] == sum(expected)
        assert await saved_hp() == 100 - sum(expected)
        assert tuple(c.args[0] for c in bonus_rolls.call_args_list) == bonus_dice
        assert d20s.call_count == len(faces)
    finally:
        if session.combat_state is not None:
            await db_mutations.delete_combat_state(session.combat_state.combat_id)
        if lifecycle is not None:
            await lifecycle.aclose()


async def kaelen_weapon(world, archetype):
    if archetype == "guardian":
        await weapon_round(
            world, archetype, faces=(15, 15), expected=(8, 8), bonus_dice=("1d4", "1d4"), earn_extra_attack=True
        )
    else:
        await weapon_round(world, archetype, faces=(15, 20), expected=(8, 16), bonus_dice=("1d4", "2d4"))
    authored = next(g for g in load_gods() if g["god_id"] == "kaelen")["layer_4_synergy_matrix"][archetype]
    reported = (await game_tools(world.ctx.userdata, query_info)("query_info", kind="patron"))["synergy"]
    assert reported == authored
    assert authored["type"] == "natural"
    assert [(c["status"], c["resolution"], c.get("implementation_id")) for c in authored["clauses"]] == [
        ("active", "engine", "kaelen_tempered_resolve"),
        ("active", "engine", IMPLEMENTATION),
    ]


@pytest.mark.parametrize(
    "patron,archetype,level,flagged",
    [
        *(("kaelen", a, 9, False) for a in ARCHETYPES),
        ("kaelen", "warrior", 10, False),
        ("kaelen", "bard", 10, True),
        ("thyra", "warrior", 10, True),
    ],
)
async def test_base_weapon_damage(world, patron, archetype, level, flagged):
    swings = 2 if flagged else 1
    await weapon_round(
        world,
        archetype,
        faces=(15,) * swings,
        expected=(5,) * swings,
        bonus_dice=(),
        patron=patron,
        level=level,
        flagged=flagged,
    )


async def test_miss_does_not_roll_bonus(world):
    await weapon_round(world, "warrior", faces=(1, 15), expected=(0, 8), bonus_dice=("1d4",))


async def test_resistance_applies_to_combined_weapon_damage(world):
    await weapon_round(world, "warrior", faces=(15, 15), expected=(5, 5), bonus_dice=("1d4", "1d4"), resistant=True)


async def test_held_swing_uses_prepared_bonus_once(world):
    await weapon_round(world, "warrior", faces=(15, 20), expected=(8, 16), bonus_dice=("1d4", "2d4"), held=True)


SCENARIOS = {
    IMPLEMENTATION: ("patron_synergy_combat:weapon_damage_bonus", kaelen_weapon, [(a,) for a in ARCHETYPES]),
}
