"""Tests for _gods_content — the sole chokepoint for content/gods.json reads.

Sprint-004 story-004: extracts shared loader so the path literal and json.loads
call live exactly once. ADR 0001 patron SoT — enforced by construction (the
grep + spy pinning tests land in a later commit).
"""

from __future__ import annotations

import pytest

from _gods_content import load_gods


@pytest.fixture(autouse=True)
def _clear_load_gods_cache():
    """Reset @functools.cache between tests for deterministic identity checks."""
    load_gods.cache_clear()
    yield
    load_gods.cache_clear()


def test_load_gods_returns_list_of_entry_dicts():
    entries = load_gods()
    assert isinstance(entries, list)
    assert len(entries) == 10  # ADR 0001 — 10 patrons
    for entry in entries:
        assert isinstance(entry, dict)
        assert "god_id" in entry


def test_load_gods_is_cached():
    first = load_gods()
    second = load_gods()
    assert first is second  # @functools.cache returns the same object
