"""Reading a live turn's transcript: what the model actually called, and what came back.

Split from ``tests/acceptance/test_m29_combat_reactions.py``, which drives the session; this holds
only the extraction over livekit's ``RunResult.events`` — the public surface its own docstring
names for test assertions, rather than session internals. Every function takes the list of
``RunResult``s accumulated so far, so nothing here knows about the pytest-bdd harness.
"""

from __future__ import annotations

import json
from typing import Any

from livekit.agents.voice.run_result import ChatMessageEvent, FunctionCallEvent, FunctionCallOutputEvent


def calls(turns: list, name: str) -> list:
    """Every ``FunctionCall`` for ``name``, in order, across every recorded turn."""
    return [e.item for t in turns for e in t.events if isinstance(e, FunctionCallEvent) and e.item.name == name]


def tool_names(turns: list) -> list[str]:
    """Every tool the model called, in order — the context a failed expectation needs."""
    return [e.item.name for t in turns for e in t.events if isinstance(e, FunctionCallEvent)]


def output_for(turns: list, call) -> Any:
    """The ``FunctionCallOutput`` answering ``call``. Fails loud on zero or more than one."""
    outputs = [
        e.item
        for t in turns
        for e in t.events
        if isinstance(e, FunctionCallOutputEvent) and e.item.call_id == call.call_id
    ]
    assert len(outputs) == 1, f"expected one output for {call.name} ({call.call_id}), got {outputs}"
    return outputs[0]


def resolve_packets(turns: list) -> list[dict]:
    """Every packet resolve_phase handed the DM — what reached the model, not internal state."""
    packets: list[dict] = []
    for call in calls(turns, "resolve_phase"):
        output = output_for(turns, call)
        if output.is_error:
            continue
        try:
            body = json.loads(output.output)
        except json.JSONDecodeError as exc:
            # resolve_phase answers a (agent, message) handoff TUPLE when the engine ends the
            # fight, and livekit surfaces only the message — so a scenario whose fight ended
            # early would otherwise die on "Expecting value: line 1 column 1" in the one lane
            # that costs an API call to re-run.
            raise AssertionError(f"resolve_phase handed back no JSON — combat ended: {output.output!r}") from exc
        # `[...]`, not `.get(..., [])`: a response that stopped carrying packets would make every
        # reader here silently empty, and each of them reports that as "the DM never acted".
        packets.extend(body["packets"])
    return packets


def reaction_packet(turns: list) -> dict | None:
    """The one packet a closed window synthesized for a spent reaction, if it has closed yet."""
    found = [p for p in resolve_packets(turns) if p.get("declaration_type") == "reaction"]
    assert len(found) <= 1, f"expected at most one reaction packet, got {found}"
    return found[0] if found else None


def turn_shapes(turns: list) -> list[str]:
    """One line per turn: what it produced. The diagnostic for "the DM did nothing".

    A turn that called no tool AND said nothing is a harness or transport problem; a turn that
    narrated instead is the model's own choice. Without this the two are indistinguishable in a
    failure message, and they have opposite fixes.
    """
    shapes = []
    for t in turns:
        tools = [e.item.name for e in t.events if isinstance(e, FunctionCallEvent)]
        said = [
            (e.item.text_content or "")[:90]
            for e in t.events
            if isinstance(e, ChatMessageEvent) and e.item.role == "assistant"
        ]
        shapes.append(f"tools={tools} said={said}")
    return shapes
