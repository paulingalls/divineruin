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
    # check / enter_mode folds). M7's exploration-agent collapse keeps a single list for ALL
    # regions; M4.6b added the travel verb (15->16); M23 story-002 added adjust_faction_reputation
    # (16->17) beside update_npc_disposition; M24 story-012 added deploy_veil_anchor, the only
    # item-use verb (17->18). M25 Phase-5 story-003 folded deploy_veil_anchor into the polymorphic
    # activate verb — a net-zero swap, so the slot at 18 is now activate — 2 free slots remain.
    assert len(EXPLORATION_TOOLS) == 18
    assert len(EXPLORATION_TOOLS) == MAX_STRICT_TOOLS - 2


def test_combat_strict_tool_count():
    # Pins the exact combat tool count so a new registration is a deliberate edit, not a
    # silent pass under the <=MAX_STRICT_TOOLS ceiling. M3.3 added cast_spell + get_spell_info
    # (9->11); M3.2 story-003 added the single polymorphic activate_veil_ward (11->12);
    # M3.4 story-005 added the Draethar inner_fire active racial (12->13); M4.7 story-009 added
    # consume_legendary_action for the Boss legendary beat (13->14); M25 Phase-5 story-002 folded
    # cast_spell/request_ability_activation/activate_veil_ward/inner_fire into activate (14->11).
    assert len(COMBAT_AGENT_TOOLS) == 11


def test_dispatch_strict_tool_count():
    # M26 Phase-5 story-003 cut DispatchAgent over from 10 folded noun tools
    # (query_training_programs, initiate_training_cycle, resolve_training_midpoint,
    # dispatch_companion_errand, resolve_companion_errand, query_recipe_requirements,
    # query_available_workspaces, rent_workspace, start_crafting_project,
    # experiment_with_materials) to begin_activity + resolve_activity (19->11).
    assert len(DISPATCH_TOOLS) == 11
