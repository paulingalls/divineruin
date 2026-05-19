"""CityAgent — handles settlement/city gameplay with focused tools and prompt."""

from typing import Any

from check_tools import discover_hidden_element, request_attack, request_saving_throw, request_skill_check, roll_dice
from combat_init import start_combat
from environment_tools import play_sound, set_music_state
from gameplay_agent import GameplayAgent
from inventory_tools import add_to_inventory, remove_from_inventory
from movement_tools import move_player
from progression_tools import award_divine_favor, award_xp
from query_tools import query_inventory, query_location, query_lore, query_npc
from quest_tools import update_quest
from region_types import REGION_CITY
from scene_tools import enter_location
from session_tools import end_session, record_story_moment, update_npc_disposition
from training_tools import initiate_training_cycle, query_training_programs, resolve_training_midpoint

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
    # Training (M1.5) — cities only. Mentors live in cities today; wilderness/dungeon agents
    # intentionally omit. Revisit if hunter/ranger mentor systems land.
    query_training_programs,
    initiate_training_cycle,
    resolve_training_midpoint,
    # Combat handoff
    start_combat,
]


class CityAgent(GameplayAgent):
    """Gameplay agent for settlement/city exploration."""

    _agent_type = REGION_CITY

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
