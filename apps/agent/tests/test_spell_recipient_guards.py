"""Catalog recipient data must survive the runtime parsing boundaries."""

import json
from pathlib import Path

from combat.test_spell_damage_lands import spell_fight as spell_fight

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
    from creature_combat_helpers import catalog, participant

    from combat_action_availability import action_summary
    from creature_combat import translate_creature

    row = next(r for r in catalog() if r["id"] == "hollow_veilrender")
    actor = participant(translate_creature(row, encounter_id="guard", enemy_id="wave", role="standard"))
    wave = next(a for a in actor.action_pool if a["name"] == "Corruption Wave")
    assert wave["shape"] == "cone" and wave["reach"] == 30
    facts = next(a for a in action_summary(actor)["executable_actions"] if a["name"] == wave["name"])
    assert facts["shape"] == "cone" and facts["reach"] == wave["reach"]


async def test_chain_cannot_arc_from_a_primary_that_fell_before_execution(spell_fight, monkeypatch):
    from combat.test_area_spell_recipients import add_enemies, resolve_cast
    from combat.test_spell_damage_lands import declare_spell, load_combat, prepare_spell
    from voice_condition_fixtures import participant

    import combat_resolve_phase

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
