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
The async wiring + real-Postgres E2E (AC4) live in test_rest_mechanics / story-006 part C.
"""

import json
from pathlib import Path

import pytest

import leveling
import spell_preparation

_ARCHETYPES_JSON = Path(__file__).resolve().parents[3] / "content" / "archetypes.json"


def _archetypes_by_magic_source() -> dict[str | None, set[str]]:
    """Group archetype ids by magic_source from the content SSOT."""
    rows = json.loads(_ARCHETYPES_JSON.read_text())
    by_source: dict[str | None, set[str]] = {}
    for row in rows:
        by_source.setdefault(row.get("magic_source"), set()).add(row["id"])
    return by_source


# --- AC2: Primal terrain gate (can_change_preparation) ---


@pytest.mark.parametrize("archetype_id", ["druid", "beastcaller", "warden"])
def test_primal_caster_cannot_change_preparation_outside_natural_terrain(archetype_id):
    with pytest.raises(ValueError, match="natural terrain"):
        spell_preparation.can_change_preparation(archetype_id, in_natural_terrain=False)


@pytest.mark.parametrize("archetype_id", ["druid", "beastcaller", "warden"])
def test_primal_caster_can_change_preparation_in_natural_terrain(archetype_id):
    assert spell_preparation.can_change_preparation(archetype_id, in_natural_terrain=True) is None


@pytest.mark.parametrize("archetype_id", ["mage", "cleric", "paladin", "warrior"])
def test_non_primal_caster_unaffected_by_terrain(archetype_id):
    # Non-primal casters re-prepare anywhere — terrain is irrelevant.
    assert spell_preparation.can_change_preparation(archetype_id, in_natural_terrain=False) is None


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


# --- Parity: hardcoded caster sets must stay in sync with content/archetypes.json ---
# These guard against silent drift if an archetype id is renamed/added in the content SSOT
# without updating the explicit sets here (the module stays pure — no runtime IO coupling).


def test_primal_terrain_casters_match_primal_source_archetypes():
    # The terrain gate must cover EXACTLY the primal-source casters — no more, no fewer.
    primal_in_content = _archetypes_by_magic_source().get("primal", set())
    assert primal_in_content == spell_preparation.PRIMAL_TERRAIN_CASTERS


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
