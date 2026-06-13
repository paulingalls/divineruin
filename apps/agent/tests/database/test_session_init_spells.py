"""Tests for the spells section of get_session_init_payload (story-007).

The character sheet shows the player's spells (magic.md:299). The payload carries
both the always-known CORE spells (archetype_abilities, spell-backed) and the
learned/prepared ELECTIVE spells (character_spells), each enriched from the catalog
to {spell_id, name, spell_tier, focus_cost, is_prepared}. Core rows are always
prepared; a learned spell that is also core is deduped out of `learned`.
"""

import json
from unittest.mock import AsyncMock, patch

import pytest

import db_queries
from abilities import Ability, Cost
from spells import Spell, SpellTier


def _spell(spell_id: str, name: str, tier: SpellTier, focus: int) -> Spell:
    return Spell(
        id=spell_id,
        name=name,
        source="arcane",
        spell_tier=tier,
        focus_cost=focus,
        mechanics="m",
        narration_cue="n",
    )


def _core_ability(spell_id: str) -> Ability:
    return Ability(
        id=f"mage_{spell_id}",
        archetype_id="mage",
        name="core",
        ability_type="core",
        level_requirement=1,
        cost=Cost(stamina=0, focus=0, scaling=None),
        effect="e",
        narration_cue="n",
        spell_id=spell_id,
    )


_CATALOG = {
    "arcane_bolt": _spell("arcane_bolt", "Arcane Bolt", "cantrip", 0),
    "arcane_fireball": _spell("arcane_fireball", "Fireball", "major", 5),
}


def _mage_pool() -> AsyncMock:
    pool = AsyncMock()
    pool.fetchrow = AsyncMock(
        return_value={"data": json.dumps({"name": "Lyra", "location_id": "tavern", "class": "mage"})}
    )
    pool.fetch = AsyncMock(return_value=[])
    return pool


class TestSessionInitSpells:
    @pytest.mark.asyncio
    async def test_includes_core_and_learned_spells(self):
        known = [
            {"spell_id": "arcane_fireball", "acquisition_track": "training", "is_prepared": True, "bonus_variant": None}
        ]
        with (
            patch("db.get_pool", return_value=_mage_pool()),
            patch("db_content_queries.get_location", return_value={"id": "tavern"}),
            patch("character_spells.get_known", AsyncMock(return_value=known)),
            patch("abilities.get_archetype_abilities", return_value=(_core_ability("arcane_bolt"),)),
            patch("spells.get_spell", side_effect=lambda sid: _CATALOG[sid]),
        ):
            result = await db_queries.get_session_init_payload("p1")

        assert "spells" in result
        assert result["spells"]["core"] == [
            {
                "spell_id": "arcane_bolt",
                "name": "Arcane Bolt",
                "spell_tier": "cantrip",
                "focus_cost": 0,
                "is_prepared": True,
            }
        ]
        assert result["spells"]["learned"] == [
            {
                "spell_id": "arcane_fireball",
                "name": "Fireball",
                "spell_tier": "major",
                "focus_cost": 5,
                "is_prepared": True,
            }
        ]

    @pytest.mark.asyncio
    async def test_learned_spell_also_core_is_deduped(self):
        # arcane_bolt is both a known elective row AND the archetype core spell -> appears
        # once, under core (the always-prepared grant), never duplicated in learned.
        known = [
            {"spell_id": "arcane_bolt", "acquisition_track": "discovery", "is_prepared": False, "bonus_variant": None}
        ]
        with (
            patch("db.get_pool", return_value=_mage_pool()),
            patch("db_content_queries.get_location", return_value={"id": "tavern"}),
            patch("character_spells.get_known", AsyncMock(return_value=known)),
            patch("abilities.get_archetype_abilities", return_value=(_core_ability("arcane_bolt"),)),
            patch("spells.get_spell", side_effect=lambda sid: _CATALOG[sid]),
        ):
            result = await db_queries.get_session_init_payload("p1")

        assert [s["spell_id"] for s in result["spells"]["core"]] == ["arcane_bolt"]
        assert result["spells"]["learned"] == []

    @pytest.mark.asyncio
    async def test_no_spells_yields_empty_sections(self):
        with (
            patch("db.get_pool", return_value=_mage_pool()),
            patch("db_content_queries.get_location", return_value={"id": "tavern"}),
            patch("character_spells.get_known", AsyncMock(return_value=[])),
            patch("abilities.get_archetype_abilities", return_value=()),
            patch("spells.get_spell", side_effect=lambda sid: _CATALOG[sid]),
        ):
            result = await db_queries.get_session_init_payload("p1")

        assert result["spells"] == {"core": [], "learned": []}

    @pytest.mark.asyncio
    async def test_unresolvable_spell_is_skipped_not_fatal(self):
        # A character_spells row whose catalog entry is missing must not blank the whole
        # session payload — it is skipped (logged), the rest of the payload survives.
        known = [
            {"spell_id": "ghost_spell", "acquisition_track": "training", "is_prepared": True, "bonus_variant": None},
            {
                "spell_id": "arcane_fireball",
                "acquisition_track": "training",
                "is_prepared": True,
                "bonus_variant": None,
            },
        ]

        def lookup(sid: str) -> Spell:
            if sid not in _CATALOG:
                raise ValueError(f"Unknown spell: {sid!r}")
            return _CATALOG[sid]

        with (
            patch("db.get_pool", return_value=_mage_pool()),
            patch("db_content_queries.get_location", return_value={"id": "tavern"}),
            patch("character_spells.get_known", AsyncMock(return_value=known)),
            patch("abilities.get_archetype_abilities", return_value=()),
            patch("spells.get_spell", side_effect=lookup),
        ):
            result = await db_queries.get_session_init_payload("p1")

        assert [s["spell_id"] for s in result["spells"]["learned"]] == ["arcane_fireball"]
        assert "character" in result  # rest of the payload intact
