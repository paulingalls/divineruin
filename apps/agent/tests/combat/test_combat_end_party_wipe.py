"""Real-PG integration: the combat_end defeat router collects EVERY fallen player participant
into a party and routes them through resurrection.resurrect_party_on_defeat (M14, story-006).

Proves against the dev Postgres at :55432 (dev_db_pool) that a 2-PC party wipe resurrects BOTH
members — each at their own 4-tier anchor — inside the one defeat transaction, while solo defeat
stays unchanged (exactly one player), a survivor is left alive, and a Stage-2+ Hollowed primary
that has transformed to a temporary_hollowed echo is still resurrected — via the M20 story-004
outcome-independent dead-life collector (which catches any temporary_hollowed participant).

Each member seeds an off-catalog death location (region-less -> no tier-2 settlement) plus a
distinct real last_rested_settlement_id, so tier-3 gives divergent anchors. Cleanup removes the
seeded players in a finally (unique keys, mirroring the other fast-lane real-PG tests).
"""

from __future__ import annotations

import json

import pytest

import conditions
import db
import db_mutations
import db_queries
from combat_end import _end_combat_db
from combat_events import EventSink
from session_data import CombatParticipant, CombatState, SessionData

_PRIMARY = "s006_wipe_primary"
_SECOND = "s006_wipe_second"
_OFF_CATALOG = "off_catalog_wilds"  # region-less -> tier-1 + tier-2 skipped, falls to tier-3
_PRIMARY_ANCHOR = "millhaven"  # greyvale village (real seed)
_SECOND_ANCHOR = "accord_guild_hall"  # sunward_coast city (real seed)


async def _seed_player(pool, player_id: str, last_rested: str, *, conditions_list=None) -> None:
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
                "conditions": conditions_list or [],
            }
        ),
    )


async def _cleanup(pool, *player_ids: str) -> None:
    for pid in player_ids:
        await pool.execute("DELETE FROM players WHERE player_id = $1", pid)


def _player_participant(
    player_id: str, *, is_fallen: bool, is_dead: bool = False, type_: str = "player"
) -> CombatParticipant:
    return CombatParticipant(
        id=player_id,
        name=player_id,
        type=type_,
        initiative=10,
        hp_current=0 if (is_fallen or is_dead) else 30,
        hp_max=40,
        ac=14,
        attributes={"strength": 14, "charisma": 8, "constitution": 13},
        level=5,
        is_fallen=is_fallen,
        is_dead=is_dead,
    )


def _enemy(is_fallen: bool = True) -> CombatParticipant:
    return CombatParticipant(
        id="s006_wipe_enemy",
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
        combat_id="s006_wipe_combat",
        participants=participants,
        initiative_order=[p.id for p in participants],
    )


async def _run_defeat(session: SessionData, cs: CombatState) -> dict:
    async with db.transaction() as conn:
        return await _end_combat_db(
            session, cs, "defeat", mutations=db_mutations, queries=db_queries, conn=conn, sink=EventSink()
        )


@pytest.mark.asyncio
async def test_party_wipe_resurrects_every_fallen_member_at_own_anchor(dev_db_pool):
    """AC1 + AC4: a 2-PC party both fallen -> both collected and revived at their OWN anchors,
    in one defeat tx; the returned death_context is the PRIMARY's (session.player_id)."""
    pool = dev_db_pool
    await _seed_player(pool, _PRIMARY, _PRIMARY_ANCHOR)
    await _seed_player(pool, _SECOND, _SECOND_ANCHOR)
    try:
        session = SessionData(player_id=_PRIMARY, location_id=_OFF_CATALOG, room=None)
        cs = _combat_state(
            [
                _player_participant(_PRIMARY, is_fallen=True),
                _player_participant(_SECOND, is_fallen=True),
                _enemy(is_fallen=True),
            ]
        )

        end_data = await _run_defeat(session, cs)

        # The returned context is the primary's — its anchor is the primary's tier-3 settlement.
        assert end_data["death_context"] is not None
        assert end_data["death_context"]["anchor"] == _PRIMARY_ANCHOR

        # BOTH members revived, each at their OWN divergent anchor, each death recorded.
        primary = await db_queries.get_player(_PRIMARY, conn=pool)
        second = await db_queries.get_player(_SECOND, conn=pool)
        assert primary is not None and second is not None
        assert primary["location_id"] == _PRIMARY_ANCHOR
        assert second["location_id"] == _SECOND_ANCHOR
        assert primary["death_history"]["count"] == 1
        assert second["death_history"]["count"] == 1
    finally:
        await _cleanup(pool, _PRIMARY, _SECOND)


@pytest.mark.asyncio
async def test_solo_defeat_resurrects_exactly_one(dev_db_pool):
    """AC2 (regression): a solo party -> exactly one player resurrected, death_context is theirs."""
    pool = dev_db_pool
    await _seed_player(pool, _PRIMARY, _PRIMARY_ANCHOR)
    try:
        session = SessionData(player_id=_PRIMARY, location_id=_OFF_CATALOG, room=None)
        cs = _combat_state([_player_participant(_PRIMARY, is_fallen=True), _enemy(is_fallen=True)])

        end_data = await _run_defeat(session, cs)

        assert end_data["death_context"] is not None
        assert end_data["death_context"]["anchor"] == _PRIMARY_ANCHOR
        primary = await db_queries.get_player(_PRIMARY, conn=pool)
        assert primary is not None
        assert primary["location_id"] == _PRIMARY_ANCHOR
        assert primary["death_history"]["count"] == 1
    finally:
        await _cleanup(pool, _PRIMARY)


