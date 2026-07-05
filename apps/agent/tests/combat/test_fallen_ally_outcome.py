"""Real-PG integration: handle savable fallen allies on deescalation/fled outcomes.

When combat ends with a deescalated or fled outcome, a savable fallen ally (is_fallen=True,
hp_current=0, NOT terminally down) was previously stranded at 0 HP with no recovery and no death.

New contract (sprint-start decision 498f0df12b14):
- deescalated: stabilize fallen allies to 1 HP (peaceful win, party holds the field)
- fled: fallen allies die → Mortaen (left behind, NOT stabilized)
- victory/defeat: unchanged regression guard

Mirrors test_combat_end_party_wipe.py for structure: seeds players via dev_db_pool,
calls _end_combat_db in a real transaction, and asserts the persisted outcome.
"""

from __future__ import annotations

import json

import pytest

import db
import db_mutations
import db_queries
from combat_end import _end_combat_db
from combat_events import EventSink
from session_data import CombatParticipant, CombatState, SessionData

_PRIMARY = "s003_fallen_ally_primary"
_ALLY = "s003_fallen_ally_ally"
_OFF_CATALOG = "off_catalog_wilds"  # region-less -> tier-1 + tier-2 skipped, falls to tier-3
_PRIMARY_ANCHOR = "millhaven"  # greyvale village (real seed)
_ALLY_ANCHOR = "accord_guild_hall"  # sunward_coast city (real seed)


async def _seed_player(pool, player_id: str, last_rested: str) -> None:
    """Seed a player row with 0 HP (fallen state)."""
    await pool.execute(
        "INSERT INTO players (player_id, data) VALUES ($1, $2::jsonb) "
        "ON CONFLICT (player_id) DO UPDATE SET data = $2::jsonb",
        player_id,
        json.dumps(
            {
                "player_id": player_id,
                "class": "warrior",
                "attributes": {"strength": 14, "charisma": 8, "constitution": 13},
                "level": 5,
                "hp": {"current": 0, "max": 40},
                "maxhp_override": 0,
                "location_id": _OFF_CATALOG,
                "last_rested_settlement_id": last_rested,
                "death_history": {"count": 0, "costs": []},
                "conditions": [],
            }
        ),
    )


async def _cleanup(pool, *player_ids: str) -> None:
    for pid in player_ids:
        await pool.execute("DELETE FROM players WHERE player_id = $1", pid)


def _savable_fallen_participant(player_id: str) -> CombatParticipant:
    """A savable fallen player: is_fallen=True, hp_current=0, NOT terminally down (death_save_failures < limit)."""
    return CombatParticipant(
        id=player_id,
        name=player_id,
        type="player",
        initiative=10,
        hp_current=0,
        hp_max=40,
        ac=14,
        attributes={"strength": 14, "charisma": 8, "constitution": 13},
        level=5,
        is_fallen=True,
        is_dead=False,
        death_save_failures=0,  # NOT terminally down
    )


def _enemy(is_fallen: bool = True) -> CombatParticipant:
    return CombatParticipant(
        id="s003_fallen_ally_enemy",
        name="Wisp",
        type="enemy",
        initiative=8,
        hp_current=0 if is_fallen else 5,
        hp_max=5,
        ac=10,
        is_fallen=is_fallen,
    )


def _combat_state(participants: list[CombatParticipant]) -> CombatState:
    return CombatState(
        combat_id="s003_fallen_ally_combat",
        participants=participants,
        initiative_order=[p.id for p in participants],
    )


async def _run_outcome(session: SessionData, cs: CombatState, outcome: str) -> dict:
    async with db.transaction() as conn:
        return await _end_combat_db(
            session, cs, outcome, mutations=db_mutations, queries=db_queries, conn=conn, sink=EventSink()
        )


