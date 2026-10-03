"""Transfer the Choir lifecycle between active combat and the durable scene receipt."""

import json
from dataclasses import asdict
from hashlib import sha256

from livekit.agents.llm import ToolError

import choir_effects
import choir_encounter
import db
import db_mutations
import db_queries
from combat_participant import CombatParticipant


def key(location_id):
    return "choir_scene_" + sha256(location_id.encode()).hexdigest()[:16]


def read(player, location_id):
    raw = player.get("flags", {}).get(key(location_id))
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise ValueError("invalid Choir scene receipt")
    record = json.loads(raw)
    if not isinstance(record, dict) or record.get("location_id") != location_id:
        raise ValueError("invalid Choir scene location")
    if record.get("status") not in {"combat", "dormant", "destroyed"}:
        raise ValueError("invalid Choir scene status")
    if record.get("source_id") != key(location_id):
        raise ValueError("invalid Choir scene source")
    if record["status"] == "combat":
        if not isinstance(record.get("combat_id"), str) or set(record) != {
            "source_id",
            "location_id",
            "status",
            "combat_id",
        }:
            raise ValueError("invalid active Choir owner pointer")
    elif record["status"] == "dormant":
        if set(record) != {"source_id", "location_id", "status", "owner", "phase", "round"}:
            raise ValueError("invalid retained Choir owner")
        source = CombatParticipant(**record["owner"])
        if source.creature_id != "hollow_choir" or source.hp_current <= 0 or source.hollow_death_resolved:
            raise ValueError("invalid retained Choir HP owner")
        if record["phase"] not in {"search", "exposed"} or type(record["round"]) is not int or record["round"] < 1:
            raise ValueError("invalid retained Choir phase")
    elif set(record) != {"source_id", "location_id", "status"}:
        raise ValueError("invalid destroyed Choir receipt")
    return record


async def load(session, *, queries=db_queries, conn=None, location_id=None):
    location_id = location_id or session.location_id
    player = await queries.get_player(session.primary_player_id, conn=conn)
    if player is None:
        raise ValueError("missing Choir scene owner player")
    return read(player, location_id)


async def preflight(session, encounter, *, queries):
    if not any(e["creature_id"] == "hollow_choir" for e in encounter["enemies"]):
        return None
    record = await load(session, queries=queries)
    if record is not None and record["status"] in {"destroyed", "combat"}:
        raise ToolError("This Choir source is already destroyed or owned by an active combat.")
    return record


async def start(session, state, retained, *, mutations=db_mutations, queries=db_queries, db_mod=db):
    source = choir_encounter.owner(state)
    if source is None:
        await mutations.save_combat_state(state.combat_id, state.to_dict())
        return
    async with db_mod.transaction() as conn:
        player = await queries.get_player(session.primary_player_id, conn=conn, for_update=True)
        if read(player, state.location_id) != retained:
            raise ToolError("Choir source changed during entry; reload the scene.")
        if retained is not None:
            restored = CombatParticipant(**retained["owner"])
            restored.initiative = source.initiative
            if restored.id != source.id:
                raise ValueError("Choir re-entry changed owner identity")
            state.participants[state.participants.index(source)] = restored
            state.choir_encounter["phase"] = retained["phase"]
            state.round_number = retained["round"]
            choir_effects.exposure(state)
        record = {
            "source_id": key(state.location_id),
            "location_id": state.location_id,
            "status": "combat",
            "combat_id": state.combat_id,
        }
        await mutations.set_player_flag(
            session.primary_player_id, key(state.location_id), json.dumps(record), conn=conn
        )
        await mutations.save_combat_state(state.combat_id, state.to_dict(), conn=conn)


async def end(session, state, outcome, *, mutations, queries, conn):
    source = choir_encounter.owner(state)
    if source is None or state.choir_encounter is None:
        return
    choir_encounter.validate(state)
    if outcome == "victory" and state.choir_encounter["phase"] != "destroyed":
        raise ToolError("The Choir core must be destroyed before victory.")
    player = await queries.get_player(session.primary_player_id, conn=conn, for_update=True)
    record = read(player, state.location_id)
    if record is None or record.get("combat_id") != state.combat_id:
        raise ValueError("Choir lifecycle lost its authoritative combat owner")
    result = {
        "source_id": key(state.location_id),
        "location_id": state.location_id,
        "status": "destroyed" if source.hollow_death_resolved else "dormant",
    }
    if result["status"] == "dormant":
        result.update(owner=asdict(source), phase=state.choir_encounter["phase"], round=state.round_number)
    await mutations.set_player_flag(session.primary_player_id, key(state.location_id), json.dumps(result), conn=conn)


async def check_data(session, player, *, queries=db_queries):
    if session.in_combat:
        return player
    record = (
        read(player, session.location_id)
        if session.acting_player_id == session.primary_player_id
        else await load(session, queries=queries)
    )
    if record is not None and record["status"] == "dormant":
        return {**player, "scene_disadvantage_skills": ["perception", "insight", "investigation"]}
    return player


async def facts(session, *, queries=db_queries, location_id=None):
    location_id = location_id or session.location_id
    if session.combat_state is not None and session.combat_state.location_id == location_id:
        return choir_encounter.facts(session.combat_state)
    record = await load(session, queries=queries, location_id=location_id)
    if record is None or record["status"] == "destroyed":
        return None
    if record["status"] == "combat":
        raise ValueError("Active Choir combat must be hydrated before scene narration")
    return {
        "phase": record["phase"],
        "source_id": record["source_id"],
        "cue": "Familiar voices drift through a wrong hum. Every voice here may be false.",
        "encounter_id": "hollow_choir",
        "entry": 'enter_mode(mode="combat", encounter_id="hollow_choir")',
        "disadvantage_skills": ["perception", "insight", "investigation"],
    }
