"""Evaluate the Oath of Justice against a single roll's context."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Any

from livekit.agents.llm import ToolError

import combat_wrongdoing
import oath_breach
from oaths import JusticeOath, OathBook
from patron_synergy import has_engine_synergy

if TYPE_CHECKING:
    from asyncpg import Connection

    from check_resolution_save import SavingThrowResult
    from combat_participant import CombatParticipant
    from combat_state import CombatState
    from session_data import SessionData

CLAUSE = "valdris_justice_at_stake"
TAG = "justice_at_stake"
BONUS = 2


def eligibility(player: dict, player_id: str) -> tuple[str | None, str | None]:
    book = OathBook.from_player(player, player_id)
    active = oath_breach.active_justice(book)
    oath = active or next((record for record in reversed(book.records) if isinstance(record, JusticeOath)), None)
    oath_id = oath.id if oath is not None else None
    if (player.get("divine_favor") or {}).get("patron") != "valdris" or player["class"] != "paladin":
        return oath_id, "unheld"
    if not has_engine_synergy(player, CLAUSE):
        return oath_id, "inactive_clause"
    if oath_breach.suppressed(player):
        return oath_id, "suppressed"
    if active is None:
        return oath_id, "no_oath" if oath is None else "inactive_oath"
    return oath_id, None


async def wrongdoer(
    session: SessionData,
    state: CombatState,
    player: dict,
    player_id: str,
    subject_id: str,
    *,
    queries: Any,
    conn: Connection | None,
) -> str | None:
    evidence = await combat_wrongdoing.wrongdoing(
        session, player, player_id=player_id, target_id=subject_id, combat_state=state, conn=conn, queries_mod=queries
    )
    if evidence is not None:
        return evidence["source"]
    if subject_id in state.encounter_facts["yielded_ally_attackers"]:
        return "yielded_ally"
    testimony = state.testimony
    if testimony is not None and subject_id in testimony.accused:
        present = await queries.get_npcs_at_location(state.location_id, conn=conn)
        if any(npc["id"] == testimony.witness for npc in present):
            return "testimony"
    return None


async def attack_receipt(
    session: SessionData,
    state: CombatState | None,
    attacker: CombatParticipant,
    target: CombatParticipant,
    player: dict | None,
    *,
    queries: Any,
    conn: Connection | None,
) -> dict | None:
    if attacker.type != "player" or player is None:
        return None
    oath_id, reason = eligibility(player, attacker.id)
    if oath_id is None and reason == "unheld":
        return None
    receipt = {"oath_id": oath_id, "context": "attack", "target_id": target.id, "modifier": 0}
    if state is None:
        return {**receipt, "reason": "outside_combat"}
    if state.get_participant(target.id) is None:
        raise ToolError(f"Unknown target: {target.id}")
    if reason is None:
        if oath_breach.evaluate(state, attacker, target):
            return {**receipt, "reason": "breaking_oath"}
        evidence = await wrongdoer(session, state, player, attacker.id, target.id, queries=queries, conn=conn)
        if evidence is not None:
            return {**receipt, "modifier": BONUS, "reason": evidence}
    return {**receipt, "reason": reason or "no_wrongdoer"}


def skill_receipt(player: dict, player_id: str, skill: str, *, in_combat: bool, auto_fail: bool) -> dict:
    oath_id, reason = eligibility(player, player_id)
    reason = reason or ("in_combat" if in_combat else "automatic_failure" if auto_fail else None)
    return {
        "oath_id": oath_id,
        "context": "skill",
        "skill": skill,
        "tag": TAG,
        "modifier": BONUS if reason is None else 0,
        "reason": reason or "applied",
    }


async def prepare_save(
    session: SessionData,
    state: CombatState | None,
    roller_id: str,
    result: SavingThrowResult,
    effect: str,
    *,
    queries: Any,
    conn: Connection | None,
    player: dict | None = None,
) -> SavingThrowResult:
    from check_resolution_save import _save_result

    source_id = result.originating_participant_id
    if state is not None:
        if source_id is not None and state.get_participant(source_id) is None:
            raise ToolError(f"Unknown save source: {source_id}")
        roller = state.get_participant(roller_id)
        if roller is None or roller.type != "player" or roller.archetype_id not in (None, "paladin"):
            return result
    if player is None:
        player = await queries.get_player(roller_id, conn=conn)
        if player is None:
            raise ToolError(f"Player '{roller_id}' not found")
    oath_id, reason = eligibility(player, roller_id)
    if oath_id is None and reason == "unheld":
        return result
    modifier = 0
    if state is None:
        reason = "outside_combat"
    elif source_id is None:
        reason = "missing_source"
    elif result.d20 is None:
        reason = "automatic_failure"
    elif reason is None:
        evidence = await wrongdoer(session, state, player, roller_id, source_id, queries=queries, conn=conn)
        modifier = BONUS if evidence is not None else 0
        reason = evidence or "no_wrongdoer"
    receipt = {
        "oath_id": oath_id,
        "context": "save",
        "source_id": source_id,
        "modifier": modifier,
        "reason": reason,
    }
    result = replace(result, oath_justice=receipt)
    if not modifier:
        return result
    assert result.d20 is not None
    d20 = replace(result.d20, modifier=result.d20.modifier + modifier)
    return _save_result(replace(result, d20=d20, modifier=d20.modifier), d20.evaluate(result.roll), effect)
