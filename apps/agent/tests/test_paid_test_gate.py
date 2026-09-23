"""Paid provider tests are skipped unless a human approved the run (tests/_paid_tests.py)."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
from _paid_tests import APPROVAL_VAR, PAID_MARKERS, paid_skip_reason

_TESTS = Path(__file__).parent
_ACCEPTANCE = _TESTS / "acceptance"
_PROVIDER_LITERALS = ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "has_live_voice_key")


@pytest.mark.parametrize("marker", sorted(PAID_MARKERS))
def test_a_paid_marker_is_skipped_even_with_every_key_present(marker):
    env = {"ANTHROPIC_API_KEY": "sk-ant-real", "OPENAI_API_KEY": "sk-real", "DEEPGRAM_API_KEY": "dg-real"}
    assert paid_skip_reason([marker, "acceptance"], env) is not None
    assert paid_skip_reason([marker], {**env, "REQUIRE_REAL_LLM": "1"}) is not None


@pytest.mark.parametrize("marker", sorted(PAID_MARKERS))
def test_only_explicit_approval_runs_a_paid_test(marker):
    assert paid_skip_reason([marker], {APPROVAL_VAR: "1"}) is None
    assert paid_skip_reason([marker], {APPROVAL_VAR: "true"}) is not None
    assert paid_skip_reason([marker], {APPROVAL_VAR: ""}) is not None


def test_an_unpaid_test_is_never_skipped_by_the_gate():
    assert paid_skip_reason(["acceptance", "asyncio"], {}) is None


def _pytestmark_markers(source: str) -> set[str]:
    match = re.search(r"^pytestmark = (\[.*?^\]|pytest\.mark\.\w+)", source, re.MULTILINE | re.DOTALL)
    return set(re.findall(r"pytest\.mark\.(\w+)", match.group(1))) if match else set()


def test_every_acceptance_module_that_reaches_a_provider_carries_a_paid_marker():
    """A module the gate cannot see spends money on every run. The walk reds when its corpus is
    empty: a moved acceptance directory must not read as 'nothing is paid'."""
    provider_modules = [
        path
        for path in sorted(_ACCEPTANCE.rglob("test_*.py"))
        if any(literal in path.read_text() for literal in _PROVIDER_LITERALS)
    ]
    assert len(provider_modules) >= 10, f"only {len(provider_modules)} provider modules found under {_ACCEPTANCE}"
    unmarked = [
        str(path.relative_to(_TESTS))
        for path in provider_modules
        if not _pytestmark_markers(path.read_text()) & PAID_MARKERS
    ]
    assert not unmarked, f"provider-reaching modules without a paid marker: {unmarked}"


def test_a_real_run_with_keys_present_skips_a_paid_module_before_any_request():
    """The collection hook, not the pure function, is what protects the budget. Fake keys make
    a gate regression fail on a refused request instead of spending."""
    env = {k: v for k, v in os.environ.items() if k != APPROVAL_VAR}
    env.update(ANTHROPIC_API_KEY="sk-ant-fake-gate-probe", REQUIRE_REAL_LLM="1")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/acceptance/test_narration_schema.py",
            "-q",
            "-rs",
            "-p",
            "no:cacheprovider",
        ],
        cwd=_TESTS.parent,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout[-2000:] + result.stderr[-2000:]
    assert re.search(r"\b\d+ skipped\b", result.stdout), result.stdout[-2000:]
    assert "passed" not in result.stdout and "failed" not in result.stdout, result.stdout[-2000:]
    assert APPROVAL_VAR in result.stdout, result.stdout[-2000:]


def test_guest_capstone_skips_for_approval_even_when_both_keys_are_present():
    env = {k: v for k, v in os.environ.items() if k != APPROVAL_VAR}
    env.update(OPENAI_API_KEY="sk-invalid-gate-probe", DEEPGRAM_API_KEY="dg-invalid-gate-probe")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/acceptance/multiplayer_voice/test_guest_capstone.py",
            "-q",
            "-rs",
            "-p",
            "no:cacheprovider",
        ],
        cwd=_TESTS.parent,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout[-2000:] + result.stderr[-2000:]
    assert "1 skipped" in result.stdout and APPROVAL_VAR in result.stdout, result.stdout[-2000:]


def test_approved_guest_capstone_fails_loud_without_openai_key():
    env = dict(os.environ)
    env.update(ALLOW_PAID_TESTS="1", REQUIRE_REAL_LLM="1", DEEPGRAM_API_KEY="dg-fake-gate-probe", OPENAI_API_KEY="")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/acceptance/multiplayer_voice/test_guest_capstone.py",
            "-q",
            "-p",
            "no:cacheprovider",
        ],
        cwd=_TESTS.parent,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode != 0, result.stdout[-2000:] + result.stderr[-2000:]
    assert "OPENAI_API_KEY is absent" in result.stdout
    assert "xfailed" not in result.stdout
