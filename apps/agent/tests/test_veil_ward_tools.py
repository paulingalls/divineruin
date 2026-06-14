"""Tests for activate_veil_ward (veil_ward_tools.py, story-003, M3.2).

Drives the tool's _impl directly with a mock RunContext + injected mock
queries/persistence/ward-mutations mods, mirroring test_ability_tools.py. The tool is
one polymorphic verb: active=True raises a ward (archetype/level/cost gated), active=False
dismisses it (free). Every user-facing failure is a ToolError raised before any write, so
an unaffordable/ineligible activation deducts nothing.

The published VEIL_WARD_CHANGED payload is the minimal {active} (mirroring the resonance
no-number discipline); publish_game_event is patched to assert the wire shape, matching
test_resonance_session.py.
"""

import json
from unittest.mock import ANY, AsyncMock, MagicMock, patch

import pytest
from livekit.agents.llm import ToolError
from sample_fixtures import make_context, make_db_mod

import event_types as E
import veil_ward_tools
from veil_ward_tools import _activate_veil_ward_impl


def _player(class_: str = "cleric", level: int = 7, focus: int = 10, stamina: int = 10) -> dict:
    return {
        "player_id": "player_1",
        "name": "Mara",
        "class": class_,
        "level": level,
        "focus": {"current": focus, "max": 10},
        "stamina": {"current": stamina, "max": 10},
    }


def _mocks(player: dict, *, ward_active: bool = False):
    ctx = make_context()
    mock_db, _conn = make_db_mod()
    queries = MagicMock()
    queries.get_player = AsyncMock(return_value=player)
    persistence = MagicMock()
    persistence.update_player_resources = AsyncMock()
    ward_mut = MagicMock()
    ward_mut.read_player_veil_ward = AsyncMock(
        return_value={"active": ward_active, "source": "cleric" if ward_active else None}
    )
    ward_mut.update_player_veil_ward = AsyncMock()
    return ctx, mock_db, queries, persistence, ward_mut


async def _invoke(ctx, mock_db, queries, persistence, ward_mut, active=True):
    with patch.object(veil_ward_tools, "publish_game_event", AsyncMock()) as pub:
        raw = await _activate_veil_ward_impl(
            ctx,
            active,
            db_mod=mock_db,
            queries_mod=queries,
            persistence_mod=persistence,
            ward_mutations_mod=ward_mut,
        )
    return json.loads(raw), pub


# --- raise path: eligible casters deduct + flip state + publish -----------------


async def test_eligible_cleric_raises_ward():
    ctx, mock_db, queries, persistence, ward_mut = _mocks(_player("cleric", level=7, focus=10))
    result, pub = await _invoke(ctx, mock_db, queries, persistence, ward_mut)

    assert result["active"] is True
    assert result["source"] == "cleric"
    assert result["deducted"] == {"focus": 4, "stamina": 0}
    persistence.update_player_resources.assert_awaited_once_with("player_1", stamina=None, focus=6, conn=ANY)
    ward_mut.update_player_veil_ward.assert_awaited_once_with("player_1", True, "cleric", conn=ANY)
    # session synced + event published with the minimal {active} payload.
    assert ctx.userdata.veil_ward.active is True
    assert ctx.userdata.veil_ward.source == "cleric"
    pub.assert_awaited_once()
    args = pub.call_args.args
    assert args[1] == E.VEIL_WARD_CHANGED
    assert args[2] == {"active": True}


async def test_paladin_pays_focus_and_stamina():
    ctx, mock_db, queries, persistence, ward_mut = _mocks(_player("paladin", level=10, focus=10, stamina=10))
    result, _pub = await _invoke(ctx, mock_db, queries, persistence, ward_mut)

    assert result["deducted"] == {"focus": 3, "stamina": 3}
    persistence.update_player_resources.assert_awaited_once_with("player_1", stamina=7, focus=7, conn=ANY)


async def test_druid_raises_ward_for_five_focus():
    ctx, mock_db, queries, persistence, ward_mut = _mocks(_player("druid", level=9, focus=10))
    result, _pub = await _invoke(ctx, mock_db, queries, persistence, ward_mut)
    assert result["deducted"] == {"focus": 5, "stamina": 0}


# --- raise path: rejections deduct nothing + write nothing ----------------------


async def test_non_ward_archetype_rejected():
    ctx, mock_db, queries, persistence, ward_mut = _mocks(_player("mage", level=20))
    with pytest.raises(ToolError, match="mage"):
        await _invoke(ctx, mock_db, queries, persistence, ward_mut)
    persistence.update_player_resources.assert_not_awaited()
    ward_mut.update_player_veil_ward.assert_not_awaited()


async def test_below_required_level_rejected():
    ctx, mock_db, queries, persistence, ward_mut = _mocks(_player("cleric", level=6))
    with pytest.raises(ToolError):
        await _invoke(ctx, mock_db, queries, persistence, ward_mut)
    persistence.update_player_resources.assert_not_awaited()
    ward_mut.update_player_veil_ward.assert_not_awaited()


async def test_insufficient_focus_rejected():
    ctx, mock_db, queries, persistence, ward_mut = _mocks(_player("cleric", level=7, focus=2))
    with pytest.raises(ToolError, match="Focus"):
        await _invoke(ctx, mock_db, queries, persistence, ward_mut)
    persistence.update_player_resources.assert_not_awaited()
    ward_mut.update_player_veil_ward.assert_not_awaited()


async def test_insufficient_stamina_rejected():
    # Paladin is the only stamina-costing source (3F+3S): enough Focus, too little Stamina.
    ctx, mock_db, queries, persistence, ward_mut = _mocks(_player("paladin", level=10, focus=10, stamina=2))
    with pytest.raises(ToolError, match="Stamina"):
        await _invoke(ctx, mock_db, queries, persistence, ward_mut)
    persistence.update_player_resources.assert_not_awaited()
    ward_mut.update_player_veil_ward.assert_not_awaited()


async def test_already_active_ward_rejected_no_double_charge():
    ctx, mock_db, queries, persistence, ward_mut = _mocks(_player("cleric", level=7), ward_active=True)
    with pytest.raises(ToolError, match="already active"):
        await _invoke(ctx, mock_db, queries, persistence, ward_mut)
    persistence.update_player_resources.assert_not_awaited()
    ward_mut.update_player_veil_ward.assert_not_awaited()


# --- dismiss path: free, flips inactive -----------------------------------------


async def test_dismiss_active_ward():
    ctx, mock_db, queries, persistence, ward_mut = _mocks(_player("cleric", level=7), ward_active=True)
    result, pub = await _invoke(ctx, mock_db, queries, persistence, ward_mut, active=False)

    assert result["active"] is False
    ward_mut.update_player_veil_ward.assert_awaited_once_with("player_1", False, None, conn=ANY)
    persistence.update_player_resources.assert_not_awaited()  # dismiss is free
    assert ctx.userdata.veil_ward.active is False
    assert ctx.userdata.veil_ward.source is None
    assert pub.call_args.args[2] == {"active": False}


async def test_dismiss_when_inactive_rejected():
    ctx, mock_db, queries, persistence, ward_mut = _mocks(_player("cleric", level=7), ward_active=False)
    with pytest.raises(ToolError):
        await _invoke(ctx, mock_db, queries, persistence, ward_mut, active=False)
    ward_mut.update_player_veil_ward.assert_not_awaited()
