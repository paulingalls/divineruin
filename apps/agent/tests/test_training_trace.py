"""Fault injection for returned-state training acceptance guards.

The guards are sync, but the tests are async: ``RunResult.__init__`` builds an
``asyncio.Future``, so a turn can only be assembled under a running loop.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from types import SimpleNamespace

import pytest
from acceptance._training_trace import (
    TrainingStart,
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
_PHYSICAL_PROGRAM = {
    "id": "combat_basics",
    "name": "Combat Fundamentals",
    "training_activity_type": "technique_base",
}
_PAIRS = {("arcane_study", "arcane_counterspell")}


@pytest.mark.asyncio
async def test_live_no_spell_judge_uses_all_returned_program_names(monkeypatch: pytest.MonkeyPatch) -> None:
    from acceptance import test_m1_5_training_cycle as training

    names = ["Temple Lessons", "Scholar's Workshop"]
    rows = [{**_PROGRAM, "name": name, "studiable_spell_ids": []} for name in names]
    # The physical row rides along because the real query returns one: the intent sentence
    # tells the judge these names ARE spell-training programs, so listing a technique row
    # among them states something the tool result denies.
    payload = {"programs": [*rows, _PHYSICAL_PROGRAM]}
    harness = SimpleNamespace(state={"result": _turn(_query(), _query_output(payload=payload))})
    intents: list[str] = []
    monkeypatch.setattr(training, "_judge", lambda _harness, intent: intents.append(intent))

    training._says_no_spell_can_be_studied(harness)

    assert len(intents) == 1
    assert all(name in intents[0] for name in names)
    assert _PHYSICAL_PROGRAM["name"] not in intents[0]
    assert "Arcane Study" not in intents[0]


def _message(text: str) -> llm.ChatMessage:
    return llm.ChatMessage(role="assistant", content=[text])


def _query(call_id: str = "query", *, kind: str = "training_programs") -> llm.FunctionCall:
    return llm.FunctionCall(call_id=call_id, name="query_info", arguments=json.dumps({"kind": kind}))


def _query_output(
    call_id: str = "query",
    *,
    payload: object = None,
    raw: str | None = None,
    name: str = "query_info",
    is_error: bool = False,
) -> llm.FunctionCallOutput:
    body = {"programs": [_PROGRAM]} if payload is None else payload
    return llm.FunctionCallOutput(
        call_id=call_id,
        name=name,
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
    name: str = "begin_activity",
    is_error: bool = False,
) -> llm.FunctionCallOutput:
    payload = {"activity_id": "train_1", "state": "running_first_half"}
    return llm.FunctionCallOutput(
        call_id=call_id,
        name=name,
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
        _PAIRS,
    )


def _begin_error() -> None:
    training_start(_turn(_begin(), _begin_output(is_error=True)), _PAIRS)


def _malformed_begin_output() -> None:
    training_start(_turn(_begin(), _begin_output(raw="not json")), _PAIRS)


def _persisted_row_mismatch() -> None:
    start = training_start(_turn(_begin(), _begin_output()), _PAIRS)
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
        _PAIRS,
    )


def _non_object_query_output() -> None:
    training_program_result(_turn(_query(), _query_output(raw=json.dumps(["arcane_study"]))))


def _query_output_precedes_call() -> None:
    training_program_result(_turn(_query_output(), _query()))


def _renamed_query_output() -> None:
    training_program_result(_turn(_query(), _query_output(name="begin_activity")))


def _no_programs_key() -> None:
    training_program_result(_turn(_query(), _query_output(payload={"spell_learning_progress": []})))


def _programs_not_a_list() -> None:
    spell_programs({"programs": "arcane_study"})


def _studiable_ids_not_a_list() -> None:
    spell_programs({"programs": [{**_PROGRAM, "studiable_spell_ids": "arcane_counterspell"}]})


def _spell_program_without_id() -> None:
    eligible_spell_pairs({"programs": [{k: v for k, v in _PROGRAM.items() if k != "id"}]})


def _turn_narrated_nothing() -> None:
    offered_spell(_turn(_query(), _query_output()), _PAIRS)


def _two_training_starts() -> None:
    training_start(_turn(_begin("a"), _begin_output("a"), _begin("b"), _begin_output("b")), _PAIRS)


def _non_training_activity() -> None:
    # Training-shaped ids under a different kind: the ids alone satisfy every
    # neighbouring guard, so only the `kind` check can red on this one.
    call = llm.FunctionCall(
        call_id="begin",
        name="begin_activity",
        arguments=json.dumps(
            {"activity": {"kind": "crafting", "program_id": "arcane_study", "spell_id": "arcane_counterspell"}}
        ),
    )
    training_start(_turn(call, _begin_output()), _PAIRS)


def _activity_not_an_object() -> None:
    call = llm.FunctionCall(call_id="begin", name="begin_activity", arguments=json.dumps({"activity": "training"}))
    training_start(_turn(call, _begin_output()), _PAIRS)


def _non_string_selection_ids() -> None:
    call = llm.FunctionCall(
        call_id="begin",
        name="begin_activity",
        arguments=json.dumps({"activity": {"kind": "training", "program_id": "arcane_study", "spell_id": None}}),
    )
    training_start(_turn(call, _begin_output()), _PAIRS)


def _mismatched_begin_output() -> None:
    training_start(_turn(_begin(), _begin_output("other")), _PAIRS)


def _begin_output_precedes_call() -> None:
    training_start(_turn(_begin_output(), _begin()), _PAIRS)


def _renamed_begin_output() -> None:
    training_start(_turn(_begin(), _begin_output(name="query_info")), _PAIRS)


def _begin_output_without_activity_id() -> None:
    training_start(_turn(_begin(), _begin_output(raw=json.dumps({"state": "running_first_half"}))), _PAIRS)


def _begin_output_without_state() -> None:
    training_start(_turn(_begin(), _begin_output(raw=json.dumps({"activity_id": "train_1"}))), _PAIRS)


def _started() -> TrainingStart:
    return training_start(_turn(_begin(), _begin_output()), _PAIRS)


def _training_not_persisted() -> None:
    assert_persisted_training(None, _started())


def _persisted_row_without_data() -> None:
    assert_persisted_training({"state": "running_first_half"}, _started())


def _persisted_state_mismatch() -> None:
    assert_persisted_training(
        {
            "state": "awaiting_decision",
            "data": {"program_id": "arcane_study", "spell_id": "arcane_counterspell"},
        },
        _started(),
    )


def _persisted_program_mismatch() -> None:
    assert_persisted_training(
        {
            "state": "running_first_half",
            "data": {"program_id": "combat_basics", "spell_id": "arcane_counterspell"},
        },
        _started(),
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
        pytest.param(_non_object_query_output, id="non-object-query-output"),
        pytest.param(_query_output_precedes_call, id="query-output-precedes-call"),
        pytest.param(_renamed_query_output, id="renamed-query-output"),
        pytest.param(_no_programs_key, id="no-programs-key"),
        pytest.param(_programs_not_a_list, id="programs-not-a-list"),
        pytest.param(_studiable_ids_not_a_list, id="studiable-ids-not-a-list"),
        pytest.param(_spell_program_without_id, id="spell-program-without-id"),
        pytest.param(_turn_narrated_nothing, id="turn-narrated-nothing"),
        pytest.param(_two_training_starts, id="two-training-starts"),
        pytest.param(_non_training_activity, id="non-training-activity"),
        pytest.param(_activity_not_an_object, id="activity-not-an-object"),
        pytest.param(_non_string_selection_ids, id="non-string-selection-ids"),
        pytest.param(_mismatched_begin_output, id="mismatched-begin-output"),
        pytest.param(_begin_output_precedes_call, id="begin-output-precedes-call"),
        pytest.param(_renamed_begin_output, id="renamed-begin-output"),
        pytest.param(_begin_output_without_activity_id, id="begin-output-without-activity-id"),
        pytest.param(_begin_output_without_state, id="begin-output-without-state"),
        pytest.param(_training_not_persisted, id="training-not-persisted"),
        pytest.param(_persisted_row_without_data, id="persisted-row-without-data"),
        pytest.param(_persisted_state_mismatch, id="persisted-state-mismatch"),
        pytest.param(_persisted_program_mismatch, id="persisted-program-mismatch"),
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
