"""Draethar Inner Fire active racial tool for the DM agent (story-005, M3.4).

inner_fire is the Draethar's once-per-encounter pressure valve (spec magic.md:262-268): the
caster's skin flares and the inner fire purges Veil disturbance — reduce current Resonance by 3,
but take 1d6 unpreventable self fire damage. The -3 / "1d6" values are read from the racial
table (racial_resonance, story-001), not hardcoded. Unlike the passive racials this is an active
combat action, so it ships as a combat @function_tool and is gated to once per encounter via
session.draethar_inner_fire_used (reset at encounter boundaries, like weapon_used_this_encounter).

It is combat-scoped (the "encounter" is a combat): a player's HP lives in two places during
combat — the in-memory CombatParticipant.hp_current and persisted players.data — so this writes
BOTH, exactly as combat_turn.py does (participant then update_player_hp). Every user-facing
failure is a ToolError raised BEFORE any write, so an ineligible use changes nothing.

Mirrors the veil_ward_tools seam: a thin @function_tool + @db_tool wrapper over an _impl with
module-injection keyword args (db_mod/queries_mod/hp_mutations_mod/resonance_mutations_mod/
resonance_events_mod/racial_mod/dice_mod) for test mocking, a single db.transaction() block, and
a post-commit in-memory sync + RESONANCE_CHANGED push (mirroring cast_spell).
"""

import json
import logging

from livekit.agents.llm import ToolError, function_tool
from livekit.agents.voice import RunContext

import db
import db_mutations
import db_mutations_resonance
import db_queries
import dice
import racial_resonance
import resonance as resonance_mod
import resonance_events
from db_errors import db_tool
from session_data import SessionData

logger = logging.getLogger("divineruin.tools")

_DRAETHAR = "draethar"


@function_tool()
@db_tool
async def inner_fire(context: RunContext[SessionData]) -> str:
    """Use the Draethar racial Inner Fire to purge Veil disturbance. Call when a Draethar caster
    chooses to burn off Resonance mid-combat: it drops their Resonance by 3 but deals 1d6
    unpreventable fire damage to them, usable once per encounter. Rejects if the caster is not a
    Draethar, has already used it this encounter, or is not in combat."""
    return await _inner_fire_impl(context)


async def _inner_fire_impl(
    context: RunContext[SessionData],
    *,
    db_mod=db,
    queries_mod=db_queries,
    hp_mutations_mod=db_mutations,
    resonance_mutations_mod=db_mutations_resonance,
    resonance_events_mod=resonance_events,
    racial_mod=racial_resonance,
    dice_mod=dice,
) -> str:
    context.disallow_interruptions()
    session: SessionData = context.userdata
    player_id = session.player_id
    logger.info("inner_fire called: player=%s", player_id)

    # Gates FIRST, all before any write (ineligible use changes nothing). Combat gate first so the
    # player fetch is skipped when there's no encounter.
    if session.combat_state is None:
        raise ToolError("Inner Fire can only be used in combat.")
    if session.draethar_inner_fire_used:
        raise ToolError("Inner Fire is already spent this encounter.")

    async with db_mod.transaction() as conn:
        player = await queries_mod.get_player(player_id, conn=conn, for_update=True)
        if player is None:
            raise ToolError(f"Unknown player: {player_id}")
        if player.get("race") != _DRAETHAR:
            raise ToolError("Only a Draethar can use Inner Fire.")
        participant = session.combat_state.get_participant(player_id)
        if participant is None:
            raise ToolError("Inner Fire requires the caster to be in the encounter.")

        reduction = racial_mod.get_racial_resonance_modifier(_DRAETHAR, "inner_fire_resonance_reduction")
        damage_dice = racial_mod.get_racial_resonance_modifier(_DRAETHAR, "inner_fire_self_damage")
        fire_damage = dice_mod.roll(damage_dice).total

        new_resonance = max(0, session.resonance.current - reduction)
        new_hp = max(0, participant.hp_current - fire_damage)
        await resonance_mutations_mod.update_player_resonance(player_id, new_resonance, conn=conn)
        await hp_mutations_mod.update_player_hp(player_id, new_hp, conn=conn)

    # Transaction committed — sync the in-memory SSOTs and push the HUD state.
    resonance_reduced = session.resonance.current - new_resonance
    session.resonance.current = new_resonance
    participant.hp_current = new_hp
    session.draethar_inner_fire_used = True
    # Persist the combat state so the participant's self-damage survives a mid-encounter crash,
    # mirroring combat_turn (participant HP lives in combat_instances, not just players.data).
    await hp_mutations_mod.save_combat_state(session.combat_state.combat_id, session.combat_state.to_dict())
    await resonance_events_mod.publish_resonance_changed(session)

    return json.dumps(
        {
            "resonance_reduced": resonance_reduced,
            "fire_damage": fire_damage,
            "hp_remaining": new_hp,
            "state": resonance_mod.get_resonance_state(new_resonance),
        }
    )
