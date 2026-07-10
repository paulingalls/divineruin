"""A stray player participant must not abort a resolved phase over a durability scratch flag.

The two ends of the weapon-durability feature disagreed on fail-loud vs fail-safe for identical
input. combat_end skips a player participant with no PartyMember behind it -- explicitly "a fail-safe
for a non-critical accrual rather than aborting the whole combat-end tx". The swing path used the
RAISING session.member_state(), so the same stray participant raised ValueError inside the phase
transaction and rolled back an entire resolved round.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from combat._helpers import _damage_resolver, _make_combat_state
from sample_fixtures import make_context

from combat_events import EventSink
from combat_packet import _resolve_one_packet
from combat_phase import ResolutionPacket
from declarations import Declaration, DeclarationType
from session_data import CombatParticipant


def _queries():
    q = MagicMock()
    q.get_player_inventory = AsyncMock(return_value=[])  # no equipped items -> no durability write
    return q


def _mutations():
    m = MagicMock()
    m.update_player_hp = AsyncMock()
    m.save_combat_state = AsyncMock()
    return m


@pytest.mark.asyncio
async def test_a_swing_by_a_player_with_no_party_member_resolves_instead_of_raising():
    """`ghost_pc` is a type="player" participant absent from PartyState. Its swing must resolve."""
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
    assert session.party.member("ghost_pc") is None  # the stray: no PartyMember behind it

    packet = ResolutionPacket(
        actor_id="ghost_pc",
        declaration=Declaration(type=DeclarationType.ATTACK, action="Longsword", target_id=enemy.id),
        initiative=20,
    )

    # Before the fix: ValueError("No party member with player_id 'ghost_pc'") inside the phase tx.
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
