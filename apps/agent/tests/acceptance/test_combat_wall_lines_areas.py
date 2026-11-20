"""Area and automatic deliveries use their authored origins in persisted combat."""

from random import Random
from unittest.mock import patch

import pytest
from _spell_heal_fixtures import MASS
from _spell_heal_fixtures import spell_heal_walk as spell_heal_walk
from acceptance._capstone_helpers import _damage_die, _resolve_round
from acceptance._spatial_helpers import pos
from acceptance._spatial_helpers import spatial_entry as spatial_entry
from acceptance._structure_helpers import _refuses, _reload, _save_and_reload, _strike
from acceptance.test_choir_encounter import search
from combat.test_area_spell_recipients import add_enemies, resolve_cast
from combat.test_spell_damage_lands import prepare_spell
from combat.test_spell_damage_lands import spell_fight as spell_fight
from voice_condition_fixtures import participant

import check_resolution_save
import combat_spatial
import db
from combat_structures import add_wall
from combat_turn import declare_phase
from declaration_payloads import AbilityDecl


@pytest.fixture
def mock_combat_agent_factory() -> None:
    return None


@pytest.fixture
async def dev_db_pool(reset_db_pool):
    return await db.get_pool()


def wall(state, x=10):
    return add_wall(state, "wall", "Slate Wall", pos(x, -5), pos(x, 5))


def cast(ctx, spell, targets):
    return AbilityDecl(kind="ability", actor_id=ctx.userdata.player_id, action=spell, targets=targets, argument_type="")


@pytest.mark.parametrize(
    "spell,caster,points,anchors,delivered,wall_x",
    [
        (
            "divine_flame_strike",
            -30,
            {"foe": (14, 0), "near": (16, 0), "hidden": (6, 0), "out": (30, 0)},
            ["foe"],
            {"foe", "near", "wall"},
            10,
        ),
        (
            "divine_flame_strike",
            -30,
            {"foe": (8, 2), "near": (8, 0), "far": (12, 0), "out": (30, 0)},
            ["wall"],
            {"foe", "near", "far", "wall"},
            10,
        ),
        ("arcane_lightning_bolt", 0, {"foe": (5, 0), "hidden": (12, 0), "out": (5, 12)}, ["foe"], {"foe", "wall"}, 10),
        ("divine_sacred_word", 0, {"foe": (3, 0), "hidden": (8, 0), "out": (0, 12)}, [], {"foe"}, 5),
        ("divine_sacred_word", 0, {"foe": (8, 0), "out": (0, 12)}, [], set(), 5),
        (
            "arcane_meteor_swarm",
            -30,
            {"foe": (0, 0), "near": (20, 17), "overlap": (15, 0), "hidden": (11, -4), "out": (45, 0)},
            ["foe", "near"],
            {"foe", "near", "overlap", "wall"},
            10,
        ),
    ],
)
async def test_authored_area_filters_coverage_by_each_effect_origin(
    spell_fight, spell, caster, points, anchors, delivered, wall_x
) -> None:
    ctx = spell_fight
    await prepare_spell(ctx, spell)
    await add_enemies(ctx, {name: (*coords, 0) for name, coords in points.items()})
    state = ctx.userdata.combat_state
    combat_spatial.place(state, ctx.userdata.player_id, pos(caster))
    for target_id in points:
        participant(state, target_id).category = "undead"
    wall(state, wall_x)
    state = await _save_and_reload(ctx)
    before = {target_id: participant(state, target_id).hp_current for target_id in [*points, "wall"]}
    await declare_phase(ctx, [cast(ctx, spell, anchors)])
    result = await resolve_cast(ctx)
    damage = {r["target_id"]: r["damage"] for r in result["damage_results"]}
    assert set(damage) == delivered and len(result["damage_results"]) == len(delivered)
    saved = await _reload(ctx)
    for target_id, hp in before.items():
        assert participant(saved, target_id).hp_current == hp - damage.get(target_id, 0)
        assert (participant(saved, target_id).hp_current < hp) == (target_id in delivered)


