"""Artificer purification: escrow at launch, clean credit at worker completion."""

import json
import random
from datetime import UTC, datetime, timedelta

import asyncpg
from livekit.agents.llm import ToolError
from livekit.agents.voice import RunContext

import db
import db_mutations
import db_queries
import inventory_allocation
from inventory_refresh import publish_inventory
from session_data import SessionData
from training_rules import parse_activity_type_row


def utc_now() -> datetime:
    return datetime.now(UTC)


async def begin_purification(
    context: RunContext[SessionData], item_id: str | None, quantity: int | None, *, rng: random.Random | None = None
) -> str:
    context.disallow_interruptions()
    player_id = context.userdata.acting_player_id
    if not item_id or type(quantity) is not int or quantity < 1:
        raise ToolError("Purification requires an item_id and an integer quantity of at least 1.")
    async with db.transaction() as conn:
        player = await db_queries.get_player(player_id, conn=conn, for_update=True)
        if not player or player.get("class") != "artificer":
            raise ToolError("Only an Artificer can begin purification.")
        try:
            inventory_allocation.purification_output(item_id)
        except ValueError as error:
            raise ToolError(str(error)) from error
        row = await conn.fetchrow(
            "SELECT COALESCE((data->>'quantity')::int,1) AS quantity FROM player_inventory "
            "WHERE player_id=$1 AND item_id=$2 AND tainted=true FOR UPDATE",
            player_id,
            item_id,
        )
        if row is None or quantity > row["quantity"]:
            raise ToolError("Purification quantity exceeds held tainted stock.")
        raw = await conn.fetchval("SELECT data FROM training_activity_types WHERE id='skill_practice'")
        if raw is None:
            raise ValueError("Missing skill_practice training duration")
        duration = parse_activity_type_row("skill_practice", json.loads(raw)).duration
        r = rng or random.Random()
        seconds = sum(
            r.randint(duration.first_half_min, duration.first_half_max)
            + r.randint(duration.second_half_min, duration.second_half_max)
            for _ in range(3)
        )
        now = utc_now()
        resolve_at = now + timedelta(seconds=seconds)
        remaining = row["quantity"] - quantity
        if remaining:
            await conn.execute(
                "UPDATE player_inventory SET data=jsonb_set(data,'{quantity}',$3::jsonb) "
                "WHERE player_id=$1 AND item_id=$2 AND tainted=true",
                player_id,
                item_id,
                json.dumps(remaining),
            )
        else:
            await conn.execute(
                "DELETE FROM player_inventory WHERE player_id=$1 AND item_id=$2 AND tainted=true", player_id, item_id
            )
        activity_id = await db_mutations.create_async_activity(
            player_id,
            {
                "activity_type": "purification",
                "status": "in_progress",
                "start_time": now.isoformat(),
                "resolve_at": resolve_at.isoformat(),
                "parameters": {"item_id": item_id, "quantity": quantity},
            },
            conn=conn,
        )
        context.userdata.validate_acting_player(player_id)
    await publish_inventory(context.userdata, player_id)
    return json.dumps({"activity_id": activity_id, "resolve_at": resolve_at.isoformat()})


def purification_outcome(activity: dict) -> dict:
    params = activity["parameters"]
    return {
        "item_id": inventory_allocation.purification_output(params["item_id"]),
        "quantity": params["quantity"],
        "tier": "success",
        "decision_options": [{"id": "collect", "label": "Acknowledge purification"}],
        "narrative_context": {"source_item_id": params["item_id"], "quantity": params["quantity"]},
    }


async def credit_purification(conn: asyncpg.Connection, activity: dict, outcome: dict) -> None:
    params = activity["parameters"]
    outcome["item_id"] = await inventory_allocation.credit_clean(
        conn,
        activity["player_id"],
        params["item_id"],
        params["quantity"],
    )
    await db_mutations.update_activity(activity["id"], {"outcome": outcome}, conn=conn)