@pytest.mark.asyncio
async def test_survivor_is_not_collected(dev_db_pool):
    """AC3: a party where a NON-primary member survives -> only fallen players are collected; the
    survivor's row is untouched (a wipe requires all players down)."""
    pool = dev_db_pool
    await _seed_player(pool, _PRIMARY, _PRIMARY_ANCHOR)
    await _seed_player(pool, _SECOND, _SECOND_ANCHOR)
    try:
        session = SessionData(player_id=_PRIMARY, location_id=_OFF_CATALOG, room=None)
        cs = _combat_state(
            [
                _player_participant(_PRIMARY, is_fallen=True),
                _player_participant(_SECOND, is_fallen=False),  # survivor
                _enemy(is_fallen=True),
            ]
        )

        end_data = await _run_defeat(session, cs)

        # Primary fell and was resurrected; the survivor is untouched (no death, location unchanged).
        assert end_data["death_context"]["anchor"] == _PRIMARY_ANCHOR
        primary = await db_queries.get_player(_PRIMARY, conn=pool)
        second = await db_queries.get_player(_SECOND, conn=pool)
        assert primary is not None and second is not None
        assert primary["death_history"]["count"] == 1
        assert second["death_history"]["count"] == 0  # survivor: no death recorded
        assert second["location_id"] == _OFF_CATALOG  # survivor: not moved to an anchor
    finally:
        await _cleanup(pool, _PRIMARY, _SECOND)


@pytest.mark.asyncio
async def test_instant_dead_non_primary_member_is_resurrected(dev_db_pool):
    """Concern ecb8bc708dc2 (M18 story-003): a NON-primary member killed OUTRIGHT (is_dead=True,
    is_fallen=False — an overkill instant death that skips the Fallen state) in a party wipe was
    never collected by the is_fallen-only predicate, so it was never resurrected. The collector now
    includes is_dead, so the instant-dead member revives at its own anchor."""
    pool = dev_db_pool
    await _seed_player(pool, _PRIMARY, _PRIMARY_ANCHOR)
    await _seed_player(pool, _SECOND, _SECOND_ANCHOR)
    try:
        session = SessionData(player_id=_PRIMARY, location_id=_OFF_CATALOG, room=None)
        cs = _combat_state(
            [
                _player_participant(_PRIMARY, is_fallen=True),
                _player_participant(_SECOND, is_fallen=False, is_dead=True),  # instant kill
                _enemy(is_fallen=True),
            ]
        )

        await _run_defeat(session, cs)

        second = await db_queries.get_player(_SECOND, conn=pool)
        assert second is not None
        assert second["location_id"] == _SECOND_ANCHOR
        assert second["death_history"]["count"] == 1
    finally:
        await _cleanup(pool, _PRIMARY, _SECOND)


@pytest.mark.asyncio
async def test_missing_player_row_on_defeat_raises(dev_db_pool):
    """Concern 2a646ecf0b4b (M18 story-003): a fallen player participant whose players.data row is
    missing (get_player returns None) is data corruption — _end_combat_db RAISES fail-loud rather
    than silently skipping resurrection and leaving the session stranded at the death site."""
    pool = dev_db_pool
    await _seed_player(pool, _PRIMARY, _PRIMARY_ANCHOR)
    # _SECOND is intentionally NOT seeded -> get_player(_SECOND) returns None.
    try:
        session = SessionData(player_id=_PRIMARY, location_id=_OFF_CATALOG, room=None)
        cs = _combat_state(
            [
                _player_participant(_PRIMARY, is_fallen=True),
                _player_participant(_SECOND, is_fallen=True),  # no row seeded
                _enemy(is_fallen=True),
            ]
        )

        with pytest.raises(RuntimeError, match=_SECOND):
            await _run_defeat(session, cs)
    finally:
        await _cleanup(pool, _PRIMARY)


@pytest.mark.asyncio
async def test_hollowed_echo_primary_still_resurrected(dev_db_pool):
    """Review concern ea3b4a268fd3: a Stage-2+ Hollowed primary whose participant has transformed
    to a temporary_hollowed echo (type flipped, id == player_id) is NOT a `player` participant, but
    the M20 story-004 dead-life collector catches it by its temporary_hollowed type and resurrects
    it, marking hollow_killed (previously handled by a now-removed special-case primary fallback)."""
    pool = dev_db_pool
    hollowed = conditions.apply_condition([], "hollowed")  # stage 1; any stage marks hollow_killed
    await _seed_player(pool, _PRIMARY, _PRIMARY_ANCHOR, conditions_list=hollowed)
    try:
        session = SessionData(player_id=_PRIMARY, location_id=_OFF_CATALOG, room=None)
        # The echo: type flipped to temporary_hollowed on the rise, is_fallen set on destruction.
        echo = _player_participant(_PRIMARY, is_fallen=True, type_="temporary_hollowed")
        cs = _combat_state([echo, _enemy(is_fallen=True)])

        end_data = await _run_defeat(session, cs)

        assert end_data["death_context"] is not None
        assert end_data["death_context"]["hollow_killed"] is True
        assert end_data["death_context"]["anchor"] == _PRIMARY_ANCHOR
        primary = await db_queries.get_player(_PRIMARY, conn=pool)
        assert primary is not None
        assert primary["location_id"] == _PRIMARY_ANCHOR
        assert primary["death_history"]["count"] == 1
    finally:
        await _cleanup(pool, _PRIMARY)
