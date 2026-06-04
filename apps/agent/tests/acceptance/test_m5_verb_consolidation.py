"""Capstone: Milestone 5 verb consolidation, system-wide (story-005).

Proves M5's four folds (transact / learn / check / enter_mode) hold across EVERY
gameplay agent at once — the milestone exit gate the per-story tests can't give
individually:

  - no removed noun tool survives on any agent's registry;
  - the consolidated verbs sit on exactly the agents that should hold them;
  - every agent stays under the Anthropic strict-tool ceiling and keeps strict schema
    on all its tools;
  - the message_event surface (Python agent tools) is genuinely green over the seeded
    testcontainer DB — a learn round-trip and a transact round-trip, two distinct
    Resolve families, both writing/reading the real database.

The four pre-M5 folds removed TEN noun tools (the story text says "six" — it omits
the three extra tools the check fold absorbed). This capstone asserts all ten are gone.

Runs under `bun run test:acceptance` (REQUIRE_DOCKER on pre-push); the DB-backed
section skips cleanly when Docker is down (postgres_container fixture).
"""

from __future__ import annotations

import json

import pytest
from acceptance.seeds import seed_player
from sample_fixtures import make_context

import db
from blacksmith_agent import BLACKSMITH_TOOLS
from check_tools import check
from choice_tools import select
from city_agent import CITY_TOOLS
from combat_agent import COMBAT_AGENT_TOOLS
from creation_agent import CREATION_TOOLS
from dispatch_agent import DISPATCH_TOOLS
from dungeon_agent import DUNGEON_TOOLS
from inventory_tools import _transact_impl, transact
from llm_config import MAX_STRICT_TOOLS
from mode_tools import enter_mode
from onboarding_agent import ONBOARDING_TOOLS
from recipe_tools import _learn_recipe_impl, learn
from wilderness_agent import WILDERNESS_TOOLS

# The complete set of noun tools the four M5 folds removed (stories 001-004). The story
# text says "six"; the real set is ten — the check fold (story-003) absorbed four.
REMOVED_NOUN_TOOLS = frozenset(
    {
        "add_to_inventory",
        "remove_from_inventory",  # -> transact (story-001)
        "learn_recipe",  # -> learn (story-002)
        "request_skill_check",
        "discover_hidden_element",
        "request_saving_throw",
        "roll_dice",  # -> check (story-003)
        "start_combat",
        "enter_dispatch",
        "enter_blacksmith",  # -> enter_mode (story-004)
    }
)

# Every assembled gameplay-agent tool registry.
AGENT_TOOL_LISTS = [
    ("city", CITY_TOOLS),
    ("wilderness", WILDERNESS_TOOLS),
    ("dungeon", DUNGEON_TOOLS),
    ("combat", COMBAT_AGENT_TOOLS),
    ("dispatch", DISPATCH_TOOLS),
    ("onboarding", ONBOARDING_TOOLS),
    ("creation", CREATION_TOOLS),
    ("blacksmith", BLACKSMITH_TOOLS),
]

# verb -> the EXACT set of agents that must hold it (grep-verified against the tool
# lists). Frozen at story-005 time: a future sprint that moves a verb on/off an agent
# must update this map in lockstep, or this capstone goes red on staleness.
VERB_PRESENCE = [
    (transact, "transact", {"city", "dungeon"}),
    (learn, "learn", {"dispatch"}),
    (check, "check", {"city", "dungeon", "wilderness", "combat", "onboarding", "dispatch"}),
    (enter_mode, "enter_mode", {"city", "dungeon", "wilderness"}),
    (select, "select", {"city", "dungeon", "wilderness"}),
]


# --- registry: no removed noun tool survives ---------------------------------


@pytest.mark.parametrize("name,tools", AGENT_TOOL_LISTS)
def test_no_removed_noun_tool_survives(name: str, tools: list) -> None:
    """No pre-M5 noun tool is registered on any agent."""
    leaked = REMOVED_NOUN_TOOLS & {t.__name__ for t in tools}
    assert not leaked, f"{name} still registers removed noun tool(s): {sorted(leaked)}"


