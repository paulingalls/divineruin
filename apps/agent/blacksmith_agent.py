"""BlacksmithAgent — handles settlement-forge item repair with a focused tool set.

Split from story-004 (the customer chose a dedicated agent over folding repair into
DispatchAgent). Holds repair_item off the region/dispatch agents so each stays under
Anthropic's strict-tool ceiling (llm_config.MAX_STRICT_TOOLS; ADR 0004). Reached by
an intent handoff (enter_mode(mode="blacksmith"), M5 fold) from a region agent; hands
back via conclude_blacksmith. Mirrors the CombatAgent/DispatchAgent (Agent, json) tuple
handoff.
"""

from typing import Any

from base_agent import BaseGameAgent
from blacksmith_tools import conclude_blacksmith
from environment_tools import play_sound, set_music_state
from query_tools import query_info
from repair_item import repair_item
from system_prompts import BLACKSMITH_SYSTEM_PROMPT

BLACKSMITH_TOOLS = [
    # The forge's reason to exist: NPC-blacksmith item repair (M5.4).
    repair_item,
    # Talk to the smith and set the scene.
    query_info,
    play_sound,
    set_music_state,
    # The sole exit back to region play (mirrors CombatAgent exiting via end_combat).
    conclude_blacksmith,
]


class BlacksmithAgent(BaseGameAgent):
    """Specialized agent for repairing gear at a settlement forge.

    Uses BLACKSMITH_SYSTEM_PROMPT and a focused tool set (no combat, exploration,
    movement, or session tools). Handed off to by enter_mode(mode="blacksmith") from a
    region agent; hands back via conclude_blacksmith.
    """

    def __init__(self, chat_ctx: Any = None) -> None:
        super().__init__(
            instructions=BLACKSMITH_SYSTEM_PROMPT,
            tools=BLACKSMITH_TOOLS,
            chat_ctx=chat_ctx,
        )


def create_blacksmith_agent(chat_ctx: Any = None) -> BlacksmithAgent:
    """Factory for BlacksmithAgent — mockable in tests to avoid LiveKit lifecycle warnings."""
    return BlacksmithAgent(chat_ctx=chat_ctx)
