"""Mentor variant acquisition helper (M9 story-002).

Variants add ZERO new @function_tools (ADR 0007): the generic learn(kind, id,
source) verb in recipe_tools dispatches kind="variant" here. Unlike
learn(recipe)/learn(spell), which acquire instantly, a variant is acquired by
TRAINING over a multi-session mentor loop — so _learn_variant_impl INITIATES
training: it validates the variant, rejects an already-unlocked one, seeds the
cycle-progress row at 0, and starts a technique_mentor_variant training activity.
The async worker advances each completed session and unlocks the variant when
cycles_required is reached (mentor_variant_progress + async_worker_training).

Errors raise LiveKit `ToolError` (ADR 0002); the `*_mod=`/`now_fn=` keyword seams
are TEST-ONLY (production callers use the defaults).
"""

import json
import logging
from datetime import UTC, datetime

from livekit.agents.llm import ToolError
from livekit.agents.voice import RunContext

import db
import db_training
import mentor_variant_progress
import mentor_variants
from session_data import SessionData
from tool_support import _validate_id
from training_rules import get_cycles_required, start_training_cycle

logger = logging.getLogger("divineruin.mentor_variant_tools")

_VARIANT_ACTIVITY_TYPE = "technique_mentor_variant"
_TERMINAL_STATE = "complete"


async def _learn_variant_impl(
    context: RunContext[SessionData],
    variant_id: str,
    source: str = "",
    *,
    db_mod=db,
    db_training_mod=db_training,
    variants_mod=mentor_variants,
    progress_mod=mentor_variant_progress,
    rules_mod=None,
    now_fn=None,
) -> str:
    context.disallow_interruptions()
    _validate_id(variant_id, "variant_id")

    # Catalog lookup is an in-memory read (no IO) — do it before touching the DB.
    # `source` is accepted for the learn(kind, id, source) dispatch shape but not
    # gated: a variant's only acquisition track is the mentor loop (mentor_training).
    try:
        variant = variants_mod.get_mentor_variant(variant_id)
    except ValueError as exc:
        raise ToolError(f"Unknown mentor variant: {variant_id}") from exc

    player_id = context.userdata.player_id
    now = (now_fn or _default_now)()
    start_fn = rules_mod or start_training_cycle
    try:
        cycle = start_fn(_VARIANT_ACTIVITY_TYPE, now)
    except ValueError as e:
        raise ToolError(str(e)) from e
    cycles_required = get_cycles_required(_VARIANT_ACTIVITY_TYPE)

    # Mentor co-location / valid-relationship gating depends on Phase 6 NPC
    # disposition (recorded cross-phase constraint) — stubbed here. The variant
    # carries its bound mentor_id; full co-location enforcement lands with Phase 6.

    async with db_mod.transaction() as conn:
        if await progress_mod.is_unlocked(player_id, variant_id, conn=conn):
            raise ToolError(f"Variant {variant_id} is already unlocked.")
        # One in-flight training cycle per player (mirrors initiate_training_cycle).
        existing = await db_training_mod.get_player_training_activities(player_id, state=None, conn=conn)
        if any(row["state"] != _TERMINAL_STATE for row in existing):
            raise ToolError("A training cycle is already in progress.")

        await progress_mod.seed_progress(player_id, variant_id, cycles_required, conn=conn)
        data = {
            "variant_id": variant_id,
            "ability_id": variant.ability_id,
            "mentor_id": variant.mentor_id,
            "cultural_attribution": variant.cultural_attribution,
            "first_half_seconds": cycle.first_half_seconds,
        }
        activity_id = await db_training_mod.create_training_activity(
            player_id=player_id,
            activity_type=_VARIANT_ACTIVITY_TYPE,
            state=cycle.state,
            data=data,
            transition_at=cycle.decision_at,
            conn=conn,
        )

    logger.info("learn variant: player=%s variant=%s mentor=%s", player_id, variant_id, variant.mentor_id)
    return json.dumps(
        {
            "training_started": variant_id,
            "ability_id": variant.ability_id,
            "mentor_id": variant.mentor_id,
            "cycles_required": cycles_required,
            "activity_id": activity_id,
            "state": cycle.state,
            "first_half_seconds": cycle.first_half_seconds,
            "decision_at": cycle.decision_at.isoformat(),
        }
    )


def _default_now() -> datetime:
    return datetime.now(UTC)
