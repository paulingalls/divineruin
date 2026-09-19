"""Ordered midpoint narration checks shared by live and deterministic acceptance tests."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

from acceptance._judged_turn import last_assistant_message_index
from livekit.agents.voice.run_result import ChatMessageEvent, FunctionCallEvent, FunctionCallOutputEvent, RunResult

MessageEvaluator = Callable[[int, str], Awaitable[None]]
PENDING_MIDPOINT_INTENT = (
    "Does not announce or imply that the training's second half has already begun or is currently underway. "
    "The midpoint decision is a choice BETWEEN the halves, not the second half itself. Saying that this "
    "decision is pending or needs resolving now, including 'right now', is permitted. Reject a statement "
    "that training has resumed into its second half before the tool result, not a statement that the "
    "midpoint decision needs to be resolved."
)


async def assert_training_midpoint(
    result: RunResult,
    evaluate_message: MessageEvaluator,
    *,
    transition_intent: str,
) -> None:
    events = result.events
    calls = [
        (i, event.item)
        for i, event in enumerate(events)
        if isinstance(event, FunctionCallEvent) and event.item.name == "resolve_activity"
    ]
    assert len(calls) == 1, f"expected one resolve_activity call, got {calls}"
    call_index, call = calls[0]

    outputs = [
        (i, event.item)
        for i, event in enumerate(events)
        if isinstance(event, FunctionCallOutputEvent) and event.item.call_id == call.call_id
    ]
    assert len(outputs) == 1, f"expected one output for resolve_activity ({call.call_id}), got {outputs}"
    output_index, output = outputs[0]
    assert call_index < output_index, "resolve_activity output preceded its call"
    assert not output.is_error, f"resolve_activity failed: {output.output!r}"

    try:
        payload: Any = json.loads(output.output)
    except (json.JSONDecodeError, TypeError) as exc:
        raise AssertionError(f"resolve_activity returned malformed JSON: {output.output!r}") from exc
    assert isinstance(payload, dict), f"resolve_activity returned non-object JSON: {payload!r}"
    assert payload.get("state") == "running_second_half", f"unexpected midpoint state: {payload.get('state')!r}"
    seconds = payload.get("second_half_seconds")
    assert isinstance(seconds, (int, float)) and not isinstance(seconds, bool) and seconds > 0, (
        f"invalid second_half_seconds: {seconds!r}"
    )
    cue = payload.get("narration_cue")
    assert isinstance(cue, str) and cue.strip(), f"invalid narration_cue: {cue!r}"

    # Which message the judge reads is `_judged_turn`'s rule, not a second copy of it here.
    final_index = last_assistant_message_index(events)
    assert final_index > output_index, "the final assistant narration did not follow the resolve_activity result"

    await evaluate_message(final_index, transition_intent)
    await evaluate_message(
        final_index,
        "States approximately how much training time remains, consistent with the actual "
        f"resolve_activity result: second_half_seconds={seconds!r}; narration_cue={cue!r}",
    )
    for index, event in enumerate(events[:output_index]):
        if isinstance(event, ChatMessageEvent) and event.item.role == "assistant":
            await evaluate_message(index, PENDING_MIDPOINT_INTENT)
