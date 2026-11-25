"""Place Thyra's barrier on the encounter battlefield."""

from __future__ import annotations

from copy import deepcopy
from typing import TYPE_CHECKING
from uuid import uuid4

from livekit.agents.llm import ToolError

import dice
from combat_damage_results import AutomaticDamageResult
from combat_spatial import distance, position, require_spatial
from combat_state import CombatState
from combat_structures import THORNWALL as GIFT
from combat_structures import Segment, add_wall, nearest_wall_point, touches, wall_facts

if TYPE_CHECKING:
    from asyncpg import Connection

    from combat_events import EventSink
    from combat_fate_rolls import PacketRolls, PhaseRolls
    from combat_participant import CombatParticipant
    from declarations import Declaration
    from session_data import SessionData


def thornwall(state: CombatState | None, actor: str, *, destination: dict | None) -> tuple[CombatState, dict]:
    from patron_combat_edges import require_complete_round

    if state is None:
        raise ToolError("Thornwall can only be used in combat.")
    require_complete_round(state, GIFT)
    follower = state.get_participant(actor)
    if (
        follower is None
        or follower.type != "player"
        or follower.is_fallen
        or follower.is_dead
        or follower.hp_current <= 0
    ):
        raise ToolError("Thornwall requires a living acting player in this fight.")
    if destination is None:
        raise ToolError("Thornwall requires start and end points.")
    segment: Segment = {"start": destination["start"], "end": destination["end"]}
    start, end = segment["start"], segment["end"]
    try:
        spatial = require_spatial(state)
        if distance(start, end) > 30:
            raise ToolError("Thornwall can be at most 30 feet long.")
        if (start["x"], start["y"]) == (end["x"], end["y"]):
            raise ToolError("Thornwall requires horizontal extent.")
        origin = position(spatial, actor)
        nearest = nearest_wall_point(origin, segment)
        if distance(origin, nearest) > 30:
            raise ToolError("The nearest point of Thornwall must be within 30 feet.")
        for creature in state.participants:
            if not creature.is_structure and touches(position(spatial, creature.id), segment):
                raise ToolError(f"Thornwall cannot pass through {creature.name}.")

        updated = deepcopy(state)
        wall = add_wall(updated, f"thornwall_{uuid4().hex}", "Thornwall", start, end, kind=GIFT)
        facts, cues = wall_facts(updated, require_spatial(updated), only=wall.id)
    except ValueError as exc:
        raise ToolError(f"Cannot place Thornwall: {exc}") from exc

    return updated, {"wall": facts[0], "dm_cue": " ".join(["Thornwall rises.", *cues])}


async def apply_contact(
    session: SessionData,
    state: CombatState,
    actor: CombatParticipant,
    facts: dict,
    *,
    conn: Connection | None,
    sink: EventSink | None,
    progress: PacketRolls | None = None,
) -> dict:
    from combat_damage import apply_attack_result

    wall_id = facts.get("thornwall_id")
    if wall_id is None:
        return facts
    if actor.thornwall_damage_round == state.round_number:
        return facts
    wall = state.get_participant(wall_id)
    if wall is None or wall.structure_kind != GIFT:
        raise ValueError(f"Unknown Thornwall {wall_id!r}")
    contact = progress.scope("thornwall_damage") if progress is not None else None
    damage = (
        None
        if contact is not None and "damage_receipt" in contact.steps
        else AutomaticDamageResult(dice.roll("1d6").total, "piercing")
    )
    receipt = await apply_attack_result(
        session,
        wall,
        {"name": wall.name},
        actor,
        damage,
        actor.ac,
        combat_state=state,
        conn=conn,
        sink=sink,
        publish_roll=False,
        progress=contact,
    )
    if contact is not None and contact.paused:
        return facts
    actor.thornwall_damage_round = state.round_number
    return {**facts, "thornwall_damage": receipt}


async def resolve_move(
    session: SessionData,
    state: CombatState,
    actor: CombatParticipant,
    declaration: Declaration,
    *,
    conn: Connection | None,
    sink: EventSink | None,
    progress: PacketRolls | None,
) -> dict:
    from combat_spatial_declarations import resolve_traversal

    previous = progress.steps.pop("thornwall_move", None) if progress is not None else None
    facts = previous
    if facts is None:
        traversal = progress.scope("traversal") if progress is not None else None
        facts = await resolve_traversal(session, state, actor, declaration, progress=traversal)
        if facts is None:
            return {}
    result = await apply_contact(session, state, actor, facts, conn=conn, sink=sink, progress=progress)
    if progress is not None and progress.paused:
        progress.steps["thornwall_move"] = facts
    return result


async def resolve_held_contact(
    session: SessionData,
    state: CombatState,
    actor: CombatParticipant,
    movement: dict,
    head: dict,
    *,
    fate_rolls: PhaseRolls | None,
    packet_deps: dict,
) -> dict | None:
    if "thornwall_id" not in movement:
        return movement
    from combat_fate_rolls import PacketRolls

    progress = None
    if fate_rolls is not None and (session.fate_lock.locked() or head.get("roll_steps")):
        progress = PacketRolls(
            fate_rolls, head.setdefault("roll_steps", {}), packet_deps["queries"], packet_deps["conn"]
        )
    result = await apply_contact(
        session, state, actor, movement, conn=packet_deps["conn"], sink=packet_deps["sink"], progress=progress
    )
    return None if progress is not None and progress.paused else result
