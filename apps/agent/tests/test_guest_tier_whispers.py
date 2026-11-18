import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import asyncpg
import pytest
from livekit.agents.voice import SpeechHandle
from speech_handles import completed_handle

import event_types as E
from background_process import BackgroundProcess
from bg_speech import PendingSpeech, SpeechPriority
from event_bus import GameEvent
from session_data import SessionData


def crossing(player="guest", *, negative=False, reason="deed judgment"):
    payload = dict(
        patron_id="aelora" if player == "guest" else "kaelen",
        previous_level=40 if negative else 35,
        new_level=35 if negative else 40,
        amount=-5 if negative else 5,
        max=100,
        last_whisper_level=0,
        reason=reason,
    )
    if player is not None:
        payload["player_id"] = player
    return GameEvent(E.DIVINE_FAVOR_CHANGED, payload)


@asynccontextmanager
async def table():
    sd = SessionData(player_id="host", location_id="hall", patron_id="kaelen")
    for pid in ("guest", "third"):
        sd.party.members.append(SessionData(player_id=pid, location_id="hall", patron_id="aelora").party.primary)
    live = set(sd.party.member_ids)
    owner = MagicMock()
    owner.lifecycle.is_live.side_effect = lambda pid: pid in live
    sd.multiplayer_owner = owner
    session = MagicMock()

    def reply(**kwargs):
        sound.assert_awaited()
        return completed_handle()

    session.generate_reply.side_effect = reply
    bg = BackgroundProcess(session, sd)
    bg._rebuild_warm_layer = AsyncMock(return_value=True)
    bg._alignment.maybe_tick = AsyncMock()
    bg._check_companion_idle = MagicMock()
    bg._check_scene_beat_hints = MagicMock()
    done = asyncio.Event()
    deliver = bg._deliver_speech

    async def pass_delivery():
        await deliver()
        done.set()

    bg._deliver_speech = pass_delivery
    with (
        patch("db_queries.get_player", new=AsyncMock(side_effect=lambda pid: {"name": f"Name {pid}"})) as names,
        patch("db_activity_queries.get_divine_favor", new=AsyncMock(return_value={"level": 40})) as favor,
        patch("db_mutations_divine.mark_favor_whisper_level", new_callable=AsyncMock) as mark,
        patch("game_events.publish_game_event", new_callable=AsyncMock) as sound,
        patch("background_process.asyncio.sleep", new_callable=AsyncMock) as delay,
    ):
        t = SimpleNamespace(
            sd=sd,
            bg=bg,
            live=live,
            session=session,
            done=done,
            mark=mark,
            names=names,
            favor=favor,
            sound=sound,
            delay=delay,
        )
        try:
            yield t
        finally:
            await bg.stop()


async def tick(t, *events):
    t.done.clear()
    for ev in events:
        t.sd.event_bus.publish(ev)
    if t.bg._task is None:
        t.bg.start()
    await asyncio.wait_for(t.done.wait(), 1)
    task = t.bg._task
    assert task is not None
    if task.done():
        task.result()


@pytest.mark.parametrize("player", ["guest", None])
async def test_due_crossing_names_and_marks_its_recipient(player):
    async with table() as t:
        await tick(t, crossing(player))
        recipient = player or "host"
        t.session.generate_reply.assert_called_once()
        instructions = t.session.generate_reply.call_args.kwargs["instructions"]
        assert f"GOD_{'AELORA' if player else 'KAELEN'}" in instructions
        assert f"Name {recipient}" in instructions
        assert "aloud" in instructions
        t.names.assert_awaited_once_with(recipient)
        t.favor.assert_awaited_once_with(recipient)
        t.mark.assert_awaited_once_with(recipient, 40)
        t.sound.assert_awaited_once()


@pytest.mark.parametrize("reason", ["deed judgment", "Patron action 'fled_battle'"])
async def test_displeasure_pending_and_heard_latches_are_per_recipient(reason):
    async with table() as t:
        guest = crossing(negative=True, reason=reason)
        await tick(t, guest, guest, crossing("host", negative=True, reason=reason))
        assert t.session.generate_reply.call_count == 2
        assert t.sd.displeasure_heard_by == {"host", "guest"}
        t.mark.assert_not_awaited()
        guest.payload.update(previous_level=20, new_level=15)
        await tick(t, guest)
        assert t.session.generate_reply.call_count == 2


async def test_two_recipients_serialize_and_same_recipient_keeps_newest_winner():
    async with table() as t:
        handle = SpeechHandle.create()
        started = asyncio.Event()

        def reply(**kwargs):
            started.set()
            return handle if t.session.generate_reply.call_count == 1 else completed_handle()

        t.session.generate_reply.side_effect = reply
        t.bg._speech_queue.append(PendingSpeech(SpeechPriority.IMPORTANT, "ordinary cue"))
        for ev in (crossing("host"), crossing(), GameEvent(E.WORLD_EVENT, {"event_id": "god_whisper:other"})):
            t.sd.event_bus.publish(ev)
        t.bg.start()
        await asyncio.wait_for(started.wait(), 1)
        assert t.session.generate_reply.call_count == 1
        t.mark.assert_not_awaited()
        handle._mark_done()
        await asyncio.wait_for(t.done.wait(), 1)
        assert t.session.generate_reply.call_count == 2
        assert {c.args for c in t.mark.await_args_list} == {("host", 40), ("guest", 40)}
        instructions = " ".join(c.kwargs["instructions"] for c in t.session.generate_reply.call_args_list)
        assert instructions.count("Name guest") == instructions.count("Name host") == 1
        assert "ordinary cue" not in instructions


