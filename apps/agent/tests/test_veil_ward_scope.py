from unittest.mock import ANY, AsyncMock

import pytest
from livekit.agents.llm import ToolError
from test_veil_ward_tools import (
    _COMBAT_ID,
    _SCOPE,
    _combat_mod,
    _in_combat,
    _invoke,
    _mocks,
    _payload,
    _player,
)


async def test_cleric_in_combat_raises_encounter_ward():
    """Encounter wards live in CombatState; the database writer refuses encounter scopes."""
    ctx, mock_db, queries, persistence, ward_mut = _mocks(_player("cleric", level=7))
    combat = _in_combat(ctx)
    combat_mod = _combat_mod()
    result, pub = await _invoke(ctx, mock_db, queries, persistence, ward_mut, combat_mod=combat_mod)

    assert result["active"] is True
    assert combat.veil_ward == {"source": "cleric", "rounds_remaining": None}
    combat_mod.save_combat_state.assert_awaited_once()
    ward_mut.write_ward.assert_not_awaited()
    assert ctx.userdata.location_ward is None
    persistence.update_player_resources.assert_awaited_once_with("player_1", stamina=None, focus=6, conn=ANY)
    pub.assert_awaited_once()
    assert pub.call_args.args[2] == _payload(True, scope_kind="encounter", scope_id=_COMBAT_ID, source="cleric")


async def test_paladin_in_combat_seeds_the_round_clock():
    ctx, mock_db, queries, persistence, ward_mut = _mocks(_player("paladin", level=10))
    combat = _in_combat(ctx)
    await _invoke(ctx, mock_db, queries, persistence, ward_mut)
    assert combat.veil_ward == {"source": "paladin", "rounds_remaining": 3}


async def test_rounds_source_out_of_combat_refused():
    """Round durations have no clock outside combat."""
    ctx, mock_db, queries, persistence, ward_mut = _mocks(_player("paladin", level=10))
    assert ctx.userdata.combat_state is None
    with pytest.raises(ToolError, match="combat"):
        await _invoke(ctx, mock_db, queries, persistence, ward_mut)
    persistence.update_player_resources.assert_not_awaited()
    ward_mut.write_ward.assert_not_awaited()


async def test_cleric_out_of_combat_raises_a_location_ward():
    ctx, mock_db, queries, persistence, ward_mut = _mocks(_player("cleric", level=7))
    combat_mod = _combat_mod()
    await _invoke(ctx, mock_db, queries, persistence, ward_mut, combat_mod=combat_mod)

    ward_mut.write_ward.assert_awaited_once_with(_SCOPE, "cleric", None, dismissible=True, conn=ANY)
    combat_mod.save_combat_state.assert_not_awaited()
    assert ctx.userdata.location_ward["source"] == "cleric"


async def test_already_active_encounter_ward_refused():
    ctx, mock_db, queries, persistence, ward_mut = _mocks(_player("cleric", level=7))
    combat = _in_combat(ctx)
    combat.veil_ward = {"source": "paladin", "rounds_remaining": 2}
    combat_mod = _combat_mod()
    with pytest.raises(ToolError, match="already active"):
        await _invoke(ctx, mock_db, queries, persistence, ward_mut, combat_mod=combat_mod)
    persistence.update_player_resources.assert_not_awaited()
    combat_mod.save_combat_state.assert_not_awaited()


async def test_in_combat_raise_refused_when_a_location_ward_already_covers():
    """A covering location ward makes another encounter ward unnecessary."""
    ctx, mock_db, queries, persistence, ward_mut = _mocks(_player("cleric", level=7))
    combat = _in_combat(ctx)
    assert combat.veil_ward is None  # the encounter scope itself is unwarded
    ward_mut.read_active_ward = AsyncMock(
        return_value={"source": "sacred_site", "expires_at": None, "dismissible": False}
    )
    combat_mod = _combat_mod()
    with pytest.raises(ToolError, match="already active"):
        await _invoke(ctx, mock_db, queries, persistence, ward_mut, combat_mod=combat_mod)
    persistence.update_player_resources.assert_not_awaited()
    combat_mod.save_combat_state.assert_not_awaited()
    ward_mut.write_ward.assert_not_awaited()


