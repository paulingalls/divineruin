"""Settle a pending Fate choice before dispatching the next registered tool."""

import inspect
import json
from functools import wraps

from livekit.agents import Agent
from livekit.agents.llm import FunctionTool, RawFunctionTool, ToolError
from livekit.agents.voice import RunContext

import zhael_fate
from session_data import SessionData


def _attach(result, facts):
    if isinstance(result, tuple) and len(result) == 2 and isinstance(result[0], Agent):
        return result[0], _attach(result[1], facts)
    if isinstance(result, str):
        try:
            payload = json.loads(result)
        except json.JSONDecodeError:
            payload = result
        if isinstance(payload, dict):
            return json.dumps({**payload, "settled_fate": facts})
    return {"result": result, "settled_fate": facts}


def wrap_tool(tool):
    if not isinstance(tool, (FunctionTool, RawFunctionTool)):
        return tool
    if getattr(tool, "_fate_wrapped", False):
        return tool
    signature = inspect.signature(tool)

    @wraps(tool)
    async def invoke(*args, **kwargs):
        bound = signature.bind(*args, **kwargs)
        context = next((value for value in bound.arguments.values() if isinstance(value, RunContext)), None)
        if context is None or not isinstance(context.userdata, SessionData):
            return await tool(*args, **kwargs)
        session = context.userdata
        async with session.fate_lock:
            if session.fate_offer is None or (tool.id == "activate" and bound.arguments.get("id") == zhael_fate.FATE):
                return await tool(*args, **kwargs)
            settled = await zhael_fate.settle(session)
            if settled.paused:
                return json.dumps(settled.facts)
            try:
                result = await tool(*args, **kwargs)
            except ToolError as error:
                raise ToolError(json.dumps({"error": str(error), "settled_fate": settled.facts})) from error
            return _attach(result, settled.facts)

    invoke.__signature__ = signature  # type: ignore[attr-defined]
    invoke.__dict__["_fate_wrapped"] = True
    if isinstance(tool, RawFunctionTool):
        return RawFunctionTool(invoke, tool.info)
    return FunctionTool(invoke, tool.info)
