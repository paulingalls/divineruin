"""The complete catalog inventory and strict damage-profile input boundary."""

import json
from copy import deepcopy
from pathlib import Path

import pytest
from combat.test_spell_damage_lands import DAMAGE_CASES

from spells import parse_spell_row

CONTENT = Path(__file__).resolve().parents[3] / "content/spells.json"
DEFERRED = {"divine_spiritual_weapon", "primal_wall_of_thorns", "primal_earthquake", "primal_storm_of_vengeance"}
INDIRECT = {
    "primal_shillelagh",
    "primal_guardian_of_nature",
    "primal_conjure_animals",
    "primal_wild_shape",
    "primal_animal_shapes",
    "divine_turn_undead_hollow",
    "divine_banishment",
    "divine_miracle",
}
UTILITY = {
    "arcane_teleport",
    "arcane_hold_person",
    "arcane_detect_magic",
    "arcane_prestidigitation",
    "arcane_wall_of_force",
    "arcane_counterspell",
    "primal_gust",
    "arcane_time_stop",
    "divine_shield_of_faith",
    "arcane_power_word_stun",
    "primal_feeblemind",
    "primal_faerie_fire",
    "arcane_arcane_eye",
    "primal_druidcraft",
    "arcane_haste",
    "primal_goodberry",
    "primal_water_breathing",
    "primal_speak_with_animals",
    "arcane_invisibility",
    "arcane_mage_light",
    "primal_regenerate",
    "arcane_fly",
    "arcane_mage_hand",
    "divine_command",
    "primal_bark_skin",
    "primal_commune_with_nature",
    "primal_protection_from_hollow",
    "arcane_mist_step",
    "arcane_slow",
    "divine_resurrection",
    "divine_holy_aura",
    "arcane_shield_spell",
    "arcane_maze",
    "divine_mass_heal",
    "divine_revivify",
    "divine_commune",
    "divine_greater_restoration",
    "arcane_arcane_lock",
    "divine_mend",
    "divine_veil_ward",
    "primal_healing_touch",
    "divine_sanctuary",
    "divine_dispel_corruption",
    "divine_heal_wounds",
    "divine_guiding_light",
    "divine_bless",
    "primal_plant_growth",
    "divine_zone_of_truth",
    "arcane_dispel_magic",
    "divine_beacon_of_hope",
    "divine_prayer_of_healing",
    "divine_detect_hollow",
    "primal_entangle",
    "primal_natures_grasp",
    "divine_divine_ward",
}


def test_all_catalog_rows_are_accounted_for_and_damage_profiles_exist():
    rows = json.loads(CONTENT.read_text())
    assert len(rows) == len({r["id"] for r in rows}) == 87
    direct = {row[0] for row in DAMAGE_CASES} | {"arcane_bolt"}
    assert len(direct) == 20 and len(DEFERRED) == 4 and len(INDIRECT) == 8
    assert {r["id"] for r in rows} == direct | DEFERRED | INDIRECT | UTILITY
    for row in rows:
        spell = parse_spell_row(row["id"], row)
        if row["id"] in direct:
            assert spell.combat_damage and spell.combat_damage["resolution"] in {"attack", "save", "automatic"}
        elif row["id"] in DEFERRED:
            assert spell.combat_damage is not None
            assert spell.combat_damage["resolution"] == "deferred" and spell.combat_damage["deferred"]
        else:
            assert spell.combat_damage is None


@pytest.mark.parametrize(
    "change",
    [
        {"resolution": "typo"},
        {"unknown": True},
        {"components": []},
        {"components": [{"dice": "-1d6", "damage_type": "force"}]},
        {"components": [{"dice": "1d6", "damage_type": "typo"}]},
        {"attribute": "typo"},
        {"ranged": 1},
        {"damage_attribute": 1},
        {"scaling": [[5, 2], [4, 3]]},
        {"scaling": []},
        {"projectiles": 0},
        {"restriction": "typo"},
        {"deferred": ""},
        {"recipients": {"shape": "radius", "radius_ft": 0, "placements": 1}},
        {"recipients": {"shape": "line", "length_ft": 100}},
        {"recipients": {"shape": "cone"}},
        {"components": [{"dice": "1d6", "damage_type": "choice"}]},
        {"resolution": "save", "save": "wisdom", "half": "yes"},
        {"resolution": "deferred", "deferred": " "},
    ],
)
def test_malformed_profile_fails_at_real_spell_parser(change):
    row = deepcopy(next(r for r in json.loads(CONTENT.read_text()) if r["id"] == "arcane_bolt"))
    if change.get("resolution") == "deferred":
        row["combat_damage"] = change
    else:
        row["combat_damage"].update(change)
    with pytest.raises(ValueError, match="combat_damage"):
        parse_spell_row(row["id"], row)