@pytest.mark.asyncio
async def test_deescalated_stabilizes_savable_fallen_ally(dev_db_pool):
    """AC1: outcome='deescalated' with a savable fallen ally -> ally is stabilized to 1 HP."""
    pool = dev_db_pool
    await _seed_player(pool, _PRIMARY, _PRIMARY_ANCHOR)
    await _seed_player(pool, _ALLY, _ALLY_ANCHOR)
    try:
        session = SessionData(player_id=_PRIMARY, location_id=_OFF_CATALOG, room=None)
        cs = _combat_state(
            [
                _savable_fallen_participant(_PRIMARY),
                _savable_fallen_participant(_ALLY),
                _enemy(is_fallen=True),
            ]
        )

        await _run_outcome(session, cs, "deescalated")

        # Both fallen allies should be stabilized to 1 HP.
        primary = await db_queries.get_player(_PRIMARY, conn=pool)
        ally = await db_queries.get_player(_ALLY, conn=pool)
        assert primary is not None
        assert ally is not None
        assert primary["hp"]["current"] == 1, "Primary fallen ally should stabilize to 1 HP"
        assert ally["hp"]["current"] == 1, "Secondary fallen ally should stabilize to 1 HP"
        # No death should be recorded.
        assert primary["death_history"]["count"] == 0
        assert ally["death_history"]["count"] == 0
    finally:
        await _cleanup(pool, _PRIMARY, _ALLY)


@pytest.mark.asyncio
async def test_fled_kills_savable_fallen_ally(dev_db_pool):
    """AC2: outcome='fled' with a savable fallen ally -> ally dies and returns via Mortaen."""
    pool = dev_db_pool
    await _seed_player(pool, _PRIMARY, _PRIMARY_ANCHOR)
    await _seed_player(pool, _ALLY, _ALLY_ANCHOR)
    try:
        session = SessionData(player_id=_PRIMARY, location_id=_OFF_CATALOG, room=None)
        cs = _combat_state(
            [
                _savable_fallen_participant(_PRIMARY),
                _savable_fallen_participant(_ALLY),
                _enemy(is_fallen=True),
            ]
        )

        end_data = await _run_outcome(session, cs, "fled")

        # Both fallen allies should be resurrected (death recorded, moved to anchor).
        primary = await db_queries.get_player(_PRIMARY, conn=pool)
        ally = await db_queries.get_player(_ALLY, conn=pool)
        assert primary is not None
        assert ally is not None
        assert primary["location_id"] == _PRIMARY_ANCHOR, "Primary should be resurrected at anchor"
        assert ally["location_id"] == _ALLY_ANCHOR, "Ally should be resurrected at own anchor"
        assert primary["death_history"]["count"] == 1
        assert ally["death_history"]["count"] == 1
        # The returned death_context is the primary's.
        assert end_data["death_context"] is not None
        assert end_data["death_context"]["anchor"] == _PRIMARY_ANCHOR
    finally:
        await _cleanup(pool, _PRIMARY, _ALLY)


@pytest.mark.asyncio
async def test_fled_primary_standing_not_force_resurrected(dev_db_pool):
    """AC3: outcome='fled' with a standing primary (not fallen) -> primary is NOT force-resurrected.
    Only downed (fallen) allies die on a flee."""
    pool = dev_db_pool
    await _seed_player(pool, _PRIMARY, _PRIMARY_ANCHOR)
    await _seed_player(pool, _ALLY, _ALLY_ANCHOR)
    try:
        session = SessionData(player_id=_PRIMARY, location_id=_OFF_CATALOG, room=None)
        cs = _combat_state(
            [
                # Primary is standing (not fallen).
                CombatParticipant(
                    id=_PRIMARY,
                    name=_PRIMARY,
                    type="player",
                    initiative=10,
                    hp_current=25,  # alive
                    hp_max=40,
                    ac=14,
                    attributes={"strength": 14, "charisma": 8, "constitution": 13},
                    level=5,
                    is_fallen=False,
                    is_dead=False,
                ),
                # Ally is fallen.
                _savable_fallen_participant(_ALLY),
                _enemy(is_fallen=True),
            ]
        )

        end_data = await _run_outcome(session, cs, "fled")

        primary = await db_queries.get_player(_PRIMARY, conn=pool)
        ally = await db_queries.get_player(_ALLY, conn=pool)
        assert primary is not None
        assert ally is not None
        # Primary survived, NOT resurrected (location unchanged, no death recorded).
        assert primary["location_id"] == _OFF_CATALOG
        assert primary["death_history"]["count"] == 0
        # Ally fled while downed, so they die and are resurrected.
        assert ally["location_id"] == _ALLY_ANCHOR
        assert ally["death_history"]["count"] == 1
        # No death_context for the primary (it survived).
        assert end_data["death_context"] is None
    finally:
        await _cleanup(pool, _PRIMARY, _ALLY)


