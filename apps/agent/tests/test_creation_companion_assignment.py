"""Tests for companion assignment at character creation (story-003).

The companion stack (profiles, scaling, 5 relationship tiers, affinity, errands, combat)
was fully built but DARK for a new character: nothing created the first
`companion_relationships` row. finalize_character now binds the one companion whose
`complements` lists the character's archetype, mirroring the M8 starting-spell grant —
after the player is persisted, non-fatal, logged.

Covers the non-overwriting writer (unit + real-PG), and the finalize_character hook.
The archetype -> companion selection itself is owned by tests/test_companion_profiles.py.
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import db_mutations_companion
from companion_relationship import tier_rank_for_session_count
from creation_tools import finalize_character
from db_mutations_companion import insert_companion_relationship_if_absent
from session_data import CreationState, SessionData

_finalize: Any = finalize_character._func


# --- the non-overwriting writer -----------------------------------------------


class _RecordingConn:
    """Captures the statement + args instead of executing them."""

    def __init__(self, returns=None):
        self.sql = ""
        self.args: tuple = ()
        self._returns = returns

    async def fetchval(self, sql, *args):
        self.sql = sql
        self.args = args
        return self._returns


class TestInsertIfAbsent:
    async def test_statement_is_do_nothing_never_do_update(self):
        # The card-review point: the existing upsert_companion_relationship is
        # DO UPDATE SET relationship_tier, session_count, affinity — it OVERWRITES, which is
        # exactly what AC3 forbids. This writer must not become that.
        conn: Any = _RecordingConn(returns="p1")
        await insert_companion_relationship_if_absent("p1", "companion_kael", conn=conn)
        assert "ON CONFLICT (player_id, companion_id) DO NOTHING" in conn.sql
        assert "DO UPDATE" not in conn.sql

    async def test_inserts_the_new_tier_defaults(self):
        conn: Any = _RecordingConn(returns="p1")
        await insert_companion_relationship_if_absent("p1", "companion_kael", conn=conn)
        assert conn.args == ("p1", "companion_kael", tier_rank_for_session_count(0), 0, 0)

    async def test_returns_true_on_insert_false_on_conflict(self):
        inserted: Any = _RecordingConn("p1")
        conflicted: Any = _RecordingConn(None)
        assert await insert_companion_relationship_if_absent("p1", "c", conn=inserted) is True
        assert await insert_companion_relationship_if_absent("p1", "c", conn=conflicted) is False


@pytest.mark.usefixtures("dev_db_pool")
class TestInsertIfAbsentAgainstPostgres:
    """The both-sides-real falsifier: a recorded SQL string proves nothing about what the
    table ends up holding. Single-table round-trip, so the fast lane per apps/agent/CLAUDE.md."""

    async def _row(self, pool, player_id):
        return await pool.fetchrow(
            "SELECT relationship_tier, session_count, affinity FROM companion_relationships "
            "WHERE player_id = $1 AND companion_id = $2",
            player_id,
            "companion_kael",
        )

    async def test_fresh_grant_creates_a_new_tier_row(self, dev_db_pool):
        player_id = "test_story003_fresh"
        await dev_db_pool.execute("DELETE FROM companion_relationships WHERE player_id = $1", player_id)
        try:
            assert await insert_companion_relationship_if_absent(player_id, "companion_kael") is True
            row = await self._row(dev_db_pool, player_id)
            assert (row["relationship_tier"], row["session_count"], row["affinity"]) == (1, 0, 0)
        finally:
            await dev_db_pool.execute("DELETE FROM companion_relationships WHERE player_id = $1", player_id)

    async def test_regrant_does_not_reset_an_accumulated_relationship(self, dev_db_pool):
        # AC3 fault injection: seed a genuinely accumulated relationship, re-run the grant.
        # Swap this writer for upsert_companion_relationship and both values reset to 0.
        player_id = "test_story003_accumulated"
        await dev_db_pool.execute("DELETE FROM companion_relationships WHERE player_id = $1", player_id)
        try:
            await dev_db_pool.execute(
                "INSERT INTO companion_relationships "
                "(player_id, companion_id, relationship_tier, session_count, affinity) "
                "VALUES ($1, 'companion_kael', 4, 12, 7)",
                player_id,
            )
            regranted = await insert_companion_relationship_if_absent(player_id, "companion_kael")
            row = await self._row(dev_db_pool, player_id)
            assert (row["relationship_tier"], row["session_count"], row["affinity"]) == (4, 12, 7)
            assert regranted is False
            count = await dev_db_pool.fetchval(
                "SELECT count(*) FROM companion_relationships WHERE player_id = $1", player_id
            )
            assert count == 1
        finally:
            await dev_db_pool.execute("DELETE FROM companion_relationships WHERE player_id = $1", player_id)


# --- the finalize_character hook ----------------------------------------------


def _state(class_choice: str) -> CreationState:
    return CreationState(
        phase="identity",
        race="human",
        class_choice=class_choice,
        deity=None,
        name="Aric",
        backstory="Seeker of truth.",
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


class TestFinalizeAssignsCompanion:
    @pytest.mark.parametrize(
        "class_choice,companion_id",
        [
            ("mage", "companion_kael"),
            ("warrior", "companion_lira"),
            ("cleric", "companion_tam"),
            ("spy", "companion_sable"),
        ],
    )
    @patch("creation_tools.db_mutations_companion.insert_companion_relationship_if_absent", new_callable=AsyncMock)
    @patch("creation_tools.db_session_queries.get_session_init_payload", new_callable=AsyncMock)
    @patch("creation_tools.db_mutations.create_player", new_callable=AsyncMock)
    async def test_each_companion_is_reachable(self, _create, payload, grant, class_choice, companion_id):
        payload.return_value = _PAYLOAD
        await _finalize(_ctx(_state(class_choice)))
        grant.assert_awaited_once_with("test_player", companion_id)

    @patch(
        "creation_tools.db_mutations_companion.insert_companion_relationship_if_absent",
        new_callable=AsyncMock,
        side_effect=Exception("DB hiccup"),
    )
    @patch("creation_tools.db_session_queries.get_session_init_payload", new_callable=AsyncMock)
    @patch("creation_tools.db_mutations.create_player", new_callable=AsyncMock)
    async def test_grant_failure_does_not_strand_a_created_character(self, _create, payload, grant):
        # The player row is already persisted; a grant hiccup must not fail creation.
        payload.return_value = _PAYLOAD
        cs = _state("mage")
        await _finalize(_ctx(cs))
        grant.assert_awaited_once()
        assert cs.phase == "complete"

    @patch("creation_tools.db_session_queries.get_session_init_payload", new_callable=AsyncMock)
    @patch("creation_tools.db_mutations.create_player", new_callable=AsyncMock)
    async def test_grant_uses_the_non_overwriting_writer(self, _create, payload):
        # Pin the seam by identity: reaching for upsert_companion_relationship here would
        # reset an existing tier/affinity (AC3), and no mock-based assertion above would notice.
        payload.return_value = _PAYLOAD
        with patch.object(db_mutations_companion, "upsert_companion_relationship", new_callable=AsyncMock) as upsert:
            with patch.object(
                db_mutations_companion, "insert_companion_relationship_if_absent", new_callable=AsyncMock
            ) as insert:
                await _finalize(_ctx(_state("mage")))
        insert.assert_awaited_once()
        upsert.assert_not_awaited()


@pytest.mark.usefixtures("dev_db_pool")
class TestUnmockedFinalizeWritesNothing:
    """The grant is wrapped in a broad `except Exception`, so an UNMOCKED test does not fail —
    it silently performs real I/O into the shared dev DB. The stub is therefore global autouse
    in tests/conftest.py, not a per-module opt-in a new module can forget."""

    @patch("creation_tools.db_session_queries.get_session_init_payload", new_callable=AsyncMock)
    @patch("creation_tools.db_mutations.create_player", new_callable=AsyncMock)
    async def test_finalize_without_a_grant_patch_leaves_the_dev_db_untouched(self, _create, payload, dev_db_pool):
        # Deliberately patches NOTHING on the grant path — that is the whole point. Narrowing
        # stub_creation_companion_grant back to an opt-in fixture reds this with a stray row.
        payload.return_value = _PAYLOAD
        player_id = "test_story003_unmocked"
        await dev_db_pool.execute("DELETE FROM companion_relationships WHERE player_id = $1", player_id)
        try:
            ctx = MagicMock()
            ctx.userdata = SessionData(player_id=player_id, location_id="", room=None, creation_state=_state("mage"))
            await _finalize(ctx)
            count = await dev_db_pool.fetchval(
                "SELECT count(*) FROM companion_relationships WHERE player_id = $1", player_id
            )
            assert count == 0
        finally:
            await dev_db_pool.execute("DELETE FROM companion_relationships WHERE player_id = $1", player_id)
