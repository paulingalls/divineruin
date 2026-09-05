"""Pin every agent's tool surface under Anthropic's three strict-schema ceilings.

The ceilings live once, in llm_config (MAX_STRICT_TOOLS / MAX_UNION_PARAMS /
MAX_NULLABLE_PER_OBJECT). A tool addition or a reshape that breaches one should fail
here as a unit test, not in production as a 400 (ADR 0004 captured the "too many
strict tools" error; ADR 0008 the union and complexity ones).
"""

import ast
import inspect
from pathlib import Path

import pytest
from livekit.agents.llm import ToolContext
from tool_schema_walk import SchemaFacts, walk_tool_schema

from blacksmith_agent import BLACKSMITH_TOOLS
from combat_agent import COMBAT_AGENT_TOOLS
from creation_agent import CREATION_TOOLS
from dispatch_agent import DISPATCH_TOOLS
from exploration_agent import EXPLORATION_TOOLS
from llm_config import MAX_NULLABLE_PER_OBJECT, MAX_STRICT_TOOLS, MAX_UNION_PARAMS
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
    # M27 story-003 tore out play_sound/set_music_state as LLM tools; audio now derives
    # only from deterministic Resolves and the Stage (18->16). M28 story-003 tore out
    # award_xp/award_divine_favor (16->14): XP and favor are granted by the combat-exit and
    # quest-completion Resolves, so a second LLM-judgement grant path no longer exists.
    assert len(EXPLORATION_TOOLS) == 14
    assert len(EXPLORATION_TOOLS) == MAX_STRICT_TOOLS - 6


def test_combat_strict_tool_count():
    # Pins the exact combat tool count so a new registration is a deliberate edit, not a
    # silent pass under the <=MAX_STRICT_TOOLS ceiling. M3.3 added cast_spell + get_spell_info
    # (9->11); M3.2 story-003 added the single polymorphic activate_veil_ward (11->12);
    # M3.4 story-005 added the Draethar inner_fire active racial (12->13); M4.7 story-009 added
    # consume_legendary_action for the Boss legendary beat (13->14); M25 Phase-5 story-002 folded
    # cast_spell/request_ability_activation/activate_veil_ward/inner_fire into activate (14->11).
    # M27 story-003 tore out play_sound/set_music_state as LLM tools (11->9).
    assert len(COMBAT_AGENT_TOOLS) == 9


def test_dispatch_strict_tool_count():
    # M26 Phase-5 story-003 cut DispatchAgent over from 10 folded noun tools
    # (query_training_programs, initiate_training_cycle, resolve_training_midpoint,
    # dispatch_companion_errand, resolve_companion_errand, query_recipe_requirements,
    # query_available_workspaces, rent_workspace, start_crafting_project,
    # experiment_with_materials) to begin_activity + resolve_activity (19->11).
    # M27 story-003 tore out play_sound/set_music_state as LLM tools (11->9).
    assert len(DISPATCH_TOOLS) == 9


def _agent_schema_facts(tools) -> dict[str, SchemaFacts]:
    """Walk the schemas the Anthropic plugin actually emits for one agent's tool list."""
    parsed = ToolContext(tools).parse_function_tools("anthropic", strict=True)
    return {tool["name"]: walk_tool_schema(tool["input_schema"]) for tool in parsed}


@pytest.mark.parametrize("name,tools", AGENT_TOOL_LISTS)
def test_agent_within_strict_schema_budget(name, tools):
    """The three limits ADR 0008 measured, walked rather than hand-counted.

    Walked, not pinned by number, because Sprint 48's 016/017 reshape declare_phase
    again: a hand-count would go stale, the walk stays true. No "warn at 12" union
    mechanism (ADR 0008 decision 2): the exact per-agent pin below fires strictly
    earlier, and a warning in a test lane is either a failure or noise.
    """
    facts = _agent_schema_facts(tools)
    unions = [path for tool, f in facts.items() for path in f.unions]
    assert len(unions) <= MAX_UNION_PARAMS, f"{name} sends {len(unions)} union-typed params: {unions}"

    for tool, f in facts.items():
        assert not f.additional_properties, f"{name}.{tool}: additionalProperties at {f.additional_properties}"
        assert not f.enum_with_null, f"{name}.{tool}: enum containing null at {f.enum_with_null}"
        assert not f.one_of, f"{name}.{tool}: oneOf at {f.one_of} (the plugin emits anyOf; oneOf is a 400)"
        for path, count in f.nullable_by_object.items():
            assert count <= MAX_NULLABLE_PER_OBJECT, f"{name}.{tool}: {count} nullables in one object at {path}"


# Every agent's exact union spend after the ADR 0008 sum-type reshape (story-019):
# check 9 -> 1, begin_activity 11 -> 1, declare_phase 0 (a hard reject) -> 1.
# Exact, not <=, so a NEW defaulted @function_tool parameter — each one emits
# `type: [x, "null"]`, i.e. exactly one union — reds here as a deliberate edit.
EXPECTED_UNION_SPEND = {
    "exploration": 9,  # check 1, travel 2, activate 2, enter_mode 2, query_info 1, transact 1
    "combat": 6,  # declare_phase 1, check 1, activate 2, request_death_save 1, query_info 1
    "training": 5,  # begin_activity 1, check 1, resolve_activity 1, learn 1, query_info 1
    "creation": 0,
    "onboarding": 2,  # check 1, query_info 1
    "blacksmith": 1,  # query_info 1
}


