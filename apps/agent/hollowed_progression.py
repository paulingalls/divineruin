"""Long-rest progression and cleansing for Hollowed."""

import asyncpg

import db
import db_mutations_conditions
import db_mutations_resurrection
import db_queries
from attribute_increase_persistence import patch_player
from attribute_increases import recompute_pools
from condition_restrictions import stat_drain
from conditions import hollowed_stage, remove_condition


def advance_hollowed_on_long_rest(conditions: list[dict] | None) -> list[dict] | None:
    """Return replacement conditions for a bearer entering the next stage, or None if nothing changes."""
    active = conditions or []
    stage = hollowed_stage(active)
    if stage not in (1, 2):
        return None
    return [{**row, "type": "hollowed", "stage": stage + 1} if row["type"] == "hollowed" else row for row in active]


async def drain_hollowed_on_long_rest(player_id: str, player: dict, *, conn: asyncpg.Connection) -> dict | None:
    active = player.get("conditions") or []
    if not stat_drain(active):
        return None
    wisdom = player["attributes"]["wisdom"]
    loss = min(1, wisdom - 1)
    if loss <= 0:
        return None

    remaining = wisdom - loss
    await _change_wisdom(player_id, player, -loss, conn=conn, refill=True)
    updated = [
        {**row, "wis_drained": row.get("wis_drained", 0) + loss} if row["type"] == "hollowed" else row for row in active
    ]
    await db_mutations_conditions.save_player_conditions(player_id, updated, conn=conn)
    return {
        "attribute": "wisdom",
        "drained": loss,
        "wisdom_after": remaining,
        "narration_cue": "Tell the player that the Hollowed condition drained 1 Wisdom during the rest.",
    }


async def cleanse_hollowed(
    player_id: str,
    player: dict,
    *,
    conn: asyncpg.Connection | asyncpg.Pool | None,
    mutations=db_mutations_resurrection,
    conditions_mutations=db_mutations_conditions,
) -> bool:
    """Clear Hollowed and return its Wisdom loss, up to the attribute cap."""
    active = player.get("conditions") or []
    hollowed = next((row for row in active if row["type"] == "hollowed"), None)
    if hollowed is None:
        return False
    drained = hollowed.get("wis_drained", 0)
    if drained:
        conn = conn or await db.get_pool()
        current = await db_queries.get_player(player_id, conn=conn)
        if current is None:
            raise ValueError(f"Missing Hollowed player {player_id}")
        restored = min(drained, 20 - current["attributes"]["wisdom"])
        if restored > 0:
            await _change_wisdom(player_id, current, restored, conn=conn, mutations=mutations)
    await conditions_mutations.save_player_conditions(player_id, remove_condition(active, "hollowed"), conn=conn)
    return True


async def _change_wisdom(
    player_id: str,
    player: dict,
    delta: int,
    *,
    conn: asyncpg.Connection | asyncpg.Pool,
    refill: bool = False,
    mutations=db_mutations_resurrection,
) -> None:
    attributes = {**player["attributes"], "wisdom": player["attributes"]["wisdom"] + delta}
    pools = recompute_pools({**player, "attributes": attributes}, refill=refill)
    await mutations.apply_attribute_penalty(player_id, "wisdom", delta, conn=conn)
    if pools:
        await patch_player(player_id, pools, conn=conn)
