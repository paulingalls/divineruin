"""Catalog recipient data must survive the runtime parsing boundaries."""

import json
from pathlib import Path

import pytest
from combat.test_area_spell_recipients import add_enemies, resolve_cast
from combat.test_spell_damage_lands import declare_spell, load_combat, prepare_spell, saved_player
from combat.test_spell_damage_lands import spell_fight as spell_fight
from creature_combat_helpers import catalog
from creature_combat_helpers import participant as enemy_participant
from livekit.agents.llm import ToolError
from voice_condition_fixtures import participant

import combat_resolve_phase
import db_mutations
from combat_action_availability import action_summary
from creature_combat import translate_creature
from spells import parse_spell_row

CONTENT = Path(__file__).resolve().parents[3] / "content/spells.json"


def test_catalog_recipient_profiles_survive_the_real_parser():
    expected = {
        "arcane_magic_missile": "projectiles",
        "arcane_elemental_burst": "radius",
        "arcane_fireball": "radius",
        "arcane_lightning_bolt": "line",
        "arcane_chain_lightning": "chain",
        "arcane_meteor_swarm": "radius",
        "divine_sacred_word": "caster_radius",
        "divine_flame_strike": "cylinder",
        "primal_ice_storm": "radius",
    }
    actual = {}
    for row in json.loads(CONTENT.read_text()):
        spell = parse_spell_row(row["id"], row)
        profile = spell.combat_damage or {}
        if "recipients" in profile:
            actual[spell.id] = profile["recipients"]["shape"]
            assert profile["recipients"] == row["combat_damage"]["recipients"]
    assert actual == expected


def test_wave_shape_survives_translation_and_is_surfaced():
    row = next(r for r in catalog() if r["id"] == "hollow_veilrender")
    actor = enemy_participant(translate_creature(row, encounter_id="guard", enemy_id="wave", role="standard"))
    wave = next(a for a in actor.action_pool if a["name"] == "Corruption Wave")
    assert wave["shape"] == "cone" and wave["reach"] == 30
    facts = next(a for a in action_summary(actor)["executable_actions"] if a["name"] == wave["name"])
    assert facts["shape"] == "cone" and facts["reach"] == wave["reach"]


async def test_chain_cannot_arc_from_a_primary_that_fell_before_execution(spell_fight, monkeypatch):
    ctx = spell_fight
    await prepare_spell(ctx, "arcane_chain_lightning")
    await add_enemies(ctx, {"foe": (0, 0, 0), "other": (10, 0, 0)})
    await declare_spell(ctx, "arcane_chain_lightning")
    original = combat_resolve_phase._prevalidate_ability_focus

    async def primary_falls(session, state, *args, **kwargs):
        result = await original(session, state, *args, **kwargs)
        primary = participant(state, "foe")
        primary.hp_current = 0
        primary.is_fallen = True
        return result

    monkeypatch.setattr(combat_resolve_phase, "_prevalidate_ability_focus", primary_falls)
    cast = await resolve_cast(ctx)
    assert cast["damage_results"] == []
    saved = await load_combat(ctx.userdata.combat_state.combat_id)
    assert participant(saved, "other").hp_current == 100


@pytest.mark.parametrize("fallen_before", ["declare", "resolve"])
async def test_fireball_refuses_fallen_anchor(spell_fight, fallen_before):
    ctx = spell_fight
    await prepare_spell(ctx, "arcane_fireball")
    await add_enemies(ctx, {"foe": (0, 0, 0), "other": (10, 0, 0)})
    if fallen_before == "resolve":
        await declare_spell(ctx, "arcane_fireball")
    state = ctx.userdata.combat_state
    anchor = participant(state, "foe")
    anchor.hp_current = 0
    anchor.is_fallen = True
    await db_mutations.save_combat_state(state.combat_id, state.to_dict())
    before = await saved_player(ctx.userdata.player_id)
    with pytest.raises(ToolError, match="requires live participant anchors"):
        if fallen_before == "declare":
            await declare_spell(ctx, "arcane_fireball")
        else:
            await resolve_cast(ctx)
    assert await saved_player(ctx.userdata.player_id) == before
    assert participant(await load_combat(state.combat_id), "other").hp_current == 100


def shielded_foe(ctx):
    row = next(r for r in catalog() if r["id"] == "hollow_choir")
    ctx.userdata.combat_state.participants[1] = enemy_participant(
        translate_creature(row, encounter_id="shield", enemy_id="foe", role="standard")
    )


async def test_redirected_darts_merge_with_darts_already_aimed_at_caster(spell_fight):
    ctx = spell_fight
    pid = ctx.userdata.player_id
    spell = await prepare_spell(ctx, "arcane_magic_missile")
    shielded_foe(ctx)
    await add_enemies(ctx, {"foe": (0, 0, 0)})
    await declare_spell(ctx, spell.id, targets=["foe", pid, "foe", pid])
    cast = await resolve_cast(ctx)
    (result,) = cast["damage_results"]
    assert result["target_id"] == pid and result["damage"] == 28
    assert sorted(result["dart_indices"]) == [0, 1, 2, 3]


async def test_produce_flame_without_target_conjures_without_damage(spell_fight):
    ctx = spell_fight
    pid = ctx.userdata.player_id
    spell = await prepare_spell(ctx, "primal_produce_flame")
    before = await saved_player(pid)
    await declare_spell(ctx, spell.id, targets=[])
    cast = await resolve_cast(ctx)
    assert "damage_result" not in cast and "damage_results" not in cast
    assert (await saved_player(pid))["focus"]["current"] == before["focus"]["current"] - spell.focus_cost
