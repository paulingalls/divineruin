"""Trigger patron gifts on floored damage before resolving zero HP."""

from typing import TYPE_CHECKING

import db_queries
from combat_down import is_terminally_down, revive
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
DAWNS_EMBRACE = "orenthel_dawns_embrace"


def death_ward_ready(player: dict) -> bool:
    return _gift_ready(player, DEATH_WARD)


def _gift_ready(player: dict, gift_id: str) -> bool:
    patron, required, ability = catalog()[gift_id]
    favor = player.get("divine_favor") or {}
    return (
        favor.get("patron") == patron
        and blocking_reason(ability, get_patron_tier(favor), required, spent_state(player, gift_id)["spent"]) is None
    )


def _embrace_transition(target: CombatParticipant, hp_before: int, hp_after: int) -> bool:
    return target.is_ally and hp_before > 0 and hp_after == 0


def _donor_ids(session: SessionData, target: CombatParticipant) -> list[str]:
    return sorted(set(session.present_member_ids) - {target.id})


async def lock_damage_players(
    session: SessionData, target_id: str | None, *, queries, conn: "Connection | None"
) -> dict[str, dict]:
    if conn is None:
        raise ValueError("Damage gift locks require a transaction connection")
    ids = set(session.present_member_ids)
    if target_id is not None:
        ids.add(target_id)
    players = await queries.get_players_for_update(sorted(ids), conn=conn)
    missing = ids - players.keys() - {target_id}
    if missing:
        raise ValueError(f"Missing authoritative players: {sorted(missing)}")
    return players


async def lock_lethal_damage_players(
    session: SessionData,
    target: CombatParticipant,
    hp_before: int,
    *,
    queries,
    conn: "Connection | None",
) -> dict[str, dict] | None:
    if not _embrace_transition(target, hp_before, target.hp_current) or not _donor_ids(session, target):
        return None
    return await lock_damage_players(
        session, target.id if target.type == "player" else None, queries=queries, conn=conn
    )


def _embrace_hp(target: CombatParticipant) -> int:
    return max(1, target.hp_max // 2)


async def _embrace_donor(
    session: SessionData,
    state: "CombatState",
    target: CombatParticipant,
    *,
    players: dict[str, dict] | None,
    queries,
    conn: "Connection | None",
) -> tuple[str, str] | None:
    for player_id in _donor_ids(session, target):
        if players is not None and player_id not in players:
            continue
        participant = state.get_participant(player_id)
        if participant is not None and (participant.type != "player" or is_terminally_down(participant)):
            continue
        player = players.get(player_id) if players is not None else await queries.get_player(player_id, conn=conn)
        if not isinstance(player, dict):
            raise ValueError(f"Missing authoritative player {player_id!r}")
        if _gift_ready(player, DAWNS_EMBRACE):
            return player_id, participant.name if participant is not None else player["name"]
    return None


async def trigger_dawns_embrace(
    session: SessionData,
    state: "CombatState | None",
    target: CombatParticipant,
    hp_before: int,
    *,
    players: dict[str, dict] | None,
    queries,
    conn: "Connection | None",
) -> dict:
    if not _embrace_transition(target, hp_before, target.hp_current) or players is None:
        return {}
    if state is None:
        raise ValueError("Dawn's Embrace requires the working combat state")
    donor = await _embrace_donor(session, state, target, players=players, queries=queries, conn=conn)
    if donor is None:
        return {}
    donor_id, donor_name = donor
    await write_state(donor_id, {"spent": True}, gift_id=DAWNS_EMBRACE, conn=conn)
    revive(target, _embrace_hp(target))
    return {
        "gift_triggered": "Dawn's Embrace",
        "gift_owner": {"id": donor_id, "name": donor_name},
        "gift_target": {"id": target.id, "name": target.name},
        "dm_cue": f"Dawn's Embrace carries {target.name} back to their feet through {donor_name}.",
    }


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
    session: SessionData, state: "CombatState", target_id: str, result: "AttackResult", queries=db_queries, *, conn
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
        if _embrace_transition(target, target.hp_current, result.target_hp_remaining) and await _embrace_donor(
            session, state, target, players=None, queries=queries, conn=conn
        ):
            return with_landed_damage(result, result.damage, target.hp_current, hp_floor=_embrace_hp(target))
    return result


async def trigger_damage_gifts(
    session: SessionData,
    state: "CombatState | None",
    target: CombatParticipant,
    hp_before: int,
    *,
    players: dict[str, dict] | None,
    queries=db_queries,
    conn=None,
) -> dict:
    player = players[target.id] if players is not None and target.type == "player" else None
    ward = await trigger_death_ward(target, hp_before, player=player, queries=queries, conn=conn)
    if ward:
        return ward
    embrace = await trigger_dawns_embrace(
        session, state, target, hp_before, players=players, queries=queries, conn=conn
    )
    if embrace:
        return embrace
    if player is None and target.type == "player" and not target.iron_resolve_spent:
        member = session.member_state(target.id)
        if member.patron_id == "kaelen":
            player = await queries.get_player(target.id, conn=conn)
    gift = trigger_iron_resolve(session, target, hp_before, player)
    return {"gift_triggered": gift} if gift else {}
