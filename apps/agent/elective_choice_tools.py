"""Resolve initial elective ownership under the acting player's row lock."""

import json

from livekit.agents import ToolError

import abilities
import ability_persistence
import elective_choices
from session_data import SessionData


async def select(session: SessionData, choice_id: str, option: str, *, db_mod, queries_mod) -> str:
    levels = {f"{elective_choices.PREFIX}{tier}": tier for tier in elective_choices.TIERS}
    if choice_id not in levels:
        raise ToolError(f"Unknown elective choice: {choice_id}.")
    level = levels[choice_id]
    actor = session.acting_player_id
    async with session.combat_state_lock, db_mod.transaction() as conn:
        players = await queries_mod.get_players_for_update([actor], conn=conn)
        player = players.get(actor)
        if player is None:
            raise ToolError(f"Unknown player: {actor}.")
        catalog = abilities.get_archetype_abilities(player["class"])
        pool = elective_choices.pool(catalog, level)
        if not pool:
            raise ToolError(f"Your archetype has no elective technique pool at level {level}.")
        if player["level"] < level:
            raise ToolError(f"You have not reached elective technique level {level}.")
        owned = await ability_persistence.get_character_abilities(actor, conn=conn)
        if elective_choices.already_chosen(pool, {row["ability_id"] for row in owned}):
            raise ToolError(f"Your level {level} elective technique was already chosen.")
        chosen = next((ability for ability in pool if ability.id == option), None)
        if chosen is None:
            raise ToolError(f"'{option}' is not in your level {level} elective technique pool.")
        session.validate_acting_player(actor)
        await ability_persistence.set_elective_equipped(actor, option, True, conn=conn)
    return json.dumps(
        {
            "player_id": actor,
            "choice_id": choice_id,
            "chosen": chosen.id,
            **elective_choices.describe(chosen),
        }
    )
