"""Social encounter resolution — pure 3-tier engine (M4.6a / story-001). Zero IO, zero RNG.

Turns an NPC disposition plus a caller-supplied skill-check total into a social outcome:
the DC derives from disposition (friendlier NPCs are easier), the result carries a margin,
a dramatic-dice verdict (routed through the M4.5 dramatic.py SSOT), a narration cue, and a
disposition shift. The caller rolls the d20 + skill modifier — this module never touches
RNG, the DB, or combat state, mirroring check_resolution.py.

Spec: docs/game_mechanics/game_mechanics_combat.md §Social Encounter Resolution (L619-844).
"""

from role_archetypes import DISPOSITIONS

# Social DC modifier by NPC disposition (spec L668): a friendlier NPC is easier to persuade,
# so the modifier shrinks (and goes negative) up the ladder. Added to the caller's base DC.
DISPOSITION_DC_MODIFIER: dict[str, int] = {
    "hostile": 6,
    "unfriendly": 3,
    "neutral": 0,
    "friendly": -3,
    "trusted": -6,
}


def social_dc_modifier(disposition: str) -> int:
    """Return the DC adjustment for `disposition` (spec L668). Fail loud off the ladder.

    Positive = harder (hostile +6), negative = easier (trusted -6). Raises ValueError for a
    disposition not on the canonical DISPOSITIONS ladder rather than silently defaulting —
    an unknown disposition is a content/caller bug, not a neutral interaction.
    """
    try:
        return DISPOSITION_DC_MODIFIER[disposition]
    except KeyError:
        raise ValueError(f"unknown disposition {disposition!r}; expected one of {DISPOSITIONS}") from None
