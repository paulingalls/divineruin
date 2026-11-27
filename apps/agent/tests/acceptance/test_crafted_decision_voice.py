"""Craft collection through the registered DM tool and the authenticated app route."""

import asyncio
import json
from collections.abc import AsyncIterator, Iterator
from contextlib import suppress
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import asyncpg
import httpx
import pytest
from _unbound_path_fixtures import world as world
from _zhael_fate_fixtures import game_tools
from acceptance._server import mint_server_jwt, start_server
from acceptance.test_common_bond_crafting import setup, stock
from livekit.agents import AgentSession
from livekit.agents.llm import FunctionTool, ToolError
from sample_fixtures import published_payloads
from test_aelora_gift import _live_party
from test_patron_engine_aelora_craft import create, poll

import db
import db_activity_queries
import db_queries
import event_types as E
from background_process import BackgroundProcess
from dispatch_agent import DispatchAgent
from exploration_agent import ExplorationAgent
from purification_tools import purification_outcome

CLUB = "club_wooden"
KEEP = {"id": "keep", "label": "Keep the item"}
SELL = {"id": "sell", "label": "Set it aside to sell"}
OPTIONS = {
    "boast": "Show off the craftsmanship",
    "rework": "Try to improve it (risk breaking)",
    "retry": "Salvage your resolve and try again later",
    "abandon": "Walk away from the forge",
}
SALE_CASES = Path(__file__).resolve().parents[4] / "packages/shared/fixtures/sale-price-cases.json"


@pytest.fixture
async def dev_db_pool(reset_db_pool: str) -> asyncpg.Pool:
    return await db.get_pool()


@pytest.fixture(scope="module")
def crafting_server(migrated_db: str) -> Iterator[dict[str, str]]:
    yield from start_server(migrated_db)


@pytest.fixture
async def bench(world: SimpleNamespace) -> AsyncIterator[SimpleNamespace]:
    world.item_ids = []
    world.agent = DispatchAgent()
    world.call = game_tools(world.ctx.userdata, agent=world.agent)
    try:
        yield world
    finally:
        await world.pool.execute("DELETE FROM async_activities WHERE player_id = ANY($1)", world.ids)
        await world.pool.execute("DELETE FROM player_inventory WHERE player_id = ANY($1)", world.ids)
        await world.pool.execute("DELETE FROM items WHERE id = ANY($1)", world.item_ids)


async def craft(
    bench: SimpleNamespace,
    *,
    owner: int = 0,
    item: str | None = CLUB,
    status: str = "resolved",
    kind: str = "crafting",
    options: tuple[dict, ...] = (KEEP, SELL),
) -> str:
    activity = f"craft_{uuid4().hex}"
    data = {
        "status": status,
        "activity_type": kind,
        "decision_options": options,
        "outcome": {
            "crafted_item_id": item,
            "crafted_item_name": "Wooden Club" if item else None,
            "tier": "success" if item else "failure",
        },
        "narration_text": "The last knock settles it.",
    }
    if kind == "purification":
        outcome = purification_outcome({"parameters": {"item_id": CLUB, "quantity": 1}})
        data.update(outcome=outcome, decision_options=outcome["decision_options"])
    await bench.pool.execute(
        "INSERT INTO async_activities (id, player_id, data) VALUES ($1,$2,$3)",
        activity,
        bench.ids[owner],
        json.dumps(data),
    )
    return activity


async def state(bench: SimpleNamespace, activity: str) -> tuple:
    async with bench.pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM async_activities WHERE id=$1", activity)
        players = await conn.fetch("SELECT * FROM players WHERE player_id=ANY($1) ORDER BY player_id", bench.ids)
        stacks = await conn.fetch(
            "SELECT * FROM player_inventory WHERE player_id=ANY($1) ORDER BY player_id,item_id,tainted", bench.ids
        )
    return row, players, stacks


async def voice(bench: SimpleNamespace, activity: str, decision: str | None = None) -> dict:
    args = {} if decision is None else {"decision": decision}
    return await bench.call("resolve_activity", kind="crafting", id=activity, **args)


async def http(server: dict, player: str, activity: str, decision: str) -> httpx.Response:
    async with httpx.AsyncClient() as client:
        return await client.post(
            f"{server['base_url']}/api/activities/{activity}/decide",
            headers={"Authorization": f"Bearer {mint_server_jwt(player)}"},
            json={"decision_id": decision},
        )


