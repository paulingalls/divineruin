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
    spell_id: str | None = None
    elapsed_seconds: int = 0
    combat_id: str | None = None
    started_round: int | None = None

    @property
    def is_active(self) -> bool:
        return self.spell_id is not None

    @classmethod
    def from_record(cls, record: dict | None) -> ConcentrationState:
        if record is None or record["spell_id"] is None:
            return cls()
        elapsed = record["elapsed_seconds"]
        if type(elapsed) is not int or elapsed < 0:
            raise ValueError("Invalid concentration elapsed_seconds")
        combat_id, started_round = record.get("combat_id"), record.get("started_round")
        if (combat_id, started_round) != (None, None) and (
            not isinstance(combat_id, str) or type(started_round) is not int or started_round < 1
        ):
            raise ValueError("Invalid concentration combat origin")
        return cls(record["spell_id"], elapsed, combat_id, started_round)
