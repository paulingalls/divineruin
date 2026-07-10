"""Deploy a crafted Veil Anchor: the item-use path that lays down an artificer-sourced ward (M24).

story-007 shipped the two anchor recipes and items; nothing set them down. A player could craft an
anchor into their inventory and it would sit there, because the agent has no item-use verb —
``inventory_tools.transact`` moves goods and nothing else, and ``write_ward``'s only production
caller raises wards at will.

This cannot route through ``activate_veil_ward``. That tool gates on ``source.tool_raisable``, and
``artificer`` is ``tool_raisable=False`` deliberately (story-005): the artificer's ward costs 0 Focus
and 0 Stamina, so a raise-at-will path would hand every level-7 artificer a free ward. Here the cost
was already paid — at the workbench. Deploying deducts nothing.

The two anchors differ, and ``veil_ward.VEIL_ANCHORS`` holds the difference as data rather than as a
conditional on the item id: the small anchor wards for an hour and is consumed; the large one wards
permanently, cannot be dismissed, and stays in the pack.

Mirrors ``veil_ward_tools``' seam: one ``db_mod.transaction()``, ``ToolError`` for every user-facing
failure BEFORE any write, and in-memory mirrors synced only after the commit — so a rolled-back
deploy leaves no phantom ward behind (story-005) and leaks no client event.

M25 Phase-5 story-003 folds the standing ``@function_tool`` wrapper into ``activate_tools.activate``
(reserved anchor-item-id path) — ``_deploy_veil_anchor_impl`` is now called only from there.
"""

import json
import logging
from datetime import UTC, datetime

from livekit.agents.llm import ToolError
from livekit.agents.voice import RunContext

import db
import db_mutations_inventory
import db_mutations_veil_ward
import db_queries
import veil_ward_events
import ward_resolution
from session_data import SessionData
from veil_ward import ANCHOR_SOURCE, VEIL_ANCHORS, WardScope, location_expires_at

logger = logging.getLogger("divineruin.tools")


async def _deploy_veil_anchor_impl(
    context: RunContext[SessionData],
    item_id: str,
    *,
    db_mod=db,
    queries_mod=db_queries,
    inventory_mutations_mod=db_mutations_inventory,
    ward_mutations_mod=db_mutations_veil_ward,
    resolution_mod=ward_resolution,
) -> str:
    context.disallow_interruptions()
    session: SessionData = context.userdata
    logger.info("deploy_veil_anchor called: item_id=%s player=%s", item_id, session.player_id)

    # item_id is untrusted LLM input. Fail loud on anything that is not an anchor rather than
    # silently warding nothing, or warding on behalf of an item that has no ward to give.
    anchor = VEIL_ANCHORS.get(item_id)
    if anchor is None:
        raise ToolError(f"'{item_id}' is not a Veil Anchor.")

    scope = WardScope.location(session.location_id)
    expires_at = location_expires_at(anchor.duration, datetime.now(UTC))

    async with db_mod.transaction() as conn:
        # Lock the stack before reading it, the same for_update read inventory_tools._lose does:
        # two concurrent deploys of one small anchor must not both consume it.
        slot = await queries_mod.get_inventory_item(session.player_id, item_id, conn=conn, for_update=True)
        if slot is None:
            raise ToolError(f"Item '{item_id}' not in inventory.")

        # A ward already covering the party makes this deploy buy nothing — the same question
        # activate_veil_ward's gate asks, through the same resolver (§3's covering-scope OR).
        # It also bounds the large anchor: it is NOT consumed, so an ungated redeploy would write
        # unbounded permanent, non-dismissible rows that dismiss_ward can never remove.
        if await resolution_mod.resolve_scope_ward(session, conn=conn, ward_mutations_mod=ward_mutations_mod):
            raise ToolError("A Veil Ward is already active.")

        await ward_mutations_mod.write_ward(scope, ANCHOR_SOURCE, expires_at, dismissible=anchor.dismissible, conn=conn)
        if anchor.consumed:
            await inventory_mutations_mod.transact_inventory(session.player_id, item_id, -1, conn=conn)

    # Committed — NOW sync the in-memory mirror and push, so a rolled-back deploy leaves the session
    # pristine and publishes nothing (story-005's phantom-ward contract).
    ward = {"source": ANCHOR_SOURCE, "expires_at": expires_at, "dismissible": anchor.dismissible}
    session.location_ward = ward
    await veil_ward_events.publish_veil_ward_changed(session, ward, scope)
    return json.dumps(
        {
            "active": True,
            "source": ANCHOR_SOURCE,
            "scope": scope.kind.value,
            "consumed": anchor.consumed,
            "dismissible": anchor.dismissible,
            "deducted": {"focus": 0, "stamina": 0},
        }
    )
