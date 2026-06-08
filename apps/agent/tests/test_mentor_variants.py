"""Unit tests for the mentor_variants loader (M9 / story-001).

Drives the production fail-loud parse_mentor_variant_row over inline fixtures and
pins the accessors. The content-catalog conformance (exact count, every row
parses, ability_id/mentor_id cross-refs) lives in test_mentor_variants_content.py
alongside the catalog itself. Mirrors test_spells.py.
"""

import pytest

from mentor_variants import (
    MentorVariant,
    get_mentor_variant,
    get_variant,
    get_variants_for_ability,
    parse_mentor_variant_row,
    set_mentor_variants,
)

_ROW = {
    "ability_id": "warrior_cleaving_blow",
    "mentor_id": "guildmaster_torin",
    "cost": {"stamina": 3, "focus": 0, "scaling": None},
    "effect": "Hits up to 2 adjacent enemies; +1 damage each.",
    "narration_cue": "A wide Drathian arc — brutal and fast.",
    "cultural_attribution": "Drathian Clans technique",
}


def _variant(variant_id: str, ability_id: str = "warrior_cleaving_blow") -> MentorVariant:
    return parse_mentor_variant_row(variant_id, {**_ROW, "ability_id": ability_id})


def test_parse_valid_row_round_trips_fields():
    variant = parse_mentor_variant_row("warrior_cleaving_blow_drathian", _ROW)
    assert variant.id == "warrior_cleaving_blow_drathian"
    assert variant.ability_id == "warrior_cleaving_blow"
    assert variant.mentor_id == "guildmaster_torin"
    assert variant.cost.stamina == 3
    assert variant.cost.focus == 0
    assert variant.cost.scaling is None
    assert variant.cultural_attribution == "Drathian Clans technique"


def test_parse_rejects_missing_cultural_attribution():
    row = {k: v for k, v in _ROW.items() if k != "cultural_attribution"}
    with pytest.raises(ValueError, match="x"):
        parse_mentor_variant_row("x", row)


def test_parse_rejects_missing_ability_id():
    row = {k: v for k, v in _ROW.items() if k != "ability_id"}
    with pytest.raises(ValueError, match="x"):
        parse_mentor_variant_row("x", row)


def test_parse_rejects_non_object_cost():
    with pytest.raises(ValueError, match=r"x\.cost"):
        parse_mentor_variant_row("x", {**_ROW, "cost": "free"})


def test_parse_rejects_non_int_cost_stamina():
    # bool/float excluded for parity with the TS integer guard.
    with pytest.raises(ValueError, match=r"x\.cost\.stamina"):
        parse_mentor_variant_row("x", {**_ROW, "cost": {"stamina": 2.5, "focus": 0, "scaling": None}})


def test_parse_rejects_non_string_ability_id():
    # parity with the TS typeof === "string" guard — a non-string field fails loud.
    with pytest.raises(ValueError, match=r"x\.ability_id is not a string"):
        parse_mentor_variant_row("x", {**_ROW, "ability_id": 123})


def test_get_mentor_variant_round_trips_and_fails_loud():
    set_mentor_variants({"warrior_cleaving_blow_drathian": _variant("warrior_cleaving_blow_drathian")})
    assert get_mentor_variant("warrior_cleaving_blow_drathian").mentor_id == "guildmaster_torin"
    with pytest.raises(ValueError, match="no_such_variant"):
        get_mentor_variant("no_such_variant")


def test_get_variant_resolves_pair_and_fails_loud_on_mismatch():
    set_mentor_variants({"warrior_cleaving_blow_drathian": _variant("warrior_cleaving_blow_drathian")})
    found = get_variant("warrior_cleaving_blow", "warrior_cleaving_blow_drathian")
    assert found.cultural_attribution == "Drathian Clans technique"
    # variant id exists but belongs to a different ability -> fail loud
    with pytest.raises(ValueError, match="warrior_cleaving_blow_drathian"):
        get_variant("guardian_taunt", "warrior_cleaving_blow_drathian")


def test_get_variants_for_ability_groups_and_empties():
    set_mentor_variants(
        {
            "warrior_cleaving_blow_drathian": _variant("warrior_cleaving_blow_drathian"),
            "warrior_cleaving_blow_keldaran": _variant("warrior_cleaving_blow_keldaran"),
            "guardian_taunt_thornwarden": _variant("guardian_taunt_thornwarden", "guardian_taunt"),
        }
    )
    cleaving = get_variants_for_ability("warrior_cleaving_blow")
    assert {v.id for v in cleaving} == {
        "warrior_cleaving_blow_drathian",
        "warrior_cleaving_blow_keldaran",
    }
    assert get_variants_for_ability("unknown_ability") == ()
