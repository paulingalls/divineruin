"""Spell preparation rules — Track 3, on long rest (M8 story-006).

Preparation is a deterministic Resolve (ADR 0007: no new @function_tool). These pure
gates enforce the Track 3 rules (game_mechanics_archetypes.md L1255-1283):
  - can only prepare a spell you KNOW (in the library)
  - can only prepare a tier you have level access to (leveling.is_spell_tier_unlocked)
  - within the elective slot limit (core spells are abilities, slot-free, untouched)
  - Primal casters (Druid/Beastcaller/Warden) may only CHANGE preparation in natural terrain
  - Paladin/Diplomat/Marshal cap at Major tier (no Supreme) — a strict subset of divine
    casters, so the cap is an explicit id set, NOT magic_source (cleric/oracle keep Supreme).

Both gates fail loud: they raise ValueError with a specific message on violation and
return None when the preparation is allowed (mirrors rest_mechanics.swap_elective_on_long_rest).
The async long-rest Resolve (rest_mechanics.prepare_spells_on_long_rest) is exercised lower
in this file against a stateful mock store; the literal real-Postgres AC4 assertion rides the
M8 story-007 capstone (ADR 0003: real-DB testcontainer fixtures are unreachable from tests/).
"""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

import leveling
import rest_mechanics
import spell_preparation

_ARCHETYPES_JSON = Path(__file__).resolve().parents[3] / "content" / "archetypes.json"


def _archetypes_by_magic_source() -> dict[str | None, set[str]]:
    """Group archetype ids by magic_source from the content SSOT."""
    rows = json.loads(_ARCHETYPES_JSON.read_text())
    by_source: dict[str | None, set[str]] = {}
    for row in rows:
        by_source.setdefault(row.get("magic_source"), set()).add(row["id"])
    return by_source


# --- AC2: Primal terrain gate (can_change_preparation, keyed on magic_source) ---


def test_primal_source_cannot_change_preparation_outside_natural_terrain():
    with pytest.raises(ValueError, match="natural terrain"):
        spell_preparation.can_change_preparation("primal", in_natural_terrain=False)


def test_primal_source_can_change_preparation_in_natural_terrain():
    assert spell_preparation.can_change_preparation("primal", in_natural_terrain=True) is None


@pytest.mark.parametrize("magic_source", ["arcane", "divine", "cross", None])
def test_non_primal_source_unaffected_by_terrain(magic_source):
    # Every non-primal source (and pure martials, None) re-prepares anywhere.
    assert spell_preparation.can_change_preparation(magic_source, in_natural_terrain=False) is None


# --- AC1: know-it / tier-access / slot gates (can_prepare) ---


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
    # standard unlocks at L4; a level-3 caster cannot prepare it.
    with pytest.raises(ValueError, match="unlock"):
        _prepare(spell_tier="standard", character_level=3)


def test_can_prepare_no_open_slot_rejected():
    with pytest.raises(ValueError, match="slot"):
        _prepare(prepared_elective_count=3, slot_limit=3)


def test_can_prepare_unknown_tier_fails_loud():
    # Delegates to is_spell_tier_unlocked, which raises on an unknown tier.
    with pytest.raises(ValueError, match="unknown spell tier"):
        _prepare(spell_tier="legendary", character_level=20, known_spell_ids={"arcane_fireball"})


# --- AC3: Major-tier cap for paladin/diplomat/marshal (divine subset) ---


@pytest.mark.parametrize("archetype_id", ["paladin", "diplomat", "marshal"])
def test_major_capped_archetype_cannot_prepare_supreme(archetype_id):
    # Level is high enough (Supreme unlocks at L13) so the rejection is the Major cap,
    # not the level gate.
    with pytest.raises(ValueError, match="Major"):
        _prepare(
            spell_id="divine_judgment",
            spell_tier="supreme",
            archetype_id=archetype_id,
            character_level=13,
            known_spell_ids={"divine_judgment"},
        )


