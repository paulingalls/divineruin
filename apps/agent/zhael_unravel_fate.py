"""Atomically rewind a fight to the preceding round's opening."""

from __future__ import annotations

import json
from collections.abc import KeysView
from copy import deepcopy
from typing import TYPE_CHECKING

import asyncpg
from livekit.agents.llm import ToolError

import combat_round_checkpoint as checkpoints
import db
import db_mutations
import db_mutations_resonance
import db_queries
import event_types as E
import patron_ability_tools
import reaction_spend
from combat_down import sync_companion_consciousness
from combat_events import isolated_publish
from combat_phase import combat_outcome
from combat_state import CombatState
from combat_ui_update import build_combat_ui_update
from game_events import publish_game_event
from inventory_refresh import publish_inventory
from patron_ability_events import publish_patron_abilities
from patron_passives import effective_hp
from resonance_events import publish_resonance_changed

if TYPE_CHECKING:
    from session_data import SessionData

GIFT = "zhael_unravel_fate"
_RESONANCE_COST = 8
_NO_FIGHT = "Unravel Fate requires an active fight."
_UNTOUCHED = "Use Unravel Fate at an untouched declaration beat."


def _require_opening(state: CombatState) -> None:
    if combat_outcome(state) is not None:
        raise ToolError(_NO_FIGHT)
    if state.beat != "declaration":
        raise ToolError(_UNTOUCHED)
    if state.open_window is not None:
        raise ToolError("Close the reaction window before using Unravel Fate.")
    if (
        state.held_actions
        or state.ally_continuation is not None
        or state.wrap_continuation is not None
        or state.legendary_continuation is not None
        or state.inner_fire_continuation is not None
    ):
        raise ToolError("Finish held work before using Unravel Fate.")


def _previous_opening(state: CombatState) -> dict:
    _require_opening(state)
    history = state.round_checkpoints
    if [entry["round_number"] for entry in history] != [state.round_number - 1, state.round_number]:
        raise ToolError("Unravel Fate has no restorable checkpoint for the previous round.")
    return history[0]


def _restore_combat(previous: dict, live: CombatState, roster: set[str]) -> CombatState:
    restored = CombatState.from_dict(deepcopy(previous))
    retained = {p.id for p in [*restored.participants, *live.participants] if p.type == "player" and p.id not in roster}
    if not retained:
        return restored
    restored.participants = [p for p in restored.participants if p.id not in retained]
    for index, participant in enumerate(live.participants):
        if participant.id in retained:
            restored.participants.insert(index, deepcopy(participant))
    restored.initiative_order = [pid for pid in restored.initiative_order if pid not in retained]
    for index, pid in enumerate(live.initiative_order):
        if pid in retained:
            restored.initiative_order.insert(index, pid)
    if restored.spatial is not None and live.spatial is not None:
        for key in ("positions", "speeds"):
            for pid in retained:
                restored.spatial[key].pop(pid, None)
                if pid in live.spatial[key]:
                    restored.spatial[key][pid] = deepcopy(live.spatial[key][pid])
    return restored


def _require_pocket_rewind(restored: CombatState, committed: CombatState) -> None:
    before, after = (
        {p.id: p.carried_items for p in state.participants if p.type == "enemy" and p.carried_items}
        for state in (committed, restored)
    )
    if before != after:
        raise ToolError(
            "Unravel Fate cannot rewind this round. The enemy pockets changed and some fighters' inventory would stay as it is."
        )


def _rewindable(player: dict) -> dict:
    """The restore-set image a rewind would overwrite; Unravel Fate spends never restore."""
    data = dict(player["data"])
    if gifts := {key: value for key, value in data.pop("patron_gifts", {}).items() if key != GIFT}:
        data["patron_gifts"] = gifts
    return {"data": data, "inventory": player["inventory"]}


def _opening_image(state: CombatState) -> dict:
    image = checkpoints.combat_image(state)
    # A declaration refused before validation reopens keeping the unspent reaction grants it made.
    image["reactions_available"] = {
        pid: entry for pid, entry in image["reactions_available"].items() if entry != reaction_spend.unspent()
    }
    return image


