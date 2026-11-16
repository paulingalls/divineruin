"""Leave travels through the registered listener and real room to a saved recap."""

import asyncio
import json
from unittest.mock import patch

from acceptance._livekit_client import register_data_packet_collector
from acceptance.fresh_recap_harness import RecapHarness

import db
import db_mutations
import db_queries


async def send(room):
    await room.local_participant.publish_data(b'{"type":"leave_requested"}', reliable=True, topic="player_hints")


async def end_packet(queue):
    async with asyncio.timeout(15):
        while True:
            packet = json.loads((await queue.get())[0])
            if packet["type"] == "session_end":
                return packet


async def join_end(sd):
    assert sd.session_end_task is not None
    await sd.session_end_task


async def test_solo_leave_once(livekit_server, reset_db_pool):
    async with RecapHarness(livekit_server) as harness:
        pid = await harness.player()
        job = await harness.start(pid)
        sd = await job.wait()
        queue = asyncio.Queue()
        register_data_packet_collector(job.player, topic="game_events", queue=queue)
        closed = asyncio.Event()
        job.episode.session.on("close", lambda _: closed.set())
        entered, release = asyncio.Event(), asyncio.Event()
        generate = __import__("session_end").generate_session_summary
        save = db_mutations.save_session_summary
        saves = []

        async def held(*args, **kwargs):
            entered.set()
            await release.wait()
            return await generate(*args, **kwargs)

        async def saving(*args):
            saves.append(args)
            return await save(*args)

        try:
            with (
                patch("session_end.generate_session_summary", side_effect=held),
                patch("db_mutations.save_session_summary", side_effect=saving),
            ):
                async with asyncio.timeout(15):
                    await send(job.player)
                    await entered.wait()
                    task = sd.session_end_task
                    assert task is not None
                    await send(job.player)
                    release.set()
                    packet = await end_packet(queue)
                    await closed.wait()
                    await task
                assert sd.session_end_task is task and task.done()
                assert sd.background is not None and sd.background._task is not None
                await asyncio.gather(sd.background._task, return_exceptions=True)
                assert sd.background._task.cancelled()
                redis = await db.get_redis()
                raw = await redis.get(f"session_outcome:{pid}")
                assert raw is not None
                assert json.loads(raw) == {
                    "session_id": sd.session_id,
                    "state": "saved",
                }
                assert len(saves) == 1
                while not queue.empty():
                    assert json.loads(queue.get_nowait()[0])["type"] != "session_end"
                row = await db_queries.get_last_session_summary(pid)
                assert row is not None and row["summary"] == packet["summary"] == "Fresh bells rang."
                assert row["session_id"] == sd.session_id
        finally:
            release.set()


async def wait_until(predicate):
    async with asyncio.timeout(15):
        while not predicate():
            await asyncio.sleep(0.02)


async def join(job, identity):
    from acceptance._livekit_client import connect_room, mint_access_token

    server = job.server
    return await connect_room(
        server["ws_url"],
        mint_access_token(
            api_key=server["api_key"], api_secret=server["api_secret"], room_name=job.room_name, identity=identity
        ),
    )


async def server_request(player, operation, room):
    import os
    from pathlib import Path

    root = Path(__file__).resolve().parents[4]
    fixture = root / "apps/server/src/session-room-process.fixture.ts"
    script = f"""
        const {{installSeam, Recording, request}} = await import({json.dumps(str(fixture))});
        const recording = new Recording();
        await installSeam(call => recording.invoke(call));
        const result = await request({json.dumps(player)}, {json.dumps(operation)}, {{room_name: {json.dumps(room)}}});
        console.log('BOUNDARY:' + JSON.stringify({{...result, calls: recording.calls}}));
        Bun.redis.close();
    """
    proc = await asyncio.create_subprocess_exec(
        "bun",
        "--env-file=.env",
        "--eval",
        script,
        cwd=root,
        env={**os.environ, "RATE_LIMIT_BYPASS": "1"},
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), 15)
    assert proc.returncode == 0, stderr.decode()
    return json.loads(stdout.decode().split("BOUNDARY:")[-1])


