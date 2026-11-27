import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import uuid4

from acceptance.first_episode_harness import EpisodeModel
from acceptance.seeds import seed_player
from livekit.agents import AgentSession, llm
from sample_fixtures import make_mock_room

import db
import db_mutations
import event_types as E
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
        self.publications: list[tuple[dict, tuple[dict, dict]]] = []

    async def capture_packet(self, payload: bytes, **_kwargs: object) -> None:
        packet = json.loads(payload)
        if packet["type"] in SALE_EVENTS:
            self.publications.append((packet, await rows(self.player_id)))

    async def sell(self, item: str, npc: str, quantity: int) -> llm.FunctionCallOutput:
        self.model.commands.append(("sell_item", {"item_id": item, "npc_id": npc, "quantity": quantity}))
        with self.data._bind_authenticated_actor(self.player_id, 1, lambda *_: None):
            await self.session.run(user_input="I'd like to sell these.")
        (receipt,) = self.model.receipts.values()
        assert receipt.name == "sell_item"
        return receipt


@asynccontextmanager
async def merchant_session(
    *,
    location: str = FORGE,
    npc: str = GRIMJAW,
    item: str = SWORD,
    held: int = 2,
    disposition: str = "neutral",
    equipped: bool = False,
    tainted: int = 0,
    guest: bool = False,
) -> AsyncIterator[SaleSession]:
    from merchant_agent import MerchantAgent

    pool = await db.get_pool()
    pid = f"sale_{uuid4().hex}"
    primary = f"sale_{uuid4().hex}" if guest else pid
    try:
        for player_id in dict.fromkeys((pid, primary)):
            await seed_player(pool, player_id=player_id, location_id=location)
            await db_mutations.update_player_gold(player_id, 7, conn=pool)
        await db_mutations.set_npc_disposition(npc, pid, disposition, "fixture", conn=pool)
        if held:
            await stock(pid, item, held, equipped=equipped)
        if tainted:
            await stock(pid, item, tainted, tainted=True)
        sale = SaleSession(pid, primary, location)
        try:
            await sale.session.start(MerchantAgent())
            yield sale
        finally:
            await sale.session.aclose()
    finally:
        await pool.execute("DELETE FROM players WHERE player_id=ANY($1)", list({pid, primary}))
