"""Persist across-encounter conditions onto players.data so subsequent out-of-combat checks see them."""

import json
from unittest.mock import AsyncMock, MagicMock

from _combat_end_fixtures import combat_end_mutations, combat_end_queries
from combat._helpers import _make_combat_state

import db_mutations_conditions
import db_queries
from check_resolution import resolve_skill_check
from combat_end import _end_combat_db
from combat_events import EventSink
from combat_packet import _resolve_tick_saves
from conditions import apply_condition
from session_data import SessionData


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

        plain = resolve_skill_check(
            {"attributes": {"strength": 14}, "level": 5},
            "athletics",
            "moderate",
            ally_present=False,
            hearing_only=False,
        )
        tired = resolve_skill_check(player, "athletics", "moderate", ally_present=False, hearing_only=False)
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


def test_tick_save_expands_abbreviated_save_type_for_real_resolver():
    import check_resolution_save

    state = _make_combat_state()
    player = state.get_participant("player_1")
    assert player is not None
    player.attributes = {"wisdom": 14}
    player.conditions = apply_condition([], "frightened", source="wraith")
    due = [{"actor_id": "player_1", "type": "frightened", "save": "wis", "source": "wraith"}]

    _resolve_tick_saves(state, due, check_resolution_save)
    assert [c["type"] for c in player.conditions] in ([], ["frightened"])


def _end_combat_mocks():
    session = SessionData(player_id="player_1", location_id="accord_guild_hall", room=None)
    mutations = combat_end_mutations()
    queries = combat_end_queries()
    return session, mutations, queries


async def test_end_combat_merges_acquired_cross_encounter_conditions(monkeypatch):
    cs = _make_combat_state(enemy_fallen=True)
    player = cs.get_participant("player_1")
    assert player is not None
    player.conditions = apply_condition(apply_condition([], "exhausted"), "prone")  # exhausted persists, prone doesn't

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

    assert sorted(c["type"] for c in captured["conditions"]) == ["exhausted", "wounded"]


async def test_end_combat_keeps_higher_stacks_on_type_conflict(monkeypatch):
    cs = _make_combat_state(enemy_fallen=True)
    player = cs.get_participant("player_1")
    assert player is not None
    exhausted_3 = apply_condition(apply_condition(apply_condition([], "exhausted"), "exhausted"), "exhausted")
    player.conditions = exhausted_3

    exhausted_2 = apply_condition(apply_condition([], "exhausted"), "exhausted")
    monkeypatch.setattr(db_mutations_conditions, "read_player_conditions", AsyncMock(return_value=exhausted_2))
    captured = {}

    async def _capture(player_id, conds, *, conn=None):
        captured["conditions"] = conds

    monkeypatch.setattr(db_mutations_conditions, "save_player_conditions", _capture)

    session, mutations, queries = _end_combat_mocks()
    await _end_combat_db(
        session, cs, "victory", mutations=mutations, queries=queries, conn=MagicMock(), sink=EventSink()
    )

    stored = captured["conditions"]
    assert len(stored) == 1
    assert stored[0]["type"] == "exhausted"
    assert stored[0]["stacks"] == 3  # higher accrual kept, not the store's 2


async def test_end_combat_skips_store_when_no_persistent_conditions_acquired(monkeypatch):
    cs = _make_combat_state(enemy_fallen=True)
    player = cs.get_participant("player_1")
    assert player is not None
    player.conditions = apply_condition([], "prone")  # phase-scoped only — nothing to persist

    save_spy = AsyncMock()
    monkeypatch.setattr(db_mutations_conditions, "save_player_conditions", save_spy)
    monkeypatch.setattr(db_mutations_conditions, "read_player_conditions", AsyncMock(return_value=[]))

    session, mutations, queries = _end_combat_mocks()
    await _end_combat_db(
        session, cs, "victory", mutations=mutations, queries=queries, conn=MagicMock(), sink=EventSink()
    )

    save_spy.assert_not_awaited()  # nothing acquired, no buff change -> reconciled == store -> no write


def _capture_save(monkeypatch) -> dict:
    """Patch save_player_conditions to record what combat-end writes back, returning the capture dict."""
    captured: dict = {}

    async def _capture(player_id, conds, *, conn=None):
        captured["conditions"] = conds

    monkeypatch.setattr(db_mutations_conditions, "save_player_conditions", _capture)
    return captured


async def test_end_combat_drops_ooc_buff_consumed_in_combat(monkeypatch):
    cs = _make_combat_state(enemy_fallen=True)
    player = cs.get_participant("player_1")
    assert player is not None
    player.conditions = []  # blessed was consumed during the fight -> gone from the participant

    monkeypatch.setattr(
        db_mutations_conditions, "read_player_conditions", AsyncMock(return_value=apply_condition([], "blessed"))
    )
    captured = _capture_save(monkeypatch)

    session, mutations, queries = _end_combat_mocks()
    await _end_combat_db(
        session, cs, "victory", mutations=mutations, queries=queries, conn=MagicMock(), sink=EventSink()
    )

    assert captured["conditions"] == []  # the spent blessed no longer rides players.data


async def test_end_combat_keeps_unconsumed_ooc_buff_without_spurious_write(monkeypatch):
    cs = _make_combat_state(enemy_fallen=True)
    player = cs.get_participant("player_1")
    assert player is not None
    player.conditions = apply_condition([], "blessed")  # still Blessed at combat end (unspent)

    monkeypatch.setattr(
        db_mutations_conditions, "read_player_conditions", AsyncMock(return_value=apply_condition([], "blessed"))
    )
    save_spy = AsyncMock()
    monkeypatch.setattr(db_mutations_conditions, "save_player_conditions", save_spy)

    session, mutations, queries = _end_combat_mocks()
    await _end_combat_db(
        session, cs, "victory", mutations=mutations, queries=queries, conn=MagicMock(), sink=EventSink()
    )

    save_spy.assert_not_awaited()  # store already matches -> no churn


async def test_end_combat_persists_in_combat_granted_buff(monkeypatch):
    cs = _make_combat_state(enemy_fallen=True)
    player = cs.get_participant("player_1")
    assert player is not None
    player.conditions = apply_condition([], "inspired")  # granted during the fight, unspent

    monkeypatch.setattr(db_mutations_conditions, "read_player_conditions", AsyncMock(return_value=[]))
    captured = _capture_save(monkeypatch)

    session, mutations, queries = _end_combat_mocks()
    await _end_combat_db(
        session, cs, "victory", mutations=mutations, queries=queries, conn=MagicMock(), sink=EventSink()
    )

    assert [c["type"] for c in captured["conditions"]] == ["inspired"]


async def test_end_combat_drops_consumed_buff_but_keeps_acquired_persistent(monkeypatch):
    cs = _make_combat_state(enemy_fallen=True)
    player = cs.get_participant("player_1")
    assert player is not None
    player.conditions = apply_condition([], "wounded")  # gained Wounded; Blessed was spent (absent)

    monkeypatch.setattr(
        db_mutations_conditions, "read_player_conditions", AsyncMock(return_value=apply_condition([], "blessed"))
    )
    captured = _capture_save(monkeypatch)

    session, mutations, queries = _end_combat_mocks()
    await _end_combat_db(
        session, cs, "victory", mutations=mutations, queries=queries, conn=MagicMock(), sink=EventSink()
    )

    assert sorted(c["type"] for c in captured["conditions"]) == ["wounded"]
