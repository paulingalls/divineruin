"""Capstone: M27 audio-out-of-the-tool-surface holds together (story-005).

M27 shipped across stories 001-004 (all merged): location tags -> Stage music
(story-001), the creation Awakening `wonder` Resolve (story-002), the audio-tool
teardown that DELETED environment_tools.py (story-003), and dispatch narration for
begin_activity kinds (story-004). Audio now derives ONLY from deterministic Resolves
and the location Stage — no `play_sound`/`set_music_state` LLM tool exists anymore;
the client infers soundscape/music from the data the Resolves already carry.

The client-side derivation (mobile `inferExplorationState`, in `src/audio/music-player.ts`)
is proven by story-001's mobile bun test (`src/__tests__/use-game-events.audio.test.ts`
sibling suite); this file asserts the PYTHON emit side only — that the seams which feed
the client's Stage still fire, and that no agent re-registers an audio tool.

This capstone proves those seams hold TOGETHER (auto-marked ``acceptance`` by
tests/acceptance/conftest.py):

  1. No agent's tool registry re-admits play_sound/set_music_state.
  2. A player move emits LOCATION_CHANGED carrying non-empty tags + ambient_sounds
     -- the data the client Stage derives exploration/tension music from.
  3. Creation Awakening fires SET_MUSIC_STATE{wonder} via a deterministic Resolve.
  4. Combat/spell SFX still emit PLAY_SOUND -- no regression from the story-003 teardown.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from acceptance.test_m5_verb_consolidation import AGENT_TOOL_LISTS, REMOVED_AUDIO_TOOLS
from sample_fixtures import make_context, make_mock_room, published_payloads

import db
import db_content_queries
import event_types as E
import movement_tools
import spells
from creation_tools import push_creation_music
from spell_casting import _cast_spell_impl

# One clean cantrip (focus_cost 0, non-concentration) so the real cast resolves
# without a target/gate -- mirrors the M17 capstone's seed shape.
_CANTRIP_ID = "divine_sacred_flame"

# Real catalog rows that carry both `tags` and `ambient_sounds` -- the two fields the
# client Stage needs to derive exploration/tension/dungeon music + soundscape.
_DESTINATION_ID = "greyvale_ruins_entrance"


async def _seed_player(pool, player_id: str, **overrides) -> None:
    """Upsert a living players.data row with a full Focus pool (mirrors the M17 capstone)."""
    data = {"player_id": player_id, "class": "cleric", "level": 5, "focus": {"current": 10, "max": 10}}
    data.update(overrides)
    await pool.execute(
        "INSERT INTO players (player_id, data) VALUES ($1, $2::jsonb) "
        "ON CONFLICT (player_id) DO UPDATE SET data = $2::jsonb",
        player_id,
        json.dumps(data),
    )


# --- 1. No agent registers an audio tool (thin re-assertion of the headline M27 "done") ---


@pytest.mark.parametrize("name,tools", AGENT_TOOL_LISTS)
def test_no_agent_registers_audio_tools(name: str, tools: list) -> None:
    """Re-asserts the audio-tool invariant under the M27 capstone's own name, so the
    milestone-exit net names it directly. This net's ASSERTION is independent of M5's
    combined-union check -- a re-added play_sound/set_music_state tool fails here even if
    M5's own test ever drops REMOVED_AUDIO_TOOLS from its union. It DOES share M5's
    AGENT_TOOL_LISTS/REMOVED_AUDIO_TOOLS constants (one source of truth for the agent
    registries), so narrowing or renaming those there narrows/breaks this net too."""
    leaked = REMOVED_AUDIO_TOOLS & {t.__name__ for t in tools}
    assert not leaked, f"{name} still registers removed audio tool(s): {sorted(leaked)}"


# --- 2. A player move emits LOCATION_CHANGED carrying tags + ambient_sounds (client-derived Stage) ---


async def test_location_move_emits_stage_audio_data(reset_db_pool: str) -> None:
    destination_location = await db_content_queries.get_location(_DESTINATION_ID)
    assert destination_location is not None, f"{_DESTINATION_ID} missing from seeded content"

    ctx = make_context(player_id="cap_m27_mover", room=make_mock_room())
    session = ctx.userdata

    db_mod = MagicMock()
    conn = AsyncMock()
    db_mod.transaction.return_value.__aenter__ = AsyncMock(return_value=conn)
    db_mod.transaction.return_value.__aexit__ = AsyncMock(return_value=False)
    db_mod.extract_exit_connections = MagicMock(return_value={})
    mutations = AsyncMock()

    with patch.object(
        movement_tools.ward_resolution, "resolve_scope_ward_with_scope", AsyncMock(return_value=(None, None))
    ):
        await movement_tools.apply_arrival(
            session, _DESTINATION_ID, destination_location, db_mod=db_mod, mutations=mutations
        )

    location_changed = [p for p in published_payloads(session.room) if p["type"] == E.LOCATION_CHANGED]
    assert len(location_changed) == 1, (
        f"expected exactly one LOCATION_CHANGED, got types {[p['type'] for p in published_payloads(session.room)]}"
    )
    payload = location_changed[0]
    assert payload["tags"], "LOCATION_CHANGED must carry non-empty tags for the client Stage to derive music"
    assert payload["ambient_sounds"], "LOCATION_CHANGED must carry non-empty ambient_sounds for the client Stage"


# --- 3. Creation Awakening fires SET_MUSIC_STATE{wonder} via a deterministic Resolve, no LLM tool ---


async def test_creation_awakening_emits_wonder_resolve() -> None:
    room = make_mock_room()

    await push_creation_music("wonder", room, None)

    music_events = [p for p in published_payloads(room) if p["type"] == E.SET_MUSIC_STATE]
    assert len(music_events) == 1, f"expected exactly one SET_MUSIC_STATE, got {published_payloads(room)}"
    assert music_events[0]["music_state"] == "wonder"


# --- 4. Combat/spell SFX still emit PLAY_SOUND -- no regression from the story-003 teardown ---


async def test_spell_cast_still_emits_play_sound(reset_db_pool: str) -> None:
    pool = await db.get_pool()
    caster_id = f"cap_m27_{_CANTRIP_ID}"
    await _seed_player(pool, caster_id)
    await spells.load_spells()
    spell = spells.get_spell(_CANTRIP_ID)

    ctx = make_context(player_id=caster_id, room=make_mock_room())
    await _cast_spell_impl(ctx, _CANTRIP_ID)

    play_sounds = [p for p in published_payloads(ctx.userdata.room) if p["type"] == E.PLAY_SOUND]
    assert len(play_sounds) == 1, (
        f"expected exactly one PLAY_SOUND, got types {[p['type'] for p in published_payloads(ctx.userdata.room)]}"
    )
    assert play_sounds[0]["sound_name"] == spell.sound_id
    assert play_sounds[0]["sound_name"] in spells.SPELL_SOUND_KEYS
