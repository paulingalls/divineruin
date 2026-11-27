"""Resolve Promised Hour against the time and facts of the working encounter."""

import json
from dataclasses import replace
from typing import TYPE_CHECKING, Literal
from uuid import uuid4

from check_resolution_save import SavingThrowResult, _save_result
from oaths import TIMED_NAME, OathBook, TimedOath
from patron_synergy import get_archetype_synergy, has_engine_clause

if TYPE_CHECKING:
    from asyncpg import Connection

    from combat_state import CombatState
    from session_data import SessionData

CLAUSE = "zhael_promised_hour"
BONUS = 1


def _active_clause() -> bool:
    row = get_archetype_synergy("paladin", "zhael")
    assert row is not None
    return has_engine_clause(row, CLAUSE)


def save_receipt(
    state: "CombatState | None",
    roller_id: str,
    player: dict,
    round_number: int | None,
    *,
    rolled: bool = True,
) -> dict | None:
    records = [oath for oath in OathBook.from_player(player, roller_id).records if isinstance(oath, TimedOath)]
    combat_id = state.combat_id if state is not None else None
    scoped = [oath for oath in records if oath.combat_id == combat_id]
    oath = next((oath for oath in reversed(scoped) if oath.status == "active"), None)
    oath = oath or next(reversed(scoped or records), None)
    if (player.get("divine_favor") or {}).get("patron") != "zhael" or player.get("class") != "paladin":
        if oath is None:
            return None
        reason = "unheld"
    elif not _active_clause():
        reason = "inactive_clause"
    elif oath is None:
        reason = "no_oath"
    elif oath.combat_id != combat_id:
        reason = "other_encounter"
    elif oath.status != "active":
        reason = "inactive_oath"
    else:
        assert round_number is not None
        if round_number > oath.last_round:
            reason = "past_deadline"
        else:
            reason = "active_objective" if rolled else "automatic_failure"
    return {
        "oath_id": oath.id if oath is not None else None,
        "synergy_clause_id": CLAUSE,
        "name": TIMED_NAME,
        "combat_id": combat_id,
        "round_number": round_number,
        "modifier": BONUS if reason == "active_objective" else 0,
        "reason": reason,
    }


def prepare_save(
    state: "CombatState | None",
    roller_id: str,
    result: SavingThrowResult,
    effect: str,
    *,
    player: dict | None,
    round_number: int | None,
) -> SavingThrowResult:
    if state is not None:
        round_number = state.round_number if round_number is None else round_number
        result = replace(result, combat_id=state.combat_id, round_number=round_number)
        roller = state.get_participant(roller_id)
        if roller is None or roller.type != "player":
            return result
    assert player is not None
    receipt = save_receipt(state, roller_id, player, round_number, rolled=result.d20 is not None)
    result = replace(result, oath_timed=receipt)
    if receipt is None or not receipt["modifier"]:
        return result
    assert result.d20 is not None
    d20 = replace(result.d20, modifier=result.d20.modifier + receipt["modifier"])
    return _save_result(replace(result, d20=d20, modifier=d20.modifier), d20.evaluate(result.roll), effect)


def owner_ids(state: "CombatState", session: "SessionData | None" = None) -> set[str]:
    ids = {p.id for p in state.participants if p.type in ("player", "temporary_hollowed")}
    for checkpoint in state.round_checkpoints:
        ids.update(checkpoint["players"])
    if session is not None:
        ids.update(session.party.member_ids)
    return ids


async def _books(conn: "Connection", ids: set[str], *, lock: bool = False) -> dict[str, OathBook]:
    sql = """
        SELECT player_id, (data->'oaths')::text AS oaths FROM players
        WHERE player_id = ANY($1::text[]) AND data ? 'oaths' ORDER BY player_id
    """
    if lock:
        if not conn.is_in_transaction():
            raise ValueError("Promised Hour settlement requires the combat transaction")
        sql += " FOR UPDATE"
    rows = await conn.fetch(sql, sorted(ids))
    return {
        row["player_id"]: OathBook.from_player({"oaths": json.loads(row["oaths"])}, row["player_id"]) for row in rows
    }


async def snapshot(conn: "Connection", state: "CombatState", session: "SessionData") -> dict[str, str]:
    books = await _books(conn, owner_ids(state, session))
    return {
        oath.id: oath.latest_state_change_event_id
        for book in books.values()
        for oath in book.records
        if isinstance(oath, TimedOath) and oath.combat_id == state.combat_id
    }


async def changes(
    conn: "Connection",
    state: "CombatState",
    session: "SessionData",
    before: dict[str, str],
) -> list[dict]:
    if not before:
        return []
    books = await _books(conn, owner_ids(state, session))
    return [
        {
            "oath_id": oath.id,
            "owner_id": oath.owner_id,
            "synergy_clause_id": CLAUSE,
            "name": TIMED_NAME,
            "old_status": "active",
            "new_status": oath.status,
            "reason": oath.transition_reason,
            "combat_id": oath.combat_id,
            "round_number": oath.transition_round,
            "event_id": oath.latest_state_change_event_id,
            "dm_cue": f"The {TIMED_NAME} oath is {'fulfilled' if oath.status == 'fulfilled' else 'over'}.",
        }
        for book in books.values()
        for oath in book.records
        if isinstance(oath, TimedOath) and oath.id in before and oath.latest_state_change_event_id != before[oath.id]
    ]


Transition = Literal["target_defeated", "ally_fell", "ally_stood", "deadline", "encounter_ended"]


async def close_round(
    state: "CombatState", *, conn: "Connection", round_number: int, session: "SessionData", terminal: bool
) -> None:
    await settle(state, conn=conn, reason="ally_stood", round_number=round_number, session=session)
    if not terminal:
        await settle(state, conn=conn, reason="deadline", round_number=round_number, session=session)


async def settle(
    state: "CombatState",
    *,
    conn: "Connection | None",
    reason: Transition,
    round_number: int,
    target_id: str | None = None,
    session: "SessionData | None" = None,
) -> None:
    if conn is None:
        raise ValueError("Promised Hour settlement requires the combat transaction")
    for owner, book in (await _books(conn, owner_ids(state, session), lock=True)).items():
        changed = False
        for index, oath in enumerate(book.records):
            if not isinstance(oath, TimedOath) or oath.status != "active" or oath.combat_id != state.combat_id:
                continue
            if reason == "target_defeated":
                if oath.objective_kind != "defeat_target" or oath.target_id != target_id:
                    continue
            elif reason == "ally_fell":
                if oath.objective_kind != "keep_ally_standing" or oath.target_id != target_id:
                    continue
            elif reason in ("ally_stood", "deadline"):
                objective = "keep_ally_standing" if reason == "ally_stood" else "defeat_target"
                if oath.objective_kind != objective or round_number != oath.last_round:
                    continue
            status = "fulfilled" if reason in ("target_defeated", "ally_stood") else "lapsed"
            book.records[index] = TimedOath.model_validate(
                {
                    **oath.model_dump(),
                    "status": status,
                    "transition_round": round_number,
                    "transition_reason": reason,
                    "latest_state_change_event_id": f"oath_event_{uuid4().hex}",
                }
            )
            changed = True
        if changed:
            await conn.execute(
                "UPDATE players SET data = jsonb_set(data, '{oaths}', $2::jsonb) WHERE player_id = $1",
                owner,
                book.model_dump_json(exclude_none=True),
            )
