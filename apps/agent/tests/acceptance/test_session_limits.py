"""Limits run at the job boundary on a manual clock, without paid providers."""

import asyncio
import json

import pytest
from acceptance._livekit_client import register_data_packet_collector
from acceptance.first_episode_harness import until
from acceptance.session_limits_harness import LimitsHarness
from acceptance.test_leave_summary import end_packet

import db
import db_queries
from creation_agent import CreationAgent
from multiplayer_transcription import _TranscriberAgent


@pytest.fixture
def mock_combat_agent_factory():
    yield


@pytest.fixture
def stub_creation_companion_grant():
    yield


@pytest.fixture
def stub_companion_hydrate_io():
    yield


@pytest.mark.parametrize("mode", ["creation", "onboarding", "gameplay"])
async def test_no_speech_expires_from_start(livekit_server, reset_db_pool, mode):
    async with LimitsHarness(livekit_server) as harness:
        pid = await harness.player(beat=1 if mode == "onboarding" else "complete")
        if mode == "creation":
            await (await db.get_pool()).execute("UPDATE players SET data='{}'::jsonb WHERE player_id=$1", pid)
        job = await harness.start(pid)
        sd = await job.wait()
        limits = sd.limits
        assert limits is not None
        queue = asyncio.Queue()
        register_data_packet_collector(job.player, topic="game_events", queue=queue)
        closed = asyncio.Event()
        job.episode.session.on("close", lambda _: closed.set())
        await harness.advance(299)
        assert not harness.instructions("Still with me?")
        await harness.advance(300)
        await until(lambda: harness.instructions("Still with me?"))
        assert len(harness.instructions("Still with me?")) == 1
        await harness.advance(599)
        assert not closed.is_set()
        await harness.advance(600)
        packet = await end_packet(queue)
        async with asyncio.timeout(15):
            await closed.wait()
            assert sd.session_end_task is not None
            await sd.session_end_task
        assert len(harness.instructions("closing line")) == 1
        row = await db_queries.get_last_session_summary(pid)
        assert row and row["summary"] == packet["summary"]
        raw = await (await db.get_redis()).get(f"session_outcome:{pid}")
        assert raw is not None
        assert json.loads(raw)["state"] == "saved"
        await limits.aclose()
        count = len(harness.requests)
        await harness.clock.advance_to(36000)
        assert len(harness.requests) == count and not limits.pending_notifications


@pytest.mark.parametrize("mode", ["onboarding", "gameplay"])
async def test_player_resets_silence_agent_does_not(livekit_server, reset_db_pool, mode):
    async with LimitsHarness(livekit_server) as harness:
        pid = await harness.player(beat=1 if mode == "onboarding" else "complete")
        job = await harness.start(pid)
        sd = await job.wait()
        limits = sd.limits
        assert limits is not None
        await harness.microphone(job)
        await harness.advance(300)
        await until(lambda: len(harness.instructions("Still with me?")) == 1)
        await harness.advance(540)
        await harness.speech(job)
        assert not limits.suppressed
        await harness.advance(600)
        assert sd.session_end_task is None
        await harness.advance(840)
        await until(lambda: len(harness.instructions("Still with me?")) == 2)
        await harness.advance(1139)
        assert sd.session_end_task is None
        # Real agent output is deliberately the last activity before the idle deadline.
        await job.episode.session.generate_reply(
            instructions="A companion comments on the weather.", tool_choice="none"
        )
        await harness.advance(1140)
        await harness.ended(job)
        assert limits.last_player == 540
        assert len(harness.instructions("closing line")) == 1


