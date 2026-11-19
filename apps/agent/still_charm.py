"""Persist the Still's zone charm on the player who holds it."""

import json
from typing import Literal, TypedDict

from livekit.agents.llm import ToolError

import check_resolution_save
import conditions

CharmKind = Literal["paradise_trap", "serenitys_touch", "final_stillness"]
PARADISE_TRAP: CharmKind = "paradise_trap"
SERENITYS_TOUCH: CharmKind = "serenitys_touch"
FINAL_STILLNESS: CharmKind = "final_stillness"


class Charm(TypedDict):
    location_id: str
    kind: CharmKind
    remaining_zone_hours: int | None


def key(location_id: str) -> str:
    return f"still_charm:{location_id}"


def read(player: dict, player_id: str, location_id: str) -> Charm | None:
    flag = key(location_id)
    flags = player.get("flags", {})
    if flag not in flags:
        return None
    error = f"Invalid Still charm record for {player_id} at {location_id}."
    try:
        record = json.loads(flags[flag])
    except (TypeError, ValueError) as exc:
        raise ToolError(error) from exc
    if (
        not isinstance(record, dict)
        or set(record) != {"location_id", "kind", "remaining_zone_hours"}
        or record["location_id"] != location_id
        or record["kind"] not in (PARADISE_TRAP, SERENITYS_TOUCH, FINAL_STILLNESS)
    ):
        raise ToolError(error)
    hours = record["remaining_zone_hours"]
    if record["kind"] == SERENITYS_TOUCH:
        if type(hours) is not int or hours != 1:
            raise ToolError(error)
    elif hours is not None:
        raise ToolError(error)
    return Charm(location_id=location_id, kind=record["kind"], remaining_zone_hours=hours)


async def lock_players(player_ids, *, queries, conn) -> dict[str, dict]:
    players = await queries.get_players_for_update(list(player_ids), conn=conn)
    for player_id in player_ids:
        if player_id not in players:
            raise ToolError(f"Player '{player_id}' is no longer available.")
    return players


def unwilling(player: dict, player_id: str) -> str:
    return f"{player.get('name') or player_id} does not want to leave the Still."


def require_departure(players, location_id):
    for player_id, player in players.items():
        if read(player, player_id, location_id) is not None:
            raise ToolError(unwilling(player, player_id))


async def grant(player_id, player, location_id, kind: CharmKind, *, mutations, conn):
    current = read(player, player_id, location_id)
    if current is not None and current["remaining_zone_hours"] is None and kind == SERENITYS_TOUCH:
        return
    record = Charm(location_id=location_id, kind=kind, remaining_zone_hours=1 if kind == SERENITYS_TOUCH else None)
    if record != current:
        await mutations.set_player_flag(player_id, key(location_id), json.dumps(record), conn=conn)


async def save_on_arrival(players, location_id, *, mutations, conn):
    for player_id, player in players.items():
        current = read(player, player_id, location_id)
        save = check_resolution_save.resolve_saving_throw(player, "wisdom", 18, "charmed", bonus_dice_eligible=False)
        if current is None and not save.success:
            await grant(player_id, player, location_id, PARADISE_TRAP, mutations=mutations, conn=conn)


def project(state, owner_id, players):
    for participant in state.participants:
        if (
            participant.type == "player"
            and read(players[participant.id], participant.id, state.location_id) is not None
        ):
            projected = conditions.apply_condition([], "charmed", source=owner_id)
            participant.conditions = [*projected, *conditions.remove_condition(participant.conditions, "charmed")]


async def clear(player_ids, location_id: str, *, conn):
    flag = key(location_id)
    await conn.execute(
        """UPDATE players SET data = data #- ARRAY['flags', $2]
           WHERE player_id = ANY($1) AND data->'flags' ? $2""",
        sorted(player_ids),
        flag,
    )


async def end_instance(state, owner_id, player_ids, *, queries, conn):
    await lock_players(player_ids, queries=queries, conn=conn)
    await clear(player_ids, state.location_id, conn=conn)
    for participant in state.participants:
        participant.conditions = [
            active
            for active in participant.conditions
            if not (active["type"] == "charmed" and active["source"] == owner_id)
        ]