async def insert_item(bench: SimpleNamespace, properties: dict) -> str:
    item = f"crafted_test_{uuid4().hex}"
    template = await bench.pool.fetchval("SELECT data FROM items WHERE id=$1", CLUB)
    data = {**json.loads(template), **properties, "id": item}
    await bench.pool.execute("INSERT INTO items (id,data) VALUES ($1,$2)", item, json.dumps(data))
    bench.item_ids.append(item)
    return item


async def saved(bench: SimpleNamespace, activity: str) -> dict:
    row = await db_activity_queries.get_activity(activity, conn=bench.pool)
    assert row is not None
    return row


async def gold(bench: SimpleNamespace, player: str) -> float:
    return await bench.pool.fetchval(
        "SELECT COALESCE((data->>'gold')::float8,0) FROM players WHERE player_id=$1", player
    )


def packets(bench: SimpleNamespace) -> list[dict]:
    return published_payloads(bench.ctx.userdata.room)


@pytest.mark.parametrize("guest", [False, True], ids=["worker", "guest"])
async def test_keep_from_worker_success(bench: SimpleNamespace, guest: bool) -> None:
    session = bench.ctx.userdata
    owner = bench.ids[int(guest)]
    if guest:
        activity = await craft(bench, owner=1)
    else:
        await setup(bench, "aelora", "artificer", trained=True)
        await stock(bench, known=True)
        queued = await create(bench, "wooden_club")
        outcome, _, _ = await poll(bench, queued, 15)
        assert (outcome["tier"], outcome["crafted_item_id"], outcome["decision_options"]) == (
            "success",
            CLUB,
            [KEEP, SELL],
        )
        activity = queued["id"]
    await bench.pool.executemany(
        "INSERT INTO player_inventory (player_id,item_id,tainted,data) VALUES ($1,$2,$3,$4)",
        [
            (owner, CLUB, False, '{"quantity":2,"equipped":true,"current_hits":7}'),
            (owner, CLUB, True, '{"quantity":4,"equipped":false}'),
        ],
    )
    other_index = 1 - int(guest)
    other = bench.ids[other_index]
    other_activity = await craft(bench, owner=other_index)
    other_before = (
        await saved(bench, other_activity),
        await db_queries.get_inventory_snapshot(other),
        await gold(bench, other),
    )
    before = await saved(bench, activity)
    inventory_before = await db_queries.get_inventory_snapshot(owner)
    balance = await gold(bench, owner)

    async def observe(data: bytes, **_kwargs: object) -> None:
        assert await saved(bench, activity) == {**before, "status": "collected", "decision": "keep"}
        inventory = await db_queries.get_inventory_snapshot(owner)
        assert json.loads(data) == {"type": E.INVENTORY_UPDATED, **inventory}
        assert int(inventory["inventory_revision"]) == int(inventory_before["inventory_revision"]) + 1
        clean, tainted = inventory["inventory"]
        assert clean["slot_info"] == {"quantity": 3, "equipped": True, "current_hits": 7}
        assert tainted == inventory_before["inventory"][1]

    transport = session.room.local_participant.publish_data
    transport.reset_mock(side_effect=True)
    transport.side_effect = observe
    with session._bind_authenticated_actor(owner, 1, lambda *_: None):
        receipt = await voice(bench, activity, "keep")
    assert receipt == {"id": activity, "status": "collected", "decision": "keep", "item_id": CLUB}
    assert [p["type"] for p in packets(bench)] == [E.INVENTORY_UPDATED]
    assert await gold(bench, owner) == balance
    assert (
        await saved(bench, other_activity),
        await db_queries.get_inventory_snapshot(other),
        await gold(bench, other),
    ) == other_before


