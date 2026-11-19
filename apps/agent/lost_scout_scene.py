"""The optional Lost Scout scene and its primary-owned history."""

import json
from typing import Literal, TypedDict, cast

from livekit.agents.llm import ToolError

import still_charm
from catalog_parse import parse_str
from game_events import publish_hidden_revealed
from tool_preconditions import require_npc_present

ENTRANCE = "greyvale_ruins_entrance"
INNER = "greyvale_ruins_inner"
TOKEN = "ressa_corrow_scout_token"
SCOUT = "hollowed_scout"
SCENE = "scene_lost_scout"
TORIN = "guildmaster_torin"
FLAG = "lost_scout"
CHOICE = "lost_scout_report"
Outcome = Literal["fought", "fled", "withdrew"]
OUTCOMES = {"fought", "fled", "withdrew"}


class Record(TypedDict):
    outcome: Outcome | None
    reported: Outcome | None
    residue_delivered: bool
    cleared: bool


def read(player: dict | None) -> Record:
    if player is None:
        raise ValueError("Missing Lost Scout scene owner")
    flags = player.get("flags", {})
    if FLAG not in flags:
        return {"outcome": None, "reported": None, "residue_delivered": False, "cleared": False}
    raw = flags[FLAG]
    if not isinstance(raw, str):
        raise ValueError("Invalid Lost Scout record")
    record = json.loads(raw)
    if (
        not isinstance(record, dict)
        or record.keys() != Record.__required_keys__
        or any(
            record[key] is not None and record[key] not in ("fought", "fled", "withdrew")
            for key in ("outcome", "reported")
        )
        or any(type(record[key]) is not bool for key in ("residue_delivered", "cleared"))
    ):
        raise ValueError("Invalid Lost Scout record")
    return cast(Record, record)


async def write(player_id, record: Record, *, mutations, conn):
    await mutations.set_player_flag(player_id, FLAG, json.dumps(record), conn=conn)


def has_token(player: dict | None) -> bool:
    return bool(player and player.get("flags", {}).get(f"{TOKEN}.discovered") is True)


def token_element(location):
    for element in location["hidden_elements"]:
        if element["id"] == TOKEN:
            return element
    raise ValueError(f"{ENTRANCE} is missing {TOKEN}")


async def reveal_token(session, location, skill, *, db_mod, queries, mutations):
    element = token_element(location)
    actor_id = session.acting_player_id
    async with db_mod.transaction() as conn:
        player = await queries.get_player(actor_id, conn=conn, for_update=True)
        session.validate_acting_player(actor_id)
        if player is None:
            raise ValueError("Missing Lost Scout search actor")
        discovered = has_token(player)
        if not discovered:
            await mutations.set_player_flag(actor_id, f"{TOKEN}.discovered", True, conn=conn)
    if not discovered:
        await publish_hidden_revealed(
            session.room,
            element_id=TOKEN,
            attaches_to=element["attaches_to"],
            description=element["description"],
            skill=skill,
            event_bus=session.event_bus,
        )
    return {"outcome": "discovered", "element_id": TOKEN, "description": element["description"]}


async def scene_text(content, field, *, conn=None):
    scene = await content.get_scene(SCENE) if conn is None else await content.get_scene(SCENE, conn=conn)
    if scene is None:
        raise ValueError(f"Missing scene {SCENE}")
    cue = parse_str(scene.get(field), f"{SCENE}.{field}")
    if not cue.strip():
        raise ValueError(f"{SCENE}.{field} is blank")
    return cue


async def facts(session, location_id, *, queries, content):
    if location_id != INNER or session.location_id != INNER:
        return None
    players = {pid: await queries.get_player(pid) for pid in session.present_member_ids}
    if not any(map(has_token, players.values())):
        return None
    primary_id = session.primary_player_id
    owner = players[primary_id] if primary_id in players else await queries.get_player(primary_id)
    if read(owner)["cleared"]:
        return None
    return {"entry": {"mode": "combat", "encounter_id": SCOUT}, "cue": await scene_text(content, "instructions")}


async def depart(session, member_ids, *, queries, mutations, conn):
    players = await still_charm.lock_players(member_ids, queries=queries, conn=conn)
    primary_id = session.primary_player_id
    record = read(players[primary_id])
    if (
        record["outcome"] is None
        and not record["cleared"]
        and any(has_token(players[pid]) for pid in session.present_member_ids)
    ):
        record["outcome"] = "withdrew"
        await write(primary_id, record, mutations=mutations, conn=conn)


def report_lines(npc_id, npc):
    lines = npc.get("lost_scout_reports")
    if not isinstance(lines, dict) or lines.keys() != OUTCOMES:
        raise ValueError(f"{npc_id}.lost_scout_reports must have fought, fled and withdrew responses")
    responses = {outcome: parse_str(line, f"{npc_id}.lost_scout_reports.{outcome}") for outcome, line in lines.items()}
    if any(not line.strip() for line in responses.values()):
        raise ValueError(f"{npc_id}.lost_scout_reports has a blank response")
    return responses


async def torin_facts(session, npc, narration, *, queries):
    record = read(await queries.get_player(session.primary_player_id))
    if reported := record["reported"]:
        narration["knowledge"].append(report_lines(TORIN, npc)[reported])
    if record["outcome"] and any(
        present["id"] == TORIN for present in await queries.get_npcs_at_location(session.location_id)
    ):
        narration["report_action"] = {"choice_id": CHOICE, "option": "report"}


async def report(session, option, *, db_mod, queries, content, mutations):
    if option != "report":
        raise ToolError("Use the report option to tell Torin about the Lost Scout.")
    actor_id = session.acting_player_id
    primary_id = session.primary_player_id
    async with session.combat_state_lock:
        await require_npc_present(session.location_id, TORIN, queries=queries)
        npc = await content.get_npc(TORIN)
        if npc is None:
            raise ValueError("Missing Guildmaster Torin")
        lines = report_lines(TORIN, npc)
        async with db_mod.transaction() as conn:
            player = await queries.get_player(primary_id, conn=conn, for_update=True)
            if player is None:
                raise ValueError("Missing Lost Scout report owner")
            if player["location_id"] != session.location_id:
                raise ToolError("The party location changed. Refresh the scene before reporting.")
            record = read(player)
            outcome = record["outcome"]
            if outcome is None:
                raise ToolError("There is no Lost Scout outcome to report.")
            session.validate_acting_player(actor_id)
            if record["reported"] != outcome:
                record["reported"] = outcome
                await write(primary_id, record, mutations=mutations, conn=conn)
    return json.dumps({"outcome": outcome, "response": lines[outcome]})
