"""Tests for abilities.py — the DB-loaded archetype-ability content config (M2.2).

Mirrors the archetypes.py loader contract: parse_ability_row (fail-loud, shared
by the DB loader and the JSON test fixture), set_abilities (test seam),
get_ability / get_archetype_abilities (accessors), is_loaded, and the
build-then-swap load_abilities (a malformed row must not wipe an already-loaded
map). The row shape is the cross-language SSOT contract (story-001); cost is the
nested object {stamina:int, focus:int, scaling:str|None}.

The conftest autouse seed_abilities fixture pre-populates the map from content
before each test, but every test here seeds its own state up front
(set_abilities / a JSON helper) and so is verifiable independent of that fixture:
test_is_loaded_reflects_population deliberately clears the pre-seeded map with
set_abilities({}) to assert the empty case.
"""

import json
from pathlib import Path

import pytest

from abilities import (
    Ability,
    Cost,
    get_ability,
    get_archetype_abilities,
    is_loaded,
    load_abilities,
    owns_ability,
    parse_ability_row,
    set_abilities,
)

CONTENT_PATH = Path(__file__).resolve().parents[3] / "content" / "archetype_abilities.json"

ARCHETYPE_IDS = {
    "warrior",
    "guardian",
    "skirmisher",
    "mage",
    "artificer",
    "seeker",
    "druid",
    "beastcaller",
    "warden",
    "cleric",
    "paladin",
    "oracle",
    "rogue",
    "spy",
    "whisper",
    "bard",
    "diplomat",
    "marshal",
}

_SMITE_ROW = {
    "id": "paladin_divine_smite",
    "archetype_id": "paladin",
    "name": "Divine Smite",
    "ability_type": "core",
    "level_requirement": 1,
    "cost": {
        "stamina": 0,
        "focus": 2,
        "scaling": "Variable on melee hit: 2 Focus=+1d8, 4 Focus=+2d8, 6 Focus=+3d8 radiant.",
    },
    "effect": "On a melee hit, channel radiant damage.",
    "narration_cue": "The blade blazes white and sears with holy wrath.",
}

_CLEAVE_ROW = {
    "id": "warrior_cleaving_blow",
    "archetype_id": "warrior",
    "name": "Cleaving Blow",
    "ability_type": "elective",
    "level_requirement": 4,
    "cost": {"stamina": 4, "focus": 0, "scaling": None},
    "effect": "A single melee attack hits up to 2 adjacent enemies.",
    "narration_cue": "One sweeping arc bites through two foes at once.",
}


def _seed_from_content() -> None:
    raw = json.loads(CONTENT_PATH.read_text())
    set_abilities({row["id"]: parse_ability_row(row["id"], row) for row in raw})


def test_parse_ability_row_full_shape():
    a = parse_ability_row(_SMITE_ROW["id"], _SMITE_ROW)
    assert isinstance(a, Ability)
    assert (a.id, a.archetype_id, a.name) == ("paladin_divine_smite", "paladin", "Divine Smite")
    assert a.ability_type == "core"
    assert a.level_requirement == 1
    assert a.cost == Cost(stamina=0, focus=2, scaling=_SMITE_ROW["cost"]["scaling"])
    assert a.effect and a.narration_cue


def test_cost_roundtrip_preserves_scaling():
    a = parse_ability_row(_SMITE_ROW["id"], _SMITE_ROW)
    assert a.cost.focus == 2
    assert a.cost.scaling is not None


_SPELL_BACKED_SEEKER_ROW = {
    "id": "seeker_arcane_bolt",
    "archetype_id": "seeker",
    "name": "Arcane Bolt",
    "ability_type": "core",
    "spell_id": "arcane_bolt",
    "level_requirement": 1,
    "effect": "Cantrip; on hit, learn one mechanical property of the target (AC, lowest save, or HP fraction).",
    "narration_cue": "A probing bolt strikes, and the foe's weakness reveals itself.",
}


def test_spell_backed_row_composes_focus_cost_from_catalog():
    import spells

    spell = spells.get_spell("arcane_bolt")
    a = parse_ability_row(_SPELL_BACKED_SEEKER_ROW["id"], _SPELL_BACKED_SEEKER_ROW)
    assert a.cost == Cost(stamina=0, focus=spell.focus_cost, scaling=None)
    assert a.spell_id == "arcane_bolt"
    assert a.effect == _SPELL_BACKED_SEEKER_ROW["effect"]  # the Seeker's reveal clause
    assert a.narration_cue == _SPELL_BACKED_SEEKER_ROW["narration_cue"]
    assert a.level_requirement == 1
    assert (a.name, a.ability_type, a.archetype_id) == ("Arcane Bolt", "core", "seeker")


