"""Choice resolution tools — the generic ``select`` verb (M4, ADR 0007).

select resolves a pending player choice surfaced by a Resolve. Today the only
pending choice is the L5 specialization fork that ``_award_xp_core`` surfaces on
level-up (its ``PendingChoice.choice_id`` is the milestone id). select absorbs the
with-choice path of ``resolve_milestone``, which is removed in story-004; until
then both coexist — each enforces immutability via the FOR UPDATE read, so a
duplicate or concurrent resolution loses cleanly.

No event is published on resolution: the client dismisses the HUD overlay locally
on tap (the present-options SPECIALIZATION_CHOICE event is owned by the level-up
path in progression_tools).
"""

import json
import logging

from livekit.agents.llm import ToolError, function_tool
from livekit.agents.voice import RunContext

import db
import db_queries
import milestone_persistence
import milestones
from db_errors import db_tool
from session_data import SessionData
from tool_support import _validate_id

logger = logging.getLogger("divineruin.tools")


@function_tool()
@db_tool
async def select(
    context: RunContext[SessionData],
    choice_id: str,
    option: str,
) -> str:
    """Resolve a pending choice the HUD surfaced — today, the level-5 specialization
    fork. Pass the choice_id from the pending choice and the chosen option id. The
    choice is permanent. Do NOT call for the level 10/15/20 grants; those apply
    automatically on level-up."""
    return await _select_impl(context, choice_id, option)


async def _select_impl(
    context: RunContext[SessionData],
    choice_id: str,
    option: str,
    *,
    db_mod=db,
    queries_mod=db_queries,
    persistence_mod=milestone_persistence,
    milestones_mod=milestones,
) -> str:
    context.disallow_interruptions()
    # Validate at the boundary before opening a transaction — choice_id/option are
    # externally supplied (DM voice tool-call or, in story-005, a HUD tap).
    _validate_id(choice_id, "choice_id")
    _validate_id(option, "option")
    session: SessionData = context.userdata
    player_id = session.player_id
    logger.info("select called: choice_id=%s option=%s player=%s", choice_id, option, player_id)

    async with db_mod.transaction() as conn:
        player = await queries_mod.get_player(player_id, conn=conn, for_update=True)
        if player is None:
            raise ToolError(f"Unknown player: {player_id}")

        try:
            milestone = milestones_mod.get_milestone(choice_id)
        except ValueError as e:
            raise ToolError(f"Unknown choice: {choice_id}") from e

        # choice_id is external, so the guarantees resolve_milestone got from deriving
        # the milestone from player state are explicit checks here.
        if milestone.kind != "specialization_fork":
            raise ToolError(f"Choice '{choice_id}' is not a selectable choice.")
        if milestone.archetype_id != player.get("class"):
            raise ToolError(f"Choice '{choice_id}' is not your specialization.")
        if milestone.patron_deferred:
            raise ToolError(
                "Your specialization is shaped by your patron — available when the Patron system arrives (Phase 8)."
            )
        if player.get("level", 1) < milestone.level:
            raise ToolError(f"You have not yet reached the milestone for '{choice_id}'.")

        existing = player.get("specialization")
        if existing:
            raise ToolError(f"Specialization already chosen ({existing}); it cannot be changed.")

        valid_ids = {o.id for o in milestone.specialization_options}
        if option not in valid_ids:
            raise ToolError(f"Invalid option: {option}. Options: {sorted(valid_ids)}")

        await persistence_mod.set_player_specialization(player_id, option, conn=conn)

    result = {"choice_id": choice_id, "chosen": option, "narration_cue": milestone.narration_cue}
    logger.info("select result: %s -> %s for %s", choice_id, option, player_id)
    return json.dumps(result)
