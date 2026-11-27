"""Faerie Fire and Slow through registered phase tools and saved combat."""

import json

import pytest
from acceptance._spell_hostile_condition_helpers import (
    add_player,
    attack,
    cast_spell,
    defend,
    instance,
    play,
    receipt,
    reload,
    set_foe,
)
from acceptance._spell_hostile_condition_helpers import dev_db_pool as dev_db_pool
from combat.test_spell_damage_lands import prepare_spell, saved_player
from combat.test_spell_damage_lands import spell_fight as spell_fight
from livekit.agents import ToolError
from voice_condition_fixtures import participant, spatial_record
from weapon_fixtures import DAGGER, SHORTBOW

import combat_turn
import db
import db_mutations
from combat_structures import add_wall
from conditions import apply_condition
from declaration_payloads import AbilityDecl, AttackDecl, Destination, MoveDecl

FIRE = "primal_faerie_fire"
SLOW = "arcane_slow"
SLING = {**SHORTBOW, "name": "Sling", "weapon_kind": "sling", "damage_type": "bludgeoning"}
CROSSBOW = {**SHORTBOW, "name": "Light Crossbow", "weapon_kind": "light_crossbow"}


def slow(actor, *targets):
    return AbilityDecl(kind="ability", actor_id=actor, action=SLOW, targets=list(targets), argument_type="")


async def test_faerie_fire_cube_saves(spell_fight):
    ctx = spell_fight
    caster = ctx.userdata.player_id
    await prepare_spell(ctx, FIRE)
    for foe in ("corner", "saved", "outside", "outside_x", "outside_y"):
        await set_foe(ctx, foe_id=foe)
    positions = spatial_record(ctx.userdata.combat_state)["positions"]
    positions.update(
        foe={"x": 40, "y": 0, "z": 0},
        corner={"x": 50, "y": 10, "z": 10},
        saved={"x": 40, "y": 10, "z": 0},
        outside={"x": 40, "y": 0, "z": 11},
        outside_x={"x": 51, "y": 0, "z": 0},
        outside_y={"x": 40, "y": 11, "z": 0},
    )
    before = await saved_player(caster)
    packets, state = await play(ctx, cast_spell(caster, FIRE), faces=[1, 1, 20, 1, 1, 1])
    cast = receipt(packets, caster)
    assert [(r["target_id"], r["save"]["attribute"], r["save"]["success"]) for r in cast["condition_results"]] == [
        ("foe", "dexterity", False),
        ("corner", "dexterity", False),
        ("saved", "dexterity", True),
    ]
    assert cast["condition_targets"] == ["foe", "corner"]
    for foe in ("foe", "corner"):
        (held,) = participant(state, foe).conditions
        assert (held["type"], held["source"], held["originating_participant_id"]) == ("outlined", FIRE, caster)
    for foe in ("saved", "outside"):
        assert participant(state, foe).conditions == []
    assert all(participant(state, foe).hp_current == 100 for foe in ("foe", "corner", "saved", "outside"))
    after = await saved_player(caster)
    assert after["focus"]["current"] == before["focus"]["current"] - 2
    assert after["concentration"]["spell_id"] == FIRE
    _, state = await play(ctx, defend(caster), face=20)
    assert all(participant(state, foe).conditions for foe in ("foe", "corner"))
    await equip(ctx, caster, SLING)
    for foe in ("foe", "corner", "saved", "outside"):
        outlined = foe in ("foe", "corner")
        packets, state = await play(ctx, attack(caster, SLING["name"], foe), faces=[3, 19] if outlined else [3])
        swing = next(p for p in packets if p["actor_id"] == caster)
        assert swing["hit"] is outlined and swing["roll"] == (19 if outlined else 3)
        assert participant(state, foe).hp_current == 100 - swing["damage"]