def test_non_spell_row_has_no_spell_id():
    a = parse_ability_row(_CLEAVE_ROW["id"], _CLEAVE_ROW)
    assert a.spell_id is None


_BRACE_ROW = {
    "id": "warrior_brace_for_impact",
    "archetype_id": "warrior",
    "name": "Brace for Impact",
    "ability_type": "reaction",
    "level_requirement": 1,
    "cost": {"stamina": 0, "focus": 0, "scaling": None},
    "effect": "Reaction when hit: reduce the damage by 1d6 + CON mod.",
    "narration_cue": "You brace, and the blow lands lighter than it should.",
    "window": "on_hit",
}


def test_parse_ability_row_reaction_row_full_shape():
    a = parse_ability_row(_BRACE_ROW["id"], _BRACE_ROW)
    assert a.window == "on_hit"
    assert a.ability_type == "reaction"


def test_non_reaction_row_has_no_window():
    a = parse_ability_row(_CLEAVE_ROW["id"], _CLEAVE_ROW)
    assert a.window is None


def test_get_archetype_abilities_filters_by_archetype():
    _seed_from_content()
    warrior = get_archetype_abilities("warrior")
    assert warrior, "warrior should have abilities"
    assert all(a.archetype_id == "warrior" for a in warrior)
    types = {a.ability_type for a in warrior}
    assert {"core", "reaction", "elective"} <= types
    mage = get_archetype_abilities("mage")
    assert mage and all(a.archetype_id == "mage" for a in mage)
    assert "elective" not in {a.ability_type for a in mage}


def test_get_archetype_abilities_resolves_all_18():
    _seed_from_content()
    for aid in ARCHETYPE_IDS:
        abilities = get_archetype_abilities(aid)
        assert abilities, f"{aid} resolves no abilities"


def test_get_archetype_abilities_unknown_returns_empty():
    set_abilities({"warrior_cleaving_blow": parse_ability_row(_CLEAVE_ROW["id"], _CLEAVE_ROW)})
    assert get_archetype_abilities("nope") == ()


def test_get_ability_resolves_and_unknown_raises():
    set_abilities({"paladin_divine_smite": parse_ability_row(_SMITE_ROW["id"], _SMITE_ROW)})
    assert get_ability("paladin_divine_smite").name == "Divine Smite"
    with pytest.raises(ValueError, match="nope"):
        get_ability("nope")


def test_set_abilities_seam_replaces_state():
    set_abilities({"warrior_cleaving_blow": parse_ability_row(_CLEAVE_ROW["id"], _CLEAVE_ROW)})
    assert get_ability("warrior_cleaving_blow").cost.stamina == 4
    with pytest.raises(ValueError):
        get_ability("paladin_divine_smite")


def test_is_loaded_reflects_population():
    set_abilities({})
    assert is_loaded() is False
    set_abilities({"warrior_cleaving_blow": parse_ability_row(_CLEAVE_ROW["id"], _CLEAVE_ROW)})
    assert is_loaded() is True


class _FakePool:
    def __init__(self, rows):
        self._rows = rows

    async def fetch(self, _query):
        return self._rows


async def test_load_abilities_malformed_row_does_not_wipe_loaded_map(monkeypatch):
    set_abilities({"paladin_divine_smite": parse_ability_row(_SMITE_ROW["id"], _SMITE_ROW)})

    import db

    bad_rows = [
        {"id": _CLEAVE_ROW["id"], "data": json.dumps(_CLEAVE_ROW)},
        {"id": "broken", "data": json.dumps({**_CLEAVE_ROW, "id": "broken", "ability_type": "passive"})},
    ]

    async def fake_get_pool():
        return _FakePool(bad_rows)

    monkeypatch.setattr(db, "get_pool", fake_get_pool)

    with pytest.raises(ValueError):
        await load_abilities()

    assert get_ability("paladin_divine_smite").name == "Divine Smite"
    with pytest.raises(ValueError, match="warrior_cleaving_blow"):
        get_ability("warrior_cleaving_blow")


def _ability(ability_type, archetype_id="warrior"):
    """A minimal Ability of a given type/archetype for the ownership predicate."""
    return Ability(
        id=f"{archetype_id}_x",
        archetype_id=archetype_id,
        name="X",
        ability_type=ability_type,
        level_requirement=1,
        cost=Cost(stamina=0, focus=0, scaling=None),
        effect="e",
        narration_cue="n",
    )


