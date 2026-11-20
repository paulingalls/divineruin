"""Prepare and resume the free Reshape that precedes an ordinary action."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from declarations import DeclarationType

if TYPE_CHECKING:
    from combat_fate_rolls import PacketRolls
    from combat_state import CombatState
    from declarations import Declaration
    from session_data import SessionData


class ReshapeRefused(ValueError):
    pass


async def resolve_reshape(
    session: SessionData,
    state: CombatState,
    actor_id: str,
    declaration: Declaration,
    cursor: dict,
    *,
    progress: PacketRolls | None,
    packet_deps: dict,
) -> bool:
    if not declaration.reshape:
        return True

    import architect_actions
    from architect_reshape import proposed_state, resolve
    from combat_ability import _find_action
    from combat_declaration_validation import validate_declaration
    from combat_down import target_unavailable

    actor = state.get_participant(actor_id)
    if "reshape_receipts" not in cursor:
        try:
            proposal = proposed_state(state, actor_id, declaration.reshape)
            validate_declaration(proposal, actor_id, replace(declaration, reshape=None), {})
            if declaration.type is DeclarationType.ATTACK:
                action = _find_action(actor, declaration.action)
                assert action is not None
                assert declaration.target_id is not None
                target = proposal.get_participant(declaration.target_id)
                if target is None or target_unavailable(target, action):
                    raise ValueError("The target is unavailable")
                if reason := architect_actions.slam_refusal(proposal, actor_id, action, target.id):
                    raise ValueError(reason)
        except ValueError as error:
            raise ReshapeRefused(str(error)) from error
        cursor["reshape_receipts"] = []

    assert actor is not None
    return await resolve(
        session,
        state,
        actor,
        declaration.reshape,
        cursor["reshape_receipts"],
        progress=progress.scope("reshape") if progress is not None else None,
        packet_deps=packet_deps,
    )
