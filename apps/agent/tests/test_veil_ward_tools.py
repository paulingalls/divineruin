"""Tests for activate_veil_ward (veil_ward_tools.py, story-003 cut-over, M24).

Drives the tool's _impl directly with a mock RunContext + injected mock
queries/persistence/ward-mutations mods, mirroring test_ability_tools.py. The tool is
one polymorphic verb: active=True raises a ward (archetype/level/cost gated), active=False
dismisses it (free). Every user-facing failure is a ToolError raised before any write, so
an unaffordable/ineligible activation deducts nothing.

M24 story-003 moves the ward off the caster's row onto the LOCATION scope. The resource cost
stays per-caster (gate_pool deducts from the raiser alone); the ward it buys is shared, so
"already active" is now a property of the location and dismissal is by scope, not by player.

Encounter-vs-location targeting and per-source durations are story-005: every raise here writes
a location ward with no absolute expiry and dismissible=True, preserving the manual-dismiss
behavior this tool has always had.

The published VEIL_WARD_CHANGED payload is {active, caster_id}; veil_ward_events.publish_game_event
is patched to assert the wire shape (the push moved to its own module in story-004 because arrival
needs it too). story-008 rebuilds the payload as scope-membership.
"""

import json
from unittest.mock import ANY, AsyncMock, MagicMock, patch

import pytest
from livekit.agents.llm import ToolError
from sample_fixtures import make_context, make_db_mod

import event_types as E
import veil_ward_events
from veil_ward import WardScope
from veil_ward_tools import _activate_veil_ward_impl

_SCOPE = WardScope.location("accord_guild_hall")  # make_context's default location


def _player(class_: str = "cleric", level: int = 7, focus: int = 10, stamina: int = 10, player_id="player_1") -> dict:
    return {
        "player_id": player_id,
        "name": "Mara",
        "class": class_,
        "level": level,
        "focus": {"current": focus, "max": 10},
        "stamina": {"current": stamina, "max": 10},
    }


_UNSET = object()


def _mocks(player: dict, *, ward_active: bool = False, party_member_ids=None, dismissed: int = 1, remaining=_UNSET):
    ctx = make_context(party_member_ids=party_member_ids)
    mock_db, _conn = make_db_mod()
    queries = MagicMock()
    queries.get_player = AsyncMock(return_value=player)
    persistence = MagicMock()
    persistence.update_player_resources = AsyncMock()
    existing = {"source": "cleric", "expires_at": None, "dismissible": True} if ward_active else None
    ward_mut = MagicMock()
    # The raise path reads once (the already-warded gate). The dismiss path reads once too, but
    # AFTER deleting, to resolve what still covers the scope (§3) — dismiss tests pass `remaining`.
    ward_mut.read_active_ward = AsyncMock(return_value=existing if remaining is _UNSET else remaining)
    ward_mut.write_ward = AsyncMock()
    ward_mut.dismiss_ward = AsyncMock(return_value=dismissed)
    if ward_active:
        ctx.userdata.location_ward = existing
    return ctx, mock_db, queries, persistence, ward_mut


async def _invoke(ctx, mock_db, queries, persistence, ward_mut, active=True, caster_id=None):
    with patch.object(veil_ward_events, "publish_game_event", AsyncMock()) as pub:
        raw = await _activate_veil_ward_impl(
            ctx,
            active,
            caster_id=caster_id,
            db_mod=mock_db,
            queries_mod=queries,
            persistence_mod=persistence,
            ward_mutations_mod=ward_mut,
        )
    return json.loads(raw), pub


# --- raise path: eligible casters deduct + write a scope ward + publish ----------


