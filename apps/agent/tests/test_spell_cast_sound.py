"""Tests for deterministic PLAY_SOUND emit at spell-cast resolution (M17 story-004).

_resolve_cast defers a PLAY_SOUND(sound_id) event alongside the existing
RESONANCE_CHANGED/echo events (rollback-safe: only fires when the caller flushes
post-commit). This mirrors the resonance_changed capture pattern in
test_spell_casting.py, but asserts on game_events.publish_game_event directly
since PLAY_SOUND is not routed through resonance_events_mod.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

from sample_fixtures import make_context, make_db_mod

import event_types as E
from spell_casting import _cast_spell_impl
from spells import Spell


def _spell(*, spell_id: str = "test_spell", sound_id: str = "impact_arcane") -> Spell:
    return Spell(
        id=spell_id,
        name="Test Spell",
        source="arcane",
        spell_tier="standard",
        focus_cost=3,
        mechanics="Deals force damage to one target.",
        narration_cue="A surge of raw power snaps outward.",
        audio_cue="SFX-001",
        resonance_by_source={"arcane": 6},
        terrain_effects={},
        sound_id=sound_id,
    )


def _player(focus: int = 10) -> dict:
    return {
        "player_id": "player_1",
        "name": "Lyra",
        "class": "mage",
        "level": 5,
        "focus": {"current": focus, "max": 10},
    }


async def _cast(spell: Spell):
    ctx = make_context()
    mock_db, _conn = make_db_mod()
    queries = MagicMock()
    row = _player()
    queries.get_player = AsyncMock(return_value=row)
    queries.get_players_for_update = AsyncMock(side_effect=lambda ids, *, conn=None: {i: row for i in ids})
    persistence = MagicMock()
    persistence.update_player_resources = AsyncMock()
    mutations = MagicMock()
    mutations.update_player_resonance = AsyncMock()
    events = MagicMock()
    events.publish_resonance_changed = AsyncMock()
    spells_mod = MagicMock()
    spells_mod.get_spell = MagicMock(return_value=spell)
    with patch("spell_casting.publish_game_event", new=AsyncMock()) as publish_mock:
        raw = await _cast_spell_impl(
            ctx,
            spell.id,
            db_mod=mock_db,
            queries_mod=queries,
            persistence_mod=persistence,
            resonance_mutations_mod=mutations,
            resonance_events_mod=events,
            spells_mod=spells_mod,
        )
    return json.loads(raw), ctx, publish_mock


class TestCastSpellPlaySound:
    async def test_cast_emits_play_sound_with_spell_sound_id_after_commit(self):
        spell = _spell(sound_id="impact_arcane")
        _packet, ctx, publish_mock = await _cast(spell)
        publish_mock.assert_awaited_once_with(
            ctx.userdata.room, E.PLAY_SOUND, {"sound_name": "impact_arcane"}, event_bus=ctx.userdata.event_bus
        )

    async def test_play_sound_is_deterministic_from_spell_sound_id_not_llm(self):
        spell = _spell(sound_id="ward_break")
        _packet, _ctx, publish_mock = await _cast(spell)
        assert publish_mock.call_args[0][2] == {"sound_name": "ward_break"}

    async def test_play_sound_is_deferred_until_flush_not_emitted_during_resolve(self):
        # _resolve_cast itself never calls publish_game_event directly; only flush_events (invoked
        # by _cast_spell_impl post-commit) triggers the emit. Patch flush_events to a no-op and
        # confirm publish_game_event is never awaited (rollback-safe deferral).
        spell = _spell()
        ctx = make_context()
        mock_db, _conn = make_db_mod()
        queries = MagicMock()
        row = _player()
        queries.get_player = AsyncMock(return_value=row)
        queries.get_players_for_update = AsyncMock(side_effect=lambda ids, *, conn=None: {i: row for i in ids})
        persistence = MagicMock()
        persistence.update_player_resources = AsyncMock()
        mutations = MagicMock()
        mutations.update_player_resonance = AsyncMock()
        events = MagicMock()
        events.publish_resonance_changed = AsyncMock()
        spells_mod = MagicMock()
        spells_mod.get_spell = MagicMock(return_value=spell)
        with (
            patch("spell_casting.publish_game_event", new=AsyncMock()) as publish_mock,
            patch("spell_casting.CastResult.flush_events", new=AsyncMock()),
        ):
            await _cast_spell_impl(
                ctx,
                spell.id,
                db_mod=mock_db,
                queries_mod=queries,
                persistence_mod=persistence,
                resonance_mutations_mod=mutations,
                resonance_events_mod=events,
                spells_mod=spells_mod,
            )
        publish_mock.assert_not_awaited()
