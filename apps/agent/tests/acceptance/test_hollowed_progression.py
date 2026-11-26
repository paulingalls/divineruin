"""Long-rest progression reaches the running DM through committed player rows."""

import asyncio
import json
from itertools import cycle
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from acceptance.rest_walk import RestWalk
from acceptance.test_creature_catalog import seed_content
from acceptance.test_hollowed_wis_drain import seed_bearer

import db
import event_types as E
from background_process import BackgroundProcess
from exploration_agent import ExplorationAgent

CONTENT = Path(__file__).resolve().parents[4] / "content" / "hollowed_hallucinations.json"


async def patch_player(walk: RestWalk, player_id: str, **fields: object) -> None:
    await walk.pool.execute(
        "UPDATE players SET data=data || $2::jsonb WHERE player_id=$1", player_id, json.dumps(fields)
    )


def test_long_rest_progression_reaches_current_gameplay_agent(harness: SimpleNamespace) -> None:
    async def check() -> None:
        walk = await RestWalk().setup(harness)
        host, guest, remote, absent, unaffected = walk.ids
        names = dict(zip(walk.ids, ("Aster", "Briar", "Cedar", "Dove", "Elm"), strict=True))
        original = {
            host: [{"type": "hollowed", "stage": 1, "source": "knight", "duration": 8}, {"type": "prone"}],
            guest: [{"type": "hollowed", "stage": 2}],
            remote: [{"type": "hollowed", "stage": 2}],
            absent: [{"type": "hollowed", "stage": 2}],
            unaffected: None,
        }
        await seed_bearer(walk, host, 12)
        await seed_bearer(walk, guest, 12)
        for pid, conditions in original.items():
            await patch_player(walk, pid, name=names[pid], conditions=conditions)

        harness.stack.enter_context(patch.object(ExplorationAgent, "_enter", new=AsyncMock()))
        agent = ExplorationAgent()
        walk.session.update_agent(agent)
        async with asyncio.timeout(5):
            while walk.session.current_agent is not agent:
                await asyncio.sleep(0)
        background = BackgroundProcess(walk.session, walk.sd)
        harness.stack.callback(lambda: harness.run_sync(background.stop()))

        async def rest(kind: str, changes: list[dict], expected: dict, guest_wisdom: int = 12) -> None:
            walk.events.clear()
            receipt = await walk.command(kind)
            assert receipt.name == "rest" and not receipt.is_error, receipt.output
            result = json.loads(receipt.output)
            assert result["rested"]
            rows = await walk.rows()
            assert {pid: row.get("conditions") for pid, row in rows.items()} == expected
            assert rows[host]["attributes"]["wisdom"] == 12
            assert rows[guest]["attributes"]["wisdom"] == guest_wisdom
            assert [
                {k: change[k] for k in ("player_id", "name", "from_stage", "to_stage")}
                for change in result["hollowed_changes"]
            ] == changes
            snapshots = {
                event["character"]["player_id"]: event["character"].get("conditions")
                for event in walk.events
                if event["type"] == E.SESSION_INIT
            }
            assert snapshots == {pid: expected[pid] for pid in (host, guest, unaffected)}

        catalog = json.loads(CONTENT.read_text())
        descriptions = [row["description"] for row in catalog]

        async def rebuild(expected: dict[str, str]) -> str:
            assert await background._rebuild_warm_layer()
            assert walk.session.current_agent is agent
            instructions = agent.instructions
            assert isinstance(instructions, str)
            sections = [
                section for section in instructions.split("\n\n") if section.startswith("HOLLOWED HALLUCINATION")
            ]
            assert len(sections) == len(expected), sections
            for pid, description in expected.items():
                (section,) = [line for line in sections if line.startswith(f"HOLLOWED HALLUCINATION — {names[pid]}\n")]
                assert "Only this character senses this." in section
                assert [entry for entry in descriptions if entry in section] == [description]
            return instructions

        def transition(pid: str, before: int, after: int) -> dict:
            return {"player_id": pid, "name": names[pid], "from_stage": before, "to_stage": after}

        advanced = {
            **original,
            host: [{**original[host][0], "stage": 2}, original[host][1]],
            guest: [{"type": "hollowed", "stage": 3}],
        }
        drained = {
            **advanced,
            host: [{**original[host][0], "stage": 3}, original[host][1]],
            guest: [{**advanced[guest][0], "wis_drained": 1}],
        }
        first, second, third, fourth = descriptions
        with patch("hollowed_hallucinations.choice", side_effect=cycle(catalog)):
            await rebuild({guest: first})
            await rest("short", [], original)
            await rest("long", [transition(host, 1, 2), transition(guest, 2, 3)], advanced)
            await rebuild({host: second, guest: first})
            await rest("long", [transition(host, 2, 3), transition(guest, 3, 3)], drained, guest_wisdom=11)
            await rebuild({host: second, guest: first})
            walk.sd.world_time = "evening"
            assert "evening" in await rebuild({host: second, guest: first})

            await patch_player(walk, guest, location_id="millhaven")
            await rebuild({host: second})
            await patch_player(walk, guest, location_id=walk.sd.location_id)
            await rebuild({host: second, guest: third})

            walk.sd.location_id = "greyvale_south_road"
            for pid in (host, guest, unaffected):
                await patch_player(walk, pid, location_id=walk.sd.location_id)
            assert "South Road" in await rebuild({host: fourth, guest: first})

            await patch_player(walk, host, conditions=[{"type": "prone"}])
            await rebuild({guest: first})

    harness.run_sync(check())


def test_full_hallucination_catalog_loads_and_fails_loudly(
    fresh_migrated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hollowed_hallucinations import get_hollowed_hallucinations

    authored = json.loads(CONTENT.read_text())
    assert authored and len({row["id"] for row in authored}) == len(authored)
    expected = sorted(authored, key=lambda row: row["id"])
    prefix = f"hallucinations-{uuid4().hex}:"
    monkeypatch.setenv("CONTENT_CACHE_PREFIX", prefix)
    monkeypatch.setenv("DATABASE_URL", fresh_migrated_db)

    async def check() -> None:
        await db.close_all()
        redis = await db.get_redis()
        key = prefix + "hollowed_hallucinations:all"
        try:
            pool = await db.get_pool()
            async with pool.acquire() as conn:
                await seed_content.seed(conn, catalog_only=True)
            assert await get_hollowed_hallucinations() == expected
            await pool.execute("DELETE FROM hollowed_hallucinations")
            assert await get_hollowed_hallucinations() == expected
            await redis.delete(key)
            with pytest.raises(ValueError, match=r"hollowed_hallucinations.*no rows"):
                await get_hollowed_hallucinations()
            for entry_id, description, field in ((" ", "A sound.", "id"), ("blank", " ", "description")):
                await pool.execute(
                    "INSERT INTO hollowed_hallucinations (id, data) VALUES ($1, $2::jsonb)",
                    entry_id,
                    json.dumps({"description": description}),
                )
                with pytest.raises(ValueError, match=rf"hollowed_hallucinations.*{field}"):
                    await get_hollowed_hallucinations()
                await pool.execute("DELETE FROM hollowed_hallucinations")
        finally:
            await redis.delete(key)
            await db.close_all()

    asyncio.run(check())
