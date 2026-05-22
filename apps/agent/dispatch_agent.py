"""DispatchAgent — handles deliberate between-adventure activities (training now;
companion errands in M1.6 story-009) with a focused tool set and one prompt.

Reached two ways: by moving into an activity-context location (move_player hands
off, mirroring the combat/region handoff) and by an intent handoff (enter_dispatch)
from any region agent. The entry chat_ctx sets the specific scene (training hall vs
companion dispatch). Keeping these tools off the region agents holds each under
Anthropic's strict-tool ceiling (llm_config.MAX_STRICT_TOOLS; see
docs/decisions/0004-agent-tool-scaling.md).
"""

from typing import Any

from base_agent import BaseGameAgent
from check_tools import roll_dice
from dispatch_tools import conclude_dispatch
from environment_tools import play_sound, set_music_state
from movement_tools import move_player
from query_tools import query_info
from session_tools import end_session
from system_prompts import DISPATCH_SYSTEM_PROMPT
from training_tools import initiate_training_cycle, query_training_programs, resolve_training_midpoint

DISPATCH_TOOLS = [
    # Training (the first async activity; errands join in story-009)
    query_training_programs,
    initiate_training_cycle,
    resolve_training_midpoint,
    # Navigation / queries — enough to talk to the mentor and leave
    move_player,
    query_info,
    roll_dice,
    play_sound,
    set_music_state,
    end_session,
    # Return to ordinary play (the intent-route exit; location route uses move_player)
    conclude_dispatch,
]


class DispatchAgent(BaseGameAgent):
    """Specialized agent for deliberate between-adventure activities.

    Uses DISPATCH_SYSTEM_PROMPT and a focused tool set. Reached by moving into an
    activity-context location, or by an intent handoff from a region agent.
    """

    def __init__(self, chat_ctx: Any = None) -> None:
        super().__init__(
            instructions=DISPATCH_SYSTEM_PROMPT,
            tools=DISPATCH_TOOLS,
            chat_ctx=chat_ctx,
        )


def create_dispatch_agent(chat_ctx: Any = None) -> DispatchAgent:
    """Factory for DispatchAgent — mockable in tests to avoid LiveKit lifecycle warnings."""
    return DispatchAgent(chat_ctx=chat_ctx)