async def _require_untouched(conn: asyncpg.Connection, committed: CombatState, party: KeysView[str]) -> None:
    """Refuse when anything settled since the current round's opening was captured."""
    current_opening = committed.round_checkpoints[-1]
    saved = current_opening["players"]
    roster = party & saved.keys()
    untouched = _restore_combat(current_opening["combat"], committed, roster)
    if _opening_image(untouched) != _opening_image(committed):
        raise ToolError(_UNTOUCHED)
    now = await checkpoints.read_party(conn, sorted(roster))
    if any(_rewindable(now[pid]) != _rewindable(saved[pid]) for pid in roster):
        raise ToolError(_UNTOUCHED)


async def _restore_player(conn: asyncpg.Connection, pid: str, current: dict, saved: dict) -> dict:
    fields = {key: saved[key] for key in checkpoints.RESTORE_KEYS & saved.keys()}
    spent = patron_ability_tools.spent_state(current, GIFT)
    if "patron_gifts" in fields or GIFT in current.get("patron_gifts", {}):
        gifts = dict(fields.get("patron_gifts", {}))
        gifts.pop(GIFT, None)
        if GIFT in current.get("patron_gifts", {}):
            gifts[GIFT] = spent
        fields["patron_gifts"] = gifts
    flags = current.get("flags") or {}
    if "flags" in current or "flags" in saved:
        fields["flags"] = {
            **{key: value for key, value in flags.items() if key not in checkpoints.RESTORE_FLAGS},
            **saved.get("flags", {}),
        }
    await conn.execute(
        "UPDATE players SET data = (data - $2::text[]) || $3::jsonb WHERE player_id = $1",
        pid,
        sorted(checkpoints.RESTORE_KEYS - fields.keys()),
        json.dumps(fields),
    )
    return {**{key: value for key, value in current.items() if key not in checkpoints.RESTORE_KEYS}, **fields}


async def _restore_inventory(conn: asyncpg.Connection, pid: str, current: list[dict], saved: list[dict]) -> bool:
    before = {(slot["item_id"], slot["tainted"]): slot["data"] for slot in current}
    after = {(slot["item_id"], slot["tainted"]): slot["data"] for slot in saved}
    removed = before.keys() - after.keys()
    changed = [(pid, *key, json.dumps(data)) for key, data in after.items() if before.get(key) != data]
    if removed:
        await conn.executemany(
            "DELETE FROM player_inventory WHERE player_id = $1 AND item_id = $2 AND tainted = $3",
            [(pid, *key) for key in sorted(removed)],
        )
    if changed:
        await conn.executemany(
            """INSERT INTO player_inventory (player_id, item_id, tainted, data) VALUES ($1,$2,$3,$4::jsonb)
            ON CONFLICT (player_id, item_id, tainted) DO UPDATE SET data = EXCLUDED.data""",
            changed,
        )
    return bool(removed or changed)


async def _publish(
    session: SessionData,
    restored: CombatState,
    players: dict[str, dict],
    resonance_ids: set[str],
    patron_ids: set[str],
    inventory_ids: set[str],
) -> None:
    for pid, player in players.items():
        with isolated_publish("Unravel Fate HP"):
            await publish_game_event(
                session.room,
                E.HP_CHANGED,
                {**effective_hp(player), "temp_hp": player.get("temp_hp", 0)},
                session.event_bus,
                destination_identities=[pid],
            )
    for pid in sorted(resonance_ids):
        with isolated_publish("Unravel Fate Resonance"):
            await publish_resonance_changed(session, resonance_track=session.member_state(pid).resonance, caster_id=pid)
    with isolated_publish("Unravel Fate combat UI"):
        await publish_game_event(session.room, E.COMBAT_UI_UPDATE, build_combat_ui_update(restored), session.event_bus)
    for pid in sorted(patron_ids):
        with isolated_publish("Unravel Fate patron abilities"):
            await publish_patron_abilities(session.room, pid, session.event_bus)
    for pid in sorted(inventory_ids):
        with isolated_publish("Unravel Fate inventory"):
            await publish_inventory(session, pid)