async def test_party_leaves(livekit_server, reset_db_pool, monkeypatch):
    from acceptance._livekit_client import (
        aclose_audio,
        aclose_room,
        create_microphone_track,
        play_audio_frames,
        wait_for_audio_track,
    )
    from acceptance.multiplayer_voice._harness import PLAYER_TWO_SPEECH
    from livekit import rtc

    for key, value in (("URL", "ws_url"), ("API_KEY", "api_key"), ("API_SECRET", "api_secret")):
        monkeypatch.setenv(f"LIVEKIT_{key}", livekit_server[value])
    for primary_leaves in (False, True):
        async with RecapHarness(livekit_server) as harness:
            host, guest = await harness.player(), await harness.player()
            job = await harness.start(host)
            sd = await job.wait()
            assert (await server_request(host, "token", job.room_name))["status"] == 200
            room = await join(job, guest)
            try:
                assert sd.multiplayer_owner is not None
                lifecycle = sd.multiplayer_owner.lifecycle
                await wait_until(
                    lambda lifecycle=lifecycle, guest=guest: lifecycle.current_generation(guest) is not None
                )
                assert await lifecycle.authorize(guest) is not None
                leaver, survivor = (host, guest) if primary_leaves else (guest, host)
                departing_room = job.player if primary_leaves else room
                queue = asyncio.Queue()
                register_data_packet_collector(departing_room, topic="game_events", queue=queue)
                disconnected = asyncio.Event()
                departing_room.on("disconnected", disconnected.set)
                async with asyncio.timeout(15):
                    await send(departing_room)
                    packet = await end_packet(queue)
                    await disconnected.wait()
                    assert sd.departure_task is not None
                    await sd.departure_task
                assert packet["player_id"] == leaver
                row = await db_queries.get_last_session_summary(leaver)
                assert row and row["summary"] == packet["summary"]
                assert await db_queries.get_last_session_summary(survivor) is None
                assert sd.primary_player_id == survivor and sd.party.member_ids == [survivor]
                assert await lifecycle.authorize(leaver) is None
                assert await lifecycle.authorize(survivor) is not None
                assert sd.session_end_task is None
                assert sd.background is not None and sd.background._task is not None
                assert not sd.background._task.done()
                survivor_room = room if primary_leaves else job.player
                assert survivor_room.isconnected()
                if primary_leaves:
                    assert (await server_request(guest, "invite", job.room_name))["status"] == 200
                    assert (await server_request(host, "invite", job.room_name))["status"] == 403
                    replacement = await server_request(host, "token", f"replacement-{host}")
                    assert replacement["status"] == 200
                    assert all(call["room"] != job.room_name for call in replacement["calls"])
                    assert survivor_room.isconnected()
                await wait_until(lambda job=job: job.episode.session.current_speech is None)
                track = await wait_for_audio_track(survivor_room, identity="recap-agent")
                stream = rtc.AudioStream(track)
                source, _, _ = await create_microphone_track(
                    survivor_room, sample_rate=16000, channels=1, name="continue"
                )
                try:
                    model = job.episode.model
                    model.narrated = False
                    job.episode.stt.epoch += 1
                    await play_audio_frames(source, PLAYER_TWO_SPEECH.frames()[:150])
                    await wait_until(lambda job=job: job.episode.model.narrated)
                    async with asyncio.timeout(15):
                        assert (await anext(stream)).frame.duration > 0
                finally:
                    await stream.aclose()
                    await aclose_audio(source)
            finally:
                await aclose_room(room)
                redis = await db.get_redis()
                for pid in (host, guest):
                    await redis.delete(f"player_room:{pid}")
                for name in (job.room_name, f"replacement-{host}"):
                    await redis.delete(f"room_owner:{name}", f"room_dispatched:{name}")