@pytest.mark.parametrize(
    ("targets", "refusal"),
    [
        (("foe", "second", "third", "fourth"), "at most 3"),
        (("fallen",), "standing creatures"),
        (("dead",), "standing creatures"),
        (("wall",), "standing creatures"),
    ],
)
async def test_slow_refuses_invalid_recipients_before_spending(spell_fight, targets, refusal):
    ctx = spell_fight
    caster = ctx.userdata.player_id
    for foe in ("second", "third", "fourth", "fallen", "dead"):
        await set_foe(ctx, foe_id=foe)
    state = ctx.userdata.combat_state
    participant(state, "fallen").is_fallen = True
    participant(state, "dead").is_dead = True
    add_wall(state, "wall", "Wall", {"x": 40, "y": -5, "z": 0}, {"x": 40, "y": 5, "z": 0})
    await db_mutations.save_combat_state(state.combat_id, state.to_dict())
    before = (await reload(ctx)).to_dict()
    row = await saved_player(caster)
    with pytest.raises(ToolError, match=refusal):
        await combat_turn.declare_phase(ctx, [slow(caster, *targets)])
    assert (await reload(ctx)).to_dict() == before
    assert await saved_player(caster) == row


async def equip(ctx, actor, weapon):
    participant(ctx.userdata.combat_state, actor).action_pool = [weapon]
    pool = await db.get_pool()
    await pool.execute(
        "UPDATE players SET data=jsonb_set(data,'{equipment}',$2::jsonb) WHERE player_id=$1",
        actor,
        json.dumps({"main_hand": weapon}),
    )


def move(actor, x):
    return MoveDecl(
        kind="move",
        actor_id=actor,
        destination=Destination(x=x, y=0, z=0),
        movement_mode="ground",
        nythera_step=False,
        reshape=[],
    )


async def test_slow_penalties_and_independent_wisdom_resave(spell_fight):
    ctx = spell_fight
    caster = ctx.userdata.player_id
    for foe in ("foe", "second", "saved"):
        target = await set_foe(ctx, foe_id=foe)
        target.attributes.update(wisdom=10, dexterity=6 if foe == "foe" else 18)
        target.ac = 14
    positions = spatial_record(ctx.userdata.combat_state)["positions"]
    positions["second"]["x"] = 50
    positions["saved"]["x"] = 55
    before = await saved_player(caster)
    packets, state = await play(ctx, slow(caster, "foe", "second", "saved"), faces=[1, 1, 20, 1, 1])
    cast = receipt(packets, caster)
    assert [(r["target_id"], r["save"]["attribute"], r["save"]["success"]) for r in cast["condition_results"]] == [
        ("foe", "wisdom", False),
        ("second", "wisdom", False),
        ("saved", "wisdom", True),
    ]
    assert (
        participant(state, "foe").conditions
        == participant(state, "second").conditions
        == [instance("slowed", SLOW, caster, "wis")]
    )
    assert not participant(state, "saved").conditions
    assert (await saved_player(caster))["focus"]["current"] == before["focus"]["current"] - 5

    with pytest.raises(ToolError, match="15 feet"):
        await combat_turn.declare_phase(ctx, [move("foe", 16)])
    packets, state = await play(ctx, move("foe", 15), defend(caster))
    assert next(p for p in packets if p["actor_id"] == "foe")["movement_spent_ft"] == 15
    assert spatial_record(state)["positions"]["foe"]["x"] == 15

    await equip(ctx, caster, CROSSBOW)
    participant(ctx.userdata.combat_state, caster).attributes["dexterity"] = 10
    packets, state = await play(ctx, attack(caster, CROSSBOW["name"], "foe"), faces=[10, 10, 6])
    swing = next(p for p in packets if p["actor_id"] == caster)
    assert (swing["hit"], swing["attack_total"], swing["target_ac"]) == (True, 12, 12)
    assert participant(state, "foe").hp_current == 100 - swing["damage"]
    assert not participant(state, "foe").conditions
    assert participant(state, "second").conditions == [instance("slowed", SLOW, caster, "wis")]
    assert (await saved_player(caster))["concentration"]["spell_id"] == SLOW
    packets, _ = await play(ctx, attack(caster, CROSSBOW["name"], "foe"), faces=[10, 1])
    swing = next(p for p in packets if p["actor_id"] == caster)
    assert (swing["hit"], swing["attack_total"], swing["target_ac"]) == (False, 12, 14)
    packets, state = await play(ctx, move("foe", 35))
    assert next(p for p in packets if p["actor_id"] == "foe")["movement_spent_ft"] == 20
    assert spatial_record(state)["positions"]["foe"]["x"] == 35


