"""Tests for veil_anchor_tools.deploy_veil_anchor (story-012, M24).

A crafted Veil Anchor is set down and wards the place it is set down in. The crafting IS the cost,
so deploying deducts no Focus and no Stamina — which is exactly why this cannot route through
activate_veil_ward: that tool gates on source.tool_raisable, and artificer is tool_raisable=False on
purpose (story-005), so a 0-cost class cannot raise a free ward at will.

The two anchors differ, and the difference is data (veil_ward.VEIL_ANCHORS), not a conditional:
  small -> REAL_TIME 1h, dismissible, CONSUMED on use
  large -> PERMANENT (expires_at NULL), NOT dismissible, NOT consumed

Drives _deploy_veil_anchor_impl directly with injected mock modules, mirroring test_veil_ward_tools.
"""

import json
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import ANY, AsyncMock, MagicMock, patch

import pytest
from livekit.agents.llm import ToolError
from sample_fixtures import make_context, make_db_mod

import db
import db_mutations_veil_ward
import event_types as E
import veil_anchor_tools
import veil_ward
import ward_resolution
from veil_anchor_tools import _deploy_veil_anchor_impl
from veil_ward import WardScope

_SMALL = "veil_ward_anchor_small"
_LARGE = "veil_ward_anchor_large"
_SCOPE = WardScope.location("accord_guild_hall")  # make_context's default location

# The real resolver over a mocked read_active_ward leaf, so the already-warded gate runs for real.
_REAL_RESOLUTION = MagicMock()
_REAL_RESOLUTION.resolve_scope_ward = ward_resolution.resolve_scope_ward


def _payload(active, *, scope_kind=None, scope_id=None, source=None) -> dict:
    return {"active": active, "scope_kind": scope_kind, "scope_id": scope_id, "source": source}


def _mocks(*, holds_item=True, covering_ward=None):
    ctx = make_context()
    mock_db, _conn = make_db_mod()
    queries = MagicMock()
    queries.get_inventory_item = AsyncMock(return_value={"quantity": 1, "equipped": False} if holds_item else None)
    inventory = MagicMock()
    inventory.transact_inventory = AsyncMock(return_value=0)
    ward_mut = MagicMock()
    ward_mut.write_ward = AsyncMock()
    # The already-warded gate resolves through this leaf; None = nothing covers the scope.
    ward_mut.read_active_ward = AsyncMock(return_value=covering_ward)
    return ctx, mock_db, queries, inventory, ward_mut


async def _deploy(ctx, mock_db, queries, inventory, ward_mut, item_id=_SMALL):
    with patch.object(veil_anchor_tools.veil_ward_events, "publish_game_event", AsyncMock()) as pub:
        raw = await _deploy_veil_anchor_impl(
            ctx,
            item_id,
            db_mod=mock_db,
            queries_mod=queries,
            inventory_mutations_mod=inventory,
            ward_mutations_mod=ward_mut,
            resolution_mod=_REAL_RESOLUTION,
        )
    return json.loads(raw), pub


class TestDeploySmallAnchor:
    async def test_writes_a_one_hour_artificer_ward(self):
        ctx, mock_db, queries, inventory, ward_mut = _mocks()
        before = datetime.now(UTC)
        result, _pub = await _deploy(ctx, mock_db, queries, inventory, ward_mut, _SMALL)

        assert result["active"] is True
        assert result["source"] == "artificer"
        ward_mut.write_ward.assert_awaited_once()
        scope, source, expires_at = ward_mut.write_ward.call_args.args
        assert scope == _SCOPE
        assert source == "artificer"
        # An hour out, give or take the test's own execution time.
        assert timedelta(minutes=59) < expires_at - before < timedelta(minutes=61)
        assert ward_mut.write_ward.call_args.kwargs["dismissible"] is True

    async def test_consumes_the_anchor(self):
        ctx, mock_db, queries, inventory, ward_mut = _mocks()
        await _deploy(ctx, mock_db, queries, inventory, ward_mut, _SMALL)
        inventory.transact_inventory.assert_awaited_once_with(ctx.userdata.player_id, _SMALL, -1, conn=ANY)

    async def test_deducts_no_focus_and_no_stamina(self):
        # The crafting was the cost. A resource write here would double-charge the player.
        ctx, mock_db, queries, inventory, ward_mut = _mocks()
        result, _pub = await _deploy(ctx, mock_db, queries, inventory, ward_mut, _SMALL)
        assert result["deducted"] == {"focus": 0, "stamina": 0}
        assert not hasattr(queries, "update_player_resources") or not queries.update_player_resources.called

    async def test_publishes_the_resolved_ward_and_syncs_the_mirror(self):
        ctx, mock_db, queries, inventory, ward_mut = _mocks()
        _result, pub = await _deploy(ctx, mock_db, queries, inventory, ward_mut, _SMALL)
        assert ctx.userdata.location_ward is not None
        assert ctx.userdata.location_ward["source"] == "artificer"
        assert pub.call_args.args[1] == E.VEIL_WARD_CHANGED
        assert pub.call_args.args[2] == _payload(
            True, scope_kind="location", scope_id="accord_guild_hall", source="artificer"
        )


