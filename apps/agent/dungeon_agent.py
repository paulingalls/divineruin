"""DungeonAgent — handles dungeon crawling with traps, puzzles, and corruption."""

from typing import Any

from gameplay_agent import GameplayAgent
from region_types import REGION_DUNGEON
from tools import (
    add_to_inventory,
    award_xp,
    discover_hidden_element,
    end_session,
    enter_location,
    move_player,
    play_sound,
    query_inventory,
    query_location,
    query_lore,
    record_story_moment,
    request_saving_throw,
    request_skill_check,
    roll_dice,
    set_music_state,
    start_combat,
    update_quest,
)

DUNGEON_TOOLS = [
    enter_location,
    query_location,
    move_player,
    request_skill_check,
    request_saving_throw,
    discover_hidden_element,
    update_quest,
    start_combat,
    award_xp,
    roll_dice,
    query_inventory,
    add_to_inventory,
    query_lore,
    record_story_moment,
    play_sound,
    set_music_state,
    end_session,
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
