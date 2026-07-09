"""Multiplayer combat-END loot and currency distribution (M18 story-003).

Shared loot pool, round-robin distribution across party members, party-wide currency multiplier
with even split, isolation from mid-combat joiners.

Fast-lane, mock-DI (no real DB): drives the victory path with mocked content/pricing/queries.
"""

from __future__ import annotations

import random

import pytest

import event_types as E
from session_data import CombatParticipant, CombatState, SessionData

from ._end_multiplayer_helpers import (
    _loot_table_id,
    _member,
    _restore_condition_module,  # noqa: F401
    _run_victory,
    _silver_per_gold,
    _two_pc_session,
)


_ITEM_ID = "s003_mp_item"

# Pinned deterministic output of the SOLO victory path at seed 1234 (2 humanoid enemies, a 0.6
# drop-chance loot table). Captured from the pre-refactor roll order; the roll/distribute refactor
# must leave the RNG consumption sequence — and therefore these values — byte-identical.
_SEEDED_SOLO_GOLD = 1.1
_SEEDED_SOLO_ITEMS = ["s003_mp_item"]


def _loot_enemy(pid: str, *, category: str = "humanoid", role: str = "standard", level: int = 5) -> CombatParticipant:
    return CombatParticipant(
        id=pid,
        name=pid,
        type="enemy",
        initiative=8,
        hp_current=0,
        hp_max=7,
        ac=13,
        is_fallen=True,
        category=category,
        role=role,
        level=level,
        loot_table_id=_loot_table_id,
    )


def _victory_cs(enemies: list[CombatParticipant], players: list[str]) -> CombatState:
    parts = [
        CombatParticipant(id=pid, name=pid, type="player", initiative=15, hp_current=20, hp_max=20, ac=14)
        for pid in players
    ] + enemies
    return CombatState(
        combat_id="c1",
        participants=parts,
        initiative_order=[p.id for p in parts],
        round_number=2,
        current_turn_index=0,
        location_id="loc1",
    )


class _AllHitRng(random.Random):
    """Every drop-chance gate passes; dice read 1 (quantity math untouched here)."""

    def random(self) -> float:
        return 0.0

    def randint(self, a: int, b: int) -> int:
        return 1


class _FixedCurrencyRng(random.Random):
    """Pins the humanoid base currency roll to a fixed silver value (tier*1d6); die chosen so
    tier(level5)=2 * die = silver."""

    def __init__(self, silver: int):
        super().__init__()
        self._die = silver // 2  # tier 2 -> 2 * die = silver

    def random(self) -> float:
        return 0.0

    def randint(self, a: int, b: int) -> int:
        return self._die


async def test_solo_victory_loot_currency_unchanged_seeded_regression():
    # RNG-sequence guard (the FakeRng constants can't catch a reordering): a SOLO victory with a
    # real seeded Random must produce a byte-identical haul before and after the roll/distribute
    # refactor. The pinned values below were captured from the pre-refactor path with seed 1234.
    session = SessionData(player_id="p1", location_id="loc1", room=None)
    cs = _victory_cs(
        [_loot_enemy("g1"), _loot_enemy("g2", role="elite")],
        ["p1"],
    )
    drops = [{"item_id": _ITEM_ID, "chance": 0.6, "quantity": 2}]
    end_data, _m, _q, sink = await _run_victory(session, cs, rng=random.Random(1234), drops=drops)

    # Pinned deterministic output (seed 1234) — reordering the currency/loot rolls changes these.
    # Solo: the primary receives the whole haul, so primary_* equals the full haul.
    assert end_data["primary_currency_gold"] == pytest.approx(_SEEDED_SOLO_GOLD)
    assert [d["item_id"] for d in end_data["primary_loot"]] == _SEEDED_SOLO_ITEMS
    # Solo: exactly one CURRENCY_GAINED for the primary.
    currency_events = [e for e in sink.captured if e.event_type == E.CURRENCY_GAINED]
    assert len(currency_events) == 1
    assert currency_events[0].payload["player_id"] == "p1"
    # Solo: the single ITEM_ACQUIRED carries the primary's own player_id (back-compat AC).
    item_events = [e for e in sink.captured if e.event_type == E.ITEM_ACQUIRED]
    assert len(item_events) == 1
    assert item_events[0].payload["player_id"] == "p1"


