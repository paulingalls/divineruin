"""create_gameplay_agent — factory for the single ExplorationAgent.

M7 collapsed the three region agents into one ExplorationAgent. This factory is
kept (name + location) so the handoff call sites (combat_end, dispatch_tools,
movement_tools, agent.py) construct the agent through one stable entry point.
"""

from typing import Any

from exploration_agent import ExplorationAgent
from region_types import REGION_CITY, REGION_DUNGEON, REGION_WILDERNESS

_KNOWN_REGIONS = (REGION_CITY, REGION_WILDERNESS, REGION_DUNGEON)


def create_gameplay_agent(
    region_type: str,
    location_id: str,
    companion: Any = None,
    chat_ctx: Any = None,
) -> ExplorationAgent:
    """Build the exploration agent for a region_type. Unknown regions default to city."""
    region = region_type if region_type in _KNOWN_REGIONS else REGION_CITY
    return ExplorationAgent(
        initial_location=location_id,
        companion=companion,
        chat_ctx=chat_ctx,
        region_type=region,
    )
