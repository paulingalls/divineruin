import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, nullcontext
from uuid import uuid4

from acceptance.first_episode_harness import EpisodeModel
from acceptance.seeds import seed_gold, seed_player
from livekit.agents import AgentSession, llm
from sample_fixtures import make_mock_room

import db
import db_mutations
import event_types as E
from db_mutations_merchant import aethos_today
from party_state import PartyState
from session_data import SessionData

FORGE = "accord_forge"
GRIMJAW = "grimjaw_blacksmith"
SWORD = "shortsword_basic"
SALE_EVENTS = (E.CURRENCY_GAINED, E.INVENTORY_UPDATED)


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


async def fund_merchant(npc: str, allocation: int, **overrides: object) -> None:
    pool = await db.get_pool()
    state = {
        "current_gold_sp": allocation,
        "max_gold_sp": allocation,
        "last_restock_day": aethos_today(),
        "buyback_history": {},
        "consigned_items": [],
        **overrides,
    }
    await pool.execute("INSERT INTO merchant_state(npc_id, data) VALUES ($1, $2::jsonb)", npc, json.dumps(state))


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

    async def capture_packet(self, payload: bytes, **_kwargs: object) -> None:
        packet = json.loads(payload)
        self.packets.append(packet)
        if packet["type"] in SALE_EVENTS:
            self.publications.append((packet, await rows(self.player_id)))

    async def sell(self, item: str, npc: str, quantity: int, offer_id: str = "") -> llm.FunctionCallOutput:
        self.model.commands.append(
            ("sell_item", {"item_id": item, "npc_id": npc, "quantity": quantity, "offer_id": offer_id})
        )
        with self.data._bind_authenticated_actor(self.player_id, 1, lambda *_: None):
            await self.session.run(user_input="I'd like to sell these.")
        receipt = list(self.model.receipts.values())[-1]
        assert receipt.name == "sell_item"
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
