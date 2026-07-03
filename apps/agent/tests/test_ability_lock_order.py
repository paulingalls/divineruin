"""Deterministic cross-player caster/target lock-order (M14 story-008, debt 361417d1bea5).

Both OOC condition-producing paths (ability activation + spell cast) used to lock the CASTER row
first (get_player FOR UPDATE), then the target rows id-sorted inside produce_ooc_condition — so two
concurrent cross-player casts (alice-on-bob vs bob-on-alice) acquired rows in opposite orders and
could deadlock. This story imposes a single GLOBAL ascending-player_id lock order over the
{caster} + {non-caster party targets} union, acquired in ONE get_players_for_update batch before any
mutation. get_players_for_update issues `... ORDER BY player_id FOR UPDATE`, so the DB acquires the
row locks in player_id order; produce_ooc_condition then re-locks a held subset (no new lock).

These tests spy get_players_for_update and assert:
- the FIRST (union) lock call carries the ascending-player_id {caster + targets} set,
- no separate caster get_player(for_update=True) is issued,
- role-swapped casts compute the IDENTICAL lock order (deadlock-free by construction),
- a self / no-target cast locks only the caster row.
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from sample_fixtures import make_context, make_db_mod

from ability_tools import _request_ability_activation_impl


def _player_row(player_id: str, *, class_: str = "bard") -> dict:
    return {
        "player_id": player_id,
        "name": player_id,
        "class": class_,
        "level": 5,
        "stamina": {"current": 10, "max": 10},
        "focus": {"current": 10, "max": 10},
        "conditions": [],
    }


def _lock_spy(class_: str = "bard") -> MagicMock:
    """A queries mock whose get_players_for_update records call order and returns a row per id.
    get_player is present but should NOT be called on the ability path (caster now comes from the
    batch) — leave it un-stubbed-as-awaitable so an accidental await surfaces."""
    queries = MagicMock()

    async def _batch(player_ids, *, conn=None):
        return {pid: _player_row(pid, class_=class_) for pid in player_ids}

    queries.get_players_for_update = AsyncMock(side_effect=_batch)
    return queries


async def _activate(*, caster: str, party: list[str], ability_id: str, target_id: str | None, class_: str = "bard"):
    """Drive the ability impl with the lock spy. Returns (parsed_result, queries_mock)."""
    ctx = make_context(player_id=caster, party_member_ids=party)
    mock_db, _conn = make_db_mod()
    queries = _lock_spy(class_)
    persistence = MagicMock()
    persistence.update_player_resources = AsyncMock()
    persistence.get_active_variant = AsyncMock(return_value=None)
    persistence.owns_elective = AsyncMock(return_value=False)
    conditions_mutations = MagicMock()
    conditions_mutations.save_many_player_conditions = AsyncMock()
    raw = await _request_ability_activation_impl(
        ctx,
        ability_id,
        target_id=target_id,
        db_mod=mock_db,
        queries_mod=queries,
        persistence_mod=persistence,
        conditions_mutations_mod=conditions_mutations,
    )
    return json.loads(raw), queries


def _first_lock_ids(queries: MagicMock) -> list[str]:
    """The player_ids passed to the FIRST get_players_for_update call (the union pre-lock)."""
    first = queries.get_players_for_update.call_args_list[0]
    return list(first.args[0])


class TestAbilityLockOrder:
    @pytest.mark.asyncio
    async def test_caster_and_target_locked_in_one_ascending_batch(self):
        """AC1: request_ability_activation locks {caster, target} in ONE ascending-player_id batch;
        the caster is not separately locked via get_player(for_update=True)."""
        _result, queries = await _activate(caster="alice", party=["bob"], ability_id="bard_inspire", target_id="bob")
        lock_ids = _first_lock_ids(queries)
        assert lock_ids == ["alice", "bob"]  # ascending player_id union
        queries.get_player.assert_not_called()  # no separate caster FOR UPDATE

    @pytest.mark.asyncio
    async def test_role_swap_yields_identical_global_order(self):
        """AC2: alice-on-bob and bob-on-alice compute the IDENTICAL lock order — so two concurrent
        cross-player activations acquire rows in the same global order and cannot deadlock."""
        _r1, q1 = await _activate(caster="alice", party=["bob"], ability_id="bard_inspire", target_id="bob")
        _r2, q2 = await _activate(caster="bob", party=["alice"], ability_id="bard_inspire", target_id="alice")
        assert _first_lock_ids(q1) == _first_lock_ids(q2) == ["alice", "bob"]

    @pytest.mark.asyncio
    async def test_self_cast_locks_only_the_caster(self):
        """AC3: a self-targeted ability (no target_id) locks the single caster row once — no ordering
        regression for the solo path."""
        _result, queries = await _activate(caster="alice", party=[], ability_id="bard_inspire", target_id=None)
        assert _first_lock_ids(queries) == ["alice"]
        # Only the caster union lock — no non-caster target batch inside produce_ooc_condition.
        assert queries.get_players_for_update.call_count == 1
