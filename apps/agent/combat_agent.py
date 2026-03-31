"""CombatAgent — handles structured combat encounters with focused tools and prompt."""

from typing import Any

from base_agent import BaseGameAgent
from prompts import COMBAT_SYSTEM_PROMPT
from tools import (
    end_combat,
    play_sound,
    query_inventory,
    request_attack,
    request_death_save,
    request_saving_throw,
    resolve_enemy_turn,
    roll_dice,
    set_music_state,
)

COMBAT_AGENT_TOOLS = [
    resolve_enemy_turn,
    request_attack,
    request_saving_throw,
    request_death_save,
    end_combat,
    roll_dice,
    play_sound,
    set_music_state,
    query_inventory,
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
