"""M4.8 story-004: Bless spell producer — apply Blessed on cast.

Stories 001-003 built the CONSUMER side (BonusDie model, +1d4 fold, consume-on-roll). This
story is the PRODUCER: a spell whose catalog row carries a structured `applies_condition`
lands that condition on the cast's target. Single-target (multi-target is story-007). Both
paths wired (customer decision story-004-in-combat-scope):

- A) catalog schema: Spell.applies_condition, parsed + fail-loud validated against the
     condition catalog.
- B) out-of-combat producer: _resolve_cast applies + persists the condition to the target's
     players.data SSOT (gated on not session.in_combat) and surfaces it in the cast packet.
- C) in-combat producer: _resolve_one_packet applies the produced condition to the target
     CombatParticipant on the working state (rides save_combat_state).
"""

import pytest

from spells import parse_spell_row

# A divine_bless-shaped catalog row carrying the new structured producer field. Mirrors the
# strict M3.3 row shape (resonance_by_source/terrain_effects/audio_cue/concentration required).
_BLESS_ROW = {
    "id": "divine_bless",
    "name": "Bless",
    "source": "divine",
    "spell_tier": "minor",
    "focus_cost": 2,
    "mechanics": "An ally gains +1d4 on attacks and saves. Concentration.",
    "narration_cue": "You speak their name and your patron hears — warmth settling into bones.",
    "resonance_by_source": {"divine": 1},
    "terrain_effects": {},
    "audio_cue": "",
    "concentration": True,
}


# --- Group A: catalog schema (pure parse) ---


def test_parse_carries_applies_condition():
    spell = parse_spell_row("divine_bless", {**_BLESS_ROW, "applies_condition": "blessed"})
    assert spell.applies_condition == "blessed"


def test_parse_without_applies_condition_defaults_none():
    # Existing spells (no producer field) parse with applies_condition None — no condition produced.
    spell = parse_spell_row(
        "arcane_bolt", {**_BLESS_ROW, "id": "arcane_bolt", "source": "arcane", "resonance_by_source": {"arcane": 0}}
    )
    assert spell.applies_condition is None


def test_parse_unknown_applies_condition_fails_loud():
    # Strict-loader convention: a typo'd / unknown condition type fails at parse, naming the row.
    with pytest.raises(ValueError, match="applies_condition"):
        parse_spell_row("divine_bless", {**_BLESS_ROW, "applies_condition": "not_a_condition"})
