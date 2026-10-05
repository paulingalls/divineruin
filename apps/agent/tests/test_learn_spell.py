"""learn(kind='spell') acquisition + the level→tier unlock gate (M8 story-005).

Spells add ZERO new @function_tools (ADR 0007): scroll/mentor acquisition rides
the existing learn(kind, id, source) verb via a 'spell' kind dispatched to
spell_tools. A character may not learn a spell above their archetype's level
allowance — leveling.is_spell_tier_unlocked, keyed by (archetype, tier, level),
is the enforced gate (shared with the prepare check). A full caster unlocks
standard/major/supreme at L3/L5/L9; the per-archetype matrix is in test_leveling.

The literal real-Postgres AC4 (mentor-taught Minor spell -> character_spells with
acquisition_track for npc_teaching, one DB) rides the M8 story-007 capstone
(ADR 0003: real-DB testcontainer fixtures are unreachable from tests/); the unit
tests here cover AC4's behavior with mock seams, consistent with story-004.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from livekit.agents.llm import ToolError
from sample_fixtures import make_context

import spell_tools
from recipe_tools import _learn_impl
from spells import Spell, SpellSource, SpellTier


def _spell(spell_id="arcane_fireball", *, tier: SpellTier = "standard", source: SpellSource = "arcane"):
    return Spell(
        verbal=True,
        hostile=True,
        id=spell_id,
        name="Fireball",
        source=source,
        spell_tier=tier,
        focus_cost=1,
        mechanics="boom",
        narration_cue="The air ignites.",
    )


def _spells_mod(spell=None):
    """A spells module stub: get_spell returns `spell`, or raises ValueError (unknown)."""
    m = MagicMock()
    if spell is None:
        m.get_spell = MagicMock(side_effect=ValueError("Unknown spell: x"))
    else:
        m.get_spell = MagicMock(return_value=spell)
    return m


def _queries_mod(*, level=20, archetype="mage", player_exists=True):
    q = MagicMock()
    q.get_player = AsyncMock(
        return_value={"player_id": "player_1", "level": level, "class": archetype} if player_exists else None
    )
    return q


class TestLearnSpell:
    @pytest.mark.asyncio
    async def test_discovery_records_track(self):
        cs = MagicMock()
        cs.record_learned = AsyncMock()
        await spell_tools._learn_spell_impl(
            make_context(player_id="player_1"),
            "arcane_fireball",
            "discovery",
            queries_mod=_queries_mod(level=20),
            spells_mod=_spells_mod(_spell(tier="cantrip")),
            character_spells_mod=cs,
        )
        cs.record_learned.assert_awaited_once_with("player_1", "arcane_fireball", "discovery")

    @pytest.mark.asyncio
    async def test_mentor_records_npc_teaching_track(self):
        cs = MagicMock()
        cs.record_learned = AsyncMock()
        await spell_tools._learn_spell_impl(
            make_context(player_id="player_1"),
            "arcane_minor_ward",
            "npc_teaching",
            queries_mod=_queries_mod(level=1),
            spells_mod=_spells_mod(_spell("arcane_minor_ward", tier="minor")),
            character_spells_mod=cs,
        )
        cs.record_learned.assert_awaited_once_with("player_1", "arcane_minor_ward", "npc_teaching")

    @pytest.mark.asyncio
    async def test_tier_gate_rejects_above_level(self):
        cs = MagicMock()
        cs.record_learned = AsyncMock()
        with pytest.raises(ToolError, match="level 3"):
            await spell_tools._learn_spell_impl(
                make_context(player_id="player_1"),
                "arcane_fireball",
                "discovery",
                queries_mod=_queries_mod(level=2, archetype="mage"),
                spells_mod=_spells_mod(_spell(tier="standard")),
                character_spells_mod=cs,
            )
        cs.record_learned.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_tier_gate_allows_at_min_level(self):
        cs = MagicMock()
        cs.record_learned = AsyncMock()
        await spell_tools._learn_spell_impl(
            make_context(player_id="player_1"),
            "arcane_fireball",
            "discovery",
            queries_mod=_queries_mod(level=3, archetype="mage"),
            spells_mod=_spells_mod(_spell(tier="standard")),
            character_spells_mod=cs,
        )
        cs.record_learned.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_non_caster_archetype_cannot_learn_spells(self):
        cs = MagicMock()
        cs.record_learned = AsyncMock()
        with pytest.raises(ToolError, match="no magic source"):
            await spell_tools._learn_spell_impl(
                make_context(player_id="player_1"),
                "arcane_fireball",
                "discovery",
                queries_mod=_queries_mod(level=20, archetype="warrior"),
                spells_mod=_spells_mod(_spell(tier="cantrip")),
                character_spells_mod=cs,
            )
        cs.record_learned.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_invalid_source_raises(self):
        cs = MagicMock()
        cs.record_learned = AsyncMock()
        with pytest.raises(ToolError, match="source"):
            await spell_tools._learn_spell_impl(
                make_context(player_id="player_1"),
                "arcane_fireball",
                "telepathy",
                queries_mod=_queries_mod(),
                spells_mod=_spells_mod(_spell()),
                character_spells_mod=cs,
            )
        cs.record_learned.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_unknown_spell_raises(self):
        with pytest.raises(ToolError, match="Unknown spell"):
            await spell_tools._learn_spell_impl(
                make_context(player_id="player_1"),
                "no_such_spell",
                "discovery",
                queries_mod=_queries_mod(),
                spells_mod=_spells_mod(None),
                character_spells_mod=MagicMock(),
            )

    @pytest.mark.asyncio
    async def test_unknown_player_raises(self):
        with pytest.raises(ToolError, match="player"):
            await spell_tools._learn_spell_impl(
                make_context(player_id="ghost"),
                "arcane_fireball",
                "discovery",
                queries_mod=_queries_mod(player_exists=False),
                spells_mod=_spells_mod(_spell(tier="cantrip")),
                character_spells_mod=MagicMock(),
            )


class TestLearnDispatch:
    @pytest.mark.asyncio
    async def test_spell_kind_delegates_to_spell_impl(self):
        with patch("recipe_tools.spell_tools._learn_spell_impl", new_callable=AsyncMock) as mock_impl:
            mock_impl.return_value = "{}"
            await _learn_impl(make_context(player_id="player_1"), "spell", "arcane_fireball", "discovery")
        mock_impl.assert_awaited_once()
        assert mock_impl.await_args is not None
        assert mock_impl.await_args.args[1:] == ("arcane_fireball", "discovery")

    @pytest.mark.asyncio
    async def test_unknown_kind_names_all_kinds(self):
        with pytest.raises(ToolError, match="recipe, spell, variant"):
            await _learn_impl(make_context(player_id="player_1"), "potion", "healing", "discovery")