async def test_two_pc_victory_rounds_robin_loot_ascending_seat():
    # Shared pool, round-robin across members in ascending player_id seat order: item 0 -> p1,
    # item 1 -> p2, item 2 -> p1 ...
    session = _two_pc_session()
    cs = _victory_cs([_loot_enemy("g1")], ["p1", "p2"])
    # Force 3 drops from the single enemy so distribution wraps.
    drops = [
        {"item_id": "sword", "chance": 1.0, "quantity": 1},
        {"item_id": "shield", "chance": 1.0, "quantity": 1},
        {"item_id": "potion", "chance": 1.0, "quantity": 1},
    ]
    end_data, mutations, _q, sink = await _run_victory(session, cs, rng=_AllHitRng(), drops=drops)

    grants = [(c.args[0], c.args[1]) for c in mutations.add_inventory_item.await_args_list]
    assert grants == [("p1", "sword"), ("p2", "shield"), ("p1", "potion")]
    # Each ITEM_ACQUIRED carries the round-robinned recipient's player_id (mirroring CURRENCY_GAINED).
    item_events = [e for e in sink.captured if e.event_type == E.ITEM_ACQUIRED]
    assert [(e.payload["item_id"], e.payload["player_id"]) for e in item_events] == [
        ("sword", "p1"),
        ("shield", "p2"),
        ("potion", "p1"),
    ]
    # The primary's own loot is only their own drops — not the party's whole haul.
    assert [d["item_id"] for d in end_data["primary_loot"]] == ["sword", "potion"]


async def test_two_pc_victory_currency_party_multiplier_split_and_lock_order():
    # Currency: total silver * multiplier(2)=1.5, split evenly; each member gets its own
    # CURRENCY_GAINED; the FOR UPDATE gold locks are acquired in ascending player_id order.
    session = _two_pc_session()
    cs = _victory_cs([_loot_enemy("g1", category="humanoid", role="standard", level=5)], ["p1", "p2"])
    drops: list[dict] = []  # no items; isolate currency
    end_data, mutations, queries, sink = await _run_victory(
        session, cs, rng=_FixedCurrencyRng(silver=20), drops=drops, gold_by_id={"p1": 0, "p2": 0}
    )

    # base 20 silver * 1.5 = 30 silver total; /2 = 15 silver each; /10 spg = 1.5 gold each.
    gold_calls = {c.args[0]: c.args[1] for c in mutations.update_player_gold.await_args_list}
    assert gold_calls == {"p1": pytest.approx(1.5), "p2": pytest.approx(1.5)}
    # the primary's own haul is only THEIR share (1.5 gold), never the summed party total (3.0).
    assert end_data["primary_currency_gold"] == pytest.approx(1.5)
    # one CURRENCY_GAINED per member.
    currency_ids = [e.payload["player_id"] for e in sink.captured if e.event_type == E.CURRENCY_GAINED]
    assert currency_ids == ["p1", "p2"]
    # FOR UPDATE gold locks acquired in ascending player_id order (deadlock-free SSOT).
    lock_order = [c.args[0] for c in queries.get_player.await_args_list if c.kwargs.get("for_update")]
    assert lock_order == ["p1", "p2"]


async def test_victory_excludes_mid_combat_joiner_from_rewards():
    # A player who joins the room mid-combat is appended to the party (participant_lifecycle) but is
    # NOT a combat participant. Loot/currency are keyed on the player PARTICIPANTS who fought, so the
    # joiner p3 neither dilutes the currency split nor receives a looted item.
    session = _two_pc_session()  # p1, p2 fought
    session.party.members.append(_member("p3"))  # mid-combat joiner — in the party, not a combatant
    cs = _victory_cs([_loot_enemy("g1", category="humanoid", role="standard", level=5)], ["p1", "p2"])
    drops = [{"item_id": "sword", "chance": 1.0, "quantity": 1}]
    _end, mutations, _q, _sink = await _run_victory(
        session, cs, rng=_FixedCurrencyRng(silver=20), drops=drops, gold_by_id={"p1": 0, "p2": 0, "p3": 0}
    )

    # Currency split across the 2 participants (multiplier(2)=1.5 -> 1.5 gold each), NOT 3 -> p3 excluded.
    gold_calls = {c.args[0]: c.args[1] for c in mutations.update_player_gold.await_args_list}
    assert set(gold_calls) == {"p1", "p2"}
    assert gold_calls["p1"] == pytest.approx(1.5)
    # The single looted item goes to a participant (ascending seat order -> p1), never the joiner.
    item_recipients = {c.args[0] for c in mutations.add_inventory_item.await_args_list}
    assert item_recipients == {"p1"}
    assert "p3" not in item_recipients
