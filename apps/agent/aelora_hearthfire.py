"""Hearthfire's encounter zone and round effects."""

import math
from copy import deepcopy
from functools import partial
from typing import TYPE_CHECKING

from livekit.agents.llm import ToolError

import check_resolution_save
import combat_spatial
import combat_spell_heal
import dice
import event_types as E
from combat_down import is_terminally_down
from combat_movement_cost import AXES
from combat_participant import CombatParticipant
from combat_state import CombatState
from rules_engine import attribute_modifier, proficiency_bonus

if TYPE_CHECKING:
    from combat_events import EventSink
    from combat_fate_rolls import PacketRolls
    from session_data import SessionData

GIFT = "aelora_hearthfire"


def _occupants(state: CombatState, spatial: dict, zone: dict) -> list[CombatParticipant]:
    return [
        target
        for target in state.participants
        if combat_spatial.inside(zone["center"], combat_spatial.position(spatial, target.id), zone["radius_ft"])
    ]


def facts(state: CombatState, heals: list[dict]) -> dict:
    zones = []
    if state.hearthfire_zones:
        spatial = combat_spatial.require_spatial(state)
        for zone in state.hearthfire_zones:
            occupants = [{"id": p.id, "name": p.name} for p in _occupants(state, spatial, zone)]
            zones.append({**zone, "occupants": occupants})
    return {"zones": zones, "heals": heals}


def place(state: CombatState | None, actor: str, *, target_id: str | None) -> tuple[CombatState, dict]:
    from patron_combat_edges import require_complete_round

    if state is None:
        raise ToolError("Hearthfire can only be used in combat.")
    require_complete_round(state, GIFT)
    # A zone placed mid-wrap would tick on resume without its first heal.
    if state.wrap_continuation is not None:
        raise ToolError("Finish the partially resolved round before using Hearthfire.")
    follower = state.get_participant(actor)
    if (
        follower is None
        or follower.type != "player"
        or follower.is_fallen
        or follower.hp_current <= 0
        or is_terminally_down(follower)
    ):
        raise ToolError("Hearthfire requires a standing player in this fight.")

    updated = deepcopy(state)
    spatial = combat_spatial.require_spatial(updated)
    updated.hearthfire_zones.append(
        {
            "source_id": actor,
            "center": combat_spatial.position(spatial, actor),
            "radius_ft": 15,
            "rounds_remaining": 3,
            "admitted_ids": [],
            "failed_rounds": {},
        }
    )
    hearthfire = facts(updated, [])
    names = ", ".join(p["name"] for p in hearthfire["zones"][-1]["occupants"])
    return updated, {
        "hearthfire": hearthfire,
        "dm_cue": f"A hearth crackles to life around {follower.name}. Inside its warmth: {names}.",
    }


def contacts(state: CombatState, mover: CombatParticipant, origin: dict, endpoint: dict) -> list[dict]:
    if mover.is_ally or mover.is_structure or not state.hearthfire_zones:
        return []
    delta = {axis: endpoint[axis] - origin[axis] for axis in AXES}
    length = math.hypot(*delta.values())
    if length == 0:
        return []
    direction = {axis: delta[axis] / length for axis in AXES}
    crossings = []
    for index, zone in enumerate(state.hearthfire_zones):
        center, radius = zone["center"], zone["radius_ft"]
        if mover.id in zone["admitted_ids"] or combat_spatial.inside(origin, center, radius):
            continue
        projection = sum((center[axis] - origin[axis]) * direction[axis] for axis in AXES) / length
        high = min(1.0, max(0.0, projection))
        if not combat_spatial.inside(_along(origin, delta, high), center, radius):
            continue
        # Keep the last exterior position so a refused mover encounters the boundary on retry.
        low = 0.0
        while low < (mid := (low + high) / 2) < high:
            if combat_spatial.inside(_along(origin, delta, mid), center, radius):
                high = mid
            else:
                low = mid
        crossings.append((high, {"zone_index": index, "edge": _along(origin, delta, low)}))
    return [contact for _, contact in sorted(crossings, key=lambda crossing: crossing[0])]


def _along(origin: dict, delta: dict, fraction: float) -> dict:
    return {axis: origin[axis] + fraction * delta[axis] for axis in AXES}


async def settle_entry(
    session: "SessionData | None",
    state: CombatState,
    mover: CombatParticipant,
    zone_index: int,
    progress: "PacketRolls | None",
) -> dict | None:
    from combat_fate_rolls import packet_save

    zone = state.hearthfire_zones[zone_index]
    source_id = zone["source_id"]
    follower = state.get_participant(source_id)
    if follower is None:
        raise ValueError(f"Unknown Hearthfire source {source_id!r}")
    dc = 8 + proficiency_bonus(follower.level) + attribute_modifier(follower.attributes.get("wisdom", 10))
    receipt = {"source_id": source_id, "mover_id": mover.id, "dc": dc, "success": False}
    if zone["failed_rounds"].get(mover.id) == state.round_number:
        return {**receipt, "same_round": True, "dm_cue": f"Hearthfire still bars {mover.name}."}
    result = await packet_save(
        progress,
        session,
        mover.id,
        GIFT,
        partial(
            check_resolution_save.roll_participant_save,
            mover,
            "WIS",
            dc,
            GIFT,
            originating_participant_id=source_id,
            combat_state=state,
        ),
        state=state,
    )
    if result is None:
        return None
    if result.success:
        zone["admitted_ids"].append(mover.id)
        cue = f"{mover.name} pushes through Hearthfire."
    else:
        zone["failed_rounds"][mover.id] = state.round_number
        cue = f"Hearthfire stops {mover.name} at its edge."
    return {**receipt, "roll": result.roll, "total": result.total, "success": result.success, "dm_cue": cue}


async def heal_round(
    session: "SessionData", state: CombatState, *, conn, mutations, queries, sink: "EventSink"
) -> list[dict]:
    if not state.hearthfire_zones:
        return []

    spatial = combat_spatial.require_spatial(state)
    heals = []
    for zone in state.hearthfire_zones:
        rolled = dice.roll("1d6").total
        for target in _occupants(state, spatial, zone):
            if not target.is_ally or is_terminally_down(target):
                continue
            was_fallen = target.is_fallen
            restored = await combat_spell_heal.restore(target, rolled, conn=conn, mutations=mutations, queries=queries)
            heals.append(
                {
                    "source_id": zone["source_id"],
                    "target_id": target.id,
                    "target_name": target.name,
                    "round": state.round_number,
                    "rolled": rolled,
                    "healed": restored,
                    "hp_current": target.hp_current,
                    "hp_max": target.hp_max,
                    "rose": was_fallen and not target.is_fallen,
                }
            )
            if restored and target.type == "player":
                await sink.emit(
                    session.room,
                    E.HP_CHANGED,
                    {"current": target.hp_current, "max": target.hp_max, "temp_hp": target.temp_hp},
                    event_bus=session.event_bus,
                    destination_identities=[target.id],
                )
    return heals


def tick(zones: list[dict]) -> list[dict]:
    return [
        {**zone, "rounds_remaining": zone["rounds_remaining"] - 1} for zone in zones if zone["rounds_remaining"] > 1
    ]