async def test_druid_raises_ward_for_five_focus():
    ctx, mock_db, queries, persistence, ward_mut = _mocks(_player("druid", level=9, focus=10))
    result, _pub = await _invoke(ctx, mock_db, queries, persistence, ward_mut)
    assert result["deducted"] == {"focus": 5, "stamina": 0}


async def test_dismiss_active_ward():
    ctx, mock_db, queries, persistence, ward_mut = _mocks(_player("cleric", level=7), ward_active=True, remaining=None)
    result, pub = await _invoke(ctx, mock_db, queries, persistence, ward_mut, active=False)

    assert result["active"] is False
    ward_mut.dismiss_ward.assert_awaited_once_with(_SCOPE, conn=ANY)
    persistence.update_player_resources.assert_not_awaited()  # dismiss is free
    assert ctx.userdata.location_ward is None
    assert pub.call_args.args[2] == _payload(False)


async def test_dismiss_publishes_resolved_state_when_a_permanent_ward_survives():
    """Publish resolved coverage: a surviving Sacred site still halves Resonance."""
    sacred = {"source": "sacred_site", "expires_at": None, "dismissible": False}
    ctx, mock_db, queries, persistence, ward_mut = _mocks(
        _player("cleric", level=7), ward_active=True, remaining=sacred
    )
    result, pub = await _invoke(ctx, mock_db, queries, persistence, ward_mut, active=False)

    assert result["active"] is True  # resolved, not the mutated scope's toggle
    assert ctx.userdata.location_ward == sacred
    assert pub.call_args.args[2] == _payload(
        True, scope_kind="location", scope_id="accord_guild_hall", source="sacred_site"
    )


async def test_dismiss_when_no_dismissible_ward_rejected():
    """A permanent Sacred site is not the party's to dispel."""
    ctx, mock_db, queries, persistence, ward_mut = _mocks(_player("cleric", level=7), dismissed=0, remaining=None)
    with pytest.raises(ToolError, match="dismiss"):
        await _invoke(ctx, mock_db, queries, persistence, ward_mut, active=False)


async def test_dismiss_in_combat_clears_the_encounter_ward():
    """Encounter dismissal must use CombatState, not the location-ward database writer."""
    ctx, mock_db, queries, persistence, ward_mut = _mocks(_player("cleric", level=7), remaining=None)
    combat = _in_combat(ctx)
    combat.veil_ward = {"source": "cleric", "rounds_remaining": None}
    combat_mod = _combat_mod()
    result, pub = await _invoke(ctx, mock_db, queries, persistence, ward_mut, active=False, combat_mod=combat_mod)

    assert result["active"] is False
    assert combat.veil_ward is None
    combat_mod.save_combat_state.assert_awaited_once()
    ward_mut.dismiss_ward.assert_not_awaited()  # the veil_wards table is not the encounter's home
    persistence.update_player_resources.assert_not_awaited()  # dismiss is free
    assert ctx.userdata.location_ward is None
    assert pub.call_args.args[2] == _payload(False)


async def test_dismiss_in_combat_still_warded_when_a_location_ward_covers():
    """Dropping an encounter ward does not drop a covering Sacred site."""
    sacred = {"source": "sacred_site", "expires_at": None, "dismissible": False}
    ctx, mock_db, queries, persistence, ward_mut = _mocks(_player("cleric", level=7), remaining=sacred)
    combat = _in_combat(ctx)
    combat.veil_ward = {"source": "cleric", "rounds_remaining": None}
    result, pub = await _invoke(ctx, mock_db, queries, persistence, ward_mut, active=False)

    assert combat.veil_ward is None  # the encounter ward is gone...
    assert result["active"] is True  # ...but the party is still warded by the location
    assert ctx.userdata.location_ward == sacred  # the LOCATION mirror, refreshed from a location read
    assert pub.call_args.args[2] == _payload(
        True, scope_kind="location", scope_id="accord_guild_hall", source="sacred_site"
    )