class TestDeployLargeAnchor:
    async def test_writes_a_permanent_undismissible_ward(self):
        ctx, mock_db, queries, inventory, ward_mut = _mocks()
        result, _pub = await _deploy(ctx, mock_db, queries, inventory, ward_mut, _LARGE)

        assert result["active"] is True
        _scope, source, expires_at = ward_mut.write_ward.call_args.args
        assert source == "artificer"  # a crafted object names its maker, not "sacred_site"
        assert expires_at is None  # PERMANENT — the row never lapses against NOW()
        assert ward_mut.write_ward.call_args.kwargs["dismissible"] is False

    async def test_is_not_consumed(self):
        # "not consumed" per items.json. The monolith stays in the pack; only the ward is laid down.
        ctx, mock_db, queries, inventory, ward_mut = _mocks()
        await _deploy(ctx, mock_db, queries, inventory, ward_mut, _LARGE)
        inventory.transact_inventory.assert_not_awaited()


class TestDeployRefusals:
    async def test_unknown_item_is_refused_before_any_write(self):
        ctx, mock_db, queries, inventory, ward_mut = _mocks()
        with pytest.raises(ToolError, match="not a Veil Anchor"):
            await _deploy(ctx, mock_db, queries, inventory, ward_mut, "iron_dagger")
        ward_mut.write_ward.assert_not_awaited()
        inventory.transact_inventory.assert_not_awaited()

    async def test_an_anchor_the_player_does_not_hold_is_refused(self):
        ctx, mock_db, queries, inventory, ward_mut = _mocks(holds_item=False)
        with pytest.raises(ToolError, match="not in inventory"):
            await _deploy(ctx, mock_db, queries, inventory, ward_mut, _SMALL)
        ward_mut.write_ward.assert_not_awaited()

    async def test_deploying_into_an_already_warded_scope_is_refused(self):
        """The large anchor is not consumed, so an ungated redeploy would write unbounded permanent,
        non-dismissible rows that dismiss_ward can never remove. Mirrors activate_veil_ward's gate:
        a second ward over a covered party buys nothing."""
        covering = {"source": "cleric", "expires_at": None, "dismissible": True}
        ctx, mock_db, queries, inventory, ward_mut = _mocks(covering_ward=covering)
        with pytest.raises(ToolError, match="already active"):
            await _deploy(ctx, mock_db, queries, inventory, ward_mut, _LARGE)
        ward_mut.write_ward.assert_not_awaited()
        inventory.transact_inventory.assert_not_awaited()

    async def test_a_failed_deploy_strands_no_ward_in_memory(self):
        # The phantom-ward lesson (story-005): mirrors sync post-commit, never mid-transaction.
        ctx, mock_db, queries, inventory, ward_mut = _mocks()
        ward_mut.write_ward = AsyncMock(side_effect=RuntimeError("db died mid-write"))
        with pytest.raises(RuntimeError):
            await _deploy(ctx, mock_db, queries, inventory, ward_mut, _SMALL)
        assert ctx.userdata.location_ward is None


# --- AC2, against real SQL -----------------------------------------------------
#
# "Not dismissible" is enforced by dismiss_ward's `AND dismissible` WHERE clause, so a mocked
# ward_mutations_mod cannot prove it — the mock would happily report a deletion. These drive the
# real table (fast-lane dev DB, unique scope id + cleanup, the _db_lifecycle pattern) with exactly
# the values VEIL_ANCHORS supplies, so a flip of large.dismissible to True turns them red.


class TestDeployedAnchorsAgainstRealSql:
    async def _write_anchor(self, pool, scope, item_id):
        anchor = veil_ward.VEIL_ANCHORS[item_id]
        await db_mutations_veil_ward.write_ward(
            scope,
            veil_ward.ANCHOR_SOURCE,
            veil_ward.location_expires_at(anchor.duration, datetime.now(UTC)),
            dismissible=anchor.dismissible,
            conn=pool,
        )

    @pytest.mark.usefixtures("dev_db_pool")
    async def test_a_deployed_large_anchor_survives_dismissal(self):
        # AC2: its lifecycle belongs to crafting, not to activate_veil_ward.
        pool = await db.get_pool()
        scope = WardScope.location(f"test_loc_{uuid.uuid4().hex}")
        try:
            await self._write_anchor(pool, scope, _LARGE)
            await db_mutations_veil_ward.dismiss_ward(scope, conn=pool)

            ward = await db_mutations_veil_ward.read_active_ward(scope, conn=pool)
            assert ward is not None, "the large anchor's ward must survive a dismiss"
            assert ward["source"] == "artificer"
            assert ward["expires_at"] is None  # permanent, never lapses against NOW()
        finally:
            await pool.execute("DELETE FROM veil_wards WHERE scope_id = $1", scope.id)

    @pytest.mark.usefixtures("dev_db_pool")
    async def test_a_deployed_small_anchor_can_be_dismissed(self):
        # The contrast that proves the assertion above is about `dismissible`, not about anchors.
        pool = await db.get_pool()
        scope = WardScope.location(f"test_loc_{uuid.uuid4().hex}")
        try:
            await self._write_anchor(pool, scope, _SMALL)
            await db_mutations_veil_ward.dismiss_ward(scope, conn=pool)
            assert await db_mutations_veil_ward.read_active_ward(scope, conn=pool) is None
        finally:
            await pool.execute("DELETE FROM veil_wards WHERE scope_id = $1", scope.id)
