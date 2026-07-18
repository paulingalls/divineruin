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

from activity_tools import begin_activity, resolve_activity
from base_agent import BaseGameAgent
from card_tap_handler import SpecializationTapHandler, start_specialization_tap
from check_tools import check
from choice_tools import select
from dispatch_tools import conclude_dispatch
from movement_tools import move_player
from query_tools import query_info
from recipe_tools import learn
from session_tools import end_session
from system_prompts import DISPATCH_SYSTEM_PROMPT

DISPATCH_TOOLS = [
    # Downtime activities (training, companion errands, crafting, workspaces,
    # experimentation) fold into these two verbs (M26 Phase-5, story-003).
    begin_activity,
    resolve_activity,
    # Recipe acquisition (M5.1 crafting; learn verb M5 story-002)
    learn,
    # Resolve a pending player choice (the L5 specialization fork) — leveling can land
    # mid-training, so select must be reachable here too, not only in exploration (story-004).
    select,
    # Navigation / queries — enough to talk to the mentor and leave
    move_player,
    query_info,
    check,
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
        self._spec_tap: SpecializationTapHandler | None = None

    async def on_enter(self) -> None:
        await super().on_enter()
        # Host the L5 specialization-tap consumer: training-driven level-ups can surface
        # the fork here, so a tap (or DM voice) resolves it via select without a handoff.
        sd = self.session.userdata
        assert sd.room is not None  # room is set before the agent enters
        self._spec_tap = start_specialization_tap(sd.room, self.session, sd)

    async def on_exit(self) -> None:
        if self._spec_tap:
            self._spec_tap.stop()
        await super().on_exit()


def create_dispatch_agent(chat_ctx: Any = None) -> DispatchAgent:
    """Factory for DispatchAgent — mockable in tests to avoid LiveKit lifecycle warnings."""
    return DispatchAgent(chat_ctx=chat_ctx)
