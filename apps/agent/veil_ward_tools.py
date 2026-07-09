"""Veil Ward activation tool for the DM agent (M24 story-003 cut-over).

activate_veil_ward is one polymorphic verb (decision veil-ward-one-tool): active=True raises
a ward, active=False dismisses it. Raising gates the caster's source (must be a WARD_SOURCES
entry whose ``tool_raisable`` is set), level, and Focus/Stamina cost, deducts on success, writes
the scope ward, and pushes a VEIL_WARD_CHANGED event; every user-facing failure is a ToolError
raised BEFORE any write, so an ineligible/unaffordable activation deducts nothing.

The ``tool_raisable`` gate is not a formality: WARD_SOURCES also carries the Artificer anchor and
the Sacred site, whose costs are 0 Focus / 0 Stamina. Gating on key presence would let any
level-7 artificer — a real playable class — raise a free ward from this tool.

The ward is SCOPE-owned (veil_ward_scope_model.md §1). The Focus/Stamina cost is per-caster —
gate_pool deducts from the raiser alone — but the ward it buys covers every caster in the scope.
So an already-warded scope refuses a second raise (no double charge for one shared ward), and
dismissal is by scope: any in-scope member may drop it, for free, because it was never the
raiser's to hold (§5).

Scope (story-003): every raise writes a LOCATION ward with no absolute expiry, dismissible —
preserving the manual-dismiss behavior this tool has always had. Encounter targeting and the
per-source durations are story-005; the Artificer crafted-item and Sacred-site passive sources
land there too.

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
import veil_ward_events
from db_errors import db_tool
from resource_costs import gate_pool
from session_data import SessionData

logger = logging.getLogger("divineruin.tools")


@function_tool()
@db_tool
async def activate_veil_ward(
    context: RunContext[SessionData],
    active: bool = True,
    caster_id: str | None = None,
) -> str:
    """Raise or dismiss a Veil Ward. Call when the caster reinforces the Veil to cast more
    safely (active=true, the default) or drops the ward (active=false). Raising requires a
    ward-capable archetype (Cleric, Druid, Paladin) at sufficient level and deducts its
    Focus/Stamina cost, rejecting if the caster is ineligible or can't afford it. While a ward
    is active, casting generates half the Resonance and Hollow Echo rolls are milder.
    Dismissing is free and requires an active ward. caster_id defaults to the speaking player;
    pass a party member's id when a non-primary member raises/dismisses their own ward."""
    return await _activate_veil_ward_impl(context, active, caster_id=caster_id)


async def _activate_veil_ward_impl(
    context: RunContext[SessionData],
    active: bool = True,
    *,
    caster_id: str | None = None,
    db_mod=db,
    queries_mod=db_queries,
    persistence_mod=ability_persistence,
    ward_mutations_mod=db_mutations_veil_ward,
    ward_mod=veil_ward,
) -> str:
    context.disallow_interruptions()
    session: SessionData = context.userdata
    pid = caster_id or session.player_id
    # caster_id is untrusted LLM input at the tool boundary; member_state fails loud (ValueError)
    # on a non-party id — convert to the sanctioned narratable ToolError so the DM can recover.
    try:
        session.member_state(pid)  # validation only — the ward is scope-owned, not the caster's
    except ValueError as e:
        raise ToolError(f"Unknown party member: {pid}") from e
    logger.info("activate_veil_ward called: active=%s player=%s", active, pid)

    # The ward belongs to the scope the party stands in, never to the caster. story-005 adds
    # encounter targeting when in combat; today every raise is location-scoped.
    scope = veil_ward.WardScope.location(session.location_id)

    if not active:
        return await _dismiss_impl(session, pid, scope, db_mod=db_mod, ward_mutations_mod=ward_mutations_mod)

    async with db_mod.transaction() as conn:
        player = await queries_mod.get_player(pid, conn=conn, for_update=True)
        if player is None:
            raise ToolError(f"Unknown player: {pid}")

        # Eligibility gates FIRST, all before any write (AC: ineligible/unaffordable deducts
        # nothing). Archetype + level come from the already-fetched player; the already-active
        # check (no double-charge) reads ward state only once the caster is eligible.
        archetype = player.get("class")
        source = ward_mod.WARD_SOURCES.get(archetype)
        if source is None:
            raise ToolError(f"{archetype} cannot raise a Veil Ward.")
        # Gate on the SOURCE, not on key presence, and before the level check: an artificer has a
        # ward source (a crafted anchor wards for an hour) but cannot will one into being, and
        # its cost is 0/0 — a presence-only gate would hand an eligible artificer a free ward.
        if not source.tool_raisable:
            raise ToolError(f"A {archetype} ward cannot be raised at will.")
        level = player.get("level", 1)
        if level < source.min_level:
            raise ToolError(f"A Veil Ward requires level {source.min_level}; you are level {level}.")

        # The ward is scope-owned: an already-warded SCOPE refuses a second raise, whichever
        # member attempts it. Two casters cannot double-charge themselves for one shared ward.
        if await ward_mutations_mod.read_active_ward(scope, conn=conn) is not None:
            raise ToolError("A Veil Ward is already active.")

        # Gate Focus then Stamina (fail-loud, pure); each returns the post-deduct
        # value or None when its cost is 0. One write below applies both.
        new_focus = gate_pool(player, "focus", source.focus, label="a Veil Ward")
        new_stamina = gate_pool(player, "stamina", source.stamina, label="a Veil Ward")
        if new_focus is not None or new_stamina is not None:
            await persistence_mod.update_player_resources(pid, stamina=new_stamina, focus=new_focus, conn=conn)
        # No absolute expiry, dismissible — today's manual-dismiss behavior, unchanged. The
        # source's duration is deliberately NOT consulted: Paladin's is ROUNDS, which has no
        # absolute clock. Per-source durations and encounter targeting arrive in story-005.
        await ward_mutations_mod.write_ward(scope, archetype, None, dismissible=True, conn=conn)

    # Transaction committed — refresh the session's HUD mirror and push the toggle. The ward is
    # scope-owned, so it lands on the session, not on the caster who paid for it.
    session.location_ward = {"source": archetype, "expires_at": None, "dismissible": True}
    await veil_ward_events.publish_veil_ward_changed(session, True, pid)
    return json.dumps(
        {"active": True, "source": archetype, "deducted": {"focus": source.focus, "stamina": source.stamina}}
    )


async def _dismiss_impl(session: SessionData, pid: str, scope, *, db_mod, ward_mutations_mod) -> str:
    """Dismiss the scope's ward (free). Fails loud when nothing dismissible covers the caster.

    Any in-scope member may dismiss — the ward is not the raiser's to hold (§5). The delete
    count, not a prior read, is the authority: a scope covered only by a permanent ward
    (a Sacred site) deletes nothing, and refusing is the honest answer.
    """
    async with db_mod.transaction() as conn:
        if not await ward_mutations_mod.dismiss_ward(scope, conn=conn):
            raise ToolError("No Veil Ward is active to dismiss.")
        # §3: publish the RESOLVED state, never the toggle of the scope we just mutated.
        # dismiss_ward spares non-dismissible wards, so a permanent Sacred site can still cover
        # this scope. Reporting active=False there would turn the ward light off while the party's
        # casts are still being halved.
        remaining = await ward_mutations_mod.read_active_ward(scope, conn=conn)

    session.location_ward = remaining
    await veil_ward_events.publish_veil_ward_changed(session, remaining is not None, pid)
    return json.dumps({"active": remaining is not None})