@pytest.mark.parametrize(("case_id", "proceeds_gold"), [("crafted", 1), ("crafted_fractional_gold", 8.1)])
async def test_sell_matches_http_and_shared_case(
    bench: SimpleNamespace, crafting_server: dict, case_id: str, proceeds_gold: float
) -> None:
    case = next(row for row in json.loads(SALE_CASES.read_text()) if row["id"] == case_id and "item" in row)
    item = await insert_item(bench, case["item"])
    voice_id, app_id = await craft(bench, item=item), await craft(bench, item=item, owner=1)
    owner, app_owner = bench.ids
    await bench.pool.execute(
        """UPDATE players SET data=data || '{"gold":12,"unrelated":"preserve me"}' WHERE player_id=ANY($1)""", bench.ids
    )
    before = await saved(bench, voice_id)
    inventories = [await db_queries.get_inventory_snapshot(player) for player in bench.ids]
    proceeds = {"price_sp": case["expected"]["price_sp"], "gold": proceeds_gold}

    async def observe(data: bytes, **_kwargs: object) -> None:
        assert await saved(bench, voice_id) == {**before, "status": "collected", "decision": "sell"}
        balance = await gold(bench, owner)
        assert balance == pytest.approx(12 + proceeds_gold)
        assert json.loads(data) == {
            "type": E.CURRENCY_GAINED,
            "player_id": owner,
            "currency": "gold",
            "source": "crafting",
            "amount": proceeds_gold,
            "new_balance": balance,
        }

    bench.ctx.userdata.room.local_participant.publish_data.side_effect = observe
    receipt = await voice(bench, voice_id, "sell")
    response = await http(crafting_server, app_owner, app_id, "sell")
    assert response.status_code == 200, response.text
    for activity, result in [(voice_id, receipt), (app_id, response.json())]:
        assert result == {"id": activity, "status": "collected", "decision": "sell", "proceeds": proceeds}
        assert (await saved(bench, activity))["decision"] == "sell"
    for player, inventory in zip(bench.ids, inventories, strict=True):
        assert await db_queries.get_inventory_snapshot(player) == inventory
        assert await gold(bench, player) == pytest.approx(12 + proceeds_gold)
        assert (
            await bench.pool.fetchval("SELECT data->>'unrelated' FROM players WHERE player_id=$1", player)
            == "preserve me"
        )
    assert [p["type"] for p in packets(bench)] == [E.CURRENCY_GAINED]


async def assert_refusal(
    bench: SimpleNamespace, activity: str, decision: str | None, message: str, error_type: type[Exception] = ToolError
) -> None:
    before = await state(bench, activity)
    error: Exception | None = None
    try:
        await voice(bench, activity, decision)
    except error_type as exc:
        error = exc
    assert await state(bench, activity) == before, "Refused craft changed persisted rows"
    assert not packets(bench)
    assert error is not None and message in str(error)


@pytest.mark.parametrize(
    ("excluded", "decision", "message"),
    [
        ("unknown", "keep", "Activity not found"),
        ("owner", "keep", "Activity not found"),
        ("in_progress", "keep", "not resolved"),
        ("resolving", "keep", "not resolved"),
        ("unoffered", "sell", "not offered"),
        ("kind", "collect", "not a crafting activity"),
        ("missing", None, "requires decision"),
        ("empty", "", "requires decision"),
    ],
)
async def test_refused_crafting_decision(
    bench: SimpleNamespace, excluded: str, decision: str | None, message: str
) -> None:
    owner = int(excluded == "owner")
    activity = await craft(
        bench,
        owner=owner,
        status=excluded if excluded in {"in_progress", "resolving"} else "resolved",
        kind="purification" if excluded == "kind" else "crafting",
        options=(KEEP,) if excluded == "unoffered" else (KEEP, SELL),
    )
    await assert_refusal(bench, "missing_craft" if excluded == "unknown" else activity, decision, message)
    if excluded in {"in_progress", "resolving", "kind"}:
        activity = await craft(bench, owner=owner)
    player = bench.ids[owner]
    with bench.ctx.userdata._bind_authenticated_actor(player, 1, lambda *_: None):
        assert (await voice(bench, activity, "keep"))["decision"] == "keep"
    inventory = await db_queries.get_inventory_snapshot(player)
    assert inventory["inventory"][0]["slot_info"]["quantity"] == 1


async def test_missing_catalog_output_cannot_be_granted(bench: SimpleNamespace) -> None:
    item = await insert_item(bench, {})
    activity = await craft(bench, item=item)
    await bench.pool.execute("DELETE FROM items WHERE id=$1", item)
    await assert_refusal(bench, activity, "keep", "has no crafted item", ValueError)


