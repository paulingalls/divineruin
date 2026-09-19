"""Deterministic falsifiers for ordered training-midpoint narration."""

from __future__ import annotations

import json

import pytest
from acceptance._midpoint_order import assert_training_midpoint
from livekit.agents import llm
from livekit.agents.voice.run_result import ChatMessageEvent, RunResult

_TRANSITION_INTENT = "Tells the player their training continues into its second half"
_GOOD = "The second half has begun; about 3 hours remain."


def _message(text: str) -> llm.ChatMessage:
    return llm.ChatMessage(role="assistant", content=[text])


def _call(call_id: str = "midpoint") -> llm.FunctionCall:
    return llm.FunctionCall(
        call_id=call_id,
        name="resolve_activity",
        arguments=json.dumps({"kind": "training", "decision": "fundamentals"}),
    )


_PAYLOAD = {
    "state": "running_second_half",
    "second_half_seconds": 3 * 3600,
    "narration_cue": "Training resumes into its second half, with about 3 hours left.",
}


def _output(call_id: str = "midpoint", *, is_error: bool = False, **overrides: object) -> llm.FunctionCallOutput:
    return llm.FunctionCallOutput(
        call_id=call_id,
        name="resolve_activity",
        output=json.dumps({**_PAYLOAD, **overrides}),
        is_error=is_error,
    )


def _raw_output(body: str) -> llm.FunctionCallOutput:
    return llm.FunctionCallOutput(call_id="midpoint", name="resolve_activity", output=body, is_error=False)


def _unrelated_output() -> llm.FunctionCallOutput:
    return llm.FunctionCallOutput(
        call_id="other",
        name="query_info",
        output=json.dumps({"status": "ok"}),
        is_error=False,
    )


def _turn(*items: llm.ChatItem) -> RunResult:
    result: RunResult = RunResult(user_input="I focus on fundamentals", output_type=None)
    for item in items:
        result._item_added(item)
    return result


def _evaluator(result: RunResult):
    async def evaluate(index: int, intent: str) -> None:
        event = result.events[index]
        assert isinstance(event, ChatMessageEvent), f"evaluator received a non-message: {event}"
        text = (event.item.text_content or "").lower()
        if intent == _TRANSITION_INTENT:
            assert "second half has begun" in text, f"missing second-half transition: {text!r}"
        elif intent.startswith("States approximately how much training time remains"):
            assert "second_half_seconds=10800" in intent and "about 3 hours left" in intent
            assert "about 3 hours remain" in text, f"remaining time disagrees with result: {text!r}"
        elif intent.startswith("Does not announce or imply"):
            assert "second half has begun" not in text and "second half is underway" not in text, (
                f"announced the outcome before its result: {text!r}"
            )
        else:
            raise AssertionError(f"unexpected evaluator intent: {intent}")

    return evaluate


async def _asserts(*items: llm.ChatItem) -> None:
    result = _turn(*items)
    await assert_training_midpoint(result, _evaluator(result), transition_intent=_TRANSITION_INTENT)


@pytest.mark.asyncio
async def test_call_result_then_complete_narration_passes():
    await _asserts(_call(), _output(), _message(_GOOD))


@pytest.mark.asyncio
async def test_pending_midpoint_decision_is_not_an_outcome_announcement():
    await _asserts(
        _message("I need to resolve your midpoint decision."),
        _call(),
        _output(),
        _message(_GOOD),
    )


@pytest.mark.asyncio
async def test_captured_pre_call_outcome_is_rejected():
    with pytest.raises(AssertionError, match="announced the outcome before"):
        await _asserts(_message(_GOOD), _call(), _output(), _message(_GOOD))


@pytest.mark.asyncio
async def test_outcome_between_call_and_result_is_rejected():
    with pytest.raises(AssertionError, match="announced the outcome before"):
        await _asserts(_call(), _message("The second half is underway."), _output(), _message(_GOOD))


@pytest.mark.asyncio
async def test_final_narration_missing_transition_is_rejected():
    with pytest.raises(AssertionError, match="missing second-half transition"):
        await _asserts(_call(), _output(), _message("About 3 hours remain."))


@pytest.mark.asyncio
async def test_final_narration_missing_time_is_rejected():
    with pytest.raises(AssertionError, match="remaining time disagrees"):
        await _asserts(_call(), _output(), _message("The second half has begun."))


@pytest.mark.asyncio
async def test_final_narration_inconsistent_with_result_is_rejected():
    with pytest.raises(AssertionError, match="remaining time disagrees"):
        await _asserts(_call(), _output(), _message("The second half has begun; about 5 hours remain."))


@pytest.mark.asyncio
async def test_narration_only_before_result_is_rejected():
    with pytest.raises(AssertionError, match="did not follow"):
        await _asserts(_message(_GOOD), _call(), _output())


@pytest.mark.asyncio
async def test_matching_output_is_selected_by_call_id():
    await _asserts(_call(), _unrelated_output(), _output(), _message(_GOOD))


@pytest.mark.asyncio
async def test_no_resolve_call_is_rejected():
    """The captured Sprint 54 failure: narration alone, the tool never called."""
    with pytest.raises(AssertionError, match="expected one resolve_activity call"):
        await _asserts(_message(_GOOD))


@pytest.mark.asyncio
async def test_repeated_resolve_calls_are_rejected():
    with pytest.raises(AssertionError, match="expected one resolve_activity call"):
        await _asserts(_call("a"), _output("a"), _call("b"), _output("b"), _message(_GOOD))


@pytest.mark.asyncio
async def test_unanswered_resolve_call_is_rejected():
    with pytest.raises(AssertionError, match="expected one output"):
        await _asserts(_call(), _unrelated_output(), _message(_GOOD))


@pytest.mark.asyncio
async def test_failed_resolve_call_is_rejected():
    with pytest.raises(AssertionError, match="resolve_activity failed"):
        await _asserts(_call(), _output(is_error=True), _message(_GOOD))


@pytest.mark.asyncio
async def test_other_midpoint_state_is_rejected():
    with pytest.raises(AssertionError, match="unexpected midpoint state"):
        await _asserts(_call(), _output(state="complete"), _message(_GOOD))


@pytest.mark.asyncio
async def test_missing_remaining_seconds_is_rejected():
    with pytest.raises(AssertionError, match="invalid second_half_seconds"):
        await _asserts(_call(), _output(second_half_seconds=None), _message(_GOOD))


@pytest.mark.asyncio
async def test_blank_narration_cue_is_rejected():
    with pytest.raises(AssertionError, match="invalid narration_cue"):
        await _asserts(_call(), _output(narration_cue="   "), _message(_GOOD))


@pytest.mark.asyncio
async def test_non_object_result_is_rejected():
    with pytest.raises(AssertionError, match="non-object JSON"):
        await _asserts(_call(), _raw_output("[]"), _message(_GOOD))


@pytest.mark.asyncio
async def test_unparseable_result_is_rejected():
    with pytest.raises(AssertionError, match="malformed JSON"):
        await _asserts(_call(), _raw_output("not json"), _message(_GOOD))


@pytest.mark.asyncio
async def test_turn_without_any_narration_is_rejected():
    with pytest.raises(AssertionError, match="emitted no assistant message"):
        await _asserts(_call(), _output())


@pytest.mark.asyncio
async def test_result_recorded_before_its_call_is_rejected():
    with pytest.raises(AssertionError, match="output preceded its call"):
        await _asserts(_raw_output(json.dumps(_PAYLOAD)), _call(), _message(_GOOD))
