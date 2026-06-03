"""Tests for the generic select(choice_id, option) verb (M4 story-003).

select resolves a pending player choice; today the only choice is the L5
specialization fork (absorbed from resolve_milestone's with-choice path). It is
fail-loud at the boundary: every bad input raises ToolError before the single
persist, so a rejected call never partially mutates."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from livekit.agents.llm import ToolError
from sample_fixtures import _WARRIOR_MILESTONES, make_context, make_db_mod

from choice_tools import _select_impl
from milestones import Milestone

# Patron-driven fork (Cleric/Paladin) — resolve_milestone/select reject these pending Phase 8.
_CLERIC_FORK = Milestone("cleric_identity", "cleric", "identity", 5, "specialization_fork", True, (), None, "cue")

_BY_ID = {m.id: m for m in _WARRIOR_MILESTONES} | {_CLERIC_FORK.id: _CLERIC_FORK}


def _player(class_="warrior", level=5, specialization=None):
    p = {"player_id": "player_1", "class": class_, "level": level}
    if specialization is not None:
        p["specialization"] = specialization
    return p


def _milestones_mod(by_id):
    """A milestones-module mock whose get_milestone resolves by id and raises
    ValueError on an unknown id (matching milestones.get_milestone)."""
    mod = MagicMock()

    def _get(milestone_id):
        if milestone_id not in by_id:
            raise ValueError(f"Unknown milestone: {milestone_id!r}")
        return by_id[milestone_id]

    mod.get_milestone = MagicMock(side_effect=_get)
    return mod


def _make_mocks(player, by_id=_BY_ID):
    mock_db, conn = make_db_mod()
    queries = MagicMock()
    queries.get_player = AsyncMock(return_value=player)
    persistence = MagicMock()
    persistence.set_player_specialization = AsyncMock()
    return SimpleNamespace(
        db=mock_db, conn=conn, queries=queries, persistence=persistence, milestones_mod=_milestones_mod(by_id)
    )


async def _select(m, choice_id, option):
    ctx = make_context()
    return await _select_impl(
        ctx,
        choice_id,
        option,
        db_mod=m.db,
        queries_mod=m.queries,
        persistence_mod=m.persistence,
        milestones_mod=m.milestones_mod,
    )


@pytest.mark.asyncio
async def test_happy_path_persists_and_returns():
    m = _make_mocks(_player(level=5))
    raw = await _select(m, "warrior_identity", "battle_master")
    assert json.loads(raw) == {"choice_id": "warrior_identity", "chosen": "battle_master", "narration_cue": "cue"}
    m.persistence.set_player_specialization.assert_awaited_once_with("player_1", "battle_master", conn=m.conn)


@pytest.mark.asyncio
async def test_threads_locked_transaction_conn():
    # Read + write share the FOR UPDATE-locked conn so the choice commits atomically.
    m = _make_mocks(_player(level=5))
    await _select(m, "warrior_identity", "battle_master")
    assert m.queries.get_player.await_args.kwargs["conn"] is m.conn
    assert m.queries.get_player.await_args.kwargs["for_update"] is True
    assert m.persistence.set_player_specialization.await_args.kwargs["conn"] is m.conn


@pytest.mark.asyncio
async def test_unknown_player_rejects():
    m = _make_mocks(None)
    with pytest.raises(ToolError, match="player"):
        await _select(m, "warrior_identity", "battle_master")
    m.persistence.set_player_specialization.assert_not_awaited()


@pytest.mark.asyncio
async def test_already_chosen_rejects_immutably():
    m = _make_mocks(_player(level=5, specialization="berserker"))
    with pytest.raises(ToolError, match="already"):
        await _select(m, "warrior_identity", "battle_master")
    m.persistence.set_player_specialization.assert_not_awaited()


@pytest.mark.asyncio
async def test_invalid_option_rejects():
    m = _make_mocks(_player(level=5))
    with pytest.raises(ToolError, match="Invalid"):
        await _select(m, "warrior_identity", "duelist")
    m.persistence.set_player_specialization.assert_not_awaited()


@pytest.mark.asyncio
async def test_unknown_choice_id_rejects():
    m = _make_mocks(_player(level=5))
    with pytest.raises(ToolError, match="Unknown"):
        await _select(m, "warrior_phantom", "battle_master")
    m.persistence.set_player_specialization.assert_not_awaited()


@pytest.mark.asyncio
async def test_wrong_archetype_rejects():
    # warrior_identity belongs to the warrior, not a guardian — reject.
    m = _make_mocks(_player(class_="guardian", level=5))
    with pytest.raises(ToolError):
        await _select(m, "warrior_identity", "battle_master")
    m.persistence.set_player_specialization.assert_not_awaited()


@pytest.mark.asyncio
async def test_non_fork_choice_id_rejects():
    # warrior_power is an auto_grant tier, not a selectable fork.
    m = _make_mocks(_player(level=10))
    with pytest.raises(ToolError):
        await _select(m, "warrior_power", "battle_master")
    m.persistence.set_player_specialization.assert_not_awaited()


@pytest.mark.asyncio
async def test_patron_deferred_rejects():
    m = _make_mocks(_player(class_="cleric", level=5))
    with pytest.raises(ToolError, match="patron"):
        await _select(m, "cleric_identity", "battle_master")
    m.persistence.set_player_specialization.assert_not_awaited()


@pytest.mark.asyncio
async def test_level_too_low_rejects():
    # A pre-L5 player (stale/replayed tap) cannot lock in the L5 fork.
    m = _make_mocks(_player(level=3))
    with pytest.raises(ToolError):
        await _select(m, "warrior_identity", "battle_master")
    m.persistence.set_player_specialization.assert_not_awaited()


@pytest.mark.asyncio
async def test_blank_choice_id_rejects_before_io():
    m = _make_mocks(_player(level=5))
    with pytest.raises(ToolError, match="Invalid"):
        await _select(m, "", "battle_master")
    m.queries.get_player.assert_not_awaited()


@pytest.mark.asyncio
async def test_blank_option_rejects_before_io():
    m = _make_mocks(_player(level=5))
    with pytest.raises(ToolError, match="Invalid"):
        await _select(m, "warrior_identity", "")
    m.queries.get_player.assert_not_awaited()