def test_owns_ability_core_owned_when_class_matches_archetype():
    assert owns_ability("warrior", 1, _ability("core", "warrior"), owns_elective=False) is True


def test_owns_ability_core_rejected_when_class_differs():
    assert owns_ability("paladin", 1, _ability("core", "warrior"), owns_elective=False) is False


def test_owns_ability_reaction_follows_the_same_class_rule_as_core():
    assert owns_ability("warrior", 1, _ability("reaction", "warrior"), owns_elective=False) is True
    assert owns_ability("mage", 1, _ability("reaction", "warrior"), owns_elective=False) is False


def test_owns_ability_elective_returns_passed_flag_regardless_of_class():
    elective = _ability("elective", "warrior")
    assert owns_ability("warrior", 1, elective, owns_elective=True) is True
    assert owns_ability("warrior", 1, elective, owns_elective=False) is False
    assert owns_ability("mage", 1, elective, owns_elective=True) is True


def test_owns_ability_rejects_below_level_before_type_rule():
    mass_inspire = get_ability("bard_mass_inspire")
    assert owns_ability("bard", 8, mass_inspire, owns_elective=False) is False
    assert owns_ability("bard", 9, mass_inspire, owns_elective=False) is True


async def test_load_abilities_populates_from_pool(monkeypatch):
    set_abilities({})
    import db

    rows = [
        {"id": _SMITE_ROW["id"], "data": json.dumps(_SMITE_ROW)},
        {"id": _CLEAVE_ROW["id"], "data": _CLEAVE_ROW},  # dict (asyncpg may return parsed JSONB)
    ]

    async def fake_get_pool():
        return _FakePool(rows)

    monkeypatch.setattr(db, "get_pool", fake_get_pool)

    await load_abilities()
    assert is_loaded() is True
    assert get_ability("paladin_divine_smite").cost.focus == 2
    assert get_ability("warrior_cleaving_blow").ability_type == "elective"


@pytest.mark.parametrize(
    "row,message",
    [
        pytest.param(
            {k: v for k, v in _CLEAVE_ROW.items() if k != "cost"},
            "warrior_cleaving_blow",
            id="test_parse_ability_row_fail_loud_names_the_row",
        ),
        pytest.param(
            {**_CLEAVE_ROW, "ability_type": "passive"},
            "ability_type",
            id="test_parse_ability_row_rejects_unknown_ability_type",
        ),
        pytest.param(
            {**_CLEAVE_ROW, "cost": {"stamina": 4, "scaling": None}},
            "warrior_cleaving_blow",
            id="test_parse_ability_row_rejects_malformed_cost_missing_key",
        ),
        pytest.param(
            {**_CLEAVE_ROW, "cost": {"stamina": "4", "focus": 0, "scaling": None}},
            "cost\\.stamina",
            id="test_parse_ability_row_rejects_noninteger_cost",
        ),
        pytest.param(
            {**_CLEAVE_ROW, "level_requirement": "4"},
            "level_requirement",
            id="test_parse_ability_row_rejects_noninteger_level_requirement",
        ),
        pytest.param(
            {**_CLEAVE_ROW, "level_requirement": True},
            "level_requirement",
            id="test_parse_ability_row_rejects_bool_level_requirement",
        ),
        pytest.param(
            {**_SPELL_BACKED_SEEKER_ROW, "spell_id": "no_such_spell"},
            None,
            id="test_spell_backed_row_fails_loud_on_unknown_spell",
        ),
        pytest.param(
            {**_SPELL_BACKED_SEEKER_ROW, "spell_id": 123}, "spell_id", id="test_spell_id_must_be_a_string_when_present"
        ),
        pytest.param(
            {k: v for k, v in _BRACE_ROW.items() if k != "window"},
            "window",
            id="test_parse_ability_row_reaction_requires_window",
        ),
        pytest.param({**_BRACE_ROW, "window": "bogus"}, "window", id="test_parse_ability_row_rejects_unknown_window"),
        pytest.param(
            {**_CLEAVE_ROW, "window": "on_hit"},
            "window",
            id="test_parse_ability_row_rejects_window_on_non_reaction_row",
        ),
    ],
)
def test_malformed_rows_are_refused(row, message):
    with pytest.raises(ValueError, match=message):
        parse_ability_row(row["id"], row)
