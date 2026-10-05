"""Construct installed vendor schemas because a local model of their limits can pass while requests fail."""

import ast
import inspect
from pathlib import Path

import pytest
from agent_tool_profiles import AGENT_PROFILE_NAMES, AGENT_TOOL_LISTS
from livekit.agents.llm import ToolContext
from tool_schema_walk import SchemaFacts, walk_tool_schema

from combat_agent import COMBAT_AGENT_TOOLS
from dispatch_agent import DISPATCH_TOOLS
from exploration_agent import EXPLORATION_TOOLS
from llm_config import MAX_NULLABLE_PER_OBJECT, MAX_STRICT_TOOLS, MAX_UNION_PARAMS


def test_every_agent_module_registers_its_tool_list():
    """Agent registration controls the scope of every discovered tool walk."""
    assert {
        "exploration",
        "combat",
        "dispatch",
        "creation",
        "onboarding",
        "blacksmith",
    } == AGENT_PROFILE_NAMES
    for name, tools in AGENT_TOOL_LISTS:
        assert tools, f"{name} registers an empty tool list"


@pytest.mark.parametrize("name,tools", AGENT_TOOL_LISTS)
def test_agent_within_strict_tool_limit(name, tools):
    assert len(tools) <= MAX_STRICT_TOOLS, f"{name} has {len(tools)} strict tools (ceiling {MAX_STRICT_TOOLS})"


def test_exploration_strict_tool_count():
    assert len(EXPLORATION_TOOLS) == 15
    assert len(EXPLORATION_TOOLS) == MAX_STRICT_TOOLS - 5


def test_combat_strict_tool_count():
    # Exact registration count makes a tool addition deliberate even below the vendor ceiling.
    assert len(COMBAT_AGENT_TOOLS) == 9


def test_dispatch_strict_tool_count():
    assert len(DISPATCH_TOOLS) == 9


def _agent_schema_facts(tools) -> dict[str, SchemaFacts]:
    """Walk the schemas the Anthropic plugin actually emits for one agent's tool list."""
    parsed = ToolContext(tools).parse_function_tools("anthropic", strict=True)
    return {tool["name"]: walk_tool_schema(tool["input_schema"]) for tool in parsed}


@pytest.mark.parametrize("name,tools", AGENT_TOOL_LISTS)
def test_agent_within_strict_schema_budget(name, tools):
    """ADR 0008 requires measured strict-schema limits rather than stale hand counts."""
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
    "dispatch": 6,  # begin_activity 2 (spell_id adds 1), check 1, resolve_activity 1, learn 1, query_info 1
    "creation": 0,
    "onboarding": 2,  # check 1, query_info 1
    "blacksmith": 1,  # query_info 1
}


@pytest.mark.parametrize("name,tools", AGENT_TOOL_LISTS)
def test_agent_union_counts_are_pinned(name, tools):
    assert name in EXPECTED_UNION_SPEND, f"{name} has no pinned union spend"
    facts = _agent_schema_facts(tools)
    spend = {tool: len(f.unions) for tool, f in facts.items() if f.unions}
    assert sum(spend.values()) == EXPECTED_UNION_SPEND[name], f"{name} union spend changed: {spend}"


def _agent_session_llm_calls() -> list[tuple[str, ast.Call]]:
    """Every inline `AgentSession(llm=...LLM(...))` construction under apps/agent."""
    root = Path(__file__).resolve().parents[1]
    sites: list[tuple[str, ast.Call]] = []
    for path in sorted(root.rglob("*.py")):
        if ".venv" in path.parts:
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            if not isinstance(node, ast.Call) or not _is_agent_session_call(node):
                continue
            for kw in node.keywords:
                if kw.arg == "llm" and isinstance(kw.value, ast.Call) and "LLM" in ast.dump(kw.value.func):
                    sites.append((str(path.relative_to(root)), kw.value))
    return sites


def _is_agent_session_call(node: ast.Call) -> bool:
    target = node.func
    return (isinstance(target, ast.Name) and target.id == "AgentSession") or (
        isinstance(target, ast.Attribute) and target.attr == "AgentSession"
    )


def _agent_session_sites() -> list[tuple[str, ast.Call]]:
    """Every `AgentSession(...)` construction under apps/agent, as AST."""
    root = Path(__file__).resolve().parents[1]
    sites: list[tuple[str, ast.Call]] = []
    for path in sorted(root.rglob("*.py")):
        if ".venv" in path.parts:
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Call) and _is_agent_session_call(node):
                sites.append((str(path.relative_to(root)), node))
    return sites


def test_agent_session_matcher_distinguishes_constructor_from_chained_calls():
    tree = ast.parse("AgentSession().options.endpointing.get('min_delay')")
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]

    assert [ast.unparse(call) for call in calls if _is_agent_session_call(call)] == ["AgentSession()"]


def test_every_agent_session_chooses_its_max_tool_steps():
    """LiveKit permits max_tool_steps + 1 calls, then silently narrates with tool_choice="none".
    Reaction pauses end turns; the longest uninterrupted turn uses four calls.
    Keep every production and acceptance session on the deliberate ceiling."""
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


def test_every_anthropic_acceptance_session_runs_strict_tool_schema_off():
    """Anthropic rejected the larger strict agents in the live probe; ADR 0008 keeps rollback strict-off."""
    sites = _agent_session_llm_calls()
    expected = {
        "tests/acceptance/test_combat_cache_prefix.py",
        "tests/acceptance/test_m1_5_training_cycle.py",
        "tests/acceptance/test_m1_6_companion_errands.py",
        "tests/acceptance/test_m29_combat_reactions.py",
    }
    assert {filename for filename, _ in sites} == expected
    for filename, call in sites:
        flags = [
            kw.value.value
            for kw in call.keywords
            if kw.arg == "_strict_tool_schema" and isinstance(kw.value, ast.Constant)
        ]
        assert flags == [False], f"{filename}: AgentSession llm must pass _strict_tool_schema=False"


def test_production_agent_session_routes_through_gameplay_factory():
    production = next(call for filename, call in _agent_session_sites() if filename == "session_startup.py")
    llm_kw = next(kw.value for kw in production.keywords if kw.arg == "llm")
    assert isinstance(llm_kw, ast.Call)
    assert isinstance(llm_kw.func, ast.Name)
    assert llm_kw.func.id == "create_gameplay_llm"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "selection,expected",
    [("anthropic", False), ("openai-luna", True)],
)
async def test_gameplay_factory_strict_direction(monkeypatch, selection, expected):
    from livekit.plugins import anthropic as anthropic_plugin
    from livekit.plugins import openai as openai_plugin

    from gameplay_llm import create_gameplay_llm

    monkeypatch.setenv("GAMEPLAY_LLM", selection)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    selected = create_gameplay_llm("claude-haiku-4-5-20251001")
    try:
        if isinstance(selected, anthropic_plugin.LLM):
            actual = selected._opts.strict_tool_schema
        else:
            assert isinstance(selected, openai_plugin.LLM)
            actual = selected._strict_tool_schema
        assert actual is expected
    finally:
        await selected.aclose()


def test_plugin_still_accepts_the_interim_strict_kwarg_and_defaults_on():
    """The interim strict switch is a private vendor kwarg whose signature can change on upgrade."""
    from livekit.plugins import anthropic

    param = inspect.signature(anthropic.LLM.__init__).parameters["_strict_tool_schema"]
    assert param.default is True

    from livekit.plugins import openai

    openai_param = inspect.signature(openai.LLM.__init__).parameters["_strict_tool_schema"]
    assert openai_param.default is True
