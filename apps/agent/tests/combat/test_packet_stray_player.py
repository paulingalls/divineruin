"""Skip noncritical durability accrual for a stray participant rather than rolling back their resolved swing."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from combat._helpers import _damage_resolver, _make_combat_state
from inventory_snapshot_fixture import snapshot_query
from sample_fixtures import make_context
from voice_condition_fixtures import place_actors

from combat_events import EventSink
from combat_packet import _resolve_one_packet
from combat_phase import ResolutionPacket
from declarations import Declaration, DeclarationType
from session_data import CombatParticipant


def _queries():
    q = MagicMock()
    q.get_player_inventory = AsyncMock(return_value=[])  # no equipped items -> no durability write
    q.get_inventory_snapshot = snapshot_query([])
    return q


def _mutations():
    m = MagicMock()
    m.update_player_hp = AsyncMock()
    m.save_combat_state = AsyncMock()
    return m


@pytest.mark.asyncio
async def test_a_swing_by_a_player_with_no_party_member_resolves_instead_of_raising():
    session = make_context().userdata
    state = _make_combat_state()
    enemy = state.get_participant("goblin_scout_1")
    assert enemy is not None
    stray = CombatParticipant(
        id="ghost_pc",
        name="Ghost",
        type="player",
        initiative=20,
        hp_current=20,
        hp_max=20,
        ac=14,
        action_pool=[{"name": "Longsword", "damage": "1d8", "damage_type": "slashing", "properties": []}],
    )
    state.participants.append(stray)
    place_actors(state)
    assert session.party.member("ghost_pc") is None  # the stray: no PartyMember behind it

    packet = ResolutionPacket(
        actor_id="ghost_pc",
        declaration=Declaration(type=DeclarationType.ATTACK, action="Longsword", target_id=enemy.id),
        initiative=20,
    )

    summary = await _resolve_one_packet(
        session,
        state,
        packet,
        mutations=_mutations(),
        queries=_queries(),
        resolver=_damage_resolver(3),
        concentration_break_mod=MagicMock(break_concentration_on_damage=AsyncMock(return_value=None)),
        sink=EventSink(),
    )

    assert summary["actor_id"] == "ghost_pc"
    assert enemy.hp_current < 7  # the swing landed; the phase carried on
