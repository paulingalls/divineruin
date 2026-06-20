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


_LOCATIONS = {
    "battlefield_danger": {"region": "r1", "danger_level": 3},
    "camp_r1": {"region": "r1", "settlement_tier": "village", "danger_level": 1},
    "accord_market_square": {"region": "r9", "settlement_tier": "city", "danger_level": 0, "tags": ["starting_area"]},
}

_ATTRS = {
    "strength": 14,
    "dexterity": 12,
    "constitution": 13,
    "intelligence": 10,
    "wisdom": 11,
    "charisma": 8,
}


def _dying_player(conditions: list[dict]):
    return {
        "player_id": "p1",
        "class": "warrior",
        "attributes": dict(_ATTRS),
        "level": 5,
        "hp": {"current": 0, "max": 60},
        "maxhp_override": 0,
        "location_id": "battlefield_danger",
        "conditions": conditions,
    }


def _death_mocks(death_count_before=0):
    death_mut = AsyncMock()
    death_mut.read_death_history = AsyncMock(return_value={"count": death_count_before, "costs": []})
    death_mut.record_death = AsyncMock()
    res_mut = AsyncMock()  # apply_attribute_penalty / apply_maxhp_override_delta / revive_player / set_hollow_killed
    cond_mut = AsyncMock()  # save_player_conditions
    return death_mut, res_mut, cond_mut


class TestHollowedOnDeathBranch:
    """trigger_character_death marks + clears Hollowed when the dying character is Hollowed."""

    @pytest.mark.asyncio
    async def test_hollowed_death_sets_flag_and_clears_condition(self):
        import conditions
        from resurrection import trigger_character_death

        death_mut, res_mut, cond_mut = _death_mocks()
        player = _dying_player(conditions.apply_condition([], "hollowed"))  # stage 1
        ctx = await trigger_character_death(
            player,
            _LOCATIONS,
            combat_cleared=False,
            death_mutations=death_mut,
            mutations=res_mut,
            conditions_mutations=cond_mut,
            conn=object(),
        )
        res_mut.set_hollow_killed.assert_awaited_once()
        assert res_mut.set_hollow_killed.call_args.args[0] == "p1"
        # Hollowed stripped from the persisted conditions.
        saved = cond_mut.save_player_conditions.call_args
        assert saved.args[0] == "p1"
        assert all(c["type"] != "hollowed" for c in saved.args[1])
        assert ctx["hollow_killed"] is True and ctx["hollowed_cleared"] is True

    @pytest.mark.asyncio
    async def test_hollowed_death_at_stage_two_also_marks(self):
        import resurrection

        death_mut, res_mut, cond_mut = _death_mocks()
        player = _dying_player([{"type": "hollowed", "duration": None, "source": "veil", "stage": 2}])
        ctx = await resurrection.trigger_character_death(
            player,
            _LOCATIONS,
            combat_cleared=False,
            death_mutations=death_mut,
            mutations=res_mut,
            conditions_mutations=cond_mut,
            conn=object(),
        )
        res_mut.set_hollow_killed.assert_awaited_once()
        assert ctx["hollow_killed"] is True

    @pytest.mark.asyncio
    async def test_non_hollowed_death_does_not_mark_or_clear(self):
        import conditions
        from resurrection import trigger_character_death

        death_mut, res_mut, cond_mut = _death_mocks()
        player = _dying_player(conditions.apply_condition([], "exhausted"))  # not hollowed
        ctx = await trigger_character_death(
            player,
            _LOCATIONS,
            combat_cleared=False,
            death_mutations=death_mut,
            mutations=res_mut,
            conditions_mutations=cond_mut,
            conn=object(),
        )
        res_mut.set_hollow_killed.assert_not_awaited()
        cond_mut.save_player_conditions.assert_not_awaited()
        assert ctx.get("hollow_killed") is False and ctx.get("hollowed_cleared") is False


class TestHollowedDeathE2E:
    """Real-PG (dev DB) capstone for the resurrection/spell path: a Hollowed death persists
    hollow_killed, clears the Hollowed condition, and a subsequent Revivify is refused."""

    @pytest.mark.asyncio
    async def test_hollowed_death_persists_flag_clears_condition_refuses_revivify(self, dev_db_pool):
        import db_mutations_conditions
        import db_mutations_resurrection
        import db_queries
        from resurrection import trigger_character_death

        pool = dev_db_pool
        pid = "s007_e2e_hollow"
        data = {
            "player_id": pid,
            "class": "warrior",
            "attributes": dict(_ATTRS),
            "level": 5,
            "hp": {"current": 0, "max": 60},
            "maxhp_override": 0,
            "location_id": "battlefield_danger",
            "conditions": [{"type": "hollowed", "duration": None, "source": "veil", "stage": 2}],
        }
        await pool.execute("DELETE FROM players WHERE player_id = $1", pid)
        await pool.execute("INSERT INTO players (player_id, data) VALUES ($1, $2::jsonb)", pid, json.dumps(data))
        try:
            player = await db_queries.get_player(pid, conn=pool)
            assert player is not None
            ctx = await trigger_character_death(player, _LOCATIONS, combat_cleared=False, conn=pool)
            assert ctx["hollow_killed"] is True and ctx["hollowed_cleared"] is True

            # Persisted on the real row: flag set, Hollowed stripped from the stored conditions.
            assert await db_mutations_resurrection.read_hollow_killed(pid, conn=pool) is True
            stored = await db_mutations_conditions.read_player_conditions(pid, conn=pool)
            assert all(c["type"] != "hollowed" for c in stored)

            # A subsequent Revivify is refused — the gate reads the persisted hollow_killed on reload.
            reloaded = await db_queries.get_player(pid, conn=pool)
            assert reloaded is not None
            assert spell_casting.revivify_refused(reloaded) is True
        finally:
            await pool.execute("DELETE FROM players WHERE player_id = $1", pid)


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
