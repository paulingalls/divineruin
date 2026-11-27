"""Gold settlement through registered tools, observed in PostgreSQL and on the wire."""

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from decimal import Decimal
from unittest.mock import AsyncMock
from uuid import uuid4

import asyncpg
import pytest
from acceptance.first_episode_harness import EpisodeModel
from acceptance.merchant_harness import FORGE, GRIMJAW, SWORD
from acceptance.seeds import seed_gold, seed_player
from livekit.agents import Agent, AgentSession, llm
from sample_fixtures import make_mock_room

import combat_end
import combat_rewards
import db
import db_mutations
import db_queries
import durability
import pricing_queries
from activity_payloads import WorkspaceRental
from activity_tools import begin_activity
from db_mutations_inventory import credit_player_gold
from party_state import PartyState
from repair_item import repair_item
from session_data import CombatParticipant, CombatState, SessionData

GAINED = "currency_gained"
SPENT = "currency_spent"


class GoldSession:
    def __init__(self, pool: asyncpg.Pool, players: list[str]) -> None:
        self.pool, self.players = pool, players
        self.actor = players[-1]
        room = make_mock_room()
        room.isconnected.return_value = True
        self.publish_data = AsyncMock(side_effect=self.capture)
        room.local_participant.publish_data = self.publish_data
        self.data = SessionData(player_id=players[0], location_id=FORGE, world_time="daytime", room=room)
        self.data.party.members.extend(PartyState.solo(pid).primary for pid in players[1:])
        self.model = EpisodeModel([])
        self.packets: list[tuple[dict, tuple]] = []
        self.session = AgentSession(userdata=self.data, llm=self.model)

    @staticmethod
    def agent() -> Agent:
        return Agent(
            instructions="Settle the encounter or service.", tools=[combat_end.end_combat, repair_item, begin_activity]
        )

    async def gold(self, pid: str) -> Decimal:
        return await self.pool.fetchval("SELECT (data->>'gold')::numeric FROM players WHERE player_id=$1", pid)

    async def snapshot(self, pid: str) -> tuple[Decimal, int | None, list[asyncpg.Record]]:
        hits = await self.pool.fetchval(
            "SELECT (data->>'current_hits')::int FROM player_inventory WHERE player_id=$1 AND item_id=$2", pid, SWORD
        )
        rentals = await self.pool.fetch(
            "SELECT id, player_id, location_id, workspace_type, source, expires_at FROM workspace_rentals "
            "WHERE player_id=$1 ORDER BY id",
            pid,
        )
        return await self.gold(pid), hits, rentals

    async def capture(self, payload: bytes, **_kwargs: object) -> None:
        packet = json.loads(payload)
        if packet["type"] in (GAINED, SPENT):
            self.packets.append((packet, await self.snapshot(packet["player_id"])))

    async def command(self, name: str, args: dict) -> llm.FunctionCallOutput:
        self.model.commands.append((name, args))
        with self.data._bind_authenticated_actor(self.actor, 1, lambda *_: None):
            async with asyncio.timeout(15):
                await self.session.run(user_input="Go ahead.")
        assert len(self.model.receipts) == len(self.model.commands)
        receipt = list(self.model.receipts.values())[-1]
        assert receipt.name == name
        return receipt

    async def victory(self, amount: Decimal) -> None:
        parts = [
            CombatParticipant(id=pid, name=pid, type="player", initiative=15, hp_current=28, hp_max=28, ac=15)
            for pid in self.players
        ]
        parts.append(
            CombatParticipant(
                id="enemy", name="Enemy", type="enemy", initiative=1, hp_current=0, hp_max=10, ac=10, is_fallen=True
            )
        )
        combat_id = self.players[0]
        state = CombatState(combat_id, parts, [p.id for p in parts], location_id=FORGE)
        self.data.combat_state = state
        await db_mutations.save_combat_state(combat_id, state.to_dict())
        receipt = await self.command("end_combat", {"outcome": "victory"})
        assert not receipt.is_error, receipt.output
        assert self.data.combat_state is None
        assert await db_mutations.load_combat_state(combat_id) is None
        assert json.loads(receipt.output)["currency_gold"] == float(amount)

    async def debit(self, service: str, *, days: int = 1) -> llm.FunctionCallOutput:
        if service == "repair":
            return await self.command("repair_item", {"item_id": SWORD, "npc_id": GRIMJAW})
        rental = WorkspaceRental(kind="workspace", workspace_type="workshop", npc_id=GRIMJAW, days=days)
        return await self.command("begin_activity", {"activity": rental.model_dump()})

    async def damaged_item(self, disposition: str = "neutral") -> None:
        await db_mutations.set_npc_disposition(GRIMJAW, self.actor, disposition, "fixture")
        await self.pool.execute(
            "INSERT INTO player_inventory (player_id, item_id, data) VALUES ($1,$2,$3::jsonb)",
            self.actor,
            SWORD,
            json.dumps({"quantity": 1, "current_hits": 2}),
        )
        await self.pool.execute(
            "INSERT INTO skill_advancement (player_id, skill_id, tier, use_counter, narrative_moment_ready) "
            "VALUES ($1, 'crafting', 'trained', 0, false)",
            self.actor,
        )


