"""Cross-language conformance guard for BLOCKED_DANGER_COMBOS.

The errand risk spec (game_mechanics_core.md §Companion Risk L887-892) is pinned
independently in two places — apps/agent/errand_risk.py (Python frozenset) and
apps/server/src/errand_risk.ts (TS Set) — because the two-language split forbids
shared code. This guard reads the TS source and asserts its blocked-combo set
equals the Python one, so a drift on either side fails CI instead of silently
diverging (closes the dual-hand-maintained-pin gap).
"""

from __future__ import annotations

import re
from pathlib import Path

from errand_risk import BLOCKED_DANGER_COMBOS

_ERRAND_RISK_TS = Path(__file__).parents[2] / "server" / "src" / "errand_risk.ts"

# Match the `BLOCKED_DANGER_COMBOS = new Set([ ... ])` block, then pull every
# "<danger>|<errand>" token from it. Tolerant of whitespace, newlines, and a
# trailing comma — a benign reformat must not false-fail this guard.
_BLOCK_RE = re.compile(r"BLOCKED_DANGER_COMBOS[^=]*=\s*new Set\(\[(.*?)\]", re.DOTALL)
_TOKEN_RE = re.compile(r'"([a-z_]+\|[a-z_]+)"')


def _ts_blocked_combos() -> frozenset[str]:
    source = _ERRAND_RISK_TS.read_text()
    block = _BLOCK_RE.search(source)
    assert block is not None, f"could not locate BLOCKED_DANGER_COMBOS Set block in {_ERRAND_RISK_TS}"
    tokens = frozenset(_TOKEN_RE.findall(block.group(1)))
    # Fail loud on a parse miss rather than passing vacuously against an empty set.
    assert tokens, f"extracted no blocked-combo tokens from {_ERRAND_RISK_TS} — parser drift?"
    return tokens


def test_blocked_danger_combos_match_across_languages():
    """The TS BLOCKED_DANGER_COMBOS must equal the Python frozenset."""
    assert _ts_blocked_combos() == BLOCKED_DANGER_COMBOS


def test_extractor_finds_the_expected_count():
    """Guards the guard: the TS source must yield the 4 spec N/A cells."""
    assert len(_ts_blocked_combos()) == len(BLOCKED_DANGER_COMBOS) == 4
