"""Pure per-cast composition of catalog/formula generation, racial contact and wards."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING

from spells import Spell
from terrain import is_earth_or_stone, resonance_base

if TYPE_CHECKING:
    from hollow_echo import HollowEchoResult


def compute_generated_resonance(spell: Spell, race: str | None, *, terrain: str | None, resonance, racial_mod) -> int:
    """Scale primal catalog generation by terrain, then apply Korath before ward halving.

    Catalog values preserve spell-specific tuning; the Focus formula serves in-code builds
    without a catalog entry. Decimal arithmetic preserves half-up ties such as farmland's 1.5.
    """
    base = resonance_base(terrain) if spell.source == "primal" else None  # type: ignore[arg-type]
    generated = spell.resonance_by_source.get(spell.source)
    if generated is None:
        generated = resonance.calculate_resonance_generated(spell.focus_cost, spell.source, terrain=terrain)
    elif base is not None:
        generated = int(
            (Decimal(generated) * Decimal(str(base)) / Decimal("0.2")).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        )

    if race == "korath" and spell.source == "primal" and is_earth_or_stone(terrain) and generated > 0:  # type: ignore[arg-type]
        reduction = racial_mod.get_racial_resonance_modifier("korath", "primal_reduction")
        generated = resonance.apply_primal_reduction(generated, reduction)
    return generated


def compute_effective_resonance(
    generated: int, current_resonance: int, race: str | None, in_combat: bool, *, resonance, racial_mod
) -> int:
    """The post-cast Resonance total: shed one round of standing decay, then accrue this cast.

    Per-round decay is cast-paced (story-010): a real cast first sheds one round of standing
    Resonance — base 1/round, +1 for a Human (Adaptive Resonance) => 2/round — before this cast's
    generation lands. ``apply_resonance_decay`` floors at 0. A cantrip (``generated`` 0) skips decay
    entirely, leaving the standing value untouched.

    IN COMBAT the cast-paced shed is SUPPRESSED (story-007): the phase WRAP beat is the canonical
    decay clock (decision resonance-decay-phase-canonical), so an in-combat cast only GENERATES.
    """
    should_decay = generated > 0 and not in_combat
    decay_modifier = 0
    if race == "human":
        decay_modifier = racial_mod.get_racial_resonance_modifier("human", "decay_bonus")
    base_resonance = (
        resonance.apply_resonance_decay(current_resonance, decay_modifier) if should_decay else current_resonance
    )
    return base_resonance + generated


def apply_ward_halving(generated: int, ward_active: bool, *, veil_ward) -> int:
    """Halve generated Resonance (round down) under an active Veil Ward; Focus cost is not halved.

    spec magic.md:197. The ``generated > 0`` guard is load-bearing beyond the arithmetic: it keeps a
    cantrip (or a Korath cast floored to 0) out of the caller's resonance-write and HUD-push gates.
    """
    if ward_active and generated > 0:
        return veil_ward.halve_generation(generated)
    return generated


def ward_combat_modifiers(state: str, ward_active: bool, *, resonance, veil_ward) -> dict[str, int]:
    """The state's net combat modifiers, with an active ward's -1 damage die / -1 DC folded in.

    spec magic.md:199-200. ``get_state_modifiers`` returns a fresh dict, so folding the penalty in
    never mutates the shared modifier table.
    """
    modifiers = resonance.get_state_modifiers(state)
    if ward_active:
        modifiers["damage_dice"] += veil_ward.WARD_DAMAGE_DIE_PENALTY
        modifiers["dc"] += veil_ward.WARD_DC_PENALTY
    return modifiers


def resolve_overreach_echo(
    effective_resonance: int,
    race: str | None,
    ward_active: bool,
    *,
    dice_mod,
    hollow_echo,
    veil_ward,
    racial_mod,
) -> tuple[HollowEchoResult, bool]:
    """Roll and resolve the Overreach Hollow Echo. Returns ``(echo, vaelti_warned)``.

    At Overreach the Veil tears: auto-roll a d20 (spec magic.md:167-185). An active ward adds +4 to
    the roll (a milder result). The echo resolves against the caller's LOCAL ``effective_resonance``,
    never the unsynced session value.

    Vaelti Hyper-awareness (spec 246-252): advantage on the save — a SECOND d20, take the better, so
    the base roll is drawn first and the advantage roll second (existing dice mocks feed a sequence
    and depend on that order). ``vaelti_warned`` is returned rather than published here, because the
    1-round advance-warning event closes over ``session``, which this pure layer never sees.
    """
    roll = dice_mod.roll("d20").total
    advantage_roll = None
    vaelti_warned = False
    if race == "vaelti" and racial_mod.get_racial_resonance_modifier("vaelti", "echo_save_advantage"):
        advantage_roll = dice_mod.roll("d20").total
        vaelti_warned = True
    echo = hollow_echo.resolve_hollow_echo(
        roll,
        effective_resonance,
        ward_bonus=veil_ward.WARD_ECHO_BONUS if ward_active else 0,
        advantage_roll=advantage_roll,
    )
    return echo, vaelti_warned
