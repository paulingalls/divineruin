"""Real-PG integration: _end_combat_db grants role-scaled loot + currency on victory (M4.7,
story-002). Proves the end-to-end victory path against the dev Postgres at :55432 (dev_db_pool):
a defeated enemy's loot table is rolled, items land in player_inventory, currency is added to
players.data.gold, and the CURRENCY_GAINED + ITEM_ACQUIRED chips are buffered into the sink.

A FakeRng pins the rolls so the grant is exact, and the loot table is injected via a content stub
(get_loot_table) plus a self-seeded test item row, so the test depends on neither the seeded
loot_tables catalog nor a specific items seed. Cleanup removes the player, its inventory, and the
test item in a finally (unique keys, mirroring the other fast-lane real-PG tests).
"""

from __future__ import annotations

import json
import random
from unittest.mock import AsyncMock, MagicMock

import pytest

import db
import db_mutations
import db_queries
import event_types as E
from combat_end import _end_combat_db
from combat_events import EventSink
from session_data import CombatParticipant, CombatState, SessionData

_PLAYER_ID = "s002_combat_end_loot_player"
_ITEM_ID = "s002_loot_test_residue"
_LOOT_TABLE_ID = "s002_loot_test_table"


class FakeRng(random.Random):
    """random.Random with a fixed per-die value and chance roll, so the loot/currency rolls are
    deterministic: every drop chance passes (random()=0.0) and each die reads ``die``."""

    def __init__(self, die: int = 4, chance: float = 0.0):
        super().__init__()
        self._die = die
        self._chance = chance

    def randint(self, a: int, b: int) -> int:
        return self._die

    def random(self) -> float:
        return self._chance


def _content_stub() -> MagicMock:
    """A db_content_queries stand-in whose get_loot_table returns one bespoke table for the known
    id. MagicMock (Any-typed) so it satisfies the injected ``content`` parameter."""

    async def _get(loot_table_id: str) -> dict | None:
        if loot_table_id == _LOOT_TABLE_ID:
            return {"id": _LOOT_TABLE_ID, "drops": [{"item_id": _ITEM_ID, "chance": 1.0, "quantity": 1}]}
        return None

    content = MagicMock()
    content.get_loot_table = AsyncMock(side_effect=_get)
    return content


async def _seed_player(pool, gold: int) -> None:
    await pool.execute(
        "INSERT INTO players (player_id, data) VALUES ($1, $2::jsonb) "
        "ON CONFLICT (player_id) DO UPDATE SET data = $2::jsonb",
        _PLAYER_ID,
        json.dumps({"player_id": _PLAYER_ID, "level": 3, "gold": gold}),
    )


async def _seed_item(pool) -> None:
    await pool.execute(
        "INSERT INTO items (id, data) VALUES ($1, $2::jsonb) ON CONFLICT (id) DO UPDATE SET data = $2::jsonb",
        _ITEM_ID,
        json.dumps({"id": _ITEM_ID, "name": "Test Residue", "type": "material"}),
    )


async def _cleanup(pool) -> None:
    await pool.execute("DELETE FROM player_inventory WHERE player_id = $1", _PLAYER_ID)
    await pool.execute("DELETE FROM players WHERE player_id = $1", _PLAYER_ID)
    await pool.execute("DELETE FROM items WHERE id = $1", _ITEM_ID)


def _victory_state() -> CombatState:
    """One defeated humanoid Standard enemy carrying the test loot table; level 3 -> tier 2."""
    enemy = CombatParticipant(
        id="s002_loot_enemy",
        name="Test Bandit",
        type="enemy",
        initiative=10,
        hp_current=0,
        hp_max=11,
        ac=12,
        level=3,
        xp_value=50,
        is_fallen=True,
        role="standard",
        category="humanoid",
        loot_table_id=_LOOT_TABLE_ID,
    )
    # The player who fought is a participant (as combat_init builds it) — loot/currency key on the
    # player participants, so a realistic victory state must include the primary.
    player = CombatParticipant(
        id=_PLAYER_ID, name="Loot Hero", type="player", initiative=15, hp_current=20, hp_max=20, ac=14
    )
    return CombatState(
        combat_id="s002_loot_combat", participants=[player, enemy], initiative_order=[_PLAYER_ID, enemy.id]
    )