@pytest.mark.parametrize("name,tools", AGENT_TOOL_LISTS)
def test_agent_union_counts_are_pinned(name, tools):
    facts = _agent_schema_facts(tools)
    spend = {tool: len(f.unions) for tool, f in facts.items() if f.unions}
    assert sum(spend.values()) == EXPECTED_UNION_SPEND[name], f"{name} union spend changed: {spend}"


def _agent_session_llm_calls() -> list[tuple[str, ast.Call]]:
    """Every `AgentSession(llm=anthropic.LLM(...))` construction under apps/agent, as AST."""
    root = Path(__file__).resolve().parents[1]
    sites: list[tuple[str, ast.Call]] = []
    for path in sorted(root.rglob("*.py")):
        if ".venv" in path.parts:
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            if not isinstance(node, ast.Call) or "AgentSession" not in ast.dump(node.func):
                continue
            for kw in node.keywords:
                if kw.arg == "llm" and isinstance(kw.value, ast.Call) and "LLM" in ast.dump(kw.value.func):
                    sites.append((str(path.relative_to(root)), kw.value))
    return sites


def _agent_session_sites() -> list[tuple[str, ast.Call]]:
    """Every `AgentSession(...)` construction under apps/agent, as AST."""
    root = Path(__file__).resolve().parents[1]
    sites: list[tuple[str, ast.Call]] = []
    for path in sorted(root.rglob("*.py")):
        if ".venv" in path.parts:
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Call) and "AgentSession" in ast.dump(node.func):
                sites.append((str(path.relative_to(root)), node))
    return sites


def test_every_agent_session_chooses_its_max_tool_steps():
    """The tool-chain ceiling is chosen here, never inherited from the plugin default.

    livekit permits `max_tool_steps + 1` consecutive steps and, on reaching the cap, does
    NOT raise: it logs and regenerates with tool_choice="none" (agent_activity.py:3073).
    The agent silently stops calling tools and narrates anyway, so a dropped death save
    reaches the player as a plausible sentence — constraint 4 fail-quiet, from inside a
    vendor library, which is exactly why the number must be deliberate.

    5 permits six steps. Today's longest chain is three (declare_phase -> resolve_phase ->
    request_death_save); M29's restored Beat-3 loop needs five (declare -> resolve allies
    -> activate reaction -> resolve enemies -> death save). Scanning EVERY site, not just
    agent.py, is what keeps the acceptance harnesses on production's ceiling — a harness
    left on the default would truncate somewhere else and certify nothing about the real
    session. Supersedes bug 50fd0838, whose arithmetic missed the +1.
    """
    sites = _agent_session_sites()
    assert sites, "no AgentSession construction found — the walk is broken, not the code"
    for where, call in sites:
        steps = next((kw for kw in call.keywords if kw.arg == "max_tool_steps"), None)
        assert steps is not None, f"{where}: AgentSession inherits the plugin's max_tool_steps default"
        assert isinstance(steps.value, ast.Constant), f"{where}: max_tool_steps must be a literal"
        value = steps.value.value
        assert isinstance(value, int) and value >= 5, (
            f"{where}: max_tool_steps must be a literal >= 5 to fit the M29 Beat-3 chain"
        )


def test_every_agent_session_runs_strict_tool_schema_off():
    """Strict is STILL interim-OFF after story-019, and this is the pin that says so.

    ADR 0008's sum types fixed the two limits the design pass measured (16 union-typed
    parameters, the additionalProperties object) — the budget walk above proves that much.
    They were not sufficient: probed live 2026-09-05, exploration, combat and dispatch all
    400 with "The compiled grammar is too large", and exploration then 400s with "Schema is
    too complex." Neither ceiling is reachable from a schema this fast lane can inspect, so
    this source pin is what keeps production off the flip until the surface actually fits.

    Production and the real-LLM acceptance harnesses have to agree: a harness left on the
    plugin default 400s on every dispatch turn, so the one tier that reaches the API tests
    nothing. Scanning every site (not just agent.py) is what makes a forgotten or
    newly-added session red here instead of at the API.
    """
    sites = _agent_session_llm_calls()
    assert "agent.py" in {f for f, _ in sites}, f"matcher found no production session: {sites}"
    assert len(sites) >= 3, f"matcher drifted — only {len(sites)} AgentSession llm= sites found"
    for filename, call in sites:
        flags = [
            kw.value.value
            for kw in call.keywords
            if kw.arg == "_strict_tool_schema" and isinstance(kw.value, ast.Constant)
        ]
        assert flags == [False], f"{filename}: AgentSession llm must pass _strict_tool_schema=False"


def test_plugin_still_accepts_the_interim_strict_kwarg_and_defaults_on():
    """The interim rides a PRIVATE plugin kwarg whose default is True. A plugin upgrade that
    renames or drops it raises TypeError at session start; one that flips the default to False
    would make the interim invisible rather than deliberate. Nothing in the fast lane constructs
    an LLM (an API key is required), so the source pin above would stay green through either.
    Pin the signature.
    """
    from livekit.plugins import anthropic

    param = inspect.signature(anthropic.LLM.__init__).parameters["_strict_tool_schema"]
    assert param.default is True
