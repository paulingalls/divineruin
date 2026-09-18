import subprocess
import sys
from pathlib import Path

AGENT_ROOT = Path(__file__).parents[2]
DISCOVER_TEST_FILES = (
    "tests/tools/test_discover.py",
    "tests/tools/test_discover_targeting.py",
    "tests/tools/test_discover_lockout.py",
)


def test_discover_split_collects_26_tests():
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", *DISCOVER_TEST_FILES],
        cwd=AGENT_ROOT,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    nodes = [line for line in result.stdout.splitlines() if line.startswith("tests/") and "::" in line]
    assert len(nodes) == 26
