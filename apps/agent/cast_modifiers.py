"""Pure per-cast composition: what a cast generates, and what the Veil Ward does to it.

Extracted from ``spell_casting._resolve_cast`` (M24 story-006), which had grown past the
500-line cap. Nothing here touches a ``conn`` or a ``session``: the async ward READ stays in
``_resolve_cast`` (it needs both), and what lives here is what the cast does with the answer.
Every function takes the caller's already-injected engine modules, so ``_resolve_cast``'s
DI seams flow straight through and its existing mocks still reach this code.

Framework-free, like ``veil_ward`` / ``hollow_echo`` / ``resonance``: these raise ``ValueError``
and the tool layer converts to ``ToolError`` at the call site.

The engines are reused, never reimplemented — ``veil_ward.halve_generation`` and the three
ward effect constants are the SSOT for ward cast-time effects, and ``hollow_echo`` remains a
narrow single-mechanic resolver that knows nothing of races, dice, or wards. This module is
the cross-engine composition layer that wires them together for one cast.

M3.4 racial Resonance: the cast reads the caster's race (players.data) and composes three
prior pure primitives — Korath -1 primal generation (``resonance.apply_primal_reduction``),
the Thessyn +1 Flickering threshold (``get_resonance_state`` flickering_bonus, applied by the
caller), and the Vaelti Hollow Echo advantage (``resolve_hollow_echo`` advantage_roll). The
engines stay untouched; this is pure composition.

Terrain note: every catalog spell (primal included) carries a designed ``resonance_by_source``
baseline, so casts no longer depend on terrain. The fallback formula
(``calculate_resonance_generated``) only reaches the terrain lookup for an in-code primal build
carrying no ``resonance_by_source`` entry, and since no runtime location->terrain map exists yet
(terrain defaults to "normal"), that one path still fails loud until terrain wiring lands. The
same missing map means the Korath -1 (spec gates it on earth/stone contact) applies on
race+source alone — terrain gating is deferred, not modelled here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from spells import Spell

if TYPE_CHECKING:
    from hollow_echo import HollowEchoResult

# Default terrain for resonance generation. Only consulted for PRIMAL non-cantrips
# (see module docstring); a real location->terrain map is M3.4 work.
_DEFAULT_TERRAIN = "normal"


def compute_generated_resonance(spell: Spell, race: str | None, *, resonance, racial_mod) -> int:
    """Resonance this cast generates: the catalog's designed value, else the formula, then Korath.

    The catalog's per-spell ``resonance_by_source`` is the SSOT (decision resonance-by-source-ssot):
    a subset of spells intentionally deviate from the source*focus formula — power spells tear the
    Veil harder, gentle ones less. The formula is the fallback only when a spell carries no entry
    for its source (in-code builds; every catalog row has one), which is also where a
    primal-without-terrain build fails loud.

    Korath Earth-anchored (spec 254-260): a Korath's primal cast generates -1 Resonance (floor 0),
    the earth absorbing the Veil disturbance. Applied to the BASE generation — before the ward
    halving, which the caller applies after resolving the ward — and before accrual, so a floored 0
    flows through the caller's ``generated > 0`` write/publish gates (no resonance write, no HUD push).
    """
    generated = spell.resonance_by_source.get(spell.source)
    if generated is None:
        generated = resonance.calculate_resonance_generated(spell.focus_cost, spell.source, terrain=_DEFAULT_TERRAIN)

    if race == "korath" and spell.source == "primal" and generated > 0:
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
