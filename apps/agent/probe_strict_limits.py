"""Ask the live Anthropic API whether each agent's strict tool schemas are accepted.

Not a test — it spends real API calls, and it is the ONLY way to see the two ceilings that
are not computable from a schema: "The compiled grammar is too large" and "Schema is too
complex." `tests/test_strict_tool_budget.py` walks the three that ARE computable and was
green on all six agents while the API refused three of them (story-019, 2026-09-05). Run
this before ever flipping `_strict_tool_schema` back on, and after any change that adds a
tool or grows a payload:

    cd apps/agent && uv run --env-file ../../.env python probe_strict_limits.py

Exits 0 iff every agent is accepted, so it doubles as the falsifier on story-019's
strict-still-off debt. See ADR 0008, "Not yet attainable".
"""

from __future__ import annotations

import asyncio
import sys

import anthropic
from livekit.agents.llm import ToolContext

from blacksmith_agent import BLACKSMITH_TOOLS
from combat_agent import COMBAT_AGENT_TOOLS
from creation_agent import CREATION_TOOLS
from dispatch_agent import DISPATCH_TOOLS
from exploration_agent import EXPLORATION_TOOLS
from llm_config import MODEL
from onboarding_agent import ONBOARDING_TOOLS

AGENTS = [
    ("exploration", EXPLORATION_TOOLS),
    ("combat", COMBAT_AGENT_TOOLS),
    ("dispatch", DISPATCH_TOOLS),
    ("onboarding", ONBOARDING_TOOLS),
    ("blacksmith", BLACKSMITH_TOOLS),
    ("creation", CREATION_TOOLS),
]


async def main() -> int:
    client = anthropic.AsyncAnthropic()
    refused = []
    for name, tools in AGENTS:
        parsed = ToolContext(tools).parse_function_tools("anthropic", strict=True)
        try:
            await client.messages.create(
                model=MODEL,
                max_tokens=16,
                tools=parsed,  # type: ignore[arg-type]  # plugin-shaped dicts, not the SDK's TypedDicts
                messages=[{"role": "user", "content": "hi"}],
            )
            print(f"{name:12} {len(parsed):2} tools  ACCEPTED")
        except anthropic.APIStatusError as e:
            message = (e.body or {}).get("error", {}).get("message", str(e)) if isinstance(e.body, dict) else str(e)
            print(f"{name:12} {len(parsed):2} tools  REFUSED: {message}")
            refused.append(name)
    if refused:
        print(f"\n{len(refused)} of {len(AGENTS)} agents refused with strict ON: {', '.join(refused)}")
    return 1 if refused else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
