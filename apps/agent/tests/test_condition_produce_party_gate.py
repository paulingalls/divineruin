"""Party-membership gate + batched locked write for produce_ooc_condition (M4.8 story-007).

Debts d2316e2f74af (no party/existence gate — a non-party PC or phantom id silently "lands") and
b0207c768743 (per-ally N round-trips) both close here. A target must be a caster's party member OR
their present companion (allowlisted narrate-only, no players.data row) — anything else is refused
fail-loud, no write. Party targets are fetched + written in ONE batched, id-ordered call each (was
N per-target round-trips).
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

import conditions
from condition_produce import produce_ooc_condition


def _row(player_id: str, conditions_list: list | None = None) -> dict:
    return {"player_id": player_id, "conditions": conditions_list if conditions_list is not None else []}


def _mods(table: dict):
    """Real conditions module + mocked batched persistence seams."""

    async def _get_players_for_update(player_ids, *, conn=None):
        return {pid: table[pid] for pid in player_ids if pid in table}

    queries = MagicMock(get_players_for_update=AsyncMock(side_effect=_get_players_for_update))
    cond_mut = MagicMock(save_many_player_conditions=AsyncMock())
    return queries, cond_mut


@pytest.mark.asyncio
async def test_non_party_non_companion_target_fails_loud_no_write():
    # AC1: target is neither a party member nor the caster's companion -> refused, no write.
    caster = _row("c1")
    queries, cond_mut = _mods({"intruder": _row("intruder")})
    with pytest.raises(ValueError):
        await produce_ooc_condition(
            "blessed",
            "divine_bless",
            target_id="intruder",
            target_ids=None,
            caster_row=caster,
            caster_id="c1",
            party_member_ids=["c1", "a1"],
            companion_id=None,
            queries_mod=queries,
            conditions_mod=conditions,
            conditions_mutations_mod=cond_mut,
        )
    cond_mut.save_many_player_conditions.assert_not_awaited()


@pytest.mark.asyncio
async def test_party_member_with_no_players_row_fails_loud():
    # AC2: a3 is a party member id but has no players.data row (non-existent) -> refused.
    caster = _row("c1")
    queries, cond_mut = _mods({"a1": _row("a1")})  # a3 deliberately absent
    with pytest.raises(ValueError):
        await produce_ooc_condition(
            "blessed",
            "divine_bless",
            target_id=None,
            target_ids=["a1", "a3"],
            caster_row=caster,
            caster_id="c1",
            party_member_ids=["c1", "a1", "a3"],
            companion_id=None,
            queries_mod=queries,
            conditions_mod=conditions,
            conditions_mutations_mod=cond_mut,
        )
    cond_mut.save_many_player_conditions.assert_not_awaited()


@pytest.mark.asyncio
async def test_three_party_allies_batch_fetch_and_batch_write_once():
    # AC3: 3 allies -> ONE get_players_for_update call with the id-sorted list, ONE batched write.
    caster = _row("c1")
    rows = {f"a{i}": _row(f"a{i}") for i in (3, 1, 2)}
    queries, cond_mut = _mods(rows)
    voiced = await produce_ooc_condition(
        "blessed",
        "divine_bless",
        target_id=None,
        target_ids=["a3", "a1", "a2"],
        caster_row=caster,
        caster_id="c1",
        party_member_ids=["c1", "a1", "a2", "a3"],
        companion_id=None,
        queries_mod=queries,
        conditions_mod=conditions,
        conditions_mutations_mod=cond_mut,
    )
    assert voiced == ["a3", "a1", "a2"]
    queries.get_players_for_update.assert_awaited_once()
    fetched_ids = queries.get_players_for_update.await_args.args[0]
    assert fetched_ids == ["a1", "a2", "a3"]  # id-sorted, deterministic lock order
    cond_mut.save_many_player_conditions.assert_awaited_once()
    written = cond_mut.save_many_player_conditions.await_args.args[0]
    assert set(written.keys()) == {"a1", "a2", "a3"}


@pytest.mark.asyncio
async def test_companion_target_preserved_as_narrate_only_no_write():
    caster = _row("c1")
    queries, cond_mut = _mods({})
    voiced = await produce_ooc_condition(
        "blessed",
        "divine_bless",
        target_id="kael",
        target_ids=None,
        caster_row=caster,
        caster_id="c1",
        party_member_ids=["c1"],
        companion_id="kael",
        queries_mod=queries,
        conditions_mod=conditions,
        conditions_mutations_mod=cond_mut,
    )
    assert voiced == ["kael"]
    queries.get_players_for_update.assert_not_awaited()
    cond_mut.save_many_player_conditions.assert_not_awaited()


@pytest.mark.asyncio
async def test_e2e_two_pc_party_ally_applied_non_party_rejected_single_batch_lock():
    # AC4: the E2E acceptance-command shape — a 2-PC party where the ally lands via ONE batched
    # lock, and a separate call against a non-party id is refused.
    caster = _row("c1")
    ally = _row("a1")
    queries, cond_mut = _mods({"a1": ally})
    voiced = await produce_ooc_condition(
        "blessed",
        "divine_bless",
        target_id="a1",
        target_ids=None,
        caster_row=caster,
        caster_id="c1",
        party_member_ids=["c1", "a1"],
        companion_id=None,
        queries_mod=queries,
        conditions_mod=conditions,
        conditions_mutations_mod=cond_mut,
    )
    assert voiced == ["a1"]
    queries.get_players_for_update.assert_awaited_once_with(["a1"], conn=None)
    cond_mut.save_many_player_conditions.assert_awaited_once()

    queries2, cond_mut2 = _mods({"outsider": _row("outsider")})
    with pytest.raises(ValueError):
        await produce_ooc_condition(
            "blessed",
            "divine_bless",
            target_id="outsider",
            target_ids=None,
            caster_row=caster,
            caster_id="c1",
            party_member_ids=["c1", "a1"],
            companion_id=None,
            queries_mod=queries2,
            conditions_mod=conditions,
            conditions_mutations_mod=cond_mut2,
        )
    cond_mut2.save_many_player_conditions.assert_not_awaited()
