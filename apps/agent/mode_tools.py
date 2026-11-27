"""The exploration verb that hands off to a focused gameplay mode."""

from typing import Literal

from livekit.agents.llm import ToolError, function_tool
from livekit.agents.voice import RunContext

from action_sound_content import ACTION_SOUND_EXPORTS, publish_action_sound
from blacksmith_tools import _enter_blacksmith_impl
from combat_init import _start_combat_impl
from db_errors import db_tool
from dispatch_tools import _enter_dispatch_impl
from merchant_tools import _enter_trade_impl
from session_data import SessionData

VALID_MODES = ("combat", "dispatch", "blacksmith", "trade")


@function_tool()
@db_tool
async def enter_mode(
    context: RunContext[SessionData],
    mode: str,
    encounter_id: str,
    encounter_description: str = "",
    difficulty: str = "",
    tier: int | None = None,
    initiated_by: Literal["enemies"] | Literal["party"] | None = None,
) -> str | tuple:
    """Hand off to a focused mode context. Always pass encounter_id.
    Use "" when there is no encounter template. Pick a mode:

    - mode="combat": combat begins. Give encounter_id (the encounter template) and
      encounter_description (a brief note on how combat starts). Rolls initiative and
      establishes turn order. For generated combat, give difficulty="standard",
      "tough" or "boss" to generate catalog enemies for this location; optional tier=1-4
      overrides the party tier. A nonempty encounter_id cannot be combined with difficulty or tier.
      Set initiated_by="enemies" if enemies started the fight, or "party" if the party
      started it. Leaving it unset grants no sanctuary initiative bonus.
    - mode="dispatch": the player wants a deliberate between-adventure activity —
      training with a mentor, or sending a companion on an errand.
    - mode="blacksmith": the player wants to repair gear at a settlement forge. A
      forge is a settlement activity; only offer it where one would plausibly exist.
    - mode="trade": the player wants to sell goods to a shopkeeper.

    Control returns here when the mode concludes."""
    return await _enter_mode_impl(
        context, mode, encounter_id, encounter_description, difficulty, tier, initiated_by=initiated_by
    )


async def _enter_mode_impl(
    context: RunContext[SessionData],
    mode: str,
    encounter_id: str = "",
    encounter_description: str = "",
    difficulty: str = "",
    tier: int | None = None,
    *,
    initiated_by: str | None = None,
) -> str | tuple:
    if mode == "combat":
        return await _start_combat_impl(
            context, encounter_id, encounter_description, difficulty=difficulty, tier=tier, initiated_by=initiated_by
        )
    if mode == "dispatch":
        result = await _enter_dispatch_impl(context)
        await publish_action_sound(context.userdata, ACTION_SOUND_EXPORTS["ACTION_ENTER_MODE_DISPATCH"])
        return result
    if mode == "blacksmith":
        result = await _enter_blacksmith_impl(context)
        await publish_action_sound(context.userdata, ACTION_SOUND_EXPORTS["ACTION_ENTER_MODE_BLACKSMITH"])
        return result
    if mode == "trade":
        result = await _enter_trade_impl(context)
        await publish_action_sound(context.userdata, ACTION_SOUND_EXPORTS["ACTION_ENTER_MODE_TRADE"])
        return result
    raise ToolError(f"Unknown mode {mode!r}; expected one of: {', '.join(VALID_MODES)}.")
