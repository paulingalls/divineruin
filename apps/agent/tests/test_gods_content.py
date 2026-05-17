"""Tests for _gods_content — the sole chokepoint for content/gods.json reads.

Sprint-004 story-004: extracts shared loader so the path literal and json.loads
call live exactly once. ADR 0001 patron SoT — enforced by construction by the
two pinning tests at the bottom of this file (grep + spy meta-test).
"""

from __future__ import annotations

import types
from pathlib import Path

import pytest

import _gods_content
from _gods_content import load_gods

_PATH_CONSTRUCTION_LITERAL = '/ "content" / "gods.json"'


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


def test_only_gods_content_module_constructs_the_real_gods_json_path():
    """Pin AC3: the path-construction literal `/ "content" / "gods.json"` must
    live in exactly one place — `_gods_content.py`. Docstrings, error messages,
    test names, and `tmp_path / "gods.json"` writes don't match this literal."""
    agent_root = Path(__file__).resolve().parents[1]
    expected = agent_root / "_gods_content.py"
    # This file defines the literal as the pattern it greps for — exclude self.
    self_file = Path(__file__).resolve()

    # Positive guard: if _gods_content.py is reformatted (e.g. spacing changes)
    # the literal must be updated, otherwise the negative scan would silently pass.
    assert _PATH_CONSTRUCTION_LITERAL in expected.read_text(), (
        f"Path-construction literal {_PATH_CONSTRUCTION_LITERAL!r} no longer appears "
        f"in {expected.name}. Update _PATH_CONSTRUCTION_LITERAL to match the new form."
    )

    offenders: list[Path] = []
    for py_file in agent_root.rglob("*.py"):
        if py_file in (expected, self_file):
            continue
        if _PATH_CONSTRUCTION_LITERAL in py_file.read_text():
            offenders.append(py_file.relative_to(agent_root))

    assert not offenders, (
        f"content/gods.json path constructed outside _gods_content.py: {offenders}. "
        "Route the new caller through _gods_content.load_gods() instead."
    )


def _install_helper_spy(monkeypatch, spy, real_fn, modules) -> None:
    """Rebind every binding of `real_fn` in `modules` to `spy`.

    Catches both module-attr callers and from-import callers. Mirrors the
    pattern proven in test_hybrid_counter.py for skill_persistence.
    """
    for module in modules:
        for name, value in list(vars(module).items()):
            if value is real_fn:
                monkeypatch.setattr(module, name, spy)


def test_load_gods_spy_install_catches_from_import_caller(monkeypatch):
    """Pin AC2 (no false-pass): a hypothetical caller that captured load_gods
    via `from _gods_content import load_gods` would evade a module-attr-only
    patch. Verify the rebind walk catches that caller too — without this guard,
    a future bypass could silently route around the chokepoint."""
    real_fn = _gods_content.load_gods

    fake_caller = types.ModuleType("fake_caller_from_import")
    setattr(fake_caller, real_fn.__name__, real_fn)

    calls: list[int] = []

    def spy():
        calls.append(1)
        return real_fn()

    _install_helper_spy(monkeypatch, spy, real_fn, [_gods_content, fake_caller])

    rebound = getattr(fake_caller, real_fn.__name__)
    assert rebound is spy

    rebound()
    assert len(calls) == 1
