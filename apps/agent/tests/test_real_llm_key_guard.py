"""The real-LLM tier must fail loud, not absent itself (sprint-47 story-019 AC1).

`5 skipped` in the pre-push gate is a false green: the only tier that reaches the
Anthropic API certified nothing. The guard is opt-in via REQUIRE_REAL_LLM so the
GitHub CI job (ci.yml runs the whole suite with no key) keeps skipping — see the
sprint-047 note on adding the secret.
"""

import re
from pathlib import Path

import pytest
from acceptance._real_llm import require_real_llm_key

_ACCEPTANCE_DIR = Path(__file__).parent / "acceptance"
# What "reaches the Anthropic API" looks like in a test module — the same grep the card used
# to establish that exactly two scenarios do.
_REACHES_THE_API = re.compile(r"anthropic\.LLM|ANTHROPIC_API_KEY")


def _real_llm_modules() -> list[Path]:
    return sorted(p for p in _ACCEPTANCE_DIR.rglob("test_*.py") if _REACHES_THE_API.search(p.read_text()))


def test_absent_opt_in_stays_silent():
    """No REQUIRE_REAL_LLM — CI's path. Today's skip is preserved, not converted to a failure."""
    require_real_llm_key({})
    require_real_llm_key({"ANTHROPIC_API_KEY": "sk-ant-real"})


def test_opt_in_without_a_key_raises_naming_the_var():
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        require_real_llm_key({"REQUIRE_REAL_LLM": "1"})


def test_opt_in_with_an_empty_key_raises():
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        require_real_llm_key({"REQUIRE_REAL_LLM": "1", "ANTHROPIC_API_KEY": ""})


def test_opt_in_with_the_env_example_placeholder_raises():
    """Every teammate worktree's .env carries .env.example's truthy `your-anthropic-api-key`.
    skipif does not fire on it, so without this branch the scenarios boot Docker and then 401."""
    with pytest.raises(RuntimeError, match="placeholder"):
        require_real_llm_key({"REQUIRE_REAL_LLM": "1", "ANTHROPIC_API_KEY": "your-anthropic-api-key"})


def test_opt_in_with_a_real_key_passes():
    require_real_llm_key({"REQUIRE_REAL_LLM": "1", "ANTHROPIC_API_KEY": "sk-ant-real"})


def test_every_real_llm_scenario_is_wired_into_the_guard():
    """The gate is only as good as the two marks a module has to carry BY HAND: the `real_llm`
    marker the conftest fixture keys on, and a skipif that knows about REQUIRE_REAL_LLM. A new
    scenario that carries neither skips exactly as before and the false green is back — and
    Sprint 48 owes a combat scenario, so this is a change that is already scheduled.
    """
    modules = _real_llm_modules()
    assert modules, f"no acceptance module matched {_REACHES_THE_API.pattern} — the scan went vacuous"
    for path in modules:
        source = path.read_text()
        assert "pytest.mark.real_llm" in source, f"{path.name} reaches the API but carries no real_llm marker"
        assert "REQUIRE_REAL_LLM" in source, (
            f"{path.name}'s skipif does not know about REQUIRE_REAL_LLM — it would fire first and "
            "keep the silence the marker is there to break"
        )
