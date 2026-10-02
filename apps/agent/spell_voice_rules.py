"""Authored spell classification and position-scoped speech rules."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from session_data import CombatState

import combat_spatial

AREA_SPELLS = frozenset(
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

NON_AREA_SPELLS = frozenset(
    {
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
        "arcane_prestidigitation",
        "arcane_mage_light",
        "arcane_shield_spell",
        "arcane_detect_magic",
        "arcane_mage_hand",
        "arcane_mist_step",
        "arcane_arcane_lock",
        "arcane_fly",
        "arcane_invisibility",
        "arcane_haste",
        "arcane_arcane_eye",
        "arcane_teleport",
        "arcane_time_stop",
        "divine_mend",
        "divine_heal_wounds",
        "divine_shield_of_faith",
        "divine_bless",
        "divine_sanctuary",
        "divine_detect_hollow",
        "divine_prayer_of_healing",
        "divine_beacon_of_hope",
        "divine_divine_ward",
        "divine_revivify",
        "divine_commune",
        "divine_greater_restoration",
        "divine_resurrection",
        "primal_druidcraft",
        "primal_shillelagh",
        "primal_healing_touch",
        "primal_bark_skin",
        "primal_speak_with_animals",
        "primal_goodberry",
        "primal_protection_from_hollow",
        "primal_water_breathing",
        "primal_wild_shape",
        "primal_commune_with_nature",
        "primal_regenerate",
        "primal_animal_shapes",
    }
)


def is_area_spell(spell_id: str) -> bool:
    if spell_id in AREA_SPELLS:
        return True
    if spell_id in NON_AREA_SPELLS:
        return False
    raise ValueError(f"Unclassified spell {spell_id!r}")


def is_silenced(state: CombatState | None, actor_id: str) -> bool:
    if state is None:
        return False
    spatial = combat_spatial.require_spatial(state)
    origin = combat_spatial.position(spatial, actor_id)
    return any(
        zone.get("kind") == "silence"
        and combat_spatial.inside(origin, combat_spatial.position(spatial, zone["center_id"]), zone["radius_ft"])
        for zone in spatial["zones"].values()
    )


def require_speech(state: CombatState | None, actor_id: str) -> None:
    if is_silenced(state, actor_id):
        raise ValueError(f"{actor_id} is silenced and cannot speak")