async def test_guest_speech_ingress_precedes_blocked_dm_turn(livekit_server, reset_db_pool):
    from unittest.mock import patch

    from acceptance._livekit_client import aclose_room
    from acceptance.first_episode_harness import until
    from acceptance.test_leave_summary import join

    async with LimitsHarness(livekit_server) as harness:
        host, guest = await harness.player(), await harness.player()
        job = await harness.start(host)
        sd = await job.wait()
        limits = sd.limits
        assert limits is not None
        multiplayer = sd.multiplayer_owner
        assert multiplayer is not None
        room = await join(job, guest)
        harness.stack.push_async_callback(aclose_room, room)
        await until(lambda: multiplayer.lifecycle.current_generation(guest) is not None)
        source = await harness.microphone(job, room)
        entered, release = asyncio.Event(), asyncio.Event()
        original = __import__("multiplayer_input").deliver_player_turn

        async def held(*args, **kwargs):
            entered.set()
            await release.wait()
            return await original(*args, **kwargs)

        try:
            with patch("multiplayer_input.deliver_player_turn", side_effect=held):
                await harness.advance(1)
                await harness.speech(job, source)
                await asyncio.wait_for(entered.wait(), 10)
                await harness.advance(540)
                await harness.speech(job, source)
                assert not release.is_set() and limits.last_player == 540
                await harness.advance(601)
                assert sd.session_end_task is None
        finally:
            release.set()
        await harness.advance(1100)
        transcriber_agent = multiplayer.transcriber._active[guest].current_agent
        assert isinstance(transcriber_agent, _TranscriberAgent)
        activity = transcriber_agent._player_activity
        assert activity is not None
        rejected = asyncio.Event()

        def observed(identity, generation):
            activity(identity, generation)
            rejected.set()

        transcriber_agent._player_activity = observed
        multiplayer.lifecycle.mark_departed(guest)
        from acceptance._livekit_client import play_audio_frames
        from acceptance.multiplayer_voice._harness import PLAYER_TWO_SPEECH

        job.episode.stt.epoch += 1
        await play_audio_frames(source, PLAYER_TWO_SPEECH.frames()[:150])
        await asyncio.wait_for(rejected.wait(), 10)
        assert limits.last_player == 540
        outsider = await join(job, "unknown-limits-player")
        harness.stack.push_async_callback(aclose_room, outsider)
        unknown_source = await harness.microphone(job, outsider)
        await play_audio_frames(unknown_source, PLAYER_TWO_SPEECH.frames()[:150])
        assert limits.last_player == 540
        await harness.advance(1140)
        await harness.ended(job)


@pytest.mark.parametrize("silent", [False, True])
async def test_cap_steers_once_through_paused_combat(livekit_server, reset_db_pool, silent):
    async with LimitsHarness(livekit_server) as harness:
        pid = await harness.player()
        job = await harness.start(pid)
        sd = await job.wait()
        limits = sd.limits
        assert limits is not None
        await harness.microphone(job)
        owner = limits
        # A deterministic tool turn, through the authenticated microphone, enters combat.
        receipt = await job.episode.turn("enter_mode", mode="combat", encounter_id="fragment_shadeling")
        assert not receipt.is_error, receipt.output
        assert sd.in_combat
        assert sd.background is not None
        sd.background.pause()
        if silent:
            await harness.advance(300)
            await until(lambda: harness.instructions("Still with me?"))
            await harness.advance(600)
            await harness.ended(job)
            return
        for seconds in (500, 1000, 1500, 2000, 2500, 3000, 3299):
            await harness.advance(seconds)
            await harness.speech(job)
        assert not harness.instructions("Steer toward")
        await harness.advance(3300)
        await until(lambda: len(harness.instructions("Steer toward")) == 1)
        await harness.advance(3599)
        await harness.speech(job)
        assert sd.session_end_task is None and limits is owner
        await harness.advance(3600)
        await harness.ended(job)
        assert len(harness.instructions("Steer toward")) == 1
        assert len(harness.instructions("closing line")) == 1


async def test_creation_handoffs_keep_original_cap(livekit_server, reset_db_pool):
    async with LimitsHarness(livekit_server) as harness:
        pid = await harness.player()
        await (await db.get_pool()).execute("UPDATE players SET data='{}'::jsonb WHERE player_id=$1", pid)
        job = await harness.start(pid)
        sd = await job.wait()
        limits = sd.limits
        assert limits is not None
        await until(
            lambda: (
                isinstance(active := job.episode.session.current_agent, CreationAgent)
                and active._ready
                and job.episode.model.narrated
            )
        )
        await harness.microphone(job)
        owner = limits
        for category, value in (("class", "warrior"), ("name", "Vale")):
            result = await job.episode.turn("set_creation_choice", category=category, value=value)
            assert not result.is_error, result.output
        await harness.advance(100)
        result = await job.episode.turn("finalize_character")
        assert not result.is_error, result.output
        await until(lambda: job.episode.session.current_agent.__class__.__name__ == "OnboardingAgent")
        assert sd.limits is owner
        await harness.advance(200)
        for _ in range(3):
            result = await job.episode.turn("advance_onboarding_beat")
            assert not result.is_error, result.output
        await until(lambda: job.episode.session.current_agent.__class__.__name__ == "ExplorationAgent")
        assert sd.limits is owner and owner.started == 0
        for seconds in (500, 1000, 1500, 2000, 2500, 3000, 3500):
            await harness.advance(seconds)
            await harness.speech(job)
        await harness.advance(3600)
        await harness.ended(job)
        assert len(harness.instructions("closing line")) == 1


