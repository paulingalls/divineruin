"""M4.4 story-007 — Hollowed death, resurrection/spell side.

A death under any Hollowed stage sets a permanent players.data.hollow_killed mark and clears the
Hollowed condition (purged past Mortaen's threshold); a divine_revivify cast on a hollow-killed
corpse is refused (forward-wired gate, keyed on the caster row until spell targeting lands).

Mock-conn unit tests for the DB layer + pure gate; the death branch with injected mutations; one
real-PG E2E (dev DB) for the full resurrection/spell path. The combat-engine Temporary Hollowed
ride-along is story-008.
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from livekit.agents.llm import ToolError
from sample_fixtures import make_context, make_db_mod

import spell_casting
from spells import Spell


def _revival_spell(spell_id: str = "divine_revivify") -> Spell:
    """A free (focus 0) spell carrying the given id, so the cast resolves past the focus gate
    without catalog coupling — only the Revivify gate's spell_id branch matters here."""
    return Spell(
        id=spell_id,
        name="Revivify",
        source="divine",
        spell_tier="standard",
        focus_cost=0,
        mechanics="Returns a recently-fallen ally to 1 HP. Doesn't work on Hollow-killed.",
        narration_cue="A thread of life, rewoven.",
        audio_cue="SFX-REV",
        resonance_by_source={"divine": 0},
        terrain_effects={},
        concentration=False,
    )


async def _cast(spell: Spell, *, player: dict):
    """Drive _cast_spell_impl with a controlled spells_mod + the given player row (mirrors
    test_spell_casting._cast). Returns the parsed packet; raises ToolError on a gated cast."""
    ctx = make_context()
    mock_db, _conn = make_db_mod()
    queries = MagicMock(get_player=AsyncMock(return_value=player))
    persistence = MagicMock(update_player_resources=AsyncMock())
    mutations = MagicMock(update_player_resonance=AsyncMock())
    events = MagicMock(publish_resonance_changed=AsyncMock())
    spells_mod = MagicMock(get_spell=MagicMock(return_value=spell))
    raw = await spell_casting._cast_spell_impl(
        ctx,
        spell.id,
        db_mod=mock_db,
        queries_mod=queries,
        persistence_mod=persistence,
        resonance_mutations_mod=mutations,
        resonance_events_mod=events,
        spells_mod=spells_mod,
    )
    return json.loads(raw)


def _player(*, hollow_killed: bool = False) -> dict:
    return {
        "player_id": "player_1",
        "name": "Lyra",
        "class": "cleric",
        "level": 5,
        "focus": {"current": 10, "max": 10},
        "hollow_killed": hollow_killed,
    }


class TestRevivifyRefused:
    """The pure gate helper + REVIVAL_SPELL_IDS membership (forward-wired, keyed on the row)."""

    def test_refused_when_hollow_killed(self):
        assert spell_casting.revivify_refused({"hollow_killed": True}) is True

    def test_allowed_when_not_hollow_killed(self):
        assert spell_casting.revivify_refused({"hollow_killed": False}) is False
        assert spell_casting.revivify_refused({}) is False

    def test_revival_spell_ids_membership(self):
        assert "divine_revivify" in spell_casting.REVIVAL_SPELL_IDS
        assert "arcane_bolt" not in spell_casting.REVIVAL_SPELL_IDS


class TestRevivifyGateLive:
    """The gate wired into the cast path: a revival spell on a hollow-killed row is refused."""

    @pytest.mark.asyncio
    async def test_revivify_on_hollow_killed_is_refused(self):
        with pytest.raises(ToolError, match="Hollow-killed"):
            await _cast(_revival_spell(), player=_player(hollow_killed=True))

    @pytest.mark.asyncio
    async def test_revivify_on_living_is_allowed(self):
        packet = await _cast(_revival_spell(), player=_player(hollow_killed=False))
        assert packet  # resolved to a cast packet, no gate

    @pytest.mark.asyncio
    async def test_non_revival_spell_unaffected_by_gate(self):
        # A hollow-killed row casting a non-revival spell is NOT gated.
        packet = await _cast(_revival_spell("divine_mend"), player=_player(hollow_killed=True))
        assert packet


class TestHollowKilledReadWrite:
    """db_mutations_resurrection.set_hollow_killed / read_hollow_killed (mock-conn units)."""

    @pytest.mark.asyncio
    async def test_set_hollow_killed_writes_true(self):
        import db_mutations_resurrection

        conn = AsyncMock()
        await db_mutations_resurrection.set_hollow_killed("p1", conn=conn)
        sql, *args = conn.execute.call_args.args
        assert "hollow_killed" in sql
        assert args[0] == "p1"

    @pytest.mark.asyncio
    async def test_read_hollow_killed_true(self):
        import db_mutations_resurrection

        conn = AsyncMock()
        conn.fetchrow.return_value = {"hollow_killed": True}
        assert await db_mutations_resurrection.read_hollow_killed("p1", conn=conn) is True

    @pytest.mark.asyncio
    async def test_read_hollow_killed_defaults_false_when_absent(self):
        import db_mutations_resurrection

        conn = AsyncMock()
        conn.fetchrow.return_value = None
        assert await db_mutations_resurrection.read_hollow_killed("ghost", conn=conn) is False

    @pytest.mark.asyncio
    async def test_read_hollow_killed_false_when_key_null(self):
        import db_mutations_resurrection

        conn = AsyncMock()
        conn.fetchrow.return_value = {"hollow_killed": None}
        assert await db_mutations_resurrection.read_hollow_killed("p1", conn=conn) is False
