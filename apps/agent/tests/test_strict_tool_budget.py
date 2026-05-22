"""Pin every agent's tool list under the Anthropic strict-tool ceiling.

The ceiling lives once, in llm_config.MAX_STRICT_TOOLS. A tool addition that
breaches it should fail here as a unit test, not in production as a 400
(see ADR 0004 for the captured "too many strict tools" error).
"""

import pytest

from city_agent import CITY_TOOLS
from combat_agent import COMBAT_AGENT_TOOLS
from creation_agent import CREATION_TOOLS
from dungeon_agent import DUNGEON_TOOLS
from llm_config import MAX_STRICT_TOOLS
from onboarding_agent import ONBOARDING_TOOLS
from training_agent import TRAINING_TOOLS
from wilderness_agent import WILDERNESS_TOOLS

AGENT_TOOL_LISTS = [
    ("city", CITY_TOOLS),
    ("wilderness", WILDERNESS_TOOLS),
    ("dungeon", DUNGEON_TOOLS),
    ("combat", COMBAT_AGENT_TOOLS),
    ("training", TRAINING_TOOLS),
    ("creation", CREATION_TOOLS),
    ("onboarding", ONBOARDING_TOOLS),
]


@pytest.mark.parametrize("name,tools", AGENT_TOOL_LISTS)
def test_agent_within_strict_tool_limit(name, tools):
    assert len(tools) <= MAX_STRICT_TOOLS, f"{name} has {len(tools)} strict tools (ceiling {MAX_STRICT_TOOLS})"
