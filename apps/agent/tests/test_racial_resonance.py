"""Tests for racial_resonance.py — the DB-loaded racial Resonance bonus table (M3.4 / story-001).

Mirrors the spells.py loader contract (parse_*_row fail-loud shared by the DB loader
and the JSON test fixture, set_racial_bonuses test seam, get_racial_resonance_modifier
accessor, is_loaded, build-then-swap load_racial_resonance). The table is the M3.4
FOUNDATION: the six racial Resonance interactions (spec game_mechanics_magic.md
§Racial Resonance Integration, 221-293) live in their own seeded table decoupled from
RaceData (audit guidance), and downstream stories read get_racial_resonance_modifier
rather than hardcoding values.

The table is HETEROGENEOUS — each race carries only its own modifier keys, stored in
the exact param shapes the downstream pure engines expect, so call sites forward the
looked-up value verbatim (human decay_bonus=1 -> apply_resonance_decay racial_modifier=1;
vaelti echo_save_advantage=True -> resolve_hollow_echo advantage_roll=<2nd d20>; draethar 3/"1d6").
get_racial_resonance_modifier fails loud on an unknown race or an unknown modifier_type
for that race — never a silent default; call sites guard by race.
"""

import json
from pathlib import Path

import pytest

from racial_resonance import (
    RacialResonance,
    get_racial_resonance_modifier,
    is_loaded,
    load_racial_resonance,
    parse_racial_resonance_row,
    set_racial_bonuses,
)

CONTENT_PATH = Path(__file__).resolve().parents[3] / "content" / "racial_resonance_bonuses.json"

# The spec contract (magic.md 221-293): each race's modifier keys and their values,
# stored as the additive params downstream engines consume. This is the SSOT the
# content file and the loader's _EXPECTED_MODIFIERS must both satisfy.
SPEC_MODIFIERS: dict[str, dict[str, object]] = {
    "human": {"decay_bonus": 1},
    "korath": {"primal_reduction": 1},
    "thessyn": {"flickering_threshold_bonus": 1},
    "vaelti": {"echo_save_advantage": True},
    "draethar": {"inner_fire_resonance_reduction": 3, "inner_fire_self_damage": "1d6"},
    "elari": {"veil_sense": True, "resonance_arcana_bonus": 1},
}

_HUMAN_ROW = {"id": "human", "name": "Adaptive Resonance", "modifiers": {"decay_bonus": 1}}
_DRAETHAR_ROW = {
    "id": "draethar",
    "name": "Inner Fire",
    "modifiers": {"inner_fire_resonance_reduction": 3, "inner_fire_self_damage": "1d6"},
}


def _seed_from_content() -> None:
    raw = json.loads(CONTENT_PATH.read_text())
    set_racial_bonuses({row["id"]: parse_racial_resonance_row(row["id"], row) for row in raw})


# --- parse_racial_resonance_row -----------------------------------------------


def test_parse_row_full_shape():
    r = parse_racial_resonance_row(_HUMAN_ROW["id"], _HUMAN_ROW)
    assert isinstance(r, RacialResonance)
    assert (r.race, r.name) == ("human", "Adaptive Resonance")
    assert r.modifiers == {"decay_bonus": 1}


def test_parse_row_keeps_heterogeneous_value_types():
    r = parse_racial_resonance_row(_DRAETHAR_ROW["id"], _DRAETHAR_ROW)
    assert r.modifiers["inner_fire_resonance_reduction"] == 3
    assert r.modifiers["inner_fire_self_damage"] == "1d6"


def test_parse_row_rejects_unknown_race():
    bad = {"id": "orc", "name": "Bloodlust", "modifiers": {"decay_bonus": 1}}
    with pytest.raises(ValueError, match="orc"):
        parse_racial_resonance_row("orc", bad)


def test_parse_row_fail_loud_names_the_row_on_missing_name():
    bad = {k: v for k, v in _HUMAN_ROW.items() if k != "name"}
    with pytest.raises(ValueError, match="human"):
        parse_racial_resonance_row("human", bad)


def test_parse_row_rejects_non_dict_modifiers():
    bad = {**_HUMAN_ROW, "modifiers": ["decay_bonus"]}
    with pytest.raises(ValueError, match="human"):
        parse_racial_resonance_row("human", bad)


def test_parse_row_rejects_missing_expected_modifier_key():
    bad = {**_DRAETHAR_ROW, "modifiers": {"inner_fire_resonance_reduction": 3}}  # missing the 1d6 key
    with pytest.raises(ValueError, match="draethar"):
        parse_racial_resonance_row("draethar", bad)


def test_parse_row_rejects_extra_modifier_key():
    bad = {**_HUMAN_ROW, "modifiers": {"decay_bonus": 1, "primal_reduction": 1}}
    with pytest.raises(ValueError, match="human"):
        parse_racial_resonance_row("human", bad)


