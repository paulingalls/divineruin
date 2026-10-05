"""Only revival fetches and validates a target row; other explicit targets may name objects or areas."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from livekit.agents.llm import ToolError
from sample_fixtures import make_context, make_db_mod

import character_spells
import spell_casting
from spells import Spell, SpellSource


def _spell(spell_id: str, *, source: SpellSource = "arcane") -> Spell:
    """A free (focus 0) spell carrying the given id so the cast resolves past the focus gate with
    generated resonance 0 (resonance_by_source[source]=0) — only the target_id plumbing + the
    Revivify gate's spell_id branch matter here."""
    return Spell(
        verbal=True,
        hostile=True,
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
    player_id -> row for the fetch side_effects (defaults to just the caster). Returns the parsed
    packet plus the queries mock for call assertions; raises ToolError on a gate. story-008: the
    caster row now comes from the id-ordered get_players_for_update batch; the revival gate still
    reads the TARGET via get_player."""
    ctx = make_context(player_id=caster["player_id"])
    mock_db, _conn = make_db_mod()
    table = {caster["player_id"]: caster, **(rows or {})}

    async def _get_player(pid, *, conn=None, for_update=False):
        return table.get(pid)

    async def _get_players_for_update(pids, *, conn=None):
        return {pid: table[pid] for pid in pids if pid in table}

    queries = MagicMock(
        get_player=AsyncMock(side_effect=_get_player),
        get_players_for_update=AsyncMock(side_effect=_get_players_for_update),
    )
    persistence = MagicMock(update_player_resources=AsyncMock())
    mutations = MagicMock(update_player_resonance=AsyncMock())
    events = MagicMock(publish_resonance_changed=AsyncMock())
    spells_mod = MagicMock(get_spell=MagicMock(return_value=spell))
    library = MagicMock(get_known=AsyncMock(return_value=[{"spell_id": spell.id}]))
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
        character_spells_mod=library,
    )
    return json.loads(raw), queries


class TestSelfTargetDefault:
    @pytest.mark.asyncio
    async def test_no_target_id_self_targets_single_fetch(self):
        packet, queries = await _cast(_spell("arcane_bolt"), caster=_player())
        assert packet  # resolved
        assert "target_id" not in packet  # self-cast packet shape unchanged (additive only when set)
        assert list(queries.get_players_for_update.await_args.args[0]) == ["caster_1"]
        queries.get_player.assert_not_called()


class TestTargetedNonRevival:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("target_id", ["ally_2", "altar_object", "blast_area_a3"])
    async def test_packet_carries_target_id_no_target_fetch(self, target_id):
        packet, queries = await _cast(_spell("arcane_bolt"), caster=_player(), target_id=target_id)
        assert packet["target_id"] == target_id
        queries.get_player.assert_not_called()


class TestTargetIdValidation:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("bad_target", ["bad id!", "drop;table", "a.b", ""])
    async def test_invalid_target_id_rejected(self, bad_target):
        with pytest.raises(ToolError, match="Invalid target_id"):
            await _cast(_spell("arcane_bolt"), caster=_player(), target_id=bad_target)

    @pytest.mark.asyncio
    async def test_object_and_area_ids_accepted(self):
        for tid in ("altar_object", "blast_area_a3", "goblin-1"):
            packet, _gp = await _cast(_spell("arcane_bolt"), caster=_player(), target_id=tid)
            assert packet["target_id"] == tid


def _revival(spell_id: str = "divine_revivify") -> Spell:
    """A free divine revival spell whose id is in REVIVAL_SPELL_IDS, so the Hollow-killed gate fires."""
    return _spell(spell_id, source="divine")


class TestRevivifyGateKeysOnTarget:
    @pytest.mark.asyncio
    async def test_refused_when_target_hollow_killed_caster_living(self):
        corpse = _player("corpse_9", hollow_killed=True)
        with pytest.raises(ToolError, match="Hollow-killed"):
            await _cast(
                _revival(), caster=_player(hollow_killed=False), target_id="corpse_9", rows={"corpse_9": corpse}
            )

    @pytest.mark.asyncio
    async def test_allowed_when_target_living_caster_hollow_killed(self):
        ally = _player("ally_3", hollow_killed=False)
        packet, _gp = await _cast(
            _revival(), caster=_player(hollow_killed=True), target_id="ally_3", rows={"ally_3": ally}
        )
        assert packet["target_id"] == "ally_3"

    @pytest.mark.asyncio
    async def test_unknown_target_raises(self):
        with pytest.raises(ToolError, match="Unknown target"):
            await _cast(_revival(), caster=_player(), target_id="ghost_x")

    @pytest.mark.asyncio
    async def test_self_cast_revival_still_keys_on_caster(self):
        with pytest.raises(ToolError, match="Hollow-killed"):
            await _cast(_revival(), caster=_player(hollow_killed=True))

    @pytest.mark.asyncio
    async def test_explicit_self_target_id_keys_on_caster_no_second_fetch(self):
        # target_id == player_id: the `!= player_id` short-circuit keys the gate on the already-fetched
        # caster row (no target re-fetch), yet the packet still carries the explicit id for narration.
        packet, queries = await _cast(_revival(), caster=_player("caster_1"), target_id="caster_1")
        assert packet["target_id"] == "caster_1"
        # target_id == player_id: the gate reuses the already-locked caster row (no target re-fetch),
        # and story-008 locks the caster via the id-ordered batch — so get_player is never called.
        queries.get_player.assert_not_called()

    @pytest.mark.asyncio
    async def test_explicit_self_target_id_hollow_killed_refused(self):
        # Same equality short-circuit, refusing branch: a Hollow-killed caster targeting their own id
        # is still refused (the gate read the caster row, not a re-fetched target).
        with pytest.raises(ToolError, match="Hollow-killed"):
            await _cast(_revival(), caster=_player("caster_1", hollow_killed=True), target_id="caster_1")


class TestRevivifyTargetRerouteE2E:
    @pytest.mark.asyncio
    async def test_revival_refused_on_hollow_killed_target_allowed_on_living(self, dev_db_pool):
        from session_data import SessionData

        pool = dev_db_pool
        caster_id, corpse_id, ally_id = "m11_caster", "m11_corpse", "m11_ally"
        rows = {
            caster_id: {"player_id": caster_id, "class": "cleric", "level": 5, "focus": {"current": 10, "max": 10}},
            corpse_id: {"player_id": corpse_id, "class": "warrior", "level": 5, "hollow_killed": True},
            ally_id: {"player_id": ally_id, "class": "scout", "level": 4},
        }
        for pid, data in rows.items():
            await pool.execute("DELETE FROM players WHERE player_id = $1", pid)
            await pool.execute("INSERT INTO players (player_id, data) VALUES ($1, $2::jsonb)", pid, json.dumps(data))
        await character_spells.record_learned(caster_id, "divine_revivify", "discovery", conn=pool)
        spells_mod = MagicMock(get_spell=MagicMock(return_value=_revival()))
        session = SessionData(player_id=caster_id, location_id="accord_guild_hall", room=None)
        try:
            with pytest.raises(ToolError, match="Hollow-killed"):
                await spell_casting._resolve_cast(
                    session, "divine_revivify", conn=pool, target_id=corpse_id, spells_mod=spells_mod
                )
            result = await spell_casting._resolve_cast(
                session, "divine_revivify", conn=pool, target_id=ally_id, spells_mod=spells_mod
            )
            assert result.packet["target_id"] == ally_id
        finally:
            for pid in rows:
                await pool.execute("DELETE FROM players WHERE player_id = $1", pid)