async def test_eligible_cleric_raises_ward():
    ctx, mock_db, queries, persistence, ward_mut = _mocks(_player("cleric", level=7, focus=10))
    result, pub = await _invoke(ctx, mock_db, queries, persistence, ward_mut)

    assert result["active"] is True
    assert result["source"] == "cleric"
    assert result["deducted"] == {"focus": 4, "stamina": 0}
    persistence.update_player_resources.assert_awaited_once_with("player_1", stamina=None, focus=6, conn=ANY)
    # The ward is written to the session's LOCATION scope, not to the caster's row.
    ward_mut.write_ward.assert_awaited_once_with(_SCOPE, "cleric", None, dismissible=True, conn=ANY)
    # The scope's ward is mirrored on the SESSION, not on the caster.
    assert ctx.userdata.location_ward is not None
    assert ctx.userdata.location_ward["source"] == "cleric"
    pub.assert_awaited_once()
    args = pub.call_args.args
    assert args[1] == E.VEIL_WARD_CHANGED
    assert args[2] == {"active": True, "caster_id": "player_1"}


async def test_raise_writes_no_absolute_expiry_and_stays_dismissible():
    """story-003 preserves manual-dismiss: no expiry, dismissible. Durations arrive in story-005.

    A source's duration must NOT be consulted here — Paladin's is ROUNDS, and location_expires_at
    raises on ROUNDS by design.
    """
    ctx, mock_db, queries, persistence, ward_mut = _mocks(_player("paladin", level=10))
    await _invoke(ctx, mock_db, queries, persistence, ward_mut)
    _scope, _source, expires_at = ward_mut.write_ward.call_args.args
    assert expires_at is None
    assert ward_mut.write_ward.call_args.kwargs["dismissible"] is True


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
    ward_mut.write_ward.assert_not_awaited()


async def test_below_required_level_rejected():
    ctx, mock_db, queries, persistence, ward_mut = _mocks(_player("cleric", level=6))
    with pytest.raises(ToolError):
        await _invoke(ctx, mock_db, queries, persistence, ward_mut)
    persistence.update_player_resources.assert_not_awaited()
    ward_mut.write_ward.assert_not_awaited()


async def test_insufficient_focus_rejected():
    ctx, mock_db, queries, persistence, ward_mut = _mocks(_player("cleric", level=7, focus=2))
    with pytest.raises(ToolError, match="Focus"):
        await _invoke(ctx, mock_db, queries, persistence, ward_mut)
    persistence.update_player_resources.assert_not_awaited()
    ward_mut.write_ward.assert_not_awaited()


async def test_insufficient_stamina_rejected():
    # Paladin is the only stamina-costing source (3F+3S): enough Focus, too little Stamina.
    ctx, mock_db, queries, persistence, ward_mut = _mocks(_player("paladin", level=10, focus=10, stamina=2))
    with pytest.raises(ToolError, match="Stamina"):
        await _invoke(ctx, mock_db, queries, persistence, ward_mut)
    persistence.update_player_resources.assert_not_awaited()
    ward_mut.write_ward.assert_not_awaited()


async def test_already_warded_scope_rejected_no_double_charge():
    """The ward is scope-owned: a scope already carrying one cannot be warded again."""
    ctx, mock_db, queries, persistence, ward_mut = _mocks(_player("cleric", level=7), ward_active=True)
    with pytest.raises(ToolError, match="already active"):
        await _invoke(ctx, mock_db, queries, persistence, ward_mut)
    ward_mut.read_active_ward.assert_awaited_once_with(_SCOPE, conn=ANY)
    persistence.update_player_resources.assert_not_awaited()
    ward_mut.write_ward.assert_not_awaited()


async def test_second_member_cannot_re_raise_a_warded_scope():
    """A ward raised by one member covers the whole scope; another member's raise is refused free."""
    ctx, mock_db, queries, persistence, ward_mut = _mocks(
        _player("druid", level=9, player_id="player_2"), ward_active=True, party_member_ids=["player_2"]
    )
    with pytest.raises(ToolError, match="already active"):
        await _invoke(ctx, mock_db, queries, persistence, ward_mut, caster_id="player_2")
    persistence.update_player_resources.assert_not_awaited()
    ward_mut.write_ward.assert_not_awaited()


# --- dismiss path: free, scope-wide ---------------------------------------------


