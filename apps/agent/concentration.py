"""Concentration rules engine (story-002, M3.4) — pure, no IO.

Some spells require concentration to sustain (the ``concentration`` flag on every catalog
row, spells.py:Spell.concentration). When a concentrating caster takes damage they make a
Constitution saving throw or the spell ends; an incapacitated caster auto-fails. A caster
holds only ONE concentration spell at a time — starting a second ends the first. Like the
Resonance / Hollow Echo / Veil Ward engines this is a deterministic mechanic (CLAUDE.md
golden rule #3): the LLM decides *when* a spell is cast and rolls the save through the dice
tool; this module only computes the DC.

Every function reads and returns plain ints/bools and never mutates its input.

Spec source: docs/milestones/03_magic.md §Milestone 3.4 — DC = max(10, damage // 2),
incapacitation auto-fails. The save roll itself is the caller's (story-006 supplies the CON
save total from the dice tool); this engine never rolls. The single-concentration enforcement
and the persisted active spell id live in the cast path (story-006) + db_mutations_concentration,
not here.

Consumer (later): M3.4 cast_spell (story-006) sets/ends the concentration spell and, when a
concentrating caster is damaged, calls check_concentration(damage); the CON save's own verdict decides
the break (natural 1 fails, natural 20 holds, else total >= DC).
"""

# Floor for the concentration save DC (spec): a small hit still demands at least a DC-10 save.
_MIN_CONCENTRATION_DC = 10


def check_concentration(damage: int) -> int:
    """Return the Constitution save DC to maintain concentration after taking ``damage``.

    DC = max(10, damage // 2) (spec 03_magic.md §M3.4). Fails loud on negative damage —
    damage is always non-negative.
    """
    if damage < 0:
        raise ValueError(f"damage must be non-negative, got {damage}")
    return max(_MIN_CONCENTRATION_DC, damage // 2)
