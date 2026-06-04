"""WildernessAgent — handles travel, exploration, and encounters in open terrain."""

from typing import Any

from check_tools import check
from choice_tools import select
from combat_init import start_combat
from dispatch_tools import enter_dispatch
from environment_tools import play_sound, set_music_state
from gameplay_agent import GameplayAgent
from movement_tools import move_player
from progression_tools import award_xp
from query_tools import query_info
from quest_tools import update_quest
from region_types import REGION_WILDERNESS
from scene_tools import enter_location
from session_tools import end_session, record_story_moment

WILDERNESS_TOOLS = [
    enter_location,
    query_info,
    move_player,
    check,
    update_quest,
    start_combat,
    enter_dispatch,
    award_xp,
    record_story_moment,
    play_sound,
    set_music_state,
    end_session,
    # Leveling happens here via award_xp — the L5 fork resolves via the select verb (3c02318dfa99).
    select,
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
