"""Tests for spells.py — the DB-loaded ELECTIVE spell catalog (M8 / story-001).

Mirrors the abilities.py loader contract (parse_spell_row fail-loud shared by the
DB loader and the JSON test fixture, set_spells test seam, get_spell /
get_spells_by_source accessors, is_loaded, build-then-swap load_spells) — but the
catalog is SOURCE-keyed (arcane/divine/primal), NOT archetype-keyed: caster CORE
spells stay archetype_abilities rows (ability_type=core, seam 235ae150c5d3), so
content/spells.json holds only the elective library. The row shape is the
cross-language SSOT contract; it borrows M3.3's schema minimally and stays
forward-compatible with the full Phase-3 Magic catalog.

Tier-unlock ladder (the floor character level at which a tier becomes learnable,
enforced by story-005's MIN_LEVEL_BY_SPELL_TIER): cantrip/minor L1, standard L4,
major L7, supreme L13. The minimal catalog sets each spell's level_requirement to
its tier floor.
"""

import json
from pathlib import Path

import pytest

from leveling import MIN_LEVEL_BY_SPELL_TIER, is_spell_tier_unlocked
from spells import (
    Spell,
    get_spell,
    get_spells_by_source,
    is_loaded,
    load_spells,
    parse_spell_row,
    set_spells,
)

CONTENT_PATH = Path(__file__).resolve().parents[3] / "content" / "spells.json"

SPELL_SOURCES = {"arcane", "divine", "primal"}
SPELL_TIERS = {"cantrip", "minor", "standard", "major", "supreme"}

# The floor character level at which each tier becomes learnable. Sourced from the
# prod gate (leveling.MIN_LEVEL_BY_SPELL_TIER) so this fixture cannot silently
# diverge from the constant that story-005/006 enforce.
TIER_LEVEL_FLOOR = MIN_LEVEL_BY_SPELL_TIER

_FIREBALL_ROW = {
    "id": "arcane_fireball",
    "name": "Fireball",
    "source": "arcane",
    "spell_tier": "major",
    "level_requirement": 7,
    "focus_cost": 5,
    "mechanics": "A bead of flame detonates in a 20 ft sphere. DEX save, half on success.",
    "narration_cue": "A bead of light detonates — heat, light, the roar of air consumed.",
}

_BLESS_ROW = {
    "id": "divine_bless",
    "name": "Bless",
    "source": "divine",
    "spell_tier": "minor",
    "level_requirement": 1,
    "focus_cost": 2,
    "mechanics": "Up to 3 allies gain +1d4 on attacks and saves. Concentration.",
    "narration_cue": "You speak their names and your patron hears — warmth settling into bones.",
}


def _seed_from_content() -> None:
    raw = json.loads(CONTENT_PATH.read_text())
    set_spells({row["id"]: parse_spell_row(row["id"], row) for row in raw})


# --- parse_spell_row -----------------------------------------------------------


def test_parse_spell_row_full_shape():
    s = parse_spell_row(_FIREBALL_ROW["id"], _FIREBALL_ROW)
    assert isinstance(s, Spell)
    assert (s.id, s.name, s.source) == ("arcane_fireball", "Fireball", "arcane")
    assert s.spell_tier == "major"
    assert s.level_requirement == 7
    assert s.focus_cost == 5
    assert s.mechanics and s.narration_cue


def test_parse_spell_row_fail_loud_names_the_row():
    bad = {k: v for k, v in _FIREBALL_ROW.items() if k != "focus_cost"}
    with pytest.raises(ValueError, match="arcane_fireball"):
        parse_spell_row("arcane_fireball", bad)


@pytest.mark.parametrize("not_a_dict", [None, []])
def test_parse_spell_row_rejects_non_dict_row(not_a_dict):
    # Parity with the TS loader's asRecord guard (spells-load.test.ts): a non-object
    # row fails loud naming the id. Python reaches it via the wrapped TypeError rather
    # than an explicit dict guard (mirroring abilities.parse_ability_row).
    with pytest.raises(ValueError, match="arcane_fireball"):
        parse_spell_row("arcane_fireball", not_a_dict)


def test_parse_spell_row_rejects_unknown_source():
    bad = {**_FIREBALL_ROW, "source": "shadow"}
    with pytest.raises(ValueError, match=r"source"):
        parse_spell_row(_FIREBALL_ROW["id"], bad)


def test_parse_spell_row_rejects_unknown_tier():
    bad = {**_FIREBALL_ROW, "spell_tier": "legendary"}
    with pytest.raises(ValueError, match=r"spell_tier"):
        parse_spell_row(_FIREBALL_ROW["id"], bad)


def test_parse_spell_row_rejects_noninteger_level_requirement():
    bad = {**_FIREBALL_ROW, "level_requirement": "7"}
    with pytest.raises(ValueError, match=r"level_requirement"):
        parse_spell_row(_FIREBALL_ROW["id"], bad)


def test_parse_spell_row_rejects_bool_level_requirement():
    # bool is an int subclass — must be excluded (parity with the TS integer guard).
    bad = {**_FIREBALL_ROW, "level_requirement": True}
    with pytest.raises(ValueError, match=r"level_requirement"):
        parse_spell_row(_FIREBALL_ROW["id"], bad)


def test_parse_spell_row_rejects_noninteger_focus_cost():
    bad = {**_FIREBALL_ROW, "focus_cost": "5"}
    with pytest.raises(ValueError, match=r"focus_cost"):
        parse_spell_row(_FIREBALL_ROW["id"], bad)


