"""Multiplayer combat-END reconcile (M18 story-003): _end_combat_db runs its post-combat paths
PER PARTY MEMBER, not for the primary only. Fast-lane, mock-DI (no real DB): patches the
condition read/save round-trip and asserts each player participant reconciles into its OWN
players.data row. The real phase-loop-to-defeat end-to-end proof is story-007's acceptance capstone.

Solo behavior (a 1-member party) is covered byte-identically by the existing single-player
combat-end suites; this suite adds the >1-member assertions.
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


async def test_victory_reconciles_persistent_conditions_per_member():
    # p1 acquired Wounded, p2 acquired Exhausted. Each must persist into its OWN players.data row.
    session = _two_pc_session()
    cs = CombatState(
        combat_id="c1",
        participants=[
            _player_participant("p1", "Kael", [_cond("wounded")]),
            _player_participant("p2", "Bren", [_cond("exhausted")]),
            CombatParticipant(id="g1", name="Goblin", type="enemy", initiative=8, hp_current=0, hp_max=7, ac=13),
        ],
        initiative_order=["p1", "p2", "g1"],
        round_number=2,
        current_turn_index=0,
        location_id="loc1",
    )
    save = AsyncMock()
    await _run_end_combat_db(session, cs, "victory", save_mock=save)

    saved = {call.args[0]: call.args[1] for call in save.await_args_list}
    assert set(saved) == {"p1", "p2"}
    assert [c["type"] for c in saved["p1"]] == ["wounded"]
    assert [c["type"] for c in saved["p2"]] == ["exhausted"]


async def test_victory_reconciles_beneficial_dice_per_member():
    # p1 keeps a surviving Blessed die, p2 an Inspired die — each lands on its own row.
    session = _two_pc_session()
    cs = CombatState(
        combat_id="c1",
        participants=[
            _player_participant("p1", "Kael", [_cond("blessed")]),
            _player_participant("p2", "Bren", [_cond("inspired")]),
            CombatParticipant(id="g1", name="Goblin", type="enemy", initiative=8, hp_current=0, hp_max=7, ac=13),
        ],
        initiative_order=["p1", "p2", "g1"],
        round_number=2,
        current_turn_index=0,
        location_id="loc1",
    )
    save = AsyncMock()
    await _run_end_combat_db(session, cs, "victory", save_mock=save)

    saved = {call.args[0]: call.args[1] for call in save.await_args_list}
    assert [c["type"] for c in saved["p1"]] == ["blessed"]
    assert [c["type"] for c in saved["p2"]] == ["inspired"]


async def test_non_primary_reconcile_reads_its_own_store():
    # The existing-store read is keyed on the member id, so a non-primary member's prior Wounded
    # merges with its own combat-gained Exhausted — not the primary's store.
    session = _two_pc_session()
    cs = CombatState(
        combat_id="c1",
        participants=[
            _player_participant("p1", "Kael", []),
            _player_participant("p2", "Bren", [_cond("exhausted", stacks=2)]),
            CombatParticipant(id="g1", name="Goblin", type="enemy", initiative=8, hp_current=0, hp_max=7, ac=13),
        ],
        initiative_order=["p1", "p2", "g1"],
        round_number=2,
        current_turn_index=0,
        location_id="loc1",
    )

    def _read(pid, conn=None):
        return [_cond("wounded")] if pid == "p2" else []

    save = AsyncMock()
    await _run_end_combat_db(session, cs, "victory", save_mock=save, read_side_effect=_read)

    saved = {call.args[0]: call.args[1] for call in save.await_args_list}
    # p1's store was empty and it gained nothing -> unchanged -> no write.
    assert "p1" not in saved
    # p2 merges its own prior Wounded with the combat-gained Exhausted.
    assert {c["type"] for c in saved["p2"]} == {"wounded", "exhausted"}
