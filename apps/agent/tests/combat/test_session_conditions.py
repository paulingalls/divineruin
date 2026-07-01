"""Condition persistence + Beat-4 tick-save orchestration (M4.3, story-004).

In-combat conditions ride combat_instances.data via save_combat_state (free, story-002). This
suite covers the NEW work: (1) the Beat-4 save-to-clear resolution (combat_packet._resolve_tick_saves)
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
from combat_packet import _resolve_tick_saves
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


def test_tick_save_expands_abbreviated_save_type_for_real_resolver():
    """Regression: the catalog's tick_save is the abbreviation ("wis") but resolve_saving_throw
    only accepts full attribute names — the real resolver must not raise on the wrap's save event."""
    import check_resolution_save

    state = _make_combat_state()
    player = state.get_participant("player_1")
    assert player is not None
    player.attributes = {"wisdom": 14}
    player.conditions = apply_condition([], "frightened", source="wraith")
    due = [{"actor_id": "player_1", "type": "frightened", "save": "wis", "source": "wraith"}]

    # Must not raise ValueError("Unknown save type: 'wis'"); the condition either clears or persists.
    _resolve_tick_saves(state, due, check_resolution_save)
    assert [c["type"] for c in player.conditions] in ([], ["frightened"])


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


async def test_end_combat_keeps_higher_stacks_on_type_conflict(monkeypatch):
    """A fight that deepens an already-persisted Exhausted must keep the higher stack count,
    not silently drop the combat-gained accrual (code-review finding, bounded by debt 1e32d78449ef)."""
    cs = _make_combat_state(enemy_fallen=True)
    player = cs.get_participant("player_1")
    assert player is not None
    # Combat ends with Exhausted at 3 stacks.
    exhausted_3 = apply_condition(apply_condition(apply_condition([], "exhausted"), "exhausted"), "exhausted")
    player.conditions = exhausted_3

    # The store already holds Exhausted at 2 stacks.
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


# --- Slice 4: combat-end reconciles OOC beneficial dice back to players.data (concern ab37d4fc61c6) ---


def _capture_save(monkeypatch) -> dict:
    """Patch save_player_conditions to record what combat-end writes back, returning the capture dict."""
    captured: dict = {}

    async def _capture(player_id, conds, *, conn=None):
        captured["conditions"] = conds

    monkeypatch.setattr(db_mutations_conditions, "save_player_conditions", _capture)
    return captured


async def test_end_combat_drops_ooc_buff_consumed_in_combat(monkeypatch):
    """A Blessed/Inspired die applied out of combat, loaded onto the participant at combat-start,
    and CONSUMED mid-fight must be removed from players.data at combat end — otherwise the player
    keeps a spent buff post-combat (concern ab37d4fc61c6). The participant's final set (no blessed)
    is authoritative because combat_init loaded the store's conditions in (M4.4 story-005)."""
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
    """A buff the player carried in and did NOT spend must survive combat — and, since the store
    already holds it, no redundant write fires (change-detected reconciliation)."""
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
    """A buff GRANTED mid-combat (e.g. a bard Inspires the player) that survives to combat end must
    persist onto players.data so the player keeps it out of combat — the participant's final set is
    authoritative in both directions (consume removes, grant adds)."""
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
    """Combined boundary: a spent Blessed is dropped while a fight-acquired Wounded persists —
    the two reconciliation paths compose without clobbering each other."""
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