@pytest.mark.parametrize("early", [False, True])
@pytest.mark.parametrize("limit_first", [False, True])
async def test_end_triggers_share_one_task(livekit_server, reset_db_pool, early, limit_first, monkeypatch):
    from unittest.mock import patch

    from acceptance.first_episode_harness import until
    from acceptance.test_leave_summary import send

    for key, value in (("URL", "ws_url"), ("API_KEY", "api_key"), ("API_SECRET", "api_secret")):
        monkeypatch.setenv(f"LIVEKIT_{key}", livekit_server[value])
    async with LimitsHarness(livekit_server) as harness:
        pid = await harness.player(beat=1 if early else "complete")
        job = await harness.start(pid)
        sd = await job.wait()
        limits = sd.limits
        assert limits is not None
        queue = asyncio.Queue()
        register_data_packet_collector(job.player, topic="game_events", queue=queue)
        deadline = 600
        if limit_first and not early:
            for seconds in (500, 1000, 1500, 2000, 2500, 3000):
                await harness.advance(seconds)
                await harness.speech(job)
            deadline = 3600
        entered, release = asyncio.Event(), asyncio.Event()
        original = __import__("session_end").generate_session_summary
        calls = []

        async def held(*args, **kwargs):
            calls.append(1)
            entered.set()
            await release.wait()
            return await original(*args, **kwargs)

        closing = None
        try:
            with patch("session_end.generate_session_summary", side_effect=held):
                if limit_first:
                    await harness.advance(deadline)
                    await asyncio.wait_for(entered.wait(), 15)
                    task = sd.session_end_task
                    await send(job.player)
                else:
                    await send(job.player)
                    await until(lambda: sd.session_end_task is not None)
                    task = sd.session_end_task
                    await harness.advance(deadline)
                assert task is not None
                closing = asyncio.create_task(job.episode.session.aclose())
                release.set()
                async with asyncio.timeout(20):
                    await asyncio.shield(task)
                    await closing
                assert sd.session_end_task is task
                assert len(calls) == (1 if limit_first or not early else 0)
                if calls:
                    assert (await end_packet(queue))["summary"] == "Fresh bells rang."
                while not queue.empty():
                    assert json.loads(queue.get_nowait()[0])["type"] != "session_end"
                row = await db_queries.get_last_session_summary(pid)
                assert bool(row) == bool(calls)
                raw = await (await db.get_redis()).get(f"session_outcome:{pid}")
                assert raw is not None
                assert json.loads(raw)["state"] == ("saved" if calls else "failed")
        finally:
            release.set()
            if closing is not None:
                await closing


async def test_idle_cues_are_revoked_and_fresh_silence_resets(livekit_server, reset_db_pool):
    import time

    from bg_speech import SpeechPriority
    from session_data import CompanionState

    async with LimitsHarness(livekit_server) as harness:
        pid = await harness.player()
        job = await harness.start(pid)
        sd = await job.wait()
        limits = sd.limits
        assert limits is not None
        await harness.microphone(job)
        bg = sd.background
        assert bg is not None
        bg.pause()
        sd.companion = CompanionState(id="companion_kael", name="Kael", last_speech_time=1)
        bg._quest_cache = [
            {"quest_id": "q", "current_stage": 0, "scene_graph": [{"scene_id": "limit-scene", "stage_refs": [0]}]}
        ]
        bg._scene_cache = {
            "limit-scene": {
                "id": "limit-scene",
                "beats": [
                    {"companion_hints": ["Follow the bells.", "Listen again."], "hint_delay_seconds": 1},
                    {"companion_hints": ["A fresh hint."], "hint_delay_seconds": 1},
                ],
            }
        }
        sd.last_player_speech_time = sd.last_agent_speech_end = 1
        bg._check_companion_idle()
        bg._check_scene_beat_hints()
        assert len(bg._speech_queue) == 2 and all(s.silence_generated for s in bg._speech_queue)
        await bg._deliver_speech()
        assert harness.instructions("offers this guidance")
        sd.companion.last_speech_time = sd.last_agent_speech_end = 1
        bg._scene_hint_state["last_hint_time"] = 1
        bg._check_companion_idle()
        bg._check_scene_beat_hints()
        assert len(bg._speech_queue) == 2
        bg._queue_speech(SpeechPriority.CRITICAL, "An event-driven companion cue remains deliverable.")
        await harness.advance(300)
        await until(lambda: limits.suppressed)
        assert not any(s.silence_generated for s in bg._speech_queue)
        await bg._deliver_speech()
        assert harness.instructions("event-driven companion cue")
        assert not harness.instructions("Listen again.")
        sd.companion.last_speech_time = 1
        old_state = dict(bg._scene_hint_state)
        old_time = sd.companion.last_speech_time
        bg._check_companion_idle()
        bg._check_scene_beat_hints()
        assert bg._scene_hint_state == old_state and sd.companion.last_speech_time == old_time
        await harness.advance(540)
        await harness.speech(job)
        sd.companion.last_speech_time = time.time() - 100
        bg._check_companion_idle()
        assert bg._speech_queue and not limits.suppressed
        await bg._deliver_speech()
        assert harness.instructions("makes an idle observation")
        sd.last_agent_speech_end = sd.last_player_speech_time = 1
        bg._scene_hint_state["last_hint_time"] = 1
        bg._check_scene_beat_hints()
        bg._check_scene_beat_hints()
        await bg._deliver_speech()
        assert harness.instructions("A fresh hint.") and not harness.instructions("Listen again.")
        await harness.advance(840)
        await until(lambda: len(harness.instructions("Still with me?")) == 2)
        await harness.advance(1140)
        await harness.ended(job)