# --- registry: consolidated verbs present exactly where expected -------------


@pytest.mark.parametrize("verb,verb_name,expected_agents", VERB_PRESENCE)
def test_consolidated_verb_present_where_expected(verb, verb_name: str, expected_agents: set) -> None:
    """Each consolidated verb is registered on exactly the agents that should hold it
    — present where expected, absent everywhere else."""
    holders = {name for name, tools in AGENT_TOOL_LISTS if verb in tools}
    assert holders == expected_agents, (
        f"{verb_name} registered on {sorted(holders)}, expected {sorted(expected_agents)}"
    )


# --- ceiling + strict schema -------------------------------------------------


@pytest.mark.parametrize("name,tools", AGENT_TOOL_LISTS)
def test_within_strict_ceiling_and_schema(name: str, tools: list) -> None:
    """Every agent stays under the strict-tool ceiling and keeps strict schema on all
    its tools. Per-agent counts are pinned in test_strict_tool_budget; here the ceiling
    assertion stays thin and adds the strict-schema guard the budget test lacks."""
    assert len(tools) <= MAX_STRICT_TOOLS, f"{name} has {len(tools)} tools (ceiling {MAX_STRICT_TOOLS})"
    for t in tools:
        # livekit-plugins-anthropic defaults _strict_tool_schema=True; the codebase never
        # opts a tool out (every registered verb counts against the ceiling). Guard it.
        assert getattr(t, "_strict_tool_schema", True) is not False, f"{name}'s {t.__name__} opted out of strict schema"


# --- message_event surface: verbs live over the seeded testcontainer DB ------


async def _seed_clean_player(player_id: str) -> None:
    """Seed a fresh player and clear the rows the verbs below write, so each run starts
    from a known-empty slate."""
    pool = await db.get_pool()
    await seed_player(pool, player_id=player_id)
    await pool.execute("DELETE FROM player_known_recipes WHERE player_id = $1", player_id)
    await pool.execute("DELETE FROM player_inventory WHERE player_id = $1", player_id)


async def test_message_event_learn_verb_over_db(reset_db_pool: str) -> None:
    """The learn verb's recipe path writes the real DB (knowledge Resolve family)."""
    await _seed_clean_player("player_m5_learn")
    ctx = make_context(player_id="player_m5_learn")

    learned = json.loads(await _learn_recipe_impl(ctx, "wooden_club", "npc_teaching"))
    assert learned["learned"] == "wooden_club"
    assert learned["known_count"] == 1

    pool = await db.get_pool()
    rows = await pool.fetchval(
        "SELECT COUNT(*) FROM player_known_recipes WHERE player_id = $1 AND recipe_id = $2",
        "player_m5_learn",
        "wooden_club",
    )
    assert rows == 1


async def test_message_event_transact_verb_over_db(reset_db_pool: str) -> None:
    """The transact verb gains then loses an item, round-tripping the real DB
    (inventory Resolve family — a different write path than learn). The item id is
    read from the seeded content so the proof isn't coupled to a specific fixture id."""
    pool = await db.get_pool()
    item_row = await pool.fetchrow("SELECT id FROM items LIMIT 1")
    assert item_row is not None, "no items seeded in the testcontainer"
    item_id = item_row["id"]

    await _seed_clean_player("player_m5_transact")
    ctx = make_context(player_id="player_m5_transact")

    gained = json.loads(await _transact_impl(ctx, item_id, 3, "capstone"))
    assert gained["action"] == "added"
    assert gained["quantity"] == 3
    after_gain = await pool.fetchval(
        "SELECT (data->>'quantity')::int FROM player_inventory WHERE player_id = $1 AND item_id = $2",
        "player_m5_transact",
        item_id,
    )
    assert after_gain == 3

    # Negative delta decrements by magnitude (quantity-aware), not a full-stack delete.
    await _transact_impl(ctx, item_id, -1, "")
    after_loss = await pool.fetchval(
        "SELECT (data->>'quantity')::int FROM player_inventory WHERE player_id = $1 AND item_id = $2",
        "player_m5_transact",
        item_id,
    )
    assert after_loss == 2