@pytest.mark.asyncio
async def test_victory_grants_role_loot_and_currency(dev_db_pool):
    pool = dev_db_pool
    await _seed_player(pool, gold=5)
    await _seed_item(pool)
    try:
        session = SessionData(player_id=_PLAYER_ID, location_id="loc_test", room=None)
        cs = _victory_state()
        sink = EventSink()
        # die=4, tier=2, humanoid Standard -> 8 sp; converted at the grant boundary to gold
        # (silver_per_gold=10) -> 0.8 gp; loot drop guaranteed (chance 1.0).
        async with db.transaction() as conn:
            end_data = await _end_combat_db(
                session,
                cs,
                "victory",
                mutations=db_mutations,
                queries=db_queries,
                conn=conn,
                sink=sink,
                content=_content_stub(),
                rng=FakeRng(die=4),
            )

        # Currency converted sp -> gp and added to players.data.gold (5 + 0.8 = 5.8).
        player = await db_queries.get_player(_PLAYER_ID, conn=pool)
        assert player is not None and player["gold"] == pytest.approx(5.8)

        # Loot item granted into inventory at the rolled quantity.
        qty = await pool.fetchval(
            "SELECT (data->>'quantity')::int FROM player_inventory WHERE player_id = $1 AND item_id = $2",
            _PLAYER_ID,
            _ITEM_ID,
        )
        assert qty == 1

        # end_data surfaces the haul for the DM narration / response (in the canonical gold unit).
        assert end_data["currency_gold"] == pytest.approx(0.8)
        assert end_data["loot"] == [{"item_id": _ITEM_ID, "quantity": 1}]

        # A single CURRENCY_GAINED chip buffered for the whole haul, plus the ITEM_ACQUIRED chip.
        currency_events = [e for e in sink.captured if e.event_type == E.CURRENCY_GAINED]
        assert len(currency_events) == 1
        payload = currency_events[0].payload
        assert payload["amount"] == pytest.approx(0.8)
        assert payload["currency"] == "gold"
        assert payload["new_balance"] == pytest.approx(5.8)
        assert payload["player_id"] == _PLAYER_ID

        item_events = [e for e in sink.captured if e.event_type == E.ITEM_ACQUIRED]
        assert len(item_events) == 1
        assert item_events[0].payload == {"item_id": _ITEM_ID, "quantity": 1, "source": "combat_loot"}
    finally:
        await _cleanup(pool)


@pytest.mark.asyncio
async def test_minion_only_victory_grants_no_currency(dev_db_pool):
    pool = dev_db_pool
    await _seed_player(pool, gold=5)
    await _seed_item(pool)
    try:
        session = SessionData(player_id=_PLAYER_ID, location_id="loc_test", room=None)
        enemy = CombatParticipant(
            id="s002_minion",
            name="Test Minion",
            type="enemy",
            initiative=8,
            hp_current=0,
            hp_max=6,
            ac=10,
            level=1,
            xp_value=10,
            is_fallen=True,
            role="minion",
            category="humanoid",  # would carry coin at any other role, but D79 zeroes a Minion
            loot_table_id=_LOOT_TABLE_ID,
        )
        player = CombatParticipant(
            id=_PLAYER_ID, name="Loot Hero", type="player", initiative=15, hp_current=20, hp_max=20, ac=14
        )
        cs = CombatState(
            combat_id="s002_minion_combat", participants=[player, enemy], initiative_order=[_PLAYER_ID, enemy.id]
        )
        sink = EventSink()
        async with db.transaction() as conn:
            end_data = await _end_combat_db(
                session,
                cs,
                "victory",
                mutations=db_mutations,
                queries=db_queries,
                conn=conn,
                sink=sink,
                content=_content_stub(),
                rng=FakeRng(die=4),
            )

        # D79: no currency, gold untouched, no CURRENCY_GAINED chip.
        assert end_data["currency_gold"] == 0
        player = await db_queries.get_player(_PLAYER_ID, conn=pool)
        assert player is not None and player["gold"] == 5
        assert not [e for e in sink.captured if e.event_type == E.CURRENCY_GAINED]
    finally:
        await _cleanup(pool)