@pytest.mark.parametrize("archetype_id", ["paladin", "diplomat", "marshal"])
def test_major_capped_archetype_can_prepare_major(archetype_id):
    assert (
        _prepare(
            spell_id="divine_smite",
            spell_tier="major",
            archetype_id=archetype_id,
            character_level=7,
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


# --- Parity: the hardcoded Major-cap set must stay in sync with content/archetypes.json ---
# Guards silent drift if a divine archetype is renamed/added in the content SSOT without
# updating the explicit cap set here. (The primal terrain rule is now derived from
# magic_source, so it needs no parity guard.)


def test_major_capped_archetypes_are_known_divine_casters():
    # The Major cap is a strict subset of divine casters (cleric/oracle keep Supreme).
    divine_in_content = _archetypes_by_magic_source().get("divine", set())
    assert divine_in_content >= spell_preparation.MAJOR_TIER_CAPPED_ARCHETYPES
    # ...and a strict superset: at least one divine caster (cleric/oracle) keeps Supreme.
    assert divine_in_content > spell_preparation.MAJOR_TIER_CAPPED_ARCHETYPES


def test_spell_tier_order_matches_min_level_tier_vocab():
    # SPELL_TIER_ORDER (derived from SpellTier) must cover the same closed enum as the
    # level-gate table, so the two representations cannot silently diverge.
    assert set(spell_preparation.SPELL_TIER_ORDER) == set(leveling.MIN_LEVEL_BY_SPELL_TIER)


# --- AC1/AC4: the async long-rest Resolve (rest_mechanics.prepare_spells_on_long_rest) ---
# These drive the full preparation flow against a stateful in-memory store (the persistence
# seam). The literal real-Postgres single-DB assertion for AC4 rides the M8 story-007 capstone
# in tests/acceptance/ (ADR 0003: real-DB testcontainer fixtures are unreachable from tests/;
# decision retro-try-ac4-capstone-placement — story-004/005 defer the same way). Catalog spell
# ids/tiers are the seeded fixture: arcane cantrip/minor/standard/major, divine supreme, primal cantrip.

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
    # Exactly slot_limit spells is allowed (boundary).
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
    # All-or-nothing: validation happens before any mutation, so nothing persisted.
    assert _prepared_ids(store) == set()


async def test_prepare_unknown_spell_refused_with_no_writes():
    # arcane_fireball is a real catalog spell but NOT in this character's library.
    store = _make_store({"arcane_frost_touch": False})
    with pytest.raises(ValueError, match="does not know"):
        await _prepare_flow(store, ["arcane_frost_touch", "arcane_fireball"], character_level=7)
    assert _prepared_ids(store) == set()


async def test_prepare_clears_deselected_electives():
    # arcane_frost_touch was prepared last rest; the new loadout drops it for arcane_magic_missile.
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
    with pytest.raises(ValueError, match="Major"):
        await _prepare_flow(store, ["divine_greater_restoration"], archetype_id="paladin", character_level=13)
    assert _prepared_ids(store) == set()


async def test_prepare_duplicate_loadout_refused_with_no_writes():
    # A loadout is a set of distinct electives; a duplicate is malformed input. It must fail
    # loud (not silently mis-count a slot or double-write) before any mutation.
    store = _make_store({"arcane_frost_touch": False, "arcane_magic_missile": False})
    with pytest.raises(ValueError, match="duplicate"):
        await _prepare_flow(store, ["arcane_frost_touch", "arcane_frost_touch"], slot_limit=3)
    assert _prepared_ids(store) == set()
    store.set_prepared.assert_not_called()


async def test_prepare_skips_rewrite_of_already_prepared_spell():
    # Delta-only: a spell already prepared and still in the loadout must NOT be re-written;
    # only the newly added spell gets a set_prepared(True) call.
    store = _make_store({"arcane_frost_touch": True, "arcane_magic_missile": False})
    await _prepare_flow(store, ["arcane_frost_touch", "arcane_magic_missile"])
    assert _prepared_ids(store) == {"arcane_frost_touch", "arcane_magic_missile"}
    # Exactly one write: arcane_magic_missile -> True. arcane_frost_touch is untouched.
    store.set_prepared.assert_called_once_with(_PLAYER, "arcane_magic_missile", True, conn=None)
