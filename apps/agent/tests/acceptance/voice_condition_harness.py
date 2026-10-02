"""Deterministic owned speech/model seams over the real LiveKit transport."""

import json
import uuid

from livekit.agents import llm
from livekit.agents.types import DEFAULT_API_CONNECT_OPTIONS


class ScenarioStream(llm.LLMStream):
    def __init__(self, model, **kwargs):
        super().__init__(model, **kwargs)
        self.model = model

    async def _run(self):
        model = self.model
        for item in self._chat_ctx.items:
            if isinstance(item, llm.FunctionCallOutput) and item.call_id in model.calls:
                model.receipts[item.call_id] = item
        if len(model.calls) < len(model.commands):
            name, arguments = model.commands[len(model.calls)]
            call_id = uuid.uuid4().hex
            model.calls[call_id] = name
            delta = llm.ChoiceDelta(
                role="assistant",
                tool_calls=[
                    llm.FunctionToolCall(
                        name=name,
                        arguments=json.dumps(arguments),
                        call_id=call_id,
                    )
                ],
            )
        else:
            assert_receipt_floor(model)
            model.narrated = True
            refused = any(output.is_error for output in model.receipts.values())
            model.narration = "Your voice reaches me. You cannot speak here." if refused else "Your action resolves."
            delta = llm.ChoiceDelta(role="assistant", content=model.narration)
        self._event_ch.send_nowait(llm.ChatChunk(id=uuid.uuid4().hex, delta=delta))


class ScenarioModel(llm.LLM):
    def __init__(self, commands):
        super().__init__()
        self.commands = commands
        self.calls = {}
        self.receipts = {}
        self.narrated = False
        self.narration = ""

    def chat(self, *, chat_ctx, tools=None, conn_options=DEFAULT_API_CONNECT_OPTIONS, **_kwargs):
        return ScenarioStream(self, chat_ctx=chat_ctx, tools=tools or [], conn_options=conn_options)


def assert_receipt_floor(model):
    assert model.commands, "empty command manifest"
    assert len(model.calls) == len(model.commands), "missing executed command"
    assert set(model.receipts) == set(model.calls), "missing DM receipt"
    assert all(output.output.strip() for output in model.receipts.values()), "empty tool result"


def assert_hud_floor(events):
    assert events, "no received HUD events"

    def walk(value):
        if isinstance(value, dict):
            assert not {"x", "y", "z", "positions", "distances_ft", "resonance_generated", "resonance_current"} & set(
                value
            ), "mechanical HUD payload"
            for key, item in value.items():
                if key == "resonance":
                    assert not isinstance(item, (int, float)), "raw Resonance HUD payload"
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    for event in events:
        walk(event)
