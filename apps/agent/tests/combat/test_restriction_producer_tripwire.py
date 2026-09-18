import ast
import inspect
import json
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path
from typing import cast

import pytest

import combat_condition_landing
import conditions
from condition_restrictions import NOT_ENFORCED

REPO_ROOT = Path(__file__).resolve().parents[4]
CONTENT_PATHS = tuple(sorted((REPO_ROOT / "content").glob("*.json")))
SOURCE_PATHS = tuple(
    path
    for path in sorted((REPO_ROOT / "apps" / "agent").rglob("*.py"))
    if not {"tests", ".venv"}.intersection(path.relative_to(REPO_ROOT / "apps" / "agent").parts)
)


def _condition_argument(callee: Callable, keyword: str) -> tuple[int, str]:
    """Where the condition type sits in ``callee``, read off the real signature.

    Taken from the live function rather than written down, so a reordered or renamed parameter
    fails here instead of leaving the walk reading the wrong argument and passing every producer.
    """
    parameters = list(inspect.signature(callee).parameters)
    if keyword not in parameters:
        raise AssertionError(f"{callee.__qualname__} no longer takes {keyword!r}: {parameters}")
    return parameters.index(keyword), keyword


CONDITION_ARGUMENTS = {
    "apply_condition": _condition_argument(conditions.apply_condition, "condition_type"),
    "_land_condition_on_one": _condition_argument(combat_condition_landing._land_condition_on_one, "cond_type"),
}


def _json_condition_values(value: object) -> Iterator[str]:
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "applies_condition" and isinstance(item, str):
                yield item
            yield from _json_condition_values(item)
    elif isinstance(value, list):
        for item in value:
            yield from _json_condition_values(item)


def _content_producers(paths: Iterable[Path]) -> list[str]:
    return [condition for path in paths for condition in _json_condition_values(json.loads(path.read_text()))]


def _callee_name(call: ast.Call) -> str | None:
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return None


def _literal_condition(call: ast.Call, position: int, keyword: str) -> str | None:
    argument: ast.expr | None = call.args[position] if len(call.args) > position else None
    if argument is None:
        argument = next((item.value for item in call.keywords if item.arg == keyword), None)
    if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
        return argument.value
    return None


def _python_producers(paths: Iterable[Path]) -> list[str]:
    produced = []
    for path in paths:
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            callee = _callee_name(node)
            if callee is None:
                continue
            signature = CONDITION_ARGUMENTS.get(callee)
            if signature is not None and (condition := _literal_condition(node, *signature)) is not None:
                produced.append(condition)
    return produced


def _produced_conditions(content_paths: Iterable[Path], source_paths: Iterable[Path]) -> set[str]:
    return set(_content_producers(content_paths)) | set(_python_producers(source_paths))


def _assert_no_deferred_carrier_is_produced(produced: set[str]) -> None:
    violations = {}
    for restriction, metadata in NOT_ENFORCED.items():
        if metadata["waits_on"] != "producer":
            continue
        carriers = cast(set[str], metadata["carriers"])
        if overlap := carriers & produced:
            violations[restriction] = overlap
    assert not violations, violations


def test_no_producer_waiting_condition_is_produced():
    _assert_no_deferred_carrier_is_produced(_produced_conditions(CONTENT_PATHS, SOURCE_PATHS))


def test_content_charmed_producer_trips_no_hostile_source(tmp_path):
    scratch = tmp_path / "charmed.json"
    scratch.write_text(json.dumps({"actions": [{"applies_condition": "charmed"}]}))

    with pytest.raises(AssertionError, match="no_hostile_source"):
        _assert_no_deferred_carrier_is_produced(_produced_conditions((*CONTENT_PATHS, scratch), SOURCE_PATHS))


def test_python_charmed_producers_trip_no_hostile_source(tmp_path):
    scratch = tmp_path / "charmed.py"
    scratch.write_text(
        """
conditions.apply_condition(
    current,
    "charmed",
)
_land_condition_on_one(state, target, attacker, "charmed", source)
conditions.apply_condition(current, condition_type="charmed")
_land_condition_on_one(state, target, attacker, cond_type="charmed", source=source)
"""
    )

    assert _python_producers((scratch,)) == ["charmed"] * 4
    with pytest.raises(AssertionError, match="no_hostile_source"):
        _assert_no_deferred_carrier_is_produced(_produced_conditions(CONTENT_PATHS, (*SOURCE_PATHS, scratch)))
