"""WildernessAgent — handles travel, exploration, and encounters in open terrain."""

from typing import Any

from check_tools import discover_hidden_element, request_skill_check, roll_dice
from combat_init import start_combat
from environment_tools import play_sound, set_music_state
from gameplay_agent import GameplayAgent
from movement_tools import move_player
from progression_tools import award_xp
from query_tools import query_inventory, query_location, query_lore
from quest_tools import update_quest
from region_types import REGION_WILDERNESS
from scene_tools import enter_location
from session_tools import end_session, record_story_moment

WILDERNESS_TOOLS = [
    enter_location,
    query_location,
    move_player,
    request_skill_check,
    discover_hidden_element,
    update_quest,
    roll_dice,
    start_combat,
    award_xp,
    query_inventory,
    query_lore,
    record_story_moment,
    play_sound,
    set_music_state,
    end_session,
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