async def test_sender_authorization_survives_handoff(livekit_server, reset_db_pool):
    from acceptance._livekit_client import aclose_room

    from exploration_agent import ExplorationAgent

    async with RecapHarness(livekit_server) as harness:
        pid = await harness.player()
        job = await harness.start(pid)
        sd = await job.wait()
        session = job.episode.session
        previous = session.current_agent
        session.update_agent(ExplorationAgent())
        await wait_until(lambda: session.current_agent is not previous and session.current_speech is None)
        outsider = await join(job, "unknown-member")
        received = asyncio.Queue()
        assert sd.room is not None
        unregister = register_data_packet_collector(sd.room, topic="player_hints", queue=received)
        try:
            assert sd.multiplayer_owner is not None
            lifecycle = sd.multiplayer_owner.lifecycle
            await wait_until(lambda: "unknown-member" in lifecycle._last_generation)
            async with asyncio.timeout(15):
                await outsider.local_participant.publish_data(
                    json.dumps({"type": "leave_requested", "player_id": pid}).encode(),
                    reliable=True,
                    topic="player_hints",
                )
                await received.get()
            await asyncio.sleep(0)
            assert sd.session_end_task is None and sd.departure_task is None
            assert await db_queries.get_last_session_summary(pid) is None
            lifecycle.mark_departed(pid)
            await send(job.player)
            async with asyncio.timeout(15):
                await received.get()
            await asyncio.sleep(0)
            assert sd.session_end_task is None and sd.departure_task is None
            assert await db_queries.get_last_session_summary(pid) is None
            await aclose_room(job.player)
            job.player = await join(job, pid)
            await wait_until(lambda: lifecycle.current_generation(pid) is not None)
            assert await lifecycle.authorize(pid) is not None
            queue = asyncio.Queue()
            register_data_packet_collector(job.player, topic="game_events", queue=queue)
            await send(job.player)
            assert (await end_packet(queue))["summary"] == "Fresh bells rang."
            await join_end(sd)
        finally:
            unregister()
            await aclose_room(outsider)


async def test_failed_recap_still_closes(livekit_server, reset_db_pool):
    import pytest

    async with RecapHarness(livekit_server) as harness:
        pid = await harness.player()
        job = await harness.start(pid)
        sd = await job.wait()
        closed = asyncio.Event()
        job.episode.session.on("close", lambda _: closed.set())
        with patch("session_end.generate_session_summary", side_effect=RuntimeError("summary unavailable")):
            await send(job.player)
            async with asyncio.timeout(15):
                await closed.wait()
            assert sd.session_end_task is not None
            with pytest.raises(RuntimeError, match="summary unavailable"):
                await sd.session_end_task
            assert await db_queries.get_last_session_summary(pid) is None
            redis = await db.get_redis()
            raw = await redis.get(f"session_outcome:{pid}")
            assert raw is not None and json.loads(raw)["state"] == "failed"


async def test_leave_before_gameplay_ends_the_room(livekit_server, reset_db_pool, monkeypatch):
    for key, value in (("URL", "ws_url"), ("API_KEY", "api_key"), ("API_SECRET", "api_secret")):
        monkeypatch.setenv(f"LIVEKIT_{key}", livekit_server[value])
    async with RecapHarness(livekit_server) as harness:
        pid = await harness.player(beat=1)
        job = await harness.start(pid)
        sd = await job.wait()
        assert sd.background is None
        closed, disconnected = asyncio.Event(), asyncio.Event()
        job.episode.session.on("close", lambda _: closed.set())
        job.player.on("disconnected", lambda *_: disconnected.set())
        await send(job.player)
        async with asyncio.timeout(5):
            await asyncio.gather(closed.wait(), disconnected.wait())
        await join_end(sd)
        raw = await (await db.get_redis()).get(f"session_outcome:{pid}")
        assert raw is not None and json.loads(raw)["state"] == "failed"
