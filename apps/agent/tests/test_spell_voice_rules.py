"""Strict spell contracts and complete authored area/hostility audit."""

import json
from pathlib import Path

import pytest

from spell_voice_rules import AREA_SPELLS, NON_AREA_SPELLS, is_area_spell
from spells import parse_spell_row

CONTENT = Path(__file__).resolve().parents[3] / "content" / "spells.json"

EXPECTED_HOSTILE = frozenset(
    {
        "arcane_elemental_burst",
        "arcane_fireball",
        "arcane_lightning_bolt",
        "arcane_wall_of_force",
        "arcane_chain_lightning",
        "arcane_meteor_swarm",
        "divine_sacred_word",
        "divine_turn_undead_hollow",
        "divine_zone_of_truth",
        "divine_flame_strike",
        "divine_holy_aura",
        "divine_miracle",
        "primal_entangle",
        "primal_faerie_fire",
        "primal_call_lightning",
        "primal_plant_growth",
        "primal_wall_of_thorns",
        "primal_guardian_of_nature",
        "primal_ice_storm",
        "primal_earthquake",
        "primal_tsunami",
        "primal_storm_of_vengeance",
        "arcane_frost_touch",
        "arcane_bolt",
        "arcane_spark",
        "arcane_magic_missile",
        "arcane_hold_person",
        "arcane_counterspell",
        "arcane_dispel_magic",
        "arcane_slow",
        "arcane_disintegrate",
        "arcane_power_word_stun",
        "arcane_maze",
        "divine_sacred_flame",
        "divine_guiding_light",
        "divine_command",
        "divine_spiritual_weapon",
        "divine_banishment",
        "divine_divine_judgment",
        "primal_thorn_whip",
        "primal_produce_flame",
        "primal_gust",
        "primal_conjure_animals",
        "primal_natures_grasp",
        "primal_blight",
        "primal_feeblemind",
    }
)

EXPECTED_AREA = frozenset(
    {
        "arcane_elemental_burst",
        "arcane_fireball",
        "arcane_lightning_bolt",
        "arcane_wall_of_force",
        "arcane_chain_lightning",
        "arcane_meteor_swarm",
        "divine_sacred_word",
        "divine_turn_undead_hollow",
        "divine_zone_of_truth",
        "divine_flame_strike",
        "divine_holy_aura",
        "divine_miracle",
        "primal_entangle",
        "primal_faerie_fire",
        "primal_call_lightning",
        "primal_plant_growth",
        "primal_wall_of_thorns",
        "primal_guardian_of_nature",
        "primal_ice_storm",
        "primal_earthquake",
        "primal_tsunami",
        "primal_storm_of_vengeance",
        "divine_dispel_corruption",
        "divine_mass_heal",
        "divine_veil_ward",
    }
)


def test_complete_spell_audit_through_production_loader():
    rows = json.loads(CONTENT.read_text())
    assert len(rows) == 87
    parsed = [parse_spell_row(row["id"], row) for row in rows]
    ids = {spell.id for spell in parsed}
    assert len(ids) == 87
    assert AREA_SPELLS.isdisjoint(NON_AREA_SPELLS)
    assert ids == AREA_SPELLS | NON_AREA_SPELLS
    assert {spell.id for spell in parsed if spell.hostile} == EXPECTED_HOSTILE
    assert {spell.id for spell in parsed if is_area_spell(spell.id)} == EXPECTED_AREA
    assert all(spell.verbal is True for spell in parsed)


def test_unknown_area_classification_refuses():
    with pytest.raises(ValueError, match="Unclassified spell"):
        is_area_spell("unreviewed_spell")
