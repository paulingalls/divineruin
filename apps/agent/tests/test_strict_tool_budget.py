"""Pin every agent's tool list under the Anthropic strict-tool ceiling.

The ceiling lives once, in llm_config.MAX_STRICT_TOOLS. A tool addition that
breaches it should fail here as a unit test, not in production as a 400
(see ADR 0004 for the captured "too many strict tools" error).
"""

import pytest

from blacksmith_agent import BLACKSMITH_TOOLS
from city_agent import CITY_TOOLS
from combat_agent import COMBAT_AGENT_TOOLS
from creation_agent import CREATION_TOOLS
from dispatch_agent import DISPATCH_TOOLS
from dungeon_agent import DUNGEON_TOOLS
from llm_config import MAX_STRICT_TOOLS
from onboarding_agent import ONBOARDING_TOOLS
from wilderness_agent import WILDERNESS_TOOLS

AGENT_TOOL_LISTS = [
    ("city", CITY_TOOLS),
    ("wilderness", WILDERNESS_TOOLS),
    ("dungeon", DUNGEON_TOOLS),
    ("combat", COMBAT_AGENT_TOOLS),
    ("training", DISPATCH_TOOLS),
    ("creation", CREATION_TOOLS),
    ("onboarding", ONBOARDING_TOOLS),
    ("blacksmith", BLACKSMITH_TOOLS),
]


@pytest.mark.parametrize("name,tools", AGENT_TOOL_LISTS)
def test_agent_within_strict_tool_limit(name, tools):
    assert len(tools) <= MAX_STRICT_TOOLS, f"{name} has {len(tools)} strict tools (ceiling {MAX_STRICT_TOOLS})"


def test_city_strict_tool_count():
    # City reached the ceiling (20) after story-007/008/009/010. M5 verb consolidation is
    # reclaiming slots: story-001's transact folded add/remove_from_inventory (20->19),
    # story-003's check absorbed discover_hidden_element + request_skill_check + roll_dice
    # (19->17 — three tools into one), and story-004's enter_mode folded start_combat +
    # enter_dispatch + enter_blacksmith (17->15 — three handoffs into one), easing the
    # M2.4 spell-tool pressure (ADR 0004).
    assert len(CITY_TOOLS) == 15
    assert len(CITY_TOOLS) == MAX_STRICT_TOOLS - 5
