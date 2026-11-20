"""Trigger patron gifts on floored damage before resolving zero HP."""

from typing import TYPE_CHECKING

import db_queries
from combat_participant import CombatParticipant
from kaelen_gift import trigger_iron_resolve
from patron_ability_tools import blocking_reason, catalog, spent_state
from patron_favor import get_patron_tier
from patron_gift_tools import write_state
from session_data import SessionData

if TYPE_CHECKING:
    from asyncpg import Connection

    from check_resolution_attack import AttackResult
    from combat_state import CombatState

DEATH_WARD = "mortaen_death_ward"


def death_ward_ready(player: dict) -> bool:
    patron, required, ability = catalog()[DEATH_WARD]
    favor = player.get("divine_favor") or {}
    return (
        favor.get("patron") == patron
        and blocking_reason(ability, get_patron_tier(favor), required, spent_state(player, DEATH_WARD)["spent"]) is None
    )


def _drops_to_zero(target: CombatParticipant, hp_before: int, hp_after: int) -> bool:
    return target.type == "player" and hp_before > 0 and hp_after == 0


async def trigger_death_ward(
    target: CombatParticipant,
    hp_before: int,
    *,
    player: dict | None,
    queries=db_queries,
    conn: "Connection | None",
) -> dict:
    if not _drops_to_zero(target, hp_before, target.hp_current):
        return {}
    if player is None:
        player = await queries.get_player(target.id, for_update=True, conn=conn)
    if not isinstance(player, dict):
        raise ValueError(f"Missing authoritative player {target.id!r}")
    if not death_ward_ready(player):
        return {}
    await write_state(target.id, {"spent": True}, gift_id=DEATH_WARD, conn=conn)
    target.hp_current = 1
    return {
        "gift_triggered": "Death Ward",
        "gift_owner": {"id": target.id, "name": target.name},
        "dm_cue": "Mortaen decides when you cross.",
    }


async def provisional_ward_verdict(
    state: "CombatState", target_id: str, result: "AttackResult", queries=db_queries, *, conn
) -> "AttackResult":
    from combat_damage_affinity import with_landed_damage

    if result.context == "killing_blow":
        target = state.get_participant(target_id)
        assert target is not None
        if _drops_to_zero(target, target.hp_current, result.target_hp_remaining):
            # The phase transaction's own connection sees a ward an earlier packet spent but has not committed.
            player = await queries.get_player(target.id, conn=conn)
            if not isinstance(player, dict):
                raise ValueError(f"Missing authoritative player {target.id!r}")
            if death_ward_ready(player):
                return with_landed_damage(result, result.damage, target.hp_current, hp_floor=1)
    return result


async def trigger_damage_gifts(
    session: SessionData,
    target: CombatParticipant,
    hp_before: int,
    *,
    player: dict | None = None,
    queries=db_queries,
    conn=None,
) -> dict:
    ward = await trigger_death_ward(target, hp_before, player=player, queries=queries, conn=conn)
    if ward:
        return ward
    if player is None and target.type == "player" and not target.iron_resolve_spent:
        member = session.member_state(target.id)
        if member.patron_id == "kaelen":
            player = await queries.get_player(target.id, conn=conn)
    gift = trigger_iron_resolve(session, target, hp_before, player)
    return {"gift_triggered": gift} if gift else {}
