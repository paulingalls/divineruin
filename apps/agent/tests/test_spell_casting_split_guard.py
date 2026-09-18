import subprocess
import sys
from pathlib import Path

AGENT_ROOT = Path(__file__).parents[1]
MAX_LINES = 500
SPELL_CASTING_TEST_FILES = (
    "tests/test_spell_cast_focus.py",
    "tests/test_spell_cast_resonance.py",
    "tests/test_spell_cast_ward.py",
    "tests/test_spell_cast_concentration.py",
    "tests/test_resolve_cast.py",
    "tests/test_spell_info_tool.py",
)
# The retired 1148-line original stays in the tree, emptied: story-061's recorded Verify
# command names this path, so deleting it would break a command already written down.
RETIRED_PATH = "tests/test_spell_casting.py"
SPELL_CASTING_FILES = tuple(
    sorted(
        {
            "tests/_spell_casting_helpers.py",
            *SPELL_CASTING_TEST_FILES,
            RETIRED_PATH,
            *(path.relative_to(AGENT_ROOT).as_posix() for path in (AGENT_ROOT / "tests").glob("test_spell_cast*.py")),
        }
    )
)


def test_spell_casting_files_stay_under_cap():
    lengths = {path: len((AGENT_ROOT / path).read_text().splitlines()) for path in SPELL_CASTING_FILES}

    assert {path: count for path, count in lengths.items() if count > MAX_LINES} == {}


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
