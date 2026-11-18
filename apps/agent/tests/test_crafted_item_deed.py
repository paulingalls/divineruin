"""Craft completion journals a pending patron deed at the worker boundary."""

import json
import random
from dataclasses import asdict
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from acceptance.seeds import seed_player
from dice_seeds import seed_for_d20

import async_worker as worker
import crafting_resolution
import db_activity_queries
import db_mutations
import patron_deeds
from dialogue_parser import Segment


async def activity_row(activity_id, **kwargs):
    row = await db_activity_queries.get_activity(activity_id, **kwargs)
    assert row is not None
    return row


@pytest.fixture
async def craft(dev_db_pool, monkeypatch):
    pool = dev_db_pool
    pid, spectator = (f"deed_{uuid4().hex}" for _ in range(2))
    ids = set()
    calls = []
    segment = Segment("DM_NARRATOR", "neutral", "The work is finished.")
    original_due = db_activity_queries.get_due_activities
    original_record = patron_deeds.record_deed
    original_resolve = crafting_resolution.resolve_crafting_outcome
    state = SimpleNamespace(face=10, fault=False)

    async def player(player_id=pid, conn=pool):
        return json.loads(await conn.fetchval("SELECT data FROM players WHERE player_id=$1", player_id))

    async def record(player_id, kind, *, conn):
        calls.append((player_id, kind))
        await original_record(player_id, kind, conn=conn)
        if state.fault:
            assert (await activity_row(state.activity_id, conn=conn))["status"] == "resolved"
            assert (await player(conn=conn))["patron_deeds"]["crafted_item"] == "pending"
            state.fault_reached += 1
            raise RuntimeError("deed terminal transaction fault")

    async def due():
        return [row for row in await original_due() if row["id"] in ids]

    async def resolve(activity, data):
        return await original_resolve(activity, data, rng=random.Random(seed_for_d20(state.face)))

    async def create(kind="crafting", cached=False):
        data = {
            "status": "in_progress",
            "activity_type": kind,
            "resolve_at": "2025-01-01T00:00:00Z",
            "parameters": {
                "recipe_id": "iron_sword",
                "result_item_id": "iron_sword",
                "result_item_name": "Iron Sword",
                "required_materials": ["iron_ingot", "leather_strip"],
                "skill": "arcana",
                "dc": 11,
                "workspace_required": "forge",
                "workspace_access": ["field", "forge"],
                "crafting_tier": "expert",
                "tainted_materials": False,
            },
        }
        if kind == "purification":
            data["parameters"] = {"item_id": "rend_shard", "quantity": 2}
        if cached:
            data.update(outcome={"tier": "success"}, narration_text=segment.text, narration_segments=[asdict(segment)])
        activity_id = await db_mutations.create_async_activity(pid, data)
        ids.add(activity_id)
        return activity_id

    for name in (
        "_backfill_progress_snippets",
        "generate_world_news",
        "generate_notification_hook",
        "send_push_notification",
        "synthesize_segments",
    ):
        monkeypatch.setattr(worker, name, AsyncMock())
    narration = AsyncMock(return_value=([segment], segment.text, "Finished."))
    resolver = AsyncMock(side_effect=resolve)
    monkeypatch.setattr(worker, "generate_activity_narration", narration)
    monkeypatch.setattr(worker, "resolve_crafting_outcome", resolver)
    monkeypatch.setattr(db_activity_queries, "get_due_activities", due)
    monkeypatch.setattr(patron_deeds, "record_deed", record)
    try:
        await seed_player(pool, player_id=pid)
        await seed_player(pool, player_id=spectator)
        data = await player()
        data.update(
            level=3,
            attributes={"intelligence": 10},
            proficiencies=["arcana"],
            sentinel="preserve",
            patron_deeds={"healed_ally": "pending"},
            divine_favor={"patron": "aelora", "balance": 7},
        )
        await pool.execute("UPDATE players SET data=$2::jsonb WHERE player_id=$1", pid, json.dumps(data))
        yield SimpleNamespace(
            pool=pool,
            pid=pid,
            spectator=spectator,
            calls=calls,
            state=state,
            create=create,
            player=player,
            narration=narration,
            resolver=resolver,
        )
    finally:
        await pool.execute("DELETE FROM async_activities WHERE player_id=$1", pid)
        await pool.execute("DELETE FROM player_inventory WHERE player_id=$1", pid)
        await pool.execute("DELETE FROM players WHERE player_id=ANY($1::text[])", [pid, spectator])


