"""Multiplayer combat-END outcome-scoped stabilize and resurrect (story-005).

Fled abandons, defeat with standing primary, echo resurrection on any outcome, empty seat order.

Fast-lane, mock-DI (no real DB): drives outcome paths with mocked content/pricing/queries.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import db_mutations_conditions
from combat_end import _end_combat_db
from combat_events import EventSink
from session_data import CombatParticipant, CombatState, SessionData

from ._end_multiplayer_helpers import (
    FakeRng,
    _player_participant,
    _restore_condition_module,  # noqa: F401
    _two_pc_session,
)


async def _run_outcome(session, cs, outcome, monkeypatch, *, resurrect_return=None):
    import resurrection

    party = AsyncMock(return_value=resurrect_return if resurrect_return is not None else [])
    on_def = AsyncMock(return_value={"anchor": "anchor_x", "revive_hp": 10})
    monkeypatch.setattr(resurrection, "resurrect_party_on_defeat", party)
    monkeypatch.setattr(resurrection, "resurrect_on_defeat", on_def)
    db_mutations_conditions.read_player_conditions = AsyncMock(return_value=[])  # type: ignore[assignment]
    db_mutations_conditions.save_player_conditions = AsyncMock()  # type: ignore[assignment]
    mutations = AsyncMock()
    queries = AsyncMock()
    queries.get_player = AsyncMock(return_value={"player_id": session.player_id, "gold": 0})
    queries.get_player_inventory = AsyncMock(return_value=[])
    end_data = await _end_combat_db(
        session,
        cs,
        outcome,
        mutations=mutations,
        queries=queries,
        conn=MagicMock(),
        sink=EventSink(),
        content=MagicMock(),
        pricing=MagicMock(),
        rng=FakeRng(),
    )
    return end_data, mutations, party, on_def


async def test_fled_abandons_fallen_ally_to_mortaen(monkeypatch):
    # M15 story-003 (decision 498f0df12b14): a flee LEAVES a downed ally behind. A savable fallen
    # ally on a 'fled' end is NOT stabilized to 1 HP for free (fleeing is not winning), but is no
    # longer stranded at 0 HP — it DIES and returns via Mortaen (resurrect_party_on_defeat), the same
    # death path as a defeat-fallen. Supersedes the earlier victory-only contract (story-005 finding 2).
    session = _two_pc_session()
    cs = CombatState(
        combat_id="c1",
        participants=[
            _player_participant("p1", "Kael", []),  # primary alive
            CombatParticipant(
                id="p2", name="Bren", type="player", initiative=12, hp_current=0, hp_max=20, ac=14, is_fallen=True
            ),
            CombatParticipant(
                id="g1", name="Goblin", type="enemy", initiative=8, hp_current=5, hp_max=7, ac=13
            ),  # alive
        ],
        initiative_order=["p1", "p2", "g1"],
        round_number=2,
        current_turn_index=0,
        location_id="loc1",
    )
    # One down ally (Bren) is collected into the death path, so resurrect_party_on_defeat receives one
    # row and must return one context (strict-zip'd against rows in _end_combat_db).
    _end, mutations, party, _on_def = await _run_outcome(
        session, cs, "fled", monkeypatch, resurrect_return=[{"anchor": "anchor_x", "revive_hp": 10}]
    )
    hp_calls = [(c.args[0], c.args[1]) for c in mutations.update_player_hp.await_args_list]
    assert ("p2", 1) not in hp_calls  # not stabilized to 1 HP on a flee (fleeing is not winning)
    party.assert_awaited_once()  # the abandoned downed ally dies -> Mortaen, never stranded at 0 HP


async def test_defeat_with_standing_primary_still_resurrects_it(monkeypatch):
    # story-005 finding 4: a DM-declared defeat with the primary still standing must still record the
    # death + anchor via the standing-primary fallback (restored after story-004 deleted it).
    session = _two_pc_session()  # primary p1
    cs = CombatState(
        combat_id="c1",
        participants=[
            _player_participant("p1", "Kael", []),  # primary STANDING
            CombatParticipant(id="g1", name="Goblin", type="enemy", initiative=8, hp_current=5, hp_max=7, ac=13),
        ],
        initiative_order=["p1", "g1"],
        round_number=2,
        current_turn_index=0,
        location_id="loc1",
    )
    end_data, _mutations, party, on_def = await _run_outcome(session, cs, "defeat", monkeypatch)
    party.assert_not_awaited()  # no down/dead participant collected
    on_def.assert_awaited_once()  # the standing primary is resurrected via the defeat fallback
    assert end_data["death_context"] is not None


async def test_destroyed_echo_primary_resurrected_even_on_fled(monkeypatch):
    # story-005 (plan-review concern): an echo is a dead player and MUST return via Mortaen on ANY
    # outcome — a destroyed echo-primary is still resurrected on a 'fled' end, never stranded.
    session = _two_pc_session()  # primary p1
    cs = CombatState(
        combat_id="c1",
        participants=[
            CombatParticipant(
                id="p1",
                name="Kael",
                type="temporary_hollowed",
                initiative=15,
                hp_current=0,
                hp_max=20,
                ac=14,
                is_fallen=True,
            ),
            _player_participant("p2", "Bren", []),  # ally alive
            CombatParticipant(id="g1", name="Goblin", type="enemy", initiative=8, hp_current=5, hp_max=7, ac=13),
        ],
        initiative_order=["p1", "p2", "g1"],
        round_number=2,
        current_turn_index=0,
        location_id="loc1",
    )
    end_data, _mutations, party, _on_def = await _run_outcome(
        session, cs, "fled", monkeypatch, resurrect_return=[{"anchor": "anchor_x"}]
    )
    party.assert_awaited_once()  # the destroyed echo-primary returns via Mortaen even on a flee
    assert end_data["death_context"] is not None


async def test_manual_victory_empty_seat_order_does_not_crash(monkeypatch):
    # concern ab4ced4c2110: a MANUAL end_combat('victory') can bypass _wrap's any_player_standing
    # gate — e.g. a solo primary risen as a temporary_hollowed echo leaves NO player participant, so
    # seat_order is empty. The loot/currency distribution must skip (nobody to receive it), not divide
    # by zero. The echo-primary still resurrects.
    session = SessionData(player_id="p1", location_id="loc1", room=None)  # solo
    cs = CombatState(
        combat_id="c1",
        participants=[
            CombatParticipant(
                id="p1",
                name="Kael",
                type="temporary_hollowed",
                initiative=15,
                hp_current=0,
                hp_max=20,
                ac=14,
                is_fallen=True,
            ),
            # a currency-bearing enemy (no loot_table -> currency only) so currency_silver > 0
            CombatParticipant(
                id="g1",
                name="Goblin",
                type="enemy",
                initiative=8,
                hp_current=0,
                hp_max=7,
                ac=13,
                is_fallen=True,
                category="humanoid",
                role="standard",
                level=5,
                xp_value=50,
            ),
        ],
        initiative_order=["p1", "g1"],
        round_number=2,
        current_turn_index=0,
        location_id="loc1",
    )
    end_data, _mutations, party, _on_def = await _run_outcome(
        session, cs, "victory", monkeypatch, resurrect_return=[{"anchor": "anchor_x"}]
    )
    # No crash; nothing distributed to an empty seat_order.
    assert end_data["primary_loot"] == []
    assert end_data["primary_currency_gold"] == 0
    party.assert_awaited_once()  # the echo-primary still returns via Mortaen
