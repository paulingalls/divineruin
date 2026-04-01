"""WildernessAgent — handles travel, exploration, and encounters in open terrain."""

from typing import Any

from gameplay_agent import GameplayAgent
from region_types import REGION_WILDERNESS
from tools import (
    discover_hidden_element,
    enter_location,
    move_player,
    play_sound,
    query_inventory,
    query_location,
    query_lore,
    record_story_moment,
    request_skill_check,
    roll_dice,
    set_music_state,
    start_combat,
    update_quest,
)

WILDERNESS_TOOLS = [
    enter_location,
    query_location,
    move_player,
    request_skill_check,
    discover_hidden_element,
    update_quest,
    roll_dice,
    start_combat,
    query_inventory,
    query_lore,
    record_story_moment,
    play_sound,
    set_music_state,
]


class WildernessAgent(GameplayAgent):
    """Gameplay agent for wilderness travel and exploration."""

    _agent_type = REGION_WILDERNESS

    def __init__(
        self,
        initial_location: str = "greyvale_south_road",
        companion: Any = None,
        chat_ctx: Any = None,
    ) -> None:
        super().__init__(
            initial_location=initial_location,
            companion=companion,
            chat_ctx=chat_ctx,
            tools=WILDERNESS_TOOLS,
        )
