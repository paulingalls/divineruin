import json

from livekit.agents.llm import FunctionCall, FunctionTool, RawFunctionTool
from livekit.agents.llm.utils import prepare_function_arguments
from livekit.agents.voice import AgentSession, RunContext, SpeechHandle

from base_agent import BaseGameAgent


def game_tools(session, *tools):
    agent = BaseGameAgent(instructions="Resolve the roll.", tools=list(tools))
    live_session = AgentSession(userdata=session)
    registered = {tool.id: tool for tool in agent.tools}

    async def call(name, **arguments):
        tool = registered[name]
        assert isinstance(tool, (FunctionTool, RawFunctionTool))
        function_call = FunctionCall(name=name, call_id=name, arguments=json.dumps(arguments))
        context = RunContext(session=live_session, speech_handle=SpeechHandle.create(), function_call=function_call)
        args, kwargs = prepare_function_arguments(fnc=tool, json_arguments=arguments, call_ctx=context)
        return json.loads(await tool(*args, **kwargs))

    return call


def attack(actor_id, target_id):
    return {
        "kind": "attack",
        "actor_id": actor_id,
        "action": "Longsword",
        "target_id": target_id,
        "held_item_id": "",
        "rider": "",
    }


def defend(actor_id):
    return {"kind": "defend", "actor_id": actor_id, "action": "defend", "targets": [], "argument_type": ""}
