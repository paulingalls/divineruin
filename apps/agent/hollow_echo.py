"""Hollow Echo rules engine (story-001, M3.2) — pure, no IO.

The Hollow Echo is the consequence the Veil exacts when a caster casts at Overreach
(Resonance 9+): a d20 is rolled and mapped to one of seven bands, from a clean
"Nothing stirs" down to a "Breach" that tears the Veil open. It is a deterministic
mechanic (CLAUDE.md golden rule #3): the LLM decides *when* a spell is cast and *how*
to narrate the strain; this module only resolves the roll to a band. The seven bands
and the two high-Resonance modifiers are a small closed table, so they live as code
constants (same call as the Resonance engine) rather than DB-loaded content.

resolve_hollow_echo returns the band id, its display name, and a mechanical-effect
descriptor. The secondary mechanical follow-through (1d4 psychic for Sympathetic,
doubled Focus for Reality fracture, 1-3 Hollow creatures for Breach) is DM/follow-up,
NOT auto-applied here — the descriptor tells the DM what to narrate and resolve.

Spec source: docs/game_mechanics/game_mechanics_magic.md §Hollow Echo Table (167-185):
rolled on a d20 at Resonance 9+; at Resonance 12+ subtract 3, at 15+ subtract 6; the
effective roll maps to 17-20 Nothing / 14-16 Whisper / 11-13 Veil scar /
8-10 Sympathetic / 5-7 Hollow attention / 2-4 Reality fracture / <=1 Breach.

Veil Ward (spec magic.md:198): while a ward is active it adds +4 to the Hollow Echo
roll, shifting results milder. That bonus is a parameter here (ward_bonus) rather than
pre-added by the caller, so the raw d20 stays validatable as 1-20 and the full roll ->
band transformation lives in this one closed table.

Consumer: M3.2 cast_spell rolls a d20 at Overreach and passes it here with the post-cast
Resonance and ward_bonus=4 when a Veil Ward is active (else the default 0).
"""

from dataclasses import dataclass

# Resonance at which the Hollow Echo is rolled (spec 169). Calling below this is a
# misuse — the cast path only rolls at Overreach.
OVERREACH_THRESHOLD = 9


@dataclass(frozen=True)
class HollowEchoResult:
    """The resolved Hollow Echo: which band, its display name, and what the DM narrates."""

    band: str
    name: str
    effect: str
    effective_roll: int


# Effective-roll floor (inclusive) -> (band id, display name, mechanical descriptor),
# highest first. The first floor the effective roll meets or exceeds wins; Breach is the
# catch-all below 2 (spec "1 or less"). Descriptors paraphrase magic.md:171-179.
_BANDS: tuple[tuple[int, str, str, str], ...] = (
    (17, "nothing", "Nothing stirs", "No side effect. The spell resolves cleanly."),
    (14, "whisper", "Whisper", "No mechanical effect; the DM plants a narrative seed."),
    (11, "veil_scar", "Veil scar", "A patch of wrongness lingers where the spell was cast, persisting 1 hour."),
    (8, "sympathetic", "Sympathetic resonance", "One random ally within earshot takes 1d4 psychic damage."),
    (
        5,
        "hollow_attention",
        "Hollow attention",
        "The caster gains stage 1 Hollowed (disadvantage on WIS checks until a short rest).",
    ),
    (
        2,
        "reality_fracture",
        "Reality fracture",
        "The spell effect is doubled, but its Focus cost is retroactively doubled.",
    ),
)
_BREACH = ("breach", "Breach", "1-3 minor Hollow creatures manifest at the spell's location within 1d4 rounds.")


def resolve_hollow_echo(
    d20_roll: int, resonance: int, ward_bonus: int = 0, advantage_roll: int | None = None
) -> HollowEchoResult:
    """Resolve a Hollow Echo for a d20 roll at the given post-cast Resonance.

    advantage_roll is the second d20 for Vaelti Hyper-awareness (spec magic.md:246-252):
    when supplied, the base roll is max(d20_roll, advantage_roll) — advantage takes the higher
    roll, which maps to a milder band (the same "shift milder" direction as ward_bonus). The
    engine never rolls; the caller supplies both rolls (story-006 rolls the second only for a
    Vaelti, gated on the echo_save_advantage racial modifier). When None, the single d20_roll
    is used unchanged.

    Adds the Veil Ward bonus (ward_bonus, +4 while a ward is active — spec magic.md:198,
    shifts results milder), then applies the high-Resonance modifier (subtract 3 at 12+,
    subtract 6 at 15+ — the larger wins, they do not stack), and maps the effective roll
    to its band. Fails loud if called below Overreach (the cast path only rolls at 9+),
    if either roll is outside 1-20, or if ward_bonus is negative.
    """
    if resonance < OVERREACH_THRESHOLD:
        raise ValueError(f"Hollow Echo is only rolled at Overreach ({OVERREACH_THRESHOLD}+), got resonance {resonance}")
    if not 1 <= d20_roll <= 20:
        raise ValueError(f"d20_roll must be in 1-20, got {d20_roll}")
    if ward_bonus < 0:
        raise ValueError(f"ward_bonus must be non-negative, got {ward_bonus}")

    base_roll = d20_roll
    if advantage_roll is not None:
        if not 1 <= advantage_roll <= 20:
            raise ValueError(f"advantage_roll must be in 1-20, got {advantage_roll}")
        base_roll = max(d20_roll, advantage_roll)  # advantage: best of two -> milder band

    if resonance >= 15:
        modifier = 6
    elif resonance >= 12:
        modifier = 3
    else:
        modifier = 0
    effective_roll = base_roll + ward_bonus - modifier

    for floor, band, name, effect in _BANDS:
        if effective_roll >= floor:
            return HollowEchoResult(band=band, name=name, effect=effect, effective_roll=effective_roll)
    band, name, effect = _BREACH
    return HollowEchoResult(band=band, name=name, effect=effect, effective_roll=effective_roll)
