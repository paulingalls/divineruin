import asyncio
import json
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, nullcontext
from uuid import uuid4

from acceptance.first_episode_harness import EpisodeModel
from acceptance.seeds import seed_gold, seed_player
from livekit.agents import AgentSession, llm
from sample_fixtures import make_mock_room

import db
import db_mutations
import db_mutations_merchant
import event_types as E
from inventory_pools import InventoryPool, get_inventory_pools
from party_state import PartyState
from session_data import SessionData

FORGE = "accord_forge"
GRIMJAW = "grimjaw_blacksmith"
SWORD = "shortsword_basic"
MAREN = "innkeeper_maren"
INN = "millhaven_inn"
SALE_EVENTS = (E.CURRENCY_GAINED, E.INVENTORY_UPDATED)


async def wait_for_merchant_readers(count: int) -> None:
    pool = await db.get_pool()
    async with asyncio.timeout(10):
        while (
            await pool.fetchval("""
            SELECT count(DISTINCT l.pid) FROM pg_locks l JOIN pg_stat_activity a USING (pid)
            WHERE NOT l.granted AND a.datname=current_database() AND a.query LIKE '%merchant_state%'
        """)
            < count
        ):
            await asyncio.sleep(0.02)


async def stock(player_id: str, item: str, quantity: int, *, tainted: bool = False, equipped: bool = False) -> None:
    pool = await db.get_pool()
    await pool.execute(
        "INSERT INTO player_inventory (player_id,item_id,tainted,data) VALUES ($1,$2,$3,$4::jsonb)",
        player_id,
        item,
        tainted,
        json.dumps({"quantity": quantity, "equipped": equipped, "source": "fixture"}),
    )


async def rows(player_id: str) -> tuple[dict, dict]:
    pool = await db.get_pool()
    player = await pool.fetchrow("SELECT data, inventory_revision FROM players WHERE player_id=$1", player_id)
    inventory = await pool.fetch(
        "SELECT item_id, tainted, data FROM player_inventory WHERE player_id=$1 ORDER BY item_id, tainted", player_id
    )
    return {**json.loads(player["data"]), "inventory_revision": player["inventory_revision"]}, {
        (row["item_id"], row["tainted"]): json.loads(row["data"]) for row in inventory
    }


async def merchant_row(npc: str) -> tuple[dict, object, object] | None:
    pool = await db.get_pool()
    row = await pool.fetchrow("SELECT data, created_at, updated_at FROM merchant_state WHERE npc_id=$1", npc)
    return (json.loads(row["data"]), row["created_at"], row["updated_at"]) if row else None


async def fund_merchant(npc: str, allocation: int, *, legacy: bool = False, **overrides: object) -> None:
    pool = await db.get_pool()
    state = {
        "current_inventory": {},
        "current_gold_sp": allocation,
        "max_gold_sp": allocation,
        "last_restock_day": db_mutations_merchant.aethos_today(),
        "buyback_history": {},
        "consigned_items": [],
        **overrides,
    }
    if legacy:
        del state["current_inventory"]
    await pool.execute("INSERT INTO merchant_state(npc_id, data) VALUES ($1, $2::jsonb)", npc, json.dumps(state))


@asynccontextmanager
async def catalog_override(item: str, **changes: bool | int) -> AsyncIterator[None]:
    pool = await db.get_pool()
    original = await pool.fetchval("SELECT data FROM items WHERE id=$1", item)
    redis = await db.get_redis()
    key = os.environ.get("CONTENT_CACHE_PREFIX", "") + f"item:{item}"
    try:
        await pool.execute("UPDATE items SET data=data || $2::jsonb WHERE id=$1", item, json.dumps(changes))
        await redis.delete(key)
        yield
    finally:
        await pool.execute("UPDATE items SET data=$2::jsonb WHERE id=$1", item, original)
        await redis.delete(key)


@asynccontextmanager
async def pool_override(pool_id: str, **changes: object) -> AsyncIterator[InventoryPool]:
    pool = await db.get_pool()
    original = await pool.fetchval("SELECT data FROM inventory_pools WHERE id=$1", pool_id)
    try:
        await pool.execute(
            "UPDATE inventory_pools SET data=data || $2::jsonb WHERE id=$1", pool_id, json.dumps(changes)
        )
        async with db.transaction() as conn:
            catalog = await get_inventory_pools(conn=conn)
        yield catalog[pool_id]
    finally:
        await pool.execute("UPDATE inventory_pools SET data=$2::jsonb WHERE id=$1", pool_id, original)


@asynccontextmanager
async def location_override(location: str, **changes: str) -> AsyncIterator[None]:
    pool = await db.get_pool()
    redis = await db.get_redis()
    key = os.environ.get("CONTENT_CACHE_PREFIX", "") + f"location:{location}"
    original = await pool.fetchval("SELECT data FROM locations WHERE id=$1", location)
    try:
        await pool.execute("UPDATE locations SET data=data || $2::jsonb WHERE id=$1", location, json.dumps(changes))
        await redis.delete(key)
        yield
    finally:
        await pool.execute("UPDATE locations SET data=$2::jsonb WHERE id=$1", location, original)
        await redis.delete(key)


