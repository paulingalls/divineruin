"""CityAgent — handles settlement/city gameplay with focused tools and prompt."""

from typing import Any

from gameplay_agent import GameplayAgent
from tools import (
    add_to_inventory,
    award_divine_favor,
    award_xp,
    discover_hidden_element,
    end_session,
    enter_location,
    move_player,
    play_sound,
    query_inventory,
    query_location,
    query_lore,
    query_npc,
    record_story_moment,
    remove_from_inventory,
    request_attack,
    request_saving_throw,
    request_skill_check,
    roll_dice,
    set_music_state,
    start_combat,
    update_npc_disposition,
    update_quest,
)

CITY_TOOLS = [
    # World query
    enter_location,
    query_location,
    query_npc,
    query_lore,
    query_inventory,
    discover_hidden_element,
    # Mechanics
    request_skill_check,
    request_attack,
    request_saving_throw,
    roll_dice,
    play_sound,
    set_music_state,
    # Mutation
    move_player,
    add_to_inventory,
    remove_from_inventory,
    update_quest,
    award_xp,
    award_divine_favor,
    update_npc_disposition,
    record_story_moment,
    end_session,
    # Combat handoff
    start_combat,
]


class CityAgent(GameplayAgent):
    """Gameplay agent for settlement/city exploration."""

    _agent_type = "city"

    def __init__(
        self,
        initial_location: str = "accord_guild_hall",
        companion: Any = None,
        chat_ctx: Any = None,
    ) -> None:
        super().__init__(
            initial_location=initial_location,
            companion=companion,
            chat_ctx=chat_ctx,
            tools=CITY_TOOLS,
        )
