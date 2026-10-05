"""Core spells are abilities and consume no elective slots; archetype tier access also subsumes hybrid caps."""

import json
from pathlib import Path
from typing import get_args
from unittest.mock import AsyncMock, MagicMock

import pytest

import archetypes
import leveling
import rest_mechanics
import spell_preparation
from spells import SpellTier

_ARCHETYPES_JSON = Path(__file__).resolve().parents[3] / "content" / "archetypes.json"


def _archetypes_by_magic_source() -> dict[str | None, set[str]]:
    """Group archetype ids by magic_source from the content SSOT."""
    rows = json.loads(_ARCHETYPES_JSON.read_text())
    by_source: dict[str | None, set[str]] = {}
    for row in rows:
        by_source.setdefault(row.get("magic_source"), set()).add(row["id"])
    return by_source


def test_primal_source_cannot_change_preparation_outside_natural_terrain():
    with pytest.raises(ValueError, match="natural terrain"):
        spell_preparation.can_change_preparation("primal", in_natural_terrain=False)


def test_primal_source_can_change_preparation_in_natural_terrain():
    assert spell_preparation.can_change_preparation("primal", in_natural_terrain=True) is None


@pytest.mark.parametrize("magic_source", ["arcane", "divine", "cross", None])
def test_non_primal_source_unaffected_by_terrain(magic_source):
    assert spell_preparation.can_change_preparation(magic_source, in_natural_terrain=False) is None


def _prepare(**overrides: object) -> None:
    """can_prepare with sensible allowed-path defaults; override one field per test.

    Overrides are deliberately untyped so fail-loud tests can pass invalid values
    (e.g. an unknown spell_tier) and assert the runtime guard fires.
    """
    kwargs: dict[str, object] = {
        "spell_id": "arcane_fireball",
        "spell_tier": "standard",
        "archetype_id": "mage",
        "character_level": 5,
        "known_spell_ids": {"arcane_fireball"},
        "prepared_elective_count": 0,
        "slot_limit": 3,
    }
    kwargs.update(overrides)
    return spell_preparation.can_prepare(**kwargs)  # type: ignore[arg-type]


def test_can_prepare_known_within_tier_and_slot_ok():
    assert _prepare() is None


def test_can_prepare_unknown_spell_rejected():
    with pytest.raises(ValueError, match="does not know"):
        _prepare(spell_id="arcane_fireball", known_spell_ids={"arcane_ward"})


def test_can_prepare_tier_above_character_level_rejected():
    with pytest.raises(ValueError, match="unlock"):
        _prepare(spell_tier="standard", character_level=2)


def test_can_prepare_no_open_slot_rejected():
    with pytest.raises(ValueError, match="slot"):
        _prepare(prepared_elective_count=3, slot_limit=3)


def test_can_prepare_unknown_tier_fails_loud():
    with pytest.raises(ValueError, match="unknown spell tier"):
        _prepare(spell_tier="legendary", character_level=20, known_spell_ids={"arcane_fireball"})


@pytest.mark.parametrize("archetype_id", ["paladin", "diplomat", "marshal"])
def test_major_capped_archetype_cannot_prepare_supreme(archetype_id):
    with pytest.raises(ValueError, match="not available"):
        _prepare(
            spell_id="divine_judgment",
            spell_tier="supreme",
            archetype_id=archetype_id,
            character_level=20,
            known_spell_ids={"divine_judgment"},
        )


@pytest.mark.parametrize("archetype_id", ["paladin", "diplomat", "marshal"])
def test_major_capped_archetype_can_prepare_major(archetype_id):
    assert (
        _prepare(
            spell_id="divine_smite",
            spell_tier="major",
            archetype_id=archetype_id,
            character_level=9,
            known_spell_ids={"divine_smite"},
        )
        is None
    )


@pytest.mark.parametrize("archetype_id", ["cleric", "oracle", "mage"])
def test_uncapped_caster_can_prepare_supreme(archetype_id):
    # Guards against a magic_source-based over-block: cleric/oracle are divine but NOT
    # in the Major-capped set, so they keep Supreme access.
    assert (
        _prepare(
            spell_id="divine_resurrection",
            spell_tier="supreme",
            archetype_id=archetype_id,
            character_level=13,
            known_spell_ids={"divine_resurrection"},
        )
        is None
    )


def test_supreme_capped_archetypes_are_known_divine_casters():
    no_supreme = {
        a.id
        for a in archetypes._archetypes.values()
        if a.magic_source is not None and "supreme" not in a.spell_tier_min_levels
    }
    assert no_supreme == {"paladin", "diplomat", "marshal"}
    divine_in_content = _archetypes_by_magic_source().get("divine", set())
    assert divine_in_content >= no_supreme
    assert divine_in_content > no_supreme


def test_gate_tier_vocab_matches_spell_tier_literal():
    assert set(get_args(SpellTier)) == leveling.SPELL_TIERS


_PLAYER = "player_1"


