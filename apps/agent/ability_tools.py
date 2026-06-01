"""Archetype ability activation tool for the DM agent (M2.2).

request_ability_activation validates a character's Stamina/Focus against an
ability's cost, deducts on success, rejects via ToolError when insufficient, and
returns the ability's narration_cue for the DM to voice.

Cost is a {stamina, focus, scaling} object (decision m22-cost-object-schema).
Variable/pool-cost abilities (Lay on Hands, Divine Smite) carry cost{0,0} with the
real cost in the free-text scaling field. The tool always surfaces scaling as
variable_cost so the DM tracks the pool/variable portion — a scaling-bearing
ability is NEVER reported as a plain free activation (resolves concern
7b34ebf86b57). Combat-window gating for reactions is deferred to Phase 4.
"""

import json
import logging

from livekit.agents.llm import ToolError, function_tool
from livekit.agents.voice import RunContext

import abilities
import ability_persistence
import db
import db_queries
from db_errors import db_tool
from session_data import SessionData
from tool_support import _validate_id

logger = logging.getLogger("divineruin.tools")


@function_tool()
@db_tool
async def request_ability_activation(
    context: RunContext[SessionData],
    ability_id: str,
) -> str:
    """Activate one of the character's archetype abilities.
    Call when the player uses a named ability, technique, spell, or reaction.
    Provide the ability_id (e.g. 'warrior_devastating_strike'). Validates and
    deducts the Stamina/Focus cost, rejecting if the character lacks the resource.
    Returns the narration cue to voice; for pool/variable-cost abilities (e.g. Lay
    on Hands) the variable_cost field carries the rule for you to track."""
    return await _request_ability_activation_impl(context, ability_id)


async def _request_ability_activation_impl(
    context: RunContext[SessionData],
    ability_id: str,
    *,
    db_mod=db,
    queries_mod=db_queries,
    persistence_mod=ability_persistence,
    abilities_mod=abilities,
) -> str:
    context.disallow_interruptions()
    _validate_id(ability_id, "ability_id")
    session: SessionData = context.userdata
    player_id = session.player_id
    logger.info("request_ability_activation called: ability=%s player=%s", ability_id, player_id)

    try:
        ability = abilities_mod.get_ability(ability_id)
    except ValueError as e:
        raise ToolError(str(e)) from e
    cost = ability.cost

    async with db_mod.transaction() as conn:
        player = await queries_mod.get_player(player_id, conn=conn, for_update=True)
        if player is None:
            raise ToolError(f"Unknown player: {player_id}")

        stamina_pool = player.get("stamina") or {}
        focus_pool = player.get("focus") or {}
        current_stamina = stamina_pool.get("current", 0)
        current_focus = focus_pool.get("current", 0)

        if cost.stamina > 0:
            if "current" not in stamina_pool:
                raise ToolError(f"{ability.name} costs Stamina but you have no Stamina pool.")
            if cost.stamina > current_stamina:
                raise ToolError(
                    f"Not enough Stamina for {ability.name}: costs {cost.stamina}, you have {current_stamina}."
                )
        if cost.focus > 0:
            if "current" not in focus_pool:
                raise ToolError(f"{ability.name} costs Focus but you have no Focus pool.")
            if cost.focus > current_focus:
                raise ToolError(f"Not enough Focus for {ability.name}: costs {cost.focus}, you have {current_focus}.")

        new_stamina = current_stamina - cost.stamina if cost.stamina > 0 else None
        new_focus = current_focus - cost.focus if cost.focus > 0 else None
        if new_stamina is not None or new_focus is not None:
            await persistence_mod.update_player_resources(player_id, stamina=new_stamina, focus=new_focus, conn=conn)

    return json.dumps(
        {
            "narration_cue": ability.narration_cue,
            "deducted": {"stamina": cost.stamina, "focus": cost.focus},
            "variable_cost": cost.scaling,
        }
    )
