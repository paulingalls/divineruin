"""Downtime-activity dispatchers for the DM agent (M26 Phase-5, story-001).

Five begin-tools -- initiate_training_cycle, dispatch_companion_errand, start_crafting_project,
rent_workspace, experiment_with_materials -- fold into one verb, ``begin_activity(kind)``, so the
strict-20 tool ceiling stops binding and new content stops adding tools (ADR 0007 SS10). Two
resolve-tools -- resolve_training_midpoint, resolve_companion_errand -- fold into
``resolve_activity(kind, id)``. Both are pure routers: they validate the chosen kind has its
required parameters, then dispatch to the matching pre-existing ``_impl``, none of which they
modify.

``begin_activity`` exposes every folded tool's params as a named-kwarg SUPERSET rather than an
opaque params dict, so the LLM tool schema stays self-documenting and each param keeps its own
type. Required-param validation is per-kind and fails loud (``ToolError``) BEFORE any dispatch --
an under-specified kind never reaches an ``_impl``.

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

import crafting_tools
import errand_tools
import experimentation_tools
import training_tools
from db_errors import db_tool
from session_data import SessionData

logger = logging.getLogger("divineruin.tools")


@function_tool()
@db_tool
async def begin_activity(
    context: RunContext[SessionData],
    kind: Literal["training", "companion_errand", "crafting", "workspace", "experiment"],
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
) -> str:
    """Begin a downtime activity: training, a companion errand, crafting, renting a workspace,
    or experimenting with materials.

    Pass kind to pick which activity, then only the params that activity needs:

    - kind='training': program_id (from query_info(kind="training_programs")).
    - kind='companion_errand': companion_id (the player's ASSIGNED companion — any other id is
      refused), errand_type (scout|social|acquire|relationship),
      destination.
    - kind='crafting': recipe_id (a recipe the player already knows).
    - kind='workspace': workspace_type (workshop|forge|laboratory, or forge_laboratory for the
      discounted Forge + Laboratory bundle, which a city or Keldaran hold only can rent),
      npc_id (renting from), days (rental length, >= 1).
    - kind='experiment': material_ids and quantities (positionally aligned, same length,
      material_ids must not repeat), intended_output (the item id hoped for).

    Returns an error if a required param for the chosen kind is missing, or if the activity's
    own preconditions refuse (e.g. a training cycle already in progress, an invalid errand
    destination, a full crafting slot, an NPC below Neutral disposition, or a duplicate/short
    material list).
    """
    return await _begin_activity_impl(
        context,
        kind,
        program_id=program_id,
        companion_id=companion_id,
        errand_type=errand_type,
        destination=destination,
        recipe_id=recipe_id,
        workspace_type=workspace_type,
        npc_id=npc_id,
        days=days,
        material_ids=material_ids,
        quantities=quantities,
        intended_output=intended_output,
    )


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
        # Preserved verbatim from experimentation_tools.experiment_with_materials (story-001):
        # the list-zip shaping the wrapper did before dispatching to its _impl.
        if len(material_ids) != len(quantities):
            raise ToolError("material_ids and quantities must have the same length.")
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