@pytest.mark.parametrize("negative", [False, True])
@pytest.mark.parametrize("departure", ["before", "stinger", "membership", "enqueue"])
async def test_departure_skips_only_absent_whisper_with_present_control(negative, departure):
    async with table() as t:
        event = crossing(negative=negative)
        if departure == "enqueue":
            t.live.remove("guest")
        else:
            t.bg._handle_events([event])
            if departure == "stinger":

                async def leave(_seconds):
                    t.live.discard("guest")

                t.delay.side_effect = leave
            elif departure == "membership":
                t.sd.party.members[:] = [m for m in t.sd.party.members if m.player_id != "guest"]
            else:
                t.live.remove("guest")
        await tick(t, event if departure == "enqueue" else GameEvent(E.PLAY_SOUND, {}))
        t.session.generate_reply.assert_not_called()
        t.mark.assert_not_awaited()
        assert not t.sd.displeasure_heard_by
        if departure != "stinger":
            t.sound.assert_not_awaited()
        t.delay.side_effect = None
        t.live.add("guest")
        if departure == "membership":
            t.sd.party.members.append(SessionData(player_id="guest", location_id="hall").party.primary)
        await tick(t, event, crossing("host"))
        assert t.session.generate_reply.call_count == 2
        assert "Name guest" in " ".join(c.kwargs["instructions"] for c in t.session.generate_reply.call_args_list)
        assert ("guest" in t.sd.displeasure_heard_by) == negative
        assert ("guest", 40) in [c.args for c in t.mark.await_args_list] or negative


async def test_handoff_keeps_present_third_players_whisper():
    async with table() as t:
        t.bg._handle_events([crossing("host"), crossing(), crossing("third")])
        t.bg._speech_queue.append(PendingSpeech(SpeechPriority.IMPORTANT, "ordinary cue"))
        t.sd.handoff_primary("host")
        await t.bg.primary_changed()
        assert {s.recipient_id for s in t.bg._speech_queue} == {None, "guest", "third"}
        await tick(t, GameEvent(E.PLAY_SOUND, {}))
        assert {c.args for c in t.mark.await_args_list} == {("guest", 40), ("third", 40)}
        t.bg._rebuild_warm_layer.assert_awaited()


async def test_failed_guest_speech_does_not_spend_latch_and_can_retry():
    async with table() as t:
        t.session.generate_reply.side_effect = lambda **kw: completed_handle(OSError("failed"))
        event = crossing(negative=True)
        await tick(t, event)
        assert not t.sd.displeasure_heard_by
        t.mark.assert_not_awaited()
        t.session.generate_reply.assert_called_once()
        t.session.generate_reply.side_effect = lambda **kw: completed_handle()
        await tick(t, event)
        assert t.sd.displeasure_heard_by == {"guest"}


async def test_transient_name_read_keeps_whisper_for_next_pass(caplog):
    async with table() as t:
        t.names.side_effect = asyncpg.PostgresError("name unavailable")
        await tick(t, crossing(), crossing("host"))
        t.session.generate_reply.assert_not_called()
        assert len(t.bg._speech_queue) == 2
        assert "name" in caplog.text.lower()
        t.names.side_effect = lambda pid: {"name": f"Name {pid}"}
        await tick(t, GameEvent(E.PLAY_SOUND, {}))
        assert t.session.generate_reply.call_count == 2


async def test_handoff_during_name_read_does_not_restore_departed_speech():
    async with table() as t:

        async def name(pid):
            if pid == "host":
                t.sd.handoff_primary("host")
                await t.bg.primary_changed()
            return {"name": f"Name {pid}"}

        t.names.side_effect = name
        await tick(t, crossing(), crossing("host"))
        t.mark.assert_awaited_once_with("guest", 40)
        t.session.generate_reply.assert_called_once()
        assert not t.bg._speech_queue


async def test_combat_safe_speech_keeps_equal_priority_held_speech():
    async with table() as t:
        held = PendingSpeech(SpeechPriority.CRITICAL, "held whisper")
        safe = PendingSpeech(SpeechPriority.CRITICAL, "combat warning", combat_safe=True)
        t.session.generate_reply.side_effect = lambda **kw: completed_handle()
        t.sd.combat_state = MagicMock()
        t.bg._speech_queue.extend([held, safe])
        await tick(t, GameEvent(E.PLAY_SOUND, {}))
        t.session.generate_reply.assert_called_once_with(instructions="combat warning")
        assert len(t.bg._speech_queue) == 1 and t.bg._speech_queue[0] is held
