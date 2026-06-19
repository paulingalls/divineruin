"""Pure dramatic-dice evaluator (M4.5).

The visible dice roll — HUD animation, audio cue, DM pause — is the game's most
powerful tension tool, and its power comes from scarcity: in a typical 5-phase
fight the player should see dramatic dice 0-2 times. This module is the single
deterministic classifier that decides, for one roll, whether it is dramatic and
why. It is pure: it reads only the explicit signals on ``DramaticContext`` (which
emission sites assemble) and never touches IO, RNG, DB, or combat state.

Catalog and ordering mirror docs/game_mechanics/game_mechanics_combat.md
§Dramatic Dice (L15-75).
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class DramaticContext:
    """Explicit roll signals assembled by an emission site for one roll.

    Every field defaults so a caller supplies only what its roll surfaces; an
    absent signal simply never satisfies its predicate.
    """

    raw_die: int | None = None
    roll_type: str | None = None
    attacker_tier: int | None = None
    ability: str | None = None
    damage_taken: int | None = None
    target_hp_remaining: int | None = None
    damage_potential: int | None = None
    player_hp_percent: float | None = None
    is_first_attack_of_combat: bool = False
    enemies_remaining: int | None = None
    margin: int | None = None
    social_stakes: str | None = None


@dataclass(frozen=True)
class DramaticVerdict:
    """Whether a roll is dramatic, and the reason label when it is ("" otherwise)."""

    dramatic: bool
    context: str


def evaluate_dramatic_context(ctx: DramaticContext) -> DramaticVerdict:
    """Classify one roll against the dramatic-dice catalog.

    Predicates are checked in catalog (severity) order; the first match wins, so
    a roll that satisfies several reasons surfaces the highest-severity label.
    A roll matching no predicate is never dramatic.
    """
    # Always dramatic — engine flags automatically, regardless of context.
    if ctx.raw_die == 20:
        return DramaticVerdict(True, "natural_20")
    if ctx.raw_die == 1:
        return DramaticVerdict(True, "natural_1")
    if ctx.roll_type == "death_save":
        return DramaticVerdict(True, "death_save")
    if ctx.attacker_tier == 4:  # Named/boss striking the player directly
        return DramaticVerdict(True, "boss_attack")
    if ctx.ability == "counterspell":
        return DramaticVerdict(True, "counterspell")
    if ctx.ability == "de_escalate":
        return DramaticVerdict(True, "de_escalate")
    if ctx.roll_type == "concentration" and ctx.damage_taken is not None and ctx.damage_taken >= 15:
        return DramaticVerdict(True, "concentration_major_damage")

    # Contextually dramatic — engine evaluates; any true flags the roll.
    if (
        ctx.target_hp_remaining is not None
        and ctx.damage_potential is not None
        and ctx.target_hp_remaining <= ctx.damage_potential
    ):
        return DramaticVerdict(True, "killing_blow")
    if ctx.roll_type == "defense" and ctx.player_hp_percent is not None and ctx.player_hp_percent <= 0.25:
        return DramaticVerdict(True, "player_near_death")
    if ctx.is_first_attack_of_combat:
        return DramaticVerdict(True, "first_attack")
    if ctx.roll_type == "attack" and ctx.enemies_remaining == 1:
        return DramaticVerdict(True, "last_enemy")
    if ctx.margin is not None and abs(ctx.margin) <= 1:
        return DramaticVerdict(True, "razor_thin")
    if ctx.social_stakes == "high":
        return DramaticVerdict(True, "high_stakes_social")

    return DramaticVerdict(False, "")
