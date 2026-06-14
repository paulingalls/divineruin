"""Concentration rules engine (story-002, M3.4) — pure, no IO.

Some spells require concentration to sustain (the ``concentration`` flag on every catalog
row, spells.py:Spell.concentration). When a concentrating caster takes damage they make a
Constitution saving throw or the spell ends; an incapacitated caster auto-fails. A caster
holds only ONE concentration spell at a time — starting a second ends the first. Like the
Resonance / Hollow Echo / Veil Ward engines this is a deterministic mechanic (CLAUDE.md
golden rule #3): the LLM decides *when* a spell is cast and rolls the save through the dice
tool; this module only computes the DC and resolves the roll.

Every function reads and returns plain ints/bools and never mutates its input.

Spec source: docs/milestones/03_magic.md §Milestone 3.4 — DC = max(10, damage // 2),
incapacitation auto-fails. The save roll itself is the caller's (story-006 supplies the CON
save total from the dice tool); this engine never rolls. The single-concentration enforcement
and the persisted active spell id live in the cast path (story-006) + db_mutations_concentration,
not here.

Consumer (later): M3.4 cast_spell (story-006) sets/ends the concentration spell and, when a
concentrating caster is damaged, calls check_concentration(damage) then concentration_holds.
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


def concentration_holds(save_total: int, dc: int, incapacitated: bool = False) -> bool:
    """Return whether concentration is maintained for a CON save total against ``dc``.

    An incapacitated caster auto-fails regardless of the roll (spec) — this short-circuits
    first, so the save total is never consulted (an incapacitated caster needs no valid roll).
    Otherwise the save succeeds (and concentration holds) when save_total meets or exceeds the
    DC. The save total is supplied by the caller (the dice tool); this function never rolls.
    Fails loud on a negative save_total on the comparison path — a CON save total is never
    negative; validated where it's used, symmetric with check_concentration's damage guard.
    """
    if incapacitated:
        return False
    if save_total < 0:
        raise ValueError(f"save_total must be non-negative, got {save_total}")
    return save_total >= dc