def _make_store(known: dict[str, bool]) -> MagicMock:
    """Mock character_spells with a stateful library; get_known/set_prepared share `state`.

    Mirrors test_rest_mechanics._make_persistence so the flow's read->validate->apply can be
    asserted without a DB (AC4's behavior). `state` maps spell_id -> is_prepared.
    """
    state = dict(known)

    async def _get_known(player_id, *, conn=None):
        return [
            {"spell_id": sid, "acquisition_track": "discovery", "is_prepared": prep, "bonus_variant": None}
            for sid, prep in state.items()
        ]

    async def _set_prepared(player_id, spell_id, prepared, *, conn=None):
        assert spell_id in state, f"set_prepared on a spell not in the library: {spell_id!r}"
        state[spell_id] = prepared

    store = MagicMock()
    store.get_known = AsyncMock(side_effect=_get_known)
    store.set_prepared = AsyncMock(side_effect=_set_prepared)
    store.state = state  # exposed for assertions
    return store


def _prepared_ids(store: MagicMock) -> set[str]:
    return {sid for sid, prep in store.state.items() if prep}


async def _prepare_flow(
    store: MagicMock,
    loadout: list[str],
    *,
    slot_limit: int = 3,
    archetype_id: str = "mage",
    character_level: int = 5,
    in_natural_terrain: bool = False,
) -> None:
    await rest_mechanics.prepare_spells_on_long_rest(
        _PLAYER,
        loadout,
        slot_limit=slot_limit,
        archetype_id=archetype_id,
        character_level=character_level,
        in_natural_terrain=in_natural_terrain,
        character_spells_mod=store,
    )


async def test_prepare_marks_loadout_prepared():
    store = _make_store({"arcane_frost_touch": False, "arcane_magic_missile": False, "arcane_mage_hand": False})
    await _prepare_flow(store, ["arcane_frost_touch", "arcane_magic_missile"])
    assert _prepared_ids(store) == {"arcane_frost_touch", "arcane_magic_missile"}


async def test_prepare_loadout_up_to_slot_limit_persists():
    store = _make_store({"arcane_frost_touch": False, "arcane_magic_missile": False, "arcane_mage_hand": False})
    await _prepare_flow(store, ["arcane_frost_touch", "arcane_magic_missile", "arcane_mage_hand"], slot_limit=3)
    assert _prepared_ids(store) == {"arcane_frost_touch", "arcane_magic_missile", "arcane_mage_hand"}


async def test_prepare_over_slot_limit_refused_with_no_writes():
    store = _make_store(
        {
            "arcane_frost_touch": False,
            "arcane_magic_missile": False,
            "arcane_mage_hand": False,
            "arcane_hold_person": False,
        }
    )
    with pytest.raises(ValueError, match="slot"):
        await _prepare_flow(
            store,
            ["arcane_frost_touch", "arcane_magic_missile", "arcane_mage_hand", "arcane_hold_person"],
            slot_limit=3,
        )
    assert _prepared_ids(store) == set()


async def test_prepare_unknown_spell_refused_with_no_writes():
    store = _make_store({"arcane_frost_touch": False})
    with pytest.raises(ValueError, match="does not know"):
        await _prepare_flow(store, ["arcane_frost_touch", "arcane_fireball"], character_level=7)
    assert _prepared_ids(store) == set()


async def test_prepare_clears_deselected_electives():
    store = _make_store({"arcane_frost_touch": True, "arcane_magic_missile": False})
    await _prepare_flow(store, ["arcane_magic_missile"])
    assert _prepared_ids(store) == {"arcane_magic_missile"}


async def test_druid_outside_natural_terrain_refused_with_no_writes():
    store = _make_store({"primal_produce_flame": False})
    with pytest.raises(ValueError, match="natural terrain"):
        await _prepare_flow(
            store, ["primal_produce_flame"], archetype_id="druid", character_level=1, in_natural_terrain=False
        )
    assert _prepared_ids(store) == set()


async def test_druid_in_natural_terrain_prepares():
    store = _make_store({"primal_produce_flame": False})
    await _prepare_flow(
        store, ["primal_produce_flame"], archetype_id="druid", character_level=1, in_natural_terrain=True
    )
    assert _prepared_ids(store) == {"primal_produce_flame"}


async def test_paladin_supreme_in_loadout_refused():
    store = _make_store({"divine_greater_restoration": False})
    with pytest.raises(ValueError, match="not available"):
        await _prepare_flow(store, ["divine_greater_restoration"], archetype_id="paladin", character_level=13)
    assert _prepared_ids(store) == set()


async def test_prepare_duplicate_loadout_refused_with_no_writes():
    store = _make_store({"arcane_frost_touch": False, "arcane_magic_missile": False})
    with pytest.raises(ValueError, match="duplicate"):
        await _prepare_flow(store, ["arcane_frost_touch", "arcane_frost_touch"], slot_limit=3)
    assert _prepared_ids(store) == set()
    store.set_prepared.assert_not_called()


async def test_prepare_skips_rewrite_of_already_prepared_spell():
    store = _make_store({"arcane_frost_touch": True, "arcane_magic_missile": False})
    await _prepare_flow(store, ["arcane_frost_touch", "arcane_magic_missile"])
    assert _prepared_ids(store) == {"arcane_frost_touch", "arcane_magic_missile"}
    store.set_prepared.assert_called_once_with(_PLAYER, "arcane_magic_missile", True, conn=None)
