"""Condition persistence + Beat-4 tick-save orchestration (M4.3, story-004).

In-combat conditions ride combat_instances.data via save_combat_state (free, story-002). This
suite covers the NEW work: (1) the Beat-4 save-to-clear resolution (combat_turn._resolve_tick_saves)
that clears Frightened on a made save; (2) cross-encounter persistence — combat_end writes the
player's persists_across_encounters conditions to players.data, and the round-trip is readable via
db_queries.get_player so out-of-combat checks (story-003 resolvers) apply them.

Real-PG tests use the shared dev DB (dev_db_pool fixture, tests/combat/conftest.py) with a unique
player id + cleanup, per the fast-lane real-PG convention.
"""

import json
from unittest.mock import AsyncMock, MagicMock

from combat._helpers import _make_combat_state

import db_mutations_conditions
import db_queries
from check_resolution import resolve_skill_check
from combat_end import _end_combat_db
from combat_events import EventSink
from combat_turn import _resolve_tick_saves
from conditions import apply_condition
from session_data import SessionData

# --- Slices 1 + 5: persistence round-trip (real dev DB) ---


async def _seed_player(pool, player_id: str) -> None:
    await pool.execute(
        "INSERT INTO players (player_id, data) VALUES ($1, $2::jsonb) "
        "ON CONFLICT (player_id) DO UPDATE SET data = $2::jsonb",
        player_id,
        json.dumps({"player_id": player_id, "attributes": {"strength": 14}, "level": 5, "skill_tiers": {}}),
    )


async def test_save_then_get_player_roundtrips_conditions(dev_db_pool):
    pool = dev_db_pool
    player_id = "s004_roundtrip_player"
    await _seed_player(pool, player_id)
    try:
        exhausted = apply_condition([], "exhausted")
        await db_mutations_conditions.save_player_conditions(player_id, exhausted, conn=pool)

        player = await db_queries.get_player(player_id, conn=pool)
        assert player is not None
        assert player["conditions"] == exhausted

        # The persisted condition flows into an out-of-combat check via the get_player dict
        # (story-003 resolver reads player["conditions"]): Exhausted -1 lands on the modifier.
        plain = resolve_skill_check({"attributes": {"strength": 14}, "level": 5}, "athletics", "moderate")
        tired = resolve_skill_check(player, "athletics", "moderate")
        assert tired.modifier == plain.modifier - 1
    finally:
        await pool.execute("DELETE FROM players WHERE player_id = $1", player_id)


async def test_save_empty_clears_conditions(dev_db_pool):
    pool = dev_db_pool
    player_id = "s004_clear_player"
    await _seed_player(pool, player_id)
    try:
        await db_mutations_conditions.save_player_conditions(player_id, apply_condition([], "wounded"), conn=pool)
        await db_mutations_conditions.save_player_conditions(player_id, [], conn=pool)
        player = await db_queries.get_player(player_id, conn=pool)
        assert player is not None
        assert player["conditions"] == []
    finally:
        await pool.execute("DELETE FROM players WHERE player_id = $1", player_id)


# --- Slice 2: Beat-4 tick-save resolution (pure helper) ---


def _save_resolver(success: bool):
    resolver = MagicMock()
    resolver.resolve_saving_throw = MagicMock(return_value=MagicMock(success=success))
    return resolver


def test_tick_save_success_clears_condition():
    state = _make_combat_state()
    player = state.get_participant("player_1")
    assert player is not None
    player.conditions = apply_condition([], "frightened", source="wraith")
    due = [{"actor_id": "player_1", "type": "frightened", "save": "wis", "source": "wraith"}]

    _resolve_tick_saves(state, due, _save_resolver(success=True))
    assert player.conditions == []


def test_tick_save_failure_keeps_condition():
    state = _make_combat_state()
    player = state.get_participant("player_1")
    assert player is not None
    player.conditions = apply_condition([], "frightened", source="wraith")
    due = [{"actor_id": "player_1", "type": "frightened", "save": "wis", "source": "wraith"}]

    _resolve_tick_saves(state, due, _save_resolver(success=False))
    assert [c["type"] for c in player.conditions] == ["frightened"]


# --- Slice 3: combat-end persists only cross-encounter conditions ---


def _end_combat_mocks():
    session = SessionData(player_id="player_1", location_id="accord_guild_hall", room=None)
    mutations = MagicMock(delete_combat_state=AsyncMock())
    return session, mutations, MagicMock()


async def test_end_combat_merges_acquired_cross_encounter_conditions(monkeypatch):
    cs = _make_combat_state(enemy_fallen=True)
    player = cs.get_participant("player_1")
    assert player is not None
    player.conditions = apply_condition(apply_condition([], "exhausted"), "prone")  # exhausted persists, prone doesn't

    # A pre-combat Wounded already in the store must survive (combat only accrues; merge, not clobber).
    monkeypatch.setattr(
        db_mutations_conditions, "read_player_conditions", AsyncMock(return_value=apply_condition([], "wounded"))
    )
    captured = {}

    async def _capture(player_id, conds, *, conn=None):
        captured["conditions"] = conds

    monkeypatch.setattr(db_mutations_conditions, "save_player_conditions", _capture)

    session, mutations, queries = _end_combat_mocks()
    await _end_combat_db(
        session, cs, "victory", mutations=mutations, queries=queries, conn=MagicMock(), sink=EventSink()
    )

    # Wounded (pre-existing) kept; exhausted (acquired) added; prone (phase-scoped) dropped.
    assert sorted(c["type"] for c in captured["conditions"]) == ["exhausted", "wounded"]


async def test_end_combat_skips_store_when_no_persistent_conditions_acquired(monkeypatch):
    cs = _make_combat_state(enemy_fallen=True)
    player = cs.get_participant("player_1")
    assert player is not None
    player.conditions = apply_condition([], "prone")  # phase-scoped only — nothing to persist

    save_spy = AsyncMock()
    monkeypatch.setattr(db_mutations_conditions, "save_player_conditions", save_spy)
    monkeypatch.setattr(db_mutations_conditions, "read_player_conditions", AsyncMock())

    session, mutations, queries = _end_combat_mocks()
    await _end_combat_db(
        session, cs, "victory", mutations=mutations, queries=queries, conn=MagicMock(), sink=EventSink()
    )

    save_spy.assert_not_awaited()  # no persistent conditions acquired -> no DB write, store untouched
