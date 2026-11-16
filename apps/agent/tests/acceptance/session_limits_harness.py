"""Manual deadline clock for real session jobs."""

import asyncio
import wave
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from acceptance.first_episode_harness import until
from acceptance.fresh_recap_harness import Job, RecapHarness


class ManualClock:
    def __init__(self):
        self.value = 0.0
        self.waiting = None

    def now(self):
        return self.value

    async def wait(self, deadline, wake):
        self.wake = wake
        self.waiting = deadline
        try:
            await wake.wait()
        finally:
            self.waiting = None

    async def advance_to(self, value):
        self.value = value
        if self.wake is not None:
            self.wake.set()
        await asyncio.sleep(0)

    wake = None


class LimitsHarness(RecapHarness):
    async def __aenter__(self):
        await super().__aenter__()
        self.clock = ManualClock()
        self.stack.enter_context(patch("session_startup.LimitClock", return_value=self.clock))
        directory = self.stack.enter_context(TemporaryDirectory())
        clip = Path(directory) / "prologue.wav"
        with wave.open(str(clip), "wb") as audio:
            audio.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
            audio.writeframes(b"\0\0" * 2400)
        self.stack.enter_context(patch("prologue.PROLOGUE_PATH", str(clip)))
        self.requests = []
        self.handles = []
        original = __import__("livekit.agents", fromlist=["AgentSession"]).AgentSession.generate_reply

        def request(session, **kwargs):
            self.requests.append(kwargs)
            handle = original(session, **kwargs)
            self.handles.append((kwargs, handle))
            return handle

        self.stack.enter_context(patch("livekit.agents.AgentSession.generate_reply", request))
        return self

    async def start(self, pid):
        job = Job(self.server, pid, self.microphone)
        make = job.episode.make_session
        # Owned tone output has no acoustic echo to warm up.
        job.episode.make_session = lambda _model, userdata, **session_options: make(
            _model, userdata, **{"aec_warmup_duration": None, **session_options}
        )
        self.jobs.append(job)
        return await job.start()

    def instructions(self, text):
        return [r for r in self.requests if text in r.get("instructions", "")]

    async def advance(self, value):
        await self.clock.advance_to(value)
        await until(
            lambda: (
                self.clock.waiting is not None or self.jobs[-1].episode.session.userdata.session_end_task is not None
            )
        )

    async def microphone(self, job, room=None):
        from acceptance._livekit_client import aclose_audio, create_microphone_track

        if room is None and hasattr(job.episode, "source"):
            return job.episode.source
        source, _, _ = await create_microphone_track(room or job.player, sample_rate=16000, channels=1, name="limits")
        self.stack.push_async_callback(aclose_audio, source)
        if room is None:
            job.episode.source = source
        return source

    async def speech(self, job, source=None):
        from acceptance._livekit_client import play_audio_frames
        from acceptance.multiplayer_voice._harness import PLAYER_TWO_SPEECH

        job.episode.stt.epoch += 1
        await play_audio_frames(source or job.episode.source, PLAYER_TWO_SPEECH.frames()[:150])
        await until(lambda: job.episode.session.userdata.limits.last_player == self.clock.now())

    async def ended(self, job):
        from acceptance.test_leave_summary import wait_until

        sd = job.episode.session.userdata
        await wait_until(lambda: sd.session_end_task is not None)
        async with asyncio.timeout(20):
            await asyncio.shield(sd.session_end_task)
        assert sd.limits.closed
        await sd.limits.aclose()
        assert sd.limits.task.done()
        closing = [h for r, h in self.handles if "closing line" in r.get("instructions", "")]
        assert len(closing) == 1 and closing[0].done() and not closing[0].interrupted