@pytest.mark.parametrize("spell", ["arcane_chain_lightning", "arcane_magic_missile"])
async def test_explicit_deliveries_refuse_and_automatic_chain_jumps_from_primary(spell_fight, spell) -> None:
    ctx = spell_fight
    await prepare_spell(ctx, spell)
    await add_enemies(ctx, {"foe": (8, 3, 0), "hidden": (12, 3, 0), "clear": (8, 15, 0), "out": (8, 50, 0)})
    state = ctx.userdata.combat_state
    combat_spatial.place(state, ctx.userdata.player_id, pos())
    wall(state)
    await _save_and_reload(ctx)
    await _refuses(ctx, cast(ctx, spell, ["hidden"]), r"Slate Wall \(wall\)")
    chain = spell == "arcane_chain_lightning"
    named = ["foe", "hidden"] if chain else ["foe", "hidden", "foe", "foe"]
    await _refuses(ctx, cast(ctx, spell, named), r"Slate Wall \(wall\)")
    await declare_phase(ctx, [cast(ctx, spell, ["foe"])])
    result = await resolve_cast(ctx)
    assert [r["target_id"] for r in result["damage_results"]] == (["foe", "wall", "clear"] if chain else ["foe"])
    saved = await _reload(ctx)
    assert participant(saved, "hidden").hp_current == 100
    assert (participant(saved, "clear").hp_current < 100) == chain


@pytest.mark.parametrize(
    "encounter,enemy,action",
    [("hollow_choir", "choir_zone", "Memory Scream"), ("hollow_veilrender_boss", "veilrender", "Corruption Wave")],
)
async def test_enemy_areas_filter_from_the_acting_enemy(spatial_entry, encounter, enemy, action) -> None:
    ctx, _ = await spatial_entry(members=3, encounter=encounter)
    if enemy == "choir_zone":
        await search(ctx)
    state = ctx.userdata.combat_state
    blocked = ctx.userdata.player_id
    clear, outside = [p.id for p in state.participants if p.is_ally and p.id != blocked]
    for actor, point in [(enemy, pos()), (blocked, pos(12)), (clear, pos(5)), (outside, pos(0, 70))]:
        combat_spatial.place(state, actor, point)
    wall(state)
    state = await _save_and_reload(ctx)
    before = {actor: participant(state, actor).hp_current for actor in (clear, blocked, outside)}
    original = check_resolution_save.resolve_saving_throw

    def fixed_save(*args, **kwargs):
        # Pass the Veilrender's turn-start field save, fail the delivered effect's save.
        return original(*args, **{**kwargs, "rng": Random(5 if args[2] == 14 else 31)})

    await declare_phase(ctx, [_strike(enemy, blocked, action)])
    with (
        patch("check_resolution_save.resolve_saving_throw", side_effect=fixed_save),
        patch("dice.roll", return_value=_damage_die(3)),
    ):
        result = await _resolve_round(ctx)
    packet = next(p for p in result["packets"] if "targets" in p and p["actor_id"] == enemy)
    assert {r["target_id"] for r in packet["targets"]} == {clear, "wall"}
    saved = await _reload(ctx)
    assert participant(saved, blocked).hp_current == before[blocked]
    assert participant(saved, outside).hp_current == before[outside]
    assert participant(saved, clear).hp_current < before[clear]


async def test_mass_heal_skips_only_the_walled_off_ally(healer) -> None:
    await healer.prepare(MASS)
    blocked, clear = await healer.add_player(), await healer.add_player()
    state = await healer.fight()
    for actor, point in [(healer.player, pos()), (blocked, pos(12)), (clear, pos(5))]:
        combat_spatial.place(state, actor, point)
    wall(state)
    await healer.save()
    await healer.command(
        "declare_phase",
        {
            "declarations": [
                {"kind": "ability", "actor_id": healer.player, "action": MASS, "targets": [], "argument_type": ""}
            ]
        },
    )
    with patch("dice.roll", return_value=_damage_die(8)):
        packet = next(p["cast"] for p in await healer.wrap() if p["actor_id"] == healer.player)
    assert {r["target_id"] for r in packet["healing_results"]} == {healer.player, clear}
    saved = await healer.checkpoint()
    assert participant(saved, blocked).hp_current == (await healer.read(blocked))["hp"]["current"] == 3
    assert participant(saved, clear).hp_current == (await healer.read(clear))["hp"]["current"] == 14
