"""Settle Valdris's Oath of Justice against the facts of a committed attack."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from combat_resolution import SURRENDER_THRESHOLD
from conditions import has_condition
from oaths import JusticeOath, OathBook, ValdrisBreach
from patron_synergy import has_engine_synergy

if TYPE_CHECKING:
    from asyncpg import Connection

    from combat_participant import CombatParticipant
    from combat_state import CombatState
    from session_data import SessionData

CLAUSE = "valdris_oath_breach"
BROKEN_REASON = "Your Oath of Justice is broken for this session."


def breach_marker(player: dict) -> ValdrisBreach | None:
    marker = player.get("oaths", {}).get("valdris_breach")
    return None if marker is None else ValdrisBreach.model_validate(marker)


def suppressed(player: dict) -> bool:
    marker = breach_marker(player)
    return marker is not None and marker.session_id == player.get("oath_session_id")


def active_justice(book: OathBook) -> JusticeOath | None:
    return next(
        (record for record in book.records if isinstance(record, JusticeOath) and record.status == "active"),
        None,
    )


def evaluate(state: CombatState, attacker: CombatParticipant, target: CombatParticipant) -> list[str]:
    if attacker.type != "player" or has_condition(attacker.conditions, "charmed"):
        return []
    if target.is_ally:
        return ["strike_yielded_ally"] if target.yielded else []
    if target.is_structure:
        return []
    terms = []
    if target.id not in state.first_hostility:
        terms.append("strike_first")
    if state.deescalation_scene.cumulative_shift.get(target.id, 0) >= SURRENDER_THRESHOLD:
        terms.append("strike_surrendered_enemy")
    return terms


async def enter_session(player_id: str, player: dict, session_id: str, *, conn: Connection) -> None:
    if breach_marker(player) is not None and player.get("oath_session_id") != session_id:
        await conn.execute(
            "UPDATE players SET data = jsonb_set(data, '{oath_session_id}', to_jsonb($2::text)) WHERE player_id = $1",
            player_id,
            session_id,
        )


async def settle(
    session: SessionData,
    state: CombatState,
    attacker: CombatParticipant,
    target: CombatParticipant,
    *,
    conn: Connection,
    queries: Any,
) -> dict | None:
    terms = evaluate(state, attacker, target)
    if not terms:
        return None
    actor = attacker.id
    player = await queries.get_player(actor, conn=conn, for_update=True)
    if player is None or "oaths" not in player:
        return None
    book = OathBook.from_player(player, actor)
    oath = active_justice(book)
    if oath is None or not has_engine_synergy(player, CLAUSE):
        return None

    event_id = f"oath_event_{uuid4().hex}"
    oath.status = "broken"
    oath.latest_state_change_event_id = event_id
    if book.valdris_breach is None or book.valdris_breach.session_id != session.session_id:
        book.valdris_breach = ValdrisBreach(
            session_id=session.session_id,
            breach_event_id=event_id,
            combat_id=state.combat_id,
            round_number=state.round_number,
        )
    await conn.execute(
        "UPDATE players SET data = data || $2::jsonb WHERE player_id = $1",
        actor,
        json.dumps({"oaths": book.model_dump(), "oath_session_id": session.session_id}),
    )
    return {"oath_id": oath.id, "terms": terms, "breach_event_id": event_id, "layer_3_suppressed": True}
