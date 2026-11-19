"""Advance the Still's hour and day boundaries on a locked player row."""

from collections.abc import Callable
from dataclasses import dataclass

import asyncpg

import check_resolution_save
import db
import db_mutations
import db_mutations_resurrection
import db_queries
import dice
import resurrection
import still_charm
from attribute_increase_events import publish_snapshots
from combat_events import isolated_publish
from session_data import SessionData

TIMER_FALLBACK_SECS = 30.0
MAX_COUNTED_GAP_SECS = 3 * TIMER_FALLBACK_SECS
REAL_SECONDS_PER_ZONE_HOUR = 120.0
HOURS_PER_ZONE_DAY = 24
PARADISE_TRAP_DC = 18


@dataclass(frozen=True)
class Drain:
    fact: str
    anchor: str | None


async def _drain(player_id: str, player: dict, conn: asyncpg.Connection) -> Drain:
    attribute = resurrection.highest_attribute(player["attributes"])
    loss = dice.roll("1d4").total
    score = player["attributes"][attribute] - loss
    await db_mutations_resurrection.apply_attribute_penalty(player_id, attribute, -loss, conn=conn)
    fact = f"{player.get('name') or player_id} loses {loss} {attribute} to the Still, leaving a score of {score}."
    if not resurrection.is_attribute_depleted({**player["attributes"], attribute: score}):
        return Drain(fact, None)

    updated = await db_queries.get_player(player_id, conn=conn)
    if updated is None:
        raise ValueError(f"Missing Still drain target {player_id}")
    death = await resurrection.resurrect_on_defeat({**updated, "player_id": player_id}, combat_cleared=False, conn=conn)
    anchor = death["anchor"]
    fact += (
        f" The character died and Mortaen returned them at {anchor} with {death['revive_hp']} HP."
        f" Death count {death['death_count']}, cost tier {death['tier']}."
    )
    return Drain(fact, anchor)


async def _advance_member(
    sd: SessionData, player_id: str, now: Callable[[], float], *, checkpoint_only: bool
) -> Drain | None:
    candidate = await db_queries.get_player(player_id)
    if not candidate or still_charm.key(candidate.get("location_id", "")) not in candidate.get("flags", {}):
        return None

    async with db.transaction() as conn:
        player = await db_queries.get_player(player_id, for_update=True, conn=conn)
        if player is None or player_id not in sd.present_member_ids:
            return None
        location = player["location_id"]
        charm = still_charm.read(player, player_id, location)
        if charm is None:
            return None

        timestamp = now()
        clock = still_charm.read_clock(player, player_id, location)
        if clock is None:
            clock = still_charm.DwellClock(checkpoint_at=timestamp, elapsed=0, saves=0)
        else:
            gap = timestamp - clock["checkpoint_at"]
            if gap <= 0:
                return None
            clock["checkpoint_at"] = timestamp
            if sd.in_combat or checkpoint_only or gap > MAX_COUNTED_GAP_SECS:
                gap = 0
            previous_hour = int(clock["elapsed"] // REAL_SECONDS_PER_ZONE_HOUR)
            clock["elapsed"] += gap
            hour = int(clock["elapsed"] // REAL_SECONDS_PER_ZONE_HOUR)
            if hour > previous_hour:
                if charm["kind"] == still_charm.SERENITYS_TOUCH or _resave(player, clock):
                    await still_charm.clear([player_id], location, conn=conn)
                    return None
                if hour % HOURS_PER_ZONE_DAY == 0:
                    drain = await _drain(player_id, player, conn)
                    if drain.anchor is None:
                        await still_charm.write_clock(player_id, location, clock, mutations=db_mutations, conn=conn)
                    return drain

        await still_charm.write_clock(player_id, location, clock, mutations=db_mutations, conn=conn)
    return None


def _resave(player: dict, clock: still_charm.DwellClock) -> bool:
    result = check_resolution_save.resolve_saving_throw(
        player, "wisdom", PARADISE_TRAP_DC, "charmed", bonus_dice_eligible=False, modifier_bonus=clock["saves"]
    )
    clock["saves"] += 1
    return result.success


async def advance(sd: SessionData, now: Callable[[], float], *, checkpoint_only: set[str]) -> str:
    facts = []
    for player_id in sd.present_member_ids:
        drain = await _advance_member(sd, player_id, now, checkpoint_only=player_id in checkpoint_only)
        if drain is None:
            continue
        if drain.anchor is not None and player_id == sd.primary_player_id:
            sd.location_id = drain.anchor
        sd.record_event(drain.fact)
        facts.append(drain.fact)
        with isolated_publish("Still absorption snapshot"):
            await publish_snapshots(sd, [player_id])
    return " ".join(facts)
