"""Scope targeting, duration, dismissal, and rollback tests for Veil Ward."""

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

# --- raise path: scope targeting + per-source durations (story-005) --------------


async def test_cleric_in_combat_raises_encounter_ward():
    """In a fight the ward belongs to the ENCOUNTER, which lives on CombatState — never in
    veil_wards (write_ward fails loud on an encounter scope by design)."""
    ctx, mock_db, queries, persistence, ward_mut = _mocks(_player("cleric", level=7))
    combat = _in_combat(ctx)
    combat_mod = _combat_mod()
    result, pub = await _invoke(ctx, mock_db, queries, persistence, ward_mut, combat_mod=combat_mod)

    assert result["active"] is True
    assert combat.veil_ward == {"source": "cleric", "rounds_remaining": None}
    combat_mod.save_combat_state.assert_awaited_once()
    ward_mut.write_ward.assert_not_awaited()
    # location_ward is a LOCATION mirror; an encounter ward must never be written into it.
    assert ctx.userdata.location_ward is None
    persistence.update_player_resources.assert_awaited_once_with("player_1", stamina=None, focus=6, conn=ANY)
    # The raiser's HUD still lights in combat (party-wide fan-out is story-008).
    pub.assert_awaited_once()
    assert pub.call_args.args[2] == _payload(True, scope_kind="encounter", scope_id=_COMBAT_ID, source="cleric")


async def test_paladin_in_combat_seeds_the_round_clock():
    ctx, mock_db, queries, persistence, ward_mut = _mocks(_player("paladin", level=10))
    combat = _in_combat(ctx)
    await _invoke(ctx, mock_db, queries, persistence, ward_mut)
    assert combat.veil_ward == {"source": "paladin", "rounds_remaining": 3}


async def test_rounds_source_out_of_combat_refused():
    """A Paladin's 3 rounds are meaningless where no rounds elapse (§4). Refuse rather than
    write a ward with no clock — and refuse BEFORE any deduction."""
    ctx, mock_db, queries, persistence, ward_mut = _mocks(_player("paladin", level=10))
    assert ctx.userdata.combat_state is None
    with pytest.raises(ToolError, match="combat"):
        await _invoke(ctx, mock_db, queries, persistence, ward_mut)
    persistence.update_player_resources.assert_not_awaited()
    ward_mut.write_ward.assert_not_awaited()


async def test_cleric_out_of_combat_raises_a_location_ward():
    """The same source targets a different scope depending on the fight (AC6)."""
    ctx, mock_db, queries, persistence, ward_mut = _mocks(_player("cleric", level=7))
    combat_mod = _combat_mod()
    await _invoke(ctx, mock_db, queries, persistence, ward_mut, combat_mod=combat_mod)

    ward_mut.write_ward.assert_awaited_once_with(_SCOPE, "cleric", None, dismissible=True, conn=ANY)
    combat_mod.save_combat_state.assert_not_awaited()
    assert ctx.userdata.location_ward["source"] == "cleric"


# --- raise path: "already active" is resolved across BOTH scopes (story-005) -----


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
    """§3's covering-scope OR, at the activation end: a party standing on a Sacred site is
    already warded, so an encounter raise buys nothing and must not charge for it. The gate
    asks "is the party warded?", not "is the scope I am about to write warded?".
    """
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


# --- dismiss path: free, scope-wide ---------------------------------------------


async def test_dismiss_active_ward():
    ctx, mock_db, queries, persistence, ward_mut = _mocks(_player("cleric", level=7), ward_active=True, remaining=None)
    result, pub = await _invoke(ctx, mock_db, queries, persistence, ward_mut, active=False)

    assert result["active"] is False
    # Dismissal is by SCOPE, not by player — the ward is not the raiser's to hold (§5).
    ward_mut.dismiss_ward.assert_awaited_once_with(_SCOPE, conn=ANY)
    persistence.update_player_resources.assert_not_awaited()  # dismiss is free
    assert ctx.userdata.location_ward is None
    assert pub.call_args.args[2] == _payload(False)


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
    assert pub.call_args.args[2] == _payload(
        True, scope_kind="location", scope_id="accord_guild_hall", source="sacred_site"
    )


