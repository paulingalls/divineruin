"""Committed material snapshots received through the live data channel."""

import asyncio
import json
import os
import subprocess
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from acceptance._livekit_client import (
    aclose_room,
    connect_room,
    mint_access_token,
    register_data_packet_collector,
    wait_for_peer,
)
from acceptance.seeds import seed_player
from livekit import rtc
from sample_fixtures import FixedRng, make_context

import db
import db_content_queries
import db_mutations
import db_queries
import event_types as E
from combat_end import _end_combat_db
from combat_events import EventSink
from crafting_tools import _start_crafting_project_impl
from experimentation_tools import _experiment_with_materials_impl
from gathering_tools import _check_gather_impl
from quest_tools import _update_quest_impl
from session_data import CombatParticipant, CombatState


@pytest.fixture
async def material_rooms(livekit_server):
    from uuid import uuid4

    room_name = f"materials-{uuid4().hex}"
    rooms = []
    try:
        for identity, kind in [("material-agent", "agent"), ("material-client", "standard")]:
            token = mint_access_token(
                api_key=livekit_server["api_key"],
                api_secret=livekit_server["api_secret"],
                room_name=room_name,
                identity=identity,
                participant_kind="agent" if kind == "agent" else "standard",
            )
            rooms.append(await connect_room(livekit_server["ws_url"], token))
        yield rooms
    finally:
        for room in reversed(rooms):
            await aclose_room(room)


async def seed_material_owner(pool, owner, entries):
    await seed_player(pool, player_id=owner, location_id="greyvale_wilderness_north")
    for mid, qty in entries.items():
        await db_mutations.add_inventory_item(owner, mid, qty)


