"""Catalog recipient data must survive the runtime parsing boundaries."""

import json
from pathlib import Path

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
