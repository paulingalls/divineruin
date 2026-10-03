"""Catalog Hollow destruction receipts and transaction-local recipient awards."""

import archetypes
import combat_spatial
import db_mutations_resonance
import ward_resolution
from combat_hollow_resonance import current_total, stage_total
from hollow_resonance import resolve_resonance_on_death


def mark_destroyed(target):
    if target.type != "enemy" or target.hollow is None:
        return False
    target.is_dead = True
    target.hollow_death_resolved = True
    return True


def new_destruction(target, resolved_before, was_fallen, hp_before):
    return target.hollow_death_resolved and not resolved_before and not was_fallen and hp_before > 0


async def accrue_death(session, state, target, *, conn, queries):
    spatial = combat_spatial.require_spatial(state)
    origin = combat_spatial.position(spatial, target.id)
    ward = await ward_resolution.resolve_scope_ward(session, conn=conn, combat_state=state)
    delta = resolve_resonance_on_death(target.hollow["resonance_on_death"], ward is not None)
    if delta == 0:
        return
    for participant in state.participants:
        if participant.type != "player" or participant.is_fallen or participant.is_dead or participant.hp_current <= 0:
            continue
        if not combat_spatial.inside(origin, combat_spatial.position(spatial, participant.id), 60):
            continue
        player = await queries.get_player(participant.id, conn=conn, for_update=True)
        if player is None:
            raise ValueError(f"Missing caster row {participant.id!r}")
        if archetypes.get_archetype_chassis(player["class"]).magic_source is None:
            continue
        caster = session.member_state(participant.id)
        total = current_total(state, caster) + delta
        await db_mutations_resonance.update_player_resonance(participant.id, total, conn=conn)
        stage_total(state, participant.id, total)