@asynccontextmanager
async def audit_merchant_updates() -> AsyncIterator[None]:
    pool = await db.get_pool()
    await pool.execute("""
        CREATE TABLE merchant_updates (npc_id text NOT NULL);
        CREATE FUNCTION audit_merchant_update() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            INSERT INTO merchant_updates VALUES (NEW.npc_id);
            RETURN NEW;
        END
        $$;
        CREATE TRIGGER audit_merchant_update AFTER UPDATE ON merchant_state
        FOR EACH ROW EXECUTE FUNCTION audit_merchant_update();
    """)
    try:
        yield
    finally:
        await pool.execute("""
            DROP TRIGGER audit_merchant_update ON merchant_state;
            DROP FUNCTION audit_merchant_update();
            DROP TABLE merchant_updates;
        """)


async def merchant_updates(npc: str) -> int:
    pool = await db.get_pool()
    return await pool.fetchval("SELECT count(*) FROM merchant_updates WHERE npc_id=$1", npc)


@asynccontextmanager
async def merchant_scope(npc: str) -> AsyncIterator[None]:
    pool = await db.get_pool()
    assert await merchant_row(npc) is None
    try:
        yield
    finally:
        await pool.execute("DELETE FROM merchant_state WHERE npc_id=$1", npc)


class SaleSession:
    def __init__(self, player_id: str, primary_id: str, location: str) -> None:
        self.player_id, self.primary_id = player_id, primary_id
        room = make_mock_room()
        room.isconnected.return_value = True
        room.local_participant.publish_data.side_effect = self.capture_packet
        self.data = SessionData(player_id=primary_id, location_id=location, world_time="daytime", room=room)
        if player_id != primary_id:
            self.data.party.members.append(PartyState.solo(player_id).primary)
        self.model = EpisodeModel([])
        self.session = AgentSession(userdata=self.data, llm=self.model)
        self.packets: list[dict] = []
        self.publications: list[tuple[dict, tuple[dict, dict]]] = []
        self.inventory_destinations: dict[str, object] = {}

    async def capture_packet(self, payload: bytes, **kwargs: object) -> None:
        packet = json.loads(payload)
        self.packets.append(packet)
        if packet["type"] == E.INVENTORY_UPDATED:
            self.inventory_destinations[packet["player_id"]] = kwargs.get("destination_identities")
        if packet["type"] in SALE_EVENTS:
            self.publications.append((packet, await rows(packet["player_id"])))

    async def sell(self, item: str, npc: str, quantity: int, offer_id: str = "") -> llm.FunctionCallOutput:
        return await self.command("sell_item", item_id=item, npc_id=npc, quantity=quantity, offer_id=offer_id)

    async def ledger(self, npc: str) -> llm.FunctionCallOutput:
        return await self.command("query_merchant_ledger", npc_id=npc)

    async def collect(self, npc: str, consignment_id: str) -> llm.FunctionCallOutput:
        return await self.command("collect_consignment", npc_id=npc, consignment_id=consignment_id)

    async def command(self, name: str, **arguments: str | int) -> llm.FunctionCallOutput:
        self.model.commands.append((name, arguments))
        with self.data._bind_authenticated_actor(self.player_id, 1, lambda *_: None):
            await self.session.run(user_input="I'd like to trade.")
        receipt = list(self.model.receipts.values())[-1]
        assert receipt.name == name
        return receipt


@asynccontextmanager
async def merchant_session(
    *,
    location: str = FORGE,
    npc: str = GRIMJAW,
    item: str = SWORD,
    held: int = 2,
    disposition: str | None = "neutral",
    equipped: bool = False,
    tainted: int = 0,
    guest: bool = False,
    own_merchant: bool = True,
) -> AsyncIterator[SaleSession]:
    from merchant_agent import MerchantAgent

    pool = await db.get_pool()
    pid = f"sale_{uuid4().hex}"
    primary = f"sale_{uuid4().hex}" if guest else pid
    try:
        for player_id in dict.fromkeys((pid, primary)):
            await seed_player(pool, player_id=player_id, location_id=location)
            await seed_gold(pool, player_id, 7)
        if disposition is not None:
            await db_mutations.set_npc_disposition(npc, pid, disposition, "fixture", conn=pool)
        if held:
            await stock(pid, item, held, equipped=equipped)
        if tainted:
            await stock(pid, item, tainted, tainted=True)
        sale = SaleSession(pid, primary, location)
        async with merchant_scope(npc) if own_merchant else nullcontext():
            try:
                await sale.session.start(MerchantAgent())
                yield sale
            finally:
                await sale.session.aclose()
    finally:
        await pool.execute("DELETE FROM players WHERE player_id=ANY($1)", list({pid, primary}))