def test_parse_spell_row_rejects_bool_focus_cost():
    bad = {**_FIREBALL_ROW, "focus_cost": True}
    with pytest.raises(ValueError, match=r"focus_cost"):
        parse_spell_row(_FIREBALL_ROW["id"], bad)


# --- accessors -----------------------------------------------------------------


def test_get_spell_resolves_and_unknown_raises():
    set_spells({"arcane_fireball": parse_spell_row(_FIREBALL_ROW["id"], _FIREBALL_ROW)})
    assert get_spell("arcane_fireball").name == "Fireball"
    with pytest.raises(ValueError, match="nope"):
        get_spell("nope")


def test_get_spells_by_source_filters():
    set_spells(
        {
            "arcane_fireball": parse_spell_row(_FIREBALL_ROW["id"], _FIREBALL_ROW),
            "divine_bless": parse_spell_row(_BLESS_ROW["id"], _BLESS_ROW),
        }
    )
    arcane = get_spells_by_source("arcane")
    assert arcane and all(s.source == "arcane" for s in arcane)
    assert {s.id for s in arcane} == {"arcane_fireball"}


def test_get_spells_by_source_unknown_returns_empty():
    set_spells({"arcane_fireball": parse_spell_row(_FIREBALL_ROW["id"], _FIREBALL_ROW)})
    assert get_spells_by_source("shadow") == ()


def test_set_spells_seam_replaces_state():
    set_spells({"divine_bless": parse_spell_row(_BLESS_ROW["id"], _BLESS_ROW)})
    assert get_spell("divine_bless").focus_cost == 2
    with pytest.raises(ValueError):
        get_spell("arcane_fireball")


def test_is_loaded_reflects_population():
    set_spells({})
    assert is_loaded() is False
    set_spells({"divine_bless": parse_spell_row(_BLESS_ROW["id"], _BLESS_ROW)})
    assert is_loaded() is True


# --- content/spells.json conformance -------------------------------------------


def test_content_every_row_parses_and_covers_each_source_and_tier():
    _seed_from_content()
    raw = json.loads(CONTENT_PATH.read_text())
    assert raw, "content/spells.json is empty"
    pairs = set()
    for row in raw:
        s = get_spell(row["id"])
        assert s.source in SPELL_SOURCES
        assert s.spell_tier in SPELL_TIERS
        pairs.add((s.source, s.spell_tier))
    # Every source has >=1 elective per tier so downstream track/prep/gate tests have data.
    for source in SPELL_SOURCES:
        for tier in SPELL_TIERS:
            assert (source, tier) in pairs, f"missing {source}/{tier} in content/spells.json"


def test_content_level_requirement_matches_tier_floor():
    _seed_from_content()
    raw = json.loads(CONTENT_PATH.read_text())
    for row in raw:
        s = get_spell(row["id"])
        assert s.level_requirement == TIER_LEVEL_FLOOR[s.spell_tier], (
            f"{s.id}: level_requirement {s.level_requirement} != tier floor "
            f"{TIER_LEVEL_FLOOR[s.spell_tier]} for {s.spell_tier}"
        )
        # The prod gate must agree with the row's own level_requirement: unlocked
        # exactly at the floor, gated one level below.
        assert is_spell_tier_unlocked(s.spell_tier, s.level_requirement) is True
        if s.level_requirement > 1:
            assert is_spell_tier_unlocked(s.spell_tier, s.level_requirement - 1) is False


def test_content_excludes_caster_core_spells():
    # Core spells (Arcane Bolt, Sacred Flame, Heal Wounds, Thorn Whip, Healing Touch)
    # live as archetype_abilities rows (seam 235ae150c5d3), NOT the elective catalog.
    _seed_from_content()
    raw = json.loads(CONTENT_PATH.read_text())
    names = {row["name"].lower() for row in raw}
    for core in ("arcane bolt", "sacred flame", "heal wounds", "thorn whip", "healing touch"):
        assert core not in names, f"core spell {core!r} must stay an ability, not a catalog row"


# --- build-then-swap load_spells (DB path) -------------------------------------


class _FakePool:
    def __init__(self, rows):
        self._rows = rows

    async def fetch(self, _query):
        return self._rows


async def test_load_spells_malformed_row_does_not_wipe_loaded_map(monkeypatch):
    set_spells({"arcane_fireball": parse_spell_row(_FIREBALL_ROW["id"], _FIREBALL_ROW)})

    import db

    bad_rows = [
        {"id": _BLESS_ROW["id"], "data": json.dumps(_BLESS_ROW)},
        {"id": "broken", "data": json.dumps({**_BLESS_ROW, "id": "broken", "source": "shadow"})},
    ]

    async def fake_get_pool():
        return _FakePool(bad_rows)

    monkeypatch.setattr(db, "get_pool", fake_get_pool)

    with pytest.raises(ValueError):
        await load_spells()

    # Prior map survived; the well-formed row preceding the malformed one did NOT leak.
    assert get_spell("arcane_fireball").name == "Fireball"
    with pytest.raises(ValueError, match="divine_bless"):
        get_spell("divine_bless")


async def test_load_spells_populates_from_pool(monkeypatch):
    set_spells({})
    import db

    rows = [
        {"id": _FIREBALL_ROW["id"], "data": json.dumps(_FIREBALL_ROW)},
        {"id": _BLESS_ROW["id"], "data": _BLESS_ROW},  # dict (asyncpg may return parsed JSONB)
    ]

    async def fake_get_pool():
        return _FakePool(rows)

    monkeypatch.setattr(db, "get_pool", fake_get_pool)

    await load_spells()
    assert is_loaded() is True
    assert get_spell("arcane_fireball").focus_cost == 5
    assert get_spell("divine_bless").source == "divine"
