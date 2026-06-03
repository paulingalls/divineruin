"""DungeonAgent — handles dungeon crawling with traps, puzzles, and corruption."""

from typing import Any

from check_tools import discover_hidden_element, request_saving_throw, request_skill_check, roll_dice
from choice_tools import select
from combat_init import start_combat
from dispatch_tools import enter_dispatch
from environment_tools import play_sound, set_music_state
from gameplay_agent import GameplayAgent
from inventory_tools import transact
from movement_tools import move_player
from progression_tools import award_xp
from query_tools import query_info
from quest_tools import update_quest
from region_types import REGION_DUNGEON
from scene_tools import enter_location
from session_tools import end_session, record_story_moment

DUNGEON_TOOLS = [
    enter_location,
    query_info,
    move_player,
    request_skill_check,
    request_saving_throw,
    discover_hidden_element,
    update_quest,
    start_combat,
    enter_dispatch,
    award_xp,
    roll_dice,
    transact,
    record_story_moment,
    play_sound,
    set_music_state,
    end_session,
    # Leveling happens here via award_xp — the L5 fork resolves via the select verb (3c02318dfa99).
    select,
]


class DungeonAgent(GameplayAgent):
    """Gameplay agent for dungeon exploration."""

    _agent_type = REGION_DUNGEON

    def __init__(
        self,
        initial_location: str = "greyvale_ruins_entrance",
        companion: Any = None,
        chat_ctx: Any = None,
    ) -> None:
        super().__init__(
            initial_location=initial_location,
            companion=companion,
            chat_ctx=chat_ctx,
            tools=DUNGEON_TOOLS,
        )
