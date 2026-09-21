"""The gameplay-agent tool registry, discovered from the agent modules.

Three separate walks assert an ABSENCE over this corpus — no removed noun tool survives,
each consolidated verb is registered on exactly its expected agents, and every profile
emits strict schemas — and an absence guard is only as wide as the corpus under it
(constraint 12). A hand-listed corpus reads green over an agent nobody added to the list,
so the list is derived and `test_every_agent_module_registers_its_tool_list` is the one
place a new agent has to be declared.
"""

import ast
from importlib import import_module
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parents[1]


def _discover_agent_tool_lists() -> list[tuple[str, list]]:
    sources = sorted(AGENT_DIR.glob("*_agent.py"))
    if not sources:
        raise AssertionError(f"no *_agent.py under {AGENT_DIR} — the walk is broken, not the code")
    found: list[tuple[str, list]] = []
    for source in sources:
        module_name = source.stem
        for node in ast.parse(source.read_text()).body:
            if not isinstance(node, ast.Assign):
                continue
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id.endswith("_TOOLS"):
                    tools = getattr(import_module(module_name), target.id)
                    found.append((module_name.removesuffix("_agent"), tools))
    if not found:
        raise AssertionError(f"no agent under {AGENT_DIR} registers a module-level *_TOOLS list")
    return found


AGENT_TOOL_LISTS = _discover_agent_tool_lists()
AGENT_PROFILE_NAMES = frozenset(name for name, _ in AGENT_TOOL_LISTS)
