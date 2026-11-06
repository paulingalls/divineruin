"""Resolve terrain at the IO boundary; combat caches never fall back to location reads."""

from livekit.agents.llm import ToolError

import db_content_queries
from combat_state import CombatState
from patron_gifts import NATURES_PULSE_SKILLS, thyra_gift
from session_data import SessionData
from terrain import is_natural, properties


async def resolve_terrain(
    session: SessionData, *, combat_state: CombatState | None = None, content_mod=db_content_queries
) -> str:
    combat = combat_state or session.combat_state
    location_id = combat.location_id if combat is not None else session.location_id
    try:
        value = combat.terrain if combat is not None else await content_mod.get_location_terrain(location_id)
        if not isinstance(value, str) or not value:
            raise ValueError("missing cached terrain" if combat is not None else "missing terrain")
        properties(value)
    except ValueError as error:
        raise ToolError(f"Location '{location_id}' has unresolvable terrain: {error}") from error
    return value


async def skill_natural_terrain(
    session: SessionData,
    player: dict,
    skill: str,
    *,
    combat_state: CombatState | None = None,
    content_mod=db_content_queries,
) -> bool:
    if thyra_gift(player.get("divine_favor") or {}) is None or skill.lower() not in NATURES_PULSE_SKILLS:
        return False
    return is_natural(await resolve_terrain(session, combat_state=combat_state, content_mod=content_mod))
