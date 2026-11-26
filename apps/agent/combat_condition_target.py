"""Resolve the single target of a condition-applying declaration."""

from __future__ import annotations

from typing import TYPE_CHECKING

from combat_down import damage_target_unavailable
from session_data import CombatParticipant

if TYPE_CHECKING:
    from declarations import Declaration


def _resolve_condition_target(
    state, attacker: CombatParticipant, decl: Declaration, *, allow_self: bool = True, damage: bool = False
):
    """Resolve the single target of a condition-applying declaration.

    Returns ``(target, None)`` for a live target, or ``(None, waste_summary)`` when the target is
    gone / disallowed — a wasted declaration must never apply the condition or
    deduct a cost. ``allow_self`` controls the ``target_id is None`` case: True (default) falls back
    to the caster (a player self-buff); False WASTES it instead — a hostile inflict must never
    self-target (an ABILITY-declared enemy condition action, which skips ATTACK's target_id
    validation, would otherwise make the enemy inflict on ITSELF). Shared by the player ability-
    condition path and the enemy condition-infliction path so the wasted-target contract lives once.
    ``damage`` permits nonterminal Fallen allies only on the damaging save path."""
    target = attacker if decl.target_id is None else state.get_participant(decl.target_id)
    # allow_self=False wastes ANY self-target: the None fallback OR an explicit target_id equal to
    # the attacker's own id — a hostile inflict must never land on its own caster.
    if not allow_self and (decl.target_id is None or (target is not None and target.id == attacker.id)):
        return None, {
            "actor_id": attacker.id,
            "resolved": False,
            "declaration_type": str(decl.type),
            "reason": "condition action requires a non-self target_id",
        }
    if target is None:
        return None, {
            "actor_id": attacker.id,
            "resolved": False,
            "declaration_type": str(decl.type),
            "reason": f"target '{decl.target_id}' not found",
        }
    if damage_target_unavailable(target) if damage else target.is_fallen:
        return None, {
            "actor_id": attacker.id,
            "resolved": False,
            "declaration_type": str(decl.type),
            "reason": f"{target.name} already fell",
        }
    return target, None