async def assert_finished(h, activity_id, *, deed=True, count=1):
    activity = await activity_row(activity_id)
    assert activity["status"] == "resolved"
    data = await h.player()
    assert data["patron_deeds"] == {"healed_ally": "pending", **({"crafted_item": "pending"} if deed else {})}
    assert h.calls == [(h.pid, "crafted_item")] * count
    return activity


@pytest.mark.parametrize(("face", "tier"), [(20, "exceptional"), (10, "success"), (4, "partial"), (1, "failure")])
async def test_fresh_craft_tiers(craft, face, tier):
    h = craft
    h.state.face = face
    before = await h.player()
    spectator = await h.player(h.spectator)
    activity_id = await h.create()
    await worker.resolve_due_activities()
    activity = await assert_finished(h, activity_id, deed=tier != "failure", count=int(tier != "failure"))
    assert activity["outcome"]["tier"] == tier
    after = await h.player()
    assert after["sentinel"] == before["sentinel"]
    assert after["divine_favor"] == before["divine_favor"]
    assert await h.player(h.spectator) == spectator


async def test_terminal_deed_failure_rolls_back_status_and_journal(craft):
    h = craft
    activity_id = await h.create()
    h.state.activity_id = activity_id
    h.state.fault = True
    h.state.fault_reached = 0
    await worker.resolve_due_activities()
    assert h.state.fault_reached == 1
    assert (await activity_row(activity_id))["status"] == "in_progress"
    assert "crafted_item" not in (await h.player())["patron_deeds"]
    h.state.fault = False
    await worker.resolve_due_activities()
    await assert_finished(h, activity_id, count=2)


@pytest.mark.parametrize("interruption", ["tts_failure", "stale_recovery"])
async def test_retry_finalizes_cached_craft_once(craft, monkeypatch, interruption):
    h = craft
    activity_id = await h.create()

    async def interrupt(*args):
        if interruption == "tts_failure":
            raise RuntimeError("TTS unavailable")
        await h.pool.execute(
            "UPDATE async_activities SET data=jsonb_set(data,'{resolving_at}',"
            "to_jsonb(NOW() - interval '1 day')) WHERE id=$1",
            activity_id,
        )
        await worker.reset_stale_resolving()
        assert (await activity_row(activity_id))["status"] == "in_progress"

    monkeypatch.setattr(worker, "synthesize_segments", interrupt)
    await worker.resolve_due_activities()
    activity = await activity_row(activity_id)
    assert activity["status"] == "in_progress"
    assert activity["outcome"]["tier"] == "success"
    assert activity["narration_segments"]
    assert "crafted_item" not in (await h.player())["patron_deeds"]
    assert h.calls == []
    monkeypatch.setattr(worker, "synthesize_segments", AsyncMock())
    await worker.resolve_due_activities()
    await assert_finished(h, activity_id)
    await worker.resolve_due_activities()
    await assert_finished(h, activity_id)
    assert h.resolver.await_count == h.narration.await_count == 1


@pytest.mark.parametrize("kind", ["crafting", "purification", "companion_errand"])
async def test_cached_activity_type_exclusions(craft, kind):
    h = craft
    activity_id = await h.create(kind, cached=True)
    await worker.resolve_due_activities()
    await assert_finished(h, activity_id, deed=kind == "crafting", count=int(kind == "crafting"))
    rows = await h.pool.fetch("SELECT item_id, tainted, data FROM player_inventory WHERE player_id=$1", h.pid)
    if kind == "purification":
        assert [(r["item_id"], r["tainted"], json.loads(r["data"])["quantity"]) for r in rows] == [
            ("rend_shard", False, 2)
        ]
    else:
        assert not rows
