"""Training-cycle agent tools (M1.5).

Errors raise LiveKit `ToolError` (ADR 0002) — the framework surfaces the message
to the LLM. `_*_impl` helpers expose `db_mod=`, `db_training_mod=`, `db_content_mod=`,
`rules_mod=`, `now_fn=` keyword arguments — TEST-ONLY injection seams; production
callers use the `@function_tool` wrappers. Do not call the `_impl` directly from
production code.
"""

import json
import logging
from datetime import UTC, datetime

from livekit.agents.llm import ToolError
from livekit.agents.voice import RunContext

import db
import db_content_queries
import db_training
from session_data import SessionData
from tool_support import _validate_id
from training_rules import TrainingState, resolve_midpoint_decision, start_training_cycle

logger = logging.getLogger("divineruin.tools")

_TERMINAL_STATE: TrainingState = "complete"
_AWAITING_DECISION_STATE: TrainingState = "awaiting_decision"


async def _query_training_programs_impl(
    context: RunContext[SessionData],
    *,
    db_content_mod=db_content_queries,
) -> str:
    logger.info("query_training_programs called")
    programs = await db_content_mod.list_training_programs()
    return json.dumps({"programs": programs})


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
    _validate_id(program_id, "program_id")
    session: SessionData = context.userdata
    player_id = session.player_id
    logger.info("initiate_training_cycle called: player_id=%s program_id=%s", player_id, program_id)

    program = await db_content_mod.get_training_program(program_id)
    if program is None:
        raise ToolError(f"Unknown training program: {program_id}")

    now = (now_fn or _default_now)()
    start_fn = rules_mod or start_training_cycle
    try:
        cycle = start_fn(program["training_activity_type"], now)
    except ValueError as e:
        raise ToolError(str(e)) from e

    async with db_mod.transaction() as conn:
        existing_rows = await db_training_mod.get_player_training_activities(player_id, state=None, conn=conn)
        if any(row["state"] != _TERMINAL_STATE for row in existing_rows):
            raise ToolError("A training cycle is already in progress.")

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


async def _resolve_training_midpoint_impl(
    context: RunContext[SessionData],
    training_id: str,
    decision_id: str,
    *,
    db_mod=db,
    db_training_mod=db_training,
    rules_mod=None,
    now_fn=None,
) -> str:
    context.disallow_interruptions()
    _validate_id(training_id, "training_id")
    session: SessionData = context.userdata
    player_id = session.player_id
    logger.info(
        "resolve_training_midpoint called: player_id=%s training_id=%s decision_id=%s",
        player_id,
        training_id,
        decision_id,
    )

    async with db_mod.transaction() as conn:
        row = await db_training_mod.get_training_activity(training_id, conn=conn, for_update=True)
        if row is None:
            raise ToolError(f"Unknown training: {training_id}")
        if row["player_id"] != player_id:
            raise ToolError(f"Training {training_id} does not belong to this player.")
        if row["state"] != _AWAITING_DECISION_STATE:
            raise ToolError(f"Training {training_id} is in state '{row['state']}', not '{_AWAITING_DECISION_STATE}'.")

        now = (now_fn or _default_now)()
        resolve_fn = rules_mod or resolve_midpoint_decision
        try:
            result = resolve_fn(row["activity_type"], decision_id, now)
        except ValueError as e:
            raise ToolError(str(e)) from e

        data_updates = {
            "decision_id": decision_id,
            "second_half_seconds": result.second_half_seconds,
            "micro_bonus": result.micro_bonus,
        }
        await db_training_mod.update_training_activity(
            training_id,
            state=result.state,
            data_updates=data_updates,
            transition_at=result.completes_at,
            conn=conn,
        )

    return json.dumps(
        {
            "activity_id": training_id,
            "state": result.state,
            "second_half_seconds": result.second_half_seconds,
            "completes_at": result.completes_at.isoformat(),
            "decision_id": decision_id,
        }
    )


def _default_now() -> datetime:
    return datetime.now(UTC)
