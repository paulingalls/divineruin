"""Drive worker polls against persisted players without paid generation."""

import asyncio
import logging
from unittest.mock import patch

import db
import db_activity_queries
import db_mutations_divine
import db_queries

RECEIPT = "first_episode_whisper_sent"
TEXT = "I heard you stand against the dark."
AUDIO = "https://example.test/episode-whisper.mp3"


class PollsComplete(BaseException):
    pass


class Worker:
    def __init__(self):
        self.calls = []
        self.ids = []

    async def generate(self, player_id, deity_id):
        self.calls.append((player_id, deity_id))
        whisper_id = await db_mutations_divine.create_god_whisper(
            player_id,
            {"deity_id": deity_id, "narration_text": TEXT, "audio_url": AUDIO, "status": "pending"},
        )
        self.ids.append(whisper_id)
        return whisper_id

    async def poll(self, caplog, ticks=1):
        import async_worker

        completed = 0

        class Clock:
            def __getattr__(self, name):
                return getattr(asyncio, name)

            async def sleep(self, delay):
                nonlocal completed
                assert delay == async_worker.POLL_INTERVAL
                completed += 1
                if completed == ticks:
                    raise PollsComplete
                await asyncio.sleep(0)

        start = len(caplog.records)
        with (
            patch.object(async_worker, "asyncio", Clock()),
            patch.dict("os.environ", {"ANTHROPIC_API_KEY": "owned-unused-worker-key"}),
            patch("god_whisper_generator.generate_god_whisper", self.generate),
        ):
            async with asyncio.timeout(30):
                try:
                    await async_worker.main()
                except PollsComplete:
                    pass
        assert completed == ticks
        assert not [r.getMessage() for r in caplog.records[start:] if r.levelno >= logging.ERROR]


async def cleanup(player_id):
    pool = await db.get_pool()
    await pool.execute("DELETE FROM god_whispers WHERE player_id=$1", player_id)
    await pool.execute("DELETE FROM companion_relationships WHERE player_id=$1", player_id)
    await pool.execute("DELETE FROM players WHERE player_id=$1", player_id)


async def observe(player_id, ids, *, pending, receipt, last):
    player = await db_queries.get_player(player_id)
    assert player is not None
    if receipt is not None:
        assert player.get("flags", {}).get(RECEIPT, False) is receipt
    assert player["divine_favor"].get("last_whisper_level", 0) == last
    rows = await db_activity_queries.get_pending_god_whispers(player_id)
    assert [row["id"] for row in rows] == pending
    pool = await db.get_pool()
    rows = await pool.fetch("SELECT id, data FROM god_whispers WHERE player_id=$1 ORDER BY created_at, id", player_id)
    assert {row["id"] for row in rows} == set(ids)
    import json

    for row in rows:
        data = json.loads(row["data"])
        assert data == {
            "deity_id": player["divine_favor"]["patron"],
            "narration_text": TEXT,
            "audio_url": AUDIO,
            "status": "pending" if row["id"] in pending else "played",
        }


async def finish_whisper_walk(player_id, caplog):
    worker = Worker()
    player = await db_queries.get_player(player_id)
    assert player is not None
    assert {key: player["divine_favor"][key] for key in ("patron", "level", "last_whisper_level")} == {
        "patron": "kaelen",
        "level": 0,
        "last_whisper_level": 0,
    }
    assert player["flags"]["first_episode"] == "complete"
    await observe(player_id, [], pending=[], receipt=False, last=0)
    await worker.poll(caplog, ticks=2)
    assert worker.calls == [(player_id, "kaelen")]
    await observe(player_id, worker.ids, pending=worker.ids, receipt=None, last=0)
    await db_mutations_divine.mark_god_whisper_played(worker.ids[0])
    await observe(player_id, worker.ids, pending=[], receipt=None, last=0)
    await worker.poll(caplog)
    assert worker.calls == [(player_id, "kaelen")]
    await observe(player_id, worker.ids, pending=[], receipt=True, last=0)
    player = await db_queries.get_player(player_id)
    assert player is not None
    assert player["divine_favor"]["level"] == 0
    await set_favor(player_id, 25)
    await worker.poll(caplog)
    assert worker.calls == [(player_id, "kaelen")] * 2
    await observe(player_id, worker.ids, pending=worker.ids[-1:], receipt=True, last=25)


async def set_favor(player_id, level):
    pool = await db.get_pool()
    await pool.execute(
        "UPDATE players SET data=jsonb_set(data, '{divine_favor,level}', to_jsonb($2::int)) WHERE player_id=$1",
        player_id,
        level,
    )
