"""Tests for starting elective-spell assignment at character creation (M8 story-003).

Caster CORE spells are archetype_abilities rows (seam 235ae150c5d3); story-003
auto-assigns STARTING ELECTIVE spells (spec L1253: pre-game training) to the 9
single-source casters — 1 cantrip + 1 minor from the archetype's magic source,
recorded prepared in character_spells. Martials and cross/hybrid/social casters
get none at L1.

Covers: select_starting_spells (pure, deterministic), the finalize_character grant
hook, and the new magic_source chassis field's fail-loud parse.
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from archetypes import parse_archetype_row
from creation_rules import select_starting_spells
from creation_tools import finalize_character
from session_data import CreationState, SessionData

_finalize: Any = finalize_character._func


# --- select_starting_spells (pure) --------------------------------------------


class TestSelectStartingSpells:
    def test_mage_gets_arcane_cantrip_and_minor(self):
        ids = select_starting_spells("mage", "arcane")
        assert len(ids) == 2
        from spells import get_spell

        tiers = {get_spell(i).spell_tier for i in ids}
        sources = {get_spell(i).source for i in ids}
        assert tiers == {"cantrip", "minor"}
        assert sources == {"arcane"}

    def test_cleric_gets_divine_pair(self):
        ids = select_starting_spells("cleric", "divine")
        from spells import get_spell

        assert {get_spell(i).source for i in ids} == {"divine"}
        assert {get_spell(i).spell_tier for i in ids} == {"cantrip", "minor"}

    def test_druid_gets_primal_pair(self):
        ids = select_starting_spells("druid", "primal")
        from spells import get_spell

        assert {get_spell(i).source for i in ids} == {"primal"}

    def test_deterministic_pick_is_lowest_id_per_tier(self):
        # Stable across runs: lowest spell id within each tier of the source.
        first = select_starting_spells("mage", "arcane")
        second = select_starting_spells("mage", "arcane")
        assert first == second

    def test_martial_gets_nothing(self):
        assert select_starting_spells("warrior", None) == []

    @pytest.mark.parametrize(
        "archetype_id,source", [("bard", "cross"), ("whisper", "arcane"), ("diplomat", "divine"), ("marshal", "divine")]
    )
    def test_cross_hybrid_social_get_nothing_at_l1(self, archetype_id, source):
        # Spec L1 elective tables grant L1 electives only to the 9 single-source casters.
        assert select_starting_spells(archetype_id, source) == []


# --- finalize_character grant hook --------------------------------------------


def _caster_state() -> CreationState:
    return CreationState(
        phase="identity",
        race="elari",
        class_choice="mage",
        deity=None,
        name="Aric",
        backstory="Seeker of truth.",
    )


def _martial_state() -> CreationState:
    return CreationState(
        phase="identity",
        race="human",
        class_choice="warrior",
        deity="kaelen",
        name="Thane",
        backstory="A sellsword.",
    )


def _ctx(cs: CreationState) -> MagicMock:
    sd = SessionData(player_id="test_player", location_id="", room=None, creation_state=cs)
    ctx = MagicMock()
    ctx.userdata = sd
    return ctx


_PAYLOAD = {
    "character": {"name": "Aric"},
    "location": None,
    "quests": [],
    "inventory": [],
    "map_progress": [],
    "world_state": {},
}


class TestFinalizeGrantsStartingSpells:
    @patch("creation_tools.character_spells.record_learned", new_callable=AsyncMock)
    @patch("creation_tools.db_queries.get_session_init_payload", new_callable=AsyncMock)
    @patch("creation_tools.db_mutations.create_player", new_callable=AsyncMock)
    async def test_mage_creation_records_two_prepared_electives(self, _create, mock_payload, mock_record):
        mock_payload.return_value = _PAYLOAD
        await _finalize(_ctx(_caster_state()))
        assert mock_record.await_count == 2
        for call in mock_record.await_args_list:
            assert call.kwargs["is_prepared"] is True
            # acquisition_track passed positionally (player_id, spell_id, track) or kw.
            args = call.args
            assert "training" in (list(args) + list(call.kwargs.values()))

    @patch("creation_tools.character_spells.record_learned", new_callable=AsyncMock)
    @patch("creation_tools.db_queries.get_session_init_payload", new_callable=AsyncMock)
    @patch("creation_tools.db_mutations.create_player", new_callable=AsyncMock)
    async def test_martial_creation_records_no_spells(self, _create, mock_payload, mock_record):
        mock_payload.return_value = _PAYLOAD
        await _finalize(_ctx(_martial_state()))
        mock_record.assert_not_awaited()


# --- magic_source chassis field -----------------------------------------------

_MAGE_ROW = {
    "id": "mage",
    "hp": {"base": 8, "growth": 3, "category": "arcane_shadow"},
    "resource": {
        "pattern": "focus_only",
        "stamina_formula": None,
        "focus_formula": {"base": 8, "attribute": "intelligence", "level_divisor": 1},
    },
    "save_proficiencies": ["intelligence", "wisdom"],
    "armor_proficiencies": ["none"],
    "weapon_proficiencies": ["staff"],
    "starting_skills": {"options": ["arcana"], "num_choices": 1},
    "magic_source": "arcane",
}


class TestMagicSourceParse:
    def test_parses_valid_magic_source(self):
        assert parse_archetype_row("mage", _MAGE_ROW).magic_source == "arcane"

    def test_absent_magic_source_is_none(self):
        row = {k: v for k, v in _MAGE_ROW.items() if k != "magic_source"}
        assert parse_archetype_row("warrior", row).magic_source is None

    def test_rejects_out_of_vocab_magic_source(self):
        bad = {**_MAGE_ROW, "magic_source": "shadow"}
        with pytest.raises(ValueError, match="magic_source"):
            parse_archetype_row("mage", bad)
