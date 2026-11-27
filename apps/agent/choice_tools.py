"""Resolve authenticated specialization and spoken Hollow Echo choices (ADR 0007 ``select``).

The L5 specialization fork's ``milestone_id`` arrives from the tap/voice call, not from
hand-off state on the Resolve's result. Immutability rides the FOR UPDATE read, so a duplicate
or concurrent resolution loses cleanly. Rewards are party-wide (M28 story-001), so the fork
belongs to the authenticated speaker. A specialization resolution publishes no event: the client
dismisses the HUD overlay locally on tap.
"""

import json
import logging
from typing import Annotated

from livekit.agents.llm import ToolError, function_tool
from livekit.agents.voice import RunContext
from pydantic import Field, StrictInt

import attribute_increase_tools
import attribute_increases
import db
import db_content_queries
import db_mutations
import db_queries
import elective_choice_tools
import elective_choices
import lost_scout_scene
import milestone_persistence
import milestones
import oath_choice
import patron_echo_choice
from db_errors import db_tool
from milestones import Milestone
from oaths import ObjectiveInput
from session_data import SessionData
from tool_support import _validate_id

logger = logging.getLogger("divineruin.tools")


# Factories let legacy JSON omit the fields without adding nullable strict-schema branches.
@function_tool()
@db_tool
async def select(
    context: RunContext[SessionData],
    choice_id: str,
    option: str,
    objective_kind: Annotated[ObjectiveInput, Field(default_factory=lambda: "none")],
    target_id: Annotated[str, Field(default_factory=str)],
    last_round: Annotated[StrictInt, Field(default_factory=int)],
) -> str:
    """Resolve a pending attribute, elective, specialization, Hollow Echo or paladin oath choice.
    For an oath, read the offered terms from query_info(kind="abilities" or "combat"), wait for
    spoken confirmation, and select the offered choice and option. Read back the receipt's oath_id
    and terms. For timed oaths, send the offered objective_kind and eligible target_id and the
    player's last_round. For every non-timed selection send objective_kind="none", target_id=""
    and last_round=0.
    query_info(kind="abilities") recovers attribute increases until the next long rest and elective techniques until chosen.
    Read elective options aloud and wait for a spoken choice. Use the emitted choice_id and option id. For Hollow Echo, offer both descriptions aloud and wait for the
    player's spoken choice before selecting. For a Lost Scout report, use the report_action from
    query_info(kind="npc") when the player tells Torin what happened. Level 10/15/20 grants apply automatically."""
    return await _select_impl(
        context, choice_id, option, objective_kind=objective_kind, target_id=target_id, last_round=last_round
    )


def _fork_block_reason(player_id: str, player: dict | None, milestone: Milestone) -> str | None:
    """Why this speaker may not resolve this milestone, or None if they may."""
    if player is None:
        return f"Unknown player: {player_id}"
    if milestone.archetype_id != player.get("class"):
        return f"Choice '{milestone.id}' is not your specialization."
    if player.get("level", 1) < milestone.level:
        return f"You have not yet reached the milestone for '{milestone.id}'."
    existing = player.get("specialization")
    if existing:
        return f"Specialization already chosen ({existing}); it cannot be changed."
    return None


async def _select_impl(
    context: RunContext[SessionData],
    choice_id: str,
    option: str,
    *,
    objective_kind: ObjectiveInput = "none",
    target_id: str = "",
    last_round: int = 0,
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
    actor = session.acting_player_id
    logger.info("select called: choice_id=%s option=%s caller=%s", choice_id, option, actor)
    if choice_id.startswith(oath_choice.PREFIX) and option == "timed":
        if objective_kind not in ("defeat_target", "keep_ally_standing"):
            raise ToolError("A timed oath requires an offered objective.")
        _validate_id(target_id, "target_id")
        if last_round < 1:
            raise ToolError("A timed oath requires a positive integer last_round.")
    elif (objective_kind, target_id, last_round) != ("none", "", 0):
        raise ToolError("Use neutral oath fields for a non-timed selection.")

    if choice_id.startswith(oath_choice.PREFIX):
        return await oath_choice.select(
            session,
            actor,
            choice_id,
            option,
            objective_kind,
            target_id,
            last_round,
            db_mod=db_mod,
            queries_mod=queries_mod,
        )

    if choice_id == lost_scout_scene.CHOICE:
        return await lost_scout_scene.report(
            session, option, db_mod=db_mod, queries=queries_mod, content=db_content_queries, mutations=db_mutations
        )

    if choice_id.startswith(attribute_increases.PREFIX):
        return await attribute_increase_tools.select(session, choice_id, option, db_mod=db_mod, queries_mod=queries_mod)

    if choice_id.startswith(elective_choices.PREFIX):
        return await elective_choice_tools.select(session, choice_id, option, db_mod=db_mod, queries_mod=queries_mod)

    if choice_id.startswith(patron_echo_choice.PREFIX):
        return await patron_echo_choice.select(session, choice_id, option, db_mod=db_mod, queries_mod=queries_mod)

    async with db_mod.transaction() as conn:
        try:
            milestone = milestones_mod.get_milestone(choice_id)
        except ValueError as e:
            raise ToolError(f"Unknown choice: {choice_id}") from e

        # choice_id is external, so verify the milestone before the player row.
        if milestone.kind != "specialization_fork":
            raise ToolError(f"Choice '{choice_id}' is not a selectable choice.")
        if milestone.patron_deferred:
            raise ToolError(
                "Your specialization is shaped by your patron — available when the Patron system arrives (Phase 8)."
            )

        # This helper uses the same deterministic lock order as the party batch readers.
        rows = await queries_mod.get_players_for_update([actor], conn=conn)

        if reason := _fork_block_reason(actor, rows.get(actor), milestone):
            raise ToolError(reason)

        valid_ids = {o.id for o in milestone.specialization_options}
        if option not in valid_ids:
            raise ToolError(f"Invalid option: {option}. Options: {sorted(valid_ids)}")

        session.validate_acting_player(actor)
        await persistence_mod.set_player_specialization(actor, option, conn=conn)

    result = {
        "choice_id": choice_id,
        "chosen": option,
        "player_id": actor,
        "narration_cue": milestone.narration_cue,
    }
    logger.info("select result: %s -> %s for %s", choice_id, option, actor)
    return json.dumps(result)
