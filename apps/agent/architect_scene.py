"""Persist the Works encounter across visits."""

import json

from livekit.agents.llm import ToolError

import architect_encounter
import combat_spatial
from combat_state import CombatState


def key(location_id: str) -> str:
    return f"architect_scene:{location_id}"


def read(player: dict | None, location_id: str) -> dict | None:
    if player is None:
        raise ValueError("Missing Architect scene owner")
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
        raise ValueError("Invalid Architect scene receipt")
    if record["status"] == "combat" and not isinstance(record["combat_id"], str):
        raise ValueError("Invalid Architect combat pointer")
    if record["status"] == "dormant" and not isinstance(record["snapshot"], dict):
        raise ValueError("Invalid dormant Architect snapshot")
    return record


async def preflight(session, encounter: dict, *, queries) -> dict | None:
    if not any(e["creature_id"] == architect_encounter.CREATURE_ID for e in encounter["enemies"]):
        return None
    record = read(await queries.get_player(session.primary_player_id), session.location_id)
    if record is not None and record["status"] != "dormant":
        raise ToolError("The Architect is already destroyed or owned by an active combat.")
    return record


async def write(session, state: CombatState, status: str, *, mutations, conn, **data) -> None:
    record = {"location_id": state.location_id, "status": status, **data}
    await mutations.set_player_flag(session.primary_player_id, key(state.location_id), json.dumps(record), conn=conn)


def _dormant(record: dict, location_id: str) -> CombatState:
    retained = CombatState.from_dict(record["snapshot"])
    old = retained.architect_encounter
    if old is None or old["phase"] != "active" or retained.location_id != location_id:
        raise ValueError("Invalid dormant Architect encounter")
    return retained


def restore(state: CombatState, record: dict) -> None:
    retained = _dormant(record, state.location_id)
    old = retained.architect_encounter
    new = state.architect_encounter
    assert old is not None and new is not None
    if retained.encounter_id != state.encounter_id or new["owner_id"] != old["owner_id"]:
        raise ValueError("Invalid retained Architect encounter identity")
    spatial = combat_spatial.require_spatial(state)
    previous_spatial = combat_spatial.require_spatial(retained)
    owner_id = old["owner_id"]
    owner = retained.get_participant(owner_id)
    assert owner is not None
    owner.initiative = next(p.initiative for p in state.participants if p.id == owner_id)
    state.participants = [p for p in state.participants if p.id not in {owner_id, *new["structure_ids"]}]
    for wall_id in new["structure_ids"]:
        for field in ("positions", "speeds", "structures"):
            del spatial[field][wall_id]
    state.participants.append(owner)
    spatial["positions"][owner_id] = previous_spatial["positions"][owner_id]
    for wall_id in old["structure_ids"]:
        wall = retained.get_participant(wall_id)
        assert wall is not None
        state.participants.append(wall)
        spatial["positions"][wall_id] = previous_spatial["positions"][wall_id]
        spatial["speeds"][wall_id] = 0
        if not wall.is_dead:
            spatial["structures"][wall_id] = previous_spatial["structures"][wall_id]
    spatial["movement_areas"] = previous_spatial["movement_areas"]
    old["pits"] = {actor: floor for actor, floor in old["pits"].items() if state.get_participant(actor) is not None}
    for actor in old["pits"]:
        spatial["positions"][actor] = previous_spatial["positions"][actor]
    state.architect_encounter = old
    state.round_number = retained.round_number
    combat_spatial.require_spatial(state)
    architect_encounter.validate(state)


async def start(session, state: CombatState, retained: dict | None, *, mutations, queries, db_mod) -> None:
    async with db_mod.transaction() as conn:
        player = await queries.get_player(session.primary_player_id, conn=conn, for_update=True)
        if read(player, state.location_id) != retained:
            raise ToolError("The Architect changed during entry. Reload the scene.")
        if retained is not None:
            restore(state, retained)
        await write(session, state, "combat", combat_id=state.combat_id, mutations=mutations, conn=conn)
        await mutations.save_combat_state(state.combat_id, state.to_dict(), conn=conn)


async def end(session, state: CombatState, outcome: str, *, mutations, queries, conn) -> None:
    if state.architect_encounter is None:
        return
    architect_encounter.validate(state)
    destroyed = state.architect_encounter["phase"] == "destroyed"
    if outcome == "victory" and not destroyed:
        raise ToolError("The Architect is still standing.")
    player = await queries.get_player(session.primary_player_id, conn=conn, for_update=True)
    record = read(player, state.location_id)
    if record is None or record.get("combat_id") != state.combat_id:
        raise ValueError("Architect lifecycle lost its authoritative combat pointer")
    if destroyed:
        await write(session, state, "destroyed", mutations=mutations, conn=conn)
    else:
        await write(session, state, "dormant", snapshot=state.to_dict(), mutations=mutations, conn=conn)


async def facts(session, *, queries, location_id: str, location: dict) -> dict | None:
    if "architect" not in location.get("tags", []):
        return None
    if session.combat_state is not None and session.combat_state.location_id == location_id:
        details = architect_encounter.facts(session.combat_state)
        if details is not None:
            return details
    record = read(await queries.get_player(session.primary_player_id), location_id)
    if record is not None and record["status"] == "destroyed":
        return None
    details = {}
    if record is not None:
        if record["status"] == "combat":
            raise ValueError("Active Architect combat must be hydrated before scene narration")
        details = architect_encounter.facts(_dormant(record, location_id))
        assert details is not None
    encounter_id = architect_encounter.CREATURE_ID
    return {
        **details,
        "encounter_id": encounter_id,
        "entry": f'enter_mode(mode="combat", encounter_id="{encounter_id}")',
    }
