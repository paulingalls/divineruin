from __future__ import annotations

import random

import pytest

import event_types as E
from session_data import CombatParticipant, CombatState

from ._end_multiplayer_helpers import (
    _restore_condition_module,  # noqa: F401
    _run_victory,
    _two_pc_session,
)


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
        tier=2,
        role=role,
        level=level,
        carried_items=[],
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


async def test_two_pc_victory_currency_party_multiplier_split_and_lock_order():
    session = _two_pc_session()
    cs = _victory_cs([_loot_enemy("g1", category="humanoid", role="standard", level=5)], ["p1", "p2"])
    end_data, mutations, queries, sink = await _run_victory(
        session, cs, rng=_FixedCurrencyRng(silver=20), gold_by_id={"p1": 0, "p2": 0}
    )

    gold_calls = {c.args[0]: c.args[1] for c in mutations.update_player_gold.await_args_list}
    assert gold_calls == {"p1": pytest.approx(1.5), "p2": pytest.approx(1.5)}
    assert end_data["primary_currency_gold"] == pytest.approx(1.5)
    currency_ids = [e.payload["player_id"] for e in sink.captured if e.event_type == E.CURRENCY_GAINED]
    assert currency_ids == ["p1", "p2"]
    lock_order = [c.args[0] for c in queries.get_player.await_args_list if c.kwargs.get("for_update")]
    assert lock_order == ["p1", "p2"]
