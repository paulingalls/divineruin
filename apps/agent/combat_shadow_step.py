"""Shadow Step uses the current battlefield and the ordinary movement path."""

from types import ModuleType
from typing import TYPE_CHECKING

from asyncpg import Connection
from livekit.agents.llm import ToolError

import combat_martial
import combat_spatial_declarations as moves
import concealment
from combat_ability_gate import SHADOW_STEP, DeclaredAbility
from combat_spatial import inside, point, position, require_spatial
from combat_structures import nearest_wall_point
from declarations import Declaration, DeclarationType

if TYPE_CHECKING:
    from combat_participant import CombatParticipant
    from combat_player_movement import PlayerMovement
    from combat_state import CombatState

COVER_FEET = 5
PIT_REASON = "Climb out of the pit before Shadow Step."


class CoverRefused(ValueError):
    """The requested point lacks qualifying cover."""


def _covered(state: "CombatState", destination: dict) -> bool:
    spatial = require_spatial(state)
    if any(
        inside(destination, nearest_wall_point(destination, segment), COVER_FEET)
        for segment in spatial.get("structures", {}).values()
    ):
        return True
    if any(
        inside(destination, position(spatial, chamber_id), COVER_FEET) for chamber_id in spatial.get("chambers", {})
    ):
        return True
    return any(
        zone.get("kind") == "smoke" and inside(destination, position(spatial, zone["center_id"]), zone["radius_ft"])
        for zone in spatial["zones"].values()
    )


def _require_cover(state: "CombatState", declaration: Declaration) -> None:
    if not _covered(state, point(declaration.destination)):
        raise CoverRefused("Shadow Step requires cover within 5 feet of a wall or standing structure, or inside smoke.")


def _move(actor_id: str, declaration: Declaration) -> Declaration:
    return Declaration(DeclarationType.MANEUVER, action="move", target_id=actor_id, destination=declaration.destination)


def validate(state: "CombatState", actor_id: str, declaration: Declaration) -> None:
    if moves.in_pit(state, actor_id):
        raise ValueError(PIT_REASON)
    _require_cover(state, declaration)
    moves.validate_move(state, actor_id, _move(actor_id, declaration))


async def resolve(
    state: "CombatState",
    actor: "CombatParticipant",
    declaration: Declaration,
    ability: DeclaredAbility,
    movement: "PlayerMovement",
    *,
    conn: Connection,
    queries: ModuleType,
) -> dict:
    from combat_ability import _with_variant

    summary = {"actor_id": actor.id, "action": SHADOW_STEP, "declaration_type": "ability", "resolved": False}
    if moves.in_pit(state, actor.id):
        return {**summary, "reason": PIT_REASON}
    try:
        _require_cover(state, declaration)
    except CoverRefused as error:
        return {**summary, "reason": str(error)}

    moved = await movement.move(actor, _move(actor.id, declaration), disengage=True)
    if moved is None:
        return {}
    if not moved["resolved"]:
        return {**moved, **summary}
    variant = await combat_martial.pay(actor.id, ability, conn=conn, queries=queries)
    cost = (variant or ability[0]).cost
    player = await queries.get_player(actor.id, conn=conn, for_update=True)
    if player is None:
        raise ToolError(f"Unknown player: {actor.id}")
    return _with_variant(
        {
            **moved,
            **summary,
            "resolved": True,
            "deducted": {"focus": cost.focus, "stamina": cost.stamina},
            "concealment": await concealment.transition(actor.id, player, True, combat_only=True, conn=conn),
        },
        variant,
    )