async def test_dismiss_active_ward():
    ctx, mock_db, queries, persistence, ward_mut = _mocks(_player("cleric", level=7), ward_active=True, remaining=None)
    result, pub = await _invoke(ctx, mock_db, queries, persistence, ward_mut, active=False)

    assert result["active"] is False
    # Dismissal is by SCOPE, not by player — the ward is not the raiser's to hold (§5).
    ward_mut.dismiss_ward.assert_awaited_once_with(_SCOPE, conn=ANY)
    persistence.update_player_resources.assert_not_awaited()  # dismiss is free
    assert ctx.userdata.location_ward is None
    assert pub.call_args.args[2] == {"active": False, "caster_id": "player_1"}


async def test_dismiss_publishes_resolved_state_when_a_permanent_ward_survives():
    """§3: dismiss spares a Sacred site, so the party is STILL warded. Say so, or the light lies.

    dismiss_ward deletes only dismissible rows. Publishing active=False here would turn the ward
    indicator off while every in-scope caster's Resonance is still being halved.
    """
    sacred = {"source": "sacred_site", "expires_at": None, "dismissible": False}
    ctx, mock_db, queries, persistence, ward_mut = _mocks(
        _player("cleric", level=7), ward_active=True, remaining=sacred
    )
    result, pub = await _invoke(ctx, mock_db, queries, persistence, ward_mut, active=False)

    assert result["active"] is True  # resolved, not the mutated scope's toggle
    assert ctx.userdata.location_ward == sacred
    assert pub.call_args.args[2] == {"active": True, "caster_id": "player_1"}


async def test_dismiss_when_no_dismissible_ward_rejected():
    """Nothing deleted means nothing dismissible covered the scope — fail loud, never silently no-op.

    This also covers a scope held only by a permanent ward (a Sacred site is not the party's to
    dispel): dismiss_ward deletes 0 rows and the tool refuses.
    """
    ctx, mock_db, queries, persistence, ward_mut = _mocks(_player("cleric", level=7), dismissed=0, remaining=None)
    with pytest.raises(ToolError, match="dismiss"):
        await _invoke(ctx, mock_db, queries, persistence, ward_mut, active=False)


# --- non-primary caster: resolves via member_state(caster_id), not the primary facade -----


async def test_non_primary_member_raises_scope_ward_and_pays_alone():
    """Cost is per-caster; the ward it buys is scope-owned."""
    player = _player("cleric", level=7, focus=10, player_id="player_2")
    ctx, mock_db, queries, persistence, ward_mut = _mocks(player, party_member_ids=["player_2"])
    result, pub = await _invoke(ctx, mock_db, queries, persistence, ward_mut, caster_id="player_2")

    assert result["active"] is True
    queries.get_player.assert_awaited_once_with("player_2", conn=ANY, for_update=True)
    persistence.update_player_resources.assert_awaited_once_with("player_2", stamina=None, focus=6, conn=ANY)
    ward_mut.write_ward.assert_awaited_once_with(_SCOPE, "cleric", None, dismissible=True, conn=ANY)
    # One shared ward on the session — a non-primary raiser does not get a private one.
    assert ctx.userdata.location_ward is not None
    assert pub.call_args.args[2] == {"active": True, "caster_id": "player_2"}


async def test_non_primary_member_dismisses_scope_ward():
    ctx, mock_db, queries, persistence, ward_mut = _mocks(
        _player("cleric", level=7, player_id="player_2"),
        ward_active=True,
        party_member_ids=["player_2"],
        remaining=None,
    )
    result, pub = await _invoke(ctx, mock_db, queries, persistence, ward_mut, active=False, caster_id="player_2")

    assert result["active"] is False
    ward_mut.dismiss_ward.assert_awaited_once_with(_SCOPE, conn=ANY)
    assert ctx.userdata.location_ward is None
    assert pub.call_args.args[2] == {"active": False, "caster_id": "player_2"}


async def test_unknown_caster_id_raises_tool_error_not_value_error():
    # caster_id is untrusted LLM input: a non-party id must surface as a narratable ToolError
    # (not a raw member_state ValueError) and touch nothing.
    ctx, mock_db, queries, persistence, ward_mut = _mocks(_player("cleric", level=7))
    with pytest.raises(ToolError):
        await _invoke(ctx, mock_db, queries, persistence, ward_mut, caster_id="not_in_party")
    queries.get_player.assert_not_awaited()
    ward_mut.write_ward.assert_not_awaited()