async def test_selected_and_livekit_queued_idle_speech_are_cancelled(livekit_server, reset_db_pool):
    from unittest.mock import patch

    from acceptance.first_episode_harness import EpisodeStream, until

    from bg_speech import SpeechPriority
    from session_data import CompanionState

    async with LimitsHarness(livekit_server) as harness:
        pid = await harness.player()
        job = await harness.start(pid)
        sd = await job.wait()
        limits = sd.limits
        assert limits is not None
        session, bg = job.episode.session, sd.background
        assert bg is not None
        bg.pause()
        await until(lambda: session.current_speech is None)
        sd.companion = CompanionState(id="companion_kael", name="Kael", last_speech_time=1)
        entered, release = asyncio.Event(), asyncio.Event()
        publish = __import__("background_process").publish_companion_cue

        async def held_publish(*args):
            entered.set()
            await release.wait()
            return await publish(*args)

        selected = None
        try:
            with patch("background_process.publish_companion_cue", side_effect=held_publish):
                bg._check_companion_idle()
                selected = asyncio.create_task(bg._deliver_speech())
                await asyncio.wait_for(entered.wait(), 10)
                await harness.advance(300)
                release.set()
                await selected
                assert not harness.instructions("makes an idle observation")
        finally:
            release.set()
            if selected:
                await selected
        # A fresh interval permits a cue, but the next threshold revokes its accepted handle.
        await harness.microphone(job)
        await harness.advance(540)
        await harness.speech(job)
        await until(lambda: session.current_speech is None)
        entered.clear()
        release.clear()
        original = EpisodeStream._run

        async def held_model(stream):
            entered.set()
            await release.wait()
            return await original(stream)

        with patch.object(EpisodeStream, "_run", held_model):
            leading = session.generate_reply(instructions="An ongoing DM reply.", tool_choice="none")
            await asyncio.wait_for(entered.wait(), 10)
            bg._queue_speech(SpeechPriority.ROUTINE, "Queued idle cue.", silence_generated=True)
            queued = asyncio.create_task(bg._deliver_speech())
            try:
                await until(lambda: harness.instructions("Queued idle cue"))
                handle = next(h for r, h in harness.handles if r.get("instructions") == "Queued idle cue.")
                await harness.advance(550)
                await harness.speech(job)
                await harness.advance(850)
                await until(lambda: handle.interrupted)
                assert session.current_speech is leading
                await harness.advance(1150)
                await until(lambda: harness.instructions("closing line"))
            finally:
                release.set()
                await queued
        await harness.ended(job)


async def test_speech_during_prologue_resets_idle(livekit_server, reset_db_pool):
    from unittest.mock import patch

    from base_agent import _silence

    async with LimitsHarness(livekit_server) as harness:
        pid = await harness.player()
        await (await db.get_pool()).execute("UPDATE players SET data='{}'::jsonb WHERE player_id=$1", pid)
        release = asyncio.Event()

        async def audio(*args, **kwargs):
            yield _silence(0.1)
            await release.wait()
            yield _silence(0.1)

        with patch("prologue.audio_frames_from_file", audio):
            job = await harness.start(pid)
            sd = await job.wait()
            limits = sd.limits
            assert limits is not None
            session = job.episode.session
            try:
                await until(lambda: session.current_speech is not None)
                assert session.current_agent.__class__.__name__ == "PrologueAgent"
                await harness.advance(540)
                await harness.speech(job)
                assert limits.last_player == 540
                await harness.advance(600)
                assert sd.session_end_task is None
            finally:
                release.set()
            await until(lambda: session.current_agent.__class__.__name__ == "CreationAgent")
            await harness.advance(1140)
            await harness.ended(job)
