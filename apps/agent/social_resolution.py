"""Social encounter resolution — pure 3-tier engine (M4.6a / story-001). Zero IO, zero RNG.

Turns an NPC disposition plus a caller-supplied skill-check total into a social outcome:
the DC derives from disposition (friendlier NPCs are easier), the result carries a margin,
a dramatic-dice verdict (routed through the M4.5 dramatic.py SSOT), a narration cue, and a
disposition shift. The caller rolls the d20 + skill modifier — this module never touches
RNG, the DB, or combat state, mirroring check_resolution.py.

Spec: docs/game_mechanics/game_mechanics_combat.md §Social Encounter Resolution (L619-844).
"""

from dataclasses import dataclass

from dramatic import DramaticContext, evaluate_dramatic_context
from role_archetypes import DISPOSITIONS, shift_disposition

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


# Canonical argument categories a player can make in a Tier-3 structured scene (spec L768-777).
ARGUMENT_TYPES: tuple[str, ...] = ("reason", "emotion", "self_interest", "threat", "bluff", "evidence")

# NPC resistance personality (spec L783-791): each tag makes some argument categories land
# harder (resistant) or softer (vulnerable). Mapped onto the canonical ARGUMENT_TYPES so a
# matching argument eases the DC and a resisted one stiffens it. story-003 tags NPC content
# against these keys.
ARGUMENT_RESISTANCE: dict[str, dict[str, tuple[str, ...]]] = {
    "pragmatic": {"vulnerable": ("self_interest", "reason", "evidence"), "resistant": ("emotion", "threat")},
    "emotional": {"vulnerable": ("emotion",), "resistant": ("reason", "threat")},
    "suspicious": {"vulnerable": ("evidence",), "resistant": ("reason", "emotion", "self_interest", "threat", "bluff")},
    "cowardly": {"vulnerable": ("threat",), "resistant": ()},
    "devout": {"vulnerable": (), "resistant": ("threat",)},
    "greedy": {"vulnerable": ("self_interest",), "resistant": ("emotion",)},
    "honorable": {"vulnerable": ("reason", "evidence"), "resistant": ("bluff", "threat")},
}

# The canonical personality tags an NPC may carry — the SSOT for content validation
# (npcs.py) so the authored resistance_tags can't drift from the resolver's keys.
RESISTANCE_TAGS: tuple[str, ...] = tuple(ARGUMENT_RESISTANCE)

# One disposition-tier of DC swing per vulnerable/resistant match — the spec pins direction,
# not magnitude, so this mirrors the ±3 granularity of the disposition modifier.
_ARGUMENT_DC_STEP = 3


def argument_dc_adjust(argument_type: str | None, resistance_tags: tuple[str, ...]) -> int:
    """DC swing for a Tier-3 argument against an NPC's resistance tags (spec L783-791).

    `None` argument (a Tier-1 simple check) is always neutral. A vulnerable match eases the DC
    (negative), a resistant match stiffens it (positive); an NPC carrying conflicting tags nets
    out. Fail loud on an argument category or personality tag outside the canonical sets.
    """
    if argument_type is None:
        return 0
    if argument_type not in ARGUMENT_TYPES:
        raise ValueError(f"unknown argument type {argument_type!r}; expected one of {ARGUMENT_TYPES}")
    adjust = 0
    for tag in resistance_tags:
        try:
            profile = ARGUMENT_RESISTANCE[tag]
        except KeyError:
            raise ValueError(f"unknown personality tag {tag!r}; expected one of {tuple(ARGUMENT_RESISTANCE)}") from None
        if argument_type in profile["vulnerable"]:
            adjust -= _ARGUMENT_DC_STEP
        if argument_type in profile["resistant"]:
            adjust += _ARGUMENT_DC_STEP
    return adjust


# Narration cue by outcome band (spec get_social_hint, L661): a short qualitative word the DM
# voices instead of a number. Distinct from rules_engine.narrative_hint (skill-check vocab).
_SOCIAL_CUE: dict[str, str] = {
    "success_10": "overwhelming",
    "success_5": "convincing",
    "success_bare": "barely",
    "fail_4": "close but no",
    "fail_5": "rejected",
    "fail_10": "backfired",
}


@dataclass(frozen=True)
class SocialResult:
    """Outcome of one Tier-1 social check. `dramatic`/`context` come from the M4.5 SSOT;
    `disposition_shift` is the delta and `new_disposition` is it applied + ladder-clamped."""

    success: bool
    dc: int
    margin: int
    dramatic: bool
    context: str
    narrative_cue: str
    disposition_shift: int
    new_disposition: str