def test_parse_row_rejects_wrong_value_type():
    # A stringly-typed int modifier fails loud at the load boundary, not downstream.
    bad = {**_HUMAN_ROW, "modifiers": {"decay_bonus": "two"}}
    with pytest.raises(ValueError, match="human"):
        parse_racial_resonance_row("human", bad)


def test_parse_row_rejects_bool_for_int_modifier():
    # bool is a subclass of int — an int modifier must reject True (parity with parse_int).
    bad = {**_HUMAN_ROW, "modifiers": {"decay_bonus": True}}
    with pytest.raises(ValueError, match="human"):
        parse_racial_resonance_row("human", bad)


@pytest.mark.parametrize("not_a_dict", [None, []])
def test_parse_row_rejects_non_dict_row(not_a_dict):
    with pytest.raises(ValueError, match="human"):
        parse_racial_resonance_row("human", not_a_dict)


# --- get_racial_resonance_modifier accessor -----------------------------------


def test_get_modifier_returns_spec_value_for_each_race():
    _seed_from_content()
    for race, mods in SPEC_MODIFIERS.items():
        for modifier_type, value in mods.items():
            got = get_racial_resonance_modifier(race, modifier_type)
            assert got == value, f"{race}.{modifier_type} expected {value!r}, got {got!r}"
            # bool/int are distinct in the contract — a True must not satisfy an int 1 and vice versa.
            assert type(got) is type(value)


def test_get_modifier_unknown_race_raises():
    _seed_from_content()
    with pytest.raises(ValueError, match="orc"):
        get_racial_resonance_modifier("orc", "decay_bonus")


def test_get_modifier_unknown_type_for_known_race_raises():
    _seed_from_content()
    # Korath has no decay_bonus — querying it is a defect, not a 0 default.
    with pytest.raises(ValueError, match=r"primal_reduction|korath|decay_bonus"):
        get_racial_resonance_modifier("korath", "decay_bonus")


def test_set_racial_bonuses_seam_replaces_state():
    set_racial_bonuses({"human": parse_racial_resonance_row(_HUMAN_ROW["id"], _HUMAN_ROW)})
    assert get_racial_resonance_modifier("human", "decay_bonus") == 1
    with pytest.raises(ValueError):
        get_racial_resonance_modifier("draethar", "inner_fire_self_damage")


def test_is_loaded_reflects_population():
    set_racial_bonuses({})
    assert is_loaded() is False
    set_racial_bonuses({"human": parse_racial_resonance_row(_HUMAN_ROW["id"], _HUMAN_ROW)})
    assert is_loaded() is True


# --- content/racial_resonance_bonuses.json conformance ------------------------


def test_content_has_exactly_the_six_races_with_spec_modifiers():
    _seed_from_content()
    raw = json.loads(CONTENT_PATH.read_text())
    assert {row["id"] for row in raw} == set(SPEC_MODIFIERS), "content must hold exactly the six spec races"
    for race, mods in SPEC_MODIFIERS.items():
        for modifier_type, value in mods.items():
            assert get_racial_resonance_modifier(race, modifier_type) == value


# --- build-then-swap load_racial_resonance (DB path) --------------------------


class _FakePool:
    def __init__(self, rows):
        self._rows = rows

    async def fetch(self, _query):
        return self._rows


async def test_load_malformed_row_does_not_wipe_loaded_map(monkeypatch):
    set_racial_bonuses({"human": parse_racial_resonance_row(_HUMAN_ROW["id"], _HUMAN_ROW)})
    import db

    bad_rows = [
        {"id": _DRAETHAR_ROW["id"], "data": json.dumps(_DRAETHAR_ROW)},
        {"id": "orc", "data": json.dumps({"id": "orc", "name": "X", "modifiers": {"decay_bonus": 1}})},
    ]

    async def fake_get_pool():
        return _FakePool(bad_rows)

    monkeypatch.setattr(db, "get_pool", fake_get_pool)

    with pytest.raises(ValueError):
        await load_racial_resonance()

    # Prior map survived; the well-formed row preceding the malformed one did NOT leak.
    assert get_racial_resonance_modifier("human", "decay_bonus") == 1
    with pytest.raises(ValueError):
        get_racial_resonance_modifier("draethar", "inner_fire_self_damage")


async def test_load_populates_from_pool(monkeypatch):
    set_racial_bonuses({})
    import db

    rows = [
        {"id": _HUMAN_ROW["id"], "data": json.dumps(_HUMAN_ROW)},
        {"id": _DRAETHAR_ROW["id"], "data": _DRAETHAR_ROW},  # dict (asyncpg may return parsed JSONB)
    ]

    async def fake_get_pool():
        return _FakePool(rows)

    monkeypatch.setattr(db, "get_pool", fake_get_pool)

    await load_racial_resonance()
    assert is_loaded() is True
    assert get_racial_resonance_modifier("human", "decay_bonus") == 1
    assert get_racial_resonance_modifier("draethar", "inner_fire_self_damage") == "1d6"
