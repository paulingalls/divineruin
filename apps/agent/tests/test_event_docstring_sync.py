"""Cross-language docstring-sync guard for prose-mirrored wire contracts (closes c9ea2e4e2dd6, 5df958b79e8e).

A few event constants carry their packet shape as *prose* in both ``apps/agent/event_types.py``
and its ``apps/mobile/src/audio/event-types.ts`` mirror, rather than in the
``packages/shared/fixtures/event_wire.json`` fixture that ``test_wire_contract.py`` pins.
Prose has no serialization test behind it, so a field rename/drop on one side (e.g. dropping the
dead ``phase`` field, debt 67f0f0f9cc20, or the RESONANCE_CHANGED ``{state, current, max}`` ->
``{state}`` drift found reviewing c9ea) silently leaves the other stale — the gap concern
c9ea2e4e2dd6 flagged and 5df958b79e8e generalized after a live drift proved the class real.

This test *is* the single source of truth: ``_MIRRORED_PACKETS`` holds the canonical
``Packet: {...}`` spec per event, and both language files must contain it verbatim (after
comment-marker + whitespace normalization). Any one-sided edit — or an edit that touches only
the two files but not this canonical spec — goes red, forcing a deliberate three-place update
instead of shipping a blank HUD field.
"""

import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_PY_EVENT_TYPES = _REPO_ROOT / "apps" / "agent" / "event_types.py"
_TS_EVENT_TYPES = _REPO_ROOT / "apps" / "mobile" / "src" / "audio" / "event-types.ts"

# Canonical prose-mirrored packet contracts (SSOT). Each event's doc comment in BOTH
# event_types.py and event-types.ts must contain the exact ``Packet: {...}`` line below.
# Nested braces (COMBAT_UI_UPDATE) are compared as a plain substring, so nesting is fine.
_MIRRORED_PACKETS = {
    "COMBAT_UI_UPDATE": (
        "Packet: {round, combatants:[{id, name, isAlly, hpCurrent, hpMax, "
        "conditions:[{type, stacks, source}], isActive}]}"
    ),
    "CURRENCY_GAINED": "Packet: {player_id, amount, currency, source, new_balance}",
    "RESONANCE_CHANGED": "Packet: {state, caster_id}",
    "HOLLOW_ECHO_RESULT": "Packet: {band}",
    "VEIL_WARD_CHANGED": "Packet: {active}",
}


def _normalize(text: str) -> str:
    """Strip line-comment markers (# or //) and collapse all whitespace to single spaces."""
    no_markers = re.sub(r"(^|\n)[ \t]*(#|//)", " ", text)
    return re.sub(r"\s+", " ", no_markers).strip()


@pytest.mark.parametrize("event_name, packet_spec", sorted(_MIRRORED_PACKETS.items()))
def test_prose_mirrored_packet_present_in_both_languages(event_name: str, packet_spec: str) -> None:
    py_text = _normalize(_PY_EVENT_TYPES.read_text())
    ts_text = _normalize(_TS_EVENT_TYPES.read_text())
    assert packet_spec in py_text, (
        f"{event_name} packet contract missing/renamed in apps/agent/event_types.py — "
        f"expected the canonical line {packet_spec!r}. Update the doc comment and this test's "
        "_MIRRORED_PACKETS together."
    )
    assert packet_spec in ts_text, (
        f"{event_name} packet contract missing/renamed in apps/mobile/src/audio/event-types.ts — "
        f"expected the canonical line {packet_spec!r}. Update the doc comment and this test's "
        "_MIRRORED_PACKETS together."
    )
