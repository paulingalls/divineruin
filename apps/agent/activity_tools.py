"""Downtime-activity dispatchers: ``begin_activity(kind)`` and ``resolve_activity(kind, id)``.

One verb per direction keeps new activity kinds from adding tools (ADR 0004 ceiling, ADR 0007).
``begin_activity`` takes a discriminated sum type (``activity_payloads``, ADR 0008) because an
optional-kwarg superset spent most of a request's union budget. Required params are still checked
per kind here, fail loud, before dispatch: the schema binds only the LLM path.

``resolve_activity`` takes an explicit ``kind`` rather than inferring it from ``id``: training and
errand ids share no disjoint namespace. ``@db_tool`` sits on both dispatchers so every routed kind
narrates DB errors the same way.

Begin cues publish here, after the delegate's write returns. Resolve cues publish inside their
delegates: an errand resolver returns the same shape for a fresh resolution and a cached re-read,
so only it knows which one committed.
"""

import json
import logging
from typing import Literal

from livekit.agents.llm import ToolError, function_tool
from livekit.agents.voice import RunContext

import activity_payloads
import crafting_tools
import errand_tools
import experimentation_tools
import training_tools
from action_sound_content import ACTION_SOUND_EXPORTS, publish_action_sound
from activity_payloads import ActivityPayload
from db_errors import db_tool
from session_data import SessionData

logger = logging.getLogger("divineruin.tools")


@function_tool()
@db_tool
async def begin_activity(
    context: RunContext[SessionData],
    activity: ActivityPayload,
) -> str:
    """Begin a downtime activity: training, a companion errand, crafting, renting a workspace,
    or experimenting with materials.

    Pass one activity object, picked by its kind: "training", "companion_errand", "crafting",
    "workspace", or "experiment". A spell_* training program requires spell_id; other training
    programs forbid it.

    Returns an error if the activity's own preconditions refuse — a training cycle already in
    progress, an invalid errand destination, a full crafting slot, an NPC below Neutral
    disposition, or a duplicate material id.
    """
    kind, kwargs = activity_payloads.to_impl_kwargs(activity)
    return await _begin_activity_impl(context, kind, **kwargs)


async def _begin_activity_impl(
    context: RunContext[SessionData],
    kind: str,
    *,
    program_id: str | None = None,
    spell_id: str | None = None,
    companion_id: str | None = None,
    errand_type: str | None = None,
    destination: str | None = None,
    recipe_id: str | None = None,
    workspace_type: str | None = None,
    npc_id: str | None = None,
    days: int | None = None,
    material_ids: list[str] | None = None,
    quantities: list[int] | None = None,
    intended_output: str | None = None,
    training_mod=training_tools,
    errand_mod=errand_tools,
    crafting_mod=crafting_tools,
    experimentation_mod=experimentation_tools,
) -> str:
    logger.info("begin_activity called: kind=%s", kind)

    if kind == "training":
        if not program_id:
            raise ToolError("kind='training' requires program_id.")
        result = await training_mod._initiate_training_cycle_impl(context, program_id, spell_id=spell_id)
        await publish_action_sound(context.userdata, ACTION_SOUND_EXPORTS["ACTION_BEGIN_TRAINING"])
        return result

    if kind == "companion_errand":
        if not (companion_id and errand_type and destination):
            raise ToolError("kind='companion_errand' requires companion_id, errand_type, and destination.")
        result = await errand_mod._dispatch_companion_errand_impl(context, companion_id, errand_type, destination)
        await publish_action_sound(context.userdata, ACTION_SOUND_EXPORTS["ACTION_BEGIN_COMPANION_ERRAND"])
        return result

    if kind == "crafting":
        if not recipe_id:
            raise ToolError("kind='crafting' requires recipe_id.")
        result = await crafting_mod._start_crafting_project_impl(context, recipe_id)
        await publish_action_sound(context.userdata, ACTION_SOUND_EXPORTS["ACTION_BEGIN_CRAFTING"])
        return result

    if kind == "workspace":
        if not workspace_type or not npc_id or days is None:
            raise ToolError("kind='workspace' requires workspace_type, npc_id, and days.")
        result = await crafting_mod._rent_workspace_impl(context, workspace_type, npc_id, days)
        await publish_action_sound(context.userdata, ACTION_SOUND_EXPORTS["ACTION_BEGIN_WORKSPACE"])
        return result

    if kind == "experiment":
        if not (material_ids and quantities and intended_output):
            raise ToolError("kind='experiment' requires material_ids, quantities, and intended_output.")
        if len(set(material_ids)) != len(material_ids):
            raise ToolError("material_ids must not contain duplicates.")
        materials = dict(zip(material_ids, quantities, strict=True))
        result = await experimentation_mod._experiment_with_materials_impl(context, materials, intended_output)
        outcome = json.loads(result)["outcome"]
        if outcome in {"success", "failure", "no_match"}:
            await publish_action_sound(context.userdata, ACTION_SOUND_EXPORTS["ACTION_BEGIN_EXPERIMENT"])
        elif outcome != "already_tried":
            raise ValueError(f"Unknown experiment outcome: {outcome!r}")
        return result

    raise ToolError(f"Unknown activity kind: {kind!r}")


@function_tool()
@db_tool
async def resolve_activity(
    context: RunContext[SessionData],
    kind: Literal["training", "companion_errand"],
    id: str,
    decision: str | None = None,
) -> str:
    """Resolve a downtime activity and report the outcome.

    kind='training': resolves the midpoint decision for an awaiting-decision training cycle.
    decision is REQUIRED -- the option id the player audibly chose from the prior midpoint
    prompt.

    kind='companion_errand': resolves a companion's errand and reports what happened. decision
    is NOT used here -- the errand computes and returns its own decision_options; pass id only.

    Args:
        kind: 'training' or 'companion_errand'.
        id: The activity_id (training) or errand_id (companion_errand) to resolve.
        decision: The midpoint option id, required for kind='training'; ignored for
            kind='companion_errand'.
    """
    return await _resolve_activity_impl(context, kind, id, decision=decision)


async def _resolve_activity_impl(
    context: RunContext[SessionData],
    kind: str,
    id: str,
    *,
    decision: str | None = None,
    training_mod=training_tools,
    errand_mod=errand_tools,
) -> str:
    logger.info("resolve_activity called: kind=%s id=%s", kind, id)

    if kind == "training":
        if not decision:
            raise ToolError("kind='training' requires decision.")
        return await training_mod._resolve_training_midpoint_impl(context, training_id=id, decision_id=decision)

    if kind == "companion_errand":
        return await errand_mod._resolve_companion_errand_impl(context, errand_id=id)

    raise ToolError(f"Unknown activity kind: {kind!r}")
