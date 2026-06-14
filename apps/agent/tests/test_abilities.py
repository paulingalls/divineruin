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


# --- parse_ability_row ---------------------------------------------------------


def test_parse_ability_row_full_shape():
    a = parse_ability_row(_SMITE_ROW["id"], _SMITE_ROW)
    assert isinstance(a, Ability)
    assert (a.id, a.archetype_id, a.name) == ("paladin_divine_smite", "paladin", "Divine Smite")
    assert a.ability_type == "core"
    assert a.level_requirement == 1
    assert a.cost == Cost(stamina=0, focus=2, scaling=_SMITE_ROW["cost"]["scaling"])
    assert a.effect and a.narration_cue


def test_parse_ability_row_fail_loud_names_the_row():
    bad = {k: v for k, v in _CLEAVE_ROW.items() if k != "cost"}
    with pytest.raises(ValueError, match="warrior_cleaving_blow"):
        parse_ability_row("warrior_cleaving_blow", bad)


def test_parse_ability_row_rejects_unknown_ability_type():
    bad = {**_CLEAVE_ROW, "ability_type": "passive"}
    with pytest.raises(ValueError, match=r"ability_type"):
        parse_ability_row(_CLEAVE_ROW["id"], bad)


def test_parse_ability_row_rejects_malformed_cost_missing_key():
    bad = {**_CLEAVE_ROW, "cost": {"stamina": 4, "scaling": None}}
    with pytest.raises(ValueError, match="warrior_cleaving_blow"):
        parse_ability_row("warrior_cleaving_blow", bad)


def test_parse_ability_row_rejects_noninteger_cost():
    bad = {**_CLEAVE_ROW, "cost": {"stamina": "4", "focus": 0, "scaling": None}}
    with pytest.raises(ValueError, match=r"cost\.stamina"):
        parse_ability_row("warrior_cleaving_blow", bad)


def test_parse_ability_row_rejects_noninteger_level_requirement():
    bad = {**_CLEAVE_ROW, "level_requirement": "4"}
    with pytest.raises(ValueError, match=r"level_requirement"):
        parse_ability_row(_CLEAVE_ROW["id"], bad)


def test_parse_ability_row_rejects_bool_level_requirement():
    # bool is an int subclass — must be excluded, mirroring _parse_cost (parity with TS).
    bad = {**_CLEAVE_ROW, "level_requirement": True}
    with pytest.raises(ValueError, match=r"level_requirement"):
        parse_ability_row(_CLEAVE_ROW["id"], bad)


def test_cost_roundtrip_preserves_scaling():
    a = parse_ability_row(_SMITE_ROW["id"], _SMITE_ROW)
    assert a.cost.focus == 2
    assert a.cost.scaling is not None


# --- spell-backed core rows compose their Focus cost from the catalog (Try 2) ---

# A spell-backed core row: the archetype owns its description + narration flavor and
# carries spell_id, but does NOT author `cost` — the Focus cost (the one number shared
# with the cast path) composes from content/spells.json so it can't drift. effect,
# narration_cue, and level stay per-archetype (e.g. the Seeker's reveal-on-hit clause).
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
    # The Focus cost is single-sourced from the catalog — no second authored copy.
    assert a.cost == Cost(stamina=0, focus=spell.focus_cost, scaling=None)
    assert a.spell_id == "arcane_bolt"
    # Per-archetype content is KEPT, not flattened to the spell's generic text.
    assert a.effect == _SPELL_BACKED_SEEKER_ROW["effect"]  # the Seeker's reveal clause
    assert a.narration_cue == _SPELL_BACKED_SEEKER_ROW["narration_cue"]
    assert a.level_requirement == 1
    assert (a.name, a.ability_type, a.archetype_id) == ("Arcane Bolt", "core", "seeker")


def test_spell_backed_row_fails_loud_on_unknown_spell():
    bad = {**_SPELL_BACKED_SEEKER_ROW, "spell_id": "no_such_spell"}
    with pytest.raises(ValueError):
        parse_ability_row(bad["id"], bad)


def test_spell_id_must_be_a_string_when_present():
    # Parity with the TS loader: a present-but-non-string spell_id fails loud rather than
    # silently falling back to an authored cost (a malformed row breaks identically on both).
    bad = {**_SPELL_BACKED_SEEKER_ROW, "spell_id": 123}
    with pytest.raises(ValueError, match="spell_id"):
        parse_ability_row(bad["id"], bad)


def test_non_spell_row_has_no_spell_id():
    a = parse_ability_row(_CLEAVE_ROW["id"], _CLEAVE_ROW)
    assert a.spell_id is None


# --- accessors -----------------------------------------------------------------


def test_get_archetype_abilities_filters_by_archetype():
    _seed_from_content()
    warrior = get_archetype_abilities("warrior")
    assert warrior, "warrior should have abilities"
    assert all(a.archetype_id == "warrior" for a in warrior)
    types = {a.ability_type for a in warrior}
    assert {"core", "reaction", "elective"} <= types
    # A pure caster has core + reaction abilities but no elective techniques (M2.2).
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


# --- build-then-swap load_abilities (DB path) ----------------------------------


class _FakePool:
    def __init__(self, rows):
        self._rows = rows

    async def fetch(self, _query):
        return self._rows


async def test_load_abilities_malformed_row_does_not_wipe_loaded_map(monkeypatch):
    # Seed a known-good map, then drive load_abilities against a fake pool whose
    # rows include a malformed one. The load must raise WITHOUT wiping the prior map.
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

    # Prior map survived the failed load.
    assert get_ability("paladin_divine_smite").name == "Divine Smite"
    # Build-then-swap: the well-formed row that preceded the malformed one in the
    # batch must NOT have leaked into the live map (an inline-mutate load would
    # have leaked it before the second row raised).
    with pytest.raises(ValueError, match="warrior_cleaving_blow"):
        get_ability("warrior_cleaving_blow")


# --- owns_ability (pure ownership predicate, story-006) ------------------------


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
    # Core abilities are always-known for the archetype — no character_abilities row.
    assert owns_ability("warrior", _ability("core", "warrior"), owns_elective=False) is True


def test_owns_ability_core_rejected_when_class_differs():
    assert owns_ability("paladin", _ability("core", "warrior"), owns_elective=False) is False


def test_owns_ability_reaction_follows_the_same_class_rule_as_core():
    assert owns_ability("warrior", _ability("reaction", "warrior"), owns_elective=False) is True
    assert owns_ability("mage", _ability("reaction", "warrior"), owns_elective=False) is False


def test_owns_ability_elective_returns_passed_flag_regardless_of_class():
    # Electives are owned via a character_abilities row; the class is irrelevant
    # (a player can equip an elective whose archetype_id is their own class only,
    # but ownership is the row, supplied here as owns_elective).
    elective = _ability("elective", "warrior")
    assert owns_ability("warrior", elective, owns_elective=True) is True
    assert owns_ability("warrior", elective, owns_elective=False) is False
    # Class never overrides the row result for electives.
    assert owns_ability("mage", elective, owns_elective=True) is True


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
