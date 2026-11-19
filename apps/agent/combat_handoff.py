"""The exploration agent a party returns to when combat ends."""

import logging

from region_types import REGION_CITY
from session_data import SessionData

logger = logging.getLogger("divineruin.tools")


def build_handoff_agent(session: SessionData, agent_type: str, summary_ctx):
    """Construct the exploration agent the party returns to — the ONE fallible step in an
    otherwise in-memory teardown, isolated here with a fallback (concern 9e2685165f07).

    It runs AFTER ``combat_state`` has been cleared (which it must, or a retried end pays the
    party twice), and the agent it returns is the only exit from CombatAgent. So a raise out of
    here would strand the session in combat forever with its rewards already banked — the exact
    outcome the post-commit ordering exists to prevent. Agent construction reaches real work
    (system-prompt assembly over the companion profile, toolset composition, the summary
    ChatContext), so "it is just a constructor" is not a guarantee.

    The fallback drops every optional input and rebuilds at the default region: losing the combat
    summary and the companion's voice for one turn is survivable, being unable to leave combat is
    not. If even that raises, the process is broken and the exception is the honest answer.
    """
    from gameplay_agent import create_gameplay_agent

    try:
        return create_gameplay_agent(agent_type, session.location_id, companion=session.companion, chat_ctx=summary_ctx)
    except Exception:
        logger.exception(
            "Combat handoff agent (%s) failed to build; falling back to a bare exploration agent so the "
            "party can leave combat. The combat summary and companion context are lost for this handoff.",
            agent_type,
        )
        return create_gameplay_agent(REGION_CITY, session.location_id)
