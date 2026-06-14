"""Pin every agent's tool list under the Anthropic strict-tool ceiling.

The ceiling lives once, in llm_config.MAX_STRICT_TOOLS. A tool addition that
breaches it should fail here as a unit test, not in production as a 400
(see ADR 0004 for the captured "too many strict tools" error).
"""

import pytest

from blacksmith_agent import BLACKSMITH_TOOLS
from combat_agent import COMBAT_AGENT_TOOLS
from creation_agent import CREATION_TOOLS
from dispatch_agent import DISPATCH_TOOLS
from exploration_agent import EXPLORATION_TOOLS
from llm_config import MAX_STRICT_TOOLS
from onboarding_agent import ONBOARDING_TOOLS

AGENT_TOOL_LISTS = [
    ("exploration", EXPLORATION_TOOLS),
    ("combat", COMBAT_AGENT_TOOLS),
    ("training", DISPATCH_TOOLS),
    ("creation", CREATION_TOOLS),
    ("onboarding", ONBOARDING_TOOLS),
    ("blacksmith", BLACKSMITH_TOOLS),
]


@pytest.mark.parametrize("name,tools", AGENT_TOOL_LISTS)
def test_agent_within_strict_tool_limit(name, tools):
    assert len(tools) <= MAX_STRICT_TOOLS, f"{name} has {len(tools)} strict tools (ceiling {MAX_STRICT_TOOLS})"


def test_exploration_strict_tool_count():
    # M5 verb consolidation reclaimed slots on the old CityAgent (20->15 via transact /
    # check / enter_mode folds). M7's exploration-agent collapse keeps that single 15-verb
    # list for ALL regions, so the per-region ceiling no longer binds — 5 free slots remain
    # under MAX_STRICT_TOOLS for the M2.4 spell tools (relieves debt e665104c753a).
    assert len(EXPLORATION_TOOLS) == 15
    assert len(EXPLORATION_TOOLS) == MAX_STRICT_TOOLS - 5


def test_combat_strict_tool_count():
    # Pins the exact combat tool count so a new registration is a deliberate edit, not a
    # silent pass under the <=MAX_STRICT_TOOLS ceiling. M3.3 added cast_spell + get_spell_info
    # (9->11); M3.2 story-003 added the single polymorphic activate_veil_ward (11->12);
    # M3.4 story-005 added the Draethar inner_fire active racial (12->13).
    assert len(COMBAT_AGENT_TOOLS) == 13
