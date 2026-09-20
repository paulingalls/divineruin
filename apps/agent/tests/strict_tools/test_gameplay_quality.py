"""Closed contract for the representative Luna gameplay manifest."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from acceptance.strict_luna_assertions import STATE_BRANCHES, state_branch
from acceptance.strict_luna_fixtures import MANIFEST_PATH, REQUIRED_CASE_IDS, load_case_manifest
from acceptance.strict_luna_runtime import _cost, grade_trace
from livekit.agents import llm
from livekit.agents.voice.run_result import ChatMessageEvent, FunctionCallEvent


def _row(case_id: str) -> dict:
    profile, action = case_id.split(".", 1)
    return {
        "id": case_id,
        "profile": profile,
        "seed": case_id,
        "prompt": f"Perform {action}",
        "expected_tool": action,
        "expected_variant": None,
        "prerequisite": None,
        "assertion": case_id,
        "narration_anchor": "done",
    }


def _write(path: Path, rows: list[dict]) -> Path:
    path.write_text(json.dumps(rows))
    return path


def test_checked_in_manifest_is_exact_and_reachable() -> None:
    cases = load_case_manifest()

    assert len(cases) == 27
    assert {case.id for case in cases} == REQUIRED_CASE_IDS
    assert {case.profile for case in cases} == {
        "exploration",
        "combat",
        "dispatch",
        "onboarding",
        "blacksmith",
        "creation",
    }


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda rows: [], "empty"),
        (lambda rows: rows[1:], "missing"),
        (lambda rows: [*rows, rows[0]], "duplicate"),
        (lambda rows: [*rows, {**rows[0], "id": "exploration.unknown"}], "unknown"),
    ],
)
def test_manifest_rejects_closed_set_faults(tmp_path: Path, mutation, message: str) -> None:
    rows = json.loads(MANIFEST_PATH.read_text())

    with pytest.raises(ValueError, match=message):
        load_case_manifest(_write(tmp_path / "cases.json", mutation(rows)))


def test_manifest_rejects_missing_or_moved_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="manifest"):
        load_case_manifest(tmp_path / "moved.json")


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("profile", "unknown", "profile"),
        ("seed", "unknown", "seed"),
        ("assertion", "unknown", "assertion"),
        ("expected_tool", "unknown", "tool"),
        ("expected_variant", "unknown", "variant"),
        ("prerequisite", "unknown", "prerequisite"),
        ("prompt", "", "prompt"),
        ("narration_anchor", "", "narration_anchor"),
        ("unexpected", True, "unknown fields"),
    ],
)
def test_manifest_rejects_unexecutable_rows(tmp_path: Path, field: str, value, message: str) -> None:
    rows = [_row(case_id) for case_id in sorted(REQUIRED_CASE_IDS)]
    rows[0][field] = value

    with pytest.raises(ValueError, match=message):
        load_case_manifest(_write(tmp_path / "cases.json", rows))


def _events(*items):
    wrappers = {llm.ChatMessage: ChatMessageEvent, llm.FunctionCall: FunctionCallEvent}
    return [wrappers[type(item)](item=item) for item in items]


def _call(name: str, arguments: str = "{}") -> llm.FunctionCall:
    return llm.FunctionCall(call_id=name, name=name, arguments=arguments)


def test_trace_rejects_abstention_extra_call_and_wrong_variant() -> None:
    case = next(case for case in load_case_manifest() if case.id == "exploration.check_gather")
    narration = llm.ChatMessage(role="assistant", content=["The herbs are gathered."])

    with pytest.raises(AssertionError, match="expected"):
        grade_trace(case, _events(narration))
    with pytest.raises(AssertionError, match="expected"):
        grade_trace(case, _events(_call("check", '{"roll":{"kind":"gather"}}'), _call("transact"), narration))
    with pytest.raises(AssertionError, match="expected variant"):
        grade_trace(case, _events(_call("check", '{"roll":{"kind":"dice"}}'), narration))


def test_trace_rejects_missing_anchor_and_overlong_direct_reply() -> None:
    case = next(case for case in load_case_manifest() if case.id == "exploration.query_inventory")
    call = _call("query_info", '{"kind":"inventory","target_id":null}')
    with pytest.raises(AssertionError, match="omitted anchor"):
        grade_trace(case, _events(call, llm.ChatMessage(role="assistant", content=["You carry a potion."])))
    with pytest.raises(AssertionError, match="5 sentences"):
        grade_trace(
            case,
            _events(call, llm.ChatMessage(role="assistant", content=["Satchel one. Two. Three. Four. Five."])),
        )
    with pytest.raises(AssertionError, match="unknown voice"):
        grade_trace(
            case,
            _events(call, llm.ChatMessage(role="assistant", content=['[INVENTED, calm]: "The satchel is ready."'])),
        )


def test_trace_rejects_a_variant_no_check_covers() -> None:
    case = replace(
        next(case for case in load_case_manifest() if case.id == "exploration.activate_self"),
        expected_variant="attack",
    )
    narration = llm.ChatMessage(role="assistant", content=["A second breath fills her lungs."])

    with pytest.raises(AssertionError, match="no variant check"):
        grade_trace(case, _events(_call("activate", '{"target_id":null,"target_ids":null}'), narration))


def test_every_required_case_routes_to_a_state_assertion() -> None:
    assert set(STATE_BRANCHES) == REQUIRED_CASE_IDS

    with pytest.raises(AssertionError, match="no persisted-state assertion"):
        state_branch("exploration.not_routed")


def test_luna_cost_separates_cached_input() -> None:
    assert _cost({"total_input": 1_000_000, "total_cache_read": 250_000, "total_output": 100_000}) == pytest.approx(
        0.275
    )