@asynccontextmanager
async def gold_session(monkeypatch: pytest.MonkeyPatch, *balances: str, silver: int = 1) -> AsyncIterator[GoldSession]:
    pool = await db.get_pool()
    prefix = f"gold_{uuid4().hex}"
    players = [f"{prefix}_{seat}" for seat in range(len(balances))]
    run = GoldSession(pool, players)
    monkeypatch.setattr(combat_end, "_build_handoff_agent", lambda *_: run.agent())
    monkeypatch.setattr(
        combat_rewards,
        "roll_encounter_spoils",
        AsyncMock(return_value=combat_rewards.EncounterSpoils(currency_silver=silver)),
    )
    try:
        for pid, gold in zip(players, balances, strict=True):
            await seed_player(pool, player_id=pid, location_id=FORGE)
            await seed_gold(pool, pid, Decimal(gold))
        await run.session.start(run.agent())
        yield run
    finally:
        await run.session.aclose()
        await db_mutations.delete_combat_state(players[0])
        await pool.execute("DELETE FROM players WHERE player_id=ANY($1)", players)


def currency_packet(kind: str, player_id: str, amount: Decimal, source: str, balance: Decimal) -> dict:
    return {
        "type": kind,
        "player_id": player_id,
        "amount": float(amount),
        "currency": "gold",
        "source": source,
        "new_balance": float(balance),
    }


@pytest.mark.parametrize(
    "starts,silver,share,fights",
    [(("15",), 1, "0.1", 8), (("15", "7.6"), 2, "0.15", 8), (("0", "1", "2"), 1, "0.06", 1)],
)
async def test_combat_rewards_accumulate_exactly(
    reset_db_pool: str, monkeypatch: pytest.MonkeyPatch, starts: tuple[str, ...], silver: int, share: str, fights: int
) -> None:
    amount = Decimal(share)
    async with gold_session(monkeypatch, *starts, silver=silver) as run:
        for _ in range(fights):
            await run.victory(amount)
        for pid, start in zip(run.players, starts, strict=True):
            assert await run.gold(pid) == Decimal(start) + fights * amount
        expected = [
            (currency_packet(GAINED, pid, amount, "combat", balance), balance)
            for fight in range(1, fights + 1)
            for pid, start in zip(run.players, starts, strict=True)
            for balance in [Decimal(start) + fight * amount]
        ]
        assert [(packet, snapshot[0]) for packet, snapshot in run.packets] == expected


async def assert_service(
    run: GoldSession, receipt: llm.FunctionCallOutput, service: str, price_sp: int, gold: str
) -> None:
    assert not receipt.is_error, receipt.output
    result = json.loads(receipt.output)
    assert result["price_sp"] == price_sp
    snapshot = await run.snapshot(run.actor)
    balance, hits, rentals = snapshot
    assert balance == Decimal(gold)
    if service == "repair":
        assert hits == result["restored_to"] == durability.max_hits("standard")
        assert not rentals
    else:
        assert hits == 2
        (rental,) = rentals
        assert tuple(rental.values()) == (
            result["rental_id"],
            run.actor,
            FORGE,
            "workshop",
            "rental",
            datetime.fromisoformat(result["expires_at"]),
        )
    if not price_sp:
        assert not run.packets
        return
    source = "repair" if service == "repair" else "workspace_rental"
    assert run.packets == [(currency_packet(SPENT, run.actor, Decimal(price_sp) / 10, source, Decimal(gold)), snapshot)]


@pytest.mark.parametrize(
    "service,start,remaining", [("repair", "0.3", "0.1"), ("rental", "0.3", "0.1"), ("rental", "0.2", "0")]
)
async def test_fractional_debit_commits_stored_balance(
    reset_db_pool: str, monkeypatch: pytest.MonkeyPatch, service: str, start: str, remaining: str
) -> None:
    async with gold_session(monkeypatch, start) as run:
        await run.damaged_item()
        await assert_service(run, await run.debit(service), service, 2, remaining)


