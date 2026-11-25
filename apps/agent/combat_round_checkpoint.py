"""Capture the transaction's round-start image and validate it when loading combat."""

from __future__ import annotations

import json
from dataclasses import replace
from typing import TYPE_CHECKING

import asyncpg

from action_contracts import positive_integer

if TYPE_CHECKING:
    from combat_state import CombatState
    from session_data import SessionData

RESTORE_KEYS = frozenset({"hp", "temp_hp", "stamina", "focus", "resonance", "concentration", "patron_gifts"})
RESTORE_FLAGS = frozenset({"shadow_veil", "concealed"})
ENTRY_RESET_FLAGS = ("weapon_used", "weapon_crit_vs_heavy", "draethar_inner_fire_used", "unbound_raw_channeling_used")
MASTERY_FLAG = "unbound_veil_mastery_used"
SESSION_FLAGS = frozenset((*ENTRY_RESET_FLAGS, MASTERY_FLAG))


def combat_image(state: CombatState) -> dict:
    image = replace(state, round_checkpoints=[]).to_dict()
    del image["round_checkpoints"]
    return image


def _json_object(value: str | dict) -> dict:
    decoded = json.loads(value) if isinstance(value, str) else value
    if not isinstance(decoded, dict):
        raise ValueError("Round checkpoint expects a JSON object")
    return decoded


async def read_party(conn: asyncpg.Connection, ids: list[str]) -> dict[str, dict]:
    rows = await conn.fetch(
        "SELECT player_id, data FROM players WHERE player_id = ANY($1::text[]) ORDER BY player_id FOR UPDATE",
        ids,
    )
    players = {}
    for row in rows:
        raw = _json_object(row["data"])
        data = {key: raw[key] for key in RESTORE_KEYS if key in raw}
        flags = raw.get("flags") or {}
        if captured := {key: flags[key] for key in RESTORE_FLAGS & flags.keys()}:
            data["flags"] = captured
        players[row["player_id"]] = {"data": data}
    if missing := set(ids) - players.keys():
        raise ValueError(f"Round checkpoint missing players: {sorted(missing)}")
    for pid, inventory in (await read_inventory(conn, ids)).items():
        players[pid]["inventory"] = inventory
    return players


async def read_inventory(conn: asyncpg.Connection, ids: list[str]) -> dict[str, list[dict]]:
    inventory: dict[str, list[dict]] = {pid: [] for pid in ids}
    slots = await conn.fetch(
        """
        SELECT player_id, item_id, tainted, data FROM player_inventory
        WHERE player_id = ANY($1::text[]) ORDER BY player_id, item_id, tainted
        """,
        ids,
    )
    for row in slots:
        inventory[row["player_id"]].append(
            {"item_id": row["item_id"], "tainted": row["tainted"], "data": _json_object(row["data"])}
        )
    return inventory


async def capture(
    session: SessionData,
    state: CombatState,
    *,
    conn: asyncpg.Connection,
    mutations,
    entry: bool = False,
    session_flags: dict[str, dict[str, bool]] | None = None,
) -> None:
    flags = (
        session_flags
        if session_flags is not None
        else {
            member.player_id: {
                **{name: False if entry else getattr(member, name) for name in ENTRY_RESET_FLAGS},
                MASTERY_FLAG: member.unbound_veil_mastery_used,
            }
            for member in session.party.members
        }
    )
    players = await read_party(conn, sorted(flags))
    for pid, image in players.items():
        image["session_flags"] = flags[pid]

    snapshot = {
        "combat_id": state.combat_id,
        "round_number": state.round_number,
        "combat": combat_image(state),
        "players": players,
    }
    state.round_checkpoints = [*state.round_checkpoints[-1:], snapshot]
    await mutations.save_combat_state(state.combat_id, state.to_dict(), conn=conn)


def _id(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _validate_player(player: object) -> None:
    if not isinstance(player, dict) or player.keys() != {"data", "inventory", "session_flags"}:
        raise ValueError("invalid player image")
    data, slots, flags = player["data"], player["inventory"], player["session_flags"]
    if not isinstance(data, dict) or data.keys() - (RESTORE_KEYS | {"flags"}):
        raise ValueError("invalid restore fields")
    restore_flags = data.get("flags", {})
    if not isinstance(restore_flags, dict) or restore_flags.keys() - RESTORE_FLAGS:
        raise ValueError("invalid restore flags")
    if restore_flags.get("shadow_veil") and restore_flags.get("concealed") is not True:
        raise ValueError("Shadow Veil requires concealment in the checkpoint")
    if not isinstance(flags, dict) or flags.keys() != SESSION_FLAGS or any(type(v) is not bool for v in flags.values()):
        raise ValueError("invalid session flags")
    if not isinstance(slots, list):
        raise ValueError("invalid inventory")
    for slot in slots:
        if (
            not isinstance(slot, dict)
            or slot.keys() != {"item_id", "tainted", "data"}
            or not _id(slot["item_id"])
            or type(slot["tainted"]) is not bool
            or not isinstance(slot["data"], dict)
        ):
            raise ValueError("invalid inventory slot")


def _validate_snapshot(snapshot: object, combat_id: str, round_number: int) -> int:
    from combat_state import CombatState

    if not isinstance(snapshot, dict) or snapshot.keys() != {"combat_id", "round_number", "combat", "players"}:
        raise ValueError("invalid snapshot fields")
    if not _id(snapshot["combat_id"]) or snapshot["combat_id"] != combat_id:
        raise ValueError("wrong combat id")
    round_start = snapshot["round_number"]
    if not positive_integer(round_start) or round_start > round_number:
        raise ValueError("invalid snapshot round")
    image = snapshot["combat"]
    if not isinstance(image, dict) or "round_checkpoints" in image:
        raise ValueError("invalid or nested combat image")
    if (
        image.get("combat_id") != combat_id
        or not positive_integer(image.get("round_number"))
        or image["round_number"] != round_start
    ):
        raise ValueError("combat image identity differs from snapshot")
    if image.get("beat") != "declaration" or image.get("wrap_continuation") is not None:
        raise ValueError("combat image is not a completed round start")
    CombatState.from_dict(image)
    players = snapshot["players"]
    if not isinstance(players, dict) or not all(_id(pid) for pid in players):
        raise ValueError("invalid party image")
    for player in players.values():
        _validate_player(player)
    return round_start


def load_history(history: object, combat_id: str, round_number: int) -> list[dict]:
    try:
        if not isinstance(history, list) or len(history) > 2:
            raise ValueError("expected at most two snapshots")
        rounds = [_validate_snapshot(snapshot, combat_id, round_number) for snapshot in history]
        if len(rounds) == 2 and rounds[0] + 1 != rounds[1]:
            raise ValueError("snapshots must be consecutive and ordered")
    except (ValueError, KeyError, IndexError, TypeError, AttributeError) as error:
        raise ValueError(f"Malformed round checkpoint: {error}") from error
    return history
