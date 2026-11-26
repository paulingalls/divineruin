"""Public tool and persistence helpers for wall encounters."""

from typing import Any

import pytest
from acceptance._spatial_helpers import persisted
from livekit.agents.llm import ToolError

import db_mutations
from combat_state import CombatState
from combat_turn import declare_phase
from declaration_payloads import AttackDecl, MoveDecl


async def _save_and_reload(ctx: Any) -> CombatState:
    state = ctx.userdata.combat_state
    await db_mutations.save_combat_state(state.combat_id, state.to_dict())
    return await _reload(ctx)


async def _reload(ctx: Any) -> CombatState:
    saved = await db_mutations.load_combat_state(ctx.userdata.combat_state.combat_id)
    assert saved is not None and saved.spatial is not None
    ctx.userdata.combat_state = saved
    return saved


def _move(actor_id: str, destination: dict) -> MoveDecl:
    return MoveDecl.model_validate(
        {"reshape": [], "movement_mode": "ground", "kind": "move", "actor_id": actor_id, "destination": destination}
    )


async def _refuses(ctx: Any, declaration: Any, message: str) -> None:
    before = ctx.userdata.combat_state.to_dict()
    publisher = ctx.userdata.room.local_participant.publish_data
    calls = publisher.call_count
    with pytest.raises(ToolError, match=message):
        await declare_phase(ctx, [declaration])
    assert ctx.userdata.combat_state.to_dict() == before
    assert await persisted(before["combat_id"]) == before
    assert publisher.call_count == calls


def _strike(actor_id: str, target: str, action: str = "Greataxe") -> AttackDecl:
    return AttackDecl(
        quick_fingers_mode="",
        quick_fingers_item="",
        reshape=[],
        kind="attack",
        actor_id=actor_id,
        action=action,
        target_id=target,
        held_item_id="",
        rider="",
    )
