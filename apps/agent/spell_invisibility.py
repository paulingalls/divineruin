"""Combat preflight and removal for the Invisibility spell."""

from typing import TYPE_CHECKING

from livekit.agents.llm import ToolError

import concealment
from condition_catalog import INVISIBLE
from condition_produce import resolve_effective_targets
from conditions import has_condition, remove_condition

if TYPE_CHECKING:
    from combat_participant import CombatParticipant
    from combat_state import CombatState
    from spells import Spell


class InvisibilityRefused(ValueError):
    """An outline prevents Invisibility from taking hold."""


def require_clear_outline(target: "CombatParticipant") -> None:
    if has_condition(target.conditions, "outlined"):
        raise InvisibilityRefused(f"{target.name} cannot become invisible while outlined.")


def guard_direct_cast(
    state: "CombatState", spell: "Spell", caster_id: str, target_id: str | None, target_ids: list[str] | None
) -> None:
    if spell.applies_condition == INVISIBLE:
        for recipient_id in resolve_effective_targets(target_ids, target_id, self_value=caster_id):
            recipient = state.get_participant(recipient_id)
            if recipient is not None:
                try:
                    require_clear_outline(recipient)
                except InvisibilityRefused as e:
                    raise ToolError(str(e)) from e
        raise ToolError("Invisibility is cast in combat with declare_phase.")
    if spell.hostile:
        caster = state.get_participant(caster_id)
        if caster is not None and has_condition(caster.conditions, INVISIBLE):
            raise ToolError(f"Cast {spell.name} with declare_phase to resolve the break in invisibility.")


def reveal_invisible(actor: "CombatParticipant") -> dict[str, str]:
    if not has_condition(actor.conditions, INVISIBLE):
        return {}
    actor.conditions = remove_condition(actor.conditions, INVISIBLE)
    return {"condition_removed": INVISIBLE}


async def reveal_attack(actor: "CombatParticipant", *, conn, queries) -> dict:
    receipt: dict = reveal_invisible(actor)
    if actor.type == "player" and (reveal := await concealment.reveal_attacker(actor.id, conn=conn, queries=queries)):
        receipt["concealment"] = reveal
    return receipt
