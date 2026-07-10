"""Caster state value types (extracted from session_data to break import cycles).

These three dataclasses are the per-player sub-state containers used by both
SessionData (single-player) and PartyState (multi-player). Extracting them into
a leaf module (imports only resonance, NOT session_data) prevents a cycle:
- session_data imports caster_state for back-compat re-export
- party_state imports caster_state
- session_data does NOT import party_state
"""

from __future__ import annotations

from dataclasses import dataclass

import resonance


@dataclass
class ResonanceTrack:
    """Per-caster Resonance carried in the session (story-003, M3.1).

    Only ``current`` (the authoritative int) is stored; the stable/flickering/
    overreach STATE is always derived via resonance.get_resonance_state — single
    source of truth, no cached copy to drift (same discipline as the companion
    HYBRID tier above and the players.data persistence in db_mutations_resonance).
    Defaults to current 0 -> "stable".

    ``flickering_bonus`` (Thessyn Deep Adaptation, M3.4) shifts the band thresholds
    up; it is a per-caster constant set once from the player's race (story-006), so
    EVERY derivation of ``state`` — the packet, the HUD push (publish_resonance_changed),
    the cast path — reads the same single value and cannot diverge. Defaults to 0
    (the canonical band) for non-Thessyn casters.
    """

    current: int = 0
    flickering_bonus: int = 0

    @property
    def state(self) -> resonance.ResState:
        return resonance.get_resonance_state(self.current, flickering_bonus=self.flickering_bonus)


@dataclass
class ConcentrationState:
    """Per-caster spell concentration carried in the session (story-002, M3.4).

    A caster sustains at most ONE concentration spell at a time; ``spell_id`` is that spell
    (None = not concentrating). The cast keystone (story-006) sets it on a concentration cast
    and ends any prior one (single-concentration enforcement), persisted via
    db_mutations_concentration. Like ResonanceTrack, only the authoritative id
    is stored — ``is_active`` is always derived, no cached flag to drift. Defaults to inactive.
    """

    spell_id: str | None = None

    @property
    def is_active(self) -> bool:
        return self.spell_id is not None