async def test_exact_price_after_fractional_rewards(reset_db_pool: str, monkeypatch: pytest.MonkeyPatch) -> None:
    async with gold_session(monkeypatch, "0") as run:
        for _ in range(3):
            await run.victory(Decimal("0.1"))
        await run.damaged_item()
        pricing = await pricing_queries.get_economy_pricing()
        monkeypatch.setattr(
            pricing_queries,
            "get_economy_pricing",
            AsyncMock(return_value={**pricing, "repair_cost_sp": {**pricing["repair_cost_sp"], "common": 3}}),
        )
        credited = await run.gold(run.actor)
        run.packets.clear()
        await assert_service(run, await run.debit("repair"), "repair", 3, "0")
        assert credited == Decimal("0.3")


@pytest.mark.parametrize(
    "service,gold,days,refusal",
    [
        ("repair", "0.1", 1, "costs 0.2gp and you have 0.1gp."),
        ("rental", "0.1", 1, "costs 0.2gp and you have 0.1gp."),
        ("rental", "1.19999999999999997", 6, "costs 1.2gp and you have 1.2gp."),
    ],
)
async def test_insufficient_debit_changes_nothing(
    reset_db_pool: str, monkeypatch: pytest.MonkeyPatch, service: str, gold: str, days: int, refusal: str
) -> None:
    async with gold_session(monkeypatch, gold) as run:
        await run.damaged_item()
        before = await run.snapshot(run.actor)
        receipt = await run.debit(service, days=days)
        assert await run.snapshot(run.actor) == before
        assert not run.packets
        assert receipt.is_error and "Not enough gold:" in receipt.output and refusal in receipt.output, receipt.output


@pytest.mark.parametrize("service", ["repair", "rental"])
async def test_concurrent_credit_is_preserved(
    reset_db_pool: str, monkeypatch: pytest.MonkeyPatch, service: str
) -> None:
    async with gold_session(monkeypatch, "0.1") as run:
        await run.damaged_item()
        read_attempted = asyncio.Event()
        read_player = db_queries.get_player

        async def signal_read(
            pid: str, *, conn: asyncpg.Connection | asyncpg.Pool | None = None, for_update: bool = False
        ) -> dict | None:
            if pid == run.actor and conn is not None:
                read_attempted.set()
            return await read_player(pid, conn=conn, for_update=for_update)

        monkeypatch.setattr(db_queries, "get_player", signal_read)
        async with asyncio.timeout(10), asyncio.TaskGroup() as tasks:
            async with db.transaction() as conn:
                await credit_player_gold(run.actor, 0.2, conn=conn)
                debit = tasks.create_task(run.debit(service))
                await read_attempted.wait()
        await assert_service(run, debit.result(), service, 2, "0.1")


@pytest.mark.parametrize("service,starts", [("repair", ("7", "0.3")), ("rental", ("0.3",))])
async def test_failed_debit_transaction_publishes_nothing(
    reset_db_pool: str, monkeypatch: pytest.MonkeyPatch, service: str, starts: tuple[str, ...]
) -> None:
    async with gold_session(monkeypatch, *starts) as run:
        await run.damaged_item()
        before = await run.snapshot(run.actor)
        transaction = db.transaction

        @asynccontextmanager
        async def roll_back() -> AsyncIterator[asyncpg.Connection]:
            async with transaction() as conn:
                yield conn
                raise RuntimeError("Forced rollback before commit")

        monkeypatch.setattr(db, "transaction", roll_back)
        receipt = await run.debit(service)
        assert receipt.is_error
        assert await run.snapshot(run.actor) == before
        assert not run.packets


async def test_free_rental_publishes_no_spend(reset_db_pool: str, monkeypatch: pytest.MonkeyPatch) -> None:
    async with gold_session(monkeypatch, "0.3") as run:
        await run.damaged_item(disposition="trusted")
        await assert_service(run, await run.debit("rental"), "rental", 0, "0.3")


@pytest.mark.parametrize("service", ["repair", "rental"])
async def test_committed_debit_returns_receipt_when_purse_delivery_fails(
    reset_db_pool: str, monkeypatch: pytest.MonkeyPatch, service: str
) -> None:
    async with gold_session(monkeypatch, "0.3") as run:
        await run.damaged_item()

        async def fail_spend_delivery(payload: bytes, **kwargs: object) -> None:
            if json.loads(payload)["type"] == SPENT:
                raise ConnectionError("Lost the purse data channel")
            await run.capture(payload, **kwargs)

        run.publish_data.side_effect = fail_spend_delivery
        receipt = await run.debit(service)
        balance, hits, rentals = await run.snapshot(run.actor)
        assert balance == Decimal("0.1")
        if service == "repair":
            assert hits == durability.max_hits("standard")
        else:
            assert len(rentals) == 1
        assert not receipt.is_error, receipt.output
        assert json.loads(receipt.output)["price_sp"] == 2
