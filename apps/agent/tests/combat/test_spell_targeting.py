"""M11 story-001 — Generalized spell targeting.

cast_spell threads an explicit target_id (corpse/ally/object/area, broader than revival). For a
revival spell the Hollow-killed gate keys on the TARGET row, not the caster (closing the story-007
forward-wire). Non-revival targeted casts carry target_id into the packet for narration and do not
validate the target row (only Revivify branches on the target, assumption eabd919bf1ca).

Mock-conn units for the plumbing + gate reroute; one real-PG e2e (dev DB) proving the rerouted
refusal reads the targeted corpse's persisted hollow_killed.
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from sample_fixtures import make_context, make_db_mod

import spell_casting
from spells import Spell, SpellSource


def _spell(spell_id: str, *, source: SpellSource = "arcane") -> Spell:
    """A free (focus 0) spell carrying the given id so the cast resolves past the focus gate with
    generated resonance 0 (resonance_by_source[source]=0) — only the target_id plumbing + the
    Revivify gate's spell_id branch matter here."""
    return Spell(
        id=spell_id,
        name=spell_id.replace("_", " ").title(),
        source=source,
        spell_tier="standard",
        focus_cost=0,
        mechanics="A test spell.",
        narration_cue="A cue.",
        audio_cue="SFX-TST",
        resonance_by_source={source: 0},
        terrain_effects={},
        concentration=False,
    )


def _player(player_id: str = "caster_1", *, hollow_killed: bool = False) -> dict:
    return {
        "player_id": player_id,
        "name": "Caster",
        "class": "mage",
        "level": 5,
        "focus": {"current": 10, "max": 10},
        "hollow_killed": hollow_killed,
    }


async def _cast(spell: Spell, *, caster: dict, target_id: str | None = None, rows: dict | None = None):
    """Drive _cast_spell_impl for caster `caster`, optionally targeting target_id. `rows` maps
    player_id -> row for the get_player side_effect (defaults to just the caster). Returns the
    parsed packet plus the get_player mock for call-count assertions; raises ToolError on a gate."""
    ctx = make_context(player_id=caster["player_id"])
    mock_db, _conn = make_db_mod()
    table = {caster["player_id"]: caster, **(rows or {})}

    async def _get_player(pid, *, conn=None, for_update=False):
        return table.get(pid)

    queries = MagicMock(get_player=AsyncMock(side_effect=_get_player))
    persistence = MagicMock(update_player_resources=AsyncMock())
    mutations = MagicMock(update_player_resonance=AsyncMock())
    events = MagicMock(publish_resonance_changed=AsyncMock())
    spells_mod = MagicMock(get_spell=MagicMock(return_value=spell))
    raw = await spell_casting._cast_spell_impl(
        ctx,
        spell.id,
        target_id=target_id,
        db_mod=mock_db,
        queries_mod=queries,
        persistence_mod=persistence,
        resonance_mutations_mod=mutations,
        resonance_events_mod=events,
        spells_mod=spells_mod,
    )
    return json.loads(raw), queries.get_player


class TestSelfTargetDefault:
    """target_id=None preserves today's self-target cast exactly."""

    @pytest.mark.asyncio
    async def test_no_target_id_self_targets_single_fetch(self):
        packet, get_player = await _cast(_spell("arcane_bolt"), caster=_player())
        assert packet  # resolved
        assert "target_id" not in packet  # self-cast packet shape unchanged (additive only when set)
        assert get_player.await_count == 1  # caster only, no target fetch


class TestTargetedNonRevival:
    """A non-revival targeted cast carries target_id into the packet and does NOT fetch the target
    (covers ally/object/area — mechanically identical plumbing; concern 4683646b034a)."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("target_id", ["ally_2", "altar_object", "blast_area_a3"])
    async def test_packet_carries_target_id_no_target_fetch(self, target_id):
        packet, get_player = await _cast(_spell("arcane_bolt"), caster=_player(), target_id=target_id)
        assert packet["target_id"] == target_id
        assert get_player.await_count == 1  # only the caster — non-revival never validates the target
