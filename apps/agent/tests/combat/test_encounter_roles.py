"""Unit coverage for the pure encounter-role module (M4.7, story-001).

The module is pure: every test constructs a plain base-enemy dict and asserts on the
returned derived dict — no DB, no RNG, no combat state. Worked-example numbers come from
docs/game_mechanics/game_mechanics_encounter_roles.md (Bandit / Grey Wolf / Mawling).
"""

import pytest

from encounter_roles import (
    ROLE_MODIFIERS,
    EncounterRole,
    derive_role_stats,
    enhance_abilities,
)

# --- base fixtures (doc worked examples) -------------------------------------------------

# Bandit (Humanoid, Tier 1): HP 16, AC 13, XP 50, one weapon attack + one active ability.
BANDIT = {
    "id": "bandit_1",
    "name": "Bandit",
    "level": 2,
    "ac": 13,
    "hp": 16,
    "attributes": {"strength": 13, "dexterity": 13, "constitution": 12},
    "action_pool": [
        {"name": "Short Sword", "damage": "1d6+2", "damage_type": "slashing", "properties": []},
        {"name": "Dirty Fighting", "damage": "0", "damage_type": "none", "properties": ["debuff"]},
    ],
    "xp_value": 50,
    "signature_ability": {"name": "Rally", "description": "+2 to allies' attacks and saves."},
}

# Grey Wolf (Beast, Tier 1): HP 11, AC 12, XP 25 — odd HP exercises the rounding rule.
GREY_WOLF = {
    "id": "wolf_1",
    "name": "Grey Wolf",
    "level": 1,
    "ac": 12,
    "hp": 11,
    "attributes": {"strength": 12, "dexterity": 15, "constitution": 12},
    "action_pool": [
        {"name": "Bite", "damage": "1d6+2", "damage_type": "piercing", "properties": []},
    ],
    "xp_value": 25,
}


def _names(action_pool: list[dict]) -> set[str]:
    return {a["name"] for a in action_pool}


# --- ROLE_MODIFIERS table ----------------------------------------------------------------


def test_all_five_roles_present_in_enum_and_table():
    assert {r.value for r in EncounterRole} == {"minion", "standard", "elite", "boss", "named"}
    # Modifier table covers the four derivable roles (standard/named short-circuit to identity).
    for role in ("minion", "standard", "elite", "boss"):
        assert role in ROLE_MODIFIERS


@pytest.mark.parametrize(
    "role,hp,ac,xp",
    [
        ("minion", 8, 12, 25),
        ("standard", 16, 13, 50),
        ("elite", 24, 14, 75),
        ("boss", 32, 15, 100),
    ],
)
def test_bandit_worked_example_hp_ac_xp(role, hp, ac, xp):
    derived = derive_role_stats(BANDIT, role)
    assert derived["hp"] == hp
    assert derived["ac"] == ac
    assert derived["xp_value"] == xp


@pytest.mark.parametrize(
    "role,hp,xp",
    [("minion", 5, 12), ("elite", 17, 37), ("boss", 22, 50)],
)
def test_grey_wolf_rounding(role, hp, xp):
    # Minion floors (5.5->5), Elite rounds up (16.5->17), XP truncates (12.5->12, 37.5->37).
    derived = derive_role_stats(GREY_WOLF, role)
    assert derived["hp"] == hp
    assert derived["xp_value"] == xp


def test_minion_hp_floors_at_one():
    tiny = {**GREY_WOLF, "hp": 1}
    assert derive_role_stats(tiny, "minion")["hp"] == 1


# --- resolver modifier carry -------------------------------------------------------------


@pytest.mark.parametrize(
    "role,attack_mod,dc_mod,damage_mult",
    [
        ("minion", 0, -1, 0.75),
        ("standard", 0, 0, 1.0),
        ("elite", 1, 1, 1.25),
        ("boss", 2, 2, 1.5),
    ],
)
def test_resolver_modifiers_carried(role, attack_mod, dc_mod, damage_mult):
    derived = derive_role_stats(BANDIT, role)
    assert derived["attack_mod"] == attack_mod
    assert derived["dc_mod"] == dc_mod
    assert derived["damage_mult"] == damage_mult
    assert derived["role"] == role


# --- abilities ---------------------------------------------------------------------------


def test_minion_strips_active_abilities_keeps_basic_attacks():
    derived = derive_role_stats(BANDIT, "minion")
    assert _names(derived["action_pool"]) == {"Short Sword"}  # Dirty Fighting (debuff) stripped


def test_elite_enhances_actives_and_keeps_attacks():
    derived = derive_role_stats(BANDIT, "elite")
    assert _names(derived["action_pool"]) == {"Short Sword", "Dirty Fighting"}
    enhanced = next(a for a in derived["action_pool"] if a["name"] == "Dirty Fighting")
    assert enhanced.get("enhanced") is True
    attack = next(a for a in derived["action_pool"] if a["name"] == "Short Sword")
    assert "enhanced" not in attack  # basic attacks are not tagged


def test_enhance_abilities_tags_each_active():
    actives = [{"name": "X", "damage": "0", "properties": ["buff"]}]
    out = enhance_abilities(actives)
    assert out[0]["enhanced"] is True


# --- boss extras -------------------------------------------------------------------------


def test_boss_carries_authored_signature_and_one_legendary():
    derived = derive_role_stats(BANDIT, "boss")
    assert derived["legendary_actions"] == 1
    assert derived["signature_ability"]["name"] == "Rally"


def test_non_boss_has_no_legendary_and_no_signature():
    for role in ("minion", "standard", "elite"):
        derived = derive_role_stats(BANDIT, role)
        assert derived["legendary_actions"] == 0
        assert derived["signature_ability"] is None


# --- identity + immutability -------------------------------------------------------------


@pytest.mark.parametrize("role", ["standard", "named"])
def test_standard_and_named_are_stat_identity(role):
    derived = derive_role_stats(BANDIT, role)
    assert derived["hp"] == BANDIT["hp"]
    assert derived["ac"] == BANDIT["ac"]
    assert derived["xp_value"] == BANDIT["xp_value"]
    assert _names(derived["action_pool"]) == _names(BANDIT["action_pool"])


def test_derive_does_not_mutate_the_input():
    before_hp = BANDIT["hp"]
    before_actions = len(BANDIT["action_pool"])
    derive_role_stats(BANDIT, "minion")
    assert BANDIT["hp"] == before_hp
    assert len(BANDIT["action_pool"]) == before_actions
    assert "role" not in BANDIT
