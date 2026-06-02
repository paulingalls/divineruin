"""Archetype milestone resolution tool for the DM agent (M2.3).

resolve_milestone is called when a character reaches a milestone level. It derives
the milestone from the player's archetype (player["class"]) and current level:

- L5 (Identity, specialization_fork): with no choice, presents the two paths and
  emits SPECIALIZATION_CHOICE for the HUD; with a valid choice id, persists the
  choice immutably (rejecting a second resolution). Patron-deferred forks
  (Cleric/Paladin) reject pending the Phase 8 Patron system.
- L10/L15/L20 (auto_grant): grants without input, setting the grant's combat flag
  (e.g. extra_attack) in players.data via set_player_flag when present; null-flag
  grants are narrative-only (Phase-4-deferred). Returns the narration cue.

Grants persist as players.data markers, never character_abilities rows (decision
4c0677dae1be). All reads+writes run in one db.transaction() with a FOR UPDATE lock
(concern 598dceba2f3e); the SPECIALIZATION_CHOICE event is published after commit.
"""

import json
import logging

from livekit.agents.llm import ToolError, function_tool
from livekit.agents.voice import RunContext

import db
import db_mutations
import db_queries
import event_types as E
import game_events
import milestone_persistence
import milestones
from db_errors import db_tool
from session_data import SessionData
from tool_support import _validate_id

logger = logging.getLogger("divineruin.tools")


async def apply_milestone_grant(
    milestone: milestones.Milestone, player_id: str, *, conn, flags_mod=db_mutations
) -> bool:
    """Write an auto_grant milestone's combat flag into players.data.flags.

    No-op (returns False) for a null grant or a narrative-only grant (flag is None).
    Shared by resolve_milestone (the tool path) and award_xp (the deterministic
    L10/15/20 side-effect path), so the grant write lives in exactly one place.
    """
    grant = milestone.grant
    if grant is not None and grant.flag:
        await flags_mod.set_player_flag(player_id, grant.flag, True, conn=conn)
        return True
    return False


@function_tool()
@db_tool
async def resolve_milestone(
    context: RunContext[SessionData],
    choice: str | None = None,
) -> str:
    """Lock in the character's level-5 specialization choice.
    Call at level 5 when the character chooses a specialization: first with no choice
    to present the two paths, then again with the chosen option id to lock it in (the
    choice is permanent). Milestone grants at levels 10/15/20 are applied automatically
    on level-up — do NOT call for those. Returns the narration cue to voice."""
    return await _resolve_milestone_impl(context, choice)


async def _resolve_milestone_impl(
    context: RunContext[SessionData],
    choice: str | None = None,
    *,
    db_mod=db,
    queries_mod=db_queries,
    persistence_mod=milestone_persistence,
    flags_mod=db_mutations,
    milestones_mod=milestones,
    events_mod=game_events,
) -> str:
    context.disallow_interruptions()
    if choice is not None:
        _validate_id(choice, "choice")
    session: SessionData = context.userdata
    player_id = session.player_id
    logger.info("resolve_milestone called: choice=%s player=%s", choice, player_id)

    pending_event: dict | None = None
    async with db_mod.transaction() as conn:
        player = await queries_mod.get_player(player_id, conn=conn, for_update=True)
        if player is None:
            raise ToolError(f"Unknown player: {player_id}")

        archetype_id = player.get("class")
        level = player.get("level")
        milestone = milestones_mod.get_milestone_by_level(archetype_id, level)
        if milestone is None:
            raise ToolError(f"No milestone at level {level} for {archetype_id}.")

        if milestone.kind == "specialization_fork":
            if milestone.patron_deferred:
                raise ToolError(
                    "Your specialization is shaped by your patron — available when the Patron system arrives (Phase 8)."
                )
            if choice is None:
                options = [
                    {"id": o.id, "name": o.name, "description": o.description} for o in milestone.specialization_options
                ]
                pending_event = {"milestone_id": milestone.id, "options": options}
                result = {
                    "milestone_id": milestone.id,
                    "requires_choice": True,
                    "options": options,
                    "narration_cue": milestone.narration_cue,
                }
            else:
                existing = player.get("specialization")
                if existing:
                    raise ToolError(f"Specialization already chosen ({existing}); it cannot be changed.")
                valid_ids = {o.id for o in milestone.specialization_options}
                if choice not in valid_ids:
                    raise ToolError(f"Invalid specialization choice: {choice}. Options: {sorted(valid_ids)}")
                await persistence_mod.set_player_specialization(player_id, choice, conn=conn)
                result = {
                    "milestone_id": milestone.id,
                    "chosen": choice,
                    "narration_cue": milestone.narration_cue,
                }
        else:  # auto_grant
            grant = milestone.grant
            await apply_milestone_grant(milestone, player_id, conn=conn, flags_mod=flags_mod)
            result = {
                "milestone_id": milestone.id,
                "grant": {"name": grant.name, "effect": grant.effect} if grant else None,
                "flag": grant.flag if grant else None,
                "narration_cue": milestone.narration_cue,
            }

    # Publish the HUD event after the transaction commits (mirror quest_tools.py).
    if pending_event is not None:
        await events_mod.publish_game_event(
            session.room, E.SPECIALIZATION_CHOICE, pending_event, event_bus=session.event_bus
        )

    return json.dumps(result)