async def test_dismiss_when_no_dismissible_ward_rejected():
    """Nothing deleted means nothing dismissible covered the scope — fail loud, never silently no-op.

    This also covers a scope held only by a permanent ward (a Sacred site is not the party's to
    dispel): dismiss_ward deletes 0 rows and the tool refuses.
    """
    ctx, mock_db, queries, persistence, ward_mut = _mocks(_player("cleric", level=7), dismissed=0, remaining=None)
    with pytest.raises(ToolError, match="dismiss"):
        await _invoke(ctx, mock_db, queries, persistence, ward_mut, active=False)


# --- dismiss path: in combat it targets the ENCOUNTER scope (story-005) ----------


async def test_dismiss_in_combat_clears_the_encounter_ward():
    """The encounter ward's one home is CombatState — dismissal clears it there, never via
    dismiss_ward (which fails loud on an encounter scope)."""
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
    """Dropping the fight's ward does not drop the Sacred site under it. Publish the RESOLVED
    state (§3), or the ward light goes dark while casts are still being halved."""
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
    """No encounter ward, but a pre-fight location ward still covers the party and still halves
    every cast. Dismiss the innermost ACTIVE scope: refusing here told the player "No Veil Ward is
    active" while their HUD was lit and their Resonance was being halved."""
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
    """A Sacred site is not the party's to dispel — but say THAT, not "no ward is active". The old
    message denied a ward the player could see lit and feel halving their casts."""
    sacred = {"source": "sacred_site", "expires_at": None, "dismissible": False}
    ctx, mock_db, queries, persistence, ward_mut = _mocks(_player("cleric", level=7), dismissed=0, remaining=sacred)
    _in_combat(ctx).veil_ward = None

    with pytest.raises(ToolError, match="cannot be dismissed"):
        await _invoke(ctx, mock_db, queries, persistence, ward_mut, active=False)


async def test_failed_raise_leaves_no_phantom_ward_in_memory():
    """A raise that dies mid-transaction must not strand a ward the DB never got.

    resolve_scope_ward reads combat.veil_ward from MEMORY first, so a phantom would become the
    authoritative answer for every later cast — the exact silent lie M24 exists to remove. The
    ward therefore goes into the save payload, and the live CombatState is synced post-commit.
    """
    ctx, mock_db, queries, persistence, ward_mut = _mocks(_player("cleric", level=7))
    combat = _in_combat(ctx)
    combat_mod = _combat_mod()
    combat_mod.save_combat_state = AsyncMock(side_effect=RuntimeError("connection lost"))

    with pytest.raises(RuntimeError):
        await _invoke(ctx, mock_db, queries, persistence, ward_mut, combat_mod=combat_mod)

    assert combat.veil_ward is None


async def test_failed_dismiss_leaves_the_ward_in_memory():
    """The mirror of the above: a dismiss that dies mid-transaction must not clear a ward the DB
    still holds, or the party's casts keep being halved while the HUD says otherwise."""
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
    """In a fight with no encounter ward, the dismiss falls through to the location scope — and when
    nothing covers that either, it fails loud rather than silently no-opping.

    Supersedes the story-005 rule that a covering location ward "is not the fight's to dismiss":
    that refused a ward the player could see lit and feel halving their casts, with no way to drop
    it until combat ended. Falling through is the honest reading of "dismiss the innermost scope".
    """
    ctx, mock_db, queries, persistence, ward_mut = _mocks(_player("cleric", level=7), dismissed=0, remaining=None)
    combat = _in_combat(ctx)
    assert combat.veil_ward is None
    with pytest.raises(ToolError, match="No Veil Ward is active"):
        await _invoke(ctx, mock_db, queries, persistence, ward_mut, active=False)
    ward_mut.dismiss_ward.assert_awaited_once_with(_SCOPE, conn=ANY)  # it reached past the empty encounter
