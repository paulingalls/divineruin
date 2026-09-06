"""Fault injection for the judged-turn selection (``tests/acceptance/_judged_turn.py``).

The helper is pure, so its falsifiers run HERE — in the fast lane, on every push — rather than in
the real-LLM tier it was written for, where it was exercised only when someone spent an API turn
on it. That is why it shipped wrong twice with nothing able to red on it.

Turns are built by handing REAL chat items to a REAL ``RunResult``, which constructs and orders
the events itself, so the shape under test is livekit's rather than one this file invented — and
``expect`` is read off that same object, which is what makes the alignment test below mean
anything (constraint 9).
"""

from __future__ import annotations

import pytest
from acceptance._judged_turn import last_assistant_message_index
from livekit.agents import llm
from livekit.agents.voice.run_result import RunResult


def _msg(role: llm.ChatRole, text: str) -> llm.ChatMessage:
    return llm.ChatMessage(role=role, content=[text])


def _call() -> llm.FunctionCall:
    return llm.FunctionCall(call_id="c1", name="resolve_activity", arguments="{}")


def _out() -> llm.FunctionCallOutput:
    return llm.FunctionCallOutput(call_id="c1", name="resolve_activity", output="ok", is_error=False)


def _turn(*items: llm.ChatItem) -> RunResult:
    """A finished turn, recorded through livekit's own item -> event path."""
    result: RunResult = RunResult(user_input="go", output_type=None)
    for item in items:
        result._item_added(item)
    return result


@pytest.mark.asyncio
async def test_the_narration_is_found_when_the_dm_narrates_then_calls():
    """The turn that broke the sprint-048 land, replayed: narration at 0, the tool at 1-2.

    This is the falsifier for ``expect[-1]`` — the last EVENT here is a function call output, so
    the old selection handed the judge a non-message and died over narration that was fine.
    """
    events = _turn(_msg("assistant", "The second half of your training begins now"), _call(), _out()).events
    assert events[-1].type != "message", "the premise: the DM did not speak last"
    assert last_assistant_message_index(events) == 0


@pytest.mark.asyncio
async def test_index_zero_is_a_found_message_not_a_miss():
    """Explicit because the observed defect produces index 0: a caller that tested the result for
    truth — ``if not idx`` — would read the one turn shape this exists for as 'nothing found'."""
    idx = last_assistant_message_index(_turn(_msg("assistant", "hi"), _call()).events)
    assert idx == 0 and idx is not None


@pytest.mark.asyncio
async def test_the_last_narration_wins_when_the_dm_calls_then_narrates():
    """The original reason to look past event 0: a "let me check" line precedes the tool call and
    the meaningful narration follows it."""
    events = _turn(
        _msg("assistant", "Let me get that started"),
        _call(),
        _out(),
        _msg("assistant", "Your training continues into its second half"),
    ).events
    assert last_assistant_message_index(events) == 3


@pytest.mark.asyncio
async def test_a_user_message_is_not_mistaken_for_narration():
    """Reds an implementation that drops the role half and matches on ``type == "message"``."""
    events = _turn(_msg("assistant", "Your training begins"), _call(), _msg("user", "and then?")).events
    assert last_assistant_message_index(events) == 0


@pytest.mark.asyncio
async def test_a_turn_that_narrated_nothing_fails_loud():
    """No sentinel: a silent turn is a failure to report, not a value to judge (constraint 4)."""
    with pytest.raises(AssertionError, match="no assistant message"):
        last_assistant_message_index(_turn(_call(), _out()).events)


@pytest.mark.asyncio
async def test_the_index_addresses_the_same_event_expect_addresses():
    """The other half of the contract, and the one that would break SILENTLY: the index is scanned
    off ``result.events`` but spent on ``result.expect[...]``, so it is only right while the two
    address the same list. Read off ONE real RunResult, so a livekit change that gave ``expect`` a
    filtered or reordered view reds here instead of quietly judging the wrong message."""
    result = _turn(_msg("user", "go"), _call(), _out(), _msg("assistant", "done"))
    for i, event in enumerate(result.events):
        assert result.expect[i].event() is event
    assert result.expect[last_assistant_message_index(result.events)].event() is result.events[3]
