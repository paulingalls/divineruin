"""Veil Ward activation tool for the DM agent (story-003, M3.2).

activate_veil_ward is one polymorphic verb (decision veil-ward-one-tool): active=True raises
a ward, active=False dismisses it. Raising gates the caster's archetype (must be a WARD_SOURCES
caster), level, and Focus/Stamina cost, deducts on success, flips the persisted + in-memory
ward state, and pushes a VEIL_WARD_CHANGED event; every user-facing failure is a ToolError
raised BEFORE any write, so an ineligible/unaffordable activation deducts nothing. Dismissing is
free and only requires an active ward. The cast path (story-004) reads session.veil_ward.active
to halve generation.

Scope (M3.2): the Focus/Stamina caster sources (Cleric/Druid/Paladin) in veil_ward.WARD_SOURCES.
Artificer crafted-item and Sacred-site passive (area-scoped world entity) sources are deferred,
as is auto-clear on rest/end_combat — explicit dismiss is the M3.2 off-switch.

Mirrors the ability_tools seam: a thin @function_tool wrapper over an _impl with module-injection
keyword args (db_mod/queries_mod/persistence_mod/ward_mutations_mod/ward_mod) for test mocking, a
single db.transaction() block, and ToolError for every user-facing failure. The publish lands on
the session's game_events channel post-commit, mirroring cast_spell.
"""

import json
import logging

from livekit.agents.llm import ToolError, function_tool
from livekit.agents.voice import RunContext

import ability_persistence
import db
import db_mutations_veil_ward
import db_queries
import veil_ward
from db_errors import db_tool
from event_types import VEIL_WARD_CHANGED
from game_events import publish_game_event
from session_data import SessionData

logger = logging.getLogger("divineruin.tools")


async def _publish_veil_ward_changed(session: SessionData, active: bool) -> None:
    """Push the ward's on/off state to the client as a VEIL_WARD_CHANGED event.

    The payload is the minimal {active} (the HUD shows a glanceable zone indicator); the
    source archetype is narration the DM voices, not wire state.
    """
    await publish_game_event(session.room, VEIL_WARD_CHANGED, {"active": active}, session.event_bus)


@function_tool()
@db_tool
async def activate_veil_ward(
    context: RunContext[SessionData],
    active: bool = True,
) -> str:
    """Raise or dismiss a Veil Ward. Call when the caster reinforces the Veil to cast more
    safely (active=true, the default) or drops the ward (active=false). Raising requires a
    ward-capable archetype (Cleric, Druid, Paladin) at sufficient level and deducts its
    Focus/Stamina cost, rejecting if the caster is ineligible or can't afford it. While a ward
    is active, casting generates half the Resonance and Hollow Echo rolls are milder.
    Dismissing is free and requires an active ward."""
    return await _activate_veil_ward_impl(context, active)


async def _activate_veil_ward_impl(
    context: RunContext[SessionData],
    active: bool = True,
    *,
    db_mod=db,
    queries_mod=db_queries,
    persistence_mod=ability_persistence,
    ward_mutations_mod=db_mutations_veil_ward,
    ward_mod=veil_ward,
) -> str:
    context.disallow_interruptions()
    session: SessionData = context.userdata
    player_id = session.player_id
    logger.info("activate_veil_ward called: active=%s player=%s", active, player_id)

    if not active:
        return await _dismiss_impl(session, player_id, db_mod=db_mod, ward_mutations_mod=ward_mutations_mod)

    async with db_mod.transaction() as conn:
        player = await queries_mod.get_player(player_id, conn=conn, for_update=True)
        if player is None:
            raise ToolError(f"Unknown player: {player_id}")

        # Eligibility gates FIRST, all before any write (AC: ineligible/unaffordable deducts
        # nothing). Archetype + level come from the already-fetched player; the already-active
        # check (no double-charge) reads ward state only once the caster is eligible.
        archetype = player.get("class")
        source = ward_mod.WARD_SOURCES.get(archetype)
        if source is None:
            raise ToolError(f"{archetype} cannot raise a Veil Ward.")
        level = player.get("level", 1)
        if level < source.min_level:
            raise ToolError(f"A Veil Ward requires level {source.min_level}; you are level {level}.")

        if (await ward_mutations_mod.read_player_veil_ward(player_id, conn=conn))["active"]:
            raise ToolError("A Veil Ward is already active.")

        focus_pool = player.get("focus") or {}
        stamina_pool = player.get("stamina") or {}
        current_focus = focus_pool.get("current", 0)
        current_stamina = stamina_pool.get("current", 0)
        if source.focus > 0:
            if "current" not in focus_pool:
                raise ToolError("A Veil Ward costs Focus but you have no Focus pool.")
            if source.focus > current_focus:
                raise ToolError(f"Not enough Focus for a Veil Ward: costs {source.focus}, you have {current_focus}.")
        if source.stamina > 0:
            if "current" not in stamina_pool:
                raise ToolError("A Veil Ward costs Stamina but you have no Stamina pool.")
            if source.stamina > current_stamina:
                raise ToolError(
                    f"Not enough Stamina for a Veil Ward: costs {source.stamina}, you have {current_stamina}."
                )

        new_focus = current_focus - source.focus if source.focus > 0 else None
        new_stamina = current_stamina - source.stamina if source.stamina > 0 else None
        if new_focus is not None or new_stamina is not None:
            await persistence_mod.update_player_resources(player_id, stamina=new_stamina, focus=new_focus, conn=conn)
        await ward_mutations_mod.update_player_veil_ward(player_id, True, archetype, conn=conn)

    # Transaction committed — sync the in-memory SSOT and push the HUD toggle.
    session.veil_ward.active = True
    session.veil_ward.source = archetype
    await _publish_veil_ward_changed(session, True)
    return json.dumps(
        {"active": True, "source": archetype, "deducted": {"focus": source.focus, "stamina": source.stamina}}
    )


async def _dismiss_impl(session: SessionData, player_id: str, *, db_mod, ward_mutations_mod) -> str:
    """Dismiss an active ward (free). Fails loud when no ward is active."""
    async with db_mod.transaction() as conn:
        if not (await ward_mutations_mod.read_player_veil_ward(player_id, conn=conn))["active"]:
            raise ToolError("No Veil Ward is active to dismiss.")
        await ward_mutations_mod.update_player_veil_ward(player_id, False, None, conn=conn)

    session.veil_ward.active = False
    session.veil_ward.source = None
    await _publish_veil_ward_changed(session, False)
    return json.dumps({"active": False})
