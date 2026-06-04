"""DungeonAgent — handles dungeon crawling with traps, puzzles, and corruption."""

from typing import Any

from check_tools import check
from choice_tools import select
from environment_tools import play_sound, set_music_state
from gameplay_agent import GameplayAgent
from inventory_tools import transact
from mode_tools import enter_mode
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
    check,
    update_quest,
    # Combat + dispatch handoffs fold into the single enter_mode verb (M5, ADR 0007).
    enter_mode,
    award_xp,
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
