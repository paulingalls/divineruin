"""Unit tests for condition_produce — the shared OOC beneficial-condition producer (M4.8 story-007).

The per-target apply -> persist-on-land -> self-row-reuse -> companion-narrate-only logic lives in
``produce_ooc_condition`` itself (the former per-target ``apply_beneficial_condition_to_player``
helper was folded in when the party gate + batched write landed). These tests pin the helper's
contract directly, independent of either caller (spell_casting / ability_tools). The party-gate
refusal paths (non-party/non-companion target, missing party row, id-ordered batch fetch) live in
``test_condition_produce_party_gate.py``.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

import conditions
from condition_produce import produce_ooc_condition


def _row(player_id: str, conditions_list: list | None = None) -> dict:
    return {"player_id": player_id, "conditions": conditions_list if conditions_list is not None else []}


def _mods(table: dict):
    """Real conditions module + mocked batched persistence; get_players_for_update serves rows
    from `table`."""

    async def _get_players_for_update(player_ids, *, conn=None):
        return {pid: table[pid] for pid in player_ids if pid in table}

    queries = MagicMock(get_players_for_update=AsyncMock(side_effect=_get_players_for_update))
    cond_mut = MagicMock(save_many_player_conditions=AsyncMock())
    return queries, cond_mut


@pytest.mark.asyncio
async def test_apply_self_target_reuses_caster_row_no_fetch():
    caster = _row("c1")
    queries, cond_mut = _mods({})
    voiced = await produce_ooc_condition(
        "blessed",
        "divine_bless",
        target_id="c1",
        target_ids=None,
        caster_row=caster,
        caster_id="c1",
        party_member_ids=["c1"],
        companion_id=None,
        queries_mod=queries,
        conditions_mod=conditions,
        conditions_mutations_mod=cond_mut,
    )
    assert voiced == ["c1"]
    queries.get_players_for_update.assert_not_awaited()  # self-target reuses the locked caster row
    cond_mut.save_many_player_conditions.assert_awaited_once()
    written = cond_mut.save_many_player_conditions.await_args.args[0]
    assert set(written.keys()) == {"c1"}


@pytest.mark.asyncio
async def test_apply_player_target_fetches_and_persists():
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
    queries.get_players_for_update.assert_awaited_once()
    written = cond_mut.save_many_player_conditions.await_args.args[0]
    assert "blessed" in [c["type"] for c in written["a1"]]


@pytest.mark.asyncio
async def test_apply_companion_target_narrates_without_write():
    # A companion has no players.data store -> narrate-only, no write, no fetch.
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
async def test_apply_immunity_no_op_omits_target_no_write():
    # An immunity no-op (apply lands nothing) writes nothing and is NOT voiced.
    caster = _row("c1")
    ally = _row("a1")
    queries, cond_mut = _mods({"a1": ally})
    no_op_conditions = MagicMock(
        apply_condition=MagicMock(return_value=[]),
        has_condition=MagicMock(return_value=False),
    )
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
        conditions_mod=no_op_conditions,
        conditions_mutations_mod=cond_mut,
    )
    assert voiced == []
    cond_mut.save_many_player_conditions.assert_not_awaited()


@pytest.mark.asyncio
async def test_produce_multi_target_returns_voiced_ids_in_order():
    caster = _row("c1")
    rows = {f"a{i}": _row(f"a{i}") for i in (1, 2, 3)}
    queries, cond_mut = _mods(rows)
    voiced = await produce_ooc_condition(
        "blessed",
        "divine_bless",
        target_id=None,
        target_ids=["a1", "a2", "a3"],
        caster_row=caster,
        caster_id="c1",
        party_member_ids=["c1", "a1", "a2", "a3"],
        companion_id=None,
        queries_mod=queries,
        conditions_mod=conditions,
        conditions_mutations_mod=cond_mut,
    )
    assert voiced == ["a1", "a2", "a3"]
    cond_mut.save_many_player_conditions.assert_awaited_once()  # ONE batched write, not N
    assert set(cond_mut.save_many_player_conditions.await_args.args[0].keys()) == {"a1", "a2", "a3"}


@pytest.mark.asyncio
async def test_produce_multi_skips_immunity_no_op_target():
    # A target whose apply no-ops is omitted from the voiced list (still produces the others).
    caster = _row("c1")
    rows = {"a1": _row("a1"), "a2": _row("a2")}
    queries, cond_mut = _mods(rows)
    real_apply = conditions.apply_condition

    def _apply(existing, ctype, *, source):
        return [] if existing is rows["a2"]["conditions"] else real_apply(existing, ctype, source=source)

    fake = MagicMock(apply_condition=MagicMock(side_effect=_apply), has_condition=conditions.has_condition)
    voiced = await produce_ooc_condition(
        "blessed",
        "divine_bless",
        target_id=None,
        target_ids=["a1", "a2"],
        caster_row=caster,
        caster_id="c1",
        party_member_ids=["c1", "a1", "a2"],
        companion_id=None,
        queries_mod=queries,
        conditions_mod=fake,
        conditions_mutations_mod=cond_mut,
    )
    assert voiced == ["a1"]


@pytest.mark.asyncio
async def test_produce_no_targets_is_self_cast():
    caster = _row("c1")
    queries, cond_mut = _mods({})
    voiced = await produce_ooc_condition(
        "blessed",
        "divine_bless",
        target_id=None,
        target_ids=None,
        caster_row=caster,
        caster_id="c1",
        party_member_ids=["c1"],
        companion_id=None,
        queries_mod=queries,
        conditions_mod=conditions,
        conditions_mutations_mod=cond_mut,
    )
    assert voiced == ["c1"]
    assert set(cond_mut.save_many_player_conditions.await_args.args[0].keys()) == {"c1"}


@pytest.mark.asyncio
async def test_produce_single_target_id():
    caster = _row("c1")
    queries, cond_mut = _mods({"a1": _row("a1")})
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
