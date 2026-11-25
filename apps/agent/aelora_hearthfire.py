"""Hearthfire's encounter zone and round effects."""

from copy import deepcopy
from typing import TYPE_CHECKING

from livekit.agents.llm import ToolError

import combat_spatial
import combat_spell_heal
import dice
import event_types as E
from combat_down import is_terminally_down
from combat_participant import CombatParticipant
from combat_state import CombatState

if TYPE_CHECKING:
    from combat_events import EventSink
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
        {"source_id": actor, "center": combat_spatial.position(spatial, actor), "radius_ft": 15, "rounds_remaining": 3}
    )
    hearthfire = facts(updated, [])
    names = ", ".join(p["name"] for p in hearthfire["zones"][-1]["occupants"])
    return updated, {
        "hearthfire": hearthfire,
        "dm_cue": f"A hearth crackles to life around {follower.name}. Inside its warmth: {names}.",
    }


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