@pytest.mark.parametrize(
    ("rider", "enhancer"),
    [
        ("dash", ""),
        ("hide", ""),
        ("disengage", ""),
        ("shield_bash", ""),
        ("quick_fingers", ""),
        ("", "extra_attack"),
        ("", "hit_and_run"),
        ("", "shield_bash"),
    ],
)
async def test_slow_refuses_paired_attacks(spell_fight, rider, enhancer):
    ctx = spell_fight
    caster = ctx.userdata.player_id
    archetype = "warrior" if rider == "shield_bash" or enhancer else "rogue"
    actor = await add_player(ctx, archetype)
    await set_foe(ctx)
    await equip(ctx, actor, DAGGER)
    participant(ctx.userdata.combat_state, actor).enhancers = [enhancer] if enhancer else []
    if rider == "quick_fingers":
        pool = await db.get_pool()
        await pool.execute(
            "INSERT INTO character_abilities (player_id, ability_id, equipped) VALUES ($1, 'rogue_quick_fingers', TRUE)",
            actor,
        )
    await play(ctx, slow(caster, actor))
    initial = (await reload(ctx)).to_dict()
    row = await saved_player(actor)
    pair = attack(actor, DAGGER["name"], "foe", rider).model_dump()
    if rider == "quick_fingers":
        pair["quick_fingers_mode"] = "steal"
    with pytest.raises(ToolError, match="Slow"):
        await combat_turn.declare_phase(ctx, [AttackDecl(**pair)])
    assert (await reload(ctx)).to_dict() == initial
    assert await saved_player(actor) == row
    packets, state = await play(
        ctx, attack(actor, DAGGER["name"], "foe", "plain" if enhancer else ""), faces=[17, 1, 1]
    )
    swing = next(p for p in packets if p["actor_id"] == actor)
    assert swing["hit"] and participant(state, "foe").hp_current == 100 - swing["damage"]
    assert "riders" not in swing and "cunning_action" not in swing
    assert (await saved_player(actor))["stamina"] == row["stamina"]
    if rider in {"dash", "hide", "disengage"}:
        await play(ctx, defend(actor), face=20)
        packets, _ = await play(ctx, AttackDecl(**pair), face=17)
        swing = next(p for p in packets if p["actor_id"] == actor)
        assert swing["hit"] and "cunning_action" in swing
        assert (await saved_player(actor))["stamina"]["current"] == row["stamina"]["current"] - 2


@pytest.mark.parametrize(
    ("spell", "condition", "archetype"),
    [
        (FIRE, "outlined", "druid"),
        (SLOW, "slowed", "mage"),
    ],
)
async def test_concentration_break_removes_all_own_conditions(spell_fight, spell, condition, archetype):
    ctx = spell_fight
    caster = ctx.userdata.player_id
    await prepare_spell(ctx, spell)
    other = await add_player(ctx, archetype, (spell,))
    for foe in ("foe", "second", "third"):
        await set_foe(ctx, foe_id=foe)
    assailant = await set_foe(ctx, "cult_leader", foe_id="assailant")
    state = ctx.userdata.combat_state
    positions = spatial_record(state)["positions"]
    participant(state, "foe").conditions = apply_condition([], "wounded")
    positions["foe"]["x"] = 30
    positions["second"]["x"] = 35
    positions["third"]["x"] = 60
    own = slow(caster, "foe", "second") if spell == SLOW else cast_spell(caster, FIRE)
    _, state = await play(ctx, own, cast_spell(other, spell, "third"))
    for foe, owner in (("foe", caster), ("second", caster), ("third", other)):
        held = next(c for c in participant(state, foe).conditions if c["type"] == condition)
        assert (held["type"], held["originating_participant_id"]) == (condition, owner)
    blow = attack(assailant.id, assailant.action_pool[0]["name"], caster)
    packets, state = await play(ctx, defend(caster), defend(other), blow, faces=[19, 1, 1])
    assert next(p for p in packets if p["actor_id"] == assailant.id)["concentration_broken"] == spell
    assert [c["type"] for c in participant(state, "foe").conditions] == ["wounded"]
    assert not participant(state, "second").conditions
    assert participant(state, "third").conditions[0]["originating_participant_id"] == other
    assert (await saved_player(caster))["concentration"]["spell_id"] is None
    assert (await saved_player(other))["concentration"]["spell_id"] == spell
