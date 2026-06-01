"""CombatAgent — handles structured combat encounters with focused tools and prompt."""

from typing import Any

from ability_tools import request_ability_activation
from base_agent import BaseGameAgent
from check_tools import request_attack, request_saving_throw, roll_dice
from combat_end import end_combat
from combat_turn import request_death_save, resolve_enemy_turn
from environment_tools import play_sound, set_music_state
from query_tools import query_info
from system_prompts import COMBAT_SYSTEM_PROMPT

COMBAT_AGENT_TOOLS = [
    resolve_enemy_turn,
    request_attack,
    request_saving_throw,
    request_death_save,
    end_combat,
    roll_dice,
    play_sound,
    set_music_state,
    query_info,
    request_ability_activation,
]


class CombatAgent(BaseGameAgent):
    """Specialized agent for running combat encounters.

    Uses COMBAT_SYSTEM_PROMPT (staccato narration, initiative tracking) and
    a focused tool set (no exploration or mutation tools). Handed off to by
    start_combat on DungeonMasterAgent, hands back via end_combat.
    """

    def __init__(self, chat_ctx: Any = None) -> None:
        super().__init__(
            instructions=COMBAT_SYSTEM_PROMPT,
            tools=COMBAT_AGENT_TOOLS,
            chat_ctx=chat_ctx,
        )


def create_combat_agent(chat_ctx: Any = None) -> CombatAgent:
    """Factory for CombatAgent — mockable in tests to avoid LiveKit lifecycle warnings."""
    return CombatAgent(chat_ctx=chat_ctx)
