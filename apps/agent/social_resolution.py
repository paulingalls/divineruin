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


# Disposition shift on success/failure by social skill and outcome band (spec L678-685).
# The band derives from the check margin (roll_total - dc): success widens the gain,
# failure widens the loss. Persuasion builds the most goodwill; Deception never wins more
# than +1; Intimidation's double edge penalizes bare success and every failure (L687).
DISPOSITION_SHIFT: dict[str, dict[str, int]] = {
    "persuasion": {"success_10": 2, "success_5": 1, "success_bare": 0, "fail_4": 0, "fail_5": -1, "fail_10": -2},
    "deception": {"success_10": 1, "success_5": 1, "success_bare": 0, "fail_4": 0, "fail_5": -1, "fail_10": -2},
    "intimidation": {"success_10": 1, "success_5": 0, "success_bare": -1, "fail_4": -1, "fail_5": -2, "fail_10": -2},
}


def _outcome_band(margin: int) -> str:
    """Map a check margin (roll_total - dc) to a DISPOSITION_SHIFT band. Boundaries inclusive
    toward the higher-magnitude band: +10/+5/0/-5/-10 each land in the stronger tier."""
    if margin >= 10:
        return "success_10"
    if margin >= 5:
        return "success_5"
    if margin >= 0:
        return "success_bare"
    if margin >= -4:
        return "fail_4"
    if margin >= -9:
        return "fail_5"
    return "fail_10"


def disposition_shift(skill: str, margin: int) -> int:
    """Return the disposition delta for a social `skill` resolved at `margin` (spec L678-685).

    Fail loud for a skill outside the three social skills — only Persuasion/Deception/
    Intimidation shift disposition, and routing any other skill here is a caller bug.
    """
    try:
        bands = DISPOSITION_SHIFT[skill]
    except KeyError:
        raise ValueError(f"unknown social skill {skill!r}; expected one of {tuple(DISPOSITION_SHIFT)}") from None
    return bands[_outcome_band(margin)]
