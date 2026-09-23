"""A test that boots a Docker container belongs to the acceptance lane.

The fast lane (`bun run test:python`, `-m "not acceptance"`) must run without Docker, and
tests/acceptance/conftest.py is what marks a test `acceptance`, so a testcontainers import
anywhere else in tests/ puts container boots into every fast-lane run.
"""

from __future__ import annotations

import re
from pathlib import Path

_TESTS = Path(__file__).parent
_CONTAINER_IMPORT = re.compile(r"^\s*(?:from|import)\s+testcontainers\b", re.MULTILINE)


def container_importers(tests: Path) -> tuple[list[Path], list[Path]]:
    """Return (files outside tests/acceptance, files inside it) that import testcontainers."""
    acceptance = tests / "acceptance"
    outside, inside = [], []
    for path in sorted(tests.rglob("*.py")):
        if _CONTAINER_IMPORT.search(path.read_text()):
            (inside if acceptance in path.parents else outside).append(path)
    return outside, inside


def test_only_acceptance_tests_boot_containers():
    outside, inside = container_importers(_TESTS)
    assert inside, "no acceptance test imports testcontainers; the walk measured nothing"
    assert outside == []


def test_a_fast_lane_container_import_is_caught(tmp_path):
    (tmp_path / "acceptance").mkdir()
    (tmp_path / "acceptance" / "conftest.py").write_text("from testcontainers.community.postgres import X\n")
    (tmp_path / "test_catalog.py").write_text("import asyncpg\nfrom testcontainers.community.postgres import X\n")
    outside, inside = container_importers(tmp_path)
    assert outside == [tmp_path / "test_catalog.py"]
    assert inside == [tmp_path / "acceptance" / "conftest.py"]