@pytest.mark.asyncio
async def test_victory_still_stabilizes_fallen_ally_regression(dev_db_pool):
    """AC4: outcome='victory' with a savable fallen ally -> unchanged behavior (stabilize to 1 HP)."""
    pool = dev_db_pool
    await _seed_player(pool, _PRIMARY, _PRIMARY_ANCHOR)
    await _seed_player(pool, _ALLY, _ALLY_ANCHOR)
    try:
        session = SessionData(player_id=_PRIMARY, location_id=_OFF_CATALOG, room=None)
        cs = _combat_state(
            [
                _savable_fallen_participant(_PRIMARY),
                _savable_fallen_participant(_ALLY),
                _enemy(is_fallen=True),
            ]
        )

        await _run_outcome(session, cs, "victory")

        primary = await db_queries.get_player(_PRIMARY, conn=pool)
        ally = await db_queries.get_player(_ALLY, conn=pool)
        assert primary is not None
        assert ally is not None
        assert primary["hp"]["current"] == 1
        assert ally["hp"]["current"] == 1
        # No death recorded on victory.
        assert primary["death_history"]["count"] == 0
        assert ally["death_history"]["count"] == 0
    finally:
        await _cleanup(pool, _PRIMARY, _ALLY)


@pytest.mark.asyncio
async def test_defeat_still_kills_fallen_ally_regression(dev_db_pool):
    """AC5: outcome='defeat' with a savable fallen ally -> unchanged behavior (die → Mortaen)."""
    pool = dev_db_pool
    await _seed_player(pool, _PRIMARY, _PRIMARY_ANCHOR)
    await _seed_player(pool, _ALLY, _ALLY_ANCHOR)
    try:
        session = SessionData(player_id=_PRIMARY, location_id=_OFF_CATALOG, room=None)
        cs = _combat_state(
            [
                _savable_fallen_participant(_PRIMARY),
                _savable_fallen_participant(_ALLY),
                _enemy(is_fallen=True),
            ]
        )

        end_data = await _run_outcome(session, cs, "defeat")

        primary = await db_queries.get_player(_PRIMARY, conn=pool)
        ally = await db_queries.get_player(_ALLY, conn=pool)
        assert primary is not None
        assert ally is not None
        # Both resurrected at their anchors.
        assert primary["location_id"] == _PRIMARY_ANCHOR
        assert ally["location_id"] == _ALLY_ANCHOR
        assert primary["death_history"]["count"] == 1
        assert ally["death_history"]["count"] == 1
        assert end_data["death_context"] is not None
        assert end_data["death_context"]["anchor"] == _PRIMARY_ANCHOR
    finally:
        await _cleanup(pool, _PRIMARY, _ALLY)


@pytest.mark.asyncio
async def test_deescalated_single_fallen_ally_e2e(dev_db_pool):
    """AC6: E2E round-trip with a single fallen ally on deescalated outcome."""
    pool = dev_db_pool
    await _seed_player(pool, _PRIMARY, _PRIMARY_ANCHOR)
    try:
        session = SessionData(player_id=_PRIMARY, location_id=_OFF_CATALOG, room=None)
        cs = _combat_state(
            [
                _savable_fallen_participant(_PRIMARY),
                _enemy(is_fallen=True),
            ]
        )

        await _run_outcome(session, cs, "deescalated")

        primary = await db_queries.get_player(_PRIMARY, conn=pool)
        assert primary is not None
        assert primary["hp"]["current"] == 1
        assert primary["death_history"]["count"] == 0
    finally:
        await _cleanup(pool, _PRIMARY)
