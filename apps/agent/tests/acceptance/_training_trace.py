"""Returned-state guards for real training turns."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from acceptance._judged_turn import last_assistant_message_index
from livekit.agents.voice.run_result import (
    ChatMessageEvent,
    FunctionCallEvent,
    FunctionCallOutputEvent,
    RunResult,
)


def _object_json(raw: str, label: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, TypeError) as exc:
        raise AssertionError(f"{label} returned malformed JSON: {raw!r}") from exc
    assert isinstance(value, dict), f"{label} returned non-object JSON: {value!r}"
    return value


def training_program_result(result: RunResult) -> dict[str, Any]:
    calls = []
    for index, event in enumerate(result.events):
        if not isinstance(event, FunctionCallEvent) or event.item.name != "query_info":
            continue
        arguments = _object_json(event.item.arguments, "query_info arguments")
        if arguments.get("kind") == "training_programs":
            calls.append((index, event.item))
    assert len(calls) == 1, f"expected one query_info(training_programs) call, got {calls}; events={result.events!r}"
    call_index, call = calls[0]

    outputs = [
        (index, event.item)
        for index, event in enumerate(result.events)
        if isinstance(event, FunctionCallOutputEvent) and event.item.call_id == call.call_id
    ]
    assert len(outputs) == 1, f"expected one output for query_info ({call.call_id}), got {outputs}"
    output_index, output = outputs[0]
    assert call_index < output_index, "query_info output preceded its call"
    assert output.name == "query_info", f"query_info call matched output named {output.name!r}"
    assert not output.is_error, f"query_info(training_programs) failed: {output.output!r}"
    payload = _object_json(output.output, "query_info(training_programs)")
    programs = payload.get("programs")
    assert isinstance(programs, list), f"training programs result has no programs list: {payload!r}"
    return payload


def spell_programs(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    programs = payload.get("programs")
    assert isinstance(programs, list), f"training programs result has no programs list: {payload!r}"
    rows = [
        row
        for row in programs
        if isinstance(row, dict)
        and isinstance(row.get("training_activity_type"), str)
        and row["training_activity_type"].startswith("spell_")
    ]
    assert rows, f"training programs result contained no spell-program rows: {programs!r}"
    for row in rows:
        choices = row.get("studiable_spell_ids")
        assert isinstance(choices, list) and all(isinstance(choice, str) for choice in choices), (
            f"spell program has invalid studiable_spell_ids: {row!r}"
        )
    return rows


def eligible_spell_pairs(payload: Mapping[str, Any]) -> set[tuple[str, str]]:
    pairs = set()
    for row in spell_programs(payload):
        program_id = row.get("id")
        assert isinstance(program_id, str) and program_id, f"spell program has invalid id: {row!r}"
        pairs.update((program_id, spell_id) for spell_id in row["studiable_spell_ids"])
    return pairs


def offered_spell(result: RunResult, eligible_pairs: set[tuple[str, str]]) -> tuple[str, str, str]:
    event = result.events[last_assistant_message_index(result.events)]
    # Narrowing for the type checker, not a guard: last_assistant_message_index only ever
    # returns the index of an event whose type is "message", and ChatMessageEvent is the only
    # such class — a turn that narrated nothing reds inside it, never here.
    assert isinstance(event, ChatMessageEvent), f"selected narration was not a message: {event!r}"
    text = (event.item.text_content or "").lower()
    matches = []
    for program_id, spell_id in sorted(eligible_pairs):
        label = spell_id.split("_", 1)[-1].replace("_", " ")
        if re.search(rf"\b{re.escape(label)}\b", text):
            matches.append((program_id, spell_id, label))
    assert matches, f"narration mentioned no returned eligible spell: {text!r}"
    return matches[0]


def assert_no_training_start(result: RunResult) -> None:
    calls = [
        event.item
        for event in result.events
        if isinstance(event, FunctionCallEvent) and event.item.name == "begin_activity"
    ]
    assert not calls, f"inquiry started an activity: {calls}"


@dataclass(frozen=True)
class TrainingStart:
    activity_id: str
    program_id: str
    spell_id: str
    state: str


def training_start(result: RunResult, eligible_pairs: set[tuple[str, str]]) -> TrainingStart:
    calls = [
        (index, event.item)
        for index, event in enumerate(result.events)
        if isinstance(event, FunctionCallEvent) and event.item.name == "begin_activity"
    ]
    assert len(calls) == 1, f"expected one begin_activity call, got {calls}; events={result.events!r}"
    call_index, call = calls[0]
    arguments = _object_json(call.arguments, "begin_activity arguments")
    activity = arguments.get("activity")
    assert isinstance(activity, dict) and activity.get("kind") == "training", (
        f"begin_activity did not select training: {arguments!r}"
    )
    program_id = activity.get("program_id")
    spell_id = activity.get("spell_id")
    assert isinstance(program_id, str) and isinstance(spell_id, str), (
        f"training selection has invalid ids: {activity!r}"
    )
    pair = (program_id, spell_id)
    assert pair in eligible_pairs, f"selected spell was not returned as eligible: {pair!r} not in {eligible_pairs!r}"

    outputs = [
        (index, event.item)
        for index, event in enumerate(result.events)
        if isinstance(event, FunctionCallOutputEvent) and event.item.call_id == call.call_id
    ]
    assert len(outputs) == 1, f"expected one output for begin_activity ({call.call_id}), got {outputs}"
    output_index, output = outputs[0]
    assert call_index < output_index, "begin_activity output preceded its call"
    assert output.name == "begin_activity", f"begin_activity call matched output named {output.name!r}"
    assert not output.is_error, f"begin_activity failed: {output.output!r}"
    payload = _object_json(output.output, "begin_activity")
    activity_id = payload.get("activity_id")
    state = payload.get("state")
    assert isinstance(activity_id, str) and activity_id, f"begin_activity returned invalid activity_id: {payload!r}"
    assert isinstance(state, str) and state, f"begin_activity returned invalid state: {payload!r}"
    return TrainingStart(activity_id, program_id, spell_id, state)


def assert_persisted_training(row: Mapping[str, Any] | None, start: TrainingStart) -> None:
    assert row is not None, f"training activity {start.activity_id!r} was not persisted"
    data = row.get("data")
    assert isinstance(data, dict), f"persisted training has invalid data: {row!r}"
    assert row.get("state") == start.state, f"persisted state disagrees with begin result: {row!r}"
    assert data.get("program_id") == start.program_id, f"persisted program disagrees with selection: {row!r}"
    assert data.get("spell_id") == start.spell_id, f"persisted spell disagrees with selection: {row!r}"
