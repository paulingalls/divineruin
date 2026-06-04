"""CityAgent — handles settlement/city gameplay with focused tools and prompt."""

from typing import Any

from check_tools import check
from choice_tools import select
from environment_tools import play_sound, set_music_state
from gameplay_agent import GameplayAgent
from inventory_tools import transact
from mode_tools import enter_mode
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
    check,
    # Mechanics
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
    # Mode handoffs (combat / dispatch / blacksmith) fold into the single enter_mode
    # verb (M5, ADR 0007). Combat, the DispatchAgent activity context, and the
    # BlacksmithAgent forge are all reached via enter_mode(mode=...); their focused
    # toolsets live on the respective mode agents — keeps City under MAX_STRICT_TOOLS.
    # See docs/decisions/0004-agent-tool-scaling.md.
    enter_mode,
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