async def test_dismiss_in_combat_falls_through_to_a_covering_location_ward():
    """Dismiss the innermost active scope, including a pre-fight location ward."""
    ctx, mock_db, queries, persistence, ward_mut = _mocks(_player("cleric", level=7), dismissed=1, remaining=None)
    combat = _in_combat(ctx)
    combat.veil_ward = None  # the fight raised none; the ward predates it
    combat_mod = _combat_mod()
    result, pub = await _invoke(ctx, mock_db, queries, persistence, ward_mut, active=False, combat_mod=combat_mod)

    assert result["active"] is False
    ward_mut.dismiss_ward.assert_awaited_once_with(_SCOPE, conn=ANY)  # reached the location scope
    combat_mod.save_combat_state.assert_not_awaited()  # no encounter ward to clear
    assert ctx.userdata.location_ward is None
    assert pub.call_args.args[2] == _payload(False)


async def test_dismiss_refuses_honestly_when_the_surviving_ward_is_undismissable():
    """Refuse an undismissible Sacred site without denying that it covers the party."""
    sacred = {"source": "sacred_site", "expires_at": None, "dismissible": False}
    ctx, mock_db, queries, persistence, ward_mut = _mocks(_player("cleric", level=7), dismissed=0, remaining=sacred)
    _in_combat(ctx).veil_ward = None

    with pytest.raises(ToolError, match="cannot be dismissed"):
        await _invoke(ctx, mock_db, queries, persistence, ward_mut, active=False)


async def test_failed_raise_leaves_no_phantom_ward_in_memory():
    """A phantom memory ward would become authoritative for later casts.
    Sync the live state only after its save commits."""
    ctx, mock_db, queries, persistence, ward_mut = _mocks(_player("cleric", level=7))
    combat = _in_combat(ctx)
    combat_mod = _combat_mod()
    combat_mod.save_combat_state = AsyncMock(side_effect=RuntimeError("connection lost"))

    with pytest.raises(RuntimeError):
        await _invoke(ctx, mock_db, queries, persistence, ward_mut, combat_mod=combat_mod)

    assert combat.veil_ward is None


async def test_failed_dismiss_leaves_the_ward_in_memory():
    """Failed dismissal must preserve the database-backed ward in memory."""
    ctx, mock_db, queries, persistence, ward_mut = _mocks(_player("cleric", level=7), remaining=None)
    combat = _in_combat(ctx)
    raised = {"source": "cleric", "rounds_remaining": None}
    combat.veil_ward = raised
    combat_mod = _combat_mod()
    combat_mod.save_combat_state = AsyncMock(side_effect=RuntimeError("connection lost"))

    with pytest.raises(RuntimeError):
        await _invoke(ctx, mock_db, queries, persistence, ward_mut, active=False, combat_mod=combat_mod)

    assert combat.veil_ward == raised


async def test_dismiss_in_combat_with_no_ward_anywhere_rejected():
    """Fall through to location coverage; combat must not trap a dismissible pre-fight ward."""
    ctx, mock_db, queries, persistence, ward_mut = _mocks(_player("cleric", level=7), dismissed=0, remaining=None)
    combat = _in_combat(ctx)
    assert combat.veil_ward is None
    with pytest.raises(ToolError, match="No Veil Ward is active"):
        await _invoke(ctx, mock_db, queries, persistence, ward_mut, active=False)
    ward_mut.dismiss_ward.assert_awaited_once_with(_SCOPE, conn=ANY)  # it reached past the empty encounter
