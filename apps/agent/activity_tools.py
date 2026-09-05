"""Downtime-activity dispatchers for the DM agent (M26 Phase-5, story-001).

Five begin-tools -- initiate_training_cycle, dispatch_companion_errand, start_crafting_project,
rent_workspace, experiment_with_materials -- fold into one verb, ``begin_activity(kind)``, so the
strict-20 tool ceiling stops binding and new content stops adding tools (ADR 0007 SS10). Two
resolve-tools -- resolve_training_midpoint, resolve_companion_errand -- fold into
``resolve_activity(kind, id)``. Both are pure routers: they validate the chosen kind has its
required parameters, then dispatch to the matching pre-existing ``_impl``, none of which they
modify.

``begin_activity`` takes a SUM TYPE -- one discriminated ``anyOf`` of kind-tagged variants
(``activity_payloads``, ADR 0008) -- rather than the optional-kwarg superset it once exposed:
eleven union-typed parameters was two thirds of a request's budget of sixteen. The schema is
still self-documenting and each field still keeps its own type. Required-param validation is
per-kind and fails loud (``ToolError``) BEFORE any dispatch: the schema binds only the LLM
path, so the engine stays the wall for every other caller.

``resolve_activity`` takes an explicit ``kind`` rather than inferring one from ``id``: training_id
and errand_id are both opaque async-activity ids with no disjoint-namespace guarantee, so
id-inference would be unsafe.

Both dispatchers carry ``@db_tool`` at the dispatcher level, so EVERY routed kind gets it —
uniform by design. Some folded wrappers already had it (training, the query reads); the
errand/crafting/workspace/experiment wrappers did not, so those kinds gain DB-error narration
here (a deliberate consistency improvement, not a strict behavior preservation). The decorator
is error-handling, not transaction management: it narrates a DB error escaping an ``_impl`` as a
friendly ``ToolError`` instead of letting a raw exception reach the player.
"""

import logging
from typing import Literal

from livekit.agents.llm import ToolError, function_tool
from livekit.agents.voice import RunContext

import activity_payloads
import crafting_tools
import errand_tools
import experimentation_tools
import training_tools
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
    "workspace", or "experiment". Each kind's fields describe themselves and are all required.

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
        return await training_mod._initiate_training_cycle_impl(context, program_id)

    if kind == "companion_errand":
        if not (companion_id and errand_type and destination):
            raise ToolError("kind='companion_errand' requires companion_id, errand_type, and destination.")
        return await errand_mod._dispatch_companion_errand_impl(context, companion_id, errand_type, destination)

    if kind == "crafting":
        if not recipe_id:
            raise ToolError("kind='crafting' requires recipe_id.")
        return await crafting_mod._start_crafting_project_impl(context, recipe_id)

    if kind == "workspace":
        if not workspace_type or not npc_id or days is None:
            raise ToolError("kind='workspace' requires workspace_type, npc_id, and days.")
        return await crafting_mod._rent_workspace_impl(context, workspace_type, npc_id, days)

    if kind == "experiment":
        if not (material_ids and quantities and intended_output):
            raise ToolError("kind='experiment' requires material_ids, quantities, and intended_output.")
        if len(set(material_ids)) != len(material_ids):
            raise ToolError("material_ids must not contain duplicates.")
        materials = dict(zip(material_ids, quantities, strict=True))
        return await experimentation_mod._experiment_with_materials_impl(context, materials, intended_output)

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
