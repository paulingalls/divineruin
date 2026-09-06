"""CombatAgent — handles structured combat encounters with focused tools and prompt."""

from typing import Any

from livekit import agents

from activate_tools import activate
from base_agent import BaseGameAgent
from check_tools import check
from combat_death_save import request_death_save
from combat_end import end_combat
from combat_turn import consume_legendary_action, declare_phase, resolve_phase
from query_tools import query_info
from session_data import SessionData
from spell_info_tools import get_spell_info
from system_prompts import COMBAT_SYSTEM_PROMPT
from warm_prompts import format_combat_hot_line

# The phase-loop drives combat (M4.1, story-003): declare_phase collects a round's
# declarations, resolve_phase resolves them in initiative order and fires end_combat on
# the engine's wrap end-condition. The old per-actor resolve_enemy_turn/request_attack
# verbs are gone — all damage routes through CombatParticipant HP via the packet path.
#
# The `select` verb is intentionally NOT here. Combat DOES award XP now — end_combat grants it
# party-wide inside its own transaction (M28 story-001), so an L10/15/20 auto-grant applies mid-
# teardown — but the L5 fork it can surface is only ever RESOLVED after the handoff: end_combat
# returns the exploration agent in the same breath, and select lives there (concern 3c02318dfa99).
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

    async def on_user_turn_completed(
        self, turn_ctx: agents.llm.ChatContext, new_message: agents.llm.ChatMessage
    ) -> None:
        """Put the round and every participant's HP status in the HOT layer.

        A message, not instructions: livekit's anthropic plugin caches on the last system
        block, so re-rendering the fight into the system prompt each round would rewrite
        the prefix and the whole message history behind it (debt ce06dd8c).
        """
        sd: SessionData = self.session.userdata
        hot = format_combat_hot_line(sd.combat_state)
        if hot:
            turn_ctx.add_message(role="assistant", content=hot)


def create_combat_agent(chat_ctx: Any = None) -> CombatAgent:
    """Factory for CombatAgent — mockable in tests to avoid LiveKit lifecycle warnings."""
    return CombatAgent(chat_ctx=chat_ctx)
