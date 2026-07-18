"""CombatAgent — handles structured combat encounters with focused tools and prompt."""

from typing import Any

from activate_tools import activate
from base_agent import BaseGameAgent
from check_tools import check
from combat_death_save import request_death_save
from combat_end import end_combat
from combat_turn import consume_legendary_action, declare_phase, resolve_phase
from query_tools import query_info
from spell_info_tools import get_spell_info
from system_prompts import COMBAT_SYSTEM_PROMPT

# The phase-loop drives combat (M4.1, story-003): declare_phase collects a round's
# declarations, resolve_phase resolves them in initiative order and fires end_combat on
# the engine's wrap end-condition. The old per-actor resolve_enemy_turn/request_attack
# verbs are gone — all damage routes through CombatParticipant HP via the packet path.
#
# resolve_milestone is intentionally NOT here: combat never awards XP (end_combat hands
# back to the exploration agent, which calls award_xp), so milestones never resolve in
# combat. It lives in the exploration agents instead (concern 3c02318dfa99).
COMBAT_AGENT_TOOLS = [
    declare_phase,
    resolve_phase,
    consume_legendary_action,
    check,
    request_death_save,
    end_combat,
    query_info,
    activate,
    get_spell_info,
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
