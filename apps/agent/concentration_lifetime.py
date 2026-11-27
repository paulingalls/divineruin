"""Settle spell lifetimes inside the transaction advancing game time."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

import concentration
import db_mutations_concentration
import spells
from caster_state import ConcentrationState
from concentration_break import end_concentration

if TYPE_CHECKING:
    import asyncpg

    from combat_state import CombatState
    from session_data import SessionData


def combat_entry(session: SessionData, state: CombatState) -> dict[str, ConcentrationState]:
    roster = {p.id for p in state.participants if p.type == "player"}
    return {
        m.player_id: replace(m.concentration, combat_id=state.combat_id, started_round=state.round_number)
        for m in session.party.members
        if m.player_id in roster and m.concentration.is_active
    }


def adopt(session: SessionData, updates: dict[str, ConcentrationState]) -> None:
    for pid, record in updates.items():
        session.member_state(pid).concentration = record


def _duration(spell_id: str) -> int:
    seconds = spells.get_spell(spell_id).concentration_duration_seconds
    if seconds is None:
        raise ValueError(f"Active concentration spell {spell_id!r} has no duration")
    return seconds


async def settle_combat(
    session: SessionData, state: CombatState, *, conn: asyncpg.Connection, ended: bool = False
) -> tuple[dict[str, ConcentrationState], list[dict[str, str]]]:
    updates: dict[str, ConcentrationState] = {}
    expired: list[dict[str, str]] = []
    for member in sorted(session.party.members, key=lambda m: m.player_id):
        current = member.concentration
        if current.combat_id != state.combat_id:
            continue
        spell_id = current.spell_id
        assert spell_id is not None and current.started_round is not None
        elapsed = concentration.elapsed_in_round(current, state.round_number)
        limit = _duration(spell_id)
        if max(elapsed, 60 if ended else 0) >= limit:
            await end_concentration(session, member.player_id, combat_state=state, conn=conn, updates=updates)
            expired.append({"caster_id": member.player_id, "spell_id": spell_id})
        elif ended:
            record = ConcentrationState(spell_id, elapsed)
            await db_mutations_concentration.update_player_concentration(member.player_id, record, conn=conn)
            updates[member.player_id] = record
    return updates, expired


async def settle_time(
    session: SessionData, players: dict[str, dict], seconds: int, *, conn: asyncpg.Connection, long_rest: bool = False
) -> tuple[dict[str, ConcentrationState], list[dict[str, str]]]:
    updates: dict[str, ConcentrationState] = {}
    expired: list[dict[str, str]] = []
    for pid, player in sorted(players.items()):
        current = ConcentrationState.from_record(player.get("concentration"))
        spell_id = current.spell_id
        if spell_id is None:
            continue
        elapsed = current.elapsed_seconds + seconds
        if long_rest or elapsed >= _duration(spell_id):
            await end_concentration(session, pid, combat_state=None, conn=conn, updates=updates, record=current)
            expired.append({"caster_id": pid, "spell_id": spell_id})
        else:
            record = replace(current, elapsed_seconds=elapsed)
            await db_mutations_concentration.update_player_concentration(pid, record, conn=conn)
            updates[pid] = record
    return updates, expired
