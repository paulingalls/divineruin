"""Veil Ward activation tool for the DM agent (M24 story-005: scope targeting).

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

Scope (story-005): a raise targets the ENCOUNTER while the party is in a fight (the ward rides
CombatState and dies with the combat row) and the LOCATION otherwise (a veil_wards row whose
expires_at comes from the source's duration). Dismissal targets that same innermost scope and
never cascades — a Sacred site under a fight is not the fight's to dispel. Both paths answer
"is the party warded?" through ward_resolution.resolve_scope_ward, never by reading one scope.

Mirrors the ability_tools seam: a thin @function_tool wrapper over an _impl with module-injection
keyword args (db_mod/queries_mod/persistence_mod/ward_mutations_mod/ward_mod/combat_mod/
resolution_mod) for test mocking, a single db.transaction() block, and ToolError for every
user-facing failure. The publish lands on the session's game_events channel post-commit,
mirroring cast_spell.
"""

import json
import logging
from datetime import UTC, datetime

from livekit.agents.llm import ToolError, function_tool
from livekit.agents.voice import RunContext

import ability_persistence
import db
import db_mutations
import db_mutations_veil_ward
import db_queries
import veil_ward
import veil_ward_events
import ward_resolution
from db_errors import db_tool
from resource_costs import gate_pool
from session_data import SessionData
from veil_ward import WardDurationKind

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
    Focus/Stamina cost, rejecting if the caster is ineligible or can't afford it. A Paladin's
    ward lasts a few rounds, so it can only be raised in combat. While a ward is active, casting
    generates half the Resonance and Hollow Echo rolls are milder — for EVERY caster present,
    not just the one who raised it, so a second raise is refused while one is already up.
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
    combat_mod=db_mutations,
    resolution_mod=ward_resolution,
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

    # The ward belongs to the scope the party stands in, never to the caster. In a fight that is
    # the ENCOUNTER (it dies with the combat row); otherwise it is the LOCATION.
    combat = session.combat_state
    scope = (
        veil_ward.WardScope.encounter(combat.combat_id)
        if combat is not None
        else veil_ward.WardScope.location(session.location_id)
    )

    if not active:
        return await _dismiss_impl(
            session,
            pid,
            db_mod=db_mod,
            ward_mutations_mod=ward_mutations_mod,
            combat_mod=combat_mod,
            resolution_mod=resolution_mod,
        )

    expires_at: datetime | None = None  # a location ward's absolute clock; None for encounter wards

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

        # A ROUNDS ward is combat-only: 3 rounds are meaningless where no rounds elapse (§4).
        # This must precede the write — location_expires_at RAISES on a ROUNDS duration, so
        # without this gate an out-of-combat Paladin gets a crash instead of a narratable refusal.
        if source.duration.kind is WardDurationKind.ROUNDS and combat is None:
            raise ToolError(f"A {archetype}'s Veil Ward lasts a few rounds; raise it in combat.")

        # The ward is scope-owned: an already-warded party refuses a second raise, whichever
        # member attempts it. Two casters cannot double-charge themselves for one shared ward.
        #
        # The question is "is the PARTY warded?", not "is the scope I am about to write warded?" —
        # §3's covering-scope OR. A party fighting on a Sacred site is already warded by the
        # location, so an encounter raise would buy nothing and charge for it. resolve_scope_ward
        # is the one place that OR lives; re-deriving it here is the drift this milestone removes.
        if await resolution_mod.resolve_scope_ward(session, conn=conn, ward_mutations_mod=ward_mutations_mod):
            raise ToolError("A Veil Ward is already active.")

        # Gate Focus then Stamina (fail-loud, pure); each returns the post-deduct
        # value or None when its cost is 0. One write below applies both.
        new_focus = gate_pool(player, "focus", source.focus, label="a Veil Ward")
        new_stamina = gate_pool(player, "stamina", source.stamina, label="a Veil Ward")
        if new_focus is not None or new_stamina is not None:
            await persistence_mod.update_player_resources(pid, stamina=new_stamina, focus=new_focus, conn=conn)

        if combat is not None:
            # rounds_remaining seeds the WRAP-beat clock story-006 ticks. Non-ROUNDS sources have
            # no round clock and carry None — the fight's end is their expiry either way.
            combat.veil_ward = {"source": archetype, "rounds_remaining": source.duration.rounds}
            await combat_mod.save_combat_state(combat.combat_id, combat.to_dict(), conn=conn)
        else:
            expires_at = ward_mod.location_expires_at(source.duration, datetime.now(UTC))
            await ward_mutations_mod.write_ward(scope, archetype, expires_at, dismissible=True, conn=conn)

    # Transaction committed — push the toggle. The ward is scope-owned, so it lands on the
    # session, not on the caster who paid for it. location_ward is a LOCATION mirror: an
    # encounter ward already has its one home on CombatState and must not be copied into it.
    if combat is None:
        session.location_ward = {"source": archetype, "expires_at": expires_at, "dismissible": True}
    await veil_ward_events.publish_veil_ward_changed(session, True, pid)
    return json.dumps(
        {
            "active": True,
            "source": archetype,
            "scope": scope.kind.value,
            "deducted": {"focus": source.focus, "stamina": source.stamina},
        }
    )


async def _dismiss_impl(
    session: SessionData, pid: str, *, db_mod, ward_mutations_mod, combat_mod, resolution_mod
) -> str:
    """Dismiss the ward over the party's innermost scope (free). Fails loud when it has none.

    Any in-scope member may dismiss — the ward is not the raiser's to hold (§5).

    ONE scope is dismissed, never a cascade: in a fight that is the ENCOUNTER, whose ward lives on
    CombatState. A covering location ward (a Sacred site, or one raised before the fight) is not
    the fight's to dispel, so an in-combat dismiss with no encounter ward refuses rather than
    reaching past its scope to delete it.

    Out of combat, the delete COUNT is the authority, not a prior read: a scope covered only by a
    permanent ward deletes nothing, and refusing is the honest answer.
    """
    combat = session.combat_state
    async with db_mod.transaction() as conn:
        if combat is not None:
            if combat.veil_ward is None:
                raise ToolError("No Veil Ward is active to dismiss.")
            combat.veil_ward = None
            await combat_mod.save_combat_state(combat.combat_id, combat.to_dict(), conn=conn)
        elif not await ward_mutations_mod.dismiss_ward(veil_ward.WardScope.location(session.location_id), conn=conn):
            raise ToolError("No Veil Ward is active to dismiss.")

        # §3: publish the RESOLVED state, never the toggle of the scope we just mutated. Dismissing
        # the encounter ward leaves a Sacred site covering the party; dismiss_ward likewise spares
        # non-dismissible rows. Reporting active=False in either case would turn the ward light off
        # while every in-scope caster's Resonance is still being halved.
        remaining = await resolution_mod.resolve_scope_ward(session, conn=conn, ward_mutations_mod=ward_mutations_mod)
        # location_ward is a LOCATION mirror: refresh it from the location scope alone, so an
        # encounter ward is never copied into the slot that answers "what wards this place?".
        location_ward = await ward_mutations_mod.read_active_ward(
            veil_ward.WardScope.location(session.location_id), conn=conn
        )

    session.location_ward = location_ward
    await veil_ward_events.publish_veil_ward_changed(session, remaining is not None, pid)
    return json.dumps({"active": remaining is not None})