def resolve_social_check(
    *,
    disposition: str,
    skill: str,
    roll_total: int,
    base_dc: int,
    argument_type: str | None = None,
    resistance_tags: tuple[str, ...] = (),
    stakes: str = "normal",
) -> SocialResult:
    """Resolve a social check (spec L636-687). Pure: the caller supplies `roll_total`
    (d20 + skill modifier) and the `base_dc`; the NPC disposition modifies the DC.

    Tier 1 leaves `argument_type=None`. Tier 3 passes a structured argument category plus the
    NPC's `resistance_tags`, which further shift the DC (argument_dc_adjust): a favored argument
    is easier, a resisted one harder. `stakes="high"` flags the roll dramatic regardless of
    margin (a faction leader, a critical secret). The dramatic verdict and its label are
    delegated to dramatic.evaluate_dramatic_context so the M4.5 catalog stays the single source
    of truth. Raises ValueError for an off-ladder disposition, a non-social skill, or an unknown
    argument category / personality tag.
    """
    dc = base_dc + social_dc_modifier(disposition) + argument_dc_adjust(argument_type, resistance_tags)
    margin = roll_total - dc
    success = roll_total >= dc
    delta = disposition_shift(skill, margin)
    verdict = evaluate_dramatic_context(DramaticContext(margin=margin, social_stakes=stakes))
    return SocialResult(
        success=success,
        dc=dc,
        margin=margin,
        dramatic=verdict.dramatic,
        context=verdict.context,
        narrative_cue=_SOCIAL_CUE[_outcome_band(margin)],
        disposition_shift=delta,
        new_disposition=shift_disposition(disposition, delta),
    )


# Failure consequence by contested skill and loss band (spec L724-729). A contested exchange
# is player-skill vs NPC-resist-skill; on a loss the NPC reacts differently per skill, and a
# wide loss (5+) bites harder than a narrow one. Insight is a contested-only skill (reading
# motives) and never appears in DISPOSITION_SHIFT.
CONTESTED_CONSEQUENCE: dict[str, dict[str, str]] = {
    "deception": {
        "failed_4": "NPC doesn't believe you, but suspects no malice",
        "failed_5": "NPC realizes you lied — trust broken, may turn hostile",
    },
    "insight": {
        "failed_4": "You misread the NPC and act on incorrect information",
        "failed_5": "You misread badly — a convincing but wrong read you act on",
    },
    "persuasion": {
        "failed_4": "NPC declines firmly; no disposition change",
        "failed_5": "NPC feels manipulated and won't engage on this again",
    },
    "intimidation": {
        "failed_4": "NPC stands firm and calls your bluff",
        "failed_5": "NPC turns hostile and may attack",
    },
}

# Qualitative cue for a contested exchange, keyed off the win/loss margin (player - npc).
_CONTESTED_CUE: tuple[tuple[int, str], ...] = (
    (5, "decisive"),
    (1, "edged out"),
    (0, "stalemate"),
    (-4, "outmatched"),
)


@dataclass(frozen=True)
class ContestedResult:
    """Outcome of a Tier-2 contested exchange (player skill vs NPC resist skill). Always
    dramatic; `consequence` is the spec failure text on a loss, empty on a win."""

    success: bool
    margin: int
    dramatic: bool
    context: str
    narrative_cue: str
    consequence: str


def _contested_band(margin: int) -> str:
    """Loss band for a contested margin: a 5+ loss is the harsher tier; ties (margin 0) and
    1-4 losses share the milder tier (a tie goes to the NPC, so it is still a loss)."""
    return "failed_5" if margin <= -5 else "failed_4"


def _contested_cue(margin: int) -> str:
    for threshold, label in _CONTESTED_CUE:
        if margin >= threshold:
            return label
    return "overpowered"


def resolve_contested_social(*, skill: str, player_total: int, npc_total: int) -> ContestedResult:
    """Resolve a Tier-2 contested social exchange (spec L689-729). Pure: the caller supplies
    both totals (each d20 + the relevant skill modifier).

    The player must BEAT the NPC — a tie goes to the defender. Contested exchanges are always
    dramatic (delegated to the M4.5 SSOT via social_stakes="high"). On a loss the result carries
    the skill-specific consequence text; a win carries none. Raises ValueError for a skill
    outside the four contested skills.
    """
    if skill not in CONTESTED_CONSEQUENCE:
        raise ValueError(f"unknown contested skill {skill!r}; expected one of {tuple(CONTESTED_CONSEQUENCE)}")
    margin = player_total - npc_total
    success = player_total > npc_total
    verdict = evaluate_dramatic_context(DramaticContext(margin=margin, social_stakes="high"))
    consequence = "" if success else CONTESTED_CONSEQUENCE[skill][_contested_band(margin)]
    return ContestedResult(
        success=success,
        margin=margin,
        dramatic=verdict.dramatic,
        context=verdict.context,
        narrative_cue=_contested_cue(margin),
        consequence=consequence,
    )
