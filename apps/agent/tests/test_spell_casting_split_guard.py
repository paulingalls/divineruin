import subprocess
import sys
from pathlib import Path

AGENT_ROOT = Path(__file__).parents[1]
MAX_LINES = 500
SPELL_CASTING_FILES = (
    "tests/_spell_casting_helpers.py",
    "tests/test_spell_cast_focus.py",
    "tests/test_spell_cast_resonance.py",
    "tests/test_spell_cast_ward.py",
    "tests/test_spell_cast_concentration.py",
    "tests/test_resolve_cast.py",
    "tests/test_spell_info_tool.py",
    "tests/test_spell_casting.py",
    "tests/test_spell_casting_split_guard.py",
)
SPELL_CASTING_TEST_FILES = (
    "tests/test_spell_cast_focus.py",
    "tests/test_spell_cast_resonance.py",
    "tests/test_spell_cast_ward.py",
    "tests/test_spell_cast_concentration.py",
    "tests/test_resolve_cast.py",
    "tests/test_spell_info_tool.py",
)


def test_spell_casting_files_stay_under_cap():
    oversized = {
        path: len((AGENT_ROOT / path).read_text().splitlines())
        for path in SPELL_CASTING_FILES
        if len((AGENT_ROOT / path).read_text().splitlines()) > MAX_LINES
    }

    assert oversized == {}


def test_spell_casting_collects_58_tests():
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", *SPELL_CASTING_TEST_FILES],
        cwd=AGENT_ROOT,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    nodes = [line for line in result.stdout.splitlines() if line.startswith("tests/") and "::" in line]
    assert len(nodes) == 58
