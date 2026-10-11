"""Probe provider strict compilation; every paid run needs explicit human approval.

Default Anthropic mode probes all six agents. Luna mode sends one request through
production's LiveKit OpenAI factory, with both retry layers disabled:

    uv run python probe_strict_limits.py --provider openai-luna --agent combat

Use OPENAI_BASE_URL and a dummy OPENAI_API_KEY for local construction checks.
A local stub proves request construction, not provider compilation. Paid runs
belong to the lead. See docs/agent_strict_mode.md for reproduction and limits.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

import anthropic
from livekit.agents import APIConnectOptions, APIError, llm
from livekit.agents.llm import ToolContext

from blacksmith_agent import BLACKSMITH_TOOLS
from combat_agent import COMBAT_AGENT_TOOLS
from creation_agent import CREATION_TOOLS
from dispatch_agent import DISPATCH_TOOLS
from exploration_agent import EXPLORATION_TOOLS
from gameplay_llm import create_luna_llm
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


async def probe_anthropic() -> int:
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


async def probe_luna(agent: str) -> int:
    tools = dict(AGENTS)[agent]
    selected = create_luna_llm()
    try:
        context = llm.ChatContext(items=[llm.ChatMessage(role="user", content=["hi"])])
        async with selected.chat(chat_ctx=context, tools=tools, conn_options=APIConnectOptions(max_retry=0)) as stream:
            async for _ in stream:
                pass
        print(f"{agent:12} {len(tools):2} tools  ACCEPTED")
        return 0
    except APIError as error:
        print(f"{agent:12} {len(tools):2} tools  REFUSED: {error}")
        return 1
    finally:
        await selected.aclose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", choices=("anthropic", "openai-luna"), default="anthropic")
    parser.add_argument("--agent", choices=[name for name, _ in AGENTS])
    args = parser.parse_args()
    if args.provider == "openai-luna":
        if args.agent is None:
            parser.error("--provider openai-luna requires --agent")
        return asyncio.run(probe_luna(args.agent))
    if args.agent is not None:
        parser.error("--agent requires --provider openai-luna")
    return asyncio.run(probe_anthropic())


if __name__ == "__main__":
    sys.exit(main())
