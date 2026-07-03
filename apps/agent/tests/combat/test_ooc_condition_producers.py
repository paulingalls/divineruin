"""E2E acceptance: both OOC beneficial-condition producer paths through the shared helpers
(story-005, sprint-032, M18).

spell_casting._resolve_cast and ability_tools._request_ability_activation_impl each used to carry
a byte-identical pre-lock preamble, then produce_ooc_condition re-fetched the target rows the
caller had already locked (debts 9a4b4d89d60a / c712fb731f06). This drives BOTH real catalog
entries (divine_bless / bard_inspire, seeded from content/*.json by the autouse conftest
fixtures) end to end and asserts: the condition lands, and exactly ONE get_players_for_update
batch call is made — proving the double-fetch is gone. A cross-player pair also pins the
deadlock-safe invariant (concern 5449cc774146): the {caster} UNION {targets} lock is ONE
ascending-player_id batch, caster NOT first, identical whether the entry is a spell or an ability.
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from sample_fixtures import make_context, make_db_mod

import ability_tools
import spell_casting


def _player_row(player_id: str, *, class_: str = "bard") -> dict:
    return {
        "player_id": player_id,
        "name": player_id,
        "class": class_,
        "level": 5,
        "focus": {"current": 10, "max": 10},
        "conditions": [],
    }


def _table_queries(table: dict) -> MagicMock:
    async def _get_players_for_update(player_ids, *, conn=None):
        return {pid: table[pid] for pid in player_ids if pid in table}

    return MagicMock(get_players_for_update=AsyncMock(side_effect=_get_players_for_update))


async def _cast_bless(*, caster: str, party: list[str], target_id: str):
    """Drive the REAL divine_bless spell (content/spells.json) through _cast_spell_impl OOC."""
    ctx = make_context(player_id=caster, party_member_ids=party)
    mock_db, _conn = make_db_mod()
    table = {pid: _player_row(pid) for pid in [caster, *party]}
    queries = _table_queries(table)
    persistence = MagicMock(update_player_resources=AsyncMock())
    res_mut = MagicMock(update_player_resonance=AsyncMock())
    res_evt = MagicMock(publish_resonance_changed=AsyncMock())
    concentration_mut = MagicMock(update_player_concentration=AsyncMock())
    cond_mut = MagicMock(save_many_player_conditions=AsyncMock())
    raw = await spell_casting._cast_spell_impl(
        ctx,
        "divine_bless",
        target_id=target_id,
        db_mod=mock_db,
        queries_mod=queries,
        persistence_mod=persistence,
        resonance_mutations_mod=res_mut,
        resonance_events_mod=res_evt,
        concentration_mutations_mod=concentration_mut,
        conditions_mutations_mod=cond_mut,
    )
    return json.loads(raw), queries, cond_mut


async def _activate_inspire(*, caster: str, party: list[str], target_id: str):
    """Drive the REAL bard_inspire ability (content/archetype_abilities.json) OOC."""
    ctx = make_context(player_id=caster, party_member_ids=party)
    mock_db, _conn = make_db_mod()
    table = {pid: _player_row(pid) for pid in [caster, *party]}
    queries = _table_queries(table)
    persistence = MagicMock(
        update_player_resources=AsyncMock(),
        get_active_variant=AsyncMock(return_value=None),
        owns_elective=AsyncMock(return_value=False),
    )
    cond_mut = MagicMock(save_many_player_conditions=AsyncMock())
    raw = await ability_tools._request_ability_activation_impl(
        ctx,
        "bard_inspire",
        target_id=target_id,
        db_mod=mock_db,
        queries_mod=queries,
        persistence_mod=persistence,
        conditions_mutations_mod=cond_mut,
    )
    return json.loads(raw), queries, cond_mut


@pytest.mark.asyncio
async def test_ooc_bless_via_cast_spell_lands_condition_single_batch_lock():
    packet, queries, cond_mut = await _cast_bless(caster="caster_1", party=["ally_1"], target_id="ally_1")

    assert packet["condition_applied"] == "blessed"
    cond_mut.save_many_player_conditions.assert_awaited_once()
    written = cond_mut.save_many_player_conditions.await_args.args[0]
    assert "blessed" in [c["type"] for c in written["ally_1"]]
    # AC: no double-fetch — produce_ooc_condition reuses the caller's lock, ONE batch total.
    queries.get_players_for_update.assert_awaited_once()


@pytest.mark.asyncio
async def test_ooc_inspire_via_ability_lands_condition_single_batch_lock():
    packet, queries, cond_mut = await _activate_inspire(caster="caster_1", party=["ally_1"], target_id="ally_1")

    assert packet["condition_applied"] == "inspired"
    cond_mut.save_many_player_conditions.assert_awaited_once()
    written = cond_mut.save_many_player_conditions.await_args.args[0]
    assert "inspired" in [c["type"] for c in written["ally_1"]]
    # AC: no double-fetch — produce_ooc_condition reuses the caller's lock, ONE batch total.
    queries.get_players_for_update.assert_awaited_once()


@pytest.mark.asyncio
async def test_cast_and_ability_use_identical_ascending_union_lock_order():
    # Cross-player, cross-path: alice casts Bless on bob; bob activates Inspire on alice. Both must
    # lock {alice, bob} ascending (caster NOT first) in their one and only batch call — the same
    # invariant regardless of which entry point produced the condition (concern 5449cc774146).
    _spell_packet, spell_queries, _sm = await _cast_bless(caster="alice", party=["bob"], target_id="bob")
    _ability_packet, ability_queries, _am = await _activate_inspire(caster="bob", party=["alice"], target_id="alice")

    spell_lock_ids = list(spell_queries.get_players_for_update.await_args_list[0].args[0])
    ability_lock_ids = list(ability_queries.get_players_for_update.await_args_list[0].args[0])
    assert spell_lock_ids == ability_lock_ids == ["alice", "bob"]
    spell_queries.get_players_for_update.assert_awaited_once()
    ability_queries.get_players_for_update.assert_awaited_once()


@pytest.mark.asyncio
async def test_self_cast_locks_only_the_caster_for_both_paths():
    packet_spell, spell_queries, _sm = await _cast_bless(caster="caster_1", party=[], target_id="caster_1")
    packet_ability, ability_queries, _am = await _activate_inspire(caster="caster_1", party=[], target_id="caster_1")

    assert packet_spell["condition_applied"] == "blessed"
    assert packet_ability["condition_applied"] == "inspired"
    assert list(spell_queries.get_players_for_update.await_args.args[0]) == ["caster_1"]
    assert list(ability_queries.get_players_for_update.await_args.args[0]) == ["caster_1"]
    spell_queries.get_players_for_update.assert_awaited_once()
    ability_queries.get_players_for_update.assert_awaited_once()
