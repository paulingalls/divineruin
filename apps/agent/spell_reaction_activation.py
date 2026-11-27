"""Commit a catalog spell cast and its held reaction spend together."""

import copy
import json

from livekit.agents import RunContext
from livekit.agents.llm import ToolError

import combat_hold
import combat_hollow_resonance
import db
import db_mutations
import reaction_gate
from session_data import SessionData
from spell_cast_resolution import _resolve_cast
from spell_cast_result import CastResult
from spells import Spell


async def activate(context: RunContext[SessionData], spell: Spell) -> str:
    session = context.userdata
    context.disallow_interruptions()
    async with session.combat_state_lock:
        result = await _activate_locked(session, spell)
    await result.flush_events()
    return json.dumps(result.packet)


async def _activate_locked(session: SessionData, spell: Spell) -> CastResult:
    state = session.combat_state
    if state is None or state.open_window is None:
        raise ToolError(f"{spell.name} is cast as a reaction during its open combat window.")

    actor_id = session.require_reaction_actor().player_id
    caster = session.member_state(actor_id)
    try:
        reaction_gate.validate_reaction_activation(state, actor_id, spell.id)
        spend = combat_hold.preflight_spend(state, actor_id, spell.id)
    except ValueError as error:
        raise ToolError(str(error)) from error

    working = copy.deepcopy(state)
    async with db.transaction() as conn:
        result = await _resolve_cast(
            session,
            spell.id,
            conn=conn,
            caster=caster,
            revalidate_actor=True,
            combat_state=working,
            prepared_reaction=True,
        )
        combat_hold.record_spend(working, actor_id, spend)
        await db_mutations.save_combat_state(working.combat_id, working.to_dict(), conn=conn)

    session.combat_state = working
    for player_id, total in combat_hollow_resonance.take_totals(working).items():
        session.member_state(player_id).resonance.current = total
    if result.concentration_update is not None:
        caster.concentration = result.concentration_update
    if result.unbound_veil_mastery_spent:
        caster.unbound_veil_mastery_used = True
    return result