async def test_actor_revoked_after_lock_cannot_collect(bench: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
    owner = bench.ids[1]
    activity = await craft(bench, owner=1)
    session = bench.ctx.userdata
    lifecycle = _live_party(session, owner)
    fetch_activity = db_activity_queries.get_activity

    async def revoke_after_read(activity_id: str, *, conn: asyncpg.Connection, **kwargs: bool) -> dict | None:
        row = await fetch_activity(activity_id, conn=conn, **kwargs)
        lifecycle.mark_departed(owner)
        return row

    try:
        generation = await lifecycle.authorize(owner)
        assert generation is not None
        with session._bind_authenticated_actor(owner, generation, lifecycle.require_authorized):
            monkeypatch.setattr(db_activity_queries, "get_activity", revoke_after_read)
            await assert_refusal(bench, activity, "keep", "is stale", RuntimeError)
    finally:
        await lifecycle.aclose()


async def test_unavailable_sale_preserves_activity(bench: SimpleNamespace) -> None:
    activity = await craft(bench, item=await insert_item(bench, {"value_base": 0}))
    await assert_refusal(bench, activity, "sell", "priced_to_zero")
    assert (await voice(bench, activity, "keep"))["decision"] == "keep"


@pytest.mark.parametrize("choice", list(OPTIONS))
async def test_other_offered_choices_collect_only(bench: SimpleNamespace, choice: str) -> None:
    item = None if choice in {"retry", "abandon"} else CLUB
    activity = await craft(bench, item=item, options=({"id": choice, "label": OPTIONS[choice]},))
    before = await saved(bench, activity)
    _, players, stacks = await state(bench, activity)
    assert await voice(bench, activity, choice) == {"id": activity, "status": "collected", "decision": choice}
    assert await saved(bench, activity) == {**before, "status": "collected", "decision": choice}
    assert (await state(bench, activity))[1:] == (players, stacks)
    assert not packets(bench)


@pytest.mark.parametrize("first", ["http", "voice"])
async def test_sequential_surface_replay(bench: SimpleNamespace, crafting_server: dict, first: str) -> None:
    activity = await craft(bench)
    player = bench.ids[0]
    if first == "http":
        response = await http(crafting_server, player, activity, "keep")
        assert response.status_code == 200, response.text
        assert response.json()["decision"] == "keep"
        await assert_refusal(bench, activity, "sell", "not resolved")
        assert (await db_queries.get_inventory_snapshot(player))["inventory"][0]["slot_info"]["quantity"] == 1
        assert await gold(bench, player) == 0
    else:
        receipt = await voice(bench, activity, "sell")
        assert receipt["proceeds"]["gold"] > 0
        before, sent = await state(bench, activity), packets(bench)
        response = await http(crafting_server, player, activity, "keep")
        assert response.status_code == 400 and response.json()["error"] == "Activity is not resolved yet"
        assert await state(bench, activity) == before
        assert packets(bench) == sent


async def test_http_voice_contention(
    bench: SimpleNamespace, crafting_server: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    activity = await craft(bench)
    owner = bench.ids[0]
    read = asyncio.Event()
    release = asyncio.Event()
    fetch_activity = db_activity_queries.get_activity
    backend_pid = None

    async def pause_after_read(activity_id: str, *, conn: asyncpg.Connection, **kwargs: bool) -> dict | None:
        nonlocal backend_pid
        row = await fetch_activity(activity_id, conn=conn, **kwargs)
        backend_pid = conn.get_server_pid()
        read.set()
        await release.wait()
        return row

    with monkeypatch.context() as patch:
        patch.setattr(db_activity_queries, "get_activity", pause_after_read)
        voice_turn = asyncio.create_task(voice(bench, activity, "keep"))
        waiting = asyncio.create_task(read.wait())
        app_turn = None
        try:
            async with asyncio.timeout(8):
                await asyncio.wait([voice_turn, waiting], return_when=asyncio.FIRST_COMPLETED)
                if voice_turn.done():
                    await voice_turn
                app_turn = asyncio.create_task(http(crafting_server, owner, activity, "sell"))
                while not app_turn.done():
                    blocked = await bench.pool.fetchval(
                        """SELECT EXISTS (SELECT 1 FROM pg_stat_activity
                           WHERE $1::int = ANY(pg_blocking_pids(pid))
                           AND query LIKE '%async_activities%FOR UPDATE%')""",
                        backend_pid,
                    )
                    if blocked:
                        break
                release.set()
                receipt, response = await asyncio.gather(voice_turn, app_turn)
        finally:
            release.set()
            for task in (waiting, voice_turn, app_turn):
                if task is not None and not task.done():
                    task.cancel()
                    with suppress(asyncio.CancelledError):
                        await task

    row = await saved(bench, activity)
    inventory = await db_queries.get_inventory_snapshot(owner)
    assert (row["status"], row["decision"], await gold(bench, owner)) == ("collected", "keep", 0)
    assert inventory["inventory"][0]["slot_info"]["quantity"] == 1
    assert receipt["decision"] == "keep"
    assert response.status_code == 400 and response.json()["error"] == "Activity is not resolved yet"
    assert [p["type"] for p in packets(bench)] == [E.INVENTORY_UPDATED]


async def test_resolved_craft_reaches_warm_instructions(bench: SimpleNamespace) -> None:
    session = bench.ctx.userdata
    await bench.pool.execute(
        """UPDATE players SET data=data || jsonb_build_object('name', player_id, 'hp', '{"current":20,"max":20}'::jsonb)
           WHERE player_id=ANY($1)""",
        bench.ids,
    )
    success = await craft(bench)
    keep_only = await craft(bench, options=(KEEP,))
    failure = await craft(bench, item=None, options=tuple({"id": c, "label": OPTIONS[c]} for c in ("retry", "abandon")))
    guest_craft = await craft(bench, owner=1)
    excluded = [
        await craft(bench, status="in_progress"),
        await craft(bench, status="collected"),
        await craft(bench, kind="purification"),
        guest_craft,
        await craft(bench, options=()),
    ]
    live_session = AgentSession(userdata=session)
    exploration = ExplorationAgent(initial_location=session.location_id)
    live_session.update_agent(exploration)
    background = session.background = BackgroundProcess(live_session, session)
    assert await background._rebuild_warm_layer()
    exploration_prompt = exploration.instructions
    assert isinstance(exploration_prompt, str)
    assert 'enter_mode(mode="dispatch", encounter_id="")' in exploration_prompt
    dispatch, receipt = await game_tools(session, agent=exploration)("enter_mode", mode="dispatch", encounter_id="")
    assert receipt["status"] == "entered_dispatch"
    assert success in dispatch.instructions
    live_session.update_agent(dispatch)
    assert await background._rebuild_warm_layer()
    instructions = dispatch.instructions
    assert bench.ids[0] in instructions
    lines = {
        activity: next(line for line in instructions.splitlines() if activity in line)
        for activity in (success, keep_only, failure)
    }
    assert "Keep the item (keep)" in lines[success] and "Set it aside to sell (sell)" in lines[success]
    assert "Keep the item (keep)" in lines[keep_only] and "(sell)" not in lines[keep_only]
    for choice in ("retry", "abandon"):
        assert f"{OPTIONS[choice]} ({choice})" in lines[failure]
    assert all(activity not in instructions for activity in excluded)
    assert "Read the offered labels aloud" in instructions
    assert 'resolve_activity(kind="crafting", id=<activity id>, decision=<chosen option id>)' in instructions
    registered = next(t for t in dispatch.tools if isinstance(t, FunctionTool) and t.id == "resolve_activity")
    assert registered.info.description is not None
    assert "Read the offered labels aloud" in registered.info.description
    assert "option id" in registered.info.description

    assert (await voice(bench, failure, "retry"))["decision"] == "retry"
    assert await background._rebuild_warm_layer()
    assert failure not in dispatch.instructions and success in dispatch.instructions

    guest = bench.ids[1]
    lifecycle = _live_party(session, *bench.ids)
    try:
        generation = await lifecycle.authorize(guest)
        assert generation is not None
        assert await background._rebuild_warm_layer()
        assert (
            f"FINISHED CRAFTS — Player {guest}\n- Wooden Club (id: {guest_craft}) — Keep the item (keep)"
            in dispatch.instructions
        )
        with session._bind_authenticated_actor(guest, generation, lifecycle.require_authorized):
            collect = game_tools(session, agent=dispatch)
            receipt = await collect("resolve_activity", kind="crafting", id=guest_craft, decision="keep")
        assert receipt["id"] == guest_craft and receipt["decision"] == "keep"
        assert await background._rebuild_warm_layer()
        assert guest_craft not in dispatch.instructions and success in dispatch.instructions
    finally:
        await lifecycle.aclose()
