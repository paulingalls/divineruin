"""The live-voice tier must skip with a reason or fail loud — never fail nameless, never vanish.

TWO DIRECTIONS, and only one of them is cheap to get wrong. A missing skipif costs a red —
the scenario fails in STT setup, loudly — so under-detection here is survivable. A missing
LOUD path is the false green story-019 was written against: `6 skipped` in a human-approved
paid run (ALLOW_PAID_TESTS=1), where the only tier that reaches a real microphone certified nothing.
"""

import ast
from pathlib import Path

import pytest
from acceptance._live_voice import KEY_VAR, has_live_voice_key, require_live_voice_key

_TESTS_DIR = Path(__file__).parent
_VOICE_DIR = _TESTS_DIR / "acceptance" / "multiplayer_voice"
_WORKFLOW = _TESTS_DIR.parents[2] / ".github" / "workflows" / "ci.yml"


def test_absent_opt_in_stays_silent():
    """No REQUIRE_REAL_LLM — CI's path, and every ad-hoc `pytest tests/`. Skipping is allowed there."""
    require_live_voice_key({})
    require_live_voice_key({KEY_VAR: "dg-real"})


def test_opt_in_without_a_key_raises_naming_the_var():
    with pytest.raises(RuntimeError, match=KEY_VAR):
        require_live_voice_key({"REQUIRE_REAL_LLM": "1"})


def test_opt_in_with_an_empty_key_raises():
    with pytest.raises(RuntimeError, match=KEY_VAR):
        require_live_voice_key({"REQUIRE_REAL_LLM": "1", KEY_VAR: ""})


def test_opt_in_with_the_env_example_placeholder_raises():
    """.env.example's `your-deepgram-api-key` is truthy, so a bare skipif does not fire on it and
    the worktree that copied it boots LiveKit and Postgres before Deepgram refuses the key."""
    with pytest.raises(RuntimeError, match="placeholder"):
        require_live_voice_key({"REQUIRE_REAL_LLM": "1", KEY_VAR: "your-deepgram-api-key"})


def test_opt_in_with_a_real_key_passes():
    require_live_voice_key({"REQUIRE_REAL_LLM": "1", KEY_VAR: "dg-real"})


@pytest.mark.parametrize(
    ("env", "usable"),
    [
        ({}, False),
        ({KEY_VAR: ""}, False),
        ({KEY_VAR: "your-deepgram-api-key"}, False),
        ({KEY_VAR: "dg-real"}, True),
    ],
)
def test_the_skipif_predicate_reads_the_key_the_way_deepgram_would(env, usable):
    assert has_live_voice_key(env) is usable


def _pytestmark_source(path: Path) -> str | None:
    """The module's top-level `pytestmark` assignment as written, or None when it has none.

    The literals have to be read out of THAT statement, not out of the file: the module
    already imports `has_live_voice_key` for the mark, so a whole-file `in source` check
    stays green against a module whose mark was deleted and whose import stayed.
    """
    source = path.read_text()
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "pytestmark" for target in node.targets
        ):
            return ast.get_source_segment(source, node)
    return None


def _is_autouse_fixture(node: ast.FunctionDef) -> bool:
    return any(
        isinstance(decorator, ast.Call)
        and any(kw.arg == "autouse" and getattr(kw.value, "value", None) is True for kw in decorator.keywords)
        for decorator in node.decorator_list
    )


def _calls(node: ast.AST, name: str) -> bool:
    return any(
        isinstance(child, ast.Call) and isinstance(child.func, ast.Name) and child.func.id == name
        for child in ast.walk(node)
    )


def test_every_live_voice_scenario_is_wired_into_the_gate():
    """The mark is carried BY HAND per module, so a sixth scenario added to this package
    inherits nothing. The walk names its corpus and reds when that corpus comes back empty —
    a moved or renamed package is the failure mode this floor exists for."""
    modules = sorted(_VOICE_DIR.glob("test_*.py"))
    assert modules, f"no live-voice scenario found under {_VOICE_DIR} — the walk went vacuous"
    for path in modules:
        mark = _pytestmark_source(path)
        assert mark is not None, (
            f"{path.name} drives a real microphone and carries no pytestmark — a keyless run "
            "fails it in STT setup with a vendor error that names no cause"
        )
        assert "has_live_voice_key" in mark, (
            f"{path.name}'s pytestmark does not consult the live-voice gate, so it skips on "
            "some other condition than a usable Deepgram key"
        )
        assert "pytest.mark.live_voice" in mark, (
            f"{path.name} reaches paid Deepgram STT but does not carry the live_voice marker, so "
            "the ALLOW_PAID_TESTS approval gate (tests/_paid_tests.py) cannot skip it"
        )
        assert "REQUIRE_REAL_LLM" in mark, (
            f"{path.name}'s skipif does not know about REQUIRE_REAL_LLM — it would fire first and "
            "keep the silence the conftest gate is there to break"
        )


def test_the_package_gate_still_arms_the_loud_path():
    """The skipif half of the gate is per module and walked above; the loud half is ONE autouse
    fixture for the whole package, and deleting it costs no red anywhere else — a keyless
    pre-push run would go back to reporting `6 skipped` over a tier that reached no microphone.
    """
    conftest = _VOICE_DIR / "conftest.py"
    assert conftest.is_file(), f"{_VOICE_DIR.name} has no conftest — nothing fails the lane loud"
    # The CALL, not the name: the conftest imports the gate, so `"require_live_voice_key" in
    # source` stays green over a body that stopped calling it.
    armed = [
        node.name
        for node in ast.walk(ast.parse(conftest.read_text()))
        if isinstance(node, ast.FunctionDef) and _is_autouse_fixture(node) and _calls(node, "require_live_voice_key")
    ]
    assert armed, (
        "no autouse fixture in the live-voice conftest calls require_live_voice_key — an opted-in "
        "run with no key would report `6 skipped` over a tier that reached no microphone"
    )


def test_ci_hands_the_python_job_the_secret_the_gate_reads():
    """Name the producer: the gate skips on an absent key, so a workflow that never passes the
    secret down would keep skipping after someone configured it, and report green either way."""
    from ci_toolchain_validation import _workflow_jobs

    job = _workflow_jobs(_WORKFLOW)["test-python"]
    assert job.get("env", {}).get(KEY_VAR) == "${{ secrets." + KEY_VAR + " }}", (
        f"the test-python job does not pass {KEY_VAR} to pytest — configuring the repository "
        "secret would change nothing and the live-voice lane would skip forever"
    )
