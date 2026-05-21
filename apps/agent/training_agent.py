"""TrainingAgent — handles mentor-led training with a focused tool set and prompt.

Players reach it by moving into a training-context location (move_player hands
off, mirroring the combat/region handoff); moving back out re-resolves to the
region agent. Splitting training out keeps CityAgent under Anthropic's 20-strict-
tool limit (see docs/decisions/0004-agent-tool-scaling.md).
"""

from typing import Any

from base_agent import BaseGameAgent
from check_tools import roll_dice
from environment_tools import play_sound, set_music_state
from movement_tools import move_player
from query_tools import query_location, query_lore, query_npc
from session_tools import end_session
from system_prompts import TRAINING_SYSTEM_PROMPT
from training_tools import initiate_training_cycle, query_training_programs, resolve_training_midpoint

TRAINING_TOOLS = [
    # Training (the activity this agent exists for)
    query_training_programs,
    initiate_training_cycle,
    resolve_training_midpoint,
    # Navigation / queries — enough to talk to the mentor and leave
    move_player,
    query_location,
    query_npc,
    query_lore,
    roll_dice,
    play_sound,
    set_music_state,
    end_session,
]


class TrainingAgent(BaseGameAgent):
    """Specialized agent for mentor-led training cycles.

    Uses TRAINING_SYSTEM_PROMPT and a focused tool set. Handed off to when the
    player enters a training-context location; hands back when they move out.
    """

    def __init__(self, chat_ctx: Any = None) -> None:
        super().__init__(
            instructions=TRAINING_SYSTEM_PROMPT,
            tools=TRAINING_TOOLS,
            chat_ctx=chat_ctx,
        )


def create_training_agent(chat_ctx: Any = None) -> TrainingAgent:
    """Factory for TrainingAgent — mockable in tests to avoid LiveKit lifecycle warnings."""
    return TrainingAgent(chat_ctx=chat_ctx)