@pytest.fixture
async def live_capture(reset_db_pool, material_rooms, tmp_path):
    pool = await db.get_pool()
    from uuid import uuid4

    suffix = uuid4().hex
    owner, guest = f"live_material_owner_{suffix}", f"live_material_guest_{suffix}"
    await seed_material_owner(pool, owner, {"oak_wood": 2, "crystal_flask": 1})
    await seed_material_owner(pool, guest, {"oak_wood": 2})
    for pid in [owner, guest]:
        await db_mutations.add_player_known_recipe(pid, "wooden_club", "experimentation")
    publisher, subscriber = material_rooms
    queue = asyncio.Queue()
    register_data_packet_collector(subscriber, topic="game_events", queue=queue)
    await asyncio.gather(
        wait_for_peer(publisher, identity="material-client"), wait_for_peer(subscriber, identity="material-agent")
    )
    assert subscriber.remote_participants["material-agent"].kind == rtc.ParticipantKind.PARTICIPANT_KIND_AGENT
    context = make_context(owner, "greyvale_wilderness_north", publisher, party_member_ids=[guest])
    context.userdata.event_bus = MagicMock()
    steps = []
    initial = {pid: await db_queries.get_player_inventory(pid) for pid in [owner, guest]}
    initial_revisions = {
        pid: (await db_queries.get_inventory_snapshot(pid))["inventory_revision"] for pid in [owner, guest]
    }
    quantities = {owner: {"oak_wood": 2, "crystal_flask": 1}, guest: {"oak_wood": 2}}
    assert {
        pid: {row["id"]: row["slot_info"]["quantity"] for row in initial[pid]} for pid in [owner, guest]
    } == quantities

    async def observe(phase, action, recipients):
        context.userdata.event_bus.publish.reset_mock()
        result = await action
        sent = [call.args[0] for call in context.userdata.event_bus.publish.call_args_list]
        snapshots = [e.payload for e in sent if e.event_type == E.INVENTORY_UPDATED]
        expected = {pid: await db_queries.get_player_inventory(pid) for pid in [owner, guest]}
        if phase == "gather_primary":
            for mid in json.loads(result)["materials"]:
                quantities[owner][mid] = quantities[owner].get(mid, 0) + 1
        elif phase in {"craft_primary_partial", "craft_guest_partial"}:
            quantities[recipients[0]]["oak_wood"] -= 1
        elif phase in {"experiment_primary_complete", "experiment_guest_empty"}:
            del quantities[recipients[0]]["oak_wood"]
        elif phase == "combat_distributed":
            for pid in [owner, guest]:
                quantities[pid]["wolf_pelt"] = 1
        elif phase == "quest_party":
            for pid in [owner, guest]:
                quantities[pid]["crystal_flask"] = quantities[pid].get("crystal_flask", 0) + 1
        for pid in [owner, guest]:
            assert {row["id"]: row["slot_info"]["quantity"] for row in expected[pid]} == quantities[pid]
        assert snapshots == [await db_queries.get_inventory_snapshot(pid) for pid in sorted(recipients)]
        assert sent
        received = []
        received_bytes = []
        for _ in sent:
            payload, identity = await asyncio.wait_for(queue.get(), timeout=5)
            assert identity == "material-agent"
            received.append(json.loads(payload))
            received_bytes.append(list(payload))
        assert received == [{"type": e.event_type, **e.payload} for e in sent]
        steps.append({"phase": phase, "received": received, "received_bytes": received_bytes, "expected": expected})
        return expected

    gained = await observe("gather_primary", _check_gather_impl(context, "herbs", rng=FixedRng(20)), [owner])
    assert any(row["type"] == "material" and row["name"] and row["slot_info"]["quantity"] for row in gained[owner])
    flask = next(row for row in gained[owner] if row["id"] == "crystal_flask")
    assert flask["type"] == "equipment" and flask["effects"] and flask["description"].startswith("Thin glass")
    partial = await observe("craft_primary_partial", _start_crafting_project_impl(context, "wooden_club"), [owner])
    assert next(row for row in partial[owner] if row["id"] == "oak_wood")["slot_info"]["quantity"] == 1
    deleted = await observe(
        "experiment_primary_complete",
        _experiment_with_materials_impl(context, {"oak_wood": 1}, "unknown_material_output"),
        [owner],
    )
    assert "oak_wood" not in {row["id"] for row in deleted[owner]}
    with context.userdata._bind_authenticated_actor(guest, 1, lambda *_: None):
        partial_guest = await observe(
            "craft_guest_partial", _start_crafting_project_impl(context, "wooden_club"), [guest]
        )
        assert next(row for row in partial_guest[guest] if row["id"] == "oak_wood")["slot_info"]["quantity"] == 1
        emptied = await observe(
            "experiment_guest_empty",
            _experiment_with_materials_impl(context, {"oak_wood": 1}, "unknown_material_output"),
            [guest],
        )
    assert emptied[guest] == []

    players = [
        CombatParticipant(id=pid, name=pid, type="player", initiative=15, hp_current=20, hp_max=20, ac=14)
        for pid in [owner, guest]
    ]
    enemy = CombatParticipant(
        id="material_enemy",
        name="Wolf",
        type="enemy",
        initiative=10,
        hp_current=0,
        hp_max=10,
        ac=10,
        is_fallen=True,
        loot_table_id="material_loot",
        role="standard",
        category="beast",
        level=1,
        tier=1,
        xp_value=0,
    )
    state = CombatState(
        combat_id="material_combat", participants=[*players, enemy], initiative_order=[owner, guest, enemy.id]
    )
    content = MagicMock(wraps=db_content_queries)
    from unittest.mock import AsyncMock

    content.get_loot_table = AsyncMock(
        return_value={
            "drops": [
                {"item_id": "wolf_pelt", "chance": 1, "quantity": 1},
                {"item_id": "wolf_pelt", "chance": 1, "quantity": 1},
            ]
        }
    )

    async def combat(*, fail_commit=False):
        sink = EventSink()
        async with db.transaction() as conn:
            await _end_combat_db(
                context.userdata,
                state,
                "victory",
                mutations=db_mutations,
                queries=db_queries,
                conn=conn,
                sink=sink,
                content=content,
                rng=FixedRng(1),
            )
            assert not context.userdata.event_bus.publish.called
            if fail_commit:
                raise RuntimeError("injected combat commit failure")
        await sink.flush()

    context.userdata.event_bus.publish.reset_mock()
    before_combat = {pid: await db_queries.get_player_inventory(pid) for pid in [owner, guest]}
    with pytest.raises(RuntimeError, match="injected combat commit failure"):
        await combat(fail_commit=True)
    assert {pid: await db_queries.get_player_inventory(pid) for pid in [owner, guest]} == before_combat
    context.userdata.event_bus.publish.assert_not_called()
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(queue.get(), timeout=0.1)
    await observe("combat_distributed", combat(), [owner, guest])

    quest_id = f"live_material_quest_{suffix}"
    await pool.execute(
        "INSERT INTO quests (id, data) VALUES ($1, $2::jsonb)",
        quest_id,
        json.dumps({"name": "Material Quest", "stages": [{"on_complete": {"rewards": [{"item": "crystal_flask"}]}}]}),
    )
    for pid in [owner, guest]:
        await db_mutations.set_player_quest(pid, quest_id, {"current_stage": 0})
    await observe("quest_party", _update_quest_impl(context, quest_id, 1), [owner, guest])
    fixture = {
        "runId": os.environ.get("LIVE_MATERIAL_INVENTORY_RUN_ID"),
        "owners": [owner, guest],
        "initial": initial,
        "initial_revisions": initial_revisions,
        "steps": steps,
        "sender": {
            "identity": "material-agent",
            "isAgent": True,
            "sid": subscriber.remote_participants["material-agent"].sid,
            "kind": subscriber.remote_participants["material-agent"].kind,
        },
    }
    path = tmp_path / "received.json"
    path.write_text(json.dumps(fixture))
    bridge = subprocess.run(
        [
            "bun",
            "test",
            "apps/mobile/src/__tests__/use-game-events.parse.test.ts",
            "-t",
            "committed inventory payloads reach independent consumers",
        ],
        env={**os.environ, "LIVE_MATERIAL_INVENTORY_FIXTURE": str(path)},
        cwd=Path(__file__).resolve().parents[4],
        capture_output=True,
        text=True,
    )
    assert bridge.returncode == 0, bridge.stdout + bridge.stderr
    artifact = Path(os.environ.get("LIVE_MATERIAL_INVENTORY_OUTPUT", "test-results/live-material-inventory.json"))
    artifact.parent.mkdir(exist_ok=True)
    artifact.write_text(json.dumps(fixture))
    return fixture


async def test_rolled_back_material_changes_publish_nothing(reset_db_pool):
    pool = await db.get_pool()
    owner = "live_material_rollback"
    await seed_material_owner(pool, owner, {"oak_wood": 1})
    context = make_context(owner, "greyvale_wilderness_north")
    context.userdata.event_bus = MagicMock()
    before = await db_queries.get_player_inventory(owner)

    @asynccontextmanager
    async def rollback():
        async with db.transaction() as conn:
            yield conn
            raise RuntimeError("injected commit failure")

    with pytest.raises(RuntimeError, match="injected commit failure"):
        await _check_gather_impl(context, "herbs", rng=FixedRng(20), db_mod=MagicMock(transaction=rollback))
    assert await db_queries.get_player_inventory(owner) == before
    context.userdata.event_bus.publish.assert_not_called()


async def test_committed_material_changes_reach_live_consumers(live_capture):
    assert len(live_capture["steps"]) == 7
