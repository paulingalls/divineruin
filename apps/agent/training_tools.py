"""Training-cycle agent tools (M1.5)."""

import json
import logging
from datetime import UTC, datetime

from livekit.agents.llm import function_tool
from livekit.agents.voice import RunContext

import db
import db_content_queries
import db_training
from db_errors import db_tool
from session_data import SessionData
from tool_support import _validate_id
from training_rules import TrainingState, start_training_cycle

logger = logging.getLogger("divineruin.tools")

_TERMINAL_STATE: TrainingState = "complete"


@function_tool()
@db_tool
async def query_training_programs(context: RunContext[SessionData]) -> str:
    """List all training programs the player can choose. Returns id, name,
    activity_type, stat, optional skill, dc, mentor_id for each. Call this
    when the player asks 'what can I train?' or before initiate_training_cycle
    when you don't already know the program ids."""
    return await _query_training_programs_impl(context)


async def _query_training_programs_impl(
    context: RunContext[SessionData],
    *,
    db_content_mod=db_content_queries,
) -> str:
    logger.info("query_training_programs called")
    programs = await db_content_mod.list_training_programs()
    return json.dumps({"programs": programs})


@function_tool()
@db_tool
async def initiate_training_cycle(
    context: RunContext[SessionData],
    program_id: str,
) -> str:
    """Start a training cycle for the current player on a named program. Use
    only after the player has explicitly chosen a program in conversation. If
    you don't know the available program ids, call query_training_programs
    first. Returns an error if the player already has a non-complete training
    cycle.

    Args:
        program_id: One of the ids returned by query_training_programs.
    """
    return await _initiate_training_cycle_impl(context, program_id)


async def _initiate_training_cycle_impl(
    context: RunContext[SessionData],
    program_id: str,
    *,
    db_mod=db,
    db_training_mod=db_training,
    db_content_mod=db_content_queries,
    rules_mod=None,
    now_fn=None,
) -> str:
    context.disallow_interruptions()
    if err := _validate_id(program_id, "program_id"):
        return err
    session: SessionData = context.userdata
    player_id = session.player_id
    logger.info("initiate_training_cycle called: player_id=%s program_id=%s", player_id, program_id)

    program = await db_content_mod.get_training_program(program_id)
    if program is None:
        return json.dumps({"error": f"Unknown training program: {program_id}"})

    now = (now_fn or _default_now)()
    start_fn = rules_mod or start_training_cycle
    try:
        cycle = start_fn(program["training_activity_type"], now)
    except ValueError as e:
        return json.dumps({"error": str(e)})

    async with db_mod.transaction() as conn:
        existing_rows = await db_training_mod.get_player_training_activities(player_id, state=None, conn=conn)
        if any(row["state"] != _TERMINAL_STATE for row in existing_rows):
            return json.dumps({"error": "A training cycle is already in progress."})

        data = {
            "program_id": program["id"],
            "program_name": program["name"],
            "first_half_seconds": cycle.first_half_seconds,
            "stat": program.get("stat"),
            "skill": program.get("skill"),
            "dc": program.get("dc"),
            "mentor_id": program.get("mentor_id"),
        }
        activity_id = await db_training_mod.create_training_activity(
            player_id=player_id,
            activity_type=program["training_activity_type"],
            state=cycle.state,
            data=data,
            transition_at=cycle.decision_at,
            conn=conn,
        )

    return json.dumps(
        {
            "activity_id": activity_id,
            "state": cycle.state,
            "first_half_seconds": cycle.first_half_seconds,
            "decision_at": cycle.decision_at.isoformat(),
            "program_name": program["name"],
        }
    )


def _default_now() -> datetime:
    return datetime.now(UTC)
