"""The `enter_mode` verb (combat/dispatch/blacksmith handoffs).

`enter_mode(mode, ...)` is the consolidated mode-entry verb (M5, ADR 0007, Verbs &
Stages §4/§10): it folds start_combat, enter_dispatch, and enter_blacksmith into one
mode-discriminated handoff tool, dispatching to the per-mode `_*_impl` handoffs that
keep living in their home modules (combat_init / dispatch_tools / blacksmith_tools).
The exit paths (end_combat, conclude_dispatch, conclude_blacksmith) stay internal to
the mode agents — out of scope here.

Errors raise LiveKit `ToolError` (ADR 0002). The dispatcher is `@db_tool`-wrapped
because the combat branch hits the DB (rolling initiative, persisting CombatState);
it is a no-op cost for the dispatch/blacksmith branches.
"""

from livekit.agents.llm import ToolError, function_tool
from livekit.agents.voice import RunContext

from blacksmith_tools import _enter_blacksmith_impl
from combat_init import _start_combat_impl
from db_errors import db_tool
from dispatch_tools import _enter_dispatch_impl
from session_data import SessionData

VALID_MODES = ("combat", "dispatch", "blacksmith")


@function_tool()
@db_tool
async def enter_mode(
    context: RunContext[SessionData],
    mode: str,
    encounter_id: str = "",
    encounter_description: str = "",
) -> str | tuple:
    """Hand off to a focused mode context. Pick a mode:

    - mode="combat": combat begins. Give encounter_id (the encounter template) and
      encounter_description (a brief note on how combat starts). Rolls initiative and
      establishes turn order.
    - mode="dispatch": the player wants a deliberate between-adventure activity —
      training with a mentor, or sending a companion on an errand. No other args.
    - mode="blacksmith": the player wants to repair gear at a settlement forge. A
      forge is a settlement activity; only offer it where one would plausibly exist.
      No other args.

    Control returns here when the mode concludes."""
    return await _enter_mode_impl(context, mode, encounter_id, encounter_description)


async def _enter_mode_impl(
    context: RunContext[SessionData],
    mode: str,
    encounter_id: str = "",
    encounter_description: str = "",
) -> str | tuple:
    if mode == "combat":
        if not encounter_id:
            raise ToolError("enter_mode(mode='combat') requires an encounter_id.")
        return await _start_combat_impl(context, encounter_id, encounter_description)
    if mode == "dispatch":
        return await _enter_dispatch_impl(context)
    if mode == "blacksmith":
        return await _enter_blacksmith_impl(context)
    raise ToolError(f"Unknown mode {mode!r}; expected one of: {', '.join(VALID_MODES)}.")
