"""Shared fixtures and helpers for multiplayer combat-END test clusters.

Extracted from test_combat_end_multiplayer.py; used by 2+ cluster files.
"""

from __future__ import annotations

import random
from unittest.mock import AsyncMock, MagicMock

import pytest

import db_mutations_conditions
from caster_state import ConcentrationState, ResonanceTrack, VeilWardState
from combat_end import _end_combat_db
from combat_events import EventSink
from party_state import PartyMember
from session_data import CombatParticipant, CombatState, SessionData


class FakeRng(random.Random):
    def __init__(self, die: int = 4, chance: float = 1.0):
        super().__init__()
        self._die = die
        self._chance = chance

    def randint(self, a: int, b: int) -> int:
        return self._die

    def random(self) -> float:
        return self._chance


def _member(player_id: str) -> PartyMember:
    return PartyMember(
        player_id=player_id,
        resonance=ResonanceTrack(),
        veil_ward=VeilWardState(),
        concentration=ConcentrationState(),
    )


def _two_pc_session() -> SessionData:
    session = SessionData(player_id="p1", location_id="loc1", room=None)
    session.party.members.append(_member("p2"))
    return session


def _player_participant(pid: str, name: str, conds: list[dict]) -> CombatParticipant:
    return CombatParticipant(
        id=pid, name=name, type="player", initiative=15, hp_current=20, hp_max=20, ac=14, conditions=conds
    )


def _cond(ctype: str, **extra) -> dict:
    return {"type": ctype, "duration": "encounter", "source": "test", "stacks": 1, **extra}


async def _run_end_combat_db(session, cs, outcome, *, save_mock, read_side_effect=None):
    """Drive _end_combat_db with a mock conn, patching the condition read/save round-trip. Returns
    nothing — assertions read the injected save_mock's call list."""
    read_mock = AsyncMock(side_effect=read_side_effect or (lambda pid, conn=None: []))
    db_mutations_conditions.read_player_conditions = read_mock  # type: ignore[assignment]
    db_mutations_conditions.save_player_conditions = save_mock  # type: ignore[assignment]
    mutations = AsyncMock()
    queries = AsyncMock()
    sink = EventSink()
    await _end_combat_db(
        session,
        cs,
        outcome,
        mutations=mutations,
        queries=queries,
        conn=MagicMock(),
        sink=sink,
        content=MagicMock(),
        pricing=MagicMock(),
        rng=FakeRng(),
    )


@pytest.fixture(autouse=True)
def _restore_condition_module():
    orig_read = db_mutations_conditions.read_player_conditions
    orig_save = db_mutations_conditions.save_player_conditions
    yield
    db_mutations_conditions.read_player_conditions = orig_read
    db_mutations_conditions.save_player_conditions = orig_save


async def _run_victory(session, cs, *, rng, drops, gold_by_id=None):
    """Drive the victory path with mock DI. Returns (end_data, mutations, queries, sink)."""
    db_mutations_conditions.read_player_conditions = AsyncMock(return_value=[])  # type: ignore[assignment]
    db_mutations_conditions.save_player_conditions = AsyncMock()  # type: ignore[assignment]
    mutations = AsyncMock()
    queries = AsyncMock()
    gold_by_id = gold_by_id or {}
    queries.get_player = AsyncMock(
        side_effect=lambda pid, conn=None, for_update=False: {"gold": gold_by_id.get(pid, 0)}
    )
    queries.get_player_inventory = AsyncMock(return_value=[])
    sink = EventSink()
    end_data = await _end_combat_db(
        session,
        cs,
        "victory",
        mutations=mutations,
        queries=queries,
        conn=MagicMock(),
        sink=sink,
        content=_content_stub(drops),
        pricing=_pricing_stub(),
        rng=rng,
    )
    return end_data, mutations, queries, sink


_loot_table_id = "s003_mp_loot_table"
_silver_per_gold = 10


def _content_stub(drops: list[dict]) -> MagicMock:
    async def _get(loot_table_id: str) -> dict | None:
        return {"id": _loot_table_id, "drops": drops} if loot_table_id == _loot_table_id else None

    content = MagicMock()
    content.get_loot_table = AsyncMock(side_effect=_get)
    return content


def _pricing_stub() -> MagicMock:
    pricing = MagicMock()
    pricing.get_economy_pricing = AsyncMock(return_value={"silver_per_gold": _silver_per_gold})
    return pricing
