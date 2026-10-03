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


def silence_state():
    from tests.combat.test_combat_spatial import spatial_state

    state = spatial_state()
    assert state.spatial is not None
    state.spatial["zones"] = {"quiet": {"kind": "silence", "center_id": "core", "radius_ft": 10}}
    return state


def test_typed_silence_survives_real_spatial_boundaries():
    from combat_spatial import facts, validate_scene
    from session_data import CombatState

    state = silence_state()
    assert state.spatial is not None
    scene = {
        "enemies": [{"id": "b", "creature_id": "goblin_scout", "role": "standard"}],
        "scene_placement": {
            "party_start": {"x": 0, "y": 0, "z": 0},
            "companion_start": {"x": 0, "y": 0, "z": 0},
            "actors": {"b": state.spatial["positions"]["b"]},
            "locations": state.spatial["locations"],
            "zones": state.spatial["zones"],
        },
    }
    assert validate_scene(scene)["zones"]["quiet"]["kind"] == "silence"
    restored = CombatState.from_dict(json.loads(json.dumps(state.to_dict())))
    assert restored.spatial == state.spatial
    assert facts(restored, "a")["zones"]["quiet"]["kind"] == "silence"


@pytest.mark.parametrize("kind", [None, True, 1, "generic", "Silence", "fire"])
def test_malformed_silence_zone_kind_refuses_at_real_boundaries(kind):
    from combat_spatial import validate_spatial
    from session_data import CombatState

    state = silence_state()
    assert state.spatial is not None
    state.spatial["zones"]["quiet"]["kind"] = kind
    with pytest.raises(ValueError, match="zone"):
        validate_spatial(state.spatial, ["a", "b"])
    with pytest.raises(ValueError, match="zone"):
        CombatState.from_dict(state.to_dict())


def test_silence_uses_position_and_explicit_kind():
    from spell_voice_rules import is_silenced
    from tests.combat.test_combat_spatial import spatial_state

    generic = spatial_state()
    assert not is_silenced(generic, "a")
    assert not is_silenced(None, "a")
    state = silence_state()
    assert state.spatial is not None
    assert not is_silenced(state, "a")
    assert is_silenced(state, "b")
    state.spatial["positions"]["b"]["x"] = 40.00001
    assert not is_silenced(state, "b")
    state.spatial["positions"]["a"]["x"] = 30
    assert is_silenced(state, "a")
    state.spatial["zones"]["second"] = {"kind": "silence", "center_id": "b", "radius_ft": 0}
    assert is_silenced(state, "b")
    with pytest.raises(ValueError, match="Unknown position"):
        is_silenced(state, "missing")
    state.spatial = None
    with pytest.raises(ValueError, match="placement"):
        is_silenced(state, "a")


def test_silence_refusal_is_typed_and_narratable():
    from spell_voice_rules import require_speech

    state = silence_state()
    assert state.spatial is not None
    require_speech(state, "a")
    with pytest.raises(ValueError, match="b is silenced and cannot speak"):
        require_speech(state, "b")
