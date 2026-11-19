"""Own the Still's combat pointer and retained anchor state at a location."""

import json

from livekit.agents.llm import ToolError

import combat_spatial
import still_encounter
from combat_state import CombatState


def key(location_id):
    return f"still_scene:{location_id}"


def read(player, location_id):
    if player is None:
        raise ValueError("Missing Still scene owner player")
    raw = player.get("flags", {}).get(key(location_id))
    if raw is None:
        return None
    record = json.loads(raw)
    fields = {"combat": {"combat_id"}, "dormant": {"snapshot"}, "destroyed": set()}
    if (
        not isinstance(record, dict)
        or record.get("location_id") != location_id
        or record.get("status") not in fields
        or set(record) != {"location_id", "status"} | fields[record["status"]]
    ):
        raise ValueError("Invalid Still scene receipt")
    if record["status"] == "combat" and not isinstance(record["combat_id"], str):
        raise ValueError("Invalid Still combat pointer")
    if record["status"] == "dormant" and not isinstance(record["snapshot"], dict):
        raise ValueError("Invalid dormant Still snapshot")
    return record


async def preflight(session, encounter, *, queries):
    if not any(e["creature_id"] == still_encounter.CREATURE_ID for e in encounter["enemies"]):
        return None
    record = read(await queries.get_player(session.primary_player_id), session.location_id)
    if record is not None and record["status"] != "dormant":
        raise ToolError("The Still is already destroyed or owned by an active combat.")
    return record


async def write(session, state, status, *, mutations, conn, **data):
    record = {"location_id": state.location_id, "status": status, **data}
    await mutations.set_player_flag(session.primary_player_id, key(state.location_id), json.dumps(record), conn=conn)


def restore(state, record):
    retained = CombatState.from_dict(record["snapshot"])
    spatial = combat_spatial.require_spatial(retained)
    old = retained.still_encounter
    new = state.still_encounter
    if (
        old is None
        or new is None
        or old["phase"] != "active"
        or retained.location_id != state.location_id
        or retained.encounter_id != state.encounter_id
        or new["owner_id"] != old["owner_id"]
        or new["anchor_ids"] != old["anchor_ids"]
    ):
        raise ValueError("Invalid retained Still encounter")
    ids = {old["owner_id"], *old["anchor_ids"]}
    for index, participant in enumerate(state.participants):
        if participant.id in ids:
            previous = retained.get_participant(participant.id)
            assert previous is not None
            previous.initiative = participant.initiative
            state.participants[index] = previous
            state.spatial["positions"][participant.id] = spatial["positions"][participant.id]
    state.still_encounter = old
    state.round_number = retained.round_number
    combat_spatial.require_spatial(state)
    still_encounter.validate(state)


async def start(session, state, retained, *, mutations, queries, db_mod):
    async with db_mod.transaction() as conn:
        player = await queries.get_player(session.primary_player_id, conn=conn, for_update=True)
        if read(player, state.location_id) != retained:
            raise ToolError("The Still changed during entry. Reload the scene.")
        if retained is not None:
            restore(state, retained)
        await write(session, state, "combat", combat_id=state.combat_id, mutations=mutations, conn=conn)
        await mutations.save_combat_state(state.combat_id, state.to_dict(), conn=conn)


async def end(session, state, outcome, *, mutations, queries, conn):
    if state.still_encounter is None:
        return
    still_encounter.validate(state)
    destroyed = state.still_encounter["phase"] == "destroyed"
    if outcome == "victory" and not destroyed:
        raise ToolError("All six Still anchors must be destroyed before victory.")
    player = await queries.get_player(session.primary_player_id, conn=conn, for_update=True)
    record = read(player, state.location_id)
    if record is None or record.get("combat_id") != state.combat_id:
        raise ValueError("Still lifecycle lost its authoritative combat pointer")
    if destroyed:
        await write(session, state, "destroyed", mutations=mutations, conn=conn)
    else:
        await write(session, state, "dormant", snapshot=state.to_dict(), mutations=mutations, conn=conn)


async def facts(session, *, queries, location_id):
    if session.combat_state is not None and session.combat_state.location_id == location_id:
        return still_encounter.facts(session.combat_state)
    record = read(await queries.get_player(session.primary_player_id), location_id)
    if record is None or record["status"] == "destroyed":
        return None
    if record["status"] == "combat":
        raise ValueError("Active Still combat must be hydrated before scene narration")
    details = still_encounter.facts(CombatState.from_dict(record["snapshot"]))
    if details is None or details["phase"] != "active":
        raise ValueError("Invalid dormant Still encounter")
    return {**details, "encounter_id": still_encounter.CREATURE_ID}