async def activate(session: SessionData) -> str:
    async with session.combat_state_lock:
        live = session.combat_state
        if live is None:
            raise ToolError(_NO_FIGHT)
        _require_opening(live)
        try:
            actor = session.actor_player_id
        except (RuntimeError, ValueError) as error:
            raise ToolError(str(error)) from error
        members = {member.player_id: member for member in session.party.members}
        player_ids = sorted(members)
        async with db.transaction() as conn:
            current = await db_queries.get_players_for_update(player_ids, conn=conn)
            if missing := set(player_ids) - current.keys():
                raise ToolError(f"Unravel Fate cannot restore missing players: {sorted(missing)}.")
            ability = await patron_ability_tools._locked_ability(conn, actor, GIFT)
            raw = await conn.fetchval(
                "SELECT data FROM combat_instances WHERE combat_id = $1 FOR UPDATE", live.combat_id
            )
            if raw is None:
                raise ToolError(_NO_FIGHT)
            committed = CombatState.from_dict(json.loads(raw))
            if committed.combat_id != live.combat_id or committed.round_number != live.round_number:
                raise ToolError("The fight opening changed. Reload it before using Unravel Fate.")
            previous = _previous_opening(committed)
            await _require_untouched(conn, committed, members.keys())
            saved = previous["players"]
            roster = members.keys() & saved.keys()
            restored = _restore_combat(previous["combat"], committed, roster)
            if saved.keys() - roster or any(
                p.id not in roster for p in committed.participants if p.type in ("player", "temporary_hollowed")
            ):
                _require_pocket_rewind(restored, committed)
            inventory_before = await checkpoints.read_inventory(conn, sorted(roster))
            restored_players = {}
            inventory_ids = set()
            patron_ids = {actor}
            for pid in sorted(roster):
                player = await _restore_player(conn, pid, current[pid], saved[pid]["data"])
                restored_players[pid] = player
                if player.get("patron_gifts") != current[pid].get("patron_gifts"):
                    patron_ids.add(pid)
                if await _restore_inventory(conn, pid, inventory_before[pid], saved[pid]["inventory"]):
                    inventory_ids.add(pid)
            await patron_ability_tools._write_spend(conn, session, actor, GIFT)
            actor_data = restored_players.get(actor, current[actor])
            resonance_cost = (actor_data.get("resonance") or {}).get("current", 0) + _RESONANCE_COST
            await db_mutations_resonance.update_player_resonance(actor, resonance_cost, conn=conn)
            flags = {
                pid: saved[pid]["session_flags"]
                if pid in roster
                else {key: getattr(member, key) for key in checkpoints.SESSION_FLAGS}
                for pid, member in members.items()
            }
            concentration = {
                pid: (player.get("concentration") or {}).get("spell_id") for pid, player in restored_players.items()
            }
            tracks = {
                pid: await db_mutations_resonance.read_player_resonance(pid, conn=conn)
                for pid in sorted(roster | {actor})
            }
            await checkpoints.capture(session, restored, conn=conn, mutations=db_mutations, session_flags=flags)

        session.combat_state = restored
        for pid, track in tracks.items():
            member = members[pid]
            member.resonance.current = track["current"]
            member.resonance.flickering_bonus = track["flickering_bonus"]
            if pid in roster:
                member.concentration.spell_id = concentration[pid]
                for key, value in flags[pid].items():
                    setattr(member, key, value)
        sync_companion_consciousness(session, restored)
        await _publish(session, restored, restored_players, set(tracks), patron_ids, inventory_ids)
    return json.dumps(
        patron_ability_tools._activation_response(
            GIFT,
            ability,
            {"round": restored.round_number, "dm_cue": "The last round unhappened. Everyone declares again."},
        )
    )
