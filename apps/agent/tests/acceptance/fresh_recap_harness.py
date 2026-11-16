"""Real LiveKit job lifecycle with owned deterministic speech providers."""

import asyncio
import json
import socket
import uuid
from contextlib import AsyncExitStack
from datetime import UTC, datetime
from unittest.mock import patch

from acceptance._livekit_client import aclose_room, connect_room, mint_access_token
from acceptance.first_episode_harness import Episode
from acceptance.multiplayer_voice.test_guest_leaves import ToneTTS
from livekit import api
from livekit.agents.ipc.channel import arecv_message, asend_message, send_message
from livekit.agents.ipc.job_proc_lazy_main import _JobProc
from livekit.agents.ipc.proc_client import _ProcClient
from livekit.agents.ipc.proto import IPC_MESSAGES, InitializeRequest, ShutdownRequest, StartJobRequest
from livekit.agents.job import JobAcceptArguments, JobExecutorType, RunningJobInfo
from livekit.agents.utils import aio
from livekit.protocol import agent as job_proto
from livekit.protocol import models

import agent
import db
import db_mutations
from creation_rules import build_character_data


class Job:
    def __init__(self, server, player_id):
        self.server, self.player_id = server, player_id
        self.room_name = f"recap-{uuid.uuid4().hex}"
        self.episode = Episode()
        self.episode.player_id = player_id
        self.ready = asyncio.Event()
        self.error = None
        self.greetings = []
        self.started_agent = ""

    async def start(self):
        server = self.server

        def token(identity):
            return mint_access_token(
                api_key=server["api_key"],
                api_secret=server["api_secret"],
                room_name=self.room_name,
                identity=identity,
            )

        self.player = await connect_room(server["ws_url"], token(self.player_id))

        async def entry(ctx):
            try:
                await agent.dm_session(ctx)
            except BaseException as exc:
                self.error = exc
                raise
            finally:
                self.ready.set()

        self.proc = _JobProc(
            lambda _: None,
            entry,
            agent._join_session_end,
            session_end_timeout=30,
            executor_type=JobExecutorType.THREAD,
        )
        parent, child = socket.socketpair()
        self.client = _ProcClient(child, None, self.proc.initialize, self.proc.entrypoint)
        sync = aio.duplex_unix._Duplex.open(parent)
        send_message(sync, InitializeRequest())
        self.client.initialize()
        sync.detach()
        self.transport = await aio.duplex_unix._AsyncDuplex.open(parent)
        await arecv_message(self.transport, IPC_MESSAGES)
        self.task = asyncio.create_task(self.client._monitor_task())

        async def drain():
            try:
                while True:
                    await arecv_message(self.transport, IPC_MESSAGES)
            except aio.duplex_unix.DuplexClosed:
                pass

        self.reader = asyncio.create_task(drain())
        request = StartJobRequest()
        request.running_job = RunningJobInfo(
            accept_arguments=JobAcceptArguments(name="recap", identity="recap-agent", metadata=""),
            job=job_proto.Job(
                id=uuid.uuid4().hex,
                room=models.Room(name=self.room_name),
                metadata=json.dumps({"player_id": self.player_id}),
            ),
            url=server["ws_url"],
            token=token("recap-agent"),
            worker_id="recap-test",
            fake_job=False,
        )
        await asend_message(self.transport, request)
        return self

    async def wait(self):
        async with asyncio.timeout(25):
            await self.ready.wait()
        if self.error:
            raise self.error
        return self.episode.session.userdata

    async def delete_room(self):
        async with api.LiveKitAPI(self.server["http_url"], self.server["api_key"], self.server["api_secret"]) as client:
            await client.room.delete_room(api.DeleteRoomRequest(room=self.room_name))

    async def close(self):
        if not self.task.done():
            await asend_message(self.transport, ShutdownRequest(reason="test cleanup"))
        async with asyncio.timeout(40):
            await self.task
        await self.transport.aclose()
        await self.reader
        await aclose_room(self.player)


class RecapHarness:
    def __init__(self, server):
        self.server = server
        self.jobs = []
        self.players = []
        self.stack = AsyncExitStack()

    async def __aenter__(self):
        await db.get_pool()

        def make(model, userdata):
            job = next(j for j in self.jobs if j.room_name == userdata.room.name)
            session = job.episode.make_session(model, userdata)
            start = session.start

            async def starting(**kwargs):
                job.started_agent = kwargs["agent"].__class__.__name__
                await start(**kwargs)

            session.start = starting
            return session

        delivery = agent.deliver_speech

        async def speak(session, **kwargs):
            job = next(j for j in self.jobs if j.episode.session is session)
            if "greeting" in kwargs.get("description", ""):
                job.greetings.append(kwargs["instructions"])
            return await delivery(session, **kwargs)

        for context in (
            patch("agent._make_agent_session", side_effect=make),
            patch("agent.deliver_speech", side_effect=speak),
            patch("base_agent._make_tts", side_effect=lambda **_: ToneTTS()),
            patch("session_startup.deepgram.STT", side_effect=lambda **_: self.jobs[-1].episode.stt),
            patch(
                "session_summary._call_llm_summary",
                return_value={
                    "summary": "Fresh bells rang.",
                    "key_events": ["Found a sword"],
                    "decisions": ["Spared the chief"],
                    "next_hooks": ["Deeper ruins await"],
                },
            ),
        ):
            self.stack.enter_context(context)
        return self

    async def player(self, *, location="accord_guild_hall", create=True, beat: str | int = "complete"):
        pid = f"recap-{uuid.uuid4().hex}"
        self.players.append(pid)
        if create:
            data = build_character_data("Vale", "human", "warrior", None, "", created_at=datetime.now(UTC))
            data.update(location_id=location, flags={"onboarding_beat": beat, "first_episode": "complete"})
            await db_mutations.create_player(pid, None, data)
        return pid

    async def start(self, pid):
        job = Job(self.server, pid)
        self.jobs.append(job)
        return await job.start()

    async def __aexit__(self, *exc):
        try:
            results = await asyncio.gather(*(job.close() for job in reversed(self.jobs)), return_exceptions=True)
            redis = await db.get_redis()
            pool = await db.get_pool()
            for pid in self.players:
                await redis.delete(f"session_outcome:{pid}")
                await pool.execute("DELETE FROM players WHERE player_id=$1", pid)
            failures = [result for result in results if isinstance(result, BaseException)]
            if failures:
                raise BaseExceptionGroup("Recap job cleanup failed", failures)
        finally:
            await self.stack.aclose()
