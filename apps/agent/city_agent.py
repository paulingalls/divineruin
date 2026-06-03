"""CityAgent — handles settlement/city gameplay with focused tools and prompt."""

from typing import Any

from blacksmith_tools import enter_blacksmith
from check_tools import discover_hidden_element, request_skill_check, roll_dice
from choice_tools import select
from combat_init import start_combat
from dispatch_tools import enter_dispatch
from environment_tools import play_sound, set_music_state
from gameplay_agent import GameplayAgent
from inventory_tools import transact
from movement_tools import move_player
from progression_tools import award_divine_favor, award_xp
from query_tools import query_info
from quest_tools import update_quest
from region_types import REGION_CITY
from scene_tools import enter_location
from session_tools import end_session, record_story_moment, update_npc_disposition

CITY_TOOLS = [
    # World query
    enter_location,
    query_info,
    discover_hidden_element,
    # Mechanics
    request_skill_check,
    roll_dice,
    play_sound,
    set_music_state,
    # Mutation
    move_player,
    transact,
    update_quest,
    award_xp,
    award_divine_favor,
    update_npc_disposition,
    record_story_moment,
    end_session,
    # Choice resolution: the L5 specialization fork (surfaced by award_xp on level-up)
    # resolves via the generic select verb (concern 3c02318dfa99). City is still AT the
    # strict-tool ceiling — relieved structurally by M7's exploration-agent collapse (debt e665104c753a).
    select,
    # Activity dispatch lives in DispatchAgent (reached by enter_dispatch intent
    # handoff, or by moving into an activity-context location) — keeps City under
    # MAX_STRICT_TOOLS. See docs/decisions/0004-agent-tool-scaling.md.
    enter_dispatch,
    # Forge repair lives in BlacksmithAgent (reached by enter_blacksmith intent
    # handoff). City-only — blacksmiths are settlement NPCs (story-009).
    enter_blacksmith,
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
