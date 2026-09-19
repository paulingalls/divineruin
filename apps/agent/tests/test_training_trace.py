"""Fault injection for returned-state training acceptance guards."""

from __future__ import annotations

import json
from collections.abc import Callable

import pytest
from acceptance._training_trace import (
    assert_no_training_start,
    assert_persisted_training,
    eligible_spell_pairs,
    offered_spell,
    spell_programs,
    training_program_result,
    training_start,
)
from livekit.agents import llm
from livekit.agents.voice.run_result import RunResult

_PROGRAM = {
    "id": "arcane_study",
    "training_activity_type": "spell_standard",
    "studiable_spell_ids": ["arcane_counterspell"],
}


def _message(text: str) -> llm.ChatMessage:
    return llm.ChatMessage(role="assistant", content=[text])


def _query(call_id: str = "query", *, kind: str = "training_programs") -> llm.FunctionCall:
    return llm.FunctionCall(call_id=call_id, name="query_info", arguments=json.dumps({"kind": kind}))


def _query_output(
    call_id: str = "query",
    *,
    payload: object = None,
    raw: str | None = None,
    is_error: bool = False,
) -> llm.FunctionCallOutput:
    body = {"programs": [_PROGRAM]} if payload is None else payload
    return llm.FunctionCallOutput(
        call_id=call_id,
        name="query_info",
        output=raw if raw is not None else json.dumps(body),
        is_error=is_error,
    )


def _begin(
    call_id: str = "begin",
    *,
    program_id: str = "arcane_study",
    spell_id: str = "arcane_counterspell",
) -> llm.FunctionCall:
    return llm.FunctionCall(
        call_id=call_id,
        name="begin_activity",
        arguments=json.dumps({"activity": {"kind": "training", "program_id": program_id, "spell_id": spell_id}}),
    )


def _begin_output(
    call_id: str = "begin",
    *,
    raw: str | None = None,
    is_error: bool = False,
) -> llm.FunctionCallOutput:
    payload = {"activity_id": "train_1", "state": "running_first_half"}
    return llm.FunctionCallOutput(
        call_id=call_id,
        name="begin_activity",
        output=raw if raw is not None else json.dumps(payload),
        is_error=is_error,
    )


def _turn(*items: llm.ChatItem) -> RunResult:
    result: RunResult = RunResult(user_input="train", output_type=None)
    for item in items:
        result._item_added(item)
    return result


def _no_query() -> None:
    training_program_result(_turn(_message("Here are your options.")))


def _mismatched_query_output() -> None:
    training_program_result(_turn(_query(), _query_output("other")))


def _query_error() -> None:
    training_program_result(_turn(_query(), _query_output(is_error=True)))


def _malformed_query_output() -> None:
    training_program_result(_turn(_query(), _query_output(raw="not json")))


def _no_spell_rows() -> None:
    payload = training_program_result(
        _turn(
            _query(),
            _query_output(payload={"programs": [{"id": "combat_basics", "training_activity_type": "technique_base"}]}),
        )
    )
    spell_programs(payload)


def _inquiry_start() -> None:
    assert_no_training_start(_turn(_query(), _query_output(), _begin(), _begin_output()))


def _unreturned_id() -> None:
    training_start(
        _turn(_begin(spell_id="arcane_fireball"), _begin_output()),
        {("arcane_study", "arcane_counterspell")},
    )


def _begin_error() -> None:
    training_start(_turn(_begin(), _begin_output(is_error=True)), {("arcane_study", "arcane_counterspell")})


def _malformed_begin_output() -> None:
    training_start(_turn(_begin(), _begin_output(raw="not json")), {("arcane_study", "arcane_counterspell")})


def _persisted_row_mismatch() -> None:
    start = training_start(_turn(_begin(), _begin_output()), {("arcane_study", "arcane_counterspell")})
    assert_persisted_training(
        {
            "state": "running_first_half",
            "data": {"program_id": "arcane_study", "spell_id": "arcane_fireball"},
        },
        start,
    )


def _no_returned_offer() -> None:
    offered_spell(
        _turn(_message("You could study something here.")),
        {("arcane_study", "arcane_counterspell")},
    )


@pytest.mark.parametrize(
    "fault",
    [
        pytest.param(_no_query, id="no-query"),
        pytest.param(_mismatched_query_output, id="mismatched-query-output"),
        pytest.param(_query_error, id="query-error"),
        pytest.param(_malformed_query_output, id="malformed-query-output"),
        pytest.param(_no_spell_rows, id="no-spell-rows"),
        pytest.param(_inquiry_start, id="inquiry-start"),
        pytest.param(_unreturned_id, id="unreturned-id"),
        pytest.param(_begin_error, id="begin-error"),
        pytest.param(_malformed_begin_output, id="malformed-begin-output"),
        pytest.param(_persisted_row_mismatch, id="persisted-row-mismatch"),
        pytest.param(_no_returned_offer, id="no-returned-offer"),
    ],
)
@pytest.mark.asyncio
async def test_training_trace_guards_reject_invalid_results(fault: Callable[[], None]) -> None:
    with pytest.raises(AssertionError):
        fault()


@pytest.mark.asyncio
async def test_training_trace_guards_accept_correlated_returned_state() -> None:
    inquiry = _turn(
        _query(),
        _query_output(),
        _message("Counterspell is available to study."),
    )
    payload = training_program_result(inquiry)
    pairs = eligible_spell_pairs(payload)
    assert_no_training_start(inquiry)
    assert offered_spell(inquiry, pairs)[:2] == ("arcane_study", "arcane_counterspell")

    start = training_start(_turn(_begin(), _begin_output()), pairs)
    assert_persisted_training(
        {
            "state": "running_first_half",
            "data": {"program_id": "arcane_study", "spell_id": "arcane_counterspell"},
        },
        start,
    )
